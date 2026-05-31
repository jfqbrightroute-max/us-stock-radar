import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime

st.set_page_config(
    page_title="US Stock Radar",
    page_icon="📈",
    layout="wide"
)

st.title("US Stock Radar")
st.caption("第一版：扫描股票池中的强势股，筛选连续上涨、5日大涨、放量大涨。")

# -----------------------------
# 读取股票池
# -----------------------------
@st.cache_data(ttl=3600 * 12)
def load_tickers():
    tickers = []

    # 1. Nasdaq 上市证券
    try:
        nasdaq_url = "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt"
        nasdaq_df = pd.read_csv(nasdaq_url, sep="|")
        nasdaq_df = nasdaq_df[
            (nasdaq_df["Test Issue"] == "N") &
            (nasdaq_df["ETF"] == "N")
        ]
        tickers.extend(nasdaq_df["Symbol"].dropna().tolist())
    except Exception as e:
        st.warning(f"Nasdaq 股票池读取失败：{e}")

    # 2. NYSE / AMEX / Cboe 等其他交易所证券
    try:
        other_url = "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt"
        other_df = pd.read_csv(other_url, sep="|")
        other_df = other_df[
            (other_df["Test Issue"] == "N") &
            (other_df["ETF"] == "N")
        ]
        tickers.extend(other_df["ACT Symbol"].dropna().tolist())
    except Exception as e:
        st.warning(f"Other Listed 股票池读取失败：{e}")

    # 3. 读取你自己的 tickers.txt，保证重点关注股票不会漏掉
    try:
        with open("tickers.txt", "r") as f:
            custom_tickers = [line.strip().upper() for line in f if line.strip()]
        tickers.extend(custom_tickers)
    except Exception as e:
        st.warning(f"自定义股票池读取失败：{e}")

    # 4. 清洗 Yahoo Finance ticker 格式
    cleaned_tickers = []
    bad_keywords = [
        "WARRANT",
        "RIGHT",
        "UNIT",
        "PREFERRED",
        "PREFERENCE",
        "DEPOSITARY",
        "NOTE",
        "BOND",
        "ETF",
        "ETN",
        "FUND",
        "TRUST"
    ]

    for ticker in tickers:
        ticker = str(ticker).strip().upper()
        ticker = ticker.replace(".", "-")

        # 过滤特殊符号
        if not ticker:
            continue
        if "$" in ticker or "^" in ticker:
            continue
        if len(ticker) > 5:
            continue

        cleaned_tickers.append(ticker)

    return list(dict.fromkeys(cleaned_tickers))

# -----------------------------
# 下载行情数据
# -----------------------------
@st.cache_data(ttl=3600)
def download_price_data(tickers):
    data = yf.download(
        tickers=tickers,
        period="1y",
        interval="1d",
        group_by="ticker",
        auto_adjust=True,
        threads=True,
        progress=False
    )
    return data


# -----------------------------
# 单只股票指标计算
# -----------------------------
def analyze_one_ticker(ticker, data):
    try:
        if len(data.columns.names) > 1:
            df = data[ticker].copy()
        else:
            df = data.copy()

        df = df.dropna()

        if len(df) < 60:
            return None

        close = df["Close"]
        volume = df["Volume"]

        latest_close = close.iloc[-1]
        prev_close = close.iloc[-2]
       
        # 基础过滤：避免低价、低流动性股票
        avg_dollar_volume_20 = (close.iloc[-21:-1] * volume.iloc[-21:-1]).mean()

        if latest_close < 2:
            return None

        if avg_dollar_volume_20 < 3_000_000:
            return None
        
        one_day_return = latest_close / prev_close - 1
        five_day_return = latest_close / close.iloc[-6] - 1
        twenty_day_return = latest_close / close.iloc[-21] - 1

        # 连续上涨天数
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
            "最新价": latest_close,
            "1日涨幅": one_day_return,
            "5日涨幅": five_day_return,
            "20日涨幅": twenty_day_return,
            "连涨天数": up_days,
            "成交量倍数": volume_ratio,
            "距离52周高点": distance_to_52w_high,
            "信号": " / ".join(signal_list)
        }

    except Exception:
        return None


# -----------------------------
# 扫描全部股票
# -----------------------------
def run_scan(tickers, raw_data):
    results = []

    for ticker in tickers:
        result = analyze_one_ticker(ticker, raw_data)
        if result is not None:
            results.append(result)

    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results)

    df = df.sort_values(
        by=["5日涨幅", "20日涨幅"],
        ascending=False
    )

    return df


# -----------------------------
# 页面控制区
# -----------------------------
tickers = load_tickers()

st.sidebar.header("扫描设置")
st.sidebar.write(f"当前股票池数量：{len(tickers)}")

min_5d_return = st.sidebar.slider(
    "最低5日涨幅过滤",
    min_value=0,
    max_value=100,
    value=0,
    step=5
)

show_all_signals = st.sidebar.checkbox(
    "显示全部信号股票",
    value=True
)

run_button = st.sidebar.button("开始扫描")
auto_run = True

st.sidebar.divider()
st.sidebar.caption("数据源：yfinance")
st.sidebar.caption("第一版仅用于个人研究，不适合实时交易。")

# -----------------------------
# 主页面
# -----------------------------
if auto_run or run_button:
    with st.spinner("正在下载行情并扫描，请稍等..."):
        raw_data = download_price_data(tickers)
        result_df = run_scan(tickers, raw_data)

    if result_df.empty:
        st.warning("当前股票池中没有符合条件的股票。")
    else:
        result_df = result_df[result_df["5日涨幅"] >= min_5d_return / 100]

        display_df = result_df.copy()

        percentage_columns = ["1日涨幅", "5日涨幅", "20日涨幅", "距离52周高点"]
        for col in percentage_columns:
            display_df[col] = display_df[col].map(lambda x: f"{x:.2%}")

        display_df["最新价"] = display_df["最新价"].map(lambda x: f"{x:.2f}")
        display_df["成交量倍数"] = display_df["成交量倍数"].map(lambda x: f"{x:.2f}x")

        st.subheader("扫描结果")
        st.write(f"更新时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True
        )

        csv = result_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            label="下载 CSV",
            data=csv,
            file_name="us_stock_radar_results.csv",
            mime="text/csv"
        )

else:
    st.info("点击左侧「开始扫描」按钮运行。")

    st.markdown("""
### 当前筛选逻辑

这个版本会筛出满足以下任一条件的股票：

1. 连续 5 个交易日上涨  
2. 最近 5 个交易日涨幅超过 20%  
3. 今日涨幅超过 10%，且成交量超过 20 日均量 2 倍  
4. 创 20 日新高  

### 下一版可以增加

- 扫描更多股票  
- 增加市值过滤  
- 增加成交额过滤  
- 增加行业分类  
- 增加财报日期  
- 增加新闻原因解释  
""")
