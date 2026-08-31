# 📋 Documentation Changelog

This file tracks changes to the living project documents in the `docs/` folder.

## [2026-08-31] — Documentation Audit: Fixed Stale Status Claims Across 5 Docs

### Context
John asked for a pass through all the documentation to confirm it's up to date before continuing. Rather than just checking the items touched in the last session (the example-building work), did a full sweep of `README.md`, `AI_INSTRUCTIONS.md`, `docs/glossary.md`, `docs/app_code_tour.md`, and `docs/needs_and_gaps.md` against the current code. Found several real, pre-existing inaccuracies unrelated to the most recent feature work — mostly documentation that was never revisited after the modularization (extracting `app.py` into `calculations.py`/`billing.py`/`data_loaders.py`/`visualizations.py`/`config.py`) and after TRC/PCT/payback were implemented.

### Fixed
- **`docs/glossary.md`:** TRC, PCT, and Payback Period were all still marked "🔴 Not yet implemented" despite being live since well before mid-August. Marked all three ✅ Implemented with their actual formulas and source location (`calculate_cost_effectiveness_tests()` in `calculations.py`). Updated "Last Updated" date (was still 2026-08-04, seven revisions behind).
- **`docs/needs_and_gaps.md`:**
  - §4.1 ("No TRC Test") and §4.2 ("No Homeowner Cost-of-Ownership / Payback") rewrote as resolved — both were stale in exactly the same way as the glossary entries above, even though §1's Executive Summary already correctly said these were done. The document had drifted out of sync with itself.
  - §7 Phase 1 Gap Mapping table: "Utility user mode" and "Product dev user mode" rows still said "TRC missing" / "no payback" — updated to reflect what's implemented and what's genuinely still missing (dedicated role/view, gap visualization).
  - §8 Prioritized Action Items: marked items 3, 4, 11, and 13 resolved (TRC, payback, full modularization, config.py) — item 11 specifically still claimed visualizations.py/config.py extraction was "remaining" when it's done. Updated item 12's test count (24 → 57) and noted in item 14 that the app_annotated.py drift has now spanned 3 sessions.
  - Updated "Last Updated" date and the `app.py` line count in the header (1,210 → 1,502).
- **`docs/app_code_tour.md`:**
  - The module line-count table was off by as much as 2.5x (`visualizations.py` claimed ~230 lines, actually 565; `config.py` claimed ~250, actually 397; `billing.py` claimed ~180, actually 269).
  - Chapters 1–6 described mock generators, the Cambium column mapper, the weather loader, the avoided-cost engine, and the URDB billing engine as if they were still inline in `app.py` with specific line ranges (e.g. "Lines 286–630") — all of that code moved to `data_loaders.py`, `calculations.py`, and `billing.py` during modularization, and the doc was never updated to say so. Added a file-map note up front and retitled each chapter header with its actual current file.
  - Updated the Example Building Library section to describe both examples (was still describing only the first, from 2026-08-18) and noted the native-BEopt-format loader support.
- **`README.md`:** The "Project Structure" section still described `app.py` as "the core Streamlit application containing the avoided cost calculation engine... and dashboard visualizations" — i.e., the pre-modularization monolith — and didn't mention `Load_Profiles_raw/`, the module split, or the Example Building Library at all. Rewrote to list all 6 modules by actual responsibility and added the missing folder/feature entries.
- **`AI_INSTRUCTIONS.md`:** Corrected "`visualizations.py` — Plotly chart builder functions (4 chart types...)" to 7 — the file has grown since that line was written.

### Not Fixed (Flagged Instead)
- **`docs/needs_and_gaps.md`** still has scattered `Lines: app.py NNN–NNN` pinpoint references throughout §3–§4 (e.g. §4.3, §4.4) that likely no longer match post-modularization line numbers. Given the volume, didn't attempt to re-verify every one this pass — treat them as approximate, same caveat the doc already carries for line-number drift generally.
- **`docs/app_annotated.py`** remains unsynced (flagged in the 2026-08-18 entry, still true). It's now 3 sessions of drift (8-18 sidebar/tab rewrite, 8-21 peak-ratio rework, 8-26 example building + loader change) — none of that is reflected in the annotated teaching copy. A full resync is a dedicated task, not a quick fix within a doc-audit pass.

### Verification
- `python -m pytest`: **57/57 passing** — this was a documentation-only pass, no source files touched.

---

## [2026-08-26] — Second Example Building: No Battery vs. 10 kWh Battery (Seasonal Strategy)

### Context
John added two new BEopt output files to `Load_Profiles_raw/` (`BEOptExample_NoBattery_Birmingham2012.csv` / `BEOptExample_Battery_Birmingham2012.csv`) for a second Example Building: the same default BEopt single-family model, baseline with no battery vs. proposed with a 10 kWh battery. Unlike the existing `ERHeatBeOptModel_*` / `HeatPumpBeOptModel_*` files (EnergyPlus-style export with a `Date/Time` column), these came straight from BEopt's native hourly CSV export, which uses a different structure the loader didn't yet handle. The battery file was replaced once mid-session with a revised (seasonal) charge/discharge strategy, and John expects to iterate on it further.

### Added / Updated
- **`config.py`:** Added a second `EXAMPLE_BUILDINGS` entry — "Birmingham, AL — No Battery vs. 10 kWh Battery (BEopt, 2012)" — baseline `BEOptExample_NoBattery_Birmingham2012_kW`, proposed `BEOptExample_Battery_Birmingham2012_kW`, 2012 weather year, AL. Description updated mid-session to match the final seasonal strategy: winter (Dec/Jan/Feb) charges 12PM–4PM / discharges 5AM–9AM; summer (Jun/Jul/Aug) charges 2AM–6AM / discharges 4PM–8PM.
- **`data_loaders.py`:** Extended `_read_profile_file()` to detect and parse BEopt's native hourly export format — a `wxDVFileHeaderVer.1` version line, then column headers, then two index rows (`0.5` / `1.0`) and a units row before the 8760 hourly data rows. Previously `pd.read_csv()` was called directly, which misparsed this format (the version line was read as a single-column header). Detection is by file signature, not filename, so it applies to any future BEopt native export dropped into `Load_Profiles_raw/`.
- **`tests/test_calculations.py`:** Added `test_beopt_native_export_format_parsing` (validates the new format parses to 8760 rows of sane kW values) and `test_beopt_battery_example_shows_charge_discharge_shift` (validates the battery profile diverges from baseline by more than 1 kW in both directions somewhere in the year, i.e. a real charge spike and discharge dip exist) to `TestLoadProfileIngestion`.
- **`docs/roadmap.md`:** Updated 1.2a (flexible load ingestion, now v2) and 4.3 (example building library) with the new file-format support and second example; updated the 5.4 test-suite count (57 passing) and the Milestone 4 progress-tracking table.
- **`docs/needs_and_gaps.md`:** Updated the "Example building models" priority-matrix row to mention both example pairs.

### Verification
- `python -m pytest`: **57/57 passing** (55 prior + 2 new).
- Manually verified via a Python script that both files parse to clean 8760-row kW series, and that the battery file's charge (elevated draw) / discharge (reduced or negative draw) windows land in the expected hours and are concentrated in Dec/Jan/Feb and Jun/Jul/Aug as described, with a few days of edge-of-season carryover from residual battery state of charge (not a bug).

### Known Gap Noticed (Not Fixed This Session)
- **`docs/needs_and_gaps.md` §7 Phase 1 Gap Mapping** (line ~433) still lists TRC as "missing" and RIM/TRC as merely "Partial," but §2 of the same document and `docs/roadmap.md` both mark the TRC test as done (2.1, v1 Done, well before this session). The two sections of `needs_and_gaps.md` disagree with each other — worth a reconciliation pass next time that doc is touched.

---

## [2026-08-21] — Weather & Peak Diagnostics: Reframed Coincidence Metrics as Peak-to-Average Ratios

### Context
Reviewed the "Peak coincidence metrics" table on the Weather & Peak Diagnostics tab with John. The old "% of annual energy in top N CWFT/price hours" framing was mathematically correct but unintuitive — it conflated genuine peak concentration with the fact that top-N hours are inherently a tiny slice of the year (e.g., 100/8760 ≈ 1.14%), making even a "peaky" load look negligible (~1-3%). The adjacent "Peak vs. Off-Peak Demand Diagnostics" table's ratio framing (average demand during peak hours vs. the rest of the year) read far more intuitively. Decided to standardize on a **peak-to-average ratio** — average demand during the peak window ÷ average demand across the **full year** (not just the "off-peak" remainder) — which behaves like an industry-recognizable coincidence/peaking factor.

### Added / Updated
- **`app.py`:**
  - Replaced the "energy share" calculations (`coinc_50_base`, `coinc_100_base`, `coinc_price_base`, and their `_prop`/`_reduct` counterparts) with peak-to-average ratio calculations (`ratio_50_*`, `ratio_100_*`, `ratio_price_*`) via a new `_peak_to_avg_ratio()` helper: `mean(Load in top-N window) / mean(Load, full year)`.
  - Removed the separate "Peak vs. Off-Peak Demand Diagnostics" table (`demand_diag_table`) — its off-peak-denominator ratio concept is now superseded by the full-year-denominator ratios above, applied across all three peak windows (top-50 CWFT, top-100 CWFT, top-100 price) instead of just one.
  - Merged what were two tables into a single **Peak coincidence metrics** table with columns: peak-to-avg ratio (Top 50 CWFT, ~2 days), peak-to-avg ratio (Top 100 CWFT, ~4 days), peak-to-avg ratio (Top 100 price hours, ~4 days), EPC, and ELCC proxy — one row per resource (Baseline / Proposed / Load reduction).
  - Added hover tooltips (via `st.column_config.TextColumn(help=...)`) on every metric column explaining the exact formula, replacing the old static `st.info()` note.
- **`docs/glossary.md`:** Rewrote the "Coincidence" and "Peak-to-Off-Peak Ratio" (now "Peak-to-Average Ratio") entries to reflect the full-year-average denominator and the reasoning for abandoning the "% of annual energy" framing.
- **`docs/app_code_tour.md`:** Updated the Weather & Peak Diagnostics tab description (§ The 7 Tab Views, item 5) to describe the new merged ratio table instead of "top 50/100 CWFT coincidence percentages ... peak-to-off-peak demand ratios."

### Verification
- `python -m pytest`: **55/55 passing**, no regressions (all touched variables were local to the Weather & Peak Diagnostics tab's display block; no test or other tab referenced the removed `coinc_*`/`avg_offpeak_*`/`ratio_base` names).
- Static analysis (`get_errors`) clean on `app.py` after edits.

---

## [2026-08-18] — Sidebar Reorganization, Example Building Library & Tab Consolidation

### Added / Updated
- **`config.py`:**
  - Added `EXAMPLE_BUILDINGS` list — the first pre-configured example is "Birmingham, AL — Electric Resistance Heat vs. Heat Pump (BEopt, 2012)", pairing the two real BEopt models added to `Load_Profiles_raw/` (`ERHeatBeOptModel_Birmingham2012.csv` baseline / `HeatPumpBeOptModel_Birmingham2012.csv` proposed) with a locked 2012 weather year and AL state.
  - Added `ratio_card_html(label, value, sublabel, passing)` helper plus matching `.kpi-card` CSS classes so ratio-style metric cards (TRC/PCT/RIM) share one consistent visual design instead of ad-hoc inline HTML per card.
- **`app.py`:**
  - **Sidebar rewrite:** converted the flat list of `st.sidebar.markdown("### ...")` sections into 7 collapsible `st.sidebar.expander(...)` groups: *Grid Scenario & Region*, *Demand Response (Optional)*, *Building / Technology & Load Data*, *Grid Valuation Assumptions*, *Retail Tariff (NREL URDB)*, *Financial Assumptions*, *Advanced: Custom Data Files*.
  - The new **Building / Technology & Load Data** section combines: a plain-language description of "the technology" being evaluated, the new **Example Building Library** picker, the existing load-profile source/column selection, and **Weather Alignment Metadata** (folded in from its own former section). When an example is selected, baseline/proposed columns and the weather-year fields auto-populate and lock (`disabled=True`).
  - **Financial Assumptions** now merges the former "Asset Lifetime & NPV" and "Measure & Program Costs" sections into one.
  - **Tab consolidation:** reduced from 9 tabs to 7: `tab_setup` (merges the old EPW Calibration Guide + AMY Weather Generator, moved to the front since they're setup-stage tools), `tab_summary` (Overview Scorecard — KPI cards now use `ratio_card_html()`), `tab_calculator` (Cost-Effectiveness Table, unchanged logic), `tab_charts` (new — merges the old Weekly Analysis Graphs + Grid Avoided Costs charts + Lifetime NPV chart into one tab with sub-groups "Overall Scorecard" → "Utility Cost Tests" → "Customer & Building Load"), `tab_weather_diag` (unchanged), `tab_scenarios` (Scenario Manager — save/compare table only, NPV chart moved to Charts), `tab_diagnostics` (renamed from "Debugger & Top Hours" — validation checks + math trace demoted into a collapsed `st.expander`, Top Stress Hours export is now the main visible content).
  - Significantly reduced emoji usage across sidebar labels, tab labels, welcome screen, calibration guide, and the AMY weather generator helper.
- **`docs/roadmap.md`:**
  - Added Milestone 4 subsection **4.0 UI/UX Layout & Sidebar Cleanup** (marked ✅ Done) documenting the agreed sidebar/tab/styling changes.
  - Annotated **4.3 Pre-Loaded Example Building Library** as ✅ Done for pick-and-view scope (what-if editing deferred to 4.2).
  - Annotated **4.4 Multi-Page App Consideration** as deferred — staying on single-page tabs for now.
  - Updated the Milestone 4 progress tracking table rows for 4.0, 4.3, 4.4.
- **`docs/needs_and_gaps.md`:**
  - Updated the "Example building models" priority-matrix status from 🔴 Not started to 🟡 In progress.
  - Updated §5.5 "Dashboard Tab Organization" with a resolution note (tabs consolidated 9→7, staying on single-page tabs).
- **`docs/app_code_tour.md`:**
  - Rewrote Chapter 7 (Sidebar Controls & Inputs) and Chapter 8 (Results Engine & Dashboard Tabs) to describe the new 7-expander sidebar and 7-tab dashboard, including the Example Building Library. Line-number references are now approximate per the file's own maintenance rules.

### Verification
- `python -m pytest` run after each major edit (sidebar rewrite, tab consolidation, KPI card refactor, emoji cleanup): **55/55 passing** throughout, no regressions.
- Static analysis (`get_errors`) clean on `app.py` and `config.py` after each edit.
- Headless `streamlit run app.py` smoke tests (twice) confirmed the app imports and serves (HTTP 200) with no server-side tracebacks.
- **Caveat:** The AI assistant could not interactively click "Run Valuation Engine" in a browser, so the post-run results tabs (Charts, Diagnostics, etc.) were verified via code review + tests + static analysis only, not a live visual check. **John should click through the consolidated tabs once to confirm they render as expected.**

### Documentation Drift Note
- **`docs/app_annotated.py`** was NOT re-synced this session — it still reflects the pre-2026-08-18 sidebar layout and 9-tab structure. This is now two sessions of drift (the 2026-08-18 weekly-graphs tab split from the entry below, plus today's full sidebar/tab rewrite). A full re-sync pass is recommended before this file is used for onboarding/teaching purposes.

---

## [2026-08-18] — New "Weekly Analysis Graphs" Tab & Customer Operating Cost Chart Row

### Added / Updated
- **`app.py`:**
  - Split the former "🔌 Retail lost revenue & RIM" tab in two: it now shows only the two-sided cost-effectiveness table, while a new **"📈 Weekly Analysis Graphs"** tab (inserted right after it) holds the weekly Building Load vs. Temperature chart and the Grid/Customer Economics chart, along with their week-selector and view-mode controls.
  - Added hourly customer retail rate/cost computation (`hourly_retail_rate`, `baseline_cost_hr`, `proposed_cost_hr`) via `billing.get_hourly_energy_rate()`, applied to whichever tariff is active (packaged URDB, fetched URDB, pasted URDB, or custom flat/demand fallback).
  - Weekly Analysis Graphs tab now also reports total customer retail bill savings for the selected week alongside total grid avoided cost value.
  - Renumbered the `# TAB N:` section comments to account for the new tab.
- **`billing.py`:**
  - Added `get_hourly_energy_rate(datetime_series, rate_json)` — returns an 8760-element array of the marginal (first-tier) retail energy rate ($/kWh) per hour, based on the URDB period mapping. This is a simplified diagnostic helper for hourly charts (ignores monthly cumulative-usage tiering); `calculate_urdb_bill()` remains the source of truth for actual bill totals.
- **`visualizations.py`:**
  - `build_weekly_grid_economics_chart()` is now a 4-row subplot (was 3): added Row 4, **"Customer Retail Operating Cost ($/hr) — Baseline vs. Proposed"**, plotting baseline and proposed hourly customer cost on the primary Y-axis and the applicable retail energy rate ($/kWh) on a secondary Y-axis.
- **`tests/test_calculations.py`:**
  - Added `TestGetHourlyEnergyRate` suite (flat rate, seasonal GP R-31 rate change, no-energy-structure zero case).
  - Updated `test_weekly_grid_economics_chart` trace-count assertions for the new 4th row (+3 traces per mode). Total tests: 55 (55/55 passing).

### Documentation Drift Note
- **`docs/app_annotated.py`** was NOT re-synced this session (still reflects the pre-2026-08-18 tab layout and 3-row grid economics chart). Flagging for a future full re-sync pass; `app.py` line count and structure have since diverged from this file.

---

## [2026-08-11] — MidCase Default, Tab List Wrapping/Scroll & Dual Weekly Analysis Charts

### Added / Updated
- **`config.py`:**
  - Updated `SCENARIO_OPTIONS` order so `"MidCase"` is the default scenario selection at app startup.
  - Enhanced `CUSTOM_CSS` with responsive wrapping (`flex-wrap: wrap !important`) and smooth horizontal scrolling for Streamlit tab list elements (`[data-testid="stTabs"]`, `div[data-baseweb="tab-list"]`).
- **`visualizations.py`:**
  - Added `build_weekly_load_and_temp_chart()` — dual-axis chart comparing Baseline vs Proposed building load (kW) on left Y-axis with Outdoor Air Temperature (°F) on right Y-axis.
  - Added `build_weekly_grid_economics_chart()` — 3-row subplot figure rendering Grid Avoided Costs ($/MWh) on Row 1, Standalone Load Reduction (kW) on Row 2, and **Hourly Operating Cost Delta ($/hr)** on Row 3 (`Load Reduction kW / 1000 * Avoided Cost $/MWh`).
- **`app.py`:**
  - Updated Tab 2 weekly profile analysis section to compute `Hourly_Savings_hr` ($/hr) and display a weekly total avoided cost value summary caption.
- **`tests/test_calculations.py`:**
  - Added unit tests for `build_weekly_load_and_temp_chart()` and `build_weekly_grid_economics_chart()`. Total tests: 52 (52/52 passing).

---

## [2026-08-10] — Excel (.xlsx/.xls) & Multi-Column Load Profile Ingestion

### Added / Updated
- **`data_loaders.py`:**
  - Added `_read_profile_file()` helper supporting both `.csv` and Excel (`.xlsx` / `.xls`) files.
  - Added `_is_date_or_time_col()` helper to automatically identify and strip date/time/hour index columns (e.g. `Date`, `DateTime`, `Time`, `Timestamp`, `Hour`).
  - Updated `load_load_profiles_from_csv()` to handle multi-case files (e.g. 3-column files like `Date` + `Total TES` + `Total No TES` from `HP_TES_DummyData.xlsx`) in both single-file mode and directory scan mode (`Load_Profiles_raw/`).
- **`app.py`:**
  - Updated `Load_Profiles_raw` path check to look for `*.csv`, `*.xlsx`, and `*.xls` files.
  - Updated Single File Mode UI to explicitly ask `"Which column in [file] is the Baseline load?"` and `"Which column in [file] is the Proposed load?"` without using keyword-guessing heuristics. Folder Mode retains smart defaults for multi-model directory scans.
- **`requirements.txt`:** Added `openpyxl>=3.0.0` for Excel file reading.
- **`tests/test_calculations.py`:**
  - Added `test_excel_file_parsing` and updated `test_load_profiles_directory_scan` in `TestLoadProfileIngestion`. Total tests: 50.
- **`docs/roadmap.md` & `docs/needs_and_gaps.md`:** Completed item 1.2b (`🔀 MODIFY` / ✅ **v1 Done**) — replaced keyword guessing in Single File Mode with explicit column selection prompts.

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
