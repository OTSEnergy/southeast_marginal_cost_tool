"""
cambium_downloader.py — Automated NLR Cambium Grid Data Downloader
===================================================================

Provides automated on-demand retrieval of NLR Cambium hourly 8,760-hour grid
datasets (energy marginal costs, emissions rates, etc.) directly from the NREL
Scenario Viewer API and S3 data store.

KEY CAPABILITIES:
    • Resolves state codes (GA, AL, TN, NC, SC, FL, MS, etc.) to NLR Balancing Areas.
    • Uses HTTP Range requests (via RemoteZipReader) to inspect the remote ZIP central
      directory without downloading the entire 600+ MB archive.
    • Streams and extracts *only* the specific balancing area CSV files required for
      the selected state(s), scenario, and planning year in seconds (~1.5–4s per file).
    • Caches extracted files in ./Cambium_Hourly_Data_raw for instant offline reuse.
    • Provides state missing-data detection and interactive progress reporting.

USED BY:
    • app.py (automatic on-demand download button & pre-check)
    • data_loaders.py (optional fallback when files are missing)
"""

import os
import io
import re
import json
import logging
import urllib.request
import urllib.parse
import zipfile
from typing import List, Dict, Tuple, Optional, Callable, Any

logger = logging.getLogger(__name__)

# Base API URLs for NLR Scenario Viewer
SCENARIO_VIEWER_HOST = "https://scenarioviewer.nlr.gov"
FILE_LIST_API = f"{SCENARIO_VIEWER_HOST}/api/file-list/"
DOWNLOAD_API = f"{SCENARIO_VIEWER_HOST}/api/download/"

# Project UUIDs on NLR Scenario Viewer
PROJECT_UUIDS = {
    "Cambium 2024": "5c7bef16-7e38-4094-92ce-8b03dfa93380",
    "Cambium 2023": "0f92fe57-3365-428a-8fe8-0afc326b3b43",
    "Cambium 2022": "82460f06-548c-4954-b2d9-b84ba92d63e2",
}

# Bundled Southeast 2024 MidCase 2030 package (fallback when NLR Scenario Viewer cloud S3 is unreachable/403)
BUNDLED_SOUTHEAST_ARCHIVE: str = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "cambium_southeast_midcase_2030.zip"
)


# Pinned NLR ReEDS-2.0 hierarchy commit SHA used to derive STATE_TO_BALANCING_AREAS
# Source: https://github.com/NREL/ReEDS-2.0/blob/b9fbed8759767c8efb9e26492a5bdc8ec903f969/inputs/hierarchy.csv
# Local copy: ./data/reeds_state_ba_hierarchy.csv
# IMPORTANT: ReEDS model balancing areas (p1..p134, z122) are NOT EIA-930 Balancing Authority codes.
# Keep ReEDS model regions and EIA-930 BA namespaces strictly separated.
REEDS_HIERARCHY_COMMIT_SHA: str = "b9fbed8759767c8efb9e26492a5bdc8ec903f969"

# In Cambium 2024 packages, ReEDS regions p119 and p122 (Pennsylvania) are aggregated into z122.
# Cambium 2023 packages retain separate p119 and p122 files.
REEDS_CAMBIUM24_AGGREG_MAP: Dict[str, str] = {
    "p119": "z122",
    "p122": "z122",
}

# Non-contiguous states and territories explicitly deferred in v1
DEFERRED_CAMBIUM_STATES: Dict[str, str] = {
    "AK": "Alaska is outside contiguous U.S. ReEDS p1-p134 Cambium geography.",
    "HI": "Hawaii is outside contiguous U.S. ReEDS p1-p134 Cambium geography.",
    "DC": "District of Columbia is not a separate state in the 48-state ReEDS hierarchy.",
    "PR": "Puerto Rico is outside contiguous U.S. ReEDS p1-p134 Cambium geography.",
    "VI": "U.S. Virgin Islands is outside contiguous U.S. ReEDS p1-p134 Cambium geography.",
    "GU": "Guam is outside contiguous U.S. ReEDS p1-p134 Cambium geography.",
    "AS": "American Samoa is outside contiguous U.S. ReEDS p1-p134 Cambium geography.",
    "MP": "Northern Mariana Islands is outside contiguous U.S. ReEDS p1-p134 Cambium geography.",
}

# State to Balancing Area mapping (ReEDS BAs in Cambium across all 48 contiguous U.S. states)
STATE_TO_BALANCING_AREAS: Dict[str, List[str]] = {
    "AL": ["p89", "p90"],
    "AR": ["p56", "p85"],
    "AZ": ["p27", "p28", "p29", "p30"],
    "CA": ["p8", "p9", "p10", "p11"],
    "CO": ["p33", "p34"],
    "CT": ["p132"],
    "DE": ["p125"],
    "FL": ["p91", "p101", "p102"],
    "GA": ["p94"],
    "IA": ["p45", "p69", "p70"],
    "ID": ["p14", "p15", "p16"],
    "IL": ["p80", "p81", "p82", "p83"],
    "IN": ["p105", "p106", "p107"],
    "KS": ["p52", "p53"],
    "KY": ["p93", "p108", "p109", "p110"],
    "LA": ["p58", "p86"],
    "MA": ["p131"],
    "MD": ["p121", "p123"],
    "ME": ["p134"],
    "MI": ["p74", "p103", "p104"],
    "MN": ["p42", "p43", "p44", "p68"],
    "MO": ["p54", "p55", "p71", "p72", "p73", "p84"],
    "MS": ["p87", "p88"],
    "MT": ["p17", "p18", "p19", "p20", "p35"],
    "NC": ["p97", "p98"],
    "ND": ["p36", "p37"],
    "NE": ["p39", "p40", "p41"],
    "NH": ["p130"],
    "NJ": ["p126"],
    "NM": ["p31", "p47"],
    "NV": ["p12", "p13"],
    "NY": ["p127", "p128"],
    "OH": ["p111", "p112", "p113", "p114"],
    "OK": ["p49", "p50", "p51"],
    "OR": ["p5", "p6", "p7"],
    "PA": ["p115", "p119", "p120", "p122"],
    "RI": ["p133"],
    "SC": ["p95", "p96"],
    "SD": ["p32", "p38"],
    "TN": ["p92"],
    "TX": ["p48", "p57", "p59", "p60", "p61", "p62", "p63", "p64", "p65", "p66", "p67"],
    "UT": ["p25", "p26"],
    "VA": ["p99", "p100", "p118", "p124"],
    "VT": ["p129"],
    "WA": ["p1", "p2", "p3", "p4"],
    "WI": ["p46", "p75", "p76", "p77", "p78", "p79"],
    "WV": ["p116", "p117"],
    "WY": ["p21", "p22", "p23", "p24"],
}


def validate_cambium_state_mapping(target_states: List[str]) -> Dict[str, List[str]]:
    """
    Validates that all requested states belong to the contiguous 48 U.S. states
    with verified ReEDS balancing area mappings. Explicitly rejects AK, HI, and territories.
    """
    if not target_states:
        raise ValueError("No target states specified for Cambium region lookup.")
    resolved: Dict[str, List[str]] = {}
    for raw_st in target_states:
        st = str(raw_st).strip().upper()
        if st in DEFERRED_CAMBIUM_STATES:
            raise ValueError(f"Unsupported geography '{st}': {DEFERRED_CAMBIUM_STATES[st]}")
        if st not in STATE_TO_BALANCING_AREAS:
            raise ValueError(f"No ReEDS balancing area mapping found for state '{st}'.")
        resolved[st] = list(STATE_TO_BALANCING_AREAS[st])
    return resolved

# Scenario to project and file ID mappings
SCENARIO_PACKAGE_MAP: Dict[str, Dict[str, any]] = {
    "MidCase": {
        "project_uuid": PROJECT_UUIDS["Cambium 2024"],
        "file_id": 69176,
        "scenario_str": "MidCase",
        "release": "Cambium24",
    },
    "HighDemandGrowth": {
        "project_uuid": PROJECT_UUIDS["Cambium 2024"],
        "file_id": 69148,
        "scenario_str": "HighDemandGrowth",
        "release": "Cambium24",
    },
    "LowCarbonConstraint": {
        "project_uuid": PROJECT_UUIDS["Cambium 2023"],
        "file_id": 67072,
        "scenario_str": "MidCase95by2050",
        "release": "Cambium23",
    },
    "LowDemandGrowth": {
        "project_uuid": PROJECT_UUIDS["Cambium 2024"],
        "file_id": 69176,
        "scenario_str": "MidCase",
        "release": "Cambium24",
    },
}


class RemoteZipReader(io.RawIOBase):
    """
    A seekable, read-only binary stream that fetches byte ranges from an HTTP(S) URL.
    Enables zipfile.ZipFile to read central directory metadata and extract specific files
    via HTTP Range requests without downloading the entire multi-hundred-megabyte archive.
    """
    def __init__(self, url: str, total_length: int, timeout: int = 30):
        self.url = url
        self.total_length = total_length
        self.pos = 0
        self.timeout = timeout

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            self.pos = offset
        elif whence == io.SEEK_CUR:
            self.pos += offset
        elif whence == io.SEEK_END:
            self.pos = self.total_length + offset
        else:
            raise ValueError(f"Invalid whence argument: {whence}")
        return self.pos

    def tell(self) -> int:
        return self.pos

    def read(self, size: int = -1) -> bytes:
        if size == -1 or (self.pos + size > self.total_length):
            size = self.total_length - self.pos

        if size <= 0:
            return b""

        end = self.pos + size - 1
        headers = {
            "Range": f"bytes={self.pos}-{end}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Southeast-Marginal-Cost-Tool",
        }
        req = urllib.request.Request(self.url, headers=headers)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = resp.read()
            self.pos += len(data)
            return data

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True


def check_missing_cambium_data(
    target_states: List[str],
    selected_scenario: str,
    planning_year: str,
    input_directory: str = "./Cambium_Hourly_Data_raw"
) -> List[str]:
    """
    Scans the local input directory to check which target states are missing valid
    Cambium hourly CSV files for the specified scenario and planning year.

    Returns
    -------
    List[str]
        List of missing state codes (e.g. ['GA']). Returns empty list if all are present.
    """
    if not os.path.exists(input_directory):
        return [s.upper() for s in target_states]

    loaded_states = set()

    for root, _, files in os.walk(input_directory):
        if any(x in root for x in ["__pycache__", ".git"]):
            continue
        for file in files:
            if not file.lower().endswith(".csv"):
                continue

            filepath = os.path.join(root, file)
            try:
                first_row = pd_read_first_rows(filepath)
                if not first_row:
                    continue

                cols_lower = [c.lower() for c in first_row.get("cols", [])]
                is_raw_nrel = 'project' in cols_lower and 'scenario' in cols_lower and ('state' in cols_lower or 'r' in cols_lower)

                if is_raw_nrel:
                    meta = first_row.get("meta", {})
                    file_state = str(meta.get('state', '')).upper()
                    file_scenario = str(meta.get('scenario', meta.get('Scenario', ''))).lower()
                    file_year = str(meta.get('t', ''))

                    if (file_scenario == selected_scenario.lower() and
                        file_state in [s.upper() for s in target_states] and
                        file_year == str(planning_year)):
                        loaded_states.add(file_state)
                else:
                    if selected_scenario.lower() in file.lower():
                        meta_state = first_row.get("meta", {}).get("State")
                        if meta_state:
                            st_upper = str(meta_state).upper()
                            if st_upper in [s.upper() for s in target_states]:
                                loaded_states.add(st_upper)
            except Exception:
                continue

    missing = [s.upper() for s in target_states if s.upper() not in loaded_states]
    return missing


def pd_read_first_rows(filepath: str) -> Optional[Dict[str, any]]:
    """Quickly extracts columns and metadata from row 0 & 1 without full pandas dependency."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            row0 = f.readline().strip()
            row1 = f.readline().strip()
            if not row0:
                return None
            cols = [c.strip().strip('"') for c in row0.split(",")]
            vals = [v.strip().strip('"') for v in row1.split(",")] if row1 else []
            meta = dict(zip(cols, vals)) if len(cols) == len(vals) else {}
            return {"cols": cols, "meta": meta}
    except Exception:
        return None


def extract_from_bundled_archive(
    target_bas: set,
    output_directory: str = "./Cambium_Hourly_Data_raw",
    progress_callback: Optional[Callable[[str, float], None]] = None,
    only_missing: bool = True,
) -> Optional[List[str]]:
    """
    Extracts required ReEDS balancing area CSV files from the local bundled archive
    (data/cambium_southeast_midcase_2030.zip) if present.

    Returns list of extracted file paths if all target_bas can be satisfied, or None.
    """
    if not os.path.exists(BUNDLED_SOUTHEAST_ARCHIVE):
        return None

    try:
        with zipfile.ZipFile(BUNDLED_SOUTHEAST_ARCHIVE, "r") as zf:
            namelist = zf.namelist()
            matched_members = []
            for member in namelist:
                member_lower = member.lower()
                for ba in target_bas:
                    if f"_{ba}_" in member_lower or f"_{ba}." in member_lower or member_lower.endswith(f"_{ba}.csv"):
                        matched_members.append(member)
                        break

            found_bas = set()
            for member in matched_members:
                for ba in target_bas:
                    if f"_{ba}_" in member.lower() or f"_{ba}." in member.lower() or member.lower().endswith(f"_{ba}.csv"):
                        found_bas.add(ba)

            if not target_bas.issubset(found_bas):
                return None

            saved_files = []
            total = len(matched_members)
            for idx, member in enumerate(matched_members):
                basename = os.path.basename(member)
                dest_path = os.path.join(output_directory, basename)
                frac = 0.30 + 0.65 * (idx / max(total, 1))
                if only_missing and os.path.exists(dest_path) and os.path.getsize(dest_path) > 1000:
                    if progress_callback:
                        progress_callback(f"Already cached: {basename} ({idx + 1}/{total})...", frac)
                    saved_files.append(os.path.abspath(dest_path))
                    continue

                if progress_callback:
                    progress_callback(f"Extracting bundled {basename} ({idx + 1}/{total})...", frac)
                with zf.open(member) as src, open(dest_path, "wb") as dst:
                    dst.write(src.read())
                saved_files.append(os.path.abspath(dest_path))

            if progress_callback:
                progress_callback("Extraction from local package complete!", 1.0)
            return saved_files
    except Exception as e:
        logger.warning(f"Failed extracting from bundled archive {BUNDLED_SOUTHEAST_ARCHIVE}: {e}")
        return None


def get_s3_download_url(project_uuid: str, file_id: int) -> Tuple[str, int]:
    """
    POSTs to the NLR Scenario Viewer /api/download/ endpoint to obtain
    the AWS S3 pre-signed URL and content length for the given file package.
    """
    data = urllib.parse.urlencode({
        "project_uuid": project_uuid,
        "file_ids": str(file_id)
    }).encode("utf-8")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Southeast-Marginal-Cost-Tool",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    req = urllib.request.Request(DOWNLOAD_API, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            s3_url = resp.geturl()
            content_len_str = resp.headers.get("Content-Length")
            content_len = int(content_len_str) if content_len_str else 0
            return s3_url, content_len
    except urllib.error.HTTPError as http_err:
        if http_err.code == 403:
            raise ConnectionError(
                f"NLR Scenario Viewer upstream cloud storage returned HTTP 403: Forbidden for package "
                f"(project_uuid={project_uuid}, file_id={file_id}). "
                f"NLR's AWS S3 IAM permissions on 'cambium-prod' currently reject download requests. "
                f"A bundled Southeast dataset fallback is available."
            ) from http_err
        raise



def download_cambium_data(
    target_states: List[str],
    selected_scenario: str,
    planning_year: str,
    output_directory: str = "./Cambium_Hourly_Data_raw",
    progress_callback: Optional[Callable[[str, float], None]] = None,
    only_missing: bool = True,
) -> List[str]:
    """
    Downloads and extracts only the required hourly Cambium balancing area CSV files
    for the specified states, scenario, and planning year directly into output_directory.

    Uses RemoteZipReader to stream only the target files from NLR's S3 storage, avoiding
    the multi-hundred-megabyte full archive download.

    Parameters
    ----------
    target_states : list of str
        State codes to download (e.g. ['GA', 'AL']).
    selected_scenario : str
        Cambium scenario name (e.g. 'MidCase', 'HighDemandGrowth').
    planning_year : str
        Planning horizon year (e.g. '2040').
    output_directory : str
        Local directory where extracted CSV files should be saved.
    progress_callback : callable, optional
        Callback with signature (status_message: str, progress_fraction: float).

    Returns
    -------
    List[str]
        List of absolute file paths to the newly extracted CSV files.
    """
    os.makedirs(output_directory, exist_ok=True)

    package_info = SCENARIO_PACKAGE_MAP.get(selected_scenario, SCENARIO_PACKAGE_MAP["MidCase"])
    project_uuid = package_info["project_uuid"]
    file_id = package_info["file_id"]

    target_bas = set()
    deferred_requested = [st.upper() for st in target_states if st.upper() in DEFERRED_CAMBIUM_STATES]
    if deferred_requested:
        st0 = deferred_requested[0]
        raise ValueError(
            f"No balancing area mappings found for deferred geography {deferred_requested}: "
            f"{DEFERRED_CAMBIUM_STATES[st0]}"
        )
    for st in target_states:
        bas = STATE_TO_BALANCING_AREAS.get(st.upper(), [])
        for ba in bas:
            ba_low = ba.lower()
            target_bas.add(ba_low)
            if ba_low in REEDS_CAMBIUM24_AGGREG_MAP:
                target_bas.add(REEDS_CAMBIUM24_AGGREG_MAP[ba_low].lower())

    if not target_bas:
        raise ValueError(f"No balancing area mappings found for states: {target_states}")

    if progress_callback:
        progress_callback(f"Connecting to NLR Scenario Viewer ({selected_scenario})...", 0.05)

    zf = None
    try:
        s3_url, content_len = get_s3_download_url(project_uuid, file_id)
        if progress_callback:
            progress_callback("Reading remote Cambium dataset package index...", 0.20)
        remote_reader = RemoteZipReader(s3_url, content_len)
        zf = zipfile.ZipFile(remote_reader)
        namelist = zf.namelist()
    except Exception as exc:
        logger.warning(f"Remote NLR Scenario Viewer connection failed ({exc}). Checking bundled package...")
        bundled = extract_from_bundled_archive(
            target_bas=target_bas,
            output_directory=output_directory,
            progress_callback=progress_callback,
            only_missing=only_missing,
        )
        if bundled:
            return bundled
        raise

    matched_members = []
    year_str = str(planning_year)

    for member in namelist:
        member_lower = member.lower()
        if not member_lower.endswith(".csv"):
            continue
        if year_str not in member_lower:
            continue
        for ba in target_bas:
            if f"_{ba}_" in member_lower or f"_{ba}." in member_lower or member_lower.endswith(f"_{ba}.csv"):
                matched_members.append(member)
                break

    if not matched_members:
        for member in namelist:
            member_lower = member.lower()
            if member_lower.endswith(".csv") and any(f"_{ba}_" in member_lower for ba in target_bas):
                matched_members.append(member)

    if not matched_members:
        raise FileNotFoundError(
            f"No matching Cambium CSV files found inside remote package for states {target_states} "
            f"(BAs: {target_bas}, Year: {planning_year})."
        )

    saved_files = []
    total_files = len(matched_members)

    for idx, member in enumerate(matched_members):
        basename = os.path.basename(member)
        dest_path = os.path.join(output_directory, basename)

        frac = 0.25 + 0.70 * (idx / max(total_files, 1))

        if only_missing and os.path.exists(dest_path) and os.path.getsize(dest_path) > 1000:
            if progress_callback:
                progress_callback(f"Already cached: {basename} ({idx + 1}/{total_files})...", frac)
            saved_files.append(os.path.abspath(dest_path))
            continue

        if progress_callback:
            progress_callback(f"Extracting {basename} ({idx + 1}/{total_files})...", frac)

        with zf.open(member) as src, open(dest_path, "wb") as dst:
            dst.write(src.read())

        saved_files.append(os.path.abspath(dest_path))

    if progress_callback:
        progress_callback("Extraction complete! Grid data is ready.", 1.0)

    return saved_files


# ==============================================================================
# GEA (GENERATION EXPANSION AREA) COMPLETE REGIONAL ROUTING & RETRIEVAL
# ==============================================================================

DEFAULT_GEA_MANIFEST_PATH: str = "./data/cambium24_reeds_gea_manifest.json"


def load_reeds_gea_manifest(manifest_path: str = DEFAULT_GEA_MANIFEST_PATH) -> Dict[str, Any]:
    """
    Loads the pinned ReEDS Balancing Area to GEA mapping manifest.
    Covers all 133 constituent BAs across the contiguous 48 U.S. states.
    """
    if not os.path.exists(manifest_path):
        raise FileNotFoundError(
            f"Cambium GEA manifest not found at '{manifest_path}'. "
            "Ensure data/cambium24_reeds_gea_manifest.json is present."
        )
    with open(manifest_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_geas_for_states(
    target_states: List[str],
    manifest_path: str = DEFAULT_GEA_MANIFEST_PATH
) -> Dict[str, List[str]]:
    """
    Resolves each requested state to all intersecting GEAs based on constituent ReEDS BAs.
    Rejects deferred non-contiguous states (AK, HI, territories).
    """
    validate_cambium_state_mapping(target_states)
    manifest = load_reeds_gea_manifest(manifest_path)
    
    state_to_geas: Dict[str, set] = {st.upper(): set() for st in target_states}
    for ba_info in manifest.get("bas", []):
        st = str(ba_info.get("state", "")).upper()
        gea = str(ba_info.get("gea", ""))
        if st in state_to_geas and gea:
            state_to_geas[st].add(gea)
            
    return {st: sorted(list(geas)) for st, geas in state_to_geas.items()}


def get_required_bas_for_geas(
    geas: List[str],
    manifest_path: str = DEFAULT_GEA_MANIFEST_PATH
) -> List[str]:
    """
    Returns a sorted list of all unique ReEDS balancing area IDs needed to
    form a complete, closed regional sum for every specified GEA.
    """
    if not geas:
        return []
    manifest = load_reeds_gea_manifest(manifest_path)
    gea_to_bas = manifest.get("gea_to_bas", {})
    
    required_bas = set()
    for g in geas:
        if g not in gea_to_bas:
            raise ValueError(f"Unknown GEA region '{g}'. Valid GEAs: {sorted(list(gea_to_bas.keys()))}")
        for b_entry in gea_to_bas[g]:
            ba_id = b_entry.get("ba", "") if isinstance(b_entry, dict) else str(b_entry)
            if ba_id:
                required_bas.add(ba_id.lower())
                
    return sorted(list(required_bas))


def check_missing_cambium_gea_data(
    geas: List[str],
    selected_scenario: str,
    planning_year: str,
    input_directory: str = "./Cambium_Hourly_Data_raw",
    manifest_path: str = DEFAULT_GEA_MANIFEST_PATH
) -> Dict[str, List[str]]:
    """
    Checks whether all constituent ReEDS BA CSVs for each requested GEA are
    locally available in input_directory. Returns a dictionary mapping each GEA
    to its list of missing ReEDS BA codes.
    """
    manifest = load_reeds_gea_manifest(manifest_path)
    gea_to_bas = manifest.get("gea_to_bas", {})
    
    # Scan local directory to find present BA files for scenario and year
    present_bas = set()
    year_str = str(planning_year)
    scenario_str = selected_scenario.lower()
    
    if os.path.exists(input_directory):
        for root, _, files in os.walk(input_directory):
            if any(x in root for x in ["__pycache__", ".git"]):
                continue
            for file in files:
                if not file.lower().endswith(".csv") or year_str not in file:
                    continue
                file_lower = file.lower()
                m = re.search(r"hourly_([a-z0-9]+)_", file_lower)
                if m:
                    present_bas.add(m.group(1))
                    
    missing_by_gea: Dict[str, List[str]] = {}
    for g in geas:
        if g not in gea_to_bas:
            missing_by_gea[g] = ["UNKNOWN_GEA"]
            continue
        req = [
            (b.get("ba", "") if isinstance(b, dict) else str(b)).lower()
            for b in gea_to_bas[g]
        ]
        missing = [b for b in req if b not in present_bas]
        missing_by_gea[g] = missing
        
    return missing_by_gea


def check_missing_cambium_gea_data_for_states(
    target_states: List[str],
    selected_scenario: str,
    planning_year: str,
    input_directory: str = "./Cambium_Hourly_Data_raw",
    manifest_path: str = DEFAULT_GEA_MANIFEST_PATH,
) -> Dict[str, List[str]]:
    """
    Checks whether constituent ReEDS BA CSVs for all GEAs covering target_states
    are locally available. Returns a dictionary mapping each GEA to its list of missing BAs,
    filtering out any GEAs that are fully satisfied.
    """
    state_to_geas = get_geas_for_states(target_states, manifest_path=manifest_path)
    all_needed_geas = sorted(list(set(g for geas in state_to_geas.values() for g in geas)))
    missing_by_gea = check_missing_cambium_gea_data(
        all_needed_geas,
        selected_scenario=selected_scenario,
        planning_year=planning_year,
        input_directory=input_directory,
        manifest_path=manifest_path,
    )
    return {g: bas for g, bas in missing_by_gea.items() if bas}


def download_cambium_gea_data(
    geas: List[str],
    selected_scenario: str,
    planning_year: str,
    output_directory: str = "./Cambium_Hourly_Data_raw",
    progress_callback: Optional[Callable[[str, float], None]] = None,
    manifest_path: str = DEFAULT_GEA_MANIFEST_PATH,
    target_bas_subset: Optional[List[str]] = None,
    only_missing: bool = True,
) -> List[str]:
    """
    Downloads and extracts all constituent ReEDS BA CSV files needed to reconstruct
    the specified GEAs directly from NLR's remote S3 archive via HTTP range requests.
    """
    if target_bas_subset:
        required_bas = sorted(list(set(b.lower() for b in target_bas_subset)))
    else:
        required_bas = get_required_bas_for_geas(geas, manifest_path=manifest_path)

    if not required_bas:
        return []
        
    os.makedirs(output_directory, exist_ok=True)
    package_info = SCENARIO_PACKAGE_MAP.get(selected_scenario, SCENARIO_PACKAGE_MAP["MidCase"])
    project_uuid = package_info["project_uuid"]
    file_id = package_info["file_id"]

    target_bas = set(b.lower() for b in required_bas)
    for ba in list(target_bas):
        if ba in REEDS_CAMBIUM24_AGGREG_MAP:
            target_bas.add(REEDS_CAMBIUM24_AGGREG_MAP[ba].lower())

    if progress_callback:
        progress_callback(f"Connecting to NLR Scenario Viewer for GEAs {geas}...", 0.05)

    zf = None
    try:
        s3_url, content_len = get_s3_download_url(project_uuid, file_id)
        if progress_callback:
            progress_callback("Reading remote Cambium dataset package index...", 0.20)
        remote_reader = RemoteZipReader(s3_url, content_len)
        zf = zipfile.ZipFile(remote_reader)
        namelist = zf.namelist()
    except Exception as exc:
        logger.warning(f"Remote NLR Scenario Viewer connection failed ({exc}). Checking bundled package...")
        bundled = extract_from_bundled_archive(
            target_bas=target_bas,
            output_directory=output_directory,
            progress_callback=progress_callback,
            only_missing=only_missing,
        )
        if bundled:
            return bundled
        raise

    matched_members = []
    year_str = str(planning_year)

    for member in namelist:
        member_lower = member.lower()
        if not member_lower.endswith(".csv") or year_str not in member_lower:
            continue
        for ba in target_bas:
            if f"_{ba}_" in member_lower or f"_{ba}." in member_lower or member_lower.endswith(f"_{ba}.csv"):
                matched_members.append(member)
                break

    if not matched_members:
        raise FileNotFoundError(
            f"No matching Cambium CSV files found inside remote package for GEAs {geas} "
            f"(BAs: {target_bas}, Year: {planning_year})."
        )

    saved_files = []
    total_files = len(matched_members)

    for idx, member in enumerate(matched_members):
        basename = os.path.basename(member)
        dest_path = os.path.join(output_directory, basename)

        frac = 0.25 + 0.70 * (idx / max(total_files, 1))

        if only_missing and os.path.exists(dest_path) and os.path.getsize(dest_path) > 1000:
            if progress_callback:
                progress_callback(f"Already cached: {basename} ({idx + 1}/{total_files})...", frac)
            saved_files.append(os.path.abspath(dest_path))
            continue

        if progress_callback:
            progress_callback(f"Extracting {basename} ({idx + 1}/{total_files})...", frac)

        with zf.open(member) as src, open(dest_path, "wb") as dst:
            dst.write(src.read())

        saved_files.append(os.path.abspath(dest_path))

    if progress_callback:
        progress_callback(f"Extraction complete for {len(geas)} GEAs!", 1.0)

    return saved_files


def download_missing_cambium_gea_data(
    missing_bas_by_gea: Dict[str, List[str]],
    selected_scenario: str,
    planning_year: str,
    output_directory: str = "./Cambium_Hourly_Data_raw",
    progress_callback: Optional[Callable[[str, float], None]] = None,
    manifest_path: str = DEFAULT_GEA_MANIFEST_PATH,
) -> List[str]:
    """
    Downloads and extracts only the missing constituent ReEDS BA CSV files
    identified in missing_bas_by_gea (e.g. from check_missing_cambium_gea_data
    or load_cambium_net_demand_stress_weights).
    """
    geas = list(missing_bas_by_gea.keys())
    specific_bas = [ba.lower() for bas in missing_bas_by_gea.values() for ba in bas]
    return download_cambium_gea_data(
        geas=geas,
        selected_scenario=selected_scenario,
        planning_year=planning_year,
        output_directory=output_directory,
        progress_callback=progress_callback,
        manifest_path=manifest_path,
        target_bas_subset=specific_bas if specific_bas else None,
        only_missing=True,
    )
