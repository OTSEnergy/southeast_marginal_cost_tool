import os
import glob
import json
import urllib.request
import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ==============================================================================
# PAGE CONFIGURATION & AESTHETICS
# ==============================================================================
st.set_page_config(
    page_title="Southeast Marginal Cost Valuation Engine",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Premium Custom CSS styling — sourced from config.py
from config import (
    CUSTOM_CSS,
    SCENARIO_OPTIONS, PLANNING_YEAR_OPTIONS, DEFAULT_PLANNING_YEAR_INDEX,
    WEATHER_CASE_OPTIONS, STATE_OPTIONS, DEFAULT_STATES,
    DEFAULT_CAP_VALUE, DEFAULT_TRANS_VALUE, DEFAULT_DIST_VALUE, DEFAULT_CARBON_TAX,
    CAP_VALUE_RANGE, TRANS_VALUE_RANGE, DIST_VALUE_RANGE, CARBON_TAX_RANGE,
    DEFAULT_ASSET_LIFE, DEFAULT_DISCOUNT_RATE, DEFAULT_ESCALATION_RATE,
    DEFAULT_RETAIL_ESCALATION, DEFAULT_DEGRADATION_RATE,
    DEFAULT_GROSS_MEASURE_COST, DEFAULT_UTILITY_INCENTIVE, DEFAULT_UTILITY_ADMIN_COST,
    DEFAULT_DR_HOURS_PER_YEAR, DEFAULT_DR_SEASON, DR_SEASON_OPTIONS,
    DEFAULT_DR_MAX_HOURS_PER_DAY, DEFAULT_DR_CAPACITY_KW,
    TARIFF_OPTIONS, GRID_COMPONENTS, WEEK_WINDOWS, COLORS,
    WEATHER_SENSITIVITY_STRONG, WEATHER_SENSITIVITY_MODERATE,
    get_weather_sensitivity_style,
    EXAMPLE_BUILDINGS, ratio_card_html,
)
from visualizations import (
    build_weekly_overlay_chart,
    build_weekly_load_and_temp_chart,
    build_weekly_grid_economics_chart,
    build_annual_avoided_cost_chart,
    build_stacked_components_chart,
    build_lifetime_npv_chart,
)
from calculations import (
    calculate_avoided_costs,
    dispatch_dr_program,
    calculate_cost_effectiveness_tests,
)
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)



# ==============================================================================
# PROJECT MODULE IMPORTS
# ==============================================================================
# These modules were extracted from app.py to keep calculation logic and data
# I/O separate from the Streamlit UI. Each module is Streamlit-free and can be
# tested, imported, or reused independently.
#
#   config.py       - Default parameters, option lists, CSS, color palette.
#                     Imported above (before page config).
#
#   calculations.py - Grid avoided cost engine + DR dispatch (pure math, no I/O)
#                     See: calculate_avoided_costs(), dispatch_dr_program()
#
#   billing.py      - URDB-compliant retail billing engine + tariff data
#                     See: calculate_urdb_bill(), GP_R31_URDB, AL_FD_URDB
#
#   data_loaders.py - All file I/O, data ingestion, and mock generators:
#                     * Cambium CSV scanner + column mapping engine
#                     * CWFT loader/generator  (default is MOCK placeholder)
#                     * Load profile loader/generator (default is MOCK)
#                     * Weather file loader (.epw / .csv, real files supported)
#                     * URDB API fetch (live tariff download from NREL)
#                     * Mock state data generator (for dev/testing only)
#                     See: load_and_aggregate_data(), load_cwft_from_csv(),
#                          load_load_profiles_from_csv(), fetch_urdb_rate(), etc.
#
#   visualizations.py - Plotly chart builder functions (pure Plotly, no Streamlit).
#                       Each function returns a go.Figure for st.plotly_chart().
#                       Imported above (before page config).
#
# All modules are tested in tests/test_calculations.py.
# Run: python -m pytest
# ==============================================================================
from calculations import calculate_avoided_costs, dispatch_dr_program
from billing import calculate_urdb_bill, get_hourly_energy_rate, GP_R31_URDB, AL_FD_URDB
from data_loaders import (
    INPUT_DIRECTORY,
    generate_default_cwft_file,
    load_cwft_from_csv,
    generate_default_load_profiles_file,
    load_load_profiles_from_csv,
    generate_mock_state_file,
    file_matches_scenario,
    parse_cambium_columns,
    load_custom_weather_file,
    load_and_aggregate_data,
    fetch_urdb_rate,
)

# ==============================================================================
# DATA LOADING & FILE GENERATION - imported from data_loaders.py
# ==============================================================================
# All data I/O has been moved to data_loaders.py. Here is what is imported
# and what each function does:
#
#   INPUT_DIRECTORY          './Cambium_Hourly_Data_raw' - where raw NREL CSVs live
#
#   generate_default_cwft_file(filepath)
#       MOCK - Generates a synthetic Southeast dual-peak CWFT CSV
#       (45% winter morning / 55% summer afternoon risk split).
#       Status: Placeholder. Must be replaced with real utility/ISO data.
#
#   load_cwft_from_csv(filepath)
#       REAL - Loads and validates a CWFT CSV (8760 rows, sum-to-1).
#
#   generate_default_load_profiles_file(filepath)
#       MOCK - Generates synthetic heat pump load profiles.
#       Status: Placeholder. Replace with real EnergyPlus prototype models.
#
#   load_load_profiles_from_csv(filepath)
#       REAL - Loads and validates a load profiles CSV (8760 rows).
#
#   generate_mock_state_file(filepath, state_code, scenario)
#       MOCK - Generates synthetic Cambium-like hourly data for dev/testing.
#
#   file_matches_scenario(filepath, scenario)
#       REAL - Checks if a simplified-format CSV matches the selected scenario.
#
#   parse_cambium_columns(df)
#       REAL - Dynamic column mapping engine for NREL naming conventions.
#
#   load_custom_weather_file(weather_case)
#       REAL - Loads .epw or .csv weather files from Weather_Data_raw/.
#
#   load_and_aggregate_data(target_states, scenario, weather_case, ...)
#       REAL - Main ingestion pipeline. @st.cache_data applied below.
#
#   fetch_urdb_rate(rate_label, api_key)
#       REAL - Live API call to NREL OpenEI URDB for tariff download.
#
# Full implementations: data_loaders.py
# ==============================================================================

# Apply Streamlit caching to the data pipeline at the app level.
# data_loaders.py is Streamlit-free, so we wrap the import here.
load_and_aggregate_data = st.cache_data(load_and_aggregate_data)



# dispatch_dr_program() has been moved to calculations.py (imported above)


def render_weather_generator(key_suffix: str):
    st.markdown("### AMY EPW Weather Generator (`diyepw`)")
    st.markdown(
        """This utility automates the generation of **Actual Meteorological Year (AMY) EPW weather files** 
using PNNL's `diyepw` tool. It automatically downloads observations from the NOAA Integrated Surface Database (ISD),
interpolates missing points, and builds a customized `.epw` file using NREL's TMY3 as a template."""
    )
    
    st.info(
        "**Requirements:** Generating files requires an active internet connection to download "
        "NOAA observations (~1MB per station/year) and NREL TMY3 templates. The process may take 1-2 minutes."
    )
    
    col1, col2 = st.columns(2)
    with col1:
        wmo_id = st.number_input(
            "WMO Station ID (6-digit)",
            min_value=100000,
            max_value=999999,
            value=722300, # Default: Birmingham Shuttlesworth, AL
            help="Check WMO IDs for your location from NOAA or climate databases. E.g. Atlanta, GA is 722190.",
            key=f"wmo_id_{key_suffix}"
        )
        
        target_year = st.selectbox(
            "Weather Observation Year",
            options=[2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024],
            index=2, # Default: 2012
            key=f"target_year_{key_suffix}"
        )
    
    with col2:
        weather_destination = st.selectbox(
            "Weather Case Destination Folder",
            options=["Baseline", "Extreme_Winter", "Extreme_Summer"],
            index=0,
            help="Determines which 'Weather_Data_raw/' folder the generated EPW file will be saved in.",
            key=f"weather_dest_{key_suffix}"
        )
        
        st.write("") # spacing
        st.write("")
        generate_button = st.button("Generate AMY Weather File", type="primary", use_container_width=True, key=f"generate_btn_{key_suffix}")
    
    if generate_button:
        try:
            # Local import of diyepw to prevent app startup failure if not installed
            import diyepw
            
            target_dir = os.path.join("Weather_Data_raw", weather_destination)
            os.makedirs(target_dir, exist_ok=True)
            
            with st.spinner(f"Downloading observations and generating AMY EPW for WMO {wmo_id} (Year {target_year})..."):
                diyepw.create_amy_epw_files_for_years_and_wmos(
                    years=[target_year],
                    wmo_indices=[wmo_id],
                    max_records_to_interpolate=10,
                    max_records_to_impute=25,
                    max_missing_amy_rows=5,
                    allow_downloads=True,
                    amy_epw_dir=target_dir
                )
            st.success(f"Success! AMY EPW file generated and saved to: `Weather_Data_raw/{weather_destination}/`")
            st.balloons()
            
        except ImportError:
            st.error(
                "**Missing Library:** The `diyepw` package is not installed. "
                "Please run `pip install diyepw` in your environment to use this generator."
            )
        except Exception as e:
            st.error(f"**Error generating EPW file:** {str(e)}")
            st.info("Check that the WMO ID is valid and that you have a stable internet connection.")

    # WMO ID lookup instructions and Citation references
    st.write("") # spacing
    with st.expander("How to find your weather station's WMO Station ID"):
        st.markdown(
            """**World Meteorological Organization (WMO) Station IDs** are 6-digit numeric codes representing weather stations.
            
You can find WMO IDs for your location in two ways:
1. **Interactive Map (Recommended):** Go to NREL's [EnergyPlus Weather Data map](https://energyplus.net/weather). Browse the map or search for your location using the search field. The 6-digit WMO ID is the number shown in parentheses in the station's title field (or in the filename of download options).
2. **Tabular Database:** Search the database at [Weather Station Identifiers](http://www.weathergraphics.com/identifiers/) to look up stations by state, city, or name.

*Note: The generator defaults to `722300` (Birmingham Shuttlesworth International Airport, AL). Other local examples: Atlanta Hartsfield-Jackson, GA is `722190`.*"""
        )
        
    with st.expander("Citation & About diyepw"):
        st.markdown(
            """The AMY weather file generator uses PNNL's open-source `diyepw` tool.
            
**GitHub Repository:** [IMMM-SFA/diyepw](https://github.com/IMMM-SFA/diyepw)

If you use these generated files in a research paper, model, or report, please cite `diyepw` as recommended by the authors:

* **Paper:** 
  > Amanda D. Smith, Benjamin Stürmer, Travis Thurber, & Chris R. Vernon. (2021). diyepw: A Python package for Do-It-Yourself EnergyPlus weather file generation. *Journal of Open Source Software*, 6(64), 3313. [https://doi.org/10.21105/joss.03313](https://doi.org/10.21105/joss.03313)
  
* **Software/Code:**
  > Amanda D. Smith, Benjamin Stürmer, Travis Thurber, & Chris R. Vernon. (2021). diyepw: A Python package for Do-It-Yourself EnergyPlus weather file generation (Version v2.0.0). *Zenodo*. [https://doi.org/10.5281/zenodo.5258122](https://doi.org/10.5281/zenodo.5258122)"""
        )


# ==============================================================================
# SIDEBAR CONTROLS & INPUT PARAMETERS
# ==============================================================================
st.sidebar.markdown(
    """<div style="text-align: center; margin-bottom: 20px;">
<h2 style="margin: 0; color: #1E293B; font-weight: 700;">Region & Scenario Settings</h2>
<p style="margin: 5px 0 0 0; color: #64748B; font-size: 0.85rem;">Configure inputs below, grouped by topic</p>
</div>""",
    unsafe_allow_html=True
)

# 1. Weather & Scenario Selectors
with st.sidebar.expander("Grid Scenario & Region", expanded=True):
    selected_scenario = st.selectbox(
        "NREL Future Scenario",
        options=SCENARIO_OPTIONS,
        index=0
    )

    planning_year = st.selectbox(
        "NREL Planning Year",
        options=PLANNING_YEAR_OPTIONS,
        index=DEFAULT_PLANNING_YEAR_INDEX,
        help="Select the target grid planning year for valuation."
    )

    weather_case = st.selectbox(
        "Grid Weather Case",
        options=WEATHER_CASE_OPTIONS,
        index=0,
        help="Alters temperatures, pushes peaks, and shifts reliability CWFT risk."
    )

    target_states = st.multiselect(
        "Target States",
        options=STATE_OPTIONS,
        default=DEFAULT_STATES
    )

# 2. Demand Response toggle (kept ahead of Building & Load Data below, since the
# load profile column logic branches on dr_mode).
with st.sidebar.expander("Demand Response (Optional)", expanded=False):
    dr_mode = st.toggle(
        "Enable DR Program Mode",
        value=False,
        help="Curbs load reduction dynamically during high-stress hours subject to call limits."
    )

    dr_hours_per_year = DEFAULT_DR_HOURS_PER_YEAR
    dr_season = DEFAULT_DR_SEASON
    dr_max_hours_per_day = DEFAULT_DR_MAX_HOURS_PER_DAY
    dr_capacity_kw = DEFAULT_DR_CAPACITY_KW

    if dr_mode:
        dr_hours_per_year = st.number_input("DR Call Hours per Year", min_value=1, max_value=8760, value=DEFAULT_DR_HOURS_PER_YEAR, step=5)
        dr_season = st.selectbox("DR Season of Applicability", DR_SEASON_OPTIONS)
        dr_max_hours_per_day = st.slider("Max Daily Call Hours", min_value=1, max_value=24, value=DEFAULT_DR_MAX_HOURS_PER_DAY)
        dr_capacity_kw = st.number_input("DR Curtailment Capacity (kW)", min_value=0.1, value=DEFAULT_DR_CAPACITY_KW, step=0.5, format="%.2f")

# 3. Building / Technology & Load Data (8760-hour input) + Example Library
with st.sidebar.expander("Building / Technology & Load Data", expanded=True):
    st.caption(
        "This defines \"the technology\" being evaluated: its Baseline and Proposed "
        "(or DR-curtailed) hourly electricity demand shape, one full year (8,760 hours)."
    )

    example_labels = ["Use my own load data"] + [b["label"] for b in EXAMPLE_BUILDINGS]
    selected_example_label = st.selectbox(
        "Try an Example Building",
        options=example_labels,
        index=0,
        help="Pick a pre-configured real building model to explore the tool without preparing your own files. More examples will be added over time."
    )
    selected_example = next((b for b in EXAMPLE_BUILDINGS if b["label"] == selected_example_label), None)

    if selected_example:
        st.info(selected_example["description"])
        load_profiles_filepath = selected_example["load_profiles_path"]
        if selected_example["state"] not in target_states:
            st.caption(f"Tip: this example represents {selected_example['state']}. Consider adding it under Grid Scenario & Region above.")
    else:
        # Load profiles path options
        has_raw_profiles = os.path.exists("Load_Profiles_raw") and any(
            len(glob.glob(os.path.join("Load_Profiles_raw", f"*{ext}"))) > 0 for ext in [".csv", ".xlsx", ".xls"]
        )
        default_load_idx = 0 if has_raw_profiles else 1

        selected_load_option = st.selectbox(
            "Load Profiles Source",
            options=["Load_Profiles_raw folder (BEopt / EnergyPlus raw models)", "load_profiles.csv (default synthetic)", "Custom path..."],
            index=default_load_idx,
            help="Supports raw BEopt / EnergyPlus output CSVs, custom 8760 CSVs or Excel files, or entire directories."
        )

        if "Custom path" in selected_load_option:
            load_profiles_filepath = st.text_input("Custom Load Profiles Path", value="load_profiles.csv")
        elif "Load_Profiles_raw" in selected_load_option:
            load_profiles_filepath = "Load_Profiles_raw"
        else:
            load_profiles_filepath = "load_profiles.csv"

    # Load profile case selection (Baseline vs Proposed)
    try:
        generate_default_load_profiles_file(load_profiles_filepath if load_profiles_filepath != "Load_Profiles_raw" else "load_profiles.csv")
        load_profiles_df = load_load_profiles_from_csv(load_profiles_filepath)
        profile_columns = [col for col in load_profiles_df.columns if col != 'Hour']

        is_folder_mode = os.path.isdir(load_profiles_filepath)
        file_basename = os.path.basename(load_profiles_filepath)

        if selected_example:
            baseline_col = selected_example["baseline_col"] if selected_example["baseline_col"] in profile_columns else profile_columns[0]
            default_prop = profile_columns[1] if len(profile_columns) > 1 else profile_columns[0]
            proposed_col = selected_example["proposed_col"] if selected_example["proposed_col"] in profile_columns else default_prop
            if dr_mode:
                proposed_col = baseline_col
            st.caption(f"Baseline: `{baseline_col}` | Proposed: `{proposed_col}` (auto-selected by example)")
        elif is_folder_mode:
            st.caption(f"Folder mode: found {len(profile_columns)} load profile case(s) in `{file_basename}`.")

            # Smart default indices for folder mode
            default_base_idx = 0
            default_prop_idx = 1 if len(profile_columns) > 1 else 0
            for idx, p in enumerate(profile_columns):
                p_low = p.lower()
                if any(k in p_low for k in ["erheat", "baseline", "standard", "electricresistance", "no tes", "no_tes", "notes"]):
                    default_base_idx = idx
                elif any(k in p_low for k in ["heatpump", "proposed", "highefficiency", "hp", "tes"]) and not any(k in p_low for k in ["no tes", "no_tes", "notes"]):
                    default_prop_idx = idx

            if dr_mode:
                baseline_col = st.selectbox(
                    "Baseline Model Case (for DR)",
                    options=profile_columns,
                    index=default_base_idx,
                    help="Select which building model or column represents the baseline load profile prior to Demand Response curtailment."
                )
                proposed_col = baseline_col
                st.caption("DR Mode Active: Proposed profile is calculated dynamically as Baseline − DR curtailment.")
            else:
                baseline_col = st.selectbox(
                    "Baseline Model Case",
                    options=profile_columns,
                    index=default_base_idx,
                    help="Select the building model file or column to use as the Baseline load profile."
                )
                proposed_col = st.selectbox(
                    "Proposed Model Case",
                    options=profile_columns,
                    index=default_prop_idx,
                    help="Select the building model file or column to use as the Proposed load profile."
                )
        else:
            # Single File Mode: Explicit column picker asking "which column?" without keyword guessing
            st.caption(f"Single file mode: select which column in `{file_basename}` represents each case.")

            # Positional defaults for single file mode (1st column = Baseline, 2nd column = Proposed if available)
            default_base_idx = 0
            default_prop_idx = 1 if len(profile_columns) > 1 else 0

            if dr_mode:
                baseline_col = st.selectbox(
                    f"Which column in '{file_basename}' is the Baseline load?",
                    options=profile_columns,
                    index=default_base_idx,
                    help="Select the column in your file representing baseline hourly demand before DR curtailment."
                )
                proposed_col = baseline_col
                st.caption("DR Mode Active: Proposed load profile is Baseline − DR curtailment.")
            else:
                baseline_col = st.selectbox(
                    f"Which column in '{file_basename}' is the Baseline load?",
                    options=profile_columns,
                    index=default_base_idx,
                    help=f"Select which numeric column from '{file_basename}' contains the Baseline load profile."
                )
                proposed_col = st.selectbox(
                    f"Which column in '{file_basename}' is the Proposed load?",
                    options=profile_columns,
                    index=default_prop_idx,
                    help=f"Select which numeric column from '{file_basename}' contains the Proposed load profile."
                )

        if baseline_col == proposed_col and not dr_mode and len(profile_columns) > 1:
            st.warning("Baseline and Proposed profiles are identical. Select two different columns for savings calculations.")

    except Exception as e:
        st.error(f"Error loading profiles: {e}")
        profile_columns = []
        baseline_col = None
        proposed_col = None

    st.markdown("---")
    st.caption("Weather Alignment Metadata — the weather year each input file represents, used to check alignment across CWFT, Cambium grid data, and this load file.")
    if selected_example:
        lock_year = selected_example["weather_year"]
        meta_load_weather = st.text_input("Load Profile Weather Year", value=lock_year, disabled=True)
        meta_cambium_weather = st.text_input("Cambium Weather Year", value=lock_year, disabled=True)
        meta_cwft_weather = st.text_input("CWFT Weather Year", value=lock_year, disabled=True)
        st.caption(f"Locked to {lock_year} by the selected example building (matching weather file).")
    else:
        meta_load_weather = st.text_input("Load Profile Weather Year", value="2012")
        meta_cambium_weather = st.text_input("Cambium Weather Year", value="2012")
        meta_cwft_weather = st.text_input("CWFT Weather Year", value="2012")

# 4. Grid Valuation Scalars
with st.sidebar.expander("Grid Valuation Assumptions", expanded=False):
    cap_value = st.number_input(
        "Gen Capacity Value ($/kW-year)",
        min_value=CAP_VALUE_RANGE[0], max_value=CAP_VALUE_RANGE[1], value=DEFAULT_CAP_VALUE, step=CAP_VALUE_RANGE[2], format="%.2f"
    )

    trans_value = st.number_input(
        "Transmission Deferral ($/kW-year)",
        min_value=TRANS_VALUE_RANGE[0], max_value=TRANS_VALUE_RANGE[1], value=DEFAULT_TRANS_VALUE, step=TRANS_VALUE_RANGE[2], format="%.2f"
    )

    dist_value = st.number_input(
        "Distribution Deferral ($/kW-year)",
        min_value=DIST_VALUE_RANGE[0], max_value=DIST_VALUE_RANGE[1], value=DEFAULT_DIST_VALUE, step=DIST_VALUE_RANGE[2], format="%.2f"
    )

    carbon_tax = st.slider(
        "Carbon Penalty ($/metric ton)",
        min_value=CARBON_TAX_RANGE[0], max_value=CARBON_TAX_RANGE[1], value=DEFAULT_CARBON_TAX, step=CARBON_TAX_RANGE[2], format="$%.2f"
    )

# 5. Retail Tariff & URDB Selector
with st.sidebar.expander("Retail Tariff (NREL URDB)", expanded=True):
    tariff_type = st.selectbox(
        "Retail Utility Tariff Type",
        options=TARIFF_OPTIONS,
        index=0,
        help="Define customer bill impact using packaged rates, pasting URDB JSONs, or querying the OpenEI API."
    )

    retail_escalation_rate = st.number_input(
        "Retail Price Escalation (%)",
        min_value=-5.0, max_value=15.0, value=DEFAULT_RETAIL_ESCALATION, step=0.5, format="%.1f"
    )

    active_tariff_json = None
    custom_rate_kwh = 0.12
    custom_demand_charge_kw = 0.0

    if tariff_type == "Georgia Power - Schedule R-31 (Residential)":
        active_tariff_json = GP_R31_URDB
    elif tariff_type == "Alabama Power - Rate FD (Family Dwelling)":
        active_tariff_json = AL_FD_URDB
    elif tariff_type == "Import from NREL URDB (API Label)":
        urdb_label = st.text_input(
            "URDB Rate Label", 
            value="5d4b00595457a3e73a0e6988", 
            help="OpenEI unique tariff label (e.g. 5d4b00595457a3e73a0e6988)"
        )
        with st.expander("How to get the Rate Label"):
            st.markdown(
                """1. Go to NREL's [Utility Rate Database](https://openei.org/wiki/Utility_Rate_Database).
2. Search for your utility (e.g., *Georgia Power*) and select the target rate plan.
3. In the rate details page URL, copy the final segment (e.g., `5d4b00595457a3e73a0e6988` from `https://openei.org/apps/USURDB/rate/view/5d4b00595457a3e73a0e6988`)."""
            )
        urdb_api_key = st.text_input("OpenEI API Key", value="DEMO_KEY", type="password")

        if st.button("Fetch Tariff Structure", use_container_width=True):
            with st.spinner("Downloading rate from NREL OpenEI..."):
                try:
                    fetched_rate = fetch_urdb_rate(urdb_label, urdb_api_key)
                    st.session_state['fetched_urdb_json'] = fetched_rate
                    st.success(f"Connected! Loaded: {fetched_rate.get('name', 'Rate')}")
                except Exception as e:
                    st.error(f"Failed to fetch rate: {str(e)}")

        if 'fetched_urdb_json' in st.session_state:
            active_tariff_json = st.session_state['fetched_urdb_json']
            st.caption(f"Active: *{active_tariff_json.get('name', 'Fetched Tariff')}*")
        else:
            st.warning("Click Fetch to load tariff details.")

    elif tariff_type == "Paste Custom URDB V3 JSON":
        raw_pasted_json = st.text_area("Paste URDB JSON here", height=150, help="Paste a full NREL V3 utility rate JSON response.")
        if raw_pasted_json:
            try:
                active_tariff_json = json.loads(raw_pasted_json)
                st.success(f"Valid JSON! Loaded: {active_tariff_json.get('name', 'Pasted Rate')}")
            except Exception as e:
                st.error(f"Invalid JSON: {str(e)}")

    elif tariff_type == "Custom Flat Rate / Demand":
        custom_rate_kwh = st.number_input("Custom Energy ($/kWh)", min_value=0.0, value=0.12, step=0.01, format="%.3f")
        custom_demand_charge_kw = st.number_input("Custom Demand ($/kW-month)", min_value=0.0, value=0.00, step=1.00, format="%.2f")

# 6. Financial Assumptions (Asset Lifetime, NPV & Measure/Program Costs)
with st.sidebar.expander("Financial Assumptions", expanded=False):
    asset_life = st.number_input("Asset Lifetime (Years)", min_value=1, max_value=50, value=DEFAULT_ASSET_LIFE, step=1)
    discount_rate = st.number_input("Discount Rate / WACC (%)", min_value=0.0, max_value=25.0, value=DEFAULT_DISCOUNT_RATE, step=0.5, format="%.1f")
    escalation_rate = st.number_input("Grid Price Escalation (%)", min_value=-5.0, max_value=15.0, value=DEFAULT_ESCALATION_RATE, step=0.5, format="%.1f")
    degradation_rate = st.number_input("Annual Efficiency Decay (%)", min_value=0.0, max_value=10.0, value=DEFAULT_DEGRADATION_RATE, step=0.1, format="%.1f")

    st.markdown("---")
    gross_measure_cost = st.number_input("Gross Installed Measure Cost ($)", min_value=0.0, value=DEFAULT_GROSS_MEASURE_COST, step=250.0, format="%.2f", help="Total upfront equipment, materials, and installation labor cost.")
    utility_incentive = st.number_input("Utility Rebate / Incentive ($)", min_value=0.0, value=DEFAULT_UTILITY_INCENTIVE, step=50.0, format="%.2f", help="Customer rebate or financial incentive provided by utility.")
    utility_admin_cost = st.number_input("Utility Admin & Marketing Cost ($)", min_value=0.0, value=DEFAULT_UTILITY_ADMIN_COST, step=25.0, format="%.2f", help="Utility administrative, marketing, and processing costs per participant.")

# 7. Advanced: Custom CWFT File Path
with st.sidebar.expander("Advanced: Custom Data Files", expanded=False):
    use_custom_cwft = st.checkbox("Use Custom CWFT CSV File", value=True)
    cwft_filepath = st.text_input("CWFT CSV File Path", value="CWFT.csv")

run_simulation = st.sidebar.button("Run Valuation Engine", type="primary", use_container_width=True)

if 'simulation_executed' not in st.session_state:
    st.session_state['simulation_executed'] = False
if 'saved_runs' not in st.session_state:
    st.session_state['saved_runs'] = []

if run_simulation:
    st.session_state['simulation_executed'] = True

# ==============================================================================
# MAIN PANEL
# ==============================================================================
if not st.session_state['simulation_executed']:
    st.info("**Welcome:** Verify your setting panels in the sidebar and click **Run Valuation Engine** to execute calculations.")
    
    welcome_tab_instruct, welcome_tab_weather_gen = st.tabs([
        "Instructions & Setup",
        "AMY Weather Generator"
    ])
    
    with welcome_tab_instruct:
        st.markdown(
            """<div style="background-color: #F8FAFC; border: 1px solid #E2E8F0; padding: 30px; border-radius: 12px; margin-top: 10px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.05); font-family: sans-serif;">
<h3 style="margin-top: 0; color: #1E3A8A; font-weight: 700; border-bottom: 2px solid #DBEAFE; padding-bottom: 8px;">
Instructions: Preparing Inputs for Energy & Capacity Valuation
</h3>
<p style="color: #475569; line-height: 1.6; font-size: 1.05rem;">
To calculate both <strong>Energy Avoided Cost Savings</strong> and <strong>Capacity Deferral Savings (from CWFT)</strong> in a single run, the calculator requires two chronologically synchronized CSV files.
</p>
<h4 style="color: #0F766E; margin-top: 20px; font-weight: 600;">1. Load Profiles Input (<code>load_profiles.csv</code>)</h4>
<p style="color: #475569; line-height: 1.6; margin-bottom: 8px;">
This file contains the hourly electricity consumption (kW) for your baseline and proposed systems (e.g. standard vs. high-efficiency heat pump), typically simulated in EnergyPlus.
</p>
<ul style="padding-left: 20px; color: #475569; line-height: 1.6;">
<li><strong>Format:</strong> Must contain exactly <strong>8,760 rows</strong> of hourly data.</li>
<li><strong>Columns:</strong> An <code>Hour</code> index column (1 to 8760) and at least one load profile column (e.g. <code>Standard_Heat_Pump_kW</code>). You can include multiple columns to evaluate several systems side-by-side.</li>
<li><strong>Units:</strong> Electric demand must be in <strong>kilowatts (kW)</strong>.</li>
</ul>
<h4 style="color: #0F766E; margin-top: 20px; font-weight: 600;">2. Capacity Worth Factor Table Input (<code>CWFT.csv</code>)</h4>
<p style="color: #475569; line-height: 1.6; margin-bottom: 8px;">
This file allocates fixed annual generation capacity value ($/kW-yr) into hourly weights based on grid reliability risk.
</p>
<ul style="padding-left: 20px; color: #475569; line-height: 1.6;">
<li><strong>Format:</strong> Must contain exactly <strong>8,760 rows</strong>.</li>
<li><strong>Columns:</strong> An <code>Hour</code> index column (1 to 8760) and a <code>CWFT</code> column containing the allocation weights.</li>
<li><strong>Constraint:</strong> The sum of the <code>CWFT</code> column <strong>MUST equal exactly 1.0 (100%)</strong> so that the annual capacity value is precisely recovered.</li>
</ul>
<h4 style="color: #0F766E; margin-top: 20px; font-weight: 600;">How to Find an NREL URDB Rate Label</h4>
<p style="color: #475569; line-height: 1.6; margin-bottom: 8px;">
To import custom tariffs dynamically from NREL's OpenEI database:
</p>
<ol style="padding-left: 20px; color: #475569; line-height: 1.6;">
<li>Go to the <a href="https://openei.org/wiki/Utility_Rate_Database" target="_blank" style="color: #0D9488; font-weight: 600; text-decoration: underline;">NREL Utility Rate Database (URDB)</a>.</li>
<li>Search for your utility company (e.g., <em>"Georgia Power Co"</em>) and select your target rate plan.</li>
<li>Look at the URL in your browser address bar. The <strong>Rate Label</strong> is the final segment of the URL (e.g., in <code>https://openei.org/apps/USURDB/rate/view/5d4b00595457a3e73a0e6988</code>, the label is <code>5d4b00595457a3e73a0e6988</code>).</li>
</ol>
<h4 style="color: #B45309; margin-top: 25px; border-top: 1px solid #FED7AA; padding-top: 15px; font-weight: 600;">
Critical Alignment Rules to Satisfy Both Calculations
</h4>
<p style="color: #475569; line-height: 1.6; margin-bottom: 8px;">
Because grid risk and heat pump loads are highly non-linear and temperature-coincident, your files must align:
</p>
<ol style="padding-left: 20px; color: #475569; line-height: 1.6;">
<li><strong>Weather Year Match:</strong> Both the building load shape (E+ output) and the grid risk shape (CWFT) must represent the <strong>same historical weather year</strong> (e.g., 2012 AMY).</li>
<li><strong>Calendar Match:</strong> Both files must start on the same day of the week (e.g., if 2012 started on Sunday, Hour 1 must be Sunday for both load and CWFT).</li>
<li><strong>Local Standard Time:</strong> Disable daylight savings offsets in your building simulations to ensure hours 1 to 8760 line up exactly.</li>
</ol>
<p style="color: #64748B; font-style: italic; margin-top: 20px; border-top: 1px solid #E2E8F0; padding-top: 15px;">
<b>Note:</b> A default mock setup (dual-peak 2012 weather profile for AL/GA) will be written to <code>CWFT.csv</code> and <code>load_profiles.csv</code> automatically in your main directory if the files are not found on execution.
</p>
</div>""",
            unsafe_allow_html=True
        )
        
    with welcome_tab_weather_gen:
        render_weather_generator("welcome")
else:
    if not target_states:
        st.warning("**Selection Required:** Please choose at least one state in the sidebar multi-select.")
    else:
        try:
            # 1. Load profiles and grid aggregated data
            default_load_path = generate_default_load_profiles_file(load_profiles_filepath)
            load_profiles_df = load_load_profiles_from_csv(load_profiles_filepath)
            profile_columns = [col for col in load_profiles_df.columns if col != 'Hour']
            
            raw_df = load_and_aggregate_data(
                target_states, 
                selected_scenario, 
                weather_case, 
                target_year=meta_load_weather,
                planning_year=planning_year
            )
            datetime_series = raw_df['Datetime']
            
            # Retrieve mapped variables for reporting
            mapped_e_col = raw_df['Mapped_Energy_Col'].iloc[0] if raw_df['Mapped_Energy_Col'].iloc[0] else 'lmp_energy (default)'
            mapped_c_col = raw_df['Mapped_Carbon_Col'].iloc[0] if raw_df['Mapped_Carbon_Col'].iloc[0] else 'co2_combust (default)'
            
            # Load CWFT array
            if use_custom_cwft:
                generate_default_cwft_file(cwft_filepath)
                cwft_array = load_cwft_from_csv(cwft_filepath)
            else:
                cwft_array = raw_df['CWFT_derived'].to_numpy()
                
            results_df = calculate_avoided_costs(raw_df, cap_value, trans_value, dist_value, carbon_tax, cwft_array)
            
            # Setup Baseline and Proposed loads
            baseline_load = load_profiles_df[baseline_col].to_numpy()
            
            if dr_mode:
                dr_reduction, dr_indices = dispatch_dr_program(
                    datetime_series, cwft_array, dr_hours_per_year, dr_season, dr_max_hours_per_day, dr_capacity_kw, baseline_load
                )
                proposed_load = baseline_load - dr_reduction
                load_reduction = dr_reduction
                st.sidebar.info(f"DR Mode Active: {len(dr_indices)} hours dispatched. Proposed load is Baseline − DR.")
            else:
                proposed_load = load_profiles_df[proposed_col].to_numpy()
                load_reduction = baseline_load - proposed_load
            
            # 2. Retail Tariff Lost Revenue Calculations via URDB Compliance Engine
            if active_tariff_json is not None:
                ann_bill_baseline, bills_baseline = calculate_urdb_bill(baseline_load, datetime_series, active_tariff_json)
                ann_bill_proposed, bills_proposed = calculate_urdb_bill(proposed_load, datetime_series, active_tariff_json)
                tariff_name_label = active_tariff_json.get("name", tariff_type)
            else:
                # Custom Flat Rate Fallback
                fallback_rate_json = {
                    "fixedcharge": 0.0,
                    "energyratewindow": [[0]*24]*12,
                    "energyratestructure": [[{"rate": custom_rate_kwh}]]
                }
                if custom_demand_charge_kw > 0:
                    fallback_rate_json["demandratewindow"] = [[0]*24]*12
                    fallback_rate_json["demandratestructure"] = [[{"rate": custom_demand_charge_kw}]]
                    
                ann_bill_baseline, bills_baseline = calculate_urdb_bill(baseline_load, datetime_series, fallback_rate_json)
                ann_bill_proposed, bills_proposed = calculate_urdb_bill(proposed_load, datetime_series, fallback_rate_json)
                tariff_name_label = f"Custom Flat Rate (${custom_rate_kwh:.3f}/kWh)"
                
            annual_lost_revenue = ann_bill_baseline - ann_bill_proposed
            
            # Hourly Customer Retail Rate & Cost (for the Graphs tab's weekly charts)
            hourly_retail_rate = get_hourly_energy_rate(
                datetime_series,
                active_tariff_json if active_tariff_json is not None else fallback_rate_json
            )
            baseline_cost_hr = hourly_retail_rate * baseline_load
            proposed_cost_hr = hourly_retail_rate * proposed_load
            
            # 3. Grid Avoided Cost Calculations
            reduction_mwh = load_reduction / 1000.0
            
            gen_cap_savings_h = reduction_mwh * results_df['Gen_Capacity_Value_MWh'].to_numpy()
            trans_savings_h = reduction_mwh * results_df['Trans_Value_MWh'].to_numpy()
            dist_savings_h = reduction_mwh * results_df['Dist_Value_MWh'].to_numpy()
            energy_savings_h = reduction_mwh * results_df['Cambium_Energy_MWh'].to_numpy()
            emissions_savings_h = reduction_mwh * results_df['Emissions_Value_MWh'].to_numpy()
            total_savings_h = reduction_mwh * results_df['Total_Avoided_Cost_MWh'].to_numpy()
            
            annual_gen_cap_savings = gen_cap_savings_h.sum()
            annual_trans_savings = trans_savings_h.sum()
            annual_dist_savings = dist_savings_h.sum()
            annual_energy_savings = energy_savings_h.sum()
            annual_emissions_savings = emissions_savings_h.sum()
            annual_grid_savings = total_savings_h.sum()
            
            # 4. Multi-year NPV discounting
            years = np.arange(1, asset_life + 1)
            discount_pct = discount_rate / 100.0
            escalation_pct = escalation_rate / 100.0
            retail_escalation_pct = retail_escalation_rate / 100.0
            degradation_pct = degradation_rate / 100.0
            
            grid_esc_factors = (1 + escalation_pct) ** (years - 1)
            retail_esc_factors = (1 + retail_escalation_pct) ** (years - 1)
            deg_factors = (1 - degradation_pct) ** (years - 1)
            disc_factors = 1 / ((1 + discount_pct) ** years)
            
            grid_pv_multipliers = (grid_esc_factors * deg_factors) * disc_factors
            retail_pv_multipliers = (retail_esc_factors * deg_factors) * disc_factors
            
            npv_grid_savings = annual_grid_savings * grid_pv_multipliers.sum()
            npv_retail_lost_revenue = annual_lost_revenue * retail_pv_multipliers.sum()
            
            npv_net_savings = npv_grid_savings - npv_retail_lost_revenue
            
            # 4b. Cost-Effectiveness & Payback Tests (TRC, PCT, RIM, Payback)
            annual_cust_savings_stream = (annual_lost_revenue * retail_esc_factors * deg_factors)
            cost_tests = calculate_cost_effectiveness_tests(
                npv_grid_savings=npv_grid_savings,
                npv_lost_revenue=npv_retail_lost_revenue,
                npv_customer_bill_savings=npv_retail_lost_revenue,
                gross_measure_cost=gross_measure_cost,
                utility_incentive=utility_incentive,
                utility_admin_cost=utility_admin_cost,
                annual_customer_savings_stream=annual_cust_savings_stream,
                pv_multipliers=retail_pv_multipliers
            )
            trc_ratio = cost_tests["trc_ratio"]
            pct_ratio = cost_tests["pct_ratio"]
            rim_ratio = cost_tests["rim_ratio"]
            simple_payback = cost_tests["simple_payback"]
            discounted_payback = cost_tests["discounted_payback"]
            net_customer_cost = cost_tests["net_customer_cost"]
            
            # 5. Peak Coincidence, EPC & ELCC Proxy Math
            epc_baseline = (baseline_load * cwft_array).sum()
            epc_proposed = (proposed_load * cwft_array).sum()
            epc_reduction = (load_reduction * cwft_array).sum()
            
            elcc_baseline = epc_baseline / baseline_load.max() if baseline_load.max() > 0 else 0.0
            elcc_proposed = epc_proposed / proposed_load.max() if proposed_load.max() > 0 else 0.0
            # User adjustment: elcc_reduction is relative to baseline_peak_load
            elcc_reduction = epc_reduction / baseline_load.max() if baseline_load.max() > 0 else 0.0
            
            # Peak coincidence
            top_50_cwft_indices = np.argsort(-cwft_array)[:50]
            top_100_cwft_indices = np.argsort(-cwft_array)[:100]
            
            top_100_price_cutoff = results_df['Cambium_Energy_MWh'].nlargest(100).min()
            top_100_price_indices = np.where(results_df['Cambium_Energy_MWh'] >= top_100_price_cutoff)[0]
            
            coinc_50_base = baseline_load[top_50_cwft_indices].sum() / baseline_load.sum()
            coinc_50_prop = proposed_load[top_50_cwft_indices].sum() / proposed_load.sum()
            coinc_50_reduct = load_reduction[top_50_cwft_indices].sum() / load_reduction.sum() if load_reduction.sum() > 0 else 0.0
            
            coinc_100_base = baseline_load[top_100_cwft_indices].sum() / baseline_load.sum()
            coinc_100_reduct = load_reduction[top_100_cwft_indices].sum() / load_reduction.sum() if load_reduction.sum() > 0 else 0.0
            
            coinc_price_base = baseline_load[top_100_price_indices].sum() / baseline_load.sum()
            coinc_price_reduct = load_reduction[top_100_price_indices].sum() / load_reduction.sum() if load_reduction.sum() > 0 else 0.0
            
            # Peak vs Off-peak Average demand (Top 100 CWFT hours)
            peak_mask_100 = np.zeros(8760, dtype=bool)
            peak_mask_100[top_100_cwft_indices] = True
            
            avg_peak_base = baseline_load[peak_mask_100].mean()
            avg_peak_prop = proposed_load[peak_mask_100].mean()
            avg_peak_reduct = load_reduction[peak_mask_100].mean()
            
            avg_offpeak_base = baseline_load[~peak_mask_100].mean()
            avg_offpeak_prop = proposed_load[~peak_mask_100].mean()
            avg_offpeak_reduct = load_reduction[~peak_mask_100].mean()
            
            ratio_base = avg_peak_base / avg_offpeak_base if avg_offpeak_base > 0 else 0.0
            ratio_prop = avg_peak_prop / avg_offpeak_prop if avg_offpeak_prop > 0 else 0.0
            ratio_reduct = avg_peak_reduct / avg_offpeak_reduct if avg_offpeak_reduct > 0 else 0.0
            
            # Statistical Temperature-Load Weather Sensitivity Correlation Check
            months_arr = datetime_series.dt.month.to_numpy()
            temp_vals = results_df['Temperature_F'].to_numpy()
            
            heating_mask = np.isin(months_arr, [10, 11, 12, 1, 2, 3, 4, 5]) & (temp_vals < 60)
            cooling_mask = np.isin(months_arr, [6, 7, 8, 9]) & (temp_vals > 70)
            
            if heating_mask.sum() > 10:
                heat_corr = np.corrcoef(baseline_load[heating_mask], 60.0 - temp_vals[heating_mask])[0, 1]
            else:
                heat_corr = 0.0
                
            if cooling_mask.sum() > 10:
                cool_corr = np.corrcoef(baseline_load[cooling_mask], temp_vals[cooling_mask] - 70.0)[0, 1]
            else:
                cool_corr = 0.0
                
            if np.isnan(heat_corr):
                heat_corr = 0.0
            if np.isnan(cool_corr):
                cool_corr = 0.0
                
            max_corr = max(abs(heat_corr), abs(cool_corr))
            ws_style = get_weather_sensitivity_style(max_corr)
            weather_sensitivity_status = ws_style["label"]
            weather_color = ws_style["bg_color"]
            weather_text_color = ws_style["text_color"]
                
            weather_aligned = (meta_load_weather == meta_cambium_weather == meta_cwft_weather)
            alignment_status = f"{weather_sensitivity_status} | User Label: {'Aligned' if weather_aligned else 'Mixed'}"
            
            # ==================================================================
            # TABS DISPLAY
            # ==================================================================
            tab_setup, tab_summary, tab_calculator, tab_charts, tab_weather_diag, tab_scenarios, tab_diagnostics = st.tabs([
                "Setup & Calibration Guide",
                "Overview Scorecard",
                "Cost-Effectiveness Table",
                "Charts",
                "Weather & Peak Diagnostics",
                "Scenario Manager",
                "Diagnostics & Top Hours"
            ])

            # ------------------------------------------------------------------
            # TAB 1: SETUP & CALIBRATION GUIDE (moved to front — setup-stage tools)
            # ------------------------------------------------------------------
            with tab_setup:
                st.markdown("### EPW & Weather Calibration Guide")
                st.markdown(
                    """To conduct a valid Marginal Cost study for electric heat pumps, water heaters, or battery storage, 
the simulated hourly demand shapes must line up with the grid dataset chronologically."""
                )

                st.warning(
                    "**Critical alignment rules:**\n\n"
                    "1. **Weather Year Sync:** Ensure your building simulator uses the **2012 AMY (Actual Meteorological Year)** weather file (`.epw`). Mismatched years displace winter cold snaps, skewing the capacity coincidence value.\n\n"
                    "2. **Calendar Shift:** 2012 began on a **Sunday**. Ensure your load simulation starts on a Sunday so weekend occupied patterns align with Cambium grid weekday rate periods.\n\n"
                    "3. **Standard Time:** Standardize on **Local Standard Time (LST)** year-round. Mismatched daylight savings transitions displace load spikes by 1 hour, incorrectly zeroing out capacity savings."
                )

                st.markdown("---")
                st.markdown("### AMY Weather Generator (`diyepw`)")
                render_weather_generator("results")

            # ------------------------------------------------------------------
            # TAB 2: EXECUTIVE SUMMARY
            # ------------------------------------------------------------------
            with tab_summary:
                # Weather Sensitivity and Year Alignment Row
                st.markdown(
                    f"""<div style="background-color: {weather_color}; border: 1px solid {ws_style['border_color']}; padding: 15px; border-radius: 8px; margin-bottom: 20px; font-size: 0.95rem; color: {weather_text_color};">
<b>Weather Sensitivity Check (NOT year alignment):</b> <b>{weather_sensitivity_status}</b> (Max $r = {max_corr:.2f}$)<br>
• Heating Season Correlation: <b>{heat_corr:.2f}</b> | • Cooling Season Correlation: <b>{cool_corr:.2f}</b><br>
• Documented Weather Years: Load = <b>{meta_load_weather}</b> | Cambium Grid = <b>{meta_cambium_weather}</b> | CWFT = <b>{meta_cwft_weather}</b> {'(Aligned)' if weather_aligned else '(Mixed)'}<br>
<i>Note: This check confirms temperature-driven responsiveness of the load profile, NOT perfect chronological synchronization with Cambium weather. Users must still ensure matching weather years (e.g. 2012) are loaded for both.</i>
</div>""",
                    unsafe_allow_html=True
                )
                
                # Main KPI row
                col1, col2, col3, col4, col5 = st.columns(5)
                with col1:
                    st.metric(
                        label="Net Valuation NPV",
                        value=f"${npv_net_savings:,.2f}",
                        delta=f"Avoided - Lost Rev"
                    )
                with col2:
                    st.markdown(
                        ratio_card_html("Ratepayer Impact Measure (RIM)", f"{rim_ratio:.3f}", "NPV Benefit / NPV Cost", rim_ratio >= 1.0),
                        unsafe_allow_html=True
                    )
                with col3:
                    st.metric(
                        label="NPV Grid Avoided Costs",
                        value=f"${npv_grid_savings:,.2f}"
                    )
                with col4:
                    st.metric(
                        label="NPV Customer Bill Savings",
                        value=f"${npv_retail_lost_revenue:,.2f}"
                    )
                with col5:
                    st.metric(
                        label="EPC Reduction (kW)",
                        value=f"{epc_reduction:.2f} kW",
                        help="Effective Peak Contribution (EPC) reduction. Calculated as sum(Load Reduction * CWFT). This drives 100% of the Generation Capacity deferral savings value."
                    )
                    
                st.markdown("### Standard Practice Manual (SPM) & Customer Payback")
                ce_col1, ce_col2, ce_col3, ce_col4, ce_col5 = st.columns(5)
                with ce_col1:
                    st.markdown(
                        ratio_card_html("Total Resource Cost (TRC)", f"{trc_ratio:.3f}", "NPV Grid / (Measure + Admin)", trc_ratio >= 1.0),
                        unsafe_allow_html=True
                    )
                with ce_col2:
                    st.markdown(
                        ratio_card_html("Participant Cost Test (PCT)", f"{pct_ratio:.3f}", "(Bill Savings + Rebate) / Measure", pct_ratio >= 1.0),
                        unsafe_allow_html=True
                    )
                with ce_col3:
                    st.markdown(
                        ratio_card_html("Rate Impact Measure (RIM)", f"{rim_ratio:.3f}", "NPV Grid / (Lost Rev + Program)", rim_ratio >= 1.0),
                        unsafe_allow_html=True
                    )
                with ce_col4:
                    sp_str = f"{simple_payback:.1f} yrs" if simple_payback != float('inf') else "N/A"
                    st.metric(
                        label="Simple Payback",
                        value=sp_str,
                        help="Net Measure Cost (Cost - Rebate) divided by Year 1 Customer Bill Savings."
                    )
                with ce_col5:
                    dp_str = f"{discounted_payback:.1f} yrs" if discounted_payback != float('inf') else "N/A"
                    st.metric(
                        label="Discounted Payback",
                        value=dp_str,
                        help="Years to break even considering customer retail price escalation and discount rate."
                    )
                    
                st.markdown("### Capacity Contribution Metrics")
                c1, c2, c3 = st.columns(3)
                c1.metric(
                    label="EPC Reduction (kW)",
                    value=f"{epc_reduction:,.2f} kW",
                    help="Effective Peak Contribution (EPC) reduction. Calculated as sum(Load Reduction * CWFT). This drives 100% of the Generation Capacity deferral savings value."
                )
                c2.metric(
                    label="Baseline ELCC Proxy",
                    value=f"{elcc_baseline*100:.1f}%",
                    help="Baseline Effective Load Carrying Capability proxy. Calculated as EPC Baseline / Peak Baseline."
                )
                c3.metric(
                    label="Proposed ELCC Proxy",
                    value=f"{elcc_proposed*100:.1f}%",
                    help="Proposed Effective Load Carrying Capability proxy. Calculated as EPC Proposed / Peak Baseline."
                )
                
                st.markdown("<br>", unsafe_allow_html=True)
                
                # Quick Details
                col_info1, col_info2 = st.columns(2)
                with col_info1:
                    st.markdown("#### Valuation Run Settings")
                    st.markdown(
                        f"""- **Customer Retail Tariff:** `{tariff_name_label}`
- **NREL Wholesale Scenario:** `{selected_scenario}`
- **Selected Weather Case:** `{weather_case}`
- **Target Region:** `{', '.join(target_states)}`
- **Demand Response Mode:** `{"Active" if dr_mode else "Inactive"}`
- **Analysis Asset Horizon:** `{asset_life} years` (discount rate: {discount_rate}%)"""
                    )
                with col_info2:
                    st.markdown("#### Capacity & Value Reduction Summary")
                    st.markdown(
                        f"""- **Baseline Profile:** `{baseline_col}` (EPC: **{epc_baseline:.2f} kW**, ELCC: **{elcc_baseline * 100:.1f}%**)
- **Proposed Profile:** `{"DR Optimised Schedule" if dr_mode else proposed_col}` (EPC: **{epc_proposed:.2f} kW**, ELCC: **{elcc_proposed * 100:.1f}%**)
- **Peak Load Reduction:** `{load_reduction.max():,.2f} kW`
- **EPC Reduction:** `**{epc_reduction:.2f} kW**` *(drives capacity avoided costs)*
- **Load Reduction ELCC Proxy:** `**{elcc_reduction * 100:.1f}%**` *(EPC reduction / Baseline Peak)*
- **Annual Load Reduction:** `{(load_reduction).sum() / 1000:,.2f} MWh`"""
                    )
                    
            # ------------------------------------------------------------------
            # TAB 3: COST-EFFECTIVENESS TABLE
            # ------------------------------------------------------------------
            with tab_calculator:
                st.markdown("### Two-Sided Cost Effectiveness Table")
                st.markdown("Annual breakdown comparing retail bill reduction (cost to utility) against wholesale grid cost deferrals (benefit to utility).")
                
                # Compute energy vs demand split for lost revenue
                if active_tariff_json is not None:
                    # To split energy and demand in URDB, we create a flat energy copy of the json
                    energy_only_json = active_tariff_json.copy()
                    energy_only_json["demandratestructure"] = None
                    energy_only_json["demandratewindow"] = None
                    
                    bill_base_e, _ = calculate_urdb_bill(baseline_load, datetime_series, energy_only_json)
                    bill_prop_e, _ = calculate_urdb_bill(proposed_load, datetime_series, energy_only_json)
                    
                    retail_energy_savings = bill_base_e - bill_prop_e
                    retail_demand_savings = annual_lost_revenue - retail_energy_savings
                else:
                    retail_energy_savings = (load_reduction * custom_rate_kwh).sum()
                    retail_demand_savings = annual_lost_revenue - retail_energy_savings
                
                # Calculate PCAF peak hours demand reduction for T&D math trace
                pcaf_mask = results_df['PCAF_Weight'].to_numpy() > 0
                avg_reduct_pcaf = load_reduction[pcaf_mask].mean() if pcaf_mask.sum() > 0 else 0.0

                # Compile side-by-side values table
                data_table = {
                    "Valuation Component": [
                        "Wholesale Energy Savings",
                        "Generation Capacity Savings",
                        "Transmission Deferral Savings",
                        "Distribution Deferral Savings",
                        "Carbon Emissions Deferral",
                        "Total Grid Avoided Cost benefits",
                        "Retail Energy Bill reduction",
                        "Retail Demand Charge reduction",
                        "Total Customer bill savings (Lost Revenue)",
                        "Net Present Value (NPV) - Grid Savings",
                        "Net Present Value (NPV) - Lost Revenue",
                        "Net Present Value (NPV) - Net Benefit",
                        "Ratepayer Impact Measure (RIM) Ratio"
                    ],
                    "Annual Unit Rate": [
                        "Hourly Cambium Price",
                        f"${cap_value:,.2f}/kW-yr × {epc_reduction:.3f} kW EPC Reduction",
                        f"${trans_value:,.2f}/kW-yr × {avg_reduct_pcaf:.3f} kW Peak Reduction",
                        f"${dist_value:,.2f}/kW-yr × {avg_reduct_pcaf:.3f} kW Peak Reduction",
                        f"${carbon_tax:,.2f} /metric ton",
                        "Sum of Grid Components",
                        "URDB TOU/Energy blocks",
                        "URDB Peak Demand blocks",
                        "Sum of Tariff Components",
                        f"NPV over {asset_life} years @ {discount_rate}% WACC",
                        f"NPV over {asset_life} years @ {discount_rate}% WACC",
                        "Grid NPV - Lost Revenue NPV",
                        "Grid NPV / Lost Revenue NPV"
                    ],
                    "Value ($/yr)": [
                        annual_energy_savings,
                        annual_gen_cap_savings,
                        annual_trans_savings,
                        annual_dist_savings,
                        annual_emissions_savings,
                        annual_grid_savings,
                        retail_energy_savings,
                        retail_demand_savings,
                        annual_lost_revenue,
                        npv_grid_savings,
                        npv_retail_lost_revenue,
                        npv_net_savings,
                        rim_ratio
                    ]
                }
                df_val = pd.DataFrame(data_table)
                
                # Format output values
                def format_vals(val, name):
                    if "Ratio" in name:
                        return f"{val:.3f}"
                    return f"${val:,.2f}"
                df_val["Value ($/yr)"] = df_val.apply(lambda r: format_vals(r["Value ($/yr)"], r["Valuation Component"]), axis=1)
                
                st.dataframe(df_val, use_container_width=True, hide_index=True)
                
            # ------------------------------------------------------------------
            # TAB 4: CHARTS (all visualizations, grouped by audience)
            # ------------------------------------------------------------------
            with tab_charts:
                st.markdown("### Charts")
                st.caption("All grid, cost, and building-load visualizations for this run, grouped by audience.")

                # --- Group 1: Overall Scorecard ---
                st.markdown("#### Overall Scorecard — Lifetime Cash Flow")
                projected_grid_nominal = annual_grid_savings * grid_esc_factors * deg_factors
                projected_grid_disc = annual_grid_savings * grid_pv_multipliers
                projected_lost_disc = annual_lost_revenue * retail_pv_multipliers

                fig_lifetime = build_lifetime_npv_chart(
                    years, projected_grid_nominal, projected_grid_disc, projected_lost_disc
                )
                st.plotly_chart(fig_lifetime, use_container_width=True)

                st.markdown("---")
                # --- Group 2: Utility Cost Tests ---
                st.markdown("#### Utility Cost Tests — Annual Wholesale Avoided Cost Distribution")
                st.caption("Distribution of the wholesale energy, generation capacity (CWFT), transmission & distribution (PCAF), and emissions value.")

                fig_grid_full = build_annual_avoided_cost_chart(results_df)
                st.plotly_chart(fig_grid_full, use_container_width=True)

                col_st1, col_st2 = st.columns(2)
                with col_st1:
                    st.markdown("##### Winter morning peak details (Jan 1-7)")
                    winter_slice = results_df.iloc[0:168]
                    fig_w_stack = build_stacked_components_chart(winter_slice, show_legend=True)
                    st.plotly_chart(fig_w_stack, use_container_width=True)

                with col_st2:
                    st.markdown("##### Summer afternoon peak details (Jul 15-21)")
                    summer_slice = results_df.iloc[4680:4848]
                    fig_s_stack = build_stacked_components_chart(summer_slice, show_legend=False)
                    st.plotly_chart(fig_s_stack, use_container_width=True)

                st.markdown("##### Weekly Grid Avoided Cost Economics")
                selected_week = st.selectbox("Select Analysis Week Window", options=list(WEEK_WINDOWS.keys()), index=0)
                start_h, end_h = WEEK_WINDOWS[selected_week]

                dt_slice = datetime_series.iloc[start_h:end_h]
                baseline_slice = baseline_load[start_h:end_h]
                proposed_slice = proposed_load[start_h:end_h]
                reduction_slice = load_reduction[start_h:end_h]
                temp_slice = results_df['Temperature_F'].iloc[start_h:end_h].to_numpy()

                econ_view_mode = st.radio(
                    "Grid Economics View Mode",
                    options=["Stacked Components", "Individual Component Lines", "Total Marginal Cost ($/MWh)"],
                    horizontal=True,
                    help="Switch between stacked component areas, individual cost lines, or total marginal avoided cost."
                )

                slice_df = results_df.iloc[start_h:end_h].copy()
                slice_df['Load_Reduction_kW'] = reduction_slice
                slice_df['Hourly_Savings_hr'] = (reduction_slice / 1000.0) * slice_df['Total_Avoided_Cost_MWh']
                slice_df['Customer_Cost_Baseline_hr'] = baseline_cost_hr[start_h:end_h]
                slice_df['Customer_Cost_Proposed_hr'] = proposed_cost_hr[start_h:end_h]
                slice_df['Retail_Rate_kWh'] = hourly_retail_rate[start_h:end_h]

                fig_grid_econ = build_weekly_grid_economics_chart(slice_df, mode=econ_view_mode)
                st.plotly_chart(fig_grid_econ, use_container_width=True)

                total_week_savings = slice_df['Hourly_Savings_hr'].sum()
                total_week_customer_savings = (slice_df['Customer_Cost_Baseline_hr'] - slice_df['Customer_Cost_Proposed_hr']).sum()
                col_g1, col_g2 = st.columns(2)
                col_g1.caption(f"Total Grid Avoided Cost Value Created for `{selected_week}`: **${total_week_savings:,.2f}**")
                col_g2.caption(f"Total Customer Retail Bill Savings for `{selected_week}`: **${total_week_customer_savings:,.2f}**")

                st.markdown("---")
                # --- Group 3: Customer & Building Load ---
                st.markdown("#### Customer & Building Load — Weekly Demand vs. Outdoor Temperature")
                st.caption(f"Building heating/cooling demand vs. outdoor air temperature (°F) for `{selected_week}`.")
                fig_load_temp = build_weekly_load_and_temp_chart(
                    dt_slice, baseline_slice, proposed_slice, temp_slice
                )
                st.plotly_chart(fig_load_temp, use_container_width=True)

            # ------------------------------------------------------------------
            # TAB 5: WEATHER & PEAK COINCIDENCE DIAGNOSTICS
            # ------------------------------------------------------------------
            with tab_weather_diag:
                st.markdown("### Temperature & grid coincidence diagnostics")
                
                # Extreme temperature statistics
                temp_vals = results_df['Temperature_F'].to_numpy()
                min_t = temp_vals.min()
                max_t = temp_vals.max()
                hrs_15 = (temp_vals < 15.0).sum()
                hrs_95 = (temp_vals > 95.0).sum()
                hrs_100 = (temp_vals > 100.0).sum()
                
                # CWFT during coldest and hottest hours
                coldest_20_idx = np.argsort(temp_vals)[:20]
                hottest_20_idx = np.argsort(-temp_vals)[:20]
                avg_cwft_coldest = cwft_array[coldest_20_idx].mean()
                avg_cwft_hottest = cwft_array[hottest_20_idx].mean()
                
                st.markdown("#### Temperature distribution check")
                col_diag1, col_diag2, col_diag3, col_diag4, col_diag5 = st.columns(5)
                with col_diag1:
                    st.metric("Minimum temp", f"{min_t:.1f} °F")
                with col_diag2:
                    st.metric("Maximum temp", f"{max_t:.1f} °F")
                with col_diag3:
                    st.metric("Hours < 15°F", f"{hrs_15} hrs")
                with col_diag4:
                    st.metric("Hours > 95°F", f"{hrs_95} hrs")
                with col_diag5:
                    st.metric("Hours > 100°F", f"{hrs_100} hrs")
                    
                col_coinc1, col_coinc2 = st.columns(2)
                with col_coinc1:
                    st.metric("Avg CWFT during coldest 20 hours", f"{avg_cwft_coldest:.6f}")
                with col_coinc2:
                    st.metric("Avg CWFT during hottest 20 hours", f"{avg_cwft_hottest:.6f}")
                    
                st.markdown("<hr>", unsafe_allow_html=True)
                st.markdown("#### Peak coincidence metrics")
                st.markdown("Displays the share (%) of annual electricity energy consumption that occurs during critical high-stress grid hours.")
                
                coinc_table = {
                    "Coincidence Metric": [
                        "Energy share in top 50 CWFT hours (%)",
                        "Energy share in top 100 CWFT hours (%)",
                        "Energy share in highest 100 price hours (%)",
                        "Effective Peak Contribution (EPC) (kW)",
                        "Effective load carrying capability proxy (%)"
                    ],
                    "Baseline load": [
                        f"{coinc_50_base * 100:.2f}%",
                        f"{coinc_100_base * 100:.2f}%",
                        f"{coinc_price_base * 100:.2f}%",
                        f"{epc_baseline:.2f} kW",
                        f"{elcc_baseline * 100:.1f}%"
                    ],
                    "Proposed load": [
                        f"{coinc_50_prop * 100:.2f}%",
                        f"{proposed_load[top_100_cwft_indices].sum() / proposed_load.sum() * 100:.2f}%",
                        f"{proposed_load[top_100_price_indices].sum() / proposed_load.sum() * 100:.2f}%",
                        f"{epc_proposed:.2f} kW",
                        f"{elcc_proposed * 100:.1f}%"
                    ],
                    "Load reduction": [
                        f"{coinc_50_reduct * 100:.2f}%" if load_reduction.sum() > 0 else "0.00%",
                        f"{coinc_100_reduct * 100:.2f}%" if load_reduction.sum() > 0 else "0.00%",
                        f"{coinc_price_reduct * 100:.2f}%" if load_reduction.sum() > 0 else "0.00%",
                        f"{epc_reduction:.2f} kW",
                        f"{elcc_reduction * 100:.1f}%" if load_reduction.max() > 0 else "0.00%"
                    ]
                }
                st.dataframe(pd.DataFrame(coinc_table), use_container_width=True, hide_index=True)
                st.info("**ELCC & EPC Note:** EPC is the weighted average load during peak risk hours: `sum(Load * CWFT)`. The ELCC proxy represents the percentage of peak demand that contributes to capacity: `EPC / Peak Load` (or `EPC / Baseline Peak` for the load reduction resource).")
                
                st.markdown("<br>", unsafe_allow_html=True)
                st.markdown("#### Peak vs. Off-Peak Demand Diagnostics (Top 100 CWFT Hours)")
                st.markdown("Quantifies electricity demand behavior during the Top 100 reliability constraint hours vs. the rest of the year.")
                
                demand_diag_table = {
                    "Demand Metric": [
                        "Average Demand during Top 100 CWFT Peaks (kW)",
                        "Average Demand during Off-Peak Hours (kW)",
                        "Peak-to-Off-Peak Demand Ratio"
                    ],
                    "Baseline load": [
                        f"{avg_peak_base:.3f} kW",
                        f"{avg_offpeak_base:.3f} kW",
                        f"{ratio_base:.3f}"
                    ],
                    "Proposed load": [
                        f"{avg_peak_prop:.3f} kW",
                        f"{avg_offpeak_prop:.3f} kW",
                        f"{ratio_prop:.3f}"
                    ],
                    "Load reduction": [
                        f"{avg_peak_reduct:.3f} kW",
                        f"{avg_offpeak_reduct:.3f} kW",
                        f"{ratio_reduct:.3f}"
                    ]
                }
                st.dataframe(pd.DataFrame(demand_diag_table), use_container_width=True, hide_index=True)

            # ------------------------------------------------------------------
            # TAB 6: SCENARIO MANAGER (save/compare runs)
            # ------------------------------------------------------------------
            with tab_scenarios:
                st.markdown("### Scenario Manager")
                st.caption("Save the current run's key results under a name, then compare multiple runs side by side.")
                
                # Save scenario current run section
                col_save1, col_save2 = st.columns([3, 1])
                with col_save1:
                    scenario_run_name = st.text_input("Enter Scenario Run name to save", value="Base Run")
                with col_save2:
                    st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
                    if st.button("Save Current Run", type="secondary", use_container_width=True):
                        new_run = {
                            "Name": scenario_run_name,
                            "Grid Scenario": selected_scenario,
                            "Weather Case": weather_case,
                            "Retail Tariff": tariff_name_label,
                            "Alignment": alignment_status,
                            "Net NPV ($)": npv_net_savings,
                            "RIM Ratio": rim_ratio,
                            "ELCC proxy (%)": f"{elcc_reduction * 100:.1f}%",
                            "Gen Capacity savings ($)": annual_gen_cap_savings,
                            "T&D Deferral savings ($)": annual_trans_savings + annual_dist_savings,
                            "Lost Revenue ($)": annual_lost_revenue
                        }
                        st.session_state['saved_runs'].append(new_run)
                        st.success(f"Saved run '{scenario_run_name}' to scenario list!")
                        
                # Table of saved runs
                if st.session_state['saved_runs']:
                    st.markdown("#### Side-by-side run comparisons")
                    runs_df = pd.DataFrame(st.session_state['saved_runs'])
                    
                    st.dataframe(
                        runs_df.style.format({
                            "Net NPV ($)": "${:,.2f}",
                            "RIM Ratio": "{:.3f}",
                            "Gen Capacity savings ($)": "${:,.2f}",
                            "T&D Deferral savings ($)": "${:,.2f}",
                            "Lost Revenue ($)": "${:,.2f}"
                        }),
                        use_container_width=True, hide_index=True
                    )
                    
                    if st.button("Clear saved runs"):
                        st.session_state['saved_runs'] = []
                        st.rerun()
                else:
                    st.info("No saved runs. Give your current configuration a name and click **Save Current Run** to build a comparison database.")

            # ------------------------------------------------------------------
            # TAB 7: DIAGNOSTICS & TOP HOURS EXPORT
            # ------------------------------------------------------------------
            with tab_diagnostics:
                st.markdown("### Top avoided cost constraint hours")
                st.markdown("Exposes hours with highest value to verify temperature coincidences and clean calendar shifts.")

                with st.expander("Validation checks & capacity math trace", expanded=False):
                    # Check validation items
                    cwft_sum = cwft_array.sum()
                    capacity_math_ok = np.isclose(annual_gen_cap_savings, cap_value * (load_reduction * cwft_array).sum(), atol=1e-2)
                    shape_length_ok = (len(baseline_load) == 8760) and (len(proposed_load) == 8760)

                    st.markdown("#### Validation checks")
                    col_chk1, col_chk2, col_chk3, col_chk4 = st.columns(4)
                    with col_chk1:
                        if np.isclose(cwft_sum, 1.0, atol=1e-3):
                            st.success(f"Sum(CWFT) = {cwft_sum:.4f}")
                        else:
                            st.error(f"Sum(CWFT) = {cwft_sum:.4f}")
                    with col_chk2:
                        if capacity_math_ok:
                            st.success("Capacity ECC x EPC matches")
                        else:
                            st.warning("Capacity ECC x EPC warning")
                    with col_chk3:
                        if shape_length_ok:
                            st.success("Shapes match 8760 hrs")
                        else:
                            st.error("Shapes mismatch 8760 hrs")
                    with col_chk4:
                        st.info(f"Mapped: Energy $\\rightarrow$ `{mapped_e_col}`, Carbon $\\rightarrow$ `{mapped_c_col}`")

                    st.markdown("<br>", unsafe_allow_html=True)
                    st.markdown("#### Capacity avoided cost mathematical trace")
                    st.markdown(
                        f"""This trace proves the causality between building load shape reduction and capacity credits.
- **Generation Capacity avoided costs:**
  $$\\text{{Capacity Credit}} = \\text{{ECC}} \\times \\text{{EPC Reduction}} = \\${cap_value:,.2f}/\\text{{kW-yr}} \\times {epc_reduction:.4f}\\text{{ kW}} = \\mathbf{{\\${cap_value * epc_reduction:,.2f}/\\text{{yr}}}}$$
  *(Matches Gen Capacity Avoided Costs: **${annual_gen_cap_savings:,.2f}/yr**)*
- **Transmission Deferral avoided costs:**
  $$\\text{{Transmission Credit}} = \\text{{Transmission Scalar}} \\times \\text{{Peak Avg Reduction}} = \\${trans_value:,.2f}/\\text{{kW-yr}} \\times {avg_reduct_pcaf:.4f}\\text{{ kW}} = \\mathbf{{\\${trans_value * avg_reduct_pcaf:,.2f}/\\text{{yr}}}}$$
  *(Matches Transmission Deferral Avoided Costs: **${annual_trans_savings:,.2f}/yr**)*
- **Distribution Deferral avoided costs:**
  $$\\text{{Distribution Credit}} = \\text{{Distribution Scalar}} \\times \\text{{Peak Avg Reduction}} = \\${dist_value:,.2f}/\\text{{kW-yr}} \\times {avg_reduct_pcaf:.4f}\\text{{ kW}} = \\mathbf{{\\${dist_value * avg_reduct_pcaf:,.2f}/\\text{{yr}}}}$$
  *(Matches Distribution Deferral Avoided Costs: **${annual_dist_savings:,.2f}/yr**)*
"""
                    )

                top_limit = st.slider("Select number of peak hours to export", min_value=10, max_value=100, value=50, step=10)
                
                sort_col = st.selectbox("Sort top hours by:", ["Total avoided cost rate ($/MWh)", "CWFT weight", "Wholesale marginal energy price ($/MWh)"])
                
                results_df_present = results_df.copy()
                results_df_present.rename(columns={
                    'Hour': 'Hour index',
                    'Datetime': 'Date & Time',
                    'Cambium_Energy_MWh': 'Wholesale marginal energy price ($/MWh)',
                    'Gen_Capacity_Value_MWh': 'Generation capacity component ($/MWh)',
                    'Trans_Value_MWh': 'Transmission component ($/MWh)',
                    'Dist_Value_MWh': 'Distribution component ($/MWh)',
                    'Emissions_Value_MWh': 'Emissions component ($/MWh)',
                    'Total_Avoided_Cost_MWh': 'Total avoided cost rate ($/MWh)',
                    'CWFT': 'CWFT weight'
                }, inplace=True)
                
                top_hours = results_df_present.sort_values(by=sort_col, ascending=False).head(top_limit)
                
                st.dataframe(
                    top_hours[[
                        'Hour index', 'Date & Time', 'Temperature_F', 'Wholesale marginal energy price ($/MWh)',
                        'Generation capacity component ($/MWh)', 'Transmission component ($/MWh)',
                        'Distribution component ($/MWh)', 'Emissions component ($/MWh)',
                        'Total avoided cost rate ($/MWh)', 'CWFT weight'
                    ]].style.format({
                        'Date & Time': lambda x: x.strftime('%b %d, %H:%M'),
                        'Temperature_F': '{:.1f} °F',
                        'Wholesale marginal energy price ($/MWh)': '${:,.2f}',
                        'Generation capacity component ($/MWh)': '${:,.2f}',
                        'Transmission component ($/MWh)': '${:,.2f}',
                        'Distribution component ($/MWh)': '${:,.2f}',
                        'Emissions component ($/MWh)': '${:,.2f}',
                        'Total avoided cost rate ($/MWh)': '${:,.2f}',
                        'CWFT weight': '{:.6f}'
                    }),
                    use_container_width=True, hide_index=True
                )
                
                debug_csv = top_hours.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label=f"Download Top {top_limit} Stress Hours CSV",
                    data=debug_csv,
                    file_name=f"top_{top_limit}_stress_hours.csv",
                    mime="text/csv",
                    use_container_width=True
                )

        except Exception as e:
            st.error(f"**Data Processing/CSV Parsing Error:** {str(e)}")
            st.info("Check your inputs and file paths. Ensure files represent exactly 8760 hours.")
