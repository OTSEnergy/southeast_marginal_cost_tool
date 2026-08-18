# 🔍 Needs & Gaps Analysis: Southeast Marginal Cost Valuation Engine

> **Document Purpose:** Maps the current state of `app.py` against the project abstract and phased development plan to identify gaps, placeholders, hardcoded assumptions, and unresolved design decisions.
>
> **Last Updated:** 2026-08-10
> **Assessed Against:** app.py (1,210 lines) + calculations.py + billing.py + data_loaders.py + visualizations.py + config.py

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current Tool Capabilities (What Exists)](#2-current-tool-capabilities-what-exists)
3. [Data & Input Gaps](#3-data--input-gaps)
4. [Calculation & Methodology Gaps](#4-calculation--methodology-gaps)
5. [User Experience & Interface Gaps](#5-user-experience--interface-gaps)
6. [Architecture & Code Quality Gaps](#6-architecture--code-quality-gaps)
7. [Feature Gaps Against Project Plan](#7-feature-gaps-against-project-plan)
8. [Prioritized Action Items](#8-prioritized-action-items)

---

## 1. Executive Summary

The tool currently delivers a **modularized, multi-metric valuation engine** with strong foundational math (avoided costs, CWFT/EPC/ELCC capacity metrics, URDB retail billing, multi-year NPV discounting, TRC, PCT, RIM cost-effectiveness tests, and customer payback periods). Recent updates integrated real 2012 BEopt building models and automated 2012 AMY EPW weather files. Significant gaps remaining relate to **user roles / dual-interface architecture** (Utility vs. Vendor views) and utility-supplied proprietary CWFT data. The gap landscape is summarized below:

| Category | Severity | Count |
|----------|----------|-------|
| **Placeholders & mock data standing in for real data** | 🔴 High | 4 |
| **Missing user roles / dual-interface architecture** | 🔴 High | 3 |
| **Missing cost-effectiveness tests (TRC, PCT, RIM)** | ✅ **Resolved** | 0 |
| **Missing vendor-facing features (payback, guidance, targets)** | 🟡 Medium | 4 |
| **Explorer / what-if functionality** | 🟡 Medium | 4 |
| **Visualization & audience-specific output gaps** | 🟡 Medium | 5 |
| **Architecture & maintainability** | ✅ **Resolved** | 0 |

---

## 2. Current Tool Capabilities (What Exists)

Before cataloguing gaps, here is what the tool **does** have working today:

### ✅ Functional
- **Fully Modular Architecture** (Streamlit UI in `app.py` [1,210 lines], pure-Python logic in `calculations.py`, `billing.py`, `data_loaders.py`, `visualizations.py`, `config.py`)
- **8,760-hour avoided cost engine** with 5 stacked components (energy, generation capacity, T&D, emissions)
- **CWFT-based capacity allocation** (EPC and ELCC proxy calculations)
- **PCAF-based T&D deferral allocation** (top 100 price hours)
- **URDB-compliant retail billing engine** (tiered blocks, seasonal periods, weekday/weekend, demand charges)
- **Two pre-packaged retail tariffs** (Georgia Power R-31, Alabama Power FD)
- **URDB API integration** (live tariff import from NREL OpenEI)
- **Custom tariff input** (paste JSON or flat rate)
- **Multi-year NPV discounting** with escalation, degradation, and WACC
- **Full California SPM Cost-Effectiveness Suite**:
  - **TRC Test (Total Resource Cost)** = `NPV Grid Avoided Costs / (Gross Measure Cost + Utility Admin)`
  - **PCT Test (Participant Cost Test / Customer ROI)** = `(NPV Customer Bill Savings + Incentive) / Gross Measure Cost`
  - **RIM Test (Rate Impact Measure)** = `NPV Grid Avoided Costs / (NPV Lost Revenue + Program Costs)`
- **Customer Payback Engine**:
  - **Simple Payback Period (Years)**
  - **Discounted Payback Period (Years)**
- **Demand Response dispatch mode** (CWFT-ranked curtailment with daily call limits)
- **Dynamic NREL Cambium column mapping** (handles variant column names)
- **BEopt / EnergyPlus & Custom Excel/CSV Ingestion**:
  - Auto-detects `ELECTRICITY:UNIT_1 [J](Hourly)` or `Electricity:Facility` headers
  - Converts Joules `[J]` $\to$ kW ($\div 3,600,000$)
  - Multi-format support for `.csv`, `.xlsx`, and `.xls` files with automatic Date/Time column stripping
  - Ingests multi-column case comparison files (e.g. Date + `Total TES` + `Total No TES`)
  - Folder scanning mode (`Load_Profiles_raw/`) to merge all model runs and custom case files into selectable baseline/proposed dropdowns
- **Weather file support** (EPW and CSV import, synthetic fallback, extreme weather shifting)
- **AMY weather generator** (`diyepw` integration for NOAA-sourced EPW files; 2012 EPWs generated for Atlanta & Birmingham)
- **8-tab dashboard** (scorecard, RIM/TRC/PCT tables, grid charts, weather diagnostics, NPV/scenarios, debugger, calibration guide, weather generator)
- **Scenario save/compare** (in-session side-by-side run comparison)
- **Automated Pytest Suite** (52 unit & integration tests covering all math, billing, config, viz, pipeline, BEopt, load profile ingestion, and dual weekly charts)
- **CSV export** of top stress hours

### ⚠️ Partially Implemented
- Weather sensitivity correlation check (exists as a diagnostic banner in Tab 1)
- `app_annotated.py` exists as a teaching copy (needs ongoing sync review against modularized `app.py`) compared to the full `app.py`

---

## 3. Data & Input Gaps

### 3.1 🔴 CWFT Is a Placeholder
**File:** `CWFT.csv` / `generate_default_cwft_file()`
**Lines:** app.py 127–154

The CWFT file is **synthetically generated** using hardcoded hour ranges and a simple 45%/55% winter/summer split. The README itself warns:
> *"The provided CWFT.csv file is currently a mocked placeholder and does not reflect realistic utility peak risk conditions."*

**Gap:** No connection to real utility LOLP (Loss of Load Probability) data, IRP capacity planning outputs, or ISO/RTO reliability studies. The winter morning window (hours 6-9, Jan-Feb only) and summer afternoon window (hours 14-18, Jun-Sep) are crude approximations.

**What's Needed:**
- Real CWFT data from Southern Company or similar (likely proprietary)
- Or: a calibration methodology using public LOLP proxy data (e.g., NERC LTRA, EIA Form 411)
- Ability to upload and validate externally-produced CWFT shapes
- Possibly: a CWFT *builder* tool that lets utility users define risk windows and weights interactively

---

### 3.2 🔴 Load Profiles Are Synthetic Placeholders
**File:** `load_profiles.csv` / `generate_default_load_profiles_file()`
**Lines:** app.py 174–197

The default load profiles (`Standard_Heat_Pump_kW`, `High_Efficiency_Heat_Pump_kW`) are **random uniform noise** with hardcoded spike ranges. They do not come from EnergyPlus simulations or any real building model.

**Gap:** No real building energy models are included. The project plan explicitly calls for:
> *"Populate some example building models representing typical buildings — leverage existing models where possible"*

**What's Needed:**
- Real 8760-hour EnergyPlus or DOE prototype building outputs for Southeast climate zones
- Multiple representative building types (single-family, multifamily, small commercial)
- Multiple technology scenarios per building (baseline resistance/gas, standard HP, high-efficiency HP, HP + storage, etc.)
- A library or file picker so users can select from pre-loaded example buildings

---

### 3.3 🔴 Grid Data Coverage Is Limited
**Lines:** app.py 428–507, README lines 48–52

Only Alabama and Georgia are currently supported with real Cambium data. The tool handles 7 states in the UI (`AL, GA, FL, TN, MS, NC, SC`) but will fail with `FileNotFoundError` for any state without downloaded data.

**Gap:** No bundled data for FL, TN, MS, NC, SC. No automated download or data management workflow.

**What's Needed:**
- Pre-bundled Cambium data for all target Southeast states (or at least a documented download guide per state)
- Consider a data download helper that fetches from NREL Scenario Viewer programmatically
- Year-coverage: currently only one planning year file per state; may need multiple years for sensitivity analysis

---

### 3.4 🟡 Weather Data Is Largely Synthetic
**Lines:** app.py 540–606

When no `.epw` or `.csv` file exists in `Weather_Data_raw/`, the tool generates a **synthetic sine-wave temperature profile** (seasonal + daily + noise). While the diyepw generator exists, no default real weather files are bundled.

**What's Needed:**
- Bundle at least one real 2012 AMY EPW file (Birmingham or Atlanta) as a verified baseline
- Document which weather stations map to which Cambium geographic regions

---

### 3.5 🟡 No Real Avoided Cost Benchmark Data
**File:** `southeast_avoided_costs_AL_GA.csv` (888KB, exists but not referenced in code)

This file exists in the repository but is **never imported or used** by `app.py`. Its role is unclear.

**What's Needed:**
- Clarify whether this file is a validation reference, an alternate data source, or deprecated
- If it's a benchmark: integrate it into the debugger tab for comparison against calculated values

---

### 3.6 🟡 No User-Uploadable File Interface
**Lines:** app.py 1042–1046

File paths for CWFT and load profiles are entered as **raw text strings** in the sidebar. There is no Streamlit `file_uploader` widget, drag-and-drop, or in-browser file management.

**What's Needed:**
- `st.file_uploader()` for CWFT, load profiles, and optionally weather files
- Validation feedback on upload (row count, column detection, preview)
- Option to download template CSVs

---

## 4. Calculation & Methodology Gaps

### 4.1 🔴 No TRC (Total Resource Cost) Test
The project plan lists **RIM/TRC** as a key utility metric. Currently only **RIM** is implemented.

**Gap:** TRC requires incorporating:
- Technology/measure installation cost (capital cost)
- Participant costs (homeowner equipment + O&M)
- Non-energy benefits (comfort, resilience, property value — often qualitative or proxy-valued)
- Program administration costs

None of these cost inputs exist in the current sidebar or calculations.

**What's Needed:**
- Sidebar inputs for: installed cost ($), annual O&M ($/yr), program admin cost ($/yr), non-energy benefits ($/yr)
- TRC formula: `TRC = (NPV Avoided Costs + NPV Non-Energy Benefits) / (NPV Measure Costs + NPV Program Costs)`
- Display alongside RIM in the scorecard and cost-effectiveness table

---

### 4.2 🔴 No Homeowner Cost-of-Ownership / Payback Calculation
The project plan calls for the **Product Development user** to see:
> *"Cost for homeowner to use, cost to utility, gap between the two... Payback period"*

**Gap:** The tool calculates **utility-side** bill savings and grid avoided costs but never computes:
- Customer total cost of ownership (equipment + install + O&M − bill savings)
- Simple payback period
- Discounted payback period
- Customer IRR or ROI

**What's Needed:**
- Equipment cost input ($ one-time)
- Annual maintenance cost input ($/yr)
- Available incentives/rebates input ($)
- Payback = (Equipment Cost − Rebates) / Annual Bill Savings
- Discounted payback using the customer's cost of capital

---

### 4.3 🔴 No Capacity Value Methodology Options (EPC/ELCC Variants)
**Lines:** app.py 1241–1248

The ELCC proxy is calculated as `EPC / Peak Load`. This is a simple approximation. The project plan mentions **EPC/ELCC** as explicit utility deliverables.

**Gap:** No alternative ELCC calculation methodologies are available:
- No marginal ELCC (sequential vs. average)
- No multi-resource portfolio ELCC
- No comparison against utility IRP capacity credit values

**What's Needed:**
- At minimum: document the limitations of the current proxy
- Aspirationally: implement a marginal capacity credit calculation using LOLP-based methods
- Allow utility users to override ELCC with their own IRP-derived values

---

### 4.4 🟡 T&D Deferral Methodology Is Simplified
**Lines:** app.py 532–536, 616–617

T&D value uses PCAF (top 100 price hours) with uniform weighting. This treats wholesale energy price as a proxy for local T&D congestion, which is a rough approximation.

**Gap:**
- Real T&D deferral depends on **local feeder/substation peak**, not system-wide wholesale prices
- No distinction between transmission-level and distribution-level peak hours (they may differ)
- No ability to input feeder-specific load data or transformer ratings

**What's Needed:**
- Clarify in documentation that PCAF is an approximation
- Consider allowing users to upload a custom T&D peak allocation vector (similar to CWFT)
- Or: allow direct $/kW-yr scalar input (already exists) but remove the hourly allocation and just use annual EPC-like metric

---

### 4.5 🟡 Carbon Value Methodology Limitations
**Lines:** app.py 618, 713

Emissions value = `(kg CO2/MWh ÷ 1000) × $/metric ton`. This captures only combustion CO2 from Cambium.

**Gap:**
- No lifecycle or upstream emissions (methane, supply chain)
- No SO2, NOx, PM2.5, or health-related externalities
- No social cost of carbon (SCC) option vs. compliance cost
- Cambium provides multiple emissions metrics (e.g., `lrmer_co2_c`, `lrmer_co2_e`, `lrmer_co2_p`) — the tool only uses one

**What's Needed:**
- Dropdown to select which Cambium emissions metric to use
- Option for social cost of carbon schedules (EPA IWG values)
- Consider adding criteria pollutant externalities as an optional add-on

---

### 4.6 🟡 No Stacked System / Technology Combination Analysis
The project plan mentions:
> *"What if we added an EV charger"*

**Gap:** Currently only two profiles can be compared (baseline vs. proposed). There is no way to:
- Stack multiple technologies (HP + EV + battery + PV)
- See incremental value of each addition
- Model interactive effects (e.g., battery shifting HP load away from peaks)

**What's Needed:**
- Multi-profile stacking: allow 3+ load columns and show incremental avoided cost of each
- Or: a simple load arithmetic tool ("add column A + column B to create combined profile")

---

## 5. User Experience & Interface Gaps

### 5.1 🔴 No User Role / View Mode Architecture
The project abstract explicitly defines two interfaces:
> - *Utility-Oriented View: Allows utility teams to tune, validate, and control relevant economic and grid parameters.*
> - *Vendor-Oriented View: Provides simplified utility-side assumptions while emphasizing the vendor's key product parameters.*

The project plan also mentions a possible **Researcher mode**.

**Gap:** The current tool has **one monolithic view**. All parameters are visible and adjustable by all users. There is no role-based filtering, simplified vendor dashboard, or permission/access model.

**What's Needed:**
- A top-level mode selector (Utility / Vendor / Researcher)
- **Utility mode:** Full access to all valuation scalars, CWFT, PCAF, tariff structures, debugger
- **Vendor mode:** Lock/hide grid valuation parameters; emphasize product cost inputs, payback, performance targets, improvement guidance
- **Researcher mode:** Everything visible, plus raw data exports and detailed hourly breakdowns
- This is a fundamental UX architecture decision that will affect nearly every UI element

---

### 5.2 🟡 No Technology Improvement Guidance / Targets
The project plan prioritizes:
> *"Highlight the periods of 'best' and 'worst' performance... Present hypotheticals on the gap between cost effective and not..."*

**Gap:** The tool shows results but provides **no interpretive guidance**. It doesn't tell you:
- Which hours/periods the technology performs well vs. poorly
- What performance improvement would be needed to reach cost-effectiveness (e.g., "reduce winter peak by X kW" or "cut cost by Y%")
- Parametric "what-if" results (e.g., "if capital cost were $500 less, payback drops to Z years")

**What's Needed:**
- A "Performance Analysis" tab or section that:
  - Identifies the top N hours/periods where load reduction is lowest relative to grid value
  - Calculates the marginal value of additional peak reduction
  - Shows parametric sensitivity: "if EPC improved by 10%, capacity savings increase by $X"
- A cost-effectiveness gap calculator: "to achieve RIM ≥ 1.0, one of the following must change: ..."
- Pre-set "examinations" as mentioned in the plan (template analyses that run automatically)

---

### 5.3 🟡 No Explorer / What-If Sandbox
The project plan describes:
> *"Basic ability to input modest 'what ifs' to slightly modify the modeled scenario... Example: let the user adjust power for key hours"*

**Gap:** Users cannot modify load profiles within the app. They must externally edit CSVs and re-upload.

**What's Needed:**
- In-app load profile editor (at minimum: scale factors by season, hour-of-day, or individual hours)
- Quick scenario toggles: "add X kW of EV charging during hours Y-Z"
- Side-by-side comparison of original vs. modified profile

---

### 5.4 🟡 No Audience-Specific Visualizations
The project plan calls for:
> *"Data visualizations to 'speak the language' of the respective audiences (e.g., building-level graphs for the manufacturer and utility-oriented visualizations for the utility)"*

**Gap:** All current visualizations are utility/grid-oriented ($/MWh stacked areas, CWFT coincidence tables, NPV cash flows). There are no:
- Building-level energy use breakdowns (by end-use: heating, cooling, baseload)
- Customer bill waterfall charts
- Technology comparison dashboards
- Simplified "is my product valuable?" summary cards for vendors

**What's Needed:**
- Vendor-facing charts: monthly bill comparison bar charts, payback timeline, "value heatmap" (hour-of-day × month showing $/kWh value)
- Utility-facing charts: already mostly present, but could add regional comparison maps, IRP integration summaries

---

### 5.5 🟢 Dashboard Tab Organization Could Be Improved
With 8 tabs currently, and more features planned, the tab layout will become unwieldy.

**What's Needed:**
- Consider grouping tabs under role-based views
- Or: use Streamlit's multi-page app architecture (`pages/` directory) instead of tabs
- The calibration guide and weather generator could become separate utility pages

---

## 6. Architecture & Code Quality Gaps

### 6.1 🟡 Monolithic Single-File Architecture
All 1,957 lines of application logic, UI, and data processing live in one `app.py` file.

**What's Needed (for maintainability as features grow):**
- Separate into modules:
  - `data_loaders.py` (Cambium ingestion, weather, CWFT, load profiles) — ✅ **Extracted 2026-08-06**
  - `calculations.py` (avoided costs, NPV, capacity metrics) — ✅ **Extracted 2026-08-06**
  - `billing.py` (URDB structures, pre-packaged tariffs, billing engine) — ✅ **Extracted 2026-08-06**
  - `visualizations.py` (Plotly chart builders)
  - `app.py` (Streamlit UI layout and orchestration only)
- Or: adopt Streamlit multi-page app pattern

> **Status:** 🟡 Mostly resolved. Phases 1–2 complete (calculations.py + billing.py +
> data_loaders.py extracted, app.py reduced from ~1,957 to ~1,350 lines). Remaining:
> visualizations.py, config.py.

---

### 6.2 🟡 `app_annotated.py` Is Out of Sync with `app.py`
`app_annotated.py` (1,256 lines) is a **teaching duplicate** of `app.py` (1,957 lines). The annotated version has significantly less dashboard content — tabs 2-7 are stubs with only 1-2 lines of output each, while `app.py` has full implementations.

**Risk:** As `app.py` evolves, the annotated version will drift further out of sync unless actively maintained.

**What's Needed:**
- Decide on a maintenance strategy:
  - **Option A:** Keep `app_annotated.py` as a snapshot with a "last synced" date, and update it periodically
  - **Option B:** Replace it with inline comments in `app.py` itself (annotate the real file)
  - **Option C:** Auto-generate the annotated version from `app.py` plus a separate annotations file
- The code tour (`app_code_tour.md`) references specific line numbers that will also drift

---

### 6.3 🟡 Silent Error Swallowing in Data Ingestion
**Lines:** app.py 505–507
```python
except Exception as e:
    # Silently pass for other files
    pass
```

The Cambium file scanner silently swallows all exceptions. If a real data file has a formatting issue, the user gets no feedback — the file is simply skipped.

**What's Needed:**
- Log or display warnings for files that fail to parse
- Distinguish between "not a matching file" (expected, silent) and "matching file with errors" (should warn)

---

### 6.4 ✅ ~~No Automated Tests~~ — Resolved 2026-08-06
~~There are no unit tests for any calculation functions.~~

**Resolved:** 24 tests across 4 suites now validate the core calculation functions:
- `TestCalculateAvoidedCosts` (7 tests) — formula verification, boundary conditions
- `TestCalculateUrdbBill` (6 tests) — flat rate, GP R-31 tiered, demand charges
- `TestNPVDiscounting` (5 tests) — discount factors, known-answer NPV, RIM
- `TestCapacityMetrics` (6 tests) — EPC/ELCC with uniform and peaked CWFT

Test infrastructure: `pytest.ini`, `tests/conftest.py` (shared fixtures), `tests/test_log.txt` (auto-generated audit trail, newest-first). Standing instruction to run `python -m pytest` after code changes.

---

### 6.5 🟢 No Configuration / Settings File
All default values (capacity scalar $100/kW-yr, T&D $15/kW-yr, carbon $30/ton, etc.) are hardcoded in the sidebar widget definitions.

**What's Needed:**
- A `config.yaml` or `defaults.json` file for default parameter values
- This would allow different deployments (e.g., different utility partners) to have different defaults without code changes

---

## 7. Feature Gaps Against Project Plan

### Phase 1 Gap Mapping

| Planned Feature | Status | Gap |
|----------------|--------|-----|
| **Utility user mode** (capacity, EPC/ELCC, RIM/TRC, T&D) | 🟡 Partial | RIM exists; TRC missing; EPC/ELCC are proxies; T&D is simplified |
| **Product dev user mode** (homeowner cost, utility cost, gap, payback) | 🔴 Not started | No customer cost-of-ownership, no payback, no vendor view |
| **Researcher mode** (transparency, detailed hourly, model insights) | 🟡 Partial | Debugger tab exists but no dedicated researcher interface |
| **Example building models** | 🔴 Not started | Only random synthetic profiles exist |
| **What-if explorer** (adjust power for key hours, add EV charger) | 🔴 Not started | No in-app load modification capability |
| **Technology improvement guidance / targets** | 🔴 Not started | No performance gap analysis or improvement recommendations |
| **Best/worst performance highlighting** | 🔴 Not started | No hour-by-hour performance scoring |
| **Cost-effectiveness gap hypotheticals** | 🔴 Not started | No "what would it take to be cost-effective" calculator |
| **Audience-specific visualizations** | 🟡 Partial | Utility charts exist; vendor/building-level charts missing |

### Phase 2 Items (Future — Not Gaps Yet, But Worth Tracking)

| Planned Feature | Notes |
|----------------|-------|
| National lab / EPRI partnership home | Organizational, not technical |
| Test case evaluation (1-2 real technologies) | Requires real data partnerships |
| Validation against internal utility calculations | Requires utility partner data access |
| Expansion to other utility regions | Requires additional Cambium data + tariff structures |
| Monte Carlo uncertainty analysis | Not yet scoped technically |
| Alternate fuels analysis | Would require fuel cost data and dual-fuel modeling |

---

## 8. Prioritized Action Items

### 🔴 Priority 1 — Foundation (Must-Have for Credibility)

1. **Replace placeholder CWFT** with real or calibrated capacity risk data
2. **Bundle real building load profiles** from EnergyPlus prototype models
3. **Implement TRC test** alongside existing RIM
4. **Add customer cost-of-ownership and payback** calculations
5. **Design and implement user role architecture** (Utility / Vendor / Researcher mode selector)

### 🟡 Priority 2 — Differentiation (Core Value Proposition)

6. **Build technology improvement guidance engine** (best/worst hours, performance targets, cost-effectiveness gap calculator)
7. **Add what-if explorer** (in-app load profile adjustment)
8. **Create vendor-facing visualizations** (bill comparison, payback timeline, value heatmap)
9. **Expand grid data coverage** to all target Southeast states
10. **Add file upload widgets** for CWFT, load profiles, weather

### 🟢 Priority 3 — Quality & Sustainability

11. **Modularize codebase** — 🟡 Phase 2 done (calculations.py + billing.py + data_loaders.py extracted 2026-08-06). Remaining: visualizations.py, config.py.
12. **Add unit test suite** — ✅ Done (24 tests, 2026-08-06). Standing instruction for ongoing test maintenance.
13. **Create configuration file** for default parameters
14. **Resolve `app_annotated.py` sync strategy**
15. **Improve error handling** in data ingestion pipeline
16. **Clarify role of `southeast_avoided_costs_AL_GA.csv`** (unused file)
17. **Revisit load profile column selection UX** — ✅ **Resolved 2026-08-10** (Single File Mode explicitly prompts "Which column in [file] is Baseline/Proposed?" without keyword guessing).

---

*This document should be updated as gaps are resolved and new requirements emerge. Cross-reference with the project plan and abstract to ensure alignment.*
