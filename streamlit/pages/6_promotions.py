"""
Northern Sauna Analytics - Promotions Page
Promotion effectiveness and discount analysis
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import sys
sys.path.insert(0, '..')
from bq_data_loader import init_session_state, render_bookeo_settings
from components.demo_banner import render_demo_banner, render_footer  # noqa: E402
from utils import render_header, render_sidebar_nav
from features.revenue.formatters import format_euro, format_number, section_gap

GIFT_CARD_PATTERN = r"gift\s*cards?|giftcard|voucher|cadeau|cadeaubon|geschenk"
FREE_SESSION_TURNOVER_THRESHOLD = 0.00

# Page configuration
st.set_page_config(
    page_title="Northern Sauna - Promotions",
    page_icon="🔥",
    layout="wide"
)

if not st.session_state.get("authenticated", False):
    st.switch_page("app.py")

# Hide default Streamlit navigation
hide_default_nav = """
<style>
[data-testid="stSidebarNav"] {
    display: none;
}
</style>
"""
st.markdown(hide_default_nav, unsafe_allow_html=True)

render_header()

# BigQuery data settings (under header)
render_bookeo_settings(page_key="promotions")

st.markdown("## Promotion Effectiveness")
st.markdown("Analyze promotion usage, turnover impact, and conversion rates")

# Initialize session state using centralized function
init_session_state()

# Check authentication
if not st.session_state.get('authenticated', False):
    st.warning("Please log in to access this page.")
    st.page_link("app.py", label="Go to Login", icon=":material/login:")
    st.stop()

render_sidebar_nav("Promotions", ["Overview", "Discount Promotions", "Gift Cards", "Coupons"])

render_demo_banner()

# Main content
if st.session_state.df1 is None or st.session_state.df2 is None:
    st.info("**No data loaded.** Use the date selector above to load booking data from BigQuery.")
else:
    df1 = st.session_state.df1
    df2 = st.session_state.df2

    # Standard column names from BigQuery
    id_col_1 = "Booking number"
    date_col_1 = "Created"
    id_col_2 = "Booking number"
    visit_col_2 = "Start"
    location_col = "Location" if "Location" in df1.columns else "None"
    revenue_col = "Total paid" if "Total paid" in df1.columns else "None"
    promotion_col = "Promotion" if "Promotion" in df1.columns else "None"

    # Check required columns
    if promotion_col == "None":
        st.warning("""
        **Promotion column not configured.**

        To use promotion analysis, please select a Promotion Column in the sidebar (e.g., "Promotion").
        """)
    elif revenue_col == "None":
        st.warning("""
        **Turnover column not configured.**

        No turnover data available to analyze promotion effectiveness.
        """)
    else:
        # Process data
        @st.cache_data
        def process_promo_data(df1, df2, id_col_1, date_col_1, id_col_2, visit_col_2,
                               location_col, revenue_col, promotion_col):
            # Prepare dataframes
            cols_to_use = [id_col_1, date_col_1]
            df1_prep = df1[cols_to_use].copy()
            df1_prep.columns = ['booking_id', 'booking_date']

            df2_prep = df2[[id_col_2, visit_col_2]].copy()
            df2_prep.columns = ['booking_id', 'visit_date']

            # Add optional columns
            if location_col != "None":
                df1_prep['location'] = df1[location_col].values

            if revenue_col != "None":
                df1_prep['revenue'] = pd.to_numeric(df1[revenue_col], errors='coerce').fillna(0)

            if promotion_col != "None":
                df1_prep['promotion'] = df1[promotion_col].values

            # Add Coupons column if available
            if 'Coupons' in df1.columns:
                df1_prep['coupons'] = df1['Coupons'].values
            if 'Number of coupons' in df1.columns:
                df1_prep['num_coupons'] = pd.to_numeric(df1['Number of coupons'], errors='coerce').fillna(0)

            # Add Prepaid package column if available
            if 'Prepaid package' in df1.columns:
                df1_prep['prepaid_package'] = df1['Prepaid package'].values
            if 'Prepaid credits' in df1.columns:
                df1_prep['prepaid_credits'] = pd.to_numeric(df1['Prepaid credits'], errors='coerce').fillna(0)

            # Merge on booking ID
            merged = df1_prep.merge(df2_prep, on='booking_id', how='inner')

            # Convert dates
            merged['booking_date'] = pd.to_datetime(merged['booking_date'], errors='coerce')
            merged['visit_date'] = pd.to_datetime(merged['visit_date'], errors='coerce')

            # Filter invalid records
            invalid_dates = merged['booking_date'].isna() | merged['visit_date'].isna()
            merged_clean = merged[~invalid_dates].copy()

            return merged_clean

        with st.spinner("Processing data..."):
            processed_data = process_promo_data(
                df1, df2, id_col_1, date_col_1, id_col_2, visit_col_2,
                location_col, revenue_col, promotion_col
            )

        if len(processed_data) == 0:
            st.error("No matching booking IDs found between files.")
        else:
            # Clean promotion data
            promo_data = processed_data.copy()
            promo_data['promotion'] = promo_data['promotion'].fillna('').astype(str)
            promo_data['has_promotion'] = promo_data['promotion'] != ''
            promo_data['has_coupon'] = False
            if 'coupons' in promo_data.columns:
                promo_data['has_coupon'] = promo_data['coupons'].notna() & (promo_data['coupons'] != '')
            promo_data['has_any_code'] = promo_data['has_promotion'] | promo_data['has_coupon']
            promo_data['is_giftcard'] = promo_data['promotion'].str.contains(
                GIFT_CARD_PATTERN, case=False, regex=True
            )

            coupon_exploded = pd.DataFrame()
            gift_coupon_rows = pd.DataFrame()
            coupon_free_rows = pd.DataFrame()
            discount_coupon_rows = pd.DataFrame()
            if 'coupons' in promo_data.columns:
                coupon_exploded = promo_data[promo_data['has_coupon']].copy()
                if len(coupon_exploded) > 0:
                    coupon_exploded['coupon_code'] = coupon_exploded['coupons'].astype(str).str.split(',')
                    coupon_exploded = coupon_exploded.explode('coupon_code')
                    coupon_exploded['coupon_code'] = coupon_exploded['coupon_code'].fillna('').astype(str).str.strip()
                    coupon_exploded = coupon_exploded[coupon_exploded['coupon_code'] != ''].copy()

                    coupon_exploded['is_giftcard_coupon'] = (
                        coupon_exploded['promotion'].fillna('').astype(str).str.contains(GIFT_CARD_PATTERN, case=False, regex=True)
                        | coupon_exploded['coupon_code'].astype(str).str.contains(GIFT_CARD_PATTERN, case=False, regex=True)
                    )
                    gift_booking_ids = set(
                        coupon_exploded.loc[coupon_exploded['is_giftcard_coupon'], 'booking_id'].unique()
                    )
                    if gift_booking_ids:
                        promo_data.loc[promo_data['booking_id'].isin(gift_booking_ids), 'is_giftcard'] = True

                    coupon_exploded['coupon_category'] = 'Discount Promotions'
                    coupon_exploded.loc[coupon_exploded['is_giftcard_coupon'], 'coupon_category'] = 'Gift Cards'
                    coupon_exploded.loc[
                        (~coupon_exploded['is_giftcard_coupon'])
                        & (coupon_exploded['revenue'] <= FREE_SESSION_TURNOVER_THRESHOLD),
                        'coupon_category'
                    ] = 'Coupons'

                    gift_coupon_rows = coupon_exploded[coupon_exploded['coupon_category'] == 'Gift Cards'].copy()
                    coupon_free_rows = coupon_exploded[coupon_exploded['coupon_category'] == 'Coupons'].copy()
                    discount_coupon_rows = coupon_exploded[coupon_exploded['coupon_category'] == 'Discount Promotions'].copy()

            promo_data['category'] = 'Uncategorized'
            promo_data.loc[promo_data['has_any_code'] & promo_data['is_giftcard'], 'category'] = 'Gift Cards'
            promo_data.loc[
                promo_data['has_any_code']
                & ~promo_data['is_giftcard']
                & (promo_data['revenue'] <= FREE_SESSION_TURNOVER_THRESHOLD),
                'category'
            ] = 'Coupons'
            promo_data.loc[
                promo_data['has_any_code']
                & ~promo_data['is_giftcard']
                & (promo_data['revenue'] > FREE_SESSION_TURNOVER_THRESHOLD),
                'category'
            ] = 'Discount Promotions'
            promo_data['has_discount_promotion'] = promo_data['category'] == 'Discount Promotions'

            # Summary metrics
            with_promo = promo_data[promo_data['category'] == 'Discount Promotions']
            giftcard_bookings = promo_data[promo_data['category'] == 'Gift Cards']
            coupon_bookings = promo_data[promo_data['category'] == 'Coupons']
            without_promo = promo_data[~promo_data['has_any_code']]
            total_revenue = promo_data['revenue'].sum()
            promo_revenue = with_promo['revenue'].sum()
            promo_rev_pct = promo_revenue / total_revenue * 100 if total_revenue > 0 else 0
            avg_with = with_promo['revenue'].mean() if len(with_promo) > 0 else 0
            avg_without = without_promo['revenue'].mean() if len(without_promo) > 0 else 0
            diff = avg_with - avg_without

            # Pre-compute values used in multiple places
            promo_pct = len(with_promo) / len(promo_data) * 100 if len(promo_data) > 0 else 0
            gift_coupon_pct = len(giftcard_bookings) / len(promo_data) * 100 if len(promo_data) > 0 else 0
            coupon_pct = len(coupon_bookings) / len(promo_data) * 100 if len(promo_data) > 0 else 0

            def build_promotion_stats(category_df: pd.DataFrame) -> pd.DataFrame:
                """Aggregate promotion performance for one booking category."""
                if len(category_df) == 0:
                    return pd.DataFrame()

                stats_df = category_df.copy()
                stats_df['promotion_label'] = stats_df['promotion'].replace('', '(No promotion name)')
                stats = stats_df.groupby('promotion_label').agg({
                    'booking_id': 'count',
                    'revenue': ['sum', 'mean'],
                }).round(2)
                stats.columns = ['Bookings', 'Total Revenue', 'Avg Booking']
                stats = stats.reset_index().rename(columns={'promotion_label': 'Promotion'})
                return stats.sort_values('Bookings', ascending=False)

            def render_promotion_table(category_df: pd.DataFrame, table_title: str, category_label: str) -> pd.DataFrame:
                """Render promotion table and return aggregated stats for charting."""
                st.markdown(f"#### {table_title}")
                stats = build_promotion_stats(category_df)
                if len(stats) == 0:
                    st.info(f"No {category_label.lower()} promotion names found in the selected data.")
                    return stats

                total_bookings = len(category_df)
                total_revenue_local = category_df['revenue'].sum()
                stats['% of Category Bookings'] = (
                    (stats['Bookings'] / total_bookings * 100).round(1) if total_bookings > 0 else 0
                )
                stats['% of Category Revenue'] = (
                    (stats['Total Revenue'] / total_revenue_local * 100).round(1) if total_revenue_local > 0 else 0
                )

                display = stats.copy()
                display['Total Revenue'] = display['Total Revenue'].apply(format_euro)
                display['Avg Booking'] = display['Avg Booking'].apply(lambda x: format_euro(x, 2))

                display_cols = ['Promotion', 'Bookings', '% of Category Bookings', 'Total Revenue', '% of Category Revenue', 'Avg Booking']
                col_config = {
                    'Promotion': st.column_config.TextColumn('Promotion'),
                    'Bookings': st.column_config.NumberColumn('Bookings'),
                    '% of Category Bookings': st.column_config.NumberColumn('% of Category Bookings'),
                    'Total Revenue': st.column_config.TextColumn('Total Turnover'),
                    '% of Category Revenue': st.column_config.NumberColumn('% of Category Turnover'),
                    'Avg Booking': st.column_config.TextColumn('Avg Booking'),
                }

                st.dataframe(
                    display[display_cols],
                    use_container_width=True,
                    hide_index=True,
                    height=min(400, 35 * len(display) + 38),
                    column_config=col_config,
                )

                return stats

            def render_code_table(section_title: str, code_rows: pd.DataFrame, pct_label: str, empty_message: str) -> None:
                """Render code-level table for one category."""
                if section_title:
                    st.markdown(f"#### {section_title}")
                if len(code_rows) == 0:
                    st.info(empty_message)
                    return

                stats = code_rows.groupby('coupon_code').agg({
                    'booking_id': 'count',
                    'revenue': ['sum', 'mean'],
                    'promotion': 'first',
                }).round(2)
                stats.columns = ['Bookings', 'Total Revenue', 'Avg Booking', 'Promotion']
                stats = stats.sort_values('Bookings', ascending=False)

                denom = code_rows['booking_id'].nunique()
                stats[pct_label] = (stats['Bookings'] / denom * 100).round(1) if denom > 0 else 0

                display = stats.copy()
                display['Total Revenue'] = display['Total Revenue'].apply(format_euro)
                display['Avg Booking'] = display['Avg Booking'].apply(lambda x: format_euro(x, 2))

                st.dataframe(
                    display[['Promotion', 'Bookings', pct_label, 'Total Revenue', 'Avg Booking']],
                    use_container_width=True,
                    height=min(400, 35 * len(display) + 38),
                    column_config={
                        'Promotion': st.column_config.TextColumn('Promotion'),
                        'Bookings': st.column_config.NumberColumn('Bookings'),
                        pct_label: st.column_config.NumberColumn(pct_label),
                        'Total Revenue': st.column_config.TextColumn('Total Turnover'),
                        'Avg Booking': st.column_config.TextColumn('Avg Booking'),
                    },
                )

            def render_location_breakdown(category_df: pd.DataFrame, category_name: str) -> None:
                """Location view for one category (no expander wrapper)."""
                if location_col == "None" or 'location' not in promo_data.columns or promo_data['location'].isna().all():
                    return
                if len(category_df) == 0:
                    return

                st.markdown("#### Location Breakdown")

                totals = promo_data.groupby('location').agg(total_bookings=('booking_id', 'count')).reset_index()
                cat_stats = category_df.groupby('location').agg(
                    category_bookings=('booking_id', 'count'),
                    category_revenue=('revenue', 'sum')
                ).reset_index()
                merged = totals.merge(cat_stats, on='location', how='left').fillna(0)
                merged['category_bookings'] = merged['category_bookings'].astype(int)
                merged['Category Rate (%)'] = (
                    merged['category_bookings'] / merged['total_bookings'] * 100
                ).round(1)
                merged = merged.sort_values('category_bookings', ascending=False)

                st.dataframe(
                    merged.rename(columns={
                        'location': 'Location',
                        'total_bookings': 'Total Bookings',
                        'category_bookings': f'{category_name} Bookings',
                        'category_revenue': f'{category_name} Revenue',
                    }),
                    use_container_width=True,
                    height=min(400, 35 * len(merged) + 38),
                    hide_index=True,
                    column_config={
                        'Category Rate (%)': st.column_config.NumberColumn('Category Rate (%)'),
                    },
                )

            # Date range for takeaway titles
            _promo_date_from = promo_data['visit_date'].min().strftime("%-d %b %Y")
            _promo_date_to = promo_data['visit_date'].max().strftime("%-d %b %Y")
            _promo_takeaway_title = f"Key Takeaways ({_promo_date_from} \u2013 {_promo_date_to})"
            _promo_date_range_days = (
                promo_data['visit_date'].max() - promo_data['visit_date'].min()
            ).days
            _show_takeaways = _promo_date_range_days >= 90

            tab_overview, tab_discount, tab_giftcards, tab_coupons = st.tabs(
                ["Overview", "Discount Promotions", "Gift Cards", "Coupons"]
            )

            with tab_overview:
                kpi_cols = st.columns(4)
                with kpi_cols[0]:
                    total_coded = len(with_promo) + len(giftcard_bookings) + len(coupon_bookings)
                    coded_pct = total_coded / len(promo_data) * 100 if len(promo_data) > 0 else 0
                    st.metric(
                        "Bookings with Promotion",
                        format_number(total_coded),
                        delta=f"{coded_pct:.1f}%".replace(".", ",") + " of all bookings",
                        delta_color="off",
                    )
                with kpi_cols[1]:
                    st.metric(
                        "Discount Promotions",
                        format_number(len(with_promo)),
                        delta=f"{promo_pct:.1f}%".replace(".", ",") + " of total",
                        delta_color="off",
                        help="Coded bookings with turnover > €0.00, excluding gift cards.",
                    )
                with kpi_cols[2]:
                    st.metric(
                        "Gift Cards",
                        format_number(len(giftcard_bookings)),
                        delta=f"{gift_coupon_pct:.1f}%".replace(".", ",") + " of total",
                        delta_color="off",
                        help="Bookings identified as gift-card redemptions.",
                    )
                with kpi_cols[3]:
                    st.metric(
                        "Coupons",
                        format_number(len(coupon_bookings)),
                        delta=f"{coupon_pct:.1f}%".replace(".", ",") + " of total",
                        delta_color="off",
                        help="Coded bookings with turnover ≤ €0.00 (free session).",
                    )

                # Category comparison
                st.markdown("#### Category Breakdown")

                category_summary = pd.DataFrame({
                    'Category': ['Discount Promotions', 'Gift Cards', 'Coupons'],
                    'Bookings': [len(with_promo), len(giftcard_bookings), len(coupon_bookings)],
                    '% of Total Bookings': [promo_pct, gift_coupon_pct, coupon_pct],
                    'Total Revenue': [
                        with_promo['revenue'].sum(),
                        giftcard_bookings['revenue'].sum(),
                        coupon_bookings['revenue'].sum(),
                    ],
                    'Avg Booking': [
                        with_promo['revenue'].mean() if len(with_promo) > 0 else 0,
                        giftcard_bookings['revenue'].mean() if len(giftcard_bookings) > 0 else 0,
                        coupon_bookings['revenue'].mean() if len(coupon_bookings) > 0 else 0,
                    ],
                }).round(2)

                category_display = category_summary.copy()
                category_display['Total Revenue'] = category_display['Total Revenue'].apply(format_euro)
                category_display['Avg Booking'] = category_display['Avg Booking'].apply(lambda x: format_euro(x, 2))

                st.dataframe(
                    category_display,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        'Category': st.column_config.TextColumn('Category'),
                        'Bookings': st.column_config.NumberColumn('Bookings'),
                        '% of Total Bookings': st.column_config.NumberColumn('% of Total', format='%.1f%%'),
                        'Total Revenue': st.column_config.TextColumn('Total Turnover'),
                        'Avg Booking': st.column_config.TextColumn('Avg Booking'),
                    },
                )

                # Pie chart
                col1, col2 = st.columns(2)
                with col1:
                    fig_pie_bookings = px.pie(
                        category_summary,
                        values='Bookings',
                        names='Category',
                        title="Share of Promotional Bookings",
                        color_discrete_sequence=['#e74c3c', '#1f77b4', '#ff7f0e'],
                    )
                    fig_pie_bookings.update_layout(height=350)
                    st.plotly_chart(fig_pie_bookings, use_container_width=True)

                with col2:
                    fig_pie_revenue = px.pie(
                        category_summary,
                        values='Total Revenue',
                        names='Category',
                        title="Share of Promotional Turnover",
                        color_discrete_sequence=['#e74c3c', '#1f77b4', '#ff7f0e'],
                    )
                    fig_pie_revenue.update_layout(height=350)
                    st.plotly_chart(fig_pie_revenue, use_container_width=True)

                # Key Takeaways
                with st.expander(_promo_takeaway_title):
                 if not _show_takeaways:
                    st.caption(
                        f"Select at least 3 months of data for meaningful takeaways. "
                        f"Current range: {_promo_date_range_days} days."
                    )
                 else:
                    # Overall promo share
                    no_promo_pct = len(without_promo) / len(promo_data) * 100 if len(promo_data) > 0 else 0
                    st.info(
                        f"**{coded_pct:.0f}% of bookings use some form of promotion** "
                        f"(discount, gift card, or coupon). The remaining "
                        f"**{no_promo_pct:.0f}%** are full-price bookings at "
                        f"{format_euro(avg_without, 2)} average. "
                        + (
                            "More than 1 in 4 bookings is discounted \u2014 monitor "
                            "whether promotions are driving incremental volume or "
                            "just discounting customers who would have paid full price."
                            if coded_pct >= 25
                            else "Promotion usage is moderate. There may be room to "
                            "use targeted promotions to fill off-peak slots."
                        )
                    )

                    # Discount vs gift card vs coupon balance
                    st.info(
                        f"**Promotion mix:** Discounts account for "
                        f"**{len(with_promo) / total_coded * 100:.0f}%** of promotional "
                        f"bookings, gift cards **{len(giftcard_bookings) / total_coded * 100:.0f}%**, "
                        f"and coupons **{len(coupon_bookings) / total_coded * 100:.0f}%**. "
                        f"Gift cards are your best type \u2014 someone else paid for "
                        f"the visit, so there's no margin loss. Coupons (free sessions) "
                        f"are the most expensive. Check the individual tabs for "
                        f"deeper analysis."
                        if total_coded > 0
                        else "No promotional bookings found in this period."
                    )


                # Diagnostics
                uncategorized_bookings = promo_data[promo_data['category'] == 'Uncategorized']
                with st.expander("Diagnostics"):
                    d1, d2, d3 = st.columns(3)
                    with d1:
                        st.metric("No-code Bookings", format_number(len(without_promo)))
                    with d2:
                        st.metric("Uncategorized", format_number(len(uncategorized_bookings)))
                    with d3:
                        st.metric("With Code/Promotion", format_number(int(promo_data['has_any_code'].sum())))

                    if len(uncategorized_bookings) > 0:
                        diag_cols = ['booking_id', 'promotion', 'revenue']
                        if 'coupons' in uncategorized_bookings.columns:
                            diag_cols.append('coupons')
                        st.dataframe(
                            uncategorized_bookings[diag_cols].head(50),
                            use_container_width=True,
                            hide_index=True,
                        )
                    else:
                        st.caption("All coded bookings were classified into one of the 3 categories.")


            with tab_discount:
                m1, m2, m3, m4 = st.columns(4)
                with m1:
                    st.metric("Bookings", format_number(len(with_promo)))
                with m2:
                    st.metric("Total Turnover", format_euro(with_promo['revenue'].sum()))
                with m3:
                    st.metric("Avg Booking", format_euro(with_promo['revenue'].mean() if len(with_promo) > 0 else 0, 2))
                with m4:
                    discount_diff_label = f"{format_euro(abs(diff), 2)} {'less' if diff < 0 else 'more'}"
                    st.metric(
                        "vs Full Price",
                        discount_diff_label,
                        help=f"Discount bookings average {format_euro(avg_with, 2)} vs {format_euro(avg_without, 2)} for full-price.",
                    )

                # Charts first — visual overview
                discount_stats = build_promotion_stats(with_promo)
                if len(discount_stats) > 0:
                    col_chart1, col_chart2 = st.columns(2)
                    with col_chart1:
                        top_by_bookings = discount_stats.head(10).reset_index()
                        fig_discount_bookings = px.bar(
                            top_by_bookings,
                            x='Promotion',
                            y='Bookings',
                            title="Top 10 by Bookings",
                            labels={'Promotion': 'Promotion', 'Bookings': 'Bookings'},
                            text='Bookings',
                        )
                        fig_discount_bookings.update_traces(marker_color='#e74c3c', textposition='outside')
                        fig_discount_bookings.update_layout(height=420, xaxis_tickangle=-45, margin=dict(t=50))
                        st.plotly_chart(fig_discount_bookings, use_container_width=True)

                    with col_chart2:
                        top_by_revenue = discount_stats.sort_values('Total Revenue', ascending=False).head(10).reset_index()
                        fig_discount_revenue = px.bar(
                            top_by_revenue,
                            x='Promotion',
                            y='Total Revenue',
                            title="Top 10 by Turnover",
                            labels={'Promotion': 'Promotion', 'Total Revenue': 'Turnover (€)'},
                            text=top_by_revenue['Total Revenue'].apply(format_euro),
                        )
                        fig_discount_revenue.update_traces(marker_color='#2ecc71', textposition='outside')
                        fig_discount_revenue.update_layout(height=420, xaxis_tickangle=-45, margin=dict(t=50))
                        st.plotly_chart(fig_discount_revenue, use_container_width=True)

                # Performance table — top 10 visible
                render_promotion_table(with_promo, "Performance by Promotion", "Discount Promotions")

                section_gap()

                # --- Key Takeaways ---
                with st.expander(_promo_takeaway_title):
                 if not _show_takeaways:
                    st.caption(
                        f"Select at least 3 months of data for meaningful takeaways. "
                        f"Current range: {_promo_date_range_days} days. "
                        f"For the best insights, select the full season "
                        f"(September\u2013April)."
                    )
                 else:

                    # 1. Discount cost / margin impact
                    discount_given = abs(diff) * len(with_promo) if diff < 0 else 0
                    st.info(
                        f"**{promo_pct:.1f}%".replace(".", ",") + " of bookings use a discount promotion.** "
                        f"These bookings average **{format_euro(avg_with, 2)}** vs "
                        f"**{format_euro(avg_without, 2)}** for full-price bookings "
                        f"({format_euro(abs(diff), 2)} {'less' if diff < 0 else 'more'} per booking). "
                        + (
                            f"That's ~{format_euro(discount_given)} in total discount "
                            f"given this season. The question: are these promotions "
                            f"driving incremental bookings that wouldn't have happened "
                            f"at full price, or are you discounting customers who "
                            f"would have paid anyway?"
                            if diff < 0
                            else "Promotional bookings have a higher average value "
                            "than regular bookings \u2014 these promotions may be "
                            "driving upsells or group bookings."
                        )
                    )

                    # 2. Promotion concentration
                    if len(discount_stats) >= 3:
                        top3_bookings = discount_stats['Bookings'].head(3).sum()
                        top3_pct = top3_bookings / len(with_promo) * 100 if len(with_promo) > 0 else 0
                        top3_names = ", ".join(map(str, discount_stats.head(3).index.tolist()))

                        st.info(
                            f"**Top 3 promotions account for {top3_pct:.0f}% of all "
                            f"discount bookings** ({top3_names}). "
                            + (
                                "The promotion mix is concentrated \u2014 these "
                                "few promotions drive most of the discounted volume. "
                                "Evaluate whether retiring underperforming promotions "
                                "would simplify operations without losing bookings."
                                if top3_pct >= 60
                                else "The promotion mix is diversified across many "
                                "campaigns. Consider consolidating into fewer, "
                                "stronger promotions for clearer messaging."
                            )
                        )


            with tab_giftcards:
                m1, m2, m3 = st.columns(3)
                with m1:
                    st.metric("Bookings", format_number(len(giftcard_bookings)))
                with m2:
                    st.metric("Total Turnover", format_euro(giftcard_bookings['revenue'].sum()))
                with m3:
                    st.metric("Avg Booking", format_euro(giftcard_bookings['revenue'].mean() if len(giftcard_bookings) > 0 else 0, 2))

                # Charts first
                gift_stats = build_promotion_stats(giftcard_bookings)
                if len(gift_stats) > 0:
                    col_chart1, col_chart2 = st.columns(2)
                    with col_chart1:
                        top_by_bookings = gift_stats.head(10).reset_index()
                        fig_gift_bookings = px.bar(
                            top_by_bookings,
                            x='Promotion',
                            y='Bookings',
                            title="Top 10 by Bookings",
                            labels={'Promotion': 'Promotion', 'Bookings': 'Bookings'},
                            text='Bookings',
                        )
                        fig_gift_bookings.update_traces(marker_color='#1f77b4', textposition='outside')
                        fig_gift_bookings.update_layout(height=420, xaxis_tickangle=-45, margin=dict(t=50))
                        st.plotly_chart(fig_gift_bookings, use_container_width=True)

                    with col_chart2:
                        top_by_revenue = gift_stats.sort_values('Total Revenue', ascending=False).head(10).reset_index()
                        fig_gift_revenue = px.bar(
                            top_by_revenue,
                            x='Promotion',
                            y='Total Revenue',
                            title="Top 10 by Turnover",
                            labels={'Promotion': 'Promotion', 'Total Revenue': 'Turnover (€)'},
                            text=top_by_revenue['Total Revenue'].apply(format_euro),
                        )
                        fig_gift_revenue.update_traces(marker_color='#6baed6', textposition='outside')
                        fig_gift_revenue.update_layout(height=420, xaxis_tickangle=-45, margin=dict(t=50))
                        st.plotly_chart(fig_gift_revenue, use_container_width=True)

                # Performance table
                render_promotion_table(giftcard_bookings, "Performance by Promotion", "Gift Cards")

                section_gap()

                # --- Key Takeaways ---
                with st.expander(_promo_takeaway_title):
                 if not _show_takeaways:
                    st.caption(
                        f"Select at least 3 months of data for meaningful takeaways. "
                        f"Current range: {_promo_date_range_days} days. "
                        f"For the best insights, select the full season "
                        f"(September\u2013April)."
                    )
                 else:

                    gift_rev = giftcard_bookings['revenue'].sum()
                    gift_avg = giftcard_bookings['revenue'].mean() if len(giftcard_bookings) > 0 else 0

                    st.info(
                        f"**{format_number(len(giftcard_bookings))} gift cards redeemed this "
                        f"season** ({format_euro(gift_rev)} in turnover). Gift card "
                        f"visitors are acquired at zero marketing cost \u2014 "
                        f"someone else paid for their visit. This is free "
                        f"customer acquisition.\n\n"
                        f"**Next step:** Check if gift card users return for a "
                        f"paid visit. Their emails are in BigQuery \u2014 cross-reference "
                        f"with repeat booking data on the Customers page. "
                        f"If they don't return, a follow-up email after their "
                        f"gift card visit ('Enjoyed your sauna? Book again with "
                        f"10% off') could convert them."
                    )


            with tab_coupons:
                m1, m2, m3 = st.columns(3)
                with m1:
                    st.metric("Bookings", format_number(len(coupon_bookings)))
                with m2:
                    st.metric(
                        "Forgone Turnover",
                        format_euro(len(coupon_bookings) * avg_without),
                        help=f"Estimated cost: {format_number(len(coupon_bookings))} free sessions × {format_euro(avg_without, 2)} full-price average.",
                    )
                with m3:
                    st.metric(
                        "% of All Bookings",
                        f"{(len(coupon_bookings) / len(promo_data) * 100 if len(promo_data) > 0 else 0):.1f}%".replace(".", ","),
                    )

                # Charts first
                coupon_stats = build_promotion_stats(coupon_bookings)
                if len(coupon_stats) > 0:
                    top_by_bookings = coupon_stats.head(10).reset_index()
                    fig_coupon_bookings = px.bar(
                        top_by_bookings,
                        x='Promotion',
                        y='Bookings',
                        title="Top 10 Coupon Promotions by Bookings",
                        labels={'Promotion': 'Promotion', 'Bookings': 'Bookings'},
                        text='Bookings',
                    )
                    fig_coupon_bookings.update_traces(marker_color='#ff7f0e', textposition='outside')
                    fig_coupon_bookings.update_layout(height=420, xaxis_tickangle=-45, margin=dict(t=50))
                    st.plotly_chart(fig_coupon_bookings, use_container_width=True)

                # Performance table
                render_promotion_table(coupon_bookings, "Performance by Promotion", "Coupons")

                section_gap()

                # --- Key Takeaways ---
                with st.expander(_promo_takeaway_title):
                 if not _show_takeaways:
                    st.caption(
                        f"Select at least 3 months of data for meaningful takeaways. "
                        f"Current range: {_promo_date_range_days} days. "
                        f"For the best insights, select the full season "
                        f"(September\u2013April)."
                    )
                 else:

                    coupon_count = len(coupon_bookings)
                    total_bookings_count = len(promo_data)
                    coupon_share = (
                        coupon_count / total_bookings_count * 100
                        if total_bookings_count > 0 else 0
                    )

                    st.info(
                        f"**{format_number(coupon_count)} free sessions given away this season** "
                        f"({f'{coupon_share:.1f}%'.replace('.', ',')} of all bookings). Each free session "
                        f"costs ~{format_euro(avg_without, 2)} in forgone revenue "
                        f"(the full-price average). Total cost: "
                        f"~{format_euro(coupon_count * avg_without)}.\n\n"
                        f"**Are they worth it?** The ROI depends on whether "
                        f"coupon users return for paid visits. Cross-reference "
                        f"coupon user emails in BigQuery with repeat bookings "
                        f"on the Customers page. If return rate is low, consider "
                        f"replacing free coupons with discount coupons (e.g. 50% off) "
                        f"to reduce cost while still driving trial."
                    )




render_footer()
