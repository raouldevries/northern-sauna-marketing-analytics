"""Marketing ROI table built over `v_location_performance`.

The view already weights each platform's spend / clicks / conversions across
locations (concept-based weighted allocation). This module is a thin pandas
presentation layer: filter by selected platforms, aggregate per location,
compute ratios. No campaign-name parsing.
"""

import pandas as pd


def create_marketing_roi_table(
    location_df: pd.DataFrame,
    selected_platforms: list[str],
    include_canceled: bool = False,
) -> pd.DataFrame | None:
    """Aggregate `location_df` (from `load_location_performance_from_bq`) into
    a per-location ROI table, filtered to `selected_platforms`.

    Args:
        location_df: rows from `v_location_performance`. The `location`
            column carries UI labels (already remapped by the loader).
        selected_platforms: subset of {"Google Ads", "Meta Ads"}.
        include_canceled: mirrors the page's `Include canceled bookings`
            toggle. When True the table sums `bookings_total` + `revenue`
            (all statuses) so the ROI universe matches the rest of the
            page; when False the canceled-excluded variants are used so
            booking count and revenue agree on the same booking subset.

    Returns:
        DataFrame with columns:
            Location, Bookings, Turnover, Clicks, Conversions,
            Conv. Rate %, Conv. Value, Ad Spend, CPA, ROAS
        Locations with `Ad Spend == 0` after platform filtering are
        dropped. Returns None when there is nothing to show.

    Notes:
        - `ROAS = (Conversions × AOV) / Ad Spend`, where `AOV = Turnover
          / Bookings` per location. This credits marketing only for the
          bookings the ad platform actually attributed, multiplied by the
          location's booking-system average order value (more reliable
          than the platform-reported `Conv. Value`). Caveat: platform
          conversions are systematically undercounted (iOS SKAdNetwork,
          cookie consent, ad-blockers) — typically 30–60%, so this ROAS
          is a lower bound on marketing's true contribution.
        - `Bookings` and `Turnover` always use the same booking universe
          (controlled by `include_canceled`) so they stay internally
          consistent.
    """
    if location_df is None or len(location_df) == 0 or not selected_platforms:
        return None

    google_selected = "Google Ads" in selected_platforms
    meta_selected = "Meta Ads" in selected_platforms

    df = location_df.copy()

    # Per-platform metric selection. When a platform is unselected its
    # contribution to spend/clicks/conversions/conv-value is zeroed out.
    # Bookings + Turnover come from the booking-side columns and are not
    # platform-conditional.
    df["Ad Spend"] = (
        (df["google_ads_spend"] if google_selected else 0)
        + (df["meta_ads_spend"] if meta_selected else 0)
    )
    df["Clicks"] = (
        (df["google_ads_clicks"] if google_selected else 0)
        + (df["meta_ads_clicks"] if meta_selected else 0)
    )
    df["Conversions"] = (
        (df["google_ads_conversions"] if google_selected else 0)
        + (df["meta_ads_conversions"] if meta_selected else 0)
    )
    df["Conv. Value"] = (
        (df["google_ads_conversion_value"] if google_selected else 0)
        + (df["meta_ads_conversion_value"] if meta_selected else 0)
    )

    # Bookings + Turnover use a matching pair so the booking count and
    # revenue agree on the same booking universe. With canceled excluded
    # (default), ~5% of EUR revenue (canceled-with-non-zero-net_amount) is
    # dropped; mixing one canceled-excluded with one canceled-included
    # column would inflate Turnover and ROAS.
    if include_canceled:
        bookings_col = "bookings_total"
        revenue_col = "revenue"
    else:
        bookings_col = "bookings_excl_canceled"
        revenue_col = "revenue_excl_canceled"
    grouped = df.groupby("location", as_index=False).agg(
        Bookings=(bookings_col, "sum"),
        Turnover=(revenue_col, "sum"),
        Clicks=("Clicks", "sum"),
        Conversions=("Conversions", "sum"),
        ConvValue=("Conv. Value", "sum"),
        AdSpend=("Ad Spend", "sum"),
    )
    grouped = grouped.rename(
        columns={
            "location": "Location",
            "ConvValue": "Conv. Value",
            "AdSpend": "Ad Spend",
        }
    )

    # Drop locations with no spend in the selected platforms — bookings-only
    # rows or zero-spend rows do not belong in a ROI table.
    grouped = grouped[grouped["Ad Spend"] > 0].reset_index(drop=True)

    if grouped.empty:
        return None

    grouped["Conv. Rate %"] = (
        grouped["Conversions"]
        / grouped["Clicks"].replace(0, float("nan"))
        * 100
    ).fillna(0)
    grouped["CPA"] = (
        grouped["Ad Spend"]
        / grouped["Conversions"].replace(0, float("nan"))
    ).fillna(0)
    # ROAS uses platform-attributed conversions × booking-system AOV,
    # not full Turnover — Turnover includes organic / direct / returning
    # bookings that marketing didn't drive. AOV per location keeps each
    # row consistent with its own booking mix.
    aov = (
        grouped["Turnover"]
        / grouped["Bookings"].replace(0, float("nan"))
    ).fillna(0)
    grouped["ROAS"] = (
        grouped["Conversions"] * aov
        / grouped["Ad Spend"].replace(0, float("nan"))
    ).fillna(0)

    columns = [
        "Location",
        "Bookings",
        "Turnover",
        "Clicks",
        "Conversions",
        "Conv. Rate %",
        "Conv. Value",
        "Ad Spend",
        "CPA",
        "ROAS",
    ]
    return grouped[columns].sort_values("Ad Spend", ascending=False).reset_index(
        drop=True
    )
