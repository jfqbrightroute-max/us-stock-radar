import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import streamlit as st
import yfinance as yf


PERIOD_LABELS = {
    "6mo": "近 6 个月",
    "1y": "近 1 年",
    "2y": "近 2 年",
    "5y": "近 5 年",
    "max": "全部历史",
}
TICKER_COLUMN_NAMES = {
    "ticker", "tickers", "symbol", "symbols", "stock", "stockcode",
    "股票代码", "证券代码", "代码", "美股代码", "关注股票",
}
MAX_TICKERS = 100


def normalize_ticker(value):
    if pd.isna(value):
        return ""
    return re.sub(r"\s+", "", str(value)).strip().upper()


def parse_tickers(value):
    tickers = re.split(r"[\s,，;；]+", str(value).upper())
    return list(dict.fromkeys(normalize_ticker(ticker) for ticker in tickers if normalize_ticker(ticker)))


def read_uploaded_watchlist(uploaded_file):
    suffix = uploaded_file.name.lower().rsplit(".", 1)[-1]
    if suffix == "csv":
        try:
            frame = pd.read_csv(uploaded_file)
        except UnicodeDecodeError:
            uploaded_file.seek(0)
            frame = pd.read_csv(uploaded_file, encoding="gb18030")
    else:
        frame = pd.read_excel(uploaded_file)
    frame.columns = [str(column).strip() for column in frame.columns]
    return frame


def find_ticker_column(columns):
    normalized = {
        str(column).strip().lower().replace("_", "").replace(" ", ""): column
        for column in columns
    }
    for candidate in TICKER_COLUMN_NAMES:
        if candidate in normalized:
            return normalized[candidate]
    return None


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


def load_all_drawdowns(tickers, period):
    rows = []
    errors = []
    with ThreadPoolExecutor(max_workers=min(8, len(tickers))) as executor:
        futures = {executor.submit(load_drawdown, ticker, period): ticker for ticker in tickers}
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                rows.append(future.result())
            except Exception as exc:
                errors.append(f"{ticker}: {exc}")
    order = {ticker: index for index, ticker in enumerate(tickers)}
    rows.sort(key=lambda row: order[row["Ticker"]])
    return rows, errors


def remove_from_watchlist(ticker):
    current = parse_tickers(st.session_state.get("current_watchlist", ""))
    st.session_state.current_watchlist = ",".join(item for item in current if item != ticker)


def render_drawdown_watch():
    st.subheader("关注股票回撤提醒")
    st.caption("上传最新关注列表后，系统会抓取历史行情，并检查股票是否自周期高点回落达到 20%。")

    upload_col, settings_col = st.columns([2, 1])
    with upload_col:
        uploaded_file = st.file_uploader(
            "上传最新关注列表",
            type=["xlsx", "xls", "csv"],
            help="支持 Excel 或 CSV。建议股票代码列命名为 Ticker、Symbol 或 股票代码。",
        )
    with settings_col:
        period = st.selectbox(
            "高点计算周期",
            options=list(PERIOD_LABELS),
            format_func=PERIOD_LABELS.get,
            index=1,
        )
        threshold = st.slider("回撤提醒阈值", min_value=5, max_value=60, value=20, step=5)

    saved_tickers = st.query_params.get("watch", "AAPL,MSFT,NVDA")
    if isinstance(saved_tickers, list):
        saved_tickers = ",".join(saved_tickers)
    if "current_watchlist" not in st.session_state:
        st.session_state.current_watchlist = saved_tickers

    imported_tickers = []
    if uploaded_file is not None:
        try:
            uploaded_frame = read_uploaded_watchlist(uploaded_file)
            if uploaded_frame.empty:
                st.warning("上传的文件没有数据。")
            else:
                detected_column = find_ticker_column(uploaded_frame.columns)
                if detected_column is None:
                    detected_column = st.selectbox(
                        "请选择股票代码所在列",
                        options=list(uploaded_frame.columns),
                    )
                imported_tickers = list(dict.fromkeys(
                    ticker for ticker in uploaded_frame[detected_column].map(normalize_ticker) if ticker
                ))
                upload_signature = f"{uploaded_file.name}:{uploaded_file.size}:{detected_column}"
                if st.session_state.get("watchlist_upload_signature") != upload_signature:
                    st.session_state.current_watchlist = ",".join(imported_tickers)
                    st.session_state.watchlist_upload_signature = upload_signature
                st.success(
                    f"已从 `{uploaded_file.name}` 的 `{detected_column}` 列导入 "
                    f"{len(imported_tickers)} 只股票，并替换当前关注列表。"
                )
        except Exception as exc:
            st.error(f"关注列表导入失败：{exc}")

    st.markdown("#### 添加新的关注股票")
    add_col, add_button_col = st.columns([4, 1])
    with add_col:
        new_ticker = st.text_input(
            "输入股票代码",
            placeholder="例如：TSLA",
            label_visibility="collapsed",
            key="new_watch_ticker",
        )
    with add_button_col:
        add_clicked = st.button("添加股票", use_container_width=True, type="primary")

    if add_clicked:
        additions = parse_tickers(new_ticker)
        if not additions:
            st.warning("请输入有效的股票代码。")
        else:
            current = parse_tickers(st.session_state.current_watchlist)
            new_items = [ticker for ticker in additions if ticker not in current]
            st.session_state.current_watchlist = ",".join(current + new_items)
            if new_items:
                st.success(f"已添加：{'、'.join(new_items)}")
            else:
                st.info("这些股票已经在关注列表中。")
            st.rerun()

    ticker_text = st.text_area(
        "当前关注列表",
        key="current_watchlist",
        height=100,
        help="上传文件后会自动替换这里的列表，也可以继续手动添加或删除代码。",
    )
    tickers = parse_tickers(ticker_text)

    if not tickers:
        st.warning("请上传关注列表，或手动输入至少一只股票。")
        return
    if len(tickers) > MAX_TICKERS:
        st.warning(f"一次最多检查 {MAX_TICKERS} 只股票，已使用前 {MAX_TICKERS} 只。")
        tickers = tickers[:MAX_TICKERS]

    st.query_params["watch"] = ",".join(tickers)
    st.caption(f"本次将检查 {len(tickers)} 只股票。关注列表已写入当前网址，收藏页面可保留列表。")

    with st.spinner(f"正在抓取 {len(tickers)} 只股票的历史行情并计算回撤..."):
        rows, errors = load_all_drawdowns(tickers, period)

    alerts = [row for row in rows if row["距高点回撤"] <= -(threshold / 100)]
    if alerts:
        names = "、".join(f"{row['Ticker']} ({row['距高点回撤']:.1%})" for row in alerts[:15])
        extra = f" 等 {len(alerts)} 只股票" if len(alerts) > 15 else ""
        st.error(f"回撤提醒：{names}{extra} 已从{PERIOD_LABELS[period]}高点下跌至少 {threshold}%")
    else:
        st.success(f"当前没有股票从{PERIOD_LABELS[period]}高点回撤达到 {threshold}%")

    if errors:
        with st.expander(f"{len(errors)} 只股票读取失败"):
            st.write("；".join(errors))

    if not rows:
        return

    result = pd.DataFrame(
        {
            "Ticker": row["Ticker"],
            "最新价": row["最新价"],
            "周期高点": row["周期高点"],
            "高点日期": row["高点日期"],
            "距高点回撤": row["距高点回撤"] * 100,
            "提醒状态": "回撤达到阈值" if row in alerts else "正常",
        }
        for row in rows
    ).sort_values("距高点回撤")

    metric1, metric2, metric3 = st.columns(3)
    metric1.metric("成功检查股票数", len(rows))
    metric2.metric("触发提醒数", len(alerts))
    metric3.metric("最大回撤", f"{result['距高点回撤'].min():.1f}%")

    st.markdown("#### 检测结果与关注管理")
    header = st.columns([1.2, 1.3, 1.3, 1.4, 1.4, 1])
    for column, label in zip(header, ["代码", "最新价", "周期高点", "距高点回撤", "状态", "操作"]):
        column.markdown(f"**{label}**")

    alert_tickers = {row["Ticker"] for row in alerts}
    for row in sorted(rows, key=lambda item: item["距高点回撤"]):
        columns = st.columns([1.2, 1.3, 1.3, 1.4, 1.4, 1])
        columns[0].write(row["Ticker"])
        columns[1].write(f"{row['最新价']:.2f}")
        columns[2].write(f"{row['周期高点']:.2f}")
        columns[3].write(f"{row['距高点回撤']:.1%}")
        if row["Ticker"] in alert_tickers:
            columns[4].error("达到阈值")
        else:
            columns[4].success("正常")
        columns[5].button(
            "删除",
            key=f"remove_{row['Ticker']}",
            on_click=remove_from_watchlist,
            args=(row["Ticker"],),
            use_container_width=True,
        )

    st.markdown("#### 完整检测数据")
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

    selected = st.selectbox("查看单只股票历史走势", [row["Ticker"] for row in rows])
    selected_row = next(row for row in rows if row["Ticker"] == selected)
    st.line_chart(selected_row["走势"], use_container_width=True)

    csv = result.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "下载回撤检查结果 CSV",
        data=csv,
        file_name="stock_drawdown_watch.csv",
        mime="text/csv",
    )
