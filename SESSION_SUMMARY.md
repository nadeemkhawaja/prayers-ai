# Prayers AI — Full Session Summary

## 1. Key Requirements & Constraints

- **Single-file vanilla HTML/CSS/JS PWA** — no frameworks, no build tools
- **GitHub Pages hosted** at `https://nadeemkhawaja.github.io/prayers-ai/`
- **5 mosques** in Murphy/Wylie/Plano TX area
- **Iqamah (congregation) times only** — adhan times never shown to users
- **Data sources:**
  - ICW, EPIC, Noori → live-scraped via Python/BeautifulSoup
  - IAQC, IACC → hardcoded in `prayer_times.json` (static sites)
- **Docker container** (`prayers-ai`) scrapes and pushes `data.json` to GitHub
- **Free APIs only** — no API keys needed anywhere
- **iOS + Android PWA** ready (apple-mobile-web-app-capable, viewport-fit=cover)

---

## 2. Current Status

All features complete and live. Latest commit: `74d2497`

**Live site:** `https://nadeemkhawaja.github.io/prayers-ai/`  
**GitHub:** `https://github.com/nadeemkhawaja/prayers-ai`

**Verified times (2026-04-27 scrape):**
| Mosque | Fajr | Dhuhr | Asr | Maghrib | Isha | Jumu'ah |
|---|---|---|---|---|---|---|
| ICW | 6:00 AM | 2:00 PM | 6:30 PM | 8:16 PM | 9:45 PM | 2:15 PM |
| EPIC | 6:00 AM | 2:00 PM | 6:15 PM | 8:16 PM | 9:30 PM | 1:45 / 3:15 PM |
| Noori | 6:15 AM | 2:00 PM | 6:30 PM | 8:11 PM | 9:50 PM | 2:10 / 3:10 PM |
| IAQC | 6:00 AM | 2:00 PM | 6:00 PM | 8:04 PM | 9:30 PM | 1:30 / 2:30 PM |
| IACC | 6:00 AM | 2:00 PM | 6:15 PM | 8:09 PM | 9:30 PM | 1:45 / 3:00 PM |

---

## 3. Key Decisions

- **Noori replaced Faizan-e-Madinah** — closer to ZIP code, easier to scrape
- **Iqamah-only display** — adhan column removed entirely from UI
- **ICW scraper uses line-by-line text parser** — not DOM traversal; homepage cards have `Prayer → time → Iqamah → time` structure across separate lines
- **Jumuah validity filter** — `is_jumuah_time()` rejects times outside 11 AM–4 PM to prevent Fajr/Asr times polluting Jumu'ah slots
- **Docker `docker compose up`** (not `run`) — gives named persistent container in Docker Desktop
- **ROOT path** uses `REPO_PATH` env var or `Path.cwd()` (Docker WORKDIR is `/repo` = correct)
- **UI: two tables** instead of 5 individual cards — one prayer matrix (mosques × prayers), one Jumu'ah table
- **Cron: 1st and 15th of every month at 4 AM** — entrypoint also runs scraper immediately on container start

---

## 4. Finalized Code & Logic

### File Locations
```
/Users/nkhawaja/Downloads/Claud Programming/Prayers AI/
├── index.html              ← PWA frontend (two-table layout)
├── data.json               ← Written by scraper, read by frontend
├── prayer_times.json       ← Hardcoded IAQC & IACC times
├── manifest.json           ← PWA manifest
├── docker-compose.yml      ← restart: unless-stopped
├── .env                    ← GITHUB_TOKEN, GITHUB_REPO (gitignored)
└── scraper/
    ├── scrape.py
    ├── Dockerfile
    ├── entrypoint.sh       ← runs scraper + starts cron daemon
    └── requirements.txt
```

### ICW Line-by-Line Parser (`scrape.py`)
```python
lines = [ln.strip() for ln in soup.get_text("\n").split("\n") if ln.strip()]
for i, line in enumerate(lines):
    for prayer in PRAYER_KEYS:
        if re.match(rf"^{prayer}$", line, re.IGNORECASE) and prayer not in prayers:
            for j in range(i + 1, min(i + 9, len(lines))):
                if re.match(r"^iqamah$", lines[j], re.IGNORECASE):
                    adhan_t = next((normalize_time(t) for k in range(i+1,j) for t in TIME_RE.findall(lines[k])), "")
                    iqamah_t = ""
                    if j + 1 < len(lines):
                        found = TIME_RE.findall(lines[j + 1])
                        if found:
                            iqamah_t = normalize_time(found[0])
                    if iqamah_t:
                        prayers[prayer] = {"adhan": adhan_t, "iqamah": iqamah_t}
                    break
```

### Jumu'ah Validity Filter
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

### ROOT Path (critical — prevents `/` in container)
```python
ROOT = Path(os.environ.get('REPO_PATH', Path.cwd()))
```

### Dockerfile (with cron)
```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git cron && rm -rf /var/lib/apt/lists/*
WORKDIR /scraper
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY scrape.py .
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
# Cron: 1st and 15th of every month at 4 AM
RUN echo "0 4 1,15 * * . /etc/environment; python /scraper/scrape.py >> /var/log/scraper.log 2>&1" | crontab -
WORKDIR /repo
CMD ["/entrypoint.sh"]
```

### entrypoint.sh
```bash
#!/bin/bash
set -e
printenv | grep -E '^(GITHUB_TOKEN|GITHUB_REPO|REPO_PATH)' > /etc/environment
echo "[entrypoint] Running scraper now..."
python /scraper/scrape.py
echo "[entrypoint] Starting cron daemon..."
cron -f
```

### docker-compose.yml
```yaml
services:
  prayers-ai:
    container_name: prayers-ai
    build:
      context: ./scraper
      dockerfile: Dockerfile
    volumes:
      - .:/repo
    env_file:
      - .env
    restart: unless-stopped
```

### prayer_times.json (hardcoded mosques)
```json
{
  "mosques": {
    "iaqc": {
      "prayers": { "fajr":"6:00 AM","dhuhr":"2:00 PM","asr":"6:00 PM","maghrib":"8:04 PM","isha":"9:30 PM" },
      "jumuah": ["1:30 PM","2:30 PM"]
    },
    "iacc": {
      "prayers": { "fajr":"6:00 AM","dhuhr":"2:00 PM","asr":"6:15 PM","maghrib":"8:09 PM","isha":"9:30 PM" },
      "jumuah": ["1:45 PM","3:00 PM"]
    }
  }
}
```

### UI — Two-Table Layout (index.html)
- **Table 1** — Prayer matrix: rows = mosques, columns = Fajr/Dhuhr/Asr/Maghrib/Isha; next-prayer column highlighted in gold
- **Table 2** — Jumu'ah: rows = mosques, column = tagged time buttons
- Map/Website links inside mosque name cell (📍 Map · 🌐 Website)
- Next prayer countdown banner (gold, counts down in real-time)
- Jumu'ah banner shown on Fridays
- Dark mode (localStorage), pull-to-refresh, PWA install button, share button

---

## 5. Known Caveats / Manual Maintenance

- **Maghrib is approximate** — hardcoded times drift ~2 min/week as sunset shifts; update `prayer_times.json` every 2–4 weeks
- **IAQC / IACC** times are fully manual — visit their sites to verify if something looks off
- **Noori Jumu'ah fallback** = `["2:10 PM", "3:10 PM"]` if live parse fails (Unicode apostrophe issue)
- **Container behavior:** `docker compose up` → runs scraper immediately + stays running for cron. To force a manual refresh, stop and start the container in Docker Desktop.
- **Cron schedule:** 1st and 15th of each month at 4 AM (inside container). Check `/var/log/scraper.log` inside container to verify cron ran.
