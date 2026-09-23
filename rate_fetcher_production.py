# rate_fetcher_production.py
import json
import logging
import re
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

OUTPUT_FILE = "live_rate.json"
FETCH_INTERVAL = 180  # 3 minutes

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}


# --- Dummy Health Check Server for Render Web Service ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass  # Suppress HTTP access logs to keep terminal logs clean


def run_dummy_server(port=10000):
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    logging.info(f"Health check server listening on port {port}")
    server.serve_forever()


# --- Currency Fetcher Functions ---
def fetch_rate_open_er() -> float | None:
    try:
        res = requests.get("https://open.er-api.com/v6/latest/USD", timeout=5)
        if res.status_code == 200:
            rate = res.json().get("rates", {}).get("INR")
            if rate and float(rate) > 0:
                logging.info("[SUCCESS] Fetched rate from Open ExchangeRate-API")
                return float(rate)
    except Exception as e:
        logging.warning(f"[FAIL] Open ExchangeRate-API error: {e}")
    return None


def fetch_rate_revolut() -> float | None:
    url = "https://www.revolut.com/currency-converter/convert-usd-to-inr-exchange-rate/"
    try:
        res = requests.get(url, headers=HTTP_HEADERS, timeout=8)
        if res.status_code == 200:
            match = re.search(r'"rate"\s*:\s*([\d\.]+)', res.text)
            if not match:
                match = re.search(r'1\s*USD\s*=\s*([\d\.]+)\s*INR', res.text, re.IGNORECASE)
            if match:
                rate = float(match.group(1))
                if 70.0 < rate < 120.0:
                    logging.info("[SUCCESS] Fetched rate from Revolut")
                    return rate
    except Exception as e:
        logging.warning(f"[FAIL] Revolut error: {e}")
    return None


def fetch_rate_wise() -> float | None:
    url = "https://wise.com/in/currency-converter/usd-to-inr-rate?amount=1"
    try:
        res = requests.get(url, headers=HTTP_HEADERS, timeout=8)
        if res.status_code == 200:
            match = re.search(r'class="[^\"]*text-success[^\"]*">([\d\.]+)<', res.text)
            if not match:
                match = re.search(r'"rate"\s*:\s*([\d\.]+)', res.text)
            if match:
                rate = float(match.group(1))
                if 70.0 < rate < 120.0:
                    logging.info("[SUCCESS] Fetched rate from Wise")
                    return rate
    except Exception as e:
        logging.warning(f"[FAIL] Wise error: {e}")
    return None


def get_live_rate_multi_source() -> float | None:
    return fetch_rate_wise() or fetch_rate_revolut() or fetch_rate_open_er()


def main():
    # Start web port listener in a background thread for Render compatibility
    import os
    port = int(os.environ.get("PORT", 10000))
    threading.Thread(target=run_dummy_server, args=(port,), daemon=True).start()

    logging.info("Starting Multi-Source USD/INR Rate Fetcher...")
    while True:
        rate = get_live_rate_multi_source()

        if rate and rate > 0:
            data = {
                "rate": rate,
                "timestamp": time.time(),
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            with open(OUTPUT_FILE, "w") as f:
                json.dump(data, f, indent=4)
            logging.info(f"Updated {OUTPUT_FILE} -> Live Rate: {rate}")
        else:
            logging.error("All rate sources failed! Keeping cached value.")

        time.sleep(FETCH_INTERVAL)


if __name__ == "__main__":
    main()
