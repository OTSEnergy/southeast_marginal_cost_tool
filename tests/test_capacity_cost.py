"""
tests/test_capacity_cost.py — Unit Tests for SERC Capacity Cost Module
======================================================================

Validates the SERC regional avoided capacity valuation engine against
regulatory dockets and mathematical formulations:
1. 2025 Composite baseline matches ~$130/kW-yr real (2024$).
2. Math invariance between capital recovery factors, levelized rates, and gross carrying costs.
3. Nominal inflation compounding across 2025–2050 at 2.2% annual GDP deflator.
4. Ambient turbine derate / seasonal accreditation adjustments (1.15x winter ratio).
5. Pydantic schema validation and bounds checks.
6. DataFrame projection structure, year spans, and column contracts.
7. Legal and regulatory formal citation completeness.
"""

import os
import subprocess
import sys
import tempfile
import pytest
import numpy as np
import pandas as pd
from pydantic import ValidationError

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from serc_capacity_cost import (
    UtilityBenchmark,
    CapacityCostProjection,
    SERCCapacityModel,
    STATE_UTILITY_BENCHMARKS,
    get_state_capacity_benchmark,
    refresh_capacity_benchmarks,
)
from calculations import (
    calculate_annual_capacity_savings,
    calculate_multi_year_avoided_costs_and_npv,
)


class TestSERCCapacityBaselines:
    """Validate empirical baseline data and 2024$ real carrying cost benchmarks."""

    def setup_method(self):
        self.model = SERCCapacityModel()

    def test_serc_composite_baseline_matches_130_real(self):
        """
        Validate that the 2025 composite baseline matches ~$130/kW-yr real (2024$):
            CapEx: $1,080/kW
            LFCR: 9.7% (0.097)
            FOM: $25.00/kW-yr
            Capital Recovery = $1,080 * 0.097 = $104.76/kW-yr
            Gross ECC = $104.76 + $25.00 = $129.76/kW-yr (~$130/kW-yr)
        """
        bm = self.model.get_benchmark("SERC Weighted Composite")
        assert bm.installed_capex_per_kw == 1080.0
        assert bm.levelized_fcr == 0.097
        assert bm.fom_per_kw_yr == 25.0

        assert pytest.approx(bm.annual_capital_recovery_per_kw_yr, abs=1e-3) == 104.76
        assert pytest.approx(bm.gross_ecc_per_kw_yr, abs=1e-3) == 129.76
        assert pytest.approx(bm.gross_ecc_per_kw_yr, abs=0.5) == 130.0

        # Check via model calculate_ecc
        ecc = self.model.calculate_ecc("SERC Weighted Composite", year=2025, currency="real_2024")
        assert pytest.approx(ecc["gross_ecc_per_kw_yr"], abs=1e-3) == 129.76

    def test_southern_company_benchmark_math(self):
        """
        Validate Southern Company benchmark (GPSC Docket 44280 / APSC Docket 33201):
            CapEx: $1,110/kW
            LFCR: 10.2% (0.102)
            FOM: $28.00/kW-yr
            Capital Recovery = $1,110 * 0.102 = $113.22/kW-yr
            Gross ECC = $113.22 + $28.00 = $141.22/kW-yr
        """
        bm = self.model.get_benchmark("Southern Company")
        assert bm.installed_capex_per_kw == 1110.0
        assert bm.levelized_fcr == 0.102
        assert bm.fom_per_kw_yr == 28.00
        assert pytest.approx(bm.annual_capital_recovery_per_kw_yr, abs=1e-3) == 113.22
        assert pytest.approx(bm.gross_ecc_per_kw_yr, abs=1e-3) == 141.22

    def test_duke_energy_benchmark_math(self):
        """
        Validate Duke Energy benchmark (NCUC Docket E-100 Sub 190):
            CapEx: $1,075/kW
            LFCR: 9.8% (0.098)
            FOM: $25.00/kW-yr
            Capital Recovery = $1,075 * 0.098 = $105.35/kW-yr
            Gross ECC = $105.35 + $25.00 = $130.35/kW-yr
        """
        bm = self.model.get_benchmark("Duke Energy Carolinas & Progress")
        assert bm.installed_capex_per_kw == 1075.0
        assert bm.levelized_fcr == 0.098
        assert bm.fom_per_kw_yr == 25.00
        assert pytest.approx(bm.annual_capital_recovery_per_kw_yr, abs=1e-3) == 105.35
        assert pytest.approx(bm.gross_ecc_per_kw_yr, abs=1e-3) == 130.35

    def test_tva_benchmark_math(self):
        """
        Validate TVA benchmark (TVA 2019/2024 IRP Supply-Side Resource Assessment):
            CapEx: $1,035/kW
            LFCR: 8.9% (0.089)
            FOM: $23.00/kW-yr
            Capital Recovery = $1,035 * 0.089 = $92.115/kW-yr
            Gross ECC = $92.115 + $23.00 = $115.115/kW-yr
        """
        bm = self.model.get_benchmark("Tennessee Valley Authority")
        assert bm.installed_capex_per_kw == 1035.0
        assert bm.levelized_fcr == 0.089
        assert bm.fom_per_kw_yr == 23.00
        assert pytest.approx(bm.annual_capital_recovery_per_kw_yr, abs=1e-3) == 92.115
        assert pytest.approx(bm.gross_ecc_per_kw_yr, abs=1e-3) == 115.115


class TestMathInvarianceAndCalculations:
    """Validate mathematical invariance between capital recovery, levelized rates, and overrides."""

    def setup_method(self):
        self.model = SERCCapacityModel()

    def test_math_invariance_across_all_benchmarks(self):
        """Verify for every benchmark that Gross ECC = CapEx * LFCR + FOM."""
        for name, bm in self.model.benchmarks.items():
            expected_cap_rec = bm.installed_capex_per_kw * bm.levelized_fcr
            expected_gross = expected_cap_rec + bm.fom_per_kw_yr
            assert pytest.approx(bm.annual_capital_recovery_per_kw_yr, abs=1e-4) == expected_cap_rec
            assert pytest.approx(bm.gross_ecc_per_kw_yr, abs=1e-4) == expected_gross

    def test_parameter_overrides(self):
        """Test calculation with custom parameter overrides."""
        res = self.model.calculate_ecc(
            "SERC Weighted Composite",
            year=2024,
            currency="real_2024",
            capex_override=1200.0,
            lfcr_override=0.10,
            fom_override=30.0,
        )
        # 1200 * 0.10 = 120; 120 + 30 = 150
        assert pytest.approx(res["annual_capital_recovery_per_kw_yr"], abs=1e-3) == 120.0
        assert pytest.approx(res["fom_per_kw_yr"], abs=1e-3) == 30.0
        assert pytest.approx(res["gross_ecc_per_kw_yr"], abs=1e-3) == 150.0

    def test_alias_resolution(self):
        """Test case-insensitive and abbreviated utility lookups."""
        assert self.model.resolve_utility_name("SO") == "Southern Company"
        assert self.model.resolve_utility_name("georgia power") == "Southern Company"
        assert self.model.resolve_utility_name("duke") == "Duke Energy Carolinas & Progress"
        assert self.model.resolve_utility_name("TVA") == "Tennessee Valley Authority"
        assert self.model.resolve_utility_name("serc") == "SERC Weighted Composite"

        with pytest.raises(KeyError):
            self.model.resolve_utility_name("ERCOT")


class TestNominalInflationCompounding:
    """Validate nominal escalation compounding across future planning years (2025–2050)."""

    def setup_method(self):
        self.model = SERCCapacityModel(annual_inflation_rate=0.022, base_year=2024)

    def test_nominal_inflation_compounding_formula(self):
        """
        Verify that nominal dollar compounding strictly follows:
            Factor_t = (1 + inflation_rate) ^ (t - base_year)
            Cost_t = Cost_base * Factor_t
        """
        base_ecc = 129.76  # SERC composite 2024$ real
        r = 0.022

        for yr in [2025, 2030, 2040, 2050]:
            delta_t = yr - 2024
            expected_factor = (1.0 + r) ** delta_t
            expected_nominal_ecc = base_ecc * expected_factor

            calc = self.model.calculate_ecc("SERC Weighted Composite", year=yr, currency="nominal")
            assert pytest.approx(calc["inflation_factor"], abs=1e-6) == expected_factor
            assert pytest.approx(calc["gross_ecc_per_kw_yr"], abs=1e-2) == expected_nominal_ecc

    def test_year_2040_nominal_value(self):
        """
        Verify exact calculated nominal values for delivery year 2040:
            Years = 2040 - 2024 = 16
            Inflation multiplier = 1.022^16 ≈ 1.415779
            SERC Composite: 129.76 * 1.415779 = $183.71/kW-yr
            Southern Company: 141.22 * 1.415779 = $199.94/kW-yr
        """
        calc_serc_2040 = self.model.calculate_ecc("SERC Weighted Composite", year=2040, currency="nominal")
        calc_so_2040 = self.model.calculate_ecc("Southern Company", year=2040, currency="nominal")

        assert pytest.approx(calc_serc_2040["gross_ecc_per_kw_yr"], abs=0.1) == 183.71
        assert pytest.approx(calc_so_2040["gross_ecc_per_kw_yr"], abs=0.1) == 199.94

    def test_monotonic_escalation(self):
        """Verify that nominal ECC increases strictly monotonically over future years."""
        df = self.model.get_projection(start_year=2025, end_year=2050, currency="nominal", utility="SERC Weighted Composite")
        values = df["gross_ecc_per_kw_yr"].values
        for i in range(len(values) - 1):
            assert values[i + 1] > values[i]

    def test_real_currency_remains_constant(self):
        """Verify that real_2024 currency projection is invariant across years."""
        df = self.model.get_projection(start_year=2025, end_year=2050, currency="real_2024", utility="SERC Weighted Composite")
        values = df["gross_ecc_per_kw_yr"].values
        assert pytest.approx(values[0], abs=1e-4) == 129.76
        assert pytest.approx(values[-1], abs=1e-4) == 129.76


class TestSeasonalAccreditationAdjustment:
    """Validate ambient derate / seasonal capacity valuation adjustments."""

    def setup_method(self):
        self.model = SERCCapacityModel()

    def test_seasonal_capacity_derate_115_ratio(self):
        """
        Verify that winter capacity value reflects 1.15x ambient air density accreditation:
            Gross ECC = $129.76
            winter_weight = 0.50, summer_weight = 0.50
            winter_ratio = 1.15, summer_ratio = 1.00
            Winter seasonal value = 129.76 * 0.50 * 1.15 = $74.612/kW-season
            Summer seasonal value = 129.76 * 0.50 * 1.00 = $64.880/kW-season
        """
        gross_ecc = 129.76
        res = self.model.calculate_seasonal_capacity_value(
            gross_ecc,
            winter_accreditation_ratio=1.15,
            summer_accreditation_ratio=1.00,
            winter_weight=0.50,
            summer_weight=0.50,
        )
        assert pytest.approx(res["winter_capacity_value_per_kw_season"], abs=1e-2) == 74.61
        assert pytest.approx(res["summer_capacity_value_per_kw_season"], abs=1e-2) == 64.88
        assert res["winter_capacity_value_per_kw_season"] > res["summer_capacity_value_per_kw_season"]

    def test_custom_seasonal_allocation_weights(self):
        """Test custom seasonal risk splits (e.g., 80% winter / 20% summer Southeast net peak)."""
        gross_ecc = 100.0
        res = self.model.calculate_seasonal_capacity_value(
            gross_ecc,
            winter_accreditation_ratio=1.15,
            summer_accreditation_ratio=1.00,
            winter_weight=0.80,
            summer_weight=0.20,
        )
        # 100 * 0.80 * 1.15 = 92.0
        # 100 * 0.20 * 1.00 = 20.0
        assert pytest.approx(res["winter_capacity_value_per_kw_season"], abs=1e-3) == 92.0
        assert pytest.approx(res["summer_capacity_value_per_kw_season"], abs=1e-3) == 20.0


class TestPydanticValidation:
    """Validate Pydantic bounds and type enforcement."""

    def test_valid_utility_benchmark_instantiation(self):
        bm = UtilityBenchmark(
            name="Test Peaker",
            operating_companies="Test Operating Co",
            benchmark_unit="GE LM6000",
            regulatory_docket="Docket 12345",
            installed_capex_per_kw=1000.0,
            levelized_fcr=0.08,
            fom_per_kw_yr=20.0,
        )
        assert bm.name == "Test Peaker"
        assert bm.annual_capital_recovery_per_kw_yr == 80.0
        assert bm.gross_ecc_per_kw_yr == 100.0

    def test_invalid_fcr_fraction_raises_validation_error(self):
        """LFCR must be a valid decimal fraction between 0.0 and 1.0."""
        with pytest.raises(ValidationError):
            UtilityBenchmark(
                name="Invalid FCR",
                operating_companies="Test Co",
                benchmark_unit="SCCT",
                regulatory_docket="Docket 123",
                installed_capex_per_kw=1000.0,
                levelized_fcr=10.2,  # Should be 0.102, not 10.2
                fom_per_kw_yr=20.0,
            )

    def test_negative_capex_raises_validation_error(self):
        with pytest.raises(ValidationError):
            UtilityBenchmark(
                name="Negative CapEx",
                operating_companies="Test Co",
                benchmark_unit="SCCT",
                regulatory_docket="Docket 123",
                installed_capex_per_kw=-500.0,
                levelized_fcr=0.09,
                fom_per_kw_yr=20.0,
            )


class TestDataFrameProjectionsAndCLI:
    """Validate DataFrame projection generation, columns, and CLI execution."""

    def setup_method(self):
        self.model = SERCCapacityModel()

    def test_get_projection_dataframe_shape_and_columns(self):
        """Verify DataFrame contract for start_year=2025 to end_year=2050."""
        df = self.model.get_projection(
            start_year=2025,
            end_year=2050,
            currency="nominal",
            utility="all",
            include_seasonal=True,
        )
        assert isinstance(df, pd.DataFrame)
        # 4 utilities * 26 years = 104 rows
        assert len(df) == 4 * 26

        expected_columns = [
            "year",
            "utility",
            "operating_companies",
            "benchmark_unit",
            "currency",
            "inflation_factor",
            "installed_capex_per_kw",
            "levelized_fcr",
            "annual_capital_recovery_per_kw_yr",
            "fom_per_kw_yr",
            "gross_ecc_per_kw_yr",
            "regulatory_docket",
            "winter_capacity_value_per_kw_season",
            "summer_capacity_value_per_kw_season",
        ]
        for col in expected_columns:
            assert col in df.columns, f"Missing column: {col}"

    def test_formal_citation_contains_key_regulatory_dockets(self):
        """Verify that get_formal_citation() includes GPSC, NCUC, and TVA references."""
        citation = self.model.get_formal_citation()
        assert "GPSC Docket No. 44280" in citation
        assert "APSC Docket No. 33201" in citation
        assert "NCUC Docket No. E-100 Sub 190" in citation
        assert "TVA" in citation
        assert "Levelized Fixed Revenue Requirement" in citation

    def test_cli_export_execution(self):
        """Test CLI command execution and CSV output writing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "test_serc_export.csv")
            cmd = [
                sys.executable,
                "serc_capacity_cost.py",
                "--export-csv",
                csv_path,
                "--currency",
                "nominal",
                "--start-year",
                "2025",
                "--end-year",
                "2030",
                "--print-year",
                "2030",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            assert os.path.exists(csv_path)
            exported_df = pd.read_csv(csv_path)
            assert len(exported_df) == 4 * (2030 - 2025 + 1)
            assert "Exported" in result.stdout
            assert "YEAR 2030 (NOMINAL)" in result.stdout


class TestStateCapacityBenchmarkDefaults:
    """Validate state-dependent company capacity cost defaults and 2+ utility prompt behavior."""

    def test_single_utility_states_default_to_company(self):
        # Georgia -> Southern Company (Georgia Power) $141.22
        ga_info = get_state_capacity_benchmark(["GA"])
        assert ga_info["has_multiple"] is False
        assert ga_info["default_utility"] == "Southern Company"
        assert pytest.approx(ga_info["default_cap_value"], abs=1e-2) == 141.22
        assert "Southern Company" in ga_info["default_preset"]

        # Tennessee -> TVA $115.12
        tn_info = get_state_capacity_benchmark("TN")
        assert tn_info["has_multiple"] is False
        assert tn_info["default_utility"] == "Tennessee Valley Authority"
        assert pytest.approx(tn_info["default_cap_value"], abs=1e-2) == 115.12
        assert "TVA" in tn_info["default_preset"]

        # North Carolina -> Duke Energy Carolinas & Progress $130.35
        nc_info = get_state_capacity_benchmark(["NC"])
        assert nc_info["has_multiple"] is False
        assert nc_info["default_utility"] == "Duke Energy Carolinas & Progress"
        assert pytest.approx(nc_info["default_cap_value"], abs=1e-2) == 130.35
        assert "Duke Energy" in nc_info["default_preset"]

    def test_multi_utility_states_default_to_composite_with_prompt(self):
        # Alabama -> 2 major utilities (Alabama Power & TVA) -> Default $129.76 with prompt
        al_info = get_state_capacity_benchmark(["AL"])
        assert al_info["has_multiple"] is True
        assert al_info["default_utility"] == "SERC Weighted Composite"
        assert pytest.approx(al_info["default_cap_value"], abs=1e-2) == 129.76
        assert al_info["prompt_message"] is not None
        assert "Alabama is served by 2 major utilities" in al_info["prompt_message"]
        # Check utility options available to user
        options = al_info["utility_options"]
        assert any("Alabama Power" in k for k in options)
        assert any("Tennessee Valley Authority" in k for k in options)
        assert any("SERC Weighted Composite" in k for k in options)

        # South Carolina -> 2+ utilities -> Default $129.76 with prompt
        sc_info = get_state_capacity_benchmark(["SC"])
        assert sc_info["has_multiple"] is True
        assert pytest.approx(sc_info["default_cap_value"], abs=1e-2) == 129.76
        assert "South Carolina" in sc_info["prompt_message"]

        # Mississippi -> 3 utilities -> Default $129.76 with prompt
        ms_info = get_state_capacity_benchmark(["MS"])
        assert ms_info["has_multiple"] is True
        assert pytest.approx(ms_info["default_cap_value"], abs=1e-2) == 129.76
        assert any("Entergy" in k for k in ms_info["utility_options"])

        # Florida -> Multiple utilities -> Default $129.76
        fl_info = get_state_capacity_benchmark(["FL"])
        assert fl_info["has_multiple"] is True
        assert pytest.approx(fl_info["default_cap_value"], abs=1e-2) == 129.76

        # Multi-state portfolio (e.g. AL + GA) -> Default $129.76 with prompt
        multi_info = get_state_capacity_benchmark(["AL", "GA"])
        assert multi_info["has_multiple"] is True
        assert multi_info["default_utility"] == "SERC Weighted Composite"
        assert pytest.approx(multi_info["default_cap_value"], abs=1e-2) == 129.76
        assert "spans 2 states" in multi_info["prompt_message"]

    def test_recalculate_refresh_script_execution(self):
        """Test recalculate script running to fetch and update latest benchmark projections."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_csv = os.path.join(tmpdir, "refreshed_capacity.csv")
            res = refresh_capacity_benchmarks(export_csv_path=test_csv, annual_inflation_rate=0.022)
            assert res["status"] == "success"
            assert res["records_generated"] == 104
            assert os.path.exists(test_csv)
            # Verify Southern Company in updated benchmarks
            so_bm = res["benchmarks"]["Southern Company"]
            assert pytest.approx(so_bm["gross_ecc_real_2024"], abs=1e-2) == 141.22
            assert pytest.approx(so_bm["gross_ecc_nominal_2040"], abs=1e-2) == 200.04


class TestAnnualCapacitySavingsAndMultiYearIntegration:
    """Validate annual capacity savings/costs accounting and multi-year trajectory schedule."""

    def test_positive_load_reduction_gives_avoided_capacity_savings(self):
        # 8,760 hours with 10 kW reduction in every hour, uniform CWFT
        load_red = np.full(8760, 10.0)
        cwft = np.full(8760, 1.0 / 8760.0)
        cap_val = 129.76

        res = calculate_annual_capacity_savings(load_red, cwft, cap_val)
        assert pytest.approx(res["credited_peak_kw"], abs=1e-3) == 10.0
        assert pytest.approx(res["accredited_capacity_kw"], abs=1e-3) == 10.0
        assert pytest.approx(res["annual_gen_cap_savings_usd"], abs=1e-2) == 1297.60
        assert res["is_cost"] is False
        assert res["label"] == "Annual Capacity Value Savings"

    def test_negative_load_reduction_gives_annual_capacity_cost(self):
        # Negative load reduction (e.g. +10 kW load increase during peak hours)
        load_red = np.full(8760, -10.0)
        cwft = np.full(8760, 1.0 / 8760.0)
        cap_val = 141.22  # Southern Company

        res = calculate_annual_capacity_savings(load_red, cwft, cap_val)
        assert pytest.approx(res["credited_peak_kw"], abs=1e-3) == -10.0
        assert pytest.approx(res["accredited_capacity_kw"], abs=1e-3) == -10.0
        assert pytest.approx(res["annual_gen_cap_savings_usd"], abs=1e-2) == -1412.20
        assert res["is_cost"] is True
        assert res["label"] == "Annual Capacity Cost"

    def test_seasonal_capacity_adjustment_breakdown(self):
        # Create timestamps for full 8,760 year
        dts = pd.date_range("2024-01-01 00:00", periods=8760, freq="h")
        load_red = np.full(8760, 5.0)
        cwft = np.full(8760, 1.0 / 8760.0)
        model = SERCCapacityModel()
        seas_dict = model.calculate_seasonal_capacity_value(gross_ecc=129.76, winter_accreditation_ratio=1.15)

        res = calculate_annual_capacity_savings(
            load_red, cwft, cap_value=129.76, seasonal_adjustment=seas_dict, datetime_series=dts
        )
        assert res["seasonal_breakdown"] is not None
        assert "winter_savings_usd" in res["seasonal_breakdown"]
        assert "summer_savings_usd" in res["seasonal_breakdown"]
        assert res["seasonal_breakdown"]["winter_capacity_value_rate"] > res["seasonal_breakdown"]["summer_capacity_value_rate"]

    def test_multi_year_capacity_cost_schedule_integration(self):
        # 3 year asset life with schedule: Year 1 = $130, Year 2 = $140, Year 3 = $150
        asset_life = 3
        start_year = 2025
        sched = {2025: 130.0, 2026: 140.0, 2027: 150.0}

        energy_prices = {
            2025: np.full(8760, 40.0),
            2026: np.full(8760, 42.0),
            2027: np.full(8760, 45.0),
        }
        load_red = np.full(8760, 10.0)  # 10 kW reduction
        cwft = np.full(8760, 1.0 / 8760.0)
        pcaf = np.full(8760, 1.0 / 8760.0)

        res = calculate_multi_year_avoided_costs_and_npv(
            asset_life=asset_life,
            start_year=start_year,
            interpolated_energy_prices=energy_prices,
            load_reduction=load_red,
            cwft_array=cwft,
            pcaf_array=pcaf,
            cap_value=100.0,  # fallback scalar
            trans_value=0.0,
            dist_value=0.0,
            carbon_tax=0.0,
            discount_rate=7.0,
            customer_discount_rate=7.0,
            degradation_rate=0.0,
            annual_lost_revenue_yr1=500.0,
            retail_escalation_rate=0.0,
            capacity_cost_schedule=sched,
        )

        df = res["cash_flow_df"]
        assert "Unit_Capacity_Cost_per_kW_yr" in df.columns
        assert list(df["Unit_Capacity_Cost_per_kW_yr"].values) == [130.0, 140.0, 150.0]
        # Gen capacity savings: 10 kW * unit_price
        assert pytest.approx(df["Gen_Capacity_Savings"].iloc[0], abs=1e-2) == 1300.0
        assert pytest.approx(df["Gen_Capacity_Savings"].iloc[1], abs=1e-2) == 1400.0
        assert pytest.approx(df["Gen_Capacity_Savings"].iloc[2], abs=1e-2) == 1500.0
