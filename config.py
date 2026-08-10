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
    "HighDemandGrowth",
    "MidCase",
    "LowCarbonConstraint",
    "LowDemandGrowth",
]

PLANNING_YEAR_OPTIONS = ["2025", "2030", "2035", "2040", "2045", "2050"]
DEFAULT_PLANNING_YEAR_INDEX = 3  # "2040"

WEATHER_CASE_OPTIONS = [
    "2012 (Cambium-aligned baseline)",
    "Extreme Winter",
    "Extreme Summer",
]

STATE_OPTIONS = ["AL", "GA", "FL", "TN", "MS", "NC", "SC"]
DEFAULT_STATES = ["AL", "GA"]


# ==============================================================================
# GRID VALUATION SCALAR DEFAULTS
# ==============================================================================

DEFAULT_CAP_VALUE = 100.00       # $/kW-year  (Generation Capacity)
DEFAULT_TRANS_VALUE = 15.00      # $/kW-year  (Transmission Deferral)
DEFAULT_DIST_VALUE = 15.00       # $/kW-year  (Distribution Deferral)
DEFAULT_CARBON_TAX = 30.00       # $/metric ton CO₂

# Scalar input ranges (min, max, step)
CAP_VALUE_RANGE = (0.0, 1000.0, 5.00)
TRANS_VALUE_RANGE = (0.0, 500.0, 1.00)
DIST_VALUE_RANGE = (0.0, 500.0, 1.00)
CARBON_TAX_RANGE = (0.0, 100.0, 5.00)


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
    "Import from NREL URDB (API Label)",
    "Paste Custom URDB V3 JSON",
    "Custom Flat Rate / Demand",
]


# ==============================================================================
# CUSTOM CSS STYLING
# ==============================================================================

CUSTOM_CSS = """<style>
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
/* Style tables and graphs */
[data-testid="stDataFrame"] {
    border: 1px solid #E2E8F0;
    border-radius: 12px;
    overflow: hidden;
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
