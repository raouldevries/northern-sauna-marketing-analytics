"""
Northern Sauna Analytics - Overview Page
Landing page after login with app information and data status
"""

import os
import sys
import time
from datetime import datetime, timedelta

import pandas as pd

import streamlit as st

# Read DEMO_MODE before bq_data_loader is imported so downstream modules
# (data.bq_client, data.queries) can short-circuit their own secret access.
DEMO_MODE = os.environ.get("DEMO_MODE", "").lower() == "true"

sys.path.insert(0, '..')
from bq_data_loader import (  # noqa: E402
    _to_date_str,
    apply_btw_toggle,
    bq_marketing_to_platform_dfs,
    estimate_loading_time,
    get_data_coverage,
    get_data_freshness,
    init_session_state,
    load_all_data_with_status,
    load_bookeo_data,
    load_bookeo_data_with_status,
    load_daily_marketing_summary_from_bq,
    load_ga4_traffic_from_bq,
    load_marketing_data_from_bq,
    load_search_console_from_bq,
    load_search_console_pages_from_bq,
    refresh_bookeo_cache,
)
from data.feedback import get_all_feedback  # noqa: E402
from features.revenue.formatters import format_euro, format_number  # noqa: E402

from components.demo_banner import render_demo_banner, render_footer  # noqa: E402
from utils import render_header, render_sidebar_nav  # noqa: E402

# BigQuery availability gate — short-circuit on DEMO_MODE so we never touch
# st.secrets when no secrets.toml is configured (the Streamlit Cloud demo).
BQ_AVAILABLE = (not DEMO_MODE) and ("gcp_service_account" in st.secrets)

# Shared preload cache (same as app.py - st.cache_resource shares across modules)
@st.cache_resource
def get_preload_cache():
    """Return a persistent dictionary for storing preloaded data."""
    return {'complete': False, 'loading': False, 'status': ''}

# Page configuration
st.set_page_config(
    page_title="Northern Sauna - Overview",
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
</style>
"""
st.markdown(hide_default_nav, unsafe_allow_html=True)

# Initialize session state
init_session_state()



render_header()

render_sidebar_nav("Overview")

render_demo_banner()

# --- Overview ---
st.markdown("## Overview")

# Placeholder for KPIs / loading indicator (static content renders below immediately)
kpi_area = st.empty()

apply_btw_toggle()
df1 = st.session_state.get('df1')
df2 = st.session_state.get('df2')

if df2 is not None and len(df2) > 0:
    # Compute season KPIs
    revenue_col = "Total paid" if "Total paid" in df2.columns else (
        "Total gross" if "Total gross" in df2.columns else None
    )
    email_col = "Email address" if "Email address" in df2.columns else None
    member_col = "Member" if "Member" in df2.columns else None

    total_bookings = len(df2)
    total_revenue = (
        pd.to_numeric(df2[revenue_col], errors="coerce").fillna(0).sum()
        if revenue_col else 0
    )
    avg_booking_value = total_revenue / total_bookings if total_bookings > 0 else 0
    unique_customers = df2[email_col].nunique() if email_col else 0
    total_members = (
        df2[df2[member_col]][email_col].nunique()
        if member_col and email_col else 0
    )
    member_pct = total_members / unique_customers * 100 if unique_customers > 0 else 0

    date_from = df2["Start"].min().strftime("%-d %b %Y") if "Start" in df2.columns else "?"
    date_to = df2["Start"].max().strftime("%-d %b %Y") if "Start" in df2.columns else "?"

    with kpi_area.container():
        st.caption(f"Season: {date_from} \u2013 {date_to}")

        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric(
                "Total Turnover", format_euro(total_revenue),
                help="Total amount paid by customers (non-cancelled bookings).",
            )
        with col2:
            st.metric(
                "Bookings", format_number(total_bookings),
                help="Total non-cancelled bookings in the selected period.",
            )
        with col3:
            st.metric(
                "Unique Customers", format_number(unique_customers),
                help="Distinct customers (by email) who booked.",
            )
        with col4:
            st.metric(
                "Members", format_number(total_members),
                help="Unique customers with an active membership.",
            )
        with col5:
            st.metric(
                "Avg Booking Value", format_euro(avg_booking_value, 2),
                help="Total turnover divided by number of bookings.",
            )

    st.markdown("---")

# What does this app do — framed as business questions
st.markdown("### What the data reveals")

col1, col2 = st.columns(2)

with col1:
    st.markdown("""
**Turnover**
- How much turnover are we generating this season?
- Which locations bring in the most turnover?
- Is the average booking value going up or down?

**Customers & Members**
- How many customers come back after their first visit?
- Who are our most valuable customers?
- Which non-members should we target with a membership offer?
- Are members visiting enough to justify the discount?

**Capacity**
- Which locations and timeslots are underutilised?
- How much turnover are we leaving on the table from empty slots?
- What does a typical weekday midday visitor look like?
""")

with col2:
    st.markdown("""
**Bookings**
- How far in advance do customers book?
- When do booking decisions happen (day and hour)?
- Does weather drive more or fewer bookings?

**Promotions**
- Are discounts driving incremental bookings or just cutting margin?
- How many gift cards are redeemed and do those customers return?
- What is the cost of free coupon sessions?

**Marketing & SEO**
- Which ad platform (Google vs Meta) delivers the best ROI?
- How much organic traffic are we getting from search?
- What search terms bring visitors to the website?
""")

st.markdown("---")



# --- Data Status (single expander) ---
def _freshness_badge(max_date):
    try:
        if max_date is None:
            return "\u2014"
        max_dt = pd.Timestamp(max_date)
        days_ago = (pd.Timestamp.now().normalize() - max_dt.normalize()).days
        if days_ago <= 3:
            return f"\U0001f7e2 {days_ago}d ago" if days_ago > 1 else "\U0001f7e2 Today"
        elif days_ago <= 7:
            return f"\U0001f7e1 {days_ago}d ago"
        else:
            return f"\U0001f534 {days_ago}d ago"
    except Exception:
        return "\u2014"


def _next_sync_label(hour, minute):
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Europe/Stockholm")
    now = datetime.now(tz)
    next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if next_run <= now:
        next_run += timedelta(days=1)
    delta = next_run - now
    hours_left = delta.total_seconds() / 3600
    if hours_left < 1:
        return f"~{int(delta.total_seconds() / 60)}min"
    return f"~{hours_left:.0f}h"


with st.expander("Data Status"):

    # Loaded data summary
    google_ads = st.session_state.get('google_ads_df')
    meta_ads = st.session_state.get('meta_ads_df')
    ga4_traffic = st.session_state.get('ga4_traffic_df')
    sc_data = st.session_state.get('search_console_df')

    st.caption("LOADED DATA")
    col1, col2, col3, col4, col5, col6, col7 = st.columns(7)
    with col1:
        st.metric("Booking Records", format_number(len(df1)) if df1 is not None else "—")
    with col2:
        st.metric("Visit Records", format_number(len(df2)) if df2 is not None else "—")
    with col3:
        if df1 is not None and df2 is not None and len(df1) > 0:
            rate = (len(df1) - len(df2)) / len(df1) * 100
            st.metric("Cancellation Rate", f"{rate:.1f}%")
        else:
            st.metric("Cancellation Rate", "—")
    with col4:
        st.metric("Google Ads Campaigns", format_number(len(google_ads)) if google_ads is not None else "—")
    with col5:
        st.metric("Meta Ads Campaigns", format_number(len(meta_ads)) if meta_ads is not None else "—")
    with col6:
        val = format_number(int(ga4_traffic['sessions'].sum())) if ga4_traffic is not None and not ga4_traffic.empty else "—"
        st.metric("GA4 Sessions", val)
    with col7:
        val = format_number(int(sc_data['impressions'].sum())) if sc_data is not None and not sc_data.empty else "—"
        st.metric("Search Impressions", val)

    st.markdown("---")

    if BQ_AVAILABLE or DEMO_MODE:
        freshness = get_data_freshness()
        coverage = get_data_coverage()
    else:
        freshness = {}
        coverage = []

    coverage_by_source = {row["source"]: row for row in coverage} if coverage else {}

    freshness_map = {
        "Bookeo": ("bookings_created", 5, 0),
        "Google Ads": ("google_ads", 1, 0),
        "Meta Ads": ("meta_ads", 7, 20),
        "GA4": ("ga4", 6, 0),
        "Search Console": ("search_console", 6, 0),
    }

    st.caption("DATA SOURCES")

    table_rows = []
    for source, (fresh_key, sync_h, sync_m) in freshness_map.items():
        fresh_label = _freshness_badge(freshness.get(fresh_key))
        next_sync = _next_sync_label(sync_h, sync_m)
        sync_time = f"{sync_h:02d}:{sync_m:02d} CET"
        cov = coverage_by_source.get(source, {})
        earliest = pd.Timestamp(cov["earliest"]).strftime("%b %Y") if cov.get("earliest") else "\u2014"
        latest = pd.Timestamp(cov["latest"]).strftime("%b %d, %Y") if cov.get("latest") else "\u2014"
        table_rows.append(
            f"| **{source}** | {earliest} | {latest} | {fresh_label} | {next_sync} ({sync_time}) |"
        )

    st.markdown(
        "| Source | From | Latest | Freshness | Next Sync |\n"
        "|--------|------|--------|-----------|----------|\n"
        + "\n".join(table_rows)
    )
    st.caption("Sync times are approximate. Data is cached per session.")

    st.markdown("")
    st.markdown(
        "**Why is this data stored separately?** "
        "Services like Bookeo, Google Ads, and Meta Ads only keep "
        "historical data for a limited time \u2014 after that it's "
        "deleted. By storing all data in a central data warehouse, "
        "nothing is lost. This gives you full historical access "
        "across seasons and enables cross-source analysis (e.g. "
        "comparing ad spend with booking turnover) that individual "
        "platforms can't provide. It's also much faster \u2014 loading "
        "data from the warehouse is significantly more efficient than "
        "querying each service's API directly, which is why this "
        "dashboard loads in seconds instead of hours."
    )

    st.markdown("#### Data Pipeline")
    st.code("""
     SOURCES                    SYNC                  STORAGE          FRONTEND

     Bookeo        ──────────>  Cloud Function  ──╮
     GA4           ──────────>  BQ Export+API   ──┤
     Search Console ─────────>  Bulk Export     ──┤  BigQuery  ──>  Dashboard
     Google Ads    ──────────>  BQ Transfer     ──┤
     Meta Ads      ──────────>  Airbyte         ──╯
""", language=None)

# --- Handle background preload from app.py (after all static content) ---
def _load_marketing_data():
    """Load marketing & organic data into session state."""
    st.session_state._mkt_load_attempted = True
    start_str = st.session_state.bookeo_start_date.strftime("%Y-%m-%d")
    end_str = st.session_state.bookeo_end_date.strftime("%Y-%m-%d")
    try:
        bq_mkt = load_marketing_data_from_bq(start_str, end_str)
        g_df, m_df = bq_marketing_to_platform_dfs(bq_mkt)
        st.session_state.google_ads_df = g_df
        st.session_state.meta_ads_df = m_df
    except Exception:
        pass
    try:
        st.session_state.ga4_traffic_df = load_ga4_traffic_from_bq(start_str, end_str)
        st.session_state.search_console_df = load_search_console_from_bq(start_str, end_str)
        st.session_state.search_console_pages_df = load_search_console_pages_from_bq(start_str, end_str)
        st.session_state.daily_marketing_summary_df = load_daily_marketing_summary_from_bq(start_str, end_str)
    except Exception:
        pass

if BQ_AVAILABLE:
    preload_cache = get_preload_cache()
    needs_bookeo = (
        (preload_cache.get('loading') and not preload_cache.get('complete'))
        or (preload_cache.get('complete') and 'df1' in preload_cache and not st.session_state.get('bookeo_loaded'))
    )
    needs_marketing = (
        st.session_state.get('google_ads_df') is None
        and st.session_state.get('_mkt_load_attempted') is None
    )

    if needs_bookeo or needs_marketing:
        with kpi_area, st.spinner("Loading data..."):
            # Wait for background bookeo preload to finish
            while preload_cache.get('loading') and not preload_cache.get('complete'):
                time.sleep(0.5)

            # Transfer preloaded bookeo data to session state
            if preload_cache.get('complete') and 'df1' in preload_cache and not st.session_state.get('bookeo_loaded'):
                st.session_state.df1 = preload_cache['df1']
                st.session_state.df2 = preload_cache['df2']
                st.session_state.bookeo_start_date = preload_cache['start_date']
                st.session_state.bookeo_end_date = preload_cache['end_date']
                st.session_state.bookeo_loaded = True
                # Snapshot the loaded range + canceled-policy. Pages
                # following the page-pinned-to-Load contract require
                # these to render; without them they block on
                # "Load bookings first" until manual reload. The
                # preload thread always runs with include_canceled=True.
                st.session_state.bookeo_loaded_start_date = preload_cache['start_date']
                st.session_state.bookeo_loaded_end_date = preload_cache['end_date']
                st.session_state.bookeo_loaded_include_canceled = True
                st.session_state.bookeo_last_refresh = preload_cache['timestamp']
                st.session_state.drive_loaded = True
                st.session_state.data_source = 'bigquery'

            # Load marketing & organic data
            if st.session_state.get('bookeo_loaded') and st.session_state.get('google_ads_df') is None:
                _load_marketing_data()

        st.rerun()

# Demo-mode equivalent: no background thread, no preload cache — the
# fixture reads are fast enough to do synchronously inside the spinner.
# Loads bookings + marketing + GA4 + Search Console so the Data Status
# cards on this page populate from first paint instead of staying "—"
# until the user clicks into Marketing / Organic.
elif DEMO_MODE and (
    not st.session_state.get('bookeo_loaded')
    or st.session_state.get('google_ads_df') is None
):
    with kpi_area, st.spinner("Loading demo data..."):
        if 'bookeo_start_date' not in st.session_state:
            st.session_state.bookeo_start_date = datetime(2025, 9, 1)
            st.session_state.bookeo_end_date = datetime.now() - timedelta(days=1)
        if not st.session_state.get('bookeo_loaded'):
            df1, df2, _errs = load_bookeo_data(
                start_date=st.session_state.bookeo_start_date,
                end_date=st.session_state.bookeo_end_date,
                include_canceled=True,
                progress_callback=None,
            )
            st.session_state.df1 = df1
            st.session_state.df2 = df2
            st.session_state.bookeo_loaded = True
            st.session_state.bookeo_loaded_start_date = st.session_state.bookeo_start_date
            st.session_state.bookeo_loaded_end_date = st.session_state.bookeo_end_date
            st.session_state.bookeo_loaded_include_canceled = True
            st.session_state.bookeo_last_refresh = datetime.now()
            st.session_state.drive_loaded = True
            st.session_state.data_source = 'demo'
        if st.session_state.get('google_ads_df') is None:
            _load_marketing_data()
    st.rerun()

# ---------------------------------------------------------------------------
# Feedback overview — all comments across pages
# ---------------------------------------------------------------------------
with st.expander("All feedback"):
    all_fb = get_all_feedback()
    if all_fb.empty:
        st.info("No feedback submitted yet.")
    else:
        pages_list = sorted(all_fb["page"].unique())
        sel_page = st.selectbox(
            "Filter by page", ["All"] + pages_list, key="feedback_admin_page"
        )
        filtered = all_fb if sel_page == "All" else all_fb[all_fb["page"] == sel_page]
        st.caption(f"{len(filtered)} comment{'s' if len(filtered) != 1 else ''}")
        display_df = filtered[["page", "tab", "user_name", "comment", "created_at"]].copy()
        display_df["created_at"] = pd.to_datetime(display_df["created_at"]).dt.strftime("%-d %b %Y, %H:%M")
        st.dataframe(
            display_df.rename(
                columns={
                    "page": "Page",
                    "tab": "Tab",
                    "user_name": "Name",
                    "comment": "Comment",
                    "created_at": "Date",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )


render_footer()
