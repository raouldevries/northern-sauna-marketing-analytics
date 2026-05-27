"""BigQuery client, constants, and utility functions."""

import os

from google.cloud import bigquery
from google.oauth2 import service_account

import streamlit as st

# ---------------------------------------------------------------------------
# Constants: BigQuery
# ---------------------------------------------------------------------------

# Demo-mode flag: when true, the BigQuery client factories below short-circuit
# to None and downstream callers never touch st.secrets["gcp_service_account"].
DEMO_MODE = os.environ.get("DEMO_MODE", "").lower() == "true"

# Env-driven so the same code runs against a real BigQuery project locally and
# against placeholders in the public demo (DEMO_MODE never reaches the client).
PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "demo-project")
GA4_PROPERTY_ID = os.environ.get("GA4_PROPERTY_ID", "000000000")
DATASET = os.environ.get("BQ_DATASET", "demo_data")
BOOKINGS_TABLE = f"{PROJECT_ID}.{DATASET}.bookings"
# Row-level enrichment view (Step 1.1 of plans/member-metric-parity-plan.md).
# Source of truth for `Member` and `Membership end` — page reads from here so
# the chatbot and the page share one definition of "member".
BOOKINGS_MEMBER_VIEW = f"{PROJECT_ID}.{DATASET}.v_bookings_member_enriched"

# Per-query byte cap. Caps damage from runaway scans or leaked credentials.
# Typical dashboard queries are MB–single-GB; 10 GB leaves ~2x headroom over a
# 90-day GA4 events scan while still failing fast on full-history scans.
MAX_BYTES_BILLED = 10 * 1024**3  # 10 GB

# ---------------------------------------------------------------------------
# Constants: Location name mapping (BQ canonical -> Streamlit expected)
# ---------------------------------------------------------------------------

_BQ_TO_STREAMLIT_LOCATION = {
    "Northern Sauna Södermalm": "Northern Sauna Stockholm Södermalm",
    "Northern Sauna Östermalm": "Northern Sauna Stockholm Östermalm",
    "Northern Sauna Stockholm Waterfront": "Northern Sauna Stockholm Waterfront",
    "Northern Sauna Kamppi": "Northern Sauna Helsinki Kamppi",
    "Northern Sauna Grünerløkka": "Northern Sauna Oslo Grünerløkka",
    "Northern Sauna Frogner": "Northern Sauna Oslo Frogner",
    "Northern Sauna Oslo Grünerløkka": "Northern Sauna Oslo Grünerløkka",
    "Northern Sauna Oslo Frogner": "Northern Sauna Oslo Frogner",
    "Northern Sauna Helsinki Kamppi": "Northern Sauna Helsinki Kamppi",
    "Northern Sauna Kallio": "Northern Sauna Helsinki Kallio",
    "Northern Sauna Helsinki Kallio": "Northern Sauna Helsinki Kallio",
}

# ---------------------------------------------------------------------------
# Constants: Status mapping (BQ -> Streamlit)
# ---------------------------------------------------------------------------

_BQ_TO_STREAMLIT_STATUS = {
    "confirmed": "normal",
    "completed": "normal",
    "canceled": "canceled",
    "no_show": "no show",
}

# ---------------------------------------------------------------------------
# Constants: Account mapping (BQ source_account -> Streamlit Account name)
# ---------------------------------------------------------------------------

_BQ_TO_STREAMLIT_ACCOUNT = {
    "stockholm": "Northern Sauna Stockholm",
    "helsinki": "Northern Sauna Helsinki",
    "oslo": "Northern Sauna Oslo",
}

# ---------------------------------------------------------------------------
# BigQuery client
# ---------------------------------------------------------------------------


def _to_date_str(d) -> str:
    """Convert date/datetime to ISO string."""
    if hasattr(d, "strftime"):
        return d.strftime("%Y-%m-%d")
    return str(d)


@st.cache_resource
def _get_bq_client() -> bigquery.Client | None:
    """Create a BigQuery client using Streamlit secrets.

    Returns None in demo mode. DEMO_MODE is read once at import time, so the
    cache holds the same value (real client or None) for the session.
    """
    if DEMO_MODE:
        return None
    creds_info = st.secrets["gcp_service_account"]
    credentials = service_account.Credentials.from_service_account_info(
        dict(creds_info),
        scopes=["https://www.googleapis.com/auth/bigquery"],
    )
    client = bigquery.Client(project=PROJECT_ID, credentials=credentials)
    _enforce_byte_limit(client)
    return client


def _enforce_byte_limit(client: bigquery.Client) -> None:
    """Wrap client.query() so every job inherits MAX_BYTES_BILLED unless
    the caller explicitly sets its own value."""
    original_query = client.query

    def query_with_limit(query, job_config=None, **kwargs):
        if job_config is None:
            job_config = bigquery.QueryJobConfig()
        if job_config.maximum_bytes_billed is None:
            job_config.maximum_bytes_billed = MAX_BYTES_BILLED
        return original_query(query, job_config=job_config, **kwargs)

    client.query = query_with_limit


def get_bq_client() -> bigquery.Client | None:
    """Public BigQuery client for pages that need custom queries.

    Returns None in demo mode (see _get_bq_client).
    """
    if DEMO_MODE:
        return None
    return _get_bq_client()


def estimate_loading_time(days: int, num_accounts: int = 3) -> str:
    """Stub — BigQuery returns in seconds, no estimate needed."""
    return ""
