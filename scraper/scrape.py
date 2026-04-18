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
ROOT = Path(os.environ.get('REPO_PATH', Path.cwd()))
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


def is_jumuah_time(t: str) -> bool:
    """Jumuah is always between 11 AM and 4 PM."""
    m = re.match(r"(\d{1,2}):(\d{2})\s*([AP]M)", t, re.IGNORECASE)
    if not m:
        return False
    h = int(m.group(1))
    ap = m.group(3).upper()
    if ap == "PM" and h != 12:
        h += 12
    if ap == "AM" and h == 12:
        h = 0
    return 11 <= h <= 16


def extract_jumuah_from_table(soup: BeautifulSoup) -> list[str]:
    times = []
    for row in soup.find_all("tr"):
        text = row.get_text(" ", strip=True)
        if re.search(r"jum[ua']+h|friday|جمعة", text, re.IGNORECASE):
            found = TIME_RE.findall(text)
            times.extend([normalize_time(t) for t in found if is_jumuah_time(t)])
    # Also search divs/spans
    for elem in soup.find_all(string=re.compile(r"jum[ua']+h|friday", re.IGNORECASE)):
        parent = elem.find_parent()
        for _ in range(4):
            if parent is None:
                break
            found = TIME_RE.findall(parent.get_text())
            valid = [normalize_time(t) for t in found if is_jumuah_time(t)]
            if valid:
                times.extend(valid)
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
# ICW Scraper — icwtx.org homepage
# Cards show: Prayer Name \n Adhan Time \n Iqamah \n Iqamah Time
# We use newline-aware text pattern to match each card reliably.
# ---------------------------------------------------------------------------

def scrape_icw() -> dict | None:
    url = "https://icwtx.org"
    log.info("Scraping ICW homepage: %s", url)
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")

        prayers = {}
        jumuah = []

        # ICW homepage card structure (line-by-line):
        #   Fajr          ← prayer name (exact line)
        #   05:41 AM      ← adhan time
        #   Iqamah        ← label (exact line)
        #   06:15 AM      ← iqamah time  ← WE WANT THIS
        #
        # Parse line-by-line: find prayer name, scan ahead for "Iqamah",
        # take the time on the NEXT line as the iqamah.
        lines = [ln.strip() for ln in soup.get_text("\n").split("\n") if ln.strip()]
        for i, line in enumerate(lines):
            for prayer in PRAYER_KEYS:
                if re.match(rf"^{prayer}$", line, re.IGNORECASE) and prayer not in prayers:
                    # Scan next 8 lines for "Iqamah" label
                    for j in range(i + 1, min(i + 9, len(lines))):
                        if re.match(r"^iqamah$", lines[j], re.IGNORECASE):
                            # Adhan = first time between prayer name and "Iqamah"
                            adhan_t = next(
                                (normalize_time(t)
                                 for k in range(i + 1, j)
                                 for t in TIME_RE.findall(lines[k])),
                                ""
                            )
                            # Iqamah = first time on the line AFTER "Iqamah"
                            iqamah_t = ""
                            if j + 1 < len(lines):
                                found = TIME_RE.findall(lines[j + 1])
                                if found:
                                    iqamah_t = normalize_time(found[0])
                            if iqamah_t:
                                prayers[prayer] = {"adhan": adhan_t, "iqamah": iqamah_t}
                            break

        # Fallback: generic table parser
        if not prayers:
            parsed = extract_from_table(soup)
            if parsed:
                prayers = parsed

        # ICW Jumuah — same line-by-line: find "Jumu'ah" then "Iqamah" then time
        for i, line in enumerate(lines):
            if re.search(r"jum[ua'\u2019]+h", line, re.IGNORECASE):
                for j in range(i + 1, min(i + 9, len(lines))):
                    if re.match(r"^iqamah$", lines[j], re.IGNORECASE):
                        if j + 1 < len(lines):
                            found = [normalize_time(t)
                                     for t in TIME_RE.findall(lines[j + 1])
                                     if is_jumuah_time(t)]
                            if found:
                                jumuah = found[:2]
                        break
                if jumuah:
                    break
        if not jumuah:
            jumuah = ["2:15 PM"]

        if len(prayers) >= 4:
            log.info("ICW scraped OK — prayers: %s, jumuah: %s",
                     {k: v["iqamah"] for k, v in prayers.items()}, jumuah)
            return {"prayers": prayers, "jumuah": jumuah, "status": "live"}

        log.warning("ICW: could not parse prayer times, will use fallback")
        return None

    except Exception as e:
        log.error("ICW scrape error: %s", e)
        return None


# ---------------------------------------------------------------------------
# Faizan-E-Madinah Scraper — us.mohid.co/tx/dallas/didfw
# MOHID platform shows Azaan + Iqama times in a consistent table
# ---------------------------------------------------------------------------

def scrape_faizan() -> dict | None:
    url = "https://us.mohid.co/tx/dallas/didfw"
    log.info("Scraping Faizan (MOHID): %s", url)
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")

        prayers = {}
        jumuah = []

        # MOHID shows a table: Prayer | Azaan | Iqama
        parsed = extract_from_table(soup)
        if parsed:
            prayers = parsed

        # Fallback: keyword proximity
        if not prayers:
            for prayer in PRAYER_KEYS:
                times = find_times_near_keyword(soup, prayer)
                if times:
                    prayers[prayer] = {
                        "adhan":  times[0],
                        "iqamah": times[-1] if len(times) > 1 else times[0],
                    }

        # Jumuah from MOHID page
        jumuah = extract_jumuah_from_table(soup)

        if len(prayers) >= 4:
            log.info("Faizan scraped OK — prayers: %s, jumuah: %s",
                     {k: v["iqamah"] for k, v in prayers.items()}, jumuah)
            return {"prayers": prayers, "jumuah": jumuah or ["2:00 PM"], "status": "live"}

        log.warning("Faizan: could not parse, will use fallback")
        return None

    except Exception as e:
        log.error("Faizan scrape error: %s", e)
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

        # EPIC labels rows "1st Jumuah" / "2nd Jumuah" — parse precisely, deduplicate
        jumuah_seen: set = set()
        jumuah = []
        for row in soup.find_all("tr"):
            text = row.get_text(" ", strip=True)
            if re.search(r"\d(st|nd|rd)\s*jum[ua']+h", text, re.IGNORECASE):
                for t in TIME_RE.findall(text):
                    nt = normalize_time(t)
                    if is_jumuah_time(nt) and nt not in jumuah_seen:
                        jumuah_seen.add(nt)
                        jumuah.append(nt)
        if not jumuah:
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
# Noori Masjid Scraper — noorimasjid.net
# Table: Prayer | Start Time | Jama't Time (congregation)
# ---------------------------------------------------------------------------

def scrape_noori() -> dict | None:
    url = "https://noorimasjid.net/"
    log.info("Scraping Noori Masjid: %s", url)
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")

        prayers = {}
        jumuah = []
        PRAYER_MAP = {"zuhar": "dhuhr", "zuhr": "dhuhr"}  # name aliases

        # Table: Prayer | Start Time | Jama't Time
        for table in soup.find_all("table"):
            for row in soup.find_all("tr"):
                text = row.get_text(" ", strip=True)
                times = TIME_RE.findall(text)
                if len(times) < 2:
                    continue
                for prayer in PRAYER_KEYS + list(PRAYER_MAP.keys()):
                    if re.search(rf"\b{prayer}\b", text, re.IGNORECASE):
                        key = PRAYER_MAP.get(prayer.lower(), prayer.lower())
                        if key in PRAYER_KEYS and key not in prayers:
                            prayers[key] = {
                                "adhan":  normalize_time(times[0]),
                                "iqamah": normalize_time(times[-1]),
                            }

        # Fallback: keyword proximity
        if not prayers:
            for prayer in PRAYER_KEYS:
                times = find_times_near_keyword(soup, prayer)
                if times:
                    prayers[prayer] = {
                        "adhan":  times[0],
                        "iqamah": times[-1] if len(times) > 1 else times[0],
                    }

        # Jumuah — Noori labels congregation time as "Jama'at"
        full_text = soup.get_text("\n", strip=True)
        # Noori Jumuah: Jama'at times are on separate lines from label,
        # making regex unreliable. Use line-by-line: find "Jama'at" line,
        # get time from next non-empty line.
        jum_times = []
        nlines = full_text.split("\n")
        for i, ln in enumerate(nlines):
            if re.search(r"jama.{0,10}at", ln, re.IGNORECASE):
                # Look at next 3 lines for a time
                for k in range(i + 1, min(i + 4, len(nlines))):
                    found = [normalize_time(t) for t in TIME_RE.findall(nlines[k])
                             if is_jumuah_time(t)]
                    if found:
                        for t in found:
                            if t not in jum_times:
                                jum_times.append(t)
                        break
        jumuah = jum_times[:2] if len(jum_times) >= 2 else NOORI_JUMUAH_FALLBACK

        if len(prayers) >= 4:
            log.info("Noori scraped OK — prayers: %s, jumuah: %s",
                     {k: v["iqamah"] for k, v in prayers.items()}, jumuah)
            return {"prayers": prayers, "jumuah": jumuah or NOORI_JUMUAH_FALLBACK, "status": "live"}

        log.warning("Noori: could not parse prayer times, will use fallback")
        return None

    except Exception as e:
        log.error("Noori scrape error: %s", e)
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
    "fajr":    {"adhan": "5:41 AM", "iqamah": "6:15 AM"},
    "dhuhr":   {"adhan": "1:26 PM", "iqamah": "2:00 PM"},
    "asr":     {"adhan": "5:04 PM", "iqamah": "6:15 PM"},
    "maghrib": {"adhan": "7:59 PM", "iqamah": "8:09 PM"},
    "isha":    {"adhan": "9:11 PM", "iqamah": "9:30 PM"},
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

NOORI_FALLBACK = {
    "fajr":    {"adhan": "5:29 AM", "iqamah": "6:15 AM"},
    "dhuhr":   {"adhan": "1:27 PM", "iqamah": "2:00 PM"},
    "asr":     {"adhan": "6:07 PM", "iqamah": "6:30 PM"},
    "maghrib": {"adhan": "8:02 PM", "iqamah": "8:04 PM"},
    "isha":    {"adhan": "9:25 PM", "iqamah": "9:40 PM"},
}
NOORI_JUMUAH_FALLBACK = ["2:10 PM", "3:10 PM"]


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
    "noori": {
        "name": "Noori Masjid",
        "address": "Wylie, TX 75098",
        "website": "https://noorimasjid.net",
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

    # --- Noori Masjid (live scrape) ---
    noori_data = scrape_noori()
    if noori_data:
        mosques.append(build_mosque_entry("noori", noori_data, "live"))
    else:
        log.info("Noori: using fallback times")
        mosques.append(build_mosque_entry("noori", {
            "prayers": NOORI_FALLBACK,
            "jumuah": NOORI_JUMUAH_FALLBACK,
        }, "fallback"))

    # --- IAQC, IACC (hardcoded) ---
    for key in ["iaqc", "iacc"]:
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
