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
    SCENARIO_PACKAGE_MAP,
    PROJECT_UUIDS,
    RemoteZipReader,
    check_missing_cambium_data,
    pd_read_first_rows,
)


class TestCambiumDownloaderConfig:
    """Verifies geographic mappings and Scenario Viewer project manifests."""

    def test_southeast_states_covered(self):
        for st in ["AL", "GA", "TN", "NC", "SC", "FL", "MS", "VA"]:
            assert st in STATE_TO_BALANCING_AREAS
            bas = STATE_TO_BALANCING_AREAS[st]
            assert len(bas) >= 1
            assert all(ba.startswith("p") for ba in bas)

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
