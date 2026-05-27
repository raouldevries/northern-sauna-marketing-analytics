"""
Northern Sauna Analytics - Marketing Campaign Analysis Page
Analyze Google Ads and Meta Ads campaign performance with SEE-THINK-DO-CARE framework
"""

import sys  # noqa: I001

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, '..')
from bq_data_loader import (  # noqa: E402, I001
    _to_date_str,
    bq_marketing_to_platform_dfs,
    init_session_state,
    load_age_demographics_from_bq,
    load_device_demographics_from_bq,
    load_gender_demographics_from_bq,
    load_google_ads_campaign_network_from_bq,
    load_google_ads_network_from_bq,
    load_google_ads_search_position_from_bq,
    load_location_performance_do_from_bq,
    load_location_performance_from_bq,
    load_marketing_data_from_bq,
    load_platform_placement_from_bq,
    render_bookeo_settings,
)
from features.marketing.metrics import (  # noqa: E402
    calculate_cpa_metrics,
    calculate_cpa_targets,
    calculate_location_actual_cpa,
    calculate_stdc_phase_metrics,
)
from features.marketing.roi import create_marketing_roi_table  # noqa: E402
from features.marketing.stdc import suggest_stdc_phase  # noqa: E402
from data.weather import get_available_locations, get_location_column  # noqa: E402
from features.revenue.formatters import format_dataframe_nl, format_euro, format_number  # noqa: E402
from features.revenue.queries import _get_clv_inputs, _get_clv_inputs_by_location  # noqa: E402
from components.demo_banner import render_demo_banner, render_footer  # noqa: E402
from utils import render_header, render_sidebar_nav  # noqa: E402

# Page configuration
st.set_page_config(
    page_title="Northern Sauna - Marketing Analysis",
    page_icon="🔥",
    layout="wide"
)

# Fixed universe of marketing platforms supported by this page. Used as
# the `options=` of the page-level segmented control so the widget's
# shape can't change across reruns — see the rationale next to the
# segmented_control call below.
PLATFORM_OPTIONS = ["Google Ads", "Meta Ads"]


def _platform_filter_caption(selected: list[str]) -> str | None:
    """Render the in-tab indicator that mirrors the page-level filter
    and pins the DO-phase scope.

    Lives inside the ROI and CPA tabs so the active filter is visible
    in-context, without giving each tab its own widget (which would
    re-introduce the rerun-vs-widget-GC race that PR #17 fixed). The
    widget itself stays at the page-top.

    The "DO-phase campaigns only" suffix is static — CPA and ROAS on
    this page measure conversion-stage spend only, so SEE / THINK
    upper-funnel campaigns are excluded from every column on the ROI
    tab and from the per-location Actual CPA on the CPA tab.

    Returns None when no platform is selected — the empty-selection
    warning that downstream code surfaces in each tab is more
    actionable than a passive caption, so we don't duplicate it.
    """
    if not selected:
        return None
    if len(selected) == 1:
        platforms = f"{selected[0]} only"
    else:
        platforms = ' + '.join(selected)
    return f"Filter: {platforms} · DO-phase campaigns only"

if not st.session_state.get("authenticated", False):
    st.switch_page("app.py")

# Hide default Streamlit navigation
hide_default_nav = """
<style>
[data-testid="stSidebarNav"] {
    display: none;
}
[data-testid="stMetricDelta"] svg {
    display: none;
}
</style>
"""
st.markdown(hide_default_nav, unsafe_allow_html=True)

render_header()

# Initialize session state BEFORE render_bookeo_settings — that helper
# can call `st.rerun()` after a successful bookings load (see
# `streamlit/data/session.py` `render_bookeo_settings`), and any widget
# whose `key=` doesn't render before that rerun fires gets its
# session-state entry garbage-collected by Streamlit. Next rerun's
# setdefault would then silently reset the value to the init default —
# which produced a visible-vs-actual desync where the segmented control
# showed `Meta Ads` while the filter operated on `Google Ads`.
init_session_state()

# Check authentication — same reason: must come before any code path
# that can `st.rerun()` so the auth gate is consistent across reruns.
if not st.session_state.get('authenticated', False):
    st.warning("Please log in to access this page.")
    st.page_link("app.py", label="Go to Login", icon=":material/login:")
    st.stop()

# Page-level platform filter — rendered VIA the `before_load=` hook
# of `render_bookeo_settings` so it appears visually UNDER the date
# range expander while still rendering inside the same rerun as the
# load + `st.rerun()`. The hook order matters: any widget whose
# `key=` doesn't render before that rerun fires gets its session_state
# entry garbage-collected by Streamlit (see PR #17).
#
# Options are a FIXED constant rather than `combined_df['Platform']
# .unique()` so the widget's shape can't change across reruns. The
# widget owns its session_state key — no code path writes to
# `st.session_state.marketing_selected_platforms` from outside the
# widget. If a selected platform has no data in the date range,
# downstream code (ROI / CPA) surfaces a genuine empty state rather
# than silently rewriting the selection.
#
# In-tab "Filter: ..." captions live inside ROI by Location + CPA
# Targets so the active selection is visible where it actually
# applies — see `_platform_filter_caption`.
def _render_platform_filter():
    st.segmented_control(
        "Marketing platform filter",
        options=PLATFORM_OPTIONS,
        selection_mode="multi",
        key="marketing_selected_platforms",
        help="Applies to ROI by Location and CPA Targets.",
        label_visibility="collapsed",
    )

# BigQuery data settings (under header)
render_bookeo_settings(
    page_key="marketing",
    before_load=_render_platform_filter,
)

st.markdown("## Marketing Campaign Analysis")
st.markdown("Analyze Google Ads and Meta Ads performance using the SEE-THINK-DO-CARE framework")

# PAGE-WIDE CONTRACT: every section on this page reflects the LAST
# SUCCESSFUL Load — the date pickers and `Include canceled bookings`
# checkbox are draft input only. Auto-load (this section) and every
# downstream BQ call MUST read the loaded-snapshot keys
# (`bookeo_loaded_start_date` / `bookeo_loaded_end_date`), never the
# live widget keys. `refresh_bookeo_cache` clears the snapshots and
# every marketing-page session frame upfront, so a failed reload can't
# leave stale data on screen with new range labels.

# Auto-load marketing data if bookeo is loaded but marketing data is missing
if (
    st.session_state.get("bookeo_loaded")
    and st.session_state.get("google_ads_df") is None
    and st.session_state.get("bookeo_loaded_start_date") is not None
    and st.session_state.get("bookeo_loaded_end_date") is not None
):
    try:
        _start = _to_date_str(st.session_state.bookeo_loaded_start_date)
        _end = _to_date_str(st.session_state.bookeo_loaded_end_date)
        bq_mkt = load_marketing_data_from_bq(_start, _end)
        g_df, m_df = bq_marketing_to_platform_dfs(bq_mkt)
        if g_df is not None:
            st.session_state.google_ads_df = g_df
        if m_df is not None:
            st.session_state.meta_ads_df = m_df
        st.rerun()
    except Exception:
        pass

# Auto-load location-level performance for the loaded range. Stash to
# session state so every section reads a frame pinned to the user's last
# successful `Load` click. `refresh_bookeo_cache` clears this frame
# upfront, so widget edits alone cannot trigger a refetch.
#
# Retry guard: once an auto-load fails (e.g. a deploy where the view
# is missing `revenue_excl_canceled`), we record the error in
# `location_performance_load_error` and STOP retrying every rerun.
# `refresh_bookeo_cache` resets the error so an explicit `Load` click
# gets one fresh attempt.
if (
    st.session_state.get("bookeo_loaded")
    and st.session_state.get("location_performance_df") is None
    and st.session_state.get("location_performance_load_error") is None
    and st.session_state.get("bookeo_loaded_start_date") is not None
    and st.session_state.get("bookeo_loaded_end_date") is not None
):
    try:
        _start = _to_date_str(st.session_state.bookeo_loaded_start_date)
        _end = _to_date_str(st.session_state.bookeo_loaded_end_date)
        st.session_state.location_performance_df = load_location_performance_from_bq(
            _start, _end,
        )
        st.session_state.location_performance_load_error = None
    except Exception as e:
        # On BigQuery failure, leave the df at None and surface a per-tab
        # warning. The error flag distinguishes "load failed" (warn) from
        # "no data in range" (graceful empty), which the CPA tab would
        # otherwise mask as a regular `Actual CPA = N/A`.
        st.session_state.location_performance_df = None
        st.session_state.location_performance_load_error = str(e)

# DO-phase-only sibling. Powers the ROI tab + per-location CPA so those
# metrics measure conversion-stage spend only — Meta's Think/Clicks
# upper-funnel campaigns are excluded from the CPA / ROAS denominator.
# Same retry-guard pattern as the all-phase loader above.
if (
    st.session_state.get("bookeo_loaded")
    and st.session_state.get("location_performance_do_df") is None
    and st.session_state.get("location_performance_do_load_error") is None
    and st.session_state.get("bookeo_loaded_start_date") is not None
    and st.session_state.get("bookeo_loaded_end_date") is not None
):
    try:
        _start = _to_date_str(st.session_state.bookeo_loaded_start_date)
        _end = _to_date_str(st.session_state.bookeo_loaded_end_date)
        st.session_state.location_performance_do_df = (
            load_location_performance_do_from_bq(_start, _end)
        )
        st.session_state.location_performance_do_load_error = None
    except Exception as e:
        st.session_state.location_performance_do_df = None
        st.session_state.location_performance_do_load_error = str(e)

# Always reset STDC tags to apply latest auto-tagging defaults
st.session_state.stdc_tags = {}

render_sidebar_nav("Marketing", ["Overview", "Campaigns", "ROI by Location", "CPA Targets", "Audience"])

render_demo_banner()

# Main content
if st.session_state.google_ads_df is None and st.session_state.meta_ads_df is None:
    st.info(
        "**No marketing data loaded.** Load booking data first using"
        " the date range selector above — marketing data will be"
        " fetched automatically from BigQuery for the same period."
    )
    st.markdown("""
    ### SEE-THINK-DO-CARE Framework
    - **SEE**: Awareness stage - reaching broad audiences (Display, Reach campaigns)
    - **THINK**: Consideration stage - engaging interested users (Non-branded, Clicks campaigns)
    - **DO**: Conversion stage - driving actions (Branded, Conversion campaigns)
    - **CARE**: Loyalty stage - retaining customers (Retargeting, Remarketing campaigns)
    """)
else:
    # Show loading message while processing
    loading_placeholder = st.empty()
    loading_placeholder.info("Loading marketing analysis...")

    # Combine data from both platforms
    dfs_to_combine = []

    if st.session_state.google_ads_df is not None:
        dfs_to_combine.append(st.session_state.google_ads_df)

    if st.session_state.meta_ads_df is not None:
        dfs_to_combine.append(st.session_state.meta_ads_df)

    combined_df = pd.concat(dfs_to_combine, ignore_index=True)

    # Extract date range from data
    data_min_date = None
    data_max_date = None

    # Try to get dates from Meta Ads data
    if st.session_state.meta_ads_df is not None:
        meta_df_dates = st.session_state.meta_ads_df
        if (
            'Reporting starts' in meta_df_dates.columns
            and 'Reporting ends' in meta_df_dates.columns
        ):
            try:
                start_dates = pd.to_datetime(meta_df_dates['Reporting starts'], errors='coerce')
                end_dates = pd.to_datetime(meta_df_dates['Reporting ends'], errors='coerce')
                data_min_date = start_dates.min()
                data_max_date = end_dates.max()
            except Exception:
                pass

    # Add date columns to combined_df for filtering
    if 'Reporting starts' in combined_df.columns:
        combined_df['report_start'] = pd.to_datetime(
            combined_df['Reporting starts'], errors='coerce'
        )
    if 'Reporting ends' in combined_df.columns:
        combined_df['report_end'] = pd.to_datetime(combined_df['Reporting ends'], errors='coerce')

    # Filter out campaigns with 0 spend or invalid names
    if 'spend' in combined_df.columns:
        combined_df = combined_df[combined_df['spend'] > 0]
    if 'campaign_name' in combined_df.columns:
        combined_df = combined_df[combined_df['campaign_name'].notna()]
        combined_df = combined_df[combined_df['campaign_name'].astype(str).str.strip() != '']
        # Filter out summary rows like "--" which are not actual campaigns
        mask_dashes = (
            combined_df['campaign_name']
            .astype(str).str.strip().str.match(r'^-+$')
        )
        combined_df = combined_df[~mask_dashes]
        mask_dashes2 = (
            combined_df['campaign_name']
            .astype(str).str.contains(r'^\s*-+\s*$', regex=True)
        )
        combined_df = combined_df[~mask_dashes2]

    if len(combined_df) > 0:
        # Check if campaign_name column exists
        if 'campaign_name' not in combined_df.columns:
            st.error(
                "Marketing data is missing 'campaign_name' column."
                " Please reboot the app in Streamlit Cloud"
                " (Manage app → Reboot) to reload data with"
                " correct column mapping."
            )
            st.write("**Available columns:**", list(combined_df.columns))
            st.stop()

        # Initialize STDC tags for new campaigns
        for campaign in combined_df['campaign_name'].unique():
            if campaign not in st.session_state.stdc_tags:
                st.session_state.stdc_tags[campaign] = suggest_stdc_phase(campaign)

        # Add STDC phase to dataframe
        combined_df['stdc_phase'] = combined_df['campaign_name'].map(st.session_state.stdc_tags)

        # Clear loading message now that data is ready
        loading_placeholder.empty()

        tab_overview, tab_campaigns, tab_roi, tab_cpa, tab_audience = st.tabs([
            "Overview", "Campaigns", "ROI by Location", "CPA Targets", "Audience",
        ])

        with tab_overview:
            # Key Metrics
            st.markdown("### Key Metrics")

            total_spend = combined_df['spend'].sum()
            total_conversions = combined_df['conversions'].sum()
            total_conv_value = (
                combined_df['conversion_value'].sum()
                if 'conversion_value' in combined_df.columns
                else 0
            )
            roas = (total_conv_value / total_spend * 100) if total_spend > 0 else 0
            cpa = (total_spend / total_conversions) if total_conversions > 0 else 0

            # Calculate platform distribution for all metrics
            google_df = combined_df[combined_df['Platform'] == 'Google Ads']
            meta_df = combined_df[combined_df['Platform'] == 'Meta Ads']

            google_spend = google_df['spend'].sum()
            meta_spend = meta_df['spend'].sum()
            google_conv = google_df['conversions'].sum()
            meta_conv = meta_df['conversions'].sum()
            google_conv_value = (
                google_df['conversion_value'].sum()
                if 'conversion_value' in google_df.columns
                else 0
            )
            meta_conv_value = (
                meta_df['conversion_value'].sum()
                if 'conversion_value' in meta_df.columns
                else 0
            )
            google_roas = (google_conv_value / google_spend * 100) if google_spend > 0 else 0
            meta_roas = (meta_conv_value / meta_spend * 100) if meta_spend > 0 else 0
            google_cpa = (google_spend / google_conv) if google_conv > 0 else 0
            meta_cpa = (meta_spend / meta_conv) if meta_conv > 0 else 0

            # Helper for platform split tooltip
            def platform_tooltip(g_val, m_val, fmt='currency'):
                if fmt == 'currency':
                    g_str = format_euro(g_val) if g_val > 0 else "-"
                    m_str = format_euro(m_val) if m_val > 0 else "-"
                elif fmt == 'percent':
                    g_str = f"{g_val:.1f}%" if g_val > 0 else "-"
                    m_str = f"{m_val:.1f}%" if m_val > 0 else "-"
                else:
                    g_str = format_number(g_val) if g_val > 0 else "-"
                    m_str = format_number(m_val) if m_val > 0 else "-"
                return f"G Ads: {g_str} · M Ads: {m_str}"

            def _pct_pill(g_val, m_val):
                """Return a caption string showing Google/Meta share."""
                total = g_val + m_val
                if total == 0:
                    return ""
                g_pct = g_val / total * 100
                m_pct = m_val / total * 100
                return f"Google {g_pct:.0f}% · Meta {m_pct:.0f}%"

            # Compute projected CLV using same inputs as Customers page
            _clv_2y = 0
            _clv_2y_total = 0
            _clv_monthly_freq = 0
            _clv_monthly_ret = 0
            _clv_aov = 0
            try:
                _end = st.session_state.get("bookeo_loaded_end_date")
                if _end:
                    _end_str = _end.strftime("%Y-%m-%d") if hasattr(_end, "strftime") else str(_end)
                    _clv_inputs = _get_clv_inputs(_end_str)
                    _clv_aov = _clv_inputs["aov"]
                    _freq = _clv_inputs["mean_annual_frequency"]
                    _ret = _clv_inputs["retention_rate"]
                    _clv_monthly_freq = _freq / 12
                    _clv_monthly_ret = _ret ** (1 / 12) if _ret > 0 else 0
                    _clv_2y = sum(
                        _clv_aov * _clv_monthly_freq * (_clv_monthly_ret ** m)
                        for m in range(24)
                    )
                    _clv_2y_total = _clv_2y * total_conversions
            except Exception:
                pass

            _clv_roas = (_clv_2y_total / total_spend * 100) if total_spend > 0 and _clv_2y_total > 0 else 0

            col1, col2, col3, col4, col5, col6, col7 = st.columns(7)
            with col1:
                st.metric(
                    "Total Spend",
                    format_euro(total_spend),
                    delta=_pct_pill(google_spend, meta_spend),
                    delta_color="off",
                    help=platform_tooltip(google_spend, meta_spend),
                )
            with col2:
                st.metric(
                    "Conversions",
                    format_number(total_conversions),
                    delta=_pct_pill(google_conv, meta_conv),
                    delta_color="off",
                    help=platform_tooltip(
                        google_conv, meta_conv, 'number'
                    ),
                )
            with col3:
                st.metric(
                    "Conv. Value",
                    format_euro(total_conv_value),
                    delta=_pct_pill(google_conv_value, meta_conv_value),
                    delta_color="off",
                    help=platform_tooltip(
                        google_conv_value, meta_conv_value
                    ),
                )
            with col4:
                st.metric(
                    "ROAS",
                    f"{format_number(roas)}%",
                    delta=f"Google {google_roas:.0f}% · Meta {meta_roas:.0f}%",
                    delta_color="off",
                    help=platform_tooltip(
                        google_roas, meta_roas, 'percent'
                    ),
                )
            with col5:
                st.metric(
                    "CLV ROAS",
                    f"{format_number(_clv_roas)}%" if _clv_roas > 0 else "N/A",
                    delta=f"{format_euro(_clv_2y_total)} / {format_euro(total_spend)}" if _clv_roas > 0 else None,
                    delta_color="off",
                    help="Return on ad spend based on projected 2-year customer lifetime value. "
                    "2Y CLV Value ÷ Total Spend. Shows the true long-term return of acquiring customers through ads.",
                )
            with col6:
                st.metric(
                    "Avg CPA",
                    format_euro(cpa),
                    delta=f"Google {format_euro(google_cpa)} · Meta {format_euro(meta_cpa)}",
                    delta_color="off",
                    help=platform_tooltip(google_cpa, meta_cpa),
                )
            with col7:
                st.metric(
                    "2Y CLV Value",
                    format_euro(_clv_2y_total) if _clv_2y_total > 0 else "N/A",
                    delta=f"{format_euro(_clv_2y, 2)} × {format_number(total_conversions)}" if _clv_2y_total > 0 else None,
                    delta_color="off",
                    help="Projected 2-year customer lifetime value of all conversions. "
                    "Conversions × 2-year CLV per customer. "
                    "CLV is calculated using AOV × monthly purchase frequency × retention decay over 24 months.",
                )

            st.markdown("### STDC Performance")

            # Show loading spinner for STDC section
            stdc_loading = st.empty()
            with stdc_loading:
                st.markdown(
                    """
    <div style="display: flex; align-items: center; """
                    """padding: 1rem; background-color: #e3f2fd; """
                    """border-radius: 8px; margin: 1rem 0;">
        <div style="width: 24px; height: 24px; """
                    """border: 3px solid #1976d2; """
                    """border-top-color: transparent; """
                    """border-radius: 50%; """
                    """animation: spin 1s linear infinite; """
                    """margin-right: 12px;"></div>
        <span style="color: #1976d2; font-weight: 500;">"""
                    """Calculating STDC metrics...</span>
    </div>
    <style>
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
    </style>
                """,
                    unsafe_allow_html=True,
                )

            def format_platform_tooltip(google_val, meta_val, fmt='number'):
                """Format platform split as tooltip text."""
                if fmt == 'currency':
                    g_str = format_euro(google_val) if google_val > 0 else "-"
                    m_str = format_euro(meta_val) if meta_val > 0 else "-"
                elif fmt == 'percent':
                    g_str = f"{google_val:.1f}%" if google_val > 0 else "-"
                    m_str = f"{meta_val:.1f}%" if meta_val > 0 else "-"
                else:
                    g_str = format_number(google_val) if google_val > 0 else "-"
                    m_str = format_number(meta_val) if meta_val > 0 else "-"
                return f"G Ads: {g_str} · M Ads: {m_str}"

            # Calculate all phase metrics using cached function
            # Create hash for cache key based on relevant columns
            stdc_cols = [
                'stdc_phase', 'Platform', 'spend',
                'impressions', 'reach', 'clicks', 'conversions',
            ]
            stdc_cols = [
                c for c in stdc_cols if c in combined_df.columns
            ]
            df_for_stdc = combined_df[stdc_cols].copy()
            df_hash = hash(df_for_stdc.to_json())
            all_phase_metrics = calculate_stdc_phase_metrics(
                df_hash, df_for_stdc.to_json()
            )
            _platform_zeros = {
                'spend': 0, 'reach': 0, 'clicks': 0,
                'conversions': 0, 'cpm': 0, 'ctr': 0,
                'cpa': 0, 'conv_rate': 0,
            }
            _phase_defaults = {
                **_platform_zeros,
                'google': {**_platform_zeros},
                'meta': {**_platform_zeros},
            }
            see_metrics = all_phase_metrics.get(
                'SEE', {**_phase_defaults}
            )
            think_metrics = all_phase_metrics.get(
                'THINK', {**_phase_defaults}
            )
            do_metrics = all_phase_metrics.get(
                'DO', {**_phase_defaults}
            )
            care_metrics = all_phase_metrics.get(
                'CARE', {**_phase_defaults}
            )

            # Save original THINK spend (from THINK-tagged campaigns only)
            original_think_spend = think_metrics['spend']
            original_think_google_spend = think_metrics['google']['spend']
            original_think_meta_spend = think_metrics['meta']['spend']

            # Override THINK clicks/CTR to use ALL campaigns (engagement metrics)
            # but keep spend from THINK-tagged campaigns only (to avoid double counting)
            all_impressions = (
                combined_df['impressions'].sum()
                if 'impressions' in combined_df.columns
                else 0
            )
            all_reach = combined_df['reach'].sum() if 'reach' in combined_df.columns else 0
            all_total_reach = all_impressions + all_reach
            all_clicks = combined_df['clicks'].sum() if 'clicks' in combined_df.columns else 0

            # Platform breakdown for all campaigns (clicks/CTR only)
            google_all = combined_df[combined_df['Platform'] == 'Google Ads']
            meta_all = combined_df[combined_df['Platform'] == 'Meta Ads']
            g_all_impr = google_all['impressions'].sum() if 'impressions' in google_all.columns else 0
            m_all_reach = meta_all['reach'].sum() if 'reach' in meta_all.columns else 0
            g_all_clicks = google_all['clicks'].sum() if 'clicks' in google_all.columns else 0
            m_all_clicks = meta_all['clicks'].sum() if 'clicks' in meta_all.columns else 0

            # Calculate CTR for all campaigns
            all_ctr = (all_clicks / all_total_reach * 100) if all_total_reach > 0 else 0
            g_all_ctr = (g_all_clicks / g_all_impr * 100) if g_all_impr > 0 else 0
            m_all_ctr = (m_all_clicks / m_all_reach * 100) if m_all_reach > 0 else 0

            # Update think_metrics: clicks/CTR from all campaigns, spend from THINK-tagged only
            think_metrics['clicks'] = all_clicks
            think_metrics['ctr'] = all_ctr
            think_metrics['spend'] = original_think_spend  # Keep original THINK spend
            think_metrics['google']['clicks'] = g_all_clicks
            think_metrics['google']['ctr'] = g_all_ctr
            think_metrics['google']['spend'] = original_think_google_spend  # Keep original
            think_metrics['meta']['clicks'] = m_all_clicks
            think_metrics['meta']['ctr'] = m_all_ctr
            think_metrics['meta']['spend'] = original_think_meta_spend  # Keep original

            # Calculate rebooking metrics from booking data
            rebookings = 0
            rebook_rate = 0
            total_customers = 0
            clv = _clv_2y  # Reuse 2-year CLV from _get_clv_inputs (same as Customers page)
            if st.session_state.df1 is not None:
                df1 = st.session_state.df1
                email_col = 'Email address' if 'Email address' in df1.columns else None

                if email_col:
                    customer_bookings = df1.groupby(email_col).size()
                    total_customers = len(customer_bookings)
                    repeat_customers = (customer_bookings > 1).sum()
                    rebookings = customer_bookings[customer_bookings > 1].sum()
                    rebook_rate = (
                        (repeat_customers / total_customers * 100)
                        if total_customers > 0
                        else 0
                    )

            # Clear loading placeholder - metrics are ready
            stdc_loading.empty()

            # Stage KPI Cards with colored backgrounds
            st.markdown("""
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
            """, unsafe_allow_html=True)

            col1, col2, col3, col4 = st.columns(4)

            with col1:
                st.markdown('<div class="stdc-card stdc-see">', unsafe_allow_html=True)
                st.markdown("**SEE** - Awareness")
                st.metric(
                    "CPM",
                    f"€{see_metrics['cpm']:.2f}",
                    help=format_platform_tooltip(
                        see_metrics['google']['cpm'],
                        see_metrics['meta']['cpm'],
                        'currency',
                    ),
                )
                st.metric(
                    "Reach",
                    format_number(see_metrics['reach']),
                    help=format_platform_tooltip(
                        see_metrics['google']['reach'],
                        see_metrics['meta']['reach'],
                    ),
                )
                st.metric(
                    "Spend",
                    format_euro(see_metrics['spend']),
                    help=format_platform_tooltip(
                        see_metrics['google']['spend'],
                        see_metrics['meta']['spend'],
                        'currency',
                    ),
                )
                st.markdown('</div>', unsafe_allow_html=True)

            with col2:
                st.markdown('<div class="stdc-card stdc-think">', unsafe_allow_html=True)
                st.markdown("**THINK** - Consideration")
                st.metric(
                    "CTR",
                    f"{think_metrics['ctr']:.2f}%",
                    help=format_platform_tooltip(
                        think_metrics['google']['ctr'],
                        think_metrics['meta']['ctr'],
                        'percent',
                    ),
                )
                st.metric(
                    "Clicks",
                    format_number(think_metrics['clicks']),
                    help=format_platform_tooltip(
                        think_metrics['google']['clicks'],
                        think_metrics['meta']['clicks'],
                    ),
                )
                st.metric(
                    "Spend",
                    format_euro(think_metrics['spend']),
                    help=format_platform_tooltip(
                        think_metrics['google']['spend'],
                        think_metrics['meta']['spend'],
                        'currency',
                    ),
                )
                st.markdown('</div>', unsafe_allow_html=True)

            with col3:
                st.markdown('<div class="stdc-card stdc-do">', unsafe_allow_html=True)
                st.markdown("**DO** - Conversion")
                cpa_val = (
                    f"€{do_metrics['cpa']:.2f}"
                    if do_metrics['cpa'] > 0
                    else "N/A"
                )
                st.metric(
                    "CPA",
                    cpa_val,
                    help=format_platform_tooltip(
                        do_metrics['google']['cpa'],
                        do_metrics['meta']['cpa'],
                        'currency',
                    ),
                )
                conv_val = (
                    format_number(do_metrics['conversions'])
                    + f" ({do_metrics['conv_rate']:.1f}%)"
                )
                st.metric(
                    "Conversions",
                    conv_val,
                    help=format_platform_tooltip(
                        do_metrics['google']['conversions'],
                        do_metrics['meta']['conversions'],
                    ),
                )
                st.metric(
                    "Spend",
                    format_euro(do_metrics['spend']),
                    help=format_platform_tooltip(
                        do_metrics['google']['spend'],
                        do_metrics['meta']['spend'],
                        'currency',
                    ),
                )
                st.markdown('</div>', unsafe_allow_html=True)

            with col4:
                st.markdown('<div class="stdc-card stdc-care">', unsafe_allow_html=True)
                st.markdown("**CARE** - Loyalty")
                rebook_val = (
                    f"{rebook_rate:.1f}%"
                    if total_customers > 0
                    else "N/A"
                )
                st.metric(
                    "Rebook Rate",
                    rebook_val,
                    help="From booking data",
                )
                clv_val = (
                    format_euro(clv) if clv > 0 else "N/A"
                )
                st.metric(
                    "CLV (2Y)",
                    clv_val,
                    help=(
                        "2-year Customer Lifetime Value — "
                        "same calculation as the Customers page"
                    ),
                )
                st.metric(
                    "Spend",
                    format_euro(care_metrics['spend']),
                    help=format_platform_tooltip(
                        care_metrics['google']['spend'],
                        care_metrics['meta']['spend'],
                        'currency',
                    ),
                )
                st.markdown('</div>', unsafe_allow_html=True)

            # Show untagged campaigns count if any
            untagged_count = len(combined_df[combined_df['stdc_phase'] == 'Untagged'])
            if untagged_count > 0:
                st.caption(
                    f"Note: {untagged_count} campaigns are"
                    " untagged. Tag them in the Campaign"
                    " Performance table below."
                )

            # --- Key Takeaways ---
            with st.expander("Key Takeaways"):
                # Spend efficiency
                if total_spend > 0 and total_conversions > 0:
                    st.info(
                        f"**Overall efficiency: €{cpa:.2f} per conversion.** "
                        f"You spent {format_euro(total_spend)} and got "
                        f"{format_number(total_conversions)} conversions. "
                        + (
                            f"ROAS is {roas:.0f}% — for every €1 spent, "
                            f"you get €{roas/100:.2f} back in tracked conversion value."
                            if roas > 0
                            else ""
                        )
                    )

                # STDC balance
                _stdc_phases = combined_df.groupby('stdc_phase')['spend'].sum()
                _do_spend = _stdc_phases.get('DO', 0)
                _see_spend = _stdc_phases.get('SEE', 0)
                _think_spend = _stdc_phases.get('THINK', 0)
                _upper_funnel = _see_spend + _think_spend
                if total_spend > 0:
                    _do_pct = _do_spend / total_spend * 100
                    _upper_pct = _upper_funnel / total_spend * 100
                    if _do_pct > 80:
                        st.info(
                            f"**{_do_pct:.0f}% of budget goes to DO (conversion) campaigns.** "
                            "Consider allocating more to SEE/THINK to build "
                            "awareness and fill the top of the funnel."
                        )
                    elif _upper_pct > 60:
                        st.info(
                            f"**{_upper_pct:.0f}% of budget goes to SEE/THINK (awareness).** "
                            "Strong brand building, but check if enough budget "
                            "reaches DO campaigns to drive conversions."
                        )

                # Platform split
                if google_spend > 0 and meta_spend > 0:
                    g_cpa_str = f"€{google_cpa:.2f}" if google_conv > 0 else "N/A"
                    m_cpa_str = f"€{meta_cpa:.2f}" if meta_conv > 0 else "N/A"
                    st.info(
                        f"**Google Ads CPA: {g_cpa_str} · Meta Ads CPA: {m_cpa_str}.** "
                        f"Google gets {google_spend/total_spend*100:.0f}% of budget, "
                        f"Meta gets {meta_spend/total_spend*100:.0f}%."
                    )


        with tab_campaigns:
            # Campaign Performance Table
            st.markdown("### Campaign Performance")

            # Prepare display table with more metrics
            display_df = combined_df.copy()

            # Filter out campaigns with invalid names (containing "--" or empty)
            display_df = display_df[
                ~display_df['campaign_name']
                .astype(str)
                .str.contains('^-+$|^ *$', regex=True, na=True)
            ]
            display_df = display_df[display_df['campaign_name'].notna()]
            display_df = display_df[display_df['campaign_name'].astype(str).str.strip() != '']

            # Calculate additional metrics (vectorized)
            display_df['cpc'] = (
                display_df['spend']
                / display_df['clicks'].replace(0, float('nan'))
            ).fillna(0)
            display_df['cpa'] = (
                display_df['spend']
                / display_df['conversions'].replace(
                    0, float('nan')
                )
            ).fillna(0)
            display_df['conv_rate'] = (
                display_df['conversions']
                / display_df['clicks'].replace(0, float('nan'))
                * 100
            ).fillna(0)

            # Create combined Reach/Impressions column (impressions for Google, reach for Meta)
            if 'impressions' not in display_df.columns:
                display_df['impressions'] = 0
            if 'reach' not in display_df.columns:
                display_df['reach'] = 0
            # Vectorized: use impressions for Google, reach for Meta
            display_df['reach_impr'] = display_df['impressions'].where(
                display_df['Platform'] == 'Google Ads', display_df['reach']
            )

            # Select and rename columns
            display_cols = [
                'campaign_name', 'Platform', 'stdc_phase',
                'spend', 'reach_impr', 'clicks', 'conversions',
                'conversion_value', 'cpc', 'cpa', 'conv_rate',
            ]
            display_cols = [c for c in display_cols if c in display_df.columns]

            display_df = display_df[display_cols].copy()
            display_df = display_df.rename(columns={
                'campaign_name': 'Campaign',
                'stdc_phase': 'STDC',
                'spend': 'Spend',
                'reach_impr': 'Reach/Impr',
                'clicks': 'Clicks',
                'conversions': 'Conv',
                'conversion_value': 'Conv. Value',
                'cpc': 'CPC',
                'cpa': 'CPA',
                'conv_rate': 'Conv %'
            })

            # Round numeric columns appropriately
            int_cols = ['Spend', 'Reach/Impr', 'Clicks', 'Conv', 'Conv. Value']
            for col in int_cols:
                if col in display_df.columns:
                    display_df[col] = display_df[col].round(0).astype(int)

            # Keep CPC and CPA with 2 decimal places
            if 'CPC' in display_df.columns:
                display_df['CPC'] = display_df['CPC'].round(2)
            if 'CPA' in display_df.columns:
                display_df['CPA'] = display_df['CPA'].round(2)

            if 'Conv %' in display_df.columns:
                display_df['Conv %'] = display_df['Conv %'].round(0).astype(int)

            # Sort by Platform (Google Ads first) then by Spend descending
            display_df = display_df.sort_values(['Platform', 'Spend'], ascending=[True, False])

            # Add total row
            total_row = {
                'Campaign': 'Total',
                'Platform': '',
                'STDC': '',
            }
            for col in ['Spend', 'Reach/Impr', 'Clicks', 'Conv', 'Conv. Value']:
                if col in display_df.columns:
                    total_row[col] = display_df[col].sum()
            if 'CPC' in display_df.columns:
                total_clicks = total_row.get('Clicks', 0)
                total_row['CPC'] = (total_row['Spend'] / total_clicks) if total_clicks > 0 else 0
            if 'CPA' in display_df.columns:
                total_conv = total_row.get('Conv', 0)
                total_row['CPA'] = (total_row['Spend'] / total_conv) if total_conv > 0 else 0
            if 'Conv %' in display_df.columns:
                total_clicks = total_row.get('Clicks', 0)
                total_conv = total_row.get('Conv', 0)
                total_row['Conv %'] = (total_conv / total_clicks * 100) if total_clicks > 0 else 0
            display_df = pd.concat([display_df, pd.DataFrame([total_row])], ignore_index=True)

            # Apply Dutch number formatting
            display_df = format_dataframe_nl(
                display_df,
                euro_cols=['Spend', 'Conv. Value'],
                int_cols=['Reach/Impr', 'Clicks', 'Conv'],
                pct_cols=['Conv %'],
                euro_decimal_cols=['CPC', 'CPA'],
            )

            # Color coding for STDC phase
            def style_stdc(val):
                if val == 'SEE':
                    return 'background-color: #dbeafe; color: #1e40af'
                elif val == 'THINK':
                    return 'background-color: #fef3c7; color: #92400e'
                elif val == 'DO':
                    return 'background-color: #dcfce7; color: #166534'
                elif val == 'CARE':
                    return 'background-color: #fce7f3; color: #9d174d'
                return 'background-color: #f3f4f6; color: #4b5563'

            def style_total_row(row):
                if row['Campaign'] == 'Total':
                    return ['font-weight: bold; border-top: 2px solid #333'] * len(row)
                return [''] * len(row)

            styled_df = display_df.style.map(style_stdc, subset=['STDC']).apply(style_total_row, axis=1)

            campaign_config = {
                'Campaign': st.column_config.TextColumn('Campaign', help='Campaign name from ad platform'),
                'Platform': st.column_config.TextColumn('Platform', help='Google Ads or Meta Ads'),
                'STDC': st.column_config.TextColumn('STDC', help='SEE-THINK-DO-CARE funnel phase'),
                'Spend': st.column_config.TextColumn('Spend', help='Total ad spend for this campaign'),
                'Reach/Impr': st.column_config.TextColumn('Reach/Impr', help='Impressions (Google) or Reach (Meta)'),
                'Clicks': st.column_config.TextColumn('Clicks', help='Link clicks on ads'),
                'Conv': st.column_config.TextColumn('Conv', help='Purchases/conversions tracked'),
                'Conv. Value': st.column_config.TextColumn('Conv. Value', help='Conversion value reported'),
                'CPC': st.column_config.TextColumn('CPC', help='Cost per Click = Spend / Clicks'),
                'CPA': st.column_config.TextColumn('CPA', help='Cost per Acquisition = Spend / Conversions'),
                'Conv %': st.column_config.TextColumn('Conv %', help='Conversion Rate = Conversions / Clicks'),
            }
            st.dataframe(
                styled_df,
                use_container_width=True,
                hide_index=True,
                height=(len(display_df) + 1) * 35 + 3,
                column_config=campaign_config,
            )

            st.write("")
            st.markdown("### Platform Comparison")

            # Better color contrast: Google = Blue, Meta = Teal
            platform_colors = {'Google Ads': '#4285f4', 'Meta Ads': '#00C4B4'}

            # Calculate platform metrics with more detail
            platform_metrics = combined_df.groupby('Platform').agg({
                'spend': 'sum',
                'conversions': 'sum',
                'clicks': 'sum',
                'conversion_value': 'sum'
            }).reset_index()

            # Add reach/impressions
            google_reach = (
                combined_df[combined_df['Platform'] == 'Google Ads']
                ['impressions'].sum()
                if 'impressions' in combined_df.columns
                else 0
            )
            meta_reach = (
                combined_df[combined_df['Platform'] == 'Meta Ads']
                ['reach'].sum()
                if 'reach' in combined_df.columns
                else 0
            )
            platform_metrics['reach'] = (
                [google_reach, meta_reach]
                if len(platform_metrics) == 2
                else [google_reach + meta_reach]
            )

            # Calculate CPA per platform
            platform_metrics['cpa'] = platform_metrics.apply(
                lambda x: (
                    x['spend'] / x['conversions']
                    if x['conversions'] > 0
                    else 0
                ),
                axis=1
            )

            # Row 1: Spend, Conversions, Conv Value
            col1, col2, col3 = st.columns(3)

            with col1:
                fig_plat_spend = px.pie(
                    platform_metrics,
                    values='spend',
                    names='Platform',
                    title='Spend',
                    color='Platform',
                    color_discrete_map=platform_colors
                )
                fig_plat_spend.update_layout(
                    height=350, showlegend=True,
                )
                fig_plat_spend.update_traces(
                    textinfo='percent+value',
                    texttemplate='%{percent:.1%}<br>€%{value:,.0f}',
                )
                st.plotly_chart(
                    fig_plat_spend, use_container_width=True,
                )

            with col2:
                fig_plat_conv = px.pie(
                    platform_metrics,
                    values='conversions',
                    names='Platform',
                    title='Conversions',
                    color='Platform',
                    color_discrete_map=platform_colors
                )
                fig_plat_conv.update_layout(
                    height=350, showlegend=True,
                )
                fig_plat_conv.update_traces(
                    textinfo='percent+value',
                    texttemplate='%{percent:.1%}<br>%{value:,.0f}',
                )
                st.plotly_chart(
                    fig_plat_conv, use_container_width=True,
                )

            with col3:
                fig_plat_value = px.pie(
                    platform_metrics,
                    values='conversion_value',
                    names='Platform',
                    title='Conversion Value',
                    color='Platform',
                    color_discrete_map=platform_colors
                )
                fig_plat_value.update_layout(
                    height=350, showlegend=True,
                )
                fig_plat_value.update_traces(
                    textinfo='percent+value',
                    texttemplate='%{percent:.1%}<br>€%{value:,.0f}',
                )
                st.plotly_chart(
                    fig_plat_value, use_container_width=True,
                )

            # Row 2: Clicks, Reach, CPA comparison
            col1, col2, col3 = st.columns(3)

            with col1:
                fig_plat_clicks = px.pie(
                    platform_metrics,
                    values='clicks',
                    names='Platform',
                    title='Clicks',
                    color='Platform',
                    color_discrete_map=platform_colors
                )
                fig_plat_clicks.update_layout(
                    height=350, showlegend=True,
                )
                fig_plat_clicks.update_traces(
                    textinfo='percent+value',
                    texttemplate='%{percent:.1%}<br>%{value:,.0f}',
                )
                st.plotly_chart(
                    fig_plat_clicks, use_container_width=True,
                )

            with col2:
                fig_plat_reach = px.pie(
                    platform_metrics,
                    values='reach',
                    names='Platform',
                    title='Reach / Impressions',
                    color='Platform',
                    color_discrete_map=platform_colors
                )
                fig_plat_reach.update_layout(
                    height=350, showlegend=True,
                )
                fig_plat_reach.update_traces(
                    textinfo='percent+value',
                    texttemplate='%{percent:.1%}<br>%{value:,.0f}',
                )
                st.plotly_chart(
                    fig_plat_reach, use_container_width=True,
                )

            with col3:
                # CTR comparison as pie chart
                # Calculate CTR per platform
                google_ctr = (
                    (
                        google_df['clicks'].sum()
                        / google_df['impressions'].sum()
                        * 100
                    )
                    if 'impressions' in google_df.columns
                    and google_df['impressions'].sum() > 0
                    else 0
                )
                meta_ctr = (
                    (
                        meta_df['clicks'].sum()
                        / meta_df['reach'].sum()
                        * 100
                    )
                    if 'reach' in meta_df.columns
                    and meta_df['reach'].sum() > 0
                    else 0
                )

                ctr_data = pd.DataFrame({
                    'Platform': ['Google Ads', 'Meta Ads'],
                    'ctr': [google_ctr, meta_ctr]
                })

                fig_plat_ctr = px.pie(
                    ctr_data,
                    values='ctr',
                    names='Platform',
                    title='CTR Distribution',
                    color='Platform',
                    color_discrete_map=platform_colors
                )
                fig_plat_ctr.update_layout(
                    height=350, showlegend=True,
                )
                fig_plat_ctr.update_traces(
                    textinfo='percent+value',
                    texttemplate='%{percent:.1%}<br>%{value:.2f}%',
                )
                st.plotly_chart(
                    fig_plat_ctr, use_container_width=True,
                )

            # STDC Tag Configuration
            with st.expander("Configure STDC Tags", expanded=False):
                st.markdown("""
                Assign each campaign to a SEE-THINK-DO-CARE phase.
                Default suggestions are based on campaign name keywords.
                """)

                campaigns = sorted(combined_df['campaign_name'].unique().tolist())

                for campaign in campaigns:
                    current_tag = st.session_state.stdc_tags.get(campaign, 'Untagged')

                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.text(campaign[:60] + '...' if len(campaign) > 60 else campaign)
                    with col2:
                        new_tag = st.selectbox(
                            "Phase",
                            options=['SEE', 'THINK', 'DO', 'CARE', 'Untagged'],
                            index=['SEE', 'THINK', 'DO', 'CARE', 'Untagged'].index(current_tag),
                            key=f"stdc_{campaign}",
                            label_visibility="collapsed"
                        )
                        st.session_state.stdc_tags[campaign] = new_tag

                if st.button("Reset All to Suggestions", key="reset_stdc"):
                    for campaign in campaigns:
                        st.session_state.stdc_tags[campaign] = suggest_stdc_phase(campaign)
                    st.rerun()

            # --- Key Takeaways ---
            with st.expander("Key Takeaways"):
                # Best performing campaign
                _camp_perf = combined_df.groupby('campaign_name').agg(
                    spend=('spend', 'sum'),
                    conversions=('conversions', 'sum'),
                ).reset_index()
                _camp_perf = _camp_perf[_camp_perf['conversions'] > 0]
                if len(_camp_perf) > 0:
                    _camp_perf['cpa'] = _camp_perf['spend'] / _camp_perf['conversions']
                    _best = _camp_perf.loc[_camp_perf['cpa'].idxmin()]
                    _worst = _camp_perf.loc[_camp_perf['cpa'].idxmax()]
                    st.info(
                        f"**Most efficient campaign: {_best['campaign_name'][:50]}** "
                        f"with a CPA of €{_best['cpa']:.2f} "
                        f"({_best['conversions']:.0f} conversions)."
                    )
                    if _best['campaign_name'] != _worst['campaign_name']:
                        st.info(
                            f"**Least efficient campaign: {_worst['campaign_name'][:50]}** "
                            f"with a CPA of €{_worst['cpa']:.2f} "
                            f"({_worst['conversions']:.0f} conversions). "
                            "Review targeting and creatives."
                        )

                # Platform comparison
                if google_conv > 0 and meta_conv > 0:
                    _better = "Google Ads" if google_cpa < meta_cpa else "Meta Ads"
                    _diff = abs(google_cpa - meta_cpa)
                    st.info(
                        f"**{_better} is €{_diff:.2f} cheaper per conversion.** "
                        f"Google CPA: €{google_cpa:.2f}, "
                        f"Meta CPA: €{meta_cpa:.2f}."
                    )


        with tab_roi:
            st.markdown("### Marketing ROI by Location")

            # Platform filter is page-level (control above the tabs).
            # Reading session_state directly removes the value=-fallback
            # path that the old per-tab toggle pair was vulnerable to.
            selected_platforms = list(
                st.session_state.marketing_selected_platforms
            )
            _filter_caption = _platform_filter_caption(selected_platforms)
            if _filter_caption:
                st.caption(_filter_caption)

            # Check if we have booking data
            if len(selected_platforms) == 0:
                st.warning(
                    "Please select at least one platform from the"
                    " filter above the tabs."
                )
            else:
                # Read the LOADED snapshot — never the live widgets.
                # Editing the date picker without pressing `Load` must
                # not relabel old data with a new range.
                min_date = st.session_state.get("bookeo_loaded_start_date")
                max_date = st.session_state.get("bookeo_loaded_end_date")

                if min_date is None or max_date is None:
                    st.warning("Load bookings first — date range required.")
                elif st.session_state.get("location_performance_do_df") is None:
                    _err = st.session_state.get(
                        "location_performance_do_load_error"
                    )
                    st.warning(
                        "Could not load location performance from"
                        " BigQuery. Try reloading."
                        + (f" ({_err})" if _err else "")
                    )
                else:
                    # Pinned to the last Load click — same lifecycle as
                    # `google_ads_df` / `meta_ads_df`, so total_spend (from
                    # `combined_df`) and attributed_spend (from this frame)
                    # always span the same date range.
                    # `include_canceled` mirrors the booking-data toggle so
                    # the ROI table uses the same booking universe as the
                    # rest of the page. We read the LOAD-TIME snapshot
                    # (`bookeo_loaded_include_canceled`), not the live
                    # checkbox — flipping the toggle without pressing
                    # `Load` must not drift the ROI table from the loaded
                    # `df1` that AOV / target-CPA already depend on.
                    #
                    # The DO-only frame is the source: every column on
                    # this tab (spend, clicks, conversions, conv. value,
                    # CPA, ROAS) reflects conversion-stage campaigns
                    # only. SEE/THINK upper-funnel spend lives on the
                    # Overview tab, not here.
                    location_df = st.session_state.location_performance_do_df
                    _include_canceled = st.session_state.get(
                        "bookeo_loaded_include_canceled", False,
                    )
                    roi_table = create_marketing_roi_table(
                        location_df,
                        selected_platforms,
                        include_canceled=_include_canceled,
                    )

                    if roi_table is None or len(roi_table) == 0:
                        st.warning(
                            "No location-level marketing data for the"
                            " selected platforms and date range."
                        )
                    else:
                        attributed_spend = float(roi_table['Ad Spend'].sum())

                        # Excluded-spend banner — both sides of the
                        # subtraction MUST use the same platform AND
                        # phase subset, otherwise the percentage
                        # conflates "not mapped to a location" with
                        # "not in the DO universe at all". Since this
                        # tab now reads from `v_location_performance_do`,
                        # we filter combined_df to DO-phase rows for
                        # the comparison total too.
                        roi_filtered_df = combined_df[
                            combined_df['Platform'].isin(selected_platforms)
                        ] if 'Platform' in combined_df.columns else combined_df
                        if 'stdc_phase' in roi_filtered_df.columns:
                            roi_filtered_df = roi_filtered_df[
                                roi_filtered_df['stdc_phase'] == 'DO'
                            ]
                        total_spend = float(roi_filtered_df['spend'].sum())
                        excluded_spend = max(total_spend - attributed_spend, 0.0)
                        excluded_pct = (
                            (excluded_spend / total_spend * 100)
                            if total_spend > 0
                            else 0
                        )

                        if excluded_spend > 0:
                            st.info(
                                f"**{format_euro(excluded_spend)}**"
                                f" ({excluded_pct:.1f}%) of DO-phase ad"
                                " spend is excluded from this table"
                                " because it doesn't map to a specific"
                                " location — see **How this table works**"
                                " below."
                            )

                        # Methodology captions (concept-based weighted
                        # allocation, funnel-exclusion explanation,
                        # visit-date aggregation note) live in the
                        # "How this table works" expander below the
                        # table — duplicating them above the metrics
                        # made the header stack feel cluttered. The
                        # banner above links readers to the expander
                        # when the excluded share matters.

                        start_str = pd.to_datetime(min_date).strftime('%d %b %Y')
                        end_str = pd.to_datetime(max_date).strftime('%d %b %Y')
                        st.caption(f"Data period: {start_str} - {end_str}")

                        # Headline metrics
                        total_bookings = int(roi_table['Bookings'].sum())
                        total_turnover = float(roi_table['Turnover'].sum())
                        total_clicks = float(roi_table['Clicks'].sum())
                        total_conversions = float(roi_table['Conversions'].sum())
                        overall_cpa = (
                            attributed_spend / total_conversions
                            if total_conversions > 0
                            else 0
                        )
                        overall_conv_rate = (
                            (total_conversions / total_clicks * 100)
                            if total_clicks > 0
                            else 0
                        )
                        # Headline ROAS mirrors the per-row definition:
                        # sum of platform-attributed revenue across rows
                        # (each row's Conversions × that row's AOV)
                        # divided by total ad spend. Avoids the "blended"
                        # inflation of total_turnover / total_spend, which
                        # would credit organic + direct bookings too.
                        _aov_per_row = (
                            roi_table["Turnover"]
                            / roi_table["Bookings"].replace(0, float("nan"))
                        ).fillna(0)
                        attributed_revenue = float(
                            (roi_table["Conversions"] * _aov_per_row).sum()
                        )
                        overall_roas = (
                            (attributed_revenue / attributed_spend)
                            if attributed_spend > 0
                            else 0
                        )

                        col1, col2, col3, col4, col5 = st.columns(5)
                        with col1:
                            st.metric(
                                "Ad Spend",
                                format_euro(attributed_spend),
                                help="Total ad spend allocated to specific locations.",
                            )
                        with col2:
                            st.metric(
                                "Attributed Revenue",
                                format_euro(attributed_revenue),
                                help=(
                                    "Platform-attributed bookings ×"
                                    " booking-system AOV — the share of"
                                    " location turnover the ad platform"
                                    " claims to have driven. Lower bound"
                                    " (platform conversions undercount"
                                    " by 30–60% due to iOS SKAdNetwork,"
                                    " cookie consent, ad-blockers)."
                                ),
                            )
                        with col3:
                            st.metric(
                                "Conv. Rate",
                                f"{overall_conv_rate:.1f}%".replace(".", ","),
                                help=(
                                    "Conversions / Clicks x 100"
                                    " (% of clicks that converted)"
                                ),
                            )
                        with col4:
                            st.metric(
                                "Avg CPA",
                                format_euro(overall_cpa, 2),
                                help="Cost per Acquisition = Ad Spend / Conversions.",
                            )
                        with col5:
                            st.metric(
                                "ROAS",
                                f"{overall_roas:.1f}x".replace(".", ","),
                                help=(
                                    "Return on Ad Spend = (Conversions ×"
                                    " AOV) / Ad Spend, where AOV ="
                                    " Turnover / Bookings per location."
                                    " Only the bookings the ad platform"
                                    " attributed are counted — Turnover"
                                    " also includes organic, direct, and"
                                    " returning customers. Caveat:"
                                    " platform-reported conversions are"
                                    " systematically undercounted (iOS"
                                    " SKAdNetwork, cookie consent,"
                                    " ad-blockers) — typically by"
                                    " 30–60%. Treat this as a lower"
                                    " bound."
                                ),
                            )

                        # Per-location profit margins
                        locations = roi_table['Location'].tolist()
                        with st.expander("Profit Margins per Location", expanded=False):
                            st.caption(
                                "Set profit margin for each location to"
                                " calculate ROAS thresholds. Default: 70%"
                            )
                            margin_cols = st.columns(min(len(locations), 4))
                            location_margins = {}
                            for i, loc in enumerate(locations):
                                col_idx = i % 4
                                with margin_cols[col_idx]:
                                    short_name = (
                                        loc
                                        .replace('Stockholm ', '')
                                        .replace('Helsinki ', '')
                                    )
                                    location_margins[loc] = st.number_input(
                                        short_name,
                                        min_value=10,
                                        max_value=95,
                                        value=70,
                                        step=5,
                                        key=f"margin_{loc}",
                                        help=f"Profit margin % for {loc}",
                                    )

                        def get_roas_thresholds(margin_pct):
                            margin_decimal = margin_pct / 100
                            breakeven = 1 / margin_decimal
                            return breakeven * 1.5, breakeven * 2  # good, excellent

                        # Numeric copy preserved for color-coding the ROAS cell.
                        _roas_numeric = roi_table['ROAS'].copy()
                        _bookings_numeric = roi_table['Bookings'].copy().astype(int)

                        st.caption(
                            "ROAS colors:"
                            " \U0001f534 < 1.5x break-even"
                            " | \U0001f7e1 1.5x - 2x break-even"
                            " | \U0001f7e2 > 2x break-even"
                            " (thresholds vary by location margin)"
                        )

                        # Format numbers Dutch-style before display.
                        # ROAS uses the dedicated `roas_cols` formatter so it
                        # renders as `5,0x`, not `5,0%` from `pct_cols`.
                        # Turnover is dropped from the displayed table — it
                        # includes organic / direct / returning bookings that
                        # marketing didn't drive, so it doesn't belong on a
                        # marketing ROI surface. It stays in `roi_table` for
                        # the AOV calculation that feeds ROAS.
                        display_df = roi_table.drop(columns=['Turnover']).copy()
                        display_df['Bookings'] = _bookings_numeric
                        # Clicks/Conversions are weighted FLOAT64 from the
                        # view (cluster splits make them fractional). Use
                        # the adaptive formatter so whole values stay clean
                        # but fractional ones don't round to misleading 0s.
                        fmt_df = format_dataframe_nl(
                            display_df,
                            euro_cols=['Conv. Value', 'Ad Spend'],
                            int_cols=['Bookings'],
                            adaptive_num_cols=['Clicks', 'Conversions'],
                            pct_cols=['Conv. Rate %'],
                            euro_decimal_cols=['CPA'],
                            roas_cols=['ROAS'],
                        )

                        roi_config = {
                            'Location': st.column_config.TextColumn('Location'),
                            'Bookings': st.column_config.TextColumn(
                                'Bookings',
                                help='Bookings (excl. canceled) at this location during the period.',
                            ),
                            'Clicks': st.column_config.TextColumn(
                                'Clicks',
                                help='Weighted ad clicks attributed to this location.',
                            ),
                            'Conversions': st.column_config.TextColumn(
                                'Conversions',
                                help='Weighted platform-reported conversions.',
                            ),
                            'Conv. Rate %': st.column_config.TextColumn(
                                'Conv. Rate %',
                                help=(
                                    'Conversions / Clicks x 100'
                                    ' (% of clicks that converted)'
                                ),
                            ),
                            'Conv. Value': st.column_config.TextColumn(
                                'Conv. Value',
                                help='Platform-reported conversion value (informational).',
                            ),
                            'Ad Spend': st.column_config.TextColumn(
                                'Ad Spend',
                                help='Weighted ad spend attributed to this location.',
                            ),
                            'CPA': st.column_config.TextColumn(
                                'CPA',
                                help='Cost per Acquisition = Ad Spend / Conversions.',
                            ),
                            'ROAS': st.column_config.TextColumn(
                                'ROAS',
                                help=(
                                    '(Conversions × AOV) / Ad Spend, where'
                                    " AOV = location Turnover / Bookings."
                                    ' Lower bound — platform conversions'
                                    ' undercount by 30–60%.'
                                ),
                            ),
                        }

                        def style_roas_fmt(row):
                            idx = fmt_df.index.get_loc(row.name)
                            roas_val = _roas_numeric.iloc[idx]
                            loc = row['Location']
                            margin = location_margins.get(loc, 70)
                            good_threshold, excellent_threshold = get_roas_thresholds(margin)

                            styles = [''] * len(row)
                            roas_idx = row.index.get_loc('ROAS')

                            if roas_val >= excellent_threshold:
                                styles[roas_idx] = (
                                    'background-color: #dcfce7;'
                                    ' color: #166534'
                                )
                            elif roas_val >= good_threshold:
                                styles[roas_idx] = (
                                    'background-color: #fef3c7;'
                                    ' color: #92400e'
                                )
                            else:
                                styles[roas_idx] = (
                                    'background-color: #fecaca;'
                                    ' color: #991b1b'
                                )
                            return styles

                        styled_roi = fmt_df.style.apply(style_roas_fmt, axis=1)

                        st.dataframe(
                            styled_roi,
                            use_container_width=True,
                            hide_index=True,
                            column_config=roi_config,
                        )

                        with st.expander("How this table works", expanded=False):
                            st.markdown(
                                "**Scope: DO-phase campaigns only.**\n"
                                "Every metric on this table reflects"
                                " conversion-stage campaigns only — Meta's"
                                " `Think | Clicks | ABO`, `Clicks | Alle"
                                " locations`, and other upper-funnel"
                                " SEE / THINK spend is excluded from the"
                                " entire ROI universe (Clicks, Conversions,"
                                " Conv. Value, Ad Spend, CPA, ROAS). To"
                                " see total marketing spend including"
                                " awareness / consideration, use the"
                                " Overview tab.\n\n"
                                "**Data Sources:**\n"
                                "- **Bookings & Turnover**: From the"
                                " bookings table, aggregated by visit"
                                " date for each location.\n"
                                "- **Clicks, Conversions, Conv. Value,"
                                " Ad Spend**: Concept-based weighted"
                                " allocation from"
                                " `v_location_performance_do`. Cluster"
                                " ad-sets (e.g. 'Stockholm City', 'Helsinki')"
                                " split spend across their constituent"
                                " locations.\n\n"
                                "**What's Excluded:**\n"
                                "- SEE / THINK upper-funnel campaigns"
                                " (Meta `Think | Clicks | ABO`, Google"
                                " awareness / Demand Gen, etc.).\n"
                                "- DO-phase funnel ad-sets without a"
                                " city/helsinki cluster name (retargeting,"
                                " lookalikes, 'Clicks | All locations').\n\n"
                                "**Metrics:**\n"
                                "- **Conv. Rate %** = Conversions / Clicks"
                                " x 100\n"
                                "- **CPA** = Ad Spend / Conversions\n"
                                "- **ROAS** = (Conversions × AOV) / Ad"
                                " Spend, where AOV = Turnover / Bookings"
                                " per location. Counts only the bookings"
                                " the ad platform attributed, valued at"
                                " the location's booking-system AOV.\n"
                                "  - ⚠ Platform-reported conversions are"
                                " systematically undercounted — iOS"
                                " SKAdNetwork, cookie consent, ad-blockers"
                                " typically remove 30–60% of true"
                                " conversions before they reach the"
                                " platform. So this ROAS is a **lower"
                                " bound** on marketing's real"
                                " contribution; the true number is higher"
                                " but cannot be measured exactly without"
                                " incrementality testing.\n"
                                "  - We deliberately don't use Turnover /"
                                " Ad Spend, which would credit marketing"
                                " for organic, direct, and returning"
                                " customers too.\n\n"
                                "**ROAS Color Thresholds (per-location,"
                                " based on profit margin):**\n"
                                "- Break-even ROAS = 100 / margin%\n"
                                "- Red: < 1.5x break-even\n"
                                "- Yellow: 1.5x - 2x break-even\n"
                                "- Green: > 2x break-even\n\n"
                                "Set margins per location in the"
                                ' "Profit Margins per Location" expander'
                                " above."
                            )

            # --- Key Takeaways ---
            with st.expander("Key Takeaways"):
                st.info(
                    "**ROI varies significantly by location.** "
                    "Use the table above to identify which locations "
                    "generate positive returns and which need "
                    "budget reallocation or campaign optimization."
                )


        with tab_cpa:
            st.markdown("### CPA Targets")
            st.caption(
                "Calculate break-even and target CPA based on"
                " your booking data and cost structure."
            )
            _cpa_filter_caption = _platform_filter_caption(
                list(st.session_state.marketing_selected_platforms)
            )
            if _cpa_filter_caption:
                st.caption(_cpa_filter_caption)

            if st.session_state.df1 is None:
                st.info("Load booking data to calculate CPA targets.")
            else:
                # Detect columns
                _cols = st.session_state.df1.columns
                date_col = (
                    'Created' if 'Created' in _cols else 'Date'
                )
                revenue_col = (
                    'Total paid'
                    if 'Total paid' in _cols
                    else None
                )
                email_col = (
                    'Email address'
                    if 'Email address' in _cols
                    else None
                )

                if revenue_col is None:
                    st.warning("Turnover column not found in booking data.")
                else:
                    # Location selectbox
                    _loc_col = get_location_column(st.session_state.df1)
                    _available_locs = get_available_locations(
                        st.session_state.df1, _loc_col,
                    )
                    _cpa_loc_options = ["All locations"] + _available_locs
                    selected_cpa_location = st.selectbox(
                        "Location",
                        options=_cpa_loc_options,
                        index=0,
                        key="cpa_location_select",
                    )

                    # Filter booking data by location.
                    # Per-location CPA uses the same UI label directly against
                    # `v_location_performance` (the loader already remaps BQ
                    # canonical names to UI labels). No reverse-map lookup —
                    # `_BQ_TO_STREAMLIT_LOCATION` is one-to-many, so a naive
                    # inversion would point at the wrong canonical key.
                    cpa_df1 = st.session_state.df1
                    if selected_cpa_location != "All locations" and _loc_col:
                        cpa_df1 = cpa_df1[
                            cpa_df1[_loc_col] == selected_cpa_location
                        ]

                    if len(cpa_df1) == 0:
                        st.warning(
                            f"No booking data found for {selected_cpa_location}."
                        )
                    else:
                        # Calculate metrics from booking data
                        cpa_metrics = calculate_cpa_metrics(
                            cpa_df1,
                            date_col=date_col,
                            revenue_col=revenue_col,
                            email_col=email_col if email_col else 'Email address'
                        )

                        if cpa_metrics is None:
                            st.warning("Could not calculate CPA metrics from booking data.")
                        else:
                            # Per-location settings persistence
                            if 'cpa_location_settings' not in st.session_state:
                                st.session_state.cpa_location_settings = {}
                            _loc_defaults = st.session_state.cpa_location_settings.get(
                                selected_cpa_location,
                                {"bedrijfskosten": 70, "winstmarge": 10},
                            )
                            _def_bk = _loc_defaults["bedrijfskosten"]
                            _def_wm = min(
                                _loc_defaults["winstmarge"], 100 - _def_bk,
                            )

                            # Platform filter is page-level (control above
                            # the tabs); only the per-location margin inputs
                            # live here now.
                            col3, col4 = st.columns([1, 1])
                            with col3:
                                bedrijfskosten = st.number_input(
                                    "Operating costs %",
                                    min_value=0,
                                    max_value=100,
                                    value=_def_bk,
                                    step=5,
                                    key=f"cpa_bedrijfskosten_{selected_cpa_location}",
                                    help=(
                                        "Operating costs as % of turnover"
                                        " (e.g., 70% means €0.70 of each"
                                        " €1 goes to costs)"
                                    )
                                )
                            with col4:
                                winstmarge = st.number_input(
                                    "Profit margin %",
                                    min_value=0,
                                    max_value=100 - bedrijfskosten,
                                    value=min(_def_wm, 100 - bedrijfskosten),
                                    step=5,
                                    key=f"cpa_winstmarge_{selected_cpa_location}",
                                    help=(
                                        "Target profit as % of turnover."
                                        " Operating costs + Profit margin"
                                        " must be ≤ 100%. The remainder"
                                        " is your ad budget per booking."
                                    )
                                )

                            # Save per-location settings
                            st.session_state.cpa_location_settings[
                                selected_cpa_location
                            ] = {
                                "bedrijfskosten": bedrijfskosten,
                                "winstmarge": winstmarge,
                            }

                            ad_budget_pct = 100 - bedrijfskosten - winstmarge
                            _, _, cost_label_col = st.columns([1, 1, 2])
                            with cost_label_col:
                                st.caption(
                                    f"{bedrijfskosten}% operating costs · {winstmarge}% profit margin"
                                    f" · **{ad_budget_pct}% ads** = 100%"
                                )

                            # Platform filter is page-level (control above
                            # the tabs). Single source of truth shared with
                            # the ROI tab — toggling Meta on the filter
                            # applies here too.
                            cpa_selected_platforms = list(
                                st.session_state.marketing_selected_platforms
                            )

                            if len(cpa_selected_platforms) == 0:
                                st.warning(
                                    "Please select at least one platform"
                                    " from the filter above the tabs to"
                                    " calculate Actual CPA."
                                )

                            # Calculate CPA targets
                            cpa_targets = calculate_cpa_targets(
                                cpa_metrics['aov'],
                                bedrijfskosten,
                                winstmarge,
                                cpa_metrics['retention_rate']
                            )

                            # Get actual CPA from marketing data.
                            # Per-location: read from
                            # `v_location_performance_do` — DO-only
                            # concept-based weighted allocation. CPA
                            # measures conversion-stage spend, so SEE
                            # / THINK upper-funnel campaigns (Meta's
                            # `Think | Clicks | ABO` etc.) are
                            # excluded from both numerator and
                            # denominator. Keeps this tab consistent
                            # with the All locations path (which has
                            # always excluded SEE/THINK) and with the
                            # ROI tab (also DO-only after this PR).
                            # "All locations": stays on the legacy
                            # combined_df path with SEE/THINK excluded
                            # — the view only contains mapped rows,
                            # so summing across all locations would
                            # silently drop ~€18k of unmapped Meta
                            # funnel spend (Decision 1).
                            actual_cpa = None
                            cpa_load_error = None
                            if selected_cpa_location != "All locations":
                                cpa_location_df = st.session_state.get(
                                    "location_performance_do_df",
                                )
                                if cpa_location_df is None:
                                    # Distinguish loader failure from "no data
                                    # in range" so the user sees BigQuery
                                    # errors explicitly rather than as N/A.
                                    cpa_load_error = st.session_state.get(
                                        "location_performance_do_load_error",
                                    )
                                elif cpa_selected_platforms:
                                    actual_cpa = calculate_location_actual_cpa(
                                        cpa_location_df,
                                        selected_cpa_location,
                                        cpa_selected_platforms,
                                    )
                            elif (
                                'combined_df' in dir()
                                and combined_df is not None
                                and len(combined_df) > 0
                            ):
                                # SEE/THINK excluded only on the legacy headline
                                # path. Per-location branch above includes all
                                # phases by design (Decision 4).
                                excluded_phases = ['SEE', 'THINK']
                                cpa_df = combined_df.copy()
                                if (
                                    'Platform' in cpa_df.columns
                                    and len(cpa_selected_platforms) > 0
                                ):
                                    cpa_df = cpa_df[cpa_df['Platform'].isin(cpa_selected_platforms)]
                                if 'stdc_phase' in cpa_df.columns:
                                    cpa_df = cpa_df[
                                        ~cpa_df['stdc_phase']
                                        .isin(excluded_phases)
                                    ]
                                total_spend = cpa_df['spend'].sum()
                                total_conversions = cpa_df['conversions'].sum()
                                if total_conversions > 0:
                                    actual_cpa = total_spend / total_conversions

                        # Build metrics table
                        st.markdown("#### Per-Booking CPA")

                        # Per-booking metrics
                        col1, col2, col3, col4 = st.columns(4)
                        with col1:
                            st.metric(
                                "AOV",
                                f"€{cpa_metrics['aov']:.2f}",
                                help=(
                                    "Average Order Value"
                                    " = Total Turnover / Total Bookings"
                                )
                            )
                        with col2:
                            st.metric(
                                "Break-even CPA",
                                f"€{cpa_targets['breakeven_cpa']:.2f}",
                                help=(
                                    "Maximum CPA to avoid loss"
                                    " = AOV x (1 - Operating costs%)"
                                    f" = €{cpa_metrics['aov']:.2f}"
                                    f" x {(100-bedrijfskosten)/100:.2f}"
                                )
                            )
                        with col3:
                            st.metric(
                                "Target CPA",
                                f"€{cpa_targets['target_cpa']:.2f}",
                                help=(
                                    "CPA to achieve target profit"
                                    " = AOV x (1 - Operating costs%"
                                    " - Profit margin%)"
                                    f" = €{cpa_metrics['aov']:.2f}"
                                    f" x {max(0, 100-bedrijfskosten-winstmarge)/100:.2f}"
                                )
                            )
                        with col4:
                            if actual_cpa is not None:
                                delta = actual_cpa - cpa_targets['target_cpa']
                                delta_color = "inverse" if delta > 0 else "normal"
                                _cpa_help = (
                                    "Per-location actual CPA from concept-based"
                                    " weighted allocation. Includes all STDC"
                                    " phases (SEE, THINK, DO, CARE)."
                                    if selected_cpa_location != "All locations"
                                    else (
                                        "Overall actual CPA across all platforms,"
                                        " excluding SEE & THINK awareness"
                                        " campaigns. Includes funnel spend that"
                                        " can't be attributed to a single"
                                        " location."
                                    )
                                )
                                st.metric(
                                    "Actual CPA",
                                    f"€{actual_cpa:.2f}",
                                    delta=f"€{delta:+.2f} vs target",
                                    delta_color=delta_color,
                                    help=_cpa_help,
                                )
                            else:
                                if cpa_load_error:
                                    _na_help = (
                                        "Could not load location performance"
                                        f" from BigQuery: {cpa_load_error}."
                                        " Try reloading."
                                    )
                                elif selected_cpa_location != "All locations":
                                    _na_help = (
                                        "No weighted-allocated spend for this"
                                        " location in the selected date range."
                                    )
                                else:
                                    _na_help = "Load marketing data to see actual CPA"
                                st.metric(
                                    "Actual CPA",
                                    "N/A",
                                    help=_na_help,
                                )
                            if (
                                actual_cpa is not None
                                and selected_cpa_location != "All locations"
                            ):
                                st.caption(
                                    "DO-phase campaigns only (SEE / THINK"
                                    " upper-funnel spend is excluded from"
                                    " the CPA calculation)."
                                )

                        # CLV-based CPA with horizon toggle
                        if _clv_aov > 0 and _clv_monthly_ret > 0:
                            # Use per-location CLV inputs when a location is selected
                            _clv_aov_eff = _clv_aov
                            _clv_freq_eff = _clv_monthly_freq
                            _clv_ret_eff = _clv_monthly_ret
                            _clv_source = "global"

                            if selected_cpa_location != "All locations":
                                _end = st.session_state.get("bookeo_loaded_end_date")
                                if _end:
                                    _end_str = _end.strftime("%Y-%m-%d") if hasattr(_end, "strftime") else str(_end)
                                    try:
                                        _loc_clv = _get_clv_inputs_by_location(_end_str, selected_cpa_location)
                                        if _loc_clv["aov"] > 0 and _loc_clv["total_customers"] > 0:
                                            _clv_aov_eff = _loc_clv["aov"]
                                            _loc_freq = _loc_clv["mean_annual_frequency"]
                                            _clv_freq_eff = _loc_freq / 12
                                            _loc_ret = _loc_clv["retention_rate"]
                                            _clv_ret_eff = _loc_ret ** (1 / 12) if _loc_ret > 0 else 0
                                            _clv_source = "location"
                                    except Exception:
                                        pass

                            clv_horizon = st.segmented_control(
                                "CLV horizon",
                                ["1-Year", "2-Year", "3-Year"],
                                default="1-Year",
                                key="cpa_clv_horizon",
                            )
                            horizon_months = {"1-Year": 12, "2-Year": 24, "3-Year": 36}
                            n_months = horizon_months.get(clv_horizon, 12)
                            horizon_label = clv_horizon or "1-Year"

                            clv_val = sum(
                                _clv_aov_eff * _clv_freq_eff * (_clv_ret_eff ** m)
                                for m in range(n_months)
                            )

                            bk_frac_val = (100 - bedrijfskosten) / 100
                            wm_frac_val = (100 - winstmarge) / 100
                            breakeven_cpa_clv = clv_val * bk_frac_val
                            target_cpa_clv = breakeven_cpa_clv * wm_frac_val

                            st.markdown(f"#### Per-Customer CPA ({horizon_label} CLV)")
                            _clv_caption = (
                                f"Based on projected {horizon_label.lower()} customer lifetime value"
                                " — allows higher CPA when customers return."
                            )
                            if _clv_source == "location":
                                _clv_caption += (
                                    f" Using **{selected_cpa_location}** AOV, frequency, and retention."
                                )
                            st.caption(_clv_caption)

                            col1, col2, col3, col4 = st.columns(4)
                            with col1:
                                if _clv_source == "location":
                                    _clv_help = (
                                        f"Projected {horizon_label.lower()} CLV based on"
                                        f" {selected_cpa_location} data only."
                                        f"\n\nAll three inputs are location-specific:"
                                        f"\n• AOV: €{_clv_aov_eff:.2f} (avg booking value here)"
                                        f"\n• Monthly freq: {_clv_freq_eff:.3f} (how often customers rebook here)"
                                        f"\n• Monthly retention: {_clv_ret_eff:.3f} (chance of returning to this location)"
                                        f"\n\nFormula: AOV × freq × retention decay over {n_months} months."
                                        f" This will be lower than the global CLV because"
                                        " customers split visits across locations."
                                    )
                                else:
                                    _clv_help = (
                                        f"Projected {horizon_label.lower()} customer lifetime value"
                                        " using AOV × monthly frequency × retention"
                                        f" decay over {n_months} months."
                                        " Based on all Northern Sauna locations combined."
                                    )
                                st.metric(
                                    f"CLV ({horizon_label})",
                                    f"€{clv_val:.2f}",
                                    help=_clv_help,
                                )
                            with col2:
                                st.metric(
                                    "Break-even CPA (CLV)",
                                    f"€{breakeven_cpa_clv:.2f}",
                                    help=(
                                        f"Maximum CPA based on {horizon_label} CLV"
                                        " = CLV × (1 - Operating costs%)"
                                        f" = €{clv_val:.2f}"
                                        f" × {bk_frac_val:.2f}"
                                    )
                                )
                            with col3:
                                st.metric(
                                    "Target CPA (CLV)",
                                    f"€{target_cpa_clv:.2f}",
                                    help=(
                                        f"Target CPA based on {horizon_label} CLV"
                                        " = Break-even (CLV) × (1 - Profit margin%)"
                                        f" = €{breakeven_cpa_clv:.2f}"
                                        f" × {wm_frac_val:.2f}"
                                    )
                                )
                            with col4:
                                if actual_cpa is not None:
                                    delta_clv = actual_cpa - target_cpa_clv
                                    delta_color_clv = "inverse" if delta_clv > 0 else "normal"
                                    st.metric(
                                        "Actual CPA",
                                        f"€{actual_cpa:.2f}",
                                        delta=f"€{delta_clv:+.2f} vs target",
                                        delta_color=delta_color_clv,
                                        help="Comparison of actual CPA to CLV-based target"
                                    )

                        # Detailed table
                        with st.expander("View Calculation Details", expanded=False):
                            aov_val = cpa_metrics['aov']
                            be_cpa = cpa_targets['breakeven_cpa']
                            t_cpa = cpa_targets['target_cpa']
                            bk_frac = (100 - bedrijfskosten) / 100
                            wm_frac = (100 - winstmarge) / 100
                            table_data = [
                                {
                                    "Metric": "AOV (Average Order Value)",
                                    "Value": f"€{aov_val:.2f}",
                                    "Source": "Booking data",
                                    "Formula": "Total Turnover / Total Bookings",
                                },
                                {
                                    "Metric": "Operating costs %",
                                    "Value": f"{bedrijfskosten}%",
                                    "Source": "User input",
                                    "Formula": "-",
                                },
                                {
                                    "Metric": "Break-even CPA",
                                    "Value": f"€{be_cpa:.2f}",
                                    "Source": "Calculated",
                                    "Formula": (
                                        f"AOV x (1 - {bedrijfskosten}% operating costs)"
                                        f" = €{aov_val:.2f}"
                                        f" x {bk_frac:.2f}"
                                    ),
                                },
                                {
                                    "Metric": "Profit margin %",
                                    "Value": f"{winstmarge}%",
                                    "Source": "User input",
                                    "Formula": "-",
                                },
                                {
                                    "Metric": "Target CPA",
                                    "Value": f"€{t_cpa:.2f}",
                                    "Source": "Calculated",
                                    "Formula": (
                                        f"AOV x (1 - {bedrijfskosten}% operating costs"
                                        f" - {winstmarge}%)"
                                        f" = €{aov_val:.2f}"
                                        f" x {max(0, 100-bedrijfskosten-winstmarge)/100:.2f}"
                                    ),
                                },
                            ]

                            if _clv_aov > 0 and _clv_monthly_ret > 0:
                                _bk = (100 - bedrijfskosten) / 100
                                _wm = (100 - winstmarge) / 100
                                _be_clv = clv_val * _bk
                                _t_clv = _be_clv * _wm
                                _src_label = (
                                    f"Location ({selected_cpa_location})"
                                    if _clv_source == "location"
                                    else "Global (all locations)"
                                )
                                table_data.extend([
                                    {
                                        "Metric": "CLV AOV",
                                        "Value": f"€{_clv_aov_eff:.2f}",
                                        "Source": _src_label,
                                        "Formula": "Total paid / Total bookings (12-month window)",
                                    },
                                    {
                                        "Metric": "Monthly frequency",
                                        "Value": f"{_clv_freq_eff:.3f}",
                                        "Source": _src_label,
                                        "Formula": "Mean annual bookings / 12",
                                    },
                                    {
                                        "Metric": "Monthly retention",
                                        "Value": f"{_clv_ret_eff:.3f}",
                                        "Source": _src_label,
                                        "Formula": "Annual retention ^ (1/12)",
                                    },
                                    {
                                        "Metric": f"CLV ({horizon_label})",
                                        "Value": f"€{clv_val:.2f}",
                                        "Source": "Calculated",
                                        "Formula": (
                                            "AOV × monthly freq × retention"
                                            f" decay over {n_months} months"
                                        ),
                                    },
                                    {
                                        "Metric": "Break-even CPA (CLV)",
                                        "Value": f"€{_be_clv:.2f}",
                                        "Source": "Calculated",
                                        "Formula": (
                                            f"CLV × (1 - {bedrijfskosten}% operating costs)"
                                            f" = €{clv_val:.2f}"
                                            f" × {_bk:.2f}"
                                        ),
                                    },
                                    {
                                        "Metric": "Target CPA (CLV)",
                                        "Value": f"€{_t_clv:.2f}",
                                        "Source": "Calculated",
                                        "Formula": (
                                            f"Break-even (CLV) × (1 - {winstmarge}% profit margin)"
                                            f" = €{_be_clv:.2f}"
                                            f" × {_wm:.2f}"
                                        ),
                                    },
                                ])

                            if actual_cpa is not None:
                                table_data.append({
                                    "Metric": (
                                        "Actual CPA (DO & CARE only)"
                                    ),
                                    "Value": f"€{actual_cpa:.2f}",
                                    "Source": "Marketing data",
                                    "Formula": (
                                        "Ad Spend / Conversions"
                                        " (excl. SEE & THINK)"
                                    ),
                                })

                            st.dataframe(
                                pd.DataFrame(table_data),
                                use_container_width=True,
                                hide_index=True,
                                column_config={
                                    'Metric': st.column_config.TextColumn('Metric', width='medium'),
                                    'Value': st.column_config.TextColumn('Value', width='small'),
                                    'Source': st.column_config.TextColumn('Source', width='small'),
                                    'Formula': st.column_config.TextColumn('Formula', width='large'),
                                }
                            )

                            # Show the span of the user-selected visit
                            # window (sidebar date picker), not the
                            # Created-date span — book-ahead behaviour
                            # makes the latter wider than the selection
                            # and confuses the reader. Retention gating
                            # still uses `data_span_months` internally.
                            _vw_start = st.session_state.get("bookeo_loaded_start_date")
                            _vw_end = st.session_state.get("bookeo_loaded_end_date")
                            if _vw_start is not None and _vw_end is not None:
                                _visit_window_months = (
                                    (pd.to_datetime(_vw_end) - pd.to_datetime(_vw_start)).days
                                    / 30.44
                                )
                                _span_line = f"- Date Range: {_visit_window_months:.1f} months"
                            else:
                                _span_line = ""

                            st.markdown(f"""
                            **Data Summary:**
                            - Total Bookings: {format_number(cpa_metrics['total_bookings'])}
                            - Total Turnover: {format_euro(cpa_metrics['total_revenue'])}
                            {_span_line}
                            """)

                            if cpa_metrics['retention_rate'] is not None:
                                ret_cust = cpa_metrics['returning_customers']
                                st.markdown(f"""
                                **Retention Analysis:**
                                - Cohort Size: {cpa_metrics['cohort_size']} first-time customers
                                - Returning Customers: {ret_cust} (within 2 months)
                                - Retention Rate: {cpa_metrics['retention_rate']:.1%}
                                """)

                        # Per-location comparison table
                        _stored = st.session_state.get(
                            'cpa_location_settings', {},
                        )
                        _configured_locs = [
                            loc for loc in _stored
                            if loc != "All locations"
                        ]
                        if _configured_locs:
                            with st.expander(
                                "Vergelijk CPA Targets per Locatie",
                                expanded=False,
                            ):
                                _comp_rows = []
                                for _loc_name in sorted(_configured_locs):
                                    _s = _stored[_loc_name]
                                    _loc_df = st.session_state.df1
                                    if _loc_col:
                                        _loc_df = _loc_df[
                                            _loc_df[_loc_col] == _loc_name
                                        ]
                                    if len(_loc_df) == 0:
                                        continue
                                    _loc_m = calculate_cpa_metrics(
                                        _loc_df,
                                        date_col=date_col,
                                        revenue_col=revenue_col,
                                        email_col=(
                                            email_col
                                            if email_col
                                            else 'Email address'
                                        ),
                                    )
                                    if _loc_m is None:
                                        continue
                                    _loc_bk = _s["bedrijfskosten"]
                                    _loc_wm = _s["winstmarge"]
                                    _loc_t = calculate_cpa_targets(
                                        _loc_m['aov'],
                                        _loc_bk,
                                        _loc_wm,
                                    )
                                    _comp_rows.append({
                                        "Location": _loc_name.replace(
                                            "Northern Sauna ", "",
                                        ),
                                        "AOV": f"€{_loc_m['aov']:.2f}",
                                        "Kosten %": _loc_bk,
                                        "Marge %": _loc_wm,
                                        "Ads %": 100 - _loc_bk - _loc_wm,
                                        "Break-even CPA": f"€{_loc_t['breakeven_cpa']:.2f}",
                                        "Target CPA": f"€{_loc_t['target_cpa']:.2f}",
                                    })
                                if _comp_rows:
                                    st.dataframe(
                                        pd.DataFrame(_comp_rows),
                                        use_container_width=True,
                                        hide_index=True,
                                    )

                        # --- Key Takeaways ---
                        with st.expander("Key Takeaways"):
                            _tgt = cpa_targets['target_cpa']
                            if actual_cpa is not None:
                                if actual_cpa <= _tgt:
                                    st.info(
                                        f"**Actual CPA (€{actual_cpa:.2f}) is below "
                                        f"target (€{_tgt:.2f}).** "
                                        "You have room to scale ad spend "
                                        "while maintaining profitability."
                                    )
                                else:
                                    _over = actual_cpa - _tgt
                                    st.info(
                                        f"**Actual CPA (€{actual_cpa:.2f}) is "
                                        f"€{_over:.2f} above target (€{_tgt:.2f}).** "
                                        "Review campaign targeting, reduce "
                                        "spend on underperforming campaigns, "
                                        "or improve operating-cost efficiency."
                                    )
                            st.info(
                                f"**Your ad budget is {ad_budget_pct}% of turnover "
                                f"(€{cpa_metrics['aov'] * ad_budget_pct / 100:.2f} "
                                f"per booking).** "
                                f"With {bedrijfskosten}% operating costs and "
                                f"{winstmarge}% profit margin, every booking "
                                f"above €{_tgt:.2f} CPA eats into profit."
                            )


        with tab_audience:
            st.markdown("### Audience — Age Groups")
            st.caption(
                "Age group performance across Google Ads and Meta Ads."
            )

            # Read the LOADED snapshot. Audience tabs are part of the
            # page-wide pinned contract — they reflect the last
            # successful Load, not the live date widgets.
            _aud_start_raw = st.session_state.get("bookeo_loaded_start_date")
            _aud_end_raw = st.session_state.get("bookeo_loaded_end_date")
            _aud_start = _to_date_str(_aud_start_raw) if _aud_start_raw else None
            _aud_end = _to_date_str(_aud_end_raw) if _aud_end_raw else None

            if not _aud_start or not _aud_end:
                st.info("Load bookings first to view audience data.")
            else:
                _aud_loading = st.empty()
                _aud_loading.info("Loading audience data...")

                try:
                    age_df = load_age_demographics_from_bq(
                        _aud_start, _aud_end,
                    )
                except Exception as e:
                    st.warning(f"Could not load audience data: {e}")
                    age_df = pd.DataFrame()

                _aud_loading.empty()

                if age_df.empty:
                    st.info(
                        "No age group data available for this date range. "
                        "Data is available from September 2024 onwards."
                    )
                else:
                    # Order age groups
                    _age_order = [
                        "18-24", "25-34", "35-44",
                        "45-54", "55-64", "65+",
                    ]
                    age_df["age_group"] = pd.Categorical(
                        age_df["age_group"],
                        categories=_age_order,
                        ordered=True,
                    )
                    age_df = age_df[
                        age_df["age_group"].notna()
                    ].sort_values("age_group")

                    # Platform colors (match existing)
                    _aud_colors = {
                        'Google Ads': '#4285f4',
                        'Meta Ads': '#00C4B4',
                    }

                    # --- Spend by age group chart ---
                    fig_age_spend = px.bar(
                        age_df,
                        x="age_group",
                        y="spend",
                        color="platform",
                        barmode="group",
                        color_discrete_map=_aud_colors,
                        labels={
                            "age_group": "Age Group",
                            "spend": "Spend (€)",
                            "platform": "Platform",
                        },
                    )
                    fig_age_spend.update_layout(
                        xaxis_title=None,
                        yaxis_title="Spend (€)",
                        legend_title=None,
                        margin=dict(t=10),
                    )
                    st.plotly_chart(
                        fig_age_spend, use_container_width=True,
                    )

                    # --- Metrics table ---
                    # Aggregate across platforms for the table
                    _tbl = age_df.groupby("age_group", observed=True).agg(
                        impressions=("impressions", "sum"),
                        clicks=("clicks", "sum"),
                        spend=("spend", "sum"),
                        conversions=("conversions", "sum"),
                    ).reset_index()

                    _tbl["CTR"] = (
                        _tbl["clicks"] / _tbl["impressions"] * 100
                    ).fillna(0)
                    _tbl["CPA"] = (
                        _tbl["spend"] / _tbl["conversions"]
                    ).replace([float("inf")], 0).fillna(0)

                    # Format for display
                    _tbl_display = pd.DataFrame({
                        "Age Group": _tbl["age_group"],
                        "Impressions": _tbl["impressions"].apply(
                            format_number
                        ),
                        "Clicks": _tbl["clicks"].apply(format_number),
                        "Spend": _tbl["spend"].apply(format_euro),
                        "Conversions": _tbl["conversions"].apply(
                            lambda x: format_number(int(x))
                        ),
                        "CTR": _tbl["CTR"].apply(
                            lambda x: f"{x:.2f}%".replace(".", ",")
                        ),
                        "CPA": _tbl["CPA"].apply(
                            lambda x: format_euro(x, 2)
                        ),
                    })

                    st.dataframe(
                        _tbl_display,
                        use_container_width=True,
                        hide_index=True,
                    )

                    # --- Key Takeaways ---
                    with st.expander("Key Takeaways"):
                        # Highest spend age group
                        _top_spend = _tbl.loc[
                            _tbl["spend"].idxmax()
                        ]
                        _total_aud_spend = _tbl["spend"].sum()
                        _spend_pct = (
                            _top_spend["spend"] / _total_aud_spend * 100
                            if _total_aud_spend > 0 else 0
                        )
                        st.info(
                            f"**Most budget goes to {_top_spend['age_group']}** "
                            f"({format_euro(_top_spend['spend'])}, "
                            f"{_spend_pct:.0f}% of total spend)."
                        )

                        # Best CPA (with meaningful conversions)
                        _conv_groups = _tbl[_tbl["conversions"] > 0]
                        if len(_conv_groups) > 0:
                            _best_cpa = _conv_groups.loc[
                                _conv_groups["CPA"].idxmin()
                            ]
                            _worst_cpa = _conv_groups.loc[
                                _conv_groups["CPA"].idxmax()
                            ]
                            st.info(
                                f"**Best converting: {_best_cpa['age_group']}** "
                                f"with CPA of {format_euro(_best_cpa['CPA'], 2)}. "
                                f"Worst: {_worst_cpa['age_group']} "
                                f"at {format_euro(_worst_cpa['CPA'], 2)}."
                            )

                        # Best CTR
                        _best_ctr = _tbl.loc[_tbl["CTR"].idxmax()]
                        _ctr_str = f"{_best_ctr['CTR']:.2f}".replace(".", ",")
                        st.info(
                            f"**Highest CTR: {_best_ctr['age_group']}** "
                            f"at {_ctr_str}%. "
                            "This age group is most responsive to your ads."
                        )

                # --- Device Breakdown (Cross-Channel) ---
                st.markdown("### Device Breakdown")
                st.caption(
                    "Mobile vs Desktop vs Tablet performance — Google Ads and Meta Ads compared."
                )

                try:
                    device_df = load_device_demographics_from_bq(
                        _aud_start, _aud_end,
                    )
                except Exception as e:
                    st.warning(f"Could not load device data: {e}")
                    device_df = pd.DataFrame()

                if device_df.empty:
                    st.info("No device data available for this date range.")
                else:
                    # Filter out "Other" (tiny numbers)
                    device_df = device_df[device_df["device"] != "Other"]

                    # Calculate derived metrics
                    device_df["ctr"] = (
                        device_df["clicks"]
                        / device_df["impressions"].replace(0, float("nan"))
                        * 100
                    ).fillna(0)
                    device_df["cpc"] = (
                        device_df["spend"]
                        / device_df["clicks"].replace(0, float("nan"))
                    ).fillna(0)
                    device_df["cpa"] = (
                        device_df["spend"]
                        / device_df["conversions"].replace(0, float("nan"))
                    ).fillna(0)

                    # Device order
                    _dev_order = ["Mobile", "Desktop", "Tablet"]
                    device_df["device"] = pd.Categorical(
                        device_df["device"],
                        categories=_dev_order,
                        ordered=True,
                    )
                    device_df = device_df.sort_values(["device", "platform"])

                    # Platform colors
                    _dev_plat_colors = {
                        "Google Ads": "#4285f4",
                        "Meta Ads": "#00C4B4",
                    }

                    # Grouped bar charts: Spend and CTR side by side
                    col1, col2 = st.columns(2)
                    with col1:
                        fig_dev_spend = px.bar(
                            device_df,
                            x="device",
                            y="spend",
                            color="platform",
                            barmode="group",
                            color_discrete_map=_dev_plat_colors,
                            labels={
                                "device": "",
                                "spend": "Spend (€)",
                                "platform": "Platform",
                            },
                            text=device_df["spend"].apply(
                                lambda x: f"€{x:,.0f}" if x >= 1 else ""
                            ),
                        )
                        fig_dev_spend.update_layout(
                            title="Spend by Device",
                            height=350,
                            legend_title=None,
                            margin=dict(t=40),
                        )
                        fig_dev_spend.update_traces(textposition="outside")
                        st.plotly_chart(fig_dev_spend, use_container_width=True)

                    with col2:
                        fig_dev_ctr = px.bar(
                            device_df,
                            x="device",
                            y="ctr",
                            color="platform",
                            barmode="group",
                            color_discrete_map=_dev_plat_colors,
                            labels={
                                "device": "",
                                "ctr": "CTR (%)",
                                "platform": "Platform",
                            },
                            text=device_df["ctr"].apply(
                                lambda x: f"{x:.2f}%" if x > 0 else ""
                            ),
                        )
                        fig_dev_ctr.update_layout(
                            title="CTR by Device",
                            height=350,
                            legend_title=None,
                            margin=dict(t=40),
                        )
                        fig_dev_ctr.update_traces(textposition="outside")
                        st.plotly_chart(fig_dev_ctr, use_container_width=True)

                    # Metrics table
                    _dev_display = device_df.copy()
                    _dev_display = _dev_display[
                        ["platform", "device", "spend", "impressions",
                         "clicks", "ctr", "cpc", "conversions", "cpa"]
                    ]
                    _dev_display = _dev_display.rename(columns={
                        "platform": "Platform",
                        "device": "Device",
                    })

                    _dev_fmt = format_dataframe_nl(
                        _dev_display,
                        euro_cols=["spend"],
                        int_cols=["impressions", "clicks", "conversions"],
                        pct_cols=["ctr"],
                        euro_decimal_cols=["cpc", "cpa"],
                    )
                    _dev_fmt = _dev_fmt.rename(columns={
                        "spend": "Spend",
                        "impressions": "Impressions",
                        "clicks": "Clicks",
                        "ctr": "CTR",
                        "cpc": "CPC",
                        "conversions": "Conv",
                        "cpa": "CPA",
                    })

                    st.dataframe(
                        _dev_fmt,
                        use_container_width=True,
                        hide_index=True,
                    )
                    st.caption(
                        "Note: Meta Ads conversion tracking is not available"
                        " in the device breakdown — Conv and CPA show Google Ads only."
                    )

                    # Key Takeaways
                    with st.expander("Key Takeaways"):
                        # Total spend per device
                        _dev_totals = device_df.groupby("device", observed=True).agg(
                            spend=("spend", "sum"),
                            clicks=("clicks", "sum"),
                            impressions=("impressions", "sum"),
                        ).reset_index()
                        _dev_totals["ctr"] = (
                            _dev_totals["clicks"]
                            / _dev_totals["impressions"].replace(0, float("nan"))
                            * 100
                        ).fillna(0)
                        _total_dev_spend = _dev_totals["spend"].sum()

                        _mobile_row = _dev_totals[_dev_totals["device"] == "Mobile"]
                        if len(_mobile_row) > 0:
                            _mob_pct = float(_mobile_row["spend"].iloc[0]) / _total_dev_spend * 100 if _total_dev_spend > 0 else 0
                            st.info(
                                f"**{_mob_pct:.0f}% of total spend goes to mobile devices** "
                                f"({format_euro(float(_mobile_row['spend'].iloc[0]))})."
                            )

                        # Compare CPC across platforms per device
                        _google_dev = device_df[device_df["platform"] == "Google Ads"]
                        _meta_dev = device_df[device_df["platform"] == "Meta Ads"]
                        _g_mobile = _google_dev[_google_dev["device"] == "Mobile"]
                        _m_mobile = _meta_dev[_meta_dev["device"] == "Mobile"]
                        if len(_g_mobile) > 0 and len(_m_mobile) > 0:
                            _g_mob_cpc = float(_g_mobile["cpc"].iloc[0])
                            _m_mob_cpc = float(_m_mobile["cpc"].iloc[0])
                            if _g_mob_cpc > 0 and _m_mob_cpc > 0:
                                _cheaper = "Meta Ads" if _m_mob_cpc < _g_mob_cpc else "Google Ads"
                                st.info(
                                    f"**Mobile CPC: Google {format_euro(_g_mob_cpc, 2)}"
                                    f" vs Meta {format_euro(_m_mob_cpc, 2)}.** "
                                    f"{_cheaper} is cheaper per mobile click."
                                )

                        # Google Ads desktop conversions insight
                        _g_desktop = _google_dev[_google_dev["device"] == "Desktop"]
                        _g_mob = _google_dev[_google_dev["device"] == "Mobile"]
                        if len(_g_desktop) > 0 and len(_g_mob) > 0:
                            _desk_cpa = float(_g_desktop["cpa"].iloc[0])
                            _mob_cpa = float(_g_mob["cpa"].iloc[0])
                            if _desk_cpa > 0 and _mob_cpa > 0:
                                _better_dev = "Desktop" if _desk_cpa < _mob_cpa else "Mobile"
                                st.info(
                                    f"**Google Ads CPA: Desktop {format_euro(_desk_cpa, 2)}"
                                    f" vs Mobile {format_euro(_mob_cpa, 2)}.** "
                                    f"{_better_dev} converts more efficiently."
                                )

                # --- Gender Breakdown (Cross-Channel) ---
                st.markdown("### Gender Breakdown")
                st.caption(
                    "Male vs female performance — Google Ads and Meta Ads compared."
                )

                try:
                    gender_df = load_gender_demographics_from_bq(
                        _aud_start, _aud_end,
                    )
                except Exception as e:
                    st.warning(f"Could not load gender data: {e}")
                    gender_df = pd.DataFrame()

                if gender_df.empty:
                    st.info(
                        "No gender data available for this date range."
                    )
                else:
                    # Calculate derived metrics
                    gender_df["ctr"] = (
                        gender_df["clicks"]
                        / gender_df["impressions"].replace(0, float("nan"))
                        * 100
                    ).fillna(0)
                    gender_df["cpc"] = (
                        gender_df["spend"]
                        / gender_df["clicks"].replace(0, float("nan"))
                    ).fillna(0)
                    gender_df["cpa"] = (
                        gender_df["spend"]
                        / gender_df["conversions"].replace(0, float("nan"))
                    ).fillna(0)

                    # Capitalise for display
                    gender_df["gender_label"] = gender_df["gender"].str.capitalize()
                    _gender_order = ["Male", "Female"]
                    gender_df["gender_label"] = pd.Categorical(
                        gender_df["gender_label"],
                        categories=_gender_order,
                        ordered=True,
                    )
                    gender_df = gender_df.sort_values(["gender_label", "platform"])

                    _gen_plat_colors = {
                        "Google Ads": "#4285f4",
                        "Meta Ads": "#00C4B4",
                    }

                    # Grouped bar charts: Spend and CTR side by side
                    col1, col2 = st.columns(2)
                    with col1:
                        fig_gen_spend = px.bar(
                            gender_df,
                            x="gender_label",
                            y="spend",
                            color="platform",
                            barmode="group",
                            color_discrete_map=_gen_plat_colors,
                            labels={
                                "gender_label": "",
                                "spend": "Spend (€)",
                                "platform": "Platform",
                            },
                            text=gender_df["spend"].apply(
                                lambda x: f"€{x:,.0f}" if x >= 1 else ""
                            ),
                        )
                        fig_gen_spend.update_layout(
                            title="Spend by Gender",
                            height=350,
                            legend_title=None,
                            margin=dict(t=40),
                        )
                        fig_gen_spend.update_traces(textposition="outside")
                        st.plotly_chart(fig_gen_spend, use_container_width=True)

                    with col2:
                        fig_gen_ctr = px.bar(
                            gender_df,
                            x="gender_label",
                            y="ctr",
                            color="platform",
                            barmode="group",
                            color_discrete_map=_gen_plat_colors,
                            labels={
                                "gender_label": "",
                                "ctr": "CTR (%)",
                                "platform": "Platform",
                            },
                            text=gender_df["ctr"].apply(
                                lambda x: f"{x:.2f}%" if x > 0 else ""
                            ),
                        )
                        fig_gen_ctr.update_layout(
                            title="CTR by Gender",
                            height=350,
                            legend_title=None,
                            margin=dict(t=40),
                        )
                        fig_gen_ctr.update_traces(textposition="outside")
                        st.plotly_chart(fig_gen_ctr, use_container_width=True)

                    # Metrics table
                    _gen_display = gender_df[
                        ["platform", "gender_label", "spend", "impressions",
                         "clicks", "ctr", "cpc", "conversions", "cpa"]
                    ].copy()
                    _gen_display = _gen_display.rename(columns={
                        "platform": "Platform",
                        "gender_label": "Gender",
                    })

                    _gen_fmt = format_dataframe_nl(
                        _gen_display,
                        euro_cols=["spend"],
                        int_cols=["impressions", "clicks", "conversions"],
                        pct_cols=["ctr"],
                        euro_decimal_cols=["cpc", "cpa"],
                    )
                    _gen_fmt = _gen_fmt.rename(columns={
                        "spend": "Spend",
                        "impressions": "Impressions",
                        "clicks": "Clicks",
                        "ctr": "CTR",
                        "cpc": "CPC",
                        "conversions": "Conv",
                        "cpa": "CPA",
                    })

                    st.dataframe(
                        _gen_fmt,
                        use_container_width=True,
                        hide_index=True,
                    )
                    st.caption(
                        "Note: Meta Ads conversion tracking is not available"
                        " in the gender breakdown — Conv and CPA show Google Ads only."
                    )

                    # Key Takeaways
                    with st.expander("Key Takeaways"):
                        # Overall gender split
                        _gen_totals = gender_df.groupby("gender").agg(
                            spend=("spend", "sum"),
                            clicks=("clicks", "sum"),
                            impressions=("impressions", "sum"),
                        ).reset_index()
                        _gen_totals["ctr"] = (
                            _gen_totals["clicks"]
                            / _gen_totals["impressions"].replace(0, float("nan"))
                            * 100
                        ).fillna(0)
                        _total_gen_spend = _gen_totals["spend"].sum()

                        _male_total = _gen_totals[_gen_totals["gender"] == "male"]
                        _female_total = _gen_totals[_gen_totals["gender"] == "female"]
                        if len(_male_total) > 0 and len(_female_total) > 0:
                            _m_sp = float(_male_total["spend"].iloc[0])
                            _f_sp = float(_female_total["spend"].iloc[0])
                            _m_pct = _m_sp / _total_gen_spend * 100 if _total_gen_spend > 0 else 0
                            st.info(
                                f"**{_m_pct:.0f}% of total spend goes to male audiences** "
                                f"(♂ {format_euro(_m_sp)} · ♀ {format_euro(_f_sp)})."
                            )

                        # Cross-platform gender comparison
                        _google_gen = gender_df[gender_df["platform"] == "Google Ads"]
                        _meta_gen = gender_df[gender_df["platform"] == "Meta Ads"]
                        _g_male = _google_gen[_google_gen["gender"] == "male"]
                        _g_female = _google_gen[_google_gen["gender"] == "female"]
                        _m_male = _meta_gen[_meta_gen["gender"] == "male"]
                        _m_female = _meta_gen[_meta_gen["gender"] == "female"]

                        if len(_g_male) > 0 and len(_g_female) > 0:
                            _g_m_ctr = float(_g_male["ctr"].iloc[0])
                            _g_f_ctr = float(_g_female["ctr"].iloc[0])
                            _g_better = "male" if _g_m_ctr > _g_f_ctr else "female"
                            st.info(
                                f"**Google Ads: {_g_better} has higher CTR** "
                                f"(♂ {_g_m_ctr:.2f}% vs ♀ {_g_f_ctr:.2f}%)."
                            )

                        if len(_m_male) > 0 and len(_m_female) > 0:
                            _m_m_ctr = float(_m_male["ctr"].iloc[0])
                            _m_f_ctr = float(_m_female["ctr"].iloc[0])
                            _m_better = "male" if _m_m_ctr > _m_f_ctr else "female"
                            st.info(
                                f"**Meta Ads: {_m_better} has higher CTR** "
                                f"(♂ {_m_m_ctr:.2f}% vs ♀ {_m_f_ctr:.2f}%)."
                            )

                        # Google Ads CPA by gender
                        if len(_g_male) > 0 and len(_g_female) > 0:
                            _g_m_cpa = float(_g_male["cpa"].iloc[0])
                            _g_f_cpa = float(_g_female["cpa"].iloc[0])
                            if _g_m_cpa > 0 and _g_f_cpa > 0:
                                _cheaper_gen = "Male" if _g_m_cpa < _g_f_cpa else "Female"
                                st.info(
                                    f"**Google Ads CPA: ♂ {format_euro(_g_m_cpa, 2)}"
                                    f" vs ♀ {format_euro(_g_f_cpa, 2)}.** "
                                    f"{_cheaper_gen} converts more efficiently."
                                )

                # --- Network & Placement ---
                st.markdown("### Network & Placement")
                st.caption(
                    "Google Ads networks (Search, YouTube, Display) and"
                    " Meta Ads placements (Facebook, Instagram, Reels, Stories)."
                )

                # Load both datasets
                try:
                    gads_network_df = load_google_ads_network_from_bq(
                        _aud_start, _aud_end,
                    )
                except Exception:
                    gads_network_df = pd.DataFrame()

                try:
                    placement_df = load_platform_placement_from_bq(
                        _aud_start, _aud_end,
                    )
                except Exception:
                    placement_df = pd.DataFrame()

                if gads_network_df.empty and placement_df.empty:
                    st.info("No placement data available for this date range.")
                else:
                    # --- Google Ads Networks ---
                    if not gads_network_df.empty:
                        # Filter to networks with at least 1% of total spend
                        _gn_min = gads_network_df["spend"].sum() * 0.01
                        _gn = gads_network_df[gads_network_df["spend"] >= max(_gn_min, 1)].copy()
                        _network_name_map = {
                            "SEARCH": "Search",
                            "YOUTUBE": "YouTube",
                            "CONTENT": "Display",
                            "DISCOVER": "Discover",
                            "SEARCH_PARTNERS": "Search Partners",
                            "GMAIL": "Gmail",
                        }
                        _gn["label"] = _gn["network"].map(
                            _network_name_map
                        ).fillna(_gn["network"])

                        _gn_colors = {
                            "Search": "#4285f4",
                            "YouTube": "#FF0000",
                            "Display": "#34A853",
                            "Discover": "#FBBC04",
                            "Search Partners": "#7BAAF7",
                            "Gmail": "#EA4335",
                        }

                    # --- Meta Ads Platforms ---
                    _has_meta = not placement_df.empty
                    if _has_meta:
                        _plat_agg = placement_df.groupby("publisher_platform").agg(
                            impressions=("impressions", "sum"),
                            clicks=("clicks", "sum"),
                            spend=("spend", "sum"),
                            reach=("reach", "sum"),
                        ).reset_index()
                        _plat_agg["ctr"] = (
                            _plat_agg["clicks"]
                            / _plat_agg["impressions"].replace(0, float("nan"))
                            * 100
                        ).fillna(0)
                        _plat_agg["cpc"] = (
                            _plat_agg["spend"]
                            / _plat_agg["clicks"].replace(0, float("nan"))
                        ).fillna(0)
                        _plat_agg = _plat_agg[_plat_agg["spend"] >= 1]
                        _plat_agg = _plat_agg.sort_values("spend", ascending=False)

                        _plat_name_map = {
                            "facebook": "Facebook",
                            "instagram": "Instagram",
                            "audience_network": "Audience Network",
                            "messenger": "Messenger",
                            "threads": "Threads",
                        }
                        _plat_agg["platform_label"] = _plat_agg["publisher_platform"].map(
                            _plat_name_map
                        ).fillna(_plat_agg["publisher_platform"])

                        _meta_plat_colors = {
                            "Facebook": "#1877F2",
                            "Instagram": "#E4405F",
                            "Audience Network": "#898F9C",
                            "Messenger": "#0084FF",
                            "Threads": "#000000",
                        }

                    # Side-by-side pie charts: Google networks vs Meta platforms
                    col1, col2 = st.columns(2)
                    with col1:
                        if not gads_network_df.empty and len(_gn) > 0:
                            fig_gn_pie = px.pie(
                                _gn,
                                values="spend",
                                names="label",
                                color="label",
                                color_discrete_map=_gn_colors,
                            )
                            fig_gn_pie.update_layout(
                                title="Google Ads — Spend by Network",
                                height=450,
                                showlegend=True,
                                legend=dict(orientation="h", y=-0.1),
                                margin=dict(t=40, b=40),
                            )
                            fig_gn_pie.update_traces(
                                textinfo="percent+value",
                                texttemplate="%{percent:.1%}<br>€%{value:,.0f}",
                                textposition="inside",
                            )
                            st.plotly_chart(fig_gn_pie, use_container_width=True)
                        else:
                            st.info("No Google Ads network data available.")

                    with col2:
                        if _has_meta and len(_plat_agg) > 0:
                            fig_meta_pie = px.pie(
                                _plat_agg,
                                values="spend",
                                names="platform_label",
                                color="platform_label",
                                color_discrete_map=_meta_plat_colors,
                            )
                            fig_meta_pie.update_layout(
                                title="Meta Ads — Spend by Platform",
                                height=450,
                                showlegend=True,
                                legend=dict(orientation="h", y=-0.1),
                                margin=dict(t=40, b=40),
                            )
                            fig_meta_pie.update_traces(
                                textinfo="percent+value",
                                texttemplate="%{percent:.1%}<br>€%{value:,.0f}",
                                textposition="inside",
                            )
                            st.plotly_chart(fig_meta_pie, use_container_width=True)
                        else:
                            st.info("No Meta Ads platform data available.")

                    # Google Ads network table
                    if not gads_network_df.empty and len(_gn) > 0:
                        with st.expander("Google Ads Network Details"):
                            # Network summary table
                            st.markdown("**Network Summary**")
                            _gn_display = _gn[
                                ["label", "spend", "impressions", "clicks",
                                 "ctr", "cpc", "conversions", "cpa"]
                            ].copy()
                            _gn_fmt = format_dataframe_nl(
                                _gn_display,
                                euro_cols=["spend"],
                                int_cols=["impressions", "clicks", "conversions"],
                                pct_cols=["ctr"],
                                euro_decimal_cols=["cpc", "cpa"],
                            )
                            _gn_fmt = _gn_fmt.rename(columns={
                                "label": "Network",
                                "spend": "Spend",
                                "impressions": "Impressions",
                                "clicks": "Clicks",
                                "ctr": "CTR",
                                "cpc": "CPC",
                                "conversions": "Conv",
                                "cpa": "CPA",
                            })
                            st.dataframe(
                                _gn_fmt,
                                use_container_width=True,
                                hide_index=True,
                            )

                            # Search ad position breakdown
                            try:
                                _pos_df = load_google_ads_search_position_from_bq(
                                    _aud_start, _aud_end,
                                )
                            except Exception:
                                _pos_df = pd.DataFrame()

                            if not _pos_df.empty:
                                st.markdown("**Search Ad Position**")
                                _slot_map = {
                                    "SEARCH_TOP": "Top of page",
                                    "SEARCH_OTHER": "Other positions",
                                }
                                _pos_df["label"] = _pos_df["slot"].map(
                                    _slot_map
                                ).fillna(_pos_df["slot"])
                                _pos_df["cpc"] = (
                                    _pos_df["spend"]
                                    / _pos_df["clicks"].replace(0, float("nan"))
                                ).fillna(0)

                                _pos_fmt = format_dataframe_nl(
                                    _pos_df[["label", "spend", "impressions", "clicks",
                                             "ctr", "cpc", "conversions", "cpa"]].copy(),
                                    euro_cols=["spend"],
                                    int_cols=["impressions", "clicks", "conversions"],
                                    pct_cols=["ctr"],
                                    euro_decimal_cols=["cpc", "cpa"],
                                )
                                _pos_fmt = _pos_fmt.rename(columns={
                                    "label": "Position",
                                    "spend": "Spend",
                                    "impressions": "Impressions",
                                    "clicks": "Clicks",
                                    "ctr": "CTR",
                                    "cpc": "CPC",
                                    "conversions": "Conv",
                                    "cpa": "CPA",
                                })
                                st.dataframe(
                                    _pos_fmt,
                                    use_container_width=True,
                                    hide_index=True,
                                )

                            # Campaign × Network breakdown
                            try:
                                _cn_df = load_google_ads_campaign_network_from_bq(
                                    _aud_start, _aud_end,
                                )
                            except Exception:
                                _cn_df = pd.DataFrame()

                            if not _cn_df.empty:
                                st.markdown("**Campaigns by Network**")
                                _network_label_map = {
                                    "SEARCH": "Search",
                                    "YOUTUBE": "YouTube",
                                    "CONTENT": "Display",
                                    "DISCOVER": "Discover",
                                    "SEARCH_PARTNERS": "Search Partners",
                                    "GMAIL": "Gmail",
                                }
                                _cn_df["network_label"] = _cn_df["network"].map(
                                    _network_label_map
                                ).fillna(_cn_df["network"])
                                _cn_df["cpc"] = (
                                    _cn_df["spend"]
                                    / _cn_df["clicks"].replace(0, float("nan"))
                                ).fillna(0)

                                _cn_fmt = format_dataframe_nl(
                                    _cn_df[["campaign_name", "network_label", "spend",
                                            "impressions", "clicks", "ctr", "cpc",
                                            "conversions", "cpa"]].copy(),
                                    euro_cols=["spend"],
                                    int_cols=["impressions", "clicks", "conversions"],
                                    pct_cols=["ctr"],
                                    euro_decimal_cols=["cpc", "cpa"],
                                )
                                _cn_fmt = _cn_fmt.rename(columns={
                                    "campaign_name": "Campaign",
                                    "network_label": "Network",
                                    "spend": "Spend",
                                    "impressions": "Impressions",
                                    "clicks": "Clicks",
                                    "ctr": "CTR",
                                    "cpc": "CPC",
                                    "conversions": "Conv",
                                    "cpa": "CPA",
                                })
                                st.dataframe(
                                    _cn_fmt,
                                    use_container_width=True,
                                    hide_index=True,
                                    height=(min(len(_cn_fmt), 15) + 1) * 35 + 3,
                                )

                    # Meta placements bar chart + details
                    if _has_meta:
                        _placement_agg = placement_df.groupby("platform_position").agg(
                            spend=("spend", "sum"),
                            clicks=("clicks", "sum"),
                            impressions=("impressions", "sum"),
                        ).reset_index()
                        _placement_agg["ctr"] = (
                            _placement_agg["clicks"]
                            / _placement_agg["impressions"].replace(0, float("nan"))
                            * 100
                        ).fillna(0)
                        _placement_agg = _placement_agg.sort_values(
                            "spend", ascending=True,
                        )
                        _placement_top = _placement_agg.tail(10).copy()

                        _pos_name_map = {
                            "feed": "Feed",
                            "facebook_reels": "FB Reels",
                            "instagram_stories": "IG Stories",
                            "instagram_reels": "IG Reels",
                            "marketplace": "Marketplace",
                            "facebook_reels_overlay": "FB Reels Overlay",
                            "video_feeds": "Video Feeds",
                            "facebook_stories": "FB Stories",
                            "instream_video": "In-stream Video",
                            "an_classic": "Audience Network",
                            "right_hand_column": "Right Column",
                            "facebook_profile_feed": "Profile Feed",
                            "search": "Search",
                            "instagram_explore_grid_home": "IG Explore",
                            "rewarded_video": "Rewarded Video",
                        }
                        _placement_top["label"] = _placement_top["platform_position"].map(
                            _pos_name_map
                        ).fillna(_placement_top["platform_position"])

                        fig_placement = px.bar(
                            _placement_top,
                            x="spend",
                            y="label",
                            orientation="h",
                            color="spend",
                            color_continuous_scale=["#c6efce", "#006100"],
                            labels={"spend": "Spend (€)", "label": ""},
                            text=_placement_top["spend"].apply(
                                lambda x: f"€{x:,.0f}"
                            ),
                        )
                        fig_placement.update_layout(
                            title="Meta Ads — Top Placements by Spend",
                            height=350,
                            showlegend=False,
                            coloraxis_showscale=False,
                            margin=dict(l=10),
                        )
                        fig_placement.update_traces(
                            textposition="outside",
                        )
                        st.plotly_chart(fig_placement, use_container_width=True)

                        with st.expander("Meta Placement Details"):
                            _plc_display = _placement_agg.sort_values(
                                "spend", ascending=False,
                            ).copy()
                            _plc_display["cpc"] = (
                                _plc_display["spend"]
                                / _plc_display["clicks"].replace(0, float("nan"))
                            ).fillna(0)
                            _plc_display = _plc_display[_plc_display["spend"] >= 1]

                            _plc_display["label"] = _plc_display["platform_position"].map(
                                _pos_name_map
                            ).fillna(_plc_display["platform_position"])

                            _plc_fmt = pd.DataFrame({
                                "Placement": _plc_display["label"],
                                "Spend": _plc_display["spend"].apply(format_euro),
                                "Impressions": _plc_display["impressions"].apply(format_number),
                                "Clicks": _plc_display["clicks"].apply(format_number),
                                "CTR": _plc_display["ctr"].apply(
                                    lambda x: f"{x:.2f}%".replace(".", ",")
                                ),
                                "CPC": _plc_display["cpc"].apply(
                                    lambda x: format_euro(x, 2)
                                ),
                            })
                            st.dataframe(
                                _plc_fmt,
                                use_container_width=True,
                                hide_index=True,
                            )

                    # Key Takeaways
                    with st.expander("Key Takeaways"):
                        _has_gn = not gads_network_df.empty and len(_gn) > 0

                        # 1. Conversions: Google Search vs everything else
                        if _has_gn:
                            _search = _gn[_gn["network"] == "SEARCH"]
                            _non_search = _gn[_gn["network"] != "SEARCH"]
                            if len(_search) > 0:
                                _s_conv = float(_search["conversions"].iloc[0])
                                _s_cpa = float(_search["cpa"].iloc[0])
                                _ns_conv = _non_search["conversions"].sum()
                                _s_pct = (
                                    _s_conv / (_s_conv + _ns_conv) * 100
                                ) if (_s_conv + _ns_conv) > 0 else 0
                                st.info(
                                    f"**Google Search drives {_s_pct:.0f}% of all Google"
                                    f" conversions** at {format_euro(_s_cpa, 2)} CPA."
                                    " YouTube and Display are awareness channels"
                                    " with near-zero direct conversions."
                                )

                        # 2. Cross-platform CPC: Meta clicks are much cheaper
                        if _has_gn and _has_meta and len(_plat_agg) > 0:
                            _fb = _plat_agg[_plat_agg["publisher_platform"] == "facebook"]
                            _ig = _plat_agg[_plat_agg["publisher_platform"] == "instagram"]
                            _fb_cpc = float(_fb["cpc"].iloc[0]) if len(_fb) > 0 else 0
                            if len(_search) > 0 and _fb_cpc > 0:
                                _s_cpc = float(_search["spend"].iloc[0]) / float(_search["clicks"].iloc[0]) if float(_search["clicks"].iloc[0]) > 0 else 0
                                if _s_cpc > 0:
                                    _ratio = _s_cpc / _fb_cpc
                                    st.info(
                                        f"**Google Search CPC ({format_euro(_s_cpc, 2)})"
                                        f" is {_ratio:.0f}x more expensive than"
                                        f" Facebook ({format_euro(_fb_cpc, 2)}).** "
                                        "Meta delivers volume, Google Search delivers intent."
                                    )

                        # 3. Facebook vs Instagram efficiency
                        if _has_meta and len(_plat_agg) > 0:
                            _fb = _plat_agg[_plat_agg["publisher_platform"] == "facebook"]
                            _ig = _plat_agg[_plat_agg["publisher_platform"] == "instagram"]
                            _fb_cpc = float(_fb["cpc"].iloc[0]) if len(_fb) > 0 else 0
                            _ig_cpc = float(_ig["cpc"].iloc[0]) if len(_ig) > 0 else 0
                            _fb_ctr = float(_fb["ctr"].iloc[0]) if len(_fb) > 0 else 0
                            _ig_ctr = float(_ig["ctr"].iloc[0]) if len(_ig) > 0 else 0
                            if _fb_cpc > 0 and _ig_cpc > 0:
                                _ig_premium = (_ig_cpc / _fb_cpc - 1) * 100
                                st.info(
                                    f"**Facebook outperforms Instagram on efficiency:**"
                                    f" CTR {_fb_ctr:.2f}% vs {_ig_ctr:.2f}%,"
                                    f" CPC {format_euro(_fb_cpc, 2)} vs"
                                    f" {format_euro(_ig_cpc, 2)}"
                                    f" (Instagram is {_ig_premium:.0f}% more expensive per click)."
                                )

                        # 4. YouTube awareness value
                        if _has_gn:
                            _yt = _gn[_gn["network"] == "YOUTUBE"]
                            if len(_yt) > 0:
                                _yt_impr = int(_yt["impressions"].iloc[0])
                                _yt_spend = float(_yt["spend"].iloc[0])
                                _yt_cpm = _yt_spend / _yt_impr * 1000 if _yt_impr > 0 else 0
                                _gn_total = _gn["spend"].sum()
                                _yt_pct = _yt_spend / _gn_total * 100 if _gn_total > 0 else 0
                                st.info(
                                    f"**YouTube: {format_number(_yt_impr)} impressions"
                                    f" for {format_euro(_yt_spend)}**"
                                    f" ({_yt_pct:.0f}% of Google budget,"
                                    f" CPM {format_euro(_yt_cpm, 2)})."
                                    " Low conversion but strong brand visibility."
                                )

                        # 5. Search ad position
                        if _has_gn:
                            try:
                                _tk_pos = load_google_ads_search_position_from_bq(
                                    _aud_start, _aud_end,
                                )
                            except Exception:
                                _tk_pos = pd.DataFrame()
                            if not _tk_pos.empty:
                                _top_pos = _tk_pos[_tk_pos["slot"] == "SEARCH_TOP"]
                                _other_pos = _tk_pos[_tk_pos["slot"] == "SEARCH_OTHER"]
                                if len(_top_pos) > 0 and len(_other_pos) > 0:
                                    _tp_ctr = float(_top_pos["ctr"].iloc[0])
                                    _op_ctr = float(_other_pos["ctr"].iloc[0])
                                    _tp_cpa = float(_top_pos["cpa"].iloc[0])
                                    _op_cpa = float(_other_pos["cpa"].iloc[0])
                                    _tp_spend_pct = (
                                        float(_top_pos["spend"].iloc[0])
                                        / (_tk_pos["spend"].sum()) * 100
                                    ) if _tk_pos["spend"].sum() > 0 else 0
                                    st.info(
                                        f"**Top-of-page search ads: {_tp_ctr:.0f}% CTR"
                                        f" vs {_op_ctr:.0f}% for other positions.** "
                                        f"Top ads get {_tp_spend_pct:.0f}% of Search spend"
                                        f" with {format_euro(_tp_cpa, 2)} CPA"
                                        f" (other: {format_euro(_op_cpa, 2)})."
                                    )

                        # 6. Top Meta placement
                        if _has_meta and len(_placement_agg) > 0:
                            _top_plc = _placement_agg.iloc[-1]
                            _top_plc_name = _pos_name_map.get(
                                _top_plc["platform_position"],
                                _top_plc["platform_position"],
                            )
                            _plc_total = _placement_agg["spend"].sum()
                            _top_plc_pct = (
                                _top_plc["spend"] / _plc_total * 100
                            ) if _plc_total > 0 else 0
                            # Find Reels combined spend
                            _reels = _placement_agg[
                                _placement_agg["platform_position"].str.contains(
                                    "reels", case=False, na=False,
                                )
                            ]
                            _reels_spend = _reels["spend"].sum()
                            _reels_pct = _reels_spend / _plc_total * 100 if _plc_total > 0 else 0
                            st.info(
                                f"**Feed dominates Meta placements"
                                f" ({_top_plc_pct:.0f}% of spend).** "
                                f"Reels (FB + IG combined) accounts for"
                                f" {_reels_pct:.0f}%"
                                f" ({format_euro(_reels_spend)})."
                            )




render_footer()
