# rate_fetcher_production.py
import json
import logging
import os
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


# ================================================================
# WEB DISPLAY SERVER (Serves UI & satisfies Render Port Checks)
# ================================================================

class LivePriceHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        """Displays live exchange rate dashboard when visiting the URL."""
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()

        rate = "Fetching..."
        updated_at = "Pending..."
        source = "Initializing..."

        if os.path.exists(OUTPUT_FILE):
            try:
                with open(OUTPUT_FILE, "r") as f:
                    data = json.load(f)
                    rate = f"₹{data.get('rate', 'N/A')}"
                    updated_at = data.get("updated_at", "Unknown")
                    source = data.get("source", "Multi-Source Engine")
            except Exception as e:
                logging.error(f"Error reading JSON for web display: {e}")

        # Render HTML page displaying live rate
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>USD / INR Live Rate</title>
    <meta http-equiv="refresh" content="30">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background-color: #0d1117;
            color: #c9d1d9;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
        }}
        .card {{
            background-color: #161b22;
            border: 1px solid #30363d;
            border-radius: 12px;
            padding: 32px;
            text-align: center;
            box-shadow: 0 10px 25px rgba(0,0,0,0.5);
            max-width: 360px;
            width: 100%;
        }}
        h2 {{
            margin: 0 0 8px 0;
            font-size: 18px;
            color: #8b949e;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        .price {{
            font-size: 48px;
            font-weight: bold;
            color: #3fb950;
            margin: 16px 0;
        }}
        .meta {{
            font-size: 13px;
            color: #8b949e;
            margin-top: 8px;
        }}
        .source {{
            display: inline-block;
            background: #21262d;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            color: #58a6ff;
            margin-top: 12px;
        }}
    </style>
</head>
<body>
    <div class="card">
        <h2>1 USD to INR</h2>
        <div class="price">{rate}</div>
        <div class="source">Source: {source}</div>
        <div class="meta">Last Updated: {updated_at}</div>
    </div>
</body>
</html>"""
        self.wfile.write(html.encode("utf-8"))

    def log_message(self, format, *args):
        # Prevent access logs from flooding output logs
        pass


def start_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), LivePriceHandler)
    logging.info(f"Web UI server running on port {port}")
    server.serve_forever()


# ================================================================
# MULTI-SOURCE CURRENCY FETCHERS
# ================================================================

def fetch_rate_wise() -> tuple[float, str] | None:
    """Source 1: Wise Currency Converter."""
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
                    return rate, "Wise"
    except Exception as e:
        logging.warning(f"[FAIL] Wise fetch error: {e}")
    return None


def fetch_rate_revolut() -> tuple[float, str] | None:
    """Source 2: Revolut Currency Converter."""
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
                    return rate, "Revolut"
    except Exception as e:
        logging.warning(f"[FAIL] Revolut fetch error: {e}")
    return None


def fetch_rate_open_er() -> tuple[float, str] | None:
    """Source 3: Open ExchangeRate API."""
    try:
        res = requests.get("https://open.er-api.com/v6/latest/USD", timeout=5)
        if res.status_code == 200:
            rate = res.json().get("rates", {}).get("INR")
            if rate and float(rate) > 0:
                logging.info("[SUCCESS] Fetched rate from Open ExchangeRate-API")
                return float(rate), "Open ExchangeRate API"
    except Exception as e:
        logging.warning(f"[FAIL] Open ExchangeRate-API fetch error: {e}")
    return None


def get_live_rate_multi_source() -> tuple[float, str] | None:
    """Tries Wise -> Revolut -> Open ExchangeRate sequentially."""
    return fetch_rate_wise() or fetch_rate_revolut() or fetch_rate_open_er()


# ================================================================
# MAIN LOOP
# ================================================================

def main():
    # 1. Start HTTP server in a separate background thread
    threading.Thread(target=start_web_server, daemon=True).start()

    logging.info("Starting Multi-Source USD/INR Rate Fetcher...")

    # 2. Main interval loop
    while True:
        result = get_live_rate_multi_source()

        if result:
            rate, source = result
            data = {
                "rate": rate,
                "source": source,
                "timestamp": time.time(),
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            }
            with open(OUTPUT_FILE, "w") as f:
                json.dump(data, f, indent=4)
            logging.info(f"Updated {OUTPUT_FILE} -> Live Rate: {rate} ({source})")
        else:
            logging.error("All rate sources failed! Retaining cached rate.")

        logging.info(f"Sleeping for {FETCH_INTERVAL} seconds...")
        time.sleep(FETCH_INTERVAL)


if __name__ == "__main__":
    main()
