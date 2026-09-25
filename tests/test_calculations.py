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
from calculations import calculate_avoided_costs, dispatch_dr_program, find_peak_week  # noqa: E402
from billing import calculate_urdb_bill, get_hourly_energy_rate  # noqa: E402
import config  # noqa: E402
from visualizations import (  # noqa: E402
    build_weekly_overlay_chart,
    build_weekly_load_and_temp_chart,
    build_weekly_grid_economics_chart,
    build_annual_avoided_cost_chart,
    build_stacked_components_chart,
    build_winter_summer_comparison_chart,
    build_lifetime_npv_chart,
    build_temp_power_cost_bubble_chart,
    build_cost_duration_chart,
    build_hour_month_heatmap,
    build_day_hour_heatmap,
    build_cumulative_cost_chart,
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


class TestFindPeakWeek:
    """Validates find_peak_week(), which replaced the old fixed-calendar-week
    assumption ('the peak week is always Jan 1-7 / Jul 15-21') with a search
    over the actual loaded data. See the BirminghamTES July 6 investigation,
    2026-09-24, where a real peak hour fell outside the old fixed window."""

    def test_finds_true_spike_outside_fixed_window(self, datetime_2012):
        """A single huge spike hour that falls outside the old hardcoded
        'Summer Peak Week (Jul 15-21)' window must still be captured."""
        n = 8760
        vals = np.random.default_rng(0).uniform(20, 40, n)
        # July 6 (hour index 4488-4511) -- outside the old fixed Jul 15-21
        # window (indices 4680-4848) -- gets a massive spike.
        vals[4495] = 5000.0
        window = find_peak_week(datetime_2012, vals, month_filter=[6, 7, 8, 9], mode="max")
        assert window is not None
        start, end = window
        assert start <= 4495 < end, "the window found should contain the actual spike hour"
        assert end - start == 168

    def test_window_stays_within_month_filter(self, datetime_2012):
        """The returned window must never spill into a month outside the filter."""
        n = 8760
        vals = np.random.default_rng(1).uniform(0, 1, n)
        window = find_peak_week(datetime_2012, vals, month_filter=[12, 1, 2], mode="max")
        assert window is not None
        start, end = window
        months_in_window = pd.to_datetime(datetime_2012.iloc[start:end]).dt.month
        assert set(months_in_window.unique()).issubset({12, 1, 2})

    def test_min_mode_finds_lowest_stress_window(self, datetime_2012):
        """A deliberately quiet week (day-of-year 100, hour 2400) with a sum
        far below every other candidate window should be the one found."""
        n = 8760
        vals = np.random.default_rng(2).uniform(50, 100, n)
        vals[2400:2568] = 1.0
        window = find_peak_week(datetime_2012, vals, month_filter=[3, 4, 5, 10, 11], mode="min")
        assert window == (2400, 2568)

    def test_returns_none_when_no_window_fits(self, datetime_2012):
        """An empty month filter can never contain a window, so this must
        return None rather than raising or silently returning a bad window."""
        n = 8760
        vals = np.ones(n)
        window = find_peak_week(datetime_2012, vals, month_filter=[], mode="max")
        assert window is None


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

    def test_scenario_descriptions_complete(self):
        assert hasattr(config, "SCENARIO_DESCRIPTIONS")
        for scen in config.SCENARIO_OPTIONS:
            assert scen in config.SCENARIO_DESCRIPTIONS
            assert len(config.SCENARIO_DESCRIPTIONS[scen]) > 20
        assert hasattr(config, "CAMBIUM_DOC_URL")
        assert config.CAMBIUM_DOC_URL.startswith("http")

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

    def test_financial_metric_card_html(self):
        # Positive case (green)
        html_pos = config.financial_metric_card_html(
            "Annual Operating Margin", "+$32.29/yr", "Positive Utility Return", is_positive=True
        )
        assert "#15803d" in html_pos
        assert "+$32.29/yr" in html_pos

        # Negative case (red)
        html_neg = config.financial_metric_card_html(
            "Annual Operating Margin", "-$125.50/yr", "Net Utility Cross-Subsidy", is_positive=False
        )
        assert "#b91c1c" in html_neg
        assert "-$125.50/yr" in html_neg

        # Neutral case (teal)
        html_neu = config.financial_metric_card_html(
            "Wholesale Grid Deferrals", "$685.33/yr", "5 Avoided Cost Streams", neutral=True
        )
        assert "#0D9488" in html_neu



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
        assert len(fig_stacked.data) == 14  # 5 component areas + 2 load-reduction (pos/neg) + 2 grid-value (pos/neg) + 2 lost-revenue (pos/neg) + baseline/proposed/rate lines

        # Test individual lines mode
        fig_lines = build_weekly_grid_economics_chart(slice_df, mode="Individual Component Lines")
        assert isinstance(fig_lines, go.Figure)
        assert len(fig_lines.data) == 15  # 5 component lines + 1 total cost line + 2 load-reduction (pos/neg) + 2 grid-value (pos/neg) + 2 lost-revenue (pos/neg) + baseline/proposed/rate lines

        # Test total marginal cost mode
        fig_total = build_weekly_grid_economics_chart(slice_df, mode="Total Marginal Cost ($/MWh)")
        assert isinstance(fig_total, go.Figure)
        assert len(fig_total.data) == 10  # 1 total cost line + 2 load-reduction (pos/neg) + 2 grid-value (pos/neg) + 2 lost-revenue (pos/neg) + baseline/proposed/rate lines

        # The positive (green) traces should carry the constant positive test
        # values; the negative (red) traces should be all-NaN since none of
        # the test data goes negative.
        reduction_pos_trace = next(t for t in fig_stacked.data if t.name == 'Reduces Demand (kW)')
        reduction_neg_trace = next(t for t in fig_stacked.data if t.name == 'Increases Demand (kW)')
        assert np.allclose(reduction_pos_trace.y, 0.5)
        assert np.all(np.isnan(np.array(reduction_neg_trace.y, dtype=float)))

        # Utility revenue effect = Proposed (0.20) - Baseline (0.30) = -0.10
        # constant: the utility collects less retail revenue every hour here.
        lost_revenue_trace = next(t for t in fig_stacked.data if t.name == 'Lost Retail Revenue ($/hr)')
        revenue_gain_trace = next(t for t in fig_stacked.data if t.name == 'Revenue Gain ($/hr)')
        assert np.allclose(lost_revenue_trace.y, -0.1)
        assert np.all(np.isnan(np.array(revenue_gain_trace.y, dtype=float)))

        # Baseline/Proposed customer cost lines should keep their own distinct
        # colors (purple/amber), separate from the green/red bar convention.
        baseline_line = next(t for t in fig_stacked.data if t.name == 'Customer Cost - Baseline ($/hr)')
        proposed_line = next(t for t in fig_stacked.data if t.name == 'Customer Cost - Proposed ($/hr)')
        assert baseline_line.line.color == config.COLORS["purple"]
        assert proposed_line.line.color == config.COLORS["amber"]

    def test_weekly_grid_economics_chart_signed_area_split(self, grid_df_8760, cwft_uniform, datetime_2012):
        """A technology (like a battery) that draws MORE than baseline some
        hours should land in the red 'Increases Demand' / 'Costs More'
        traces for exactly those hours, and in the green traces otherwise —
        this is the good/bad color coding requested for rows 2 and 3."""
        from calculations import calculate_avoided_costs
        results = calculate_avoided_costs(grid_df_8760, 100, 15, 15, 30, cwft_uniform)
        results["Datetime"] = datetime_2012.values
        slice_df = results.iloc[0:168].copy()

        reduction = np.ones(168) * 0.5
        reduction[10] = -2.0  # e.g. a battery charging that hour
        slice_df['Load_Reduction_kW'] = reduction
        slice_df['Customer_Cost_Baseline_hr'] = np.ones(168) * 0.30
        slice_df['Customer_Cost_Proposed_hr'] = np.ones(168) * 0.20
        slice_df['Retail_Rate_kWh'] = np.ones(168) * 0.15

        fig = build_weekly_grid_economics_chart(slice_df, mode="Total Marginal Cost ($/MWh)")

        reduction_pos = np.array(next(t for t in fig.data if t.name == 'Reduces Demand (kW)').y, dtype=float)
        reduction_neg = np.array(next(t for t in fig.data if t.name == 'Increases Demand (kW)').y, dtype=float)
        assert np.isnan(reduction_pos[10])
        assert reduction_neg[10] == -2.0
        assert reduction_pos[0] == 0.5
        assert np.isnan(reduction_neg[0])

        savings_pos = np.array(next(t for t in fig.data if t.name == 'Grid Value Created ($/hr)').y, dtype=float)
        savings_neg = np.array(next(t for t in fig.data if t.name == 'Grid Value Lost ($/hr)').y, dtype=float)
        # With positive avoided-cost scalars, the charging hour's negative
        # reduction must flow through to a negative ($/hr) value.
        assert np.isnan(savings_pos[10])
        assert savings_neg[10] < 0

    def test_weekly_grid_economics_chart_revenue_gain_hour_is_distinct_from_grid_value(
        self, grid_df_8760, cwft_uniform, datetime_2012
    ):
        """
        An hour where the customer's bill goes UP under Proposed (e.g. backup
        resistance heat kicking in) is a revenue GAIN for the utility, not a
        loss -- it should land in the green 'Revenue Gain' bucket, distinct
        from (and independently signed from) that same hour's grid value.
        """
        from calculations import calculate_avoided_costs
        results = calculate_avoided_costs(grid_df_8760, 100, 15, 15, 30, cwft_uniform)
        results["Datetime"] = datetime_2012.values
        slice_df = results.iloc[0:168].copy()

        slice_df['Load_Reduction_kW'] = np.ones(168) * 0.5  # grid value stays positive throughout
        baseline_cost = np.ones(168) * 0.30
        proposed_cost = np.ones(168) * 0.20
        proposed_cost[20] = 0.45  # hour 20: proposed costs MORE than baseline
        slice_df['Customer_Cost_Baseline_hr'] = baseline_cost
        slice_df['Customer_Cost_Proposed_hr'] = proposed_cost
        slice_df['Retail_Rate_kWh'] = np.ones(168) * 0.15

        fig = build_weekly_grid_economics_chart(slice_df, mode="Total Marginal Cost ($/MWh)")

        lost_revenue = np.array(next(t for t in fig.data if t.name == 'Lost Retail Revenue ($/hr)').y, dtype=float)
        revenue_gain = np.array(next(t for t in fig.data if t.name == 'Revenue Gain ($/hr)').y, dtype=float)
        grid_value = np.array(next(t for t in fig.data if t.name == 'Grid Value Created ($/hr)').y, dtype=float)

        # Hour 20: revenue gain of 0.15 (0.45 proposed - 0.30 baseline), not a loss.
        assert np.isnan(lost_revenue[20])
        assert revenue_gain[20] == pytest.approx(0.15)
        # Every other hour: a loss of -0.10, as in the baseline test case.
        assert lost_revenue[0] == pytest.approx(-0.10)
        assert np.isnan(revenue_gain[0])
        # Grid value is unaffected by the bill swing -- stays positive throughout,
        # confirming the two series are independent, not netted together.
        assert grid_value[20] > 0

    def test_annual_avoided_cost_returns_figure(self, grid_df_8760, cwft_uniform):
        from calculations import calculate_avoided_costs
        results = calculate_avoided_costs(grid_df_8760, 100, 15, 15, 30, cwft_uniform)
        fig = build_annual_avoided_cost_chart(results)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 1  # single trace
        assert fig.layout.yaxis.title.text == "Wholesale Avoided Cost ($/MWh)"

    def test_annual_avoided_cost_monthly_boxplot(self, grid_df_8760, cwft_uniform):
        from calculations import calculate_avoided_costs
        results = calculate_avoided_costs(grid_df_8760, 100, 15, 15, 30, cwft_uniform)
        fig = build_annual_avoided_cost_chart(results, mode="Monthly Box & Whisker")
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 1
        assert fig.data[0].type == "box"
        assert len(fig.data[0].y) == len(results)

    def test_annual_avoided_cost_boxplot_caps_yaxis_and_annotates_outliers(self, datetime_2012):
        """A year with a handful of extreme-price hours should get a capped,
        legible y-axis (not stretched to the max spike) plus a text
        annotation on whichever month(s) had hours above that cap."""
        n = 8760
        vals = np.random.default_rng(0).uniform(20, 50, n)
        vals[100] = 4000.0  # one huge January spike hour
        results = pd.DataFrame({
            'Datetime': datetime_2012.values,
            'Total_Avoided_Cost_MWh': vals
        })

        fig = build_annual_avoided_cost_chart(results, mode="Monthly Box & Whisker")

        y_ceiling = fig.layout.yaxis.range[1]
        assert y_ceiling < 4000.0, "y-axis should be capped well below the spike, not stretched to fit it"
        assert y_ceiling > 50.0, "y-axis should still comfortably cover the normal range"

        annotation_texts = " ".join(a.text for a in fig.layout.annotations)
        assert "1 hr" in annotation_texts
        assert "4,000" in annotation_texts or "4000" in annotation_texts

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

    def test_winter_summer_comparison_shares_one_legend(self, grid_df_8760, cwft_uniform):
        """The combined two-panel chart should carry all 10 traces (5
        components x 2 panels) but only the first panel's 5 should show in
        the legend, since the two panels share one legend across the top."""
        from calculations import calculate_avoided_costs
        results = calculate_avoided_costs(grid_df_8760, 100, 15, 15, 30, cwft_uniform)
        winter_slice = results.iloc[0:168]
        summer_slice = results.iloc[4680:4848]
        fig = build_winter_summer_comparison_chart(
            winter_slice, summer_slice, winter_label="Dec 6-12", summer_label="Jul 6-12"
        )
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 10
        legend_visible = [t for t in fig.data if t.showlegend]
        legend_hidden = [t for t in fig.data if t.showlegend is False]
        assert len(legend_visible) == 5
        assert len(legend_hidden) == 5

    def test_winter_summer_comparison_y_range_caps_both_panels(self, grid_df_8760, cwft_uniform):
        """Passing y_range should cap BOTH subplot y-axes (not just one),
        for the 'zoomed in' companion chart next to the full-scope one."""
        from calculations import calculate_avoided_costs
        results = calculate_avoided_costs(grid_df_8760, 100, 15, 15, 30, cwft_uniform)
        winter_slice = results.iloc[0:168]
        summer_slice = results.iloc[4680:4848]
        fig = build_winter_summer_comparison_chart(
            winter_slice, summer_slice, winter_label="Dec 6-12", summer_label="Jul 6-12",
            y_range=(0, 500)
        )
        assert list(fig.layout.yaxis.range) == [0, 500]
        assert list(fig.layout.yaxis2.range) == [0, 500]

    def test_cost_duration_chart_returns_figure(self):
        n = 744  # roughly a month's worth of hours
        rng = np.random.default_rng(0)
        x_vals = np.arange(1, n + 1)
        baseline = rng.uniform(0, 50, n)
        proposed = baseline - rng.normal(2, 5, n)  # sometimes saves, sometimes costs more
        fig = build_cost_duration_chart(x_vals, baseline, proposed, x_title="Hour Rank", y_title="Cost ($/hr)")
        assert isinstance(fig, go.Figure)
        # 2 lines (Baseline, Proposed) in row 1 + 2 signed fill areas (Saves/Costs) in row 2
        assert len(fig.data) == 4
        assert all(t.type == "scatter" for t in fig.data)
        trace_names = [t.name for t in fig.data]
        assert trace_names == ["Baseline", "Proposed", "Saves Money", "Costs More"]

    def test_cost_duration_chart_change_matches_baseline_minus_proposed(self):
        x_vals = np.array([1, 2, 3])
        baseline = np.array([10.0, 20.0, 5.0])
        proposed = np.array([8.0, 25.0, 5.0])  # hour 1: saves 2, hour 2: costs 5 more, hour 3: no change
        fig = build_cost_duration_chart(x_vals, baseline, proposed, x_title="Hour Rank")
        saves_trace = next(t for t in fig.data if t.name == "Saves Money")
        costs_trace = next(t for t in fig.data if t.name == "Costs More")

        # Each trace is a series of isolated (x, 0) -> (x, value) -> break
        # stems, not one y-value per input hour, so index into stem triplets
        # by matching on x rather than position.
        def stem_value(trace, x):
            xs = np.asarray(trace.x)
            ys = np.asarray(trace.y, dtype=float)
            idx = np.where(xs == x)[0][0]  # first occurrence: the (x, 0) anchor
            return ys[idx + 1]  # the (x, value) point right after it

        assert stem_value(saves_trace, 1) == pytest.approx(2.0)
        assert 2 not in np.asarray(saves_trace.x)  # hour 2 costs more, not in the saves stems at all
        assert stem_value(costs_trace, 2) == pytest.approx(-5.0)
        assert stem_value(saves_trace, 3) == pytest.approx(0.0)  # zero change counts as "not negative" -> saves bucket

    def test_cost_duration_chart_y_range_caps_row1_axis(self):
        x_vals = np.array([1, 2, 3])
        baseline = np.array([100.0, 100.0, 5000.0])  # hour 3 is a huge outlier
        proposed = np.array([90.0, 95.0, 4800.0])
        fig = build_cost_duration_chart(x_vals, baseline, proposed, x_title="Hour Rank", y_range=(0, 500))
        assert list(fig.layout.yaxis.range) == [0, 500]
        # row 2 (Change) must stay uncapped -- only row 1 gets the cap
        assert fig.layout.yaxis2.range is None

    def test_cost_duration_chart_no_y_range_means_no_cap(self):
        x_vals = np.array([1, 2])
        baseline = np.array([100.0, 200.0])
        proposed = np.array([90.0, 190.0])
        fig = build_cost_duration_chart(x_vals, baseline, proposed, x_title="Hour Rank")
        assert fig.layout.yaxis.range is None

    def test_hour_month_heatmap_returns_figure(self, datetime_2012):
        n = 8760
        rng = np.random.default_rng(1)
        values = rng.normal(0, 5, n)
        fig = build_hour_month_heatmap(datetime_2012, values, title="Test Heatmap")
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 1
        assert fig.data[0].type == "heatmap"
        assert fig.data[0].z.shape == (24, 12)

    def test_hour_month_heatmap_colorbar_labels_good_and_bad(self, datetime_2012):
        n = 8760
        rng = np.random.default_rng(2)
        values = rng.normal(0, 5, n)
        fig = build_hour_month_heatmap(
            datetime_2012, values, title="Test Heatmap",
            good_label="Saves Money", bad_label="Costs More"
        )
        colorbar = fig.data[0].colorbar
        assert any("Saves Money" in t for t in colorbar.ticktext)
        assert any("Costs More" in t for t in colorbar.ticktext)

    def test_day_hour_heatmap_returns_figure(self, datetime_2012):
        jan_mask = datetime_2012.dt.month == 1
        jan_dt = datetime_2012[jan_mask]
        rng = np.random.default_rng(3)
        values = rng.normal(0, 5, jan_mask.sum())
        fig = build_day_hour_heatmap(jan_dt, values, title="Test Day x Hour Heatmap")
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 1
        assert fig.data[0].type == "heatmap"
        assert fig.data[0].z.shape == (24, 31)  # January has 31 days

    def test_day_hour_heatmap_colorbar_labels_good_and_bad(self, datetime_2012):
        jan_mask = datetime_2012.dt.month == 1
        jan_dt = datetime_2012[jan_mask]
        rng = np.random.default_rng(4)
        values = rng.normal(0, 5, jan_mask.sum())
        fig = build_day_hour_heatmap(
            jan_dt, values, title="Test Day x Hour Heatmap",
            good_label="Saves Money", bad_label="Costs More"
        )
        colorbar = fig.data[0].colorbar
        assert any("Saves Money" in t for t in colorbar.ticktext)
        assert any("Costs More" in t for t in colorbar.ticktext)

    def test_cumulative_cost_chart_returns_figure(self, datetime_2012):
        n = 8760
        rng = np.random.default_rng(5)
        baseline_grid = rng.uniform(0, 10, n)
        proposed_grid = baseline_grid - rng.uniform(0, 2, n)
        utility_net_hr = proposed_grid - baseline_grid
        baseline_cust = rng.uniform(0, 20, n)
        proposed_cust = baseline_cust - rng.uniform(0, 5, n)
        fig = build_cumulative_cost_chart(
            datetime_2012, utility_net_hr, baseline_cust, proposed_cust
        )
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 4  # Savings/Added Cost x Utility/Customer rows
        assert all(t.type == "scatter" for t in fig.data)
        trace_names = [t.name for t in fig.data]
        assert trace_names == [
            "Cumulative Savings", "Cumulative Added Cost",
            "Cumulative Savings", "Cumulative Added Cost",
        ]

    def test_cumulative_cost_chart_is_the_proposed_minus_baseline_running_total(self):
        years_as_hours = pd.Series(pd.date_range("2012-01-01", periods=4, freq="h"))
        # Proposed cheaper every hour in both perspectives -> cumulative diff sinks negative (savings).
        utility_net_hr = np.array([-4.0, -4.0, -4.0, -4.0])  # e.g. grid savings of $4/hr, no netting
        baseline_cust = np.array([20.0, 20.0, 20.0, 20.0])
        proposed_cust = np.array([15.0, 15.0, 15.0, 15.0])
        fig = build_cumulative_cost_chart(
            years_as_hours, utility_net_hr, baseline_cust, proposed_cust
        )
        # Row 1 (utility): Savings trace then Added Cost trace.
        savings_grid = fig.data[0]
        cost_grid = fig.data[1]
        assert list(savings_grid.y) == pytest.approx([-4.0, -8.0, -12.0, -16.0])
        assert all(np.isnan(v) for v in cost_grid.y)  # never positive here -> all-NaN, not shown
        # Row 2 (customer): Savings trace then Added Cost trace.
        savings_cust = fig.data[2]
        cost_cust = fig.data[3]
        assert list(savings_cust.y) == pytest.approx([-5.0, -10.0, -15.0, -20.0])
        assert all(np.isnan(v) for v in cost_cust.y)
        # Only the top row's traces show in the (shared) legend.
        assert fig.data[0].showlegend is not False
        assert fig.data[1].showlegend is not False
        assert fig.data[2].showlegend is False
        assert fig.data[3].showlegend is False

    def test_cumulative_cost_chart_shows_added_cost_when_proposed_is_more_expensive(self):
        years_as_hours = pd.Series(pd.date_range("2012-01-01", periods=3, freq="h"))
        utility_net_hr = np.array([4.0, 4.0, 4.0])  # Proposed costs more every hour
        baseline_cust = np.array([20.0, 20.0, 20.0])
        proposed_cust = np.array([20.0, 20.0, 20.0])
        fig = build_cumulative_cost_chart(
            years_as_hours, utility_net_hr, baseline_cust, proposed_cust
        )
        cost_grid = fig.data[1]
        assert list(cost_grid.y) == pytest.approx([4.0, 8.0, 12.0])

    def test_lifetime_npv_returns_figure(self):
        years = np.arange(1, 16)
        disc_grid = np.ones(15) * 80
        disc_lost = np.ones(15) * 60
        fig = build_lifetime_npv_chart(years, disc_grid, disc_lost)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 3  # 2 bar traces (savings, lost revenue) + cumulative net line
        assert fig.data[0].type == "bar"
        assert fig.data[1].type == "bar"
        assert fig.data[2].type == "scatter"

    def test_lifetime_npv_lost_revenue_is_negative_and_cumulative_nets_out(self):
        years = np.arange(1, 4)
        disc_grid = np.array([100.0, 100.0, 100.0])
        disc_lost = np.array([30.0, 30.0, 30.0])
        fig = build_lifetime_npv_chart(years, disc_grid, disc_lost)
        lost_trace = next(t for t in fig.data if t.name == "Lost Retail Revenue (PV)")
        cumulative_trace = next(t for t in fig.data if "Cumulative" in t.name)
        assert list(lost_trace.y) == pytest.approx([-30.0, -30.0, -30.0])
        assert list(cumulative_trace.y) == pytest.approx([70.0, 140.0, 210.0])

    def test_lifetime_npv_customer_perspective_adds_year_zero_upfront_cost(self):
        years = np.arange(1, 4)
        bill_savings = np.array([40.0, 40.0, 40.0])
        fig = build_lifetime_npv_chart(
            years, bill_savings, benefit_name="Bill Savings (PV)",
            upfront_cost=100.0, upfront_name="Upfront Cost (after rebate)"
        )
        upfront_trace = next(t for t in fig.data if t.name == "Upfront Cost (after rebate)")
        savings_trace = next(t for t in fig.data if t.name == "Bill Savings (PV)")
        cumulative_trace = next(t for t in fig.data if "Cumulative" in t.name)

        # A "Year 0" column is prepended for the upfront cost.
        assert list(upfront_trace.x) == [0, 1, 2, 3]
        assert list(upfront_trace.y) == pytest.approx([-100.0, 0.0, 0.0, 0.0])
        assert list(savings_trace.y) == pytest.approx([0.0, 40.0, 40.0, 40.0])
        # Cumulative starts negative (the upfront cost) and crosses zero as savings accrue.
        assert list(cumulative_trace.y) == pytest.approx([-100.0, -60.0, -20.0, 20.0])

    def test_lifetime_npv_utility_combines_recurring_cost_and_upfront_program_cost(self):
        years = np.arange(1, 4)
        grid_savings = np.array([100.0, 100.0, 100.0])
        lost_revenue = np.array([30.0, 30.0, 30.0])
        fig = build_lifetime_npv_chart(
            years, grid_savings, cost_stream=lost_revenue,
            benefit_name="Grid Savings (PV)", cost_name="Lost Retail Revenue (PV)",
            upfront_cost=50.0, upfront_name="Program Cost (Incentive + Admin)"
        )
        # 4 traces: grid savings, upfront program cost, recurring lost revenue, cumulative line.
        assert len(fig.data) == 4
        upfront_trace = next(t for t in fig.data if t.name == "Program Cost (Incentive + Admin)")
        lost_trace = next(t for t in fig.data if t.name == "Lost Retail Revenue (PV)")
        cumulative_trace = next(t for t in fig.data if "Cumulative" in t.name)

        assert list(upfront_trace.x) == [0, 1, 2, 3]
        assert list(upfront_trace.y) == pytest.approx([-50.0, 0.0, 0.0, 0.0])
        assert list(lost_trace.y) == pytest.approx([0.0, -30.0, -30.0, -30.0])
        # Year 0: just -program cost. Years 1-3: +100 savings -30 lost revenue = +70/yr.
        assert list(cumulative_trace.y) == pytest.approx([-50.0, 20.0, 90.0, 160.0])

    def test_lifetime_npv_chart_has_no_in_figure_title(self):
        years = np.arange(1, 4)
        fig = build_lifetime_npv_chart(years, np.array([1.0, 1.0, 1.0]))
        assert fig.layout.title.text is None

    def test_lifetime_npv_colors_follow_sign_not_fixed_category(self):
        """
        Regression test: a negative `cost_stream` value (e.g. a year where the
        customer's bill actually went UP under Proposed, so the utility
        gained retail revenue instead of losing it) must render as a GREEN
        "gain" bar, not a red/pink "cost" bar drawn upside-down above zero.
        Likewise a negative `benefit_stream` value must render red, not
        green. Bug: originally a fixed color was assigned per named series
        regardless of that year's actual sign.
        """
        years = np.arange(1, 3)
        grid_savings = np.array([-20.0, 100.0])  # year 1: technology adds grid stress
        lost_revenue = np.array([-15.0, 30.0])   # year 1: customer bill went UP -> revenue gain
        fig = build_lifetime_npv_chart(
            years, grid_savings, cost_stream=lost_revenue,
            benefit_name="Grid Savings (PV)", benefit_negative_name="Grid Cost (PV)",
            cost_name="Lost Retail Revenue (PV)", cost_negative_name="Revenue Gain (PV)"
        )
        grid_cost_trace = next(t for t in fig.data if t.name == "Grid Cost (PV)")
        revenue_gain_trace = next(t for t in fig.data if t.name == "Revenue Gain (PV)")
        grid_savings_trace = next(t for t in fig.data if t.name == "Grid Savings (PV)")
        lost_revenue_trace = next(t for t in fig.data if t.name == "Lost Retail Revenue (PV)")

        # The flipped-sign year (year 1) shows up in the "negative" buckets, colored red...
        assert list(grid_cost_trace.y) == pytest.approx([-20.0, 0.0])
        assert grid_cost_trace.marker.color == config.COLORS["red"]
        # ...and the revenue gain shows up GREEN, not red, since it helped that year.
        assert list(revenue_gain_trace.y) == pytest.approx([15.0, 0.0])
        assert revenue_gain_trace.marker.color == config.COLORS["green"]
        # Year 2 (normal sign) still lands in the usual named/colored buckets.
        assert list(grid_savings_trace.y) == pytest.approx([0.0, 100.0])
        assert grid_savings_trace.marker.color == config.COLORS["green"]
        assert list(lost_revenue_trace.y) == pytest.approx([0.0, -30.0])
        assert lost_revenue_trace.marker.color == config.COLORS["red"]

    def test_economic_balance_chart_returns_figure(self):
        from visualizations import build_economic_balance_chart
        fig = build_economic_balance_chart(
            npv_grid_savings=4967.38,
            npv_retail_lost_revenue=6296.74,
            npv_net_savings=-1329.36
        )
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 1
        assert fig.data[0].type == "waterfall"
        # No program cost given -> no extra bar, just the original 3 steps.
        assert list(fig.data[0].y) == ["Grid Avoided Costs", "Utility Lost Revenue", "Net Valuation NPV"]

    def test_economic_balance_chart_adds_program_cost_bar_when_given(self):
        from visualizations import build_economic_balance_chart
        fig = build_economic_balance_chart(
            npv_grid_savings=5000.0,
            npv_retail_lost_revenue=6000.0,
            npv_net_savings=-1600.0,
            npv_program_cost=600.0
        )
        wf = fig.data[0]
        assert list(wf.y) == [
            "Grid Avoided Costs", "Utility Lost Revenue", "Utility Program Cost", "Net Valuation NPV"
        ]
        assert list(wf.x) == [5000.0, -6000.0, -600.0, 0]
        assert list(wf.measure) == ["relative", "relative", "relative", "total"]

    def test_economic_balance_chart_labels_follow_actual_sign_not_hardcoded_prefix(self):
        """
        Regression test: a negative npv_grid_savings previously always got a
        hardcoded "+" prefix, printing nonsense like "+$-474". Each label
        should carry its own bar's real sign instead.
        """
        from visualizations import build_economic_balance_chart
        fig = build_economic_balance_chart(
            npv_grid_savings=-474.0,          # grid value is net negative
            npv_retail_lost_revenue=-1590.0,  # a revenue GAIN, not a loss
            npv_net_savings=-1264.0,
            npv_program_cost=200.0
        )
        wf = fig.data[0]
        texts = dict(zip(wf.y, wf.text))
        assert texts["Grid Avoided Costs"] == "-$474"
        # Bar value is -(-1590) = +1590 (a gain), so the label must read positive too.
        assert texts["Utility Lost Revenue"] == "+$1,590"
        assert texts["Utility Program Cost"] == "-$200"
        assert texts["Net Valuation NPV"] == "-$1,264"

    def test_two_sided_cost_effectiveness_chart_returns_figure(self):
        from visualizations import build_two_sided_cost_effectiveness_chart
        # Test positive net operating margin
        fig_pos = build_two_sided_cost_effectiveness_chart(
            annual_energy_savings=124.24,
            annual_gen_cap_savings=466.03,
            annual_trans_savings=4.47,
            annual_dist_savings=57.99,
            annual_emissions_savings=32.59,
            retail_energy_savings=653.04,
            retail_demand_savings=0.0,
            annual_net_savings=32.29
        )
        assert isinstance(fig_pos, go.Figure)
        assert len(fig_pos.data) == 8  # 5 grid components + 2 retail components + 1 net margin
        assert len(fig_pos.layout.annotations) == 3  # 3 total/net annotations

        # Test negative net operating margin (cross-subsidy)
        fig_neg = build_two_sided_cost_effectiveness_chart(
            annual_energy_savings=100.0,
            annual_gen_cap_savings=200.0,
            annual_trans_savings=5.0,
            annual_dist_savings=20.0,
            annual_emissions_savings=10.0,
            retail_energy_savings=500.0,
            retail_demand_savings=50.0,
            annual_net_savings=-215.0
        )
        assert isinstance(fig_neg, go.Figure)
        assert len(fig_neg.data) == 8

    def test_bubble_chart_handles_nan_load_defensively(self):
        """Regression test: a stray NaN in baseline/proposed load (e.g. from
        an upstream data gap that slipped through ingestion) must not crash
        Plotly's marker-size validation, which rejects NaN outright."""
        n = 100
        temp_vals = np.linspace(30, 90, n)
        baseline_load = np.full(n, 1.5)
        proposed_load = np.full(n, 1.2)
        proposed_load[10] = np.nan
        baseline_cost_hr = np.full(n, 5.0)
        proposed_cost_hr = np.full(n, 4.0)

        fig = build_temp_power_cost_bubble_chart(
            temp_vals, baseline_load, proposed_load, baseline_cost_hr, proposed_cost_hr
        )
        assert isinstance(fig, go.Figure)
        for trace in fig.data:
            assert not np.isnan(trace.marker.size).any()



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
            years, np.ones(15) * 80, np.ones(15) * 60
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

    def test_missing_hour_is_interpolated_not_left_as_nan(self, tmp_path):
        """Regression test: a single blank cell in an otherwise-complete load
        profile export (e.g. one missing hour) should be linearly
        interpolated, not passed through as NaN — a stray NaN in the load
        array crashes downstream Plotly marker-size charts. See the
        BirminghamTES_ETS_Case.xlsx bug report, 2026-09-22."""
        from data_loaders import load_load_profiles_from_csv
        n = 8760
        clean_vals = np.linspace(1.0, 2.0, n)
        gappy_vals = clean_vals.copy()
        gap_idx = 19
        gappy_vals[gap_idx] = np.nan
        src_df = pd.DataFrame({
            "Date": pd.date_range("2012-01-01", periods=n, freq="h"),
            "Total_WithoutETS": clean_vals,
            "Total_WithETS": gappy_vals,
        })
        filepath = tmp_path / "gap_test.xlsx"
        src_df.to_excel(filepath, index=False)

        result = load_load_profiles_from_csv(str(filepath))

        assert not result["Total_WithETS"].isna().any()
        neighbor_avg = (result["Total_WithETS"].iloc[gap_idx - 1] + result["Total_WithETS"].iloc[gap_idx + 1]) / 2
        assert abs(result["Total_WithETS"].iloc[gap_idx] - neighbor_avg) < 1e-9

        warnings = result.attrs.get("ingestion_warnings", [])
        assert len(warnings) == 1
        assert "Total_WithETS" in warnings[0]
        assert "Total_WithoutETS" not in " ".join(warnings)  # the clean column shouldn't be flagged

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

    def test_zero_cost_ratios_are_infinite_not_misleadingly_zero(self):
        """
        A real benefit against $0 cost (e.g. a user zeroes out Gross Measure
        Cost while testing) is infinitely favorable and should read that way,
        not as a 0.0 that looks like a failing/worthless ratio.
        """
        from calculations import calculate_cost_effectiveness_tests

        res = calculate_cost_effectiveness_tests(
            npv_grid_savings=5000.0, npv_lost_revenue=0.0, npv_customer_bill_savings=3000.0,
            gross_measure_cost=0.0, utility_incentive=0.0, utility_admin_cost=0.0,
            annual_customer_savings_stream=np.ones(15) * 300.0, pv_multipliers=np.ones(15) * 0.8
        )
        assert res["trc_ratio"] == float('inf')
        assert res["pct_ratio"] == float('inf')
        assert res["rim_ratio"] == float('inf')

    def test_zero_cost_and_zero_benefit_ratio_is_neutral_zero(self):
        from calculations import calculate_cost_effectiveness_tests

        res = calculate_cost_effectiveness_tests(
            npv_grid_savings=0.0, npv_lost_revenue=0.0, npv_customer_bill_savings=0.0,
            gross_measure_cost=0.0, utility_incentive=0.0, utility_admin_cost=0.0,
            annual_customer_savings_stream=np.zeros(15), pv_multipliers=np.ones(15) * 0.8
        )
        assert res["trc_ratio"] == 0.0
        assert res["pct_ratio"] == 0.0
        assert res["rim_ratio"] == 0.0

    def test_negative_cost_basis_returns_nan_not_a_sign_flipped_ratio(self):
        """
        Regression test for a real Electric Thermal Storage case: the
        technology's proposed load used enough MORE total energy that the
        customer's bill went up, making annual_lost_revenue negative (a
        revenue GAIN, not a loss) large enough that RIM's cost basis
        (lost revenue + program cost) goes negative overall. Dividing a
        negative grid-savings benefit by that negative cost would flip the
        sign and read as a deceptively positive ("passing") ratio -- it
        must come back as NaN instead, distinct from the true zero-cost
        cases above.
        """
        from calculations import calculate_cost_effectiveness_tests

        res = calculate_cost_effectiveness_tests(
            npv_grid_savings=-632.0, npv_lost_revenue=-1590.0, npv_customer_bill_savings=-1590.0,
            gross_measure_cost=100.0, utility_incentive=100.0, utility_admin_cost=100.0,
            annual_customer_savings_stream=np.full(15, -175.0), pv_multipliers=np.ones(15) * 0.8
        )
        # rim_costs = -1590 + (100 + 100) = -1390 < 0 -> degenerate, not a real ratio.
        assert np.isnan(res["rim_ratio"])
        # -632 / -1390 would otherwise be +0.4547 -- a deceptively "almost passing"
        # number for a scenario where both sides are actually unfavorable.
        assert res["rim_ratio"] != pytest.approx(-632.0 / -1390.0)


# ======================================================================
#  TEST SUITE 11: Southeast Utility Capacity & Feeder Engine
# ======================================================================

class TestSoutheastUtilityCapacityEngine:
    """
    Validates Southeast utility peaker carrying cost, regulated FCR,
    dual-peak CWF allocation, LOLP proxies, peaker spark spreads, and feeder weights.
    """

    def test_regulated_fcr_bounds(self):
        from calculations import calculate_regulated_fcr
        # 7.1% WACC, 30 year life, 25% tax rate
        fcr = calculate_regulated_fcr(wacc=0.071, economic_life=30, tax_rate=0.25, macrs_life=15)
        # Expected FCR is in the 8.0% - 9.0% range typical of regulated electric utilities
        assert 0.075 < fcr < 0.095

    def test_regulated_fcr_zero_tax(self):
        from calculations import calculate_regulated_fcr
        # With zero tax, FCR equals pure CRF
        d = 0.07
        n = 30
        expected_crf = d / (1.0 - (1.0 + d) ** (-n))
        fcr = calculate_regulated_fcr(wacc=d, economic_life=n, tax_rate=0.0)
        assert pytest.approx(fcr, rel=1e-5) == expected_crf

    def test_ct_carrying_cost_gross_and_net(self):
        from calculations import calculate_ct_carrying_cost
        capex = 1000.0  # $/kW
        fom = 15.0      # $/kW-yr
        fcr = 0.085     # 8.5%
        eas = 10.0      # $/kW-yr

        res = calculate_ct_carrying_cost(capex, fom, fcr, eas_offset_kw_yr=eas)
        # Capital recovery = 1000 * 0.085 = 85.0
        assert res["capital_recovery_annuity"] == 85.0
        # Gross = 85.0 + 15.0 = 100.0
        assert res["gross_carrying_cost"] == 100.0
        # Net = 100.0 - 10.0 = 90.0
        assert res["net_capacity_cost"] == 90.0

    def test_southeast_dual_peak_cwf_sums_and_shape(self):
        from calculations import calculate_southeast_dual_peak_cwf
        cwf = calculate_southeast_dual_peak_cwf(winter_weight=0.5, summer_weight=0.5)
        assert len(cwf) == 8760
        assert np.all(cwf >= 0.0)
        assert pytest.approx(cwf.sum(), abs=1e-6) == 1.0

        # Check that winter morning hours and summer afternoon hours get the weights
        # Jan 15 hour 7 (7 AM) is a winter morning hour -> should be > 0
        jan_15_7am = 14 * 24 + 7
        assert cwf[jan_15_7am] > 0.0

        # Jul 15 hour 15 (3 PM) is a summer afternoon hour -> should be > 0
        # Day 195 (approx July 15), hour 15
        jul_15_3pm = 195 * 24 + 15
        assert cwf[jul_15_3pm] > 0.0

        # Apr 15 hour 12 (spring midday) should be 0
        apr_15_12pm = 104 * 24 + 12
        assert cwf[apr_15_12pm] == 0.0

    def test_southeast_dual_peak_cwf_exceedance_with_load(self):
        from calculations import calculate_southeast_dual_peak_cwf
        np.random.seed(42)
        load = np.random.uniform(1.0, 5.0, 8760)
        cwf = calculate_southeast_dual_peak_cwf(winter_weight=0.6, summer_weight=0.4, load_array=load)
        assert pytest.approx(cwf.sum(), abs=1e-6) == 1.0

    def test_cwf_lolp_proxy(self):
        from calculations import calculate_cwf_lolp_proxy
        demand = np.linspace(100.0, 1000.0, 8760)
        cwf = calculate_cwf_lolp_proxy(demand, alpha=12.0)
        assert len(cwf) == 8760
        assert pytest.approx(cwf.sum(), abs=1e-6) == 1.0
        assert np.all(cwf >= 0.0)
        # Highest demand hour (last) should have much higher risk than lowest (first)
        assert cwf[-1] > cwf[0] * 1000.0

    def test_cwf_top_n_uniform_and_exceedance(self):
        from calculations import calculate_cwf_top_n
        demand = np.arange(8760, dtype=float)
        cwf_uni = calculate_cwf_top_n(demand, top_n=100, weighting_method="uniform")
        assert pytest.approx(cwf_uni.sum(), abs=1e-6) == 1.0
        assert (cwf_uni > 0).sum() == 100
        assert np.isclose(cwf_uni[-1], 0.01)

        cwf_exc = calculate_cwf_top_n(demand, top_n=100, weighting_method="exceedance")
        assert pytest.approx(cwf_exc.sum(), abs=1e-6) == 1.0
        assert (cwf_exc > 0).sum() == 100

    def test_cwf_peaker_rent(self):
        from calculations import calculate_cwf_peaker_rent
        prices = np.ones(8760) * 30.0  # below peaker operating cost
        prices[-10:] = 200.0           # 10 peaker hours above cost
        cwf = calculate_cwf_peaker_rent(prices, heat_rate=10500, gas_price=3.50, vom=4.0)
        assert pytest.approx(cwf.sum(), abs=1e-6) == 1.0
        # Only the 10 peak hours should have non-zero weight
        assert (cwf > 0).sum() == 10

    def test_feeder_pcaf_weights(self):
        from calculations import calculate_feeder_pcaf_weights
        w_winter = calculate_feeder_pcaf_weights(feeder_type="Winter-Peaking Feeder (Southeast Heating / Cold Snap)")
        assert pytest.approx(w_winter.sum(), abs=1e-6) == 1.0
        assert np.all(w_winter >= 0.0)

        w_summer = calculate_feeder_pcaf_weights(feeder_type="Summer-Peaking Feeder (Southeast Cooling)")
        assert pytest.approx(w_summer.sum(), abs=1e-6) == 1.0

        w_dual = calculate_feeder_pcaf_weights(feeder_type="Dual-Peaking Feeder (Suburban Mixed 50/50)")
        assert pytest.approx(w_dual.sum(), abs=1e-6) == 1.0

    def test_avoided_costs_decoupled_td_weights(self, grid_df_8760, cwft_uniform):
        from calculations import calculate_avoided_costs
        df = grid_df_8760.copy()
        custom_dist = np.zeros(8760)
        custom_dist[:100] = 0.01  # First 100 hours

        res = calculate_avoided_costs(
            df,
            cap_value=100.0,
            trans_value=15.0,
            dist_value=25.0,
            carbon_tax=30.0,
            cwft_array=cwft_uniform,
            dist_weight_array=custom_dist
        )
        # Dist_Value_MWh should be 25 * 0.01 * 1000 = 250 in hour 0
        assert pytest.approx(res['Dist_Value_MWh'].iloc[0], rel=1e-5) == 250.0
        # Dist_Value_MWh should be 0 in hour 500
        assert res['Dist_Value_MWh'].iloc[500] == 0.0

    def test_new_visualization_functions(self):
        from visualizations import (
            plot_peaker_carrying_cost_breakdown,
            plot_southeast_cwf_distribution,
            plot_feeder_vs_system_load
        )
        # 1. Peaker breakdown
        c_dict = {
            "capital_recovery_annuity": 85.0,
            "fom_kw_yr": 15.0,
            "gross_carrying_cost": 100.0,
            "eas_offset_kw_yr": 5.0,
            "net_capacity_cost": 95.0
        }
        fig1 = plot_peaker_carrying_cost_breakdown(c_dict)
        assert fig1 is not None

        # 2. CWF distribution
        cwf = np.ones(8760) / 8760
        fig2 = plot_southeast_cwf_distribution(cwf)
        assert fig2 is not None

        # 3. Feeder vs system
        feeder = np.ones(8760) / 8760
        system = np.ones(8760) / 8760
        fig3 = plot_feeder_vs_system_load(feeder, system)
        assert fig3 is not None

    def test_cwf_temperature_exceedance_sums_and_shape(self):
        from calculations import calculate_cwf_temperature_exceedance
        # Synthetic temperature profile: winter cold (20-40F), summer hot (75-95F), shoulder (60F)
        temps = np.full(8760, 60.0)
        # Cold winter morning in January
        temps[100] = 18.0
        # Hot summer afternoon in July
        temps[5000] = 98.0

        cwf = calculate_cwf_temperature_exceedance(temps, freeze_threshold_f=32.0, heat_threshold_f=90.0)
        assert cwf.shape == (8760,)
        assert pytest.approx(cwf.sum(), abs=1e-6) == 1.0
        assert np.all(cwf >= 0.0)

    def test_cwf_temperature_exceedance_colder_gets_more_weight(self):
        from calculations import calculate_cwf_temperature_exceedance
        # Standard non-leap year: hour 6 is Jan 1 06:00 (winter window)
        # hour 30 is Jan 2 06:00 (winter window)
        temps = np.full(8760, 50.0)
        temps[6] = 15.0   # 17 degrees below 32
        temps[30] = 27.0  # 5 degrees below 32
        temps[54] = 35.0  # above 32, zero severity

        cwf = calculate_cwf_temperature_exceedance(
            temps, freeze_threshold_f=32.0, heat_threshold_f=90.0,
            winter_weight=1.0, summer_weight=0.0
        )
        assert cwf[6] > cwf[30] > 0.0
        assert cwf[54] == 0.0
        assert pytest.approx(cwf[6] / cwf[30], rel=1e-4) == (32.0 - 15.0) / (32.0 - 27.0)

    def test_cwf_temperature_exceedance_seasonal_split_and_fallback(self):
        from calculations import calculate_cwf_temperature_exceedance
        # Test 75% winter / 25% summer split
        temps = np.full(8760, 65.0)
        temps[6] = 20.0     # winter freeze hour
        # Jul 15 15:00 is approx hour 4719
        temps[4719] = 95.0  # summer heat hour

        cwf = calculate_cwf_temperature_exceedance(
            temps, freeze_threshold_f=32.0, heat_threshold_f=90.0,
            winter_weight=0.75, summer_weight=0.25
        )
        assert pytest.approx(cwf[6], abs=1e-6) == 0.75
        assert pytest.approx(cwf[4719], abs=1e-6) == 0.25

        # Fallback when no temperatures cross threshold
        flat_temps = np.full(8760, 65.0)
        cwf_fallback = calculate_cwf_temperature_exceedance(flat_temps, freeze_threshold_f=32.0, heat_threshold_f=90.0)
        assert pytest.approx(cwf_fallback.sum(), abs=1e-6) == 1.0
        assert np.all(cwf_fallback >= 0.0)




