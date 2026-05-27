"""Feedback storage and retrieval — BigQuery backed."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

import pandas as pd
from google.cloud import bigquery

import streamlit as st
from data.bq_client import DATASET, DEMO_MODE, PROJECT_ID, _get_bq_client

FEEDBACK_TABLE = f"{PROJECT_ID}.{DATASET}.feedback"

_FEEDBACK_COLUMNS = ("page", "tab", "user_name", "comment", "created_at")


def insert_feedback(
    page: str, tab: str, comment: str, user_name: str,
) -> None:
    """Insert a feedback entry into BigQuery via streaming insert.

    In demo mode this is a silent no-op — the demo never reaches BigQuery.
    """
    if DEMO_MODE:
        return
    client = _get_bq_client()
    rows = [{
        "id": str(uuid.uuid4()),
        "page": page,
        "tab": tab or "",
        "comment": comment,
        "user_name": user_name or "",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }]
    errors = client.insert_rows_json(FEEDBACK_TABLE, rows)
    if errors:
        raise RuntimeError(f"BigQuery insert errors: {errors}")


@st.cache_data(ttl=60, show_spinner=False)
def get_feedback(page: str, tab: str = "") -> pd.DataFrame:
    """Return the last 5 feedback entries for a specific page+tab.

    Returns an empty DataFrame in demo mode.
    """
    if DEMO_MODE:
        return pd.DataFrame(columns=["user_name", "comment", "created_at"])
    client = _get_bq_client()
    query = f"""
    SELECT user_name, comment, created_at
    FROM `{FEEDBACK_TABLE}`
    WHERE page = @page AND tab = @tab
    ORDER BY created_at DESC
    LIMIT 5
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("page", "STRING", page),
            bigquery.ScalarQueryParameter("tab", "STRING", tab or ""),
        ],
    )
    return client.query(query, job_config=job_config).to_dataframe()


@st.cache_data(ttl=60, show_spinner=False)
def get_all_feedback() -> pd.DataFrame:
    """Return all feedback entries, newest first.

    Returns an empty DataFrame in demo mode (preserves the column shape so
    `pages/1_overview.py` can iterate without conditional logic).
    """
    if DEMO_MODE:
        return pd.DataFrame(columns=list(_FEEDBACK_COLUMNS))
    client = _get_bq_client()
    query = f"""
    SELECT page, tab, user_name, comment, created_at
    FROM `{FEEDBACK_TABLE}`
    ORDER BY created_at DESC
    """
    return client.query(query).to_dataframe()



@st.dialog("Leave feedback")
def _feedback_dialog(page: str, tabs: list[str] | None = None) -> None:
    """Modal dialog for feedback submission. Closes on submit via st.rerun()."""
    st.caption("Your feedback is shared with the team on the Overview page.")

    if "feedback_user_name" not in st.session_state:
        st.session_state.feedback_user_name = ""

    selected_tab = ""
    if tabs:
        selected_tab = st.selectbox("Section", tabs)

    user_name = st.text_input(
        "Your name (optional)",
        value=st.session_state.feedback_user_name,
    )
    comment = st.text_area(
        "Comment",
        placeholder="What would you like to see changed or added?",
    )

    if st.button("Submit", use_container_width=True):
        if not comment.strip():
            st.warning("Please enter a comment.")
        else:
            try:
                st.session_state.feedback_user_name = user_name
                insert_feedback(page, selected_tab, comment.strip(), user_name.strip())
                st.toast("Feedback submitted!")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to save feedback: {e}")


def render_feedback(page: str, tabs: list[str] | None = None) -> None:
    """Render a feedback button in the sidebar that opens a dialog."""
    st.markdown("---")
    if st.button("Feedback", key="fb_open", use_container_width=True):
        st.session_state._fb_page = page
        st.session_state._fb_tabs = tabs
        st.session_state._fb_open = True
        st.rerun()


def _check_feedback_dialog() -> None:
    """Call this outside sidebar context to open the dialog if requested."""
    if st.session_state.get("_fb_open"):
        st.session_state._fb_open = False
        _feedback_dialog(
            st.session_state.get("_fb_page", ""),
            st.session_state.get("_fb_tabs"),
        )
