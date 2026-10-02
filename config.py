"""
config.py — Default Configuration, Constants & UI Styling
==========================================================

Central configuration module for the Southeast Marginal Cost Valuation Engine.
Collects hardcoded defaults, option lists, color palettes, and CSS styling
that were previously scattered across app.py.

WHAT IT DOES:
    Provides a single source of truth for:
    • Sidebar default parameter values (capacity scalars, discount rate, etc.)
    • Dropdown option lists (scenarios, planning years, weather cases, states)
    • Chart display constants (grid component definitions with colors/labels)
    • Weekly analysis window definitions
    • Custom CSS styling for the Streamlit UI

WHY IT'S SEPARATE:
    Centralizing configuration means:
    • Changing a default value or adding a new scenario requires editing one
      file instead of hunting through 1,400 lines of UI code
    • config.py can be imported by tests to verify default values
    • Future config.yaml migration is straightforward — replace this module's
      constants with a YAML loader

USED BY:
    app.py imports all constants and option lists from this module.

TESTED BY:
    tests/test_calculations.py::TestConfig
"""

# ==============================================================================
# GRID SCENARIO & PLANNING YEAR OPTIONS
# ==============================================================================

SCENARIO_OPTIONS = [
    "MidCase",
    "HighDemandGrowth",
    "LowCarbonConstraint",
    "LowDemandGrowth",
]

CAMBIUM_DOC_URL = "https://docs.nlr.gov/docs/fy25osti/93005.pdf"

SCENARIO_DESCRIPTIONS = {
    "MidCase": (
        "Central baseline projection under current federal and state policies (including the Inflation Reduction Act [IRA]). "
        "Uses moderate technology cost declines (NREL ATB) and benchmark fuel prices (EIA AEO Reference)."
    ),
    "HighDemandGrowth": (
        "High electricity demand growth driven by rapid electrification across transportation (EVs) and building space/water heating (heat pumps), "
        "along with accelerated computing, data center, and industrial load expansion. Leads to higher peak demand and capacity additions."
    ),
    "LowDemandGrowth": (
        "Low electricity demand growth characterized by slower economic expansion, modest electrification adoption, and aggressive "
        "building energy efficiency improvements. Leads to lower peak demand, lower wholesale energy prices, and deferred capacity buildout."
    ),
    "LowCarbonConstraint": (
        "Strict power sector emissions constraint targeting deep decarbonization (e.g., 95% emissions cuts by 2050). Models accelerated "
        "fossil unit retirements, rapid deployment of solar, wind, and battery storage, and significantly lower grid marginal carbon rates."
    ),
}

PLANNING_YEAR_OPTIONS = ["2025", "2030", "2035", "2040", "2045", "2050"]
DEFAULT_PLANNING_YEAR_INDEX = 1  # "2030"

WEATHER_CASE_OPTIONS = [
    "2012 (Cambium-aligned baseline)",
    "Extreme Winter",
    "Extreme Summer",
]

STATE_OPTIONS = ["AL", "GA", "FL", "TN", "MS", "NC", "SC"]
DEFAULT_STATES = ["AL"]

# Planning & Educational Use Disclaimer
TOOL_DISCLAIMER_TEXT = (
    "This tool is for planning and educational purposes only. It is meant to help "
    "guide research and product teams to understand what is treated as valuable by "
    "electric utilities in the Southeast, but is not a certified tool and uses "
    "simplifications and only publicly available data, so is not fully "
    "representative of results from true utility evaluation studies for the same technology."
)

TOOL_DISCLAIMER_HTML = (
    '<div style="margin-top: 20px; margin-bottom: 16px; padding: 12px 16px; '
    'background: #FFFBEB; border: 1px solid #FDE68A; border-left: 4px solid #F59E0B; '
    'border-radius: 6px; font-size: 0.82rem; color: #92400E; line-height: 1.5;">'
    '<div style="font-weight: 700; display: flex; align-items: center; gap: 6px; '
    'margin-bottom: 3px; font-size: 0.86rem; color: #B45309;">'
    '<span>⚠️ Planning & Educational Purpose Disclaimer</span>'
    '</div>'
    + TOOL_DISCLAIMER_TEXT +
    '</div>'
)



# ==============================================================================
# EXAMPLE BUILDING LIBRARY (pick-and-view sandbox)
# ==============================================================================
# Pre-configured, real BEopt building models a user can pick from instead of
# manually wiring up load profile paths/columns. Each entry locks the Weather
# Alignment Metadata to the model's documented weather year, since the building
# simulation and its weather file are a matched pair.
#
# Add new entries here as more example models become available (see
# docs/roadmap.md M4.3). "baseline_col"/"proposed_col" must match the column
# names produced by data_loaders.load_load_profiles_from_csv() for
# Load_Profiles_raw/ (folder mode names columns "<filename>_kW").
#
# Optional "tariff" key: set to one of the exact strings in TARIFF_OPTIONS
# (below) to lock the sidebar's Retail Tariff Structure selector to that
# tariff whenever this example is selected — so multiple variants of the
# same building (e.g. different battery dispatch strategies) are always
# compared on an identical utility rate rather than whatever the sidebar
# happened to be left on. Omit the key (or leave it None) to leave the
# tariff selector unlocked.

EXAMPLE_BUILDINGS = [
    {
        "label": "Birmingham, AL \u2014 Electric Resistance Heat vs. Heat Pump (BEopt, 2012)",
        "description": (
            "Single-family home in Birmingham, AL. Baseline uses electric resistance "
            "heating; Proposed replaces it with an air-source heat pump. Both simulated "
            "in BEopt on the same 2012 AMY weather year."
        ),
        "load_profiles_path": "Load_Profiles_raw",
        "baseline_col": "ERHeatBeOptModel_Birmingham2012_kW",
        "proposed_col": "HeatPumpBeOptModel_Birmingham2012_kW",
        "weather_year": "2012",
        "state": "AL",
        "tariff": None,
    },
    {
        "label": "Birmingham, AL — No Battery vs. 10 kWh Battery (BEopt, 2012)",
        "description": (
            "Single-family home in Birmingham, AL (default BEopt building model). Baseline "
            "has no battery; Proposed adds a 10 kWh battery with a seasonal charge/discharge "
            "strategy — winter (Dec/Jan/Feb) charges 12PM–4PM and discharges 5AM–9AM; "
            "summer (Jun/Jul/Aug) charges 2AM–6AM and discharges 4PM–8PM. Both simulated "
            "in BEopt on the same 2012 AMY weather year."
        ),
        "load_profiles_path": "Load_Profiles_raw",
        "baseline_col": "BEOptExample_NoBattery_Birmingham2012_kW",
        "proposed_col": "BEOptExample_Battery_Birmingham2012_kW",
        "weather_year": "2012",
        "state": "AL",
        "tariff": None,
    },
    {
        "label": "Birmingham, AL — No Battery vs. Balanced-Priority Battery Dispatch (BEopt, 2012)",
        "description": (
            "Single-family home in Birmingham, AL. Baseline has no battery; Proposed adds a "
            "5 kWh / 2 kW battery dispatched hour-by-hour to balance homeowner retail cost and "
            "grid avoided cost equally (percentile-rank blend of both signals). Uses a simple "
            "24-hour look-ahead, similar to a utility's day-ahead price signal: it only charges/"
            "discharges when an hour is at or near the best opportunity in the next 24 hours, so "
            "it won't drain itself on a merely-good spike right before an even bigger one. Both "
            "simulated in BEopt on the same 2012 AMY weather year."
        ),
        "load_profiles_path": "Load_Profiles_raw/Battery_Priority_Examples",
        "baseline_col": "Baseline_NoBattery_Birmingham2012_kW",
        "proposed_col": "Battery_Balanced_Birmingham2012_kW",
        "weather_year": "2012",
        "state": "AL",
        "tariff": "Alabama Power - Rate RTA-E (Residential Time Advantage - Energy Only)",
    },
    {
        "label": "Birmingham, AL — No Battery vs. Homeowner-Priority Battery Dispatch (BEopt, 2012)",
        "description": (
            "Single-family home in Birmingham, AL. Baseline has no battery; Proposed adds a "
            "5 kWh / 2 kW battery dispatched to primarily minimize the homeowner's retail bill, "
            "with grid avoided cost as a lower-priority tiebreaker. Uses the same 24-hour "
            "look-ahead as the Balanced case (like a utility's day-ahead price signal) so it "
            "holds its charge for the best hour in sight rather than draining early. Both "
            "simulated in BEopt on the same 2012 AMY weather year."
        ),
        "load_profiles_path": "Load_Profiles_raw/Battery_Priority_Examples",
        "baseline_col": "Baseline_NoBattery_Birmingham2012_kW",
        "proposed_col": "Battery_HomeownerPriority_Birmingham2012_kW",
        "weather_year": "2012",
        "state": "AL",
        "tariff": "Alabama Power - Rate RTA-E (Residential Time Advantage - Energy Only)",
    },
    {
        "label": "Birmingham, AL — No Battery vs. Grid-Priority Battery Dispatch (BEopt, 2012)",
        "description": (
            "Single-family home in Birmingham, AL. Baseline has no battery; Proposed adds a "
            "5 kWh / 2 kW battery dispatched to primarily minimize grid avoided cost, with "
            "homeowner retail rate as a lower-priority tiebreaker. Uses the same 24-hour "
            "look-ahead as the Balanced case (like a utility's day-ahead price signal) so it "
            "holds its charge for the best hour in sight rather than draining early. Both "
            "simulated in BEopt on the same 2012 AMY weather year."
        ),
        "load_profiles_path": "Load_Profiles_raw/Battery_Priority_Examples",
        "baseline_col": "Baseline_NoBattery_Birmingham2012_kW",
        "proposed_col": "Battery_GridPriority_Birmingham2012_kW",
        "weather_year": "2012",
        "state": "AL",
        "tariff": "Alabama Power - Rate RTA-E (Residential Time Advantage - Energy Only)",
    },
    {
        "label": "Birmingham, AL — No Battery vs. Strict-TOU Battery Dispatch (BEopt, 2012)",
        "description": (
            "Single-family home in Birmingham, AL. Baseline has no battery; Proposed adds a "
            "5 kWh / 2 kW battery dispatched purely off the retail tariff's own on-peak/off-peak "
            "windows (charges only in that month's cheapest tier, discharges only in that month's "
            "most expensive tier — evaluated per month since this tariff's true on-peak tier only "
            "exists Jun-Sep, so winter runs off its own, more modest shoulder-tier gap instead), "
            "ignoring grid avoided cost entirely — a tariff-only benchmark case. No look-ahead "
            "needed here, unlike the other 3 battery cases: a TOU schedule is already fully known "
            "in advance. Both simulated in BEopt on the same 2012 AMY weather year."
        ),
        "load_profiles_path": "Load_Profiles_raw/Battery_Priority_Examples",
        "baseline_col": "Baseline_NoBattery_Birmingham2012_kW",
        "proposed_col": "Battery_TOUStrict_Birmingham2012_kW",
        "weather_year": "2012",
        "state": "AL",
        "tariff": "Alabama Power - Rate RTA-E (Residential Time Advantage - Energy Only)",
    },
]


# ==============================================================================
# GRID VALUATION SCALAR DEFAULTS
# ==============================================================================

DEFAULT_CAP_VALUE = 110.20       # $/kW-year  (Generation Capacity: NREL ATB 2024 CT Carrying Cost Benchmark: $1,100/kW * 8.2% FCR + $20/kW-yr FOM)
DEFAULT_TRANS_VALUE = 15.00      # $/kW-year  (Transmission Deferral)
DEFAULT_DIST_VALUE = 15.00       # $/kW-year  (Distribution Deferral)
DEFAULT_CARBON_TAX = 30.00       # $/metric ton CO₂

# Scalar input ranges (min, max, step)
CAP_VALUE_RANGE = (0.0, 1000.0, 5.00)
TRANS_VALUE_RANGE = (0.0, 500.0, 1.00)
DIST_VALUE_RANGE = (0.0, 500.0, 1.00)
CARBON_TAX_RANGE = (0.0, 100.0, 5.00)

# ==============================================================================
# SOUTHEAST UTILITY PEAKER & T&D PRESETS
# ==============================================================================

SOUTHEAST_PEAKER_PRESETS = {
    "NREL ATB 2024: Natural Gas CT Benchmark (Moderate / Regulated Utility)": {
        "description": "NREL Annual Technology Baseline (ATB 2024) Natural Gas: Combustion Turbine (CT) — Utility-scale F-Class, Moderate Scenario, Regulated Utility Financing. (CAPEX: $1,100/kW, FCR: 8.20%, FOM: $20.00/kW-yr -> ECC: $110.20/kW-yr).",
        "source": "[Data | Electricity | 2024 | ATB | NLR](https://atb.nlr.gov/electricity/2024/data)",
        "capex_kw": 1100.0,
        "fom_kw_yr": 20.00,
        "fcr": 0.082,
        "wacc": 0.070,
        "life": 30,
        "tax_rate": 0.257,
        "eas_offset_kw_yr": 0.0,
    },
    "NREL ATB 2024: Natural Gas CT (Merchant / R&D Financing)": {
        "description": "NREL ATB 2024 Natural Gas CT with independent power producer (IPP) / merchant commercial financing (CAPEX: $1,100/kW, FCR: 10.20%, FOM: $20.00/kW-yr -> ECC: $132.20/kW-yr).",
        "source": "[Data | Electricity | 2024 | ATB | NLR](https://atb.nlr.gov/electricity/2024/data)",
        "capex_kw": 1100.0,
        "fom_kw_yr": 20.00,
        "fcr": 0.102,
        "wacc": 0.085,
        "life": 25,
        "tax_rate": 0.257,
        "eas_offset_kw_yr": 0.0,
    },
    "Southern Company / Georgia Power IRP SCCT Benchmark": {
        "description": "Next planned F-Class simple cycle combustion turbine based on Southern Company 2022/2025 IRP dockets.",
        "source": "Southern Company 2022/2025 Integrated Resource Plan (IRP) dockets",
        "capex_kw": 1080.0,
        "fom_kw_yr": 15.00,
        "fcr": 0.084,
        "wacc": 0.071,
        "life": 30,
        "tax_rate": 0.25,
        "eas_offset_kw_yr": 0.0,
    },
    "TVA Capacity Expansion SCCT Benchmark": {
        "description": "TVA 2019/2024 IRP capacity expansion peaker proxy with federal financing.",
        "source": "TVA 2019/2024 IRP capacity expansion peaker proxy",
        "capex_kw": 1020.0,
        "fom_kw_yr": 14.00,
        "fcr": 0.079,
        "wacc": 0.068,
        "life": 30,
        "tax_rate": 0.21,
        "eas_offset_kw_yr": 0.0,
    },
    "Duke Energy Carolinas 2024 IRP SCCT Benchmark": {
        "description": "Next planned GE 7F.05 simple-cycle combustion turbine from Duke Energy 2024 Carolinas Resource Plan / Carbon Plan.",
        "source": "Duke Energy Carolinas 2024 Integrated Resource Plan / Carbon Plan (NCUC Docket E-100 Sub 190)",
        "capex_kw": 1060.0,
        "fom_kw_yr": 16.00,
        "fcr": 0.081,
        "wacc": 0.071,
        "life": 30,
        "tax_rate": 0.25,
        "eas_offset_kw_yr": 0.0,
    },
    "Entergy 2023/2024 IRP Peaker Benchmark": {
        "description": "Next planned simple-cycle combustion turbine peaker proxy from Entergy operating companies 2023/2024 IRP dockets.",
        "source": "Entergy 2023/2024 Integrated Resource Plan dockets",
        "capex_kw": 1050.0,
        "fom_kw_yr": 15.50,
        "fcr": 0.083,
        "wacc": 0.072,
        "life": 30,
        "tax_rate": 0.25,
        "eas_offset_kw_yr": 0.0,
    },
    "Southeast Regional Composite SCCT Benchmark": {
        "description": "Composite average simple-cycle combustion turbine carrying cost across Southeast utilities ($104.00/kW-yr).",
        "source": "Composite Southeast Utility IRPs & NREL ATB 2024",
        "capex_kw": 1060.0,
        "fom_kw_yr": 16.00,
        "fcr": 0.083,
        "wacc": 0.071,
        "life": 30,
        "tax_rate": 0.25,
        "eas_offset_kw_yr": 0.0,
    },
    "NREL ATB 2024: Aeroderivative CT": {
        "description": "Fast-ramping aeroderivative peaker (e.g. LM6000) for winter morning cold snap / peak following.",
        "source": "NREL ATB 2024 Natural Gas: Combustion Turbine (Aeroderivative)",
        "capex_kw": 1250.0,
        "fom_kw_yr": 18.00,
        "fcr": 0.082,
        "wacc": 0.071,
        "life": 30,
        "tax_rate": 0.25,
        "eas_offset_kw_yr": 0.0,
    },
}

SOUTHEAST_TD_PRESETS = {
    "Georgia Power Rate Case Benchmark": {
        "dist_value": 25.00,
        "trans_value": 15.00,
        "description": "Derived from Georgia Power retail rate dockets and FERC Form 1 growth additions ($40.00/kW-yr combined).",
    },
    "Alabama Power Rate Case Benchmark": {
        "dist_value": 22.00,
        "trans_value": 14.00,
        "description": "Derived from Alabama Power retail rate filings and FERC Form 1 ($36.00/kW-yr combined).",
    },
    "Mississippi Power Rate Case Benchmark": {
        "dist_value": 19.00,
        "trans_value": 12.00,
        "description": "Derived from Mississippi Power MPSC retail rate filings, PEP filings, and FERC Form 1 ($31.00/kW-yr combined).",
    },
    "TVA / LPC Composite Benchmark": {
        "dist_value": 20.00,
        "trans_value": 16.50,
        "description": "Derived from TVA Wholesale Transmission Rate filings and composite Local Power Company (LPC) distribution studies ($36.50/kW-yr combined).",
    },
    "Duke Energy Carolinas Rate Case Benchmark": {
        "dist_value": 27.00,
        "trans_value": 15.00,
        "description": "Derived from Duke Energy Carolinas NCUC/SCPSC rate dockets (Docket E-7 Sub 1276) and FERC Form 1 ($42.00/kW-yr combined).",
    },
    "Entergy Mississippi Rate Case Benchmark": {
        "dist_value": 21.00,
        "trans_value": 13.00,
        "description": "Derived from Entergy Mississippi retail rate filings and FERC Form 1 growth additions ($34.00/kW-yr combined).",
    },
    "LBNL Southeast Regional Average": {
        "dist_value": 22.00,
        "trans_value": 14.00,
        "description": "Lawrence Berkeley National Lab (LBNL) and regional composite avoided T&D cost benchmark ($36.00/kW-yr combined).",
    },
    "Constrained Urban / High Growth Corridor": {
        "dist_value": 35.00,
        "trans_value": 20.00,
        "description": "Rapidly growing Southeast metro area (Atlanta / Charlotte / Birmingham perimeter) with heavy transformer loading ($55.00/kW-yr combined).",
    },
    "None / Exclude T&D ($0/kW-yr)": {
        "dist_value": 0.00,
        "trans_value": 0.00,
        "description": "Excludes transmission and distribution deferral credits ($0.00/kW-yr) for conservative generation-only screening.",
    },
}

# ==============================================================================
# TOP-LEVEL BALANCING AUTHORITY / UTILITY SYSTEM PRESETS
# ==============================================================================

ORGANIZATION_PRESETS = {
    "Southern Company (Georgia Power / Alabama Power / Mississippi Power)": {
        "label": "Southern Company",
        "description": "Vertically integrated Southern Company pool (Georgia Power, Alabama Power, Mississippi Power). Strong winter morning reliability risk combined with summer cooling peaks.",
        "states": ["GA", "AL"],
        "scenario": "MidCase",
        "planning_year": "2030",
        "weather_case": "2012 (Cambium-aligned baseline)",
        "carbon_tax": 30.00,
        "cap_value": 105.72,
        "peaker_preset": "Southern Company / Georgia Power IRP SCCT Benchmark",
        "cwf_mode": "Southeast Dual-Peak (Weather-Driven)",
        "cwf_winter_split": 80.0,
        "td_preset": "Georgia Power Rate Case Benchmark",
        "trans_value": 15.00,
        "dist_value": 25.00,
        "feeder_type": "Winter-Peaking Feeder (Southeast Heating / Dec–Feb 6–9 AM)",
        "tariff_type": "Georgia Power - Schedule R-31 (Residential)",
    },
    "Tennessee Valley Authority (TVA / LPCs)": {
        "label": "TVA / Public Power",
        "description": "Federal wholesale bulk power provider serving 153 municipal/cooperative Local Power Companies across TN, north AL, and north GA. Extreme winter morning space-heating peaks.",
        "states": ["TN"],
        "scenario": "MidCase",
        "planning_year": "2030",
        "weather_case": "2012 (Cambium-aligned baseline)",
        "carbon_tax": 0.00,
        "cap_value": 94.58,
        "peaker_preset": "TVA Capacity Expansion SCCT Benchmark",
        "cwf_mode": "Southeast Dual-Peak (Weather-Driven)",
        "cwf_winter_split": 85.0,
        "td_preset": "TVA / LPC Composite Benchmark",
        "trans_value": 16.50,
        "dist_value": 20.00,
        "feeder_type": "Winter-Peaking Feeder (Southeast Heating / Dec–Feb 6–9 AM)",
        "tariff_type": "TVA LPC - Standard Residential Benchmark",
    },
    "Duke Energy (Carolinas & Progress — NC / SC)": {
        "label": "Duke Energy Carolinas",
        "description": "Duke Energy Carolinas and Duke Energy Progress. High-growth Piedmont corridor with balanced dual-peaking (winter freeze spikes + summer afternoon cooling).",
        "states": ["NC", "SC"],
        "scenario": "MidCase",
        "planning_year": "2030",
        "weather_case": "2012 (Cambium-aligned baseline)",
        "carbon_tax": 30.00,
        "cap_value": 101.86,
        "peaker_preset": "Duke Energy Carolinas 2024 IRP SCCT Benchmark",
        "cwf_mode": "Southeast Dual-Peak (Weather-Driven)",
        "cwf_winter_split": 70.0,
        "td_preset": "Duke Energy Carolinas Rate Case Benchmark",
        "trans_value": 15.00,
        "dist_value": 27.00,
        "feeder_type": "Dual-Peaking Feeder (Suburban Mixed 50/50)",
        "tariff_type": "Duke Energy Carolinas - Schedule RES (Residential)",
    },
    "Entergy (Entergy Mississippi / Mid-South)": {
        "label": "Entergy",
        "description": "Entergy operating companies across the lower Mississippi Delta. High summer cooling load with winter polar freeze vulnerability.",
        "states": ["MS"],
        "scenario": "MidCase",
        "planning_year": "2030",
        "weather_case": "2012 (Cambium-aligned baseline)",
        "carbon_tax": 25.00,
        "cap_value": 102.50,
        "peaker_preset": "Entergy 2023/2024 IRP Peaker Benchmark",
        "cwf_mode": "Southeast Dual-Peak (Weather-Driven)",
        "cwf_winter_split": 65.0,
        "td_preset": "Entergy Mississippi Rate Case Benchmark",
        "trans_value": 13.00,
        "dist_value": 21.00,
        "feeder_type": "Dual-Peaking Feeder (Suburban Mixed 50/50)",
        "tariff_type": "Entergy Mississippi - Rate Schedule RS (Residential)",
    },
    "Southeast Regional Average (Composite Benchmark)": {
        "label": "Southeast Average",
        "description": "Weighted empirical composite average across Southern Company, TVA, Duke Energy, and Entergy territories.",
        "states": ["AL", "GA", "TN", "NC", "SC", "MS"],
        "scenario": "MidCase",
        "planning_year": "2030",
        "weather_case": "2012 (Cambium-aligned baseline)",
        "carbon_tax": 25.00,
        "cap_value": 104.00,
        "peaker_preset": "Southeast Regional Composite SCCT Benchmark",
        "cwf_mode": "Southeast Dual-Peak (Weather-Driven)",
        "cwf_winter_split": 75.0,
        "td_preset": "LBNL Southeast Regional Average",
        "trans_value": 14.00,
        "dist_value": 22.00,
        "feeder_type": "System Coincident (Top 100 Peak Hours)",
        "tariff_type": "Southeast Regional Average Tariff ($0.135/kWh)",
    },
}

CWF_METHOD_OPTIONS = [
    "Southeast Dual-Peak (Winter 6–9 AM + Summer 2–6 PM)",
    "Ambient Temperature Severity (Weather-Triggered)",
    "Cambium Price-Exceedance LOLP Proxy (Exponential)",
    "Top-N Peak Hours Exceedance",
    "Wholesale Peaker Rent (Spark Spread)",
    "Uploaded / Default CWFT CSV",
]

FEEDER_TYPE_OPTIONS = [
    "System Coincident (Top 100 Peak Hours)",
    "Winter-Peaking Feeder (Southeast Heating / Dec–Feb 6–9 AM)",
    "Summer-Peaking Feeder (Southeast Cooling / Jun–Sep 2–6 PM)",
    "Dual-Peaking Feeder (Suburban Mixed 50/50)",
]


# ==============================================================================
# FINANCIAL / NPV DEFAULTS
# ==============================================================================

DEFAULT_ASSET_LIFE = 15          # years
DEFAULT_DISCOUNT_RATE = 7.0      # %  (WACC)
DEFAULT_ESCALATION_RATE = 2.0    # %  (grid price escalation)
DEFAULT_RETAIL_ESCALATION = 2.0  # %  (retail price escalation)
DEFAULT_DEGRADATION_RATE = 1.0   # %  (annual efficiency decay)

# Measure & Program Cost Defaults
DEFAULT_GROSS_MEASURE_COST = 3000.0   # $ (Total upfront installed equipment & labor cost)
DEFAULT_UTILITY_INCENTIVE = 500.0     # $ (Customer rebate / incentive paid by utility)
DEFAULT_UTILITY_ADMIN_COST = 100.0    # $ (Utility program marketing & administrative cost)


# ==============================================================================
# DEMAND RESPONSE DEFAULTS
# ==============================================================================

DEFAULT_DR_HOURS_PER_YEAR = 50
DEFAULT_DR_SEASON = "Summer Only (Jun-Sep)"
DR_SEASON_OPTIONS = [
    "Summer Only (Jun-Sep)",
    "Winter Only (Oct-May)",
    "Both Seasons",
]
DEFAULT_DR_MAX_HOURS_PER_DAY = 4
DEFAULT_DR_CAPACITY_KW = 1.0

# Fraction of nameplate DR capacity accredited as firm/reliable generation capacity.
# This is the DR analog of a generator's UCAP/ELCC accreditation factor: it de-rates
# expected non-performance, opt-outs, and M&V shortfall relative to a program's
# nameplate curtailment capability. Applied only to the Generation Capacity ($/kW-yr)
# credit -- NOT to metered energy savings, which reflect actual dispatched curtailment.
DEFAULT_DR_PERFORMANCE_FACTOR = 0.85
DR_PERFORMANCE_FACTOR_RANGE = (10, 100, 1)  # percent: (min, max, step)


# ==============================================================================
# CHART / VISUALIZATION CONSTANTS
# ==============================================================================

# Grid avoided cost component definitions — used for stacked area charts
# Format: (DataFrame column name, display label, hex color)
GRID_COMPONENTS = [
    ("Cambium_Energy_MWh",       "Wholesale Energy",                "#F59E0B"),
    ("Gen_Capacity_Value_MWh",   "Generation Capacity (CWFT)",      "#0D9488"),
    ("Trans_Value_MWh",          "Transmission Deferral (PCAF)",    "#3B82F6"),
    ("Dist_Value_MWh",           "Distribution Deferral (PCAF)",    "#EC4899"),
    ("Emissions_Value_MWh",      "Emissions Compliance",            "#10B981"),
]

# Week window definitions for the weekly profile overlay chart
# Format: label → (start_hour, end_hour)
WEEK_WINDOWS = {
    "Winter Peak Week (Jan 1-7)": (0, 168),
    "Summer Peak Week (Jul 15-21)": (4680, 4848),
    "Shoulder Week (Apr 10-16)": (2376, 2544),
}

# Standard chart color palette
COLORS = {
    "teal":       "#0D9488",
    "amber":      "#F59E0B",
    "red":        "#EF4444",
    "purple":     "#8B5CF6",
    "blue":       "#3B82F6",
    "pink":       "#EC4899",
    "green":      "#10B981",
    "slate_dark": "#1E293B",
    "slate_mid":  "#4B5563",
    "slate_light": "#64748B",
    "slate_bg":   "#F8FAFC",
    "border":     "#E2E8F0",
}


# ==============================================================================
# RETAIL TARIFF SELECTOR OPTIONS
# ==============================================================================

TARIFF_OPTIONS = [
    "Georgia Power - Schedule R-31 (Residential)",
    "Alabama Power - Rate FD (Family Dwelling)",
    "Alabama Power - Rate FD-D (Family Dwelling Demand)",
    "Alabama Power - Rate RTA (Residential Time Advantage - Demand)",
    "Alabama Power - Rate RTA-E (Residential Time Advantage - Energy Only)",
    "Duke Energy Carolinas - Schedule RES (Residential)",
    "TVA LPC - Standard Residential Benchmark",
    "Mississippi Power - Rate Schedule RS (Residential)",
    "Entergy Mississippi - Rate Schedule RS (Residential)",
    "Southeast Regional Average Tariff ($0.135/kWh)",
    "Import from NREL URDB (API Label)",
    "Paste Custom URDB V3 JSON",
    "Custom Flat Rate / Demand",
]


# ==============================================================================
# STANDARDIZED KPI RATIO CARD HELPER
# ==============================================================================
# Several ratio-style KPIs (TRC, PCT, RIM) need color-coded pass/fail styling
# that st.metric() doesn't natively support. This helper builds HTML matching
# the same visual style as native st.metric() cards (see .kpi-card CSS below),
# so ratio cards and native metric cards look consistent side-by-side.

def ratio_card_html(label, value, sublabel, passing, help_text=None):
    """
    Returns an HTML snippet for a color-coded ratio KPI card (e.g. TRC, PCT, RIM),
    styled to match native st.metric() cards. `passing` controls green/red color.
    If `help_text` is provided, renders a help (?) icon with hover tooltip.
    """
    color = "#15803d" if passing else "#b91c1c"
    if help_text:
        formatted_help = help_text.strip()
        if "<" not in formatted_help and ">" not in formatted_help:
            formatted_help = formatted_help.replace("\n", "<br>")
        help_icon_html = (
            f'<span class="kpi-help-tooltip" tabindex="0">'
            f'<svg class="kpi-help-icon" xmlns="http://www.w3.org/2000/svg" width="14" height="14" '
            f'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            f'stroke-linecap="round" stroke-linejoin="round">'
            f'<circle cx="12" cy="12" r="10"></circle>'
            f'<path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"></path>'
            f'<line x1="12" y1="17" x2="12.01" y2="17"></line>'
            f'</svg>'
            f'<div class="kpi-tooltip-bubble">{formatted_help}</div>'
            f'</span>'
        )
    else:
        help_icon_html = ""

    return f"""<div class="kpi-card">
<div class="kpi-card-label"><span>{label}</span>{help_icon_html}</div>
<div class="kpi-card-value" style="color: {color};">{value}</div>
<div class="kpi-card-sublabel">{sublabel}</div>
</div>"""


def financial_metric_card_html(label, value, sublabel, is_positive=True, neutral=False, help_text=None):
    """
    Returns an HTML snippet for a financial KPI card (e.g. Annual Operating Margin, Lifetime NPV),
    styled to match native st.metric() cards, where the primary number's font color dynamically
    matches positive (green #15803d), negative / cross-subsidy (red #b91c1c), or neutral (teal #0D9488).
    If `help_text` is provided, renders a help (?) icon with hover tooltip.
    """
    if neutral:
        color = "#0D9488"
        sub_color = "#64748B"
    elif is_positive:
        color = "#15803d"
        sub_color = "#15803d"
    else:
        color = "#b91c1c"
        sub_color = "#b91c1c"
    
    if help_text:
        formatted_help = help_text.strip()
        if "<" not in formatted_help and ">" not in formatted_help:
            formatted_help = formatted_help.replace("\n", "<br>")
        help_icon_html = (
            f'<span class="kpi-help-tooltip" tabindex="0">'
            f'<svg class="kpi-help-icon" xmlns="http://www.w3.org/2000/svg" width="14" height="14" '
            f'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            f'stroke-linecap="round" stroke-linejoin="round">'
            f'<circle cx="12" cy="12" r="10"></circle>'
            f'<path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"></path>'
            f'<line x1="12" y1="17" x2="12.01" y2="17"></line>'
            f'</svg>'
            f'<div class="kpi-tooltip-bubble">{formatted_help}</div>'
            f'</span>'
        )
    else:
        help_icon_html = ""

    return f"""<div class="kpi-card">
<div class="kpi-card-label"><span>{label}</span>{help_icon_html}</div>
<div class="kpi-card-value" style="color: {color};">{value}</div>
<div class="kpi-card-sublabel" style="color: {sub_color}; font-weight: 500;">{sublabel}</div>
</div>"""



# ==============================================================================
# CUSTOM CSS STYLING
# ==============================================================================

CUSTOM_CSS = """<style>
/* Reduce excessive default top whitespace to move header elements higher */
.block-container {
    padding-top: 1.5rem !important;
    padding-bottom: 2rem !important;
}

/* Metric styling */
[data-testid="stMetricValue"] {
    font-size: 1.8rem;
    font-weight: 700;
    color: #0D9488; /* Sleek teal color for key figures */
}
[data-testid="stMetricLabel"] {
    font-size: 0.9rem;
    font-weight: 600;
    color: #4B5563;
}
div[data-testid="metric-container"] {
    background-color: #F8FAFC;
    border: 1px solid #E2E8F0;
    padding: 15px 18px;
    border-radius: 12px;
    box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.05), 0 2px 4px -2px rgb(0 0 0 / 0.05);
    transition: transform 0.2s ease-in-out;
}
div[data-testid="metric-container"]:hover {
    transform: translateY(-2px);
    box-shadow: 0 10px 15px -3px rgb(0 0 0 / 0.05);
}
/* Standardized ratio KPI cards (TRC/PCT/RIM) — matches native st.metric() cards */
.kpi-card {
    background-color: #F8FAFC;
    border: 1px solid #E2E8F0;
    padding: 15px 18px;
    border-radius: 12px;
    box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.05), 0 2px 4px -2px rgb(0 0 0 / 0.05);
    transition: transform 0.2s ease-in-out;
}
.kpi-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 10px 15px -3px rgb(0 0 0 / 0.05);
}
.kpi-card-label {
    font-size: 0.9rem;
    font-weight: 600;
    color: #4B5563;
    display: flex;
    align-items: center;
    gap: 4px;
}
.kpi-card-value {
    font-size: 1.8rem;
    font-weight: 700;
    line-height: 1.3;
}
.kpi-card-sublabel {
    font-size: 0.8rem;
    color: #64748B;
}
.kpi-help-tooltip {
    position: relative;
    display: inline-flex;
    align-items: center;
    cursor: help;
    color: #808495;
    vertical-align: middle;
}
.kpi-help-tooltip:hover, .kpi-help-tooltip:focus {
    color: #1E293B;
    outline: none;
}
.kpi-help-icon {
    width: 14px;
    height: 14px;
    stroke: currentColor;
    display: block;
}
.kpi-tooltip-bubble {
    visibility: hidden;
    opacity: 0;
    position: absolute;
    bottom: calc(100% + 8px);
    left: 50%;
    transform: translateX(-50%);
    background-color: #1E293B;
    color: #F8FAFC;
    padding: 10px 14px;
    border-radius: 8px;
    font-size: 0.78rem;
    font-weight: 400;
    line-height: 1.45;
    width: 310px;
    max-width: 85vw;
    box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.35), 0 8px 10px -6px rgba(0, 0, 0, 0.2);
    z-index: 99999;
    pointer-events: none;
    transition: opacity 0.15s ease-in-out, visibility 0.15s ease-in-out;
    white-space: normal;
    text-align: left;
}
.kpi-tooltip-bubble::after {
    content: "";
    position: absolute;
    top: 100%;
    left: 50%;
    transform: translateX(-50%);
    border-width: 6px;
    border-style: solid;
    border-color: #1E293B transparent transparent transparent;
}
.kpi-tooltip-bubble strong {
    color: #FFFFFF;
    font-weight: 600;
}
.kpi-tooltip-bubble em {
    color: #38BDF8;
    font-style: normal;
    font-weight: 600;
}
.kpi-help-tooltip:hover .kpi-tooltip-bubble,
.kpi-help-tooltip:focus .kpi-tooltip-bubble {
    visibility: visible;
    opacity: 1;
}
/* Style tables and graphs */
[data-testid="stDataFrame"] {
    border: 1px solid #E2E8F0;
    border-radius: 12px;
    overflow: hidden;
}
/* Enable responsive wrapping & smooth horizontal scrolling for Streamlit tabs */
div[data-testid="stTabs"] {
    overflow-x: auto !important;
}
div[data-testid="stTabs"] [role="tablist"] {
    flex-wrap: wrap !important;
    gap: 8px !important;
    border-bottom: 2px solid #E2E8F0 !important;
    padding-bottom: 6px !important;
}
div[data-testid="stTabs"] button[role="tab"] {
    height: auto !important;
    padding: 8px 16px !important;
    border-radius: 8px !important;
    white-space: nowrap !important;
    background-color: #F8FAFC !important;
    border: 1px solid #CBD5E1 !important;
    margin-right: 4px !important;
}
div[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
    background-color: #0D9488 !important;
    color: #FFFFFF !important;
    border-color: #0D9488 !important;
    font-weight: 700 !important;
}
div[data-testid="stTabs"] button[role="tab"][aria-selected="true"] span,
div[data-testid="stTabs"] button[role="tab"][aria-selected="true"] p,
div[data-testid="stTabs"] button[role="tab"][aria-selected="true"] div {
    color: #FFFFFF !important;
}
/* Fallback selectors for older Streamlit/BaseWeb DOM structures */
div[data-baseweb="tab-list"] {
    flex-wrap: wrap !important;
    gap: 8px !important;
    border-bottom: 2px solid #E2E8F0 !important;
    padding-bottom: 6px !important;
}
div[data-baseweb="tab"] {
    height: auto !important;
    padding: 8px 16px !important;
    border-radius: 8px !important;
    white-space: nowrap !important;
    background-color: #F8FAFC !important;
    border: 1px solid #CBD5E1 !important;
    margin-right: 4px !important;
}
div[data-baseweb="tab"][aria-selected="true"] {
    background-color: #0D9488 !important;
    color: #FFFFFF !important;
    border-color: #0D9488 !important;
    font-weight: 700 !important;
}
div[data-baseweb="tab"][aria-selected="true"] span,
div[data-baseweb="tab"][aria-selected="true"] p {
    color: #FFFFFF !important;
}
.badge {
    display: inline-block;
    padding: 0.35em 0.65em;
    font-size: 0.85em;
    font-weight: 700;
    line-height: 1;
    text-align: center;
    white-space: nowrap;
    vertical-align: baseline;
    border-radius: 0.375rem;
}
.badge-success {
    color: #fff;
    background-color: #15803d;
}
.badge-warning {
    color: #854d0e;
    background-color: #fef08a;
    border: 1px solid #eab308;
}
.badge-danger {
    color: #fff;
    background-color: #b91c1c;
}
</style>"""


# ==============================================================================
# WEATHER SENSITIVITY THRESHOLDS
# ==============================================================================

WEATHER_SENSITIVITY_STRONG = 0.60
WEATHER_SENSITIVITY_MODERATE = 0.35

# Styling for weather sensitivity status banners
WEATHER_SENSITIVITY_STYLES = {
    "strong": {
        "label": "Responsive (Strong Temperature Correlation)",
        "bg_color": "#ECFDF5",
        "text_color": "#065F46",
        "border_color": "#10B981",
    },
    "moderate": {
        "label": "Moderate Sensitivity",
        "bg_color": "#FFFBEB",
        "text_color": "#92400E",
        "border_color": "#F59E0B",
    },
    "low": {
        "label": "Unresponsive / Low Sensitivity",
        "bg_color": "#FEF2F2",
        "text_color": "#991B1B",
        "border_color": "#EF4444",
    },
}


def get_weather_sensitivity_style(max_corr):
    """Return the appropriate style dict for a given max correlation value."""
    if max_corr >= WEATHER_SENSITIVITY_STRONG:
        return WEATHER_SENSITIVITY_STYLES["strong"]
    elif max_corr >= WEATHER_SENSITIVITY_MODERATE:
        return WEATHER_SENSITIVITY_STYLES["moderate"]
    else:
        return WEATHER_SENSITIVITY_STYLES["low"]
