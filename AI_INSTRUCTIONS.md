# AI Instructions: Southeast Marginal Cost Valuation Engine

> **For any AI assistant working on this project.** This file contains standing
> instructions that should be followed in every session. If your AI tool supports
> a project-level instruction file (e.g., `.github/copilot-instructions.md`,
> Cursor rules, or similar), you can point it here or copy the contents.

---

## Living Documentation Maintenance

Whenever code changes are made to any of the project's **source modules** — `app.py`, `calculations.py`, `billing.py`, `data_loaders.py`, or any future extracted modules (e.g., `visualizations.py`, `config.py`) — the following **living documents** in the `docs/` folder must be reviewed and updated as appropriate:

### Documents to Maintain

| Document | Purpose | When to Update |
|----------|---------|----------------|
| `docs/app_annotated.py` | Heavily annotated, runnable teaching copy of `app.py` | When functions are added, removed, renamed, or their logic changes significantly |
| `docs/app_code_tour.md` | Plain-English chapter-by-chapter walkthrough | When sections are reorganized, new major features are added, or line number references drift |
| `docs/needs_and_gaps.md` | Gap analysis mapping current state vs. project vision | When gaps are resolved, new gaps are discovered, or priorities shift |
| `docs/glossary.md` | Definitions and acronyms for all domain terms | When new terms, metrics, or concepts are introduced in code or planning |
| `docs/roadmap.md` | Prioritized development milestones and progress tracking | When milestones are completed, reprioritized, or user-annotated decisions change |
| `docs/CHANGELOG.md` | Change log tracking all documentation modifications | Every time any of the above documents are modified |

### Update Rules

1. **After every code change session:** Check whether the change affects any of the docs above. If yes, update them before closing out the session.
2. **CHANGELOG.md is mandatory:** Every documentation update must be logged in `CHANGELOG.md` with date, what changed, and why.
3. **needs_and_gaps.md status tracking:** When a gap is resolved by code changes, mark it as ✅ resolved with the date and a brief note on what was implemented.
4. **app_annotated.py sync:** When updating, note the "last synced" date and the line count of `app.py` at time of sync. If a full re-sync is not feasible in a session, add a note to `CHANGELOG.md` flagging the drift.
5. **app_code_tour.md line references:** Line number references will naturally drift as code changes. Update them when practical, or note them as approximate.

---

## Roadmap Annotation Processing

At the start of each session working on this project, read `docs/roadmap.md` for any new user-added comments or decision tags. The roadmap uses these conventions:

| Tag | Meaning | AI Action |
|-----|---------|-----------|
| `🔨 BUILD` | We will implement this ourselves | Treat as confirmed scope — proceed when milestone is active |
| `📦 EXTERNAL` | Provided by an external party | Do not build; note as dependency; ask user for status if relevant |
| `🔀 MODIFY` | Directionally right but scope/approach needs to change | Update the item per the user's comment; confirm revision with user |
| `❌ ABANDON` | Dropping this item | Strike or move to "Abandoned" section |
| `⏸️ DEFER` | Pushing to a later phase | Move to later milestone or "Deferred" section |
| `❓ DISCUSS` | Needs team discussion | Flag for user's attention; do not proceed without resolution |

After processing annotations, update the progress tracking table, clear resolved comments, and log changes in `docs/CHANGELOG.md`.

---

## Testing

- **Run `python -m pytest` after code changes.** After modifying any source code (especially `app.py` or any extracted modules), run the test suite to catch regressions.
- **Fix failures before closing the session.** Do not leave the test suite in a broken state.
- **Add tests for new features.** When adding new functionality, add corresponding tests to `tests/test_calculations.py` or create new test modules as appropriate.
- **Test log:** Each test run automatically appends a timestamped entry to `tests/test_log.txt` (newest first). This file is auto-generated — do not edit it manually.

---

## Key Project Context

- **Architecture:** Streamlit UI app (`app.py`) with extracted pure-Python modules:
  - `calculations.py` — grid avoided cost engine + DR dispatch (5-component hourly valuation)
  - `billing.py` — URDB-compliant retail billing engine + pre-packaged tariff schedules
  - `data_loaders.py` — all file I/O: Cambium ingestion, CWFT, load profiles, weather, URDB API, mock generators
  - `visualizations.py` — Plotly chart builder functions (7 chart types, returns `go.Figure`)
  - `config.py` — default parameters, option lists, CSS styling, color palette, constants
- **Stakeholders:** JB (John Bush, project lead), JH (Justin, utility-side partner), SC (cost-effectiveness reviewer), Al/Mitch (external reviewers).
- **Scope:** Southeast US utilities (currently GA & AL, planned TN). Single-family residential for prototyping.
- **See `docs/roadmap.md`** for the full 6-milestone development plan and current status.

---

## Self-Maintenance

- **When adding or removing source modules**, update the Architecture section above and the module list in the Living Documentation trigger (top of this file).
- **When adding new living documents** to `docs/`, add them to the Documents to Maintain table.
- This file is the canonical source of truth. The `AGENTS.md` and `.github/copilot-instructions.md` files just point here — they do not need separate updates.
