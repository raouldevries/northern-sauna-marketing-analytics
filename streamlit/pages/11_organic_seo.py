"""
Northern Sauna Analytics - Organic & SEO Page
Search visibility (Search Console), organic traffic (GA4), and paid-vs-organic comparison
using the STDC measurement framework.
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import sys
sys.path.insert(0, '..')
from bq_data_loader import (
    init_session_state, render_bookeo_settings, _to_date_str,
    load_ga4_traffic_from_bq, load_search_console_from_bq,
    load_search_console_pages_from_bq, load_daily_marketing_summary_from_bq,
)
from components.demo_banner import render_demo_banner, render_footer  # noqa: E402
from utils import render_header, render_sidebar_nav
from features.revenue.formatters import format_euro, format_number

# Page configuration
st.set_page_config(
    page_title="Northern Sauna - Organic & SEO",
    page_icon="🔥",
    layout="wide"
)

if not st.session_state.get("authenticated", False):
    st.switch_page("app.py")

# Hide default Streamlit navigation
hide_default_nav = """
<style>
[data-testid="stSidebarNav"] {
    display: none;
}
/* Hide "Press Enter to apply" tooltip on text inputs */
[data-testid="InputInstructions"] {
    display: none;
}
</style>
"""
st.markdown(hide_default_nav, unsafe_allow_html=True)

render_header()

# BigQuery data settings (under header)
render_bookeo_settings(page_key="organic_seo")

# Auto-load organic data when booking data is loaded but organic isn't
if (
    st.session_state.get("bookeo_loaded")
    and st.session_state.get("ga4_traffic_df") is None
):
    try:
        _start = _to_date_str(st.session_state.bookeo_start_date)
        _end = _to_date_str(st.session_state.bookeo_end_date)
        st.session_state.ga4_traffic_df = (
            load_ga4_traffic_from_bq(_start, _end)
        )
        st.session_state.search_console_df = (
            load_search_console_from_bq(_start, _end)
        )
        st.session_state.search_console_pages_df = (
            load_search_console_pages_from_bq(_start, _end)
        )
        st.session_state.daily_marketing_summary_df = (
            load_daily_marketing_summary_from_bq(_start, _end)
        )
        st.rerun()
    except Exception:
        pass  # Organic data is optional

st.markdown("## Organic & SEO")

# Initialize session state using centralized function
init_session_state()

# Check authentication
if not st.session_state.get('authenticated', False):
    st.warning("Please log in to access this page.")
    st.page_link("app.py", label="Go to Login", icon=":material/login:")
    st.stop()

render_sidebar_nav("Organic & SEO", ["Search Visibility", "Organic Traffic", "Paid vs Organic"])

render_demo_banner()


# ---------------------------------------------------------------------------
# STDC card CSS (reused from Marketing page)
# ---------------------------------------------------------------------------

STDC_CSS = """
<style>
.stdc-card {
    padding: 1rem;
    border-radius: 8px;
    margin-bottom: 0.5rem;
}
.stdc-see {
    background: linear-gradient(135deg, #3498db20 0%, #3498db10 100%);
    border-left: 4px solid #3498db;
}
.stdc-think {
    background: linear-gradient(135deg, #f39c1220 0%, #f39c1210 100%);
    border-left: 4px solid #f39c12;
}
.stdc-do {
    background: linear-gradient(135deg, #27ae6020 0%, #27ae6010 100%);
    border-left: 4px solid #27ae60;
}
.stdc-care {
    background: linear-gradient(135deg, #9b59b620 0%, #9b59b610 100%);
    border-left: 4px solid #9b59b6;
}
</style>
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_number(val, prefix="", suffix="", decimals=0):
    """Format a number with Dutch notation, optional prefix/suffix."""
    if pd.isna(val):
        return "N/A"
    return f"{prefix}{format_number(val, decimals)}{suffix}"


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab_search, tab_organic, tab_paid_organic = st.tabs([
    "Search Visibility", "Organic Traffic", "Paid vs Organic",
])

# ===================================================================
# TAB 1: Search Visibility (Search Console — SEE + THINK)
# ===================================================================

with tab_search:
    sc_df = st.session_state.get("search_console_df")

    if sc_df is None or (hasattr(sc_df, "empty") and sc_df.empty):
        st.info(
            "No Search Console data loaded. "
            "Load data from the Overview page or use the date picker above."
        )
    else:
        st.caption(
            "Data delayed 2-3 days from Google Search Console."
        )
        sc_min = sc_df["data_date"].min()
        sc_max = sc_df["data_date"].max()

        # --- Key metrics ---
        total_impressions = int(sc_df["impressions"].sum())
        total_clicks = int(sc_df["clicks"].sum())
        avg_ctr = (
            total_clicks / total_impressions * 100
            if total_impressions > 0 else 0
        )
        # Weighted avg position: sum(impressions * position) / sum(impressions)
        # sc_df already has per-row avg_position weighted at SQL level
        # Re-weight across all query/date combos
        weighted_pos = (
            (sc_df["avg_position"] * sc_df["impressions"]).sum()
            / total_impressions
            if total_impressions > 0 else 0
        )

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Impressions", _fmt_number(total_impressions))
        with col2:
            st.metric("Clicks", _fmt_number(total_clicks))
        with col3:
            st.metric("Avg CTR", f"{avg_ctr:.2f}%")
        with col4:
            st.metric("Avg Position", f"{weighted_pos:.1f}")

        # --- STDC cards ---
        st.markdown(STDC_CSS, unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(
                '<div class="stdc-card stdc-see">', unsafe_allow_html=True,
            )
            st.markdown("**SEE** — Search Visibility")
            st.markdown(
                f"Your site appeared **{format_number(total_impressions)}** times "
                f"in search results, with an average position of "
                f"**{weighted_pos:.1f}**."
            )
            st.markdown('</div>', unsafe_allow_html=True)
        with col2:
            st.markdown(
                '<div class="stdc-card stdc-think">',
                unsafe_allow_html=True,
            )
            st.markdown("**THINK** — Engagement")
            st.markdown(
                f"**{avg_ctr:.2f}%** of impressions led to a click "
                f"({format_number(total_clicks)} total clicks)."
            )
            st.markdown('</div>', unsafe_allow_html=True)

        st.markdown("---")

        # --- Impressions + Clicks trend ---
        st.markdown("#### Impressions & Clicks Over Time")
        daily = sc_df.groupby("data_date", as_index=False).agg(
            impressions=("impressions", "sum"),
            clicks=("clicks", "sum"),
        ).sort_values("data_date")

        fig_trend = go.Figure()
        fig_trend.add_trace(go.Bar(
            x=daily["data_date"], y=daily["impressions"],
            name="Impressions", marker_color="#3498db",
            opacity=0.5,
        ))
        fig_trend.add_trace(go.Scatter(
            x=daily["data_date"], y=daily["clicks"],
            name="Clicks", yaxis="y2",
            line=dict(color="#f39c12", width=2.5),
            mode="lines+markers",
        ))
        fig_trend.update_layout(
            yaxis=dict(title="Impressions", side="left"),
            yaxis2=dict(
                title="Clicks", side="right",
                overlaying="y", showgrid=False,
            ),
            legend=dict(
                orientation="h", yanchor="bottom",
                y=1.02, xanchor="right", x=1,
            ),
            margin=dict(l=40, r=40, t=30, b=30),
            height=350,
            bargap=0.3,
        )
        st.plotly_chart(fig_trend, use_container_width=True)

        # --- Position distribution ---
        st.markdown("#### Position Distribution")

        # Aggregate per query across all dates
        query_agg = sc_df.groupby("query", as_index=False).agg(
            clicks=("clicks", "sum"),
            impressions=("impressions", "sum"),
        )
        # Recalculate weighted avg position per query
        query_pos = sc_df.groupby("query", as_index=False).apply(
            lambda g: pd.Series({
                "avg_position": (
                    (g["avg_position"] * g["impressions"]).sum()
                    / g["impressions"].sum()
                ) if g["impressions"].sum() > 0 else None,
            }),
            include_groups=False,
        )
        query_agg = query_agg.merge(query_pos, on="query")

        # Filter to 10+ impressions for meaningful position data
        pos_df = query_agg[query_agg["impressions"] >= 10].copy()

        if not pos_df.empty:
            def _pos_bucket(pos):
                if pd.isna(pos):
                    return "Unknown"
                if pos <= 3:
                    return "Top 3"
                if pos <= 10:
                    return "4-10"
                if pos <= 20:
                    return "11-20"
                return "20+"

            pos_df["bucket"] = pos_df["avg_position"].apply(_pos_bucket)
            bucket_order = ["Top 3", "4-10", "11-20", "20+"]
            bucket_counts = (
                pos_df["bucket"]
                .value_counts()
                .reindex(bucket_order, fill_value=0)
            )
            bucket_df = pd.DataFrame({
                "Position Range": bucket_counts.index,
                "Queries": bucket_counts.values,
            })

            fig_pos = px.bar(
                bucket_df, x="Position Range", y="Queries",
                color="Position Range",
                color_discrete_map={
                    "Top 3": "#27ae60", "4-10": "#3498db",
                    "11-20": "#f39c12", "20+": "#e74c3c",
                },
            )
            fig_pos.update_layout(
                showlegend=False,
                margin=dict(l=40, r=20, t=20, b=30),
                height=300,
            )
            st.plotly_chart(fig_pos, use_container_width=True)
            st.caption(
                "Only queries with 10+ impressions are included."
            )
        else:
            st.info("Not enough query data for position distribution.")

        # --- Top queries table ---
        st.markdown("#### Top Queries")

        top_queries = (
            query_agg
            .sort_values("clicks", ascending=False)
            .head(20)
            .reset_index(drop=True)
        )
        top_queries["ctr"] = (
            top_queries["clicks"] / top_queries["impressions"] * 100
        ).round(2)
        top_queries["avg_position"] = top_queries["avg_position"].round(1)

        st.dataframe(
            top_queries.rename(columns={
                "query": "Query",
                "clicks": "Clicks",
                "impressions": "Impressions",
                "ctr": "CTR %",
                "avg_position": "Avg Position",
            }),
            use_container_width=True,
            hide_index=True,
            column_config={
                "CTR %": st.column_config.NumberColumn(format="%.2f%%"),
                "Avg Position": st.column_config.NumberColumn(
                    format="%.1f",
                ),
            },
        )

        if len(query_agg) > 20:
            with st.expander(
                f"Show all {len(query_agg)} queries"
            ):
                full = query_agg.sort_values(
                    "clicks", ascending=False,
                ).reset_index(drop=True)
                full["ctr"] = (
                    full["clicks"] / full["impressions"] * 100
                ).round(2)
                full["avg_position"] = full["avg_position"].round(1)
                st.dataframe(
                    full.rename(columns={
                        "query": "Query",
                        "clicks": "Clicks",
                        "impressions": "Impressions",
                        "ctr": "CTR %",
                        "avg_position": "Avg Position",
                    }),
                    use_container_width=True,
                    hide_index=True,
                )

        # --- Key Takeaways ---
        st.markdown("---")
        _sc_date_from = sc_df["data_date"].min().strftime("%-d %b %Y")
        _sc_date_to = sc_df["data_date"].max().strftime("%-d %b %Y")
        with st.expander(f"Key Takeaways ({_sc_date_from} \u2013 {_sc_date_to})"):
            top_query = sc_df.groupby("query")["clicks"].sum().idxmax() if total_clicks > 0 else "N/A"
            top_clicks = int(sc_df.groupby("query")["clicks"].sum().max()) if total_clicks > 0 else 0
            is_branded = top_query and "northern sauna" in str(top_query).lower()

            st.info(
                f"**{format_number(total_impressions)}** search impressions with a **{avg_ctr:.1f}%** CTR "
                f"and average position **{weighted_pos:.1f}**. "
                f"Top query: **{top_query}** ({format_number(top_clicks)} clicks). "
                + ("Strong brand visibility — most top queries contain 'northern sauna'."
                   if is_branded else
                   "Opportunity to improve branded search presence.")
            )



# ===================================================================
# TAB 2: Organic Traffic (GA4 — THINK + DO)
# ===================================================================

with tab_organic:
    ga4_df = st.session_state.get("ga4_traffic_df")

    if ga4_df is None or (hasattr(ga4_df, "empty") and ga4_df.empty):
        st.info(
            "No GA4 traffic data loaded. "
            "Load data from the Overview page or use the date picker above."
        )
    else:
        # Check data availability
        has_historical = ga4_df["new_users"].notna().any()
        all_not_available = (
            ga4_df["session_default_channel_group"] == "(not available)"
        ).all()

        if not has_historical:
            st.info(
                "Detailed metrics (new user %, engagement rate, "
                "pages/session) are only available for dates before "
                "Feb 24, 2026. Expand your date range to include "
                "earlier dates for full metrics."
            )

        # --- Key metrics ---
        total_sessions = int(ga4_df["sessions"].sum())
        total_users = int(ga4_df["total_users"].sum())

        metrics_cols = st.columns(4)
        with metrics_cols[0]:
            st.metric("Sessions", _fmt_number(total_sessions))
        with metrics_cols[1]:
            st.metric("Users", _fmt_number(total_users))
        with metrics_cols[2]:
            if has_historical:
                total_new = int(ga4_df["new_users"].sum())
                new_pct = (
                    total_new / total_users * 100
                    if total_users > 0 else 0
                )
                st.metric("New User %", f"{new_pct:.1f}%")
            else:
                st.metric("New User %", "N/A")
        with metrics_cols[3]:
            if has_historical:
                total_pvs = int(
                    ga4_df["screen_page_views"].dropna().sum()
                )
                ppv = (
                    total_pvs / total_sessions
                    if total_sessions > 0 else 0
                )
                st.metric("Pages/Session", f"{ppv:.2f}")
            else:
                st.metric("Pages/Session", "N/A")

        # Secondary metrics (engagement) — only when historical data
        if has_historical:
            hist = ga4_df[ga4_df["engagement_rate"].notna()]
            if not hist.empty:
                total_engaged = int(hist["engaged_sessions"].sum())
                total_hist_sessions = int(hist["sessions"].sum())
                eng_rate = (
                    total_engaged / total_hist_sessions * 100
                    if total_hist_sessions > 0 else 0
                )
                avg_dur = hist["average_session_duration"].mean()

                sec_cols = st.columns(4)
                with sec_cols[0]:
                    st.metric(
                        "Engagement Rate", f"{eng_rate:.1f}%",
                        help="Sessions with engagement > 10s "
                        "or key event",
                    )
                with sec_cols[1]:
                    st.metric(
                        "Avg Session Duration",
                        f"{avg_dur:.0f}s" if pd.notna(avg_dur)
                        else "N/A",
                    )

        st.markdown("---")

        # --- Daily sessions trend ---
        st.markdown("#### Sessions Over Time")
        daily_ga4 = ga4_df.groupby("date", as_index=False).agg(
            sessions=("sessions", "sum"),
            users=("total_users", "sum"),
        ).sort_values("date")

        fig_sessions = px.line(
            daily_ga4, x="date", y="sessions",
            labels={"date": "Date", "sessions": "Sessions"},
            color_discrete_sequence=["#3498db"],
        )
        fig_sessions.update_layout(
            margin=dict(l=40, r=20, t=20, b=30), height=350,
        )
        st.plotly_chart(fig_sessions, use_container_width=True)

        # --- Source breakdown ---
        st.markdown("#### Traffic Source Breakdown")

        if all_not_available:
            st.info(
                "Source breakdown is only available for dates "
                "before Feb 24, 2026. Expand your date range "
                "for channel-level insights."
            )
        else:
            source_df = ga4_df[
                ga4_df["session_default_channel_group"]
                != "(not available)"
            ]
            channel_agg = (
                source_df
                .groupby(
                    "session_default_channel_group", as_index=False,
                )
                .agg(sessions=("sessions", "sum"))
                .sort_values("sessions", ascending=False)
            )

            fig_source = px.bar(
                channel_agg,
                x="session_default_channel_group",
                y="sessions",
                labels={
                    "session_default_channel_group": "Channel",
                    "sessions": "Sessions",
                },
                color="session_default_channel_group",
            )
            fig_source.update_layout(
                showlegend=False,
                margin=dict(l=40, r=20, t=20, b=30),
                height=350,
            )
            st.plotly_chart(fig_source, use_container_width=True)

        # --- Top landing pages ---
        st.markdown("#### Top Landing Pages")
        sc_pages_df = st.session_state.get("search_console_pages_df")

        if (
            sc_pages_df is not None
            and not sc_pages_df.empty
        ):
            pages_agg = (
                sc_pages_df
                .groupby("url", as_index=False)
                .agg(
                    clicks=("clicks", "sum"),
                    impressions=("impressions", "sum"),
                )
            )
            # Weighted avg position per URL
            url_pos = sc_pages_df.groupby(
                "url", as_index=False,
            ).apply(
                lambda g: pd.Series({
                    "avg_position": (
                        (g["avg_position"] * g["impressions"]).sum()
                        / g["impressions"].sum()
                    ) if g["impressions"].sum() > 0 else None,
                }),
                include_groups=False,
            )
            pages_agg = pages_agg.merge(url_pos, on="url")
            pages_agg = (
                pages_agg
                .sort_values("clicks", ascending=False)
                .head(20)
                .reset_index(drop=True)
            )
            pages_agg["avg_position"] = (
                pages_agg["avg_position"].round(1)
            )

            st.dataframe(
                pages_agg.rename(columns={
                    "url": "URL",
                    "clicks": "Clicks",
                    "impressions": "Impressions",
                    "avg_position": "Avg Position",
                }),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No Search Console page data available.")

        # --- STDC cards ---
        st.markdown("---")
        st.markdown(STDC_CSS, unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(
                '<div class="stdc-card stdc-think">',
                unsafe_allow_html=True,
            )
            st.markdown("**THINK** — Engagement")
            if has_historical:
                st.markdown(
                    f"Engagement rate: **{eng_rate:.1f}%** "
                    f"with **{ppv:.2f}** pages per session."
                )
            else:
                st.markdown(
                    "Engagement metrics require historical data "
                    "(before Feb 24, 2026)."
                )
            st.markdown('</div>', unsafe_allow_html=True)
        with col2:
            st.markdown(
                '<div class="stdc-card stdc-do">',
                unsafe_allow_html=True,
            )
            st.markdown("**DO** — Conversion Potential")
            st.markdown(
                f"**{format_number(total_sessions)}** sessions — "
                "direct booking attribution is not yet available. "
                "Use date-level correlation with booking trends."
            )
            st.markdown('</div>', unsafe_allow_html=True)

        # --- Key Takeaways ---
        st.markdown("---")
        with st.expander(f"Key Takeaways"):
            new_pct_val = (
                ga4_df["new_users"].sum() / total_users * 100
                if total_users > 0 and ga4_df["new_users"].notna().any() else None
            )
            eng_hist = ga4_df[ga4_df["engagement_rate"].notna()]
            eng_val = (
                eng_hist["engaged_sessions"].sum() / eng_hist["sessions"].sum() * 100
                if not eng_hist.empty and eng_hist["sessions"].sum() > 0 else None
            )
            insight = f"**{format_number(total_sessions)}** sessions from **{format_number(total_users)}** users."
            if new_pct_val is not None:
                insight += f" **{new_pct_val:.0f}%** are new visitors — {'mostly discovery traffic' if new_pct_val > 50 else 'strong returning base'}."
            if eng_val is not None:
                insight += f" **{eng_val:.0f}%** engagement rate — {'healthy engagement' if eng_val > 60 else 'room to improve on-site experience'}."
            st.info(insight)



# ===================================================================
# TAB 3: Paid vs Organic (Full Funnel — STDC comparison)
# ===================================================================

with tab_paid_organic:
    summary_df = st.session_state.get("daily_marketing_summary_df")
    sc_df_tab3 = st.session_state.get("search_console_df")
    ga4_df_tab3 = st.session_state.get("ga4_traffic_df")

    if summary_df is None or (
        hasattr(summary_df, "empty") and summary_df.empty
    ):
        st.info(
            "No marketing summary data loaded. "
            "Load data from the Overview page or use the date "
            "picker above."
        )
    else:
        # Split paid vs organic
        paid_sources = ["google_ads", "meta_ads"]
        organic_sources = ["ga4", "search_console"]

        paid = summary_df[summary_df["source"].isin(paid_sources)]
        organic = summary_df[
            summary_df["source"].isin(organic_sources)
        ]

        paid_clicks_total = int(paid["clicks"].sum())
        paid_spend_total = paid["spend"].sum()
        org_clicks_total = int(organic["clicks"].dropna().sum())
        org_sessions_total = int(organic["sessions"].dropna().sum())

        # --- Side-by-side comparison ---
        st.markdown("#### Paid vs Organic Comparison")
        col_paid, col_organic = st.columns(2)

        with col_paid:
            st.markdown("##### Paid Channels")
            paid_imp = int(paid["impressions"].sum())
            paid_clicks = int(paid["clicks"].sum())
            paid_spend = paid["spend"].sum()
            st.metric("Impressions", _fmt_number(paid_imp))
            st.metric("Clicks", _fmt_number(paid_clicks))
            st.metric("Spend", format_euro(paid_spend))

        with col_organic:
            st.markdown("##### Organic Channels")
            org_imp = int(organic["impressions"].dropna().sum())
            org_clicks = int(organic["clicks"].dropna().sum())
            org_sessions = int(organic["sessions"].dropna().sum())
            st.metric("Impressions", _fmt_number(org_imp))
            st.metric("Clicks / Sessions",
                       _fmt_number(org_clicks + org_sessions))
            st.metric("Cost", "Free")

        st.markdown("---")

        # --- Channel contribution over time ---
        st.markdown("#### Channel Contribution Over Time")

        source_labels = {
            "google_ads": "Google Ads",
            "meta_ads": "Meta Ads",
            "search_console": "Search Console",
        }
        # Build daily time series — clicks for ads and search console
        # GA4 excluded: its sessions overlap with the other channels
        chart_rows = []
        for _, row in summary_df.iterrows():
            if row["source"] == "ga4":
                continue
            val = 0
            if row["source"] in paid_sources:
                val = 0 if pd.isna(row["clicks"]) else row["clicks"]
            elif row["source"] == "search_console":
                val = 0 if pd.isna(row["clicks"]) else row["clicks"]
            chart_rows.append({
                "date": row["date"],
                "source": source_labels.get(
                    row["source"], row["source"],
                ),
                "value": val,
            })

        chart_df = pd.DataFrame(chart_rows)
        if not chart_df.empty:
            chart_agg = chart_df.groupby(
                ["date", "source"], as_index=False,
            ).agg(value=("value", "sum"))

            fig_area = px.area(
                chart_agg, x="date", y="value", color="source",
                labels={
                    "date": "Date", "value": "Clicks",
                    "source": "Channel",
                },
                color_discrete_map={
                    "Google Ads": "#4285F4",
                    "Meta Ads": "#1877F2",
                    "Search Console": "#f39c12",
                },
            )
            fig_area.update_layout(
                margin=dict(l=40, r=20, t=20, b=30),
                height=400,
                legend=dict(
                    orientation="h", yanchor="bottom",
                    y=1.02, xanchor="right", x=1,
                ),
            )
            st.plotly_chart(fig_area, use_container_width=True)

        st.markdown("---")

        # --- STDC cards for organic ---
        st.markdown("#### Organic STDC Performance")
        st.markdown(STDC_CSS, unsafe_allow_html=True)

        # Compute STDC metrics
        # SEE: from Search Console
        sc_impressions = 0
        sc_avg_pos = 0
        if sc_df_tab3 is not None and not sc_df_tab3.empty:
            sc_impressions = int(sc_df_tab3["impressions"].sum())
            total_sc_imp = sc_df_tab3["impressions"].sum()
            if total_sc_imp > 0:
                sc_avg_pos = (
                    (
                        sc_df_tab3["avg_position"]
                        * sc_df_tab3["impressions"]
                    ).sum() / total_sc_imp
                )

        # THINK: CTR from SC, engagement from GA4
        sc_ctr = 0
        if sc_df_tab3 is not None and not sc_df_tab3.empty:
            total_sc_clicks = sc_df_tab3["clicks"].sum()
            total_sc_imp = sc_df_tab3["impressions"].sum()
            if total_sc_imp > 0:
                sc_ctr = total_sc_clicks / total_sc_imp * 100

        ga4_eng_rate = None
        if ga4_df_tab3 is not None and not ga4_df_tab3.empty:
            hist = ga4_df_tab3[
                ga4_df_tab3["engagement_rate"].notna()
            ]
            if not hist.empty:
                total_engaged = hist["engaged_sessions"].sum()
                total_hist_s = hist["sessions"].sum()
                if total_hist_s > 0:
                    ga4_eng_rate = (
                        total_engaged / total_hist_s * 100
                    )

        # DO: Organic sessions from GA4 (filtered to Organic Search)
        organic_sessions = None
        organic_sessions_na = False
        if ga4_df_tab3 is not None and not ga4_df_tab3.empty:
            org_filtered = ga4_df_tab3[
                ga4_df_tab3["session_default_channel_group"]
                == "Organic Search"
            ]
            if not org_filtered.empty:
                organic_sessions = int(
                    org_filtered["sessions"].sum()
                )
            else:
                organic_sessions_na = True

        # CARE: Brand query % from SC, returning user % from GA4
        brand_pct = None
        if sc_df_tab3 is not None and not sc_df_tab3.empty:
            brand_q = sc_df_tab3[
                sc_df_tab3["query"].str.contains(
                    "northern sauna", case=False, na=False,
                )
            ]
            total_q_clicks = sc_df_tab3["clicks"].sum()
            if total_q_clicks > 0:
                brand_pct = (
                    brand_q["clicks"].sum()
                    / total_q_clicks * 100
                )

        returning_pct = None
        if ga4_df_tab3 is not None and not ga4_df_tab3.empty:
            if ga4_df_tab3["new_users"].notna().any():
                total_u = ga4_df_tab3["total_users"].sum()
                total_new = ga4_df_tab3["new_users"].sum()
                if total_u > 0:
                    returning_pct = (
                        (total_u - total_new) / total_u * 100
                    )

        # Render STDC cards
        c1, c2, c3, c4 = st.columns(4)

        with c1:
            st.markdown(
                '<div class="stdc-card stdc-see">',
                unsafe_allow_html=True,
            )
            st.markdown("**SEE** — Visibility")
            st.metric(
                "Search Impressions",
                _fmt_number(sc_impressions),
            )
            st.metric(
                "Avg Position",
                f"{sc_avg_pos:.1f}" if sc_avg_pos else "N/A",
            )
            st.markdown('</div>', unsafe_allow_html=True)

        with c2:
            st.markdown(
                '<div class="stdc-card stdc-think">',
                unsafe_allow_html=True,
            )
            st.markdown("**THINK** — Consideration")
            st.metric("Organic CTR", f"{sc_ctr:.2f}%")
            st.metric(
                "Engagement Rate",
                f"{ga4_eng_rate:.1f}%"
                if ga4_eng_rate is not None else "N/A",
            )
            st.markdown('</div>', unsafe_allow_html=True)

        with c3:
            st.markdown(
                '<div class="stdc-card stdc-do">',
                unsafe_allow_html=True,
            )
            st.markdown("**DO** — Conversion")
            if organic_sessions is not None:
                st.metric(
                    "Organic Sessions",
                    _fmt_number(organic_sessions),
                )
            elif organic_sessions_na:
                st.metric("Organic Sessions", "N/A")
                st.caption(
                    "Channel data unavailable for recent dates."
                )
            else:
                st.metric("Organic Sessions", "N/A")
            st.markdown('</div>', unsafe_allow_html=True)

        with c4:
            st.markdown(
                '<div class="stdc-card stdc-care">',
                unsafe_allow_html=True,
            )
            st.markdown("**CARE** — Loyalty")
            st.metric(
                "Brand Query %",
                f"{brand_pct:.1f}%"
                if brand_pct is not None else "N/A",
                help="% of clicks on queries containing 'northern sauna'",
            )
            st.metric(
                "Returning Users",
                f"{returning_pct:.1f}%"
                if returning_pct is not None else "N/A",
                help=(
                    "Requires historical data (before Feb 24, 2026)"
                    if returning_pct is None else
                    "% of users who are not new"
                ),
            )
            st.markdown('</div>', unsafe_allow_html=True)

        # --- Key Takeaways ---
        st.markdown("---")
        with st.expander("Key Takeaways"):
            cost_per_click = paid_spend_total / paid_clicks_total if paid_clicks_total > 0 else 0
            organic_share = (
                org_clicks_total / (org_clicks_total + paid_clicks_total) * 100
                if (org_clicks_total + paid_clicks_total) > 0 else 0
            )
            insight = (
                f"Paid: **{format_number(paid_clicks_total)}** clicks at **{format_euro(paid_spend_total)}** "
                f"({format_euro(cost_per_click, 2)}/click). "
                f"Organic: **{format_number(org_clicks_total)}** clicks at zero cost. "
                f"Organic accounts for **{organic_share:.0f}%** of total clicks. "
            )
            if organic_share > 50:
                insight += "Organic is the dominant traffic driver — protect SEO investment."
            else:
                insight += "Paid channels drive most traffic — growing organic could reduce acquisition cost."
            st.info(insight)




render_footer()
