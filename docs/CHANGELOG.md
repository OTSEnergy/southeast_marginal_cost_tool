# 📋 Documentation Changelog

This file tracks changes to the living project documents in the `docs/` folder.

---

## [2026-08-10] — Living Documentation Sync Pass

### Updated
- **`docs/needs_and_gaps.md`**: Updated Capabilities section, Executive Summary gap count table, and architecture status to reflect completion of Phase 3 modularization, real 2012 BEopt model ingestion, 2012 AMY weather files, TRC/PCT/RIM cost-effectiveness tests, and 49 passing automated tests.
- **`docs/app_code_tour.md`**: Updated introduction and table of contents to map the 6-module architecture (`app.py`, `calculations.py`, `billing.py`, `data_loaders.py`, `visualizations.py`, `config.py`).
- **`docs/roadmap.md`**: Verified milestone statuses (M1.2a, M1.4, M1.6, M2.1, M2.2, M3.1, M5.4 marked Done).
- **`AI_INSTRUCTIONS.md`**: Verified standing instructions for 6-module maintenance and test suite execution.

---

## [2026-08-10] — Measure & Program Costs, TRC, PCT & Payback Tests (M2.1, M2.2, M3.1)

### Added
- **`config.py` Defaults:** `DEFAULT_GROSS_MEASURE_COST` ($3,000), `DEFAULT_UTILITY_INCENTIVE` ($500), `DEFAULT_UTILITY_ADMIN_COST` ($100).
- **`calculations.py` Engine:**
  - `calculate_cost_effectiveness_tests()` — Computes standard California SPM test ratios (**TRC**, **PCT**, **RIM**) and **Simple & Discounted Customer Payback Periods (Years)**.
- **`app.py` UI Enhancements:**
  - Sidebar section **"💰 Measure & Program Costs"** for Gross Installed Measure Cost ($), Utility Rebate / Incentive ($), and Utility Program Admin Cost ($).
  - Executive Overview Scorecard (Tab 1) updated with **TRC**, **PCT**, **RIM**, **Simple Payback**, and **Discounted Payback** KPI cards.
- **`tests/test_calculations.py`:**
  - Added `TestCostEffectivenessTests` suite (TRC, PCT, RIM, Simple Payback, and Discounted Payback math). Total tests: 49.

### Verified
- `python -m pytest`: 49/49 passed (0.66s)

---

## [2026-08-10] — Real Building Models & Flexible Load Profile Ingestion (M1.2a & M1.4)

### Added
- **`Load_Profiles_raw/`** — New directory created for raw building simulation outputs (BEopt, EnergyPlus, eQUEST, or custom 8760 CSVs) with `instructions.txt`.
- **BEopt Model Output Support** — Added `ERHeatBeOptModel_Birmingham2012.csv` and `HeatPumpBeOptModel_Birmingham2012.csv` to `Load_Profiles_raw/`.
- **`data_loaders.py` Enhancements:**
  - `_extract_profile_from_beopt_or_eplus()` — Smart helper that auto-detects `ELECTRICITY:UNIT_1 [J](Hourly)` or `Electricity:Facility` headers, converts Joules `[J]` → kW (`/ 3,600,000`), and formats 8760 hours.
  - `load_load_profiles_from_csv()` — Updated to accept single BEopt/E+ CSV files or an entire folder (e.g. `Load_Profiles_raw/`), combining all model runs into a unified 8760 DataFrame.
- **`app.py` UI Upgrade:**
  - Added sidebar dropdown allowing users to toggle between `Load_Profiles_raw` (real BEopt models), `load_profiles.csv` (synthetic baseline), or a custom file path.
- **`tests/test_calculations.py`:**
  - Added `TestLoadProfileIngestion` suite (2 tests: single raw BEopt parsing & directory multi-file merging). Total tests: 48.

### Verified
- `python -m pytest`: 48/48 passed (0.56s)

---

## [2026-08-10] — Code Modularization Phase 3 (M1.6)

### Added
- **`config.py`** (248 lines) — Central configuration module. Extracted all hardcoded defaults (sidebar values, scenario/state option lists, financial parameters, DR defaults), chart constants (grid component definitions with colors, week windows), CSS styling, weather sensitivity thresholds, and tariff selector options from `app.py`. Includes `get_weather_sensitivity_style()` helper.
- **`visualizations.py`** (230 lines) — Plotly chart builder module. Four Streamlit-free functions that each return a `go.Figure`:
  - `build_weekly_overlay_chart()` — dual-axis weekly load + avoided cost overlay
  - `build_annual_avoided_cost_chart()` — full-year hourly avoided cost time series
  - `build_stacked_components_chart()` — stacked area of 5 grid cost components
  - `build_lifetime_npv_chart()` — grouped bar of nominal vs discounted cash flows

### Modified
- **`calculations.py`** (170 lines, was 103) — Added `dispatch_dr_program()` function, moved from `app.py`. Pure NumPy demand response dispatch logic with season filtering, daily call limits, and load-capped curtailment.
- **`app.py`** (1,210 lines, was 1,433) — Net reduction of 223 lines:
  - Removed dead duplicate tariff dicts (`GP_R31_URDB`, `AL_FD_URDB`) that were already imported from `billing.py`
  - Replaced all inline sidebar defaults with `config.py` constants
  - Replaced 4 inline Plotly chart builders with `visualizations.py` function calls
  - Replaced weather sensitivity threshold logic with `config.get_weather_sensitivity_style()`
  - Moved `dispatch_dr_program()` to `calculations.py`, imported it back
  - Updated module header comments to reflect all 6 extracted modules
- **`tests/test_calculations.py`** — Added 17 new tests (total: 41):
  - `TestDispatchDrProgram` (5 tests): hour limits, daily limits, season filtering, load cap, shapes
  - `TestConfig` (7 tests): option list integrity, default values, grid components, week windows, CSS, weather sensitivity function
  - `TestVisualizations` (5 tests): each builder returns valid `go.Figure` with correct trace counts
  - Removed Plotly stubs — tests now use real Plotly for visualization validation

### Verified
- `python -m pytest`: 46/46 passed (0.65s)

### Module Summary After Phase 3
| Module | Lines | Role |
|--------|-------|------|
| `app.py` | 1,210 | UI orchestration (Streamlit layout, sidebar, tabs) |
| `calculations.py` | 170 | Grid avoided costs + DR dispatch |
| `billing.py` | 219 | URDB billing engine + tariff data |
| `data_loaders.py` | 699 | All file I/O |
| `visualizations.py` | 230 | Plotly chart builders |
| `config.py` | 248 | Defaults, constants, CSS |

---

## [2026-08-06] — Code Modularization Phase 2 (M1.6)

### Added
- **`data_loaders.py`** — Extracted all data I/O from `app.py`: Cambium CSV ingestion pipeline, CWFT loader/generator, load profile loader/generator, weather file loader, URDB API fetch, mock state data generator, and column mapping engine. Each function annotated with ⚠️ MOCK or ✅ REAL status. Full docstrings throughout.

### Modified
- **`app.py`** — Now imports 10 functions + 1 constant from `data_loaders`. Old 530-line inline block replaced with annotated comment block (with ⚠️/✅ status per function). `@st.cache_data` applied at app level since `data_loaders.py` is Streamlit-free. Net reduction: ~470 lines.
- **`AI_INSTRUCTIONS.md`** — Architecture section updated: `data_loaders.py` moved from "Planned" to extracted.
- **`docs/roadmap.md`** — M1.6 marked 🟡 Phase 2 Done.

### Verified
- `python -m pytest`: 24/24 passed (0.11s)
- `streamlit run app.py`: clean launch, no import errors

---

## [2026-08-06] — Code Modularization Phase 1 (M1.6)

### Added
- **`calculations.py`** — Extracted `calculate_avoided_costs()` from `app.py`. Full docstrings explaining each of the 5 avoided cost components, why it's separate, what it connects to.
- **`billing.py`** — Extracted `calculate_urdb_bill()` + `GP_R31_URDB` + `AL_FD_URDB` tariff constants from `app.py`. Full docstrings explaining URDB V3 schema, billing engine logic, and tariff derivations.

### Modified
- **`app.py`** — Now imports from `calculations` and `billing` modules. Old inline definitions replaced with annotated comment blocks pointing readers to the modules (what the function does, where to find it, where it's tested). Net reduction: ~130 lines.
- **`tests/test_calculations.py`** — Updated imports to use modules directly (`from calculations import ...`, `from billing import ...`) instead of through `app`.
- **`docs/roadmap.md`** — M1.6 marked 🔶 Phase 1 Done.

### Verified
- `python -m pytest`: 24/24 passed (0.12s)

---

## [2026-08-06] — Test Infrastructure Established (M5.4 v1)

### Added
- **`pytest.ini`** — Pytest configuration pointing to `tests/` directory
- **`tests/conftest.py`** — Shared fixtures: 8760-hour grid DataFrames, CWFT arrays (uniform + peaked), rate structures (GP R-31, flat, flat+demand), load profiles, datetime series
- **`tests/test_calculations.py`** — 24 tests across 4 suites:
  - `TestCalculateAvoidedCosts` (7 tests): output schema, gen capacity formula, PCAF-based T&D, emissions formula, total=sum check, zero-scalar boundary
  - `TestCalculateUrdbBill` (6 tests): flat rate billing, seasonal tiers (GP R-31), demand charges, zero-load boundary, proportionality
  - `TestNPVDiscounting` (5 tests): discount factor monotonicity, zero-rate boundary, known-answer NPV, RIM ratio, zero-division guard
  - `TestCapacityMetrics` (6 tests): EPC with uniform/peaked CWFT, EPC reduction, ELCC proxy formula, CWFT sum validation

### Updated
- **Standing instruction** — Added rule 7: run `python -m pytest` after code changes
- **`roadmap.md`** — M5.4 marked ✅ v1 Done

---

## [2026-08-06] — Roadmap Annotations Processed

### Updated
- **`roadmap.md`** — Processed John's inline comments from 8/4–8/6. Updated §9 Progress Tracking with decision tags, owners, and scope modifications for all M1–M3 items. Key changes:
  - 1.1 CWFT → `📦 EXTERNAL` (Justin to provide)
  - 1.2 Load profiles → `📦 EXTERNAL` (John, scoped to single-family res)
  - 1.3 State coverage → `🔀 MODIFY` (GA/AL only, maybe TN)
  - 1.4, 1.5, 1.6, 1.7 → `🔨 BUILD` (AI-led or JB+AI)
  - M2 goal updated to include team buy-in for ongoing maintenance
  - 2.1–2.2 → JB lead, JH+SC review; 2.3–2.4 → JH lead; 2.5–2.6 → deferred
  - 3.1–3.4 → JB lead with various reviewers; 3.3, 3.5, M4 → needs discussion/vetting
  - Added Key Stakeholders table (JB, JH, SC, Al/Mitch)
  - M5.4 automated tests flagged for early start per John's M1.6 comment

---

## [2026-08-04] — Roadmap Added

### Added
- **`roadmap.md`** — Development roadmap with 6 sequenced milestones (Harden Foundation → Utility Value Story → Vendor Experience → Dual-View & Explorer → Validation → Handoff). Includes dependency map, open design decisions, and progress tracking table with commenting conventions (`🔨 BUILD`, `📦 EXTERNAL`, `🔀 MODIFY`, `❌ ABANDON`, `⏸️ DEFER`, `❓ DISCUSS`) so team members can annotate items with decisions and context.

---

## [2026-08-04] — Glossary Added

### Added
- **`glossary.md`** — Comprehensive definitions and acronyms document covering 80+ terms organized into 9 topic areas: grid economics, capacity metrics, cost-effectiveness tests, retail tariffs, data sources, weather/simulation, financial, software, and organizations. Marked as a living document under the same maintenance rules as other docs.

---

## [2026-08-04] — Initial Setup

### Added
- **`docs/` folder created** as the central home for project planning and documentation artifacts.
- **`app_annotated.py`** — Copied from project root. Fully annotated, runnable duplicate of `app.py` designed for non-coders and energy analysts. *(Note: Dashboard tabs 2-7 are stubs compared to the full `app.py` — see needs_and_gaps.md §6.2 for sync strategy discussion.)*
- **`app_code_tour.md`** — Copied from project root. Chapter-by-chapter plain-English walkthrough of `app.py` covering all 8 sections (imports, rate structures, mock generators, pipelines, billing engine, weather generator, sidebar, dashboard).
- **`needs_and_gaps.md`** — New document. Comprehensive gap analysis mapping the current state of `app.py` (v1957 lines) against the project abstract and phased development plan. Identifies 33+ specific gaps across data, calculations, UX, architecture, and planned features.
- **`CHANGELOG.md`** — This file. Tracks modifications to all docs/ documents.

### Status of Source Files at Time of Copy
- `app.py`: 1,957 lines (99,650 bytes) — the production application
- `app_annotated.py`: 1,256 lines (58,821 bytes) — the annotated teaching copy
- `app_code_tour.md`: 217 lines (14,435 bytes) — the narrative code tour

---

*Update this log whenever documents in `docs/` are created, significantly modified, or retired.*
