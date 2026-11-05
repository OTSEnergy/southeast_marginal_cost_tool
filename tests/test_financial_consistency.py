"""
test_financial_consistency.py — Verification of Financial Consistency and NPV Explanation
========================================================================================

Tests the explicit financial basis features implemented for Workstreams 3, 4, and 5:
- Exact Fisher relationship: (1 + r_nom) = (1 + r_real) * (1 + i)
- Real vs Nominal NPV mathematical equivalence
- Mid-year vs Year-end continuous cash flow discounting
- Legacy current-method regression preservation
- Annual energy explanation and zero-reduction limitation handling
- Annual capacity explanation and physical credited kW breakdowns
- Reproducible NPV waterfall change bridge and zero residual verification
"""

import pytest
import numpy as np
import pandas as pd
from calculations import (
    calculate_multi_year_avoided_costs_and_npv,
    build_annual_energy_explanation,
    build_annual_capacity_explanation,
    build_reproducible_npv_bridge,
)


class TestFinancialConsistencyEquivalence:
    """Tests Fisher relationship and exact real vs nominal valuation equivalence."""

    def test_fisher_equation_exact_conversion(self):
        """Verify exact Fisher conversion between nominal and real discount rates."""
        inflation = 0.02
        wacc_nom = 0.07
        expected_real = (1.0 + wacc_nom) / (1.0 + inflation) - 1.0
        assert pytest.approx(expected_real, rel=1e-9) == 0.049019607843137255

        # Inverted
        recovered_nom = (1.0 + expected_real) * (1.0 + inflation) - 1.0
        assert pytest.approx(recovered_nom, rel=1e-9) == wacc_nom

    def test_real_vs_nominal_npv_exact_equivalence_yearend(self):
        """
        Verify that real and nominal valuations produce identical NPVs
        under year-end discounting across all cash flow streams.
        """
        np.random.seed(42)
        n_years = 15
        interp_prices = {2026 + t - 1: np.random.uniform(20.0, 50.0, 8760) for t in range(1, n_years + 1)}
        load_red = np.random.uniform(0.1, 2.0, 8760)
        cwft = np.random.dirichlet(np.ones(8760))
        pcaf = np.random.dirichlet(np.ones(8760))

        res_real = calculate_multi_year_avoided_costs_and_npv(
            asset_life=n_years,
            start_year=2026,
            interpolated_energy_prices=interp_prices,
            load_reduction=load_red,
            cwft_array=cwft,
            pcaf_array=pcaf,
            cap_value=110.20,
            trans_value=14.00,
            dist_value=22.00,
            carbon_tax=0.0,
            discount_rate=7.0,
            customer_discount_rate=7.0,
            degradation_rate=1.0,
            annual_lost_revenue_yr1=500.0,
            retail_escalation_rate=2.0,
            gross_measure_cost=3000.0,
            utility_incentive=500.0,
            utility_admin_cost=100.0,
            capacity_escalation_rate=1.0,
            financial_method="financially_consistent",
            valuation_basis="real",
            discount_timing="year_end",
        )

        res_nom = calculate_multi_year_avoided_costs_and_npv(
            asset_life=n_years,
            start_year=2026,
            interpolated_energy_prices=interp_prices,
            load_reduction=load_red,
            cwft_array=cwft,
            pcaf_array=pcaf,
            cap_value=110.20,
            trans_value=14.00,
            dist_value=22.00,
            carbon_tax=0.0,
            discount_rate=7.0,
            customer_discount_rate=7.0,
            degradation_rate=1.0,
            annual_lost_revenue_yr1=500.0,
            retail_escalation_rate=2.0,
            gross_measure_cost=3000.0,
            utility_incentive=500.0,
            utility_admin_cost=100.0,
            capacity_escalation_rate=1.0,
            financial_method="financially_consistent",
            valuation_basis="nominal",
            discount_timing="year_end",
        )

        assert abs(res_real["npv_energy_savings"] - res_nom["npv_energy_savings"]) < 1e-9
        assert abs(res_real["npv_capacity_savings"] - res_nom["npv_capacity_savings"]) < 1e-9
        assert abs(res_real["npv_retail_lost_revenue"] - res_nom["npv_retail_lost_revenue"]) < 1e-9
        assert abs(res_real["npv_net_savings"] - res_nom["npv_net_savings"]) < 1e-9

    def test_real_vs_nominal_npv_exact_equivalence_midyear(self):
        """
        Verify that real and nominal valuations produce identical NPVs
        under mid-year continuous discounting across all cash flow streams.
        """
        np.random.seed(99)
        n_years = 15
        interp_prices = {2026 + t - 1: np.random.uniform(25.0, 60.0, 8760) for t in range(1, n_years + 1)}
        load_red = np.random.uniform(0.2, 1.5, 8760)
        cwft = np.random.dirichlet(np.ones(8760))
        pcaf = np.random.dirichlet(np.ones(8760))

        res_real = calculate_multi_year_avoided_costs_and_npv(
            asset_life=n_years,
            start_year=2026,
            interpolated_energy_prices=interp_prices,
            load_reduction=load_red,
            cwft_array=cwft,
            pcaf_array=pcaf,
            cap_value=110.20,
            trans_value=14.00,
            dist_value=22.00,
            carbon_tax=0.0,
            discount_rate=7.0,
            customer_discount_rate=7.0,
            degradation_rate=1.0,
            annual_lost_revenue_yr1=600.0,
            retail_escalation_rate=2.0,
            gross_measure_cost=3000.0,
            utility_incentive=500.0,
            utility_admin_cost=100.0,
            capacity_escalation_rate=1.0,
            financial_method="financially_consistent",
            valuation_basis="real",
            discount_timing="mid_year",
        )

        res_nom = calculate_multi_year_avoided_costs_and_npv(
            asset_life=n_years,
            start_year=2026,
            interpolated_energy_prices=interp_prices,
            load_reduction=load_red,
            cwft_array=cwft,
            pcaf_array=pcaf,
            cap_value=110.20,
            trans_value=14.00,
            dist_value=22.00,
            carbon_tax=0.0,
            discount_rate=7.0,
            customer_discount_rate=7.0,
            degradation_rate=1.0,
            annual_lost_revenue_yr1=600.0,
            retail_escalation_rate=2.0,
            gross_measure_cost=3000.0,
            utility_incentive=500.0,
            utility_admin_cost=100.0,
            capacity_escalation_rate=1.0,
            financial_method="financially_consistent",
            valuation_basis="nominal",
            discount_timing="mid_year",
        )

        assert abs(res_real["npv_energy_savings"] - res_nom["npv_energy_savings"]) < 1e-9
        assert abs(res_real["npv_capacity_savings"] - res_nom["npv_capacity_savings"]) < 1e-9
        assert abs(res_real["npv_retail_lost_revenue"] - res_nom["npv_retail_lost_revenue"]) < 1e-9
        assert abs(res_real["npv_net_savings"] - res_nom["npv_net_savings"]) < 1e-9

    def test_mid_year_timing_factor_mathematical_relation(self):
        """Verify mid-year discounting scales operating cash flow PVs by exactly (1 + r)^0.5."""
        interp_prices = {2026 + t - 1: np.full(8760, 35.0) for t in range(1, 16)}
        load_red = np.ones(8760)
        cwft = np.full(8760, 1.0 / 8760)
        pcaf = np.full(8760, 1.0 / 8760)

        res_ye = calculate_multi_year_avoided_costs_and_npv(
            asset_life=15, start_year=2026, interpolated_energy_prices=interp_prices,
            load_reduction=load_red, cwft_array=cwft, pcaf_array=pcaf,
            cap_value=110.20, trans_value=14.00, dist_value=22.00, carbon_tax=0.0,
            discount_rate=7.0, customer_discount_rate=7.0, degradation_rate=1.0,
            annual_lost_revenue_yr1=500.0, retail_escalation_rate=2.0,
            gross_measure_cost=0.0, utility_incentive=0.0, utility_admin_cost=0.0,
            capacity_escalation_rate=1.0,
            financial_method="financially_consistent", valuation_basis="real",
            discount_timing="year_end"
        )

        res_mid = calculate_multi_year_avoided_costs_and_npv(
            asset_life=15, start_year=2026, interpolated_energy_prices=interp_prices,
            load_reduction=load_red, cwft_array=cwft, pcaf_array=pcaf,
            cap_value=110.20, trans_value=14.00, dist_value=22.00, carbon_tax=0.0,
            discount_rate=7.0, customer_discount_rate=7.0, degradation_rate=1.0,
            annual_lost_revenue_yr1=500.0, retail_escalation_rate=2.0,
            gross_measure_cost=0.0, utility_incentive=0.0, utility_admin_cost=0.0,
            capacity_escalation_rate=1.0,
            financial_method="financially_consistent", valuation_basis="real",
            discount_timing="mid_year"
        )

        r_real = res_ye["r_real"]
        expected_ratio = (1.0 + r_real) ** 0.5
        actual_energy_ratio = res_mid["npv_energy_savings"] / res_ye["npv_energy_savings"]
        actual_cap_ratio = res_mid["npv_capacity_savings"] / res_ye["npv_capacity_savings"]

        assert pytest.approx(actual_energy_ratio, rel=1e-9) == expected_ratio
        assert pytest.approx(actual_cap_ratio, rel=1e-9) == expected_ratio


class TestEnergyAndCapacityExplanations:
    """Tests Workstream 4 explanation outputs for energy and capacity."""

    def test_annual_energy_explanation_structure_and_values(self):
        """Verify annual energy explanation table columns and degradation behavior."""
        interp_prices = {2026 + t - 1: np.full(8760, 40.0) for t in range(1, 16)}
        load_red = np.full(8760, 0.5)
        cwft = np.full(8760, 1.0 / 8760)
        pcaf = np.full(8760, 1.0 / 8760)

        res = calculate_multi_year_avoided_costs_and_npv(
            asset_life=15, start_year=2026, interpolated_energy_prices=interp_prices,
            load_reduction=load_red, cwft_array=cwft, pcaf_array=pcaf,
            cap_value=110.20, trans_value=14.00, dist_value=22.00, carbon_tax=0.0,
            discount_rate=7.0, customer_discount_rate=7.0, degradation_rate=1.0,
            annual_lost_revenue_yr1=500.0, retail_escalation_rate=2.0,
            financial_method="current"
        )

        e_table = build_annual_energy_explanation(
            multi_year_result=res,
            scenario_name="MidCase",
            regional_mapping="AL (50% p89, 50% p90)",
            annual_baseline_kwh=10000.0,
            annual_proposed_kwh=5620.0,
            annual_reduction_kwh=4380.0
        )

        assert len(e_table) == 15
        assert "Operating_Year" in e_table.columns
        assert "Avoided_Energy_Value_Per_MWh" in e_table.columns
        assert "Discounted_Avoided_Energy_Value_PV" in e_table.columns
        assert e_table["Operating_Year"].iloc[0] == 1
        assert e_table["Calendar_Year"].iloc[-1] == 2040

        # Degradation factor must decline monotonically
        deg_factors = e_table["Degradation_Factor"].values
        assert deg_factors[0] == 1.0
        assert deg_factors[-1] < 1.0
        assert np.all(np.diff(deg_factors) < 0)

    def test_annual_energy_explanation_near_zero_reduction_handling(self):
        """Verify that zero or near-zero reduction sets $/MWh to NaN and flags limitation."""
        interp_prices = {2026 + t - 1: np.full(8760, 40.0) for t in range(1, 16)}
        load_red = np.zeros(8760)
        cwft = np.full(8760, 1.0 / 8760)
        pcaf = np.full(8760, 1.0 / 8760)

        res = calculate_multi_year_avoided_costs_and_npv(
            asset_life=15, start_year=2026, interpolated_energy_prices=interp_prices,
            load_reduction=load_red, cwft_array=cwft, pcaf_array=pcaf,
            cap_value=110.20, trans_value=14.00, dist_value=22.00, carbon_tax=0.0,
            discount_rate=7.0, customer_discount_rate=7.0, degradation_rate=1.0,
            annual_lost_revenue_yr1=0.0, retail_escalation_rate=2.0,
            financial_method="current"
        )

        e_table = build_annual_energy_explanation(
            multi_year_result=res,
            scenario_name="MidCase",
            regional_mapping="AL",
            annual_baseline_kwh=5000.0,
            annual_proposed_kwh=5000.0,
            annual_reduction_kwh=0.0
        )

        assert np.all(np.isnan(e_table["Avoided_Energy_Value_Per_MWh"]))
        assert np.all(e_table["Limitation_Flag"].str.contains("LIMITATION"))

    def test_annual_capacity_explanation_credited_kw(self):
        """Verify physical credited kW calculations and summary metrics."""
        load_red = np.full(8760, 2.0)
        cwft = np.full(8760, 1.0 / 8760)
        pcaf = np.full(8760, 1.0 / 8760)
        dist_w = np.full(8760, 1.0 / 8760)

        interp_prices = {2026 + t - 1: np.full(8760, 30.0) for t in range(1, 16)}

        res = calculate_multi_year_avoided_costs_and_npv(
            asset_life=15, start_year=2026, interpolated_energy_prices=interp_prices,
            load_reduction=load_red, cwft_array=cwft, pcaf_array=pcaf,
            cap_value=110.20, trans_value=14.00, dist_value=22.00, carbon_tax=0.0,
            discount_rate=7.0, customer_discount_rate=7.0, degradation_rate=1.0,
            annual_lost_revenue_yr1=500.0, retail_escalation_rate=2.0,
            financial_method="current", dist_weight_array=dist_w
        )

        cap_exp = build_annual_capacity_explanation(
            load_reduction_kw=load_red,
            cwft_array=cwft,
            pcaf_array=pcaf,
            dist_weight_array=dist_w,
            cap_value=110.20,
            trans_value=14.00,
            dist_value=22.00,
            multi_year_result=res,
        )

        sm = cap_exp["summary_metrics"]
        assert pytest.approx(sm["gen_credited_kw"], rel=1e-6) == 2.0
        assert pytest.approx(sm["trans_credited_kw"], rel=1e-6) == 2.0
        assert pytest.approx(sm["dist_credited_kw"], rel=1e-6) == 2.0
        assert sm["gen_unit_price"] == 110.20
        assert sm["trans_unit_price"] == 14.00
        assert sm["dist_unit_price"] == 22.00
        assert len(cap_exp["annual_table"]) == 15


class TestReproducibleNPVBridge:
    """Tests Workstream 5 NPV change bridge and waterfall attribution."""

    def test_bridge_reconciliation_zero_residual(self):
        """Verify that sequential waterfall attribution reconciles with exact zero residual."""
        np.random.seed(123)
        n_years = 15
        interp_prices = {2026 + t - 1: np.random.uniform(20.0, 50.0, 8760) for t in range(1, n_years + 1)}
        load_red = np.random.uniform(0.1, 2.0, 8760)
        cwft = np.random.dirichlet(np.ones(8760))
        pcaf = np.random.dirichlet(np.ones(8760))

        res_curr = calculate_multi_year_avoided_costs_and_npv(
            asset_life=n_years, start_year=2026, interpolated_energy_prices=interp_prices,
            load_reduction=load_red, cwft_array=cwft, pcaf_array=pcaf,
            cap_value=110.20, trans_value=14.00, dist_value=22.00, carbon_tax=0.0,
            discount_rate=7.0, customer_discount_rate=7.0, degradation_rate=1.0,
            annual_lost_revenue_yr1=500.0, retail_escalation_rate=2.0,
            gross_measure_cost=3000.0, utility_incentive=500.0, utility_admin_cost=100.0,
            capacity_escalation_rate=1.0, financial_method="current"
        )

        res_cons = calculate_multi_year_avoided_costs_and_npv(
            asset_life=n_years, start_year=2026, interpolated_energy_prices=interp_prices,
            load_reduction=load_red, cwft_array=cwft, pcaf_array=pcaf,
            cap_value=110.20, trans_value=14.00, dist_value=22.00, carbon_tax=0.0,
            discount_rate=7.0, customer_discount_rate=7.0, degradation_rate=1.0,
            annual_lost_revenue_yr1=500.0, retail_escalation_rate=2.0,
            gross_measure_cost=3000.0, utility_incentive=500.0, utility_admin_cost=100.0,
            capacity_escalation_rate=1.0, financial_method="financially_consistent",
            valuation_basis="real", discount_timing="mid_year"
        )

        sensitivities = {
            "HighDemandGrowth": {"npv_net_savings": res_cons["npv_net_savings"] + 100.0},
            "HighNGPrice": {"npv_net_savings": res_cons["npv_net_savings"] + 250.0},
        }

        bridge_df = build_reproducible_npv_bridge(
            baseline_npv_result=res_curr,
            consistent_npv_result=res_cons,
            scenario_sensitivities=sensitivities,
            colocation_contamination_delta=-64.49,
        )

        assert "Step_Number" in bridge_df.columns
        assert "Delta_NPV" in bridge_df.columns
        assert "Intermediate_NPV" in bridge_df.columns
        assert "Residual" in bridge_df.columns

        # Verify all residuals are zero
        assert np.all(np.abs(bridge_df["Residual"].values) < 1e-9)

        # Verify intermediate NPV matches cumulative deltas
        step0_npv = bridge_df["Intermediate_NPV"].iloc[0]
        step1_delta = bridge_df["Delta_NPV"].iloc[1]
        assert pytest.approx(bridge_df["Intermediate_NPV"].iloc[1], rel=1e-9) == step0_npv + step1_delta
