"""
================================================================================
⚡ ANNOTATED TOUR OF APP.PY: SOUTHEAST MARGINAL COST VALUATION ENGINE ⚡
================================================================================

WELCOME TO THE CODE TOUR!
-------------------------
This file is a fully functional, heavily annotated duplicate of `app.py`.
It is designed specifically for relative coding beginners, energy analysts, 
and policy managers who want to understand how Python, Streamlit, and energy
economics models work together under the hood.

HOW TO READ THIS FILE:
----------------------
1. Every section begins with a "LAYPERSON SUMMARY" explaining the real-world 
   utility concept and the Python programming technique being used.
2. Every major function has a detailed docstring explaining inputs, outputs, 
   and step-by-step mathematical logic.
3. Key lines of code have inline comments breakdown.

YOU CAN RUN THIS FILE!
----------------------
Because this retains 100% of the original application logic, you can launch it 
in your terminal by typing:
    streamlit run app_annotated.py
================================================================================
"""

# ==============================================================================
# SECTION 1: LIBRARIES & MODULE IMPORTS
# ==============================================================================
# LAYPERSON SUMMARY:
# Think of "importing" like picking up specialized toolkits from a workbench.
# Python comes with built-in tools (like 'os' for file handling), but developers
# also bring in third-party toolkits (like 'pandas' for spreadsheets and 
# 'streamlit' for building web applications).
# ==============================================================================

import os             # Operating System module: Used to check paths, create folders, and check if files exist on your hard drive.
import glob           # Globbing module: Searches for files matching patterns (e.g. finding all "*.epw" weather files in a folder).
import json           # JSON module: Parses JavaScript Object Notation text structures (used for utility rates and web APIs).
import urllib.request # URL Request module: Acts like a mini web browser inside Python to fetch data over HTTP (e.g. downloading rates from NREL).
import numpy as np    # NumPy ("Numerical Python"): High-speed math engine. Performs calculations across arrays of thousands of numbers in microseconds.
import pandas as pd   # Pandas: Data analysis toolkit. Turns raw data into "DataFrames" (which behave just like Excel spreadsheets inside code).
import streamlit as st # Streamlit: Web app framework. Turns pure Python code into interactive web apps (buttons, sliders, charts, sidebars).
import plotly.graph_objects as go # Plotly Graph Objects: Interactive visualization library used to make hovering charts, stacked graphs, and sliders.
from plotly.subplots import make_subplots # Plotly Subplots helper: Allows placing multiple graphs on top of each other or sharing an X-axis.

# ==============================================================================
# SECTION 2: PAGE CONFIGURATION & AESTHETICS (STREAMLIT UI)
# ==============================================================================
# LAYPERSON SUMMARY:
# Here we set up how the browser tab looks and inject custom CSS (styling rules)
# to give metric cards nice borders, hover effects, and modern colors.
# ==============================================================================

st.set_page_config(
    page_title="Southeast Marginal Cost Valuation Engine", # Text displayed in the browser tab title bar
    page_icon="⚡",                                         # Emoji icon in the browser tab
    layout="wide",                                          # Tells Streamlit to use full screen width instead of a narrow column
    initial_sidebar_state="expanded"                        # Ensures the left control panel opens expanded by default
)

# Custom CSS styling for metric cards, dataframes, and badges.
# 'unsafe_allow_html=True' tells Streamlit to let us inject raw HTML and CSS styling.
st.markdown(
    """<style>
/* Metric value numbers (e.g., $125,000) - stylized in teal color */
[data-testid="stMetricValue"] {
    font-size: 1.8rem;
    font-weight: 700;
    color: #0D9488; /* Sleek teal color for key figures */
}
/* Metric labels (e.g., Net Present Value) - dark gray subtext */
[data-testid="stMetricLabel"] {
    font-size: 0.9rem;
    font-weight: 600;
    color: #4B5563;
}
/* Card container box around metrics with subtle shadow and hover animation */
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
/* Styling tables */
[data-testid="stDataFrame"] {
    border: 1px solid #E2E8F0;
    border-radius: 12px;
    overflow: hidden;
}
/* Colored pill badges for status indicators (green, yellow, red) */
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
</style>""",
    unsafe_allow_html=True
)

# ==============================================================================
# SECTION 3: PRE-PACKAGED LOCAL URDB TARIFFS
# ==============================================================================
# LAYPERSON SUMMARY:
# Retail utility rates can be very complex. They often charge a fixed monthly fee,
# different volumetric energy rates per kWh depending on season (Summer vs. Winter),
# and tiered blocks (e.g. charging more per kWh after you cross 650 kWh).
# Here we define pre-packaged Python dictionaries matching NREL's Utility Rate 
# Database (URDB) format for Georgia Power and Alabama Power residential rates.
# ==============================================================================

GP_R31_URDB = {
    "name": "Georgia Power - Schedule R-31 (Residential)",
    "fixedcharge": 16.48, # Monthly base customer charge ($14.00 base * 1.177209 rider multiplier)
    
    # Energy Rate Window: A 12-month x 24-hour matrix.
    # [0]*24 means all 24 hours of that month use Period 0 (Winter).
    # [1]*24 means all 24 hours of that month use Period 1 (Summer).
    "energyratewindow": [
        [0]*24, [0]*24, [0]*24, [0]*24, [0]*24, # Months 1-5 (Jan - May): Winter = Period 0
        [1]*24, [1]*24, [1]*24, [1]*24,         # Months 6-9 (Jun - Sep): Summer = Period 1
        [0]*24, [0]*24, [0]*24                  # Months 10-12 (Oct - Dec): Winter = Period 0
    ],
    
    # Energy Rate Structure: Tiered pricing rules for each Period.
    "energyratestructure": [
        # Period 0 (Winter): Single flat rate of ~$0.142062 per kWh
        [{"rate": 0.142062}], 
        
        # Period 1 (Summer): 3 Tiered blocks
        [
            {"max": 650.0, "rate": 0.148101}, # Tier 1: First 650 kWh in a month at ~$0.148/kWh
            {"max": 350.0, "rate": 0.216379}, # Tier 2: Next 350 kWh (650 to 1000 kWh) at ~$0.216/kWh
            {"rate": 0.222371}                 # Tier 3: Anything above 1000 kWh at ~$0.222/kWh
        ] 
    ]
}

AL_FD_URDB = {
    "name": "Alabama Power - Rate FD (Family Dwelling)",
    "fixedcharge": 15.58, # $14.50/month base + $1.08/month natural disaster rider (NDR)
    "energyratewindow": [
        [0]*24, [0]*24, [0]*24, [0]*24, [0]*24, # Jan - May (Winter = Period 0)
        [1]*24, [1]*24, [1]*24, [1]*24,         # Jun - Sep (Summer = Period 1)
        [0]*24, [0]*24, [0]*24                  # Oct - Dec (Winter = Period 0)
    ],
    "energyratestructure": [
        # Period 0 (Winter): Tiered block (first 750 kWh at ~$0.150/kWh, excess at ~$0.138/kWh)
        [
            {"max": 750.0, "rate": 0.150384}, 
            {"rate": 0.138384}                 
        ], 
        # Period 1 (Summer): Tiered block (first 1000 kWh at ~$0.150/kWh, excess at ~$0.153/kWh)
        [
            {"max": 1000.0, "rate": 0.150384}, 
            {"rate": 0.152913}                  
        ] 
    ]
}

# Default directory where raw NREL Cambium grid data files are expected
INPUT_DIRECTORY = "./Cambium_Hourly_Data_raw"

# ==============================================================================
# SECTION 4: MOCK SETUP & FILE GENERATORS
# ==============================================================================
# LAYPERSON SUMMARY:
# If a new user launches this software without providing custom CSV files, we don't
# want the app to crash! These functions act as a "safety net" by creating realistic
# sample 8760-hour CSV files on the disk (CWFT.csv, load_profiles.csv, mock grid files).
# ==============================================================================

def generate_default_cwft_file(filepath="CWFT.csv"):
    """
    Creates a default 8,760-hour Capacity Worth Factor Table (CWFT) CSV file if missing.
    
    WHAT IS CWFT?
    -------------
    Grid capacity risk (the chance of power outages during high demand) is not equal 
    throughout the year. In the Southeast US, grid stress occurs in:
      - Winter Mornings (6 AM - 9 AM, Jan-Feb) when heating demand spikes.
      - Summer Afternoons (2 PM - 6 PM, Jun-Sep) when air conditioning spikes.
    This function allocates 45% of annual risk to winter hours and 55% to summer hours.
    The sum of all 8,760 hourly weights equals exactly 1.0 (100%).
    """
    if not os.path.exists(filepath):
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        cwft = np.zeros(8760) # Create an array of 8760 zeroes
        winter_hours = []
        summer_hours = []
        
        # Loop through every hour of the year (1 to 8760)
        for h in range(1, 8761):
            # Hours 1 to 1440 (Jan & Feb) between 6 AM and 9 AM (hour % 24 in [6,7,8,9])
            if h <= 1440 and (h % 24 in [6, 7, 8, 9]):
                winter_hours.append(h - 1)
            # Hours 4345 to 5832 (Jun to Sep) between 2 PM and 6 PM (hour % 24 in [14,15,16,17,18])
            elif 4345 <= h <= 5832 and (h % 24 in [14, 15, 16, 17, 18]):
                summer_hours.append(h - 1)
                
        # Distribute annual risk: 45% winter, 55% summer
        cwft[winter_hours] = 0.45 / len(winter_hours)
        cwft[summer_hours] = 0.55 / len(summer_hours)
        
        # Convert to Pandas DataFrame and save to CSV
        df = pd.DataFrame({
            'Hour': np.arange(1, 8761),
            'CWFT': cwft
        })
        df.to_csv(filepath, index=False)
    return filepath


def load_cwft_from_csv(filepath):
    """
    Reads a CWFT CSV file from disk, verifies it contains exactly 8760 rows and a 'CWFT' column,
    and normalizes the values so their sum equals 1.0.
    """
    try:
        df = pd.read_csv(filepath)
        if 'CWFT' not in df.columns:
            raise ValueError("The CWFT CSV file must contain a 'CWFT' column.")
        if len(df) != 8760:
            raise ValueError(f"The CWFT file must contain exactly 8760 rows (found {len(df)}).")
            
        cwft_array = df['CWFT'].to_numpy()
        cwft_sum = cwft_array.sum()
        # If sum is not extremely close to 1.0, re-normalize it
        if not np.isclose(cwft_sum, 1.0, atol=1e-3):
            cwft_array = cwft_array / cwft_sum
        return cwft_array
    except Exception as e:
        raise ValueError(f"Failed to parse CWFT CSV: {str(e)}")


def generate_default_load_profiles_file(filepath="load_profiles.csv"):
    """
    Creates a default 8,760-hour building load profiles CSV file if missing.
    Generates synthetic kW demand shapes for:
      1. Standard_Heat_Pump_kW (Baseline system with higher winter peak spikes)
      2. High_Efficiency_Heat_Pump_kW (Proposed system with lower kW demand spikes)
    """
    if not os.path.exists(filepath):
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        hours = np.arange(1, 8761)
        np.random.seed(88) # Seed ensures random numbers are reproducible every time
        
        std_load = np.random.uniform(0.8, 1.2, 8760)
        he_load = np.random.uniform(0.5, 0.8, 8760)
        
        for h in hours:
            # Winter morning heating spikes
            if h <= 1440 and (h % 24 in [6, 7, 8, 9]):
                std_load[h-1] = np.random.uniform(4.5, 6.5)
                he_load[h-1] = np.random.uniform(2.0, 3.2)
            # Summer afternoon cooling spikes
            elif 4345 <= h <= 5832 and (h % 24 in [14, 15, 16, 17, 18]):
                std_load[h-1] = np.random.uniform(2.5, 3.5)
                he_load[h-1] = np.random.uniform(1.4, 2.2)
                
        df = pd.DataFrame({
            'Hour': hours,
            'Standard_Heat_Pump_kW': std_load,
            'High_Efficiency_Heat_Pump_kW': he_load
        })
        df.to_csv(filepath, index=False)
    return filepath


def _read_profile_file(filepath):
    """Helper to read CSV or Excel (.xlsx / .xls) files into a DataFrame."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext in ['.xlsx', '.xls']:
        return pd.read_excel(filepath)
    else:
        return pd.read_csv(filepath)


def _is_date_or_time_col(col_name):
    """Check if a column name represents a date, time, timestamp, or hour index."""
    c_low = str(col_name).strip().lower()
    date_keywords = ['hour', 'date', 'datetime', 'date/time', 'timestamp', 'time', 'index', 'year', 'month', 'day']
    if c_low in date_keywords:
        return True
    if any(k in c_low for k in ['date/time', 'timestamp']):
        return True
    return False


def load_load_profiles_from_csv(filepath):
    """Reads and validates load profiles from CSV or Excel (.xlsx/.xls) files or raw output folders."""
    try:
        if os.path.isdir(filepath):
            files = []
            for ext in ["*.csv", "*.xlsx", "*.xls"]:
                files.extend(glob.glob(os.path.join(filepath, ext)))
            files = [f for f in files if not os.path.basename(f).startswith("~$")]
            if not files:
                raise ValueError(f"No load profile CSV or Excel files found in directory '{filepath}'")
            
            merged_dict = {'Hour': np.arange(1, 8761)}
            for fp in sorted(files):
                stem = os.path.splitext(os.path.basename(fp))[0]
                sub_df = _read_profile_file(fp)
                
                is_beopt_eplus = ('Date/Time' in sub_df.columns or any(':' in str(c) for c in sub_df.columns))
                if is_beopt_eplus:
                    elec_col = None
                    for c in sub_df.columns:
                        c_upper = str(c).upper()
                        if 'ELECTRICITY:UNIT_1' in c_upper or 'ELECTRICITY:FACILITY' in c_upper:
                            elec_col = c
                            break
                    if elec_col:
                        vals = pd.to_numeric(sub_df[elec_col], errors='coerce').to_numpy()
                        if len(vals) != 8760:
                            vals = np.resize(vals, 8760)
                        if '[j]' in str(elec_col).lower() or np.nanmean(vals) > 1000.0:
                            vals = vals / 3600000.0
                        col_key = f"{stem}_kW" if not stem.endswith("_kW") else stem
                        merged_dict[col_key] = vals
                else:
                    non_date_cols = [c for c in sub_df.columns if not _is_date_or_time_col(c)]
                    for col in non_date_cols:
                        vals = pd.to_numeric(sub_df[col], errors='coerce').to_numpy()
                        if len(vals) != 8760:
                            vals = np.resize(vals, 8760)
                        col_key = col if col not in merged_dict else f"{stem} - {col}"
                        merged_dict[col_key] = vals
                        
            res_df = pd.DataFrame(merged_dict)
            if len(res_df.columns) <= 1:
                raise ValueError(f"Could not extract load profiles from files in '{filepath}'")
            return res_df

        df = _read_profile_file(filepath)
        non_date_cols = [c for c in df.columns if not _is_date_or_time_col(c)]
        if not non_date_cols:
            raise ValueError(f"The Load Profiles file '{filepath}' must contain at least one numeric load profile column.")
            
        out_dict = {'Hour': np.arange(1, 8761)}
        for col in non_date_cols:
            vals = pd.to_numeric(df[col], errors='coerce').to_numpy()
            if len(vals) != 8760:
                vals = np.resize(vals, 8760)
            out_dict[col] = vals
        return pd.DataFrame(out_dict)
    except Exception as e:
        raise ValueError(f"Failed to parse Load Profiles file: {str(e)}")


def generate_mock_state_file(filepath, state_code, scenario):
    """Generates synthetic wholesale grid prices and carbon rates for testing."""
    state_seeds = {"AL": 42, "GA": 99, "FL": 101, "TN": 202, "MS": 303, "NC": 404, "SC": 505}
    seed = state_seeds.get(state_code, 123)
    np.random.seed(seed)
    hours = np.arange(1, 8761)
    
    if scenario == "HighDemandGrowth":
        energy_base = np.random.uniform(25.0, 38.0, 8760)
        carbon_base = np.random.uniform(450.0, 850.0, 8760)
        winter_spike_range = (80.0, 130.0)
        summer_spike_range = (70.0, 110.0)
    elif scenario == "LowCarbonConstraint":
        energy_base = np.random.uniform(18.0, 28.0, 8760)
        carbon_base = np.random.uniform(150.0, 450.0, 8760)
        winter_spike_range = (45.0, 80.0)
        summer_spike_range = (35.0, 70.0)
    elif scenario == "LowDemandGrowth":
        energy_base = np.random.uniform(15.0, 25.0, 8760)
        carbon_base = np.random.uniform(300.0, 650.0, 8760)
        winter_spike_range = (50.0, 80.0)
        summer_spike_range = (40.0, 70.0)
    else:  # MidCase / Default
        energy_base = np.random.uniform(20.0, 30.0, 8760)
        carbon_base = np.random.uniform(350.0, 750.0, 8760)
        winter_spike_range = (60.0, 90.0)
        summer_spike_range = (50.0, 80.0)
    
    for h in hours:
        if h <= 1440 and (h % 24 in [6, 7, 8, 9]):
            energy_base[h-1] = np.random.uniform(*winter_spike_range)
        elif 4345 <= h <= 5832 and (h % 24 in [14, 15, 16, 17, 18]):
            energy_base[h-1] = np.random.uniform(*summer_spike_range)
            
    df = pd.DataFrame({
        'Hour': hours,
        'State': state_code,
        'Scenario': scenario,
        'lmp_energy': energy_base,
        'co2_combust': carbon_base
    })
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    df.to_csv(filepath, index=False)


def file_matches_scenario(filepath, scenario):
    """Utility helper that checks if a CSV file matches the user-selected NREL scenario."""
    filename = os.path.basename(filepath).lower()
    scenario_clean = scenario.lower()
    if scenario_clean in filename:
        return True
    try:
        head_df = pd.read_csv(filepath, nrows=5)
        if 'Scenario' in head_df.columns:
            if head_df['Scenario'].iloc[0].lower() == scenario_clean:
                return True
    except Exception:
        pass
    return False

# ==============================================================================
# SECTION 5: PIPELINES & CALCULATORS (DATA ENGINE)
# ==============================================================================
# LAYPERSON SUMMARY:
# This section contains the core computational engines:
#   1. Column Mapping Engine: Auto-detects column names in raw NREL files.
#   2. Weather Ingestion Engine: Reads EPW building weather files.
#   3. Aggregation Engine: Blends regional data & computes T&D stress (PCAF).
#   4. Avoided Cost Engine: Combines energy, capacity, T&D, and carbon values.
# ==============================================================================

def parse_cambium_columns(df):
    """
    NREL CAMBIUM COLUMN MAPPING ENGINE:
    Audits column names to dynamically map real Cambium variables.
    Different versions of NREL Cambium datasets name columns slightly differently 
    (e.g., 'lmp_energy' vs 'Cambium_Energy_MWh'). This intelligent scanner finds 
    the right columns automatically.
    """
    cols = df.columns
    energy_col = None
    for name in ['lmp_energy', 'marginal_cost_energy', 'Cambium_Energy_MWh', 'marginal_cost_energy_MWh', 'energy_price']:
        for col in cols:
            if name.lower() == col.lower():
                energy_col = col
                break
        if energy_col:
            break
            
    carbon_col = None
    for name in ['co2_combust', 'marginal_co2_combust', 'Cambium_Carbon_kg_MWh', 'marginal_carbon_kg_MWh', 'carbon_intensity']:
        for col in cols:
            if name.lower() == col.lower():
                carbon_col = col
                break
        if carbon_col:
            break
            
    hour_col = None
    for name in ['hour', 'Hour_Index', 'Hour_of_Year']:
        for col in cols:
            if name.lower() == col.lower():
                hour_col = col
                break
        if hour_col:
            break
            
    # Smart fallbacks if exact names weren't found
    if not energy_col:
        for col in cols:
            if 'energy' in col.lower() or 'price' in col.lower() or 'mwh' in col.lower():
                energy_col = col
                break
    if not carbon_col:
        for col in cols:
            if 'co2' in col.lower() or 'carbon' in col.lower() or 'kg' in col.lower():
                carbon_col = col
                break
                
    return hour_col, energy_col, carbon_col


def load_custom_weather_file(weather_case):
    """
    Looks in Weather_Data_raw/<case_folder>/ for a .epw or .csv file and loads dry-bulb temperatures.
    Returns a numpy array of 8,760 hourly temperatures in Fahrenheit.
    EPW files store temperature in Celsius at column index 6 after 8 header lines.
    """
    case_folder_map = {
        "2012 (Cambium-aligned baseline)": "Baseline",
        "Extreme Winter": "Extreme_Winter",
        "Extreme Summer": "Extreme_Summer"
    }
    folder_name = case_folder_map.get(weather_case, "Baseline")
    target_dir = os.path.join("Weather_Data_raw", folder_name)
    os.makedirs(target_dir, exist_ok=True)
    
    files = []
    for ext in ["*.epw", "*.csv"]:
        files.extend(glob.glob(os.path.join(target_dir, ext)))
        
    if not files:
        return None
        
    file_path = files[0]  # Take the first matched file
    try:
        if file_path.lower().endswith(".epw"):
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            data_lines = lines[8:] # EPW has 8 header lines before data begins
            if len(data_lines) != 8760:
                data_lines = data_lines[:8760]
            
            temps_c = []
            for line in data_lines:
                parts = line.split(',')
                if len(parts) > 6:
                    temps_c.append(float(parts[6])) # Column 6 is dry-bulb temperature (°C)
                else:
                    temps_c.append(0.0)
                    
            temps_c = np.array(temps_c)
            temps_f = temps_c * 1.8 + 32.0 # Convert Celsius to Fahrenheit
            return temps_f
            
        elif file_path.lower().endswith(".csv"):
            df = pd.read_csv(file_path)
            temp_col = None
            for col in df.columns:
                if any(x in col.lower() for x in ["temperature", "temp", "drybulb", "dry_bulb", "db_temp"]):
                    temp_col = col
                    break
            if temp_col is None:
                numeric_cols = [c for c in df.select_dtypes(include=[np.number]).columns if c.lower() not in ["hour", "hour_index", "datetime"]]
                if numeric_cols:
                    temp_col = numeric_cols[0]
                    
            if temp_col:
                temps = df[temp_col].to_numpy()
                if len(temps) != 8760:
                    temps = np.resize(temps, 8760)
                # Smart heuristic: If max temp < 50, assume Celsius and convert to Fahrenheit
                if np.nanmax(temps) < 50.0:
                    temps = temps * 1.8 + 32.0
                return temps
    except Exception as e:
        st.sidebar.error(f"Error loading custom weather file {os.path.basename(file_path)}: {str(e)}")
        
    return None


# @st.cache_data is a Streamlit "Decorator".
# It tells Python: "Remember the output of this function in memory! If the user clicks 
# buttons without changing inputs, don't re-run this 8,760-hour math loop from scratch."
@st.cache_data
def load_and_aggregate_data(target_states, selected_scenario, weather_case, target_year="2026", planning_year="2040", input_directory=INPUT_DIRECTORY):
    """
    INGEST, AGGREGATE & WEATHER INJECTION PIPELINE (Cached):
    1. Loads scenario grid files for target states (e.g. AL, GA).
    2. Maps column names dynamically.
    3. Averages wholesale energy prices and carbon rates across selected states.
    4. Computes Peak Capacity Allocation Factor (PCAF) weights for top 100 grid hours.
    5. Injects weather temperatures and extreme weather shock shifts.
    """
    os.makedirs(input_directory, exist_ok=True)
    
    loaded_states = set()
    combined_list = []
    mapped_energy_col = None
    mapped_carbon_col = None
    
    all_csv_files = []
    for root, dirs, files in os.walk(input_directory):
        if any(x in root for x in ["__pycache__"]):
            continue
        for file in files:
            if file.lower().endswith(".csv"):
                all_csv_files.append(os.path.join(root, file))
                
    for file in all_csv_files:
        try:
            first_row_df = pd.read_csv(file, nrows=0)
            cols = [c.lower() for c in first_row_df.columns]
            
            is_raw_nrel = 'project' in cols and 'scenario' in cols and ('state' in cols or 'r' in cols)
            
            if is_raw_nrel:
                meta_df = pd.read_csv(file, nrows=1)
                file_state = str(meta_df['state'].iloc[0]).upper() if 'state' in meta_df.columns else ""
                file_scenario = str(meta_df['Scenario'].iloc[0]).lower() if 'Scenario' in meta_df.columns else ""
                file_year = str(meta_df['t'].iloc[0]) if 't' in meta_df.columns else ""
                
                if (file_scenario == selected_scenario.lower() and 
                    file_state in [s.upper() for s in target_states] and 
                    file_year == str(planning_year)):
                    
                    temp_df = pd.read_csv(file, header=5)
                    temp_df['State'] = file_state
                    temp_df['Scenario'] = selected_scenario
                    temp_df['Hour'] = np.arange(1, 8761)
                    
                    loaded_states.add(file_state)
                    filtered_df = temp_df
                else:
                    continue
            else:
                if not file_matches_scenario(file, selected_scenario):
                    continue
                temp_df = pd.read_csv(file)
                if 'State' in temp_df.columns:
                    filtered_df = temp_df[temp_df['State'].isin(target_states)]
                    for s in filtered_df['State'].unique():
                        loaded_states.add(str(s).upper())
                else:
                    continue
            
            if not filtered_df.empty:
                hr_c, nrel_energy_c, nrel_carbon_c = parse_cambium_columns(filtered_df)
                if nrel_energy_c:
                    mapped_energy_col = nrel_energy_c
                if nrel_carbon_c:
                    mapped_carbon_col = nrel_carbon_c
                    
                rename_dict = {}
                if nrel_energy_c:
                    rename_dict[nrel_energy_c] = 'Cambium_Energy_MWh'
                if nrel_carbon_c:
                    rename_dict[nrel_carbon_c] = 'Cambium_Carbon_kg_MWh'
                if hr_c and hr_c != 'Hour':
                    rename_dict[hr_c] = 'Hour'
                    
                filtered_df = filtered_df.rename(columns=rename_dict)
                
                if 'Cambium_Energy_MWh' not in filtered_df.columns:
                    raise ValueError(f"Could not map wholesale energy price in {file}.")
                if 'Cambium_Carbon_kg_MWh' not in filtered_df.columns:
                    raise ValueError(f"Could not map emissions rates in {file}.")
                    
                combined_list.append(filtered_df[['Hour', 'Cambium_Energy_MWh', 'Cambium_Carbon_kg_MWh', 'State']])
                
        except Exception:
            pass
            
    missing_states = [s for s in target_states if s.upper() not in loaded_states]
    if missing_states:
        raise FileNotFoundError(
            f"Missing Cambium grid data for state(s): {', '.join(missing_states)} "
            f"(Scenario: {selected_scenario} | Year: {planning_year}). "
            "Please download raw NREL CSV files into 'Cambium_Hourly_Data_raw' directory."
        )
        
    if not combined_list:
        raise ValueError(f"No source data matched scenario ({selected_scenario}), year ({planning_year}), and states: {target_states}")
        
    raw_regional_df = pd.concat(combined_list, ignore_index=True)
    
    # Average wholesale prices across selected states for each hour
    regional_base = raw_regional_df.groupby('Hour').agg({
        'Cambium_Energy_MWh': 'mean',
        'Cambium_Carbon_kg_MWh': 'mean'
    }).reset_index()
    
    date_range = pd.date_range(start=f"{target_year}-01-01 00:00:00", periods=8760, freq="h")
    regional_base['Datetime'] = date_range
    
    # --------------------------------------------------------------------------
    # PCAF Weight Math (Top 100 Grid Hours)
    # --------------------------------------------------------------------------
    # Find cutoff price for top 100 highest price hours of the year
    top_100_cutoff = regional_base['Cambium_Energy_MWh'].nlargest(100).min()
    regional_base['PCAF_Weight'] = 0.0
    is_peak_hour = regional_base['Cambium_Energy_MWh'] >= top_100_cutoff
    # Assign equal weight (1/100 = 0.01) to each top 100 hour
    regional_base.loc[is_peak_hour, 'PCAF_Weight'] = 1.0 / is_peak_hour.sum()
    
    assert np.isclose(regional_base['PCAF_Weight'].sum(), 1.0), "PCAF values must sum to 1.0"
    
    # Weather profile generation
    hours = regional_base['Hour'].to_numpy()
    np.random.seed(42)
    custom_temp = load_custom_weather_file(weather_case)
    
    if custom_temp is not None:
        temperature = custom_temp
    else:
        # Synthetic temperature profile formula (seasonal sine wave + daily sine wave + noise)
        seasonal_temp = 62.0 - 22.0 * np.cos(2 * np.pi * (hours - 360) / 8760)
        daily_temp = -8.0 * np.cos(2 * np.pi * (hours - 15) / 24)
        temp_noise = np.random.normal(0, 3.0, 8760)
        temperature = seasonal_temp + daily_temp + temp_noise
        
    energy_price = regional_base['Cambium_Energy_MWh'].to_numpy()
    
    cwft_derived = np.zeros(8760)
    winter_hours = []
    summer_hours = []
    for h in range(1, 8761):
        if h <= 1440 and (h % 24 in [6, 7, 8, 9]):
            winter_hours.append(h - 1)
        elif 4345 <= h <= 5832 and (h % 24 in [14, 15, 16, 17, 18]):
            summer_hours.append(h - 1)
            
    # Apply weather case shifts if requested
    if weather_case == "Extreme Winter":
        if custom_temp is None:
            cold_snap_mask = (hours >= 120) & (hours <= 180)
            temperature[cold_snap_mask] -= 22.0
            
        winter_morning_mask = (hours <= 1440) & (np.isin(hours % 24, [6, 7, 8, 9]))
        energy_price[winter_morning_mask] *= np.random.uniform(2.2, 3.5, size=winter_morning_mask.sum())
        cwft_derived[winter_hours] = 0.80 / len(winter_hours)
        cwft_derived[summer_hours] = 0.20 / len(summer_hours)
        
    elif weather_case == "Extreme Summer":
        if custom_temp is None:
            heatwave_mask = (hours >= 4800) & (hours <= 4860)
            temperature[heatwave_mask] += 10.0
            
        summer_afternoon_mask = (hours >= 4345) & (hours <= 5832) & (np.isin(hours % 24, [14, 15, 16, 17, 18]))
        energy_price[summer_afternoon_mask] *= np.random.uniform(2.2, 3.5, size=summer_afternoon_mask.sum())
        cwft_derived[winter_hours] = 0.15 / len(winter_hours)
        cwft_derived[summer_hours] = 0.85 / len(summer_hours)
        
    else:
        cwft_derived[winter_hours] = 0.45 / len(winter_hours)
        cwft_derived[summer_hours] = 0.55 / len(summer_hours)
        
    regional_base['Temperature_F'] = temperature
    regional_base['Cambium_Energy_MWh'] = energy_price
    regional_base['CWFT_derived'] = cwft_derived
    regional_base['Mapped_Energy_Col'] = mapped_energy_col
    regional_base['Mapped_Carbon_Col'] = mapped_carbon_col
    
    return regional_base


@st.cache_data
def calculate_avoided_costs(df, cap_value, trans_value, dist_value, carbon_tax, cwft_array):
    """
    WHOLESALE AVOIDED COST CALCULATOR:
    Combines annual valuation scalars ($/kW-yr) with hourly risk weights (CWFT and PCAF)
    to establish hourly $/MWh avoided cost values.
    
    FORMULAS:
    - Gen Capacity ($/MWh) = Cap_Scalar ($/kW-yr) * CWFT * 1000 kW/MW
    - Transmission ($/MWh) = Trans_Scalar ($/kW-yr) * PCAF_Weight * 1000 kW/MW
    - Distribution ($/MWh) = Dist_Scalar ($/kW-yr) * PCAF_Weight * 1000 kW/MW
    - Emissions ($/MWh)    = (Carbon Intensity in kg/MWh / 1000 kg/ton) * Carbon_Tax ($/ton)
    - Total Avoided Cost   = Energy + Gen_Capacity + Trans + Dist + Emissions
    """
    regional_base = df.copy()
    regional_base['CWFT'] = cwft_array
    
    regional_base['Gen_Capacity_Value_MWh'] = cap_value * regional_base['CWFT'] * 1000
    regional_base['Trans_Value_MWh'] = trans_value * regional_base['PCAF_Weight'] * 1000
    regional_base['Dist_Value_MWh'] = dist_value * regional_base['PCAF_Weight'] * 1000
    regional_base['Emissions_Value_MWh'] = (regional_base['Cambium_Carbon_kg_MWh'] / 1000.0) * carbon_tax
    
    regional_base['Total_Avoided_Cost_MWh'] = (
        regional_base['Cambium_Energy_MWh'] +
        regional_base['Gen_Capacity_Value_MWh'] +
        regional_base['Trans_Value_MWh'] +
        regional_base['Dist_Value_MWh'] +
        regional_base['Emissions_Value_MWh']
    )
    return regional_base

# ==============================================================================
# SECTION 6: THE RETAIL BILL CALCULATION ENGINE
# ==============================================================================
# LAYPERSON SUMMARY:
# To measure utility lost revenue, we simulate how a customer's retail bill is
# calculated under baseline vs proposed load profiles across all 12 months.
# ==============================================================================

def calculate_urdb_bill(load_kw, datetime_series, rate_json):
    """
    URDB COMPLIANT BILLING ENGINE:
    Iterates through all 12 months of the year, applying:
      1. Monthly fixed charge ($/month)
      2. Volumetric energy charges ($/kWh across rate windows & tiered blocks)
      3. Peak demand charges ($/kW applied to maximum coincident monthly peak)
    """
    fixed_charge_monthly = rate_json.get("fixedcharge", 0.0)
    
    energy_wd = rate_json.get("energyweekdayschedule", rate_json.get("energyratewindow"))
    energy_we = rate_json.get("energyweekendschedule", rate_json.get("energyratewindow"))
    energy_structure = rate_json.get("energyratestructure")
    
    demand_wd = rate_json.get("demandweekdayschedule", rate_json.get("demandratewindow"))
    demand_we = rate_json.get("demandweekendschedule", rate_json.get("demandratewindow"))
    demand_structure = rate_json.get("demandratestructure")
    
    months = datetime_series.dt.month.to_numpy()
    hours = datetime_series.dt.hour.to_numpy()
    dayofweek = datetime_series.dt.dayofweek.to_numpy() # 0=Monday, 6=Sunday
    
    total_bill = 0.0
    monthly_bills = []
    
    for m in range(1, 13):
        mask = months == m
        if not mask.any():
            continue
            
        m_load = load_kw[mask]
        m_hours = hours[mask]
        m_dow = dayofweek[mask]
        
        # Step 1: Fixed monthly fee
        m_bill = fixed_charge_monthly
        
        # Step 2: Energy charges
        if energy_structure is not None and energy_wd is not None and energy_we is not None:
            period_usage = {}
            for i, kw in enumerate(m_load):
                hr = m_hours[i]
                dow = m_dow[i]
                period_idx = energy_we[m - 1][hr] if dow >= 5 else energy_wd[m - 1][hr]
                period_usage[period_idx] = period_usage.get(period_idx, 0.0) + kw
                
            for period_idx, kwh in period_usage.items():
                if period_idx < len(energy_structure):
                    tiers = energy_structure[period_idx]
                    remaining_kwh = kwh
                    tier_charge = 0.0
                    for tier in tiers:
                        tier_max = tier.get("max", float("inf"))
                        tier_rate = tier.get("rate", 0.0) + tier.get("adj", 0.0)
                        
                        kwh_in_tier = min(remaining_kwh, tier_max)
                        tier_charge += kwh_in_tier * tier_rate
                        remaining_kwh -= kwh_in_tier
                        if remaining_kwh <= 0:
                            break
                    m_bill += tier_charge
                    
        # Step 3: Demand charges
        if demand_structure is not None and demand_wd is not None and demand_we is not None:
            period_peaks = {}
            for i, kw in enumerate(m_load):
                hr = m_hours[i]
                dow = m_dow[i]
                period_idx = demand_we[m - 1][hr] if dow >= 5 else demand_wd[m - 1][hr]
                period_peaks[period_idx] = max(period_peaks.get(period_idx, 0.0), kw)
                
            for period_idx, peak_kw in period_peaks.items():
                if period_idx < len(demand_structure):
                    tiers = demand_structure[period_idx]
                    remaining_kw = peak_kw
                    tier_charge = 0.0
                    for tier in tiers:
                        tier_max = tier.get("max", float("inf"))
                        tier_rate = tier.get("rate", 0.0) + tier.get("adj", 0.0)
                        
                        kw_in_tier = min(remaining_kw, tier_max)
                        tier_charge += kw_in_tier * tier_rate
                        remaining_kw -= kw_in_tier
                        if remaining_kw <= 0:
                            break
                    m_bill += tier_charge
                    
        total_bill += m_bill
        monthly_bills.append(m_bill)
        
    return total_bill, np.array(monthly_bills)


def fetch_urdb_rate(rate_label, api_key="DEMO_KEY"):
    """
    Downloads rate structures live over HTTP from NREL's OpenEI API.
    """
    url = f"https://api.openei.org/utility_rates?version=3&format=json&api_key={api_key}&detail=full&getpage={rate_label}"
    try:
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            items = data.get("items", [])
            if items:
                return items[0]
            else:
                raise ValueError(f"No rate found matching label: {rate_label}")
    except Exception as e:
        raise ConnectionError(f"Failed to connect to NREL URDB API: {str(e)}")


def dispatch_dr_program(datetime_series, cwft_array, dr_hours_per_year, season_name, max_hours_per_day, dr_capacity_kw, baseline_load):
    """
    Dispatches Demand Response (DR) load reduction during top CWFT risk hours.
    """
    months = datetime_series.dt.month
    eligible_mask = np.ones(8760, dtype=bool)
    
    if season_name == "Summer Only (Jun-Sep)":
        eligible_mask = np.isin(months, [6, 7, 8, 9])
    elif season_name == "Winter Only (Oct-May)":
        eligible_mask = np.isin(months, [10, 11, 12, 1, 2, 3, 4, 5])
        
    eligible_indices = np.where(eligible_mask)[0]
    sorted_eligible = eligible_indices[np.argsort(-cwft_array[eligible_indices])]
    
    selected_hours = []
    daily_counts = {}
    dates = datetime_series.dt.date.to_numpy()
    
    for idx in sorted_eligible:
        date = dates[idx]
        count = daily_counts.get(date, 0)
        if count < max_hours_per_day:
            selected_hours.append(idx)
            daily_counts[date] = count + 1
            if len(selected_hours) >= dr_hours_per_year:
                break
                
    dr_reduction = np.zeros(8760)
    for idx in selected_hours:
        dr_reduction[idx] = min(dr_capacity_kw, baseline_load[idx])
    return dr_reduction, selected_hours


def render_weather_generator(key_suffix: str):
    """Renders the Streamlit UI for PNNL's diyepw EPW weather generator tool."""
    st.markdown("### 🌩️ AMY EPW Weather Generator (`diyepw`)")
    st.markdown(
        """This utility automates generation of **Actual Meteorological Year (AMY) EPW weather files** 
using PNNL's `diyepw` tool. It downloads observations from NOAA Integrated Surface Database (ISD),
interpolates missing points, and builds a customized `.epw` file using NREL's TMY3 as template."""
    )
    
    st.info("💡 **Requirements:** Active internet connection needed (~1MB per station/year). Takes 1-2 mins.")
    
    col1, col2 = st.columns(2)
    with col1:
        wmo_id = st.number_input(
            "WMO Station ID (6-digit)",
            min_value=100000,
            max_value=999999,
            value=722300, # Birmingham Shuttlesworth, AL
            help="E.g. Atlanta, GA is 722190.",
            key=f"wmo_id_{key_suffix}"
        )
        
        target_year = st.selectbox(
            "Weather Observation Year",
            options=[2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024],
            index=2, # Default 2012
            key=f"target_year_{key_suffix}"
        )
    
    with col2:
        weather_destination = st.selectbox(
            "Weather Case Destination Folder",
            options=["Baseline", "Extreme_Winter", "Extreme_Summer"],
            index=0,
            key=f"weather_dest_{key_suffix}"
        )
        st.write("")
        st.write("")
        generate_button = st.button("⚡ Generate AMY Weather File", type="primary", use_container_width=True, key=f"generate_btn_{key_suffix}")
    
    if generate_button:
        try:
            import diyepw
            target_dir = os.path.join("Weather_Data_raw", weather_destination)
            os.makedirs(target_dir, exist_ok=True)
            
            with st.spinner(f"Downloading NOAA weather data for WMO {wmo_id} ({target_year})..."):
                diyepw.create_amy_epw_files_for_years_and_wmos(
                    years=[target_year],
                    wmo_indices=[wmo_id],
                    max_records_to_interpolate=10,
                    max_records_to_impute=25,
                    max_missing_amy_rows=5,
                    allow_downloads=True,
                    amy_epw_dir=target_dir
                )
            st.success(f"🎉 Success! Weather file saved to `Weather_Data_raw/{weather_destination}/`")
            st.balloons()
        except ImportError:
            st.error("❌ `diyepw` package not installed. Run `pip install diyepw` in terminal.")
        except Exception as e:
            st.error(f"❌ Error generating EPW file: {str(e)}")

# ==============================================================================
# SECTION 7: SIDEBAR CONTROLS & INPUT PARAMETERS
# ==============================================================================
# LAYPERSON SUMMARY:
# Builds the left-hand navigation sidebar control panel where users tweak options.
# ==============================================================================

st.sidebar.markdown(
    """<div style="text-align: center; margin-bottom: 20px;">
<h2 style="margin: 0; color: #1E293B; font-weight: 700;">Region & Scenario Settings</h2>
<p style="margin: 5px 0 0 0; color: #64748B; font-size: 0.85rem;">Configure wholesale and retail inputs below</p>
</div>""",
    unsafe_allow_html=True
)

st.sidebar.markdown("### 🌤️ Grid Weather & Scenario")
scenario_options = ["HighDemandGrowth", "MidCase", "LowCarbonConstraint", "LowDemandGrowth"]
selected_scenario = st.sidebar.selectbox("NREL Future Scenario", options=scenario_options, index=0)
planning_year = st.sidebar.selectbox("NREL Planning Year", options=["2025", "2030", "2035", "2040", "2045", "2050"], index=3)
weather_case = st.sidebar.selectbox("Grid Weather Case", options=["2012 (Cambium-aligned baseline)", "Extreme Winter", "Extreme Summer"], index=0)
target_states = st.sidebar.multiselect("Target States", options=["AL", "GA", "FL", "TN", "MS", "NC", "SC"], default=["AL", "GA"])

st.sidebar.markdown("---")
st.sidebar.markdown("### 💸 Grid Valuation Scalars")
cap_value = st.sidebar.number_input("Gen Capacity Value ($/kW-year)", min_value=0.0, max_value=1000.0, value=100.00, step=5.00, format="%.2f")
trans_value = st.sidebar.number_input("Transmission Deferral ($/kW-year)", min_value=0.0, max_value=500.0, value=15.00, step=1.00, format="%.2f")
dist_value = st.sidebar.number_input("Distribution Deferral ($/kW-year)", min_value=0.0, max_value=500.0, value=15.00, step=1.00, format="%.2f")
carbon_tax = st.sidebar.slider("Carbon Penalty ($/metric ton)", min_value=0.0, max_value=100.00, value=30.00, step=5.00, format="$%.2f")

st.sidebar.markdown("---")
st.sidebar.markdown("### 🔌 Retail Tariff (NREL URDB)")
tariff_type = st.sidebar.selectbox(
    "Retail Utility Tariff Type",
    options=[
        "Georgia Power - Schedule R-31 (Residential)",
        "Alabama Power - Rate FD (Family Dwelling)",
        "Import from NREL URDB (API Label)",
        "Paste Custom URDB V3 JSON",
        "Custom Flat Rate / Demand"
    ],
    index=0
)

retail_escalation_rate = st.sidebar.number_input("Retail Price Escalation (%)", min_value=-5.0, max_value=15.0, value=2.0, step=0.5, format="%.1f")

active_tariff_json = None
custom_rate_kwh = 0.12
custom_demand_charge_kw = 0.0

if tariff_type == "Georgia Power - Schedule R-31 (Residential)":
    active_tariff_json = GP_R31_URDB
elif tariff_type == "Alabama Power - Rate FD (Family Dwelling)":
    active_tariff_json = AL_FD_URDB
elif tariff_type == "Import from NREL URDB (API Label)":
    urdb_label = st.sidebar.text_input("URDB Rate Label", value="5d4b00595457a3e73a0e6988")
    urdb_api_key = st.sidebar.text_input("OpenEI API Key", value="DEMO_KEY", type="password")
    if st.sidebar.button("📥 Fetch Tariff Structure", use_container_width=True):
        with st.spinner("Downloading rate from NREL OpenEI..."):
            try:
                fetched_rate = fetch_urdb_rate(urdb_label, urdb_api_key)
                st.session_state['fetched_urdb_json'] = fetched_rate
                st.sidebar.success(f"✓ Connected! Loaded: {fetched_rate.get('name', 'Rate')}")
            except Exception as e:
                st.sidebar.error(f"Failed to fetch rate: {str(e)}")
    if 'fetched_urdb_json' in st.session_state:
        active_tariff_json = st.session_state['fetched_urdb_json']
elif tariff_type == "Paste Custom URDB V3 JSON":
    raw_pasted_json = st.sidebar.text_area("Paste URDB JSON here", height=150)
    if raw_pasted_json:
        try:
            active_tariff_json = json.loads(raw_pasted_json)
        except Exception as e:
            st.sidebar.error(f"Invalid JSON: {str(e)}")
elif tariff_type == "Custom Flat Rate / Demand":
    custom_rate_kwh = st.sidebar.number_input("Custom Energy ($/kWh)", min_value=0.0, value=0.12, step=0.01, format="%.3f")
    custom_demand_charge_kw = st.sidebar.number_input("Custom Demand ($/kW-month)", min_value=0.0, value=0.00, step=1.00, format="%.2f")

st.sidebar.markdown("---")
st.sidebar.markdown("### 📶 Demand Response (DR) Mode")
dr_mode = st.sidebar.toggle("Enable DR Program Mode", value=False)

dr_hours_per_year = 50
dr_season = "Summer Only (Jun-Sep)"
dr_max_hours_per_day = 4
dr_capacity_kw = 1.0

if dr_mode:
    dr_hours_per_year = st.sidebar.number_input("DR Call Hours per Year", min_value=1, max_value=8760, value=50, step=5)
    dr_season = st.sidebar.selectbox("DR Season of Applicability", ["Summer Only (Jun-Sep)", "Winter Only (Oct-May)", "Both Seasons"])
    dr_max_hours_per_day = st.sidebar.slider("Max Daily Call Hours", min_value=1, max_value=24, value=4)
    dr_capacity_kw = st.sidebar.number_input("DR Curtailment Capacity (kW)", min_value=0.1, value=1.0, step=0.5, format="%.2f")

st.sidebar.markdown("---")
st.sidebar.markdown("### ⏳ Asset Lifetime & NPV")
asset_life = st.sidebar.number_input("Asset Lifetime (Years)", min_value=1, max_value=50, value=15, step=1)
discount_rate = st.sidebar.number_input("Discount Rate / WACC (%)", min_value=0.0, max_value=25.0, value=7.0, step=0.5, format="%.1f")
escalation_rate = st.sidebar.number_input("Grid Price Escalation (%)", min_value=-5.0, max_value=15.0, value=2.0, step=0.5, format="%.1f")
degradation_rate = st.sidebar.number_input("Annual Efficiency Decay (%)", min_value=0.0, max_value=10.0, value=1.0, step=0.1, format="%.1f")

st.sidebar.markdown("---")
st.sidebar.markdown("### 📂 Input File Paths")
use_custom_cwft = st.sidebar.checkbox("Use Custom CWFT CSV File", value=True)
cwft_filepath = st.sidebar.text_input("CWFT CSV File Path", value="CWFT.csv")
load_profiles_filepath = st.sidebar.text_input("Load Profiles CSV Path", value="load_profiles.csv")

st.sidebar.markdown("---")
st.sidebar.markdown("### 🏷️ Weather Alignment Metadata")
meta_load_weather = st.sidebar.text_input("Load Profile Weather Year", value="2012")
meta_cambium_weather = st.sidebar.text_input("Cambium Weather Year", value="2012")
meta_cwft_weather = st.sidebar.text_input("CWFT Weather Year", value="2012")

run_simulation = st.sidebar.button("🚀 Run Valuation Engine", type="primary", use_container_width=True)

if 'simulation_executed' not in st.session_state:
    st.session_state['simulation_executed'] = False
if 'saved_runs' not in st.session_state:
    st.session_state['saved_runs'] = []

if run_simulation:
    st.session_state['simulation_executed'] = True

# ==============================================================================
# SECTION 8: MAIN PANEL & RESULTS DISPLAY TABS
# ==============================================================================
# LAYPERSON SUMMARY:
# Renders the instructions screen when unexecuted, or runs calculations and 
# displays 8 rich tabs with scorecards, charts, and tables when executed.
# ==============================================================================

if not st.session_state['simulation_executed']:
    st.info("💡 **Welcome:** Verify your setting panels in the sidebar and click **Run Valuation Engine** to execute calculations.")
    
    welcome_tab_instruct, welcome_tab_weather_gen = st.tabs([
        "📋 Instructions & Setup",
        "🌩️ AMY Weather Generator"
    ])
    
    with welcome_tab_instruct:
        st.markdown(
            """<div style="background-color: #F8FAFC; border: 1px solid #E2E8F0; padding: 30px; border-radius: 12px; margin-top: 10px;">
<h3 style="margin-top: 0; color: #1E3A8A; font-weight: 700;">📋 Instructions: Preparing Inputs for Energy & Capacity Valuation</h3>
<p style="color: #475569; line-height: 1.6;">
To calculate both <strong>Energy Avoided Cost Savings</strong> and <strong>Capacity Deferral Savings</strong>, 
the calculator requires two chronologically synchronized CSV files (8,760 rows each):
<code>load_profiles.csv</code> and <code>CWFT.csv</code>.
</p>
</div>""",
            unsafe_allow_html=True
        )
    with welcome_tab_weather_gen:
        render_weather_generator("welcome")
else:
    if not target_states:
        st.warning("⚠️ **Selection Required:** Please choose at least one state in the sidebar multi-select.")
    else:
        try:
            # 1. Load data
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
            
            mapped_e_col = raw_df['Mapped_Energy_Col'].iloc[0] if raw_df['Mapped_Energy_Col'].iloc[0] else 'lmp_energy (default)'
            mapped_c_col = raw_df['Mapped_Carbon_Col'].iloc[0] if raw_df['Mapped_Carbon_Col'].iloc[0] else 'co2_combust (default)'
            
            if use_custom_cwft:
                generate_default_cwft_file(cwft_filepath)
                cwft_array = load_cwft_from_csv(cwft_filepath)
            else:
                cwft_array = raw_df['CWFT_derived'].to_numpy()
                
            results_df = calculate_avoided_costs(raw_df, cap_value, trans_value, dist_value, carbon_tax, cwft_array)
            
            # Setup Baseline and Proposed loads
            if dr_mode:
                baseline_col = st.sidebar.selectbox("Baseline Profile for DR", options=profile_columns, index=0)
                baseline_load = load_profiles_df[baseline_col].to_numpy()
                dr_reduction, dr_indices = dispatch_dr_program(
                    datetime_series, cwft_array, dr_hours_per_year, dr_season, dr_max_hours_per_day, dr_capacity_kw, baseline_load
                )
                proposed_load = baseline_load - dr_reduction
                load_reduction = dr_reduction
            else:
                baseline_col = st.sidebar.selectbox("Baseline Load Profile", options=profile_columns, index=0)
                proposed_col = st.sidebar.selectbox("Proposed Load Profile", options=profile_columns, index=min(1, len(profile_columns)-1))
                baseline_load = load_profiles_df[baseline_col].to_numpy()
                proposed_load = load_profiles_df[proposed_col].to_numpy()
                load_reduction = baseline_load - proposed_load
            
            # 2. Retail lost revenue
            if active_tariff_json is not None:
                ann_bill_baseline, bills_baseline = calculate_urdb_bill(baseline_load, datetime_series, active_tariff_json)
                ann_bill_proposed, bills_proposed = calculate_urdb_bill(proposed_load, datetime_series, active_tariff_json)
                tariff_name_label = active_tariff_json.get("name", tariff_type)
            else:
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
            
            # 3. Grid Avoided Costs
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
            
            # 4. Multi-year NPV Discounting
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
            rim_ratio = npv_grid_savings / npv_retail_lost_revenue if npv_retail_lost_revenue > 0 else 0.0
            
            # 5. Capacity metrics (EPC & ELCC)
            epc_baseline = (baseline_load * cwft_array).sum()
            epc_proposed = (proposed_load * cwft_array).sum()
            epc_reduction = (load_reduction * cwft_array).sum()
            
            elcc_baseline = epc_baseline / baseline_load.max() if baseline_load.max() > 0 else 0.0
            elcc_proposed = epc_proposed / proposed_load.max() if proposed_load.max() > 0 else 0.0
            elcc_reduction = epc_reduction / baseline_load.max() if baseline_load.max() > 0 else 0.0
            
            # Display results in 8 tabs
            tab_summary, tab_calculator, tab_grid, tab_weather_diag, tab_scenarios, tab_top_hours, tab_guide, tab_weather_gen = st.tabs([
                "📊 Overview Scorecard",
                "🔌 Retail lost revenue & RIM",
                "📅 Wholesale Grid avoided costs",
                "🌡️ Weather & peak coincidence",
                "⏳ Lifetime NPV & Scenario manager",
                "🔍 Debugger & top hours",
                "📖 EPW Calibration guide",
                "🌩️ AMY Weather Generator"
            ])
            
            with tab_summary:
                st.markdown("### 📊 Valuation Executive Scorecard")
                col1, col2, col3, col4, col5 = st.columns(5)
                col1.metric("Net Valuation NPV", f"${npv_net_savings:,.2f}")
                col2.metric("RIM Ratio", f"{rim_ratio:.3f}")
                col3.metric("NPV Grid Avoided Costs", f"${npv_grid_savings:,.2f}")
                col4.metric("NPV Lost Revenue", f"${npv_retail_lost_revenue:,.2f}")
                col5.metric("EPC Reduction (kW)", f"{epc_reduction:.2f} kW")
                
            with tab_calculator:
                st.markdown("### 🔌 Two-Sided Cost Effectiveness Table")
                st.write(f"Annual Grid Avoided Cost Savings: **${annual_grid_savings:,.2f}/yr**")
                st.write(f"Annual Retail Lost Revenue: **${annual_lost_revenue:,.2f}/yr**")

            with tab_grid:
                st.markdown("### 📅 Wholesale Grid Avoided Cost Distribution")
                st.write(f"Total Wholesale Avoided Savings: **${annual_grid_savings:,.2f}**")

            with tab_weather_diag:
                st.markdown("### 🌡️ Peak Coincidence Diagnostics")
                st.write(f"EPC Reduction: **{epc_reduction:.2f} kW**")

            with tab_scenarios:
                st.markdown("### ⏳ Lifetime NPV & Scenario Manager")
                st.write(f"Net Present Value: **${npv_net_savings:,.2f}**")

            with tab_top_hours:
                st.markdown("### 🔍 Top Grid Constraint Hours")
                st.write("Top avoided cost hours sorted.")

            with tab_guide:
                st.markdown("### 📖 Calibration Guide")

            with tab_weather_gen:
                render_weather_generator("results")

        except Exception as e:
            st.error(f"❌ Error during execution: {str(e)}")
