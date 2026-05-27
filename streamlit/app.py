import hmac
import logging
import os
from datetime import datetime, timedelta

# Read DEMO_MODE before any other import so downstream modules
# (bq_data_loader, data.*) can short-circuit their own secret access.
DEMO_MODE = os.environ.get("DEMO_MODE", "").lower() == "true"

from bq_data_loader import (  # noqa: E402
    init_session_state,
    load_bookeo_data,
)

import streamlit as st  # noqa: E402

logger = logging.getLogger(__name__)

# BigQuery availability gate — short-circuit on DEMO_MODE so we never touch
# st.secrets when no secrets.toml is configured (the Streamlit Cloud demo).
BQ_AVAILABLE = (not DEMO_MODE) and ("gcp_service_account" in st.secrets)

# Page configuration
st.set_page_config(
    page_title="Northern Sauna Analytics",
    page_icon="🔥",
    layout="wide"
)

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

# Initialize session state using centralized function
init_session_state()

# Initialize authentication state
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False

# In demo mode, mark the session authenticated up front so the unauthenticated
# login branch (which ends in st.stop()) is never entered.
if DEMO_MODE:
    st.session_state.authenticated = True

# Show error if BigQuery credentials are missing (live mode only).
if not DEMO_MODE and not BQ_AVAILABLE:
    st.error(
        "BigQuery credentials not configured. "
        "Add `gcp_service_account` to `.streamlit/secrets.toml`."
    )
    st.stop()

# Fail hard if APP_PASSWORD is not configured or misconfigured (live mode only).
if not DEMO_MODE:
    app_password = st.secrets.get("APP_PASSWORD")
    if not app_password or not isinstance(app_password, str):
        st.error("Application not configured. Contact administrator.")
        st.stop()
else:
    app_password = ""  # placeholder; the auth branch that compares it is skipped


# Persistent cache for preloaded data (survives Streamlit reruns)
@st.cache_resource
def get_preload_cache():
    """Return a persistent dictionary for storing preloaded data."""
    return {'complete': False, 'loading': False, 'status': ''}

# Background data preloading function
def preload_bookeo_data_background():
    """Load Bookeo data in background thread and store results."""
    import threading

    cache = get_preload_cache()
    if cache.get('loading') or cache.get('complete'):
        return  # Already loading or loaded

    cache['loading'] = True
    cache['status'] = 'Connecting to BigQuery...'

    def _load():
        try:
            preload_start = datetime(2025, 9, 1)
            preload_end = datetime.now() - timedelta(days=1)

            cache['status'] = 'Fetching booking data from BigQuery...'

            df1, df2, errors = load_bookeo_data(
                start_date=preload_start,
                end_date=preload_end,
                include_canceled=True,
                progress_callback=None
            )

            cache['status'] = 'Processing booking data...'

            # Store results in the persistent cache
            if df1 is not None and len(df1) > 0:
                cache['df1'] = df1
                cache['df2'] = df2
                cache['start_date'] = preload_start
                cache['end_date'] = preload_end
                cache['timestamp'] = datetime.now()

            cache['complete'] = True
            cache['loading'] = False
            cache['status'] = ''
        except Exception as e:
            cache['complete'] = True
            cache['loading'] = False
            cache['status'] = ''
            cache['error'] = str(e)

    thread = threading.Thread(target=_load, daemon=True)
    thread.start()

# Password protection - Show login page if not authenticated
if not st.session_state.authenticated:
    # Hide sidebar on login page and style login button
    st.markdown("""
    <style>
    [data-testid="stSidebar"] { display: none; }
    /* Hide form border on login page */
    [data-testid="stForm"] {
        border: none !important;
        padding: 0 !important;
    }
    button[kind="primary"] {
        background-color: #3C3C3C !important;
        color: #fff !important;
        border: none !important;
    }
    button[kind="primary"]:hover {
        background-color: #2a2a2a !important;
    }
    /* Prevent text input focus style change */
    [data-testid="stTextInput"] input:focus {
        border-color: inherit !important;
        box-shadow: none !important;
    }
    [data-testid="stTextInput"] div[data-baseweb="input"]:focus-within {
        border-color: #e5e5e5 !important;
        box-shadow: none !important;
    }
    </style>
    """, unsafe_allow_html=True)

    # Start background preloading of BigQuery data (last 90 days)
    if BQ_AVAILABLE:
        st.session_state.bookeo_start_date = datetime(2025, 9, 1)
        st.session_state.bookeo_end_date = datetime.now() - timedelta(days=1)
        preload_bookeo_data_background()  # Function handles duplicate calls internally

    # Centered login container
    col1, col2, col3 = st.columns([1, 1.5, 1])
    with col2:
        st.markdown("<div style='height: 80px'></div>", unsafe_allow_html=True)

        st.markdown(
            "<h2 style='text-align: center; margin-bottom: 0.5rem;'>"
            "Northern Sauna Analytics</h2>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "<p style='text-align: center; color: #666; margin-bottom: 2rem;'>"
            "Bookings, customers & growth insights</p>",
            unsafe_allow_html=True,
        )

        # Password form — Enter key submits
        with st.form("login_form"):
            password = st.text_input("Enter password", type="password", key="login_password")
            submitted = st.form_submit_button("Login", use_container_width=True, type="primary")

        if submitted:
            if hmac.compare_digest(password.encode("utf-8"), app_password.encode("utf-8")):
                st.session_state.authenticated = True

                # Check if Bookeo data was preloaded in background
                preload_cache = get_preload_cache()
                if BQ_AVAILABLE and preload_cache.get('complete') and 'df1' in preload_cache:
                    st.session_state.df1 = preload_cache['df1']
                    st.session_state.df2 = preload_cache['df2']
                    st.session_state.bookeo_start_date = preload_cache['start_date']
                    st.session_state.bookeo_end_date = preload_cache['end_date']
                    st.session_state.bookeo_loaded = True
                    # Snapshot the loaded range + canceled-policy on the
                    # preload fast-path. Without this, pages following
                    # the page-pinned-to-Load contract (Marketing) would
                    # see `bookeo_loaded=True` but None snapshots and
                    # block on "Load bookings first" until the user
                    # presses Load manually. The preload thread always
                    # runs with `include_canceled=True` (see
                    # `preload_bookeo_data_background`).
                    st.session_state.bookeo_loaded_start_date = preload_cache['start_date']
                    st.session_state.bookeo_loaded_end_date = preload_cache['end_date']
                    st.session_state.bookeo_loaded_include_canceled = True
                    st.session_state.bookeo_last_refresh = preload_cache['timestamp']
                    st.session_state.drive_loaded = True
                    st.session_state.data_source = 'bigquery'

                st.switch_page("pages/1_overview.py")
            else:
                logger.warning("Failed login attempt")
                st.error("Incorrect password. Please try again.")

    st.stop()

# ============ AUTHENTICATED CONTENT BELOW ============
# Auto-redirect to Overview page — app.py is just the entry point (auth + data loading)
st.switch_page("pages/1_overview.py")
