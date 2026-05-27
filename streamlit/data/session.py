"""Session state management, data loading, and UI components."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timedelta

import pandas as pd

import streamlit as st
from data.bq_client import _to_date_str
from data.queries import (
    _query_bookings,
    _transform_bq_to_bookeo_format,
    bq_marketing_to_platform_dfs,
    load_age_demographics_from_bq,
    load_daily_marketing_summary_from_bq,
    load_device_demographics_from_bq,
    load_ga4_traffic_from_bq,
    load_gender_demographics_from_bq,
    load_google_ads_campaign_network_from_bq,
    load_google_ads_network_from_bq,
    load_google_ads_search_position_from_bq,
    load_location_performance_do_from_bq,
    load_location_performance_from_bq,
    load_marketing_data_from_bq,
    load_platform_placement_from_bq,
    load_search_console_from_bq,
    load_search_console_pages_from_bq,
)


def init_session_state():
    """Initialize all session state variables for data storage."""
    defaults = {
        "authenticated": False,
        "df1": None,
        "df2": None,
        "google_ads_df": None,
        "meta_ads_df": None,
        "location_performance_df": None,
        "location_performance_do_df": None,
        "drive_loaded": False,
        "processed_data": None,
        "data_hash": None,
        "bookeo_loaded": False,
        "bookeo_last_refresh": None,
        # Loaded-state snapshots for the marketing page's
        # "pinned to last successful Load" contract. Pages must read
        # these — never the live `bookeo_start_date` / `bookeo_end_date`
        # / `marketing_bookeo_include_canceled` widgets — for any
        # section that reflects already-loaded data.
        "bookeo_loaded_start_date": None,
        "bookeo_loaded_end_date": None,
        "bookeo_loaded_include_canceled": None,
        "bookeo_errors": {},
        "data_source": "bigquery",
        "loading_status": {},
        "post_filter_debug": [],
        "per_account_dedup_debug": [],
        "merge_dedup_debug": [],
        "ga4_traffic_df": None,
        "search_console_df": None,
        "search_console_pages_df": None,
        "daily_marketing_summary_df": None,
        # Shared platform filter for the marketing page. ROI and CPA tabs
        # both read this single source of truth instead of maintaining
        # their own toggle pairs — removes the failure mode where the
        # value= default could override key-based widget state and
        # consolidates the filter UX across tabs.
        "marketing_selected_platforms": ["Google Ads"],
    }

    for key, default_value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_value


def load_bookeo_data(
    start_date,
    end_date,
    include_canceled: bool = False,
    progress_callback=None,
    max_workers: int = 3,
    date_column: str = "visit_datetime",
) -> tuple[pd.DataFrame | None, pd.DataFrame | None, dict[str, str]]:
    """Load booking data from BigQuery (drop-in replacement for Bookeo API loader).

    Returns (df1, df2, errors_dict).
    """
    try:
        start_str = _to_date_str(start_date)
        end_str = _to_date_str(end_date)

        bq_df = _query_bookings(
            start_str, end_str,
            include_canceled=include_canceled, date_column=date_column,
        )
        df1, df2 = _transform_bq_to_bookeo_format(bq_df)

        if df1.empty:
            return None, None, {}

        return df1, df2, {}
    except Exception:
        return None, None, {"bigquery": "BigQuery error: failed to load booking data"}


def load_bookeo_data_with_status(
    start_date,
    end_date,
    include_canceled: bool = False,
    date_column: str = "visit_datetime",
) -> tuple[pd.DataFrame | None, pd.DataFrame | None, dict[str, str]]:
    """Load booking data from BigQuery with st.status() UI."""
    import time

    start_time = time.time()

    with st.status("Loading bookings...", expanded=True) as status:
        st.write("Fetching your data...")

        try:
            start_str = _to_date_str(start_date)
            end_str = _to_date_str(end_date)

            bq_df = _query_bookings(
                start_str, end_str,
                include_canceled=include_canceled,
                date_column=date_column,
            )

            if bq_df.empty:
                elapsed = time.time() - start_time
                status.update(
                    label=f"No bookings found ({elapsed:.1f}s)", state="error", expanded=False
                )
                return None, None, {}

            st.write("Preparing your dashboard...")
            df1, df2 = _transform_bq_to_bookeo_format(bq_df)

            elapsed = time.time() - start_time
            total = len(df1) if df1 is not None else 0
            status.update(
                label=f"Ready! {total:,} bookings loaded in {elapsed:.1f}s",
                state="complete",
                expanded=False,
            )
            return df1, df2, {}

        except Exception as e:
            elapsed = time.time() - start_time
            status.update(
                label=f"Something went wrong ({elapsed:.1f}s)", state="error", expanded=False
            )
            return None, None, {"bigquery": f"BigQuery error: {e}"}


def load_all_data_with_status(
    start_date,
    end_date,
    include_canceled: bool = False,
) -> dict:
    """Load all data sources from BigQuery with step-by-step status UI.

    Returns a dict with keys: df1, df2, google_ads_df, meta_ads_df,
    ga4_traffic_df, search_console_df, search_console_pages_df,
    daily_marketing_summary_df, errors (list of str), sources_loaded (int).
    """
    import time

    start_time = time.time()
    result = {
        "df1": None, "df2": None,
        "google_ads_df": None, "meta_ads_df": None,
        "ga4_traffic_df": None, "search_console_df": None,
        "search_console_pages_df": None, "daily_marketing_summary_df": None,
        "errors": [], "sources_loaded": 0, "total_sources": 4,
    }
    start_str = _to_date_str(start_date)
    end_str = _to_date_str(end_date)

    with st.status("Loading data from BigQuery...", expanded=True) as status:

        # 1. Bookeo bookings
        st.write("Loading bookings...")
        try:
            bq_df = _query_bookings(start_str, end_str, include_canceled=include_canceled)
            if bq_df.empty:
                elapsed = time.time() - start_time
                status.update(
                    label=f"No bookings found ({elapsed:.1f}s)", state="error", expanded=False
                )
                return result
            df1, df2 = _transform_bq_to_bookeo_format(bq_df)
            result["df1"] = df1
            result["df2"] = df2
            total = len(df1) if df1 is not None else 0
            st.write(f":material/check_circle: Bookings — {total:,} rows")
            result["sources_loaded"] += 1
        except Exception:
            result["errors"].append("Bookings: failed to load")
            st.write(":material/error: Bookings — failed")

        # 2. Marketing (Google Ads + Meta Ads)
        st.write("Loading marketing data...")
        try:
            bq_mkt = load_marketing_data_from_bq(start_str, end_str)
            g_df, m_df = bq_marketing_to_platform_dfs(bq_mkt)
            if g_df is not None:
                result["google_ads_df"] = g_df
            if m_df is not None:
                result["meta_ads_df"] = m_df
            parts = []
            if g_df is not None:
                parts.append(f"Google Ads {len(g_df):,}")
            if m_df is not None:
                parts.append(f"Meta Ads {len(m_df):,}")
            label = ' + '.join(parts) + ' rows' if parts else 'no data'
            st.write(f":material/check_circle: Marketing — {label}")
            result["sources_loaded"] += 1
        except Exception:
            result["errors"].append("Marketing: failed to load")
            st.write(":material/error: Marketing — failed")

        # 3. GA4 traffic
        st.write("Loading GA4 traffic...")
        try:
            ga4_df = load_ga4_traffic_from_bq(start_str, end_str)
            result["ga4_traffic_df"] = ga4_df
            rows = len(ga4_df) if ga4_df is not None else 0
            st.write(f":material/check_circle: GA4 Traffic — {rows:,} rows")
            result["sources_loaded"] += 1
        except Exception:
            result["errors"].append("GA4: failed to load")
            st.write(":material/error: GA4 Traffic — failed")

        # 4. Search Console + daily summary
        st.write("Loading Search Console & SEO...")
        try:
            sc_df = load_search_console_from_bq(start_str, end_str)
            sc_pages_df = load_search_console_pages_from_bq(start_str, end_str)
            mkt_summary_df = load_daily_marketing_summary_from_bq(start_str, end_str)
            result["search_console_df"] = sc_df
            result["search_console_pages_df"] = sc_pages_df
            result["daily_marketing_summary_df"] = mkt_summary_df
            rows = len(sc_df) if sc_df is not None else 0
            st.write(f":material/check_circle: Search Console — {rows:,} rows")
            result["sources_loaded"] += 1
        except Exception:
            result["errors"].append("Search Console: failed to load")
            st.write(":material/error: Search Console — failed")

        # Final summary
        elapsed = time.time() - start_time
        loaded = result["sources_loaded"]
        total_src = result["total_sources"]
        if loaded == total_src:
            status.update(
                label=f"Complete! {loaded}/{total_src} sources loaded in {elapsed:.1f}s",
                state="complete", expanded=False,
            )
        elif loaded > 0:
            status.update(
                label=f"Partial: {loaded}/{total_src} sources loaded in {elapsed:.1f}s",
                state="complete", expanded=True,
            )
        else:
            status.update(
                label=f"Failed to load data ({elapsed:.1f}s)",
                state="error", expanded=True,
            )

    return result


def refresh_bookeo_cache():
    """Clear BigQuery caches and stale page state before a fresh fetch.

    This must clear ALL session state that the marketing page renders
    from, not just bookings. Otherwise a failed reload leaves yesterday's
    `google_ads_df` / `location_performance_df` etc. on screen while the
    widgets show today's draft range — exactly the stale-data bug.

    The cache-clear sweep covers every `@st.cache_data` loader the
    marketing page calls directly so that backfills, view fixes, or
    late-arriving rows propagate consistently across all tabs after a
    manual reload, not only the booking-side ones.
    """
    _query_bookings.clear()
    load_marketing_data_from_bq.clear()
    load_location_performance_from_bq.clear()
    load_location_performance_do_from_bq.clear()
    load_daily_marketing_summary_from_bq.clear()
    load_age_demographics_from_bq.clear()
    load_device_demographics_from_bq.clear()
    load_gender_demographics_from_bq.clear()
    load_google_ads_network_from_bq.clear()
    load_google_ads_campaign_network_from_bq.clear()
    load_google_ads_search_position_from_bq.clear()
    load_platform_placement_from_bq.clear()

    st.session_state.bookeo_loaded = False
    st.session_state.bookeo_last_refresh = None
    st.session_state.loading_status = {}
    st.session_state.df1 = None
    st.session_state.df2 = None
    # Clear loaded-state snapshots — a failed reload must not leave
    # stale captions ("Data period: <old range>") visible.
    st.session_state.bookeo_loaded_start_date = None
    st.session_state.bookeo_loaded_end_date = None
    st.session_state.bookeo_loaded_include_canceled = None
    # Clear ALL marketing-page session frames upfront, BEFORE the
    # reload attempt. If the bookings query fails or returns zero rows,
    # we'd previously fall through and never null these (they only got
    # cleared in the success branch), leaving last-load's marketing data
    # on screen with the new draft range labels.
    st.session_state.google_ads_df = None
    st.session_state.meta_ads_df = None
    st.session_state.location_performance_df = None
    st.session_state.location_performance_load_error = None
    st.session_state.location_performance_do_df = None
    st.session_state.location_performance_do_load_error = None
    st.session_state.daily_marketing_summary_df = None
    st.session_state.ga4_traffic_df = None
    st.session_state.search_console_df = None
    st.session_state.search_console_pages_df = None
    st.session_state.post_filter_debug = []
    st.session_state.per_account_dedup_debug = []
    st.session_state.merge_dedup_debug = []


def apply_btw_toggle():
    """Apply BTW toggle to loaded data.

    Default (Excl. BTW): "Total paid" = net_amount (already set at data layer).
    Incl. BTW: "Total paid" = gross_amount (from "Total gross" column).
    """
    if st.session_state.get("bookeo_loaded"):
        btw_mode = st.session_state.get("btw_mode", "Excl. BTW")
        if btw_mode == "Incl. BTW":
            for _df_key in ("df1", "df2"):
                _df = st.session_state.get(_df_key)
                if _df is not None and "Total gross" in _df.columns:
                    st.session_state[_df_key]["Total paid"] = _df["Total gross"]
        else:
            # Excl. BTW — restore to net_amount (the data layer default)
            for _df_key in ("df1", "df2"):
                _df = st.session_state.get(_df_key)
                if _df is not None and "Total net" in _df.columns:
                    st.session_state[_df_key]["Total paid"] = _df["Total net"]


def render_bookeo_settings(
    page_key: str = "default",
    date_column: str = "visit_datetime",
    before_load: Callable[[], None] | None = None,
):
    """Render date range picker + Load button (BigQuery version).

    Args:
        page_key: Unique key prefix for Streamlit widgets.
        date_column: BQ column to filter on ("visit_datetime" or "booking_created_at").
        before_load: Optional callback fired AFTER the date range expander
            renders but BEFORE any bookings load + `st.rerun()`. Use this
            to render page-specific widgets (e.g. the marketing platform
            filter) that need their `key=` to render in every rerun —
            including the one where `should_load` fires `st.rerun()` —
            so Streamlit doesn't garbage-collect their session_state
            entry mid-reload-chain (see PR #17). Visually places the
            widget below the date range and above any load status /
            page data.
    """
    # Initialize date range in session state (default: last 90 days)
    if "bookeo_start_date" not in st.session_state:
        st.session_state.bookeo_start_date = datetime(2025, 9, 1)
    if "bookeo_end_date" not in st.session_state:
        st.session_state.bookeo_end_date = datetime.now() - timedelta(days=1)
    if "btw_mode" not in st.session_state:
        st.session_state.btw_mode = "Excl. BTW"

    start_str = st.session_state.bookeo_start_date.strftime("%-d %b %Y")
    end_str = st.session_state.bookeo_end_date.strftime("%-d %b %Y")

    # Quick date range buttons
    yesterday = datetime.now() - timedelta(days=1)
    _quick_ranges = {
        "Last 7 days": (yesterday - timedelta(days=6), yesterday),
        "Last 30 days": (yesterday - timedelta(days=29), yesterday),
        "Last 90 days": (yesterday - timedelta(days=89), yesterday),
        "Current season": (datetime(2025, 9, 1), yesterday),
    }

    def _apply_quick_range(label):
        start, end = _quick_ranges[label]
        start_date = start.date() if hasattr(start, 'date') else start
        end_date = end.date() if hasattr(end, 'date') else end
        st.session_state.bookeo_start_date = datetime.combine(start_date, datetime.min.time())
        st.session_state.bookeo_end_date = datetime.combine(end_date, datetime.max.time())
        # Also update widget keys so date_input reflects new values on rerun
        st.session_state[f"{page_key}_bookeo_start_input"] = start_date
        st.session_state[f"{page_key}_bookeo_end_input"] = end_date
        st.session_state.bookeo_loaded = False

    qcols = st.columns(len(_quick_ranges))
    for i, label in enumerate(_quick_ranges):
        with qcols[i]:
            st.button(label, key=f"{page_key}_quick_{i}", on_click=_apply_quick_range, args=(label,), use_container_width=True)

    with st.expander(
        f"Date range: {start_str} \u2013 {end_str} (default: from 1 Sep 2025)",
        expanded=not st.session_state.get("bookeo_loaded", False),
    ):
        col1, col2 = st.columns(2)
        with col1:
            bookeo_start = st.date_input(
                "From",
                value=st.session_state.bookeo_start_date,
                key=f"{page_key}_bookeo_start_input",
                format="DD/MM/YYYY",
            )
        with col2:
            bookeo_end = st.date_input(
                "To",
                value=st.session_state.bookeo_end_date,
                key=f"{page_key}_bookeo_end_input",
                format="DD/MM/YYYY",
            )

        st.session_state.bookeo_start_date = datetime.combine(
            bookeo_start, datetime.min.time()
        )
        st.session_state.bookeo_end_date = datetime.combine(
            bookeo_end, datetime.max.time()
        )

        include_canceled = st.checkbox(
            "Include canceled bookings",
            value=True,
            key=f"{page_key}_bookeo_include_canceled",
        )

        col1, col2 = st.columns([1, 3])
        with col1:
            load_btn = st.button(
                "Load", key=f"{page_key}_load_bookeo_btn", use_container_width=True
            )
        with col2:
            if st.session_state.get("bookeo_last_refresh"):
                st.markdown(
                    f'<p style="margin: 0; padding-top: 8px; font-size: 0.85em; color: #888;">'
                    f'Last updated: {st.session_state.bookeo_last_refresh.strftime("%H:%M")}</p>',
                    unsafe_allow_html=True,
                )

        # Auto-load on first visit (no data yet), or manual Load
        should_load = load_btn
        if not st.session_state.get("bookeo_loaded", False) and not should_load:
            should_load = True  # auto-load default date range

    # `before_load` fires AFTER the date range expander renders but
    # BEFORE the load + `st.rerun()` below — see the docstring. Any
    # caller-supplied widget renders inside the current rerun, so its
    # `key=` is preserved if the load aborts the rerun.
    if before_load is not None:
        before_load()

    if should_load:
        refresh_bookeo_cache()

        df1, df2, errors = load_bookeo_data_with_status(
            start_date=st.session_state.bookeo_start_date,
            end_date=st.session_state.bookeo_end_date,
            include_canceled=include_canceled,
            date_column=date_column,
        )

        if errors:
            for key, msg in errors.items():
                st.warning(f"{key}: {msg}")

        if df1 is not None and len(df1) > 0:
            st.session_state.df1 = df1
            st.session_state.df2 = df2
            st.session_state.bookeo_loaded = True
            # Snapshot the dates + canceled-bookings policy that
            # were actually loaded. Pages MUST read these snapshots
            # (NOT the live widgets) for any section that reflects
            # already-loaded data — otherwise editing the date
            # picker without pressing `Load` would relabel old data
            # with the new range, and flipping the toggle would
            # drift booking-derived metrics from each other.
            st.session_state.bookeo_loaded_start_date = (
                st.session_state.bookeo_start_date
            )
            st.session_state.bookeo_loaded_end_date = (
                st.session_state.bookeo_end_date
            )
            st.session_state.bookeo_loaded_include_canceled = include_canceled
            st.session_state.bookeo_last_refresh = datetime.now()
            st.session_state.drive_loaded = True
            st.session_state.data_source = "bigquery"
            # Marketing/supplementary frames are already nulled by
            # `refresh_bookeo_cache` upfront — auto-load paths on
            # each page repopulate them from the new range.
            st.rerun()
        elif not errors:
            st.warning("No bookings found in selected date range")

    apply_btw_toggle()
