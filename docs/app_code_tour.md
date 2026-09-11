# ⚡ Deep Code Tour: Southeast Marginal Cost Valuation Engine

Welcome! This guide is written specifically for **non-coders, energy analysts, policy managers, and relative programming beginners**. It breaks down line-by-line and section-by-section what is happening under the hood of the Southeast Marginal Cost Valuation Engine.

The application is structured into **6 modular Python files** to ensure clean separation of calculation logic, data ingestion, billing, chart building, configuration, and Streamlit user interface:

| Module | Role & Purpose |
|--------|----------------|
| **`app.py`** (~1,660 lines) | Streamlit web application layout, sidebar controls, dashboard tabs, and orchestration. |
| **`calculations.py`** (~670 lines) | Pure-Python calculation engine: 5-component avoided costs, Southeast Next Planned Peaker carrying cost / regulated FCR, dual-peak CWF allocation, LOLP proxies, feeder PCAF, DR dispatch, and SPM/payback math. |
| **`billing.py`** (~270 lines) | URDB V3 retail electricity billing engine and pre-packaged tariff schedules (Georgia Power R-31, Alabama Power Rate FD). |
| **`data_loaders.py`** (~825 lines) | Data ingestion pipeline: NREL Cambium CSV scanner, raw BEopt/EnergyPlus load profile parser (including BEopt's native `wxDVFileHeaderVer` hourly export format), weather EPW loader, CWFT loader, URDB API client. |
| **`visualizations.py`** (~780 lines) | Streamlit-free Plotly chart builder functions (10 chart types) returning interactive `go.Figure` objects for all dashboard tabs. |
| **`config.py`** (~480 lines) | Central configuration: sidebar defaults, Southeast peaker & T&D presets, option lists, the `EXAMPLE_BUILDINGS` library, color palettes, and CSS styling. |

> **Note:** Updated 2026-09-10 with Southeast utility capacity, dual-peak CWF, and feeder T&D engine additions.

---

## 🧭 Table of Contents
1. [Core Concepts & Glossary](#1-core-concepts--glossary)
2. [Module 1: `config.py` — Central Defaults & Styling](#module-1-configpy--central-defaults--styling)
3. [Module 2: `data_loaders.py` — Grid, Weather & BEopt Ingestion](#module-2-data_loaderspy--grid-weather--beopt-ingestion)
4. [Module 3: `calculations.py` — Wholesale Avoided Costs & SPM Tests](#module-3-calculationspy--wholesale-avoided-costs--spm-tests)
5. [Module 4: `billing.py` — Retail Tariffs & URDB Billing Engine](#module-4-billingpy--retail-tariffs--urdb-billing-engine)
6. [Module 5: `visualizations.py` — Interactive Plotly Charts](#module-5-visualizationspy--interactive-plotly-charts)
7. [Module 6: `app.py` — Sidebar Controls & Dashboard Tabs](#module-6-apppy--sidebar-controls--dashboard-tabs)

---

## 1. Core Concepts & Glossary

Before diving into the code, here are a few key building blocks:

*   **Python**: The programming language executing our math, data sorting, and web presentation.
*   **Streamlit (`st`)**: A Python library that automatically transforms Python scripts into interactive web applications. Whenever you see `st.title`, `st.sidebar`, `st.metric`, or `st.selectbox`, Streamlit is drawing a visual web component on screen.
*   **Pandas (`pd`) & DataFrames**: Think of a DataFrame as an **Excel spreadsheet inside Python**. It holds rows and columns of data (like 8,760 hourly rows for a full year).
*   **NumPy (`np`)**: A hyper-fast math library. It performs matrix and vector operations across thousands of numbers instantly (e.g., multiplying 8,760 hourly load values by hourly prices in microseconds).
*   **8760 Hourly Data**: An electricity standard representing every hour of a non-leap year ($24 \text{ hours/day} \times 365 \text{ days} = 8,760 \text{ hours}$).
*   **CWFT (Capacity Worth Factor Table)**: An 8,760-hour profile of weights (summing to $1.0$) that distributes fixed annual generation capacity risk across hours of grid stress (winter cold snaps and summer heatwaves).
*   **PCAF (Peak Capacity Allocation Factor)**: Allocates localized Transmission & Distribution (T&D) deferral costs across the top grid stress hours.
*   **URDB (Utility Rate Database)**: NREL's standardized JSON schema for describing complex retail electricity tariffs (fixed monthly fees, volumetric energy tiers, seasonal peak demand charges).
*   **RIM Ratio (Ratepayer Impact Measure)**: Measures program cost-effectiveness from non-participating customers' perspective:
    $$\text{RIM Ratio} = \frac{\text{Net Present Value of Wholesale Grid Savings}}{\text{Net Present Value of Retail Lost Revenue}}$$
    A ratio $> 1.0$ means grid savings exceed lost utility revenue, putting downward pressure on customer rates.

---

> **File map for Chapters 1–6:** After modularization, the code these chapters describe
> no longer all lives in `app.py`. Chapter 1 is still `app.py` (imports + page setup);
> Chapter 2's rate dictionaries and Chapter 5's billing engine are in `billing.py`;
> Chapter 3's mock generators and Chapter 4's data/weather loading are in
> `data_loaders.py`; Chapter 4's avoided-cost formula and Chapter 5's DR dispatch are in
> `calculations.py`; Chapter 6 (the `diyepw` weather generator UI) is still inline in
> `app.py`. Line numbers below are approximate per-file, not a single continuous range.

## Chapter 1: Imports & UI Setup — `app.py` (Lines ~1–55)

### What the Code Does
This section loads essential software toolkits (libraries) into memory and sets up the browser tab title. Custom CSS styling (`CUSTOM_CSS`) now lives in `config.py` and is imported and applied with `st.markdown(CUSTOM_CSS, unsafe_allow_html=True)`.

```python
import os
import glob
import json
import urllib.request
import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
```

*   **`os` & `glob`**: Operating system tools used to find files on your computer (e.g., searching folders for `.csv` or `.epw` weather files).
*   **`json`**: Translates text blocks in JavaScript Object Notation (JSON) format into Python dictionaries.
*   **`urllib.request`**: A web browser built into Python. It makes HTTP calls to fetch live tariffs from NREL's OpenEI API over the internet.
*   **`plotly.graph_objects` (`go`)**: Interactive plotting engine used to build hovering charts, stacked area plots, and secondary-axis graphs.

### Page Aesthetics & Styling
```python
st.set_page_config(
    page_title="Southeast Marginal Cost Valuation Engine",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)
```
This tells Streamlit to use the full horizontal width of your monitor (`layout="wide"`) and name the web browser tab "Southeast Marginal Cost Valuation Engine".

Lines 22–79 inject custom **CSS (Cascading Style Sheets)** to give metric cards rounded corners, drop shadows, hover animations, and color-coded status badges (`.badge-success`, `.badge-warning`, `.badge-danger`).

---

## Chapter 2: Utility Rate Structures (URDB) — `billing.py`

### What the Code Does
Defines exact pre-packaged residential retail tariffs for Georgia Power and Alabama Power as structured Python dictionaries.

```python
GP_R31_URDB = {
    "name": "Georgia Power - Schedule R-31 (Residential)",
    "fixedcharge": 16.48, # includes riders: $14.00/mo base * 1.177209 rider multiplier
    "energyratewindow": [
        [0]*24, [0]*24, [0]*24, [0]*24, [0]*24, # Jan - May (Winter = Period 0)
        [1]*24, [1]*24, [1]*24, [1]*24,         # Jun - Sep (Summer = Period 1)
        [0]*24, [0]*24, [0]*24                  # Oct - Dec (Winter = Period 0)
    ],
    ...
}
```

### Explanation for Non-Coders
*   `fixedcharge`: Customer base fee billed every month ($16.48/month for Georgia Power R-31 after rider multipliers).
*   `energyratewindow`: A 12-month by 24-hour grid matrix mapping every hour of the year to a season/period index:
    *   `Period 0` = Winter (Jan–May & Oct–Dec). Flat rate of ~$0.142062/kWh.
    *   `Period 1` = Summer (Jun–Sep). Billed in 3 consumption tiers (Tier 1 up to 650 kWh at ~$0.148/kWh; Tier 2 next 350 kWh at ~$0.216/kWh; Tier 3 above 1000 kWh at ~$0.222/kWh).

---

## Chapter 3: Mock Data Generators & File Handlers — `data_loaders.py`

### What the Code Does
Acts as a safety net. If you launch the tool without providing your own CSV files, these functions automatically generate sample 8,760-hour files so the web app can run immediately without crashing.

1.  `generate_default_cwft_file()`:
    Creates a `CWFT.csv` file representing a classic Southeastern dual-peak risk shape:
    *   **Winter Morning Peak (45% of annual risk)**: Distributes weight during winter morning heating hours (6:00 AM – 9:00 AM in Jan–Feb).
    *   **Summer Afternoon Peak (55% of annual risk)**: Distributes weight during hot summer afternoon cooling hours (2:00 PM – 6:00 PM in Jun–Sep).
2.  `generate_default_load_profiles_file()`:
    Creates synthetic hourly kW profiles for two building systems:
    *   `Standard_Heat_Pump_kW`: Higher electricity spikes during freezing winter mornings.
    *   `High_Efficiency_Heat_Pump_kW`: Lower peak spikes due to variable-speed compressor technology.
3.  `generate_mock_state_file()`:
    Simulates NREL Cambium wholesale grid files (hourly LMP energy prices in $/MWh and carbon intensity in kg/MWh).

`_read_profile_file()` (used by the real load-profile loader, not a mock generator) also
knows how to parse **two different real-world export formats**, auto-detected by file
signature: the EnergyPlus-style export (`Date/Time` column or `Electricity:Facility`-type
headers), and — added 2026-08-26 — BEopt's *native* hourly CSV export (a
`wxDVFileHeaderVer.1` version line, then headers, then two index rows and a units row
before the 8,760 data rows). This second format was needed for the battery-storage
example building, whose files come straight from BEopt rather than an EnergyPlus export.

---

## Chapter 4: Data Processing & Valuation Pipeline — `data_loaders.py` (ingestion) + `calculations.py` (avoided costs)

This is the mathematical core of the application.

### 1. Dynamic Column Mapper (`parse_cambium_columns`)
Raw CSV files from NREL Cambium or utility models often use slightly different column header names. This function scans column titles and automatically maps them:
*   `lmp_energy`, `marginal_cost_energy`, or `Cambium_Energy_MWh` $\rightarrow$ Wholesale Energy Price
*   `co2_combust`, `marginal_co2_combust`, or `Cambium_Carbon_kg_MWh` $\rightarrow$ Grid Carbon Intensity

### 2. Weather EPW Loader (`load_custom_weather_file`)
Parses `.epw` (EnergyPlus Weather) or `.csv` files from the `Weather_Data_raw/` directory. It reads 8,760 dry-bulb temperature values, converts Celsius to Fahrenheit if needed ($^\circ\text{F} = ^\circ\text{C} \times 1.8 + 32$), and passes them to the simulation.

### 3. Ingestion & Aggregation (`load_and_aggregate_data`)
Decorated with `@st.cache_data` so Python caches heavy data loading operations in memory, making button clicks instantaneous.
*   **State Averaging**: If multiple states are selected (e.g., AL and GA), it computes the hourly average wholesale energy price and emissions across those regions.
*   **PCAF Stress Allocator**: Identifies the top 100 highest grid energy price hours of the year and assigns equal weight to them ($1/100 = 0.01$), ensuring T&D deferral costs are only allocated during severe grid congestion.
*   **Weather Shifting Engine**: If "Extreme Winter" or "Extreme Summer" is selected, it dynamically depresses temperatures and scales up wholesale prices during peak hours.

### 4. Wholesale Avoided Cost Engine (`calculate_avoided_costs`)
Calculates the hourly total wholesale cost of electricity ($\text{Total Avoided Cost in } \$/\text{MWh}$) by summing 5 distinct components:

$$\text{Total Avoided Cost} = \text{Wholesale Energy} + \text{Gen Capacity} + \text{Transmission} + \text{Distribution} + \text{Emissions}$$

1.  **Wholesale Energy**: Hourly Cambium price ($/\text{MWh}$).
2.  **Generation Capacity**: $\text{Capacity Scalar } (\$/\text{kW-yr}) \times \text{CWFT Weight} \times 1000$.
3.  **Transmission Deferral**: $\text{Transmission Scalar } (\$/\text{kW-yr}) \times \text{PCAF Weight} \times 1000$.
4.  **Distribution Deferral**: $\text{Distribution Scalar } (\$/\text{kW-yr}) \times \text{PCAF Weight} \times 1000$.
5.  **Emissions Value**: $(\text{Grid Carbon Intensity in kg/MWh} / 1000) \times \text{Carbon Penalty } (\$/\text{metric ton})$.

---

## Chapter 5: The Retail Bill Calculation Engine — `billing.py` (bill) + `calculations.py` (DR dispatch)

### How `calculate_urdb_bill()` Works
To compute utility "Lost Revenue", we must calculate what a customer would pay under their retail rate schedule before and after installing efficient equipment.

```python
def calculate_urdb_bill(load_kw, datetime_series, rate_json):
```

The function steps month-by-month ($m = 1 \dots 12$):
1.  **Fixed Charge**: Adds monthly base fee (`fixedcharge`).
2.  **Energy Charge**: Checks day of week (weekday vs. weekend) and hour to find the active rate period index. Accumulates total monthly kWh per period, then runs them through tiered block structures.
3.  **Demand Charge**: Finds the single highest peak demand ($\text{kW}$) established during peak window hours for that month and applies peak demand charges ($\$/\text{kW}$).

### Demand Response Dispatch (`dispatch_dr_program`)
Simulates a smart grid Demand Response program:
*   Identifies the top $N$ grid stress hours (ranked by highest CWFT weights).
*   Enforces daily call limits (e.g., max 4 hours per day).
*   Curtails building load by `dr_capacity_kw` during those hours.

---

## Chapter 6: Weather File Generator (`diyepw`) — `app.py`, Setup & Calibration Guide tab (~lines 155–225)

Interfaces with Pacific Northwest National Laboratory's (PNNL) `diyepw` Python tool.
*   Takes a 6-digit NOAA WMO Station ID (e.g., `722300` for Birmingham, AL or `722190` for Atlanta, GA) and an observation year (2010–2024).
*   Downloads raw NOAA ISD weather data, fills missing weather gaps using NREL TMY3 templates, and saves a ready-to-use `.epw` weather file into `Weather_Data_raw/`.

---

## Chapter 7: Sidebar Controls & Inputs (~lines 260–580, approximate)

> **Updated 2026-08-18:** The sidebar was reorganized into seven collapsible
> `st.sidebar.expander(...)` sections (previously a flat list of markdown headers).
> Line numbers below are approximate and will drift as the file changes.

*   **Grid Scenario & Region** *(expanded by default)*: NREL Cambium grid projection (HighDemandGrowth, MidCase, LowCarbonConstraint, LowDemandGrowth), planning horizon (2025–2050), weather case, and target Southeast states (AL, GA, FL, TN, MS, NC, SC).
*   **Demand Response (Optional)** *(collapsed by default)*: DR mode toggle plus hours/season/max-hours-per-day/capacity inputs.
*   **Building / Technology & Load Data** *(expanded by default)*: Describes the technology/measure being evaluated and is where the 8760-hour load data comes in. Includes the new **Example Building Library** picker (select a pre-configured example instead of your own data — see Chapter 8 note below) and, when no example is selected, the original Load Profiles Source picker (folder / synthetic / custom path) plus baseline/proposed column selection. Weather Alignment Metadata (load/Cambium/CWFT weather years) now lives at the bottom of this same section, and is auto-locked (disabled, pre-filled) when an example is selected.
*   **Grid Valuation Assumptions** *(collapsed by default)*: Generation Capacity ($/kW-yr), Transmission Deferral ($/kW-yr), Distribution Deferral ($/kW-yr), and Carbon Penalty ($/ton).
*   **Retail Tariff (NREL URDB)** *(expanded by default)*: Tariff type, retail escalation rate, and URDB fetch/paste/custom-flat-rate controls.
*   **Financial Assumptions** *(collapsed by default)*: Merges the former "Asset Lifetime & NPV" (asset life, discount rate, escalation, degradation) and "Measure & Program Costs" (gross measure cost, utility incentive, admin cost) into one section.
*   **Advanced: Custom Data Files** *(collapsed by default)*: Optional custom CWFT file path.

---

## Chapter 8: Results Engine & Dashboard Tabs (~lines 580–1500, approximate)

When the user clicks **Run Valuation Engine**, the app executes financial calculations and populates 7 organized dashboard tabs (consolidated from 9 on 2026-08-18).

### Key Math Performed in the Dashboard
1.  **EPC (Effective Peak Contribution)**:
    $$\text{EPC (kW)} = \sum_{h=1}^{8760} (\text{Hourly Load Reduction}_h \times \text{CWFT}_h)$$
    This single metric drives $100\%$ of the Generation Capacity deferral savings value!
2.  **ELCC Proxy (Effective Load Carrying Capability)**:
    $$\text{ELCC Proxy (\%)} = \frac{\text{EPC (kW)}}{\text{Peak Baseline Load (kW)}}$$
3.  **Multi-Year Cash Flow Discounting**:
    Applies discount factors $1 / (1 + r)^t$, price escalation $(1 + e)^t$, and annual heat pump efficiency degradation $(1 - d)^t$ over the asset lifetime (e.g., 15 years) to compute Net Present Value (NPV).

### The 7 Tab Views
1.  **Setup & Calibration Guide**: EPW/weather alignment best practices for matching EnergyPlus building simulations to Cambium grid datasets, plus the in-app AMY Weather Generator (`diyepw`). Placed first since these are setup-stage tools, not results.
2.  **Overview Scorecard**: Top-level KPI metrics (Net NPV, RIM Ratio, Grid Savings, Customer Bill Savings, EPC Reduction), temperature responsiveness checks, and the TRC/PCT/RIM ratio cards (now rendered via the shared `ratio_card_html()` helper in `config.py` for a consistent style).
3.  **Cost-Effectiveness Table**: Side-by-side cost-effectiveness comparison table (wholesale grid savings vs. retail lost revenue vs. RIM ratio).
4.  **Charts**: All chart/plot content consolidated into one tab with three logical groups: **Overall Scorecard** (lifetime discounted cash flow chart), **Utility Cost Tests** (annual wholesale avoided cost distribution, winter/summer stacked component charts, weekly grid economics chart), and **Customer & Building Load** (weekly building demand vs. outdoor temperature chart).
5.  **Weather & Peak Diagnostics**: Statistical correlations, temperature extremes, and a peak coincidence table showing peak-to-average demand ratios (top 50/100 CWFT hours and top 100 price hours) with hover tooltips explaining each formula, plus EPC and ELCC proxy.
6.  **Scenario Manager**: Save runs and compare scenarios side-by-side in a table (the lifetime NPV chart itself moved to the Charts tab).
7.  **Diagnostics & Top Hours**: Validation checks and the capacity avoided-cost math trace are now tucked into a collapsed expander at the top; the Top Stress Hours table + CSV export is the main visible content.

### Example Building Library (introduced 2026-08-18, expanded 2026-08-26)
The sidebar's Building/Technology section includes a pre-configured example picker (`EXAMPLE_BUILDINGS` in `config.py`), currently with two entries — both Birmingham, AL, BEopt, 2012 weather year:
1.  Electric Resistance Heat (Baseline) vs. Heat Pump (Proposed)
2.  No Battery (Baseline) vs. 10 kWh Battery (Proposed) — seasonal charge/discharge strategy (winter: charge 12PM–4PM / discharge 5AM–9AM; summer: charge 2AM–6AM / discharge 4PM–8PM)

Selecting an example auto-loads its baseline/proposed load columns and locks the Weather Alignment Metadata to the example's documented weather year. Current scope is **pick-and-view only** — editing an example via a what-if explorer is planned for later (see `docs/roadmap.md` §4.2).

---
*Generated for the Southeast Marginal Cost Valuation Engine. Designed for clear, transparent energy modeling.*
