"""
Tests for scrape.main() — orchestration, fallback logic, and data.json output.
All scrapers and push_to_github are mocked; only the merge/write logic is exercised.
"""
import json
from unittest.mock import patch

import pytest

import scrape


def _live():
    return {
        "prayers": {k: {"adhan": "5:00 AM", "iqamah": "5:30 AM"} for k in scrape.PRAYER_KEYS},
        "jumuah": ["1:30 PM"],
        "status": "live",
    }


def _hardcoded():
    return {
        "prayers": {k: {"adhan": "5:00 AM", "iqamah": "5:00 AM"} for k in scrape.PRAYER_KEYS},
        "jumuah": ["2:00 PM"],
        "status": "hardcoded",
    }


class TestScraperMain:
    def test_five_mosques_written_when_all_succeed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(scrape, "DATA_FILE", tmp_path / "data.json")
        hc = _hardcoded()
        with patch.multiple("scrape",
                            scrape_icw=lambda: _live(),
                            scrape_epic=lambda: _live(),
                            scrape_noori=lambda: _live(),
                            load_hardcoded=lambda k: hc,
                            push_to_github=lambda: True):
            scrape.main()
        output = json.loads((tmp_path / "data.json").read_text())
        assert len(output["mosques"]) == 5
        assert {m["id"] for m in output["mosques"]} == {"icw", "epic", "noori", "iaqc", "iacc"}

    def test_icw_failure_produces_fallback_status(self, tmp_path, monkeypatch):
        monkeypatch.setattr(scrape, "DATA_FILE", tmp_path / "data.json")
        hc = _hardcoded()
        with patch.multiple("scrape",
                            scrape_icw=lambda: None,
                            scrape_epic=lambda: _live(),
                            scrape_noori=lambda: _live(),
                            load_hardcoded=lambda k: hc,
                            push_to_github=lambda: True):
            scrape.main()
        output = json.loads((tmp_path / "data.json").read_text())
        icw = next(m for m in output["mosques"] if m["id"] == "icw")
        assert icw["status"] == "fallback"

    def test_epic_failure_produces_fallback_status(self, tmp_path, monkeypatch):
        monkeypatch.setattr(scrape, "DATA_FILE", tmp_path / "data.json")
        hc = _hardcoded()
        with patch.multiple("scrape",
                            scrape_icw=lambda: _live(),
                            scrape_epic=lambda: None,
                            scrape_noori=lambda: _live(),
                            load_hardcoded=lambda k: hc,
                            push_to_github=lambda: True):
            scrape.main()
        output = json.loads((tmp_path / "data.json").read_text())
        epic = next(m for m in output["mosques"] if m["id"] == "epic")
        assert epic["status"] == "fallback"

    def test_noori_failure_produces_fallback_status(self, tmp_path, monkeypatch):
        monkeypatch.setattr(scrape, "DATA_FILE", tmp_path / "data.json")
        hc = _hardcoded()
        with patch.multiple("scrape",
                            scrape_icw=lambda: _live(),
                            scrape_epic=lambda: _live(),
                            scrape_noori=lambda: None,
                            load_hardcoded=lambda k: hc,
                            push_to_github=lambda: True):
            scrape.main()
        output = json.loads((tmp_path / "data.json").read_text())
        noori = next(m for m in output["mosques"] if m["id"] == "noori")
        assert noori["status"] == "fallback"

    def test_all_live_scrapers_fail_three_fallbacks(self, tmp_path, monkeypatch):
        monkeypatch.setattr(scrape, "DATA_FILE", tmp_path / "data.json")
        hc = _hardcoded()
        with patch.multiple("scrape",
                            scrape_icw=lambda: None,
                            scrape_epic=lambda: None,
                            scrape_noori=lambda: None,
                            load_hardcoded=lambda k: hc,
                            push_to_github=lambda: True):
            scrape.main()
        output = json.loads((tmp_path / "data.json").read_text())
        fallbacks = [m for m in output["mosques"] if m["status"] == "fallback"]
        assert len(fallbacks) == 3

    def test_output_has_timestamp_fields(self, tmp_path, monkeypatch):
        monkeypatch.setattr(scrape, "DATA_FILE", tmp_path / "data.json")
        hc = _hardcoded()
        with patch.multiple("scrape",
                            scrape_icw=lambda: _live(),
                            scrape_epic=lambda: _live(),
                            scrape_noori=lambda: _live(),
                            load_hardcoded=lambda k: hc,
                            push_to_github=lambda: True):
            scrape.main()
        output = json.loads((tmp_path / "data.json").read_text())
        assert "last_updated" in output
        assert "last_updated_display" in output

    def test_mosque_entries_have_required_fields(self, tmp_path, monkeypatch):
        monkeypatch.setattr(scrape, "DATA_FILE", tmp_path / "data.json")
        hc = _hardcoded()
        with patch.multiple("scrape",
                            scrape_icw=lambda: _live(),
                            scrape_epic=lambda: _live(),
                            scrape_noori=lambda: _live(),
                            load_hardcoded=lambda k: hc,
                            push_to_github=lambda: True):
            scrape.main()
        output = json.loads((tmp_path / "data.json").read_text())
        for m in output["mosques"]:
            assert {"id", "name", "address", "website", "prayers", "jumuah", "status"} <= m.keys()

    def test_hardcoded_failure_omits_mosque_from_output(self, tmp_path, monkeypatch):
        """If load_hardcoded returns None, the mosque is not written to data.json."""
        monkeypatch.setattr(scrape, "DATA_FILE", tmp_path / "data.json")
        with patch.multiple("scrape",
                            scrape_icw=lambda: _live(),
                            scrape_epic=lambda: _live(),
                            scrape_noori=lambda: _live(),
                            load_hardcoded=lambda k: None,
                            push_to_github=lambda: True):
            scrape.main()
        output = json.loads((tmp_path / "data.json").read_text())
        ids = {m["id"] for m in output["mosques"]}
        assert "iaqc" not in ids
        assert "iacc" not in ids
        assert len(output["mosques"]) == 3

    def test_push_to_github_called_exactly_once(self, tmp_path, monkeypatch):
        monkeypatch.setattr(scrape, "DATA_FILE", tmp_path / "data.json")
        hc = _hardcoded()
        push_calls = {"n": 0}

        def fake_push():
            push_calls["n"] += 1
            return True

        with patch.multiple("scrape",
                            scrape_icw=lambda: _live(),
                            scrape_epic=lambda: _live(),
                            scrape_noori=lambda: _live(),
                            load_hardcoded=lambda k: hc,
                            push_to_github=fake_push):
            scrape.main()

        assert push_calls["n"] == 1

    def test_icw_live_data_uses_scraped_prayers(self, tmp_path, monkeypatch):
        """When ICW scrapes successfully, its prayer times come from the scraper."""
        monkeypatch.setattr(scrape, "DATA_FILE", tmp_path / "data.json")
        hc = _hardcoded()
        custom_icw = {
            "prayers": {"fajr": {"adhan": "4:59 AM", "iqamah": "5:45 AM"},
                        **{k: {"adhan": "1:00 AM", "iqamah": "1:00 AM"}
                           for k in ["dhuhr", "asr", "maghrib", "isha"]}},
            "jumuah": ["3:00 PM"],
            "status": "live",
        }
        with patch.multiple("scrape",
                            scrape_icw=lambda: custom_icw,
                            scrape_epic=lambda: _live(),
                            scrape_noori=lambda: _live(),
                            load_hardcoded=lambda k: hc,
                            push_to_github=lambda: True):
            scrape.main()
        output = json.loads((tmp_path / "data.json").read_text())
        icw = next(m for m in output["mosques"] if m["id"] == "icw")
        assert icw["prayers"]["fajr"]["iqamah"] == "5:45 AM"
        assert icw["jumuah"] == ["3:00 PM"]
