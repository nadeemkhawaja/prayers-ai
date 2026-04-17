#!/usr/bin/env python3
"""
Prayers AI Scraper
------------------
Scrapes live iqamah times from ICW and EPIC Masjid.
Reads hardcoded times for IAQC, IACC, and Faizan from prayer_times.json.
Outputs data.json, then git commits + pushes to GitHub.

Run:  python scrape.py
Env:  GITHUB_TOKEN, GITHUB_REPO (e.g. nadeemkhawaja/prayers-ai)
"""

import re
import json
import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
ROOT = Path(__file__).parent.parent
DATA_FILE = ROOT / "data.json"
CONFIG_FILE = ROOT / "prayer_times.json"

TIME_RE = re.compile(r"\b(\d{1,2}:\d{2}\s*[AP]M)\b", re.IGNORECASE)
PRAYER_KEYS = ["fajr", "dhuhr", "asr", "maghrib", "isha"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize_time(t: str) -> str:
    """Ensure consistent format: '6:00 AM' → '6:00 AM'"""
    t = t.strip().upper()
    t = re.sub(r"\s+", " ", t)
    return t


def find_times_near_keyword(soup: BeautifulSoup, keyword: str) -> list[str]:
    """Search all text nodes for keyword proximity to time patterns."""
    for elem in soup.find_all(string=re.compile(keyword, re.IGNORECASE)):
        parent = elem.find_parent()
        for _ in range(4):
            if parent is None:
                break
            times = TIME_RE.findall(parent.get_text())
            if times:
                return [normalize_time(t) for t in times]
            parent = parent.find_parent()
    return []


def extract_from_table(soup: BeautifulSoup) -> dict | None:
    """Generic table parser: find rows with prayer names, extract last time as iqamah."""
    result = {}
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            text = row.get_text(" ", strip=True)
            for prayer in PRAYER_KEYS:
                if re.search(rf"\b{prayer}\b", text, re.IGNORECASE):
                    times = TIME_RE.findall(text)
                    if times:
                        result[prayer] = {
                            "adhan": normalize_time(times[0]),
                            "iqamah": normalize_time(times[-1]) if len(times) > 1 else normalize_time(times[0]),
                        }
    return result if len(result) >= 4 else None


def extract_jumuah_from_table(soup: BeautifulSoup) -> list[str]:
    times = []
    for row in soup.find_all("tr"):
        text = row.get_text(" ", strip=True)
        if re.search(r"jum[ua']+h|friday|جمعة", text, re.IGNORECASE):
            found = TIME_RE.findall(text)
            times.extend([normalize_time(t) for t in found])
    # Also search divs/spans
    for elem in soup.find_all(string=re.compile(r"jum[ua']+h|friday", re.IGNORECASE)):
        parent = elem.find_parent()
        for _ in range(4):
            if parent is None:
                break
            found = TIME_RE.findall(parent.get_text())
            if found:
                times.extend([normalize_time(t) for t in found])
                break
            parent = parent.find_parent()
    # Deduplicate preserving order
    seen = set()
    unique = []
    for t in times:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique[:3]  # cap at 3 Jumuah sessions


# ---------------------------------------------------------------------------
# ICW Scraper — icwtx.org/prayer-timings/
# Weekly table: each row is a day; find today's row by date match
# ---------------------------------------------------------------------------

def scrape_icw() -> dict | None:
    url = "https://icwtx.org/prayer-timings/"
    log.info("Scraping ICW: %s", url)
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")

        today_str = datetime.now().strftime("%m-%d-%y")   # e.g. 04-17-26
        today_alt = datetime.now().strftime("%m/%d/%Y")   # e.g. 04/17/2026
        today_alt2 = datetime.now().strftime("%-m/%-d/%Y") if os.name != "nt" else datetime.now().strftime("%#m/%#d/%Y")

        prayers = {}
        jumuah = []

        # Strategy 1: find the table row whose date cell matches today
        for row in soup.find_all("tr"):
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            row_text = " ".join(cells)
            if any(d in row_text for d in [today_str, today_alt, today_alt2]):
                times = TIME_RE.findall(row_text)
                # ICW column order: Day | Date | Fajr-Adhan | Fajr-Iqamah | Ishraq | Dhuhr-Adhan | Dhuhr-Iqamah | Asr-Adhan | Asr-Iqamah | Maghrib-Adhan | Maghrib-Iqamah | Isha-Adhan | Isha-Iqamah | Sunrise | Sunset
                # We want iqamah (2nd of each pair)
                if len(times) >= 8:
                    prayers = {
                        "fajr":    {"adhan": normalize_time(times[0]), "iqamah": normalize_time(times[1])},
                        "dhuhr":   {"adhan": normalize_time(times[3]), "iqamah": normalize_time(times[4])},
                        "asr":     {"adhan": normalize_time(times[5]), "iqamah": normalize_time(times[6])},
                        "maghrib": {"adhan": normalize_time(times[7]), "iqamah": normalize_time(times[8]) if len(times) > 8 else normalize_time(times[7])},
                        "isha":    {"adhan": normalize_time(times[9]) if len(times) > 9 else "", "iqamah": normalize_time(times[10]) if len(times) > 10 else ""},
                    }
                    break

        # Strategy 2: generic table parser as fallback
        if not prayers:
            parsed = extract_from_table(soup)
            if parsed:
                prayers = parsed

        # Jumuah from ICW page
        jumuah = extract_jumuah_from_table(soup)

        if len(prayers) >= 4:
            log.info("ICW scraped OK")
            return {"prayers": prayers, "jumuah": jumuah, "status": "live"}

        log.warning("ICW: could not parse prayer times, will use fallback")
        return None

    except Exception as e:
        log.error("ICW scrape error: %s", e)
        return None


# ---------------------------------------------------------------------------
# EPIC Masjid Scraper — epicmasjid.org (times on homepage)
# ---------------------------------------------------------------------------

def scrape_epic() -> dict | None:
    url = "https://epicmasjid.org"
    log.info("Scraping EPIC Masjid: %s", url)
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")

        prayers = {}
        jumuah = []

        # Strategy 1: table parser
        parsed = extract_from_table(soup)
        if parsed:
            prayers = parsed

        # Strategy 2: keyword proximity fallback
        if not prayers:
            for prayer in PRAYER_KEYS:
                times = find_times_near_keyword(soup, prayer)
                if times:
                    prayers[prayer] = {
                        "adhan": times[0],
                        "iqamah": times[-1] if len(times) > 1 else times[0],
                    }

        # Strategy 3: structured text scan — look for "Fajr | 05:43 AM | 06:00 AM" patterns
        if not prayers:
            full_text = soup.get_text("\n")
            for prayer in PRAYER_KEYS:
                pattern = rf"{prayer}\s*[|\-:]\s*({TIME_RE.pattern})\s*[|\-:]\s*({TIME_RE.pattern})"
                m = re.search(pattern, full_text, re.IGNORECASE)
                if m:
                    prayers[prayer] = {"adhan": normalize_time(m.group(1)), "iqamah": normalize_time(m.group(2))}

        jumuah = extract_jumuah_from_table(soup)

        if len(prayers) >= 4:
            log.info("EPIC scraped OK")
            return {"prayers": prayers, "jumuah": jumuah, "status": "live"}

        log.warning("EPIC: could not parse prayer times, will use fallback")
        return None

    except Exception as e:
        log.error("EPIC scrape error: %s", e)
        return None


# ---------------------------------------------------------------------------
# Hardcoded loader — reads prayer_times.json
# ---------------------------------------------------------------------------

def load_hardcoded(mosque_key: str) -> dict | None:
    try:
        config = json.loads(CONFIG_FILE.read_text())
        mosque = config["mosques"].get(mosque_key)
        if not mosque:
            return None
        raw = mosque["prayers"]
        prayers = {k: {"adhan": v, "iqamah": v} for k, v in raw.items()}
        return {
            "prayers": prayers,
            "jumuah": mosque.get("jumuah", []),
            "status": "hardcoded",
        }
    except Exception as e:
        log.error("Failed to load hardcoded %s: %s", mosque_key, e)
        return None


# ---------------------------------------------------------------------------
# ICW fallback — last-known good times (updated when scrape fails)
# ---------------------------------------------------------------------------

ICW_FALLBACK = {
    "fajr":    {"adhan": "5:48 AM", "iqamah": "6:15 AM"},
    "dhuhr":   {"adhan": "1:27 PM", "iqamah": "2:00 PM"},
    "asr":     {"adhan": "5:04 PM", "iqamah": "6:15 PM"},
    "maghrib": {"adhan": "7:55 PM", "iqamah": "8:05 PM"},
    "isha":    {"adhan": "9:06 PM", "iqamah": "9:30 PM"},
}
ICW_JUMUAH_FALLBACK = ["2:15 PM"]

EPIC_FALLBACK = {
    "fajr":    {"adhan": "5:43 AM", "iqamah": "6:00 AM"},
    "dhuhr":   {"adhan": "1:27 PM", "iqamah": "2:00 PM"},
    "asr":     {"adhan": "5:05 PM", "iqamah": "6:15 PM"},
    "maghrib": {"adhan": "7:59 PM", "iqamah": "8:09 PM"},
    "isha":    {"adhan": "9:10 PM", "iqamah": "9:30 PM"},
}
EPIC_JUMUAH_FALLBACK = ["1:45 PM", "3:15 PM"]


# ---------------------------------------------------------------------------
# Git push
# ---------------------------------------------------------------------------

def push_to_github() -> bool:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repo = os.environ.get("GITHUB_REPO", "").strip()  # e.g. nadeemkhawaja/prayers-ai

    if not token or not repo:
        log.warning("GITHUB_TOKEN or GITHUB_REPO not set — skipping git push")
        return False

    try:
        remote = f"https://{token}@github.com/{repo}.git"
        date_str = datetime.now().strftime("%Y-%m-%d %H:%M")

        def run(cmd, **kw):
            subprocess.run(cmd, cwd=ROOT, check=True, capture_output=True, **kw)

        run(["git", "config", "user.email", "bot@prayers-ai.local"])
        run(["git", "config", "user.name", "Prayers AI Bot"])
        run(["git", "remote", "set-url", "origin", remote])
        run(["git", "add", "data.json"])

        # Only commit if there are staged changes
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=ROOT, capture_output=True
        )
        if result.returncode == 0:
            log.info("No changes to data.json — skipping commit")
            return True

        run(["git", "commit", "-m", f"Update prayer times {date_str}"])
        run(["git", "push", "origin", "HEAD"])
        log.info("Pushed to GitHub: %s", repo)
        return True

    except subprocess.CalledProcessError as e:
        log.error("Git push failed: %s\nstdout: %s\nstderr: %s",
                  e, e.stdout.decode(errors="replace"), e.stderr.decode(errors="replace"))
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

MOSQUE_META = {
    "icw": {
        "name": "Islamic Center of Wylie (ICW)",
        "address": "3990 Lakeway Dr, St. Paul, TX 75098",
        "website": "https://icwtx.org",
        "phone": "",
    },
    "epic": {
        "name": "EPIC Masjid",
        "address": "4700 14th Street, Plano, TX 75074",
        "website": "https://epicmasjid.org",
        "phone": "(214) 396-1943",
    },
    "iaqc": {
        "name": "IAQC - Islamic Association of Quad Cities",
        "address": "3800 Parker Rd, St. Paul, TX 75098",
        "website": "https://iaqctx.org",
        "phone": "(214) 435-8961",
    },
    "iacc": {
        "name": "Plano Masjid (IACC)",
        "address": "6401 Independence Pkwy, Plano, TX 75023",
        "website": "https://planomasjid.org",
        "phone": "972-491-5800",
    },
    "faizan": {
        "name": "Masjid Faizan-E-Madinah",
        "address": "641 W Brown St, Wylie, TX 75098",
        "website": "https://www.facebook.com/faizanemadinahdallas/",
        "phone": "",
    },
}


def build_mosque_entry(mosque_id: str, prayer_data: dict, status: str) -> dict:
    meta = MOSQUE_META[mosque_id]
    return {
        "id": mosque_id,
        "name": meta["name"],
        "address": meta["address"],
        "website": meta["website"],
        "phone": meta["phone"],
        "status": status,
        "prayers": prayer_data["prayers"],
        "jumuah": prayer_data.get("jumuah", []),
    }


def main():
    log.info("=== Prayers AI Scraper starting ===")
    mosques = []

    # --- ICW (live scrape) ---
    icw_data = scrape_icw()
    if icw_data:
        mosques.append(build_mosque_entry("icw", icw_data, "live"))
    else:
        log.info("ICW: using fallback times")
        mosques.append(build_mosque_entry("icw", {
            "prayers": ICW_FALLBACK,
            "jumuah": ICW_JUMUAH_FALLBACK,
        }, "fallback"))

    # --- EPIC (live scrape) ---
    epic_data = scrape_epic()
    if epic_data:
        mosques.append(build_mosque_entry("epic", epic_data, "live"))
    else:
        log.info("EPIC: using fallback times")
        mosques.append(build_mosque_entry("epic", {
            "prayers": EPIC_FALLBACK,
            "jumuah": EPIC_JUMUAH_FALLBACK,
        }, "fallback"))

    # --- IAQC, IACC, Faizan (hardcoded) ---
    for key in ["iaqc", "iacc", "faizan"]:
        data = load_hardcoded(key)
        if data:
            mosques.append(build_mosque_entry(key, data, "hardcoded"))
        else:
            log.error("Could not load hardcoded data for %s", key)

    # Write data.json
    output = {
        "last_updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "last_updated_display": datetime.now().strftime("%B %d, %Y at %I:%M %p"),
        "mosques": mosques,
    }
    DATA_FILE.write_text(json.dumps(output, indent=2))
    log.info("Wrote %s", DATA_FILE)

    # Push to GitHub
    push_to_github()
    log.info("=== Done ===")


if __name__ == "__main__":
    main()
