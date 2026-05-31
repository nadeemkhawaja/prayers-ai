"""
Tests for pure helper functions in scrape.py.
No network calls; all inputs are constructed in-process.
"""
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from bs4 import BeautifulSoup

import scrape


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


# ---------------------------------------------------------------------------
# normalize_time
# ---------------------------------------------------------------------------

class TestNormalizeTime:
    def test_passthrough(self):
        assert scrape.normalize_time("6:00 AM") == "6:00 AM"

    def test_strips_leading_trailing_whitespace(self):
        assert scrape.normalize_time("  6:00 AM  ") == "6:00 AM"

    def test_uppercases_am(self):
        assert scrape.normalize_time("6:00 am") == "6:00 AM"

    def test_uppercases_pm(self):
        assert scrape.normalize_time("6:00 pm") == "6:00 PM"

    def test_collapses_internal_whitespace(self):
        assert scrape.normalize_time("6:00  AM") == "6:00 AM"

    def test_mixed_case(self):
        assert scrape.normalize_time("6:00 Pm") == "6:00 PM"

    def test_zero_padded_hour(self):
        assert scrape.normalize_time("05:41 AM") == "05:41 AM"


# ---------------------------------------------------------------------------
# is_jumuah_time
# ---------------------------------------------------------------------------

class TestIsJumuahTime:
    def test_11am_lower_boundary(self):
        assert scrape.is_jumuah_time("11:00 AM") is True

    def test_4pm_upper_boundary(self):
        assert scrape.is_jumuah_time("4:00 PM") is True

    def test_midday_valid(self):
        assert scrape.is_jumuah_time("1:30 PM") is True

    def test_noon_pm_valid(self):
        # 12:00 PM → h stays 12, 11 ≤ 12 ≤ 16
        assert scrape.is_jumuah_time("12:00 PM") is True

    def test_midnight_am_invalid(self):
        # 12:00 AM → h becomes 0, below 11
        assert scrape.is_jumuah_time("12:00 AM") is False

    def test_too_early(self):
        assert scrape.is_jumuah_time("10:59 AM") is False

    def test_too_late(self):
        assert scrape.is_jumuah_time("5:00 PM") is False

    def test_lowercase_input(self):
        assert scrape.is_jumuah_time("1:30 pm") is True

    def test_malformed_returns_false(self):
        assert scrape.is_jumuah_time("not-a-time") is False

    def test_empty_string_returns_false(self):
        assert scrape.is_jumuah_time("") is False


# ---------------------------------------------------------------------------
# extract_from_table
# ---------------------------------------------------------------------------

class TestExtractFromTable:
    def test_parses_five_prayers(self):
        html = """<table>
            <tr><td>Fajr</td><td>5:00 AM</td><td>5:30 AM</td></tr>
            <tr><td>Dhuhr</td><td>1:00 PM</td><td>1:30 PM</td></tr>
            <tr><td>Asr</td><td>5:00 PM</td><td>5:30 PM</td></tr>
            <tr><td>Maghrib</td><td>7:00 PM</td><td>7:05 PM</td></tr>
            <tr><td>Isha</td><td>9:00 PM</td><td>9:30 PM</td></tr>
        </table>"""
        result = scrape.extract_from_table(soup(html))
        assert result is not None
        assert result["fajr"]["adhan"] == "5:00 AM"
        assert result["fajr"]["iqamah"] == "5:30 AM"
        assert result["maghrib"]["adhan"] == "7:00 PM"
        assert result["maghrib"]["iqamah"] == "7:05 PM"

    def test_last_time_used_as_iqamah(self):
        html = """<table>
            <tr><td>Fajr</td><td>5:00 AM</td><td>5:15 AM</td><td>5:30 AM</td></tr>
            <tr><td>Dhuhr</td><td>1:00 PM</td><td>1:30 PM</td></tr>
            <tr><td>Asr</td><td>5:00 PM</td><td>5:30 PM</td></tr>
            <tr><td>Maghrib</td><td>7:00 PM</td><td>7:05 PM</td></tr>
        </table>"""
        result = scrape.extract_from_table(soup(html))
        assert result is not None
        assert result["fajr"]["adhan"] == "5:00 AM"
        assert result["fajr"]["iqamah"] == "5:30 AM"

    def test_single_time_row_uses_it_for_both(self):
        html = """<table>
            <tr><td>Fajr</td><td>5:00 AM</td></tr>
            <tr><td>Dhuhr</td><td>1:00 PM</td></tr>
            <tr><td>Asr</td><td>5:00 PM</td></tr>
            <tr><td>Maghrib</td><td>7:00 PM</td></tr>
        </table>"""
        result = scrape.extract_from_table(soup(html))
        assert result is not None
        assert result["fajr"]["adhan"] == "5:00 AM"
        assert result["fajr"]["iqamah"] == "5:00 AM"

    def test_fewer_than_4_prayers_returns_none(self):
        html = """<table>
            <tr><td>Fajr</td><td>5:00 AM</td><td>5:30 AM</td></tr>
            <tr><td>Dhuhr</td><td>1:00 PM</td><td>1:30 PM</td></tr>
            <tr><td>Asr</td><td>5:00 PM</td><td>5:30 PM</td></tr>
        </table>"""
        result = scrape.extract_from_table(soup(html))
        assert result is None

    def test_no_table_returns_none(self):
        result = scrape.extract_from_table(soup("<div>No tables here</div>"))
        assert result is None

    def test_case_insensitive_prayer_names(self):
        html = """<table>
            <tr><td>FAJR</td><td>5:00 AM</td><td>5:30 AM</td></tr>
            <tr><td>DHUHR</td><td>1:00 PM</td><td>1:30 PM</td></tr>
            <tr><td>ASR</td><td>5:00 PM</td><td>5:30 PM</td></tr>
            <tr><td>MAGHRIB</td><td>7:00 PM</td><td>7:05 PM</td></tr>
        </table>"""
        result = scrape.extract_from_table(soup(html))
        assert result is not None
        assert "fajr" in result


# ---------------------------------------------------------------------------
# find_times_near_keyword
# ---------------------------------------------------------------------------

class TestFindTimesNearKeyword:
    def test_finds_time_in_same_element(self):
        html = "<div>Fajr: 5:00 AM</div>"
        result = scrape.find_times_near_keyword(soup(html), "Fajr")
        assert "5:00 AM" in result

    def test_finds_time_in_parent_element(self):
        # Space between spans is required: get_text() concatenates without it,
        # which breaks the \b word-boundary in TIME_RE.
        html = "<div><span>Fajr</span> <span>5:00 AM</span></div>"
        result = scrape.find_times_near_keyword(soup(html), "Fajr")
        assert "5:00 AM" in result

    def test_returns_empty_list_when_no_keyword(self):
        html = "<div>5:00 AM</div>"
        result = scrape.find_times_near_keyword(soup(html), "Fajr")
        assert result == []

    def test_returns_empty_list_when_no_time_near_keyword(self):
        html = "<div>Fajr prayer info here</div>"
        result = scrape.find_times_near_keyword(soup(html), "Fajr")
        assert result == []

    def test_normalizes_returned_times(self):
        html = "<div>Fajr 5:00 am</div>"
        result = scrape.find_times_near_keyword(soup(html), "Fajr")
        assert "5:00 AM" in result


# ---------------------------------------------------------------------------
# extract_jumuah_from_table
# ---------------------------------------------------------------------------

class TestExtractJumuahFromTable:
    def test_finds_jumuah_time_in_table_row(self):
        html = "<table><tr><td>Jumuah</td><td>1:30 PM</td></tr></table>"
        result = scrape.extract_jumuah_from_table(soup(html))
        assert "1:30 PM" in result

    def test_finds_friday_keyword(self):
        html = "<table><tr><td>Friday Prayer</td><td>2:00 PM</td></tr></table>"
        result = scrape.extract_jumuah_from_table(soup(html))
        assert "2:00 PM" in result

    def test_filters_out_non_jumuah_times(self):
        html = "<table><tr><td>Jumuah</td><td>10:00 AM</td><td>6:00 PM</td></tr></table>"
        result = scrape.extract_jumuah_from_table(soup(html))
        assert result == []

    def test_deduplicates_times(self):
        html = """<table>
            <tr><td>Jumuah</td><td>1:30 PM</td></tr>
            <tr><td>Friday</td><td>1:30 PM</td></tr>
        </table>"""
        result = scrape.extract_jumuah_from_table(soup(html))
        assert result.count("1:30 PM") == 1

    def test_caps_results_at_three(self):
        html = """<table>
            <tr><td>Jumuah 1</td><td>12:00 PM</td></tr>
            <tr><td>Jumuah 2</td><td>1:00 PM</td></tr>
            <tr><td>Jumuah 3</td><td>2:00 PM</td></tr>
            <tr><td>Jumuah 4</td><td>3:00 PM</td></tr>
        </table>"""
        result = scrape.extract_jumuah_from_table(soup(html))
        assert len(result) <= 3

    def test_finds_jumuah_in_divs_via_keyword_proximity(self):
        # Space between siblings so <div>.get_text() produces "Friday 1:30 PM"
        # and the \b boundary before "1" is satisfied.
        html = "<div><p>Friday</p> <p>1:30 PM</p></div>"
        result = scrape.extract_jumuah_from_table(soup(html))
        assert "1:30 PM" in result


# ---------------------------------------------------------------------------
# build_mosque_entry
# ---------------------------------------------------------------------------

class TestBuildMosqueEntry:
    def test_basic_shape(self):
        prayer_data = {
            "prayers": {"fajr": {"adhan": "5:00 AM", "iqamah": "5:30 AM"}},
            "jumuah": ["1:30 PM"],
        }
        entry = scrape.build_mosque_entry("icw", prayer_data, "live")
        assert entry["id"] == "icw"
        assert entry["name"] == "Islamic Center of Wylie (ICW)"
        assert entry["status"] == "live"
        assert entry["prayers"] == prayer_data["prayers"]
        assert entry["jumuah"] == ["1:30 PM"]

    def test_includes_meta_fields(self):
        prayer_data = {"prayers": {}, "jumuah": []}
        entry = scrape.build_mosque_entry("epic", prayer_data, "fallback")
        assert "address" in entry
        assert "website" in entry
        assert "phone" in entry

    def test_missing_jumuah_key_defaults_to_empty_list(self):
        prayer_data = {"prayers": {}}
        entry = scrape.build_mosque_entry("iaqc", prayer_data, "hardcoded")
        assert entry["jumuah"] == []

    def test_fallback_status_preserved(self):
        prayer_data = {"prayers": {}, "jumuah": []}
        entry = scrape.build_mosque_entry("noori", prayer_data, "fallback")
        assert entry["status"] == "fallback"


# ---------------------------------------------------------------------------
# load_hardcoded
# ---------------------------------------------------------------------------

class TestLoadHardcoded:
    def test_loads_valid_mosque(self, tmp_path, monkeypatch):
        config = {
            "mosques": {
                "test_mosque": {
                    "prayers": {
                        "fajr":    "5:00 AM",
                        "dhuhr":   "1:00 PM",
                        "asr":     "5:00 PM",
                        "maghrib": "7:00 PM",
                        "isha":    "9:00 PM",
                    },
                    "jumuah": ["1:30 PM", "2:30 PM"],
                }
            }
        }
        config_file = tmp_path / "prayer_times.json"
        config_file.write_text(json.dumps(config))
        monkeypatch.setattr(scrape, "CONFIG_FILE", config_file)

        result = scrape.load_hardcoded("test_mosque")
        assert result is not None
        assert result["status"] == "hardcoded"
        assert result["prayers"]["fajr"]["adhan"] == "5:00 AM"
        assert result["prayers"]["fajr"]["iqamah"] == "5:00 AM"
        assert result["jumuah"] == ["1:30 PM", "2:30 PM"]

    def test_adhan_equals_iqamah_for_hardcoded(self, tmp_path, monkeypatch):
        config = {
            "mosques": {
                "m": {"prayers": {"dhuhr": "1:00 PM"}, "jumuah": []}
            }
        }
        config_file = tmp_path / "prayer_times.json"
        config_file.write_text(json.dumps(config))
        monkeypatch.setattr(scrape, "CONFIG_FILE", config_file)

        result = scrape.load_hardcoded("m")
        assert result["prayers"]["dhuhr"]["adhan"] == result["prayers"]["dhuhr"]["iqamah"]

    def test_missing_key_returns_none(self, tmp_path, monkeypatch):
        config = {"mosques": {}}
        config_file = tmp_path / "prayer_times.json"
        config_file.write_text(json.dumps(config))
        monkeypatch.setattr(scrape, "CONFIG_FILE", config_file)

        result = scrape.load_hardcoded("nonexistent")
        assert result is None

    def test_file_not_found_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(scrape, "CONFIG_FILE", tmp_path / "missing.json")
        result = scrape.load_hardcoded("iaqc")
        assert result is None

    def test_loads_real_iaqc_config(self):
        result = scrape.load_hardcoded("iaqc")
        assert result is not None
        assert result["status"] == "hardcoded"
        assert set(result["prayers"].keys()) >= {"fajr", "dhuhr", "asr", "maghrib", "isha"}

    def test_loads_real_iacc_config(self):
        result = scrape.load_hardcoded("iacc")
        assert result is not None
        assert len(result["jumuah"]) > 0

    def test_malformed_json_returns_none(self, tmp_path, monkeypatch):
        bad = tmp_path / "prayer_times.json"
        bad.write_text("{ not valid json !!}")
        monkeypatch.setattr(scrape, "CONFIG_FILE", bad)
        assert scrape.load_hardcoded("iaqc") is None

    def test_missing_mosques_key_returns_none(self, tmp_path, monkeypatch):
        config = {"something_else": {}}
        config_file = tmp_path / "prayer_times.json"
        config_file.write_text(json.dumps(config))
        monkeypatch.setattr(scrape, "CONFIG_FILE", config_file)
        assert scrape.load_hardcoded("iaqc") is None

    def test_jumuah_defaults_to_empty_list_when_key_absent(self, tmp_path, monkeypatch):
        config = {"mosques": {"m": {"prayers": {"fajr": "5:00 AM"}}}}
        config_file = tmp_path / "prayer_times.json"
        config_file.write_text(json.dumps(config))
        monkeypatch.setattr(scrape, "CONFIG_FILE", config_file)
        result = scrape.load_hardcoded("m")
        assert result is not None
        assert result["jumuah"] == []

    def test_partial_config_only_returns_requested_mosque(self, tmp_path, monkeypatch):
        """File has multiple mosques; only the requested one is returned."""
        config = {
            "mosques": {
                "iaqc": {"prayers": {"fajr": "5:00 AM"}, "jumuah": []},
                "iacc": {"prayers": {"fajr": "5:10 AM"}, "jumuah": ["1:30 PM"]},
            }
        }
        config_file = tmp_path / "prayer_times.json"
        config_file.write_text(json.dumps(config))
        monkeypatch.setattr(scrape, "CONFIG_FILE", config_file)

        iaqc = scrape.load_hardcoded("iaqc")
        iacc = scrape.load_hardcoded("iacc")
        assert iaqc["prayers"]["fajr"]["adhan"] == "5:00 AM"
        assert iacc["prayers"]["fajr"]["adhan"] == "5:10 AM"


# ---------------------------------------------------------------------------
# push_to_github (env-var paths only; no subprocess calls)
# ---------------------------------------------------------------------------

class TestPushToGithub:
    def test_returns_false_when_token_missing(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_REPO", raising=False)
        assert scrape.push_to_github() is False

    def test_returns_false_when_repo_missing(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        monkeypatch.delenv("GITHUB_REPO", raising=False)
        assert scrape.push_to_github() is False

    def test_returns_true_when_no_staged_changes(self, monkeypatch):
        """No staged changes → skips commit/push and returns True."""
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        monkeypatch.setenv("GITHUB_REPO", "owner/repo")
        calls = []
        no_change = MagicMock()
        no_change.returncode = 0

        def fake_run(cmd, **kw):
            calls.append(list(cmd))
            if cmd[:2] == ["git", "diff"]:
                return no_change
            return MagicMock()

        with patch("scrape.subprocess.run", side_effect=fake_run):
            result = scrape.push_to_github()

        assert result is True
        flat = [" ".join(c) for c in calls]
        assert not any("commit" in c for c in flat)
        assert not any("push" in c for c in flat)

    def test_commits_and_pushes_when_changes_exist(self, monkeypatch):
        """Staged changes present → git commit and git push are called."""
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        monkeypatch.setenv("GITHUB_REPO", "owner/repo")
        calls = []
        has_changes = MagicMock()
        has_changes.returncode = 1

        def fake_run(cmd, **kw):
            calls.append(list(cmd))
            if cmd[:2] == ["git", "diff"]:
                return has_changes
            return MagicMock()

        with patch("scrape.subprocess.run", side_effect=fake_run):
            result = scrape.push_to_github()

        assert result is True
        flat = [" ".join(c) for c in calls]
        assert any("commit" in c for c in flat)
        assert any("push" in c for c in flat)

    def test_remote_url_contains_token_and_repo(self, monkeypatch):
        """Remote URL embeds the auth token and repo slug."""
        monkeypatch.setenv("GITHUB_TOKEN", "secret123")
        monkeypatch.setenv("GITHUB_REPO", "myorg/myrepo")
        calls = []
        no_change = MagicMock()
        no_change.returncode = 0

        def fake_run(cmd, **kw):
            calls.append(list(cmd))
            if cmd[:2] == ["git", "diff"]:
                return no_change
            return MagicMock()

        with patch("scrape.subprocess.run", side_effect=fake_run):
            scrape.push_to_github()

        set_url = next((c for c in calls if "set-url" in c), None)
        assert set_url is not None
        assert "secret123" in set_url[-1]
        assert "myorg/myrepo" in set_url[-1]

    def test_stages_data_json_before_diff(self, monkeypatch):
        """git add data.json is always called before the diff check."""
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        monkeypatch.setenv("GITHUB_REPO", "owner/repo")
        calls = []
        no_change = MagicMock()
        no_change.returncode = 0

        def fake_run(cmd, **kw):
            calls.append(list(cmd))
            if cmd[:2] == ["git", "diff"]:
                return no_change
            return MagicMock()

        with patch("scrape.subprocess.run", side_effect=fake_run):
            scrape.push_to_github()

        assert ["git", "add", "data.json"] in calls

    def test_returns_false_on_subprocess_error(self, monkeypatch):
        """CalledProcessError from any git command returns False."""
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        monkeypatch.setenv("GITHUB_REPO", "owner/repo")
        error = subprocess.CalledProcessError(1, "git", b"", b"fatal: error")
        with patch("scrape.subprocess.run", side_effect=error):
            assert scrape.push_to_github() is False
