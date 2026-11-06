"""
tests/test_escalation_scenarios.py — Unit Tests for Non-Cambium Escalation Scenarios
===================================================================================

Validates non-Cambium cost escalation scenarios (Base Growth, High Escalation,
Low Growth, Custom):
1. Scenario dictionary structure and get_escalation_scenario_adders helper.
2. Incremental adder compounding in SERCCapacityModel.get_projection.
3. Multi-year valuation engine integration in calculate_multi_year_avoided_costs_and_npv:
   - Base Growth produces exact baseline invariance.
   - High Escalation strictly increases capacity, T&D, carbon, and retail cash flows.
   - Low Growth strictly decreases them relative to base.
   - Decoupled stream behavior (modifying one adder does not bleed into others).
4. Validation across both 'current' and 'financially_consistent' financial methods.
"""

import os
import sys
import pytest
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config import (
    ESCALATION_SCENARIO_BASE,
    ESCALATION_SCENARIO_HIGH,
    ESCALATION_SCENARIO_LOW,
    ESCALATION_SCENARIO_CUSTOM,
    NON_CAMBIUM_ESCALATION_SCENARIOS,
    get_escalation_scenario_adders,
)
from serc_capacity_cost import SERCCapacityModel
from calculations import (
    calculate_multi_year_avoided_costs_and_npv,
    build_annual_escalated_values_table,
)


@pytest.fixture
def mock_multi_year_inputs():
    """Synthetic inputs for 5-year avoided cost and NPV testing."""
    n_hours = 8760
    years = [2026, 2027, 2028, 2029, 2030]
    asset_life = len(years)
    start_year = 2026

    # Flat synthetic load reduction: 10 kW across all hours
    load_reduction = np.full(n_hours, 10.0)

    # Uniform CWFT and PCAF summing to 1.0
    cwft_array = np.full(n_hours, 1.0 / n_hours)
    pcaf_array = np.full(n_hours, 1.0 / n_hours)

    # Energy prices: $40/MWh flat across all years
    interpolated_energy = {yr: np.full(n_hours, 40.0) for yr in years}

    # Carbon emissions: 400 kg CO2/MWh
    interpolated_carbon = {yr: np.full(n_hours, 400.0) for yr in years}

    return {
        "asset_life": asset_life,
        "start_year": start_year,
        "interpolated_energy_prices": interpolated_energy,
        "load_reduction": load_reduction,
        "cwft_array": cwft_array,
        "pcaf_array": pcaf_array,
        "cap_value": 140.0,
        "trans_value": 25.0,
        "dist_value": 35.0,
        "carbon_tax": 20.0,
        "discount_rate": 7.0,
        "customer_discount_rate": 7.0,
        "degradation_rate": 0.0,
        "annual_lost_revenue_yr1": 5000.0,
        "retail_escalation_rate": 2.0,
        "capacity_escalation_rate": 1.0,
        "interpolated_carbon_emissions": interpolated_carbon,
    }


class TestEscalationScenarioConfig:
    """Validate scenario configurations, rates, and benchmark citations."""

    def test_scenario_names_and_structure(self):
        expected_scenarios = [
            ESCALATION_SCENARIO_BASE,
            ESCALATION_SCENARIO_HIGH,
            ESCALATION_SCENARIO_LOW,
            ESCALATION_SCENARIO_CUSTOM,
        ]
        for sc in expected_scenarios:
            assert sc in NON_CAMBIUM_ESCALATION_SCENARIOS
            data = NON_CAMBIUM_ESCALATION_SCENARIOS[sc]
            assert "description" in data
            assert "source" in data
            for cat_key in ["capacity_adder", "td_adder", "carbon_adder", "retail_adder"]:
                assert cat_key in data
                assert isinstance(data[cat_key], (int, float))

    def test_base_scenario_adders_are_zero(self):
        adders = get_escalation_scenario_adders(ESCALATION_SCENARIO_BASE)
        assert adders["capacity_adder"] == 0.0
        assert adders["td_adder"] == 0.0
        assert adders["carbon_adder"] == 0.0
        assert adders["retail_adder"] == 0.0

    def test_high_scenario_adders_are_positive(self):
        adders = get_escalation_scenario_adders(ESCALATION_SCENARIO_HIGH)
        assert adders["capacity_adder"] == 5.0
        assert adders["td_adder"] == 1.8
        assert adders["carbon_adder"] == 2.5
        assert adders["retail_adder"] == 1.5

    def test_low_scenario_adders_are_negative(self):
        adders = get_escalation_scenario_adders(ESCALATION_SCENARIO_LOW)
        assert adders["capacity_adder"] == -1.0
        assert adders["td_adder"] == -1.0
        assert adders["carbon_adder"] == -1.5
        assert adders["retail_adder"] == -1.0

    def test_unknown_scenario_fallback(self):
        adders = get_escalation_scenario_adders("NonExistentScenario")
        assert adders["capacity_adder"] == 0.0
        assert adders["td_adder"] == 0.0
        assert adders["carbon_adder"] == 0.0
        assert adders["retail_adder"] == 0.0


class TestSERCCapacityModelEscalationAdder:
    """Validate incremental escalation adder compounding on SERCCapacityModel."""

    def setup_method(self):
        self.model = SERCCapacityModel()

    def test_zero_adder_identical_to_default(self):
        df_default = self.model.get_projection(start_year=2026, end_year=2030, currency="real_2024")
        df_zero = self.model.get_projection(start_year=2026, end_year=2030, currency="real_2024", capacity_escalation_adder=0.0)
        pd.testing.assert_frame_equal(df_default, df_zero)

    def test_positive_adder_multiplicative_growth(self):
        adder = 1.5
        df_base = self.model.get_projection(start_year=2026, end_year=2030, currency="real_2024", capacity_escalation_adder=0.0)
        df_high = self.model.get_projection(start_year=2026, end_year=2030, currency="real_2024", capacity_escalation_adder=adder)

        # In year 1 (start_year=2026), adder factor is (1 + r)^0 = 1.0 -> exactly equal
        base_yr1 = df_base.loc[df_base["year"] == 2026, "gross_ecc_per_kw_yr"].values[0]
        high_yr1 = df_high.loc[df_high["year"] == 2026, "gross_ecc_per_kw_yr"].values[0]
        assert pytest.approx(base_yr1, abs=0.01) == high_yr1

        # In year 2 (2027), adder factor is (1 + 0.015)^1
        base_yr2 = df_base.loc[df_base["year"] == 2027, "gross_ecc_per_kw_yr"].values[0]
        high_yr2 = df_high.loc[df_high["year"] == 2027, "gross_ecc_per_kw_yr"].values[0]
        expected_yr2 = round(base_yr2 * (1.0 + adder / 100.0), 2)
        assert pytest.approx(expected_yr2, abs=0.05) == high_yr2

        # Final year strictly greater
        base_final = df_base.loc[df_base["year"] == 2030, "gross_ecc_per_kw_yr"].values[0]
        high_final = df_high.loc[df_high["year"] == 2030, "gross_ecc_per_kw_yr"].values[0]
        assert high_final > base_final

    def test_negative_adder_compounds_lower(self):
        adder = -1.0
        df_base = self.model.get_projection(start_year=2026, end_year=2030, currency="real_2024", capacity_escalation_adder=0.0)
        df_low = self.model.get_projection(start_year=2026, end_year=2030, currency="real_2024", capacity_escalation_adder=adder)

        base_yr1 = df_base.loc[df_base["year"] == 2026, "gross_ecc_per_kw_yr"].values[0]
        low_yr1 = df_low.loc[df_low["year"] == 2026, "gross_ecc_per_kw_yr"].values[0]
        assert pytest.approx(base_yr1, abs=0.01) == low_yr1

        base_final = df_base.loc[df_base["year"] == 2030, "gross_ecc_per_kw_yr"].values[0]
        low_final = df_low.loc[df_low["year"] == 2030, "gross_ecc_per_kw_yr"].values[0]
        assert low_final < base_final


class TestCalculationsMultiYearEscalationAdders:
    """Validate calculate_multi_year_avoided_costs_and_npv integration with adders."""

    def test_base_growth_identical_to_zero_adders(self, mock_multi_year_inputs):
        res_zero = calculate_multi_year_avoided_costs_and_npv(**mock_multi_year_inputs)
        res_base = calculate_multi_year_avoided_costs_and_npv(
            **mock_multi_year_inputs,
            capacity_escalation_adder=0.0,
            td_escalation_adder=0.0,
            carbon_escalation_adder=0.0,
            retail_escalation_adder=0.0,
        )
        assert pytest.approx(res_zero["npv_grid_savings"], rel=1e-6) == res_base["npv_grid_savings"]
        assert pytest.approx(res_zero["npv_capacity_savings"], rel=1e-6) == res_base["npv_capacity_savings"]
        assert pytest.approx(res_zero["npv_retail_lost_revenue"], rel=1e-6) == res_base["npv_retail_lost_revenue"]

    def test_high_escalation_increases_grid_and_retail_streams(self, mock_multi_year_inputs):
        high_adders = get_escalation_scenario_adders(ESCALATION_SCENARIO_HIGH)
        res_base = calculate_multi_year_avoided_costs_and_npv(**mock_multi_year_inputs)
        res_high = calculate_multi_year_avoided_costs_and_npv(
            **mock_multi_year_inputs,
            capacity_escalation_adder=high_adders["capacity_adder"],
            td_escalation_adder=high_adders["td_adder"],
            carbon_escalation_adder=high_adders["carbon_adder"],
            retail_escalation_adder=high_adders["retail_adder"],
        )

        # Net present values must be strictly higher
        assert res_high["npv_capacity_savings"] > res_base["npv_capacity_savings"]
        assert res_high["npv_grid_savings"] > res_base["npv_grid_savings"]
        assert res_high["npv_retail_lost_revenue"] > res_base["npv_retail_lost_revenue"]

        # Unit costs in cash flow table
        cf_base = res_base["cash_flow_df"]
        cf_high = res_high["cash_flow_df"]

        assert cf_high["Unit_Capacity_Cost_per_kW_yr"].iloc[-1] > cf_base["Unit_Capacity_Cost_per_kW_yr"].iloc[-1]
        assert cf_high["Unit_Trans_Value_per_kW_yr"].iloc[-1] > cf_base["Unit_Trans_Value_per_kW_yr"].iloc[-1]
        assert cf_high["Unit_Dist_Value_per_kW_yr"].iloc[-1] > cf_base["Unit_Dist_Value_per_kW_yr"].iloc[-1]
        assert cf_high["Unit_Carbon_Tax_per_Ton"].iloc[-1] > cf_base["Unit_Carbon_Tax_per_Ton"].iloc[-1]

    def test_low_growth_decreases_grid_and_retail_streams(self, mock_multi_year_inputs):
        low_adders = get_escalation_scenario_adders(ESCALATION_SCENARIO_LOW)
        res_base = calculate_multi_year_avoided_costs_and_npv(**mock_multi_year_inputs)
        res_low = calculate_multi_year_avoided_costs_and_npv(
            **mock_multi_year_inputs,
            capacity_escalation_adder=low_adders["capacity_adder"],
            td_escalation_adder=low_adders["td_adder"],
            carbon_escalation_adder=low_adders["carbon_adder"],
            retail_escalation_adder=low_adders["retail_adder"],
        )

        assert res_low["npv_capacity_savings"] < res_base["npv_capacity_savings"]
        assert res_low["npv_grid_savings"] < res_base["npv_grid_savings"]
        assert res_low["npv_retail_lost_revenue"] < res_base["npv_retail_lost_revenue"]

    def test_decoupled_adders_isolation(self, mock_multi_year_inputs):
        """Modifying one adder must only impact its corresponding cash flow stream."""
        res_base = calculate_multi_year_avoided_costs_and_npv(**mock_multi_year_inputs)

        # Only modify carbon adder
        res_carbon_only = calculate_multi_year_avoided_costs_and_npv(
            **mock_multi_year_inputs,
            carbon_escalation_adder=3.0,
        )

        # Capacity, T&D, energy, and retail should be identical
        np.testing.assert_allclose(
            res_carbon_only["cash_flow_df"]["Gen_Capacity_Savings"],
            res_base["cash_flow_df"]["Gen_Capacity_Savings"],
        )
        np.testing.assert_allclose(
            res_carbon_only["cash_flow_df"]["Trans_Capacity_Savings"],
            res_base["cash_flow_df"]["Trans_Capacity_Savings"],
        )
        np.testing.assert_allclose(
            res_carbon_only["cash_flow_df"]["Dist_Capacity_Savings"],
            res_base["cash_flow_df"]["Dist_Capacity_Savings"],
        )
        np.testing.assert_allclose(
            res_carbon_only["cash_flow_df"]["Wholesale_Energy_Savings"],
            res_base["cash_flow_df"]["Wholesale_Energy_Savings"],
        )
        np.testing.assert_allclose(
            res_carbon_only["cash_flow_df"]["Lost_Retail_Revenue"],
            res_base["cash_flow_df"]["Lost_Retail_Revenue"],
        )

        # Emissions savings must strictly differ
        assert res_carbon_only["cash_flow_df"]["Emissions_Savings"].iloc[-1] > res_base["cash_flow_df"]["Emissions_Savings"].iloc[-1]

    def test_financially_consistent_method_supports_adders(self, mock_multi_year_inputs):
        """Validate financially_consistent method produces higher NPV under High Escalation."""
        high_adders = get_escalation_scenario_adders(ESCALATION_SCENARIO_HIGH)

        res_fc_base = calculate_multi_year_avoided_costs_and_npv(
            **mock_multi_year_inputs,
            financial_method="financially_consistent",
            valuation_basis="real",
        )
        res_fc_high = calculate_multi_year_avoided_costs_and_npv(
            **mock_multi_year_inputs,
            financial_method="financially_consistent",
            valuation_basis="real",
            capacity_escalation_adder=high_adders["capacity_adder"],
            td_escalation_adder=high_adders["td_adder"],
            carbon_escalation_adder=high_adders["carbon_adder"],
            retail_escalation_adder=high_adders["retail_adder"],
        )

        assert res_fc_high["npv_grid_savings"] > res_fc_base["npv_grid_savings"]
        assert res_fc_high["npv_capacity_savings"] > res_fc_base["npv_capacity_savings"]

    def test_high_capacity_low_energy_combination(self, mock_multi_year_inputs):
        """User requirement: high escalation for capacity (+1.5%) and low for energy (-1.0%)."""
        res_base = calculate_multi_year_avoided_costs_and_npv(**mock_multi_year_inputs)
        res_mixed = calculate_multi_year_avoided_costs_and_npv(
            **mock_multi_year_inputs,
            capacity_escalation_adder=1.5,
            energy_escalation_adder=-1.0,
        )
        # Capacity savings strictly greater than base
        assert res_mixed["npv_capacity_savings"] > res_base["npv_capacity_savings"]
        # Energy savings strictly less than base
        assert res_mixed["npv_energy_savings"] < res_base["npv_energy_savings"]



class TestAnnualEscalatedValuesTable:
    """Validate build_annual_escalated_values_table structure and math."""

    def test_table_shape_and_columns(self):
        df = build_annual_escalated_values_table(
            asset_life=15,
            start_year=2026,
            cap_value=141.22,
            trans_value=25.0,
            dist_value=35.0,
            carbon_tax=20.0,
        )
        assert len(df) == 15
        assert list(df["Calendar Year"]) == list(range(2026, 2041))
        expected_cols = [
            "Operating Year",
            "Calendar Year",
            "Capacity ECC ($/kW-yr)",
            "Transmission ($/kW-yr)",
            "Distribution ($/kW-yr)",
            "Carbon Tax ($/ton)",
            "Retail Rate Factor",
        ]
        for col in expected_cols:
            assert col in df.columns

    def test_capacity_cost_schedule_override(self):
        sched = {2026: 147.50, 2027: 150.75, 2028: 154.06}
        df = build_annual_escalated_values_table(
            asset_life=3,
            start_year=2026,
            cap_value=999.0,
            capacity_cost_schedule=sched,
        )
        assert df["Capacity ECC ($/kW-yr)"].iloc[0] == 147.50
        assert df["Capacity ECC ($/kW-yr)"].iloc[1] == 150.75
        assert df["Capacity ECC ($/kW-yr)"].iloc[2] == 154.06

    def test_high_escalation_adders_compound(self):
        high_adders = get_escalation_scenario_adders(ESCALATION_SCENARIO_HIGH)
        df_base = build_annual_escalated_values_table(
            asset_life=10,
            start_year=2026,
            cap_value=140.0,
            trans_value=25.0,
            dist_value=35.0,
            carbon_tax=20.0,
        )
        df_high = build_annual_escalated_values_table(
            asset_life=10,
            start_year=2026,
            cap_value=140.0,
            trans_value=25.0,
            dist_value=35.0,
            carbon_tax=20.0,
            capacity_escalation_adder=high_adders["capacity_adder"],
            td_escalation_adder=high_adders["td_adder"],
            carbon_escalation_adder=high_adders["carbon_adder"],
            retail_escalation_adder=high_adders["retail_adder"],
        )
        # Year 1 (t=0) values match
        assert df_high["Transmission ($/kW-yr)"].iloc[0] == df_base["Transmission ($/kW-yr)"].iloc[0]
        assert df_high["Carbon Tax ($/ton)"].iloc[0] == df_base["Carbon Tax ($/ton)"].iloc[0]

        # Year 10 values are strictly greater under high escalation
        assert df_high["Transmission ($/kW-yr)"].iloc[-1] > df_base["Transmission ($/kW-yr)"].iloc[-1]
        assert df_high["Distribution ($/kW-yr)"].iloc[-1] > df_base["Distribution ($/kW-yr)"].iloc[-1]
        assert df_high["Carbon Tax ($/ton)"].iloc[-1] > df_base["Carbon Tax ($/ton)"].iloc[-1]

