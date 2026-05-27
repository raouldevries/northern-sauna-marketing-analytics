from __future__ import annotations

import base64
from pathlib import Path

import streamlit as st

_LOGO_SVG_RAW = (Path(__file__).parent / "assets" / "logo_black.svg").read_bytes()
LOGO_B64 = base64.b64encode(_LOGO_SVG_RAW).decode()

# ---------------------------------------------------------------------------
# Sidebar navigation
# ---------------------------------------------------------------------------

_SIDEBAR_NAV_CSS = """
<style>
/* Stronger active state: darker bg + bold text + left accent */
a[data-testid="stPageLink-NavLink"][aria-current="page"] {
    background-color: rgba(26, 26, 46, 0.10) !important;
    font-weight: 600 !important;
    border-left: 3px solid #1a1a2e !important;
    border-radius: 0 8px 8px 0 !important;
}
a[data-testid="stPageLink-NavLink"][aria-current="page"] p,
a[data-testid="stPageLink-NavLink"][aria-current="page"] span,
a[data-testid="stPageLink-NavLink"][aria-current="page"] * {
    font-weight: 600 !important;
}

/* Gray hover instead of yellow-green */
a[data-testid="stPageLink-NavLink"]:hover {
    background-color: rgba(26, 26, 46, 0.04) !important;
}

/* Bump icon opacity and size */
[data-testid="stSidebar"] [data-testid="stIconMaterial"] {
    color: rgba(26, 26, 46, 0.85) !important;
    font-size: 1.3rem !important;
}

/* Spacer between nav groups */
.sidebar-group-spacer {
    height: 6px;
}

/* Vertically center icon and text within nav links */
a[data-testid="stPageLink-NavLink"] {
    display: flex !important;
    align-items: center !important;
    padding: 0.4rem 0.65rem !important;
}

/* Center nav items: fixed width block, centered in sidebar */
[data-testid="stSidebar"] [data-testid="stPageLink"] {
    width: 85% !important;
    margin: 0 auto !important;
}

/* Larger nav text */
a[data-testid="stPageLink-NavLink"] p {
    font-size: 1.12rem !important;
}
</style>
"""


def render_sidebar_nav(feedback_page: str = "", feedback_tabs: list[str] | None = None) -> None:
    """Render the shared sidebar navigation with grouped links."""
    with st.sidebar:
        st.markdown(_SIDEBAR_NAV_CSS, unsafe_allow_html=True)

        st.page_link("pages/1_overview.py", label="Overview", icon=":material/home:")

        st.markdown('<div class="sidebar-group-spacer"></div>', unsafe_allow_html=True)
        st.page_link("pages/2_turnover.py", label="Turnover", icon=":material/payments:")
        st.page_link("pages/10_bookings.py", label="Bookings", icon=":material/bar_chart:")

        st.markdown('<div class="sidebar-group-spacer"></div>', unsafe_allow_html=True)
        st.page_link("pages/3_customers.py", label="Customers", icon=":material/group:")
        st.page_link("pages/4_members.py", label="Members", icon=":material/card_membership:")

        st.markdown('<div class="sidebar-group-spacer"></div>', unsafe_allow_html=True)
        st.page_link("pages/5_capacity.py", label="Capacity", icon=":material/analytics:")
        st.page_link("pages/6_promotions.py", label="Promotions", icon=":material/sell:")

        st.markdown('<div class="sidebar-group-spacer"></div>', unsafe_allow_html=True)
        st.page_link("pages/7_marketing.py", label="Marketing", icon=":material/campaign:")
        st.page_link("pages/11_organic_seo.py", label="Organic & SEO", icon=":material/travel_explore:")
        st.page_link("pages/8_reviews.py", label="Reviews", icon=":material/reviews:")

        st.markdown('<div class="sidebar-group-spacer"></div>', unsafe_allow_html=True)
        st.page_link("pages/12_ai_assistant.py", label="Northern Sauna AI", icon=":material/auto_awesome:")

        # Feedback
        if feedback_page:
            from data.feedback import render_feedback
            render_feedback(feedback_page, feedback_tabs)

        # Logout
        st.markdown('<div class="sidebar-group-spacer"></div>', unsafe_allow_html=True)
        if st.button("Logout", icon=":material/logout:", use_container_width=True):
            st.session_state.authenticated = False
            st.switch_page("app.py")

    # Dialog must be triggered outside sidebar context
    if feedback_page:
        from data.feedback import _check_feedback_dialog
        _check_feedback_dialog()


def render_header(subtitle: str | None = None) -> None:
    """Render the app header with inline SVG logo and title."""
    subtitle_html = ""
    if subtitle:
        subtitle_html = (
            f'<span class="ns-header__subtitle">{subtitle}</span>'
        )

    st.markdown(
        "<style>"
        ".ns-header{display:flex;align-items:center;gap:14px;padding:0 0 1.5rem 0;margin-top:-1.3rem}"
        ".ns-header__logo{flex-shrink:0;height:44px;width:44px}"
        ".ns-header__logo img{height:100%;width:100%}"
        ".ns-header__text{display:flex;flex-direction:column;gap:2px}"
        ".ns-header__title{font-size:1.75rem;font-weight:700;color:#1a1a2e;"
        "line-height:1.2;margin:0;font-family:-apple-system,BlinkMacSystemFont,"
        '"Segoe UI",Roboto,Helvetica,Arial,sans-serif}'
        ".ns-header__subtitle{font-size:0.85rem;color:#888;line-height:1.3;margin:0}"
        "\n"
        "/* Global spacing: consistent top/bottom breathing room */\n"
        "[data-testid='stPlotlyChart'] { margin: 1rem 0; }\n"
        "[data-testid='stDataFrame'],\n"
        "[data-testid='stDataFrameResizable'] { margin: 1rem 0; }\n"
        "[data-testid='stMetricValue'] { margin-bottom: 0.15rem; }\n"
        "[data-testid='stMainBlockContainer'] h3 { margin: 1rem 0 1rem 0; }\n"
        "[data-testid='stExpander'] { margin: 0.75rem 0; }\n"
        "[data-testid='stHorizontalBlock']:has([data-testid='stMetric']) { margin-bottom: 0.75rem; }\n"
        "</style>"
        '<div class="ns-header">'
        '<div class="ns-header__logo">'
        f'<img src="data:image/svg+xml;base64,{LOGO_B64}" alt="Northern Sauna logo">'
        "</div>"
        '<div class="ns-header__text">'
        '<span class="ns-header__title">Northern Sauna Analytics</span>'
        f"{subtitle_html}"
        "</div>"
        "</div>"
        "<hr style='margin:0 0 2rem 0;border:none;border-top:1px solid #e0e0e0'>",
        unsafe_allow_html=True,
    )
