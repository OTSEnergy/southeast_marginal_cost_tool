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
    SCENARIO_OPTIONS, SCENARIO_DESCRIPTIONS, CAMBIUM_DOC_URL,
    PLANNING_YEAR_OPTIONS, DEFAULT_PLANNING_YEAR_INDEX,
    WEATHER_CASE_OPTIONS, STATE_OPTIONS, DEFAULT_STATES,
    DEFAULT_CAP_VALUE, DEFAULT_TRANS_VALUE, DEFAULT_DIST_VALUE, DEFAULT_CARBON_TAX,
    CAP_VALUE_RANGE, TRANS_VALUE_RANGE, DIST_VALUE_RANGE, CARBON_TAX_RANGE,
    DEFAULT_ASSET_LIFE, DEFAULT_DISCOUNT_RATE, DEFAULT_ESCALATION_RATE,
    DEFAULT_RETAIL_ESCALATION, DEFAULT_DEGRADATION_RATE,
    DEFAULT_GROSS_MEASURE_COST, DEFAULT_UTILITY_INCENTIVE, DEFAULT_UTILITY_ADMIN_COST,
    DEFAULT_DR_HOURS_PER_YEAR, DEFAULT_DR_SEASON, DR_SEASON_OPTIONS,
    DEFAULT_DR_MAX_HOURS_PER_DAY, DEFAULT_DR_CAPACITY_KW,
    DEFAULT_DR_PERFORMANCE_FACTOR, DR_PERFORMANCE_FACTOR_RANGE,
    TARIFF_OPTIONS, GRID_COMPONENTS, WEEK_WINDOWS, COLORS,
    WEATHER_SENSITIVITY_STRONG, WEATHER_SENSITIVITY_MODERATE,
    get_weather_sensitivity_style,
    EXAMPLE_BUILDINGS, ratio_card_html, financial_metric_card_html,
    SOUTHEAST_PEAKER_PRESETS, SOUTHEAST_TD_PRESETS, DEFAULT_TD_PRESET,
    CWF_METHOD_OPTIONS, FEEDER_TYPE_OPTIONS,
    TOOL_DISCLAIMER_TEXT, TOOL_DISCLAIMER_HTML,
    SOUTHEAST_STATES, REGIONAL_PRESET_DISCLOSURE,
    AVAILABLE_EIA_STRESS_YEARS, DEFAULT_EIA_STRESS_YEAR,
    SYSTEM_STRESS_CWF_LABEL, CAMBIUM_NET_DEMAND_CWF_LABEL, CAMBIUM_SEASONAL_NET_DEMAND_CWF_LABEL, DEFAULT_SYSTEM_STRESS_PERCENTILE,
    SYSTEM_STRESS_PERCENTILE_RANGE, PROFILE_YEAR_BASIS_OPTIONS,
    PROFILE_INTERVAL_CONVENTION_OPTIONS, DEFAULT_PROFILE_INTERVAL_CONVENTION,
    STANDARD_UTC_OFFSET_OPTIONS, STATE_TIMEZONE_METADATA,
)
from visualizations import (
    build_weekly_overlay_chart,
    build_weekly_load_and_temp_chart,
    build_weekly_grid_economics_chart,
    build_annual_avoided_cost_chart,
    build_winter_summer_comparison_chart,
    build_lifetime_npv_chart,
    build_cost_duration_chart,
    build_top_risk_hours_chart,
    build_hour_month_heatmap,
    build_day_hour_heatmap,
    build_cumulative_cost_chart,
    plot_peaker_carrying_cost_breakdown,
    plot_southeast_cwf_distribution,
    plot_feeder_vs_system_load,
    build_economic_balance_chart,
    build_two_sided_cost_effectiveness_chart,
    plot_system_stress_vs_weather_cwf_comparison,
)
from calculations import (
    calculate_avoided_costs,
    dispatch_dr_program,
    calculate_cost_effectiveness_tests,
    calculate_regulated_fcr,
    calculate_ct_carrying_cost,
    calculate_southeast_dual_peak_cwf,
    calculate_cwf_temperature_exceedance,
    calculate_cwf_lolp_proxy,
    calculate_cwf_top_n,
    calculate_cwf_peaker_rent,
    calculate_feeder_pcaf_weights,
    find_peak_week,
    calculate_upper_tail_stress_weights,
    combine_ba_weights_to_state_portfolio,
    calculate_system_stress_capacity_metrics,
)
from system_stress_data import (
    evaluate_system_stress_capacity_proxy,
    resolve_profile_time_basis,
    parse_weather_year_from_case,
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
#                     See: calculate_urdb_bill(), GP_R31_URDB, AL_FD_URDB,
#                          AL_FDD_URDB, AL_RTA_URDB, AL_RTA_E_URDB
#
#   data_loaders.py - All file I/O, data ingestion, and mock generators:
#                     * Cambium CSV scanner + column mapping engine
#                     * CWFT loader/generator  (default is MOCK placeholder)
#                     * Load profile loader/generator (default is MOCK)
#                     * Weather file loader (.epw / .csv, real files supported)
#                     * URDB API fetch (live tariff download from NLR)
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
from billing import (
    calculate_urdb_bill,
    get_hourly_energy_rate,
    GP_R31_URDB,
    AL_FD_URDB,
    AL_FDD_URDB,
    AL_RTA_URDB,
    AL_RTA_E_URDB,
    DUKE_RES_URDB,
    TVA_LPC_URDB,
    MS_RS_URDB,
    ENTERGY_RS_URDB,
    SOUTHEAST_AVG_URDB,
)
from data_loaders import (
    INPUT_DIRECTORY,
    generate_default_cwft_file,
    load_cwft_from_csv,
    load_cwft_file,
    generate_default_load_profiles_file,
    load_load_profiles_from_csv,
    get_load_profile_warnings,
    generate_mock_state_file,
    file_matches_scenario,
    parse_cambium_columns,
    load_custom_weather_file,
    load_and_aggregate_data,
    fetch_urdb_rate,
    load_wmo_station_lookup,
    sanitize_filepath,
    load_cambium_net_demand_stress_weights,
)
from cambium_downloader import (
    check_missing_cambium_data,
    download_cambium_data,
    STATE_TO_BALANCING_AREAS,
    check_missing_cambium_gea_data_for_states,
    download_cambium_gea_data,
    download_missing_cambium_gea_data,
)

# ==============================================================================
# DATA LOADING & FILE GENERATION - imported from data_loaders.py
# ==============================================================================
# All data I/O has been moved to data_loaders.py. Here is what is imported
# and what each function does:
#
#   INPUT_DIRECTORY          './Cambium_Hourly_Data_raw' - where raw NLR CSVs live
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
#       REAL - Dynamic column mapping engine for NLR naming conventions.
#
#   load_custom_weather_file(weather_case)
#       REAL - Loads .epw or .csv weather files from Weather_Data_raw/.
#
#   load_and_aggregate_data(target_states, scenario, weather_case, ...)
#       REAL - Main ingestion pipeline. @st.cache_data applied below.
#
#   fetch_urdb_rate(rate_label, api_key)
#       REAL - Live API call to NLR OpenEI URDB for tariff download.
#
# Full implementations: data_loaders.py
# ==============================================================================

# Apply Streamlit caching to the data pipeline at the app level.
# data_loaders.py is Streamlit-free, so we wrap the import here.
load_and_aggregate_data = st.cache_data(load_and_aggregate_data)
load_wmo_station_lookup = st.cache_data(load_wmo_station_lookup)



# dispatch_dr_program() has been moved to calculations.py (imported above)


def render_weather_generator(key_suffix: str):
    st.markdown("### AMY EPW Weather Generator (`diyepw`)")
    st.markdown(
        """This utility automates the generation of **Actual Meteorological Year (AMY) EPW weather files** 
using PNNL's `diyepw` tool. It automatically downloads observations from the NOAA Integrated Surface Database (ISD),
interpolates missing points, and builds a customized `.epw` file using NLR's TMY3 as a template."""
    )
    
    st.info(
        "**Requirements:** Generating files requires an active internet connection to download "
        "NOAA observations (~1MB per station/year) and NLR TMY3 templates. The process may take 1-2 minutes."
    )
    
    station_lookup = load_wmo_station_lookup()

    col1, col2 = st.columns(2)
    with col1:
        manual_entry = st.checkbox(
            "Enter WMO Station ID manually",
            value=station_lookup.empty,
            disabled=station_lookup.empty,
            help="Use this if your station isn't in the search list below, or if you already know its 6-digit WMO ID.",
            key=f"wmo_manual_toggle_{key_suffix}"
        )

        if manual_entry:
            wmo_id = st.number_input(
                "WMO Station ID (6-digit)",
                min_value=100000,
                max_value=999999,
                value=722300, # Default: Birmingham-Shelby County AP, AL
                help="Check WMO IDs for your location from NOAA or climate databases. E.g. Atlanta, GA is 722190.",
                key=f"wmo_id_{key_suffix}"
            )
        else:
            labels = station_lookup["label"].tolist()
            default_idx = 0
            default_matches = station_lookup.index[station_lookup["wmo_id"] == "722300"].tolist()
            if default_matches:
                default_idx = station_lookup.index.get_loc(default_matches[0])

            selected_label = st.selectbox(
                "Weather Station (City, State)",
                options=labels,
                index=default_idx,
                help="Type to search by city or state name — this looks up the WMO Station ID for you.",
                key=f"wmo_station_search_{key_suffix}"
            )
            wmo_id = int(station_lookup.loc[station_lookup["label"] == selected_label, "wmo_id"].iloc[0])

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
        generate_button = st.button("Generate AMY Weather File", type="primary", width="stretch", key=f"generate_btn_{key_suffix}")
    
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

The **Weather Station (City, State)** search box above looks up the WMO ID for you — just type a city or state name and pick your station from the list. It's built from the same NLR/onebuilding.org station catalog shown on the [EnergyPlus Weather Data map](https://energyplus.net/weather).

If your station isn't in that list, check **"Enter WMO Station ID manually"** and look it up yourself:
1. **Interactive Map (Recommended):** Go to NLR's [EnergyPlus Weather Data map](https://energyplus.net/weather). Browse the map or search for your location using the search field. The 6-digit WMO ID is the number shown in parentheses in the station's title field (or in the filename of download options).
2. **Tabular Database:** Search the database at [Weather Station Identifiers](http://www.weathergraphics.com/identifiers/) to look up stations by state, city, or name.

*Note: The generator defaults to `722300` (Birmingham-Shelby County AP, AL). Other local examples: Atlanta Hartsfield-Jackson, GA is `722190`.*"""
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
    target_states = st.multiselect(
        "State(s)",
        options=STATE_OPTIONS,
        default=DEFAULT_STATES,
        help="Which state's Cambium grid price data to value against. Selecting more than one averages their hourly prices together into a single blended series."
    )
    if len(target_states) > 1:
        st.caption(f"Averaging grid prices across {len(target_states)} states: {', '.join(target_states)}.")
    non_se_selected = [s for s in target_states if s not in SOUTHEAST_STATES]
    if non_se_selected:
        st.caption(f"ℹ️ {REGIONAL_PRESET_DISCLOSURE}")

    selected_scenario = st.selectbox(
        "NLR Future Scenario",
        options=SCENARIO_OPTIONS,
        index=0,
        help="Select which NLR Cambium future power sector scenario to model."
    )
    if selected_scenario in SCENARIO_DESCRIPTIONS:
        st.caption(SCENARIO_DESCRIPTIONS[selected_scenario])

    st.markdown(
        f"""<details style="margin-top: 4px; margin-bottom: 12px; font-size: 0.82rem; color: #475569; background: #F8FAFC; padding: 8px 10px; border-radius: 6px; border: 1px solid #E2E8F0;">
  <summary style="cursor: pointer; font-weight: 600; color: #0284C7;">📖 Future Scenario Guide & Docs</summary>
  <div style="margin-top: 8px; line-height: 1.45;">
    <p style="margin-bottom: 6px;"><b>MidCase:</b> {SCENARIO_DESCRIPTIONS['MidCase']}</p>
    <p style="margin-bottom: 6px;"><b>HighDemandGrowth:</b> {SCENARIO_DESCRIPTIONS['HighDemandGrowth']}</p>
    <p style="margin-bottom: 6px;"><b>LowDemandGrowth:</b> {SCENARIO_DESCRIPTIONS['LowDemandGrowth']}</p>
    <p style="margin-bottom: 8px;"><b>LowCarbonConstraint:</b> {SCENARIO_DESCRIPTIONS['LowCarbonConstraint']}</p>
    <hr style="margin: 8px 0; border: none; border-top: 1px solid #CBD5E1;" />
    <p style="margin: 0; font-size: 0.8rem;">
      Full report & methodology: <br/>
      <a href="{CAMBIUM_DOC_URL}" target="_blank" style="color: #0284C7; font-weight: 600; text-decoration: underline;">Cambium 2024 Scenario Descriptions and Documentation</a>
    </p>
  </div>
</details>""",
        unsafe_allow_html=True
    )

    planning_year = st.selectbox(
        "NLR Planning Year",
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

    missing_in_sidebar = check_missing_cambium_data(target_states, selected_scenario, planning_year)
    if missing_in_sidebar:
        st.caption(f"⚡ *NLR data for {', '.join(missing_in_sidebar)} will auto-download on run.*")
    else:
        st.caption("✅ *Cambium grid data cached locally.*")

    st.markdown("---")
    st.markdown("**Avoided Emissions Valuation**")
    carbon_tax = st.slider(
        "Carbon Penalty ($/metric ton CO₂)",
        min_value=CARBON_TAX_RANGE[0],
        max_value=CARBON_TAX_RANGE[1],
        value=DEFAULT_CARBON_TAX,
        step=CARBON_TAX_RANGE[2],
        format="$%.2f",
        help="Monetizes marginal carbon emissions reductions based on Cambium CO₂ intensity ($/metric ton CO₂). Set to $0 for non-carbon evaluations."
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
    dr_performance_factor = DEFAULT_DR_PERFORMANCE_FACTOR

    if dr_mode:
        dr_hours_per_year = st.number_input("DR Call Hours per Year", min_value=1, max_value=8760, value=DEFAULT_DR_HOURS_PER_YEAR, step=5)
        dr_season = st.selectbox("DR Season of Applicability", DR_SEASON_OPTIONS)
        dr_max_hours_per_day = st.slider("Max Daily Call Hours", min_value=1, max_value=24, value=DEFAULT_DR_MAX_HOURS_PER_DAY)
        dr_capacity_kw = st.number_input("DR Curtailment Capacity (kW)", min_value=0.1, value=DEFAULT_DR_CAPACITY_KW, step=0.5, format="%.2f")
        dr_performance_factor = st.slider(
            "Capacity Accreditation Factor (%)",
            min_value=DR_PERFORMANCE_FACTOR_RANGE[0],
            max_value=DR_PERFORMANCE_FACTOR_RANGE[1],
            value=int(DEFAULT_DR_PERFORMANCE_FACTOR * 100),
            step=DR_PERFORMANCE_FACTOR_RANGE[2],
            help=(
                "De-rates this program's **Generation Capacity ($/kW-yr) credit only** — not its "
                "metered energy savings — to reflect expected non-performance, opt-outs, and M&V "
                "shortfall relative to nameplate curtailment. This is the DR analog of a generator's "
                "UCAP/ELCC accreditation factor: a 100 kW program at 85% is credited with 85 kW of "
                "firm capacity toward the reserve margin, even though it still delivers 100 kW of "
                "actual curtailment (and energy savings) when called."
            )
        ) / 100.0

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
            load_profiles_filepath = st.text_input(
                "Custom Load Profiles Path", 
                value="load_profiles.csv",
                help="Supports single CSV/Excel files (e.g. C:\\data\\hp_data.xlsx) or entire directories. Windows quoted paths ('Copy as path') are sanitized automatically."
            )
        elif "Load_Profiles_raw" in selected_load_option:
            load_profiles_filepath = "Load_Profiles_raw"
        else:
            load_profiles_filepath = "load_profiles.csv"

        load_profiles_filepath = sanitize_filepath(load_profiles_filepath)

    # Load profile case selection (Baseline vs Proposed)
    try:
        if load_profiles_filepath == "load_profiles.csv":
            generate_default_load_profiles_file("load_profiles.csv")
        load_profiles_df = load_load_profiles_from_csv(load_profiles_filepath)
        profile_columns = [col for col in load_profiles_df.columns if col != 'Hour']

        is_folder_mode = os.path.isdir(load_profiles_filepath)
        file_basename = os.path.basename(load_profiles_filepath) or load_profiles_filepath

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

            # Smart default indices for single file mode
            default_base_idx = 0
            default_prop_idx = 1 if len(profile_columns) > 1 else 0
            for idx, p in enumerate(profile_columns):
                p_low = p.lower()
                if any(k in p_low for k in ["erheat", "baseline", "standard", "electricresistance", "base", "no tes", "no_tes", "notes"]):
                    default_base_idx = idx
                elif any(k in p_low for k in ["heatpump", "proposed", "highefficiency", "hp", "tes", "efficient"]) and not any(k in p_low for k in ["no tes", "no_tes", "notes"]):
                    default_prop_idx = idx

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

        active_cols = [baseline_col] if dr_mode else [baseline_col, proposed_col]
        for w in get_load_profile_warnings(load_profiles_df, active_cols):
            st.warning(f"Load profile data gap: {w}")

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

# 4. Avoided Generation Capacity (CT Carrying Cost / IRP Benchmark)
with st.sidebar.expander("Total Economic Carrying Cost of a CT (ECC of a CT)", expanded=False):
    cap_mode = st.radio(
        "Capacity Valuation Method",
        options=["Direct IRP Scaler ($/kW-year)", "Carrying cost of a CT Builder"],
        index=0,
        help="Default: Direct IRP scalar pre-populated with calculated NLR ATB 2024 Combustion Turbine (CT) economic carrying cost ($110.20/kW-yr), or build custom capacity value using the CT Carrying Cost Builder."
    )

    ct_calc = None
    if "Carrying cost of a CT Builder" in cap_mode:
        selected_peaker_preset = st.selectbox(
            "Combustion Turbine (CT) Benchmark Preset",
            options=list(SOUTHEAST_PEAKER_PRESETS.keys()) + ["Custom Peaker Parameters"],
            index=0,
            help="Choose a pre-configured peaker benchmark from NLR Annual Technology Baseline (ATB 2024) or Southeast utility IRP dockets."
        )

        if selected_peaker_preset in SOUTHEAST_PEAKER_PRESETS:
            preset_data = SOUTHEAST_PEAKER_PRESETS[selected_peaker_preset]
            st.caption(preset_data["description"])
            if "source" in preset_data:
                st.caption(f"**Data Source:** {preset_data['source']}")
            def_capex = preset_data["capex_kw"]
            def_fom = preset_data["fom_kw_yr"]
            def_fcr = preset_data.get("fcr", 0.082) * 100.0
            def_wacc = preset_data.get("wacc", 0.070) * 100.0
            def_life = preset_data.get("life", 30)
            def_tax = preset_data.get("tax_rate", 0.257) * 100.0
            def_eas = preset_data.get("eas_offset_kw_yr", 0.0)
        else:
            def_capex, def_fom, def_fcr, def_wacc, def_life, def_tax, def_eas = 1100.0, 20.0, 8.20, 7.0, 30, 25.7, 0.0

        col_ct1, col_ct2 = st.columns(2)
        with col_ct1:
            ct_capex = st.number_input("Overnight CAPEX ($/kW)", min_value=100.0, max_value=3000.0, value=def_capex, step=25.0, format="%.1f",
                                       help="Overnight capital expenditure ($/kW) from NLR ATB (typical CT range: $950 – $1,250/kW).")
            ct_fcr = st.number_input("Fixed Charge Rate (FCR %)", min_value=1.0, max_value=30.0, value=def_fcr, step=0.1, format="%.2f",
                                     help="Annual Fixed Charge Rate (FCR) accounting for WACC, depreciation, taxes, and asset life (NLR ATB Regulated Utility: 7.5%–8.8%, Merchant: 9.5%–11.2%).")
        with col_ct2:
            ct_fom = st.number_input("Fixed O&M ($/kW-yr)", min_value=0.0, max_value=100.0, value=def_fom, step=0.5, format="%.2f",
                                     help="Annual fixed operations and maintenance cost ($/kW-yr) from NLR ATB (typical CT range: $15 – $25/kW-yr).")
            ct_eas = st.number_input("E&AS Offset ($/kW-yr)", min_value=0.0, max_value=50.0, value=def_eas, step=0.5, format="%.2f",
                                     help="Inframarginal energy/ancillary profit offset. Often $0 in Southeast cost-of-service IRPs (Gross CONE).")

        with st.expander("Financing & Tax Depreciation Detail (WACC / MACRS)", expanded=False):
            st.caption("Optionally calculate FCR from underlying utility WACC and 15-year MACRS depreciation tax shield:")
            col_fin1, col_fin2 = st.columns(2)
            with col_fin1:
                ct_wacc = st.number_input("Utility WACC (%)", min_value=1.0, max_value=15.0, value=def_wacc, step=0.1, format="%.2f")
                ct_tax = st.number_input("Corporate Tax (%)", min_value=0.0, max_value=40.0, value=def_tax, step=0.5, format="%.1f")
            with col_fin2:
                ct_life = st.number_input("Economic Life (yrs)", min_value=10, max_value=50, value=def_life, step=1)
                calc_fcr_toggle = st.checkbox("Use Synthesized WACC/MACRS FCR", value=False,
                                              help="When checked, computes FCR dynamically via Capital Recovery Factor (CRF) and MACRS depreciation rather than using the direct NLR ATB FCR.")

        if calc_fcr_toggle:
            fcr = calculate_regulated_fcr(wacc=ct_wacc/100.0, economic_life=ct_life, tax_rate=ct_tax/100.0)
            st.caption(f"Synthesized Regulated FCR: **{fcr*100:.2f}%**")
        else:
            fcr = ct_fcr / 100.0

        ct_calc = calculate_ct_carrying_cost(ct_capex, ct_fom, fcr, eas_offset_kw_yr=ct_eas)
        cap_value = ct_calc["net_capacity_cost"]
        st.metric(
            label="Calculated Avoided Capacity",
            value=f"${cap_value:,.2f}/kW-yr",
            delta=f"FCR: {fcr*100:.2f}% | Cap Recovery: ${ct_calc['capital_recovery_annuity']:,.2f} | FOM: ${ct_calc['fom_kw_yr']:,.2f}"
        )
        st.caption("Source: [Data | Electricity | 2024 | ATB | NLR](https://atb.nlr.gov/electricity/2024/data)")
    else:
        cap_value = st.number_input(
            "Total Economic Carrying Cost of a CT ($/kW-year)",
            min_value=CAP_VALUE_RANGE[0], max_value=CAP_VALUE_RANGE[1], value=DEFAULT_CAP_VALUE, step=CAP_VALUE_RANGE[2], format="%.2f",
            help="Commission-approved avoided generation capacity credit from utility IRP or PURPA docket (Total ECC of a CT). Default $110.20/kW-yr from NLR ATB 2024."
        )
        st.caption("Source: [Data | Electricity | 2024 | ATB | NLR](https://atb.nlr.gov/electricity/2024/data)")
        # Populate benchmark breakdown for waterfall visualization when default is unchanged
        if abs(cap_value - DEFAULT_CAP_VALUE) < 1e-4:
            ct_calc = calculate_ct_carrying_cost(1100.0, 20.00, 0.082)

# 5. Capacity Risk Allocation (CWF)
with st.sidebar.expander("Capacity Worth Factor (CWF)/ Capacity Risk Allocation", expanded=False):
    cwf_source_mode = st.radio(
        "Allocation Method",
        options=[
            CAMBIUM_SEASONAL_NET_DEMAND_CWF_LABEL,
            "Custom 8,760 File (CSV / Excel)",
        ],
        index=0,
        help=(
            "Select 'Seasonal Split Net-Demand (Cambium)' (default) to allocate capacity risk across state-level "
            "modeled net-demand peaks in winter and summer, or 'Custom 8,760 File' to upload your own 8,760 hourly CWF profile."
        ),
    )

    # Core background defaults
    selected_cwf_method = CAMBIUM_SEASONAL_NET_DEMAND_CWF_LABEL
    cwft_filepath = "CWFT.csv"
    cwft_uploaded_file = None
    winter_split_pct = 80.0
    freeze_threshold_f = 32.0
    heat_threshold_f = 90.0
    lag_days = 3
    lag_weight_pct = 30.0
    lolp_alpha = 4.0
    top_n_peak_hours = 100
    peaker_heat_rate = 10500.0
    peaker_gas_price = 3.50
    stress_percentile = DEFAULT_SYSTEM_STRESS_PERCENTILE
    profile_year_basis = "AMY"
    profile_interval_convention = DEFAULT_PROFILE_INTERVAL_CONVENTION
    profile_utc_offset = -5
    user_confirmed_utc_offset = False
    eia_api_key_session = st.session_state.get("eia_api_key_session", "")
    force_eia_cache_refresh = False

    if cwf_source_mode == CAMBIUM_SEASONAL_NET_DEMAND_CWF_LABEL:
        selected_cwf_method = CAMBIUM_SEASONAL_NET_DEMAND_CWF_LABEL
        st.caption(
            "**Seasonal Split Net-Demand (Cambium 2024 / 2023):** "
            "Evaluates state-level net-load (`busbar_load − variable_generation`) peak hours separately across "
            "Winter (Dec–Feb) and Summer (Jun–Sep), allocating capacity value between seasonal peaks. "
            "Prevents single-season dilution while grounding reliability in state-level modeled physical grid stress."
        )
        winter_split_pct = st.slider(
            "Winter Capacity Risk Share (%)",
            min_value=0.0,
            max_value=100.0,
            value=80.0,
            step=5.0,
            help="Percent of annual capacity value assigned to winter net-demand peak hours (remainder goes to summer net-demand peaks). Defaults to 80% to reflect Southeast winter heating peak risk."
        )
        top_n_peak_hours = st.slider(
            "Peak Hours (Annual)",
            min_value=50,
            max_value=1000,
            value=100,
            step=25,
            help="Total number of upper-tail net-demand peak hours evaluated across the year (default 100). Allocated between winter and summer according to seasonal capacity risk shares."
        )
        w_hrs_label = int(round(top_n_peak_hours * (winter_split_pct / 100.0)))
        s_hrs_label = top_n_peak_hours - w_hrs_label
        st.caption(
            f"Seasonal split: **{winter_split_pct:.0f}% Winter ({w_hrs_label} hrs)** / **{100.0 - winter_split_pct:.0f}% Summer ({s_hrs_label} hrs)** "
            f"across **{top_n_peak_hours} total peak hours**."
        )
        if target_states:
            try:
                from cambium_downloader import STATE_TO_BALANCING_AREAS
                state_bas_list = [f"{st}: {', '.join(STATE_TO_BALANCING_AREAS.get(st.upper(), []))}" for st in target_states]
                st.caption(f"📍 *Constituent Balancing Areas: {'; '.join(state_bas_list)}*")
            except Exception:
                pass
    else:
        selected_cwf_method = "Uploaded / Default CWFT CSV"
        st.caption("Upload or specify an 8,760-hour Capacity Worth Factor table (`.csv` or `.xlsx`). Values are auto-normalized to sum to 1.0.")
        cwft_uploaded_file = st.file_uploader(
            "Upload 8,760 CWF File (.csv, .xlsx)",
            type=["csv", "xlsx", "xls"],
            help="Select a CSV or Excel file containing an 8,760 hourly CWF profile (with a 'CWFT' column or single numeric column)."
        )
        cwft_filepath = st.text_input(
            "Or specify local file path",
            value="CWFT.csv",
            help="Local file path to load if no file is uploaded above."
        )
        cwft_filepath = sanitize_filepath(cwft_filepath)

# 6. Transmission & Distribution Deferral & Feeder
with st.sidebar.expander("T&D Deferral & Local Feeder Profile", expanded=False):
    td_options = list(SOUTHEAST_TD_PRESETS.keys()) + ["Custom T&D Values"]
    default_td_index = td_options.index(DEFAULT_TD_PRESET) if DEFAULT_TD_PRESET in td_options else 0
    selected_td_preset = st.selectbox(
        "Southeast T&D Benchmark Preset",
        options=td_options,
        index=default_td_index,
        help="Select empirical T&D deferral benchmarks from Southeast utility rate cases, exclude T&D, or enter custom values."
    )

    if selected_td_preset in SOUTHEAST_TD_PRESETS:
        td_data = SOUTHEAST_TD_PRESETS[selected_td_preset]
        st.caption(td_data["description"])
        def_dist = td_data["dist_value"]
        def_trans = td_data["trans_value"]
    else:
        def_dist = DEFAULT_DIST_VALUE
        def_trans = DEFAULT_TRANS_VALUE

    col_td1, col_td2 = st.columns(2)
    with col_td1:
        trans_value = st.number_input(
            "Transmission ($/kW-yr)",
            min_value=TRANS_VALUE_RANGE[0],
            max_value=TRANS_VALUE_RANGE[1],
            value=def_trans,
            step=TRANS_VALUE_RANGE[2],
            format="%.2f",
            key=f"td_trans_{selected_td_preset}",
            help="Bulk transmission capacity deferral credit ($/kW-yr). Allocated across top 100 system wholesale price hours."
        )
    with col_td2:
        dist_value = st.number_input(
            "Distribution ($/kW-yr)",
            min_value=DIST_VALUE_RANGE[0],
            max_value=DIST_VALUE_RANGE[1],
            value=def_dist,
            step=DIST_VALUE_RANGE[2],
            format="%.2f",
            key=f"td_dist_{selected_td_preset}",
            help="Local distribution capacity deferral credit ($/kW-yr). Allocated across local feeder peak hours."
        )

    combined_td = trans_value + dist_value
    if combined_td == 0.0:
        st.info("ℹ️ **T&D Deferral Excluded** ($0.00/kW-yr). Results reflect generation capacity & wholesale energy savings only.")
    else:
        st.caption(f"⚡ **Combined T&D Rate:** **\\${combined_td:,.2f}/kW-yr** (\\${trans_value:,.2f} Trans + \\${dist_value:,.2f} Dist)")

    st.markdown("---")
    st.markdown("**Distribution Peak Alignment**")
    selected_feeder_type = st.selectbox(
        "Local Distribution Feeder Peaking Type",
        options=FEEDER_TYPE_OPTIONS,
        index=0,
        help="Select whether the target distribution feeder/substation is winter-peaking (electric heating), "
             "summer-peaking (cooling), or follows system prices. Transmission deferral tracks bulk system peak "
             "while distribution deferral follows this local profile."
    )
    st.caption("💡 *Transmission deferral tracks bulk system peak hours; Distribution deferral tracks the local feeder profile selected above.*")

# 7. Retail Tariff & URDB Selector
with st.sidebar.expander("Retail Tariff Structure", expanded=True):
    lock_tariff = selected_example.get("tariff") if selected_example else None
    if lock_tariff and lock_tariff in TARIFF_OPTIONS:
        tariff_type = st.selectbox(
            "Retail Utility Tariff Type",
            options=TARIFF_OPTIONS,
            index=TARIFF_OPTIONS.index(lock_tariff),
            disabled=True,
            help="Define customer bill impact using packaged rates, pasting URDB JSONs, or querying the OpenEI API."
        )
        st.caption(f"Locked to {lock_tariff} by the selected example building, so all its variants are compared on the same rate.")
    else:
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
    elif tariff_type == "Alabama Power - Rate FD-D (Family Dwelling Demand)" or "FD-D" in tariff_type:
        active_tariff_json = AL_FDD_URDB
    elif tariff_type == "Alabama Power - Rate RTA (Residential Time Advantage - Demand)" or ("RTA" in tariff_type and "Energy Only" not in tariff_type and "RTA-E" not in tariff_type):
        active_tariff_json = AL_RTA_URDB
    elif tariff_type == "Alabama Power - Rate RTA-E (Residential Time Advantage - Energy Only)" or "RTA-E" in tariff_type or "Energy Only" in tariff_type:
        active_tariff_json = AL_RTA_E_URDB
    elif "Duke Energy Carolinas" in tariff_type:
        active_tariff_json = DUKE_RES_URDB
    elif "TVA LPC" in tariff_type:
        active_tariff_json = TVA_LPC_URDB
    elif "Mississippi Power" in tariff_type:
        active_tariff_json = MS_RS_URDB
    elif "Entergy" in tariff_type:
        active_tariff_json = ENTERGY_RS_URDB
    elif "Southeast Regional Average" in tariff_type:
        active_tariff_json = SOUTHEAST_AVG_URDB
    elif tariff_type in ["Import from NLR URDB (API Label)", "Import from NREL URDB (API Label)"]:
        urdb_label = st.text_input(
            "URDB Rate Label", 
            value="5d4b00595457a3e73a0e6988", 
            help="OpenEI unique tariff label (e.g. 5d4b00595457a3e73a0e6988)"
        )
        with st.expander("How to get the Rate Label"):
            st.markdown(
                """1. Go to NLR's [Utility Rate Database](https://openei.org/wiki/Utility_Rate_Database).
2. Search for your utility (e.g., *Georgia Power*) and select the target rate plan.
3. In the rate details page URL, copy the final segment (e.g., `5d4b00595457a3e73a0e6988` from `https://openei.org/apps/USURDB/rate/view/5d4b00595457a3e73a0e6988`)."""
            )
        urdb_api_key = st.text_input("OpenEI API Key", value="DEMO_KEY", type="password")

        if st.button("Fetch Tariff Structure", width="stretch"):
            with st.spinner("Downloading rate from NLR OpenEI..."):
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
        raw_pasted_json = st.text_area("Paste URDB JSON here", height=150, help="Paste a full NLR V3 utility rate JSON response.")
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
    discount_rate = st.number_input("Discount Rate / WACC (%)", min_value=0.0, max_value=25.0, value=DEFAULT_DISCOUNT_RATE, step=0.5, format="%.1f", help="The utility's cost of capital -- discounts the grid-side (utility) NPV streams.")
    customer_discount_rate = st.number_input("Customer Discount Rate (%)", min_value=0.0, max_value=25.0, value=discount_rate, step=0.5, format="%.1f", help="The homeowner's own discount rate for their bill-savings NPV and payback -- in practice often higher than a utility's WACC (personal opportunity cost of money, financing terms, risk tolerance). Defaults to match the WACC above; change it to model a more realistic customer perspective.")
    escalation_rate = st.number_input("Grid Price Escalation (%)", min_value=-5.0, max_value=15.0, value=DEFAULT_ESCALATION_RATE, step=0.5, format="%.1f")
    degradation_rate = st.number_input("Annual Efficiency Decay (%)", min_value=0.0, max_value=10.0, value=DEFAULT_DEGRADATION_RATE, step=0.1, format="%.1f")

    st.markdown("---")
    gross_measure_cost = st.number_input("Gross Installed Measure Cost ($)", min_value=0.0, value=DEFAULT_GROSS_MEASURE_COST, step=250.0, format="%.2f", help="Total upfront equipment, materials, and installation labor cost.")
    utility_incentive = st.number_input("Utility Rebate / Incentive ($)", min_value=0.0, value=DEFAULT_UTILITY_INCENTIVE, step=50.0, format="%.2f", help="Customer rebate or financial incentive provided by utility.")
    utility_admin_cost = st.number_input("Utility Admin & Marketing Cost ($)", min_value=0.0, value=DEFAULT_UTILITY_ADMIN_COST, step=25.0, format="%.2f", help="Utility administrative, marketing, and processing costs per participant.")

run_simulation = st.sidebar.button("Run Valuation Engine", type="primary", width="stretch")

if 'simulation_executed' not in st.session_state:
    st.session_state['simulation_executed'] = False
if 'saved_runs' not in st.session_state:
    st.session_state['saved_runs'] = []

if run_simulation:
    st.session_state['simulation_executed'] = True

if st.session_state.get('simulation_executed', False):
    if st.sidebar.button("🏠 Home / Info Screen", width="stretch", help="Return to the Instructions & Setup screen"):
        st.session_state['simulation_executed'] = False
        st.rerun()

st.sidebar.markdown("---")
st.sidebar.caption(f"⚠️ **Disclaimer:** {TOOL_DISCLAIMER_TEXT}")

# ==============================================================================
# MAIN PANEL
# ==============================================================================

# Top-of-UI Persona View Switcher (Future Use Case Mock-Up)
with st.container(border=True):
    mock_hdr_col, mock_ctrl_col, mock_home_col = st.columns([1.1, 1.8, 0.7], gap="medium")
    with mock_hdr_col:
        st.markdown(
            """<div style="padding-top: 2px;">
                <div style="display: flex; align-items: center; gap: 6px; margin-bottom: 3px;">
                    <span style="background: #E0F2FE; color: #0284C7; font-size: 0.68rem; font-weight: 800; padding: 2px 7px; border-radius: 4px; border: 1px solid #BAE6FD; letter-spacing: 0.5px;">MOCK-UP</span>
                    <span style="font-weight: 700; color: #0F172A; font-size: 0.92rem;">Stakeholder View</span>
                </div>
                <p style="margin: 0; font-size: 0.76rem; color: #64748B; line-height: 1.3;">
                    Non-functional future prototype for persona-tailored dashboards
                </p>
            </div>""",
            unsafe_allow_html=True
        )
    with mock_ctrl_col:
        view_mode = st.radio(
            "Stakeholder View Selector",
            options=["Utility", "Manufacturer", "Tech Research"],
            index=0,
            horizontal=True,
            label_visibility="collapsed",
            help="Non-functional mock-up demonstrating future UI tailoring for different stakeholder groups."
        )
    with mock_home_col:
        st.markdown("<div style='padding-top: 2px;'></div>", unsafe_allow_html=True)
        if st.button("🏠 Home", width="stretch", help="Return to the original Instructions & Setup info screen."):
            st.session_state['simulation_executed'] = False
            st.rerun()

    persona_notes = {
        "Utility": (
            "**Utility View**: Configured for IRP resource planners and regulatory commissions. "
            "Prioritizes generation capacity value (ECC of CT), TRC/RIM cost-effectiveness tests, and bulk transmission/local feeder coincident peak reductions."
        ),
        "Manufacturer": (
            "**Manufacturer View**: Configured for HVAC, heat pump, and thermal storage OEMs. "
            "Prioritizes customer electric bill savings, payback horizons, equipment COP curves under freeze conditions, and utility incentive optimization."
        ),
        "Tech Research": (
            "**Tech Research View**: Configured for national labs, universities, and energy modelers. "
            "Prioritizes full 8,760-hour marginal cost timeseries, temperature-driven LOLP risk curves, emissions abatement rates, and dynamic DR dispatch."
        )
    }

    st.markdown(
        f"""<div style="margin-top: 8px; padding: 8px 12px; background: #F8FAFC; border-left: 3px solid #0284C7; border-radius: 0 6px 6px 0; font-size: 0.80rem; color: #334155; line-height: 1.4;">
            💡 {persona_notes[view_mode]} <span style="color: #94A3B8; font-style: italic;">(Future use case preview — calculations currently unified)</span>
        </div>""",
        unsafe_allow_html=True
    )

st.write("")  # Clear vertical separation between header boxed card and dashboard content

if not st.session_state['simulation_executed']:
    st.info("**Welcome:** Verify your setting panels in the sidebar and click **Run Valuation Engine** to execute calculations.")
    
    welcome_tab_instruct, welcome_tab_weather_gen = st.tabs([
        "Instructions & Setup",
        "AMY Weather Generator"
    ])
    
    with welcome_tab_instruct:
        st.markdown(TOOL_DISCLAIMER_HTML, unsafe_allow_html=True)
        st.markdown("##### Before you run, check three things:")
        st.markdown(
            "1. **Load profile CSV** — 8,760 hourly rows; baseline + proposed columns (kW)\n"
            "2. **CWFT.csv** — 8,760 rows; capacity-risk weights that sum to 1.0\n"
            "3. **Weather years match** — load data, Cambium grid data, and CWFT all use the same year"
        )
        st.caption("No load/CWFT files yet? Default examples are generated automatically the first time you run.")
        st.info("💡 **Automated Grid Data:** Cambium hourly grid data is downloaded automatically on-demand from the NLR Scenario Viewer if not already cached locally.")

        with st.expander("NLR Cambium Auto-Downloader & Data Guide"):
            st.markdown(
                """**Automated On-Demand Retrieval:**
- When you select your target states and click **Run Valuation Engine**, the tool automatically checks `Cambium_Hourly_Data_raw/`.
- If missing, it connects directly to the NLR Scenario Viewer cloud data store, uses HTTP Range requests to target only your selected states/balancing areas, and extracts the CSVs in seconds (~2–4s per state).
- Extracted files remain cached locally in `Cambium_Hourly_Data_raw/` for 100% offline reuse.

**Manual Placement (Optional / Air-Gapped Environments):**
1. Visit the [NLR Cambium Scenario Viewer](https://scenarioviewer.nlr.gov/) or NLR data portal.
2. Select your desired dataset (e.g. Cambium 2024), **Scenario** (e.g. `MidCase`), **Geography / State** (e.g. `GA`, `AL`), and **Planning Horizon Year** (e.g. `2040`).
3. Download the hourly dataset and extract the `.csv` files into the `Cambium_Hourly_Data_raw/` directory in the project root."""
            )

        with st.expander("File format details (Load Profiles & CWFT)"):
            st.markdown(
                """**Load Profiles (`load_profiles.csv`)** — hourly electricity consumption (kW) for your baseline and proposed systems (e.g. standard vs. high-efficiency heat pump), typically simulated in EnergyPlus.
- **Format:** exactly 8,760 rows of hourly data.
- **Columns:** an `Hour` index column (1–8760) plus at least one load profile column (e.g. `Standard_Heat_Pump_kW`). Multiple columns can be included to compare several systems.
- **Units:** kilowatts (kW).

**Capacity Worth Factor Table (`CWFT.csv`)** — allocates fixed annual generation capacity value ($/kW-yr) into hourly weights based on grid reliability risk.
- **Format:** exactly 8,760 rows.
- **Columns:** an `Hour` index column (1–8760) and a `CWFT` column of allocation weights.
- **Constraint:** the `CWFT` column must sum to exactly 1.0 (100%) so annual capacity value is recovered precisely."""
            )

        with st.expander("How to find an NLR URDB rate label"):
            st.markdown(
                """1. Go to the [NLR Utility Rate Database (URDB)](https://openei.org/wiki/Utility_Rate_Database).
2. Search for your utility (e.g. *"Georgia Power Co"*) and select your target rate plan.
3. The **Rate Label** is the last segment of the URL — e.g. in `https://openei.org/apps/USURDB/rate/view/5d4b00595457a3e73a0e6988`, the label is `5d4b00595457a3e73a0e6988`."""
            )

        with st.expander("Why file alignment matters"):
            st.markdown(
                """Grid risk and building loads are both temperature-driven, so your files must line up hour-for-hour:
1. **Weather year match:** the building load shape (E+ output) and the grid risk shape (CWFT) must represent the same historical weather year (e.g. 2012 AMY).
2. **Calendar match:** both files must start on the same day of the week.
3. **Local standard time:** disable daylight savings in building simulations so hours 1–8760 line up exactly."""
            )

    with welcome_tab_weather_gen:
        render_weather_generator("welcome")
else:
    col_nav_home, col_nav_status = st.columns([1.2, 3.8])
    with col_nav_home:
        if st.button("← Back to Instructions & Setup", key="btn_nav_home_main", type="secondary"):
            st.session_state['simulation_executed'] = False
            st.rerun()
    with col_nav_status:
        st.caption("Viewing valuation dashboard. Click this button or '🏠 Home' above to return to setup instructions.")

    if not target_states:
        st.warning("**Selection Required:** Please choose at least one state in the sidebar multi-select.")
    else:
        # Pre-execution check: Verify Cambium hourly data is downloaded
        missing_states = check_missing_cambium_data(
            target_states=target_states,
            selected_scenario=selected_scenario,
            planning_year=planning_year
        )
        if missing_states:
            st.warning(
                f"⚠️ **Cambium Grid Data Missing:** Hourly grid data for state(s) **{', '.join(missing_states)}** "
                f"({selected_scenario} | Planning Year {planning_year}) is not yet in local storage."
            )
            col_dl_btn, col_dl_info = st.columns([1.6, 3.4])
            with col_dl_btn:
                if st.button(
                    f"📥 Auto-Download from NLR ({', '.join(missing_states)})",
                    key="btn_auto_download_cambium",
                    type="primary"
                ):
                    prog_bar = st.progress(0, text="Connecting to NLR Scenario Viewer...")
                    try:
                        def _cb(msg, frac):
                            prog_bar.progress(int(frac * 100), text=msg)
                        download_cambium_data(
                            target_states=missing_states,
                            selected_scenario=selected_scenario,
                            planning_year=planning_year,
                            progress_callback=_cb
                        )
                        st.success(f"Downloaded and extracted grid data for {', '.join(missing_states)}!")
                        st.rerun()
                    except Exception as dl_err:
                        st.error(f"Failed to auto-download from NLR: {dl_err}")
            with col_dl_info:
                st.caption(
                    "The tool automatically streams only the required balancing area CSVs directly from NLR's cloud storage "
                    "using HTTP range requests (~2–4 seconds per state) and saves them locally for permanent offline reuse."
                )

            # Look up specific balancing areas and sample filenames for missing states
            needed_bas = []
            for st_code in missing_states:
                bas = STATE_TO_BALANCING_AREAS.get(st_code.upper(), [])
                needed_bas.extend(bas)
            needed_bas_str = ", ".join(needed_bas) if needed_bas else "constituent balancing areas"
            sample_filenames = [
                f"`Cambium24_{selected_scenario}_hourly_{ba}_{planning_year}.csv`" for ba in needed_bas[:4]
            ]
            sample_str = ", ".join(sample_filenames)
            raw_dir_abs = os.path.abspath("./Cambium_Hourly_Data_raw")

            with st.expander("🛠️ Manual Download Instructions & File Placement Guide (Fallback)", expanded=False):
                st.markdown(
                    f"""
                    ### How to Manually Download and Place Cambium Grid Data
                    If the automated cloud download fails (for example, if NLR's upstream AWS S3 cloud storage returns `HTTP 403 Forbidden` due to backend IAM restrictions, or if your machine is behind a firewall):

                    1. **Open the NLR Scenario Viewer**:
                       - Go to the [NLR Cambium Scenario Viewer](https://scenarioviewer.nlr.gov/?project=5c7bef16-7e38-4094-92ce-8b03dfa93380) or the [NLR Cambium Datasets Portal](https://www.nlr.gov/analysis/cambium.html).
                    2. **Locate the Package**:
                       - Filter by **Scenario**: `{selected_scenario}`
                       - Filter by **Time Resolution**: `hourly`
                       - Filter by **Location Type**: `Balancing Areas`
                       - Download the dataset package ZIP (e.g., `Cambium24_{selected_scenario}_hourly_balancingArea.zip`).
                    3. **Extract the Balancing Area CSV File(s)**:
                       - Required Balancing Areas for **{', '.join(missing_states)}**: **{needed_bas_str}**
                       - Files needed: {sample_str}
                    4. **Place the Files in `./Cambium_Hourly_Data_raw/`**:
                       - Copy the extracted `.csv` files into the local folder:
                         ```
                         ./Cambium_Hourly_Data_raw/
                         ```
                       - Destination folder path: `{raw_dir_abs}`
                    5. **Rerun the Tool**:
                       - Once the CSV files are placed in that folder, click the **Rerun** button in the top right or press **R** to resume analysis immediately.
                    """
                )
            st.stop()

        # Pre-execution check: If Cambium Net-Demand proxy is selected with GEA mode, verify GEA data
        # Note: Default aggregation_level is "state", which is already checked and handled by check_missing_cambium_data above.

        try:
            # 1. Load profiles and grid aggregated data
            if load_profiles_filepath == "load_profiles.csv":
                generate_default_load_profiles_file("load_profiles.csv")
            load_profiles_df = load_load_profiles_from_csv(load_profiles_filepath)
            profile_columns = [col for col in load_profiles_df.columns if col != 'Hour']
            active_cols = [baseline_col] if dr_mode else [baseline_col, proposed_col]
            for w in get_load_profile_warnings(load_profiles_df, active_cols):
                st.warning(f"Load profile data gap: {w}")
            
            raw_df, cambium_ingestion_warnings = load_and_aggregate_data(
                target_states,
                selected_scenario,
                weather_case,
                target_year=meta_load_weather,
                planning_year=planning_year
            )
            for w in cambium_ingestion_warnings:
                st.warning(f"Cambium data file skipped: {w}")
            datetime_series = raw_df['Datetime']
            
            # Retrieve mapped variables for reporting
            mapped_e_col = raw_df['Mapped_Energy_Col'].iloc[0] if raw_df['Mapped_Energy_Col'].iloc[0] else 'lmp_energy (default)'
            mapped_c_col = raw_df['Mapped_Carbon_Col'].iloc[0] if raw_df['Mapped_Carbon_Col'].iloc[0] else 'co2_combust (default)'
            
            # Setup Baseline and Proposed loads
            baseline_load = load_profiles_df[baseline_col].to_numpy()

            # Extract hourly temperature array (if present from EPW weather)
            temp_arr = raw_df['Temperature_F'].to_numpy() if 'Temperature_F' in raw_df.columns else None
            weather_source_attr = raw_df.attrs.get(
                "weather_source",
                str(raw_df["Weather_Source"].iloc[0]) if "Weather_Source" in raw_df.columns else "measured_file",
            )

            # Reference Weather-Based Dual-Peak CWF (always computed for comparator & fallback)
            weather_comparator_cwft = calculate_southeast_dual_peak_cwf(
                datetime_series=datetime_series,
                winter_weight=winter_split_pct / 100.0,
                summer_weight=(100.0 - winter_split_pct) / 100.0,
                temperature_array=temp_arr,
                freeze_threshold_f=freeze_threshold_f,
                heat_threshold_f=heat_threshold_f,
                lag_days=lag_days,
                lag_weight=lag_weight_pct / 100.0,
            )

            system_stress_eval = None
            cambium_stress_eval = None
            effective_cwf_method = selected_cwf_method

            # Capacity Risk Allocation (CWF Array)
            if selected_cwf_method in [CAMBIUM_SEASONAL_NET_DEMAND_CWF_LABEL, CAMBIUM_NET_DEMAND_CWF_LABEL]:
                is_seasonal = (selected_cwf_method == CAMBIUM_SEASONAL_NET_DEMAND_CWF_LABEL)
                cambium_stress_eval = load_cambium_net_demand_stress_weights(
                    target_states=target_states,
                    selected_scenario=selected_scenario,
                    planning_year=planning_year,
                    raw_directory="./Cambium_Hourly_Data_raw",
                    custom_tz=profile_utc_offset,
                    seasonal_split=is_seasonal,
                    winter_weight=winter_split_pct / 100.0 if is_seasonal else 0.60,
                    summer_weight=(100.0 - winter_split_pct) / 100.0 if is_seasonal else 0.40,
                    aggregation_level="state",
                    top_n_peak_hours=top_n_peak_hours,
                )
                if cambium_stress_eval.get("is_qualified"):
                    cwft_array = cambium_stress_eval["cwft_array"]
                    effective_cwf_method = selected_cwf_method
                    w_diag = cambium_stress_eval['diagnostics'].get('active_winter_hours', int(round(top_n_peak_hours * (winter_split_pct / 100.0))))
                    s_diag = cambium_stress_eval['diagnostics'].get('active_summer_hours', top_n_peak_hours - w_diag)
                    tot_diag = cambium_stress_eval['diagnostics'].get('active_hours', top_n_peak_hours)
                    split_desc = (
                        f"Seasonal split ({winter_split_pct:.0f}% Winter [{w_diag} hrs] / {100.0 - winter_split_pct:.0f}% Summer [{s_diag} hrs])"
                        if is_seasonal else "Annual exceedance"
                    )
                    st.info(
                        f"ℹ️ **Cambium State-Level Net-Demand Proxy Active:** {split_desc} "
                        f"evaluated for {', '.join(target_states)} (BAs: {', '.join(cambium_stress_eval.get('needed_bas', []))}), "
                        f"modeled year {planning_year}, 2012 weather basis. Active stress hours: {tot_diag}."
                    )
                else:
                    cwft_array = weather_comparator_cwft
                    effective_cwf_method = f"Southeast Dual-Peak (Weather Fallback: {cambium_stress_eval.get('status', 'missing data')})"
                    st.warning(
                        f"⚠️ **Cambium Net-Demand Notice:** {cambium_stress_eval.get('warning', 'Missing constituent BA files')}. "
                        "Using Southeast Dual-Peak weather capacity weights as fallback."
                    )
            elif selected_cwf_method in [SYSTEM_STRESS_CWF_LABEL, CAMBIUM_NET_DEMAND_CWF_LABEL]:
                effective_stress_weather_case = (
                    meta_load_weather if weather_case == "Baseline" else weather_case
                )
                system_stress_eval = evaluate_system_stress_capacity_proxy(
                    selected_states=target_states,
                    weather_case=effective_stress_weather_case,
                    weather_fallback_cwft=weather_comparator_cwft,
                    profile_year_basis=profile_year_basis,
                    weather_source=weather_source_attr,
                    utc_offset_hours=profile_utc_offset,
                    user_confirmed_offset=user_confirmed_utc_offset,
                    interval_convention=profile_interval_convention,
                    percentile=stress_percentile,
                    api_key=eia_api_key_session,
                    force_refresh=force_eia_cache_refresh,
                    load_df=load_profiles_df,
                    active_profile_cols=active_cols,
                    datetime_series=datetime_series,
                    cambium_planning_year=planning_year,
                    stress_year=selected_stress_year,
                )
                cwft_array = system_stress_eval["cwft_array"]
                effective_cwf_method = system_stress_eval["effective_method"]
                for sw in system_stress_eval.get("warnings", []):
                    if system_stress_eval.get("fallback_triggered"):
                        st.warning(f"⚠️ **System-Stress Proxy Notice:** {sw}")
                    else:
                        st.info(f"ℹ️ **System-Stress Proxy Notice:** {sw}", icon="ℹ️")
                if cwft_array is None:
                    st.error("System-stress capacity weights and weather fallback are both unavailable.")
                    st.stop()
            elif "Southeast Dual-Peak" in selected_cwf_method:
                cwft_array = weather_comparator_cwft
            elif "Ambient Temperature Severity" in selected_cwf_method:
                weather_arr = temp_arr if temp_arr is not None else np.full(len(datetime_series), 65.0)
                cwft_array = calculate_cwf_temperature_exceedance(
                    temperature_array=weather_arr,
                    datetime_series=datetime_series,
                    freeze_threshold_f=freeze_threshold_f,
                    heat_threshold_f=heat_threshold_f,
                    winter_weight=winter_split_pct / 100.0,
                    summer_weight=(100.0 - winter_split_pct) / 100.0
                )
            elif "Cambium Price-Exceedance LOLP" in selected_cwf_method:
                cwft_array = calculate_cwf_lolp_proxy(raw_df['Cambium_Energy_MWh'].to_numpy(), alpha=lolp_alpha)
            elif "Top-N Peak Hours" in selected_cwf_method:
                cwft_array = calculate_cwf_top_n(raw_df['Cambium_Energy_MWh'].to_numpy(), top_n=top_n_peak_hours, weighting_method="exceedance")
            elif "Wholesale Peaker Rent" in selected_cwf_method:
                cwft_array = calculate_cwf_peaker_rent(raw_df['Cambium_Energy_MWh'].to_numpy(), heat_rate=peaker_heat_rate, gas_price=peaker_gas_price)
            else:
                if cwft_uploaded_file is not None:
                    cwft_array = load_cwft_file(cwft_uploaded_file)
                else:
                    if cwft_filepath == "CWFT.csv":
                        generate_default_cwft_file("CWFT.csv")
                    cwft_array = load_cwft_file(cwft_filepath)

            # Localized Feeder Distribution Weights
            dist_weight_array = calculate_feeder_pcaf_weights(
                feeder_type=selected_feeder_type,
                load_array=baseline_load,
                price_array=raw_df['Cambium_Energy_MWh'].to_numpy(),
                datetime_series=datetime_series,
                top_n=100
            )

            results_df = calculate_avoided_costs(
                raw_df, cap_value, trans_value, dist_value, carbon_tax, cwft_array, dist_weight_array=dist_weight_array
            )

            if dr_mode:
                dr_reduction, dr_indices = dispatch_dr_program(
                    datetime_series, cwft_array, dr_hours_per_year, dr_season, dr_max_hours_per_day, dr_capacity_kw, baseline_load
                )
                proposed_load = baseline_load - dr_reduction
                load_reduction = dr_reduction
                st.sidebar.info(f"DR Mode Active: {len(dr_indices)} hours dispatched. Proposed load is Baseline − DR.")
                if selected_cwf_method == SYSTEM_STRESS_CWF_LABEL:
                    st.warning(
                        "⚠️ **DR Dispatch Rescheduling Notice:** In Demand Response mode, selecting the "
                        "**Public-data system-stress proxy (EIA)** reschedules DR curtailment into the highest "
                        "observed BA net-demand hours. Because the dispatched hours change, **Wholesale Energy "
                        "savings, Customer Retail Bills, and T&D deferral can also change** alongside Generation "
                        "Capacity. See the **Same-Dispatch Weather Comparator** table below to isolate pure "
                        "capacity valuation differences on the identical dispatch schedule."
                    )
            else:
                proposed_load = load_profiles_df[proposed_col].to_numpy()
                load_reduction = baseline_load - proposed_load

            # Generation-capacity accreditation derate: DR programs rarely deliver
            # 100% of nameplate curtailment when called (opt-outs, non-performance,
            # M&V shortfall), so only a fraction of load_reduction counts as firm
            # capacity for the Gen Capacity ($/kW-yr) credit. Metered energy savings
            # (and T&D deferral, which is driven by actual local coincidence rather
            # than a portfolio-wide reliability statistic) are left undiminished.
            dr_capacity_derate = dr_performance_factor if dr_mode else 1.0
            
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
            
            # Hourly Customer Retail Rate & Cost (for the Graphs tab's weekly, duration,
            # and cumulative charts). get_hourly_energy_rate() only reflects the first
            # tier's rate (see its docstring) and ignores the fixed monthly charge, so
            # the raw hourly product alone won't sum to the same annual total as
            # calculate_urdb_bill() above for a tiered tariff or usage that crosses a
            # tier threshold. Rescale each hourly series so it sums to the exact
            # official annual bill -- preserves the hourly shape the charts need while
            # keeping every tab's annual $ totals reconciled with each other.
            hourly_retail_rate = get_hourly_energy_rate(
                datetime_series,
                active_tariff_json if active_tariff_json is not None else fallback_rate_json
            )
            baseline_cost_hr = hourly_retail_rate * baseline_load
            proposed_cost_hr = hourly_retail_rate * proposed_load
            baseline_hr_sum = baseline_cost_hr.sum()
            proposed_hr_sum = proposed_cost_hr.sum()
            if baseline_hr_sum > 0:
                baseline_cost_hr = baseline_cost_hr * (ann_bill_baseline / baseline_hr_sum)
            if proposed_hr_sum > 0:
                proposed_cost_hr = proposed_cost_hr * (ann_bill_proposed / proposed_hr_sum)
            
            # 3. Grid Avoided Cost Calculations
            reduction_mwh = load_reduction / 1000.0
            # Capacity-accreditation-derated reduction, used for the Generation Capacity
            # component only (see dr_capacity_derate above).
            capacity_reduction_mwh = reduction_mwh * dr_capacity_derate

            gen_cap_savings_h = capacity_reduction_mwh * results_df['Gen_Capacity_Value_MWh'].to_numpy()
            trans_savings_h = reduction_mwh * results_df['Trans_Value_MWh'].to_numpy()
            dist_savings_h = reduction_mwh * results_df['Dist_Value_MWh'].to_numpy()
            energy_savings_h = reduction_mwh * results_df['Cambium_Energy_MWh'].to_numpy()
            emissions_savings_h = reduction_mwh * results_df['Emissions_Value_MWh'].to_numpy()
            # Summed explicitly (rather than reduction_mwh * Total_Avoided_Cost_MWh) since
            # the Gen Capacity component above may use a different (derated) reduction basis.
            total_savings_h = gen_cap_savings_h + trans_savings_h + dist_savings_h + energy_savings_h + emissions_savings_h
            
            annual_gen_cap_savings = gen_cap_savings_h.sum()
            annual_trans_savings = trans_savings_h.sum()
            annual_dist_savings = dist_savings_h.sum()
            annual_energy_savings = energy_savings_h.sum()
            annual_emissions_savings = emissions_savings_h.sum()
            annual_grid_savings = total_savings_h.sum()
            
            # 4. Multi-year NPV discounting
            years = np.arange(1, asset_life + 1)
            discount_pct = discount_rate / 100.0
            customer_discount_pct = customer_discount_rate / 100.0
            escalation_pct = escalation_rate / 100.0
            retail_escalation_pct = retail_escalation_rate / 100.0
            degradation_pct = degradation_rate / 100.0

            grid_esc_factors = (1 + escalation_pct) ** (years - 1)
            retail_esc_factors = (1 + retail_escalation_pct) ** (years - 1)
            deg_factors = (1 - degradation_pct) ** (years - 1)
            disc_factors = 1 / ((1 + discount_pct) ** years)
            customer_disc_factors = 1 / ((1 + customer_discount_pct) ** years)

            grid_pv_multipliers = (grid_esc_factors * deg_factors) * disc_factors
            # Utility-side view of the same lost-revenue dollar stream, discounted at the
            # utility's own WACC (feeds RIM, the Scorecard/Lifetime Cash Flow Utility view).
            retail_pv_multipliers = (retail_esc_factors * deg_factors) * disc_factors
            # Customer-side view of that same stream, discounted at the customer's own
            # rate (feeds PCT, discounted payback, and the Lifetime Cash Flow Customer
            # view) -- a homeowner's appropriate discount rate is often higher than a
            # utility's regulated WACC, so this defaults to match it but can be raised.
            customer_pv_multipliers = (retail_esc_factors * deg_factors) * customer_disc_factors

            pv_grid_mult_sum = grid_pv_multipliers.sum()
            npv_grid_savings = annual_grid_savings * pv_grid_mult_sum
            npv_energy_savings = annual_energy_savings * pv_grid_mult_sum
            npv_capacity_savings = (annual_gen_cap_savings + annual_trans_savings + annual_dist_savings + annual_emissions_savings) * pv_grid_mult_sum
            npv_retail_lost_revenue = annual_lost_revenue * retail_pv_multipliers.sum()
            npv_customer_bill_savings = annual_lost_revenue * customer_pv_multipliers.sum()
            
            # Includes the utility's one-time program cost (incentive + admin) so this
            # headline NPV agrees with the Lifetime Cash Flow tab's Utility perspective
            # total, rather than being a narrower "grid savings vs. lost revenue only"
            # figure that silently excludes real utility cash outflows.
            npv_program_cost = utility_incentive + utility_admin_cost
            npv_net_savings = npv_grid_savings - npv_retail_lost_revenue - npv_program_cost
            
            # 4b. Cost-Effectiveness & Payback Tests (TRC, PCT, RIM, Payback)
            annual_cust_savings_stream = (annual_lost_revenue * retail_esc_factors * deg_factors)
            cost_tests = calculate_cost_effectiveness_tests(
                npv_grid_savings=npv_grid_savings,
                npv_lost_revenue=npv_retail_lost_revenue,
                npv_customer_bill_savings=npv_customer_bill_savings,
                gross_measure_cost=gross_measure_cost,
                utility_incentive=utility_incentive,
                utility_admin_cost=utility_admin_cost,
                annual_customer_savings_stream=annual_cust_savings_stream,
                pv_multipliers=customer_pv_multipliers
            )
            trc_ratio = cost_tests["trc_ratio"]
            pct_ratio = cost_tests["pct_ratio"]
            rim_ratio = cost_tests["rim_ratio"]
            simple_payback = cost_tests["simple_payback"]
            discounted_payback = cost_tests["discounted_payback"]
            net_customer_cost = cost_tests["net_customer_cost"]
            
            # 5. Peak Coincidence, EPC & Capacity Credit Proxy Math
            epc_baseline = (baseline_load * cwft_array).sum()
            epc_proposed = (proposed_load * cwft_array).sum()
            epc_reduction = (load_reduction * cwft_array).sum()  # technical/undiminished coincident reduction

            # Seasonal decomposition: compute independent Winter and Summer coincident capacity reductions
            dts_months = pd.to_datetime(datetime_series).dt.month.to_numpy()
            is_w_mo = np.isin(dts_months, [12, 1, 2])
            is_s_mo = np.isin(dts_months, [6, 7, 8, 9])
            cwft_w_sum = cwft_array[is_w_mo].sum()
            cwft_s_sum = cwft_array[is_s_mo].sum()
            winter_coincident_kw = float(np.sum(load_reduction[is_w_mo] * (cwft_array[is_w_mo] / cwft_w_sum))) if cwft_w_sum > 0 else 0.0
            summer_coincident_kw = float(np.sum(load_reduction[is_s_mo] * (cwft_array[is_s_mo] / cwft_s_sum))) if cwft_s_sum > 0 else 0.0
            binding_seasonal_kw = winter_coincident_kw if winter_split_pct >= 50.0 else summer_coincident_kw

            coincidence_baseline = epc_baseline / baseline_load.max() if baseline_load.max() > 0 else 0.0
            coincidence_proposed = epc_proposed / proposed_load.max() if proposed_load.max() > 0 else 0.0

            accredited_capacity_kw = epc_reduction * dr_capacity_derate
            nameplate_reduction_kw = dr_capacity_kw if dr_mode else load_reduction.max()
            if nameplate_reduction_kw > 1e-6:
                elcc_reduction = accredited_capacity_kw / nameplate_reduction_kw
                elcc_ratio_valid = True
            else:
                elcc_reduction = 0.0
                elcc_ratio_valid = False

            is_system_stress_selected = (selected_cwf_method in [SYSTEM_STRESS_CWF_LABEL, CAMBIUM_NET_DEMAND_CWF_LABEL, CAMBIUM_SEASONAL_NET_DEMAND_CWF_LABEL])
            if is_system_stress_selected:
                coincidence_ratio_label = "Proxy Coincidence Ratio (Not Accredited ELCC)"
                coincidence_delta_str = (
                    f"{elcc_reduction * 100:.1f}% Proxy Coincidence (Screening Only)"
                    if elcc_ratio_valid
                    else "N/A (No Positive Peak Reduction)"
                )
            else:
                coincidence_ratio_label = "Capacity Accreditation (ELCC/UCAP-Style Proxy %)"
                coincidence_delta_str = (
                    f"{elcc_reduction * 100:.1f}% ELCC Accreditation"
                    if elcc_ratio_valid
                    else "N/A (No Positive Peak Reduction)"
                )

            # Weather-Based Comparator evaluated on the EXACT SAME realized baseline & proposed profiles
            # (Isolates pure capacity-weighting valuation differences without altering energy, bills, emissions, or T&D)
            comp_epc_reduction = float((load_reduction * weather_comparator_cwft).sum())
            comp_accredited_kw = comp_epc_reduction * dr_capacity_derate
            comp_annual_gen_cap_savings = float(comp_accredited_kw * cap_value)
            comp_annual_grid_savings = (
                comp_annual_gen_cap_savings
                + annual_trans_savings
                + annual_dist_savings
                + annual_energy_savings
                + annual_emissions_savings
            )
            comp_npv_grid_savings = float(comp_annual_grid_savings * grid_pv_multipliers.sum())
            comp_npv_net_savings = comp_npv_grid_savings - npv_retail_lost_revenue - npv_program_cost
            comp_cost_tests = calculate_cost_effectiveness_tests(
                npv_grid_savings=comp_npv_grid_savings,
                npv_lost_revenue=npv_retail_lost_revenue,
                npv_customer_bill_savings=npv_customer_bill_savings,
                gross_measure_cost=gross_measure_cost,
                utility_incentive=utility_incentive,
                utility_admin_cost=utility_admin_cost,
                annual_customer_savings_stream=annual_cust_savings_stream,
                pv_multipliers=customer_pv_multipliers,
            )
            comp_trc_ratio = comp_cost_tests["trc_ratio"]
            comp_rim_ratio = comp_cost_tests["rim_ratio"]

            # Optional DR Weather-Dispatched comparator (shows impact when DR dispatch itself follows weather CWF)
            dr_weather_dispatched_summary = None
            if dr_mode and is_system_stress_selected:
                w_dr_red, w_dr_idx = dispatch_dr_program(
                    datetime_series,
                    weather_comparator_cwft,
                    dr_hours_per_year,
                    dr_season,
                    dr_max_hours_per_day,
                    dr_capacity_kw,
                    baseline_load,
                )
                w_dr_mwh = w_dr_red / 1000.0
                w_epc_red = float((w_dr_red * weather_comparator_cwft).sum())
                w_acc_kw = w_epc_red * dr_capacity_derate
                w_gen_cap_sav = float(w_acc_kw * cap_value)
                w_ene_sav = float((w_dr_mwh * results_df["Cambium_Energy_MWh"].to_numpy()).sum())
                w_trans_sav = float((w_dr_mwh * results_df["Trans_Value_MWh"].to_numpy()).sum())
                w_dist_sav = float((w_dr_mwh * results_df["Dist_Value_MWh"].to_numpy()).sum())
                w_emi_sav = float((w_dr_mwh * results_df["Emissions_Value_MWh"].to_numpy()).sum())
                dr_weather_dispatched_summary = {
                    "dispatched_hours": int(len(w_dr_idx)),
                    "accredited_capacity_kw": w_acc_kw,
                    "annual_gen_cap_savings": w_gen_cap_sav,
                    "annual_energy_savings": w_ene_sav,
                    "annual_td_savings": w_trans_sav + w_dist_sav,
                    "annual_emissions_savings": w_emi_sav,
                }
            
            # Peak-to-average coincidence ratios: average demand during the highest-stress
            # hours, divided by the average demand across the full year. A ratio of 2.0
            # means the load draws twice as much power during those hours as it does normally.
            # For the Load reduction resource, a ratio isn't meaningful (the "load" being
            # measured is itself a difference), so it's expressed instead as the % cut in
            # demand during that window, relative to baseline demand in that same window.
            top_50_cwft_indices = np.argsort(-cwft_array)[:50]
            top_100_cwft_indices = np.argsort(-cwft_array)[:100]
            
            top_100_price_cutoff = results_df['Cambium_Energy_MWh'].nlargest(100).min()
            top_100_price_indices = np.where(results_df['Cambium_Energy_MWh'] >= top_100_price_cutoff)[0]
            
            avg_full_base = baseline_load.mean()
            avg_full_prop = proposed_load.mean()
            
            def _peak_to_avg_ratio(load_arr, peak_indices, full_avg):
                if full_avg <= 0:
                    return 0.0
                return load_arr[peak_indices].mean() / full_avg
            
            def _pct_reduction_in_window(base_arr, reduct_arr, peak_indices):
                window_base_avg = base_arr[peak_indices].mean()
                if window_base_avg <= 0:
                    return 0.0
                return reduct_arr[peak_indices].mean() / window_base_avg * 100.0
            
            ratio_50_base = _peak_to_avg_ratio(baseline_load, top_50_cwft_indices, avg_full_base)
            ratio_50_prop = _peak_to_avg_ratio(proposed_load, top_50_cwft_indices, avg_full_prop)
            pct_reduct_50 = _pct_reduction_in_window(baseline_load, load_reduction, top_50_cwft_indices)
            
            ratio_100_base = _peak_to_avg_ratio(baseline_load, top_100_cwft_indices, avg_full_base)
            ratio_100_prop = _peak_to_avg_ratio(proposed_load, top_100_cwft_indices, avg_full_prop)
            pct_reduct_100 = _pct_reduction_in_window(baseline_load, load_reduction, top_100_cwft_indices)
            
            ratio_price_base = _peak_to_avg_ratio(baseline_load, top_100_price_indices, avg_full_base)
            ratio_price_prop = _peak_to_avg_ratio(proposed_load, top_100_price_indices, avg_full_prop)
            pct_reduct_price = _pct_reduction_in_window(baseline_load, load_reduction, top_100_price_indices)
            
            
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
                
            weather_aligned = (meta_load_weather == meta_cambium_weather == meta_cwft_weather)
            alignment_status = f"{weather_sensitivity_status} | User Label: {'Aligned' if weather_aligned else 'Mixed'}"
            
            # ==================================================================
            # TABS DISPLAY
            # ==================================================================
            tab_setup, tab_summary, tab_calculator, tab_charts, tab_scenarios, tab_diagnostics = st.tabs([
                "Calibration Check",
                "Overview Scorecard",
                "Cost-Effectiveness Table",
                "Charts",
                "Scenario Manager",
                "Diagnostics & Top Hours"
            ])

            # ------------------------------------------------------------------
            # TAB 1: CALIBRATION CHECK (does the weather actually line up?)
            # ------------------------------------------------------------------
            with tab_setup:
                if weather_aligned:
                    st.success(
                        f"**Weather Year Alignment: PASS** \u2014 Load, Cambium grid, and CWFT data are all documented as **{meta_load_weather}**."
                    )
                else:
                    st.error(
                        f"**Weather Year Alignment: MISMATCH** \u2014 Load = **{meta_load_weather}**, Cambium Grid = **{meta_cambium_weather}**, "
                        f"CWFT = **{meta_cwft_weather}**. Capacity coincidence values may be skewed. Align these in the sidebar's "
                        "Building/Technology section."
                    )

                st.markdown(f"**Temperature Sensitivity Check:** {weather_sensitivity_status} (max $r$ = {max_corr:.2f})")
                st.caption(f"Heating season correlation: {heat_corr:.2f}  |  Cooling season correlation: {cool_corr:.2f}")
                st.caption("Confirms the load profile responds to temperature as expected \u2014 this is a sanity check, not a substitute for the year-alignment check above.")

                with st.expander("Alignment rules & how to fix a mismatch"):
                    st.markdown(
                        """To conduct a valid Marginal Cost study for electric heat pumps, water heaters, or battery storage,
the simulated hourly demand shapes must line up with the grid dataset chronologically.

1. **Weather Year Sync:** Ensure your building simulator uses the same AMY (Actual Meteorological Year) as the Cambium grid data (e.g. 2012). Mismatched years displace winter cold snaps, skewing the capacity coincidence value.
2. **Calendar Shift:** Verify both files start on the same day of the week so weekend occupied patterns align with Cambium grid weekday rate periods.
3. **Standard Time:** Standardize on Local Standard Time (LST) year-round. Mismatched daylight savings transitions displace load spikes by 1 hour, incorrectly zeroing out capacity savings."""
                    )

                with st.expander("Need a different weather year? Generate an AMY EPW file"):
                    render_weather_generator("results")

            # ------------------------------------------------------------------
            # TAB 2: EXECUTIVE SUMMARY
            # ------------------------------------------------------------------
            with tab_summary:
                # Full weather sensitivity + year-alignment check lives in Calibration Check tab
                if not weather_aligned:
                    st.warning("Weather years are not aligned across Load/Cambium/CWFT — see the **Calibration Check** tab for details.")

                # 1. Top Section: Lifetime Economic Balance Strip & Net Verdict Card
                with st.container(border=True):
                    col_bal_chart, col_bal_net = st.columns([3.3, 1.2])
                    with col_bal_chart:
                        st.markdown("#### Lifetime Economic Balance (NPV Valuation)")
                        st.caption(
                            "Compares total wholesale grid avoided costs against utility retail lost revenue and the "
                            f"one-time program cost, over the {asset_life}-year horizon ({discount_rate}% discount rate)."
                        )
                        fig_balance = build_economic_balance_chart(
                            npv_grid_savings=npv_grid_savings,
                            npv_retail_lost_revenue=npv_retail_lost_revenue,
                            npv_net_savings=npv_net_savings,
                            npv_program_cost=npv_program_cost,
                            npv_energy_savings=npv_energy_savings,
                            npv_capacity_savings=npv_capacity_savings,
                        )
                        st.plotly_chart(fig_balance, width="stretch", config={"displayModeBar": False})
                    with col_bal_net:
                        st.markdown("<div style='height: 18px;'></div>", unsafe_allow_html=True)
                        st.markdown(
                            financial_metric_card_html(
                                label="Net Valuation NPV",
                                value=f"{'+' if npv_net_savings >= 0 else '-'}${abs(npv_net_savings):,.2f}",
                                sublabel="↑ Net Utility Benefit" if npv_net_savings >= 0 else "↓ Net Utility Cross-Subsidy",
                                is_positive=(npv_net_savings >= 0),
                                help_text="Grid Avoided Costs minus Utility Lost Revenue minus the one-time utility Rebate/Incentive and Admin & Marketing cost. Negative values indicate retail bill savings plus program cost exceed grid cost deferrals, requiring cross-subsidization."
                            ),
                            unsafe_allow_html=True
                        )
                        if npv_net_savings < 0:
                            st.caption("⚠️ **Cross-Subsidy Notice:** Bill savings outpace wholesale avoided costs under current retail rate design.")
                        else:
                            st.caption("✅ **Positive Grid Return:** Grid cost deferrals exceed utility lost revenue.")

                st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

                # A ratio can come back NaN when its cost basis itself goes negative (e.g.
                # RIM when the customer's bill increase is large enough that "lost revenue
                # + program cost" nets negative) -- a degenerate case, not a real 0-1+ ratio.
                # Show "N/A" with an explanatory sublabel instead of a misleading number.
                def _ratio_card(label, ratio, sublabel, help_text=None):
                    if np.isnan(ratio):
                        st.markdown(
                            ratio_card_html(label, "N/A", "Cost basis went negative — see Net NPV", False, help_text=help_text),
                            unsafe_allow_html=True
                        )
                    else:
                        st.markdown(
                            ratio_card_html(label, f"{ratio:.3f}", sublabel, ratio >= 1.0, help_text=help_text),
                            unsafe_allow_html=True
                        )

                # 2. Row of 4 Primary Headline Cards (No duplicates)
                kpi_col1, kpi_col2, kpi_col3, kpi_col4 = st.columns(4)
                with kpi_col1:
                    _ratio_card(
                        "Total Resource Cost (TRC)",
                        trc_ratio,
                        "NPV Grid / (Measure + Admin)",
                        help_text=(
                            "<strong>Total Resource Cost (TRC) Test</strong><br>"
                            "Measures overall cost-effectiveness from the combined perspective of the utility and customer.<br><br>"
                            "<strong>Basis:</strong> NPV Grid Avoided Costs ÷ (Gross Installed Measure Cost + Utility Admin Cost)<br><br>"
                            "<strong>• Above 1.0 (Pass):</strong> Lifetime avoided grid benefits exceed total installed measure and program costs, delivering net resource savings.<br><br>"
                            "<strong>• Below 1.0 (Fail):</strong> Total costs exceed grid benefits (net resource loss)."
                        )
                    )
                with kpi_col2:
                    _ratio_card(
                        "Rate Impact Measure (RIM)",
                        rim_ratio,
                        "NPV Grid / (Lost Rev + Program)",
                        help_text=(
                            "<strong>Rate Impact Measure (RIM) Test</strong><br>"
                            "Evaluates whether this measure increases or decreases electric rates, measuring the impact on non-participating ratepayers.<br><br>"
                            "<strong>Basis:</strong> NPV Grid Avoided Costs ÷ (NPV Lost Retail Revenue + Utility Program Costs)<br><br>"
                            "<strong>• Above 1.0 (Pass):</strong> Avoided grid savings exceed lost revenue and program costs, putting <em>downward pressure</em> on electric rates (benefiting non-participating customers with no cross-subsidy).<br><br>"
                            "<strong>• Below 1.0 (Cross-Subsidy):</strong> Avoided grid savings are less than lost revenue and program costs, putting <em>upward pressure</em> on electric rates (non-participating ratepayers cross-subsidize participants)."
                        )
                    )
                with kpi_col3:
                    sp_str = f"{simple_payback:.1f} yrs" if simple_payback != float('inf') else "N/A"
                    dp_str = f"{discounted_payback:.1f} yrs" if discounted_payback != float('inf') else "N/A"
                    st.metric(
                        label="Participant Payback",
                        value=sp_str,
                        delta=f"Discounted: {dp_str}",
                        delta_color="off",
                        help="Net Measure Cost divided by Year 1 Customer Bill Savings."
                    )
                with kpi_col4:
                    if is_system_stress_selected or "Dual-Peak" in selected_cwf_method:
                        st.metric(
                            label="Winter Peak Capacity",
                            value=f"{winter_coincident_kw:,.2f} kW",
                            delta=f"Summer: {summer_coincident_kw:,.2f} kW | Blended: {accredited_capacity_kw:,.2f} kW",
                            delta_color="normal" if winter_coincident_kw >= summer_coincident_kw else "off",
                            help=(
                                "Peak physical demand reduction during winter freeze net-demand hours (Dec–Feb). "
                                f"Delta shows summer cooling relief ({summer_coincident_kw:,.2f} kW) and "
                                f"annual blended capacity ({accredited_capacity_kw:,.2f} kW) weighted at {winter_split_pct:.0f}% Winter / {100-winter_split_pct:.0f}% Summer."
                            )
                        )
                    else:
                        st.metric(
                            label="Coincident Capacity",
                            value=f"{accredited_capacity_kw:,.2f} kW",
                            delta=coincidence_delta_str,
                            delta_color="off",
                            help=(
                                "Coincident capacity reduction driving Generation Capacity avoided costs. "
                                "When the public-data system-stress proxy is active, the displayed ratio is a "
                                "screening proxy coincidence ratio relative to peak load reduction — not measured LOLP or accredited ELCC."
                            )
                        )

                st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)

                # 3. Progressive Disclosure: Collapsible Detailed SPM & Technical Audit Expander
                with st.expander("▸ Detailed SPM Tests & Technical Engineering Audit", expanded=False):
                    st.markdown("##### Secondary Standard Practice Manual (SPM) Tests & Peak Coincidence")
                    audit_m1, audit_m2, audit_m3, audit_m4, audit_m5 = st.columns(5)
                    audit_m1.metric(
                        label="Participant Cost Test (PCT)",
                        value="N/A" if np.isnan(pct_ratio) else f"{pct_ratio:.3f}",
                        delta="Fail (cost basis negative)" if np.isnan(pct_ratio) else ("Pass" if pct_ratio >= 1.0 else "Fail"),
                        delta_color="inverse" if np.isnan(pct_ratio) else ("normal" if pct_ratio >= 1.0 else "inverse"),
                        help="(Bill Savings + Rebate) ÷ Measure Cost"
                    )
                    audit_m2.metric(
                        label="Winter Peak Reduction",
                        value=f"{winter_coincident_kw:,.2f} kW",
                        delta=f"Summer: {summer_coincident_kw:,.2f} kW",
                        delta_color="off",
                        help="Coincident demand reduction during winter reliability hours (Dec–Feb) vs summer (Jun–Sep)."
                    )
                    audit_m3.metric(
                        label="Peak Coincidence Factor",
                        value=f"{coincidence_baseline * 100:.1f}% → {coincidence_proposed * 100:.1f}%",
                        help="Baseline vs. Proposed load coincidence with system stress hours."
                    )
                    audit_m4.metric(
                        label="Max Peak Load Reduction",
                        value=f"{load_reduction.max():,.2f} kW",
                        help="Maximum single-hour reduction across the 8,760 hours."
                    )
                    audit_m5.metric(
                        label="Annual Energy Reduction",
                        value=f"{(load_reduction).sum() / 1000:,.2f} MWh",
                        help="Total annual volumetric electricity savings."
                    )

                    st.markdown("<hr style='margin: 12px 0; border: none; border-top: 1px solid #E2E8F0;'>", unsafe_allow_html=True)

                    col_info1, col_info2 = st.columns(2)
                    with col_info1:
                        st.markdown("###### Valuation Run Settings")
                        st.markdown(
                            f"""- **Customer Retail Tariff:** `{tariff_name_label}`
- **NLR Wholesale Scenario:** `{selected_scenario}`
- **Selected Weather Case:** `{weather_case}`
- **Target Region:** `{', '.join(target_states)}`
- **Demand Response Mode:** `{"Active" if dr_mode else "Inactive"}`
- **Analysis Asset Horizon:** `{asset_life} years` (utility WACC: {discount_rate}%, customer discount rate: {customer_discount_rate}%)"""
                        )
                    with col_info2:
                        elcc_audit_str = f"{elcc_reduction * 100:.1f}%" if elcc_ratio_valid else "N/A (no positive peak reduction)"
                        st.markdown("###### Capacity & Profile Breakdown")
                        st.markdown(
                            f"""- **Baseline Profile:** `{baseline_col}` (EPC: **{epc_baseline:.2f} kW**, Coincidence: **{coincidence_baseline * 100:.1f}%**)
- **Proposed Profile:** `{"DR Optimised Schedule" if dr_mode else proposed_col}` (EPC: **{epc_proposed:.2f} kW**, Coincidence: **{coincidence_proposed * 100:.1f}%**)
- **Technical EPC Reduction:** `**{epc_reduction:.2f} kW**` *(undiminished physical coincident cut)*
- **Accredited / Valued Capacity:** `**{accredited_capacity_kw:.2f} kW**` *(drives Gen Capacity avoided costs)*
- **{coincidence_ratio_label}:** `**{elcc_audit_str}**`
- **Gross Measure Cost / Utility Incentive:** `\${gross_measure_cost:,.2f} / \${utility_incentive:,.2f}`"""
                        )

                # 4. Capacity Method Summary & Cambium Net-Demand Diagnostics Expander
                with st.expander(
                    "▸ Capacity Valuation Breakdown & Cambium Net-Demand Diagnostics",
                    expanded=is_system_stress_selected,
                ):
                    st.markdown("##### Capacity Valuation & SPM Cost-Effectiveness Summary")
                    st.caption(
                        "Summary of seasonal coincident capacity reduction, annual avoided grid costs, and standard California Standard Practice Manual (SPM) "
                        "cost-effectiveness tests (TRC, RIM, Utility NPV) under the **Seasonal Split Net-Demand** framework."
                    )
                    if is_seasonal:
                        summary_metrics = [
                            f"Winter Peak Capacity Reduction ({winter_split_pct:.0f}% Risk Weight)",
                            f"Summer Peak Capacity Reduction ({100.0 - winter_split_pct:.0f}% Risk Weight)",
                            "Annual Blended Capacity Credit / EPC Reduction (kW)",
                            "Valued Generation Capacity (kW)",
                            "Annual Generation Capacity Avoided Cost ($/yr)",
                            "Annual Wholesale Delivered Energy Savings ($/yr)",
                            "Annual Transmission & Distribution Deferral ($/yr)",
                            "Annual Emissions Avoided Cost ($/yr)",
                            "Total Annual Grid Avoided Cost ($/yr)",
                            "Annual Customer Bill Savings / Lost Revenue ($/yr)",
                            "Utility Net Valuation NPV ($)",
                            "Total Resource Cost (TRC) Ratio",
                            "Rate Impact Measure (RIM) Ratio",
                        ]
                        summary_values = [
                            f"{winter_coincident_kw:,.3f} kW",
                            f"{summer_coincident_kw:,.3f} kW",
                            f"{epc_reduction:,.3f} kW",
                            f"{accredited_capacity_kw:,.3f} kW",
                            f"${annual_gen_cap_savings:,.2f}",
                            f"${annual_energy_savings:,.2f}",
                            f"${(annual_trans_savings + annual_dist_savings):,.2f}",
                            f"${annual_emissions_savings:,.2f}",
                            f"${annual_grid_savings:,.2f}",
                            f"${annual_lost_revenue:,.2f}",
                            f"${npv_net_savings:,.2f}",
                            "N/A" if np.isnan(trc_ratio) else f"{trc_ratio:.3f}",
                            "N/A" if np.isnan(rim_ratio) else f"{rim_ratio:.3f}",
                        ]
                    else:
                        summary_metrics = [
                            "Capacity Credit / EPC Reduction (kW)",
                            "Valued Generation Capacity (kW)",
                            "Annual Generation Capacity Avoided Cost ($/yr)",
                            "Annual Wholesale Delivered Energy Savings ($/yr)",
                            "Annual Transmission & Distribution Deferral ($/yr)",
                            "Annual Emissions Avoided Cost ($/yr)",
                            "Total Annual Grid Avoided Cost ($/yr)",
                            "Annual Customer Bill Savings / Lost Revenue ($/yr)",
                            "Utility Net Valuation NPV ($)",
                            "Total Resource Cost (TRC) Ratio",
                            "Rate Impact Measure (RIM) Ratio",
                        ]
                        summary_values = [
                            f"{epc_reduction:,.3f} kW",
                            f"{accredited_capacity_kw:,.3f} kW",
                            f"${annual_gen_cap_savings:,.2f}",
                            f"${annual_energy_savings:,.2f}",
                            f"${(annual_trans_savings + annual_dist_savings):,.2f}",
                            f"${annual_emissions_savings:,.2f}",
                            f"${annual_grid_savings:,.2f}",
                            f"${annual_lost_revenue:,.2f}",
                            f"${npv_net_savings:,.2f}",
                            "N/A" if np.isnan(trc_ratio) else f"{trc_ratio:.3f}",
                            "N/A" if np.isnan(rim_ratio) else f"{rim_ratio:.3f}",
                        ]
                    val_col = f"Seasonal Split Net-Demand ({winter_split_pct:.0f}% Winter / {100.0 - winter_split_pct:.0f}% Summer)" if is_seasonal else f"Value ({effective_cwf_method})"
                    summary_df = pd.DataFrame({
                        "Metric": summary_metrics,
                        val_col: summary_values,
                    })
                    st.dataframe(summary_df, width="stretch", hide_index=True)

                    if cambium_stress_eval is not None and cambium_stress_eval.get("is_qualified"):
                        c_diag = cambium_stress_eval.get("diagnostics", {})
                        bas = cambium_stress_eval.get('needed_bas', []) or cambium_stress_eval.get('needed_geas', [])
                        st.markdown("---")
                        st.markdown("##### Cambium Net-Demand Proxy Provenance & Diagnostics")
                        st.caption(
                            "Evaluated using Cambium regional net-demand exceedance "
                            "on modeled year " + str(planning_year) + " under 2012 weather basis."
                        )
                        c_col1, c_col2, c_col3, c_col4 = st.columns(4)
                        c_col1.metric("Requested Method", selected_cwf_method)
                        c_col2.metric("Region Coverage", f"{len(bas)} Area(s) Active")
                        c_col3.metric("Modeled Year / Weather", f"{planning_year} / 2012 Basis")
                        c_col4.metric("Active Stress Hours", f"{c_diag.get('active_hours', 0)} hrs")

                        c_sub1, c_sub2, c_sub3, c_sub4 = st.columns(4)
                        c_sub1.metric("Max Single-Hour Weight", f"{c_diag.get('top_hour_weight', 0.0) * 100:.2f}%")
                        c_sub2.metric("Effective Hours (1 / Σw²)", f"{c_diag.get('effective_hours', 0.0):.1f} hrs")
                        c_sub3.metric("State Routing", f"{', '.join(target_states)}")
                        c_sub4.metric("Constituent Regions", f"{', '.join(bas)}")
                    
            # ------------------------------------------------------------------
            # TAB 3: COST-EFFECTIVENESS TABLE
            # ------------------------------------------------------------------
            with tab_calculator:
                st.markdown("### Two-Sided Cost Effectiveness")
                st.caption("Annual financial balance comparing wholesale utility avoided cost benefits against customer retail bill reductions (lost revenue).")
                
                # Compute energy vs demand split for lost revenue
                if active_tariff_json is not None:
                    # To split energy and demand in URDB, we create a flat energy copy of the json
                    energy_only_json = active_tariff_json.copy()
                    energy_only_json["demandratestructure"] = None
                    energy_only_json["demandratewindow"] = None
                    energy_only_json["demandweekdayschedule"] = None
                    energy_only_json["demandweekendschedule"] = None
                    
                    bill_base_e, _ = calculate_urdb_bill(baseline_load, datetime_series, energy_only_json)
                    bill_prop_e, _ = calculate_urdb_bill(proposed_load, datetime_series, energy_only_json)
                    
                    retail_energy_savings = bill_base_e - bill_prop_e
                    retail_demand_savings = annual_lost_revenue - retail_energy_savings
                else:
                    retail_energy_savings = (load_reduction * custom_rate_kwh).sum()
                    retail_demand_savings = annual_lost_revenue - retail_energy_savings

                annual_net_savings = annual_grid_savings - annual_lost_revenue

                # 1. Headline Annual & Lifetime KPI Metric Cards
                kpi1, kpi2, kpi3, kpi4 = st.columns(4)
                with kpi1:
                    st.markdown(
                        financial_metric_card_html(
                            label="Wholesale Grid Deferrals",
                            value=f"${annual_grid_savings:,.2f}/yr",
                            sublabel="5 Avoided Cost Streams",
                            neutral=True,
                            help_text="Total annual utility wholesale avoided costs across energy, generation capacity, transmission, distribution, and carbon deferrals."
                        ),
                        unsafe_allow_html=True
                    )
                with kpi2:
                    st.markdown(
                        financial_metric_card_html(
                            label="Customer Bill Reductions",
                            value=f"${annual_lost_revenue:,.2f}/yr",
                            sublabel="Utility Lost Revenue",
                            neutral=True,
                            help_text="Total annual customer bill reduction under the selected retail tariff, representing lost retail revenue to the utility."
                        ),
                        unsafe_allow_html=True
                    )
                with kpi3:
                    st.markdown(
                        financial_metric_card_html(
                            label="Annual Operating Margin",
                            value=f"{'+' if annual_net_savings >= 0 else '-'}${abs(annual_net_savings):,.2f}/yr",
                            sublabel="↑ Positive Utility Return" if annual_net_savings >= 0 else "↓ Net Utility Cross-Subsidy",
                            is_positive=(annual_net_savings >= 0),
                            help_text="Annual Wholesale Grid Avoided Costs minus Annual Retail Bill Reductions. This does NOT include the one-time utility Rebate/Incentive or Admin & Marketing cost from the sidebar — those are one-time, not annual, so they don't belong in an annual figure. See the Lifetime Cash Flow tab's Utility perspective for the version that nets those in."
                        ),
                        unsafe_allow_html=True
                    )
                with kpi4:
                    st.markdown(
                        financial_metric_card_html(
                            label="Lifetime Net Valuation NPV",
                            value=f"{'+' if npv_net_savings >= 0 else '-'}${abs(npv_net_savings):,.2f}",
                            sublabel=f"{'↑' if npv_net_savings >= 0 else '↓'} {asset_life} yrs @ {discount_rate}% WACC",
                            is_positive=(npv_net_savings >= 0),
                            help_text="Discounted net present value of wholesale grid cost deferrals minus customer bill reductions, minus the utility's one-time Rebate/Incentive and Admin & Marketing cost, over the asset lifetime. For the year-by-year cash flow behind this number, see the Lifetime Cash Flow tab's Utility perspective."
                        ),
                        unsafe_allow_html=True
                    )

                st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

                # 2. Visual Two-Sided Comparison: Plotly Stacked Bar Chart & Component Breakdown Panel
                col_chart, col_breakdown = st.columns([3, 2])
                with col_chart:
                    fig_two_sided = build_two_sided_cost_effectiveness_chart(
                        annual_energy_savings=annual_energy_savings,
                        annual_gen_cap_savings=annual_gen_cap_savings,
                        annual_trans_savings=annual_trans_savings,
                        annual_dist_savings=annual_dist_savings,
                        annual_emissions_savings=annual_emissions_savings,
                        retail_energy_savings=retail_energy_savings,
                        retail_demand_savings=retail_demand_savings,
                        annual_net_savings=annual_net_savings
                    )
                    st.plotly_chart(fig_two_sided, width="stretch", config={"displayModeBar": False})

                with col_breakdown:
                    pct_cap = (annual_gen_cap_savings / annual_grid_savings * 100) if annual_grid_savings > 0 else 0
                    pct_ene = (annual_energy_savings / annual_grid_savings * 100) if annual_grid_savings > 0 else 0
                    pct_dis = (annual_dist_savings / annual_grid_savings * 100) if annual_grid_savings > 0 else 0
                    pct_emi = (annual_emissions_savings / annual_grid_savings * 100) if annual_grid_savings > 0 else 0
                    pct_tra = (annual_trans_savings / annual_grid_savings * 100) if annual_grid_savings > 0 else 0

                    pct_retail_e = (retail_energy_savings / annual_lost_revenue * 100) if annual_lost_revenue > 0 else 0
                    pct_retail_d = (retail_demand_savings / annual_lost_revenue * 100) if annual_lost_revenue > 0 else 0
                    recovery_rate = (annual_lost_revenue / annual_grid_savings * 100) if annual_grid_savings > 0 else 0

                    st.markdown(
                        f"""
<div style="background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px; padding: 14px 16px; margin-bottom: 12px;">
    <div style="font-weight: 600; font-size: 13px; color: #0F172A; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px;">Wholesale Grid Deferrals (${annual_grid_savings:,.2f}/yr)</div>
    <div style="display: flex; justify-content: space-between; font-size: 12.5px; padding: 2px 0; color: #334155;">
        <span><span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:#0D9488;margin-right:6px;"></span>Gen Capacity</span>
        <b>${annual_gen_cap_savings:,.2f} <span style="color:#64748B;font-weight:normal;">({pct_cap:.1f}%)</span></b>
    </div>
    <div style="display: flex; justify-content: space-between; font-size: 12.5px; padding: 2px 0; color: #334155;">
        <span><span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:#F59E0B;margin-right:6px;"></span>Wholesale Energy</span>
        <b>${annual_energy_savings:,.2f} <span style="color:#64748B;font-weight:normal;">({pct_ene:.1f}%)</span></b>
    </div>
    <div style="display: flex; justify-content: space-between; font-size: 12.5px; padding: 2px 0; color: #334155;">
        <span><span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:#EC4899;margin-right:6px;"></span>Distribution Deferral</span>
        <b>${annual_dist_savings:,.2f} <span style="color:#64748B;font-weight:normal;">({pct_dis:.1f}%)</span></b>
    </div>
    <div style="display: flex; justify-content: space-between; font-size: 12.5px; padding: 2px 0; color: #334155;">
        <span><span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:#10B981;margin-right:6px;"></span>Carbon Emissions</span>
        <b>${annual_emissions_savings:,.2f} <span style="color:#64748B;font-weight:normal;">({pct_emi:.1f}%)</span></b>
    </div>
    <div style="display: flex; justify-content: space-between; font-size: 12.5px; padding: 2px 0; color: #334155;">
        <span><span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:#3B82F6;margin-right:6px;"></span>Transmission Deferral</span>
        <b>${annual_trans_savings:,.2f} <span style="color:#64748B;font-weight:normal;">({pct_tra:.1f}%)</span></b>
    </div>
</div>

<div style="background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px; padding: 14px 16px;">
    <div style="font-weight: 600; font-size: 13px; color: #0F172A; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px;">Customer Bill Reductions (${annual_lost_revenue:,.2f}/yr)</div>
    <div style="display: flex; justify-content: space-between; font-size: 12.5px; padding: 2px 0; color: #334155;">
        <span><span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:#F43F5E;margin-right:6px;"></span>Volumetric Energy</span>
        <b>${retail_energy_savings:,.2f} <span style="color:#64748B;font-weight:normal;">({pct_retail_e:.1f}%)</span></b>
    </div>
    <div style="display: flex; justify-content: space-between; font-size: 12.5px; padding: 2px 0; color: #334155;">
        <span><span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:#BE123C;margin-right:6px;"></span>Demand Charges</span>
        <b>${retail_demand_savings:,.2f} <span style="color:#64748B;font-weight:normal;">({pct_retail_d:.1f}%)</span></b>
    </div>
    <div style="margin-top: 8px; padding-top: 8px; border-top: 1px dashed #CBD5E1; font-size: 12px; color: #475569;">
        Customer Bill Capture Rate: <b>{recovery_rate:.1f}%</b> of wholesale grid deferrals
    </div>
</div>
""",
                        unsafe_allow_html=True
                    )

                st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)

                # 3. Preserved Detailed Data Table in Collapsible Expander
                with st.expander("▸ Full Two-Sided Cost-Effectiveness Data Table", expanded=False):
                    st.caption("Complete breakdown of individual value streams, engineering unit rates, lost revenue components, and discounted lifetime metrics.")
                    
                    # Calculate PCAF peak hours demand reduction for T&D math trace
                    pcaf_mask = results_df['PCAF_Weight'].to_numpy() > 0
                    avg_reduct_pcaf = load_reduction[pcaf_mask].mean() if pcaf_mask.sum() > 0 else 0.0

                    feeder_mask = dist_weight_array > 0
                    avg_reduct_dist = load_reduction[feeder_mask].mean() if feeder_mask.sum() > 0 else avg_reduct_pcaf

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
                            "Rate Impact Measure (RIM) Ratio"
                        ],
                        "Annual Unit Rate": [
                            "Hourly Cambium Price",
                            f"${cap_value:,.2f}/kW-yr × {accredited_capacity_kw:.3f} kW Accredited Capacity",
                            f"${trans_value:,.2f}/kW-yr × {avg_reduct_pcaf:.3f} kW Peak Reduction",
                            f"${dist_value:,.2f}/kW-yr × {avg_reduct_dist:.3f} kW Feeder Peak Reduction",
                            f"${carbon_tax:,.2f} /metric ton",
                            "Sum of Grid Components",
                            "URDB TOU/Energy blocks",
                            "URDB Peak Demand blocks",
                            "Sum of Tariff Components",
                            f"NPV over {asset_life} years @ {discount_rate}% WACC",
                            f"NPV over {asset_life} years @ {discount_rate}% WACC",
                            "Grid NPV - Lost Revenue NPV - Program Cost (Incentive + Admin)",
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
                            return "N/A (cost basis negative)" if np.isnan(val) else f"{val:.3f}"
                        return f"${val:,.2f}"
                    df_val["Value ($/yr)"] = df_val.apply(lambda r: format_vals(r["Value ($/yr)"], r["Valuation Component"]), axis=1)
                    
                    st.dataframe(df_val, width="stretch", hide_index=True)
                
            # ------------------------------------------------------------------
            # TAB 4: CHARTS (ordered simplest/most relatable → most technical)
            # ------------------------------------------------------------------
            with tab_charts:
                st.markdown("### Charts")
                st.caption("All grid, cost, and building-load visualizations for this run, one chart (or closely related pair) per sub-tab, ordered from the building level up to the full financial picture.")

                def _chart_explainer(text, title="What this shows"):
                    with st.container(border=True):
                        st.markdown(f"**{title}**")
                        st.markdown(text)

                def _cwf_methodology_caveat():
                    """TODO(2026-09-23): revisit once the CWF/feeder methodology has been
                    validated further — see docs/roadmap.md DD-2."""
                    st.markdown(
                        "*Generation Capacity and Distribution Deferral values on this page "
                        "come from the sidebar's CWF Allocation Methodology (default: Cambium "
                        "Price-Exceedance LOLP Proxy, alpha=4) and Feeder Peaking Type (default: "
                        "System Coincident / Wholesale Price PCAF) — simplified proxies for system stress, not a "
                        "full probabilistic LOLP study.*"
                    )

                # --- Shared week selector (used by the "Building Load vs. Temperature" and
                # "Weekly Grid Economics" sub-tabs below; has no effect on the others) ---
                # Computed from this run's actual data rather than fixed calendar dates, since
                # the real peak/shoulder week shifts by state, scenario, and CWF methodology
                # (e.g. a state's true peak-price hour can fall outside a fixed "Jul 15-21" guess).
                def _week_label(prefix, start, end):
                    d0 = pd.to_datetime(results_df['Datetime'].iloc[start])
                    d1 = pd.to_datetime(results_df['Datetime'].iloc[end - 1])
                    date_range = (f"{d0.strftime('%b')} {d0.day}-{d1.day}" if d0.month == d1.month
                                  else f"{d0.strftime('%b')} {d0.day} - {d1.strftime('%b')} {d1.day}")
                    return f"{prefix} ({date_range})"

                stress_signal = results_df['Total_Avoided_Cost_MWh'].to_numpy()
                winter_window = find_peak_week(results_df['Datetime'], stress_signal, month_filter=[12, 1, 2], mode="max")
                summer_window = find_peak_week(results_df['Datetime'], stress_signal, month_filter=[6, 7, 8, 9], mode="max")
                shoulder_window = find_peak_week(results_df['Datetime'], stress_signal, month_filter=[3, 4, 5, 10, 11], mode="min")

                week_windows = {}
                if winter_window:
                    week_windows[_week_label("Winter Peak Week", *winter_window)] = winter_window
                if summer_window:
                    week_windows[_week_label("Summer Peak Week", *summer_window)] = summer_window
                if shoulder_window:
                    week_windows[_week_label("Shoulder Week", *shoulder_window)] = shoulder_window
                if not week_windows:
                    week_windows = WEEK_WINDOWS  # fallback: static defaults if none could be computed

                selected_week = st.selectbox("Select Analysis Week Window", options=list(week_windows.keys()), index=0)
                st.caption("Applies to the **Building Load vs. Temperature** and **Weekly Grid Economics** sub-tabs below. Weeks are computed from this run's actual grid data (the highest/lowest avoided-cost week within each season), not fixed calendar dates.")
                base_start_h, base_end_h = week_windows[selected_week]

                def _resolve_view_span(key_suffix):
                    """Renders its own 'View span' (Selected Week / Full Month) radio,
                    scoped to whichever tab calls it — this only affects the Building Load
                    vs. Temperature and Weekly Grid Economics tabs, so it's rendered inside
                    each of those tabs individually rather than once globally above all 7,
                    where it would misleadingly look like it applies to every tab."""
                    view_span = st.radio(
                        "View span",
                        options=["Selected Week", "Full Month"],
                        horizontal=True,
                        key=f"view_span_{key_suffix}",
                        help="Show just the selected week above, or expand to the entire calendar month it falls in."
                    )
                    if view_span == "Full Month":
                        week_start_ts = pd.to_datetime(results_df['Datetime'].iloc[base_start_h])
                        month_start = week_start_ts.replace(day=1, hour=0, minute=0, second=0)
                        month_end = month_start + pd.DateOffset(months=1)
                        dt_all = pd.to_datetime(results_df['Datetime'])
                        month_indices = np.where((dt_all >= month_start) & (dt_all < month_end))[0]
                        start_h, end_h = int(month_indices[0]), int(month_indices[-1]) + 1
                        label = week_start_ts.strftime('%B %Y')
                    else:
                        start_h, end_h = base_start_h, base_end_h
                        label = _week_label("", start_h, end_h).strip(" ()")
                    return start_h, end_h, label

                (chart_tab_load, chart_tab_econ, chart_tab_annual, chart_tab_seasonal,
                 chart_tab_peaker, chart_tab_cwf, chart_tab_lifetime, chart_tab_duration,
                 chart_tab_cumulative) = st.tabs([
                    "Building Load vs. Temperature",
                    "Weekly Grid Economics",
                    "Annual Wholesale Cost",
                    "Winter and Summer Peak Comparison",
                    "Peaker Carrying Cost",
                    "Capacity Risk & Feeder Stress",
                    "Lifetime Cash Flow",
                    "Cost Duration Curve",
                    "Cumulative Annual Cost",
                ])

                # --- Sub-tab 1: Customer & Building Load (simplest, most relatable) ---
                with chart_tab_load:
                    start_h, end_h, current_range_label = _resolve_view_span("load")
                    dt_slice = datetime_series.iloc[start_h:end_h]
                    baseline_slice = baseline_load[start_h:end_h]
                    proposed_slice = proposed_load[start_h:end_h]
                    temp_slice = results_df['Temperature_F'].iloc[start_h:end_h].to_numpy()

                    st.markdown(f"#### Customer & Building Load — Weekly Demand vs. Outdoor Temperature ({current_range_label})")
                    col_chart, col_text = st.columns([3, 2])
                    with col_chart:
                        fig_load_temp = build_weekly_load_and_temp_chart(
                            dt_slice, baseline_slice, proposed_slice, temp_slice
                        )
                        st.plotly_chart(fig_load_temp, width="stretch")
                    with col_text:
                        _chart_explainer(
                            "This chart shows the hourly demand of the Baseline and Proposed "
                            "cases (top) alongside outdoor temperature (bottom), lined up "
                            "hour-by-hour. If the load data you uploaded is whole-premise "
                            "power, that's what's shown; if you uploaded device-level power "
                            "instead, that's shown in its place. Use the **Select Analysis "
                            "Week Window** menu above to switch between Winter, Summer, and "
                            "Shoulder season weeks."
                        )

                # --- Sub-tab 2: Weekly Grid Economics (one layer deeper — dollars, still weekly) ---
                with chart_tab_econ:
                    start_h, end_h, current_range_label = _resolve_view_span("econ")
                    reduction_slice = load_reduction[start_h:end_h]

                    st.markdown(f"#### Weekly Grid Avoided Cost Economics ({current_range_label})")

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

                    col_chart, col_text = st.columns([3, 2])
                    with col_chart:
                        fig_grid_econ = build_weekly_grid_economics_chart(slice_df, mode=econ_view_mode)
                        st.plotly_chart(fig_grid_econ, width="stretch")

                        total_week_savings = slice_df['Hourly_Savings_hr'].sum()
                        total_week_customer_savings = (slice_df['Customer_Cost_Baseline_hr'] - slice_df['Customer_Cost_Proposed_hr']).sum()
                        col_g1, col_g2 = st.columns(2)
                        col_g1.caption(f"Total Grid Avoided Cost Value Created for `{current_range_label}`: **${total_week_savings:,.2f}**")
                        col_g2.caption(f"Total Customer Retail Bill Savings for `{current_range_label}`: **${total_week_customer_savings:,.2f}**")
                    with col_text:
                        _chart_explainer(
                            "This breaks the same week into four layers, from the grid's "
                            "perspective to the homeowner's:\n\n"
                            "- **Grid Avoided Cost ($/MWh)** — what it costs the grid per "
                            "unit of energy, hour by hour. This is the same no matter which "
                            "technology you pick — it depends on season, weather, and grid "
                            "data only, not the technology being examined.\n"
                            "- **Load Change (kW)** — how much less (green) or more (red) "
                            "power the Proposed case uses vs. Baseline that hour.\n"
                            "- **Grid Value Created vs. Lost Retail Revenue ($/hr)** — two "
                            "things shown side by side, not netted together: Grid Value "
                            "Created (green/red) is Grid Avoided Cost × Load Change, the "
                            "dollars the technology is worth to the grid that hour; Lost "
                            "Retail Revenue (green/pink) is what the utility collects less "
                            "of in retail sales that same hour. A technology can create real "
                            "grid value while still costing the utility retail revenue — "
                            "seeing both bars together shows whether they're pulling the "
                            "same direction or fighting each other hour by hour.\n"
                            "- **Customer Retail Cost ($/hr)** — the customer's cost, "
                            "Baseline vs. Proposed, plus the retail rate itself (dotted "
                            "line)."
                        )
                        _cwf_methodology_caveat()

                # --- Sub-tab 3: Utility Cost Tests (deeper — full year, component decomposition) ---
                with chart_tab_annual:
                    st.markdown("#### Annual Wholesale Cost")

                    annual_view_mode = st.radio(
                        "Annual View Mode",
                        options=["Hourly Line (Full Year)", "Monthly Box & Whisker"],
                        horizontal=True,
                        help="The hourly line is dominated by a handful of extreme-price hours (cold snaps, heat waves). Switch to the box plot to see each month's typical range instead."
                    )

                    col_chart, col_text = st.columns([3, 2])
                    with col_chart:
                        fig_grid_full = build_annual_avoided_cost_chart(results_df, mode=annual_view_mode)
                        st.plotly_chart(fig_grid_full, width="stretch")
                    with col_text:
                        _chart_explainer(
                            "This shows the same $/MWh wholesale avoided-cost value as the "
                            "top panel of Weekly Grid Economics, but stretched across the "
                            "full year instead of one week. It's the grid's cost story "
                            "only — not affected by which technology you've selected.\n\n"
                            "A handful of extreme-price hours (cold snaps, heat waves) can "
                            "dominate the hourly line and make the rest of the year look "
                            "flat. Click and drag on the graph to zoom in, or switch to "
                            "**Monthly Box & Whisker** to see each month's typical range "
                            "instead. In Box & Whisker view, each box covers the middle 50% "
                            "of that month's hours, the line inside is the median, and dots "
                            "mark outlier hours."
                        )
                        _cwf_methodology_caveat()

                # --- Sub-tab 4: Winter vs. Summer peak detail pair (makes sense together — same
                # metric, two seasons) ---
                with chart_tab_seasonal:
                    st.markdown("#### Winter and Summer Peak Comparison")
                    st.caption("Uses the same dynamically-computed Winter/Summer Peak Weeks as the Weekly Grid Economics selector above.")

                    w_start, w_end = winter_window if winter_window else WEEK_WINDOWS["Winter Peak Week (Jan 1-7)"]
                    s_start, s_end = summer_window if summer_window else WEEK_WINDOWS["Summer Peak Week (Jul 15-21)"]
                    winter_slice = results_df.iloc[w_start:w_end]
                    summer_slice = results_df.iloc[s_start:s_end]
                    winter_panel_label = _week_label('', w_start, w_end).strip(' ()')
                    summer_panel_label = _week_label('', s_start, s_end).strip(' ()')

                    combined_totals = pd.concat([winter_slice['Total_Avoided_Cost_MWh'], summer_slice['Total_Avoided_Cost_MWh']])
                    zoom_cap = max(float(np.percentile(combined_totals, 90)) * 1.15, 1.0)
                    pct_visible = float((combined_totals <= zoom_cap).mean() * 100)

                    col_chart, col_text = st.columns([3, 2])
                    with col_chart:
                        st.markdown("###### Full scope")
                        fig_seasonal = build_winter_summer_comparison_chart(
                            winter_slice, summer_slice,
                            winter_label=winter_panel_label, summer_label=summer_panel_label
                        )
                        st.plotly_chart(fig_seasonal, width="stretch")

                        st.markdown(f"###### Zoomed in — typical range ({pct_visible:.0f}% of hours fully visible, capped at ${zoom_cap:,.0f}/MWh)")
                        fig_seasonal_zoom = build_winter_summer_comparison_chart(
                            winter_slice, summer_slice,
                            winter_label=winter_panel_label, summer_label=summer_panel_label,
                            y_range=(0, zoom_cap)
                        )
                        st.plotly_chart(fig_seasonal_zoom, width="stretch")
                    with col_text:
                        _chart_explainer(
                            "Side-by-side comparison of the same 5 wholesale avoided-cost "
                            "components (Wholesale Energy, Generation Capacity, "
                            "Transmission Deferral, Distribution Deferral, Emissions "
                            "Compliance) during the year's highest-stress winter week and "
                            "highest-stress summer week, plotted on matching axes so the "
                            "two seasons can be compared directly. One shared legend "
                            "covers both panels — click an entry to toggle that component "
                            "on both sides at once.\n\n"
                            "The **Full scope** chart shows every hour, including the "
                            "handful of extreme-price hours that can dwarf everything "
                            "else. The **Zoomed in** chart below it shows the exact same "
                            "data with the y-axis capped so the typical, \"meat and "
                            "potatoes\" range is actually readable — a few of the tallest "
                            "hours run off the top of this one, but they're already fully "
                            "visible in the chart above."
                        )
                        _cwf_methodology_caveat()

                # --- Sub-tab 5: Peaker Carrying Cost Breakdown (optional — only when the
                # advanced peaker-cost inputs are configured) ---
                with chart_tab_peaker:
                    st.markdown("#### Next Planned Peaker Carrying Cost Breakdown")
                    if ct_calc is not None:
                        col_chart, col_text = st.columns([3, 2])
                        with col_chart:
                            st.caption("Annual gross carrying cost annuity and net avoided capacity credit ($/kW-yr).")
                            fig_peaker_wf = plot_peaker_carrying_cost_breakdown(ct_calc)
                            st.plotly_chart(fig_peaker_wf, width="stretch")
                        with col_text:
                            _chart_explainer(
                                "This builds up the **Generation Capacity ($/kW-yr)** value "
                                "used throughout the rest of the tool, using the Next "
                                "Planned Peaker — a Simple-Cycle Combustion Turbine (CT / SCCT) — "
                                "as the benchmark for what new capacity costs the utility to build:\n\n"
                                "- **Capital Recovery = CAPEX × FCR** — the annualized cost "
                                "of building 1 kW of the peaker ($1,100/kW × 8.20% = $90.20/kW-yr "
                                "under central NLR ATB 2024 Moderate values). FCR (Fixed Charge Rate) "
                                "accounts for utility WACC, depreciation tax shield (MACRS), corporate tax, "
                                "and economic project life.\n"
                                "- **+ Fixed O&M** — the annual cost to staff and maintain "
                                "the plant ($20.00/kW-yr in NLR ATB 2024).\n"
                                "- **= Gross Carrying Cost** — what it costs to simply own "
                                "and maintain the plant for a year ($110.20/kW-yr benchmark).\n"
                                "- **− E&AS Offset** (if any) — energy/ancillary profit offset; "
                                "usually $0 in Southeast cost-of-service IRPs (Gross CONE).\n"
                                "- **= Net Avoided Capacity** — the final number, fed back "
                                "as the Generation Capacity scalar everywhere in this tool.\n\n"
                                "**Data Source:** [Data | Electricity | 2024 | ATB | NLR](https://atb.nlr.gov/electricity/2024/data), "
                                "*Electricity > Fossil Energy Technologies > Natural Gas: Combustion Turbine (CT)*."
                            )
                            _cwf_methodology_caveat()
                    else:
                        st.info("Peaker carrying cost inputs aren't configured for this run — nothing to show here. Enable the advanced capacity cost calculator in the sidebar to populate this chart.")

                # --- Sub-tab 6: Capacity Risk Distribution & Local Feeder Stress pair (makes
                # sense together — risk shape vs. where it's felt on the system) ---
                with chart_tab_cwf:
                    st.markdown("#### Southeast Capacity Risk Distribution & Local Feeder Stress")
                    col_cwf1, col_cwf2, col_text = st.columns([3, 3, 2])
                    with col_cwf1:
                        fig_cwf_dist = plot_southeast_cwf_distribution(cwft_array, datetime_series)
                        st.plotly_chart(fig_cwf_dist, width="stretch")
                    with col_cwf2:
                        fig_feeder = plot_feeder_vs_system_load(dist_weight_array, results_df['PCAF_Weight'].to_numpy(), datetime_series)
                        st.plotly_chart(fig_feeder, width="stretch")
                    with col_text:
                        _chart_explainer(
                            "Two diagnostic views of *when during the day* risk "
                            "concentrates, based on the sidebar's chosen allocation "
                            "methodology — not a dollar chart.\n\n"
                            "- **Capacity Risk by Hour of Day** collapses the year's CWFT "
                            "weights into a typical 24-hour shape, split Winter vs. "
                            "Summer. It shows when Generation Capacity risk concentrates, "
                            "and is a good way to sanity-check whether your chosen "
                            "methodology lands where you'd expect.\n"
                            "- **Feeder vs. Bulk Transmission Peaking** compares your "
                            "chosen *local* feeder assumption (pink) against the *system-"
                            "wide* top-100-price-hour weighting that always drives "
                            "Transmission Deferral dollars (blue dashed, not "
                            "configurable). If the two curves diverge, your local feeder "
                            "assumption doesn't match system-wide price stress timing — "
                            "worth a second look."
                        )
                        _cwf_methodology_caveat()

                    st.markdown("---")
                    st.markdown("#### Capacity Weighting Method Comparison (Monthly & Diurnal Risk Shape)")
                    fig_method_comp = plot_system_stress_vs_weather_cwf_comparison(
                        stress_cwft=cwft_array,
                        weather_cwft=weather_comparator_cwft,
                        datetime_series=datetime_series,
                        stress_label=effective_cwf_method,
                        weather_label="Southeast Dual-Peak Weather Reference",
                    )
                    st.plotly_chart(fig_method_comp, width="stretch")

                    st.markdown("---")
                    st.markdown("#### Top 100 Capacity-Risk Hours — Did Load Go Up, Down, or Flat?")
                    col_risk_chart, col_risk_text = st.columns([3, 2])
                    with col_risk_chart:
                        top_risk_load_change = load_reduction[top_100_cwft_indices]
                        fig_top_risk = build_top_risk_hours_chart(top_risk_load_change)
                        st.plotly_chart(fig_top_risk, width="stretch")
                    with col_risk_text:
                        _chart_explainer(
                            "The 100 hours this run's CWFT weighting treats as carrying the most "
                            "generation-capacity risk, ranked left-to-right from the single most "
                            "critical hour down to the 100th. Each is colored by whether the "
                            "technology's load went **down** (green — eases the system exactly "
                            "when capacity risk is highest), **up** (red — adds to risk right when "
                            "it matters most), or stayed within "
                            "±0.1 kW (gray — no meaningful response)."
                        )

                # --- Sub-tab 7: Overall Scorecard (most technical — lifetime discounted cash flow) ---
                with chart_tab_lifetime:
                    st.markdown("#### Lifetime Cash Flow")
                    perspective = st.radio(
                        "Perspective",
                        options=["Utility", "Customer"],
                        horizontal=True,
                        help="Utility: grid savings captured vs. retail revenue given up. Customer: "
                             "their bill savings vs. the net equipment cost they pay after any "
                             "utility rebate."
                    )
                    col_chart, col_text = st.columns([3, 2])
                    with col_chart:
                        grid_savings_disc = annual_grid_savings * grid_pv_multipliers
                        # Same underlying $ stream either way — one side's lost retail
                        # revenue is the other side's bill savings — but discounted at
                        # each party's own rate (utility WACC vs. the sidebar's Customer
                        # Discount Rate), which can differ.

                        if perspective == "Utility":
                            retail_stream_disc = annual_lost_revenue * retail_pv_multipliers
                            fig_lifetime = build_lifetime_npv_chart(
                                years, grid_savings_disc, cost_stream=retail_stream_disc,
                                benefit_name="Grid Savings (PV)",
                                benefit_negative_name="Grid Cost (PV)",
                                cost_name="Lost Retail Revenue (PV)",
                                cost_negative_name="Revenue Gain (PV)",
                                upfront_cost=utility_incentive + utility_admin_cost,
                                upfront_name="Program Cost (Incentive + Admin)"
                            )
                        else:
                            customer_stream_disc = annual_lost_revenue * customer_pv_multipliers
                            fig_lifetime = build_lifetime_npv_chart(
                                years, customer_stream_disc,
                                benefit_name="Bill Savings (PV)",
                                benefit_negative_name="Bill Increase (PV)",
                                upfront_cost=net_customer_cost,
                                upfront_name="Upfront Cost (after rebate)"
                            )
                        st.plotly_chart(fig_lifetime, width="stretch")
                    with col_text:
                        if perspective == "Utility":
                            st.markdown(
                                "**Utility view — dollars are in today's present value.** Future "
                                "amounts are discounted back to present value, the same way the "
                                "payback period and NPV figures on the Cost-Effectiveness Table are "
                                "calculated, so this chart is the year-by-year detail behind those "
                                "two headline numbers."
                            )
                            st.markdown(
                                "- **Green bars** — whatever is *helping* the utility's net "
                                "position that year: grid-side value created (avoided generation "
                                "capacity, transmission, distribution, energy, and emissions "
                                "costs), and — in the rare case the customer's bill actually goes "
                                "*up* under Proposed — the extra retail revenue that comes with it."
                            )
                            st.markdown(
                                "- **Red / pink bars** — whatever is *hurting* the utility's net "
                                "position that year: the one-time \"Year 0\" program cost (rebate/"
                                "incentive plus admin & marketing, both set in the sidebar, bright "
                                "red), the recurring lost retail revenue from the customer buying "
                                "less electricity (pink), or — in the rare case the technology adds "
                                "grid stress instead of reducing it — negative grid savings."
                            )
                            st.markdown(
                                "- **Dark line** — the running total (every green bar minus every "
                                "red/pink one, added up year over year, starting from the Year 0 "
                                "program cost). Where it crosses from negative to positive is the "
                                "utility's **discounted payback year**; its value in the final year "
                                "is the **net NPV**."
                            )
                            st.caption(
                                "Colors follow each year's actual sign, not a fixed category — so a "
                                "bar's color always means \"helps\" or \"hurts,\" even in an unusual "
                                "year. This is the same cost basis as the Rate Impact Measure (RIM) "
                                "test on the Cost-Effectiveness Table."
                            )
                            _cwf_methodology_caveat()
                        else:
                            st.markdown(
                                "**Customer view — what the participant actually pays and gets "
                                "back.** The \"Year 0\" red bar is their net out-of-pocket cost: "
                                "full equipment/installation cost *minus* the utility incentive/"
                                "rebate (both set in the sidebar)."
                            )
                            st.markdown(
                                "- **Green bars** — the customer's retail bill savings each year "
                                "from using less energy — the same underlying dollars as the Utility "
                                "view's \"Lost Retail Revenue,\" just from the other side of the "
                                "meter, and discounted at the sidebar's Customer Discount Rate "
                                "instead of the utility's WACC."
                            )
                            st.markdown(
                                "- **Red bars (beyond Year 0)** — only appear if the customer's "
                                "bill actually goes *up* under Proposed in a given year; colors "
                                "follow each year's actual sign, not a fixed category."
                            )
                            st.markdown(
                                "- **Dark line** — cumulative net position, starting *negative* at "
                                "the upfront cost. Where it crosses from negative to positive is the "
                                "customer's own **discounted payback year** — the same number "
                                "behind the Participant Cost Test (PCT) on the Cost-Effectiveness "
                                "Table."
                            )

                # --- Sub-tab 8: Cost Duration Curve (full hourly detail, one month at a time) ---
                with chart_tab_duration:
                    st.markdown("#### Cost Duration Curve")
                    st.caption(
                        "Baseline vs. Proposed hourly cost for one month at a time, ordered by the sort mode "
                        "below, with the hour-by-hour change shown underneath (green = Proposed saves money "
                        "that hour, red = it costs more). Baseline and Proposed always stay paired to the "
                        "same hour — the shape of the change panel is real hour-by-hour variability, not two "
                        "independently-smoothed curves."
                    )

                    # KNOWN GAP (deferred 2026-09-25): under DR Mode, this simplified
                    # load_reduction x Total_Avoided_Cost_MWh basis does NOT apply the
                    # sidebar's Capacity Accreditation Factor derate that annual_grid_savings
                    # (Scorecard / Lifetime Cash Flow) applies to just the Gen Capacity
                    # component -- so this tab can overstate grid savings vs. those tabs
                    # while DR Mode is active. Punted for now; revisit if DR Mode usage grows.
                    grid_avoided = results_df['Total_Avoided_Cost_MWh'].to_numpy()
                    all_temp_vals = results_df['Temperature_F'].to_numpy()
                    all_datetimes = pd.to_datetime(results_df['Datetime'])

                    month_label_list = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
                    month_dropdown_options = month_label_list + ["Full Year"]
                    col_month, col_basis, col_sort = st.columns(3)
                    with col_month:
                        selected_month_label = st.selectbox("Month", options=month_dropdown_options, index=0)
                    is_full_year = selected_month_label == "Full Year"
                    period_label = "the full year" if is_full_year else selected_month_label
                    with col_basis:
                        cost_basis = st.radio(
                            "Cost basis",
                            options=["Customer Bill Cost ($/hr)", "Grid Avoided Cost ($/hr)"],
                            help="Customer = retail rate x load. Grid = wholesale/capacity avoided cost x load."
                        )
                    with col_sort:
                        sort_mode = st.radio(
                            "Sort by",
                            options=["Cost (High to Low)", "Chronological", "Outdoor Temperature (Cold to Hot)"],
                            help="Cost sorts into a classic duration-curve shape within the selected month. "
                                 "Chronological is a normal time series. Temperature sorts coldest-to-hottest "
                                 "left to right, using each hour's ODT."
                        )

                    if cost_basis == "Customer Bill Cost ($/hr)":
                        baseline_cost_curve = baseline_cost_hr
                        proposed_cost_curve = proposed_cost_hr
                        duration_y_title = "Customer Bill Cost ($/hr)"
                    else:
                        baseline_cost_curve = (baseline_load / 1000.0) * grid_avoided
                        proposed_cost_curve = (proposed_load / 1000.0) * grid_avoided
                        duration_y_title = "Grid Avoided Cost ($/hr)"

                    if is_full_year:
                        month_mask = np.ones(len(all_datetimes), dtype=bool)
                    else:
                        selected_month_num = month_label_list.index(selected_month_label) + 1
                        month_mask = all_datetimes.dt.month.to_numpy() == selected_month_num
                    month_baseline = baseline_cost_curve[month_mask]
                    month_proposed = proposed_cost_curve[month_mask]
                    month_temp = all_temp_vals[month_mask]
                    month_dt = all_datetimes[month_mask]

                    if sort_mode == "Cost (High to Low)":
                        order = np.argsort(-month_baseline)
                        x_vals = np.arange(1, len(order) + 1)
                        duration_x_title = f"Hour Rank within {period_label}, sorted by Baseline cost (highest to lowest)"
                    elif sort_mode == "Outdoor Temperature (Cold to Hot)":
                        order = np.argsort(month_temp)
                        x_vals = np.arange(1, len(order) + 1)
                        duration_x_title = f"Hour Rank within {period_label}, sorted by outdoor temperature (coldest to hottest)"
                    else:
                        order = np.arange(len(month_baseline))
                        x_vals = month_dt
                        duration_x_title = "Date"

                    # Cap the y-axis at 10x the month's median hour, but never below the actual
                    # max (so a normal, non-skewed month is never artificially clipped) -- a
                    # single cold-snap or heat-wave hour can otherwise dwarf a whole month's view.
                    combined_for_cap = np.concatenate([month_baseline, month_proposed])
                    median_val = float(np.median(combined_for_cap))
                    actual_max = float(np.max(combined_for_cap))
                    duration_y_cap = min(actual_max, max(median_val * 10.0, 1.0)) if median_val > 0 else actual_max
                    n_capped = int((combined_for_cap > duration_y_cap).sum()) if duration_y_cap < actual_max else 0

                    fig_duration = build_cost_duration_chart(
                        x_vals, month_baseline[order], month_proposed[order],
                        x_title=duration_x_title, y_title=duration_y_title,
                        change_y_title="Change ($/hr)",
                        y_range=(0, duration_y_cap) if duration_y_cap < actual_max else None
                    )
                    st.plotly_chart(fig_duration, width="stretch")

                    if n_capped > 0:
                        st.caption(f"Y-axis capped at ${duration_y_cap:,.0f}/hr (10x {period_label}'s "
                                   f"median hour) — **{n_capped}** hour(s) run higher than that, up to "
                                   f"**${actual_max:,.0f}/hr**.")

                    total_change = float((month_baseline - month_proposed).sum())
                    st.caption(f"Total change in {period_label} under this cost basis: **${total_change:,.2f}** "
                               f"({'net savings' if total_change >= 0 else 'net cost increase'}).")

                    st.markdown("---")
                    if is_full_year:
                        st.markdown("##### Is It Predictable? (Hour of Day x Month, full year)")
                        st.caption(
                            "Average dollar impact in each hour-of-day / month cell across the whole year, "
                            "using the cost basis selected above. A clean, consistent block of color means "
                            "the pattern is predictable; a speckled, inconsistent grid means it's closer to "
                            "random. The colorbar labels which direction is good and which is bad."
                        )
                        heatmap_values = baseline_cost_curve - proposed_cost_curve
                        fig_heatmap = build_hour_month_heatmap(
                            results_df['Datetime'], heatmap_values,
                            title=f"{duration_y_title.replace(' ($/hr)', '')} Impact by Hour x Month",
                            colorbar_title="$/hr"
                        )
                    else:
                        st.markdown(f"##### Is It Predictable? (Day x Hour within {selected_month_label})")
                        st.caption(
                            "Actual dollar impact for each day/hour in this month (real values, not averaged "
                            "away like the full-year view), using the cost basis selected above. A clean, "
                            "consistent block of color means the pattern is predictable within the month; a "
                            "speckled, inconsistent grid means it's closer to random. The colorbar labels which "
                            "direction is good and which is bad. Pick \"Full Year\" above to see the "
                            "season-level version instead."
                        )
                        heatmap_values = month_baseline - month_proposed
                        fig_heatmap = build_day_hour_heatmap(
                            month_dt, heatmap_values,
                            title=f"{duration_y_title.replace(' ($/hr)', '')} Impact by Day x Hour ({selected_month_label})",
                            colorbar_title="$/hr"
                        )
                    st.plotly_chart(fig_heatmap, width="stretch")

                    st.markdown(
                        "*Grid-side values above depend on the sidebar's CWF Allocation Methodology and Feeder "
                        "Peaking Type — see this Charts tab's CWF-related sub-tabs for details.*"
                    )

                # --- Sub-tab 9: Cumulative Annual Cost (running total, utility + customer) ---
                with chart_tab_cumulative:
                    st.markdown("#### Annual Cumulative Cost to Operate")
                    utility_cost_basis = st.radio(
                        "Utility cost basis",
                        options=[
                            "RIM (Grid Savings vs. Lost Retail Revenue)",
                            "TRC (Grid Savings Only — No Revenue Netting)",
                        ],
                        help="RIM (Rate Impact Measure): does this measure raise costs for other "
                             "ratepayers? Nets grid savings against the utility's lost retail revenue. "
                             "TRC (Total Resource Cost): is the wholesale/grid value created positive on "
                             "its own, ignoring the retail-revenue transfer between utility and customer? "
                             "Shows grid savings alone. Both mirror the same-named tests on the "
                             "Cost-Effectiveness Table, but scoped to just this year's energy usage — "
                             "neither one includes the one-time equipment, incentive, or admin cost; see "
                             "the Lifetime Cash Flow tab for the full picture including those."
                    )
                    col_chart, col_text = st.columns([3, 2])
                    with col_chart:
                        # KNOWN GAP (deferred 2026-09-25): see matching note on the Cost
                        # Duration Curve tab -- this tab's grid savings also don't apply
                        # DR Mode's Capacity Accreditation Factor derate, so they can run
                        # ahead of annual_grid_savings while DR Mode is active.
                        grid_avoided_arr = results_df['Total_Avoided_Cost_MWh'].to_numpy()
                        baseline_grid_cost_hr = (baseline_load / 1000.0) * grid_avoided_arr
                        proposed_grid_cost_hr = (proposed_load / 1000.0) * grid_avoided_arr
                        grid_diff_hr = proposed_grid_cost_hr - baseline_grid_cost_hr
                        cust_diff_hr = proposed_cost_hr - baseline_cost_hr

                        if utility_cost_basis.startswith("RIM"):
                            # A drop in the customer's bill is retail revenue the utility no
                            # longer collects, i.e. a cost to the utility -- subtracted, not added.
                            utility_net_hr = grid_diff_hr - cust_diff_hr
                            utility_row_title = "Utility Perspective — RIM Test (Grid Savings minus Lost Retail Revenue)"
                        else:
                            utility_net_hr = grid_diff_hr
                            utility_row_title = "Utility Perspective — TRC Test (Grid Savings Only)"

                        fig_cumulative = build_cumulative_cost_chart(
                            results_df['Datetime'], utility_net_hr,
                            baseline_cost_hr, proposed_cost_hr,
                            utility_row_title=utility_row_title
                        )
                        st.plotly_chart(fig_cumulative, width="stretch")

                        utility_net_annual = float(utility_net_hr.sum())
                        cust_net_annual = float(cust_diff_hr.sum())
                        st.caption(
                            f"By Dec 31 — **Utility ({'RIM' if utility_cost_basis.startswith('RIM') else 'TRC'}):** "
                            f"net {'benefit' if utility_net_annual <= 0 else 'cost'} of "
                            f"${abs(utility_net_annual):,.0f} from this year's energy usage alone. "
                            f"**Customer:** {'saves' if cust_net_annual <= 0 else 'costs'} "
                            f"${abs(cust_net_annual):,.0f} on their bill."
                        )
                    with col_text:
                        st.markdown(
                            "**What this shows:** pure year-1 operating cash flow from energy usage — "
                            "each hour's cost difference (Proposed minus Baseline) is added to a running "
                            "total, so a line's height at any date is *the net effect Proposed has had so "
                            "far that year*, and its height on Dec 31 is the full annual net difference. "
                            "**Green (below zero) = cumulative savings so far; red (above zero) = "
                            "cumulative added cost so far.** Both lines start at $0 on Jan 1 — one-time "
                            "capital costs (equipment, incentive, admin) are deliberately left out here; "
                            "see the Lifetime Cash Flow tab for those, plus the multi-year discounted "
                            "payback and NPV they produce."
                        )
                        st.markdown(
                            "- **Top panel — Utility** — nets grid-side savings (same Grid Avoided Cost "
                            "basis as the Cost Duration Curve tab) against whichever cost-effectiveness "
                            "test is selected above (RIM or TRC)."
                        )
                        st.markdown(
                            "- **Bottom panel — Customer/Occupant** — the building's own retail electric "
                            "bill difference, using the sidebar's selected tariff, accumulated the same way "
                            "(this one doesn't change with the toggle above — the customer's bill is the "
                            "customer's bill regardless of which utility-side test is selected)."
                        )
                        st.markdown(
                            "- A line that keeps sinking further into green means the technology is "
                            "consistently saving money in that perspective all year; a line that flattens, "
                            "climbs back toward zero, or crosses into red means some months are giving "
                            "that back — check the Cost Duration Curve or Weekly Grid Economics tabs for "
                            "the hourly detail behind any inflection point you notice here."
                        )
                        st.caption(
                            "*RIM and TRC here use one representative year's energy-usage dollars — "
                            "whichever Planning Year is selected in the sidebar — with no capital cost and "
                            "no multi-year escalation, degradation, or discounting applied. For the full "
                            "multi-year, discounted version of these same tests (including PCT, the "
                            "customer's own cost-effectiveness "
                            "ratio), see the Cost-Effectiveness Table and Lifetime Cash Flow tabs.*"
                        )

            # ------------------------------------------------------------------
            # TAB 5: SCENARIO MANAGER (save/compare runs)
            # ------------------------------------------------------------------
            with tab_scenarios:
                st.markdown("### Scenario Manager")
                st.caption("Save the current run's key results under a name, then compare multiple runs side by side.")

                if ("Southeast Dual-Peak" in selected_cwf_method) or ("Ambient Temperature Severity" in selected_cwf_method):
                    st.info(
                        f"**Comparing Grid Scenarios or Planning Years?** Your current Capacity Risk Allocation "
                        f"method (**{selected_cwf_method}**) is a fixed calendar/temperature window that doesn't "
                        f"reference Cambium grid data — it allocates capacity risk identically no matter which "
                        f"Grid Scenario or Planning Year is selected. Saved runs below will still show different "
                        f"$ totals across scenarios (energy prices and `cap_value` still change), but the *timing* "
                        f"of when risk is assigned won't shift with the scenario (e.g. a high-solar future pushing "
                        f"net-peak risk into the evening). For scenario-comparison analysis, consider switching to "
                        f"**Cambium Price-Exceedance LOLP Proxy** in the sidebar's Capacity Risk Allocation (CWF) "
                        f"section, which derives its risk weights from each scenario's own dispatch prices."
                    )

                with st.expander("📖 Cambium Future Scenario Reference & Documentation", expanded=False):
                    st.markdown(
                        f"Detailed modeling assumptions, technology cost projections, and ReEDS IRA policy implementations:  \n"
                        f"[Cambium 2024 Scenario Descriptions and Documentation]({CAMBIUM_DOC_URL})\n\n"
                        f"• **MidCase**: {SCENARIO_DESCRIPTIONS['MidCase']}\n\n"
                        f"• **HighDemandGrowth**: {SCENARIO_DESCRIPTIONS['HighDemandGrowth']}\n\n"
                        f"• **LowDemandGrowth**: {SCENARIO_DESCRIPTIONS['LowDemandGrowth']}\n\n"
                        f"• **LowCarbonConstraint**: {SCENARIO_DESCRIPTIONS['LowCarbonConstraint']}"
                    )
                
                # Save scenario current run section
                col_save1, col_save2 = st.columns([3, 1])
                with col_save1:
                    scenario_run_name = st.text_input("Enter Scenario Run name to save", value="Base Run")
                with col_save2:
                    st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
                    if st.button("Save Current Run", type="secondary", width="stretch"):
                        prov_info = system_stress_eval.get("provenance", {}) if system_stress_eval else {}
                        new_run = {
                            "Name": scenario_run_name,
                            "States": ", ".join(target_states),
                            "Grid Scenario": f"{selected_scenario} ({planning_year})",
                            "Weather Case": f"{weather_case} ({meta_load_weather})",
                            "Requested CWF": selected_cwf_method,
                            "Effective CWF": effective_cwf_method,
                            "EIA-861 Vintage": str(prov_info.get("crosswalk_vintage", "N/A")),
                            "Retail Tariff": tariff_name_label,
                            "Alignment": alignment_status,
                            "Net NPV ($)": npv_net_savings,
                            "RIM Ratio": rim_ratio,
                            "Capacity Credit / Proxy Ratio": (
                                f"{elcc_reduction * 100:.1f}%" if elcc_ratio_valid else "N/A"
                            ),
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
                        width="stretch", hide_index=True
                    )
                    
                    if st.button("Clear saved runs"):
                        st.session_state['saved_runs'] = []
                        st.rerun()
                else:
                    st.info("No saved runs. Give your current configuration a name and click **Save Current Run** to build a comparison database.")

            # ------------------------------------------------------------------
            # TAB 6: DIAGNOSTICS & TOP HOURS EXPORT
            # ------------------------------------------------------------------
            with tab_diagnostics:
                st.markdown("### Diagnostics & Load Response")
                st.markdown("Validation checks, a capacity-math trace, and hour-by-hour tables showing whether the technology actually responded to grid price signals.")

                with st.expander("Validation checks & capacity math trace", expanded=False):
                    # Check validation items
                    cwft_sum = cwft_array.sum()
                    capacity_math_ok = np.isclose(annual_gen_cap_savings, cap_value * accredited_capacity_kw, atol=1e-2)
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
  $$\\text{{Capacity Credit}} = \\text{{ECC}} \\times \\text{{Technical EPC Reduction}} \\times \\text{{Accreditation Factor}} = \\${cap_value:,.2f}/\\text{{kW-yr}} \\times {epc_reduction:.4f}\\text{{ kW}} \\times {dr_capacity_derate:.2f} = \\mathbf{{\\${cap_value * accredited_capacity_kw:,.2f}/\\text{{yr}}}}$$
  *(Matches Gen Capacity Avoided Costs: **${annual_gen_cap_savings:,.2f}/yr**{" — Accreditation Factor = 100% outside DR Mode" if not dr_mode else f" — Accreditation Factor set via the DR sidebar's Capacity Accreditation Factor ({dr_capacity_derate*100:.0f}%)"})*
- **Transmission Deferral avoided costs:**
  $$\\text{{Transmission Credit}} = \\text{{Transmission Scalar}} \\times \\text{{Peak Avg Reduction}} = \\${trans_value:,.2f}/\\text{{kW-yr}} \\times {avg_reduct_pcaf:.4f}\\text{{ kW}} = \\mathbf{{\\${trans_value * avg_reduct_pcaf:,.2f}/\\text{{yr}}}}$$
  *(Matches Transmission Deferral Avoided Costs: **${annual_trans_savings:,.2f}/yr**)*
- **Distribution Deferral avoided costs:**
  $$\\text{{Distribution Credit}} = \\text{{Distribution Scalar}} \\times \\text{{Feeder Peak Avg Reduction}} = \\${dist_value:,.2f}/\\text{{kW-yr}} \\times {avg_reduct_dist:.4f}\\text{{ kW}} = \\mathbf{{\\${dist_value * avg_reduct_dist:,.2f}/\\text{{yr}}}}$$
  *(Matches Distribution Deferral Avoided Costs: **${annual_dist_savings:,.2f}/yr**)*
"""
                    )

                st.markdown("---")
                st.markdown("#### Export Hourly Cost Data")
                st.caption(
                    "The full 8,760-hour wholesale price, avoided-cost, and retail rate series for this "
                    "exact run (current state/scenario/planning year/CWF/tariff selections) — useful for "
                    "designing a synthetic load profile outside the tool, e.g. a battery dispatch "
                    "schedule that charges during the cheapest hours and discharges during the priciest "
                    "ones, to test against the Load Response Diagnostics tables below. Includes the "
                    "hourly retail rate so a TOU tariff's own peak/off-peak windows — which don't "
                    "necessarily line up with wholesale price timing — can be designed against too."
                )
                export_df = pd.DataFrame({
                    "Hour index": results_df['Hour'],
                    "Date & Time": pd.to_datetime(results_df['Datetime']),
                    "Temperature (°F)": results_df['Temperature_F'],
                    "Wholesale Energy Price ($/MWh)": results_df['Cambium_Energy_MWh'],
                    "Generation Capacity Value ($/MWh)": results_df['Gen_Capacity_Value_MWh'],
                    "Transmission Value ($/MWh)": results_df['Trans_Value_MWh'],
                    "Distribution Value ($/MWh)": results_df['Dist_Value_MWh'],
                    "Emissions Value ($/MWh)": results_df['Emissions_Value_MWh'],
                    "Total Grid Avoided Cost ($/MWh)": results_df['Total_Avoided_Cost_MWh'],
                    "CWFT Weight": results_df['CWFT'],
                    "Weather Comparator CWFT Weight": weather_comparator_cwft,
                    "CWF Requested Method": selected_cwf_method,
                    "CWF Effective Method": effective_cwf_method,
                    "EIA Portfolio Stress Signal (MW)": (
                        system_stress_eval["portfolio_stress_signal_mw"]
                        if system_stress_eval is not None
                        else np.full(len(results_df), np.nan)
                    ),
                    "EIA Portfolio Gross Demand (MW)": (
                        system_stress_eval["portfolio_demand_mw"]
                        if system_stress_eval is not None
                        else np.full(len(results_df), np.nan)
                    ),
                    "EIA Portfolio Wind Generation (MW)": (
                        system_stress_eval["portfolio_wind_mw"]
                        if system_stress_eval is not None
                        else np.full(len(results_df), np.nan)
                    ),
                    "EIA Portfolio Solar Generation (MW)": (
                        system_stress_eval["portfolio_solar_mw"]
                        if system_stress_eval is not None
                        else np.full(len(results_df), np.nan)
                    ),
                    "Hourly Generation Capacity Savings ($/hr)": gen_cap_savings_h,
                    "Retail Energy Rate ($/kWh)": hourly_retail_rate,
                    "Baseline Customer Bill Cost ($/hr)": baseline_cost_hr,
                    "Proposed Customer Bill Cost ($/hr)": proposed_cost_hr,
                    "Baseline Load (kW)": baseline_load,
                    "Proposed Load (kW)": proposed_load,
                })
                st.download_button(
                    "Download Full Year Hourly Cost Data (CSV)",
                    export_df.to_csv(index=False).encode('utf-8'),
                    file_name="hourly_wholesale_retail_and_avoided_cost.csv",
                    mime="text/csv",
                    width="stretch"
                )

                st.markdown("---")
                st.markdown("#### Load Response Diagnostics")
                st.caption(
                    "Cross-references each hour's grid cost against whether the technology actually "
                    "responded to it, surfacing four patterns: expensive hours where it helped (or hurt), "
                    "expensive hours where it did nothing, cheap hours where it shifted load in to take "
                    "advantage, and cheap hours where it did nothing. Uses the same Grid Avoided Cost "
                    "basis as the Cost Duration Curve tab. 'High' and 'low' cost are evaluated **within "
                    "each calendar month**, not against the whole year — otherwise a uniformly cheap month "
                    "(e.g. April) would crowd out every other month's low-cost pool, and a technology "
                    "would get unfairly penalized for not shifting load into August's cheapest hours just "
                    "because they're still pricier than a typical April hour."
                )

                col_p1, col_p2, col_p3 = st.columns(3)
                with col_p1:
                    hours_per_month = st.slider(
                        "Hours per month defining 'high' / 'low' cost", min_value=5, max_value=150, value=40, step=5,
                        help="Within each calendar month, the N highest-cost and N lowest-cost hours (by "
                             "Grid Avoided Cost) define that month's contribution to the 'high cost' and "
                             "'low cost' pools below -- so every month is judged against its own price "
                             "range, not the year's."
                    )
                with col_p2:
                    response_threshold_pct = st.slider(
                        "Response threshold (% of baseline load)", min_value=0.0, max_value=25.0, value=5.0, step=0.5,
                        help="A load change smaller than this percentage of that hour's baseline load counts "
                             "as 'no response' rather than a real behavioral change."
                    )
                with col_p3:
                    rows_per_table = st.slider("Rows per table", min_value=10, max_value=200, value=100, step=10)

                grid_avoided_diag = results_df['Total_Avoided_Cost_MWh'].to_numpy()
                diag_cost_hr = (baseline_load / 1000.0) * grid_avoided_diag
                diag_value_hr = (load_reduction / 1000.0) * grid_avoided_diag  # + = saved, - = cost more

                response_mask = np.abs(load_reduction) >= (response_threshold_pct / 100.0) * np.maximum(baseline_load, 1e-6)

                # High/low cost are ranked WITHIN each calendar month rather than across the
                # whole year, so every month contributes its own relatively-expensive and
                # relatively-cheap hours instead of one uniformly cheap/pricey month dominating
                # the pool (see caption above).
                month_of_hour = pd.to_datetime(results_df['Datetime']).dt.month.to_numpy()
                high_cost_mask = np.zeros(len(diag_cost_hr), dtype=bool)
                low_cost_mask = np.zeros(len(diag_cost_hr), dtype=bool)
                for m in range(1, 13):
                    month_idx = np.where(month_of_hour == m)[0]
                    if len(month_idx) == 0:
                        continue
                    month_costs = diag_cost_hr[month_idx]
                    k = min(hours_per_month, len(month_idx))
                    high_cost_mask[month_idx[np.argsort(-month_costs)[:k]]] = True
                    low_cost_mask[month_idx[np.argsort(month_costs)[:k]]] = True

                diag_df = pd.DataFrame({
                    "Date & Time": pd.to_datetime(results_df['Datetime']).dt.strftime('%b %d, %H:%M'),
                    "Temperature (°F)": results_df['Temperature_F'].to_numpy(),
                    "Grid Avoided Cost ($/hr)": diag_cost_hr,
                    "Baseline Load (kW)": baseline_load,
                    "Proposed Load (kW)": proposed_load,
                    "Load Change (kW)": load_reduction,
                    "$ Impact ($/hr)": diag_value_hr,
                })

                def _response_table(title, caption, mask, sort_col, ascending, sort_by_abs=False):
                    # sort_by_abs ranks by the magnitude of sort_col instead of its raw
                    # signed value, so a big "made it worse" hour surfaces at the top
                    # alongside a big "saved a lot" hour instead of sinking to the bottom
                    # just because it's negative. Only meaningful for columns that can
                    # actually go negative ($ Impact, Load Change) -- the cost columns
                    # used by the "No Response" tables are already >= 0, so abs() there
                    # is a no-op and ascending/descending keeps its current meaning
                    # (priciest-of-the-expensive or cheapest-of-the-cheap first).
                    if sort_by_abs:
                        subset = diag_df[mask].assign(_sort_key=diag_df.loc[mask, sort_col].abs()) \
                            .sort_values('_sort_key', ascending=False).drop(columns='_sort_key').head(rows_per_table)
                    else:
                        subset = diag_df[mask].sort_values(sort_col, ascending=ascending).head(rows_per_table)
                    with st.container(border=True):
                        st.markdown(f"##### {title}")
                        st.caption(f"{caption} ({int(mask.sum())} qualifying hour(s); showing up to {rows_per_table}.)")
                        st.dataframe(
                            subset.style.format({
                                "Temperature (°F)": "{:.1f}",
                                "Grid Avoided Cost ($/hr)": "${:,.2f}",
                                "Baseline Load (kW)": "{:.2f}",
                                "Proposed Load (kW)": "{:.2f}",
                                "Load Change (kW)": "{:+.2f}",
                                "$ Impact ($/hr)": "${:+,.2f}",
                            }),
                            width="stretch", hide_index=True, height=320
                        )
                        st.download_button(
                            "Download CSV", subset.to_csv(index=False).encode('utf-8'),
                            file_name=f"{title.lower().replace(' ', '_').replace('—', '-')}.csv",
                            mime="text/csv", width="stretch", key=f"dl_{title}"
                        )

                row1_col1, row1_col2 = st.columns(2)
                with row1_col1:
                    _response_table(
                        "High Cost — Technology Responded",
                        "Expensive hours where the technology responded, sorted by the size of the $ impact so the biggest hits and misses show first (a negative $ Impact means it made an expensive hour worse).",
                        high_cost_mask & response_mask, "$ Impact ($/hr)", False, sort_by_abs=True
                    )
                with row1_col2:
                    _response_table(
                        "High Cost — No Response",
                        "Missed-opportunity hours: hours that were expensive relative to their own month where the technology's load barely changed.",
                        high_cost_mask & ~response_mask, "Grid Avoided Cost ($/hr)", False
                    )

                row2_col1, row2_col2 = st.columns(2)
                with row2_col1:
                    _response_table(
                        "Low Cost — Load Shifted Here",
                        "Cheap-hour arbitrage: hours that were inexpensive relative to their own month where the technology deliberately used more power (e.g. pre-heating/cooling, battery charging), sorted by the size of the load change so the biggest responses show first.",
                        low_cost_mask & response_mask, "Load Change (kW)", True, sort_by_abs=True
                    )
                with row2_col2:
                    _response_table(
                        "Low Cost — No Response",
                        "Unused opportunity: hours that were inexpensive relative to their own month where the technology didn't take advantage.",
                        low_cost_mask & ~response_mask, "Grid Avoided Cost ($/hr)", True
                    )

                st.markdown("---")
                top_risk_mask = np.zeros(len(diag_cost_hr), dtype=bool)
                top_risk_mask[top_100_cwft_indices] = True
                _response_table(
                    "Top 100 Capacity-Risk Hours",
                    "The 100 hours this run's CWFT weighting treats as carrying the most generation-capacity risk — not a cost-pool table like the four above, but the diagnostic counterpart to the Capacity Risk & Feeder Stress tab's up/down/flat chart. Sorted by the size of the $ impact so the biggest hits and misses show first.",
                    top_risk_mask, "$ Impact ($/hr)", False, sort_by_abs=True
                )

            # Persistent disclaimer at the base of the valuation dashboard
            st.markdown(TOOL_DISCLAIMER_HTML, unsafe_allow_html=True)

        except Exception as e:
            st.error(f"**Data Processing/CSV Parsing Error:** {str(e)}")
            st.info("Check your inputs and file paths. Ensure files represent exactly 8760 hours.")
            if st.button("🏠 Return to Info & Setup Screen", key="error_back_home", type="primary"):
                st.session_state['simulation_executed'] = False
                st.rerun()
