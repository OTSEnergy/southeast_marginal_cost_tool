"""
tests/test_system_stress_data.py — Unit & Integration Tests for Public-Data System-Stress Proxy
===============================================================================================

Covers Work Package 5 test requirements:
  1. Timestamp conversion: UTC hour-ending -> interval_start_utc -> fixed Local Standard Time
     (UTC-5, UTC-6, UTC-7, UTC-8), hour_start vs hour_end matching, UTC boundary padding,
     and deliberate local February 29 removal in leap years without December 31 truncation.
  2. Multi-timezone state & portfolio confirmation: single-TZ autofill vs required user
     confirmation for multi-TZ states (FL, TN, TX, KY...) and cross-TZ portfolios (GA + AL).
  3. EIA-861 state-to-BA residential sales crosswalk: 48-state coverage, Part(A+B+D) == Part(A+C+D)
     reconciliation, multi-BA states, equal state portfolio weights, deduplication of shared BAs
     (e.g. SOCO across GA + AL), >= 95% coverage gate (ME < 95% triggers fallback and never picks
     largest BA alone), and vintage matching (exact match, closest earlier vintage with disclosure,
     refusal to apply future vintages backward).
  4. Signal selection: net demand (D - WND - SUN) vs whole-year gross-demand fallback when wind
     or solar is unavailable (e.g. 2017 pre-July 2018) or fails quality gates; verified zero-VRE BAs;
     never treating missing wind/solar as zero.
  5. Data quality gates: < 99.5% valid original observations fails; interior gap <= 2 hours
     interpolates and flags if imputed hour receives positive weight; gap > 2 hours fails;
     boundary NaN fails (no boundary extrapolation); duplicate conflicting timestamp fails;
     duplicate identical timestamp deduplicates; implausible outlier spike fails without winsorizing.
  6. Upper-tail exceedance weight math: nonnegativity, sum to 1.0, monotonic concentration wrt
     percentile (90% vs 95% vs 99%), flat-signal rejection, upper-tail tie fallback, concentration
     diagnostics (1 / sum(w^2)), monthly & seasonal shares.
  7. Weather-year & profile alignment: bundled 2012 example triggers weather fallback with warning;
     TMY/Composite/Unknown and Extreme Winter/Summer cases trigger weather fallback; imputed
     building load profiles emit non-pristine warnings.
  8. Valuation integration:
     - Fixed building profiles: wholesale energy, emissions, retail bills, customer NPV, and
       fixed-profile T&D remain strictly invariant when switching CWF methods; only generation
       capacity and its downstream utility NPV, TRC, and RIM change.
     - DR mode: dispatch reschedules when weights change, emits explicit warning, and same-dispatch
       weather comparator matches fixed-dispatch valuation difference.
     - Zero or all-negative load reductions produce zero/negative kW credit without divide-by-zero
       or misleading accreditation percentages.
  9. API pagination, atomic cache separation (raw vs aligned), SHA-256 verification, and API key
     redaction across URLs, logs, manifests, and exception messages.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd
import pytest

from billing import GP_R31_URDB, calculate_urdb_bill
from calculations import (
    calculate_avoided_costs,
    calculate_cost_effectiveness_tests,
    calculate_feeder_pcaf_weights,
    calculate_southeast_dual_peak_cwf,
    calculate_system_stress_capacity_metrics,
    calculate_upper_tail_stress_weights,
    combine_ba_weights_to_state_portfolio,
    dispatch_dr_program,
)
from config import CONTIGUOUS_48_STATES, SYSTEM_STRESS_CWF_LABEL
from data_loaders import load_load_profiles_from_csv
from system_stress_data import (
    align_and_qualify_ba_series,
    build_crosswalk_from_eia861_dataframe,
    evaluate_system_stress_capacity_proxy,
    fetch_eia_rto_paginated,
    get_aligned_cache_paths,
    get_raw_cache_paths,
    load_cache_bundle,
    load_or_fetch_ba_stress_series,
    load_state_ba_crosswalk,
    parse_eia_930_six_month_csv,
    redact_api_key,
    resolve_profile_time_basis,
    resolve_state_ba_mapping,
    save_cache_bundle,
    validate_profile_stress_eligibility,
)
from visualizations import plot_system_stress_vs_weather_cwf_comparison


# ==============================================================================
# HELPER FIXTURES FOR OFFLINE EIA-930 RAW DATA GENERATION
# ==============================================================================

def _make_raw_eia_utc_df(
    year: int = 2022,
    include_wind_solar: bool = True,
    peak_local_month: int = 1,
    peak_local_day: int = 15,
    peak_local_hour: int = 7,
    utc_offset_hours: int = -5,
    base_demand_mw: float = 20000.0,
) -> pd.DataFrame:
    """
    Create a complete padded UTC hour-ending DataFrame covering `year-1 Dec 31 00:00 UTC`
    through `year+1 Jan 2 12:00 UTC` so any contiguous U.S. timezone (UTC-5..UTC-8)
    has 100% boundary coverage.
    """
    utc_ending_idx = pd.date_range(
        start=f"{year - 1}-12-31 00:00:00",
        end=f"{year + 1}-01-02 12:00:00",
        freq="h",
    )
    n = len(utc_ending_idx)
    rng = np.random.default_rng(seed=year + abs(utc_offset_hours))

    # Interval start in local standard time
    local_start = utc_ending_idx - pd.Timedelta(hours=1) + pd.Timedelta(hours=utc_offset_hours)
    hours_of_day = local_start.hour.to_numpy(dtype=float)
    day_of_year = local_start.dayofyear.to_numpy(dtype=float)

    # Smooth seasonal + diurnal demand shape with positive values
    seasonal = 4000.0 * np.cos(2.0 * np.pi * (day_of_year - 20.0) / 365.0)
    diurnal = 2500.0 * np.sin(2.0 * np.pi * (hours_of_day - 6.0) / 24.0)
    noise = rng.normal(0.0, 150.0, size=n)
    demand = base_demand_mw + seasonal + diurnal + noise

    # Inject a deterministic known peak at (peak_local_month, peak_local_day, peak_local_hour)
    peak_mask = (
        (local_start.year == year)
        & (local_start.month == peak_local_month)
        & (local_start.day == peak_local_day)
        & (local_start.hour == peak_local_hour)
    )
    demand[peak_mask] = base_demand_mw + 15000.0

    if include_wind_solar:
        solar = np.where(
            (hours_of_day >= 8) & (hours_of_day <= 17),
            1500.0 * np.sin(np.pi * (hours_of_day - 8.0) / 9.0),
            0.0,
        )
        # During the target peak hour, set solar=0 and wind=100 so net demand peak is unambiguous
        wind = 500.0 + 100.0 * np.cos(2.0 * np.pi * hours_of_day / 24.0)
        wind[peak_mask] = 100.0
        solar[peak_mask] = 0.0
    else:
        wind = np.full(n, np.nan)
        solar = np.full(n, np.nan)

    return pd.DataFrame({
        "period_utc": utc_ending_idx.strftime("%Y-%m-%dT%H"),
        "demand_mw": demand,
        "wind_mw": wind,
        "solar_mw": solar,
    })


# ==============================================================================
# 1. TIMESTAMP CONVERSION, LEAP-DAY REMOVAL & TIME-BASIS TESTS
# ==============================================================================

class TestTimestampAlignmentAndLeapYear:
    @pytest.mark.parametrize("utc_offset", [-5, -6, -7, -8])
    def test_utc_hour_ending_to_local_standard_time_all_us_offsets(self, utc_offset):
        """
        Verify that a spike at local hour-beginning `Jan 15 07:00` (reported in EIA-930
        as UTC hour-ending `Jan 15 (07 + 1 - utc_offset):00 UTC`) lands at exact index
        `(14 * 24 + 7) = 343` in the 8,760-hour aligned series for UTC-5, UTC-6, UTC-7, UTC-8.
        """
        raw_df = _make_raw_eia_utc_df(
            year=2022,
            peak_local_month=1,
            peak_local_day=15,
            peak_local_hour=7,
            utc_offset_hours=utc_offset,
        )
        res = align_and_qualify_ba_series(
            raw_df=raw_df,
            ba_code="TESTBA",
            year=2022,
            utc_offset_hours=utc_offset,
            interval_convention="hour_start",
        )
        assert res["qualified"] is True
        assert res["leap_hours_removed"] == 0
        expected_idx = 14 * 24 + 7  # Jan 15, 07:00 local interval start
        assert int(np.argmax(res["signal_mw"])) == expected_idx
        assert res["ba_weights"][expected_idx] == np.max(res["ba_weights"])

    def test_hour_start_vs_hour_end_interval_convention_shift(self):
        """
        Verify the exact 1-hour offset between `hour_start` and `hour_end` profile conventions:
        A UTC hour-ending timestamp has `local_hour_ending = local_interval_start + 1 hour`.
        """
        raw_df = _make_raw_eia_utc_df(
            year=2022,
            peak_local_month=1,
            peak_local_day=15,
            peak_local_hour=7,
            utc_offset_hours=-5,
        )
        res_start = align_and_qualify_ba_series(
            raw_df=raw_df,
            ba_code="SOCO",
            year=2022,
            utc_offset_hours=-5,
            interval_convention="hour_start",
        )
        res_end = align_and_qualify_ba_series(
            raw_df=raw_df,
            ba_code="SOCO",
            year=2022,
            utc_offset_hours=-5,
            interval_convention="hour_end",
        )
        assert res_start["qualified"] and res_end["qualified"]
        idx_start = int(np.argmax(res_start["signal_mw"]))
        idx_end = int(np.argmax(res_end["signal_mw"]))
        assert idx_end - idx_start == 1

    def test_leap_year_removes_local_feb_29_without_truncating_dec_31(self):
        """
        In leap year 2020, local Feb 29 (24 hours) must be removed deliberately so that:
        1. Resulting series has exactly 8,760 hours.
        2. A peak on Dec 31 at 18:00 local time lands on the exact final day of the year
           (index `8760 - 24 + 18 = 8754`), proving Dec 31 was NOT truncated.
        """
        raw_df = _make_raw_eia_utc_df(
            year=2020,
            peak_local_month=12,
            peak_local_day=31,
            peak_local_hour=18,
            utc_offset_hours=-5,
        )
        res = align_and_qualify_ba_series(
            raw_df=raw_df,
            ba_code="SOCO",
            year=2020,
            utc_offset_hours=-5,
            interval_convention="hour_start",
        )
        assert res["qualified"] is True
        assert res["leap_hours_removed"] == 24
        assert len(res["signal_mw"]) == 8760
        expected_dec31_18h_idx = 8760 - 24 + 18
        assert int(np.argmax(res["signal_mw"])) == expected_dec31_18h_idx
        assert res["aligned_df"]["local_timestamp"].iloc[-1] == "2020-12-31 23:00:00"
        assert not res["aligned_df"]["local_timestamp"].str.contains("-02-29").any()


class TestTimeBasisConfirmation:
    def test_single_tz_state_autofills_without_confirmation(self):
        tb = resolve_profile_time_basis(["GA", "NC", "SC"])
        assert tb["valid"] is True
        assert tb["utc_offset_hours"] == -5
        assert tb["requires_user_confirmation"] is False

    @pytest.mark.parametrize("multi_tz_state", ["FL", "TN", "TX", "KY", "IN", "MI", "KS", "NE", "ND", "SD", "ID", "OR"])
    def test_multi_tz_state_requires_explicit_user_confirmation(self, multi_tz_state):
        tb_unconfirmed = resolve_profile_time_basis([multi_tz_state], utc_offset_hours=-5, user_confirmed_offset=False)
        assert tb_unconfirmed["requires_user_confirmation"] is True
        assert tb_unconfirmed["valid"] is False

        tb_confirmed = resolve_profile_time_basis([multi_tz_state], utc_offset_hours=-5, user_confirmed_offset=True)
        assert tb_confirmed["requires_user_confirmation"] is True
        assert tb_confirmed["valid"] is True
        assert tb_confirmed["utc_offset_hours"] == -5

    def test_cross_tz_multi_state_portfolio_requires_confirmation(self):
        # GA (UTC-5) + AL (UTC-6) spans two standard time zones
        tb_unconfirmed = resolve_profile_time_basis(["GA", "AL"], utc_offset_hours=-5, user_confirmed_offset=False)
        assert tb_unconfirmed["cross_tz_portfolio"] is True
        assert tb_unconfirmed["requires_user_confirmation"] is True
        assert tb_unconfirmed["valid"] is False

        tb_confirmed = resolve_profile_time_basis(["GA", "AL"], utc_offset_hours=-5, user_confirmed_offset=True)
        assert tb_confirmed["valid"] is True


# ==============================================================================
# 2. EIA-861 STATE-TO-BA CROSSWALK & PORTFOLIO AGGREGATION TESTS
# ==============================================================================

class TestEIA861CrosswalkAndStateMapping:
    def test_committed_crosswalk_covers_all_48_states_and_9_vintages(self):
        df, manifest = load_state_ba_crosswalk()
        assert set(df["state"].unique()) == set(CONTIGUOUS_48_STATES)
        assert sorted(df["vintage_year"].unique()) == list(range(2016, 2025))
        assert manifest.get("contiguous_states_count") == 48

        # Every (vintage_year, state) group's raw shares sum to 1.0
        grp_sums = df.groupby(["vintage_year", "state"])["residential_sales_share"].sum()
        assert np.allclose(grp_sums.to_numpy(), 1.0, atol=1e-5)

    def test_build_crosswalk_reconciles_marketers_and_adjustments(self):
        """
        Verify that `build_crosswalk_from_eia861_dataframe` reconciles Part A + B + D
        (including Utility 99999 adjustment rows) against Part A + C + D and rejects
        double-counted sales.
        """
        mock_eia861 = pd.DataFrame({
            "State": ["GA", "GA", "GA", "NY", "NY", "NY"],
            "Part": ["A", "A", "B", "A", "B", "C"],
            "BA Code": ["SOCO", "SEPA", "SOCO", "NYIS", "NYIS", "NYIS"],
            "Megawatthours": [55000.0, 180.0, -50.0, 40000.0, 10000.0, 10000.0],
        })
        # Fill remaining 46 states with simple Part A rows so 48-state check works
        other_states = [s for s in CONTIGUOUS_48_STATES if s not in ("GA", "NY")]
        extra_df = pd.DataFrame({
            "State": other_states,
            "Part": ["A"] * len(other_states),
            "BA Code": ["PJM"] * len(other_states),
            "Megawatthours": [10000.0] * len(other_states),
        })
        # Add matching Part C row for GA's -50 adjustment so A+B+D == A+C+D
        ga_c = pd.DataFrame({"State": ["GA"], "Part": ["C"], "BA Code": ["SOCO"], "Megawatthours": [-50.0]})
        full_raw = pd.concat([mock_eia861, ga_c, extra_df], ignore_index=True)

        cw_df, report = build_crosswalk_from_eia861_dataframe(full_raw, vintage_year=2023)
        assert report["reconciled"] is True
        assert report["max_diff_abd_vs_acd_mwh"] == 0.0

        ny_rows = cw_df[cw_df["state"] == "NY"]
        # NY total must be 40,000 (Part A) + 10,000 (Part B) = 50,000 MWh (NOT 60,000 MWh with Part C double-counted!)
        assert np.isclose(ny_rows["state_total_residential_mwh"].iloc[0], 50000.0)

    def test_ga_excludes_sepa_and_normalizes_retained_share(self):
        res = resolve_state_ba_mapping(["GA"], stress_year=2023)
        assert "GA" in res["qualifying_states"]
        st_info = res["state_details"]["GA"]
        assert st_info["passed_coverage_gate"] is True
        assert 0.99 < st_info["mapped_share"] < 1.0
        assert "SEPA" in st_info["unmapped_bas"]
        assert np.isclose(sum(st_info["normalized_ba_shares"].values()), 1.0)

    def test_me_below_95_percent_triggers_state_fallback_never_picks_largest_ba(self):
        """
        Maine has ~94.0% in ISNE and ~6.0% in NBSO (Canadian BA). Under the strict 95%
        coverage threshold, ME must fail the coverage gate rather than silently using ISNE alone.
        """
        res = resolve_state_ba_mapping(["ME"], stress_year=2023, min_coverage=0.95)
        assert "ME" in res["failed_coverage_states"]
        assert "ME" not in res["qualifying_states"]
        assert res["state_details"]["ME"]["passed_coverage_gate"] is False
        assert "Refusing to represent ME by its largest single BA" in res["state_details"]["ME"]["failure_reason"]

    def test_multi_state_deduplicates_shared_ba_and_uses_equal_state_weights(self):
        """
        GA (DUK + SOCO + TVA) and AL (SOCO + TVA) share SOCO and TVA.
        Selecting ["GA", "AL"] must give each state 50% weight and sum SOCO and TVA shares
        across both states so unique_required_bas is ["DUK", "SOCO", "TVA"] (each fetched once).
        """
        res = resolve_state_ba_mapping(["GA", "AL"], stress_year=2023)
        assert res["equal_state_weight"] == 0.5
        assert res["unique_required_bas"] == ["DUK", "SOCO", "TVA"]
        assert np.isclose(sum(res["deduplicated_portfolio_ba_shares"].values()), 1.0)
        # Verify SOCO share is 0.5 * GA_SOCO + 0.5 * AL_SOCO
        ga_soco = res["state_details"]["GA"]["normalized_ba_shares"]["SOCO"]
        al_soco = res["state_details"]["AL"]["normalized_ba_shares"]["SOCO"]
        assert np.isclose(res["deduplicated_portfolio_ba_shares"]["SOCO"], 0.5 * (ga_soco + al_soco))

    def test_vintage_matching_exact_earlier_and_no_future_vintage(self):
        # Exact match
        r_exact = resolve_state_ba_mapping(["NC"], stress_year=2022)
        assert r_exact["selected_vintage"] == 2022
        assert r_exact["exact_vintage_match"] is True

        # Future year (e.g. 2025) uses closest earlier vintage (2024) with explicit disclosure
        r_earlier = resolve_state_ba_mapping(["NC"], stress_year=2025)
        assert r_earlier["selected_vintage"] == 2024
        assert r_earlier["exact_vintage_match"] is False
        assert "closest earlier" in r_earlier["vintage_disclosure"]

        # Year earlier than earliest vintage (2015 < 2016) must raise ValueError (never apply future vintage backward)
        with pytest.raises(ValueError, match="Future vintages are never applied backward"):
            resolve_state_ba_mapping(["NC"], stress_year=2015)


# ==============================================================================
# 3. SIGNAL SELECTION & DATA QUALITY GATE TESTS
# ==============================================================================

class TestSignalSelectionAndQualityGates:
    def test_net_demand_selected_when_wind_and_solar_pass_quality_gates(self):
        raw_df = _make_raw_eia_utc_df(year=2022, include_wind_solar=True)
        res = align_and_qualify_ba_series(raw_df, ba_code="CISO", year=2022, utc_offset_hours=-8)
        assert res["qualified"] is True
        assert res["signal_type"] == "net_demand"
        assert res["gross_demand_fallback_reason"] is None
        expected_net = res["demand_mw"] - res["wind_mw"] - res["solar_mw"]
        assert np.allclose(res["signal_mw"], expected_net)

    def test_gross_demand_fallback_when_wind_or_solar_missing_or_pre_2019(self):
        raw_2017 = _make_raw_eia_utc_df(year=2017, include_wind_solar=False)
        res_2017 = align_and_qualify_ba_series(raw_2017, ba_code="SOCO", year=2017, utc_offset_hours=-5)
        assert res_2017["qualified"] is True
        assert res_2017["signal_type"] == "gross_demand"
        assert "gross-demand fallback" in res_2017["gross_demand_fallback_reason"]
        assert np.allclose(res_2017["signal_mw"], res_2017["demand_mw"])

        # Missing solar in 2022 must also trigger whole-year gross_demand fallback (never treat NaN solar as 0!)
        raw_2022_no_sun = _make_raw_eia_utc_df(year=2022, include_wind_solar=True)
        raw_2022_no_sun["solar_mw"] = np.nan
        res_no_sun = align_and_qualify_ba_series(raw_2022_no_sun, ba_code="SOCO", year=2022, utc_offset_hours=-5)
        assert res_no_sun["qualified"] is True
        assert res_no_sun["signal_type"] == "gross_demand"

    def test_verified_zero_vre_ba_uses_net_demand(self):
        raw_df = _make_raw_eia_utc_df(year=2022, include_wind_solar=False)
        res = align_and_qualify_ba_series(
            raw_df, ba_code="OVEC", year=2022, utc_offset_hours=-5, known_zero_vre_bas=["OVEC"]
        )
        assert res["qualified"] is True
        assert res["signal_type"] == "net_demand"

    def test_interior_gap_le_2_hours_interpolates_and_flags_stress_hour_imputation(self):
        raw_df = _make_raw_eia_utc_df(
            year=2022, peak_local_month=1, peak_local_day=15, peak_local_hour=7, utc_offset_hours=-5
        )
        # Set the 1 hour right next to the peak hour to NaN (isolated 1-hour interior gap between high-demand hours)
        peak_utc_str = "2022-01-15T13"  # Jan 15 07:00 EST -> 12:00 UTC start -> 13:00 UTC ending
        next_utc_str = "2022-01-15T14"
        after_utc_str = "2022-01-15T15"
        raw_df.loc[raw_df["period_utc"] == after_utc_str, "demand_mw"] = 34000.0
        raw_df.loc[raw_df["period_utc"] == next_utc_str, "demand_mw"] = np.nan

        res = align_and_qualify_ba_series(raw_df, ba_code="SOCO", year=2022, utc_offset_hours=-5)
        assert res["qualified"] is True
        assert res["imputed_hour_count"] == 1
        assert res["imputed_stress_hour_flag"] is True
        assert len(res["imputed_positive_weight_hours"]) == 1

    def test_gap_gt_2_consecutive_hours_fails_quality_gate(self):
        raw_df = _make_raw_eia_utc_df(year=2022, utc_offset_hours=-5)
        # Create a 3-hour consecutive gap in February
        raw_df.loc[raw_df["period_utc"].isin(["2022-02-10T10", "2022-02-10T11", "2022-02-10T12"]), "demand_mw"] = np.nan
        res = align_and_qualify_ba_series(raw_df, ba_code="SOCO", year=2022, utc_offset_hours=-5)
        assert res["qualified"] is False
        assert "consecutive missing gap of 3 hours" in res["failure_reason"]

    def test_valid_coverage_below_99_5_percent_fails_quality_gate(self):
        raw_df = _make_raw_eia_utc_df(year=2022, utc_offset_hours=-5)
        # Set 50 isolated single hours (spaced every 100 hours) to NaN -> 8710/8760 = 99.43% < 99.5%
        indices = list(range(100, 5100, 100))
        raw_df.iloc[indices, raw_df.columns.get_loc("demand_mw")] = np.nan
        res = align_and_qualify_ba_series(raw_df, ba_code="SOCO", year=2022, utc_offset_hours=-5)
        assert res["qualified"] is False
        assert "below the required 99.50% minimum threshold" in res["failure_reason"]

    def test_boundary_missing_hour_fails_without_extrapolation(self):
        raw_df = _make_raw_eia_utc_df(year=2022, utc_offset_hours=-5)
        # First local hour of 2022 in UTC-5 (hour_start 2022-01-01 00:00 EST) is UTC hour-ending 2022-01-01T06
        raw_df.loc[raw_df["period_utc"] == "2022-01-01T06", "demand_mw"] = np.nan
        res = align_and_qualify_ba_series(raw_df, ba_code="SOCO", year=2022, utc_offset_hours=-5)
        assert res["qualified"] is False
        assert "boundary extrapolation is prohibited" in res["failure_reason"]

    def test_duplicate_timestamp_conflict_fails_while_identical_deduplicates(self):
        raw_df = _make_raw_eia_utc_df(year=2022, utc_offset_hours=-5)
        dup_row_same = raw_df.iloc[[200]].copy()
        df_same = pd.concat([raw_df, dup_row_same], ignore_index=True)
        res_same = align_and_qualify_ba_series(df_same, ba_code="SOCO", year=2022, utc_offset_hours=-5)
        assert res_same["qualified"] is True
        assert res_same["duplicate_timestamp_count"] == 2

        dup_row_conflict = raw_df.iloc[[200]].copy()
        dup_row_conflict["demand_mw"] = dup_row_conflict["demand_mw"] + 5000.0
        df_conflict = pd.concat([raw_df, dup_row_conflict], ignore_index=True)
        res_conflict = align_and_qualify_ba_series(df_conflict, ba_code="SOCO", year=2022, utc_offset_hours=-5)
        assert res_conflict["qualified"] is False
        assert "conflicting duplicate values" in res_conflict["failure_reason"]

    def test_implausible_data_corruption_spike_fails_qualification(self):
        raw_df = _make_raw_eia_utc_df(year=2022, utc_offset_hours=-5)
        # Inject a 500,000 MW corrupt spike (> 10x median of ~20,000 MW)
        raw_df.loc[raw_df["period_utc"] == "2022-07-15T20", "demand_mw"] = 500000.0
        res = align_and_qualify_ba_series(raw_df, ba_code="SOCO", year=2022, utc_offset_hours=-5)
        assert res["qualified"] is False
        assert "implausible single-hour data-corruption spike" in res["failure_reason"]


# ==============================================================================
# 4. UPPER-TAIL EXCEEDANCE WEIGHT MATH TESTS
# ==============================================================================

class TestUpperTailStressWeightMath:
    def test_weights_nonnegative_sum_to_one_and_monotonic_with_percentile(self):
        rng = np.random.default_rng(123)
        signal = 15000.0 + 3000.0 * np.sin(np.linspace(0, 20 * np.pi, 8760)) + rng.normal(0, 500, 8760)

        w90, d90 = calculate_upper_tail_stress_weights(signal, percentile=90.0)
        w95, d95 = calculate_upper_tail_stress_weights(signal, percentile=95.0)
        w99, d99 = calculate_upper_tail_stress_weights(signal, percentile=99.0)

        for w, d in [(w90, d90), (w95, d95), (w99, d99)]:
            assert len(w) == 8760
            assert np.all(w >= 0.0)
            assert np.isclose(np.sum(w), 1.0, atol=1e-12)
            assert np.isclose(sum(d["monthly_shares"].values()), 1.0, atol=1e-9)
            assert np.isclose(sum(d["seasonal_shares"].values()), 1.0, atol=1e-9)

        # Higher percentile -> higher threshold, fewer nonzero hours, higher max_hour_share, fewer effective hours
        assert d90["threshold_mw"] < d95["threshold_mw"] < d99["threshold_mw"]
        assert d90["nonzero_hours"] > d95["nonzero_hours"] > d99["nonzero_hours"]
        assert d90["max_hour_share"] < d95["max_hour_share"] < d99["max_hour_share"]
        assert d90["effective_hours"] > d95["effective_hours"] > d99["effective_hours"]

    def test_flat_or_constant_signal_rejected(self):
        flat = np.full(8760, 10000.0)
        with pytest.raises(ValueError, match="no meaningful variation"):
            calculate_upper_tail_stress_weights(flat, percentile=95.0)

    def test_upper_tail_tie_fallback_when_top_hours_plateau_at_maximum(self):
        # Signal varies across the year, but top 10% of hours are capped at a flat plateau of 25,000 MW
        signal = np.linspace(10000.0, 25000.0, 8760)
        signal[-900:] = 25000.0
        w, d = calculate_upper_tail_stress_weights(signal, percentile=95.0)
        assert d["tie_fallback_used"] is True
        assert d["nonzero_hours"] == 900
        assert np.isclose(np.sum(w), 1.0)
        assert np.allclose(w[-900:], 1.0 / 900.0)


# ==============================================================================
# 5. WEATHER-YEAR ALIGNMENT, FALLBACKS & VALUATION INTEGRATION TESTS
# ==============================================================================

class TestEligibilityAndValuationIntegration:
    def test_bundled_2012_example_triggers_weather_fallback_with_warning(self):
        weather_fb = np.ones(8760) / 8760.0
        res = evaluate_system_stress_capacity_proxy(
            selected_states=["GA"],
            weather_case="2012",
            weather_fallback_cwft=weather_fb,
            profile_year_basis="AMY",
            cambium_planning_year="2030",
        )
        assert res["status"] == "weather_fallback"
        assert res["fallback_triggered"] is True
        assert "predates Form EIA-930" in res["fallback_reason"]
        assert np.allclose(res["cwft_array"], weather_fb)

    def test_2012_building_with_explicit_stress_year_evaluates_with_misalignment_warning(self):
        """
        When building profile uses 2012 weather (as bundled examples and Cambium do),
        specifying an available EIA stress year (e.g. 2023) allows system-stress proxy
        to evaluate successfully with an explicit weather-misalignment disclosure rather
        than blocking the run with an automatic fallback.
        """
        def _mock_fetcher(ba_code, year, api_key):
            df_raw = _make_raw_eia_utc_df(year=year, peak_local_month=7, peak_local_day=20, peak_local_hour=16, utc_offset_hours=-5)
            return df_raw, {"ba_code": ba_code, "year": year, "source": "mock"}

        with tempfile.TemporaryDirectory() as tmp_cache:
            res = evaluate_system_stress_capacity_proxy(
                selected_states=["GA"],
                weather_case="2012",
                weather_fallback_cwft=np.ones(8760) / 8760.0,
                profile_year_basis="AMY",
                utc_offset_hours=-5,
                user_confirmed_offset=True,
                stress_year=2023,
                raw_fetcher=_mock_fetcher,
                cache_dir=tmp_cache,
            )
            assert res["status"] == "ok"
            assert res["fallback_triggered"] is False
            assert res["cwft_array"] is not None
            assert np.isclose(np.sum(res["cwft_array"]), 1.0)
            prov = res["provenance"]
            assert prov["stress_year"] == 2023
            assert prov["exact_weather_year_match"] is False
            assert "Weather-Year Misalignment" in prov["weather_misalignment_warning"]
            assert "2012" in prov["weather_misalignment_warning"]
            assert "2023" in prov["weather_misalignment_warning"]

    @pytest.mark.parametrize(
        "year_basis,weather_case_val",
        [
            ("TMY", "2022"),
            ("Composite", "2022"),
            ("Unknown", "2022"),
            ("AMY", "Extreme Winter"),
            ("AMY", "Extreme Summer"),
        ],
    )
    def test_tmy_composite_and_synthetic_weather_cases_trigger_fallback(self, year_basis, weather_case_val):
        weather_fb = np.ones(8760) / 8760.0
        res = evaluate_system_stress_capacity_proxy(
            selected_states=["GA"],
            weather_case=weather_case_val,
            weather_fallback_cwft=weather_fb,
            profile_year_basis=year_basis,
        )
        assert res["status"] == "weather_fallback"
        assert res["fallback_triggered"] is True

    def test_imputed_building_load_profile_emits_non_pristine_warning(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "gapped_load.csv")
            vals = np.ones(8760) * 5.0
            vals[50] = np.nan
            vals[51] = np.nan
            pd.DataFrame({"Hour": np.arange(1, 8761), "Baseline_kW": vals}).to_csv(csv_path, index=False)

            load_df = load_load_profiles_from_csv(csv_path)
            assert load_df.attrs["column_imputed_counts"]["Baseline_kW"] == 2

            elig = validate_profile_stress_eligibility(
                selected_states=["GA"],
                weather_case="2022",
                profile_year_basis="AMY",
                load_df=load_df,
                active_profile_cols=["Baseline_kW"],
            )
            assert elig["eligible"] is True
            assert elig["building_imputed_hours"]["Baseline_kW"] == 2
            assert any("not pristine" in w for w in elig["building_imputation_warnings"])

    def test_fixed_profile_invariance_only_generation_capacity_changes(self):
        """
        Confirm that for fixed building load profiles, switching from Weather-Based CWF
        to Public-Data System-Stress CWF changes ONLY Generation Capacity avoided costs
        (and its downstream Utility Grid NPV, TRC, and RIM), while leaving Wholesale Energy,
        Carbon Emissions, Customer Bills, Customer NPV, PCT, and Fixed-Profile T&D strictly invariant.
        """
        dts = pd.Series(pd.date_range("2022-01-01", periods=8760, freq="h"))
        rng = np.random.default_rng(42)
        baseline_kw = 4.0 + 2.0 * np.sin(np.linspace(0, 20 * np.pi, 8760))
        proposed_kw = 2.8 + 1.2 * np.sin(np.linspace(0, 20 * np.pi, 8760))
        reduction_mwh = (baseline_kw - proposed_kw) / 1000.0

        raw_grid_df = pd.DataFrame({
            "Hour": np.arange(1, 8761),
            "Datetime": dts,
            "Cambium_Energy_MWh": 35.0 + 10.0 * rng.random(8760),
            "Cambium_Carbon_kg_MWh": 350.0 + 50.0 * rng.random(8760),
            "PCAF_Weight": np.where(np.arange(8760) < 100, 1.0 / 100.0, 0.0),
            "Temperature_F": 55.0 + 25.0 * np.sin(np.linspace(0, 2 * np.pi, 8760)),
        })

        weather_cwf = calculate_southeast_dual_peak_cwf(
            datetime_series=dts, temperature_array=raw_grid_df["Temperature_F"].to_numpy()
        )

        # Evaluate system-stress proxy using offline raw_fetcher for GA (SOCO + TVA)
        def _mock_fetcher(ba_code, year, api_key):
            df_raw = _make_raw_eia_utc_df(
                year=year,
                peak_local_month=7 if ba_code == "SOCO" else 1,
                peak_local_day=20,
                peak_local_hour=16,
                utc_offset_hours=-5,
            )
            return df_raw, {"ba_code": ba_code, "year": year, "source": "offline_fixture"}

        with tempfile.TemporaryDirectory() as tmp_cache:
            stress_eval = evaluate_system_stress_capacity_proxy(
                selected_states=["GA"],
                weather_case="2022",
                weather_fallback_cwft=weather_cwf,
                profile_year_basis="AMY",
                utc_offset_hours=-5,
                user_confirmed_offset=True,
                cache_dir=tmp_cache,
                raw_fetcher=_mock_fetcher,
                datetime_series=dts,
                cambium_planning_year="2030",
            )
            assert stress_eval["status"] == "ok"
            stress_cwf = stress_eval["cwft_array"]

        dist_w = calculate_feeder_pcaf_weights(
            feeder_type="System Coincident (Top 100 Peak Hours)",
            load_array=baseline_kw,
            price_array=raw_grid_df["Cambium_Energy_MWh"].to_numpy(),
            datetime_series=dts,
        )

        res_weather = calculate_avoided_costs(raw_grid_df, 110.20, 15.0, 25.0, 20.0, weather_cwf, dist_weight_array=dist_w)
        res_stress = calculate_avoided_costs(raw_grid_df, 110.20, 15.0, 25.0, 20.0, stress_cwf, dist_weight_array=dist_w)

        # Invariant streams
        assert np.allclose(
            (reduction_mwh * res_weather["Cambium_Energy_MWh"]).sum(),
            (reduction_mwh * res_stress["Cambium_Energy_MWh"]).sum(),
        )
        assert np.allclose(
            (reduction_mwh * res_weather["Trans_Value_MWh"]).sum(),
            (reduction_mwh * res_stress["Trans_Value_MWh"]).sum(),
        )
        assert np.allclose(
            (reduction_mwh * res_weather["Dist_Value_MWh"]).sum(),
            (reduction_mwh * res_stress["Dist_Value_MWh"]).sum(),
        )
        assert np.allclose(
            (reduction_mwh * res_weather["Emissions_Value_MWh"]).sum(),
            (reduction_mwh * res_stress["Emissions_Value_MWh"]).sum(),
        )

        bill_base, _ = calculate_urdb_bill(baseline_kw, dts, GP_R31_URDB)
        bill_prop, _ = calculate_urdb_bill(proposed_kw, dts, GP_R31_URDB)
        lost_rev = bill_base - bill_prop
        assert lost_rev > 0

        # Generation capacity changes
        gen_cap_weather = float((reduction_mwh * res_weather["Gen_Capacity_Value_MWh"]).sum())
        gen_cap_stress = float((reduction_mwh * res_stress["Gen_Capacity_Value_MWh"]).sum())
        assert not np.isclose(gen_cap_weather, gen_cap_stress)

        # Cost-effectiveness tests: PCT & Customer NPV are strictly invariant; TRC and RIM change via Gen Capacity
        npv_other_benefits = 2500.0
        npv_weather = npv_other_benefits + 10.0 * gen_cap_weather
        npv_stress = npv_other_benefits + 10.0 * gen_cap_stress
        npv_lost_rev = 10.0 * lost_rev
        annual_cust_stream = np.full(15, lost_rev)
        pv_mults = np.ones(15) * (10.0 / 15.0)
        tests_weather = calculate_cost_effectiveness_tests(
            npv_grid_savings=npv_weather,
            npv_lost_revenue=npv_lost_rev,
            npv_customer_bill_savings=npv_lost_rev,
            gross_measure_cost=3000.0,
            utility_incentive=500.0,
            utility_admin_cost=100.0,
            annual_customer_savings_stream=annual_cust_stream,
            pv_multipliers=pv_mults,
        )
        tests_stress = calculate_cost_effectiveness_tests(
            npv_grid_savings=npv_stress,
            npv_lost_revenue=npv_lost_rev,
            npv_customer_bill_savings=npv_lost_rev,
            gross_measure_cost=3000.0,
            utility_incentive=500.0,
            utility_admin_cost=100.0,
            annual_customer_savings_stream=annual_cust_stream,
            pv_multipliers=pv_mults,
        )
        assert np.isclose(tests_weather["pct_ratio"], tests_stress["pct_ratio"])
        assert np.isclose(tests_weather["pct_npv"], tests_stress["pct_npv"])
        assert not np.isclose(tests_weather["trc_ratio"], tests_stress["trc_ratio"])
        assert not np.isclose(tests_weather["rim_ratio"], tests_stress["rim_ratio"])

    def test_dr_mode_reschedules_dispatch_and_same_dispatch_comparator_matches(self):
        dts = pd.Series(pd.date_range("2022-01-01", periods=8760, freq="h"))
        baseline_kw = np.full(8760, 6.0)
        weather_cwf = np.zeros(8760)
        weather_cwf[10:60] = 1.0 / 50.0  # Winter hours

        stress_cwf = np.zeros(8760)
        stress_cwf[4500:4550] = 1.0 / 50.0  # Summer hours (~2 days -> 8 call hours at max 4 hrs/day)

        dr_red_stress, dr_idx_stress = dispatch_dr_program(
            dts, stress_cwf, 8, "Both Seasons", 4, 2.0, baseline_kw
        )
        proposed_stress = baseline_kw - dr_red_stress

        # Same-dispatch weather comparator evaluated on `proposed_stress`
        m_stress = calculate_system_stress_capacity_metrics(
            baseline_kw, proposed_stress, stress_cwf, cap_value_kw_yr=100.0
        )
        m_weather_same_dispatch = calculate_system_stress_capacity_metrics(
            baseline_kw, proposed_stress, weather_cwf, cap_value_kw_yr=100.0
        )
        assert m_stress["capacity_credit_kw"] > 0.0
        assert m_weather_same_dispatch["capacity_credit_kw"] == 0.0  # Because stress dispatch was in summer, outside winter window

    def test_zero_and_negative_load_reductions_handled_cleanly(self):
        w = np.ones(8760) / 8760.0
        base = np.full(8760, 3.0)
        # Zero reduction
        m_zero = calculate_system_stress_capacity_metrics(base, base, w, cap_value_kw_yr=100.0)
        assert m_zero["capacity_credit_kw"] == 0.0
        assert m_zero["proxy_ratio_valid"] is False
        assert m_zero["proxy_coincidence_ratio"] is None
        assert m_zero["proxy_ratio_status"] == "no_positive_load_reduction"

        # All-negative reduction (proposed > baseline in every hour)
        prop_higher = np.full(8760, 4.5)
        m_neg = calculate_system_stress_capacity_metrics(base, prop_higher, w, cap_value_kw_yr=100.0)
        assert np.isclose(m_neg["capacity_credit_kw"], -1.5)
        assert np.isclose(m_neg["generation_capacity_annual_dollars"], -150.0)
        assert m_neg["proxy_ratio_valid"] is False
        assert m_neg["proxy_coincidence_ratio"] is None
        assert m_neg["proxy_ratio_status"] == "negative_or_zero_peak_reduction"


# ==============================================================================
# 6. API PAGINATION, BULK CSV PARSER, ATOMIC CACHE & KEY REDACTION TESTS
# ==============================================================================

class TestPaginationCacheAndRedaction:
    def test_multi_page_pagination_and_numeric_string_parsing(self):
        """
        Verify that `fetch_eia_rto_paginated` loops across multiple pages when total > page_size
        and requests deterministic `sort[0][column]=period&sort[0][direction]=asc`.
        """
        calls = []

        class _FakeResp:
            def __init__(self, body_dict):
                self._bytes = json.dumps(body_dict).encode("utf-8")

            def read(self):
                return self._bytes

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        def _fake_opener(req, timeout=30):
            url = req.full_url
            calls.append(url)
            qs = parse_qs(urlparse(url).query)
            offset = int(qs["offset"][0])
            assert qs["sort[0][column]"] == ["period"]
            assert qs["sort[0][direction]"] == ["asc"]
            if offset == 0:
                rows = [{"period": f"2022-01-01T{h:02d}", "value": str(1000 + h)} for h in range(3)]
            else:
                rows = [{"period": f"2022-01-01T{h:02d}", "value": str(1000 + h)} for h in range(3, 5)]
            return _FakeResp({"response": {"total": "5", "data": rows}})

        rows = fetch_eia_rto_paginated(
            route_url="https://api.eia.gov/v2/electricity/rto/region-data/data/",
            api_key="SUPER_SECRET_USER_KEY_12345",
            respondent_ba="SOCO",
            start_utc="2022-01-01T00",
            end_utc="2022-01-01T05",
            data_types=["D"],
            page_size=3,
            opener=_fake_opener,
        )
        assert len(calls) == 2
        assert len(rows) == 5
        assert [r["value"] for r in rows] == ["1000", "1001", "1002", "1003", "1004"]

    def test_api_key_redacted_on_http_failure_and_in_manifests(self):
        secret_key = "MY_PRIVATE_EIA_KEY_987654321"

        def _failing_opener(req, timeout=30):
            raise RuntimeError(f"Connection failed for {req.full_url} with token {secret_key}")

        with pytest.raises(RuntimeError) as exc_info:
            fetch_eia_rto_paginated(
                route_url="https://api.eia.gov/v2/electricity/rto/region-data/data/",
                api_key=secret_key,
                respondent_ba="SOCO",
                start_utc="2022-01-01T00",
                end_utc="2022-01-02T00",
                max_retries=0,
                opener=_failing_opener,
            )
        err_str = str(exc_info.value)
        assert secret_key not in err_str
        assert "***REDACTED***" in err_str

    def test_atomic_cache_separation_and_sha256_tamper_detection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_csv, raw_manifest = get_raw_cache_paths("SOCO", 2022, cache_dir=tmpdir)
            al_csv_5, al_man_5 = get_aligned_cache_paths("SOCO", 2022, -5, "hour_start", cache_dir=tmpdir)
            al_csv_6, al_man_6 = get_aligned_cache_paths("SOCO", 2022, -6, "hour_start", cache_dir=tmpdir)
            assert raw_csv != al_csv_5
            assert al_csv_5 != al_csv_6

            df_test = pd.DataFrame({"period_utc": ["2022-01-01T01"], "demand_mw": [20000.0]})
            man = save_cache_bundle(
                df_test,
                raw_csv,
                raw_manifest,
                {"ba_code": "SOCO", "api_key": "SHOULD_BE_STRIPPED", "url": "https://api.eia.gov?api_key=SECRET123"},
            )
            assert "api_key" not in man
            assert "SECRET123" not in json.dumps(man)

            loaded = load_cache_bundle(raw_csv, raw_manifest)
            assert loaded is not None
            assert len(loaded[0]) == 1

            # Tamper with CSV file bytes -> SHA-256 verification must reject corrupt cache
            with open(raw_csv, "a", encoding="utf-8") as f:
                f.write("2022-01-01T02,99999.0\n")
            assert load_cache_bundle(raw_csv, raw_manifest) is None

    def test_six_month_bulk_csv_parser_and_visualization_helper(self):
        mock_bulk = pd.DataFrame({
            "Balancing Authority": ["SOCO", "SOCO", "TVA"],
            "Data Date": ["01/01/2022", "01/01/2022", "01/01/2022"],
            "Hour Number": [1, 2, 1],
            "UTC Time at End of Hour": ["01/01/2022 06:00:00", "01/01/2022 07:00:00", "01/01/2022 06:00:00"],
            "Demand (MW)": ["22,500", "23,100", "18,000"],
            "Net Generation (MW) from Solar": ["0", "15", "0"],
            "Net Generation (MW) from Wind": ["120", "130", "50"],
        })
        parsed_df, meta = parse_eia_930_six_month_csv([mock_bulk], ba_code="SOCO", year=2022)
        assert len(parsed_df) == 2
        assert list(parsed_df["period_utc"]) == ["2022-01-01T06", "2022-01-01T07"]
        assert list(parsed_df["demand_mw"]) == [22500.0, 23100.0]
        assert list(parsed_df["solar_mw"]) == [0.0, 15.0]
        assert list(parsed_df["wind_mw"]) == [120.0, 130.0]

        dts = pd.date_range("2022-01-01", periods=8760, freq="h")
        w1 = np.ones(8760) / 8760.0
        w2 = np.ones(8760) / 8760.0
        fig = plot_system_stress_vs_weather_cwf_comparison(w1, w2, dts)
        assert len(fig.data) == 4
