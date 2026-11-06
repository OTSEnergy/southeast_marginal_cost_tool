"""
serc_capacity_cost.py -- SERC Regional Capacity Cost & Economic Carrying Cost Module
=====================================================================================

Calculates and exports the annual Economic Carrying Cost (Gross ECC / CONE) and
avoided cost of generation capacity ($/kW-year) across Southeast / SERC utilities
for long-term demand-side management (DSM) and marginal cost valuation.

Regulatory & Analytical Framework:
    Implements the Levelized Fixed Revenue Requirement (LFRR) methodology derived
    from approved Southeast utility Integrated Resource Plans (IRPs) and state
    avoided-cost dockets:
    
    1. Southern Company (Georgia Power / Alabama Power):
       - Benchmark Unit: 2x GE 7HA.02 SCCT
       - Installed CapEx: $1,110/kW (overnight + interconnection)
       - Approved LFCR: 10.20%
       - Fixed O&M + Gas Transport Reservation: $28.00/kW-yr
       - Docket: GPSC Docket No. 44280 / APSC Docket No. 33201
       
    2. Duke Energy Carolinas & Progress:
       - Benchmark Unit: Simple-Cycle F-Frame CT
       - Installed CapEx: $1,075/kW
       - Approved LFCR: 9.80%
       - Fixed O&M + Gas Transport Reservation: $25.00/kW-yr
       - Docket: NCUC Docket No. E-100 Sub 190 (2024 Carolinas Resource Plan)
       
    3. Tennessee Valley Authority (TVA):
       - Benchmark Unit: SCCT Peaker Addition
       - Installed CapEx: $1,035/kW
       - Approved LFCR: 8.90% (Public Power tax-exempt capital structure)
       - Fixed Non-Fuel O&M: $23.00/kW-yr
       - Docket: TVA 2019/2024 IRP Supply-Side Resource Assessment
       
    4. SERC Weighted Composite:
       - Installed CapEx: $1,080/kW | LFCR: 9.70% | FOM: $25.00/kW-yr
       - Capacity-weighted regional benchmark across Southeast states.

Annual Carrying Cost Formulation:
    Annual Capital Recovery ($/kW-yr) = Installed_CapEx * LFCR
    Gross ECC ($/kW-yr) = Annual Capital Recovery + Fixed_O&M
    Future Nominal Escalation = Base_Cost * (1 + inflation_rate) ^ (Year - Base_Year)
    Seasonal Value ($/kW-season) adjusted for winter vs. summer ambient turbine derate (default 1.15x).
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, List, Literal, Optional, Union

import pandas as pd
try:
    from pydantic import BaseModel, Field, field_validator, ValidationError
except (ImportError, ModuleNotFoundError):
    class ValidationError(ValueError):
        """Fallback validation error when pydantic is not installed."""
        pass

    class BaseModel:
        """Lightweight fallback base model using standard library."""
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
            if hasattr(self, "__post_init__"):
                self.__post_init__()

        def dict(self):
            return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}

        def model_dump(self):
            return self.dict()

    def Field(default=..., description=None, gt=None, ge=None, lt=None, le=None):
        return default

    def field_validator(*args, **kwargs):
        def decorator(fn):
            return fn
        return decorator


# ==============================================================================
# PYDANTIC DATA MODELS
# ==============================================================================

class UtilityBenchmark(BaseModel):
    """
    Data model representing an empirical utility SCCT capacity anchor benchmark.
    All cost metrics are defined in constant base year dollars (default 2024$).
    """
    name: str = Field(..., description="Standard identifier for utility or composite")
    operating_companies: str = Field(..., description="Operating utility companies or reliability jurisdiction")
    benchmark_unit: str = Field(..., description="Specific technology configuration and prime mover")
    regulatory_docket: str = Field(..., description="Authorizing state commission docket or public power assessment")
    base_year: int = Field(default=2024, description="Base dollar year for constant real parameters")
    installed_capex_per_kw: float = Field(..., gt=0, description="Overnight capital + firm grid interconnection ($/kW)")
    levelized_fcr: float = Field(..., gt=0.0, lt=1.0, description="Approved Levelized Fixed Charge Rate as decimal (e.g., 0.102 for 10.2%)")
    fom_per_kw_yr: float = Field(..., ge=0, description="Fixed Non-Fuel O&M + firm pipeline reservation ($/kW-yr)")
    notes: Optional[str] = Field(default=None, description="Regulatory and engineering context")

    @field_validator("levelized_fcr")
    @classmethod
    def validate_fcr(cls, v: float) -> float:
        if v >= 1.0 or v <= 0.0:
            raise ValueError(f"levelized_fcr must be a fraction between 0.0 and 1.0; received {v}")
        return v

    def __post_init__(self):
        capex = getattr(self, "installed_capex_per_kw", None)
        if capex is not None and capex <= 0:
            raise ValidationError(f"installed_capex_per_kw must be positive; received {capex}")
        fcr = getattr(self, "levelized_fcr", None)
        if fcr is not None and (fcr >= 1.0 or fcr <= 0.0):
            raise ValidationError(f"levelized_fcr must be a fraction between 0.0 and 1.0; received {fcr}")

    @property
    def annual_capital_recovery_per_kw_yr(self) -> float:
        """Annual Capital Recovery ($/kW-yr) = Installed_CapEx * LFCR."""
        return self.installed_capex_per_kw * self.levelized_fcr

    @property
    def gross_ecc_per_kw_yr(self) -> float:
        """Gross Economic Carrying Cost ($/kW-yr) = Annual Capital Recovery + Fixed O&M."""
        return self.annual_capital_recovery_per_kw_yr + self.fom_per_kw_yr


class CapacityCostProjection(BaseModel):
    """
    Annual capacity cost projection record for a given delivery year and currency convention.
    """
    year: int = Field(..., description="Projection planning year (e.g. 2025 to 2050)")
    utility: str = Field(..., description="Utility benchmark name")
    benchmark_unit: str = Field(..., description="Benchmark unit technology")
    currency: str = Field(..., description="'real_2024' or 'nominal'")
    inflation_factor: float = Field(default=1.0, description="Cumulative inflation escalation factor relative to base year")
    installed_capex_per_kw: float = Field(..., description="Installed CapEx in projection currency ($/kW)")
    annual_capital_recovery_per_kw_yr: float = Field(..., description="Annual Capital Recovery ($/kW-yr)")
    fom_per_kw_yr: float = Field(..., description="Fixed O&M in projection currency ($/kW-yr)")
    gross_ecc_per_kw_yr: float = Field(..., description="Gross Economic Carrying Cost ($/kW-yr)")
    seasonal_winter_value_per_kw_season: Optional[float] = Field(default=None, description="Winter seasonal capacity value ($/kW-season)")
    seasonal_summer_value_per_kw_season: Optional[float] = Field(default=None, description="Summer seasonal capacity value ($/kW-season)")
    regulatory_docket: Optional[str] = Field(default=None, description="Regulatory docket or authority citation")


# ==============================================================================
# NREL ATB COMBUSTION TURBINE (CT) CAPITAL COST TRAJECTORY INDEX
# ==============================================================================
# Overnight capital cost index derived from NREL ATB 2024/2025 Natural Gas CT
# Moderate scenario (2024 Base Year = 1.0000).
# Captures technology learning and mature turbine manufacturing cost drift over time.
NREL_ATB_CT_CAPITAL_COST_INDEX: Dict[int, float] = {
    2024: 1.0000,
    2025: 0.9989,
    2026: 0.9978,
    2027: 0.9967,
    2028: 0.9956,
    2029: 0.9945,
    2030: 0.9934,
    2031: 0.9923,
    2032: 0.9911,
    2033: 0.9900,
    2034: 0.9889,
    2035: 0.9877,
    2036: 0.9866,
    2037: 0.9854,
    2038: 0.9843,
    2039: 0.9831,
    2040: 0.9820,
    2041: 0.9808,
    2042: 0.9796,
    2043: 0.9784,
    2044: 0.9772,
    2045: 0.9760,
    2046: 0.9748,
    2047: 0.9736,
    2048: 0.9724,
    2049: 0.9712,
    2050: 0.9700,
}


def get_nrel_atb_ct_capital_cost_index(year: int) -> float:
    """
    Return the NREL ATB Combustion Turbine capital cost index relative to base year 2024.

    Parameters
    ----------
    year : int
        Calendar year.

    Returns
    -------
    float
        Capital cost index multiplier (e.g. 1.000 in 2024, 0.9934 in 2030, 0.9700 in 2050).
    """
    if year in NREL_ATB_CT_CAPITAL_COST_INDEX:
        return NREL_ATB_CT_CAPITAL_COST_INDEX[year]
    if year < 2024:
        return 1.0
    return max(0.85, 0.9700 - (year - 2050) * 0.0012)


# ==============================================================================
# CORE SERC CAPACITY MODEL
# ==============================================================================

class SERCCapacityModel:
    """
    Core calculator for SERC / Southeast regional avoided capacity costs.
    
    Provides annual and seasonal carrying cost projections (2025-2050) across
    individual utilities and the SERC weighted composite benchmark.
    """

    # Empirical baselines anchored in 2024 Southeast IRP dockets (2024$ Real)
    BENCHMARKS: Dict[str, UtilityBenchmark] = {
        "Southern Company": UtilityBenchmark(
            name="Southern Company",
            operating_companies="Georgia Power / Alabama Power",
            benchmark_unit="2x GE 7HA.02 SCCT",
            regulatory_docket="GPSC Docket No. 44160 (2022 IRP) / GPSC Docket No. 44280 (2022 Rate Case) & APSC Docket No. 33201",
            base_year=2024,
            installed_capex_per_kw=1110.0,
            levelized_fcr=0.102,
            fom_per_kw_yr=28.00,
            notes="Next planned peaking unit: 2x GE 7HA.02 simple-cycle combustion turbines (Plant Yates/Plant Barry expansions); includes firm natural gas pipeline reservation. GPSC Docket 44160 approved resource capacity additions; Docket 44280 establishes base rate cost-of-service parameters.",
        ),
        "Duke Energy Carolinas & Progress": UtilityBenchmark(
            name="Duke Energy Carolinas & Progress",
            operating_companies="Duke Energy Carolinas & Duke Energy Progress",
            benchmark_unit="Simple-Cycle F-Frame CT",
            regulatory_docket="NCUC Docket No. E-100 Sub 190 (2024 Carolinas Resource Plan / Carbon Plan)",
            base_year=2024,
            installed_capex_per_kw=1075.0,
            levelized_fcr=0.098,
            fom_per_kw_yr=25.00,
            notes="Simple-cycle F-Frame combustion turbine additions approved under the Carolinas Resource Plan; includes firm pipeline transport and network upgrades.",
        ),
        "Tennessee Valley Authority": UtilityBenchmark(
            name="Tennessee Valley Authority",
            operating_companies="TVA Power System (Direct / LPCs)",
            benchmark_unit="SCCT Peaker Addition",
            regulatory_docket="TVA 2019/2024 Integrated Resource Plan, Supply-Side Resource Assessment",
            base_year=2024,
            installed_capex_per_kw=1035.0,
            levelized_fcr=0.089,
            fom_per_kw_yr=23.00,
            notes="SCCT capacity additions leveraging federal public power tax-exempt debt financing structure.",
        ),
        "SERC Weighted Composite": UtilityBenchmark(
            name="SERC Weighted Composite",
            operating_companies="SERC Regional Weighted Average",
            benchmark_unit="SERC Composite SCCT Peaker",
            regulatory_docket="SERC Southeast Regional IRP Composite Weighted Average (GA, AL, NC, SC, TN)",
            base_year=2024,
            installed_capex_per_kw=1080.0,
            levelized_fcr=0.097,
            fom_per_kw_yr=25.00,
            notes="Regional screening proxy composite benchmark representative of the Southeast reliability footprint (weights: ~35% Southern Co, ~30% Duke Carolinas, ~25% TVA, ~10% other SERC). CapEx $1,080/kW, FCR 9.7%, FOM $25/kW-yr.",
        ),
        "NREL ATB 2025": UtilityBenchmark(
            name="NREL ATB 2025",
            operating_companies="NREL Annual Technology Baseline (National Benchmark)",
            benchmark_unit="Natural Gas CT — F-Class (Moderate)",
            regulatory_docket="NREL 2025 Annual Technology Baseline (2023$ Base; atb.nrel.gov)",
            base_year=2024,
            installed_capex_per_kw=1105.80,
            levelized_fcr=0.0820,
            fom_per_kw_yr=26.60,
            notes="NREL ATB 2025 Natural Gas CT Moderate scenario ($1,105.80/kW CAPEX, $26.60/kW-yr FOM). Note: ATB reports conventional gas in 2023$ with IPP/merchant financing; 8.20% FCR reflects synthesized regulated utility financing (~7.16% WACC, 30-yr life, MACRS tax shield) yielding $117.28/kW-yr ECC.",
        ),
    }

    # Normalized alias mapping for ergonomic lookups
    ALIAS_MAP: Dict[str, str] = {
        "southern company": "Southern Company",
        "southern": "Southern Company",
        "georgia power": "Southern Company",
        "alabama power": "Southern Company",
        "so": "Southern Company",
        "duke energy carolinas & progress": "Duke Energy Carolinas & Progress",
        "duke energy": "Duke Energy Carolinas & Progress",
        "duke": "Duke Energy Carolinas & Progress",
        "dec": "Duke Energy Carolinas & Progress",
        "dep": "Duke Energy Carolinas & Progress",
        "tennessee valley authority": "Tennessee Valley Authority",
        "tva": "Tennessee Valley Authority",
        "serc weighted composite": "SERC Weighted Composite",
        "serc composite": "SERC Weighted Composite",
        "serc": "SERC Weighted Composite",
        "composite": "SERC Weighted Composite",
        "nrel atb 2025": "NREL ATB 2025",
        "nlr / nrel atb 2025": "NREL ATB 2025",
        "nlr atb 2025": "NREL ATB 2025",
        "nrel atb": "NREL ATB 2025",
        "atb 2025": "NREL ATB 2025",
        "atb": "NREL ATB 2025",
        "nlr": "NREL ATB 2025",
    }

    def __init__(
        self,
        annual_inflation_rate: float = 0.022,
        base_year: int = 2024,
        benchmarks: Optional[Dict[str, UtilityBenchmark]] = None,
    ):
        """
        Initialize the SERC capacity valuation model.
        
        Parameters
        ----------
        annual_inflation_rate : float
            Annual escalation rate for nominal dollar compounding (default 2.2% GDP deflator).
        base_year : int
            Base dollar year of the empirical benchmarks (default 2024).
        benchmarks : Optional[Dict[str, UtilityBenchmark]]
            Optional override for the empirical utility benchmarks dict.
        """
        self.annual_inflation_rate = annual_inflation_rate
        self.base_year = base_year
        self.benchmarks = benchmarks or dict(self.BENCHMARKS)

    def resolve_utility_name(self, utility: str) -> str:
        """Resolve a case-insensitive or abbreviated utility string to canonical name."""
        cleaned = utility.strip().lower()
        if cleaned in self.ALIAS_MAP:
            return self.ALIAS_MAP[cleaned]
        for key in self.benchmarks:
            if cleaned == key.lower():
                return key
        raise KeyError(
            f"Utility '{utility}' not recognized. Available: {list(self.benchmarks.keys())}"
        )

    def get_benchmark(self, utility: str) -> UtilityBenchmark:
        """Retrieve the UtilityBenchmark instance for a given utility."""
        canonical = self.resolve_utility_name(utility)
        return self.benchmarks[canonical]

    def calculate_ecc(
        self,
        utility: str = "SERC Weighted Composite",
        year: int = 2024,
        currency: Literal["real_2024", "nominal"] = "real_2024",
        capex_override: Optional[float] = None,
        lfcr_override: Optional[float] = None,
        fom_override: Optional[float] = None,
    ) -> Dict[str, float]:
        """
        Calculate the annual Gross Economic Carrying Cost (ECC) for a utility and target year.

        Parameters
        ----------
        utility : str
            Utility name or composite benchmark.
        year : int
            Planning year of delivery (e.g. 2025, 2040).
        currency : Literal["real_2024", "nominal"]
            Output currency basis. If "nominal", applies compounding inflation from base_year.
        capex_override : Optional[float]
            Optional override for installed CapEx ($/kW).
        lfcr_override : Optional[float]
            Optional override for Levelized Fixed Charge Rate (decimal).
        fom_override : Optional[float]
            Optional override for Fixed O&M ($/kW-yr).

        Returns
        -------
        Dict[str, float]
            Breakdown of capital recovery, FOM, gross ECC, and inflation escalation factor.
        """
        bm = self.get_benchmark(utility)
        capex_base = capex_override if capex_override is not None else bm.installed_capex_per_kw
        lfcr = lfcr_override if lfcr_override is not None else bm.levelized_fcr
        fom_base = fom_override if fom_override is not None else bm.fom_per_kw_yr

        # Invariance check: Capital Recovery ($/kW-yr) = CapEx * LFCR
        cap_recovery_base = capex_base * lfcr
        gross_ecc_base = cap_recovery_base + fom_base

        if currency == "nominal":
            delta_years = max(0, year - self.base_year)
            inflation_factor = (1.0 + self.annual_inflation_rate) ** delta_years
        else:
            inflation_factor = 1.0

        capex_adj = capex_base * inflation_factor
        cap_recovery_adj = cap_recovery_base * inflation_factor
        fom_adj = fom_base * inflation_factor
        gross_ecc_adj = gross_ecc_base * inflation_factor

        return {
            "year": float(year),
            "inflation_factor": inflation_factor,
            "installed_capex_per_kw": capex_adj,
            "annual_capital_recovery_per_kw_yr": cap_recovery_adj,
            "fom_per_kw_yr": fom_adj,
            "gross_ecc_per_kw_yr": gross_ecc_adj,
        }

    def calculate_seasonal_capacity_value(
        self,
        gross_ecc: float,
        winter_accreditation_ratio: float = 1.15,
        summer_accreditation_ratio: float = 1.00,
        winter_weight: float = 0.50,
        summer_weight: float = 0.50,
        normalize_to_annual: bool = True,
    ) -> Dict[str, float]:
        """
        Calculate Seasonal Capacity Value ($/kW-season) adjusted for winter vs. summer
        ambient turbine derate / Effective Load Carrying Capability (ELCC).

        In cold ambient conditions (winter), denser air increases gas turbine mass flow
        and mechanical output, yielding an accredited rating of ~1.15x summer nameplate.
        This method computes the season-specific avoided capacity values based on seasonal
        allocation shares and ambient accreditation multipliers.

        Parameters
        ----------
        gross_ecc : float
            Annual Gross Economic Carrying Cost ($/kW-yr).
        winter_accreditation_ratio : float
            Accredited winter peaking capacity relative to summer nameplate (default 1.15).
        summer_accreditation_ratio : float
            Summer nameplate baseline rating (default 1.00).
        winter_weight : float
            Portion of annual capacity value assigned to winter peak (default 0.50).
        summer_weight : float
            Portion of annual capacity value assigned to summer peak (default 0.50).
        normalize_to_annual : bool
            When True (default), normalizes seasonal values so that the weighted sum
            (winter_weight * V_winter + summer_weight * V_summer) equals gross_ecc,
            eliminating artificial capacity expansion (107.5%) while preserving the
            1.15:1.00 relative seasonal ratio. When False, uses raw ambient multiplier.

        Returns
        -------
        Dict[str, float]
            winter_capacity_value, summer_capacity_value, and accreditation ratios.
        """
        if normalize_to_annual:
            tot_w = winter_weight + summer_weight
            nw = (winter_weight / tot_w) if tot_w > 0 else 0.5
            ns = (summer_weight / tot_w) if tot_w > 0 else 0.5
            mean_mult = (nw * winter_accreditation_ratio) + (ns * summer_accreditation_ratio)
            winter_ratio_norm = winter_accreditation_ratio / mean_mult if mean_mult > 0 else 1.0
            summer_ratio_norm = summer_accreditation_ratio / mean_mult if mean_mult > 0 else 1.0
            winter_val = gross_ecc * nw * winter_ratio_norm
            summer_val = gross_ecc * ns * summer_ratio_norm
        else:
            winter_val = gross_ecc * winter_weight * winter_accreditation_ratio
            summer_val = gross_ecc * summer_weight * summer_accreditation_ratio

        return {
            "winter_capacity_value_per_kw_season": winter_val,
            "summer_capacity_value_per_kw_season": summer_val,
            "winter_accreditation_ratio": winter_accreditation_ratio,
            "summer_accreditation_ratio": summer_accreditation_ratio,
            "winter_weight": winter_weight,
            "summer_weight": summer_weight,
            "normalized_to_annual": normalize_to_annual,
        }

    def get_projection(
        self,
        start_year: int = 2025,
        end_year: int = 2050,
        currency: Literal["real_2024", "nominal"] = "real_2024",
        utility: Optional[str] = "SERC Weighted Composite",
        include_seasonal: bool = True,
        winter_accreditation_ratio: float = 1.15,
        summer_accreditation_ratio: float = 1.00,
        winter_weight: float = 0.50,
        summer_weight: float = 0.50,
        capacity_escalation_adder: float = 0.0,
        base_cost_override: Optional[float] = None,
        capex_override: Optional[float] = None,
        lfcr_override: Optional[float] = None,
        fom_override: Optional[float] = None,
        normalize_seasonal: bool = True,
        apply_atb_tech_index: bool = True,
    ) -> pd.DataFrame:
        """
        Generate a multi-year capacity cost projection DataFrame.

        Parameters
        ----------
        start_year : int
            First projection year (default 2025).
        end_year : int
            Final projection year (default 2050).
        currency : Literal["real_2024", "nominal"]
            Currency basis ("real_2024" or "nominal").
        utility : Optional[str]
            Utility identifier or "all" to project all empirical benchmarks.
        include_seasonal : bool
            Whether to compute and include seasonal winter/summer values.
        winter_accreditation_ratio : float
            Winter accreditation ratio vs. summer nameplate (default 1.15).
        summer_accreditation_ratio : float
            Summer accreditation ratio (default 1.00).
        winter_weight : float
            Winter seasonal allocation factor (default 0.50).
        summer_weight : float
            Summer seasonal allocation factor (default 0.50).
        capacity_escalation_adder : float
            Incremental annual escalation rate (%/yr) applied on top of the
            underlying baseline carrying cost / inflation trajectory. Default 0.0.
        base_cost_override : Optional[float]
            Optional user-specified starting Year 1 $/kW-yr capacity value (e.g. from
            direct scalar input or CT Builder calculation). When provided, the projection
            faithfully anchors Year 1 at this value rather than reverting to hardcoded benchmarks.
        capex_override : Optional[float]
            Optional override for installed CapEx ($/kW).
        lfcr_override : Optional[float]
            Optional override for Levelized Fixed Charge Rate (decimal).
        fom_override : Optional[float]
            Optional override for Fixed O&M ($/kW-yr).
        normalize_seasonal : bool
            Whether seasonal values should be normalized so their sum equals gross ECC (default True).

        Returns
        -------
        pd.DataFrame
            Structured projection table with annual and seasonal metrics.
        """
        currency_norm = currency.lower().strip()
        if currency_norm in ["real", "real_2024", "2024", "2024$"]:
            curr_tag = "real_2024"
        elif currency_norm in ["nominal", "nominal$", "nom"]:
            curr_tag = "nominal"
        else:
            raise ValueError(f"currency must be 'real_2024' or 'nominal'; received '{currency}'")

        if utility is None or utility.lower() in ["all", "all_utilities", "all_benchmarks"]:
            target_utilities = list(self.benchmarks.keys())
        else:
            target_utilities = [self.resolve_utility_name(utility)]

        records: List[Dict[str, Union[int, float, str, None]]] = []

        for yr in range(start_year, end_year + 1):
            adder_factor = (1.0 + (capacity_escalation_adder / 100.0)) ** (yr - start_year)
            tech_index = (
                get_nrel_atb_ct_capital_cost_index(yr) / get_nrel_atb_ct_capital_cost_index(start_year)
                if apply_atb_tech_index else 1.0
            )
            for u in target_utilities:
                bm = self.get_benchmark(u)

                if base_cost_override is not None:
                    # User-specified starting Year 1 cost ($/kW-yr)
                    delta_years = max(0, yr - start_year)
                    inf_factor = ((1.0 + self.annual_inflation_rate) ** delta_years) if curr_tag == "nominal" else 1.0
                    scale_ratio = (base_cost_override / bm.gross_ecc_per_kw_yr) if bm.gross_ecc_per_kw_yr > 0 else 1.0

                    base_cap_rec = bm.annual_capital_recovery_per_kw_yr * scale_ratio
                    base_fom = bm.fom_per_kw_yr * scale_ratio

                    ann_cap_rec = round(base_cap_rec * tech_index * inf_factor * adder_factor, 2)
                    fom_val = round(base_fom * inf_factor * adder_factor, 2)
                    gross_ecc = round(ann_cap_rec + fom_val, 2)
                    installed_capex = round(
                        (ann_cap_rec / bm.levelized_fcr) if bm.levelized_fcr > 0 else (bm.installed_capex_per_kw * scale_ratio * tech_index * inf_factor * adder_factor),
                        2
                    )
                else:
                    capex_base = capex_override if capex_override is not None else bm.installed_capex_per_kw
                    lfcr = lfcr_override if lfcr_override is not None else bm.levelized_fcr
                    fom_base = fom_override if fom_override is not None else bm.fom_per_kw_yr

                    delta_years = max(0, yr - self.base_year)
                    inf_factor = ((1.0 + self.annual_inflation_rate) ** delta_years) if curr_tag == "nominal" else 1.0

                    base_cap_rec = capex_base * lfcr
                    ann_cap_rec = round(base_cap_rec * tech_index * inf_factor * adder_factor, 2)
                    fom_val = round(fom_base * inf_factor * adder_factor, 2)
                    gross_ecc = round(ann_cap_rec + fom_val, 2)
                    installed_capex = round(
                        (ann_cap_rec / lfcr) if lfcr > 0 else (capex_base * tech_index * inf_factor * adder_factor),
                        2
                    )

                row: Dict[str, Union[int, float, str, None]] = {
                    "year": yr,
                    "utility": bm.name,
                    "operating_companies": bm.operating_companies,
                    "benchmark_unit": bm.benchmark_unit,
                    "currency": curr_tag,
                    "inflation_factor": round(inf_factor, 6),
                    "installed_capex_per_kw": installed_capex,
                    "levelized_fcr": round(bm.levelized_fcr, 4),
                    "annual_capital_recovery_per_kw_yr": ann_cap_rec,
                    "fom_per_kw_yr": fom_val,
                    "gross_ecc_per_kw_yr": round(gross_ecc, 2),
                    "capacity_escalation_adder": capacity_escalation_adder,
                    "regulatory_docket": bm.regulatory_docket,
                }

                if include_seasonal:
                    seas = self.calculate_seasonal_capacity_value(
                        gross_ecc,
                        winter_accreditation_ratio=winter_accreditation_ratio,
                        summer_accreditation_ratio=summer_accreditation_ratio,
                        winter_weight=winter_weight,
                        summer_weight=summer_weight,
                        normalize_to_annual=normalize_seasonal,
                    )
                    row["winter_capacity_value_per_kw_season"] = round(seas["winter_capacity_value_per_kw_season"], 2)
                    row["summer_capacity_value_per_kw_season"] = round(seas["summer_capacity_value_per_kw_season"], 2)

                records.append(row)

        return pd.DataFrame(records)

        return pd.DataFrame(records)

    def get_formal_citation(self, utility: Optional[str] = None) -> str:
        """
        Return the exact legal and regulatory text citation for state commission
        and academic peer review.
        """
        header = (
            "================================================================================\n"
            "SERC REGIONAL CAPACITY COST BENCHMARK -- FORMAL REGULATORY CITATION\n"
            "================================================================================\n"
            "Methodology: Levelized Fixed Revenue Requirement (LFRR) / Economic Carrying Cost (ECC)\n"
            "Standard Formulation:\n"
            "    Annual Capital Recovery ($/kW-yr) = Installed CapEx ($/kW) * Levelized Fixed Charge Rate (LFCR)\n"
            "    Gross ECC ($/kW-yr) = Annual Capital Recovery + Fixed Non-Fuel O&M (FOM)\n"
            f"    Nominal Compounding: Cost_t = Cost_2024 * (1 + i)^(t - 2024), where i = {self.annual_inflation_rate * 100:.1f}% annual GDP Deflator\n"
            "--------------------------------------------------------------------------------\n"
        )

        entries = []
        target_keys = (
            [self.resolve_utility_name(utility)]
            if utility and utility.lower() not in ["all", "all_benchmarks"]
            else list(self.benchmarks.keys())
        )

        for key in target_keys:
            bm = self.benchmarks[key]
            cap_rec = bm.annual_capital_recovery_per_kw_yr
            ecc = bm.gross_ecc_per_kw_yr
            entry = (
                f"* {bm.name} ({bm.operating_companies}):\n"
                f"    - Benchmark Technology: {bm.benchmark_unit}\n"
                f"    - Overnight + Interconnection CapEx: ${bm.installed_capex_per_kw:,.2f}/kW (2024$ Real)\n"
                f"    - Approved Levelized Fixed Charge Rate (LFCR): {bm.levelized_fcr * 100:.2f}%\n"
                f"    - Fixed Non-Fuel O&M + Gas Transport: ${bm.fom_per_kw_yr:,.2f}/kW-yr\n"
                f"    - Gross Economic Carrying Cost: ${ecc:,.2f}/kW-yr (${cap_rec:,.2f} Capital Recovery + ${bm.fom_per_kw_yr:,.2f} FOM)\n"
                f"    - Regulatory Docket: {bm.regulatory_docket}\n"
                f"    - Notes: {bm.notes or 'None'}\n"
            )
            entries.append(entry)

        footer = (
            "--------------------------------------------------------------------------------\n"
            "Seasonal & Ambient Correction:\n"
            "    - Winter Ambient Turbine Derate Multiplier: 1.15x summer nameplate rating.\n"
            "    - Source: IEEE / ASME Gas Turbine Standards & SERC Reliability Corporation guidelines.\n"
            "================================================================================\n"
        )

        return header + "\n".join(entries) + footer



# ==============================================================================
# STATE-TO-UTILITY BENCHMARK MAPPING
# ==============================================================================

STATE_UTILITY_BENCHMARKS: Dict[str, Dict[str, Any]] = {
    "GA": {
        "utilities": ["Southern Company (Georgia Power)"],
        "default_utility": "Southern Company",
        "default_cap_value": 141.22,
        "default_preset": "Southern Company / Georgia Power IRP SCCT Benchmark",
        "has_multiple": False,
        "state_summary": "Georgia: Defaulted to Georgia Power / Southern Company IRP benchmark ($141.22/kW-yr; GPSC Docket 44280).",
        "prompt_message": None,
        "utility_options": {
            "Southern Company (Georgia Power, $141.22/kW-yr)": {
                "utility": "Southern Company",
                "cap_value": 141.22,
                "preset": "Southern Company / Georgia Power IRP SCCT Benchmark",
            },
            "SERC Weighted Composite ($129.76/kW-yr)": {
                "utility": "SERC Weighted Composite",
                "cap_value": 129.76,
                "preset": "SERC Regional SCCT Composite Benchmark (2024$ Real)",
            },
            "NLR / NREL ATB 2025: Natural Gas CT Benchmark ($117.28/kW-yr)": {
                "utility": "NREL ATB 2025",
                "cap_value": 117.28,
                "preset": "NLR / NREL ATB 2025: Natural Gas CT Benchmark (Moderate / Regulated Utility)",
            },
        },
    },
    "TN": {
        "utilities": ["Tennessee Valley Authority (TVA)"],
        "default_utility": "Tennessee Valley Authority",
        "default_cap_value": 115.12,
        "default_preset": "TVA Capacity Expansion SCCT Benchmark",
        "has_multiple": False,
        "state_summary": "Tennessee: Defaulted to TVA IRP Supply-Side benchmark ($115.12/kW-yr; Federal Public Power debt structure).",
        "prompt_message": None,
        "utility_options": {
            "Tennessee Valley Authority (TVA, $115.12/kW-yr)": {
                "utility": "Tennessee Valley Authority",
                "cap_value": 115.12,
                "preset": "TVA Capacity Expansion SCCT Benchmark",
            },
            "SERC Weighted Composite ($129.76/kW-yr)": {
                "utility": "SERC Weighted Composite",
                "cap_value": 129.76,
                "preset": "SERC Regional SCCT Composite Benchmark (2024$ Real)",
            },
            "NLR / NREL ATB 2025: Natural Gas CT Benchmark ($117.28/kW-yr)": {
                "utility": "NREL ATB 2025",
                "cap_value": 117.28,
                "preset": "NLR / NREL ATB 2025: Natural Gas CT Benchmark (Moderate / Regulated Utility)",
            },
        },
    },
    "NC": {
        "utilities": ["Duke Energy Carolinas & Progress"],
        "default_utility": "Duke Energy Carolinas & Progress",
        "default_cap_value": 130.35,
        "default_preset": "Duke Energy Carolinas 2024 IRP SCCT Benchmark",
        "has_multiple": False,
        "state_summary": "North Carolina: Defaulted to Duke Energy Carolinas & Progress benchmark ($130.35/kW-yr; NCUC Docket E-100 Sub 190).",
        "prompt_message": None,
        "utility_options": {
            "Duke Energy Carolinas & Progress ($130.35/kW-yr)": {
                "utility": "Duke Energy Carolinas & Progress",
                "cap_value": 130.35,
                "preset": "Duke Energy Carolinas 2024 IRP SCCT Benchmark",
            },
            "SERC Weighted Composite ($129.76/kW-yr)": {
                "utility": "SERC Weighted Composite",
                "cap_value": 129.76,
                "preset": "SERC Regional SCCT Composite Benchmark (2024$ Real)",
            },
            "NLR / NREL ATB 2025: Natural Gas CT Benchmark ($117.28/kW-yr)": {
                "utility": "NREL ATB 2025",
                "cap_value": 117.28,
                "preset": "NLR / NREL ATB 2025: Natural Gas CT Benchmark (Moderate / Regulated Utility)",
            },
        },
    },
    "AL": {
        "utilities": ["Alabama Power (Southern Company)", "Tennessee Valley Authority (TVA)"],
        "default_utility": "SERC Weighted Composite",
        "default_cap_value": 129.76,
        "default_preset": "SERC Regional SCCT Composite Benchmark (2024$ Real)",
        "has_multiple": True,
        "state_summary": "Alabama: Served by 2 major utilities (Alabama Power & TVA). Defaulting to SERC Regional Composite ($129.76/kW-yr).",
        "prompt_message": "Alabama is served by 2 major utilities (Alabama Power in central/south and TVA in north AL). Using the SERC Composite default ($129.76/kW-yr); please select your utility below:",
        "utility_options": {
            "SERC Weighted Composite ($129.76/kW-yr)": {
                "utility": "SERC Weighted Composite",
                "cap_value": 129.76,
                "preset": "SERC Regional SCCT Composite Benchmark (2024$ Real)",
            },
            "Alabama Power (Southern Company, $141.22/kW-yr)": {
                "utility": "Southern Company",
                "cap_value": 141.22,
                "preset": "Southern Company / Georgia Power IRP SCCT Benchmark",
            },
            "Tennessee Valley Authority (TVA, $115.12/kW-yr)": {
                "utility": "Tennessee Valley Authority",
                "cap_value": 115.12,
                "preset": "TVA Capacity Expansion SCCT Benchmark",
            },
            "NLR / NREL ATB 2025: Natural Gas CT Benchmark ($117.28/kW-yr)": {
                "utility": "NREL ATB 2025",
                "cap_value": 117.28,
                "preset": "NLR / NREL ATB 2025: Natural Gas CT Benchmark (Moderate / Regulated Utility)",
            },
        },
    },
    "SC": {
        "utilities": ["Duke Energy Carolinas & Progress", "Dominion Energy South Carolina"],
        "default_utility": "SERC Weighted Composite",
        "default_cap_value": 129.76,
        "default_preset": "SERC Regional SCCT Composite Benchmark (2024$ Real)",
        "has_multiple": True,
        "state_summary": "South Carolina: Served by multiple utilities (Duke Energy Carolinas/Progress & Dominion Energy SC). Defaulting to SERC Composite ($129.76/kW-yr).",
        "prompt_message": "South Carolina is served by 2 or more utilities (Duke Energy and Dominion Energy SC / Santee Cooper). Using the SERC Composite default ($129.76/kW-yr); please select your utility below:",
        "utility_options": {
            "SERC Weighted Composite ($129.76/kW-yr)": {
                "utility": "SERC Weighted Composite",
                "cap_value": 129.76,
                "preset": "SERC Regional SCCT Composite Benchmark (2024$ Real)",
            },
            "Duke Energy Carolinas & Progress ($130.35/kW-yr)": {
                "utility": "Duke Energy Carolinas & Progress",
                "cap_value": 130.35,
                "preset": "Duke Energy Carolinas 2024 IRP SCCT Benchmark",
            },
            "Southern Company / Regional Interconnection ($141.22/kW-yr)": {
                "utility": "Southern Company",
                "cap_value": 141.22,
                "preset": "Southern Company / Georgia Power IRP SCCT Benchmark",
            },
            "NLR / NREL ATB 2025: Natural Gas CT Benchmark ($117.28/kW-yr)": {
                "utility": "NREL ATB 2025",
                "cap_value": 117.28,
                "preset": "NLR / NREL ATB 2025: Natural Gas CT Benchmark (Moderate / Regulated Utility)",
            },
        },
    },
    "MS": {
        "utilities": ["Mississippi Power (Southern Company)", "Tennessee Valley Authority (TVA)", "Entergy Mississippi"],
        "default_utility": "SERC Weighted Composite",
        "default_cap_value": 129.76,
        "default_preset": "SERC Regional SCCT Composite Benchmark (2024$ Real)",
        "has_multiple": True,
        "state_summary": "Mississippi: Served by 3 major utilities (Mississippi Power, Entergy MS, & TVA). Defaulting to SERC Composite ($129.76/kW-yr).",
        "prompt_message": "Mississippi is served by 3 major utilities (Mississippi Power, Entergy MS, and TVA). Using the SERC Composite default ($129.76/kW-yr); please select your utility below:",
        "utility_options": {
            "SERC Weighted Composite ($129.76/kW-yr)": {
                "utility": "SERC Weighted Composite",
                "cap_value": 129.76,
                "preset": "SERC Regional SCCT Composite Benchmark (2024$ Real)",
            },
            "Mississippi Power (Southern Company, $141.22/kW-yr)": {
                "utility": "Southern Company",
                "cap_value": 141.22,
                "preset": "Southern Company / Georgia Power IRP SCCT Benchmark",
            },
            "Tennessee Valley Authority (TVA, $115.12/kW-yr)": {
                "utility": "Tennessee Valley Authority",
                "cap_value": 115.12,
                "preset": "TVA Capacity Expansion SCCT Benchmark",
            },
            "Entergy Mississippi ($102.65/kW-yr)": {
                "utility": "Entergy Mississippi",
                "cap_value": 102.65,
                "preset": "Entergy 2023/2024 IRP Peaker Benchmark",
            },
            "NLR / NREL ATB 2025: Natural Gas CT Benchmark ($117.28/kW-yr)": {
                "utility": "NREL ATB 2025",
                "cap_value": 117.28,
                "preset": "NLR / NREL ATB 2025: Natural Gas CT Benchmark (Moderate / Regulated Utility)",
            },
        },
    },
    "FL": {
        "utilities": ["Florida Power & Light (FPL)", "Duke Energy Florida", "Tampa Electric (TECO)"],
        "default_utility": "SERC Weighted Composite",
        "default_cap_value": 129.76,
        "default_preset": "SERC Regional SCCT Composite Benchmark (2024$ Real)",
        "has_multiple": True,
        "state_summary": "Florida: Served by multiple major utilities (FPL, Duke Energy FL, TECO). Defaulting to SERC Composite ($129.76/kW-yr).",
        "prompt_message": "Florida is served by multiple major utilities (FPL, Duke Energy Florida, TECO). Using the SERC Composite default ($129.76/kW-yr); please select your utility below:",
        "utility_options": {
            "SERC Weighted Composite ($129.76/kW-yr)": {
                "utility": "SERC Weighted Composite",
                "cap_value": 129.76,
                "preset": "SERC Regional SCCT Composite Benchmark (2024$ Real)",
            },
            "Duke Energy Florida / Carolinas ($130.35/kW-yr)": {
                "utility": "Duke Energy Carolinas & Progress",
                "cap_value": 130.35,
                "preset": "Duke Energy Carolinas 2024 IRP SCCT Benchmark",
            },
            "Southern Company / Gulf Interconnection ($141.22/kW-yr)": {
                "utility": "Southern Company",
                "cap_value": 141.22,
                "preset": "Southern Company / Georgia Power IRP SCCT Benchmark",
            },
            "NLR / NREL ATB 2025 CT Benchmark ($117.28/kW-yr)": {
                "utility": "NREL ATB 2025",
                "cap_value": 117.28,
                "preset": "NLR / NREL ATB 2025: Natural Gas CT Benchmark (Moderate / Regulated Utility)",
            },
        },
    },
}

DEFAULT_COMPOSITE_OPTIONS: Dict[str, Dict[str, Any]] = {
    "SERC Weighted Composite ($129.76/kW-yr)": {
        "utility": "SERC Weighted Composite",
        "cap_value": 129.76,
        "preset": "SERC Regional SCCT Composite Benchmark (2024$ Real)",
    },
    "Southern Company (Georgia Power / Alabama Power, $141.22/kW-yr)": {
        "utility": "Southern Company",
        "cap_value": 141.22,
        "preset": "Southern Company / Georgia Power IRP SCCT Benchmark",
    },
    "Duke Energy Carolinas & Progress ($130.35/kW-yr)": {
        "utility": "Duke Energy Carolinas & Progress",
        "cap_value": 130.35,
        "preset": "Duke Energy Carolinas 2024 IRP SCCT Benchmark",
    },
    "Tennessee Valley Authority (TVA, $115.12/kW-yr)": {
        "utility": "Tennessee Valley Authority",
        "cap_value": 115.12,
        "preset": "TVA Capacity Expansion SCCT Benchmark",
    },
    "NLR / NREL ATB 2025: Natural Gas CT Benchmark ($117.28/kW-yr)": {
        "utility": "NREL ATB 2025",
        "cap_value": 117.28,
        "preset": "NLR / NREL ATB 2025: Natural Gas CT Benchmark (Moderate / Regulated Utility)",
    },
}


def get_state_capacity_benchmark(states: Union[str, List[str]]) -> Dict[str, Any]:
    """
    Determine the default capacity cost benchmark and utility options based on the
    selected state(s) in the Southeast / SERC footprint.

    Rules:
    - Single-utility states (GA -> Southern Company $141.22, TN -> TVA $115.12,
      NC -> Duke Energy Carolinas & Progress $130.35) default directly to that utility.
    - States with 2 or more utilities (AL, SC, MS, FL) or multi-state portfolios
      default to the SERC Weighted Composite ($129.76/kW-yr) and provide a prompt
      for the user to select the correct utility value.
    """
    if isinstance(states, str):
        state_list = [states.strip().upper()]
    else:
        state_list = [str(s).strip().upper() for s in states if str(s).strip()]

    if not state_list:
        state_list = ["AL"]

    if len(state_list) == 1:
        st = state_list[0]
        if st in STATE_UTILITY_BENCHMARKS:
            return STATE_UTILITY_BENCHMARKS[st]
        else:
            return {
                "utilities": ["SERC Weighted Composite"],
                "default_utility": "SERC Weighted Composite",
                "default_cap_value": 129.76,
                "default_preset": "SERC Regional SCCT Composite Benchmark (2024$ Real)",
                "has_multiple": True,
                "state_summary": f"{st}: Outside core Southeast IRP anchor states; defaulting to SERC Regional Composite ($129.76/kW-yr).",
                "prompt_message": f"State '{st}' is outside the core Southeast IRP anchors. Using the SERC Composite default ($129.76/kW-yr); select specific utility if applicable:",
                "utility_options": DEFAULT_COMPOSITE_OPTIONS,
            }

    # Multi-state portfolio selected
    states_str = ", ".join(state_list)
    return {
        "utilities": ["SERC Weighted Composite"],
        "default_utility": "SERC Weighted Composite",
        "default_cap_value": 129.76,
        "default_preset": "SERC Regional SCCT Composite Benchmark (2024$ Real)",
        "has_multiple": True,
        "state_summary": f"Multi-state portfolio ({states_str}): Defaulting to SERC Regional Composite ($129.76/kW-yr).",
        "prompt_message": f"Selected portfolio spans {len(state_list)} states ({states_str}). Using the SERC Composite default ($129.76/kW-yr); please select your utility below if evaluating a specific operating jurisdiction:",
        "utility_options": DEFAULT_COMPOSITE_OPTIONS,
    }


def refresh_capacity_benchmarks(
    export_csv_path: Optional[str] = "data/serc_capacity_2025_2050.csv",
    annual_inflation_rate: float = 0.022,
) -> Dict[str, Any]:
    """
    Generate the documented analytical utility capacity cost baselines across SERC
    (Southern Company, Duke Energy, TVA, NREL ATB, Composite) and export fresh
    2025-2050 projections to disk.

    Returns
    -------
    Dict[str, Any]
        Dictionary with status, exported benchmarks summary, and file write confirmation.
    """
    model = SERCCapacityModel(annual_inflation_rate=annual_inflation_rate)
    df_nominal = model.get_projection(start_year=2025, end_year=2050, currency="nominal", utility="all")
    
    if export_csv_path:
        out_dir = os.path.dirname(os.path.abspath(export_csv_path))
        os.makedirs(out_dir, exist_ok=True)
        df_nominal.to_csv(export_csv_path, index=False)

    summary_benchmarks = {}
    for name, bm in model.benchmarks.items():
        ecc_2025 = model.calculate_ecc(name, year=2025, currency="nominal")
        ecc_2040 = model.calculate_ecc(name, year=2040, currency="nominal")
        summary_benchmarks[name] = {
            "installed_capex_per_kw": bm.installed_capex_per_kw,
            "levelized_fcr": bm.levelized_fcr,
            "fom_per_kw_yr": bm.fom_per_kw_yr,
            "gross_ecc_real_2024": round(bm.gross_ecc_per_kw_yr, 2),
            "gross_ecc_nominal_2025": round(ecc_2025["gross_ecc_per_kw_yr"], 2),
            "gross_ecc_nominal_2040": round(ecc_2040["gross_ecc_per_kw_yr"], 2),
        }

    return {
        "status": "success",
        "records_generated": len(df_nominal),
        "export_csv_path": export_csv_path,
        "benchmarks": summary_benchmarks,
        "message": f"Successfully exported {len(df_nominal)} reference capacity projection records across 2025-2050 at {annual_inflation_rate*100:.1f}% inflation.",
    }


# ==============================================================================
# CLI EXPORT SCRIPT ENTRYPOINT
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Calculate and export SERC Regional Capacity Cost projections (2025-2050)."
    )
    parser.add_argument(
        "--export-csv",
        type=str,
        default=None,
        help="Target filepath to export projection CSV (e.g. data/serc_capacity_2025_2050.csv)",
    )
    parser.add_argument(
        "--currency",
        type=str,
        default="nominal",
        choices=["nominal", "real_2024"],
        help="Currency output basis: 'nominal' (compounded at 2.2%/yr) or 'real_2024' (constant 2024$)",
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=2025,
        help="Projection start year (default: 2025)",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=2050,
        help="Projection end year (default: 2050)",
    )
    parser.add_argument(
        "--utility",
        type=str,
        default="all",
        help="Utility benchmark or 'all' for all benchmarks (default: 'all')",
    )
    parser.add_argument(
        "--print-year",
        type=int,
        default=2040,
        help="Target planning year to display in console summary (default: 2040)",
    )
    parser.add_argument(
        "--citation",
        action="store_true",
        help="Print formal regulatory citation and legal authorities",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-calculate and overwrite projection data with latest regulatory baselines",
    )

    args = parser.parse_args()

    model = SERCCapacityModel()

    if args.refresh:
        res = refresh_capacity_benchmarks(export_csv_path=args.export_csv or "data/serc_capacity_2025_2050.csv")
        print(f"Refreshed capacity benchmarks: {res['message']}")
        return

    if args.citation:
        print(model.get_formal_citation(args.utility if args.utility != "all" else None))

    df = model.get_projection(
        start_year=args.start_year,
        end_year=args.end_year,
        currency=args.currency,
        utility=args.utility,
    )

    if args.export_csv:
        export_path = args.export_csv
        os.makedirs(os.path.dirname(os.path.abspath(export_path)), exist_ok=True)
        df.to_csv(export_path, index=False)
        print(f"Exported {len(df)} projection records to: {export_path}")

    # Display console summary for requested target year (default 2040)
    target_year = args.print_year
    sub_df = df[df["year"] == target_year]

    print("\n" + "=" * 78)
    print(f"SERC REGIONAL CAPACITY COST PROJECTION -- YEAR {target_year} ({args.currency.upper()})")
    print("=" * 78)
    if not sub_df.empty:
        cols_to_print = [
            "utility",
            "installed_capex_per_kw",
            "annual_capital_recovery_per_kw_yr",
            "fom_per_kw_yr",
            "gross_ecc_per_kw_yr",
            "winter_capacity_value_per_kw_season",
            "summer_capacity_value_per_kw_season",
        ]
        # Format neatly
        pd.set_option("display.max_columns", 10)
        pd.set_option("display.width", 120)
        print(sub_df[cols_to_print].to_string(index=False))
    else:
        print(f"No records found for year {target_year}.")
    print("=" * 78 + "\n")


if __name__ == "__main__":
    main()
