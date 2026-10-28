"""
tests/test_cambium_downloader.py — Unit Tests for Automated Cambium Downloader
==============================================================================
"""

import os
import io
import pytest
import tempfile
import pandas as pd
from cambium_downloader import (
    STATE_TO_BALANCING_AREAS,
    REEDS_HIERARCHY_COMMIT_SHA,
    REEDS_CAMBIUM24_AGGREG_MAP,
    DEFERRED_CAMBIUM_STATES,
    SCENARIO_PACKAGE_MAP,
    PROJECT_UUIDS,
    RemoteZipReader,
    check_missing_cambium_data,
    pd_read_first_rows,
    validate_cambium_state_mapping,
    check_missing_cambium_gea_data_for_states,
    download_missing_cambium_gea_data,
    download_cambium_gea_data,
)
from config import CONTIGUOUS_48_STATES


class TestCambiumDownloaderConfig:
    """Verifies geographic mappings and Scenario Viewer project manifests."""

    def test_southeast_states_covered(self):
        for st in ["AL", "GA", "TN", "NC", "SC", "FL", "MS", "VA"]:
            assert st in STATE_TO_BALANCING_AREAS
            bas = STATE_TO_BALANCING_AREAS[st]
            assert len(bas) >= 1
            assert all(ba.startswith("p") for ba in bas)

    def test_all_48_contiguous_states_covered_and_partition_p1_to_p134(self):
        assert set(STATE_TO_BALANCING_AREAS.keys()) == set(CONTIGUOUS_48_STATES)
        assert len(STATE_TO_BALANCING_AREAS) == 48
        assert len(REEDS_HIERARCHY_COMMIT_SHA) == 40

        all_bas = []
        for st, bas in STATE_TO_BALANCING_AREAS.items():
            assert len(bas) >= 1, f"State {st} has no ReEDS regions"
            assert all(ba.startswith("p") for ba in bas)
            all_bas.extend(bas)

        expected_p = {f"p{i}" for i in range(1, 135)}
        assert set(all_bas) == expected_p
        assert len(all_bas) == 134  # Exact 1-to-1 partition of p1..p134 across 48 states

    def test_pa_cambium24_z122_aggregation_map(self):
        assert REEDS_CAMBIUM24_AGGREG_MAP.get("p119") == "z122"
        assert REEDS_CAMBIUM24_AGGREG_MAP.get("p122") == "z122"
        assert "p119" in STATE_TO_BALANCING_AREAS["PA"]
        assert "p122" in STATE_TO_BALANCING_AREAS["PA"]

    def test_deferred_geographies_rejected_explicitly(self):
        for deferred_st in ["AK", "HI", "PR", "VI", "GU", "AS", "MP", "DC"]:
            assert deferred_st in DEFERRED_CAMBIUM_STATES
            with pytest.raises(ValueError, match="Unsupported geography"):
                validate_cambium_state_mapping([deferred_st])

    def test_scenario_package_map_structure(self):
        for scen, pkg in SCENARIO_PACKAGE_MAP.items():
            assert "project_uuid" in pkg
            assert "file_id" in pkg
            assert isinstance(pkg["file_id"], int)
            assert len(pkg["project_uuid"]) == 36


class TestRemoteZipReader:
    """Tests file-like stream navigation without network calls."""

    def test_seek_and_tell(self):
        reader = RemoteZipReader(url="http://dummy", total_length=1000)
        assert reader.tell() == 0

        reader.seek(100)
        assert reader.tell() == 100

        reader.seek(50, whence=io.SEEK_CUR)
        assert reader.tell() == 150

        reader.seek(-20, whence=io.SEEK_END)
        assert reader.tell() == 980

    def test_invalid_whence(self):
        reader = RemoteZipReader(url="http://dummy", total_length=1000)
        with pytest.raises(ValueError):
            reader.seek(10, whence=99)

    def test_read_boundary(self):
        reader = RemoteZipReader(url="http://dummy", total_length=100)
        reader.seek(100)
        assert reader.read(10) == b""


class TestMissingDataDetection:
    """Tests checking whether Cambium files exist locally."""

    def test_empty_directory_flags_all(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = check_missing_cambium_data(
                target_states=["GA", "AL"],
                selected_scenario="MidCase",
                planning_year="2040",
                input_directory=tmpdir
            )
            assert set(missing) == {"GA", "AL"}

    def test_detected_file_reduces_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a mock raw NREL file for GA
            mock_file = os.path.join(tmpdir, "Cambium24_MidCase_hourly_p94_2040.csv")
            with open(mock_file, "w", encoding="utf-8") as f:
                f.write("Project,Scenario,Dollar_year,Weather_year,Start_day,r,state,gea,country,tz,t\n")
                f.write("Cambium24,MidCase,2023$,2012,Sunday,p94,GA,SERTP,usa,ET,2040\n")
                f.write("meta1,meta2\n")
                f.write("meta3,meta4\n")
                f.write("meta5,meta6\n")
                f.write("Hour,energy_cost_enduse,lrmer_co2e\n")
                f.write("1,25.0,400.0\n")

            missing = check_missing_cambium_data(
                target_states=["GA", "AL"],
                selected_scenario="MidCase",
                planning_year="2040",
                input_directory=tmpdir
            )
            assert missing == ["AL"]
            assert "GA" not in missing

    def test_pd_read_first_rows(self):
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as f:
            f.write("state,scenario,t\n")
            f.write("GA,MidCase,2040\n")
            tmp_name = f.name

        try:
            res = pd_read_first_rows(tmp_name)
            assert res is not None
            assert res["cols"] == ["state", "scenario", "t"]
            assert res["meta"]["state"] == "GA"
            assert res["meta"]["scenario"] == "MidCase"
        finally:
            os.remove(tmp_name)


class TestGeaConstituentDownloader:
    """Verifies detection and extraction logic for regional GEA datasets."""

    def test_check_missing_cambium_gea_data_for_states(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = check_missing_cambium_gea_data_for_states(
                target_states=['AL'],
                selected_scenario='MidCase',
                planning_year='2030',
                input_directory=tmpdir
            )
            # AL maps to SERTP with 11 BAs
            assert 'SERTP' in missing
            assert len(missing['SERTP']) == 11
            assert 'p89' in missing['SERTP']
            assert 'p90' in missing['SERTP']

    def test_partial_gea_detection_filters_existing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Pre-create p89 and p90 in tmpdir
            for p in ['p89', 'p90']:
                with open(os.path.join(tmpdir, f'Cambium24_MidCase_hourly_{p}_2030.csv'), 'w') as f:
                    f.write('dummy,data\n1,2\n')

            missing = check_missing_cambium_gea_data_for_states(
                target_states=['AL'],
                selected_scenario='MidCase',
                planning_year='2030',
                input_directory=tmpdir
            )
            assert 'SERTP' in missing
            # Should have 9 missing (11 total - 2 present)
            assert len(missing['SERTP']) == 9
            assert 'p89' not in missing['SERTP']
            assert 'p90' not in missing['SERTP']
            assert 'p88' in missing['SERTP']

    def test_download_missing_cambium_gea_data_delegation(self, monkeypatch):
        called = {}
        def mock_download_cambium_gea_data(geas, selected_scenario, planning_year, **kwargs):
            called['geas'] = geas
            called['target_bas_subset'] = kwargs.get('target_bas_subset')
            return ['/mock/path.csv']

        monkeypatch.setattr('cambium_downloader.download_cambium_gea_data', mock_download_cambium_gea_data)
        missing_dict = {'SERTP': ['p88', 'p91', 'p92']}
        res = download_missing_cambium_gea_data(
            missing_bas_by_gea=missing_dict,
            selected_scenario='MidCase',
            planning_year='2030'
        )
        assert res == ['/mock/path.csv']
        assert called['geas'] == ['SERTP']
        assert set(called['target_bas_subset']) == {'p88', 'p91', 'p92'}

    def test_data_loaders_auto_download_delegation(self, monkeypatch):
        from data_loaders import load_cambium_net_demand_stress_weights
        dl_called = {}
        def mock_download_missing(missing_bas_by_gea, **kwargs):
            dl_called['missing'] = missing_bas_by_gea
            return ['/mock/p88.csv']

        monkeypatch.setattr('cambium_downloader.download_missing_cambium_gea_data', mock_download_missing)
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                res = load_cambium_net_demand_stress_weights(
                    target_states=['AL'],
                    selected_scenario='MidCase',
                    planning_year='2030',
                    raw_directory=tmpdir,
                    auto_download_missing=True,
                    aggregation_level="gea",
                )
            except Exception:
                pass
            assert 'missing' in dl_called
            assert 'SERTP' in dl_called['missing']


class TestParseCambiumColumns:
    """Verifies dynamic column mapping, prioritizing enduse over busbar."""

    def test_prioritizes_energy_cost_enduse_over_busbar(self):
        from data_loaders import parse_cambium_columns
        df = pd.DataFrame(columns=[
            'energy_cost_busbar',
            'energy_cost_enduse',
            'aer_gen_co2_c',
            'Hour',
        ])
        hr_c, energy_c, carbon_c = parse_cambium_columns(df)
        assert energy_c == 'energy_cost_enduse'
        assert carbon_c == 'aer_gen_co2_c'
        assert hr_c == 'Hour'

    def test_falls_back_to_busbar_when_enduse_missing(self):
        from data_loaders import parse_cambium_columns
        df = pd.DataFrame(columns=[
            'energy_cost_busbar',
            'lrmer_co2e',
            'hour',
        ])
        hr_c, energy_c, carbon_c = parse_cambium_columns(df)
        assert energy_c == 'energy_cost_busbar'
        assert carbon_c == 'lrmer_co2e'
        assert hr_c == 'hour'
