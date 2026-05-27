"""Revenue-specific BQ queries.

Each public function has a DEMO_MODE early-return that aggregates from
`demo_data/bookings.csv` via `_demo_bookings()` instead of hitting BQ.
The fixture aggregations live just below `_demo_bookings()`; the BQ
path that follows is unchanged.
"""

import numpy as np
import pandas as pd
from data.bq_client import BOOKINGS_TABLE, DEMO_MODE, get_bq_client
from data.queries import _load_fixture

import streamlit as st


@st.cache_data(ttl=3600, show_spinner=False)
def _demo_bookings() -> pd.DataFrame:
    """Cached fixture-bookings DataFrame for demo-mode aggregations."""
    df = _load_fixture("bookings")
    df["visit_datetime"] = pd.to_datetime(df["visit_datetime"], errors="coerce")
    df["net_amount"] = df["net_amount"].astype(float)
    return df


def _demo_period_summary(start_date: str, end_date: str) -> dict:
    df = _demo_bookings()
    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize() + pd.Timedelta(days=1)
    period = df[
        (df["visit_datetime"] >= start)
        & (df["visit_datetime"] < end)
        & (df["status"] != "canceled")
    ]
    bookings = int(len(period))
    turnover = float(period["net_amount"].sum())
    aov = float(turnover / bookings) if bookings else 0.0
    unique_customers = int(period["customer_email"].nunique())
    return {
        "turnover": turnover,
        "bookings": bookings,
        "aov": aov,
        "unique_customers": unique_customers,
    }


def _demo_prev_customer_metrics(start_date: str, end_date: str) -> dict:
    df = _demo_bookings()
    df = df[df["status"] != "canceled"]
    df = df[df["customer_email"].fillna("") != ""]
    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize() + pd.Timedelta(days=1)
    period = df[(df["visit_datetime"] >= start) & (df["visit_datetime"] < end)]
    grouped = period.groupby("customer_email").size()
    repeat_pct = float((grouped >= 2).mean() * 100) if len(grouped) else 0.0

    # Cohort retention: first month's customers returning within 12 months.
    first_visit = df.groupby("customer_email")["visit_datetime"].min()
    if first_visit.empty:
        return {"repeat_pct": repeat_pct, "retention_pct": None}
    cohort_start = first_visit.min().to_period("M").to_timestamp()
    cohort_customers = first_visit[
        first_visit.dt.to_period("M").dt.to_timestamp() == cohort_start
    ].index
    cohort_size = len(cohort_customers)
    if cohort_size == 0:
        return {"repeat_pct": repeat_pct, "retention_pct": None}
    return_window_start = cohort_start + pd.DateOffset(months=1)
    return_window_end = cohort_start + pd.DateOffset(months=13)
    returners = df[
        df["customer_email"].isin(cohort_customers)
        & (df["visit_datetime"] > return_window_start)
        & (df["visit_datetime"] <= return_window_end)
    ]["customer_email"].nunique()
    retention_pct = float(returners / cohort_size * 100)
    return {"repeat_pct": repeat_pct, "retention_pct": retention_pct}


def _demo_clv_inputs(end_date: str, location_filter: tuple | None = None) -> dict:
    """Shared CLV-inputs computation for both _get_clv_inputs and _by_location."""
    df = _demo_bookings()
    df = df[df["status"] != "canceled"]
    df = df[df["customer_email"].fillna("") != ""]
    if location_filter:
        df = df[df["location"].isin(location_filter)]

    end_dt = pd.Timestamp(end_date).normalize()
    window_start = end_dt - pd.DateOffset(months=12)
    window = df[(df["visit_datetime"] >= window_start) & (df["visit_datetime"] <= end_dt)]
    agg = window.groupby("customer_email").agg(
        bookings=("visit_datetime", "size"),
        total_paid=("net_amount", "sum"),
    )

    if agg.empty:
        return {
            "aov": 0, "mean_annual_frequency": 1.0,
            "retention_rate": 0.3, "num_cohorts": 0,
            "total_customers": 0,
            "window_start": end_date, "window_end": end_date,
            "segments": [],
        }

    first_ever = df.groupby("customer_email")["visit_datetime"].min().rename("first_ever_visit")
    agg = agg.join(first_ever, how="left")
    agg["cohort_month"] = agg["first_ever_visit"].dt.to_period("M")

    # has_return: did this customer book again within months 1–13 after first-ever visit?
    df_visits = df[["customer_email", "visit_datetime"]].merge(
        first_ever.reset_index(), on="customer_email", how="left",
    )
    df_visits["months_since_first"] = (
        (df_visits["visit_datetime"] - df_visits["first_ever_visit"]).dt.days / 30.4
    )
    returners = set(
        df_visits[(df_visits["months_since_first"] > 1) & (df_visits["months_since_first"] <= 13)]
        ["customer_email"].unique()
    )
    agg["has_return"] = agg.index.to_series().isin(returners)

    total_bookings = agg["bookings"].sum()
    total_paid = float(agg["total_paid"].sum())
    aov = float(total_paid / total_bookings) if total_bookings else 0.0
    mean_annual_frequency = float(agg["bookings"].mean())

    agg["segment"] = agg["bookings"].apply(
        lambda b: "VIP" if b >= 5 else ("Regular" if b >= 2 else "New")
    )

    cutoff = (end_dt - pd.DateOffset(months=6)).to_period("M")
    eligible = agg[agg["cohort_month"] <= cutoff]
    retention_rate = 0.3
    num_cohorts = 0
    if not eligible.empty:
        cohort_rates = eligible.groupby("cohort_month").apply(
            lambda g: g["has_return"].sum() / len(g) if len(g) >= 3 else np.nan,
            include_groups=False,
        ).dropna()
        if len(cohort_rates):
            retention_rate = float(cohort_rates.mean())
            num_cohorts = int(len(cohort_rates))

    segments = []
    for seg_name in ("New", "Regular", "VIP"):
        seg_df = agg[agg["segment"] == seg_name]
        if seg_df.empty:
            continue
        seg_aov = float(seg_df["total_paid"].sum() / seg_df["bookings"].sum())
        seg_mean_freq = float(seg_df["bookings"].mean())
        seg_eligible = eligible[eligible["segment"] == seg_name]
        seg_retention = None
        if not seg_eligible.empty:
            seg_rates = seg_eligible.groupby("cohort_month").apply(
                lambda g: g["has_return"].sum() / len(g) if len(g) >= 3 else np.nan,
                include_groups=False,
            ).dropna()
            if len(seg_rates):
                seg_retention = float(seg_rates.mean())
        if seg_retention is None:
            seg_retention = {
                "VIP": min(retention_rate * 1.5, 0.95),
                "Regular": min(retention_rate * 1.2, 0.95),
                "New": retention_rate * 0.7,
            }[seg_name]
        segments.append({
            "segment": seg_name,
            "customers": int(len(seg_df)),
            "aov": seg_aov,
            "mean_frequency": seg_mean_freq,
            "retention_rate": seg_retention,
        })

    return {
        "aov": aov,
        "mean_annual_frequency": mean_annual_frequency,
        "retention_rate": retention_rate,
        "num_cohorts": num_cohorts,
        "total_customers": int(len(agg)),
        "window_start": window_start.strftime("%Y-%m-%d"),
        "window_end": end_date,
        "segments": segments,
    }


def _demo_location_loyalty(start_date: str, end_date: str) -> dict:
    df = _demo_bookings()
    df = df[df["status"] != "canceled"]
    df = df[df["customer_email"].fillna("") != ""]
    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize() + pd.Timedelta(days=1)
    period = df[(df["visit_datetime"] >= start) & (df["visit_datetime"] < end)]
    by_customer = period.groupby("customer_email").agg(
        total_bookings=("visit_datetime", "size"),
        num_locations=("location", "nunique"),
    )
    repeat = by_customer[by_customer["total_bookings"] >= 2]
    distribution = [
        {"loyalty_type": "Single location",
         "customers": int((repeat["num_locations"] == 1).sum())},
        {"loyalty_type": "2 locations",
         "customers": int((repeat["num_locations"] == 2).sum())},
        {"loyalty_type": "3+ locations",
         "customers": int((repeat["num_locations"] >= 3).sum())},
    ]
    return {
        "distribution": distribution,
        "total_repeat_customers": int(sum(d["customers"] for d in distribution)),
    }


@st.cache_data(ttl=300, show_spinner=False)
def _get_prev_customer_metrics(start_date: str, end_date: str) -> dict:
    """Get repeat customer % and retention rate for a date range."""
    if DEMO_MODE:
        return _demo_prev_customer_metrics(start_date, end_date)
    from google.cloud import bigquery
    client = get_bq_client()
    query = f"""
    WITH customer_bookings AS (
        SELECT customer_email, COUNT(*) as bookings,
               MIN(visit_datetime) as first_visit
        FROM `{BOOKINGS_TABLE}`
        WHERE DATE(visit_datetime) BETWEEN @start_date AND @end_date
            AND status != 'canceled'
            AND customer_email IS NOT NULL
            AND customer_email != ''
        GROUP BY customer_email
    ),
    repeat_stats AS (
        SELECT
            SAFE_DIVIDE(COUNTIF(bookings >= 2), COUNT(*)) * 100 as repeat_pct
        FROM customer_bookings
    ),
    -- Cohort retention: first full month's new customers who return within 12 months
    first_month AS (
        SELECT
            DATE_TRUNC(DATE(MIN(first_visit)), MONTH) as cohort_start
        FROM customer_bookings
    ),
    cohort AS (
        SELECT cb.customer_email
        FROM customer_bookings cb, first_month fm
        WHERE DATE_TRUNC(DATE(cb.first_visit), MONTH) = fm.cohort_start
    ),
    returning AS (
        SELECT DISTINCT b.customer_email
        FROM `{BOOKINGS_TABLE}` b
        JOIN cohort c ON b.customer_email = c.customer_email
        CROSS JOIN first_month fm
        WHERE b.status != 'canceled'
            AND DATE(b.visit_datetime) > DATE_ADD(fm.cohort_start, INTERVAL 1 MONTH)
            AND DATE(b.visit_datetime) <= DATE_ADD(fm.cohort_start, INTERVAL 13 MONTH)
    )
    SELECT
        rs.repeat_pct,
        (SELECT COUNT(*) FROM cohort) as cohort_size,
        SAFE_DIVIDE(
            (SELECT COUNT(*) FROM returning),
            (SELECT COUNT(*) FROM cohort)
        ) * 100 as retention_pct
    FROM repeat_stats rs
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
    )
    result = client.query(query, job_config=job_config).to_dataframe()
    row = result.iloc[0]
    return {
        "repeat_pct": float(row["repeat_pct"]) if row["repeat_pct"] is not None else 0,
        "retention_pct": float(row["retention_pct"]) if row["retention_pct"] is not None else None,
    }


@st.cache_data(ttl=300, show_spinner=False)
def _get_period_summary(start_date: str, end_date: str) -> dict:
    """Get turnover, AOV, and bookings for a date range via lightweight BQ query."""
    if DEMO_MODE:
        return _demo_period_summary(start_date, end_date)
    from google.cloud import bigquery
    client = get_bq_client()
    query = f"""
    SELECT
        COALESCE(SUM(net_amount), 0) as total_turnover,
        COUNT(*) as bookings,
        SAFE_DIVIDE(SUM(net_amount), COUNT(*)) as aov,
        COUNT(DISTINCT customer_email) as unique_customers
    FROM `{BOOKINGS_TABLE}`
    WHERE DATE(visit_datetime) BETWEEN @start_date AND @end_date
        AND status != 'canceled'
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
    )
    result = client.query(query, job_config=job_config).to_dataframe()
    row = result.iloc[0]
    return {
        "turnover": float(row["total_turnover"]),
        "bookings": int(row["bookings"]),
        "aov": float(row["aov"]) if row["aov"] is not None else 0,
        "unique_customers": int(row["unique_customers"]),
    }


@st.cache_data(ttl=3600, show_spinner="Loading CLV data...")
def _get_clv_inputs(end_date: str) -> dict:
    """Get CLV model inputs from the last 12 months ending at end_date.

    Returns AOV, median annual frequency, multi-cohort retention rate,
    and per-segment breakdowns — all decoupled from the UI date range.
    """
    if DEMO_MODE:
        return _demo_clv_inputs(end_date)
    from google.cloud import bigquery
    client = get_bq_client()
    query = f"""
    WITH customer_window AS (
        SELECT
            customer_email,
            COUNT(*) as bookings,
            SUM(net_amount) as total_paid
        FROM `{BOOKINGS_TABLE}`
        WHERE DATE(visit_datetime) BETWEEN DATE_SUB(@end_date, INTERVAL 12 MONTH) AND @end_date
            AND status != 'canceled'
            AND customer_email IS NOT NULL AND customer_email != ''
        GROUP BY customer_email
    ),
    customer_first_ever AS (
        SELECT customer_email, MIN(DATE(visit_datetime)) as first_ever_visit
        FROM `{BOOKINGS_TABLE}`
        WHERE status != 'canceled'
            AND customer_email IS NOT NULL AND customer_email != ''
        GROUP BY customer_email
    ),
    returning_customers AS (
        SELECT DISTINCT cfe.customer_email
        FROM customer_first_ever cfe
        JOIN `{BOOKINGS_TABLE}` b
            ON b.customer_email = cfe.customer_email
        WHERE b.status != 'canceled'
            AND DATE(b.visit_datetime) > DATE_ADD(
                DATE_TRUNC(cfe.first_ever_visit, MONTH), INTERVAL 1 MONTH)
            AND DATE(b.visit_datetime) <= DATE_ADD(
                DATE_TRUNC(cfe.first_ever_visit, MONTH), INTERVAL 13 MONTH)
    )
    SELECT
        cw.customer_email,
        cw.bookings,
        cw.total_paid,
        cfe.first_ever_visit,
        CASE WHEN rc.customer_email IS NOT NULL THEN TRUE ELSE FALSE END as has_return
    FROM customer_window cw
    JOIN customer_first_ever cfe ON cw.customer_email = cfe.customer_email
    LEFT JOIN returning_customers rc ON cw.customer_email = rc.customer_email
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
    )
    result = client.query(query, job_config=job_config).to_dataframe()

    if len(result) == 0:
        return {
            "aov": 0, "mean_annual_frequency": 1.0,
            "retention_rate": 0.3, "num_cohorts": 0,
            "total_customers": 0,
            "window_start": end_date, "window_end": end_date,
            "segments": [],
        }

    df = result
    total_bookings = df["bookings"].sum()
    total_paid = df["total_paid"].sum()
    aov = float(total_paid / total_bookings) if total_bookings > 0 else 0

    # Mean annual frequency — 12-month window so booking count = annual freq
    mean_annual_frequency = float(df["bookings"].mean())

    # Segment column (needed before cohort filtering for per-segment retention)
    df["segment"] = df["bookings"].apply(
        lambda b: "VIP" if b >= 5 else ("Regular" if b >= 2 else "New")
    )

    # Multi-cohort retention: average across monthly cohorts with enough data
    end_dt = pd.Timestamp(end_date)
    df["cohort_month"] = pd.to_datetime(df["first_ever_visit"]).dt.to_period("M")
    # Only use cohorts with >= 6 months of follow-up
    cutoff = (end_dt - pd.DateOffset(months=6)).to_period("M")
    cohort_eligible = df[df["cohort_month"] <= cutoff]

    retention_rate = 0.3
    num_cohorts = 0
    if len(cohort_eligible) > 0:
        cohort_rates = cohort_eligible.groupby("cohort_month").apply(
            lambda g: g["has_return"].sum() / len(g) if len(g) >= 3 else np.nan,
            include_groups=False,
        ).dropna()
        if len(cohort_rates) > 0:
            retention_rate = float(cohort_rates.mean())
            num_cohorts = len(cohort_rates)
    segments = []
    for seg_name in ["New", "Regular", "VIP"]:
        seg_df = df[df["segment"] == seg_name]
        if len(seg_df) == 0:
            continue
        seg_aov = float(seg_df["total_paid"].sum() / seg_df["bookings"].sum())
        seg_mean_freq = float(seg_df["bookings"].mean())
        # Segment retention from eligible cohorts
        seg_retention = None
        seg_eligible = cohort_eligible[cohort_eligible["segment"] == seg_name]
        if len(seg_eligible) > 0:
            seg_rates = seg_eligible.groupby("cohort_month").apply(
                lambda g: g["has_return"].sum() / len(g) if len(g) >= 3 else np.nan,
                include_groups=False,
            ).dropna()
            if len(seg_rates) > 0:
                seg_retention = float(seg_rates.mean())
        if seg_retention is None:
            seg_retention = {
                "VIP": min(retention_rate * 1.5, 0.95),
                "Regular": min(retention_rate * 1.2, 0.95),
                "New": retention_rate * 0.7,
            }[seg_name]
        segments.append({
            "segment": seg_name,
            "customers": len(seg_df),
            "aov": seg_aov,
            "mean_frequency": seg_mean_freq,
            "retention_rate": seg_retention,
        })

    window_start = (end_dt - pd.DateOffset(months=12)).strftime("%Y-%m-%d")
    return {
        "aov": aov,
        "mean_annual_frequency": mean_annual_frequency,
        "retention_rate": retention_rate,
        "num_cohorts": num_cohorts,
        "total_customers": len(df),
        "window_start": window_start,
        "window_end": end_date,
        "segments": segments,
    }


@st.cache_data(ttl=3600, show_spinner=False)
def _get_clv_inputs_by_location(end_date: str, bq_locations: tuple) -> dict:
    """Get CLV model inputs for a location from the last 12 months.

    Same methodology as _get_clv_inputs but filtered to bookings at one location.
    Retention measures return to the same location, not just to Northern Sauna overall.
    bq_locations is a tuple of raw BQ location names (to handle name mappings).
    """
    if DEMO_MODE:
        return _demo_clv_inputs(end_date, location_filter=tuple(bq_locations))
    from google.cloud import bigquery
    client = get_bq_client()
    query = f"""
    WITH customer_window AS (
        SELECT
            customer_email,
            COUNT(*) as bookings,
            SUM(net_amount) as total_paid
        FROM `{BOOKINGS_TABLE}`
        WHERE DATE(visit_datetime) BETWEEN DATE_SUB(@end_date, INTERVAL 12 MONTH) AND @end_date
            AND status != 'canceled'
            AND customer_email IS NOT NULL AND customer_email != ''
            AND location IN UNNEST(@locations)
        GROUP BY customer_email
    ),
    customer_first_at_location AS (
        SELECT customer_email, MIN(DATE(visit_datetime)) as first_visit
        FROM `{BOOKINGS_TABLE}`
        WHERE status != 'canceled'
            AND customer_email IS NOT NULL AND customer_email != ''
            AND location IN UNNEST(@locations)
        GROUP BY customer_email
    ),
    returning_to_location AS (
        SELECT DISTINCT cfl.customer_email
        FROM customer_first_at_location cfl
        JOIN `{BOOKINGS_TABLE}` b
            ON b.customer_email = cfl.customer_email
        WHERE b.status != 'canceled'
            AND b.location IN UNNEST(@locations)
            AND DATE(b.visit_datetime) > DATE_ADD(
                DATE_TRUNC(cfl.first_visit, MONTH), INTERVAL 1 MONTH)
            AND DATE(b.visit_datetime) <= DATE_ADD(
                DATE_TRUNC(cfl.first_visit, MONTH), INTERVAL 13 MONTH)
    )
    SELECT
        cw.customer_email,
        cw.bookings,
        cw.total_paid,
        cfl.first_visit,
        CASE WHEN rt.customer_email IS NOT NULL THEN TRUE ELSE FALSE END as has_return
    FROM customer_window cw
    JOIN customer_first_at_location cfl ON cw.customer_email = cfl.customer_email
    LEFT JOIN returning_to_location rt ON cw.customer_email = rt.customer_email
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
            bigquery.ArrayQueryParameter("locations", "STRING", list(bq_locations)),
        ]
    )
    result = client.query(query, job_config=job_config).to_dataframe()

    if len(result) == 0:
        return {
            "aov": 0, "mean_annual_frequency": 1.0,
            "retention_rate": 0.3, "num_cohorts": 0,
            "total_customers": 0,
        }

    df = result
    total_bookings = df["bookings"].sum()
    total_paid = df["total_paid"].sum()
    aov = float(total_paid / total_bookings) if total_bookings > 0 else 0
    mean_annual_frequency = float(df["bookings"].mean())

    # Multi-cohort retention at this location
    end_dt = pd.Timestamp(end_date)
    df["cohort_month"] = pd.to_datetime(df["first_visit"]).dt.to_period("M")
    cutoff = (end_dt - pd.DateOffset(months=6)).to_period("M")
    cohort_eligible = df[df["cohort_month"] <= cutoff]

    retention_rate = 0.3
    num_cohorts = 0
    if len(cohort_eligible) > 0:
        cohort_rates = cohort_eligible.groupby("cohort_month").apply(
            lambda g: g["has_return"].sum() / len(g) if len(g) >= 3 else np.nan,
            include_groups=False,
        ).dropna()
        if len(cohort_rates) > 0:
            retention_rate = float(cohort_rates.mean())
            num_cohorts = len(cohort_rates)

    return {
        "aov": aov,
        "mean_annual_frequency": mean_annual_frequency,
        "retention_rate": retention_rate,
        "num_cohorts": num_cohorts,
        "total_customers": len(df),
    }


@st.cache_data(ttl=3600, show_spinner=False)
def _get_location_loyalty(start_date: str, end_date: str) -> dict:
    """Location loyalty for repeat customers within the date range.

    Counts bookings and distinct locations from non-canceled bookings
    in [start_date, end_date] only. Repeat = 2+ bookings in this range.
    """
    if DEMO_MODE:
        return _demo_location_loyalty(start_date, end_date)
    from google.cloud import bigquery
    client = get_bq_client()
    query = f"""
    WITH customer_stats AS (
        SELECT
            customer_email,
            COUNT(*) as total_bookings,
            COUNT(DISTINCT location) as num_locations
        FROM `{BOOKINGS_TABLE}`
        WHERE DATE(visit_datetime) BETWEEN @start_date AND @end_date
            AND status != 'canceled'
            AND customer_email IS NOT NULL AND customer_email != ''
        GROUP BY customer_email
        HAVING COUNT(*) >= 2
    )
    SELECT
        CASE
            WHEN num_locations = 1 THEN 'Single location'
            WHEN num_locations = 2 THEN '2 locations'
            ELSE '3+ locations'
        END as loyalty_type,
        COUNT(*) as customers
    FROM customer_stats
    GROUP BY 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
    )
    result = client.query(query, job_config=job_config).to_dataframe()

    loyalty_order = ["Single location", "2 locations", "3+ locations"]
    distribution = []
    for lt in loyalty_order:
        row = result[result["loyalty_type"] == lt]
        count = int(row["customers"].iloc[0]) if len(row) > 0 else 0
        distribution.append({"loyalty_type": lt, "customers": count})

    total = sum(d["customers"] for d in distribution)
    return {
        "distribution": distribution,
        "total_repeat_customers": total,
    }
