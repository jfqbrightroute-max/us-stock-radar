import re

import pandas as pd
import streamlit as st
import yfinance as yf


PERIOD_LABELS = {
    "6mo": "近 6 个月",
    "1y": "近 1 年",
    "2y": "近 2 年",
    "5y": "近 5 年",
}


def parse_tickers(value):
    tickers = re.split(r"[\s,，;；]+", value.upper())
    return list(dict.fromkeys(ticker.strip() for ticker in tickers if ticker.strip()))


@st.cache_data(ttl=60 * 60, show_spinner=False)
def load_drawdown(ticker, period):
    history = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=False)
    if history.empty:
        raise ValueError("没有找到行情数据")

    prices = history["Close"].dropna()
    highs = history["High"].dropna()
    if prices.empty or highs.empty:
        raise ValueError("行情数据不完整")

    latest = float(prices.iloc[-1])
    peak = float(highs.max())
    peak_date = highs.idxmax().date()
    drawdown = (latest / peak) - 1
    chart = pd.DataFrame({"收盘价": prices})
    chart.index = chart.index.tz_localize(None)
    return {
        "Ticker": ticker,
        "最新价": latest,
        "周期高点": peak,
        "高点日期": str(peak_date),
        "距高点回撤": drawdown,
        "走势": chart,
    }


def render_drawdown_watch():
    st.subheader("关注股票回撤提醒")
    st.caption("输入关注股票，检查当前价格相对所选周期高点的回撤。达到阈值时会在页面顶部提示。")

    saved_tickers = st.query_params.get("watch", "AAPL,MSFT,NVDA")
    if isinstance(saved_tickers, list):
        saved_tickers = ",".join(saved_tickers)

    control1, control2 = st.columns([2, 1])
    with control1:
        ticker_text = st.text_input(
            "关注股票",
            value=saved_tickers,
            placeholder="例如：AAPL, MSFT, NVDA",
            help="使用 Yahoo Finance 股票代码，多个代码用逗号或空格分隔。",
        )
    with control2:
        period = st.selectbox(
            "高点计算周期",
            options=list(PERIOD_LABELS),
            format_func=PERIOD_LABELS.get,
            index=1,
        )

    option1, option2 = st.columns([1, 2])
    with option1:
        threshold = st.slider("回撤提醒阈值", min_value=5, max_value=60, value=20, step=5)
    with option2:
        st.info("关注列表会写入当前网址参数。检查后收藏页面，下次打开即可继续查看。")

    tickers = parse_tickers(ticker_text)
    if not tickers:
        st.warning("请先输入至少一只股票。")
        return
    if len(tickers) > 30:
        st.warning("一次最多检查 30 只股票，已使用前 30 只。")
        tickers = tickers[:30]

    st.query_params["watch"] = ",".join(tickers)

    rows = []
    errors = []
    with st.spinner("正在检查关注股票走势..."):
        for ticker in tickers:
            try:
                rows.append(load_drawdown(ticker, period))
            except Exception as exc:
                errors.append(f"{ticker}: {exc}")

    alerts = [row for row in rows if row["距高点回撤"] <= -(threshold / 100)]
    if alerts:
        names = "、".join(f"{row['Ticker']} ({row['距高点回撤']:.1%})" for row in alerts)
        st.error(f"回撤提醒：{names} 已从{PERIOD_LABELS[period]}高点下跌至少 {threshold}%")
    else:
        st.success(f"当前没有股票从{PERIOD_LABELS[period]}高点回撤达到 {threshold}%")

    if errors:
        st.warning("部分股票读取失败：" + "；".join(errors))

    if not rows:
        return

    result = pd.DataFrame(
        {
            "Ticker": row["Ticker"],
            "最新价": row["最新价"],
            "周期高点": row["周期高点"],
            "高点日期": row["高点日期"],
            "距高点回撤": row["距高点回撤"] * 100,
            "提醒状态": "需要留意" if row in alerts else "正常",
        }
        for row in rows
    ).sort_values("距高点回撤")

    metric1, metric2, metric3 = st.columns(3)
    metric1.metric("关注股票数", len(rows))
    metric2.metric("触发提醒数", len(alerts))
    metric3.metric("最大回撤", f"{result['距高点回撤'].min():.1f}%")

    st.dataframe(
        result,
        use_container_width=True,
        hide_index=True,
        column_config={
            "最新价": st.column_config.NumberColumn(format="%.2f"),
            "周期高点": st.column_config.NumberColumn(format="%.2f"),
            "距高点回撤": st.column_config.ProgressColumn(
                format="%.1f%%",
                min_value=-100.0,
                max_value=0.0,
            ),
        },
    )

    selected = st.selectbox("查看走势", [row["Ticker"] for row in rows])
    selected_row = next(row for row in rows if row["Ticker"] == selected)
    st.line_chart(selected_row["走势"], use_container_width=True)

    csv = result.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "下载回撤检查结果 CSV",
        data=csv,
        file_name="stock_drawdown_watch.csv",
        mime="text/csv",
    )
