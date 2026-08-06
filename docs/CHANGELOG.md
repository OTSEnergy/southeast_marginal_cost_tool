# 📋 Documentation Changelog

This file tracks changes to the living project documents in the `docs/` folder.

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
