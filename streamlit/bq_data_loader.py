"""Backward-compatibility shim for bq_data_loader.

All logic has been moved to the ``data`` package. This module re-exports
every public symbol so that existing ``from bq_data_loader import ...``
statements continue to work without changes.
"""

# ruff: noqa: I001

# --- data.feedback ---
from data.feedback import (  # noqa: F401
    get_all_feedback,
    get_feedback,
    insert_feedback,
    render_feedback,
)

# --- data.bq_client ---
from data.bq_client import (  # noqa: F401
    _BQ_TO_STREAMLIT_ACCOUNT,
    _BQ_TO_STREAMLIT_LOCATION,
    _BQ_TO_STREAMLIT_STATUS,
    BOOKINGS_TABLE,
    DATASET,
    PROJECT_ID,
    _get_bq_client,
    _to_date_str,
    estimate_loading_time,
    get_bq_client,
)

# --- data.queries ---
from data.queries import (  # noqa: F401
    GA4_HISTORICAL_BOUNDARY,
    SC_BULK_EXPORT_START,
    _query_bookings,
    _transform_bq_to_bookeo_format,
    bq_marketing_to_platform_dfs,
    get_data_coverage,
    get_data_freshness,
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

# --- data.session ---
from data.session import (  # noqa: F401
    apply_btw_toggle,
    init_session_state,
    load_all_data_with_status,
    load_bookeo_data,
    load_bookeo_data_with_status,
    refresh_bookeo_cache,
    render_bookeo_settings,
)

# --- data.status ---
from data.status import (  # noqa: F401
    get_data_hash,
    is_bookeo_data_loaded,
    is_data_loaded,
    is_marketing_data_loaded,
    is_organic_data_loaded,
)

# --- data.transforms ---
from data.transforms import (  # noqa: F401
    calculate_distribution_data,
    calculate_heatmap_data,
    calculate_location_stats,
    prepare_chart_data,
    process_booking_data,
)

# --- data.weather ---
from data.weather import (  # noqa: F401
    add_temperature_to_bookings,
    get_available_locations,
    get_location_column,
    get_temperature_data,
)
