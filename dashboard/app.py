# -*- coding: utf-8 -*-
"""
FB Ad Spy — Streamlit Dashboard

Four views:
  1. Leaderboard    — top keywords across all niches (current counts)
  2. By Niche       — keyword table for a selected niche with trend + video %
  3. Trends         — line chart for any keyword over time
  4. Swipe File     — individual ads sorted by scale signal (Stage 2+ data)

Run: streamlit run dashboard/app.py
"""

import sys
import json
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from storage.database import (
    init_db, get_latest_snapshots, get_keyword_trend, get_stats, get_conn,
    get_latest_benchmark_report, get_benchmark_history,
)
from core.keywords import get_available_nichos, KEYWORDS

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="FB Ad Spy",
    page_icon="🕵️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

init_db()

# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300)  # refresh every 5 minutes
def load_all_snapshots() -> pd.DataFrame:
    """Latest snapshot per keyword across all niches."""
    rows = []
    for niche in get_available_nichos():
        rows.extend(get_latest_snapshots(niche, "US"))
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["snapshot_at"] = pd.to_datetime(df["snapshot_at"])
    # Parse top_pages JSON
    df["top_pages_parsed"] = df["top_pages"].apply(
        lambda x: json.loads(x) if x else []
    )
    df["top_advertiser"] = df["top_pages_parsed"].apply(
        lambda pages: pages[0]["page_name"] if pages else ""
    )
    df["top_advertiser_count"] = df["top_pages_parsed"].apply(
        lambda pages: pages[0]["ad_count"] if pages else 0
    )
    df["video_pct"] = df.apply(
        lambda r: round(r["video_count"] / r["active_ad_count"] * 100, 1)
        if r["active_ad_count"] > 0 else 0,
        axis=1,
    )
    return df


@st.cache_data(ttl=300)
def load_trend_data(keyword: str, days: int = 30) -> pd.DataFrame:
    rows = get_keyword_trend(keyword, days)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["snapshot_at"] = pd.to_datetime(df["snapshot_at"])
    return df


@st.cache_data(ttl=300)
def load_7day_delta(df_latest: pd.DataFrame) -> pd.Series:
    """
    For each keyword in df_latest, compute the change vs the snapshot
    closest to 7 days ago. Returns a Series indexed by keyword.
    """
    deltas = {}
    since = datetime.now() - timedelta(days=8)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT keyword, active_ad_count, snapshot_at FROM keyword_snapshots "
            "WHERE snapshot_at >= ? ORDER BY snapshot_at ASC",
            (since.isoformat(),),
        ).fetchall()
    if not rows:
        return pd.Series(dtype=int)

    hist = pd.DataFrame([dict(r) for r in rows])
    hist["snapshot_at"] = pd.to_datetime(hist["snapshot_at"])

    # For each keyword: oldest snapshot in window vs current
    for kw, group in hist.groupby("keyword"):
        group = group.sort_values("snapshot_at")
        if len(group) >= 2:
            deltas[kw] = int(group.iloc[-1]["active_ad_count"]) - int(group.iloc[0]["active_ad_count"])
        else:
            deltas[kw] = 0

    return pd.Series(deltas)


@st.cache_data(ttl=300)
def load_swipe_ads(limit: int = 200) -> pd.DataFrame:
    """Individual ads from Stage 2, ordered by scale signal."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT ad_archive_id, page_name, keyword_found, industry, "
            "       ad_body, hook, cta, ad_type, days_running, collation_count, "
            "       swipe_score, start_date, active_status, ad_snapshot_url "
            "FROM ads "
            "WHERE active_status = 'ACTIVE' "
            "ORDER BY collation_count DESC NULLS LAST, days_running DESC NULLS LAST "
            "LIMIT ?",
            (limit,),
        ).fetchall()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([dict(r) for r in rows])


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.title("🕵️ FB Ad Spy")

df_all = load_all_snapshots()

if df_all.empty:
    st.warning(
        "No data yet. Run Stage 1 first: `python -m agents.count_agent --niche diabetes`"
    )
    st.stop()

last_update = df_all["snapshot_at"].max()
total_ads   = df_all["active_ad_count"].sum()
niches_live = df_all["niche"].nunique()

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Active Ads", f"{total_ads:,.0f}")
col2.metric("Niches Monitored", niches_live)
col3.metric("Keywords Tracked", len(df_all))
col4.metric("Last Updated", last_update.strftime("%b %d, %H:%M") if pd.notna(last_update) else "—")

st.markdown("---")

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_leader, tab_niche, tab_trend, tab_swipe, tab_benchmark = st.tabs([
    "🏆 Leaderboard", "🔍 By Niche", "📈 Trends", "💼 Swipe File", "🧠 Benchmark Reports"
])


# ── Tab 1: Leaderboard ───────────────────────────────────────────────────────
with tab_leader:
    st.subheader("Top Keywords — All Niches")
    st.caption("Sorted by total active English ads in FB Ad Library right now.")

    deltas = load_7day_delta(df_all)
    df_leader = df_all.copy()
    df_leader["7d_change"] = df_leader["keyword"].map(deltas).fillna(0).astype(int)
    df_leader["trend"] = df_leader["7d_change"].apply(
        lambda x: f"🔥 +{x:,}" if x > 500 else (f"↑ +{x:,}" if x > 0 else (f"↓ {x:,}" if x < 0 else "—"))
    )

    display = df_leader.sort_values("active_ad_count", ascending=False).head(30)

    st.dataframe(
        display[[
            "keyword", "niche", "active_ad_count",
            "video_count", "image_count", "video_pct",
            "trend", "top_advertiser", "top_advertiser_count", "fb_library_url",
        ]].rename(columns={
            "keyword": "Keyword",
            "niche": "Niche",
            "active_ad_count": "Total Ads",
            "video_count": "Video",
            "image_count": "Image",
            "video_pct": "Video %",
            "trend": "7-Day Trend",
            "top_advertiser": "Top Advertiser",
            "top_advertiser_count": "Creatives",
            "fb_library_url": "FB Link",
        }),
        column_config={
            "FB Link": st.column_config.LinkColumn("FB Link", display_text="Open ↗"),
            "Total Ads": st.column_config.NumberColumn(format="%d"),
            "Video": st.column_config.NumberColumn(format="%d"),
            "Image": st.column_config.NumberColumn(format="%d"),
            "Video %": st.column_config.NumberColumn(format="%.1f%%"),
            "Creatives": st.column_config.NumberColumn(format="%d"),
        },
        use_container_width=True,
        hide_index=True,
        height=600,
    )


# ── Tab 2: By Niche ───────────────────────────────────────────────────────────
with tab_niche:
    niches = sorted(df_all["niche"].unique())
    selected = st.selectbox("Select niche", niches, key="niche_select")

    df_niche = df_all[df_all["niche"] == selected].copy()

    # Header metrics for this niche
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Keywords", len(df_niche))
    m2.metric("Total Active Ads", f"{df_niche['active_ad_count'].sum():,}")
    m3.metric("Avg Video %", f"{df_niche['video_pct'].mean():.0f}%")
    dominant_video = (df_niche["video_pct"] >= 80).sum()
    m4.metric("Video-Dominant Keywords", dominant_video)

    st.markdown("")

    # Add 7-day delta
    df_niche["7d_change"] = df_niche["keyword"].map(deltas).fillna(0).astype(int)
    df_niche["trend"] = df_niche["7d_change"].apply(
        lambda x: f"🔥 +{x:,}" if x > 500 else (f"↑ +{x:,}" if x > 0 else (f"↓ {x:,}" if x < 0 else "—"))
    )

    df_display = df_niche.sort_values("active_ad_count", ascending=False)

    st.dataframe(
        df_display[[
            "keyword", "active_ad_count", "video_count", "image_count",
            "video_pct", "trend", "top_advertiser", "top_advertiser_count",
            "snapshot_at", "fb_library_url",
        ]].rename(columns={
            "keyword": "Keyword",
            "active_ad_count": "Total Ads",
            "video_count": "Video",
            "image_count": "Image",
            "video_pct": "Video %",
            "trend": "7-Day Trend",
            "top_advertiser": "Top Advertiser",
            "top_advertiser_count": "Creatives",
            "snapshot_at": "Last Checked",
            "fb_library_url": "FB Link",
        }),
        column_config={
            "FB Link": st.column_config.LinkColumn("FB Link", display_text="Open ↗"),
            "Total Ads": st.column_config.NumberColumn(format="%d"),
            "Video": st.column_config.NumberColumn(format="%d"),
            "Image": st.column_config.NumberColumn(format="%d"),
            "Video %": st.column_config.NumberColumn(format="%.1f%%"),
            "Creatives": st.column_config.NumberColumn(format="%d"),
            "Last Checked": st.column_config.DatetimeColumn(format="MMM D, HH:mm"),
        },
        use_container_width=True,
        hide_index=True,
        height=500,
    )

    # ── Top 10 advertisers panel ─────────────────────────────────────────────
    st.markdown("### Top 10 advertisers by keyword")
    kw_options = df_display["keyword"].tolist()
    selected_kw = st.selectbox(
        "Select a keyword to see its top advertisers",
        kw_options,
        key="adv_kw_select",
    )

    if selected_kw:
        row = df_display[df_display["keyword"] == selected_kw].iloc[0]
        pages = row["top_pages_parsed"] if "top_pages_parsed" in row.index else []

        if pages:
            df_pages = pd.DataFrame(pages)
            # Build a link to search this advertiser's ads for this keyword
            kw_enc = selected_kw.replace(" ", "+")
            df_pages["fb_search_url"] = df_pages["page_id"].apply(
                lambda pid: (
                    f"https://www.facebook.com/ads/library/"
                    f"?active_status=active&ad_type=all&country=US"
                    f"&media_type=all&q={kw_enc}"
                    f"&search_type=keyword_unordered"
                    f"&sort_data[direction]=desc&sort_data[mode]=total_impressions"
                    f"&publisher_platforms[0]=facebook"
                )
            )

            a1, a2 = st.columns([2, 1])
            with a1:
                st.dataframe(
                    df_pages[["page_name", "ad_count", "fb_search_url"]].rename(columns={
                        "page_name": "Advertiser",
                        "ad_count":  "Active Creatives",
                        "fb_search_url": "Search Link",
                    }),
                    column_config={
                        "Active Creatives": st.column_config.NumberColumn(format="%d"),
                        "Search Link": st.column_config.LinkColumn(
                            "Search Link", display_text="Search ↗"
                        ),
                    },
                    use_container_width=True,
                    hide_index=True,
                    height=min(40 * len(df_pages) + 60, 420),
                )
            with a2:
                # Mini bar chart of advertiser distribution
                fig_adv = go.Figure(go.Bar(
                    x=df_pages["ad_count"],
                    y=df_pages["page_name"],
                    orientation="h",
                    marker_color="#3b82f6",
                ))
                fig_adv.update_layout(
                    height=min(40 * len(df_pages) + 60, 420),
                    margin=dict(l=0, r=0, t=10, b=0),
                    xaxis_title="Creatives",
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    yaxis=dict(autorange="reversed"),
                )
                st.plotly_chart(fig_adv, use_container_width=True)
        else:
            st.caption("No advertiser data yet for this keyword — run Stage 1 first.")

    st.markdown("---")

    # Bar chart: total vs video vs image
    st.markdown("### Volume breakdown")
    fig = go.Figure()
    df_sorted = df_display.sort_values("active_ad_count", ascending=True).tail(15)
    fig.add_trace(go.Bar(name="Image", y=df_sorted["keyword"], x=df_sorted["image_count"],
                         orientation="h", marker_color="#94a3b8"))
    fig.add_trace(go.Bar(name="Video", y=df_sorted["keyword"], x=df_sorted["video_count"],
                         orientation="h", marker_color="#3b82f6"))
    fig.update_layout(
        barmode="stack", height=400,
        margin=dict(l=0, r=0, t=20, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        xaxis_title="Active Ads",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig, use_container_width=True)


# ── Tab 3: Trends ─────────────────────────────────────────────────────────────
with tab_trend:
    st.subheader("Keyword Trend Over Time")

    all_keywords = sorted(df_all["keyword"].unique())
    kw = st.selectbox("Select keyword", all_keywords, key="trend_kw")
    days = st.slider("Days back", 7, 90, 30)

    df_trend = load_trend_data(kw, days)

    if df_trend.empty:
        st.info("Only one snapshot so far — trends build up after a few days of daily runs.")
    else:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df_trend["snapshot_at"], y=df_trend["active_ad_count"],
            name="Total", line=dict(color="#3b82f6", width=2), mode="lines+markers",
        ))
        fig.add_trace(go.Scatter(
            x=df_trend["snapshot_at"], y=df_trend["video_count"],
            name="Video", line=dict(color="#10b981", width=1.5, dash="dot"), mode="lines",
        ))
        fig.add_trace(go.Scatter(
            x=df_trend["snapshot_at"], y=df_trend["image_count"],
            name="Image", line=dict(color="#f59e0b", width=1.5, dash="dot"), mode="lines",
        ))
        fig.update_layout(
            title=f'"{kw}"',
            height=380,
            margin=dict(l=0, r=0, t=40, b=0),
            yaxis_title="Active Ads",
            legend=dict(orientation="h"),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig, use_container_width=True)

        # Stats summary
        if len(df_trend) >= 2:
            first = df_trend.iloc[0]["active_ad_count"]
            last  = df_trend.iloc[-1]["active_ad_count"]
            delta = int(last - first)
            pct   = ((last - first) / first * 100) if first > 0 else 0
            c1, c2, c3 = st.columns(3)
            c1.metric("Current", f"{int(last):,}")
            c2.metric(f"Change ({days}d)", f"{delta:+,}", delta_color="normal" if delta >= 0 else "inverse")
            c3.metric("% Change", f"{pct:+.1f}%")


# ── Tab 4: Swipe File ─────────────────────────────────────────────────────────
with tab_swipe:
    st.subheader("Swipe File — Individual Ads")
    st.caption(
        "Populated after Stage 2 runs. Sorted by collation_count "
        "(active creatives from this advertiser) — the Gustavo Rafaell scale signal."
    )

    df_swipe = load_swipe_ads(300)

    if df_swipe.empty:
        st.info(
            "No ads collected yet. Run Stage 2:\n\n"
            "`python -m agents.metadata_agent --niche diabetes --min-ads 5000`"
        )
    else:
        # Filters
        fc1, fc2, fc3 = st.columns(3)
        niche_opts = ["All"] + sorted(df_swipe["industry"].dropna().unique().tolist())
        sel_niche  = fc1.selectbox("Niche", niche_opts, key="swipe_niche")
        sel_type   = fc2.selectbox("Ad type", ["All", "video", "image"], key="swipe_type")
        min_creatives = fc3.slider("Min creatives (collation_count)", 0, 1000, 0, step=10)

        df_f = df_swipe.copy()
        if sel_niche != "All":
            df_f = df_f[df_f["industry"] == sel_niche]
        if sel_type != "All":
            df_f = df_f[df_f["ad_type"] == sel_type]
        df_f = df_f[df_f["collation_count"].fillna(0) >= min_creatives]

        st.caption(f"{len(df_f)} ads matching filters")

        # Summary metrics
        sm1, sm2, sm3 = st.columns(3)
        sm1.metric("Ads shown", len(df_f))
        sm2.metric("Avg days running", f"{df_f['days_running'].mean():.0f}" if not df_f.empty else "—")
        sm3.metric("Max creatives", f"{df_f['collation_count'].max():,.0f}" if not df_f.empty else "—")

        st.dataframe(
            df_f[[
                "page_name", "keyword_found", "industry", "ad_type",
                "collation_count", "days_running", "swipe_score",
                "hook", "ad_body", "ad_snapshot_url",
            ]].rename(columns={
                "page_name": "Publisher",
                "keyword_found": "Keyword",
                "industry": "Niche",
                "ad_type": "Type",
                "collation_count": "Creatives",
                "days_running": "Days Running",
                "swipe_score": "Score",
                "hook": "Hook",
                "ad_body": "Copy Preview",
                "ad_snapshot_url": "FB Link",
            }),
            column_config={
                "FB Link": st.column_config.LinkColumn("FB Link", display_text="Open ↗"),
                "Creatives": st.column_config.NumberColumn(format="%d"),
                "Days Running": st.column_config.NumberColumn(format="%d"),
                "Score": st.column_config.ProgressColumn(
                    "Score", min_value=0, max_value=100, format="%d"
                ),
                "Copy Preview": st.column_config.TextColumn(max_chars=120),
            },
            use_container_width=True,
            hide_index=True,
            height=550,
        )

        # Export
        csv = df_f.to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️ Export CSV",
            csv,
            f"swipe_file_{datetime.now().strftime('%Y%m%d')}.csv",
            "text/csv",
        )


# ── Tab 5: Benchmark Reports ────────────────────────────────────────────────
with tab_benchmark:
    st.subheader("Benchmark Analyst Reports")
    st.caption(
        "Generated by agents/benchmark_agent.py — synthesizes keyword trends, new "
        "scale-leader advertisers, and top swipe candidates into a per-niche report. "
        "Human-triggered today: `python -m agents.benchmark_agent --niche <name>`."
    )

    bench_niche = st.selectbox("Select niche", get_available_nichos(), key="bench_niche")
    latest = get_latest_benchmark_report(bench_niche)

    if not latest:
        st.info(
            f"No report yet for '{bench_niche}'. Generate one:\n\n"
            f"`python -m agents.benchmark_agent --niche {bench_niche}`"
        )
    else:
        generated = pd.to_datetime(latest["generated_at"])
        st.caption(f"Last generated: {generated.strftime('%b %d, %Y %H:%M')}")
        st.markdown(latest["report_md"])

        history = get_benchmark_history(bench_niche, limit=10)
        if len(history) > 1:
            st.markdown("---")
            st.markdown("### Previous reports")
            for h in history[1:]:
                ts = pd.to_datetime(h["generated_at"]).strftime("%b %d, %Y %H:%M")
                with st.expander(ts):
                    st.markdown(h["report_md"])
