"""Marketing metrics: CPA, ROAS, and STDC phase calculations."""

from io import StringIO

import pandas as pd

import streamlit as st


@st.cache_data(show_spinner=False)
def _calculate_cpa_metrics_cached(
    _df_hash, total_revenue, total_bookings,
    date_min_str, date_max_str,
    email_data_json, date_col, revenue_col,
):
    """
    Cached CPA metrics calculation. Called by calculate_cpa_metrics().
    """
    aov = total_revenue / total_bookings if total_bookings > 0 else 0

    # Calculate data span
    if date_min_str and date_max_str:
        min_date = pd.to_datetime(date_min_str)
        max_date = pd.to_datetime(date_max_str)
        data_span_days = (max_date - min_date).days
        data_span_months = data_span_days / 30.44
    else:
        data_span_months = 0

    # Calculate retention rate
    retention_rate = None
    cohort_size = 0
    returning_customers = 0

    if email_data_json and data_span_months >= 2:
        try:
            customer_data = pd.read_json(StringIO(email_data_json))
            customer_data['booking_date'] = pd.to_datetime(
                customer_data['booking_date'], errors='coerce',
            )
            # Normalize timezone for comparison (remove timezone info if present)
            if customer_data['booking_date'].dt.tz is not None:
                customer_data['booking_date'] = customer_data['booking_date'].dt.tz_localize(None)
            customer_data = customer_data.dropna(subset=['booking_date', 'email'])

            if len(customer_data) > 0:
                min_date = customer_data['booking_date'].min()
                first_month_start = (min_date + pd.offsets.MonthBegin(1)).normalize()
                first_month_end = (first_month_start + pd.offsets.MonthEnd(0)).normalize()

                first_booking_dates = (
                    customer_data.groupby('email')['booking_date']
                    .min().reset_index()
                )
                first_booking_dates.columns = ['email', 'first_booking']

                cohort_customers = first_booking_dates[
                    (first_booking_dates['first_booking'] >= first_month_start) &
                    (first_booking_dates['first_booking'] <= first_month_end)
                ]['email'].tolist()

                cohort_size = len(cohort_customers)

                if cohort_size > 0:
                    two_months_later = first_month_end + pd.DateOffset(months=2)
                    cohort_set = set(cohort_customers)

                    customer_data_ranked = customer_data.copy()
                    customer_data_ranked['booking_rank'] = (
                        customer_data_ranked.groupby('email')['booking_date']
                        .rank(method='first')
                    )

                    second_bookings = customer_data_ranked[
                        (customer_data_ranked['email'].isin(cohort_set)) &
                        (customer_data_ranked['booking_rank'] == 2)
                    ]

                    returning_customers = (
                        second_bookings['booking_date'] <= two_months_later
                    ).sum()
                    retention_rate = returning_customers / cohort_size
        except Exception:
            retention_rate = None

    return {
        'aov': aov,
        'retention_rate': retention_rate,
        'data_span_months': data_span_months,
        'has_sufficient_data': data_span_months >= 2,
        'total_bookings': total_bookings,
        'total_revenue': total_revenue,
        'cohort_size': cohort_size,
        'returning_customers': returning_customers
    }


def calculate_cpa_metrics(
    df1, df2=None, date_col='Created',
    revenue_col='Total paid', email_col='Email address',
):
    """
    Calculate CPA-related metrics from booking data. Uses caching for performance.
    """
    if df1 is None or len(df1) == 0:
        return None

    if revenue_col not in df1.columns:
        return None

    # Pre-calculate hashable values
    total_revenue = pd.to_numeric(df1[revenue_col], errors='coerce').fillna(0).sum()
    total_bookings = len(df1)

    # Get date range
    date_min_str = None
    date_max_str = None
    if date_col in df1.columns:
        dates = pd.to_datetime(df1[date_col], errors='coerce')
        date_min_str = str(dates.min())
        date_max_str = str(dates.max())

    # Prepare email data for retention calculation
    email_data_json = None
    if email_col in df1.columns and date_col in df1.columns:
        email_data = df1[[email_col, date_col]].copy()
        email_data.columns = ['email', 'booking_date']
        email_data_json = email_data.to_json(date_format='iso')

    # Create hash for cache key
    df_hash = hash((total_bookings, round(total_revenue, 2), date_min_str, date_max_str))

    return _calculate_cpa_metrics_cached(
        df_hash, total_revenue, total_bookings, date_min_str, date_max_str,
        email_data_json, date_col, revenue_col
    )


def calculate_cpa_targets(aov, bedrijfskosten_pct, winstmarge_pct, retention_rate=None):
    """
    Calculate break-even and target CPA values.

    Args:
        aov: Average Order Value
        bedrijfskosten_pct: Operating costs percentage (0-100)
        winstmarge_pct: Target profit margin percentage (0-100)
        retention_rate: Optional retention rate for LTV calculations

    Returns dict with per-booking and LTV-based CPA targets
    """
    bedrijfskosten = bedrijfskosten_pct / 100
    winstmarge = winstmarge_pct / 100

    # Per-booking calculations (additive: costs + profit + ad budget = 100%)
    breakeven_cpa = aov * (1 - bedrijfskosten)
    target_cpa = aov * max(0, 1 - bedrijfskosten - winstmarge)

    result = {
        'breakeven_cpa': breakeven_cpa,
        'target_cpa': target_cpa,
    }

    # LTV-based calculations (only if retention rate available)
    if retention_rate is not None and retention_rate > 0 and retention_rate < 1:
        expected_bookings = 1 / (1 - retention_rate)
        ltv = aov * expected_bookings
        breakeven_cpa_ltv = ltv * (1 - bedrijfskosten)
        target_cpa_ltv = breakeven_cpa_ltv * (1 - winstmarge)

        result.update({
            'expected_bookings': expected_bookings,
            'ltv': ltv,
            'breakeven_cpa_ltv': breakeven_cpa_ltv,
            'target_cpa_ltv': target_cpa_ltv,
        })

    return result


def calculate_location_actual_cpa(
    location_df: pd.DataFrame,
    location_ui_label: str,
    selected_platforms: list[str],
) -> float | None:
    """Per-location actual CPA from `v_location_performance`.

    Per-location only — the caller is responsible for routing
    "All locations" to the legacy combined_df path. The view contains
    only mapped rows, so summing platform spend across all locations
    would silently drop unmapped funnel spend and overstate the headline.

    Args:
        location_df: DataFrame from `load_location_performance_from_bq`.
            The `location` column already carries UI labels.
        location_ui_label: UI label of the chosen location, e.g.
            ``"Northern Sauna Helsinki Kamppi"``. Filtered against `location_df`
            directly — unknown labels return None (no crash).
        selected_platforms: subset of {"Google Ads", "Meta Ads"}.

    Returns:
        Actual CPA (spend / conversions) or None if no data / no
        conversions / empty platform selection.
    """
    if location_df is None or len(location_df) == 0 or not selected_platforms:
        return None

    rows = location_df[location_df["location"] == location_ui_label]
    if rows.empty:
        return None

    spend = 0.0
    conversions = 0.0
    if "Google Ads" in selected_platforms:
        spend += rows["google_ads_spend"].sum()
        conversions += rows["google_ads_conversions"].sum()
    if "Meta Ads" in selected_platforms:
        spend += rows["meta_ads_spend"].sum()
        conversions += rows["meta_ads_conversions"].sum()

    if conversions > 0:
        return spend / conversions
    return None


@st.cache_data(show_spinner=False)
def calculate_marketing_metrics(_df_hash, df_json):
    """Calculate all marketing metrics with caching. Uses df_hash for cache key."""
    df = pd.read_json(StringIO(df_json))

    total_spend = df['spend'].sum()
    total_conversions = df['conversions'].sum()
    total_conv_value = df['conversion_value'].sum() if 'conversion_value' in df.columns else 0
    roas = (total_conv_value / total_spend * 100) if total_spend > 0 else 0
    cpa = (total_spend / total_conversions) if total_conversions > 0 else 0

    # Platform breakdown
    google_df = df[df['Platform'] == 'Google Ads']
    meta_df = df[df['Platform'] == 'Meta Ads']

    return {
        'total_spend': total_spend,
        'total_conversions': total_conversions,
        'total_conv_value': total_conv_value,
        'roas': roas,
        'cpa': cpa,
        'google_spend': google_df['spend'].sum(),
        'meta_spend': meta_df['spend'].sum(),
        'google_conv': google_df['conversions'].sum(),
        'meta_conv': meta_df['conversions'].sum(),
        'google_conv_value': (
            google_df['conversion_value'].sum()
            if 'conversion_value' in google_df.columns else 0
        ),
        'meta_conv_value': (
            meta_df['conversion_value'].sum()
            if 'conversion_value' in meta_df.columns else 0
        ),
    }


@st.cache_data(show_spinner=False)
def calculate_stdc_phase_metrics(_df_hash, df_json):
    """Calculate STDC phase metrics with caching."""
    df = pd.read_json(StringIO(df_json))

    # Ensure columns exist
    if 'impressions' not in df.columns:
        df['impressions'] = 0
    if 'reach' not in df.columns:
        df['reach'] = 0
    if 'clicks' not in df.columns:
        df['clicks'] = 0
    if 'conversions' not in df.columns:
        df['conversions'] = 0

    # Aggregate by phase
    phase_agg = df.groupby('stdc_phase').agg({
        'spend': 'sum',
        'impressions': 'sum',
        'reach': 'sum',
        'clicks': 'sum',
        'conversions': 'sum'
    }).to_dict('index')

    # Aggregate by phase + platform
    platform_agg = df.groupby(['stdc_phase', 'Platform']).agg({
        'spend': 'sum',
        'impressions': 'sum',
        'reach': 'sum',
        'clicks': 'sum',
        'conversions': 'sum'
    })

    results = {}

    for phase in ['SEE', 'THINK', 'DO', 'CARE', 'Untagged']:
        if phase in phase_agg:
            p = phase_agg[phase]
            total_reach = p['impressions'] + p['reach']
            spend, clicks, conversions = p['spend'], p['clicks'], p['conversions']
        else:
            total_reach = spend = clicks = conversions = 0

        cpm = (spend / total_reach * 1000) if total_reach > 0 else 0
        ctr = (clicks / total_reach * 100) if total_reach > 0 else 0
        cpa = (spend / conversions) if conversions > 0 else 0
        conv_rate = (conversions / clicks * 100) if clicks > 0 else 0

        _zeros = {
            'spend': 0, 'impressions': 0, 'reach': 0,
            'clicks': 0, 'conversions': 0,
        }
        g_key = (phase, 'Google Ads')
        m_key = (phase, 'Meta Ads')
        g_data = platform_agg.loc[g_key] if g_key in platform_agg.index else _zeros
        m_data = platform_agg.loc[m_key] if m_key in platform_agg.index else _zeros

        g_spend = g_data['spend']
        g_impr = g_data['impressions']
        g_clicks, g_conv = g_data['clicks'], g_data['conversions']
        m_spend = m_data['spend']
        m_reach = m_data['reach']
        m_clicks, m_conv = m_data['clicks'], m_data['conversions']

        g_cpm = (g_spend / g_impr * 1000) if g_impr > 0 else 0
        m_cpm = (m_spend / m_reach * 1000) if m_reach > 0 else 0
        g_ctr = (g_clicks / g_impr * 100) if g_impr > 0 else 0
        m_ctr = (m_clicks / m_reach * 100) if m_reach > 0 else 0
        g_cpa = (g_spend / g_conv) if g_conv > 0 else 0
        m_cpa = (m_spend / m_conv) if m_conv > 0 else 0
        g_conv_rate = (g_conv / g_clicks * 100) if g_clicks > 0 else 0
        m_conv_rate = (m_conv / m_clicks * 100) if m_clicks > 0 else 0

        results[phase] = {
            'spend': spend, 'reach': total_reach, 'clicks': clicks, 'conversions': conversions,
            'cpm': cpm, 'ctr': ctr, 'cpa': cpa, 'conv_rate': conv_rate,
            'google': {
                'spend': g_spend, 'reach': g_impr,
                'clicks': g_clicks, 'conversions': g_conv,
                'cpm': g_cpm, 'ctr': g_ctr,
                'cpa': g_cpa, 'conv_rate': g_conv_rate,
            },
            'meta': {
                'spend': m_spend, 'reach': m_reach,
                'clicks': m_clicks, 'conversions': m_conv,
                'cpm': m_cpm, 'ctr': m_ctr,
                'cpa': m_cpa, 'conv_rate': m_conv_rate,
            }
        }
    return results
