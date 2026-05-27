"""Pure data transforms for booking pattern analysis."""

import pandas as pd

import streamlit as st


@st.cache_data
def process_booking_data(df1, df2, id_col_1, date_col_1, id_col_2, visit_col_2, location_col):
    """Process and merge booking data with caching.

    Returns (merged_clean, unmatched_count, invalid_count, negative_count).
    The merged_clean DataFrame includes derived columns: interval_category,
    booking_hour, and booking_dow.
    """
    df1_prep = df1[[id_col_1, date_col_1]].copy()
    df1_prep.columns = ["booking_id", "booking_date"]

    if location_col != "None" and location_col in df1.columns:
        df1_prep["location"] = df1[location_col]

    df2_prep = df2[[id_col_2, visit_col_2]].copy()
    df2_prep.columns = ["booking_id", "visit_date"]

    merged = df1_prep.merge(df2_prep, on="booking_id", how="inner")
    unmatched_count = max(0, len(df1) + len(df2) - (2 * len(merged)))

    merged["booking_date"] = pd.to_datetime(merged["booking_date"], errors="coerce")
    merged["visit_date"] = pd.to_datetime(merged["visit_date"], errors="coerce")
    merged["interval_days"] = (merged["visit_date"] - merged["booking_date"]).dt.days

    invalid_dates = merged["booking_date"].isna() | merged["visit_date"].isna()
    negative_intervals = (~invalid_dates) & (merged["interval_days"] < 0)
    invalid_count = int(invalid_dates.sum())
    negative_count = int(negative_intervals.sum())

    merged_clean = merged[~invalid_dates & ~negative_intervals].copy()

    def _categorize_interval(days):
        if days == 0:
            return "Same day"
        elif 1 <= days <= 3:
            return "1-3 days"
        elif 4 <= days <= 7:
            return "4-7 days"
        elif 8 <= days <= 14:
            return "1-2 weeks"
        else:
            return "2+ weeks"

    merged_clean["interval_category"] = merged_clean["interval_days"].apply(_categorize_interval)
    merged_clean["booking_hour"] = merged_clean["booking_date"].dt.hour
    merged_clean["booking_dow"] = merged_clean["booking_date"].dt.day_name()

    return merged_clean, unmatched_count, invalid_count, negative_count


@st.cache_data
def prepare_chart_data(df, group_col, value_col, agg_func="sum"):
    """Prepare aggregated data for charts with caching."""
    if df is None or len(df) == 0:
        return pd.DataFrame()

    return df.groupby(group_col).agg({value_col: agg_func}).reset_index()


@st.cache_data
def calculate_distribution_data(interval_categories_tuple):
    """Calculate lead time distribution data with caching."""
    category_order = ["Same day", "1-3 days", "4-7 days", "1-2 weeks", "2+ weeks"]
    series = pd.Series(interval_categories_tuple)
    distribution = series.value_counts()
    distribution = distribution.reindex(category_order, fill_value=0)
    total = distribution.sum()
    distribution_pct = (
        (distribution / total * 100).round(1) if total > 0 else distribution
    )
    return distribution, distribution_pct


@st.cache_data
def calculate_location_stats(df_values, location_col_values, interval_col_values):
    """Calculate location-wise statistics with caching."""
    df = pd.DataFrame(
        {"location": location_col_values, "interval_days": interval_col_values}
    )

    stats = df.groupby("location").agg({"interval_days": ["count", "mean", "median"]}).round(1)
    stats.columns = ["Total Bookings", "Avg Lead Time (days)", "Median Lead Time (days)"]
    stats = stats.sort_values("Total Bookings", ascending=False)
    stats["Total Bookings"] = stats["Total Bookings"].astype(int)

    same_day_pct = df.groupby("location")["interval_days"].apply(
        lambda x: round((x == 0).sum() / len(x) * 100, 1)
    )
    stats["Same-Day %"] = same_day_pct

    return stats


@st.cache_data
def calculate_heatmap_data(booking_hours, booking_dows):
    """Calculate heatmap data for booking time analysis with caching."""
    day_order = [
        "Monday", "Tuesday", "Wednesday", "Thursday",
        "Friday", "Saturday", "Sunday",
    ]

    df = pd.DataFrame(
        {"booking_hour": list(booking_hours), "booking_dow": list(booking_dows)}
    )
    df["booking_dow"] = pd.Categorical(
        df["booking_dow"], categories=day_order, ordered=True
    )

    heatmap_pivot = (
        df.groupby(["booking_hour", "booking_dow"]).size().unstack(fill_value=0)
    )
    heatmap_pivot = heatmap_pivot.reindex(columns=day_order, fill_value=0)

    peak_hour = int(df["booking_hour"].mode().iloc[0]) if len(df) > 0 else 0
    peak_day = str(df["booking_dow"].mode().iloc[0]) if len(df) > 0 else "Unknown"
    evening_pct = (
        (df["booking_hour"] >= 18).sum() / len(df) * 100 if len(df) > 0 else 0
    )

    return heatmap_pivot, peak_hour, peak_day, evening_pct
