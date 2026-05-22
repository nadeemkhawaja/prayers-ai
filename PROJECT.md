# Prayers AI — Complete Project Document

A consolidated reference covering every requirement, decision, file, output, and runtime detail discussed so far. This supersedes nothing — `SESSION_SUMMARY.md` remains the original session log — but this file is the single source of truth going forward, including the **post-Docker migration to plain processes on fixed ports**.

---

## 1. What the app is

A minimalist Progressive Web App that shows **live iqamah (congregation) prayer times** for 5 mosques in the Murphy / Wylie / Plano, TX area. It is intentionally:

- Vanilla HTML / CSS / JS — no frameworks, no build step
- A single-page PWA installable on iOS and Android
- Backed by a small Python scraper that refreshes `data.json` on a schedule
- Originally hosted on GitHub Pages; now also runnable as two long-lived processes on any Linux/macOS server

---

## 2. Mosques covered

| ID    | Name                                       | Address                                   | Source       |
| ----- | ------------------------------------------ | ----------------------------------------- | ------------ |
| icw   | Islamic Center of Wylie (ICW)              | 3990 Lakeway Dr, St. Paul, TX 75098       | live scrape  |
| epic  | EPIC Masjid                                | 4700 14th Street, Plano, TX 75074         | live scrape  |
| noori | Noori Masjid                               | Wylie, TX 75098                           | live scrape  |
| iaqc  | IAQC – Islamic Association of Quad Cities  | 3800 Parker Rd, St. Paul, TX 75098        | hardcoded    |
| iacc  | Plano Masjid (IACC)                        | 6401 Independence Pkwy, Plano, TX 75023   | hardcoded    |

Hardcoded mosques live in `prayer_times.json` and are intended to be hand-updated every 2–4 weeks as Maghrib (sunset) shifts.

---

## 3. Core requirements & constraints

- **Iqamah-only display.** Adhan (call-to-prayer) times are scraped but never rendered in the UI.
- **5 prayers per mosque:** Fajr, Dhuhr, Asr, Maghrib, Isha. Plus 1–2 Jumu’ah slots on Fridays.
- **Free, key-less data sources.** No paid APIs, no API keys for prayer times.
- **PWA-ready** on iOS and Android (`apple-mobile-web-app-capable`, `viewport-fit=cover`, full manifest + icons).
- **Resilient parsing.** Each scraper has fallbacks; failed mosques degrade gracefully without breaking the page.
- **Single source of truth = `data.json`.** The frontend only reads `./data.json`. Everything else is implementation detail.
- **Jumu’ah validity filter** rejects any time outside the 11 AM – 4 PM window to keep stray Fajr/Asr matches out of the Jumu’ah row.
- **GitHub Pages compatible** (legacy mode): scraper commits and pushes `data.json` if `GITHUB_TOKEN` + `GITHUB_REPO` env vars are set; otherwise it just writes the file locally.

---

## 4. Repository layout (current)

```
/Users/nkhawaja/Downloads/Claud Programming/Prayers AI/
├── index.html                # PWA frontend (single file, vanilla JS)
├── manifest.json             # PWA manifest
├── data.json                 # Written by server, served to frontend
├── prayer_times.json         # Hardcoded mosques (IAQC, IACC, Noori fallback)
├── server.py                 # Single-process app: static files + scraper + API on :8080
├── start.sh                  # Convenience launcher
├── deploy/
│   └── prayers-ai.service    # systemd unit
├── scraper/
│   ├── scrape.py             # The scraper (importable; `scrape.main()`)
│   └── requirements.txt      # requests, beautifulsoup4, lxml
├── SESSION_SUMMARY.md        # Original session notes (pre-migration)
└── PROJECT.md                # This file
```

Removed during the Docker→process migration:

- `docker-compose.yml`, `scraper/Dockerfile`, `scraper/entrypoint.sh`

Removed during the single-port consolidation:

- `backend.py`, `frontend.py`, `deploy/prayers-ai-backend.service`, `deploy/prayers-ai-frontend.service` — all replaced by `server.py` + `deploy/prayers-ai.service`.

---

## 5. Runtime architecture

One Python process. No Docker, no external scheduler, no second port.

```
                 ┌────────────────────────────────────────┐
                 │  Server (any Linux / macOS host)       │
                 │                                        │
   browser ───►  │  :8080  server.py                      │
   (PWA)         │           - serves index.html,         │
                 │             manifest.json, data.json,  │
                 │             icons/                     │
                 │           - background thread runs     │
                 │             scrape.main() at startup   │
                 │             and every                  │
                 │             SCRAPE_INTERVAL_HOURS      │
                 │           - GET  /health               │
                 │           - POST /api/refresh          │
                 │                                        │
                 │  ./data.json  (written + served)       │
                 └────────────────────────────────────────┘
```

Key invariant: **`server.py` both writes and serves `data.json` from the project root.** The browser hits `./data.json` relatively, so no JS changes were ever needed.

### Port

| Variable                | Default |
| ----------------------- | ------- |
| `PORT`                  | 8080    |
| `SCRAPE_INTERVAL_HOURS` | 12      |

### Endpoints

| Method | Path           | Behavior                                                |
| ------ | -------------- | ------------------------------------------------------- |
| GET    | `/`, `/index.html`, `/data.json`, `/manifest.json`, `/icons/*` | Static files |
| GET    | `/health`      | `{status, last_run, last_status, running}`              |
| POST   | `/api/refresh` | Queues an immediate scrape in a background thread (202) |

### Scheduler

- Runs `scrape.main()` once at startup.
- Then sleeps `SCRAPE_INTERVAL_HOURS` (default 12) and repeats.
- A mutex prevents overlapping runs even if `/api/refresh` is hit during a scrape.
- This replaces the previous Docker cron (`0 4 1,15 * *`). The new default (every 12 h) keeps Maghrib drift tight; tune as needed.

---

## 6. How to run

### Local / quick

```bash
cd "/path/to/Prayers AI"
pip install -r scraper/requirements.txt
./start.sh
# App + API: http://localhost:8080
```

`start.sh` sources `.env` if present, exports defaults, installs deps, and `exec`s `server.py`. Ctrl-C stops it.

### Moving to another server

1. Copy the entire project directory to the target (e.g. `/opt/prayers-ai`).
2. Create a service user: `sudo useradd -r -s /usr/sbin/nologin prayers && sudo chown -R prayers:prayers /opt/prayers-ai`.
3. Install deps: `sudo -u prayers python3 -m pip install --user -r /opt/prayers-ai/scraper/requirements.txt` (or use a venv).
4. Install the systemd unit:
   ```bash
   sudo cp /opt/prayers-ai/deploy/prayers-ai.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now prayers-ai
   ```
5. (Optional) Front with nginx / Caddy on :80/:443 → proxy to :8080.
6. (Optional) Create `/opt/prayers-ai/.env` with `GITHUB_TOKEN=...` and `GITHUB_REPO=nadeemkhawaja/prayers-ai` if you still want the scraper to push to GitHub Pages.

### Environment variables

| Variable                 | Default     | Purpose                                                 |
| ------------------------ | ----------- | ------------------------------------------------------- |
| `PORT`                   | 8080        | HTTP port for the whole app                             |
| `SCRAPE_INTERVAL_HOURS`  | 12          | How often the scraper re-runs                           |
| `REPO_PATH`              | project dir | Where `data.json` and `prayer_times.json` live          |
| `GITHUB_TOKEN`           | unset       | Optional. If set, scraper commits + pushes `data.json`  |
| `GITHUB_REPO`            | unset       | Optional. e.g. `nadeemkhawaja/prayers-ai`               |

---

## 7. Data contract — `data.json`

Written atomically by the scraper. Shape:

```json
{
  "last_updated": "2026-04-18T04:26:24",
  "last_updated_display": "April 18, 2026 at 04:26 AM",
  "mosques": [
    {
      "id": "icw",
      "name": "Islamic Center of Wylie (ICW)",
      "address": "3990 Lakeway Dr, St. Paul, TX 75098",
      "website": "https://icwtx.org",
      "phone": "",
      "status": "live" | "hardcoded" | "stale",
      "prayers": {
        "fajr":    {"adhan": "05:41 AM", "iqamah": "06:15 AM"},
        "dhuhr":   {"adhan": "01:26 PM", "iqamah": "02:00 PM"},
        "asr":     {"adhan": "05:04 PM", "iqamah": "06:15 PM"},
        "maghrib": {"adhan": "07:59 PM", "iqamah": "08:09 PM"},
        "isha":    {"adhan": "09:11 PM", "iqamah": "09:30 PM"}
      },
      "jumuah": ["02:15 PM"]
    }
  ]
}
```

`status` values:

- `live` — successfully scraped this run
- `hardcoded` — read from `prayer_times.json` (IAQC, IACC always; Noori on parse failure)
- `stale` — last scrape failed, kept previous values

---

## 8. Scraper logic (`scraper/scrape.py`)

### Entry point
`scrape.main()` — importable and idempotent. The new backend imports and calls it directly instead of `subprocess`-ing it.

### Per-mosque strategies

- **ICW** — line-by-line text parser over `soup.get_text("\n")`. Homepage cards lay out `Prayer → adhan time → "Iqamah" → iqamah time` across separate lines. DOM traversal fails because the markup is generated and nested unpredictably; line-based parsing is far more robust.
  ```python
  lines = [ln.strip() for ln in soup.get_text("\n").split("\n") if ln.strip()]
  for i, line in enumerate(lines):
      for prayer in PRAYER_KEYS:
          if re.match(rf"^{prayer}$", line, re.IGNORECASE) and prayer not in prayers:
              for j in range(i + 1, min(i + 9, len(lines))):
                  if re.match(r"^iqamah$", lines[j], re.IGNORECASE):
                      ...
  ```

- **EPIC** — table-based extractor (`extract_from_table`) + keyword proximity fallback.

- **Noori** — table extractor; on failure falls back to hardcoded `["2:10 PM", "3:10 PM"]` Jumu’ah due to a known Unicode apostrophe issue on the source page.

- **IAQC, IACC** — never scraped. Loaded from `prayer_times.json` via `load_hardcoded()`.

### Jumu’ah validity filter

```python
def is_jumuah_time(t: str) -> bool:
    m = re.match(r"(\d{1,2}):(\d{2})\s*([AP]M)", t, re.IGNORECASE)
    if not m: return False
    h = int(m.group(1))
    ap = m.group(3).upper()
    if ap == "PM" and h != 12: h += 12
    if ap == "AM" and h == 12: h = 0
    return 11 <= h <= 16
```

### Path resolution

```python
ROOT = Path(os.environ.get('REPO_PATH', Path.cwd()))
```

`server.py` sets `REPO_PATH` to the project directory before importing `scrape`, so writes always land in the right place regardless of CWD.

### Optional GitHub push

`push_to_github()` runs at the end of `main()` and is a no-op unless both `GITHUB_TOKEN` and `GITHUB_REPO` are set. Useful if you still want the existing GitHub Pages mirror updated.

---

## 9. Frontend (`index.html`)

- Single file, no build, no framework.
- Fetches `./data.json?t=<timestamp>` (cache-busted) on load and on pull-to-refresh.
- Two tables:
  - **Prayer matrix** — rows = mosques, columns = Fajr/Dhuhr/Asr/Maghrib/Isha. Iqamah only. Next-prayer column highlighted in gold.
  - **Jumu’ah** — rows = mosques, column = tagged time buttons.
- Each mosque row shows `📍 Map` and `🌐 Website` links inline with its name.
- Real-time **next-prayer countdown banner** (gold).
- Friday-only Jumu’ah banner.
- Dark mode toggle (persisted via `localStorage`).
- PWA install button and native share button.
- iOS- and Android-friendly viewport and theme color.

Static assets and `/api/*` share the same origin (single port), so there is no CORS surface at all. `/health` and `/api/refresh` are for ops use and can be firewalled off without affecting the PWA.

---

## 10. Maintenance notes

- **Maghrib drifts ~2 min/week** as sunset shifts. Edit `prayer_times.json` every 2–4 weeks for IAQC and IACC; the live-scraped mosques self-update.
- **If a scraper breaks**, the mosque’s `status` flips to `stale` and prior values stay on screen — the page never goes blank.
- **Force a manual refresh**: `curl -X POST http://<host>:8080/api/refresh`.
- **Check status**: `curl http://<host>:8080/health`.
- **Logs**: `journalctl -u prayers-ai -f` (or stdout if run via `start.sh`).
- **Tune cadence**: raise `SCRAPE_INTERVAL_HOURS` to be gentler on mosque websites, or lower it if you want tighter Maghrib alignment.

---

## 11. Verified output (most recent scrape, 2026-04-27)

| Mosque | Fajr    | Dhuhr   | Asr     | Maghrib | Isha    | Jumu’ah         |
| ------ | ------- | ------- | ------- | ------- | ------- | --------------- |
| ICW    | 6:00 AM | 2:00 PM | 6:30 PM | 8:16 PM | 9:45 PM | 2:15 PM         |
| EPIC   | 6:00 AM | 2:00 PM | 6:15 PM | 8:16 PM | 9:30 PM | 1:45 / 3:15 PM  |
| Noori  | 6:15 AM | 2:00 PM | 6:30 PM | 8:11 PM | 9:50 PM | 2:10 / 3:10 PM  |
| IAQC   | 6:00 AM | 2:00 PM | 6:00 PM | 8:04 PM | 9:30 PM | 1:30 / 2:30 PM  |
| IACC   | 6:00 AM | 2:00 PM | 6:15 PM | 8:09 PM | 9:30 PM | 1:45 / 3:00 PM  |

---

## 12. Key historical decisions

- **Noori replaced Faizan-e-Madinah** — closer to the target ZIP code and easier to scrape.
- **Iqamah-only UI** — adhan column was removed entirely to reduce visual noise; the data is still captured.
- **Two-table layout** beat the original 5-card layout for at-a-glance comparison.
- **Docker compose `up` (not `run`)** was used historically so the container persisted in Docker Desktop. *This is no longer relevant — Docker has been removed.*
- **Cron 1st & 15th @ 4 AM (in container)** is replaced by an in-process scheduler at a configurable interval (default 12 h).
- **GitHub Pages remains supported** but is now optional rather than central. The processes can stand alone on any host.

---

## 13. Migration summary (this session)

**Step 1 — Docker → processes.** Removed `docker-compose.yml`, `scraper/Dockerfile`, `scraper/entrypoint.sh`. Added a two-process design (backend on 8080, frontend on 8081). Smoke-tested.

**Step 2 — Consolidation to a single port.** Merged backend and frontend into one `server.py` on port 8080. The merge gave us:
- One port to firewall / TLS-terminate / reverse-proxy.
- Same-origin static + `/api/*` → zero CORS surface.
- One process, one systemd unit, one log stream.
- Slightly lower RAM (one Python interpreter).
- No risk of frontend and backend ever drifting on `data.json` — the same process writes and serves it.

Final added files:
- `server.py` — static files + scheduler + `/health` + `/api/refresh`, all on `PORT` (default 8080).
- `start.sh` — `exec`s `server.py` after loading `.env` and installing deps.
- `deploy/prayers-ai.service` — single systemd unit.
- `PROJECT.md` — this document.

Smoke-tested on macOS: process starts, scraper kicks off on launch, `/health` → 200, `/index.html` → 200, `/data.json` → 200, `POST /api/refresh` → 202. Ready to copy to any Linux server.
