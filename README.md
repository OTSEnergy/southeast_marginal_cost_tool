# Marginal Cost & Retail Savings Valuation Tool

A rigorous, 8760-hourly marginal cost energy valuation application built with Python and Streamlit. This tool enables users to analyze utility avoided costs (generation capacity, transmission & distribution, carbon/emissions, energy) and calculate customer bill savings under different rate structures.

---

## 🚀 Getting Started

Follow these steps to set up and run the application locally:

### 1. Create a Python Virtual Environment
Navigate to your project directory and create a virtual environment (`venv`):
```bash
python -m venv venv
```

### 2. Activate the Virtual Environment
Activate the environment based on your operating system:
* **Windows (PowerShell)**:
  ```powershell
  .\venv\Scripts\Activate.ps1
  ```
* **Windows (Command Prompt)**:
  ```cmd
  .\venv\Scripts\activate.bat
  ```
* **Mac / Linux**:
  ```bash
  source venv/bin/activate
  ```

### 3. Install Dependencies
Install all required packages from `requirements.txt`:
```bash
pip install -r requirements.txt
```

### 4. Run the Application
Launch the Streamlit dashboard in your web browser:
```bash
streamlit run app.py
```

---

## 📊 Energy & Avoided Cost Datasets

### Current Coverage
This repository includes processed baseline datasets preloaded under the `cambium_data/` directory. Currently, it supports:
* **Alabama (AL)** (Midcase & High Demand Growth scenarios)
* **Georgia (GA)** (Midcase & High Demand Growth scenarios)

### Expanding to Other Regions (Full NREL Cambium Data)
To evaluate projects in states or balancing authorities outside of Alabama and Georgia, users must download the raw Cambium datasets from the official NREL sources:

1. **Visit the NREL Scenario Viewer**:  
   Download datasets directly from [NREL Scenario Viewer](https://scenarioviewer.nlr.gov/).
2. **Additional Information**:  
   Read more about the methodology, metrics, and scenario assumptions on the [NREL Cambium Homepage](https://www.nlr.gov/analysis/cambium).

#### Ingesting New Data:
The tool is built to dynamically pull, parse, and aggregate raw Cambium datasets recursively. You do **not** need to manually rename, preprocess, or format individual files. 

To evaluate other regions or scenarios, download any of NREL's hourly scenario datasets from the Scenario Viewer and **paste the raw CSV files directly into the `Cambium_Hourly_Data_raw/` directory** at the root of the project.

The application's ingestion engine will automatically:
1. **Recursive Scan**: Recursively scan the `Cambium_Hourly_Data_raw/` directory for all `.csv` files.
2. **Metadata Audit**: For each file, look at the NREL-standard first two lines to extract the file's static state, scenario, and year information.
3. **Filter and Aggregate**: Filter for files matching your sidebar selections:
   * **NREL Future Scenario** (e.g., `HighDemandGrowth`)
   * **NREL Planning Year** (2025, 2030, 2035, 2040, 2045, or 2050)
   * **Target States** (e.g., `AL`, `GA`, etc.)
4. **Multi-row Skip & Map**: Skip the first 5 metadata/description rows of raw files to load the actual hourly 8760 data, and auto-resolve column headers using an intelligent variable mapping engine (mapping energy price columns like `energy_cost_busbar` or `energy_cost_enduse` and emission columns like `lrmer_co2_c`).



> [!WARNING]
> **Capacity Worth Factor Table (CWFT) Data:**  
> The provided `CWFT.csv` file in this repository is currently a **mocked placeholder** and does not reflect realistic utility peak risk conditions. It should **not** be used for final engineering or economic evaluations. Users must replace it with a valid, region-specific Capacity Worth Factor dataset.

---

## 📂 Project Structure

The app is split into `app.py` (Streamlit UI/orchestration only) plus five pure-Python modules with no Streamlit dependency, so they can be tested standalone:

- `app.py`: Streamlit page layout, sidebar controls, and the 7 dashboard tabs. Calls into the modules below rather than containing the calculation/ingestion logic itself.
- `calculations.py`: Avoided-cost engine (5 components), Demand Response dispatch, EPC/ELCC capacity metrics, and the TRC/PCT/RIM/payback cost-effectiveness math.
- `billing.py`: URDB V3 retail billing engine plus pre-packaged tariff schedules (Georgia Power R-31, Alabama Power Rate FD).
- `data_loaders.py`: All file I/O — NREL Cambium CSV scanner, CWFT loader, weather (.epw/.csv) loader, load-profile parser (synthetic CSVs, EnergyPlus-style exports, and BEopt's native hourly export format), URDB API client, and the default mock-data generators.
- `visualizations.py`: Plotly chart-builder functions (Streamlit-free), returning `go.Figure` objects for the dashboard tabs.
- `config.py`: Central defaults, option lists, CSS styling, color palette, and the `EXAMPLE_BUILDINGS` pre-loaded example library.
- `requirements.txt`: Python package dependencies (Streamlit, Pandas, NumPy, Plotly).
- `Cambium_Hourly_Data_raw/`: Folder where users should place raw NREL hourly CSV downloads (for any scenario/year).
- `Load_Profiles_raw/`: Folder for real building load-profile exports (BEopt/EnergyPlus, single file or a whole folder of them). Backs the sidebar's Example Building Library (currently two Birmingham, AL examples: ER Heat vs. Heat Pump, and No Battery vs. 10 kWh Battery) as well as any load profile you supply yourself.
- `Weather_Data_raw/`: Contains subfolders (`Baseline/`, `Extreme_Winter/`, `Extreme_Summer/`) where users can place real weather datasets (e.g. `.epw` or `.csv` files) to override synthetic temperatures with real weather profiles.
- `CWFT.csv`: The Capacity Weighting Factor Table (CWFT) representing hour-by-hour system risk weights. *(Note: Must be replaced with real utility/ISO risk factor data for real-world evaluations).*
- `load_profiles.csv`: Default synthetic building load shapes, auto-generated if no real load data is supplied.
- `southeast_avoided_costs_AL_GA.csv`: Hourly avoided cost projections derived from NREL Cambium datasets for Alabama and Georgia balancing authorities. *(Role still unconfirmed with Justin — see `docs/roadmap.md` §1.8.)*

---

## 🤖 AI-Assisted Development

This project uses AI coding assistants. Standing instructions for any AI working on this codebase are in [`AI_INSTRUCTIONS.md`](AI_INSTRUCTIONS.md). These cover:
- **Living documentation** — 6 docs in `docs/` that must stay in sync with code
- **Roadmap annotations** — user comments in `docs/roadmap.md` that guide priorities
- **Testing** — `python -m pytest` after every code change

Auto-discovery files are set up for GitHub Copilot (`.github/copilot-instructions.md`) and Gemini (`AGENTS.md`).

---

## 🧪 Testing

Run the test suite:
```bash
python -m pytest
```

Tests cover the core calculation functions (avoided costs, URDB billing, NPV discounting, EPC/ELCC capacity metrics) and do not require Streamlit to be running.

---

## 📖 Documentation

See the `docs/` folder for living project documentation:
- [`docs/roadmap.md`](docs/roadmap.md) — Development milestones & progress tracking
- [`docs/needs_and_gaps.md`](docs/needs_and_gaps.md) — Gap analysis vs. project vision
- [`docs/glossary.md`](docs/glossary.md) — Domain terms & acronyms
- [`docs/app_code_tour.md`](docs/app_code_tour.md) — Plain-English code walkthrough
- [`docs/app_annotated.py`](docs/app_annotated.py) — Annotated teaching copy of `app.py`
- [`docs/CHANGELOG.md`](docs/CHANGELOG.md) — Change log
