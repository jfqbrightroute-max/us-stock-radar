import os
import json
import time
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import yfinance as yf


DATA_DIR = "data"
RESULT_FILE = os.path.join(DATA_DIR, "latest_results.csv")
STATUS_FILE = os.path.join(DATA_DIR, "latest_status.json")
META_CACHE_FILE = os.path.join(DATA_DIR, "company_meta_cache.json")
META_CACHE_DAYS = 7


def load_tickers():
    tickers = []

    try:
        nasdaq_url = "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt"
        nasdaq_df = pd.read_csv(nasdaq_url, sep="|")
        nasdaq_df = nasdaq_df[
            (nasdaq_df["Test Issue"] == "N") &
            (nasdaq_df["ETF"] == "N")
        ]
        tickers.extend(nasdaq_df["Symbol"].dropna().tolist())
    except Exception as e:
        print(f"Nasdaq 股票池读取失败: {e}")

    try:
        other_url = "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt"
        other_df = pd.read_csv(other_url, sep="|")
        other_df = other_df[
            (other_df["Test Issue"] == "N") &
            (other_df["ETF"] == "N")
        ]
        tickers.extend(other_df["ACT Symbol"].dropna().tolist())
    except Exception as e:
        print(f"Other Listed 股票池读取失败: {e}")

    try:
        with open("tickers.txt", "r", encoding="utf-8") as f:
            custom_tickers = [line.strip().upper() for line in f if line.strip()]
        tickers.extend(custom_tickers)
    except Exception as e:
        print(f"自定义股票池读取失败: {e}")

    cleaned_tickers = []
    for ticker in tickers:
        ticker = str(ticker).strip().upper()
        ticker = ticker.replace(".", "-")
        if not ticker:
            continue
        if "$" in ticker or "^" in ticker:
            continue
        if len(ticker) > 5:
            continue
        cleaned_tickers.append(ticker)

    return list(dict.fromkeys(cleaned_tickers))


def analyze_one_ticker(ticker, df):
    try:
        df = df.dropna()

        if len(df) < 60:
            return None

        close = df["Close"]
        volume = df["Volume"]

        latest_close = close.iloc[-1]
        prev_close = close.iloc[-2]

        avg_dollar_volume_20 = (close.iloc[-21:-1] * volume.iloc[-21:-1]).mean()

        if latest_close < 5:
            return None

        if avg_dollar_volume_20 < 10_000_000:
            return None

        one_day_return = latest_close / prev_close - 1
        five_day_return = latest_close / close.iloc[-6] - 1
        twenty_day_return = latest_close / close.iloc[-21] - 1

        up_days = 0
        for i in range(1, min(20, len(close))):
            if close.iloc[-i] > close.iloc[-i - 1]:
                up_days += 1
            else:
                break

        avg_volume_20 = volume.iloc[-21:-1].mean()
        volume_ratio = volume.iloc[-1] / avg_volume_20 if avg_volume_20 > 0 else np.nan

        high_52w = close.iloc[-252:].max()
        distance_to_52w_high = latest_close / high_52w - 1

        signal_list = []

        if up_days >= 5:
            signal_list.append("连续5天上涨")

        if five_day_return >= 0.20:
            signal_list.append("5日涨幅>20%")

        if one_day_return >= 0.10 and volume_ratio >= 2:
            signal_list.append("放量大涨")

        if latest_close >= close.iloc[-21:].max():
            signal_list.append("20日新高")

        if not signal_list:
            return None

        return {
            "Ticker": ticker,
            "最新价": round(float(latest_close), 4),
            "公司主营": "",
            "市值": np.nan,
            "1日涨幅": float(one_day_return),
            "5日涨幅": float(five_day_return),
            "20日涨幅": float(twenty_day_return),
            "连涨天数": int(up_days),
            "成交量倍数": float(volume_ratio),
            "20日平均成交额": float(avg_dollar_volume_20),
            "距离52周高点": float(distance_to_52w_high),
            "信号": " / ".join(signal_list),
        }

    except Exception:
        return None


def download_and_scan(tickers, batch_size=200, sleep_seconds=2):
    results = []
    failed_batches = 0
    total_batches = int(np.ceil(len(tickers) / batch_size))

    for batch_index, start in enumerate(range(0, len(tickers), batch_size), start=1):
        batch = tickers[start:start + batch_size]

        print(f"正在扫描第 {batch_index}/{total_batches} 批，股票数：{len(batch)}")

        try:
            data = yf.download(
                tickers=batch,
                period="1y",
                interval="1d",
                group_by="ticker",
                auto_adjust=True,
                threads=True,
                progress=False
            )

            if data.empty:
                failed_batches += 1
                continue

            for ticker in batch:
                try:
                    if isinstance(data.columns, pd.MultiIndex):
                        if ticker not in data.columns.get_level_values(0):
                            continue
                        ticker_df = data[ticker].copy()
                    else:
                        ticker_df = data.copy()

                    result = analyze_one_ticker(ticker, ticker_df)

                    if result is not None:
                        results.append(result)

                except Exception:
                    continue

        except Exception as e:
            failed_batches += 1
            print(f"第 {batch_index} 批失败: {e}")

        time.sleep(sleep_seconds)

    return results, failed_batches, total_batches


def clean_business_summary(value, limit=220):
    text = " ".join(str(value or "").replace("\n", " ").split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def load_meta_cache():
    if not os.path.exists(META_CACHE_FILE):
        return {}
    try:
        with open(META_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_meta_cache(cache):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(META_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def cache_is_fresh(item):
    fetched_at = item.get("fetched_at_utc")
    if not fetched_at:
        return False
    try:
        fetched_dt = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    except Exception:
        return False
    return datetime.now(timezone.utc) - fetched_dt < timedelta(days=META_CACHE_DAYS)


def fetch_company_meta(ticker):
    info = yf.Ticker(ticker).get_info()
    sector = info.get("sector") or ""
    industry = info.get("industry") or ""
    summary = (
        info.get("longBusinessSummary")
        or info.get("businessSummary")
        or " / ".join(part for part in [sector, industry] if part)
        or ""
    )
    return {
        "公司主营": clean_business_summary(summary),
        "市值": info.get("marketCap") or np.nan,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def enrich_results_with_company_meta(results):
    if not results:
        return results

    cache = load_meta_cache()
    updated = False

    for index, result in enumerate(results, start=1):
        ticker = result["Ticker"]
        meta = cache.get(ticker)

        if not meta or not cache_is_fresh(meta):
            try:
                meta = fetch_company_meta(ticker)
                cache[ticker] = meta
                updated = True
            except Exception as exc:
                print(f"{ticker} 公司信息读取失败: {exc}")
                meta = {"公司主营": "", "市值": np.nan}

            if index % 25 == 0:
                save_meta_cache(cache)
            time.sleep(0.05)

        result["公司主营"] = meta.get("公司主营", "")
        result["市值"] = meta.get("市值", np.nan)

    if updated:
        save_meta_cache(cache)

    return results


def save_outputs(results, status):
    os.makedirs(DATA_DIR, exist_ok=True)
    results = enrich_results_with_company_meta(results)

    if results:
        df = pd.DataFrame(results)
        df = df.drop_duplicates(subset=["Ticker"])
        df = df.sort_values(by=["5日涨幅", "20日涨幅"], ascending=False)
    else:
        df = pd.DataFrame(columns=[
            "Ticker",
            "最新价",
            "公司主营",
            "市值",
            "1日涨幅",
            "5日涨幅",
            "20日涨幅",
            "连涨天数",
            "成交量倍数",
            "20日平均成交额",
            "距离52周高点",
            "信号",
        ])

    df.to_csv(RESULT_FILE, index=False, encoding="utf-8-sig")

    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)

    print(f"结果已保存到 {RESULT_FILE}")
    print(f"状态已保存到 {STATUS_FILE}")


def main():
    started_at = datetime.now(timezone.utc)

    tickers = load_tickers()
    print(f"股票池数量：{len(tickers)}")

    results, failed_batches, total_batches = download_and_scan(tickers)

    finished_at = datetime.now(timezone.utc)

    status = {
        "started_at_utc": started_at.isoformat(),
        "finished_at_utc": finished_at.isoformat(),
        "ticker_count": len(tickers),
        "signal_count": len(results),
        "total_batches": total_batches,
        "failed_batches": failed_batches,
    }

    save_outputs(results, status)


if __name__ == "__main__":
    main()
