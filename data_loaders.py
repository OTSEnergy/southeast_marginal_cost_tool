"""
data_loaders.py — Data Ingestion, File Generators, and Column Mapping
=====================================================================

This module handles ALL data loading and file generation for the
Southeast Marginal Cost Valuation Engine:

    1. CAMBIUM GRID DATA
       - Recursive scanner for NREL Cambium CSV files
       - Supports both raw NREL download format (5-row header) and
         pre-processed simplified format
       - Dynamic column mapping engine (auto-detects energy price and
         carbon emissions columns across NREL naming conventions)
       - Multi-state aggregation and 8760-hour alignment

    2. WEATHER DATA
       - Loads real weather files (.epw or .csv) from Weather_Data_raw/
       - Smart Celsius-vs-Fahrenheit detection
       - Falls back to synthetic temperature profile if no file found
       - Supports Baseline, Extreme Winter, and Extreme Summer cases

    3. CWFT (Capacity Weighting Factor Table)
       - Loads from CSV (validates 8760 rows, CWFT column, sum-to-1)
       - Generates default mock CWFT if file doesn't exist

    4. LOAD PROFILES
       - Loads from CSV (validates 8760 rows, at least one profile column)
       - Generates default mock profiles if file doesn't exist

    5. URDB API
       - Fetches retail tariff structures from NREL OpenEI URDB API

    6. MOCK DATA GENERATORS
       - Synthetic Cambium-like state files for development/testing
       - Synthetic CWFT and load profile generators

WHY IT'S SEPARATE:
    Data ingestion involves file I/O, network calls, and format parsing —
    none of which belongs in the UI layer or the calculation engine.
    Keeping it in its own module means:
    • File format changes don't touch calculation logic
    • New data sources (e.g., diyepw weather) can be added without risk
    • Data loading can be tested independently

USED BY:
    app.py imports these functions and calls them during the sidebar
    configuration phase to load grid data, weather, CWFT, and load profiles
    before passing them to the calculation and billing engines.

NOTE ON STREAMLIT:
    This module is intentionally Streamlit-free. The one place where
    load_custom_weather_file() previously called st.sidebar.error() has
    been changed to return None + print a warning. The UI layer (app.py)
    is responsible for displaying user-facing messages.
"""

import os
import glob
import json
import urllib.request
import numpy as np
import pandas as pd


# ==============================================================================
# CONSTANTS
# ==============================================================================

INPUT_DIRECTORY = "./Cambium_Hourly_Data_raw"


# ==============================================================================
# CWFT (Capacity Weighting Factor Table) — File Generation & Loading
# ==============================================================================

def generate_default_cwft_file(filepath="CWFT.csv"):
    """
    Creates a default 8760-hour Southeast Dual-Peak CWFT CSV if it doesn't exist.

    The default distribution is 45% winter morning risk (hours 6-9, Jan-Feb)
    and 55% summer afternoon risk (hours 14-18, Jun-Sep).

    Returns the filepath (for chaining).
    """
    if not os.path.exists(filepath):
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        cwft = np.zeros(8760)
        winter_hours = []
        summer_hours = []

        for h in range(1, 8761):
            if h <= 1440 and (h % 24 in [6, 7, 8, 9]):
                winter_hours.append(h - 1)
            elif 4345 <= h <= 5832 and (h % 24 in [14, 15, 16, 17, 18]):
                summer_hours.append(h - 1)

        # Distribute risk (45% winter, 55% summer)
        cwft[winter_hours] = 0.45 / len(winter_hours)
        cwft[summer_hours] = 0.55 / len(summer_hours)

        df = pd.DataFrame({
            'Hour': np.arange(1, 8761),
            'CWFT': cwft
        })
        df.to_csv(filepath, index=False)
    return filepath


def load_cwft_from_csv(filepath):
    """
    Load and validate a CWFT CSV file.

    Requirements:
    - Must contain a 'CWFT' column
    - Must have exactly 8760 rows
    - Values are auto-normalized to sum to 1.0 if they don't already

    Returns: np.ndarray of shape (8760,)
    Raises: ValueError on invalid format
    """
    try:
        df = pd.read_csv(filepath)
        if 'CWFT' not in df.columns:
            raise ValueError("The CWFT CSV file must contain a 'CWFT' column.")
        if len(df) != 8760:
            raise ValueError(f"The CWFT file must contain exactly 8760 rows (found {len(df)}).")

        cwft_array = df['CWFT'].to_numpy()
        cwft_sum = cwft_array.sum()
        if not np.isclose(cwft_sum, 1.0, atol=1e-3):
            cwft_array = cwft_array / cwft_sum
        return cwft_array
    except Exception as e:
        raise ValueError(f"Failed to parse CWFT CSV: {str(e)}")


# ==============================================================================
# LOAD PROFILES — File Generation & Loading
# ==============================================================================

def generate_default_load_profiles_file(filepath="load_profiles.csv"):
    """
    Creates a default 8760-hour load profiles CSV with two synthetic profiles:
    - Standard_Heat_Pump_kW: higher peaks (4.5-6.5 kW winter, 2.5-3.5 kW summer)
    - High_Efficiency_Heat_Pump_kW: reduced peaks (2.0-3.2 kW winter, 1.4-2.2 kW summer)

    Returns the filepath (for chaining).
    """
    if not os.path.exists(filepath):
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        hours = np.arange(1, 8761)
        np.random.seed(88)

        std_load = np.random.uniform(0.8, 1.2, 8760)
        he_load = np.random.uniform(0.5, 0.8, 8760)

        for h in hours:
            if h <= 1440 and (h % 24 in [6, 7, 8, 9]):
                std_load[h-1] = np.random.uniform(4.5, 6.5)
                he_load[h-1] = np.random.uniform(2.0, 3.2)
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


def _extract_profile_from_beopt_or_eplus(df, filename_stem):
    """
    Helper to extract total electricity demand/consumption from a BEopt or
    EnergyPlus CSV export file.
    
    Converts Joules [J] -> kW by dividing by 3.6e6.
    """
    elec_col = None
    # 1. Look for known standard output meter names
    for c in df.columns:
        c_upper = str(c).upper()
        if 'ELECTRICITY:UNIT_1' in c_upper or 'ELECTRICITY:FACILITY' in c_upper:
            elec_col = c
            break
            
    # 2. Fallback to fuzzy search
    if not elec_col:
        for c in df.columns:
            c_low = str(c).lower()
            if 'electricity' in c_low and ('unit_1' in c_low or 'facility' in c_low or 'total' in c_low or 'building' in c_low):
                elec_col = c
                break
                
    if elec_col:
        vals = pd.to_numeric(df[elec_col], errors='coerce').to_numpy()
        if len(vals) != 8760:
            vals = np.resize(vals, 8760)
            
        # Unit conversion: Joules [J] to kW (kWh per hour)
        if '[j]' in str(elec_col).lower() or np.nanmean(vals) > 1000.0:
            vals = vals / 3600000.0
        elif '[w]' in str(elec_col).lower():
            vals = vals / 1000.0
            
        col_name = f"{filename_stem}_kW" if not filename_stem.endswith("_kW") else filename_stem
        return col_name, vals
        
    return None, None


def load_load_profiles_from_csv(filepath):
    """
    Load and validate a load profiles file (CSV or Excel) or directory of raw simulation files.

    Supports:
    - Standard simplified CSV or Excel files (with date/time column + profile columns)
    - Multi-case files (e.g. Date + 2 case columns like Total TES and Total No TES)
    - Raw BEopt / EnergyPlus exports (extracts ELECTRICITY:UNIT_1 or
      Electricity:Facility, converts Joules -> kW, auto-generates 8760 hours)
    - Directory path (e.g., 'Load_Profiles_raw/'): scans all CSV/Excel files, extracts
      their load profiles, and merges them into a single 8760-hour DataFrame.

    Returns: pd.DataFrame with 'Hour' + numeric profile columns in kW
    Raises: ValueError on invalid format
    """
    try:
        # If filepath is a directory, load all CSV and Excel files in that directory
        if os.path.isdir(filepath):
            files = []
            for ext in ["*.csv", "*.xlsx", "*.xls"]:
                files.extend(glob.glob(os.path.join(filepath, ext)))
            # Filter out temporary office lock files starting with ~$
            files = [f for f in files if not os.path.basename(f).startswith("~$")]
            if not files:
                raise ValueError(f"No load profile CSV or Excel files found in directory '{filepath}'")
            
            merged_dict = {'Hour': np.arange(1, 8761)}
            for fp in sorted(files):
                stem = os.path.splitext(os.path.basename(fp))[0]
                sub_df = _read_profile_file(fp)
                
                # Check if it's a BEopt or EnergyPlus output export
                is_beopt_eplus = ('Date/Time' in sub_df.columns or any(':' in str(c) for c in sub_df.columns))
                
                if is_beopt_eplus:
                    col_name, vals = _extract_profile_from_beopt_or_eplus(sub_df, stem)
                    if vals is not None:
                        col_key = col_name if col_name not in merged_dict else f"{stem} - {col_name}"
                        merged_dict[col_key] = vals
                else:
                    # Filter out date/time columns
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

        # Otherwise, process single file
        df = _read_profile_file(filepath)
        stem = os.path.splitext(os.path.basename(filepath))[0]
        
        # Check if this is a BEopt or EnergyPlus output export
        is_beopt_eplus = ('Date/Time' in df.columns or any(':' in str(c) for c in df.columns))
        
        if is_beopt_eplus:
            col_name, vals = _extract_profile_from_beopt_or_eplus(df, stem)
            if vals is not None:
                return pd.DataFrame({
                    'Hour': np.arange(1, 8761),
                    col_name: vals
                })
            else:
                raise ValueError(f"Could not find an electricity/facility load column in '{filepath}'")

        # Identify profile columns (exclude date/time/hour index columns)
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


# ==============================================================================
# MOCK CAMBIUM STATE DATA GENERATOR
# ==============================================================================

def generate_mock_state_file(filepath, state_code, scenario):
    """
    Generates a synthetic 8760-hour Cambium-like CSV for development/testing.

    Simulates the dual-peaking load pattern of the Southeastern US:
    - Winter morning peaks (hours 6-9, Jan-Feb)
    - Summer afternoon peaks (hours 14-18, Jun-Sep)

    Scenario-dependent price/carbon ranges:
    - HighDemandGrowth: highest prices and carbon
    - LowCarbonConstraint: lower carbon, moderate prices
    - LowDemandGrowth: lowest prices
    - MidCase (default): moderate across the board
    """
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

    # Outputs raw NREL Cambium column headers
    df = pd.DataFrame({
        'Hour': hours,
        'State': state_code,
        'Scenario': scenario,
        'lmp_energy': energy_base,
        'co2_combust': carbon_base
    })

    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    df.to_csv(filepath, index=False)


# ==============================================================================
# CAMBIUM DATA INGESTION PIPELINE
# ==============================================================================

def file_matches_scenario(filepath, scenario):
    """Check if a simplified-format CSV matches the selected scenario."""
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


def parse_cambium_columns(df):
    """
    NREL Cambium Column Mapping Engine.

    Dynamically maps column names from various Cambium CSV formats to
    the standardized names used internally:
    - Energy price → 'Cambium_Energy_MWh'
    - Carbon emissions → 'Cambium_Carbon_kg_MWh'
    - Hour index → 'Hour'

    Handles exact matches first, then falls back to fuzzy keyword matching.

    Returns: (hour_col, energy_col, carbon_col) — each is a string or None
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

    # Intelligent fallbacks
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
    Load a real weather file (.epw or .csv) from Weather_Data_raw/<case_folder>/.

    Searches for .epw files first, then .csv. For EPW files, reads dry-bulb
    temperature from column index 6 (after 8 header lines) and converts
    Celsius → Fahrenheit. For CSV files, auto-detects a temperature column
    by name, with a smart C-vs-F heuristic (if max < 50, assumes Celsius).

    Parameters
    ----------
    weather_case : str
        One of: "2012 (Cambium-aligned baseline)", "Extreme Winter", "Extreme Summer"

    Returns
    -------
    np.ndarray or None
        8760-element array of temperatures in Fahrenheit, or None if no file found.
    """
    case_folder_map = {
        "2012 (Cambium-aligned baseline)": "Baseline",
        "Extreme Winter": "Extreme_Winter",
        "Extreme Summer": "Extreme_Summer"
    }
    folder_name = case_folder_map.get(weather_case, "Baseline")
    target_dir = os.path.join("Weather_Data_raw", folder_name)
    os.makedirs(target_dir, exist_ok=True)

    # Search for .epw or .csv files
    files = []
    for ext in ["*.epw", "*.csv"]:
        files.extend(glob.glob(os.path.join(target_dir, ext)))

    if not files:
        return None

    file_path = files[0]  # Take the first matched file
    try:
        if file_path.lower().endswith(".epw"):
            # EPW files have 8 header lines, then 8760 data lines.
            # Temperature is column index 6 (0-indexed), in Celsius.
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            data_lines = lines[8:]
            if len(data_lines) != 8760:
                data_lines = data_lines[:8760]

            temps_c = []
            for line in data_lines:
                parts = line.split(',')
                if len(parts) > 6:
                    temps_c.append(float(parts[6]))
                else:
                    temps_c.append(0.0)

            temps_c = np.array(temps_c)
            # Convert to Fahrenheit
            temps_f = temps_c * 1.8 + 32.0
            return temps_f

        elif file_path.lower().endswith(".csv"):
            df = pd.read_csv(file_path)
            # Try to find a temperature column
            temp_col = None
            for col in df.columns:
                if any(x in col.lower() for x in ["temperature", "temp", "drybulb", "dry_bulb", "db_temp"]):
                    temp_col = col
                    break
            if temp_col is None:
                # If no clear header, take the first numeric column that isn't Hour
                numeric_cols = [c for c in df.select_dtypes(include=[np.number]).columns if c.lower() not in ["hour", "hour_index", "datetime"]]
                if numeric_cols:
                    temp_col = numeric_cols[0]

            if temp_col:
                temps = df[temp_col].to_numpy()
                if len(temps) != 8760:
                    temps = np.resize(temps, 8760)
                # Smart heuristic: Celsius vs Fahrenheit check
                # If max temp is < 50, assume Celsius and convert
                if np.nanmax(temps) < 50.0:
                    temps = temps * 1.8 + 32.0
                return temps
    except Exception as e:
        # Note: previously this called st.sidebar.error(). Now it prints
        # a warning and returns None; the UI layer handles user messaging.
        print(f"Warning: Error loading weather file {os.path.basename(file_path)}: {str(e)}")

    return None


def load_and_aggregate_data(target_states, selected_scenario, weather_case, target_year="2026", planning_year="2040", input_directory=INPUT_DIRECTORY):
    """
    Main data ingestion pipeline: load, map, aggregate, and weather-inject.

    This is the primary entry point for loading grid data. It:
    1. Recursively scans Cambium_Hourly_Data_raw/ for matching CSV files
    2. Dynamically maps NREL column names to internal names
    3. Aggregates hourly data across states (mean of energy price + carbon)
    4. Generates the 8760-hour datetime series (aligned to target_year)
    5. Computes PCAF weights (top 100 price hours)
    6. Injects weather profile (real file or synthetic)
    7. Applies weather-case-specific price and CWFT adjustments

    Parameters
    ----------
    target_states : list of str
        State codes to include (e.g., ["AL", "GA"])
    selected_scenario : str
        NREL scenario name (e.g., "MidCase", "HighDemandGrowth")
    weather_case : str
        Weather scenario for temperature/price adjustments
    target_year : str
        Calendar year for datetime alignment (default "2026")
    planning_year : str
        NREL planning horizon year (default "2040")
    input_directory : str
        Path to Cambium CSV directory (default "./Cambium_Hourly_Data_raw")

    Returns
    -------
    pd.DataFrame
        8760-row DataFrame with columns: Hour, Datetime, Cambium_Energy_MWh,
        Cambium_Carbon_kg_MWh, PCAF_Weight, Temperature_F, CWFT_derived,
        Mapped_Energy_Col, Mapped_Carbon_Col
    """
    os.makedirs(input_directory, exist_ok=True)

    # Track which states we successfully loaded from real data
    loaded_states = set()
    combined_list = []
    mapped_energy_col = None
    mapped_carbon_col = None

    # 1. Search recursively under the raw Cambium directory for all .csv files
    all_csv_files = []
    for root, dirs, files in os.walk(input_directory):
        if any(x in root for x in ["__pycache__"]):
            continue
        for file in files:
            if file.lower().endswith(".csv"):
                all_csv_files.append(os.path.join(root, file))

    for file in all_csv_files:
        try:
            # Check if this is a raw NREL Cambium file
            first_row_df = pd.read_csv(file, nrows=0)
            cols = [c.lower() for c in first_row_df.columns]

            is_raw_nrel = 'project' in cols and 'scenario' in cols and ('state' in cols or 'r' in cols)

            if is_raw_nrel:
                # Read metadata from row index 1
                meta_df = pd.read_csv(file, nrows=1)
                file_state = str(meta_df['state'].iloc[0]).upper() if 'state' in meta_df.columns else ""
                file_scenario = str(meta_df['Scenario'].iloc[0]).lower() if 'Scenario' in meta_df.columns else ""
                file_year = str(meta_df['t'].iloc[0]) if 't' in meta_df.columns else ""

                # Check if file matches selected scenario, state, and planning year
                if (file_scenario == selected_scenario.lower() and
                    file_state in [s.upper() for s in target_states] and
                    file_year == str(planning_year)):

                    # Read the hourly data (header is at row index 5)
                    temp_df = pd.read_csv(file, header=5)
                    temp_df['State'] = file_state
                    temp_df['Scenario'] = selected_scenario
                    temp_df['Hour'] = np.arange(1, 8761)

                    loaded_states.add(file_state)
                    filtered_df = temp_df
                else:
                    continue
            else:
                # Processed simplified format file
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
                # Dynamically map headers
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
                    raise ValueError(f"Could not map wholesale energy price in {file}. Found: {list(filtered_df.columns)}")
                if 'Cambium_Carbon_kg_MWh' not in filtered_df.columns:
                    raise ValueError(f"Could not map emissions rates in {file}. Found: {list(filtered_df.columns)}")

                combined_list.append(filtered_df[['Hour', 'Cambium_Energy_MWh', 'Cambium_Carbon_kg_MWh', 'State']])

        except Exception as e:
            # Silently pass for other files
            pass

    # Ensure all requested states were successfully loaded from real files
    missing_states = [s for s in target_states if s.upper() not in loaded_states]
    if missing_states:
        raise FileNotFoundError(
            f"Missing Cambium grid data for state(s): {', '.join(missing_states)} "
            f"(Scenario: {selected_scenario} | Year: {planning_year}). "
            "Please download the raw NREL CSV files and place them in the 'Cambium_Hourly_Data_raw' directory."
        )

    if not combined_list:
        raise ValueError(f"No source data matched scenario ({selected_scenario}), year ({planning_year}), and states: {target_states}")

    raw_regional_df = pd.concat(combined_list, ignore_index=True)

    regional_base = raw_regional_df.groupby('Hour').agg({
        'Cambium_Energy_MWh': 'mean',
        'Cambium_Carbon_kg_MWh': 'mean'
    }).reset_index()

    # Standard 8760-hour generation, aligned to the target year
    date_range = pd.date_range(start=f"{target_year}-01-01 00:00:00", periods=8760, freq="h")
    regional_base['Datetime'] = date_range

    # Peak Capacity Allocation Factor (PCAF) for localized T&D stress (top 100 grid hours)
    top_100_cutoff = regional_base['Cambium_Energy_MWh'].nlargest(100).min()
    regional_base['PCAF_Weight'] = 0.0
    is_peak_hour = regional_base['Cambium_Energy_MWh'] >= top_100_cutoff
    regional_base.loc[is_peak_hour, 'PCAF_Weight'] = 1.0 / is_peak_hour.sum()

    assert np.isclose(regional_base['PCAF_Weight'].sum(), 1.0), "PCAF values must sum to 1.0"

    # --------------------------------------------------------------------------
    # Weather Profile & Temperature Generation
    # --------------------------------------------------------------------------
    hours = regional_base['Hour'].to_numpy()
    np.random.seed(42)

    # Try to load custom weather file (.epw or .csv) from Weather_Data_raw/
    custom_temp = load_custom_weather_file(weather_case)

    if custom_temp is not None:
        temperature = custom_temp
    else:
        # Fall back to synthetic profile
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

    if weather_case == "Extreme Winter":
        if custom_temp is None:
            cold_snap_mask = (hours >= 120) & (hours <= 180)
            temperature[cold_snap_mask] -= 22.0

        winter_morning_mask = (hours <= 1440) & (np.isin(hours % 24, [6, 7, 8, 9]))
        energy_price[winter_morning_mask] *= np.random.uniform(2.2, 3.5, size=winter_morning_mask.sum())

        if custom_temp is None:
            energy_price[cold_snap_mask & (np.isin(hours % 24, [6, 7, 8, 9]))] *= 2.0

        cwft_derived[winter_hours] = 0.80 / len(winter_hours)
        cwft_derived[summer_hours] = 0.20 / len(summer_hours)

    elif weather_case == "Extreme Summer":
        if custom_temp is None:
            heatwave_mask = (hours >= 4800) & (hours <= 4860)
            temperature[heatwave_mask] += 10.0

        summer_afternoon_mask = (hours >= 4345) & (hours <= 5832) & (np.isin(hours % 24, [14, 15, 16, 17, 18]))
        energy_price[summer_afternoon_mask] *= np.random.uniform(2.2, 3.5, size=summer_afternoon_mask.sum())

        if custom_temp is None:
            energy_price[heatwave_mask & (np.isin(hours % 24, [14, 15, 16, 17, 18]))] *= 2.0

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


# ==============================================================================
# URDB API — Tariff Fetch
# ==============================================================================

def fetch_urdb_rate(rate_label, api_key="DEMO_KEY"):
    """
    Fetch a retail tariff structure from the NREL OpenEI URDB API.

    Parameters
    ----------
    rate_label : str
        OpenEI unique tariff label (e.g., "5d4b00595457a3e73a0e6988")
    api_key : str
        NREL API key (default "DEMO_KEY" for development)

    Returns
    -------
    dict
        URDB V3 rate structure JSON

    Raises
    ------
    ValueError: if no rate matches the label
    ConnectionError: if the API request fails
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
