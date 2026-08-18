"""
Shared test fixtures for the Southeast Marginal Cost Valuation Engine.

Provides reusable data objects (DataFrames, arrays, rate structures)
so individual test modules don't need to reconstruct them each time.

Also contains a session-level hook that logs every test run to
tests/test_log.txt (newest entries at the top) for audit trail purposes.
"""

import os
from datetime import datetime
import numpy as np
import pandas as pd
import pytest


# ──────────────────────────────────────────────────────────────────────
#  TEST LOG — prepend timestamped results after each run (newest first)
# ──────────────────────────────────────────────────────────────────────

LOG_FILE = os.path.join(os.path.dirname(__file__), "test_log.txt")


def pytest_sessionfinish(session, exitstatus):
    """
    Called after the entire test session finishes.
    Prepends a timestamped summary block to tests/test_log.txt.
    """
    # Collect results from the session
    passed = session.testscollected - session.testsfailed if hasattr(session, 'testsfailed') else 0
    failed = getattr(session, 'testsfailed', 0)

    # Build per-test detail lines from the session's items
    detail_lines = []
    for item in session.items:
        # Each item has a .nodeid and we can check its report
        status = "?"
        for report_key in ("setup", "call", "teardown"):
            report = getattr(item, f"_report_{report_key}", None)
            if report and report.failed:
                status = "FAIL"
                break
            elif report and report.passed:
                status = "PASS"
        detail_lines.append(f"    {status}  {item.nodeid}")

    # Count from detail lines (more reliable than session attributes)
    pass_count = sum(1 for l in detail_lines if "PASS" in l)
    fail_count = sum(1 for l in detail_lines if "FAIL" in l)
    unknown_count = sum(1 for l in detail_lines if "  ?  " in l)
    total = len(detail_lines)

    status_map = {0: "ALL PASSED", 1: "FAILURES", 2: "INTERRUPTED", 3: "INTERNAL ERROR", 4: "USAGE ERROR", 5: "NO TESTS"}
    overall = status_map.get(exitstatus, f"EXIT CODE {exitstatus}")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Build the log entry
    entry = []
    entry.append(f"{'='*70}")
    entry.append(f"  Test Run: {timestamp}  |  Result: {overall}")
    entry.append(f"  {total} tests: {pass_count} passed, {fail_count} failed" +
                 (f", {unknown_count} unknown" if unknown_count else ""))
    entry.append(f"{'='*70}")
    for line in detail_lines:
        entry.append(line)
    entry.append("")  # blank line separator

    new_entry = "\n".join(entry) + "\n"

    # Prepend to existing log (newest first)
    existing = ""
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            existing = f.read()

    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write(new_entry + existing)


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """
    Store the test report on the item so pytest_sessionfinish
    can read pass/fail status for each individual test.
    """
    outcome = yield
    report = outcome.get_result()
    setattr(item, f"_report_{report.when}", report)


# ──────────────────────────────────────────────────────────────────────
#  CONSTANTS — mirror the production defaults in app.py
# ──────────────────────────────────────────────────────────────────────

DEFAULT_CAP_VALUE = 100.0       # $/kW-yr
DEFAULT_TRANS_VALUE = 15.0      # $/kW-yr
DEFAULT_DIST_VALUE = 15.0       # $/kW-yr
DEFAULT_CARBON_TAX = 30.0       # $/metric ton


# ──────────────────────────────────────────────────────────────────────
#  FIXTURE: Minimal 8760-hour grid DataFrame
# ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def grid_df_8760():
    """
    Builds a synthetic but structurally valid 8760-hour DataFrame
    matching the output schema of load_and_aggregate_data().

    Energy prices follow a deterministic daily sine wave so that
    the top-100 price hours and PCAF weights are reproducible.
    """
    hours = np.arange(8760)

    # Deterministic price: daily sine wave + small seasonal trend
    daily_cycle = 30.0 + 15.0 * np.sin(2 * np.pi * (hours % 24) / 24)
    seasonal_trend = 5.0 * np.sin(2 * np.pi * hours / 8760)
    energy_price = daily_cycle + seasonal_trend

    # Carbon emissions: constant baseline
    carbon_kg = np.full(8760, 400.0)

    # Build the DataFrame
    date_range = pd.date_range(start="2012-01-01 00:00:00", periods=8760, freq="h")

    df = pd.DataFrame({
        "Hour": hours,
        "Datetime": date_range,
        "Cambium_Energy_MWh": energy_price,
        "Cambium_Carbon_kg_MWh": carbon_kg,
    })

    # PCAF: top 100 hours by energy price (mirrors app.py logic)
    top_100_cutoff = df["Cambium_Energy_MWh"].nlargest(100).min()
    df["PCAF_Weight"] = 0.0
    is_peak = df["Cambium_Energy_MWh"] >= top_100_cutoff
    df.loc[is_peak, "PCAF_Weight"] = 1.0 / is_peak.sum()

    return df


@pytest.fixture
def cwft_uniform():
    """Uniform CWFT array (equal weight every hour). Sums to 1.0."""
    return np.full(8760, 1.0 / 8760)


@pytest.fixture
def cwft_peaked():
    """
    CWFT array with weight concentrated in winter mornings (hours 6-9, Jan-Feb)
    and summer afternoons (hours 14-18, Jun-Sep), matching the synthetic
    generator's pattern in app.py.
    """
    cwft = np.zeros(8760)
    hours = np.arange(8760)

    # Winter: Jan-Feb, hours 6-9
    winter_mask = (hours < 1416) & (np.isin(hours % 24, [6, 7, 8, 9]))
    # Summer: Jun-Sep, hours 14-18
    summer_mask = (hours >= 3624) & (hours < 6552) & (np.isin(hours % 24, [14, 15, 16, 17, 18]))

    winter_hours = winter_mask.sum()
    summer_hours = summer_mask.sum()

    cwft[winter_mask] = 0.45 / winter_hours
    cwft[summer_mask] = 0.55 / summer_hours

    return cwft


# ──────────────────────────────────────────────────────────────────────
#  FIXTURE: Rate structures (copied from app.py for test isolation)
# ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def gp_r31_rate():
    """Georgia Power Schedule R-31 URDB JSON (residential, tiered summer)."""
    return {
        "name": "Georgia Power - Schedule R-31 (Residential)",
        "fixedcharge": 16.48,
        "energyratewindow": [
            [0]*24, [0]*24, [0]*24, [0]*24, [0]*24,  # Jan-May (Winter=0)
            [1]*24, [1]*24, [1]*24, [1]*24,           # Jun-Sep (Summer=1)
            [0]*24, [0]*24, [0]*24                    # Oct-Dec (Winter=0)
        ],
        "energyratestructure": [
            [{"rate": 0.142062}],                       # Period 0: Winter flat
            [
                {"max": 650.0, "rate": 0.148101},      # Summer Tier 1
                {"max": 350.0, "rate": 0.216379},      # Summer Tier 2
                {"rate": 0.222371}                      # Summer Tier 3
            ]
        ]
    }


@pytest.fixture
def flat_rate():
    """Simple flat rate for easy hand-verification."""
    return {
        "fixedcharge": 10.0,
        "energyratewindow": [[0]*24]*12,
        "energyratestructure": [[{"rate": 0.10}]]  # $0.10/kWh flat
    }


@pytest.fixture
def flat_rate_with_demand():
    """Flat rate with demand charge for testing demand billing."""
    return {
        "fixedcharge": 10.0,
        "energyratewindow": [[0]*24]*12,
        "energyratestructure": [[{"rate": 0.10}]],
        "demandratewindow": [[0]*24]*12,
        "demandratestructure": [[{"rate": 5.0}]]  # $5.00/kW-month
    }


@pytest.fixture
def constant_load_1kw():
    """Constant 1 kW load for all 8760 hours."""
    return np.ones(8760) * 1.0


@pytest.fixture
def datetime_2012():
    """Standard 2012 datetime series (8760 hours, aligned to Cambium).
    Returns a pd.Series (not DatetimeIndex) to match app.py's usage."""
    return pd.Series(pd.date_range(start="2012-01-01 00:00:00", periods=8760, freq="h"))
