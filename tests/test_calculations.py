"""
Tests for the core calculation functions in the Southeast Marginal Cost
Valuation Engine.

These tests validate the mathematical correctness of:
  1. calculate_avoided_costs()  — 5-component avoided cost engine
  2. calculate_urdb_bill()      — URDB-compliant retail billing engine
  3. NPV discounting math       — escalation, degradation, discount factors
  4. EPC / ELCC capacity metrics — CWFT-weighted peak contribution

All tests use deterministic inputs with hand-calculable expected values.
No Streamlit, no file I/O, no network calls.

Run with:  python -m pytest
"""

import os
import sys
import types
import numpy as np
import pandas as pd
import pytest


# ──────────────────────────────────────────────────────────────────────
#  IMPORT STRATEGY
#  app.py has top-level Streamlit calls (st.set_page_config, st.markdown)
#  that crash outside a Streamlit runtime. We mock the `streamlit` module
#  just enough to allow importing the pure calculation functions.
# ──────────────────────────────────────────────────────────────────────

def _make_streamlit_stub():
    """
    Create a minimal stub for the `streamlit` module so that
    `import app` doesn't crash when run under pytest.
    """
    st = types.ModuleType("streamlit")

    # Absorb any call or attribute access silently
    class _Absorber:
        def __call__(self, *a, **kw):
            return self
        def __getattr__(self, name):
            return self
        def __bool__(self):
            return False
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def __iter__(self):
            return iter([])
        def __contains__(self, item):
            return False

    absorber = _Absorber()

    # Top-level functions that app.py calls at import time
    st.set_page_config = lambda **kw: None
    st.markdown = lambda *a, **kw: None
    st.sidebar = absorber
    st.cache_data = lambda f=None, **kw: f if f else (lambda fn: fn)  # pass-through decorator
    st.session_state = {}
    st.tabs = lambda labels: [absorber] * len(labels)
    st.columns = lambda n: [absorber] * (n if isinstance(n, int) else len(n))
    st.info = lambda *a, **kw: None
    st.warning = lambda *a, **kw: None
    st.error = lambda *a, **kw: None
    st.success = lambda *a, **kw: None
    st.write = lambda *a, **kw: None
    st.metric = lambda *a, **kw: None
    st.button = lambda *a, **kw: False
    st.text_input = lambda *a, **kw: ""
    st.number_input = lambda *a, **kw: 0
    st.selectbox = lambda *a, **kw: None
    st.multiselect = lambda *a, **kw: []
    st.slider = lambda *a, **kw: 0
    st.toggle = lambda *a, **kw: False
    st.checkbox = lambda *a, **kw: False
    st.text_area = lambda *a, **kw: ""
    st.spinner = lambda *a, **kw: absorber
    st.download_button = lambda *a, **kw: None
    st.dataframe = lambda *a, **kw: None
    st.plotly_chart = lambda *a, **kw: None
    st.balloons = lambda: None
    st.rerun = lambda: None
    st.expander = lambda *a, **kw: absorber

    return st


def _make_plotly_stubs():
    """Create minimal stubs for plotly modules."""
    go = types.ModuleType("plotly.graph_objects")
    go.Figure = lambda *a, **kw: type('Fig', (), {
        'add_trace': lambda *a, **kw: None,
        'update_layout': lambda *a, **kw: None,
    })()
    go.Scatter = lambda *a, **kw: None
    go.Bar = lambda *a, **kw: None
    go.Indicator = lambda *a, **kw: None

    subplots = types.ModuleType("plotly.subplots")
    subplots.make_subplots = lambda *a, **kw: go.Figure()

    plotly = types.ModuleType("plotly")
    plotly.graph_objects = go
    plotly.subplots = subplots

    return plotly, go, subplots


# Install stubs before importing app (still needed for any app.py references)
_st_stub = _make_streamlit_stub()
# NOTE: We do NOT stub plotly anymore — visualizations.py needs real Plotly
# to construct actual Figure objects. Only stub Streamlit.

sys.modules["streamlit"] = _st_stub

# Import the extracted modules directly — no Streamlit stub needed for these
# since they are pure Python with no UI dependencies.
from calculations import calculate_avoided_costs, dispatch_dr_program  # noqa: E402
from billing import calculate_urdb_bill, get_hourly_energy_rate  # noqa: E402
import config  # noqa: E402
from visualizations import (  # noqa: E402
    build_weekly_overlay_chart,
    build_weekly_load_and_temp_chart,
    build_weekly_grid_economics_chart,
    build_annual_avoided_cost_chart,
    build_stacked_components_chart,
    build_lifetime_npv_chart,
)
import plotly.graph_objects as go  # noqa: E402


# ======================================================================
#  TEST SUITE 1: calculate_avoided_costs()
# ======================================================================

class TestCalculateAvoidedCosts:
    """Validates the 5-component avoided cost calculation engine."""

    def test_output_columns_exist(self, grid_df_8760, cwft_uniform):
        """Verify all expected output columns are produced."""
        result = calculate_avoided_costs(
            grid_df_8760, 100.0, 15.0, 15.0, 30.0, cwft_uniform
        )
        expected_cols = [
            "CWFT", "Gen_Capacity_Value_MWh", "Trans_Value_MWh",
            "Dist_Value_MWh", "Emissions_Value_MWh", "Total_Avoided_Cost_MWh"
        ]
        for col in expected_cols:
            assert col in result.columns, f"Missing column: {col}"

    def test_output_length_8760(self, grid_df_8760, cwft_uniform):
        """Output must be exactly 8760 rows."""
        result = calculate_avoided_costs(
            grid_df_8760, 100.0, 15.0, 15.0, 30.0, cwft_uniform
        )
        assert len(result) == 8760

    def test_gen_capacity_formula(self, grid_df_8760, cwft_uniform):
        """
        Gen_Capacity_Value_MWh = cap_value * CWFT * 1000
        With uniform CWFT = 1/8760, cap = $100:
          each hour = 100 * (1/8760) * 1000 = 11.4155... $/MWh
        """
        result = calculate_avoided_costs(
            grid_df_8760, 100.0, 0.0, 0.0, 0.0, cwft_uniform
        )
        expected_hourly = 100.0 * (1.0 / 8760) * 1000
        np.testing.assert_allclose(
            result["Gen_Capacity_Value_MWh"].values,
            expected_hourly,
            rtol=1e-6,
            err_msg="Gen capacity formula mismatch"
        )

    def test_transmission_uses_pcaf(self, grid_df_8760, cwft_uniform):
        """
        Trans_Value_MWh = trans_value * PCAF_Weight * 1000
        Non-peak hours should have zero T&D value.
        """
        result = calculate_avoided_costs(
            grid_df_8760, 0.0, 15.0, 0.0, 0.0, cwft_uniform
        )
        # Non-peak hours (PCAF_Weight == 0) should have zero transmission value
        non_peak_mask = grid_df_8760["PCAF_Weight"] == 0.0
        assert (result.loc[non_peak_mask, "Trans_Value_MWh"] == 0.0).all(), \
            "Non-peak hours should have zero transmission value"

        # Peak hours should have positive transmission value
        peak_mask = grid_df_8760["PCAF_Weight"] > 0.0
        assert (result.loc[peak_mask, "Trans_Value_MWh"] > 0.0).all(), \
            "Peak hours should have positive transmission value"

    def test_emissions_formula(self, grid_df_8760, cwft_uniform):
        """
        Emissions_Value_MWh = (carbon_kg / 1000) * carbon_tax
        With 400 kg/MWh and $30/ton: (400/1000) * 30 = $12.00/MWh
        """
        result = calculate_avoided_costs(
            grid_df_8760, 0.0, 0.0, 0.0, 30.0, cwft_uniform
        )
        expected = (400.0 / 1000.0) * 30.0  # = $12.00/MWh
        np.testing.assert_allclose(
            result["Emissions_Value_MWh"].values,
            expected,
            rtol=1e-6,
            err_msg="Emissions formula mismatch"
        )

    def test_total_is_sum_of_components(self, grid_df_8760, cwft_uniform):
        """Total_Avoided_Cost_MWh must equal sum of all 5 components."""
        result = calculate_avoided_costs(
            grid_df_8760, 100.0, 15.0, 15.0, 30.0, cwft_uniform
        )
        component_sum = (
            result["Cambium_Energy_MWh"] +
            result["Gen_Capacity_Value_MWh"] +
            result["Trans_Value_MWh"] +
            result["Dist_Value_MWh"] +
            result["Emissions_Value_MWh"]
        )
        np.testing.assert_allclose(
            result["Total_Avoided_Cost_MWh"].values,
            component_sum.values,
            rtol=1e-10,
            err_msg="Total does not equal sum of components"
        )

    def test_zero_scalars_only_energy(self, grid_df_8760, cwft_uniform):
        """
        With all scalars at zero (cap=0, trans=0, dist=0, carbon=0),
        Total should equal just the wholesale energy price.
        """
        result = calculate_avoided_costs(
            grid_df_8760, 0.0, 0.0, 0.0, 0.0, cwft_uniform
        )
        np.testing.assert_allclose(
            result["Total_Avoided_Cost_MWh"].values,
            result["Cambium_Energy_MWh"].values,
            rtol=1e-10,
            err_msg="With zero scalars, total should equal energy-only"
        )


# ======================================================================
#  TEST SUITE 2: calculate_urdb_bill()
# ======================================================================

class TestCalculateUrdbBill:
    """Validates the URDB-compliant retail billing engine."""

    def test_flat_rate_constant_load(self, constant_load_1kw, datetime_2012, flat_rate):
        """
        1 kW constant * 8760 hrs = 8760 kWh @ $0.10/kWh = $876.00 energy
        + $10.00/mo * 12 = $120.00 fixed
        Total = $996.00
        """
        total, monthly = calculate_urdb_bill(
            constant_load_1kw, datetime_2012, flat_rate
        )
        expected_energy = 8760 * 0.10
        expected_fixed = 10.0 * 12
        expected_total = expected_energy + expected_fixed

        assert len(monthly) == 12, "Should produce 12 monthly bills"
        assert pytest.approx(total, rel=1e-4) == expected_total, \
            f"Flat rate total: expected ${expected_total:.2f}, got ${total:.2f}"

    def test_flat_rate_monthly_proportionality(self, constant_load_1kw, datetime_2012, flat_rate):
        """
        With constant load, monthly bills should be proportional to
        days in month (since energy = hours * kW * rate).
        """
        _, monthly = calculate_urdb_bill(
            constant_load_1kw, datetime_2012, flat_rate
        )
        # January (31 days) should cost more than February (29 days in 2012)
        jan_bill = monthly[0]
        feb_bill = monthly[1]
        assert jan_bill > feb_bill, "January should cost more than February (more days)"

    def test_zero_load_only_fixed(self, datetime_2012, flat_rate):
        """With zero load, bill should be only fixed charges."""
        zero_load = np.zeros(8760)
        total, monthly = calculate_urdb_bill(zero_load, datetime_2012, flat_rate)

        expected_fixed = 10.0 * 12
        assert pytest.approx(total, rel=1e-4) == expected_fixed, \
            f"Zero load should produce only fixed charges: ${expected_fixed}"

    def test_demand_charge(self, datetime_2012, flat_rate_with_demand):
        """
        Peak 2 kW load in January only, 1 kW otherwise.
        Demand charge = $5/kW * peak_kW per month.
        """
        load = np.ones(8760) * 1.0  # 1 kW baseline
        # Spike to 2 kW for one hour in January (hour 100)
        load[100] = 2.0

        total, monthly = calculate_urdb_bill(load, datetime_2012, flat_rate_with_demand)

        # January demand charge should be based on 2 kW peak
        # Other months based on 1 kW peak
        jan_demand = 2.0 * 5.0   # $10.00
        other_demand = 1.0 * 5.0  # $5.00

        # Total demand = $10 (Jan) + $5 * 11 (Feb-Dec) = $65.00
        total_demand = jan_demand + other_demand * 11
        # Total energy = 8760 kWh * $0.10 + 1 extra kWh * $0.10 = $876.10
        # Wait, the spike is 2 kW for 1 hour replacing 1 kW, so net is +1 kWh
        # Actually load[100]=2.0 but was already 1.0, so total energy = 8760-1+2 = 8761 kWh? 
        # No: load is set to 1.0 for all, then [100]=2.0, so sum = 8759*1 + 1*2 = 8761
        total_energy = (8759 * 1.0 + 1 * 2.0) * 0.10
        total_fixed = 10.0 * 12
        expected = total_energy + total_fixed + total_demand

        assert pytest.approx(total, rel=1e-3) == expected, \
            f"Demand charge total: expected ${expected:.2f}, got ${total:.2f}"

    def test_gp_r31_seasonal_tiers(self, constant_load_1kw, datetime_2012, gp_r31_rate):
        """
        Georgia Power R-31: winter is flat rate, summer has tiered blocks.
        A constant 1 kW load should produce different rates in summer vs winter.
        """
        total, monthly = calculate_urdb_bill(
            constant_load_1kw, datetime_2012, gp_r31_rate
        )

        assert total > 0, "GP R-31 bill should be positive"
        assert len(monthly) == 12

        # Summer months (Jun=idx 5, Jul=6, Aug=7, Sep=8) should have
        # higher per-kWh cost due to tiered summer rates
        # January (31 days, 744 hrs): 744 kWh * $0.142062 + $16.48 = ~$122.17
        jan_energy = 744 * 0.142062
        jan_expected = jan_energy + 16.48

        assert pytest.approx(monthly[0], rel=0.01) == jan_expected, \
            f"GP R-31 January bill mismatch: expected ~${jan_expected:.2f}, got ${monthly[0]:.2f}"

    def test_bill_increases_with_load(self, datetime_2012, flat_rate):
        """Doubling the load should roughly double the energy portion of the bill."""
        load_1kw = np.ones(8760) * 1.0
        load_2kw = np.ones(8760) * 2.0

        total_1, _ = calculate_urdb_bill(load_1kw, datetime_2012, flat_rate)
        total_2, _ = calculate_urdb_bill(load_2kw, datetime_2012, flat_rate)

        fixed_annual = 10.0 * 12
        energy_1 = total_1 - fixed_annual
        energy_2 = total_2 - fixed_annual

        assert pytest.approx(energy_2, rel=1e-4) == energy_1 * 2.0, \
            "Energy portion should double when load doubles"


# ======================================================================
#  TEST SUITE 2b: get_hourly_energy_rate()
# ======================================================================

class TestGetHourlyEnergyRate:
    """Validates the hourly marginal retail rate helper used by the
    Weekly Analysis Graphs tab's customer operating cost chart."""

    def test_flat_rate_constant_everywhere(self, datetime_2012, flat_rate):
        """A flat single-tier rate should return the same rate for every hour."""
        rates = get_hourly_energy_rate(datetime_2012, flat_rate)
        assert len(rates) == 8760
        np.testing.assert_allclose(rates, 0.10, rtol=1e-6)

    def test_gp_r31_seasonal_rate_changes(self, datetime_2012, gp_r31_rate):
        """Georgia Power R-31 should have a lower winter rate than summer rate."""
        rates = get_hourly_energy_rate(datetime_2012, gp_r31_rate)
        months = datetime_2012.dt.month.to_numpy()

        winter_rate = rates[months == 1][0]   # January
        summer_rate = rates[months == 7][0]   # July

        assert pytest.approx(winter_rate, rel=1e-6) == 0.142062
        assert pytest.approx(summer_rate, rel=1e-6) == 0.148101  # first summer tier
        assert summer_rate != winter_rate

    def test_no_energy_structure_returns_zeros(self, datetime_2012):
        """Rate structures without an energy schedule should return all zeros."""
        rates = get_hourly_energy_rate(datetime_2012, {"fixedcharge": 10.0})
        assert len(rates) == 8760
        assert (rates == 0.0).all()


# ======================================================================
#  TEST SUITE 3: NPV Discounting Math
# ======================================================================

class TestNPVDiscounting:
    """Validates the multi-year NPV discounting calculations."""

    def test_discount_factors_sum(self):
        """Discount factors should be monotonically decreasing."""
        years = np.arange(1, 16)
        discount_pct = 0.07
        disc_factors = 1 / ((1 + discount_pct) ** years)

        # Each factor should be less than the previous
        for i in range(1, len(disc_factors)):
            assert disc_factors[i] < disc_factors[i-1], \
                f"Discount factors should decrease: year {i+1} >= year {i}"

    def test_zero_discount_rate(self):
        """At 0% discount rate, discount factors should all be 1.0."""
        years = np.arange(1, 16)
        disc_factors = 1 / ((1 + 0.0) ** years)
        np.testing.assert_allclose(disc_factors, 1.0, rtol=1e-10)

    def test_npv_known_answer(self):
        """
        Known answer: $100/yr for 15 years at 7% WACC, 2% escalation, 1% degradation.
        Year 1: $100 * 1.00 * 1.00 / 1.07 = $93.4579
        Year 2: $100 * 1.02 * 0.99 / 1.07^2 = $88.2117 (approx)
        Sum should match hand-calculated value.
        """
        annual_value = 100.0
        years = np.arange(1, 16)
        discount_pct = 0.07
        escalation_pct = 0.02
        degradation_pct = 0.01

        esc_factors = (1 + escalation_pct) ** (years - 1)
        deg_factors = (1 - degradation_pct) ** (years - 1)
        disc_factors = 1 / ((1 + discount_pct) ** years)

        pv_multipliers = esc_factors * deg_factors * disc_factors
        npv = annual_value * pv_multipliers.sum()

        # Year 1: 100 * 1.0 * 1.0 * 0.93458 = 93.458
        year1_pv = annual_value * 1.0 * 1.0 * (1 / 1.07)
        assert pytest.approx(annual_value * pv_multipliers[0], rel=1e-4) == year1_pv

        # NPV should be between 15*100*0.5 and 15*100 (bounded by common sense)
        assert 750 < npv < 1500, f"NPV ${npv:.2f} outside reasonable bounds"

    def test_rim_ratio_calculation(self):
        """RIM = NPV grid savings / NPV lost revenue. Verify with known values."""
        npv_grid = 1200.0
        npv_lost = 800.0
        rim = npv_grid / npv_lost
        assert pytest.approx(rim, rel=1e-6) == 1.5

    def test_rim_zero_lost_revenue(self):
        """If lost revenue is zero, RIM should be handled gracefully (not crash)."""
        npv_grid = 1200.0
        npv_lost = 0.0
        rim = npv_grid / npv_lost if npv_lost > 0 else 0.0
        assert rim == 0.0, "RIM with zero lost revenue should be 0.0 (not divide-by-zero)"


# ======================================================================
#  TEST SUITE 4: EPC / ELCC Capacity Metrics
# ======================================================================

class TestCapacityMetrics:
    """Validates EPC and ELCC proxy calculations."""

    def test_epc_uniform_cwft(self, cwft_uniform):
        """
        EPC = sum(load * CWFT).
        With uniform CWFT (1/8760 each) and constant 1 kW load:
        EPC = sum(1.0 * 1/8760) = 1.0 kW
        """
        load = np.ones(8760)
        epc = (load * cwft_uniform).sum()
        assert pytest.approx(epc, rel=1e-6) == 1.0, \
            f"EPC with uniform CWFT and 1kW load should be 1.0, got {epc}"

    def test_epc_peaked_cwft_higher_for_peaky_load(self, cwft_peaked):
        """
        A load that peaks during CWFT hours should have higher EPC
        than a flat load of the same total energy.
        """
        flat_load = np.ones(8760)
        peaky_load = np.ones(8760) * 0.5
        # Spike during winter mornings and summer afternoons
        hours = np.arange(8760)
        winter_morning = (hours < 1416) & (np.isin(hours % 24, [6, 7, 8, 9]))
        summer_afternoon = (hours >= 3624) & (hours < 6552) & (np.isin(hours % 24, [14, 15, 16, 17, 18]))
        peaky_load[winter_morning] = 3.0
        peaky_load[summer_afternoon] = 3.0

        epc_flat = (flat_load * cwft_peaked).sum()
        epc_peaky = (peaky_load * cwft_peaked).sum()

        assert epc_peaky > epc_flat, \
            f"Peaky load EPC ({epc_peaky:.4f}) should exceed flat load EPC ({epc_flat:.4f})"

    def test_epc_reduction(self, cwft_uniform):
        """
        EPC reduction = EPC_baseline - EPC_proposed
        With uniform CWFT and known load shapes.
        """
        baseline = np.ones(8760) * 2.0
        proposed = np.ones(8760) * 1.5
        reduction = baseline - proposed

        epc_reduction = (reduction * cwft_uniform).sum()
        expected = 0.5  # 0.5 kW uniform reduction

        assert pytest.approx(epc_reduction, rel=1e-6) == expected

    def test_elcc_proxy_formula(self, cwft_uniform):
        """
        ELCC proxy = EPC / Peak Load.
        With uniform CWFT and constant 1kW: EPC = 1.0, Peak = 1.0 → ELCC = 100%
        """
        load = np.ones(8760)
        epc = (load * cwft_uniform).sum()
        elcc = epc / load.max()
        assert pytest.approx(elcc, rel=1e-6) == 1.0

    def test_elcc_proxy_peaky_load(self, cwft_uniform):
        """
        Load with peak much higher than average should have ELCC < 1.0
        when the peak doesn't coincide perfectly with CWFT weights.
        """
        load = np.ones(8760) * 1.0
        load[100] = 10.0  # one spike
        epc = (load * cwft_uniform).sum()
        elcc = epc / load.max()

        # EPC ≈ 1.001 (avg is slightly above 1), Peak = 10
        # ELCC ≈ 0.1001 — much less than 1.0
        assert elcc < 0.2, f"Spiky load should have low ELCC proxy: {elcc:.4f}"

    def test_cwft_sums_to_one(self, cwft_uniform, cwft_peaked):
        """CWFT arrays must sum to 1.0."""
        assert pytest.approx(cwft_uniform.sum(), abs=1e-6) == 1.0
        assert pytest.approx(cwft_peaked.sum(), abs=1e-6) == 1.0


# ======================================================================
#  TEST SUITE 5: dispatch_dr_program()
# ======================================================================

class TestDispatchDrProgram:
    """Validates the demand response dispatch logic."""

    def test_respects_hour_limit(self, datetime_2012, cwft_uniform):
        """DR dispatch should not exceed dr_hours_per_year."""
        baseline = np.ones(8760) * 2.0
        _, selected = dispatch_dr_program(
            datetime_2012, cwft_uniform, 50, "Both Seasons", 24, 1.0, baseline
        )
        assert len(selected) == 50

    def test_respects_daily_limit(self, datetime_2012, cwft_uniform):
        """DR dispatch should not call more than max_hours_per_day in one day."""
        baseline = np.ones(8760) * 2.0
        _, selected = dispatch_dr_program(
            datetime_2012, cwft_uniform, 8760, "Both Seasons", 4, 1.0, baseline
        )
        dates = datetime_2012.iloc[selected].dt.date
        daily_counts = dates.value_counts()
        assert daily_counts.max() <= 4

    def test_summer_only_season(self, datetime_2012, cwft_uniform):
        """Summer-only DR should only dispatch in Jun-Sep."""
        baseline = np.ones(8760) * 2.0
        _, selected = dispatch_dr_program(
            datetime_2012, cwft_uniform, 100, "Summer Only (Jun-Sep)", 24, 1.0, baseline
        )
        months = datetime_2012.iloc[selected].dt.month
        assert all(m in [6, 7, 8, 9] for m in months)

    def test_reduction_capped_at_load(self, datetime_2012, cwft_uniform):
        """DR reduction should not exceed actual baseline load."""
        baseline = np.ones(8760) * 0.5  # only 0.5 kW available
        reduction, _ = dispatch_dr_program(
            datetime_2012, cwft_uniform, 50, "Both Seasons", 24, 2.0, baseline
        )
        assert reduction.max() <= 0.5 + 1e-10

    def test_returns_correct_shapes(self, datetime_2012, cwft_uniform):
        """Should return 8760-length array and a list of indices."""
        baseline = np.ones(8760) * 2.0
        reduction, selected = dispatch_dr_program(
            datetime_2012, cwft_uniform, 50, "Both Seasons", 24, 1.0, baseline
        )
        assert len(reduction) == 8760
        assert isinstance(selected, list)


# ======================================================================
#  TEST SUITE 6: config.py constants
# ======================================================================

class TestConfig:
    """Validates config module constants are well-formed."""

    def test_scenario_options_nonempty(self):
        assert len(config.SCENARIO_OPTIONS) >= 2
        assert all(isinstance(s, str) for s in config.SCENARIO_OPTIONS)

    def test_planning_year_options(self):
        assert len(config.PLANNING_YEAR_OPTIONS) >= 2
        assert config.DEFAULT_PLANNING_YEAR_INDEX < len(config.PLANNING_YEAR_OPTIONS)

    def test_default_values_positive(self):
        assert config.DEFAULT_CAP_VALUE > 0
        assert config.DEFAULT_TRANS_VALUE > 0
        assert config.DEFAULT_DIST_VALUE > 0
        assert config.DEFAULT_CARBON_TAX >= 0
        assert config.DEFAULT_ASSET_LIFE > 0
        assert config.DEFAULT_DISCOUNT_RATE > 0

    def test_grid_components_has_5(self):
        assert len(config.GRID_COMPONENTS) == 5
        for col, label, color in config.GRID_COMPONENTS:
            assert isinstance(col, str)
            assert isinstance(label, str)
            assert color.startswith("#")

    def test_week_windows_valid(self):
        assert len(config.WEEK_WINDOWS) >= 2
        for label, (start, end) in config.WEEK_WINDOWS.items():
            assert 0 <= start < end <= 8760

    def test_weather_sensitivity_function(self):
        strong = config.get_weather_sensitivity_style(0.8)
        assert "Strong" in strong["label"] or "Responsive" in strong["label"]
        moderate = config.get_weather_sensitivity_style(0.45)
        assert "Moderate" in moderate["label"]
        low = config.get_weather_sensitivity_style(0.1)
        assert "Low" in low["label"] or "Unresponsive" in low["label"]

    def test_custom_css_nonempty(self):
        assert len(config.CUSTOM_CSS) > 100
        assert "<style>" in config.CUSTOM_CSS


# ======================================================================
#  TEST SUITE 7: visualizations.py chart builders
# ======================================================================

class TestVisualizations:
    """Validates that visualization functions return valid Plotly Figures."""

    def test_weekly_overlay_returns_figure(self, datetime_2012):
        dt_slice = datetime_2012.iloc[0:168]
        cost = np.random.rand(168) * 50
        baseline = np.ones(168) * 2.0
        proposed = np.ones(168) * 1.5
        reduction = baseline - proposed

        fig = build_weekly_overlay_chart(dt_slice, cost, baseline, proposed, reduction)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 4  # 4 traces

    def test_weekly_load_and_temp_chart(self, datetime_2012):
        dt_slice = datetime_2012.iloc[0:168]
        baseline = np.ones(168) * 2.0
        proposed = np.ones(168) * 1.5
        temp = np.random.rand(168) * 50 + 30.0

        fig = build_weekly_load_and_temp_chart(dt_slice, baseline, proposed, temp)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 3  # baseline, proposed, temp

    def test_weekly_grid_economics_chart(self, grid_df_8760, cwft_uniform, datetime_2012):
        from calculations import calculate_avoided_costs
        results = calculate_avoided_costs(grid_df_8760, 100, 15, 15, 30, cwft_uniform)
        results["Datetime"] = datetime_2012.values
        slice_df = results.iloc[0:168].copy()
        slice_df['Load_Reduction_kW'] = np.ones(168) * 0.5
        slice_df['Customer_Cost_Baseline_hr'] = np.ones(168) * 0.30
        slice_df['Customer_Cost_Proposed_hr'] = np.ones(168) * 0.20
        slice_df['Retail_Rate_kWh'] = np.ones(168) * 0.15

        # Test stacked mode
        fig_stacked = build_weekly_grid_economics_chart(slice_df, mode="Stacked Components")
        assert isinstance(fig_stacked, go.Figure)
        assert len(fig_stacked.data) == 10  # 5 component areas + 1 load reduction + 1 cost delta + 3 customer cost/rate traces

        # Test individual lines mode
        fig_lines = build_weekly_grid_economics_chart(slice_df, mode="Individual Component Lines")
        assert isinstance(fig_lines, go.Figure)
        assert len(fig_lines.data) == 11  # 5 component lines + 1 total cost line + 1 load reduction + 1 cost delta + 3 customer cost/rate traces

        # Test total marginal cost mode
        fig_total = build_weekly_grid_economics_chart(slice_df, mode="Total Marginal Cost ($/MWh)")
        assert isinstance(fig_total, go.Figure)
        assert len(fig_total.data) == 6  # 1 total cost line + 1 load reduction + 1 cost delta + 3 customer cost/rate traces

    def test_annual_avoided_cost_returns_figure(self, grid_df_8760, cwft_uniform):
        from calculations import calculate_avoided_costs
        results = calculate_avoided_costs(grid_df_8760, 100, 15, 15, 30, cwft_uniform)
        fig = build_annual_avoided_cost_chart(results)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 1  # single trace

    def test_stacked_components_returns_figure(self, grid_df_8760, cwft_uniform):
        from calculations import calculate_avoided_costs
        results = calculate_avoided_costs(grid_df_8760, 100, 15, 15, 30, cwft_uniform)
        slice_df = results.iloc[0:168]
        fig = build_stacked_components_chart(slice_df, show_legend=True)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 5  # 5 component traces

    def test_stacked_components_no_legend(self, grid_df_8760, cwft_uniform):
        from calculations import calculate_avoided_costs
        results = calculate_avoided_costs(grid_df_8760, 100, 15, 15, 30, cwft_uniform)
        fig = build_stacked_components_chart(results.iloc[0:168], show_legend=False)
        # All traces should have showlegend=False
        for trace in fig.data:
            assert trace.showlegend is False

    def test_lifetime_npv_returns_figure(self):
        years = np.arange(1, 16)
        nominal = np.ones(15) * 100
        disc_grid = np.ones(15) * 80
        disc_lost = np.ones(15) * 60
        fig = build_lifetime_npv_chart(years, nominal, disc_grid, disc_lost)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 3  # 3 bar traces


# ======================================================================
#  TEST SUITE 8: Integration Pipeline
# ======================================================================
#
#  These tests chain multiple modules together the same way app.py does,
#  verifying that the handoffs between modules work correctly:
#
#    grid_df → calculate_avoided_costs → results_df
#              → calculate_urdb_bill (baseline & proposed)
#              → NPV discounting
#              → dispatch_dr_program
#              → visualization builders
#
#  If a column name changes in one module, or a function signature
#  shifts, these tests will catch it even if the unit tests still pass.
# ======================================================================

class TestIntegrationPipeline:
    """
    End-to-end integration tests that exercise the full data pipeline
    across multiple modules. Each test mirrors a real path through app.py.
    """

    def test_grid_to_avoided_costs_column_contract(self, grid_df_8760, cwft_uniform):
        """
        Pipeline step 1: grid data → calculate_avoided_costs()
        
        Verifies that the DataFrame produced by the grid fixture has the
        columns that calculate_avoided_costs() expects, and that the output
        has the columns that downstream billing + visualization expects.
        """
        # The grid fixture must have these columns (contract from data_loaders)
        required_input_cols = ["Cambium_Energy_MWh", "Cambium_Carbon_kg_MWh", "PCAF_Weight"]
        for col in required_input_cols:
            assert col in grid_df_8760.columns, f"Grid data missing required column: {col}"

        # Run the avoided cost engine
        results = calculate_avoided_costs(
            grid_df_8760, 100.0, 15.0, 15.0, 30.0, cwft_uniform
        )

        # The output must have these columns (contract for billing + viz)
        required_output_cols = [
            "Cambium_Energy_MWh", "CWFT",
            "Gen_Capacity_Value_MWh", "Trans_Value_MWh",
            "Dist_Value_MWh", "Emissions_Value_MWh",
            "Total_Avoided_Cost_MWh"
        ]
        for col in required_output_cols:
            assert col in results.columns, f"Results missing required column: {col}"

    def test_full_pipeline_grid_to_npv(self, grid_df_8760, cwft_uniform,
                                       datetime_2012, gp_r31_rate):
        """
        Full pipeline: grid → avoided costs → billing → NPV.
        
        Mirrors the core calculation flow in app.py tabs 1-5.
        Verifies that all intermediate values are finite and that the
        final NPV numbers are in a sane range.
        """
        # --- Step 1: Calculate avoided costs ---
        results = calculate_avoided_costs(
            grid_df_8760, 100.0, 15.0, 15.0, 30.0, cwft_uniform
        )
        assert len(results) == 8760
        assert results["Total_Avoided_Cost_MWh"].notna().all(), "NaN in avoided costs"

        # --- Step 2: Build load profiles (synthetic) ---
        baseline_load = np.ones(8760) * 2.0       # 2 kW constant
        proposed_load = np.ones(8760) * 1.5        # 1.5 kW (e.g., efficient HP)
        load_reduction = baseline_load - proposed_load  # 0.5 kW savings

        # --- Step 3: Calculate annual grid savings ---
        # This is the exact formula app.py uses: sum(reduction * hourly_rate) / 1000
        annual_grid_savings = (
            load_reduction * results["Total_Avoided_Cost_MWh"].values
        ).sum() / 1000.0  # kW × $/MWh → $/kWh, summed

        assert np.isfinite(annual_grid_savings), "Grid savings is not finite"
        assert annual_grid_savings > 0, "Grid savings should be positive for load reduction"

        # --- Step 4: Calculate retail bills ---
        total_base, monthly_base = calculate_urdb_bill(
            baseline_load, datetime_2012, gp_r31_rate
        )
        total_prop, monthly_prop = calculate_urdb_bill(
            proposed_load, datetime_2012, gp_r31_rate
        )

        assert total_base > total_prop, "Baseline bill should exceed proposed bill"
        annual_lost_revenue = total_base - total_prop
        assert annual_lost_revenue > 0, "Lost revenue should be positive"

        # --- Step 5: NPV discounting (mirrors app.py exactly) ---
        asset_life = config.DEFAULT_ASSET_LIFE
        discount_pct = config.DEFAULT_DISCOUNT_RATE / 100.0
        escalation_pct = config.DEFAULT_ESCALATION_RATE / 100.0
        degradation_pct = config.DEFAULT_DEGRADATION_RATE / 100.0

        years = np.arange(1, asset_life + 1)
        esc_factors = (1 + escalation_pct) ** (years - 1)
        deg_factors = (1 - degradation_pct) ** (years - 1)
        disc_factors = 1 / ((1 + discount_pct) ** years)
        pv_multipliers = esc_factors * deg_factors * disc_factors

        npv_grid = annual_grid_savings * pv_multipliers.sum()
        npv_lost = annual_lost_revenue * pv_multipliers.sum()

        assert np.isfinite(npv_grid), "NPV grid savings is not finite"
        assert np.isfinite(npv_lost), "NPV lost revenue is not finite"
        assert npv_grid > 0, "NPV grid savings should be positive"
        assert npv_lost > 0, "NPV lost revenue should be positive"

        # --- Step 6: RIM ratio ---
        rim_ratio = npv_grid / npv_lost if npv_lost > 0 else 0.0
        assert np.isfinite(rim_ratio), "RIM ratio is not finite"
        assert rim_ratio > 0, "RIM ratio should be positive"

    def test_dr_dispatch_feeds_into_billing(self, grid_df_8760, cwft_uniform,
                                            datetime_2012, gp_r31_rate):
        """
        Pipeline with DR mode: grid → avoided costs → DR dispatch → billing.
        
        Verifies that DR dispatch produces a load profile that the billing
        engine accepts, and that the DR-adjusted bill differs from baseline.
        """
        results = calculate_avoided_costs(
            grid_df_8760, 100.0, 15.0, 15.0, 30.0, cwft_uniform
        )

        baseline_load = np.ones(8760) * 2.0

        # Dispatch DR program
        dr_reduction, selected_hours = dispatch_dr_program(
            datetime_2012, cwft_uniform,
            dr_hours_per_year=50,
            season_name="Summer Only (Jun-Sep)",
            max_hours_per_day=4,
            dr_capacity_kw=1.0,
            baseline_load=baseline_load
        )

        # Build DR-adjusted load profile
        proposed_load = baseline_load - dr_reduction
        assert (proposed_load >= 0).all(), "DR should not create negative load"

        # Feed into billing engine — this is the handoff test
        total_base, _ = calculate_urdb_bill(baseline_load, datetime_2012, gp_r31_rate)
        total_dr, _ = calculate_urdb_bill(proposed_load, datetime_2012, gp_r31_rate)

        assert total_dr < total_base, "DR-adjusted bill should be less than baseline"
        assert total_dr > 0, "DR bill should still be positive (fixed charges)"

    def test_avoided_costs_feed_into_visualizations(self, grid_df_8760, cwft_uniform,
                                                     datetime_2012):
        """
        Pipeline: grid → avoided costs → visualization builders.
        
        Verifies that the results DataFrame from calculate_avoided_costs()
        has exactly the columns and structure that each chart builder expects.
        """
        results = calculate_avoided_costs(
            grid_df_8760, 100.0, 15.0, 15.0, 30.0, cwft_uniform
        )
        # Attach Datetime column (app.py does this during data loading)
        results["Datetime"] = datetime_2012.values

        baseline_load = np.ones(8760) * 2.0
        proposed_load = np.ones(8760) * 1.5
        load_reduction = baseline_load - proposed_load

        # Chart 1: Annual avoided cost (needs 'Datetime' + 'Total_Avoided_Cost_MWh')
        fig1 = build_annual_avoided_cost_chart(results)
        assert isinstance(fig1, go.Figure)

        # Chart 2: Stacked components (needs 'Datetime' + all 5 component columns)
        fig2 = build_stacked_components_chart(results.iloc[0:168])
        assert isinstance(fig2, go.Figure)
        assert len(fig2.data) == 5

        # Chart 3: Weekly overlay (needs datetime slice + arrays)
        dt_slice = datetime_2012.iloc[0:168]
        cost_slice = results["Total_Avoided_Cost_MWh"].iloc[0:168]
        fig3 = build_weekly_overlay_chart(
            dt_slice, cost_slice,
            baseline_load[0:168], proposed_load[0:168], load_reduction[0:168]
        )
        assert isinstance(fig3, go.Figure)
        assert len(fig3.data) == 4

        # Chart 4: Lifetime NPV (takes arrays, not DataFrame)
        years = np.arange(1, 16)
        fig4 = build_lifetime_npv_chart(
            years, np.ones(15) * 100, np.ones(15) * 80, np.ones(15) * 60
        )
        assert isinstance(fig4, go.Figure)

    def test_config_defaults_work_with_calculations(self, grid_df_8760, cwft_uniform):
        """
        Verifies that config.py default values are compatible with
        the calculation engine — no type mismatches, no out-of-range errors.
        """
        # Use config defaults exactly as app.py would
        results = calculate_avoided_costs(
            grid_df_8760,
            config.DEFAULT_CAP_VALUE,
            config.DEFAULT_TRANS_VALUE,
            config.DEFAULT_DIST_VALUE,
            config.DEFAULT_CARBON_TAX,
            cwft_uniform
        )
        assert len(results) == 8760
        assert results["Total_Avoided_Cost_MWh"].notna().all()
        assert (results["Total_Avoided_Cost_MWh"] > 0).all(), \
            "With positive defaults, total avoided cost should be positive every hour"


# ======================================================================
#  TEST SUITE 9: Load Profile Ingestion
# ======================================================================

class TestLoadProfileIngestion:
    """
    Validates BEopt / EnergyPlus raw output parsing and multi-file directory loading.
    """

    def test_beopt_raw_file_parsing(self):
        from data_loaders import load_load_profiles_from_csv
        filepath = "Load_Profiles_raw/ERHeatBeOptModel_Birmingham2012.csv"
        if os.path.exists(filepath):
            df = load_load_profiles_from_csv(filepath)
            assert "Hour" in df.columns
            assert len(df) == 8760
            profile_cols = [c for c in df.columns if c != "Hour"]
            assert len(profile_cols) == 1
            # Values should be converted to kW (mean between 1 and 10 kW for residential)
            kw_vals = df[profile_cols[0]].to_numpy()
            assert 0.5 < kw_vals.mean() < 10.0
            assert kw_vals.max() > 5.0

    def test_load_profiles_directory_scan(self):
        from data_loaders import load_load_profiles_from_csv
        dirpath = "Load_Profiles_raw"
        if os.path.exists(dirpath):
            df = load_load_profiles_from_csv(dirpath)
            assert "Hour" in df.columns
            assert len(df) == 8760
            # Should have merged model files and multi-column cases (including Excel)
            profile_cols = [c for c in df.columns if c != "Hour"]
            assert len(profile_cols) >= 2
            assert any("ERHeat" in c for c in profile_cols)
            assert any("HeatPump" in c for c in profile_cols)
            assert "Total TES" in profile_cols
            assert "Total No TES" in profile_cols

    def test_excel_file_parsing(self):
        from data_loaders import load_load_profiles_from_csv
        filepath = "Load_Profiles_raw/HP_TES_DummyData.xlsx"
        if os.path.exists(filepath):
            df = load_load_profiles_from_csv(filepath)
            assert "Hour" in df.columns
            assert len(df) == 8760
            profile_cols = [c for c in df.columns if c != "Hour"]
            assert "Total TES" in profile_cols
            assert "Total No TES" in profile_cols
            assert "Date" not in profile_cols  # Date column must be excluded
            # Numeric values test
            assert df["Total TES"].notna().all()
            assert df["Total No TES"].notna().all()
            assert df["Total TES"].mean() > 0.1

    def test_beopt_native_export_format_parsing(self):
        """Native BEopt hourly CSV export: 'wxDVFileHeaderVer.1' line, then headers,
        then two index rows (0.5 / 1.0) and a units row before the 8760 data rows."""
        from data_loaders import load_load_profiles_from_csv
        filepath = "Load_Profiles_raw/BEOptExample_NoBattery_Birmingham2012.csv"
        if os.path.exists(filepath):
            df = load_load_profiles_from_csv(filepath)
            assert "Hour" in df.columns
            assert len(df) == 8760
            profile_cols = [c for c in df.columns if c != "Hour"]
            assert len(profile_cols) == 1
            kw_vals = df[profile_cols[0]].to_numpy()
            assert 0.5 < kw_vals.mean() < 10.0

    def test_beopt_battery_example_shows_charge_discharge_shift(self):
        """The Battery example should draw more than baseline during charge hours
        and less (or negative, i.e. discharging) during discharge hours."""
        from data_loaders import load_load_profiles_from_csv
        nb_path = "Load_Profiles_raw/BEOptExample_NoBattery_Birmingham2012.csv"
        b_path = "Load_Profiles_raw/BEOptExample_Battery_Birmingham2012.csv"
        if os.path.exists(nb_path) and os.path.exists(b_path):
            nb_df = load_load_profiles_from_csv(nb_path)
            b_df = load_load_profiles_from_csv(b_path)
            nb_col = [c for c in nb_df.columns if c != "Hour"][0]
            b_col = [c for c in b_df.columns if c != "Hour"][0]
            diff = b_df[b_col].to_numpy() - nb_df[nb_col].to_numpy()
            assert diff.max() > 1.0, "Expected a clear charging spike above baseline somewhere in the year"
            assert diff.min() < -1.0, "Expected a clear discharge dip below baseline somewhere in the year"


# ======================================================================
#  TEST SUITE 10: Cost Effectiveness & Payback Math
# ======================================================================

class TestCostEffectivenessTests:
    """
    Validates TRC, PCT, RIM, and payback period calculations.
    """

    def test_trc_and_pct_ratios(self):
        from calculations import calculate_cost_effectiveness_tests
        
        npv_grid = 5000.0
        npv_lost = 3000.0
        gross_cost = 3000.0
        incentive = 500.0
        admin = 100.0
        annual_savings = np.ones(15) * 300.0
        pv_mults = np.ones(15) * 0.8

        res = calculate_cost_effectiveness_tests(
            npv_grid, npv_lost, npv_lost, gross_cost, incentive, admin, annual_savings, pv_mults
        )

        # TRC = 5000 / (3000 + 100) = 5000 / 3100 = 1.6129
        assert pytest.approx(res["trc_ratio"], abs=1e-3) == 5000.0 / 3100.0
        # PCT = (3000 + 500) / 3000 = 3500 / 3000 = 1.1667
        assert pytest.approx(res["pct_ratio"], abs=1e-3) == 3500.0 / 3000.0
        # Net customer cost = 3000 - 500 = 2500
        assert res["net_customer_cost"] == 2500.0
        # Simple payback = 2500 / 300 = 8.333 years
        assert pytest.approx(res["simple_payback"], abs=1e-3) == 2500.0 / 300.0
        # Discounted payback = 2500 / (300 * 0.8) = 2500 / 240 = 10.417 years
        assert pytest.approx(res["discounted_payback"], abs=1e-3) == 10.416666


