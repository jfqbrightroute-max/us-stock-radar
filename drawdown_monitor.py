import csv
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yfinance as yf


WATCHLIST_FILE = Path("watchlist.txt")
OUTPUT_FILE = Path("data/latest_drawdown.csv")
PERIOD = os.environ.get("DRAWDOWN_PERIOD", "1y")
THRESHOLD = float(os.environ.get("DRAWDOWN_THRESHOLD", "20"))
WEBHOOK_URL = os.environ.get("ALERT_WEBHOOK_URL", "").strip()


def load_tickers():
    return [
        line.strip().upper()
        for line in WATCHLIST_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def check_ticker(ticker):
    history = yf.Ticker(ticker).history(period=PERIOD, interval="1d", auto_adjust=False)
    prices = history["Close"].dropna()
    highs = history["High"].dropna()
    if prices.empty or highs.empty:
        raise ValueError("no price data")
    latest = float(prices.iloc[-1])
    peak = float(highs.max())
    drawdown = ((latest / peak) - 1) * 100
    return {
        "Ticker": ticker,
        "Latest": round(latest, 4),
        "PeriodHigh": round(peak, 4),
        "HighDate": str(highs.idxmax().date()),
        "DrawdownPct": round(drawdown, 2),
        "Alert": drawdown <= -THRESHOLD,
        "CheckedAtUTC": datetime.now(timezone.utc).isoformat(),
    }


def send_alert(rows):
    if not WEBHOOK_URL or not rows:
        return
    detail = "；".join(f"{row['Ticker']} {row['DrawdownPct']:.1f}%" for row in rows)
    message = f"股票回撤提醒：{detail}，已从 {PERIOD} 周期高点下跌至少 {THRESHOLD:.0f}%"
    payload = json.dumps({"text": message, "content": message, "alerts": rows}).encode("utf-8")
    request = urllib.request.Request(
        WEBHOOK_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20):
        pass


def main():
    rows = []
    for ticker in load_tickers():
        try:
            rows.append(check_ticker(ticker))
        except Exception as exc:
            rows.append({"Ticker": ticker, "Error": str(exc), "Alert": False})

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    with OUTPUT_FILE.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    alerts = [row for row in rows if row.get("Alert")]
    send_alert(alerts)
    print(json.dumps({"checked": len(rows), "alerts": len(alerts)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
