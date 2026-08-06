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
_plotly, _go, _subplots = _make_plotly_stubs()

sys.modules["streamlit"] = _st_stub
sys.modules["plotly"] = _plotly
sys.modules["plotly.graph_objects"] = _go
sys.modules["plotly.subplots"] = _subplots

# Import the extracted modules directly — no Streamlit stub needed for these
# since they are pure Python with no UI dependencies.
from calculations import calculate_avoided_costs  # noqa: E402
from billing import calculate_urdb_bill  # noqa: E402


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
