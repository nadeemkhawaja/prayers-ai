FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git cron && rm -rf /var/lib/apt/lists/*

WORKDIR /scraper
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY scrape.py .
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Cron: run scraper on the 1st and 15th of every month at 4 AM
RUN echo "0 4 1,15 * * . /etc/environment; python /scraper/scrape.py >> /var/log/scraper.log 2>&1" | crontab -

WORKDIR /repo

CMD ["/entrypoint.sh"]
