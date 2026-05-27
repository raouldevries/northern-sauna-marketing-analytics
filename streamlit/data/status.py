"""Data status checking utilities."""

import streamlit as st


def is_data_loaded():
    """Check if booking data is loaded in session state."""
    return (
        st.session_state.get("df1") is not None
        or st.session_state.get("df2") is not None
    )


def is_marketing_data_loaded():
    """Check if marketing data is loaded in session state."""
    return (
        st.session_state.get("google_ads_df") is not None
        or st.session_state.get("meta_ads_df") is not None
    )


def is_organic_data_loaded():
    """Check if organic traffic data is loaded in session state."""
    return (
        st.session_state.get("ga4_traffic_df") is not None
        or st.session_state.get("search_console_df") is not None
    )


def is_bookeo_data_loaded() -> bool:
    """Check if booking data is currently loaded in session state."""
    return st.session_state.get("bookeo_loaded", False)


def get_data_hash(df1, df2):
    """Generate a hash to detect if data has changed."""
    if df1 is None and df2 is None:
        return None

    hash_parts = []
    if df1 is not None:
        hash_parts.append(str(len(df1)))
        hash_parts.append(str(df1.columns.tolist()))
    if df2 is not None:
        hash_parts.append(str(len(df2)))
        hash_parts.append(str(df2.columns.tolist()))

    return hash(tuple(hash_parts))
