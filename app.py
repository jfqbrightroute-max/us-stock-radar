import json
import os
from datetime import datetime, timezone, timedelta

import pandas as pd
import streamlit as st

from drawdown_watch import render_drawdown_watch


st.set_page_config(
    page_title="US Stock Radar",
    page_icon="📈",
    layout="wide"
)

RESULT_FILE = "data/latest_results.csv"
STATUS_FILE = "data/latest_status.json"

st.title("US Stock Radar")
st.caption("每日盘后美股动量雷达：读取 GitHub Actions 生成的静态扫描结果。")


def load_status():
    if not os.path.exists(STATUS_FILE):
        return None
    with open(STATUS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_results():
    if not os.path.exists(RESULT_FILE):
        return pd.DataFrame()
    return pd.read_csv(RESULT_FILE)


def get_latest_expected_market_date():
    now_utc = datetime.now(timezone.utc)
    today = now_utc.date()
    if now_utc.hour < 23:
        expected_date = today - timedelta(days=1)
    else:
        expected_date = today
    while expected_date.weekday() >= 5:
        expected_date -= timedelta(days=1)
    return expected_date


def is_data_fresh(status):
    if not status:
        return False, None, None
    finished_at = status.get("finished_at_utc")
    if not finished_at:
        return False, None, None
    try:
        finished_dt = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
    except Exception:
        return False, None, None
    finished_date = finished_dt.date()
    expected_date = get_latest_expected_market_date()
    return finished_date >= expected_date, finished_date, expected_date


def render_momentum_radar(df, status, data_is_fresh, data_date, expected_market_date):
    st.sidebar.header("数据状态")
    if status:
        st.sidebar.metric("股票池数量", status.get("ticker_count", 0))
        st.sidebar.metric("触发信号数量", status.get("signal_count", 0))
        st.sidebar.metric("总批次数", status.get("total_batches", 0))
        st.sidebar.metric("失败批次数", status.get("failed_batches", 0))
        finished_at = status.get("finished_at_utc", "")
        st.sidebar.caption(f"最近扫描完成时间 UTC：{finished_at}")
        if data_is_fresh:
            st.sidebar.success(f"数据已更新：{data_date}")
        else:
            st.sidebar.warning(f"数据可能过期：当前 {data_date}，应为 {expected_market_date}")
    else:
        st.sidebar.warning("还没有扫描状态文件。")

    st.sidebar.divider()
    st.sidebar.header("筛选")
    min_5d_return = st.sidebar.slider(
        "最低5日涨幅", min_value=-50, max_value=200, value=0, step=5
    )
    signal_keyword = st.sidebar.selectbox(
        "信号类型",
        ["全部", "连续5天上涨", "5日涨幅>20%", "放量大涨", "20日新高"]
    )
    sort_by = st.sidebar.selectbox(
        "排序方式",
        ["5日涨幅", "20日涨幅", "1日涨幅", "成交量倍数", "20日平均成交额", "距离52周高点"]
    )
    ascending = st.sidebar.checkbox("升序排列", value=False)

    if df.empty:
        st.warning("还没有扫描结果。下一步需要配置 GitHub Actions，让它每天生成 data/latest_results.csv。")
        return

    if data_is_fresh:
        st.success(f"当前显示的是最新静态扫描结果，扫描日期：{data_date}")
    else:
        st.warning(
            f"当前静态数据可能不是最近一个美股交易日。"
            f" 最近扫描日期：{data_date}，理论应更新至：{expected_market_date}。"
            f" 可以等待 GitHub Actions 自动运行，或手动运行 daily scan。"
        )

    filtered_df = df.copy()
    filtered_df = filtered_df[filtered_df["5日涨幅"] >= min_5d_return / 100]
    if signal_keyword != "全部":
        filtered_df = filtered_df[
            filtered_df["信号"].astype(str).str.contains(signal_keyword, na=False)
        ]
    if sort_by in filtered_df.columns:
        filtered_df = filtered_df.sort_values(by=sort_by, ascending=ascending)

    st.subheader("扫描结果")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("显示股票数", len(filtered_df))
    col2.metric("原始信号数", len(df))
    col3.metric("最高5日涨幅", f"{df['5日涨幅'].max():.2%}" if not df.empty else "-")
    col4.metric("最高20日涨幅", f"{df['20日涨幅'].max():.2%}" if not df.empty else "-")

    display_df = filtered_df.copy()
    percentage_columns = ["1日涨幅", "5日涨幅", "20日涨幅", "距离52周高点"]
    for col in percentage_columns:
        if col in display_df.columns:
            display_df[col] = display_df[col].map(lambda x: f"{x:.2%}")
    if "最新价" in display_df.columns:
        display_df["最新价"] = display_df["最新价"].map(lambda x: f"{x:.2f}")
    if "成交量倍数" in display_df.columns:
        display_df["成交量倍数"] = display_df["成交量倍数"].map(lambda x: f"{x:.2f}x")
    if "20日平均成交额" in display_df.columns:
        display_df["20日平均成交额"] = display_df["20日平均成交额"].map(lambda x: f"{x:,.0f}")

    st.dataframe(display_df, use_container_width=True, hide_index=True)

    csv = filtered_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        label="下载当前筛选结果 CSV",
        data=csv,
        file_name="us_stock_radar_filtered.csv",
        mime="text/csv"
    )

    st.divider()
    st.markdown("""
    ### 当前信号含义
    - **连续5天上涨**：最近 5 个交易日连续收涨。
    - **5日涨幅>20%**：最近 5 个交易日累计涨幅超过 20%。
    - **放量大涨**：单日涨幅超过 10%，且成交量超过 20 日均量 2 倍。
    - **20日新高**：最新收盘价创最近 20 个交易日新高。
    """)


status = load_status()
df = load_results()
data_is_fresh, data_date, expected_market_date = is_data_fresh(status)

view = st.segmented_control(
    "功能",
    ["动量扫描", "关注股票回撤"],
    default="动量扫描",
    label_visibility="collapsed",
)

if view == "动量扫描":
    render_momentum_radar(df, status, data_is_fresh, data_date, expected_market_date)
else:
    render_drawdown_watch()
