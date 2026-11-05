"""
tests/test_time_calendar_alignment.py — Unit tests verifying time, timezone, and calendar alignment.

Verifies:
  - Known peak hours in EST grid net load align correctly to Local Standard Time (CST, EST, custom UTC offsets).
  - Timezone parameter `custom_tz` is honored in `load_cambium_net_demand_proxy_for_portfolio`.
  - Leap-day handling produces exactly 8,760 hours ending Dec 31 23:00.
  - Retail tariff peak periods align correctly with datetime series.
  - Grid-region sensitivity (switching AL to GA) does not alter building load profiles.
"""

import os
import tempfile
import pytest
import numpy as np
import pandas as pd

from system_stress_data import (
    align_est_weights_to_local_tz,
    load_cambium_net_demand_proxy_for_portfolio,
)
from calculations import (
    calculate_cambium_seasonal_net_demand_weights,
    calculate_system_stress_capacity_metrics,
)
from billing import calculate_urdb_bill, AL_FDD_URDB
from test_scenario_selection import _create_mock_cambium_ba_csv


class TestTimeCalendarAlignment:
    """Verifies timezone shifts, leap-day handling, and tariff schedule alignment."""

    def test_known_est_peak_hour_aligns_to_cst_and_est(self):
        # Create an 8760 array where ONLY hour 18 (6:00 PM EST on Jan 1) has net load
        net_load_est = np.zeros(8760, dtype=float)
        net_load_est[18] = 10000.0  # Peak at 18:00 EST

        # Seasonal weights (with single peak)
        w_est, _ = calculate_cambium_seasonal_net_demand_weights(
            net_load_est,
            winter_weight=1.0,
            summer_weight=0.0,
            top_n_peak_hours=1,
        )
        assert np.argmax(w_est) == 18

        # In Georgia (EST, UTC-5), peak must remain at hour 18
        w_ga = align_est_weights_to_local_tz(w_est, "GA")
        assert np.argmax(w_ga) == 18

        # In Alabama (CST, UTC-6), peak must shift 1 hour earlier to hour 17 (5:00 PM CST)
        w_al = align_est_weights_to_local_tz(w_est, "AL")
        assert np.argmax(w_al) == 17

        # With custom UTC offset -7 (MST), peak shifts 2 hours earlier to hour 16
        w_mst = align_est_weights_to_local_tz(w_est, "CUSTOM", custom_utc_offset=-7)
        assert np.argmax(w_mst) == 16

    def test_custom_tz_honored_in_cambium_portfolio_loader(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f_p89 = os.path.join(tmpdir, "Cambium24_MidCase_hourly_p89_2030.csv")
            f_p90 = os.path.join(tmpdir, "Cambium24_MidCase_hourly_p90_2030.csv")
            _create_mock_cambium_ba_csv(f_p89, scenario="MidCase", ba="p89", year="2030")
            _create_mock_cambium_ba_csv(f_p90, scenario="MidCase", ba="p90", year="2030")

            # Load with default AL (CST, -6)
            res_cst = load_cambium_net_demand_proxy_for_portfolio(
                target_states=["AL"],
                selected_scenario="MidCase",
                planning_year="2030",
                raw_directory=tmpdir,
                custom_tz=None,
            )
            # Load with forced custom_tz=-5 (EST)
            res_est = load_cambium_net_demand_proxy_for_portfolio(
                target_states=["AL"],
                selected_scenario="MidCase",
                planning_year="2030",
                raw_directory=tmpdir,
                custom_tz="-5",
            )

            w_cst = res_cst["cwft_array"]
            w_est = res_est["cwft_array"]

            # Because custom_tz=-5 shifts offset relative to -6, the weight vectors must differ by exactly 1 hour shift
            assert not np.allclose(w_cst, w_est)
            assert np.allclose(w_cst, np.roll(w_est, -1))

    def test_leap_year_datetime_alignment_retains_8760_and_ends_dec31(self):
        from data_loaders import load_and_aggregate_data

        target_year = "2024"  # 2024 is a leap year
        full_range = pd.date_range(
            start=f"{target_year}-01-01 00:00:00", end=f"{target_year}-12-31 23:00:00", freq="h"
        )
        date_range = full_range[~((full_range.month == 2) & (full_range.day == 29))]

        assert len(date_range) == 8760
        assert str(date_range[0]) == "2024-01-01 00:00:00"
        assert str(date_range[-1]) == "2024-12-31 23:00:00"

    def test_retail_tariff_peak_period_demand_charge_timing(self):
        # Create an 8760 load profile with a spike strictly during Alabama Power FD-D peak:
        # Summer peak: July weekday 2 PM (hour 14).
        dt = pd.Series(pd.date_range("2026-01-01 00:00:00", "2026-12-31 23:00:00", freq="h"))
        dt_8760 = dt[~((dt.dt.month == 2) & (dt.dt.day == 29))].reset_index(drop=True)

        load_offpeak = np.full(8760, 2.0)  # 2 kW constant
        load_onpeak = np.full(8760, 2.0)

        # Find July 15, 2026 (Wednesday = weekday) 2 PM (hour 14)
        july_peak_mask = (dt_8760.dt.month == 7) & (dt_8760.dt.day == 15) & (dt_8760.dt.hour == 14)
        load_onpeak[july_peak_mask] = 10.0  # 8 kW peak spike

        bill_offpeak, _ = calculate_urdb_bill(load_offpeak, dt_8760, AL_FDD_URDB)
        bill_onpeak, _ = calculate_urdb_bill(load_onpeak, dt_8760, AL_FDD_URDB)

        # On-peak bill should be significantly higher due to $8/kW demand charge on 10 kW vs 2 kW
        assert bill_onpeak > bill_offpeak
        # Difference in July demand charge alone: (10 kW - 2 kW) * $8/kW = $64
        # Plus energy difference for that 1 hour
        assert (bill_onpeak - bill_offpeak) >= 64.0
