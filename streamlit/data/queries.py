"""BigQuery query functions for bookings, marketing, GA4, and Search Console."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from google.cloud import bigquery

import streamlit as st
from data.bq_client import (
    _BQ_TO_STREAMLIT_ACCOUNT,
    _BQ_TO_STREAMLIT_LOCATION,
    _BQ_TO_STREAMLIT_STATUS,
    BOOKINGS_MEMBER_VIEW,
    DATASET,
    DEMO_MODE,
    GA4_PROPERTY_ID,
    PROJECT_ID,
    _get_bq_client,
)

# ---------------------------------------------------------------------------
# Demo-mode fixture loader
# ---------------------------------------------------------------------------

# Repo-root-relative default; override via DEMO_DATA_DIR for tests or alt layouts.
_DEMO_DATA_DIR = Path(
    os.environ.get(
        "DEMO_DATA_DIR",
        str(Path(__file__).resolve().parent.parent.parent / "demo_data"),
    )
)


def _load_fixture(
    name: str,
    start_date: str | None = None,
    end_date: str | None = None,
    date_column: str | None = None,
) -> pd.DataFrame:
    """Read demo_data/{name}.csv and optionally filter by date range.

    Used by every BigQuery loader's DEMO_MODE early-return path. Fixtures
    without a date column (aggregates like age_demographics) are returned
    in full — they were pre-aggregated by the generator over the demo
    window, so the caller's start/end date is already implicit.

    `date_column`, when given, is parsed to pandas Timestamps so the demo
    path matches the BQ contract — `to_dataframe()` returns DATE columns
    as db-dtypes (have `.dt` / `.strftime`); pd.read_csv returns object
    strings (don't). Pages call `.strftime` / `.dt.date` on these
    columns, so we coerce once here rather than in every caller.
    """
    df = pd.read_csv(_DEMO_DATA_DIR / f"{name}.csv")
    if date_column and date_column in df.columns:
        df[date_column] = pd.to_datetime(df[date_column], errors="coerce")
        if start_date and end_date:
            start = pd.Timestamp(start_date).normalize()
            end = pd.Timestamp(end_date).normalize() + pd.Timedelta(days=1)
            df = df[
                (df[date_column] >= start) & (df[date_column] < end)
            ].reset_index(drop=True)
    return df


def _load_bookings_from_fixture(
    start_date: str,
    end_date: str,
    include_canceled: bool,
    date_column: str,
) -> pd.DataFrame:
    """Demo-mode bookings reader — mirrors the column shape of _query_bookings.

    The fixture CSV already carries every column listed in
    BOOKINGS_QUERY_SELECT_COLUMNS, so the downstream
    _transform_bq_to_bookeo_format() runs unchanged.
    """
    allowed_columns = {"visit_datetime", "booking_created_at"}
    if date_column not in allowed_columns:
        date_column = "visit_datetime"
    df = _load_fixture("bookings", start_date, end_date, date_column=date_column)
    if not include_canceled and not df.empty:
        df = df[df["status"] != "canceled"].reset_index(drop=True)
    return df

# ---------------------------------------------------------------------------
# Core query: bookings from BigQuery
# ---------------------------------------------------------------------------

# Canonical SELECT-list for the bookings query path. Exported as a
# module-level constant so `scripts/verify_member_parity.py` (Step 4.1
# parity check) can build a syntactically equivalent query without
# duplicating the column list — if the page adds/removes a column here,
# the parity check picks it up automatically.
BOOKINGS_QUERY_SELECT_COLUMNS = """
    id,
    source_account,
    customer_email,
    customer_name,
    customer_phone,
    location,
    product_name,
    booking_created_at,
    visit_datetime,
    status,
    participants,
    gross_amount,
    net_amount,
    paid_amount,
    -- Extract fields from raw_data JSON for Promotions/Capacity/Source pages
    JSON_VALUE(raw_data, '$.endTime') AS end_time,
    JSON_VALUE(raw_data, '$.promotionName') AS promotion_name,
    JSON_VALUE(raw_data, '$.source') AS booking_source,
    JSON_VALUE(raw_data, '$.privateEvent') AS private_event,
    JSON_VALUE(raw_data, '$.canceled') AS is_canceled,
    JSON_VALUE(raw_data, '$.cancelationTime') AS cancelation_time,
    JSON_VALUE(raw_data, '$.cancelationAgent') AS cancelation_agent,
    JSON_VALUE(raw_data, '$.creationAgent') AS creation_agent,
    JSON_VALUE(raw_data, '$.lastChangeTime') AS last_change_time,
    JSON_VALUE(raw_data, '$.lastChangeAgent') AS last_change_agent,
    JSON_VALUE(raw_data, '$.noShow') AS is_no_show,
    TO_JSON_STRING(raw_data.couponCodes) AS coupon_codes_json,
    -- `is_member` (BOOL) and `membership_end` (DATE) are denormalized in
    -- the view (Step 1.1 of plans/member-metric-parity-plan.md). Page no
    -- longer parses customer.member JSON itself.
    is_member,
    membership_end
"""


@st.cache_data(ttl=3600, show_spinner=False)
def _query_bookings(
    start_date: str,
    end_date: str,
    include_canceled: bool = True,
    date_column: str = "visit_datetime",
) -> pd.DataFrame:
    """Query bookings from BigQuery with date range filter.

    Args:
        start_date: ISO date string (YYYY-MM-DD)
        end_date: ISO date string (YYYY-MM-DD)
        include_canceled: Whether to include canceled bookings
        date_column: Column to filter on ("visit_datetime" or "booking_created_at")

    Returns:
        Raw BigQuery DataFrame with all columns including raw_data JSON extracts.
    """
    if DEMO_MODE:
        return _load_bookings_from_fixture(
            start_date, end_date, include_canceled, date_column,
        )
    client = _get_bq_client()

    # Whitelist to prevent SQL injection
    allowed_columns = {"visit_datetime", "booking_created_at"}
    if date_column not in allowed_columns:
        date_column = "visit_datetime"

    status_filter = ""
    if not include_canceled:
        status_filter = "AND status != 'canceled'"

    query = f"""
    SELECT {BOOKINGS_QUERY_SELECT_COLUMNS}
    FROM `{BOOKINGS_MEMBER_VIEW}`
    WHERE DATE({date_column}) BETWEEN @start_date AND @end_date
        {status_filter}
    ORDER BY {date_column}
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
    )

    df = client.query(query, job_config=job_config).to_dataframe()
    return df


# ---------------------------------------------------------------------------
# Transform: BigQuery row -> Bookeo-format columns
# ---------------------------------------------------------------------------


def _transform_bq_to_bookeo_format(
    bq_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Transform BigQuery bookings DataFrame to Bookeo-compatible format.

    Returns (df1, df2) matching the exact column schema of the original data_loader.
    df1 = all bookings (including canceled)
    df2 = non-canceled bookings only
    """
    if bq_df.empty:
        return pd.DataFrame(), pd.DataFrame()

    df = pd.DataFrame()

    # --- Core identifiers ---
    df["Booking number"] = bq_df["id"]
    df["Product code"] = bq_df["product_name"]

    # --- Account ---
    df["Account"] = bq_df["source_account"].map(_BQ_TO_STREAMLIT_ACCOUNT).fillna(
        bq_df["source_account"]
    )

    # --- Dates ---
    df["Created"] = pd.to_datetime(bq_df["booking_created_at"])
    df["Start"] = pd.to_datetime(bq_df["visit_datetime"])
    df["End"] = pd.to_datetime(bq_df["end_time"], errors="coerce")

    # --- Location ---
    df["Activity"] = bq_df["product_name"]
    df["Tour"] = bq_df["product_name"]
    df["Location"] = bq_df["location"].map(
        lambda loc: _BQ_TO_STREAMLIT_LOCATION.get(loc, loc)
    )

    # Drop test/non-real locations
    df = df[~df["Location"].isin(["UTM test"])].reset_index(drop=True)

    # --- Customer ---
    # Split customer_name on first space -> First name / Last name
    names = bq_df["customer_name"].fillna("").str.split(n=1, expand=True)
    df["First name"] = names[0] if 0 in names.columns else ""
    df["Last name"] = names[1].fillna("") if 1 in names.columns else ""
    df["Email address"] = bq_df["customer_email"].fillna("").str.strip().str.lower()
    df["Phone"] = bq_df["customer_phone"].fillna("")

    # --- Participants ---
    df["Participants"] = bq_df["participants"].fillna(0).astype(int)
    df["Adults"] = df["Participants"]  # BQ doesn't split adults/children
    df["Children"] = 0

    # --- Pricing ---
    df["Total gross"] = bq_df["gross_amount"].fillna(0).astype(float)
    df["Total net"] = bq_df["net_amount"].fillna(0).astype(float)
    # BQ has no tax_amount column; derived from gross - net.
    # May differ from Bookeo API totalTaxes by rounding (cents).
    df["BTW"] = df["Total gross"] - df["Total net"]
    df["Total paid"] = bq_df["net_amount"].fillna(0).astype(float)
    df["Total due"] = df["Total gross"] - df["Total paid"]

    # --- Status ---
    df["Status"] = bq_df["status"].map(_BQ_TO_STREAMLIT_STATUS).fillna("normal")
    df["Canceled"] = pd.to_datetime(bq_df["cancelation_time"], errors="coerce")
    df["Canceled by"] = bq_df["cancelation_agent"].fillna("")

    # --- Marketing ---
    df["Source"] = bq_df["booking_source"].fillna("")
    df["Promotion"] = bq_df["promotion_name"].fillna("")

    # --- Coupons ---
    import json as _json

    def _parse_coupons(raw):
        if pd.isna(raw) or raw in ("", "[]", "null"):
            return "", 0
        try:
            codes = _json.loads(raw)
            if isinstance(codes, list) and codes:
                return ",".join(str(c) for c in codes), len(codes)
        except (ValueError, TypeError):
            pass
        return "", 0

    parsed = bq_df["coupon_codes_json"].apply(_parse_coupons)
    df["Coupons"] = parsed.apply(lambda x: x[0])
    df["Number of coupons"] = parsed.apply(lambda x: x[1])

    # --- Member ---
    # `is_member` arrives as BOOL from v_bookings_member_enriched. fillna(False)
    # is defensive in case a hand-built DataFrame leaks NaN; the view itself
    # already COALESCEs to FALSE.
    df["Member"] = bq_df["is_member"].fillna(False).astype(bool)
    df["Membership end"] = pd.to_datetime(bq_df["membership_end"], errors="coerce")

    # --- Metadata ---
    # `.astype(str)` keeps the BQ path identical (private_event is already
    # object dtype) and rescues the demo-mode CSV path, where pandas auto-
    # infers all-"false" columns to bool and the .str accessor would fail.
    df["Private event"] = (
        bq_df["private_event"].astype(str).fillna("false").str.lower() == "true"
    )
    df["Created by"] = bq_df["creation_agent"].fillna("API")
    df["Last changed"] = pd.to_datetime(bq_df["last_change_time"], errors="coerce")
    df["Last changed by"] = bq_df["last_change_agent"].fillna("")

    # df1: all bookings (including canceled)
    df1 = df.copy()

    # df2: non-canceled only
    df2 = df[df["Status"] != "canceled"].copy()

    return df1, df2


# ---------------------------------------------------------------------------
# Marketing data from BigQuery cross-channel views
# ---------------------------------------------------------------------------


@st.cache_data(ttl=3600, show_spinner=False)
def load_marketing_data_from_bq(
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """Query campaign performance from the v_campaign_performance view.

    Args:
        start_date: ISO date string (YYYY-MM-DD)
        end_date: ISO date string (YYYY-MM-DD)

    Returns:
        DataFrame with columns: date, platform, campaign_name, impressions,
        clicks, spend, ctr, cpc
    """
    if DEMO_MODE:
        return _load_fixture(
            "campaign_performance", start_date, end_date, date_column="date",
        )
    client = _get_bq_client()

    query = f"""
    SELECT
        date, platform, campaign_name,
        impressions, clicks, spend, ctr, cpc,
        conversions, conversion_value, reach
    FROM `{PROJECT_ID}.{DATASET}.v_campaign_performance`
    WHERE date BETWEEN @start_date AND @end_date
    ORDER BY date, platform, campaign_name
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
    )

    return client.query(query, job_config=job_config).to_dataframe()


@st.cache_data(ttl=3600, show_spinner=False)
def load_location_performance_from_bq(
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """Fetch per-location daily metrics from v_location_performance.

    Applies _BQ_TO_STREAMLIT_LOCATION post-query so the returned
    DataFrame carries the same UI labels the bookings page and CPA
    selector use. Locations not in the map pass through unchanged.

    Returns DataFrame with columns: date, location, bookings,
    bookings_total, bookings_excl_canceled, participants, revenue,
    revenue_excl_canceled, google_ads_clicks, google_ads_impressions,
    google_ads_spend, google_ads_conversions, google_ads_conversion_value,
    meta_ads_clicks, meta_ads_impressions, meta_ads_spend,
    meta_ads_conversions, meta_ads_conversion_value
    """
    if DEMO_MODE:
        return _load_fixture(
            "location_performance", start_date, end_date, date_column="date",
        )
    client = _get_bq_client()

    query = f"""
    SELECT
        date, location,
        bookings, bookings_total, bookings_excl_canceled,
        participants, revenue, revenue_excl_canceled,
        google_ads_clicks, google_ads_impressions, google_ads_spend,
        google_ads_conversions, google_ads_conversion_value,
        meta_ads_clicks, meta_ads_impressions, meta_ads_spend,
        meta_ads_conversions, meta_ads_conversion_value
    FROM `{PROJECT_ID}.{DATASET}.v_location_performance`
    WHERE date BETWEEN @start_date AND @end_date
    ORDER BY date, location
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
    )

    df = client.query(query, job_config=job_config).to_dataframe()
    if not df.empty:
        df["location"] = df["location"].replace(_BQ_TO_STREAMLIT_LOCATION)
        # `revenue` / `revenue_excl_canceled` are BQ NUMERIC → pandas
        # returns `decimal.Decimal`. Downstream ratios mix them with
        # FLOAT64 ad-spend columns; `Decimal / float` raises TypeError.
        # Cast to float so the loader's contract is "all-numeric, all
        # float" — consumers don't have to worry about the dtype mix.
        for _col in ("revenue", "revenue_excl_canceled"):
            if _col in df.columns:
                df[_col] = df[_col].astype(float)
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def load_location_performance_do_from_bq(
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """Fetch DO-only per-location daily metrics from v_location_performance_do.

    Same shape as `load_location_performance_from_bq` but restricted to
    STDC=DO source campaigns/ad-sets. Used by the CPA tab and the ROI
    tab's CPA + ROAS columns so those metrics measure conversion-stage
    spend only — Meta's `Think | Clicks | ABO` and `Clicks | Alle
    locations` (high spend, near-zero attributed conversions) don't
    inflate the CPA figure.

    All-phase metrics elsewhere on the page (Overview, Campaigns tab)
    continue to read from the original `v_location_performance` /
    `v_campaign_performance`.
    """
    if DEMO_MODE:
        return _load_fixture(
            "location_performance_do", start_date, end_date, date_column="date",
        )
    client = _get_bq_client()

    query = f"""
    SELECT
        date, location,
        bookings, bookings_total, bookings_excl_canceled,
        participants, revenue, revenue_excl_canceled,
        google_ads_clicks, google_ads_impressions, google_ads_spend,
        google_ads_conversions, google_ads_conversion_value,
        meta_ads_clicks, meta_ads_impressions, meta_ads_spend,
        meta_ads_conversions, meta_ads_conversion_value
    FROM `{PROJECT_ID}.{DATASET}.v_location_performance_do`
    WHERE date BETWEEN @start_date AND @end_date
    ORDER BY date, location
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
    )

    df = client.query(query, job_config=job_config).to_dataframe()
    if not df.empty:
        df["location"] = df["location"].replace(_BQ_TO_STREAMLIT_LOCATION)
        for _col in ("revenue", "revenue_excl_canceled"):
            if _col in df.columns:
                df[_col] = df[_col].astype(float)
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def load_age_demographics_from_bq(
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """Query age group performance from Google Ads and Meta Ads.

    Returns DataFrame with columns: platform, age_group, impressions,
    clicks, spend, conversions, conversion_value
    """
    # Demo-mode caveat (carries through age/gender/device/platform/network/
    # search-position/campaign-network loaders below): the Phase 3 generator
    # emits these aggregates pre-computed over the full demo window — there's
    # no date dimension to filter on. The BQ path filters by date; the
    # fixture path returns the full-window aggregate regardless of
    # start_date/end_date. Numbers on the Marketing page's demographic tabs
    # therefore won't reconcile with campaign_performance.csv when the user
    # narrows the date range. Tracked for Phase 3 fixture regeneration with
    # a date dimension (out of Phase 4 scope).
    if DEMO_MODE:
        return _load_fixture("age_demographics")
    client = _get_bq_client()

    query = f"""
    -- Google Ads age demographics
    SELECT
        'Google Ads' AS platform,
        CASE ar.ad_group_criterion_criterion_id
            WHEN 503001 THEN '18-24'
            WHEN 503002 THEN '25-34'
            WHEN 503003 THEN '35-44'
            WHEN 503004 THEN '45-54'
            WHEN 503005 THEN '55-64'
            WHEN 503006 THEN '65+'
        END AS age_group,
        SUM(ar.metrics_impressions) AS impressions,
        SUM(ar.metrics_clicks) AS clicks,
        SUM(ar.metrics_cost_micros) / 1e6 AS spend,
        SUM(ar.metrics_conversions) AS conversions,
        SUM(ar.metrics_conversions_value) AS conversion_value
    FROM `{PROJECT_ID}.google_ads.ads_AgeRangeStats_2079223948` ar
    WHERE ar.ad_group_criterion_criterion_id BETWEEN 503001 AND 503006
      AND ar.segments_date BETWEEN @start_date AND @end_date
    GROUP BY 1, 2

    UNION ALL

    -- Meta Ads age demographics (aggregate across genders)
    SELECT
        'Meta Ads' AS platform,
        age AS age_group,
        SUM(CAST(impressions AS INT64)) AS impressions,
        SUM(CAST(clicks AS INT64)) AS clicks,
        SUM(CAST(spend AS FLOAT64)) AS spend,
        -- Meta age table has no conversion data; conversions only from Google
        0 AS conversions,
        0 AS conversion_value
    FROM `{PROJECT_ID}.meta_ads.ads_insights_age_and_gender`
    WHERE date_start BETWEEN @start_date AND @end_date
      AND age IS NOT NULL
      AND age != ''
    GROUP BY 1, 2
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
    )

    return client.query(query, job_config=job_config).to_dataframe()


@st.cache_data(ttl=3600, show_spinner=False)
def load_gender_demographics_from_bq(
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """Query gender performance from both Google Ads and Meta Ads.

    Google Ads: criterion_id 10=MALE, 11=FEMALE (excludes UNDETERMINED).
    Meta Ads: gender column from ads_insights_age_and_gender.

    Returns DataFrame with columns: platform, gender, impressions,
    clicks, spend, conversions, conversion_value, cpc, ctr
    """
    if DEMO_MODE:
        return _load_fixture("gender_demographics")
    client = _get_bq_client()

    query = f"""
    -- Google Ads gender stats
    SELECT
        'Google Ads' AS platform,
        CASE ad_group_criterion_criterion_id
            WHEN 10 THEN 'male'
            WHEN 11 THEN 'female'
        END AS gender,
        SUM(metrics_impressions) AS impressions,
        SUM(metrics_clicks) AS clicks,
        SUM(metrics_cost_micros) / 1e6 AS spend,
        SUM(metrics_conversions) AS conversions,
        SUM(metrics_conversions_value) AS conversion_value
    FROM `{PROJECT_ID}.google_ads.ads_GenderBasicStats_2079223948`
    WHERE segments_date BETWEEN @start_date AND @end_date
      AND ad_group_criterion_criterion_id IN (10, 11)
    GROUP BY 1, 2

    UNION ALL

    -- Meta Ads gender stats (no conversion data in this table)
    SELECT
        'Meta Ads' AS platform,
        gender,
        SUM(CAST(impressions AS INT64)) AS impressions,
        SUM(CAST(clicks AS INT64)) AS clicks,
        SUM(CAST(spend AS FLOAT64)) AS spend,
        0 AS conversions,
        0 AS conversion_value
    FROM `{PROJECT_ID}.meta_ads.ads_insights_age_and_gender`
    WHERE date_start BETWEEN @start_date AND @end_date
      AND gender IS NOT NULL AND gender != '' AND gender != 'unknown'
    GROUP BY 1, 2
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
    )

    df = client.query(query, job_config=job_config).to_dataframe()
    if not df.empty:
        df['cpc'] = (df['spend'] / df['clicks'].replace(0, float('nan'))).fillna(0)
        df['ctr'] = (df['clicks'] / df['impressions'].replace(0, float('nan')) * 100).fillna(0)
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def load_device_demographics_from_bq(
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """Query device performance from both Google Ads and Meta Ads.

    Normalises device categories to Mobile / Desktop / Tablet for
    cross-channel comparison.

    Returns DataFrame with columns: platform, device, impressions,
    clicks, spend, conversions, conversion_value
    """
    if DEMO_MODE:
        return _load_fixture("device_demographics")
    client = _get_bq_client()

    query = f"""
    -- Google Ads device stats (aggregated from AgeRange table)
    SELECT
        'Google Ads' AS platform,
        CASE segments_device
            WHEN 'MOBILE' THEN 'Mobile'
            WHEN 'DESKTOP' THEN 'Desktop'
            WHEN 'TABLET' THEN 'Tablet'
            ELSE 'Other'
        END AS device,
        SUM(metrics_impressions) AS impressions,
        SUM(metrics_clicks) AS clicks,
        SUM(metrics_cost_micros) / 1e6 AS spend,
        SUM(metrics_conversions) AS conversions,
        SUM(metrics_conversions_value) AS conversion_value
    FROM `{PROJECT_ID}.google_ads.ads_AgeRangeStats_2079223948`
    WHERE segments_date BETWEEN @start_date AND @end_date
    GROUP BY 1, 2

    UNION ALL

    -- Meta Ads device stats (normalised from granular device names)
    SELECT
        'Meta Ads' AS platform,
        CASE
            WHEN impression_device IN ('iphone', 'android_smartphone', 'ipod') THEN 'Mobile'
            WHEN impression_device = 'desktop' THEN 'Desktop'
            WHEN impression_device IN ('ipad', 'android_tablet') THEN 'Tablet'
            ELSE 'Other'
        END AS device,
        SUM(CAST(impressions AS INT64)) AS impressions,
        SUM(CAST(clicks AS INT64)) AS clicks,
        SUM(CAST(spend AS FLOAT64)) AS spend,
        0 AS conversions,
        0 AS conversion_value
    FROM `{PROJECT_ID}.meta_ads.ads_insights_platform_and_device`
    WHERE date_start BETWEEN @start_date AND @end_date
      AND impression_device IS NOT NULL
      AND impression_device != ''
    GROUP BY 1, 2
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
    )

    return client.query(query, job_config=job_config).to_dataframe()


@st.cache_data(ttl=3600, show_spinner=False)
def load_platform_placement_from_bq(
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """Query Meta Ads performance by publisher platform and placement.

    Returns DataFrame with columns: publisher_platform, platform_position,
    impressions, clicks, spend, reach
    """
    if DEMO_MODE:
        return _load_fixture("platform_placement")
    client = _get_bq_client()

    query = f"""
    SELECT
        publisher_platform,
        platform_position,
        SUM(CAST(impressions AS INT64)) AS impressions,
        SUM(CAST(clicks AS INT64)) AS clicks,
        SUM(CAST(spend AS FLOAT64)) AS spend,
        SUM(CAST(reach AS INT64)) AS reach
    FROM `{PROJECT_ID}.meta_ads.ads_insights_platform_and_device`
    WHERE date_start BETWEEN @start_date AND @end_date
      AND publisher_platform IS NOT NULL
      AND publisher_platform != ''
      AND publisher_platform != 'unknown'
    GROUP BY 1, 2
    ORDER BY spend DESC
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
    )

    df = client.query(query, job_config=job_config).to_dataframe()
    if not df.empty:
        df['cpc'] = (df['spend'] / df['clicks'].replace(0, float('nan'))).fillna(0)
        df['ctr'] = (df['clicks'] / df['impressions'].replace(0, float('nan')) * 100).fillna(0)
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def load_google_ads_network_from_bq(
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """Query Google Ads performance by ad network type.

    Returns DataFrame with columns: network, impressions, clicks, spend,
    conversions, conversion_value
    """
    if DEMO_MODE:
        return _load_fixture("google_ads_network")
    client = _get_bq_client()

    query = f"""
    SELECT
        segments_ad_network_type AS network,
        SUM(metrics_impressions) AS impressions,
        SUM(metrics_clicks) AS clicks,
        SUM(metrics_cost_micros) / 1e6 AS spend,
        SUM(metrics_conversions) AS conversions,
        SUM(metrics_conversions_value) AS conversion_value
    FROM `{PROJECT_ID}.google_ads.ads_AdGroupBasicStats_2079223948`
    WHERE segments_date BETWEEN @start_date AND @end_date
    GROUP BY 1
    ORDER BY spend DESC
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
    )

    df = client.query(query, job_config=job_config).to_dataframe()
    if not df.empty:
        df['cpc'] = (df['spend'] / df['clicks'].replace(0, float('nan'))).fillna(0)
        df['ctr'] = (df['clicks'] / df['impressions'].replace(0, float('nan')) * 100).fillna(0)
        df['cpa'] = (df['spend'] / df['conversions'].replace(0, float('nan'))).fillna(0)
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def load_google_ads_campaign_network_from_bq(
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """Query Google Ads performance by campaign and network type.

    Joins AdGroupBasicStats with Campaign dimension to get campaign names.

    Returns DataFrame with columns: campaign_name, network, impressions,
    clicks, spend, conversions
    """
    if DEMO_MODE:
        return _load_fixture("google_ads_campaign_network")
    client = _get_bq_client()

    query = f"""
    SELECT
        c.campaign_name,
        s.segments_ad_network_type AS network,
        SUM(s.metrics_impressions) AS impressions,
        SUM(s.metrics_clicks) AS clicks,
        SUM(s.metrics_cost_micros) / 1e6 AS spend,
        SUM(s.metrics_conversions) AS conversions
    FROM `{PROJECT_ID}.google_ads.ads_AdGroupBasicStats_2079223948` s
    JOIN `{PROJECT_ID}.google_ads.ads_Campaign_2079223948` c
      USING (campaign_id, customer_id)
    WHERE s.segments_date BETWEEN @start_date AND @end_date
    GROUP BY 1, 2
    HAVING SUM(s.metrics_cost_micros) / 1e6 > 1
    ORDER BY spend DESC
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
    )

    df = client.query(query, job_config=job_config).to_dataframe()
    if not df.empty:
        df['ctr'] = (df['clicks'] / df['impressions'].replace(0, float('nan')) * 100).fillna(0)
        df['cpa'] = (df['spend'] / df['conversions'].replace(0, float('nan'))).fillna(0)
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def load_google_ads_search_position_from_bq(
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """Query Google Ads Search performance by ad position (top vs other).

    Returns DataFrame with columns: slot, impressions, clicks, spend,
    conversions
    """
    if DEMO_MODE:
        return _load_fixture("google_ads_search_position")
    client = _get_bq_client()

    query = f"""
    SELECT
        segments_slot AS slot,
        SUM(metrics_impressions) AS impressions,
        SUM(metrics_clicks) AS clicks,
        SUM(metrics_cost_micros) / 1e6 AS spend,
        SUM(metrics_conversions) AS conversions
    FROM `{PROJECT_ID}.google_ads.ads_AdGroupBasicStats_2079223948`
    WHERE segments_date BETWEEN @start_date AND @end_date
      AND segments_ad_network_type = 'SEARCH'
      AND segments_slot IS NOT NULL
      AND segments_slot != ''
    GROUP BY 1
    ORDER BY spend DESC
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
    )

    df = client.query(query, job_config=job_config).to_dataframe()
    if not df.empty:
        df['ctr'] = (df['clicks'] / df['impressions'].replace(0, float('nan')) * 100).fillna(0)
        df['cpa'] = (df['spend'] / df['conversions'].replace(0, float('nan'))).fillna(0)
    return df


def bq_marketing_to_platform_dfs(
    bq_df: pd.DataFrame,
) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    """Split BQ campaign data into Google Ads and Meta Ads DataFrames.

    Aggregates daily rows to campaign-level totals and maps to the schema
    expected by 7_Marketing.py.

    Returns (google_ads_df, meta_ads_df). Either may be None if no data.
    """
    if bq_df.empty:
        return None, None

    agg_cols = {
        "impressions": "sum",
        "clicks": "sum",
        "spend": "sum",
        "conversions": "sum",
        "conversion_value": "sum",
        "reach": "sum",
    }

    results = []
    for platform_key, platform_label in [("google", "Google Ads"), ("meta", "Meta Ads")]:
        subset = bq_df[bq_df["platform"] == platform_key]
        if subset.empty:
            results.append(None)
            continue

        agg = subset.groupby("campaign_name", as_index=False).agg(agg_cols)

        # Recalculate derived metrics from aggregated totals
        agg["ctr"] = (agg["clicks"] / agg["impressions"] * 100).where(
            agg["impressions"] > 0, 0
        )
        agg["cpc"] = (agg["spend"] / agg["clicks"]).where(agg["clicks"] > 0, 0)
        agg["Platform"] = platform_label
        results.append(agg)

    return results[0], results[1]


# GMB reviews + ad-copy coverage loaders were removed in Step 5.3 of the
# public-demo-showcase plan — pages 8 (Reviews) and 12 (Northern Sauna AI) are now
# live-build-only stubs, so the data dependency they pulled doesn't ship
# in the demo. The full implementations live in the live repo.


# ---------------------------------------------------------------------------
# GA4 traffic from BigQuery (historical + native)
# ---------------------------------------------------------------------------


GA4_HISTORICAL_BOUNDARY = "2026-02-23"


@st.cache_data(ttl=3600, show_spinner=False)
def load_ga4_traffic_from_bq(start_date: str, end_date: str) -> pd.DataFrame:
    """Load GA4 traffic data from both historical and native datasets.

    Historical (<=2026-02-23): full source/medium/engagement breakdown from daily_traffic.
    Native (>2026-02-23): basic session/user counts from events_*.

    Returns DataFrame with columns: date, session_source, session_medium,
    session_default_channel_group, sessions, total_users, new_users,
    engaged_sessions, engagement_rate, screen_page_views, average_session_duration
    """
    if DEMO_MODE:
        return _load_fixture(
            "ga4_traffic", start_date, end_date, date_column="date",
        )
    client = _get_bq_client()

    query = f"""
    SELECT * FROM (
        -- Historical: full breakdown
        SELECT
            date,
            session_source,
            session_medium,
            session_default_channel_group,
            sessions,
            total_users,
            new_users,
            engaged_sessions,
            engagement_rate,
            screen_page_views,
            average_session_duration
        FROM `{PROJECT_ID}.analytics_{GA4_PROPERTY_ID}_historical.daily_traffic`
        WHERE date BETWEEN @start_date AND LEAST(@end_date, DATE '{GA4_HISTORICAL_BOUNDARY}')

        UNION ALL

        -- Native: lightweight aggregation from events_*
        SELECT
            PARSE_DATE('%Y%m%d', event_date) AS date,
            '(not available)' AS session_source,
            '(not available)' AS session_medium,
            '(not available)' AS session_default_channel_group,
            COUNTIF(event_name = 'session_start') AS sessions,
            COUNT(DISTINCT user_pseudo_id) AS total_users,
            CAST(NULL AS INT64) AS new_users,
            CAST(NULL AS INT64) AS engaged_sessions,
            CAST(NULL AS FLOAT64) AS engagement_rate,
            CAST(NULL AS INT64) AS screen_page_views,
            CAST(NULL AS FLOAT64) AS average_session_duration
        FROM `{PROJECT_ID}.analytics_{GA4_PROPERTY_ID}.events_*`
        WHERE _TABLE_SUFFIX >= FORMAT_DATE('%Y%m%d', GREATEST(
            @start_date,
            DATE_ADD(DATE '{GA4_HISTORICAL_BOUNDARY}', INTERVAL 1 DAY)
        ))
        AND _TABLE_SUFFIX <= FORMAT_DATE('%Y%m%d', @end_date)
        GROUP BY event_date
    )
    ORDER BY date
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
    )

    return client.query(query, job_config=job_config).to_dataframe()


# ---------------------------------------------------------------------------
# Search Console from BigQuery (historical API backfill + bulk export)
# ---------------------------------------------------------------------------


SC_BULK_EXPORT_START = "2026-02-24"


@st.cache_data(ttl=3600, show_spinner=False)
def load_search_console_from_bq(start_date: str, end_date: str) -> pd.DataFrame:
    """Load Search Console query data aggregated per query per date.

    UNIONs historical (SC API backfill, < 2026-02-24) with bulk export (>= 2026-02-24).
    Returns DataFrame with columns: data_date, query, clicks, impressions,
    avg_position, ctr
    """
    if DEMO_MODE:
        return _load_fixture(
            "search_console_queries", start_date, end_date,
            date_column="data_date",
        )
    client = _get_bq_client()

    query = f"""
    SELECT * FROM (
        -- Historical (SC API backfill)
        SELECT data_date, query,
            SUM(clicks) AS clicks, SUM(impressions) AS impressions,
            SUM(position * impressions) / NULLIF(SUM(impressions), 0) AS avg_position,
            SUM(ctr * impressions) / NULLIF(SUM(impressions), 0) AS ctr
        FROM `{PROJECT_ID}.searchconsole_historical.sc_query_data`
        WHERE data_date BETWEEN @start_date AND LEAST(@end_date, DATE '{SC_BULK_EXPORT_START}' - 1)
        GROUP BY data_date, query

        UNION ALL

        -- Bulk export (streaming)
        SELECT data_date, query,
            SUM(clicks) AS clicks, SUM(impressions) AS impressions,
            SAFE_DIVIDE(SUM(sum_top_position), SUM(impressions)) AS avg_position,
            SAFE_DIVIDE(SUM(clicks), SUM(impressions)) AS ctr
        FROM `{PROJECT_ID}.searchconsole.searchdata_site_impression`
        WHERE data_date BETWEEN GREATEST(@start_date, DATE '{SC_BULK_EXPORT_START}') AND @end_date
        GROUP BY data_date, query
    )
    ORDER BY data_date, clicks DESC
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
    )

    return client.query(query, job_config=job_config).to_dataframe()


@st.cache_data(ttl=3600, show_spinner=False)
def load_search_console_pages_from_bq(start_date: str, end_date: str) -> pd.DataFrame:
    """Load Search Console URL-level data aggregated per URL per date.

    UNIONs historical (SC API backfill, < 2026-02-24) with bulk export (>= 2026-02-24).
    Returns DataFrame with columns: data_date, url, clicks, impressions, avg_position
    """
    if DEMO_MODE:
        return _load_fixture(
            "search_console_pages", start_date, end_date,
            date_column="data_date",
        )
    client = _get_bq_client()

    query = f"""
    SELECT * FROM (
        -- Historical (SC API backfill)
        SELECT data_date, url,
            SUM(clicks) AS clicks, SUM(impressions) AS impressions,
            SUM(position * impressions) / NULLIF(SUM(impressions), 0) AS avg_position
        FROM `{PROJECT_ID}.searchconsole_historical.sc_url_data`
        WHERE data_date BETWEEN @start_date AND LEAST(@end_date, DATE '{SC_BULK_EXPORT_START}' - 1)
        GROUP BY data_date, url

        UNION ALL

        -- Bulk export (streaming)
        SELECT data_date, url,
            SUM(clicks) AS clicks, SUM(impressions) AS impressions,
            SAFE_DIVIDE(SUM(sum_position), SUM(impressions)) AS avg_position
        FROM `{PROJECT_ID}.searchconsole.searchdata_url_impression`
        WHERE data_date BETWEEN GREATEST(@start_date, DATE '{SC_BULK_EXPORT_START}') AND @end_date
        GROUP BY data_date, url
    )
    ORDER BY data_date, clicks DESC
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
    )

    return client.query(query, job_config=job_config).to_dataframe()


# ---------------------------------------------------------------------------
# Daily marketing summary (cross-channel time series)
# ---------------------------------------------------------------------------


@st.cache_data(ttl=3600, show_spinner=False)
def load_daily_marketing_summary_from_bq(
    start_date: str, end_date: str
) -> pd.DataFrame:
    """Load daily cross-channel summary from v_daily_marketing_summary view.

    Returns DataFrame with columns: date, source, impressions, clicks, spend,
    sessions, conversions
    """
    if DEMO_MODE:
        return _load_fixture(
            "daily_marketing_summary", start_date, end_date, date_column="date",
        )
    client = _get_bq_client()

    query = f"""
    SELECT
        date, source, impressions, clicks, spend, sessions, conversions
    FROM `{PROJECT_ID}.{DATASET}.v_daily_marketing_summary`
    WHERE date BETWEEN @start_date AND @end_date
    ORDER BY date, source
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
    )

    return client.query(query, job_config=job_config).to_dataframe()


# ---------------------------------------------------------------------------
# Data freshness: lightweight MAX(date) queries for overview dashboard
# ---------------------------------------------------------------------------


def _demo_freshness() -> dict:
    """Return "yesterday" for every source in demo mode.

    Earlier this function returned the actual MAX(date) per fixture, but
    fixtures have a fixed end date so the freshness badges on the Data
    Status table kept drifting ("3d ago", "1w ago", …) as days passed
    without a re-generation. For a portfolio demo the right signal is
    "the sync is healthy", which is what a live build with a daily cron
    would show — so we pin every source to yesterday.
    """
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    return {
        "bookings_created": yesterday,
        "bookings_visit": yesterday,
        "ga4": yesterday,
        "search_console": yesterday,
        "google_ads": yesterday,
        "meta_ads": yesterday,
    }


@st.cache_data(ttl=3600, show_spinner=False)
def get_data_freshness() -> dict:
    """Query the latest available date for each data source.

    Returns dict with keys: ga4, search_console, google_ads, meta_ads.
    Each value is a date string (YYYY-MM-DD) or None.
    """
    if DEMO_MODE:
        return _demo_freshness()
    client = _get_bq_client()

    query = f"""
    SELECT
        (SELECT MAX(DATE(booking_created_at))
         FROM `{PROJECT_ID}.{DATASET}.bookings`) AS bookings_created,
        (SELECT MAX(DATE(visit_datetime))
         FROM `{PROJECT_ID}.{DATASET}.bookings`) AS bookings_visit,
        (SELECT MAX(date) FROM `{PROJECT_ID}.analytics_{GA4_PROPERTY_ID}_historical.daily_traffic`)
            AS ga4_historical,
        (SELECT MAX(PARSE_DATE('%Y%m%d', event_date))
         FROM `{PROJECT_ID}.analytics_{GA4_PROPERTY_ID}.events_*`
         WHERE event_name = 'session_start') AS ga4_native,
        (SELECT MAX(data_date)
         FROM `{PROJECT_ID}.searchconsole.searchdata_site_impression`) AS sc_bulk,
        (SELECT MAX(data_date)
         FROM `{PROJECT_ID}.searchconsole_historical.sc_query_data`) AS sc_historical,
        (SELECT MAX(segments_date)
         FROM `{PROJECT_ID}.google_ads.ads_CampaignBasicStats_2079223948`) AS google_ads,
        (SELECT MAX(date_start)
         FROM `{PROJECT_ID}.meta_ads.ads_insights`) AS meta_ads
    """

    try:
        row = client.query(query).to_dataframe().iloc[0]
        return {
            "bookings_created": str(row["bookings_created"]) if row["bookings_created"] else None,
            "bookings_visit": str(row["bookings_visit"]) if row["bookings_visit"] else None,
            "ga4": str(max(
                pd.Timestamp(row["ga4_historical"] or "1970-01-01"),
                pd.Timestamp(row["ga4_native"] or "1970-01-01"),
            ).date()) if row["ga4_historical"] or row["ga4_native"] else None,
            "search_console": str(max(
                pd.Timestamp(row["sc_bulk"] or "1970-01-01"),
                pd.Timestamp(row["sc_historical"] or "1970-01-01"),
            ).date()) if row["sc_bulk"] or row["sc_historical"] else None,
            "google_ads": str(row["google_ads"]) if row["google_ads"] else None,
            "meta_ads": str(row["meta_ads"]) if row["meta_ads"] else None,
        }
    except Exception:
        return {
            "bookings_created": None, "bookings_visit": None,
            "ga4": None, "search_console": None, "google_ads": None, "meta_ads": None,
        }


def _demo_coverage() -> list[dict]:
    """Derive coverage rows from fixture date ranges."""
    sources: list[tuple[str, pd.Series]] = []
    bookings = _load_fixture("bookings")
    sources.append(("Bookeo", bookings["booking_created_at"]))
    campaigns = _load_fixture("campaign_performance")
    sources.append((
        "Google Ads",
        campaigns[campaigns["platform"].str.lower() == "google"]["date"],
    ))
    sources.append((
        "Meta Ads",
        campaigns[campaigns["platform"].str.lower() == "meta"]["date"],
    ))
    sources.append(("GA4", _load_fixture("ga4_traffic")["date"]))
    sources.append((
        "Search Console", _load_fixture("search_console_queries")["data_date"],
    ))

    rows: list[dict] = []
    for source, series in sources:
        dates = pd.to_datetime(series, errors="coerce").dt.date.dropna()
        if dates.empty:
            continue
        rows.append({
            "source": source,
            "earliest": dates.min(),
            "latest": dates.max(),
            "days": int(dates.nunique()),
        })
    rows.sort(key=lambda r: r["source"])
    return rows


@st.cache_data(ttl=3600, show_spinner=False)
def get_data_coverage() -> list[dict]:
    """Query the earliest date, latest date, and day count for each data source.

    Returns a list of dicts with keys: source, earliest, latest, days.
    """
    if DEMO_MODE:
        return _demo_coverage()
    client = _get_bq_client()

    query = f"""
    WITH raw AS (
        SELECT 'Bookeo' AS source, DATE(booking_created_at) AS dt
        FROM `{PROJECT_ID}.{DATASET}.bookings`
        WHERE booking_created_at IS NOT NULL
        UNION ALL
        SELECT 'Google Ads' AS source, segments_date AS dt
        FROM `{PROJECT_ID}.google_ads.ads_CampaignBasicStats_2079223948`
        UNION ALL
        SELECT 'Meta Ads', date_start
        FROM `{PROJECT_ID}.meta_ads.ads_insights`
        UNION ALL
        SELECT 'GA4', date
        FROM `{PROJECT_ID}.analytics_{GA4_PROPERTY_ID}_historical.daily_traffic`
        UNION ALL
        SELECT 'GA4', PARSE_DATE('%Y%m%d', event_date)
        FROM `{PROJECT_ID}.analytics_{GA4_PROPERTY_ID}.events_*`
        WHERE _TABLE_SUFFIX NOT LIKE 'intraday%'
          AND event_name = 'session_start'
        UNION ALL
        SELECT 'Search Console', data_date
        FROM `{PROJECT_ID}.searchconsole_historical.sc_query_data`
        UNION ALL
        SELECT 'Search Console', data_date
        FROM `{PROJECT_ID}.searchconsole.searchdata_site_impression`
    )
    SELECT source, MIN(dt) AS earliest, MAX(dt) AS latest,
           COUNT(DISTINCT dt) AS days
    FROM raw
    GROUP BY source
    ORDER BY source
    """

    try:
        df = client.query(query).to_dataframe()
        return df.to_dict("records")
    except Exception:
        return []
