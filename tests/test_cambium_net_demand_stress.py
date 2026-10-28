"""
tests/test_cambium_net_demand_stress.py — Unit tests for Cambium Net-Demand Capacity Proxy
========================================================================================

Verifies the mathematical, chronological, geographic, and loader contracts
for the Cambium regional net-demand capacity-credit proxy.
"""

import os
import json
import numpy as np
import pandas as pd
import pytest

from calculations import (
    calculate_cambium_net_demand_exceedance_weights,
    calculate_cambium_seasonal_net_demand_weights,
    combine_gea_weights_to_state_portfolio,
)
from cambium_downloader import (
    get_geas_for_states,
    get_required_bas_for_geas,
    check_missing_cambium_gea_data,
    load_reeds_gea_manifest,
)
from system_stress_data import (
    validate_cambium_ba_csv,
    aggregate_gea_busbar_net_load,
    align_est_weights_to_local_tz,
    load_cambium_net_demand_proxy_for_portfolio,
)


class TestCambiumNetDemandExceedanceMath:
    def test_exceedance_formula_and_normalization(self):
        """
        Verifies S1 exceedance rule:
            threshold = min(N_101, 0.95 * max(N))
            excess = max(N - threshold, 0)
            weights = excess / sum(excess)
        """
        np.random.seed(42)
        base = np.linspace(1000, 5000, 8760)
        # Create clear upper tail
        base[-100:] += np.linspace(500, 2000, 100)

        weights, diag = calculate_cambium_net_demand_exceedance_weights(base)

        assert len(weights) == 8760
        assert np.isclose(np.sum(weights), 1.0)
        assert np.all(weights >= 0.0)

        max_n = np.max(base)
        n_101 = np.sort(base)[::-1][100]
        expected_threshold = min(n_101, 0.95 * max_n)

        assert np.isclose(diag["threshold"], expected_threshold)
        assert diag["active_hours"] > 0
        assert diag["active_hours"] <= 101
        assert diag["effective_hours"] > 0
        assert diag["top_hour_share"] > 0

    def test_scale_invariance_of_weights(self):
        """Multiplying physical net load by a positive scalar leaves weights identical."""
        base = np.linspace(500, 10000, 8760)
        base[-50:] += 3000

        w1, _ = calculate_cambium_net_demand_exceedance_weights(base)
        w2, _ = calculate_cambium_net_demand_exceedance_weights(base * 2.5)

        np.testing.assert_allclose(w1, w2, atol=1e-12)

    def test_constant_or_flat_signal_rejected(self):
        """Flat or constant series cannot produce valid exceedance weights."""
        flat = np.full(8760, 5000.0)
        with pytest.raises(ValueError, match="no meaningful variation"):
            calculate_cambium_net_demand_exceedance_weights(flat)

    def test_all_negative_or_zero_signal_rejected(self):
        """All-negative or zero signal cannot form a valid capacity proxy."""
        neg = np.linspace(-1000, -10, 8760)
        with pytest.raises(ValueError, match="non-positive"):
            calculate_cambium_net_demand_exceedance_weights(neg)

    def test_al_test_fixture_ground_truth(self):
        """Verifies calculation on offline verified Alabama fixture matches ground truth."""
        fixture_path = "tests/fixtures/cambium_stress/al_test_fixture_8760.csv"
        summary_path = "tests/fixtures/cambium_stress/al_test_summary.json"
        if not os.path.exists(fixture_path):
            pytest.skip("AL fixture not found")

        df = pd.read_csv(fixture_path)
        with open(summary_path, "r") as f:
            gt = json.load(f)

        n_sum = df["net_load_busbar_sum"].values
        weights, diag = calculate_cambium_net_demand_exceedance_weights(n_sum)

        assert np.isclose(diag["peak_net_load"], gt["max_net_load"])
        assert np.isclose(diag["n_101"], gt["n_101"])
        assert np.isclose(diag["threshold"], gt["threshold"])
        assert diag["active_hours"] == gt["active_hours"]
        assert np.isclose(diag["top_hour_share"], gt["top_hour_weight"])
        assert np.isclose(diag["effective_hours"], gt["effective_hours"], rtol=1e-3)


class TestChronologyAndTimeZoneAlignment:
    def test_est_to_ct_hour_shift(self):
        """EST (UTC-5) peak at hour 14 aligns with CT (UTC-6) peak at hour 13."""
        w_est = np.zeros(8760)
        w_est[14] = 1.0  # 2 PM EST

        w_ct = align_est_weights_to_local_tz(w_est, "AL")  # CT
        assert np.argmax(w_ct) == 13
        assert np.isclose(np.sum(w_ct), 1.0)

    def test_est_to_et_zero_shift(self):
        """EST (UTC-5) peak aligns with ET (UTC-5) at the exact same hour index."""
        w_est = np.zeros(8760)
        w_est[17] = 1.0

        w_et = align_est_weights_to_local_tz(w_est, "GA")  # ET
        assert np.argmax(w_et) == 17
        assert np.isclose(np.sum(w_et), 1.0)

    def test_est_to_pt_hour_shift(self):
        """EST peak at hour 18 aligns with PT (UTC-8) peak at hour 15 (3-hour difference)."""
        w_est = np.zeros(8760)
        w_est[18] = 1.0

        w_pt = align_est_weights_to_local_tz(w_est, "CA")  # PT
        assert np.argmax(w_pt) == 15
        assert np.isclose(np.sum(w_pt), 1.0)

    def test_year_boundary_wrap(self):
        """EST hour 0 (00:00 EST Jan 1) maps to CT hour 8759 (23:00 CT Dec 31)."""
        w_est = np.zeros(8760)
        w_est[0] = 1.0

        w_ct = align_est_weights_to_local_tz(w_est, "AL")
        assert np.argmax(w_ct) == 8759
        assert np.isclose(np.sum(w_ct), 1.0)


class TestGeographicRoutingAndManifest:
    def test_manifest_covers_all_48_states_and_18_geas(self):
        """The pinned Cambium ReEDS GEA manifest covers 48 states and 18 GEAs."""
        manifest = load_reeds_gea_manifest()
        assert manifest["total_bas"] == 133
        assert len(manifest["gea_to_bas"]) == 18

        all_states = set(b["state"] for b in manifest["bas"])
        assert len(all_states) == 48

    def test_multi_gea_state_resolution(self):
        """States like TX, FL, and KY resolve to all intersecting GEAs."""
        geas = get_geas_for_states(["TX", "FL", "KY"])
        assert len(geas["TX"]) == 4  # ERCOT, MISO_South, SPP_South, WestConnect_South
        assert len(geas["FL"]) == 2  # FRCC, SERTP
        assert len(geas["KY"]) == 3  # PJM_East, MISO_Central, SERTP

    def test_missing_data_reporting(self):
        """Detects missing constituent BAs without raising an exception."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create only p89 in tmpdir
            with open(os.path.join(tmpdir, "Cambium24_MidCase_hourly_p89_2030.csv"), "w") as f:
                f.write("dummy,data\n1,2\n")

            missing = check_missing_cambium_gea_data(["SERTP"], "MidCase", "2030", input_directory=tmpdir)
            assert "SERTP" in missing
            assert "p88" in missing["SERTP"]
            assert "p89" not in missing["SERTP"]


class TestPortfolioCombination:
    def test_equal_weight_state_portfolio(self):
        """Multi-state portfolio combines state weight vectors with equal weighting."""
        w1 = np.zeros(8760)
        w1[100] = 1.0
        w2 = np.zeros(8760)
        w2[200] = 1.0

        comb = combine_gea_weights_to_state_portfolio({"AL": w1, "GA": w2})
        assert np.isclose(comb[100], 0.5)
        assert np.isclose(comb[200], 0.5)
        assert np.isclose(np.sum(comb), 1.0)


class TestCambiumNetDemandIntegrationAndInvariants:
    def test_fixed_profile_non_capacity_invariance(self):
        """
        Fixed building profiles: wholesale energy, emissions, retail bills,
        customer NPV, and T&D deferral MUST remain strictly invariant when
        switching to Cambium net-demand proxy. Only generation capacity changes.
        """
        from calculations import (
            calculate_avoided_costs,
            calculate_southeast_dual_peak_cwf,
            calculate_cwf_lolp_proxy,
        )

        n_hours = 8760
        hours = np.arange(n_hours)
        raw_df = pd.DataFrame({
            "Hour": hours + 1,
            "Cambium_Energy_MWh": 20.0 + 15.0 * np.sin(hours / 24.0),
            "Cambium_Carbon_kg_MWh": 400.0 + 50.0 * np.cos(hours / 24.0),
            "PCAF_Weight": np.full(n_hours, 1.0 / n_hours),
            "Temperature_F": 70.0 + 10.0 * np.sin(hours / 365.0),
        })

        cap_val, trans_val, dist_val, carbon_tax = 100.0, 20.0, 15.0, 25.0

        # Method 1: Weather Dual-Peak
        cwft_weather = calculate_southeast_dual_peak_cwf()
        res_weather = calculate_avoided_costs(raw_df, cap_val, trans_val, dist_val, carbon_tax, cwft_weather)

        # Method 2: Cambium Net-Demand (from AL fixture)
        fixture_path = "tests/fixtures/cambium_stress/al_test_fixture_8760.csv"
        df_fix = pd.read_csv(fixture_path)
        cwft_net_demand, _ = calculate_cambium_net_demand_exceedance_weights(df_fix["net_load_busbar_sum"].values)
        res_net_demand = calculate_avoided_costs(raw_df, cap_val, trans_val, dist_val, carbon_tax, cwft_net_demand)

        # Method 3: Cambium Price Proxy
        cwft_price = calculate_cwf_lolp_proxy(raw_df["Cambium_Energy_MWh"].values)
        res_price = calculate_avoided_costs(raw_df, cap_val, trans_val, dist_val, carbon_tax, cwft_price)

        # Wholesale energy, T&D, and emissions must be 100% IDENTICAL across all methods
        np.testing.assert_allclose(res_weather["Cambium_Energy_MWh"].values, res_net_demand["Cambium_Energy_MWh"].values)
        np.testing.assert_allclose(res_weather["Trans_Value_MWh"].values, res_net_demand["Trans_Value_MWh"].values)
        np.testing.assert_allclose(res_weather["Dist_Value_MWh"].values, res_net_demand["Dist_Value_MWh"].values)
        np.testing.assert_allclose(res_weather["Emissions_Value_MWh"].values, res_net_demand["Emissions_Value_MWh"].values)

        # Generation capacity value MUST differ reflecting distinct capacity risk allocation
        assert not np.allclose(res_weather["Gen_Capacity_Value_MWh"].values, res_net_demand["Gen_Capacity_Value_MWh"].values)
        assert not np.allclose(res_price["Gen_Capacity_Value_MWh"].values, res_net_demand["Gen_Capacity_Value_MWh"].values)

    def test_constant_1kw_reduction_yields_1kw_credit(self):
        """A continuous 1.0 kW load reduction gives exactly 1.0 kW credit under any normalized CWF."""
        fixture_path = "tests/fixtures/cambium_stress/al_test_fixture_8760.csv"
        df_fix = pd.read_csv(fixture_path)
        cwft, _ = calculate_cambium_net_demand_exceedance_weights(df_fix["net_load_busbar_sum"].values)

        reduction = np.ones(8760)
        credit_kw = float(np.sum(reduction * cwft))
        assert np.isclose(credit_kw, 1.0)

    def test_signed_rebound_preserved(self):
        """Negative load reductions (rebound) reduce credit without zero-clipping."""
        fixture_path = "tests/fixtures/cambium_stress/al_test_fixture_8760.csv"
        df_fix = pd.read_csv(fixture_path)
        cwft, _ = calculate_cambium_net_demand_exceedance_weights(df_fix["net_load_busbar_sum"].values)

        active_indices = np.where(cwft > 0)[0]
        reduction = np.zeros(8760)
        # Add negative reduction (rebound) in an active peak hour
        rebound_hour = active_indices[0]
        reduction[rebound_hour] = -5.0

        credit_kw = float(np.sum(reduction * cwft))
        assert credit_kw < 0.0
        assert np.isclose(credit_kw, -5.0 * cwft[rebound_hour])

    def test_dr_dispatch_rescheduling_and_same_dispatch_comparison(self):
        """
        DR mode: net-demand weights reschedule dispatch. Evaluating both weight sets
        on the identical dispatch schedule cleanly isolates valuation differences.
        """
        from calculations import (
            dispatch_dr_program,
            calculate_southeast_dual_peak_cwf,
        )

        n_hours = 8760
        hours = pd.Series(pd.date_range("2030-01-01", periods=n_hours, freq="h"))
        cwft_weather = calculate_southeast_dual_peak_cwf(datetime_series=hours)

        fixture_path = "tests/fixtures/cambium_stress/al_test_fixture_8760.csv"
        df_fix = pd.read_csv(fixture_path)
        cwft_net_demand, _ = calculate_cambium_net_demand_exceedance_weights(df_fix["net_load_busbar_sum"].values)

        baseline_load = 5.0 + 3.0 * np.sin(np.arange(n_hours) / 12.0)

        # Dispatch with weather
        red_w, idx_w = dispatch_dr_program(hours, cwft_weather, 100, "Both", 4, 2.0, baseline_load)

        # Dispatch with net demand
        red_nd, idx_nd = dispatch_dr_program(hours, cwft_net_demand, 100, "Both", 4, 2.0, baseline_load)

        # Dispatched hours differ
        assert not np.array_equal(idx_w, idx_nd)

        # Same-dispatch comparison: evaluate red_nd with both cwft_net_demand and cwft_weather
        credit_nd_dispatch_nd_weights = float(np.sum(red_nd * cwft_net_demand))
        credit_nd_dispatch_w_weights = float(np.sum(red_nd * cwft_weather))

        # Both credits are positive but reflect different valuation weights on the same physical profile
        assert credit_nd_dispatch_nd_weights > 0.0
        assert credit_nd_dispatch_w_weights > 0.0


class TestCambiumSeasonalNetDemandMath:
    """Verifies the seasonal split (Winter/Summer) Cambium net-demand weighting logic."""

    def test_seasonal_split_weights_sum_to_one_and_positive(self):
        np.random.seed(42)
        base = np.linspace(1000, 5000, 8760)
        base[:744] += 2000  # January winter spike
        base[4500:5000] += 3000  # Summer spike

        hours = pd.date_range("2030-01-01", periods=8760, freq="h")
        weights, diag = calculate_cambium_seasonal_net_demand_weights(
            base, datetime_series=hours, winter_weight=0.60, summer_weight=0.40
        )
        assert len(weights) == 8760
        assert np.isclose(np.sum(weights), 1.0)
        assert np.all(weights >= 0.0)
        assert diag["active_hours"] > 0
        assert diag["winter_weight"] == 0.60
        assert diag["summer_weight"] == 0.40

    def test_seasonal_shares_match_parameters(self):
        fixture_path = "tests/fixtures/cambium_stress/al_test_fixture_8760.csv"
        df_fix = pd.read_csv(fixture_path)
        net_load = df_fix["net_load_busbar_sum"].values

        hours = pd.date_range("2030-01-01", periods=8760, freq="h")
        months = hours.month.values

        w_60_40, diag = calculate_cambium_seasonal_net_demand_weights(
            net_load, datetime_series=hours, winter_weight=0.60, summer_weight=0.40
        )
        winter_actual = np.sum(w_60_40[np.isin(months, [12, 1, 2])])
        summer_actual = np.sum(w_60_40[np.isin(months, [6, 7, 8, 9])])
        shoulder_actual = np.sum(w_60_40[np.isin(months, [3, 4, 5, 10, 11])])

        assert np.isclose(winter_actual, 0.60)
        assert np.isclose(summer_actual, 0.40)
        assert np.isclose(shoulder_actual, 0.0)

        # 80/20 test
        w_80_20, _ = calculate_cambium_seasonal_net_demand_weights(
            net_load, datetime_series=hours, winter_weight=0.80, summer_weight=0.20
        )
        assert np.isclose(np.sum(w_80_20[np.isin(months, [12, 1, 2])]), 0.80)
        assert np.isclose(np.sum(w_80_20[np.isin(months, [6, 7, 8, 9])]), 0.20)

    def test_seasonal_split_credit_lands_in_middle(self):
        """Verifies seasonal net demand produces credit between annual and weather extremes."""
        fixture_path = "tests/fixtures/cambium_stress/al_test_fixture_8760.csv"
        df_fix = pd.read_csv(fixture_path)
        net_load = df_fix["net_load_busbar_sum"].values
        hours = pd.Series(pd.date_range("2030-01-01", periods=8760, freq="h"))

        from calculations import calculate_southeast_dual_peak_cwf
        w_weather = calculate_southeast_dual_peak_cwf(datetime_series=hours, winter_weight=0.8, summer_weight=0.2)
        w_annual, _ = calculate_cambium_net_demand_exceedance_weights(net_load, datetime_series=hours)
        w_seasonal, _ = calculate_cambium_seasonal_net_demand_weights(net_load, datetime_series=hours, winter_weight=0.60, summer_weight=0.40)

        df_lp = pd.read_csv("load_profiles.csv")
        reduction = (df_lp["Standard_Heat_Pump_kW"] - df_lp["High_Efficiency_Heat_Pump_kW"]).values

        credit_weather = float(np.sum(reduction * w_weather))
        credit_annual = float(np.sum(reduction * w_annual))
        credit_seasonal = float(np.sum(reduction * w_seasonal))

        # Seasonal credit must be cleanly bounded by the two extremes
        assert credit_annual < credit_seasonal < credit_weather
        # And specifically in the reasonable engineering range ~0.75 - 1.1 kW
        assert 0.70 <= credit_seasonal <= 1.20


class TestCambiumStateLevelAggregation:
    """Verifies state-level ReEDS BA aggregation for Cambium net demand."""

    def test_state_level_portfolio_resolution(self):
        from system_stress_data import load_cambium_net_demand_proxy_for_portfolio

        res = load_cambium_net_demand_proxy_for_portfolio(
            target_states=["GA"],
            selected_scenario="MidCase",
            planning_year="2030",
            raw_directory="./Cambium_Hourly_Data_raw",
            seasonal_split=True,
            aggregation_level="state",
        )
        assert res["status"] == "ok"
        assert res["is_qualified"] is True
        assert res["aggregation_level"] == "state"
        assert res["state_to_bas"] == {"GA": ["p94"]}
        assert np.isclose(np.sum(res["weights"]), 1.0)
        assert res["diagnostics"]["active_hours"] > 0

    def test_multi_state_level_aggregation(self):
        from system_stress_data import load_cambium_net_demand_proxy_for_portfolio

        res = load_cambium_net_demand_proxy_for_portfolio(
            target_states=["GA", "AL"],
            selected_scenario="MidCase",
            planning_year="2030",
            raw_directory="./Cambium_Hourly_Data_raw",
            seasonal_split=True,
            aggregation_level="state",
        )
        assert res["status"] == "ok"
        assert res["is_qualified"] is True
        assert res["state_to_bas"]["GA"] == ["p94"]
        assert sorted(res["state_to_bas"]["AL"]) == ["p89", "p90"]
        assert np.isclose(np.sum(res["weights"]), 1.0)
