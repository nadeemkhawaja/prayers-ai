"""
Tests for per-mosque scraper functions.
HTTP is mocked so no live network calls are made.
Each test loads an HTML fixture that matches the real site's structure.
"""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import scrape

FIXTURES = Path(__file__).parent / "fixtures"


def _mock_response(html: str) -> MagicMock:
    resp = MagicMock()
    resp.text = html
    resp.raise_for_status.return_value = None
    return resp


def _load(name: str) -> str:
    return (FIXTURES / name).read_text()


# ---------------------------------------------------------------------------
# ICW scraper
# ---------------------------------------------------------------------------

class TestScrapeICW:
    def test_returns_five_prayers(self):
        with patch("scrape.requests.get", return_value=_mock_response(_load("icw_sample.html"))):
            result = scrape.scrape_icw()
        assert result is not None
        assert len(result["prayers"]) == 5

    def test_prayer_iqamah_times_correct(self):
        with patch("scrape.requests.get", return_value=_mock_response(_load("icw_sample.html"))):
            result = scrape.scrape_icw()
        assert result["prayers"]["fajr"]["iqamah"] == "06:15 AM"
        assert result["prayers"]["dhuhr"]["iqamah"] == "2:00 PM"
        assert result["prayers"]["asr"]["iqamah"] == "6:15 PM"
        assert result["prayers"]["maghrib"]["iqamah"] == "8:09 PM"
        assert result["prayers"]["isha"]["iqamah"] == "9:30 PM"

    def test_prayer_adhan_times_correct(self):
        with patch("scrape.requests.get", return_value=_mock_response(_load("icw_sample.html"))):
            result = scrape.scrape_icw()
        assert result["prayers"]["fajr"]["adhan"] == "05:41 AM"
        assert result["prayers"]["dhuhr"]["adhan"] == "1:26 PM"

    def test_status_is_live(self):
        with patch("scrape.requests.get", return_value=_mock_response(_load("icw_sample.html"))):
            result = scrape.scrape_icw()
        assert result["status"] == "live"

    def test_jumuah_parsed(self):
        with patch("scrape.requests.get", return_value=_mock_response(_load("icw_sample.html"))):
            result = scrape.scrape_icw()
        assert len(result["jumuah"]) > 0
        assert "2:15 PM" in result["jumuah"]

    def test_returns_none_on_empty_page(self):
        html = "<html><body><p>No prayer times here</p></body></html>"
        with patch("scrape.requests.get", return_value=_mock_response(html)):
            result = scrape.scrape_icw()
        assert result is None

    def test_returns_none_on_network_error(self):
        with patch("scrape.requests.get", side_effect=OSError("network down")):
            result = scrape.scrape_icw()
        assert result is None

    def test_returns_none_on_http_error(self):
        resp = MagicMock()
        resp.raise_for_status.side_effect = Exception("404 Not Found")
        with patch("scrape.requests.get", return_value=resp):
            result = scrape.scrape_icw()
        assert result is None

    def test_falls_back_to_table_parser(self):
        # Page with no card structure but with a valid table
        html = """<html><body><table>
            <tr><td>Fajr</td><td>5:00 AM</td><td>5:30 AM</td></tr>
            <tr><td>Dhuhr</td><td>1:00 PM</td><td>1:30 PM</td></tr>
            <tr><td>Asr</td><td>5:00 PM</td><td>5:30 PM</td></tr>
            <tr><td>Maghrib</td><td>7:00 PM</td><td>7:05 PM</td></tr>
            <tr><td>Isha</td><td>9:00 PM</td><td>9:30 PM</td></tr>
        </table></body></html>"""
        with patch("scrape.requests.get", return_value=_mock_response(html)):
            result = scrape.scrape_icw()
        assert result is not None
        assert len(result["prayers"]) >= 4

    def test_jumuah_defaults_when_not_found(self):
        # Page with prayers but no Jumuah section
        html = """<html><body>
            <p>Fajr</p><p>5:00 AM</p><p>Iqamah</p><p>5:30 AM</p>
            <p>Dhuhr</p><p>1:00 PM</p><p>Iqamah</p><p>1:30 PM</p>
            <p>Asr</p><p>5:00 PM</p><p>Iqamah</p><p>5:30 PM</p>
            <p>Maghrib</p><p>7:00 PM</p><p>Iqamah</p><p>7:05 PM</p>
            <p>Isha</p><p>9:00 PM</p><p>Iqamah</p><p>9:30 PM</p>
        </body></html>"""
        with patch("scrape.requests.get", return_value=_mock_response(html)):
            result = scrape.scrape_icw()
        assert result is not None
        # Falls back to hardcoded default
        assert result["jumuah"] == ["2:15 PM"]


# ---------------------------------------------------------------------------
# EPIC scraper
# ---------------------------------------------------------------------------

class TestScrapeEPIC:
    def test_returns_five_prayers(self):
        with patch("scrape.requests.get", return_value=_mock_response(_load("epic_sample.html"))):
            result = scrape.scrape_epic()
        assert result is not None
        assert len(result["prayers"]) == 5

    def test_prayer_iqamah_times_correct(self):
        with patch("scrape.requests.get", return_value=_mock_response(_load("epic_sample.html"))):
            result = scrape.scrape_epic()
        assert result["prayers"]["fajr"]["iqamah"] == "6:00 AM"
        assert result["prayers"]["dhuhr"]["iqamah"] == "2:00 PM"
        assert result["prayers"]["isha"]["iqamah"] == "9:30 PM"

    def test_status_is_live(self):
        with patch("scrape.requests.get", return_value=_mock_response(_load("epic_sample.html"))):
            result = scrape.scrape_epic()
        assert result["status"] == "live"

    def test_jumuah_parsed_from_numbered_rows(self):
        with patch("scrape.requests.get", return_value=_mock_response(_load("epic_sample.html"))):
            result = scrape.scrape_epic()
        assert "1:45 PM" in result["jumuah"]
        assert "3:15 PM" in result["jumuah"]

    def test_returns_none_on_empty_page(self):
        html = "<html><body><p>No prayer times here</p></body></html>"
        with patch("scrape.requests.get", return_value=_mock_response(html)):
            result = scrape.scrape_epic()
        assert result is None

    def test_returns_none_on_network_error(self):
        with patch("scrape.requests.get", side_effect=OSError("network down")):
            result = scrape.scrape_epic()
        assert result is None


# ---------------------------------------------------------------------------
# Noori scraper
# ---------------------------------------------------------------------------

class TestScrapeNoori:
    def test_returns_five_prayers(self):
        with patch("scrape.requests.get", return_value=_mock_response(_load("noori_sample.html"))):
            result = scrape.scrape_noori()
        assert result is not None
        assert len(result["prayers"]) == 5

    def test_zuhr_alias_mapped_to_dhuhr(self):
        with patch("scrape.requests.get", return_value=_mock_response(_load("noori_sample.html"))):
            result = scrape.scrape_noori()
        assert "dhuhr" in result["prayers"]

    def test_prayer_iqamah_times_correct(self):
        with patch("scrape.requests.get", return_value=_mock_response(_load("noori_sample.html"))):
            result = scrape.scrape_noori()
        assert result["prayers"]["fajr"]["iqamah"] == "6:15 AM"
        assert result["prayers"]["dhuhr"]["iqamah"] == "2:00 PM"
        assert result["prayers"]["maghrib"]["iqamah"] == "8:04 PM"

    def test_status_is_live(self):
        with patch("scrape.requests.get", return_value=_mock_response(_load("noori_sample.html"))):
            result = scrape.scrape_noori()
        assert result["status"] == "live"

    def test_jumuah_parsed_from_jamat_section(self):
        with patch("scrape.requests.get", return_value=_mock_response(_load("noori_sample.html"))):
            result = scrape.scrape_noori()
        assert "2:10 PM" in result["jumuah"]
        assert "3:10 PM" in result["jumuah"]

    def test_returns_none_on_empty_page(self):
        html = "<html><body><p>No prayer times here</p></body></html>"
        with patch("scrape.requests.get", return_value=_mock_response(html)):
            result = scrape.scrape_noori()
        assert result is None

    def test_returns_none_on_network_error(self):
        with patch("scrape.requests.get", side_effect=OSError("network down")):
            result = scrape.scrape_noori()
        assert result is None

    def test_falls_back_to_noori_jumuah_when_jamat_missing(self):
        # Valid prayers but no Jama'at section
        html = """<html><body><table>
            <tr><td>Fajr</td><td>5:29 AM</td><td>6:15 AM</td></tr>
            <tr><td>Zuhr</td><td>1:27 PM</td><td>2:00 PM</td></tr>
            <tr><td>Asr</td><td>6:07 PM</td><td>6:30 PM</td></tr>
            <tr><td>Maghrib</td><td>8:02 PM</td><td>8:04 PM</td></tr>
            <tr><td>Isha</td><td>9:25 PM</td><td>9:40 PM</td></tr>
        </table></body></html>"""
        with patch("scrape.requests.get", return_value=_mock_response(html)):
            result = scrape.scrape_noori()
        assert result is not None
        assert result["jumuah"] == scrape.NOORI_JUMUAH_FALLBACK


# ---------------------------------------------------------------------------
# Cross-scraper robustness (partial / malformed HTML)
# ---------------------------------------------------------------------------

class TestScraperEdgeCases:
    def test_icw_too_few_prayers_returns_none(self):
        """ICW page with only 3 parseable prayer cards returns None."""
        html = """<html><body>
            <p>Fajr</p><p>5:00 AM</p><p>Iqamah</p><p>5:30 AM</p>
            <p>Dhuhr</p><p>1:00 PM</p><p>Iqamah</p><p>1:30 PM</p>
            <p>Asr</p><p>5:00 PM</p><p>Iqamah</p><p>5:30 PM</p>
        </body></html>"""
        with patch("scrape.requests.get", return_value=_mock_response(html)):
            result = scrape.scrape_icw()
        assert result is None

    def test_epic_keyword_proximity_fallback(self):
        """EPIC falls back to keyword proximity when no table is present."""
        html = """<html><body>
            <div>Fajr 5:43 AM Iqamah 6:00 AM</div>
            <div>Dhuhr 1:27 PM Iqamah 2:00 PM</div>
            <div>Asr 5:05 PM Iqamah 6:15 PM</div>
            <div>Maghrib 7:59 PM Iqamah 8:09 PM</div>
            <div>Isha 9:10 PM Iqamah 9:30 PM</div>
        </body></html>"""
        with patch("scrape.requests.get", return_value=_mock_response(html)):
            result = scrape.scrape_epic()
        assert result is not None
        assert len(result["prayers"]) >= 4

    def test_noori_too_few_prayers_returns_none(self):
        """Noori page with only 3 table rows returns None."""
        html = """<html><body><table>
            <tr><td>Fajr</td><td>5:29 AM</td><td>6:15 AM</td></tr>
            <tr><td>Zuhr</td><td>1:27 PM</td><td>2:00 PM</td></tr>
            <tr><td>Asr</td><td>6:07 PM</td><td>6:30 PM</td></tr>
        </table></body></html>"""
        with patch("scrape.requests.get", return_value=_mock_response(html)):
            result = scrape.scrape_noori()
        assert result is None

    def test_icw_http_error_returns_none(self):
        resp = MagicMock()
        resp.raise_for_status.side_effect = Exception("500 Server Error")
        with patch("scrape.requests.get", return_value=resp):
            assert scrape.scrape_icw() is None

    def test_epic_http_error_returns_none(self):
        resp = MagicMock()
        resp.raise_for_status.side_effect = Exception("503 Service Unavailable")
        with patch("scrape.requests.get", return_value=resp):
            assert scrape.scrape_epic() is None

    def test_noori_connection_error_returns_none(self):
        with patch("scrape.requests.get", side_effect=ConnectionError("timeout")):
            assert scrape.scrape_noori() is None

    def test_icw_empty_iqamah_time_skips_prayer(self):
        """ICW card with no time after 'Iqamah' does not include that prayer."""
        html = """<html><body>
            <p>Fajr</p><p>5:00 AM</p><p>Iqamah</p>
            <p>Dhuhr</p><p>1:00 PM</p><p>Iqamah</p><p>1:30 PM</p>
            <p>Asr</p><p>5:00 PM</p><p>Iqamah</p><p>5:30 PM</p>
            <p>Maghrib</p><p>7:00 PM</p><p>Iqamah</p><p>7:05 PM</p>
            <p>Isha</p><p>9:00 PM</p><p>Iqamah</p><p>9:30 PM</p>
        </body></html>"""
        with patch("scrape.requests.get", return_value=_mock_response(html)):
            result = scrape.scrape_icw()
        # Fajr should not be present (no iqamah time)
        if result is not None:
            assert "fajr" not in result["prayers"]

    def test_epic_jumuah_non_standard_hours_filtered_out(self):
        """EPIC Jumuah times outside 11 AM–4 PM window are excluded."""
        html = """<html><body><table>
            <tr><td>Fajr</td><td>5:43 AM</td><td>6:00 AM</td></tr>
            <tr><td>Dhuhr</td><td>1:27 PM</td><td>2:00 PM</td></tr>
            <tr><td>Asr</td><td>5:05 PM</td><td>6:15 PM</td></tr>
            <tr><td>Maghrib</td><td>7:59 PM</td><td>8:09 PM</td></tr>
            <tr><td>Isha</td><td>9:10 PM</td><td>9:30 PM</td></tr>
            <tr><td>1st Jumuah</td><td>5:00 PM</td><td></td></tr>
            <tr><td>2nd Jumuah</td><td>9:00 AM</td><td></td></tr>
        </table></body></html>"""
        with patch("scrape.requests.get", return_value=_mock_response(html)):
            result = scrape.scrape_epic()
        assert result is not None
        assert result["jumuah"] == []  # both times outside valid window
