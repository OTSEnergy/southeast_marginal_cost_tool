"""
system_stress_data.py — Public-Data System-Stress Capacity-Credit Proxy Data Layer
==================================================================================

Streamlit-free data ingestion, timestamp alignment, quality-gate verification,
caching, and state-to-BA portfolio orchestration for the public-data system-stress
capacity-credit screening proxy.

SOURCES & GOVERNANCE:
    • S1/S2/S3: U.S. EIA Form EIA-930 (Hourly Electric Grid Monitor) via API v2
      (`electricity/rto/region-data` and `electricity/rto/fuel-type-data`) and
      six-month bulk CSV files. Values are hourly integrated MW reported with
      UTC hour-ending timestamps.
    • S4: U.S. EIA Form EIA-861 Annual Electric Power Industry Report (`Sales_Ult_Cust`)
      residential sales by state and Balancing Authority (2016–2024 vintages).

STRICT BOUNDARIES:
    • No Streamlit (`st.*`) imports or UI calls.
    • Never consumes PRICEM data, derives parameters from PRICEM, or applies an
      arbitrary realization factor to mimic proprietary ELCC outputs.
    • Never logs, persists, or exposes user EIA API keys in cache paths, manifests,
      scenario exports, or exception strings.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from calculations import (
    calculate_upper_tail_stress_weights,
    combine_ba_weights_to_state_portfolio,
)
from config import (
    AVAILABLE_EIA_STRESS_YEARS,
    CONTIGUOUS_48_STATES,
    DEFAULT_EIA_STRESS_YEAR,
    DEFAULT_PROFILE_INTERVAL_CONVENTION,
    DEFAULT_SYSTEM_STRESS_PERCENTILE,
    DEFERRED_GEOGRAPHIES,
    EIA_930_EARLIEST_DEMAND_YEAR,
    EIA_930_EARLIEST_FULL_NET_LOAD_YEAR,
    EIA_API_V2_FUEL_TYPE_ROUTE,
    EIA_API_V2_REGION_DATA_ROUTE,
    EIA_API_V2_MAX_PAGE_ROWS,
    IMPLAUSIBLE_SPIKE_MULTIPLIER_MEDIAN,
    MAX_INTERIOR_GAP_HOURS,
    MIN_STATE_BA_SALES_COVERAGE,
    MIN_VALID_HOURLY_FRACTION,
    SOUTHEAST_STATES,
    STATE_BA_CROSSWALK_MANIFEST_PATH,
    STATE_BA_CROSSWALK_PATH,
    STATE_TIMEZONE_METADATA,
    SYSTEM_STRESS_CACHE_DIR,
    SYSTEM_STRESS_CACHE_SCHEMA_VERSION,
)

logger = logging.getLogger(__name__)

# Non-demand / generation-only or foreign BA codes in EIA-861 that do not report
# contiguous U.S. BA system demand in EIA-930 region-data (type='D').
NON_DEMAND_EIA_BAS = {
    "SEPA": "Southeastern Power Administration (generation-only federal marketing agency; no EIA-930 BA demand)",
    "SPA": "Southwestern Power Administration (generation-only federal marketing agency; no EIA-930 BA demand)",
    "NBSO": "New Brunswick System Operator (Canadian balancing authority outside contiguous U.S. EIA-930)",
    "NO BA": "Unassigned / Alaska & Hawaii non-interconnected utility records",
    "NONE": "Unassigned balancing authority record",
}


# ==============================================================================
# 1. API KEY REDACTION & RESOLUTION
# ==============================================================================

def redact_api_key(text: str, api_key: Optional[str] = None) -> str:
    """
    Scrub any `api_key=...` query parameter or literal `api_key` token from a string
    so user credentials never leak into logs, UI warnings, or exception tracebacks.
    """
    if not text:
        return ""
    cleaned = re.sub(r"([?&]api_key=)[^&\s\"']+", r"\1***REDACTED***", str(text), flags=re.IGNORECASE)
    if api_key and str(api_key).strip():
        key_str = str(api_key).strip()
        if len(key_str) >= 4:
            cleaned = cleaned.replace(key_str, "***REDACTED***")
    return cleaned


def resolve_eia_api_key(session_api_key: Optional[str] = None) -> Optional[str]:
    """
    Resolve an EIA API v2 key from the session input or environment (`EIA_API_KEY`).
    Never returns `DEMO_KEY` unless explicitly passed by the caller.
    """
    if session_api_key and str(session_api_key).strip():
        return str(session_api_key).strip()
    env_key = os.environ.get("EIA_API_KEY", "").strip()
    if env_key:
        return env_key
    return None


# ==============================================================================
# 2. EIA-861 STATE-TO-BA CROSSWALK LOADING, RECONCILIATION & VINTAGE SELECTION
# ==============================================================================

def load_state_ba_crosswalk(
    crosswalk_path: str = STATE_BA_CROSSWALK_PATH,
    manifest_path: str = STATE_BA_CROSSWALK_MANIFEST_PATH,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Load the committed EIA-861 state-to-BA residential sales crosswalk CSV and manifest.
    """
    if not os.path.exists(crosswalk_path):
        raise FileNotFoundError(
            f"State-to-BA residential sales crosswalk not found at '{crosswalk_path}'."
        )
    df = pd.read_csv(crosswalk_path)
    if "raw_sales_share" in df.columns and "residential_sales_share" not in df.columns:
        df["residential_sales_share"] = df["raw_sales_share"]
    elif "residential_sales_share" in df.columns and "raw_sales_share" not in df.columns:
        df["raw_sales_share"] = df["residential_sales_share"]
    required_cols = {
        "vintage_year",
        "state",
        "ba_code",
        "residential_sales_mwh",
        "state_total_residential_mwh",
        "residential_sales_share",
        "is_eia930_demand_ba",
    }
    missing_cols = required_cols - set(df.columns)
    if missing_cols:
        raise ValueError(f"Crosswalk CSV '{crosswalk_path}' is missing columns: {sorted(missing_cols)}")

    df["vintage_year"] = pd.to_numeric(df["vintage_year"], errors="raise").astype(int)
    df["state"] = df["state"].astype(str).str.strip().str.upper()
    df["ba_code"] = df["ba_code"].astype(str).str.strip().str.upper()
    df["residential_sales_mwh"] = pd.to_numeric(df["residential_sales_mwh"], errors="coerce").fillna(0.0)
    df["state_total_residential_mwh"] = pd.to_numeric(df["state_total_residential_mwh"], errors="coerce").fillna(0.0)
    df["residential_sales_share"] = pd.to_numeric(df["residential_sales_share"], errors="coerce").fillna(0.0)
    df["is_eia930_demand_ba"] = df["is_eia930_demand_ba"].astype(bool)

    manifest: Dict[str, Any] = {}
    if manifest_path and os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception as exc:
            logger.warning("Failed to parse crosswalk manifest '%s': %s", manifest_path, exc)

    return df, manifest


def build_crosswalk_from_eia861_dataframe(
    df_raw: pd.DataFrame,
    vintage_year: int,
    valid_demand_bas: Optional[Sequence[str]] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Build a validated state-to-BA residential sales crosswalk from an EIA-861
    `Sales_Ult_Cust_YYYY.xlsx` (`States` sheet) DataFrame.

    Deduplication & Reconciliation Contract (Section A.2–A.3):
        • EIA-861 `Sales_Ult_Cust` reports:
          - Part A: Bundled utility retail sales (Energy + Delivery)
          - Part B: Retail Energy Marketers (Energy-only sales) + EIA survey adjustment rows (Utility 99999)
          - Part C: Distribution utilities delivering for retail marketers (Delivery-only sales)
          - Part D: Texas deregulated Retail Electric Providers (ERCOT)
          - Ownership = 'Total' summary rows (where Utility Number is NaN)
        • Summing Part A + B + C would double-count retail choice customers (once on Part B energy
          and once on Part C delivery).
        • Physical energy consumed by ultimate residential customers is `Part in ('A', 'B', 'D')`
          (including `Utility Number == 99999` adjustment rows), which reconciles identically to
          `Part in ('A', 'C', 'D')` across all 48 states.
    """
    df = df_raw.copy()

    # Locate header row if raw Excel sheet with multi-row title header was passed
    if "State" not in df.columns:
        header_idx = None
        for idx in range(min(10, len(df))):
            row_vals = [str(v).strip() for v in df.iloc[idx].values]
            if "State" in row_vals and "Part" in row_vals:
                header_idx = idx
                break
        if header_idx is None:
            raise ValueError("Could not locate EIA-861 header row containing 'State' and 'Part'.")
        cols = [str(v).strip().replace("\n", " ") for v in df.iloc[header_idx].values]
        df = df.iloc[header_idx + 1 :].copy()
        df.columns = cols

    # Identify State, Part, BA_CODE, and Residential Megawatthours columns
    col_names = list(df.columns)
    state_col = next((c for c in col_names if str(c).strip().lower() == "state"), None)
    part_col = next((c for c in col_names if str(c).strip().lower() == "part"), None)
    ba_col = next((c for c in col_names if "ba" in str(c).strip().lower() and "code" in str(c).strip().lower()), None)
    mwh_cols = [c for c in col_names if str(c).strip().lower().startswith("megawatthours")]
    if not (state_col and part_col and ba_col and mwh_cols):
        raise ValueError(f"Missing required EIA-861 columns in DataFrame: found {col_names[:15]}")
    res_mwh_col = mwh_cols[0]

    sub = pd.DataFrame({
        "state": df[state_col].astype(str).str.strip().str.upper(),
        "part": df[part_col].astype(str).str.strip().str.upper(),
        "ba_code": df[ba_col].fillna("No BA").astype(str).str.strip().str.upper(),
        "res_mwh": pd.to_numeric(df[res_mwh_col], errors="coerce").fillna(0.0),
    })
    sub.loc[sub["ba_code"].isin(["NAN", "", "NONE"]), "ba_code"] = "NO BA"
    sub = sub[sub["state"].isin(CONTIGUOUS_48_STATES)]

    abd = sub[sub["part"].isin(["A", "B", "D"])]
    acd = sub[sub["part"].isin(["A", "C", "D"])]

    state_abd = abd.groupby("state")["res_mwh"].sum()
    state_acd = acd.groupby("state")["res_mwh"].sum()
    max_reconcile_diff = float((state_abd - state_acd).abs().max()) if len(state_abd) > 0 else 0.0

    if max_reconcile_diff > 1.0:
        raise ValueError(
            f"EIA-861 vintage {vintage_year} reconciliation check failed: "
            f"max |Part(A+B+D) - Part(A+C+D)| = {max_reconcile_diff:.2f} MWh."
        )

    valid_set = {b.upper() for b in valid_demand_bas} if valid_demand_bas is not None else None
    rows = []
    for st in sorted(CONTIGUOUS_48_STATES):
        st_abd = abd[abd["state"] == st]
        total_mwh = float(st_abd["res_mwh"].sum())
        if total_mwh <= 0.0:
            continue
        ba_totals = st_abd.groupby("ba_code")["res_mwh"].sum()
        for ba, mwh in sorted(ba_totals.items(), key=lambda x: (-x[1], x[0])):
            mwh_f = float(mwh)
            if mwh_f <= 0.0:
                continue
            if valid_set is not None:
                is_demand_ba = ba in valid_set and ba not in NON_DEMAND_EIA_BAS
            else:
                is_demand_ba = ba not in NON_DEMAND_EIA_BAS
            rows.append({
                "vintage_year": int(vintage_year),
                "state": st,
                "ba_code": ba,
                "residential_sales_mwh": round(mwh_f, 3),
                "state_total_residential_mwh": round(total_mwh, 3),
                "residential_sales_share": round(mwh_f / total_mwh, 8),
                "is_eia930_demand_ba": bool(is_demand_ba),
            })

    out_df = pd.DataFrame(rows)
    reconcile_report = {
        "vintage_year": int(vintage_year),
        "states_count": int(out_df["state"].nunique()) if not out_df.empty else 0,
        "max_diff_abd_vs_acd_mwh": max_reconcile_diff,
        "reconciled": bool(max_reconcile_diff <= 1.0),
    }
    return out_df, reconcile_report


def resolve_state_ba_mapping(
    selected_states: Sequence[str],
    stress_year: int,
    crosswalk_df: Optional[pd.DataFrame] = None,
    min_coverage: float = MIN_STATE_BA_SALES_COVERAGE,
    available_bas: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """
    Resolve state-to-BA residential sales shares for `selected_states` and `stress_year`.

    Rules (Section A):
      1. Reject deferred geographies (AK, HI, DC, territories).
      2. Match `stress_year` to the exact EIA-861 vintage when available; otherwise use
         the closest earlier valid vintage and disclose it. Never apply a future vintage
         to an earlier stress year.
      3. Exclude non-demand BAs (e.g. SEPA, NBSO) and any BA not in `available_bas` (if provided).
      4. Require `mapped_share >= min_coverage` (default 95.0%) per state; states below 95%
         fail state qualification (`passed_coverage_gate = False`) and trigger whole-state fallback.
      5. Normalize retained BA shares within each qualifying state and sum repeated BA shares
         across states using equal state portfolio weights (`1 / N_states`).
    """
    if not selected_states:
        raise ValueError("selected_states must not be empty.")

    clean_states = []
    for raw_st in selected_states:
        st = str(raw_st).strip().upper()
        if not st:
            continue
        if st in DEFERRED_GEOGRAPHIES:
            raise ValueError(f"Unsupported geography '{st}': {DEFERRED_GEOGRAPHIES[st]}")
        if st not in CONTIGUOUS_48_STATES:
            raise ValueError(f"Unrecognized state code '{st}'. Must be one of the 48 contiguous U.S. states.")
        if st not in clean_states:
            clean_states.append(st)

    if not clean_states:
        raise ValueError("No valid contiguous U.S. states provided.")

    if crosswalk_df is None:
        crosswalk_df, _ = load_state_ba_crosswalk()

    available_vintages = sorted(int(v) for v in crosswalk_df["vintage_year"].unique())
    if not available_vintages:
        raise ValueError("Crosswalk DataFrame contains no valid vintage years.")

    target_year = int(stress_year)
    if target_year in available_vintages:
        selected_vintage = target_year
        exact_vintage_match = True
        vintage_disclosure = f"Matched exact EIA-861 annual residential sales vintage ({selected_vintage})."
    else:
        earlier_vintages = [v for v in available_vintages if v <= target_year]
        if not earlier_vintages:
            # No earlier or matching vintage exists — never silently apply a future vintage!
            raise ValueError(
                f"No matching or earlier EIA-861 vintage available for stress year {target_year} "
                f"(earliest vintage is {available_vintages[0]}). Future vintages are never applied backward."
            )
        selected_vintage = max(earlier_vintages)
        exact_vintage_match = False
        vintage_disclosure = (
            f"EIA-861 vintage {target_year} not yet published in local crosswalk; using closest earlier "
            f"validated EIA-861 vintage ({selected_vintage}) for state-to-BA residential sales shares."
        )

    v_df = crosswalk_df[crosswalk_df["vintage_year"] == selected_vintage].copy()
    avail_ba_set = {str(b).strip().upper() for b in available_bas} if available_bas is not None else None

    state_details: Dict[str, Dict[str, Any]] = {}
    qualifying_state_ba_shares: Dict[str, Dict[str, float]] = {}
    qualifying_states: List[str] = []
    failed_coverage_states: List[str] = []
    unique_required_bas: set = set()
    warnings_list: List[str] = []

    if not exact_vintage_match:
        warnings_list.append(vintage_disclosure)

    for st in clean_states:
        st_rows = v_df[v_df["state"] == st]
        if st_rows.empty:
            failed_coverage_states.append(st)
            state_details[st] = {
                "state": st,
                "vintage_year": selected_vintage,
                "passed_coverage_gate": False,
                "mapped_share": 0.0,
                "unmapped_share": 1.0,
                "raw_ba_shares": {},
                "retained_ba_shares": {},
                "normalized_ba_shares": {},
                "unmapped_bas": {},
                "failure_reason": f"No EIA-861 residential sales records found for state '{st}' in vintage {selected_vintage}.",
            }
            warnings_list.append(state_details[st]["failure_reason"])
            continue

        raw_ba_shares = {}
        retained_ba_shares = {}
        unmapped_bas = {}

        for _, row in st_rows.iterrows():
            ba = str(row["ba_code"]).strip().upper()
            sh = float(row["residential_sales_share"])
            is_dem = bool(row["is_eia930_demand_ba"])
            raw_ba_shares[ba] = raw_ba_shares.get(ba, 0.0) + sh

            is_usable = is_dem and (avail_ba_set is None or ba in avail_ba_set)
            if is_usable and sh > 0.0:
                retained_ba_shares[ba] = retained_ba_shares.get(ba, 0.0) + sh
            elif sh > 0.0:
                reason = NON_DEMAND_EIA_BAS.get(ba, "BA unavailable or failed EIA-930 quality gate")
                unmapped_bas[ba] = {"share": sh, "reason": reason}

        mapped_share = float(sum(retained_ba_shares.values()))
        unmapped_share = max(0.0, 1.0 - mapped_share)
        passed = bool(mapped_share >= float(min_coverage) - 1e-9)

        if passed and mapped_share > 0.0:
            norm_shares = {ba: sh / mapped_share for ba, sh in retained_ba_shares.items()}
            qualifying_state_ba_shares[st] = norm_shares
            qualifying_states.append(st)
            unique_required_bas.update(norm_shares.keys())
            failure_reason = None
            if unmapped_share > 1e-4:
                unmapped_desc = ", ".join(f"{b} ({info['share']*100:.2f}%)" for b, info in unmapped_bas.items())
                warnings_list.append(
                    f"State {st}: {mapped_share*100:.2f}% of residential sales mapped to EIA-930 demand BAs "
                    f"(>= {min_coverage*100:.1f}% threshold). Unmapped share ({unmapped_share*100:.2f}%: {unmapped_desc}) "
                    f"excluded and retained BA shares normalized to 100%."
                )
        else:
            norm_shares = {}
            failed_coverage_states.append(st)
            unmapped_desc = ", ".join(f"{b} ({info['share']*100:.2f}%)" for b, info in unmapped_bas.items())
            failure_reason = (
                f"State {st} mapped residential-sales share is {mapped_share*100:.2f}%, which is below the "
                f"required {min_coverage*100:.1f}% coverage threshold (unmapped: {unmapped_desc or '100%'}). "
                f"Refusing to represent {st} by its largest single BA; falling back for {st}."
            )
            warnings_list.append(failure_reason)

        state_details[st] = {
            "state": st,
            "vintage_year": selected_vintage,
            "passed_coverage_gate": passed,
            "mapped_share": mapped_share,
            "unmapped_share": unmapped_share,
            "raw_ba_shares": raw_ba_shares,
            "retained_ba_shares": retained_ba_shares,
            "normalized_ba_shares": norm_shares,
            "unmapped_bas": unmapped_bas,
            "failure_reason": failure_reason,
        }

    # Compute deduplicated portfolio-level BA shares across qualifying states
    n_selected = len(clean_states)
    equal_state_weight = 1.0 / n_selected
    deduplicated_portfolio_ba_shares: Dict[str, float] = {}
    for st in qualifying_states:
        for ba, norm_sh in qualifying_state_ba_shares[st].items():
            deduplicated_portfolio_ba_shares[ba] = (
                deduplicated_portfolio_ba_shares.get(ba, 0.0) + equal_state_weight * norm_sh
            )

    return {
        "selected_states": clean_states,
        "stress_year": target_year,
        "selected_vintage": selected_vintage,
        "exact_vintage_match": exact_vintage_match,
        "vintage_disclosure": vintage_disclosure,
        "min_coverage_threshold": float(min_coverage),
        "equal_state_weight": equal_state_weight,
        "state_details": state_details,
        "qualifying_states": qualifying_states,
        "failed_coverage_states": failed_coverage_states,
        "qualifying_state_ba_shares": qualifying_state_ba_shares,
        "deduplicated_portfolio_ba_shares": deduplicated_portfolio_ba_shares,
        "unique_required_bas": sorted(unique_required_bas),
        "warnings": warnings_list,
    }


# ==============================================================================
# 3. PROFILE TIME-BASIS & WEATHER-YEAR ELIGIBILITY CHECKS (SECTION B)
# ==============================================================================

def parse_weather_year_from_case(weather_case: Any) -> Optional[int]:
    """
    Parse a 4-digit historical calendar year (e.g., 2012, 2022) from `weather_case`
    if and only if it represents a specific single calendar year.
    Returns None for synthetic cases ("Extreme Winter", "Extreme Summer") or TMY strings.
    """
    if weather_case is None:
        return None
    s = str(weather_case).strip()
    if any(tok in s.upper() for tok in ["TMY", "EXTREME", "SYNTHETIC", "COMPOSITE", "UNKNOWN"]):
        return None
    if re.fullmatch(r"(19|20)\d{2}", s):
        return int(s)
    m = re.search(r"(?:^|[^0-9])((?:19|20)\d{2})(?:[^0-9]|$)", s)
    if m:
        return int(m.group(1))
    return None


def resolve_profile_time_basis(
    selected_states: Sequence[str],
    utc_offset_hours: Optional[int] = None,
    user_confirmed_offset: bool = False,
    interval_convention: str = DEFAULT_PROFILE_INTERVAL_CONVENTION,
) -> Dict[str, Any]:
    """
    Resolve and validate the building profile's Local Standard Time UTC offset
    and interval timestamp convention (`hour_start` vs `hour_end`).

    Rules (Section B):
      • Autofill standard UTC offset only when all selected states belong to a single
        unambiguous standard time zone.
      • If a state spans multiple time zones (e.g., FL, TN, KY, IN, MI, TX, KS, NE, ND, SD, ID, OR)
        or if multiple selected states span different time zones (e.g., GA + AL),
        require explicit user confirmation (`user_confirmed_offset=True`) before running
        the system-stress method.
    """
    clean_states = [str(s).strip().upper() for s in selected_states if str(s).strip()]
    conv = str(interval_convention).strip().lower()
    if conv not in ("hour_start", "hour_end"):
        raise ValueError(f"interval_convention must be 'hour_start' or 'hour_end' (got '{interval_convention}').")

    multi_tz_states = []
    default_offsets = set()
    tz_notes = []

    for st in clean_states:
        meta = STATE_TIMEZONE_METADATA.get(st)
        if not meta:
            continue
        default_offsets.add(int(meta["default_utc_offset"]))
        if bool(meta.get("multi_tz", meta.get("is_multi_tz", False))):
            multi_tz_states.append(st)
            if meta.get("note"):
                tz_notes.append(f"{st}: {meta['note']}")

    cross_tz_portfolio = len(default_offsets) > 1
    requires_confirmation = bool(len(multi_tz_states) > 0 or cross_tz_portfolio)

    if not requires_confirmation:
        inferred_offset = next(iter(default_offsets)) if default_offsets else -5
        effective_offset = int(utc_offset_hours) if utc_offset_hours is not None else inferred_offset
        return {
            "valid": True,
            "utc_offset_hours": effective_offset,
            "interval_convention": conv,
            "requires_user_confirmation": False,
            "user_confirmed_offset": True,
            "multi_tz_states": [],
            "cross_tz_portfolio": False,
            "tz_notes": tz_notes,
            "reason": f"Unambiguous single standard time zone (UTC{effective_offset:+d}).",
        }

    # Ambiguous time zone (multi-TZ state or multi-TZ state portfolio)
    inferred_offset = int(utc_offset_hours) if utc_offset_hours is not None else (
        STATE_TIMEZONE_METADATA.get(clean_states[0], {}).get("default_utc_offset", -5)
    )
    reasons = []
    if multi_tz_states:
        reasons.append(f"state(s) {', '.join(multi_tz_states)} span multiple time zones")
    if cross_tz_portfolio:
        reasons.append(f"selected states span multiple standard UTC offsets ({sorted(default_offsets)})")
    ambiguity_desc = " and ".join(reasons)

    if not user_confirmed_offset or utc_offset_hours is None:
        return {
            "valid": False,
            "utc_offset_hours": inferred_offset,
            "interval_convention": conv,
            "requires_user_confirmation": True,
            "user_confirmed_offset": False,
            "multi_tz_states": multi_tz_states,
            "cross_tz_portfolio": cross_tz_portfolio,
            "tz_notes": tz_notes,
            "reason": (
                f"Building profile time-basis confirmation required because {ambiguity_desc}. "
                f"Confirm the building profile's fixed Local Standard Time UTC offset to prevent a 1-hour peak alignment shift."
            ),
        }

    return {
        "valid": True,
        "utc_offset_hours": int(utc_offset_hours),
        "interval_convention": conv,
        "requires_user_confirmation": True,
        "user_confirmed_offset": True,
        "multi_tz_states": multi_tz_states,
        "cross_tz_portfolio": cross_tz_portfolio,
        "tz_notes": tz_notes,
        "reason": (
            f"User-confirmed building profile time basis (UTC{int(utc_offset_hours):+d}, {conv}) "
            f"applied across portfolio ({ambiguity_desc})."
        ),
    }


def validate_profile_stress_eligibility(
    selected_states: Sequence[str],
    weather_case: Any,
    profile_year_basis: str = "AMY",
    weather_source: str = "measured_file",
    utc_offset_hours: Optional[int] = None,
    user_confirmed_offset: bool = False,
    interval_convention: str = DEFAULT_PROFILE_INTERVAL_CONVENTION,
    load_df: Optional[pd.DataFrame] = None,
    active_profile_cols: Optional[Sequence[str]] = None,
    stress_year: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Validate whether a building simulation run is eligible for the historical
    EIA-930 system-stress proxy, or must fall back to the weather-based method.

    Enforces:
      • Contiguous 48 U.S. states only (explicitly rejects AK, HI, territories).
      • Profile year basis must be Actual Meteorological Year (`AMY`), not `TMY`/composite/unknown.
      • `weather_case` must map to a single historical year `>= 2016` (the bundled `2012` example
        and synthetic `Extreme Winter` / `Extreme Summer` cases are rejected with explicit warnings).
      • Building profile time basis (UTC offset & interval convention) must be unambiguous or confirmed.
      • Imputed building load profiles are flagged in provenance warnings and never reported as pristine.
    """
    warnings_list: List[str] = []
    clean_states = [str(s).strip().upper() for s in selected_states if str(s).strip()]

    # 1. Check deferred geographies
    deferred = [s for s in clean_states if s in DEFERRED_GEOGRAPHIES]
    if deferred:
        st0 = deferred[0]
        return {
            "eligible": False,
            "fallback_reason": f"Deferred geography ({', '.join(deferred)}): {DEFERRED_GEOGRAPHIES[st0]}",
            "stress_year": None,
            "profile_year_basis": profile_year_basis,
            "time_basis": None,
            "building_imputation_warnings": [],
            "building_imputed_hours": {},
            "synthetic_weather_warning": None,
            "warnings": [f"Deferred geography ({', '.join(deferred)}): {DEFERRED_GEOGRAPHIES[st0]}"],
        }

    invalid_states = [s for s in clean_states if s not in CONTIGUOUS_48_STATES]
    if not clean_states or invalid_states:
        msg = f"Invalid or unsupported state selection: {invalid_states or 'empty'}."
        return {
            "eligible": False,
            "fallback_reason": msg,
            "stress_year": None,
            "profile_year_basis": profile_year_basis,
            "time_basis": None,
            "building_imputation_warnings": [],
            "building_imputed_hours": {},
            "synthetic_weather_warning": None,
            "warnings": [msg],
        }

    # 2. Check building load profile imputation provenance
    building_imputed_hours: Dict[str, int] = {}
    building_imputation_warnings: List[str] = []
    if load_df is not None and hasattr(load_df, "attrs"):
        col_counts = load_df.attrs.get("column_imputed_counts", {})
        cols_to_check = list(active_profile_cols) if active_profile_cols else list(col_counts.keys())
        for c in cols_to_check:
            n_imp = int(col_counts.get(c, 0))
            if n_imp > 0:
                building_imputed_hours[c] = n_imp
                w_msg = (
                    f"Building load profile '{c}' contains {n_imp} imputed hour(s) filled via linear "
                    f"interpolation during ingestion; input profile is not pristine."
                )
                building_imputation_warnings.append(w_msg)
                warnings_list.append(w_msg)

    # 3. Check synthetic Southeast weather provenance for non-Southeast states
    non_se_states = [s for s in clean_states if s not in SOUTHEAST_STATES]
    synthetic_weather_warning = None
    if weather_source == "synthetic_southeast" and non_se_states:
        synthetic_weather_warning = (
            f"Selected state(s) {', '.join(non_se_states)} are outside the Southeast, and no measured "
            f"weather file was found in Weather_Data_raw/ for '{weather_case}'. Synthetic Southeast "
            f"temperature curves are NOT nationally validated for non-Southeast states."
        )
        warnings_list.append(synthetic_weather_warning)

    # 4. Check AMY vs TMY / Composite / Unknown year basis
    basis_norm = str(profile_year_basis).strip().upper()
    if basis_norm != "AMY" and not basis_norm.startswith("AMY"):
        reason = (
            f"Building profile year basis is '{profile_year_basis}' (not a single Actual Meteorological Year / AMY). "
            f"Hourly EIA-930 system stress cannot be chronologically aligned to TMY or multi-year composite weather; "
            f"falling back to weather-based CWF."
        )
        warnings_list.append(reason)
        return {
            "eligible": False,
            "fallback_reason": reason,
            "stress_year": None,
            "profile_year_basis": profile_year_basis,
            "time_basis": None,
            "building_imputation_warnings": building_imputation_warnings,
            "building_imputed_hours": building_imputed_hours,
            "synthetic_weather_warning": synthetic_weather_warning,
            "warnings": warnings_list,
        }

    # 5. Determine effective EIA historical stress year and check weather-year alignment
    parsed_case_year = parse_weather_year_from_case(weather_case)
    effective_stress_year = int(stress_year) if stress_year is not None else parsed_case_year

    if effective_stress_year is None:
        reason = (
            f"Selected weather case '{weather_case}' is a synthetic or non-calendar-year stress scenario "
            f"rather than a historical meteorological year, and no explicit EIA stress year was specified. "
            f"Hourly EIA-930 system stress requires a historical grid year; falling back to weather-based CWF."
        )
        warnings_list.append(reason)
        return {
            "eligible": False,
            "fallback_reason": reason,
            "stress_year": None,
            "profile_year_basis": profile_year_basis,
            "time_basis": None,
            "building_imputation_warnings": building_imputation_warnings,
            "building_imputed_hours": building_imputed_hours,
            "synthetic_weather_warning": synthetic_weather_warning,
            "warnings": warnings_list,
        }

    if effective_stress_year < EIA_930_EARLIEST_DEMAND_YEAR:
        reason = (
            f"Building profile weather year is {effective_stress_year}, which predates Form EIA-930 hourly BA reporting "
            f"(earliest full calendar year is {EIA_930_EARLIEST_DEMAND_YEAR}). Refusing to relabel another year's "
            f"hourly EIA-930 demand onto {effective_stress_year} weather; falling back to weather-based CWF. "
            f"To evaluate system stress from an available EIA-930 historical year, select a stress year (2016–2024)."
        )
        warnings_list.append(reason)
        return {
            "eligible": False,
            "fallback_reason": reason,
            "stress_year": effective_stress_year,
            "profile_year_basis": profile_year_basis,
            "time_basis": None,
            "building_imputation_warnings": building_imputation_warnings,
            "building_imputed_hours": building_imputed_hours,
            "synthetic_weather_warning": synthetic_weather_warning,
            "warnings": warnings_list,
        }

    exact_weather_year_match = True
    weather_misalignment_warning = None
    if parsed_case_year is not None and parsed_case_year != effective_stress_year:
        exact_weather_year_match = False
        weather_misalignment_warning = (
            f"Weather-Year Misalignment: Building load profile is based on {parsed_case_year} weather, "
            f"while EIA-930 system-stress weights are derived from historical {effective_stress_year} grid observations. "
            f"Capacity credit reflects {effective_stress_year} grid stress hours rather than synchronized {parsed_case_year} weather events."
        )
        warnings_list.append(weather_misalignment_warning)

    # 6. Check time-basis (UTC offset & interval convention)
    time_basis = resolve_profile_time_basis(
        selected_states=clean_states,
        utc_offset_hours=utc_offset_hours,
        user_confirmed_offset=user_confirmed_offset,
        interval_convention=interval_convention,
    )
    if not time_basis["valid"]:
        warnings_list.append(time_basis["reason"])
        return {
            "eligible": False,
            "fallback_reason": time_basis["reason"],
            "stress_year": effective_stress_year,
            "exact_weather_year_match": exact_weather_year_match,
            "weather_misalignment_warning": weather_misalignment_warning,
            "profile_year_basis": profile_year_basis,
            "time_basis": time_basis,
            "building_imputation_warnings": building_imputation_warnings,
            "building_imputed_hours": building_imputed_hours,
            "synthetic_weather_warning": synthetic_weather_warning,
            "warnings": warnings_list,
        }

    return {
        "eligible": True,
        "fallback_reason": None,
        "stress_year": effective_stress_year,
        "exact_weather_year_match": exact_weather_year_match,
        "weather_misalignment_warning": weather_misalignment_warning,
        "profile_year_basis": "AMY",
        "time_basis": time_basis,
        "building_imputation_warnings": building_imputation_warnings,
        "building_imputed_hours": building_imputed_hours,
        "synthetic_weather_warning": synthetic_weather_warning,
        "warnings": warnings_list,
    }


# ==============================================================================
# 4. ATOMIC CACHE MANAGEMENT (RAW & ALIGNED SEPARATION)
# ==============================================================================

def _compute_sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _atomic_write_bytes(dest_path: str, payload: bytes) -> str:
    """Write bytes to a temporary file in the same directory and atomically replace `dest_path`."""
    parent = os.path.dirname(os.path.abspath(dest_path))
    os.makedirs(parent, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=parent, prefix=".tmp_", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, dest_path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    return _compute_sha256_bytes(payload)


def get_raw_cache_paths(ba_code: str, year: int, cache_dir: str = SYSTEM_STRESS_CACHE_DIR) -> Tuple[str, str]:
    ba_clean = re.sub(r"[^A-Za-z0-9_-]", "", str(ba_code).strip().upper())
    raw_dir = os.path.join(cache_dir, "raw")
    base = f"eia930_raw_{ba_clean}_{int(year)}_v{SYSTEM_STRESS_CACHE_SCHEMA_VERSION}"
    return os.path.join(raw_dir, f"{base}.csv"), os.path.join(raw_dir, f"{base}_manifest.json")


def get_aligned_cache_paths(
    ba_code: str,
    year: int,
    utc_offset_hours: int,
    interval_convention: str,
    cache_dir: str = SYSTEM_STRESS_CACHE_DIR,
) -> Tuple[str, str]:
    ba_clean = re.sub(r"[^A-Za-z0-9_-]", "", str(ba_code).strip().upper())
    conv_clean = re.sub(r"[^a-z0-9_]", "", str(interval_convention).strip().lower())
    off_str = f"utc{int(utc_offset_hours):+d}".replace("+", "p").replace("-", "m")
    aligned_dir = os.path.join(cache_dir, "aligned")
    base = f"eia930_aligned_{ba_clean}_{int(year)}_{off_str}_{conv_clean}_v{SYSTEM_STRESS_CACHE_SCHEMA_VERSION}"
    return os.path.join(aligned_dir, f"{base}.csv"), os.path.join(aligned_dir, f"{base}_manifest.json")


def save_cache_bundle(df: pd.DataFrame, csv_path: str, manifest_path: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
    """
    Atomically write a DataFrame CSV and its provenance manifest (including SHA-256 hash).
    Ensures no API keys are ever written to the manifest.
    """
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    csv_sha256 = _atomic_write_bytes(csv_path, csv_bytes)

    clean_meta = {}
    for k, v in metadata.items():
        if "api_key" in str(k).lower():
            continue
        if isinstance(v, str):
            clean_meta[k] = redact_api_key(v)
        else:
            clean_meta[k] = v

    manifest = {
        "schema_version": SYSTEM_STRESS_CACHE_SCHEMA_VERSION,
        "saved_at_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "csv_filename": os.path.basename(csv_path),
        "csv_sha256": csv_sha256,
        "row_count": int(len(df)),
        **clean_meta,
    }
    manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
    _atomic_write_bytes(manifest_path, manifest_bytes)
    return manifest


def load_cache_bundle(csv_path: str, manifest_path: str) -> Optional[Tuple[pd.DataFrame, Dict[str, Any]]]:
    """
    Load and verify a cached CSV + manifest bundle. Returns None if missing, corrupt,
    schema-mismatched, or SHA-256 verification fails.
    """
    if not (os.path.exists(csv_path) and os.path.exists(manifest_path)):
        return None
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        if manifest.get("schema_version") != SYSTEM_STRESS_CACHE_SCHEMA_VERSION:
            return None
        with open(csv_path, "rb") as f:
            csv_bytes = f.read()
        actual_sha = _compute_sha256_bytes(csv_bytes)
        expected_sha = manifest.get("csv_sha256")
        if expected_sha and actual_sha != expected_sha:
            logger.warning("Cache SHA-256 mismatch for '%s'; ignoring corrupt cache.", csv_path)
            return None
        df = pd.read_csv(csv_path)
        return df, manifest
    except Exception as exc:
        logger.warning("Failed to load cache bundle '%s': %s", csv_path, exc)
        return None


# ==============================================================================
# 5. EIA API V2 PAGINATION CLIENT & SIX-MONTH BULK CSV PARSER
# ==============================================================================

def fetch_eia_rto_paginated(
    route_url: str,
    api_key: str,
    respondent_ba: str,
    start_utc: str,
    end_utc: str,
    data_types: Optional[Sequence[str]] = None,
    fuel_types: Optional[Sequence[str]] = None,
    page_size: int = EIA_API_V2_MAX_PAGE_ROWS,
    timeout: int = 30,
    max_retries: int = 2,
    opener: Optional[Callable[..., Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch all hourly pages from an EIA API v2 RTO endpoint with deterministic sorting
    (`sort[0][column]=period&sort[0][direction]=asc`) and `length=5000` pagination.
    All API keys are strictly redacted from any raised error messages.
    """
    if not api_key or not str(api_key).strip():
        raise ValueError("An EIA API v2 key is required for live EIA-930 data requests.")

    key_clean = str(api_key).strip()
    ba_clean = str(respondent_ba).strip().upper()
    page_len = min(max(1, int(page_size)), EIA_API_V2_MAX_PAGE_ROWS)
    urlopen_fn = opener or urllib.request.urlopen

    all_rows: List[Dict[str, Any]] = []
    offset = 0
    total_available: Optional[int] = None

    while True:
        query_pairs = [
            ("api_key", key_clean),
            ("frequency", "hourly"),
            ("data[0]", "value"),
            ("facets[respondent][]", ba_clean),
            ("start", start_utc),
            ("end", end_utc),
            ("sort[0][column]", "period"),
            ("sort[0][direction]", "asc"),
            ("offset", str(offset)),
            ("length", str(page_len)),
        ]
        if data_types:
            for dt in data_types:
                query_pairs.append(("facets[type][]", str(dt).strip().upper()))
        if fuel_types:
            for ft in fuel_types:
                query_pairs.append(("facets[fueltype][]", str(ft).strip().upper()))

        query_str = urllib.parse.urlencode(query_pairs)
        full_url = f"{route_url}?{query_str}"

        last_err: Optional[Exception] = None
        payload: Optional[Dict[str, Any]] = None

        for attempt in range(max_retries + 1):
            try:
                req = urllib.request.Request(
                    full_url,
                    headers={"User-Agent": "Southeast-Marginal-Cost-Tool/1.0 (Public-Data-System-Stress-Proxy)"},
                )
                with urlopen_fn(req, timeout=timeout) as resp:
                    raw_body = resp.read().decode("utf-8")
                    payload = json.loads(raw_body)
                break
            except Exception as exc:
                last_err = exc
                # Retry only on transient HTTP 429/5xx or timeout
                code = getattr(exc, "code", None)
                if attempt < max_retries and (code in (429, 500, 502, 503, 504) or isinstance(exc, TimeoutError)):
                    time.sleep(0.5 * (attempt + 1))
                    continue
                break

        if payload is None:
            safe_msg = redact_api_key(str(last_err), key_clean)
            raise RuntimeError(f"EIA API v2 request failed for BA '{ba_clean}' at offset {offset}: {safe_msg}")

        resp_block = payload.get("response", {})
        if total_available is None:
            try:
                total_available = int(resp_block.get("total", 0))
            except (TypeError, ValueError):
                total_available = 0

        data_rows = resp_block.get("data", [])
        if not isinstance(data_rows, list) or len(data_rows) == 0:
            break

        all_rows.extend(data_rows)
        offset += len(data_rows)

        if len(data_rows) < page_len or (total_available is not None and offset >= total_available):
            break

    return all_rows


def _parse_numeric_eia_value(val: Any) -> float:
    """Parse EIA API v2 numeric string or number; return np.nan on null/missing."""
    if val is None:
        return np.nan
    s = str(val).strip()
    if s == "" or s.lower() in ("none", "null", "nan", "na", "n/a"):
        return np.nan
    try:
        return float(s)
    except (TypeError, ValueError):
        return np.nan


def fetch_eia_ba_year_raw(
    ba_code: str,
    year: int,
    api_key: str,
    timeout: int = 30,
    max_retries: int = 2,
    opener: Optional[Callable[..., Any]] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Fetch a full calendar year of hourly EIA-930 data for `ba_code` in `year`,
    including UTC boundary padding (`Dec 31 of year-1 00:00 UTC` through
    `Jan 2 of year+1 12:00 UTC`) so converting UTC hour-ending timestamps to any
    contiguous U.S. Local Standard Time (`UTC-5` to `UTC-8`) never leaves boundary gaps.
    """
    ba_clean = str(ba_code).strip().upper()
    yr = int(year)
    start_utc = f"{yr - 1}-12-31T00"
    end_utc = f"{yr + 1}-01-02T12"

    # 1. Fetch hourly BA system demand (type='D')
    demand_rows = fetch_eia_rto_paginated(
        route_url=EIA_API_V2_REGION_DATA_ROUTE,
        api_key=api_key,
        respondent_ba=ba_clean,
        start_utc=start_utc,
        end_utc=end_utc,
        data_types=["D"],
        timeout=timeout,
        max_retries=max_retries,
        opener=opener,
    )

    if not demand_rows:
        raise ValueError(f"No EIA-930 hourly demand records (type='D') returned for BA '{ba_clean}' in year {yr}.")

    dem_records = []
    for r in demand_rows:
        p = str(r.get("period", "")).strip()
        if p:
            dem_records.append({"period_utc": p, "demand_mw": _parse_numeric_eia_value(r.get("value"))})
    df_dem = pd.DataFrame(dem_records)

    # 2. Fetch wind (WND) and solar (SUN) hourly generation when year >= 2019
    # (Form EIA-930 fuel-type generation began July 1, 2018; 2019 is first full calendar year)
    fuel_rows: List[Dict[str, Any]] = []
    fuel_fetch_status = "not_requested_pre_2019"
    if yr >= EIA_930_EARLIEST_FULL_NET_LOAD_YEAR:
        try:
            fuel_rows = fetch_eia_rto_paginated(
                route_url=EIA_API_V2_FUEL_TYPE_DATA_ROUTE_COMPAT(),
                api_key=api_key,
                respondent_ba=ba_clean,
                start_utc=start_utc,
                end_utc=end_utc,
                fuel_types=["SUN", "WND"],
                timeout=timeout,
                max_retries=max_retries,
                opener=opener,
            )
            fuel_fetch_status = "fetched" if fuel_rows else "empty_response"
        except Exception as exc:
            fuel_fetch_status = f"fetch_error: {redact_api_key(str(exc), api_key)}"

    if fuel_rows:
        wnd_records = []
        sun_records = []
        for r in fuel_rows:
            p = str(r.get("period", "")).strip()
            ft = str(r.get("fueltype", "")).strip().upper()
            val = _parse_numeric_eia_value(r.get("value"))
            if not p:
                continue
            if ft == "WND":
                wnd_records.append({"period_utc": p, "wind_mw": val})
            elif ft == "SUN":
                sun_records.append({"period_utc": p, "solar_mw": val})

        df_wnd = pd.DataFrame(wnd_records) if wnd_records else pd.DataFrame(columns=["period_utc", "wind_mw"])
        df_sun = pd.DataFrame(sun_records) if sun_records else pd.DataFrame(columns=["period_utc", "solar_mw"])

        # Merge on period_utc while preserving any duplicate timestamps in df_dem for quality-gate inspection
        if not df_wnd.empty:
            df_wnd_dedup = df_wnd.groupby("period_utc", as_index=False)["wind_mw"].first()
            df_dem = df_dem.merge(df_wnd_dedup, on="period_utc", how="left")
        else:
            df_dem["wind_mw"] = np.nan

        if not df_sun.empty:
            df_sun_dedup = df_sun.groupby("period_utc", as_index=False)["solar_mw"].first()
            df_dem = df_dem.merge(df_sun_dedup, on="period_utc", how="left")
        else:
            df_dem["solar_mw"] = np.nan
    else:
        df_dem["wind_mw"] = np.nan
        df_dem["solar_mw"] = np.nan

    meta = {
        "ba_code": ba_clean,
        "year": yr,
        "source": "eia_api_v2",
        "start_utc_requested": start_utc,
        "end_utc_requested": end_utc,
        "demand_row_count": int(len(demand_rows)),
        "fuel_row_count": int(len(fuel_rows)),
        "fuel_fetch_status": fuel_fetch_status,
    }
    return df_dem, meta


def EIA_API_V2_FUEL_TYPE_DATA_ROUTE_COMPAT() -> str:
    return EIA_API_V2_FUEL_TYPE_ROUTE


def parse_eia_930_six_month_csv(
    csv_frames_or_paths: Sequence[Union[str, pd.DataFrame]],
    ba_code: str,
    year: int,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Parse one or more EIA-930 six-month bulk `BALANCE` CSV files (or DataFrames)
    into the standardized raw UTC hour-ending schema (`period_utc`, `demand_mw`,
    `wind_mw`, `solar_mw`).
    """
    ba_clean = str(ba_code).strip().upper()
    frames = []
    for item in csv_frames_or_paths:
        if isinstance(item, pd.DataFrame):
            frames.append(item.copy())
        else:
            frames.append(pd.read_csv(str(item), low_memory=False))

    if not frames:
        raise ValueError("No EIA-930 bulk CSV data provided.")

    full_df = pd.concat(frames, ignore_index=True)
    ba_col = next((c for c in full_df.columns if str(c).strip().lower() in ("balancing authority", "respondent", "ba_code")), None)
    utc_col = next((c for c in full_df.columns if "utc time at end of hour" in str(c).strip().lower()), None)
    dem_col = next((c for c in full_df.columns if str(c).strip().lower() == "demand (mw)"), None)
    sun_col = next((c for c in full_df.columns if "from solar" in str(c).strip().lower()), None)
    wnd_col = next((c for c in full_df.columns if "from wind" in str(c).strip().lower()), None)

    if not (ba_col and utc_col and dem_col):
        raise ValueError(f"EIA-930 six-month CSV missing required columns: found {list(full_df.columns)[:10]}")

    sub = full_df[full_df[ba_col].astype(str).str.strip().str.upper() == ba_clean].copy()
    if sub.empty:
        raise ValueError(f"BA '{ba_clean}' not found in provided EIA-930 six-month CSV file(s).")

    utc_dt = pd.to_datetime(sub[utc_col], format="mixed", errors="coerce")
    valid_ts = ~utc_dt.isna()
    sub = sub.loc[valid_ts].copy()
    utc_dt = utc_dt.loc[valid_ts]

    out = pd.DataFrame({
        "period_utc": utc_dt.dt.strftime("%Y-%m-%dT%H"),
        "demand_mw": pd.to_numeric(
            sub[dem_col].astype(str).str.replace(",", "", regex=False), errors="coerce"
        ).to_numpy(),
        "wind_mw": (
            pd.to_numeric(sub[wnd_col].astype(str).str.replace(",", "", regex=False), errors="coerce").to_numpy()
            if wnd_col
            else np.nan
        ),
        "solar_mw": (
            pd.to_numeric(sub[sun_col].astype(str).str.replace(",", "", regex=False), errors="coerce").to_numpy()
            if sun_col
            else np.nan
        ),
    })

    meta = {
        "ba_code": ba_clean,
        "year": int(year),
        "source": "eia_930_six_month_bulk_csv",
        "demand_row_count": int(len(out)),
        "has_wind_column": bool(wnd_col is not None),
        "has_solar_column": bool(sun_col is not None),
    }
    return out, meta


# ==============================================================================
# 6. TIMESTAMP ALIGNMENT, LEAP-DAY REMOVAL & QUALITY GATE ENGINE
# ==============================================================================

def _parse_eia_period_utc(period_series: pd.Series) -> pd.Series:
    """Parse EIA-930 `YYYY-MM-DDTHH` UTC hour-ending strings into naive UTC timestamps."""
    s = period_series.astype(str).str.strip()
    return pd.to_datetime(s, format="%Y-%m-%dT%H", errors="coerce")


def _evaluate_series_quality_gate(
    arr: np.ndarray,
    series_name: str,
    min_valid_fraction: float = MIN_VALID_HOURLY_FRACTION,
    max_interior_gap: int = MAX_INTERIOR_GAP_HOURS,
    check_positive_and_spikes: bool = True,
) -> Dict[str, Any]:
    """
    Evaluate an 8,760-hour aligned series against data-quality gates:
      1. Boundary hours (index 0 and index 8759) must be finite (no boundary extrapolation).
      2. Fraction of original valid finite observations must be >= `min_valid_fraction` (99.5%).
      3. No consecutive missing gap may exceed `max_interior_gap` (2 hours).
      4. If `check_positive_and_spikes=True` (for demand):
         - Non-positive demand values (<= 0 MW) are treated as invalid/corrupt before gap checks.
         - Checks for implausible single-hour data corruption spikes (> 10x median AND > 3x 2nd highest hour)
           without winsorizing real extreme weather peaks.
      5. Linearly interpolates isolated interior gaps <= 2 hours and returns the cleaned array
         plus exact imputed hour indices.
    """
    n = len(arr)
    work = np.asarray(arr, dtype=float).copy()

    non_positive_count = 0
    if check_positive_and_spikes:
        bad_non_pos = np.isfinite(work) & (work <= 0.0)
        non_positive_count = int(np.sum(bad_non_pos))
        if non_positive_count > 0:
            work[bad_non_pos] = np.nan

    is_valid = np.isfinite(work)
    n_valid = int(np.sum(is_valid))
    n_missing = int(n - n_valid)
    valid_fraction = float(n_valid / n) if n > 0 else 0.0

    # Check boundary hours (no boundary extrapolation allowed)
    boundary_missing = bool(n == 0 or not is_valid[0] or not is_valid[-1])

    # Compute maximum consecutive missing gap
    max_gap = 0
    cur_gap = 0
    for v in is_valid:
        if not v:
            cur_gap += 1
            if cur_gap > max_gap:
                max_gap = cur_gap
        else:
            cur_gap = 0

    if boundary_missing:
        return {
            "passed": False,
            "series_name": series_name,
            "failure_reason": f"{series_name}: missing boundary hour(s) at start or end of local calendar year (boundary extrapolation is prohibited).",
            "valid_count": n_valid,
            "missing_count": n_missing,
            "valid_fraction": valid_fraction,
            "max_consecutive_gap": max_gap,
            "non_positive_count": non_positive_count,
            "imputed_indices": [],
            "cleaned_array": None,
            "outlier_flagged": False,
        }

    if valid_fraction < float(min_valid_fraction) - 1e-12:
        return {
            "passed": False,
            "series_name": series_name,
            "failure_reason": (
                f"{series_name}: valid hourly coverage is {valid_fraction*100:.2f}% ({n_valid}/{n}), "
                f"below the required {min_valid_fraction*100:.2f}% minimum threshold."
            ),
            "valid_count": n_valid,
            "missing_count": n_missing,
            "valid_fraction": valid_fraction,
            "max_consecutive_gap": max_gap,
            "non_positive_count": non_positive_count,
            "imputed_indices": [],
            "cleaned_array": None,
            "outlier_flagged": False,
        }

    if max_gap > int(max_interior_gap):
        return {
            "passed": False,
            "series_name": series_name,
            "failure_reason": (
                f"{series_name}: found consecutive missing gap of {max_gap} hours, "
                f"exceeding the maximum allowed interior interpolation gap of {max_interior_gap} hours."
            ),
            "valid_count": n_valid,
            "missing_count": n_missing,
            "valid_fraction": valid_fraction,
            "max_consecutive_gap": max_gap,
            "non_positive_count": non_positive_count,
            "imputed_indices": [],
            "cleaned_array": None,
            "outlier_flagged": False,
        }

    # Check implausible data-corruption spikes on demand (without winsorizing real peaks)
    outlier_flagged = False
    if check_positive_and_spikes and n_valid >= 10:
        valid_vals = work[is_valid]
        med = float(np.median(valid_vals))
        sorted_vals = np.sort(valid_vals)
        max_val = float(sorted_vals[-1])
        second_max = float(sorted_vals[-2]) if len(sorted_vals) >= 2 else max_val
        if med <= 0.0:
            return {
                "passed": False,
                "series_name": series_name,
                "failure_reason": f"{series_name}: non-positive median ({med:.2f} MW).",
                "valid_count": n_valid,
                "missing_count": n_missing,
                "valid_fraction": valid_fraction,
                "max_consecutive_gap": max_gap,
                "non_positive_count": non_positive_count,
                "imputed_indices": [],
                "cleaned_array": None,
                "outlier_flagged": True,
            }
        if max_val > IMPLAUSIBLE_SPIKE_MULTIPLIER_MEDIAN * med and max_val > 3.0 * max(second_max, 1.0):
            return {
                "passed": False,
                "series_name": series_name,
                "failure_reason": (
                    f"{series_name}: implausible single-hour data-corruption spike detected "
                    f"(max={max_val:.1f} MW vs median={med:.1f} MW and 2nd-highest={second_max:.1f} MW)."
                ),
                "valid_count": n_valid,
                "missing_count": n_missing,
                "valid_fraction": valid_fraction,
                "max_consecutive_gap": max_gap,
                "non_positive_count": non_positive_count,
                "imputed_indices": [],
                "cleaned_array": None,
                "outlier_flagged": True,
            }

    imputed_indices = [int(i) for i in np.where(~is_valid)[0]]
    if imputed_indices:
        cleaned = pd.Series(work).interpolate(method="linear", limit=int(max_interior_gap), limit_area="inside").to_numpy(dtype=float)
    else:
        cleaned = work

    if not np.isfinite(cleaned).all():
        return {
            "passed": False,
            "series_name": series_name,
            "failure_reason": f"{series_name}: NaN values remained after interior linear interpolation.",
            "valid_count": n_valid,
            "missing_count": n_missing,
            "valid_fraction": valid_fraction,
            "max_consecutive_gap": max_gap,
            "non_positive_count": non_positive_count,
            "imputed_indices": imputed_indices,
            "cleaned_array": None,
            "outlier_flagged": outlier_flagged,
        }

    return {
        "passed": True,
        "series_name": series_name,
        "failure_reason": None,
        "valid_count": n_valid,
        "missing_count": n_missing,
        "valid_fraction": valid_fraction,
        "max_consecutive_gap": max_gap,
        "non_positive_count": non_positive_count,
        "imputed_indices": imputed_indices,
        "cleaned_array": cleaned,
        "outlier_flagged": outlier_flagged,
    }


def align_and_qualify_ba_series(
    raw_df: pd.DataFrame,
    ba_code: str,
    year: int,
    utc_offset_hours: int,
    interval_convention: str = DEFAULT_PROFILE_INTERVAL_CONVENTION,
    percentile: float = DEFAULT_SYSTEM_STRESS_PERCENTILE,
    known_zero_vre_bas: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """
    Convert raw UTC hour-ending EIA-930 observations for `ba_code` and `year` into
    an 8,760-hour local-standard-time aligned series, enforce all data-quality gates,
    select `net_demand` vs `gross_demand`, and compute BA upper-tail exceedance weights.

    Timestamp Conversion Contract (Section B):
      1. `utc_hour_ending` parsed from `period_utc`.
      2. `interval_start_utc = utc_hour_ending - 1 hour`.
      3. `local_interval_start = interval_start_utc + utc_offset_hours`.
         `local_hour_ending = utc_hour_ending + utc_offset_hours`.
      4. If `interval_convention == "hour_start"`, match `local_interval_start` to the
         local calendar year (`Jan 1 00:00` .. `Dec 31 23:00`).
         If `interval_convention == "hour_end"`, match `local_hour_ending` to the
         local calendar year (`Jan 1 00:00` .. `Dec 31 23:00`).
      5. Deliberately drop local February 29 (24 hours) after UTC-to-local shift in leap years,
         yielding exactly 8,760 hours without shifting March–December or truncating December 31.
    """
    ba_clean = str(ba_code).strip().upper()
    yr = int(year)
    off_hrs = int(utc_offset_hours)
    conv = str(interval_convention).strip().lower()
    if conv not in ("hour_start", "hour_end"):
        raise ValueError(f"interval_convention must be 'hour_start' or 'hour_end' (got '{interval_convention}').")

    if raw_df is None or raw_df.empty or "period_utc" not in raw_df.columns or "demand_mw" not in raw_df.columns:
        return {
            "qualified": False,
            "ba_code": ba_clean,
            "year": yr,
            "failure_reason": f"BA '{ba_clean}' ({yr}): raw DataFrame is empty or missing required columns.",
        }

    df = raw_df.copy()
    df["utc_hour_ending"] = _parse_eia_period_utc(df["period_utc"])
    df = df.dropna(subset=["utc_hour_ending"]).copy()
    if df.empty:
        return {
            "qualified": False,
            "ba_code": ba_clean,
            "year": yr,
            "failure_reason": f"BA '{ba_clean}' ({yr}): no valid UTC timestamps found.",
        }

    df["demand_mw"] = pd.to_numeric(df["demand_mw"], errors="coerce")
    df["wind_mw"] = pd.to_numeric(df["wind_mw"], errors="coerce") if "wind_mw" in df.columns else np.nan
    df["solar_mw"] = pd.to_numeric(df["solar_mw"], errors="coerce") if "solar_mw" in df.columns else np.nan

    # Check duplicate UTC timestamps
    dup_mask = df.duplicated(subset=["utc_hour_ending"], keep=False)
    duplicate_timestamp_count = int(dup_mask.sum())
    if duplicate_timestamp_count > 0:
        dup_sub = df.loc[dup_mask]
        for ts, grp in dup_sub.groupby("utc_hour_ending"):
            for col in ["demand_mw", "wind_mw", "solar_mw"]:
                valid_vals = grp[col].dropna().to_numpy(dtype=float)
                if len(valid_vals) > 1 and not np.allclose(valid_vals, valid_vals[0], rtol=1e-5, atol=1e-3):
                    return {
                        "qualified": False,
                        "ba_code": ba_clean,
                        "year": yr,
                        "failure_reason": (
                            f"BA '{ba_clean}' ({yr}): conflicting duplicate values on UTC timestamp "
                            f"'{ts}' in column '{col}' ({valid_vals.tolist()})."
                        ),
                    }
        df = df.drop_duplicates(subset=["utc_hour_ending"], keep="first").copy()

    # Step 1 & 2: Compute UTC interval start and shift to Local Standard Time
    df["interval_start_utc"] = df["utc_hour_ending"] - pd.Timedelta(hours=1)
    df["local_interval_start"] = df["interval_start_utc"] + pd.Timedelta(hours=off_hrs)
    df["local_hour_ending"] = df["utc_hour_ending"] + pd.Timedelta(hours=off_hrs)

    align_col = "local_interval_start" if conv == "hour_start" else "local_hour_ending"

    # Build full local calendar year hourly grid (8,760 in non-leap year, 8,784 in leap year)
    full_local_index = pd.date_range(
        start=f"{yr}-01-01 00:00:00",
        end=f"{yr}-12-31 23:00:00",
        freq="h",
    )
    leap_day_mask = (full_local_index.month == 2) & (full_local_index.day == 29)
    leap_hours_removed = int(np.sum(leap_day_mask))
    target_local_index = full_local_index[~leap_day_mask]

    if len(target_local_index) != 8760:
        raise RuntimeError(f"Expected 8,760 target local hours after Feb 29 removal, got {len(target_local_index)}.")

    aligned_df = pd.DataFrame({align_col: target_local_index}).merge(
        df[[align_col, "utc_hour_ending", "interval_start_utc", "demand_mw", "wind_mw", "solar_mw"]],
        on=align_col,
        how="left",
    )

    # Evaluate Demand Quality Gate
    dem_gate = _evaluate_series_quality_gate(
        aligned_df["demand_mw"].to_numpy(dtype=float),
        series_name=f"{ba_clean} demand_mw",
        min_valid_fraction=MIN_VALID_HOURLY_FRACTION,
        max_interior_gap=MAX_INTERIOR_GAP_HOURS,
        check_positive_and_spikes=True,
    )
    if not dem_gate["passed"]:
        return {
            "qualified": False,
            "ba_code": ba_clean,
            "year": yr,
            "failure_reason": dem_gate["failure_reason"],
            "demand_quality": dem_gate,
        }

    demand_clean = dem_gate["cleaned_array"]

    # Evaluate Wind & Solar for Net Demand vs Gross Demand Fallback (Section D)
    zero_vre_set = {str(b).strip().upper() for b in (known_zero_vre_bas or [])}
    verified_zero_vre = ba_clean in zero_vre_set

    wind_raw = aligned_df["wind_mw"].to_numpy(dtype=float)
    solar_raw = aligned_df["solar_mw"].to_numpy(dtype=float)

    wind_gate = _evaluate_series_quality_gate(
        wind_raw,
        series_name=f"{ba_clean} wind_mw",
        min_valid_fraction=MIN_VALID_HOURLY_FRACTION,
        max_interior_gap=MAX_INTERIOR_GAP_HOURS,
        check_positive_and_spikes=False,
    )
    solar_gate = _evaluate_series_quality_gate(
        solar_raw,
        series_name=f"{ba_clean} solar_mw",
        min_valid_fraction=MIN_VALID_HOURLY_FRACTION,
        max_interior_gap=MAX_INTERIOR_GAP_HOURS,
        check_positive_and_spikes=False,
    )

    gross_demand_fallback_reason: Optional[str] = None
    if wind_gate["passed"] and solar_gate["passed"]:
        wind_clean = wind_gate["cleaned_array"]
        solar_clean = solar_gate["cleaned_array"]
        signal_type = "net_demand"
        signal_mw = demand_clean - wind_clean - solar_clean
    elif verified_zero_vre and (wind_gate["passed"] or solar_gate["passed"] or yr >= EIA_930_EARLIEST_FULL_NET_LOAD_YEAR):
        wind_clean = wind_gate["cleaned_array"] if wind_gate["passed"] else np.zeros(8760, dtype=float)
        solar_clean = solar_gate["cleaned_array"] if solar_gate["passed"] else np.zeros(8760, dtype=float)
        signal_type = "net_demand"
        signal_mw = demand_clean - wind_clean - solar_clean
    else:
        wind_clean = np.full(8760, np.nan, dtype=float)
        solar_clean = np.full(8760, np.nan, dtype=float)
        signal_type = "gross_demand"
        signal_mw = demand_clean.copy()
        if yr < EIA_930_EARLIEST_FULL_NET_LOAD_YEAR:
            gross_demand_fallback_reason = (
                f"BA '{ba_clean}' ({yr}): EIA-930 hourly wind/solar generation reporting began July 1, 2018; "
                f"using gross-demand fallback for full year {yr}."
            )
        else:
            reasons = []
            if not wind_gate["passed"]:
                reasons.append(wind_gate["failure_reason"])
            if not solar_gate["passed"]:
                reasons.append(solar_gate["failure_reason"])
            gross_demand_fallback_reason = (
                f"BA '{ba_clean}' ({yr}): wind/solar generation unavailable or failed quality gate "
                f"({'; '.join(reasons)}); using gross-demand fallback for the entire BA-year."
            )

    # Compute BA upper-tail exceedance weights
    try:
        ba_weights, weight_diag = calculate_upper_tail_stress_weights(
            signal_array=signal_mw,
            percentile=percentile,
            datetime_series=target_local_index,
        )
    except Exception as exc:
        return {
            "qualified": False,
            "ba_code": ba_clean,
            "year": yr,
            "failure_reason": f"BA '{ba_clean}' ({yr}): failed upper-tail weight calculation ({exc}).",
        }

    # Check if any imputed hour is a positive-weight stress hour
    all_imputed_indices = set(dem_gate["imputed_indices"])
    if signal_type == "net_demand":
        all_imputed_indices.update(wind_gate.get("imputed_indices", []))
        all_imputed_indices.update(solar_gate.get("imputed_indices", []))

    imputed_sorted = sorted(all_imputed_indices)
    imputed_stress_hours = [int(h) for h in imputed_sorted if ba_weights[h] > 0.0]

    aligned_out_df = pd.DataFrame({
        "Hour": np.arange(1, 8761, dtype=int),
        "local_timestamp": target_local_index.strftime("%Y-%m-%d %H:%M:%S"),
        "demand_mw": demand_clean,
        "wind_mw": wind_clean,
        "solar_mw": solar_clean,
        "stress_signal_mw": signal_mw,
        "ba_weight": ba_weights,
        "is_imputed": np.isin(np.arange(8760), imputed_sorted),
    })

    return {
        "qualified": True,
        "ba_code": ba_clean,
        "year": yr,
        "utc_offset_hours": off_hrs,
        "interval_convention": conv,
        "leap_hours_removed": leap_hours_removed,
        "duplicate_timestamp_count": duplicate_timestamp_count,
        "signal_type": signal_type,
        "gross_demand_fallback_reason": gross_demand_fallback_reason,
        "demand_valid_fraction": dem_gate["valid_fraction"],
        "demand_missing_count": dem_gate["missing_count"],
        "demand_max_consecutive_gap": dem_gate["max_consecutive_gap"],
        "imputed_hour_count": len(imputed_sorted),
        "imputed_hour_indices": imputed_sorted,
        "imputed_stress_hour_flag": bool(len(imputed_stress_hours) > 0),
        "imputed_positive_weight_hours": imputed_stress_hours,
        "ba_weights": ba_weights,
        "signal_mw": signal_mw,
        "demand_mw": demand_clean,
        "wind_mw": wind_clean,
        "solar_mw": solar_clean,
        "weight_diagnostics": weight_diag,
        "aligned_df": aligned_out_df,
    }


# ==============================================================================
# 7. END-TO-END PORTFOLIO ORCHESTRATOR & FALLBACK CHAIN
# ==============================================================================

def load_or_fetch_ba_stress_series(
    ba_code: str,
    year: int,
    utc_offset_hours: int,
    interval_convention: str = DEFAULT_PROFILE_INTERVAL_CONVENTION,
    percentile: float = DEFAULT_SYSTEM_STRESS_PERCENTILE,
    api_key: Optional[str] = None,
    cache_dir: str = SYSTEM_STRESS_CACHE_DIR,
    force_refresh: bool = False,
    raw_fetcher: Optional[Callable[..., Tuple[pd.DataFrame, Dict[str, Any]]]] = None,
    known_zero_vre_bas: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """
    Retrieve, align, and qualify a single BA-year series using the cache-first hierarchy:
      1. Load verified raw cache if available and `not force_refresh`.
      2. Otherwise fetch from EIA API v2 (or custom `raw_fetcher` in tests) and atomically cache raw data.
      3. Align to `(utc_offset_hours, interval_convention)`, run quality gates, and atomically save aligned cache.
    """
    ba_clean = str(ba_code).strip().upper()
    yr = int(year)
    raw_csv_path, raw_manifest_path = get_raw_cache_paths(ba_clean, yr, cache_dir=cache_dir)
    aligned_csv_path, aligned_manifest_path = get_aligned_cache_paths(
        ba_clean, yr, utc_offset_hours, interval_convention, cache_dir=cache_dir
    )

    raw_df: Optional[pd.DataFrame] = None
    raw_meta: Dict[str, Any] = {}
    used_cache = False

    if not force_refresh:
        bundle = load_cache_bundle(raw_csv_path, raw_manifest_path)
        if bundle is not None:
            raw_df, raw_meta = bundle
            used_cache = True

    if raw_df is None:
        fetch_fn = raw_fetcher or fetch_eia_ba_year_raw
        resolved_key = resolve_eia_api_key(api_key)
        if raw_fetcher is None and not resolved_key:
            return {
                "qualified": False,
                "ba_code": ba_clean,
                "year": yr,
                "used_cache": False,
                "failure_reason": (
                    f"BA '{ba_clean}' ({yr}): no local cached EIA-930 data found and no EIA API key provided. "
                    f"Provide a free EIA API key or pre-populate the cache."
                ),
            }
        try:
            raw_df, raw_meta = fetch_fn(ba_clean, yr, resolved_key)
            save_cache_bundle(raw_df, raw_csv_path, raw_manifest_path, raw_meta)
            used_cache = False
        except Exception as exc:
            safe_err = redact_api_key(str(exc), resolved_key)
            return {
                "qualified": False,
                "ba_code": ba_clean,
                "year": yr,
                "used_cache": False,
                "failure_reason": f"BA '{ba_clean}' ({yr}) fetch failed: {safe_err}",
            }

    res = align_and_qualify_ba_series(
        raw_df=raw_df,
        ba_code=ba_clean,
        year=yr,
        utc_offset_hours=utc_offset_hours,
        interval_convention=interval_convention,
        percentile=percentile,
        known_zero_vre_bas=known_zero_vre_bas,
    )
    res["used_cache"] = used_cache
    res["raw_cache_path"] = raw_csv_path
    res["aligned_cache_path"] = aligned_csv_path

    if res.get("qualified") and "aligned_df" in res:
        try:
            save_cache_bundle(
                res["aligned_df"],
                aligned_csv_path,
                aligned_manifest_path,
                {
                    "ba_code": ba_clean,
                    "year": yr,
                    "utc_offset_hours": int(utc_offset_hours),
                    "interval_convention": interval_convention,
                    "signal_type": res["signal_type"],
                    "demand_valid_fraction": res["demand_valid_fraction"],
                    "imputed_hour_count": res["imputed_hour_count"],
                    "imputed_stress_hour_flag": res["imputed_stress_hour_flag"],
                },
            )
        except Exception as exc:
            logger.warning("Failed to write aligned cache for %s %s: %s", ba_clean, yr, exc)

    return res


def evaluate_system_stress_capacity_proxy(
    selected_states: Sequence[str],
    weather_case: Any,
    weather_fallback_cwft: Optional[np.ndarray] = None,
    profile_year_basis: str = "AMY",
    weather_source: str = "measured_file",
    utc_offset_hours: Optional[int] = None,
    user_confirmed_offset: bool = False,
    interval_convention: str = DEFAULT_PROFILE_INTERVAL_CONVENTION,
    percentile: float = DEFAULT_SYSTEM_STRESS_PERCENTILE,
    api_key: Optional[str] = None,
    cache_dir: str = SYSTEM_STRESS_CACHE_DIR,
    force_refresh: bool = False,
    min_coverage: float = MIN_STATE_BA_SALES_COVERAGE,
    crosswalk_df: Optional[pd.DataFrame] = None,
    load_df: Optional[pd.DataFrame] = None,
    active_profile_cols: Optional[Sequence[str]] = None,
    stress_year: Optional[int] = None,
    datetime_series: Optional[Any] = None,
    raw_fetcher: Optional[Callable[..., Tuple[pd.DataFrame, Dict[str, Any]]]] = None,
    known_zero_vre_bas: Optional[Sequence[str]] = None,
    cambium_planning_year: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Execute the complete public-data system-stress capacity-credit proxy workflow
    with deterministic fallback hierarchy:
      `cached net demand -> fetched net demand -> gross demand -> weather fallback with warning -> unavailable`

    Returns a dictionary containing:
      • `cwft_array`: 8,760-hour weight vector summing to 1.0 (or None if unavailable).
      • `requested_method`: `"Public-data system-stress proxy (EIA)"`
      • `effective_method`: e.g. `"Public-data system-stress proxy (EIA net demand)"`,
        `"Public-data system-stress proxy (EIA gross-demand fallback)"`,
        `"Mixed portfolio: Public-data system-stress proxy + Weather fallback"`, or
        `"Weather-based CWF fallback"`
      • `fallback_triggered`: bool
      • `warnings`: list of user-facing warning strings
      • `provenance`: full audit dictionary (selected states, equal state weights, crosswalk vintage,
        BA shares, unmapped shares, BA signal types, coverage %, imputation flags, concentration metrics,
        historical demand year vs Cambium planning year).
    """
    requested_label = "Public-data system-stress proxy (EIA)"
    warnings_list: List[str] = []

    def _return_weather_fallback(reason_msg: str, extra_prov: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if reason_msg and reason_msg not in warnings_list:
            warnings_list.append(reason_msg)
        if weather_fallback_cwft is not None:
            fb_arr = np.asarray(weather_fallback_cwft, dtype=float)
            fb_sum = float(np.sum(fb_arr))
            if fb_sum > 0:
                fb_arr = fb_arr / fb_sum
            return {
                "status": "weather_fallback",
                "cwft_array": fb_arr,
                "requested_method": requested_label,
                "effective_method": "Weather-based CWF (fallback from EIA system-stress proxy)",
                "signal_regime": "weather_fallback",
                "fallback_triggered": True,
                "fallback_reason": reason_msg,
                "warnings": warnings_list,
                "portfolio_stress_signal_mw": np.full(8760, np.nan),
                "portfolio_demand_mw": np.full(8760, np.nan),
                "portfolio_wind_mw": np.full(8760, np.nan),
                "portfolio_solar_mw": np.full(8760, np.nan),
                "provenance": {
                    "requested_method": requested_label,
                    "effective_method": "Weather-based CWF (fallback from EIA system-stress proxy)",
                    "fallback_triggered": True,
                    "fallback_reason": reason_msg,
                    "cambium_planning_year": cambium_planning_year,
                    **(extra_prov or {}),
                },
            }
        return {
            "status": "unavailable",
            "cwft_array": None,
            "requested_method": requested_label,
            "effective_method": "Unavailable (no matching EIA stress data or weather fallback)",
            "signal_regime": "unavailable",
            "fallback_triggered": True,
            "fallback_reason": reason_msg,
            "warnings": warnings_list,
            "portfolio_stress_signal_mw": np.full(8760, np.nan),
            "portfolio_demand_mw": np.full(8760, np.nan),
            "portfolio_wind_mw": np.full(8760, np.nan),
            "portfolio_solar_mw": np.full(8760, np.nan),
            "provenance": {
                "requested_method": requested_label,
                "effective_method": "Unavailable",
                "fallback_triggered": True,
                "fallback_reason": reason_msg,
                "cambium_planning_year": cambium_planning_year,
                **(extra_prov or {}),
            },
        }

    # Step 1: Validate profile eligibility & time basis
    elig = validate_profile_stress_eligibility(
        selected_states=selected_states,
        weather_case=weather_case,
        profile_year_basis=profile_year_basis,
        weather_source=weather_source,
        utc_offset_hours=utc_offset_hours,
        user_confirmed_offset=user_confirmed_offset,
        interval_convention=interval_convention,
        load_df=load_df,
        active_profile_cols=active_profile_cols,
        stress_year=stress_year,
    )
    for w in elig.get("warnings", []):
        if w not in warnings_list:
            warnings_list.append(w)

    if not elig["eligible"]:
        return _return_weather_fallback(
            elig["fallback_reason"],
            extra_prov={
                "stress_year": elig.get("stress_year"),
                "profile_year_basis": elig.get("profile_year_basis"),
                "time_basis": elig.get("time_basis"),
                "building_imputed_hours": elig.get("building_imputed_hours", {}),
            },
        )

    stress_year = int(elig["stress_year"])
    time_basis = elig["time_basis"]
    eff_utc_offset = int(time_basis["utc_offset_hours"])
    eff_conv = str(time_basis["interval_convention"])

    # Step 2: Initial state-to-BA crosswalk lookup
    try:
        initial_map = resolve_state_ba_mapping(
            selected_states=selected_states,
            stress_year=stress_year,
            crosswalk_df=crosswalk_df,
            min_coverage=min_coverage,
        )
    except Exception as exc:
        return _return_weather_fallback(str(exc), extra_prov={"stress_year": stress_year})

    # Step 3: Load or fetch each unique candidate BA once
    candidate_bas = initial_map["unique_required_bas"]
    ba_results: Dict[str, Dict[str, Any]] = {}
    qualified_bas: List[str] = []

    for ba in candidate_bas:
        ba_res = load_or_fetch_ba_stress_series(
            ba_code=ba,
            year=stress_year,
            utc_offset_hours=eff_utc_offset,
            interval_convention=eff_conv,
            percentile=percentile,
            api_key=api_key,
            cache_dir=cache_dir,
            force_refresh=force_refresh,
            raw_fetcher=raw_fetcher,
            known_zero_vre_bas=known_zero_vre_bas,
        )
        ba_results[ba] = ba_res
        if ba_res.get("qualified"):
            qualified_bas.append(ba)
            if ba_res.get("gross_demand_fallback_reason"):
                warnings_list.append(ba_res["gross_demand_fallback_reason"])
            if ba_res.get("imputed_stress_hour_flag"):
                warnings_list.append(
                    f"BA '{ba}' ({stress_year}): {len(ba_res['imputed_positive_weight_hours'])} linearly interpolated "
                    f"interior hour(s) received positive capacity stress weight."
                )
        else:
            warnings_list.append(ba_res.get("failure_reason", f"BA '{ba}' failed qualification."))

    # Step 4: Re-evaluate state coverage gate using ONLY BAs that passed EIA-930 quality gates
    final_map = resolve_state_ba_mapping(
        selected_states=selected_states,
        stress_year=stress_year,
        crosswalk_df=crosswalk_df,
        min_coverage=min_coverage,
        available_bas=qualified_bas,
    )
    for w in final_map.get("warnings", []):
        if w not in warnings_list:
            warnings_list.append(w)

    qualifying_states = final_map["qualifying_states"]
    failed_states = final_map["failed_coverage_states"]

    if not qualifying_states:
        reason = (
            f"No selected state achieved the required {min_coverage*100:.1f}% residential-sales coverage "
            f"with qualified EIA-930 BA stress series in {stress_year}."
        )
        return _return_weather_fallback(
            reason,
            extra_prov={
                "stress_year": stress_year,
                "exact_weather_year_match": elig.get("exact_weather_year_match", True),
                "weather_misalignment_warning": elig.get("weather_misalignment_warning"),
                "crosswalk_vintage": final_map["selected_vintage"],
                "state_details": final_map["state_details"],
                "ba_results_summary": {
                    b: {"qualified": r.get("qualified"), "failure_reason": r.get("failure_reason")}
                    for b, r in ba_results.items()
                },
            },
        )

    # Step 5: Handle mixed state portfolios if some states failed coverage and weather_fallback_cwft is available
    fallback_state_weights: Dict[str, np.ndarray] = {}
    if failed_states:
        if weather_fallback_cwft is None:
            return _return_weather_fallback(
                f"State(s) {', '.join(failed_states)} failed the >= {min_coverage*100:.1f}% BA coverage gate "
                f"and no weather fallback curve was provided."
            )
        for fst in failed_states:
            fallback_state_weights[fst] = np.asarray(weather_fallback_cwft, dtype=float)
        warnings_list.append(
            f"Mixed-method state portfolio: state(s) {', '.join(qualifying_states)} use EIA-930 system-stress weights, "
            f"while state(s) {', '.join(failed_states)} fell back to weather-based CWF weights."
        )

    ba_weights_map = {ba: ba_results[ba]["ba_weights"] for ba in qualified_bas}
    portfolio_weights, portfolio_diag = combine_ba_weights_to_state_portfolio(
        ba_weights_map=ba_weights_map,
        state_ba_shares_map=final_map["qualifying_state_ba_shares"],
        selected_states=final_map["selected_states"],
        fallback_state_weights=fallback_state_weights,
        datetime_series=datetime_series,
    )

    # Compute portfolio-weighted hourly MW series across qualified BAs for visualization & CSV export
    comb_ba_shares = portfolio_diag["combined_ba_shares"]
    comb_ba_sum = sum(comb_ba_shares.values())
    portfolio_stress_mw = np.zeros(8760, dtype=float)
    portfolio_demand_mw = np.zeros(8760, dtype=float)
    portfolio_wind_mw = np.zeros(8760, dtype=float)
    portfolio_solar_mw = np.zeros(8760, dtype=float)
    any_gross = False
    any_net = False

    for ba, sh in comb_ba_shares.items():
        norm_sh = sh / comb_ba_sum if comb_ba_sum > 0 else 0.0
        r = ba_results[ba]
        portfolio_stress_mw += norm_sh * r["signal_mw"]
        portfolio_demand_mw += norm_sh * r["demand_mw"]
        if r["signal_type"] == "net_demand":
            any_net = True
            portfolio_wind_mw += norm_sh * np.nan_to_num(r["wind_mw"], nan=0.0)
            portfolio_solar_mw += norm_sh * np.nan_to_num(r["solar_mw"], nan=0.0)
        else:
            any_gross = True
            portfolio_wind_mw[:] = np.nan
            portfolio_solar_mw[:] = np.nan

    if failed_states:
        effective_method = (
            f"Mixed portfolio: EIA-930 system-stress ({', '.join(qualifying_states)}) + "
            f"Weather fallback ({', '.join(failed_states)})"
        )
        signal_regime = "mixed_stress_and_weather"
    elif any_net and not any_gross:
        effective_method = "Public-data system-stress proxy (EIA-930 net demand)"
        signal_regime = "net_demand"
    elif any_gross and not any_net:
        effective_method = "Public-data system-stress proxy (EIA-930 gross-demand fallback)"
        signal_regime = "gross_demand"
    else:
        effective_method = "Public-data system-stress proxy (EIA-930 mixed net/gross BA demand)"
        signal_regime = "mixed_net_and_gross_demand"

    ba_summary_table = []
    for ba in sorted(comb_ba_shares.keys()):
        r = ba_results[ba]
        w_diag = r["weight_diagnostics"]
        ba_summary_table.append({
            "ba_code": ba,
            "portfolio_share": round(float(comb_ba_shares[ba]), 6),
            "signal_type": r["signal_type"],
            "used_cache": bool(r.get("used_cache", False)),
            "demand_valid_pct": round(float(r["demand_valid_fraction"] * 100.0), 3),
            "imputed_hours": int(r["imputed_hour_count"]),
            "imputed_stress_hour_flag": bool(r["imputed_stress_hour_flag"]),
            "threshold_mw": round(float(w_diag["threshold_mw"]), 2),
            "peak_signal_mw": round(float(w_diag["signal_max_mw"]), 2),
            "nonzero_hours": int(w_diag["nonzero_hours"]),
            "max_hour_share_pct": round(float(w_diag["max_hour_share"] * 100.0), 3),
            "effective_hours": round(float(w_diag["effective_hours"]), 2),
        })

    provenance = {
        "requested_method": requested_label,
        "effective_method": effective_method,
        "signal_regime": signal_regime,
        "fallback_triggered": bool(len(failed_states) > 0 or any_gross),
        "stress_year": stress_year,
        "exact_weather_year_match": elig.get("exact_weather_year_match", True),
        "weather_misalignment_warning": elig.get("weather_misalignment_warning"),
        "cambium_planning_year": cambium_planning_year,
        "year_separation_note": (
            f"Historical system-stress demand year ({stress_year}) is matched to the building's "
            f"actual meteorological year and kept strictly separate from the modeled Cambium "
            f"planning horizon ({cambium_planning_year or 'N/A'})."
        ),
        "profile_year_basis": "AMY",
        "time_basis": time_basis,
        "threshold_percentile": float(percentile),
        "crosswalk_vintage": final_map["selected_vintage"],
        "exact_vintage_match": final_map["exact_vintage_match"],
        "vintage_disclosure": final_map["vintage_disclosure"],
        "selected_states": final_map["selected_states"],
        "equal_state_weight": final_map["equal_state_weight"],
        "qualifying_states": qualifying_states,
        "failed_coverage_states": failed_states,
        "state_details": final_map["state_details"],
        "combined_ba_shares": comb_ba_shares,
        "ba_summary_table": ba_summary_table,
        "portfolio_diagnostics": portfolio_diag,
        "building_imputed_hours": elig.get("building_imputed_hours", {}),
        "building_imputation_warnings": elig.get("building_imputation_warnings", []),
        "synthetic_weather_warning": elig.get("synthetic_weather_warning"),
    }

    return {
        "status": "ok" if not failed_states else "mixed_fallback",
        "cwft_array": portfolio_weights,
        "requested_method": requested_label,
        "effective_method": effective_method,
        "signal_regime": signal_regime,
        "fallback_triggered": bool(len(failed_states) > 0 or any_gross),
        "fallback_reason": None if not failed_states else f"Partial state fallback for {', '.join(failed_states)}",
        "warnings": warnings_list,
        "portfolio_stress_signal_mw": portfolio_stress_mw,
        "portfolio_demand_mw": portfolio_demand_mw,
        "portfolio_wind_mw": portfolio_wind_mw,
        "portfolio_solar_mw": portfolio_solar_mw,
        "ba_results": ba_results,
        "provenance": provenance,
    }


# ==============================================================================
# CAMBIUM REGIONAL NET-DEMAND CAPACITY-CREDIT PROXY LOADER
# ==============================================================================

from calculations import (
    calculate_cambium_net_demand_exceedance_weights,
    calculate_cambium_seasonal_net_demand_weights,
    combine_gea_weights_to_state_portfolio,
)
from cambium_downloader import (
    DEFAULT_GEA_MANIFEST_PATH,
    validate_cambium_state_mapping,
    get_geas_for_states,
    get_required_bas_for_geas,
    check_missing_cambium_gea_data,
    load_reeds_gea_manifest,
)


def validate_cambium_ba_csv(filepath: str) -> Dict[str, Any]:
    """
    Validates an individual ReEDS balancing area CSV from Cambium.
    Checks 8,760 rows, physical column presence, absence of NaNs, and
    verifies net_load_busbar identity within rounding tolerance.
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Cambium BA file not found: '{filepath}'")

    # Read row 0 and 1 for metadata
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        row0 = f.readline().strip().split(",")
        row1 = f.readline().strip().split(",")
    meta = dict(zip([c.strip() for c in row0], [v.strip() for v in row1])) if len(row0) == len(row1) else {}

    # Read hourly data (skip metadata rows 0-4, header is row 5)
    df = pd.read_csv(filepath, skiprows=5)
    if len(df) != 8760:
        raise ValueError(f"Cambium BA file '{filepath}' has {len(df)} rows; expected exactly 8,760.")

    req_cols = ["timestamp", "timestamp_local", "busbar_load", "variable_generation", "net_load_busbar", "enduse_load"]
    missing_cols = [c for c in req_cols if c not in df.columns]
    if missing_cols:
        raise ValueError(f"Cambium BA file '{filepath}' is missing physical columns: {missing_cols}")

    for c in ["busbar_load", "variable_generation", "net_load_busbar", "enduse_load"]:
        vals = df[c].values
        if not np.isfinite(vals).all():
            raise ValueError(f"Cambium BA file '{filepath}' contains non-finite values in column '{c}'.")

    # Check identity: net_load_busbar == busbar_load - variable_generation
    diff = np.abs(df["net_load_busbar"].values - (df["busbar_load"].values - df["variable_generation"].values))
    max_diff = float(np.max(diff))
    if max_diff > 1.0:  # Allow small rounding slack for 1-decimal published MWh
        logger.warning(
            f"Physical net_load_busbar diverges from (busbar_load - variable_generation) by up to {max_diff:.2f} MWh in '{filepath}'."
        )

    ba = meta.get("r", os.path.basename(filepath).split("_")[3] if "_" in filepath else "unknown")
    gea = meta.get("gea", "unknown")
    state = meta.get("state", "unknown")
    tz = meta.get("tz", "CT")
    planning_year = meta.get("t", "unknown")

    return {
        "df": df,
        "metadata": meta,
        "ba": str(ba).lower(),
        "gea": gea,
        "state": state,
        "tz": tz,
        "planning_year": str(planning_year),
    }


def aggregate_state_busbar_net_load(
    state: str,
    ba_data_map: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Sums constituent ReEDS BA physical loads for a target state along
    a common Eastern Standard Time (EST) clock.
    """
    if not ba_data_map:
        raise ValueError(f"No constituent BA data provided for state '{state}'.")

    tz_est_offsets = {"ET": 0, "EST": 0, "CT": 1, "CST": 1, "MT": 2, "MST": 2, "PT": 3, "PST": 3}

    sum_net_load_est = np.zeros(8760, dtype=float)
    sum_enduse_load_est = np.zeros(8760, dtype=float)
    ba_annual_enduse: Dict[str, float] = {}

    for ba, data in ba_data_map.items():
        df = data["df"]
        tz = str(data.get("tz", "CT")).upper()
        offset = tz_est_offsets.get(tz, 1)

        # Shift local hour index to synchronous EST hour index: h_est = (h_local + offset) % 8760
        h_est_indices = (np.arange(8760) + offset) % 8760

        net_load = df["net_load_busbar"].values
        enduse = df["enduse_load"].values

        sum_net_load_est[h_est_indices] += net_load
        sum_enduse_load_est[h_est_indices] += enduse

        tot_enduse = float(np.sum(enduse))
        ba_annual_enduse[ba] = tot_enduse

    return {
        "state": state,
        "net_load_est": sum_net_load_est,
        "enduse_load_est": sum_enduse_load_est,
        "ba_annual_enduse": ba_annual_enduse,
        "constituent_count": len(ba_data_map),
    }


def aggregate_gea_busbar_net_load(
    gea: str,
    ba_data_map: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Sums constituent ReEDS BA physical loads for a complete GEA region along
    a common Eastern Standard Time (EST) clock.
    """
    if not ba_data_map:
        raise ValueError(f"No constituent BA data provided for GEA '{gea}'.")

    tz_est_offsets = {"ET": 0, "EST": 0, "CT": 1, "CST": 1, "MT": 2, "MST": 2, "PT": 3, "PST": 3}

    sum_net_load_est = np.zeros(8760, dtype=float)
    sum_enduse_load_est = np.zeros(8760, dtype=float)
    ba_annual_enduse: Dict[str, float] = {}
    ba_states: Dict[str, str] = {}

    for ba, data in ba_data_map.items():
        df = data["df"]
        tz = str(data.get("tz", "CT")).upper()
        offset = tz_est_offsets.get(tz, 1)

        # Shift local hour index to synchronous EST hour index: h_est = (h_local + offset) % 8760
        h_est_indices = (np.arange(8760) + offset) % 8760

        net_load = df["net_load_busbar"].values
        enduse = df["enduse_load"].values

        sum_net_load_est[h_est_indices] += net_load
        sum_enduse_load_est[h_est_indices] += enduse

        tot_enduse = float(np.sum(enduse))
        ba_annual_enduse[ba] = tot_enduse
        ba_states[ba] = data.get("state", "unknown")

    return {
        "gea": gea,
        "net_load_est": sum_net_load_est,
        "enduse_load_est": sum_enduse_load_est,
        "ba_annual_enduse": ba_annual_enduse,
        "ba_states": ba_states,
        "constituent_count": len(ba_data_map),
    }


def align_est_weights_to_local_tz(
    weights_est: np.ndarray,
    tz_or_state: str,
    custom_utc_offset: Optional[int] = None,
) -> np.ndarray:
    """
    Converts 8,760-hour EST grid stress weights to the building profile's
    Local Standard Time basis.
    """
    w_est = np.asarray(weights_est, dtype=float)
    if len(w_est) != 8760:
        raise ValueError(f"weights_est must have length 8760 (got {len(w_est)}).")

    # Determine building standard-time offset relative to EST (UTC-5)
    if custom_utc_offset is not None:
        local_utc = custom_utc_offset
    elif tz_or_state.upper() in STATE_TIMEZONE_METADATA:
        local_utc = STATE_TIMEZONE_METADATA[tz_or_state.upper()]["default_utc_offset"]
    elif tz_or_state.upper() in ["ET", "EST"]:
        local_utc = -5
    elif tz_or_state.upper() in ["CT", "CST"]:
        local_utc = -6
    elif tz_or_state.upper() in ["MT", "MST"]:
        local_utc = -7
    elif tz_or_state.upper() in ["PT", "PST"]:
        local_utc = -8
    else:
        local_utc = -6  # Default CT

    offset_from_est = local_utc - (-5)  # ET: 0, CT: -1, MT: -2, PT: -3

    # Building hour h corresponds to EST hour (h - offset_from_est) % 8760
    building_h_indices = np.arange(8760)
    est_corresponding_h = (building_h_indices - offset_from_est) % 8760

    weights_local = w_est[est_corresponding_h]
    # Re-normalize to guarantee exact sum = 1.0
    tot = float(np.sum(weights_local))
    if tot > 0:
        weights_local = weights_local / tot
    return weights_local


def load_cambium_net_demand_proxy_for_portfolio(
    target_states: List[str],
    selected_scenario: str,
    planning_year: str,
    raw_directory: str = "./Cambium_Hourly_Data_raw",
    custom_tz: Optional[str] = None,
    manifest_path: str = DEFAULT_GEA_MANIFEST_PATH,
    seasonal_split: bool = True,
    winter_weight: float = 0.60,
    summer_weight: Optional[float] = None,
    aggregation_level: str = "state",
    top_n_peak_hours: int = 100,
) -> Dict[str, Any]:
    """
    Loads, qualifies, and computes Cambium net-demand capacity weights
    for the requested states and scenario.

    Parameters:
        aggregation_level: "state" (default) evaluates net-demand physical load aggregated
                           directly across constituent ReEDS BAs belonging to the target state(s).
                           "gea" evaluates net-demand aggregated across the full regional
                           Generation and Emissions Assessment (GEA) region (e.g. SERTP across 11 BAs).
    """
    validate_cambium_state_mapping(target_states)

    if aggregation_level == "state":
        from cambium_downloader import STATE_TO_BALANCING_AREAS, REEDS_CAMBIUM24_AGGREG_MAP

        # Determine required constituent BAs per target state
        state_to_bas: Dict[str, List[str]] = {}
        missing_by_state: Dict[str, List[str]] = {}
        year_str = str(planning_year)

        for st in target_states:
            st_upper = st.upper()
            raw_bas = STATE_TO_BALANCING_AREAS.get(st_upper, [])
            mapped_bas = [
                REEDS_CAMBIUM24_AGGREG_MAP.get(b.lower(), b.lower())
                for b in raw_bas
            ]
            state_to_bas[st_upper] = mapped_bas

            missing_for_st = []
            for ba in mapped_bas:
                matched_file = None
                for root, _, files in os.walk(raw_directory):
                    for f_name in files:
                        f_low = f_name.lower()
                        if f_low.endswith(".csv") and year_str in f_low and f"_{ba}_" in f_low:
                            matched_file = os.path.join(root, f_name)
                            break
                    if matched_file:
                        break
                if not matched_file:
                    missing_for_st.append(ba)

            if missing_for_st:
                missing_by_state[st_upper] = missing_for_st

        if missing_by_state:
            return {
                "status": "missing_data",
                "is_qualified": False,
                "missing_bas_by_state": missing_by_state,
                "target_states": target_states,
                "weights": None,
                "diagnostics": None,
                "warning": (
                    f"Missing constituent Cambium balancing area files for state(s): {missing_by_state}. "
                    "Download constituent datasets via cambium_downloader or use the weather capacity method."
                ),
            }

        # Parse constituent BA CSVs and aggregate state busbar net load
        state_aggregated: Dict[str, Dict[str, Any]] = {}
        state_weights_local: Dict[str, np.ndarray] = {}
        state_diagnostics: Dict[str, Dict[str, Any]] = {}

        for st in target_states:
            st_upper = st.upper()
            ba_data_map: Dict[str, Dict[str, Any]] = {}
            for ba in state_to_bas[st_upper]:
                matched_file = None
                for root, _, files in os.walk(raw_directory):
                    for f_name in files:
                        f_low = f_name.lower()
                        if f_low.endswith(".csv") and year_str in f_low and f"_{ba}_" in f_low:
                            matched_file = os.path.join(root, f_name)
                            break
                    if matched_file:
                        break
                if not matched_file:
                    raise FileNotFoundError(f"Expected BA file for '{ba}' in state '{st}' not found in '{raw_directory}'.")
                parsed = validate_cambium_ba_csv(matched_file)
                ba_data_map[ba] = parsed

            # Aggregate state busbar net load along EST clock
            agg = aggregate_state_busbar_net_load(st_upper, ba_data_map)
            state_aggregated[st_upper] = agg

            # Compute seasonal or annual exceedance weights on the state's net load
            if seasonal_split:
                w_est, diag = calculate_cambium_seasonal_net_demand_weights(
                    agg["net_load_est"],
                    winter_weight=winter_weight,
                    summer_weight=summer_weight,
                    top_n_peak_hours=top_n_peak_hours,
                )
            else:
                w_est, diag = calculate_cambium_net_demand_exceedance_weights(agg["net_load_est"])

            # Align EST weights to building local standard time
            w_st_local = align_est_weights_to_local_tz(w_est, st_upper, custom_utc_offset=None)
            state_weights_local[st] = w_st_local
            state_diagnostics[st] = diag

        # Combine state weights into multi-state portfolio
        portfolio_weights = combine_gea_weights_to_state_portfolio(state_weights_local)
        port_sum_sq = float(np.sum(portfolio_weights ** 2))
        portfolio_diag = {
            "active_hours": int(np.sum(portfolio_weights > 0.0)),
            "top_hour_weight": float(np.max(portfolio_weights)),
            "effective_hours": float(1.0 / port_sum_sq) if port_sum_sq > 0 else 0.0,
            "state_diagnostics": state_diagnostics,
            "state_to_bas": state_to_bas,
            "states": target_states,
            "scenario": selected_scenario,
            "planning_year": planning_year,
            "weather_year": 2012,
            "aggregation_level": "state",
        }

        all_bas = sorted(list(set(b for bas in state_to_bas.values() for b in bas)))
        return {
            "status": "ok",
            "is_qualified": True,
            "weights": portfolio_weights,
            "cwft_array": portfolio_weights,
            "diagnostics": portfolio_diag,
            "state_weights": state_weights_local,
            "state_to_bas": state_to_bas,
            "needed_bas": all_bas,
            "aggregation_level": "state",
        }

    # GEA-level aggregation (backwards-compatible)
    manifest = load_reeds_gea_manifest(manifest_path)
    state_to_geas = get_geas_for_states(target_states, manifest_path=manifest_path)

    all_needed_geas = sorted(list(set(g for geas in state_to_geas.values() for g in geas)))
    missing_by_gea = check_missing_cambium_gea_data(
        all_needed_geas, selected_scenario, planning_year,
        input_directory=raw_directory, manifest_path=manifest_path
    )

    any_missing = any(len(bas) > 0 for bas in missing_by_gea.values())
    if any_missing:
        missing_summary = {g: bas for g, bas in missing_by_gea.items() if bas}
        return {
            "status": "missing_data",
            "is_qualified": False,
            "missing_bas_by_gea": missing_summary,
            "needed_geas": all_needed_geas,
            "weights": None,
            "diagnostics": None,
            "warning": (
                f"Missing constituent Cambium balancing area files for GEA region(s): {missing_summary}. "
                "Download complete regional datasets via cambium_downloader or use the weather capacity method."
            ),
        }

    # Locate and parse all constituent BA CSVs
    gea_to_bas = manifest.get("gea_to_bas", {})
    gea_aggregated: Dict[str, Dict[str, Any]] = {}
    gea_weights_est: Dict[str, np.ndarray] = {}
    gea_diagnostics: Dict[str, Dict[str, Any]] = {}

    year_str = str(planning_year)
    for g in all_needed_geas:
        req_bas = [
            (b.get("ba", "") if isinstance(b, dict) else str(b)).lower()
            for b in gea_to_bas[g]
        ]
        ba_data_map: Dict[str, Dict[str, Any]] = {}
        for ba in req_bas:
            # Look up matching file in raw_directory
            matched_file = None
            for root, _, files in os.walk(raw_directory):
                for f_name in files:
                    f_low = f_name.lower()
                    if f_low.endswith(".csv") and year_str in f_low and f"_{ba}_" in f_low:
                        matched_file = os.path.join(root, f_name)
                        break
                if matched_file:
                    break

            if not matched_file:
                raise FileNotFoundError(f"Expected BA file for '{ba}' in GEA '{g}' not found in '{raw_directory}'.")

            parsed = validate_cambium_ba_csv(matched_file)
            ba_data_map[ba] = parsed

        # Aggregate GEA along EST clock
        agg = aggregate_gea_busbar_net_load(g, ba_data_map)
        gea_aggregated[g] = agg

        # Compute exceedance weights on the complete GEA EST sum
        if seasonal_split:
            w_est, diag = calculate_cambium_seasonal_net_demand_weights(
                agg["net_load_est"],
                winter_weight=winter_weight,
                summer_weight=summer_weight,
            )
        else:
            w_est, diag = calculate_cambium_net_demand_exceedance_weights(agg["net_load_est"])
        gea_weights_est[g] = w_est
        gea_diagnostics[g] = diag

    # Compute state-level weights
    state_weights_local: Dict[str, np.ndarray] = {}
    state_shares_by_gea: Dict[str, Dict[str, float]] = {}

    for st in target_states:
        st_geas = state_to_geas[st]
        if len(st_geas) == 1:
            g = st_geas[0]
            w_st_est = gea_weights_est[g]
            state_shares_by_gea[st] = {g: 1.0}
        else:
            # State spans multiple GEAs: calculate annual enduse load in state per GEA
            state_enduse_by_gea: Dict[str, float] = {}
            for g in st_geas:
                agg = gea_aggregated[g]
                tot_state_in_gea = sum(
                    agg["ba_annual_enduse"][ba]
                    for ba, s_name in agg["ba_states"].items()
                    if s_name.upper() == st.upper() and ba in agg["ba_annual_enduse"]
                )
                state_enduse_by_gea[g] = max(tot_state_in_gea, 0.0)

            tot_state_enduse = sum(state_enduse_by_gea.values())
            if tot_state_enduse <= 0:
                shares = {g: 1.0 / len(st_geas) for g in st_geas}
            else:
                shares = {g: state_enduse_by_gea[g] / tot_state_enduse for g in st_geas}

            state_shares_by_gea[st] = shares
            w_st_est = np.zeros(8760, dtype=float)
            for g, sh in shares.items():
                w_st_est += sh * gea_weights_est[g]

        # Convert EST weights to building local standard time
        w_st_local = align_est_weights_to_local_tz(w_st_est, st, custom_utc_offset=None)
        state_weights_local[st] = w_st_local

    # Combine state weights into multi-state portfolio
    portfolio_weights = combine_gea_weights_to_state_portfolio(state_weights_local)
    port_sum_sq = float(np.sum(portfolio_weights ** 2))
    portfolio_diag = {
        "active_hours": int(np.sum(portfolio_weights > 0.0)),
        "top_hour_weight": float(np.max(portfolio_weights)),
        "effective_hours": float(1.0 / port_sum_sq) if port_sum_sq > 0 else 0.0,
        "gea_diagnostics": gea_diagnostics,
        "state_shares_by_gea": state_shares_by_gea,
        "states": target_states,
        "geas": all_needed_geas,
        "scenario": selected_scenario,
        "planning_year": planning_year,
        "weather_year": 2012,
    }

    return {
        "status": "ok",
        "is_qualified": True,
        "weights": portfolio_weights,
        "cwft_array": portfolio_weights,
        "diagnostics": portfolio_diag,
        "state_weights": state_weights_local,
        "gea_weights_est": gea_weights_est,
        "state_to_geas": state_to_geas,
        "needed_geas": all_needed_geas,
    }
