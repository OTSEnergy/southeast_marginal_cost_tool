"""
tests/test_scenario_selection.py — Unit tests for strict Cambium scenario matching and resolution.

Verifies:
  - Mixed-scenario directories cannot contaminate capacity weights.
  - Metadata takes precedence over misleading filenames.
  - Conflicting duplicate files raise an explicit ValueError rather than silently
    depending on directory traversal order.
  - Identical duplicate files are handled gracefully.
  - Missing requested data is flagged and never reported as successful.
  - Unsupported or unknown scenario names raise ValueError and never silently resolve to MidCase.
"""

import os
import tempfile
import pytest
import numpy as np
import pandas as pd

from system_stress_data import (
    find_cambium_ba_file,
    load_cambium_net_demand_proxy_for_portfolio,
    validate_cambium_ba_csv,
)
from cambium_downloader import (
    get_scenario_package_info,
    download_cambium_data,
    scenario_matches,
)


def _create_mock_cambium_ba_csv(filepath, scenario="MidCase", ba="p89", year="2030", state="AL", load_multiplier=1.0):
    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        # Row 0: metadata header
        f.write("Project,Scenario,Dollar_year,Weather_year,Start_day,r,state,gea,country,tz,t\n")
        # Row 1: metadata values
        f.write(f"Cambium24,{scenario},2023$,2012,Sunday,{ba},{state},SERTP,usa,CT,{year}\n")
        # Row 2: description
        f.write("Metric definitions and scenario descriptions: 2024 Cambium Documentation\n")
        # Row 3: category
        f.write("Time,Time,Load,Transmission,Operational,Operational,Emissions,Busbar costs,End use cost,Generation,Generation\n")
        # Row 4: units
        f.write("Datetime,Datetime,MWh,MWh,unitless,unitless,kg/MWh,$/MWh,$/MWh,MWh,MWh\n")
        # Row 5: data columns
        f.write("timestamp,timestamp_local,busbar_load,trans_losses,distloss_rate_avg,distloss_rate_marg,aer_load_co2e,energy_cost_busbar,energy_cost_enduse,generation,variable_generation,net_load_busbar,enduse_load\n")
        
        # 8760 rows
        for h in range(8760):
            busbar = 4000.0 * load_multiplier + float(h % 100)
            vg = 500.0 * load_multiplier
            net = busbar - vg
            f.write(f"2030-01-01 {h%24:02d}:00:00,2030-01-01 {h%24:02d}:00:00,{busbar:.1f},0.0,0.03,0.04,100.0,30.0,31.0,4500.0,{vg:.1f},{net:.1f},{busbar*0.95:.1f}\n")


class TestCambiumScenarioStrictMatching:
    """Verifies strict scenario matching and prevention of contamination."""

    def test_find_cambium_ba_file_isolates_scenario_in_mixed_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f_mid = os.path.join(tmpdir, "Cambium24_MidCase_hourly_p89_2030.csv")
            f_hdg = os.path.join(tmpdir, "Cambium24_HighDemandGrowth_hourly_p89_2030.csv")
            f_hng = os.path.join(tmpdir, "Cambium24_HighNGPrice_hourly_p89_2030.csv")

            _create_mock_cambium_ba_csv(f_mid, scenario="MidCase", ba="p89", year="2030", load_multiplier=1.0)
            _create_mock_cambium_ba_csv(f_hdg, scenario="HighDemandGrowth", ba="p89", year="2030", load_multiplier=1.5)
            _create_mock_cambium_ba_csv(f_hng, scenario="HighNGPrice", ba="p89", year="2030", load_multiplier=1.2)

            # Request MidCase
            matched_mid = find_cambium_ba_file(tmpdir, ba="p89", planning_year="2030", selected_scenario="MidCase")
            assert matched_mid == f_mid
            parsed_mid = validate_cambium_ba_csv(matched_mid)
            assert parsed_mid["scenario"] == "MidCase"

            # Request HighDemandGrowth
            matched_hdg = find_cambium_ba_file(tmpdir, ba="p89", planning_year="2030", selected_scenario="HighDemandGrowth")
            assert matched_hdg == f_hdg
            parsed_hdg = validate_cambium_ba_csv(matched_hdg)
            assert parsed_hdg["scenario"] == "HighDemandGrowth"

            # Request HighNGPrice
            matched_hng = find_cambium_ba_file(tmpdir, ba="p89", planning_year="2030", selected_scenario="HighNGPrice")
            assert matched_hng == f_hng

            # Request HighGasPrice (alias of HighNGPrice)
            matched_alias = find_cambium_ba_file(tmpdir, ba="p89", planning_year="2030", selected_scenario="HighGasPrice")
            assert matched_alias == f_hng

    def test_misleading_filename_metadata_precedence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # File named MidCase, but row 1 metadata has HighDemandGrowth
            misleading = os.path.join(tmpdir, "Cambium24_MidCase_hourly_p89_2030.csv")
            _create_mock_cambium_ba_csv(misleading, scenario="HighDemandGrowth", ba="p89", year="2030")

            # Searching for MidCase should NOT return this file because metadata does not match
            matched = find_cambium_ba_file(tmpdir, ba="p89", planning_year="2030", selected_scenario="MidCase")
            assert matched is None

            # Searching for HighDemandGrowth SHOULD return this file because metadata matches
            matched_hdg = find_cambium_ba_file(tmpdir, ba="p89", planning_year="2030", selected_scenario="HighDemandGrowth")
            assert matched_hdg == misleading

    def test_conflicting_duplicates_raises_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sub1 = os.path.join(tmpdir, "folder1")
            sub2 = os.path.join(tmpdir, "folder2")
            f1 = os.path.join(sub1, "Cambium24_MidCase_hourly_p89_2030.csv")
            f2 = os.path.join(sub2, "Cambium24_MidCase_hourly_p89_2030.csv")

            # Conflicting data (load_multiplier 1.0 vs 2.0)
            _create_mock_cambium_ba_csv(f1, scenario="MidCase", ba="p89", year="2030", load_multiplier=1.0)
            _create_mock_cambium_ba_csv(f2, scenario="MidCase", ba="p89", year="2030", load_multiplier=2.0)

            with pytest.raises(ValueError, match="Conflicting duplicate Cambium BA files"):
                find_cambium_ba_file(tmpdir, ba="p89", planning_year="2030", selected_scenario="MidCase")

    def test_identical_duplicates_handled_cleanly(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sub1 = os.path.join(tmpdir, "folder1")
            sub2 = os.path.join(tmpdir, "folder2")
            f1 = os.path.join(sub1, "Cambium24_MidCase_hourly_p89_2030.csv")
            f2 = os.path.join(sub2, "Cambium24_MidCase_hourly_p89_2030.csv")

            # Identical data
            _create_mock_cambium_ba_csv(f1, scenario="MidCase", ba="p89", year="2030", load_multiplier=1.0)
            _create_mock_cambium_ba_csv(f2, scenario="MidCase", ba="p89", year="2030", load_multiplier=1.0)

            matched = find_cambium_ba_file(tmpdir, ba="p89", planning_year="2030", selected_scenario="MidCase")
            assert matched in (f1, f2)

    def test_missing_data_reporting(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Provide only p89, missing p90 for AL
            f_p89 = os.path.join(tmpdir, "Cambium24_MidCase_hourly_p89_2030.csv")
            _create_mock_cambium_ba_csv(f_p89, scenario="MidCase", ba="p89", year="2030")

            res = load_cambium_net_demand_proxy_for_portfolio(
                target_states=["AL"],
                selected_scenario="MidCase",
                planning_year="2030",
                raw_directory=tmpdir,
            )
            assert res["status"] == "missing_data"
            assert res["is_qualified"] is False
            assert "p90" in res["missing_bas_by_state"]["AL"]

    def test_unsupported_scenario_raises_error(self):
        with pytest.raises(ValueError, match="Unsupported or unknown Cambium scenario"):
            get_scenario_package_info("CompletelyBogusScenario")

        with pytest.raises(ValueError, match="Unsupported or unknown Cambium scenario"):
            download_cambium_data(
                target_states=["AL"],
                selected_scenario="CompletelyBogusScenario",
                planning_year="2030",
            )
