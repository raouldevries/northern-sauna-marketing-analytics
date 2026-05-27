"""
Northern Sauna Analytics - Bookings Page
Lead time distribution, heatmaps, location breakdown, and temperature analysis
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import numpy as np
from datetime import timedelta
import sys
sys.path.insert(0, '..')
from bq_data_loader import (
    init_session_state, render_bookeo_settings,
    calculate_distribution_data, calculate_location_stats,
    calculate_heatmap_data, process_booking_data,
    add_temperature_to_bookings,
)
from data.queries import _query_bookings, _transform_bq_to_bookeo_format
from features.revenue.formatters import format_number  # noqa: E402
from components.demo_banner import render_demo_banner, render_footer  # noqa: E402
from utils import render_header, render_sidebar_nav

# Page configuration
st.set_page_config(
    page_title="Northern Sauna - Bookings",
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
/* Hide "Press Enter to apply" tooltip on text inputs */
[data-testid="InputInstructions"] {
    display: none;
}
</style>
"""
st.markdown(hide_default_nav, unsafe_allow_html=True)

render_header()

# BigQuery data settings (under header)
render_bookeo_settings(page_key="booking_patterns")

st.markdown("## Bookings")

# Initialize session state using centralized function
init_session_state()

# Check authentication
if not st.session_state.get('authenticated', False):
    st.warning("Please log in to access this page.")
    st.page_link("app.py", label="Go to Login", icon=":material/login:")
    st.stop()

render_sidebar_nav("Bookings", ["Lead Time", "Timing", "Weather"])

render_demo_banner()

# Standard column names from BigQuery (no manual mapping needed)
if st.session_state.df1 is not None and st.session_state.df2 is not None:
    df1 = st.session_state.df1
    df2 = st.session_state.df2

    # Standard column names from BigQuery
    id_col_1 = "Booking number"
    date_col_1 = "Created"
    id_col_2 = "Booking number"
    visit_col_2 = "Start"
    location_col = "Location" if "Location" in df1.columns else "None"
    email_col = "Email address" if "Email address" in df1.columns else "None"

    # Process the data
    with st.spinner("Processing data..."):
        processed_data, unmatched, invalid, negative = process_booking_data(
            df1, df2, id_col_1, date_col_1, id_col_2, visit_col_2, location_col
        )

    # Check if we have data to display
    if len(processed_data) == 0:
        st.error("No matching booking IDs found between files. Please check your column selections.")
    else:
        # Use all data (no location filtering on this page)
        filtered_data = processed_data.copy()

        # Calculate metrics
        if len(filtered_data) > 0:
            avg_interval = filtered_data['interval_days'].mean()
            median_interval = filtered_data['interval_days'].median()
            total_bookings = len(filtered_data)
            same_day_pct = (filtered_data['interval_days'] == 0).sum() / total_bookings * 100

            # Date range for takeaway titles
            _bp_date_from = filtered_data['visit_date'].min().strftime("%-d %b %Y")
            _bp_date_to = filtered_data['visit_date'].max().strftime("%-d %b %Y")
            takeaway_title = f"Key Takeaways ({_bp_date_from} \u2013 {_bp_date_to})"
            _bp_date_range_days = (
                filtered_data['visit_date'].max() - filtered_data['visit_date'].min()
            ).days
            MIN_DAYS_FOR_TAKEAWAYS = 90
            show_takeaways = _bp_date_range_days >= MIN_DAYS_FOR_TAKEAWAYS

            # ============== Tabbed Layout ==============
            has_location = location_col != "None" and 'location' in filtered_data.columns and filtered_data['location'].notna().any()

            tab_lead_time, tab_timing, tab_weather = st.tabs(["Lead Time", "Timing", "Weather"])

            # ---- Tab 1: Lead Time ----
            with tab_lead_time:
                # Key metrics for lead time
                max_interval = filtered_data['interval_days'].max()
                col1, col2, col3, col4, col5 = st.columns(5)

                with col1:
                    st.metric(
                        "Average Lead Time",
                        f"{avg_interval:.1f} days",
                        help="Mean number of days between booking creation and visit date."
                    )

                with col2:
                    st.metric(
                        "Median Lead Time",
                        f"{median_interval:.1f} days",
                        help="Middle value of lead times. Less affected by outliers than average."
                    )

                with col3:
                    st.metric(
                        "Max Lead Time",
                        f"{max_interval:.0f} days",
                        help="Longest lead time in the dataset. Shows how far ahead some customers book."
                    )

                with col4:
                    st.metric(
                        "Total Bookings",
                        format_number(total_bookings),
                        help="Total number of successfully matched bookings in the dataset."
                    )

                with col5:
                    st.metric(
                        "Same-Day Bookings",
                        f"{same_day_pct:.1f}%",
                        help="Percentage of bookings made on the same day as the visit."
                    )

                with st.expander("How to interpret these metrics", expanded=False):
                    st.markdown("""
                    **The date range filters by visit date** (when the customer visits), not by booking creation date.

                    This means:
                    - Selecting "Jan 1 - Mar 1" shows all bookings **for visits** in that period
                    - These customers may have booked days, weeks, or months before their visit
                    - Lead time = visit date - booking date

                    **Example:** If someone booked on Dec 1 for a visit on Jan 7, the lead time is 37 days.

                    This view answers: *"What's the booking behavior of customers who booked during this period?"*
                    - A high lead time means customers are planning ahead
                    - A low lead time (or high same-day %) means spontaneous bookings
                    """)

                    # Outlier analysis
                    max_lead = filtered_data['interval_days'].max()
                    p95_lead = filtered_data['interval_days'].quantile(0.95)
                    p99_lead = filtered_data['interval_days'].quantile(0.99)
                    over_30_days = (filtered_data['interval_days'] > 30).sum()
                    over_60_days = (filtered_data['interval_days'] > 60).sum()
                    over_90_days = (filtered_data['interval_days'] > 90).sum()

                    st.markdown("---")
                    st.markdown("**Lead Time Outlier Analysis:**")
                    st.markdown(f"""
                    | Metric | Value |
                    |--------|-------|
                    | Maximum Lead Time | **{max_lead:.0f} days** |
                    | 95th Percentile | {p95_lead:.0f} days |
                    | 99th Percentile | {p99_lead:.0f} days |
                    | Bookings > 30 days | {format_number(over_30_days)} ({over_30_days/total_bookings*100:.1f}%) |
                    | Bookings > 60 days | {format_number(over_60_days)} ({over_60_days/total_bookings*100:.1f}%) |
                    | Bookings > 90 days | {format_number(over_90_days)} ({over_90_days/total_bookings*100:.1f}%) |
                    """)

                    st.markdown("---")
                    st.markdown(
                        f"{format_number(unmatched)} unmatched (likely cancelled bookings) | "
                        f"{format_number(invalid)} invalid dates | {format_number(negative)} negative intervals"
                    )
                # Distribution chart
                distribution, distribution_pct = calculate_distribution_data(
                    tuple(filtered_data['interval_category'].tolist())
                )

                text_labels = [f"{pct}%" for pct in distribution_pct.values]

                fig_dist = px.bar(
                    x=distribution_pct.index,
                    y=distribution_pct.values,
                    labels={'x': 'Lead Time', 'y': 'Percentage of Total Bookings'},
                    title="How far in advance do customers book?"
                )
                fig_dist.update_traces(marker_color='#1f77b4', text=text_labels, textposition='outside')
                fig_dist.update_layout(
                    showlegend=False,
                    height=450,
                    margin=dict(t=50),
                    yaxis=dict(range=[0, max(distribution_pct.values) * 1.2])
                )

                st.plotly_chart(fig_dist, use_container_width=True)

                with st.expander("What does 'Lead Time' mean?", expanded=False):
                    st.markdown("""
                    **Lead time** is the time gap between when a customer makes a booking and when they actually visit.

                    **Examples:**
                    - **0 days (Same-day)**: Customer books today for today's visit
                    - **1 day**: Customer books on Monday for Tuesday
                    - **7 days**: Customer books a week in advance
                    - **14+ days**: Customer books 2+ weeks ahead

                    **Why it matters:**
                    - **Short lead time (0-3 days)**: Spontaneous bookings, requires flexible staffing
                    - **Long lead time (7+ days)**: Planned visits, allows advance scheduling optimization

                    Different locations may show different booking patterns, helping you understand customer behavior per branch.
                    """)

                # --- Booking behavior mix over time ---
                st.markdown("#### How is booking behavior changing?")

                # Location filter
                if has_location:
                    trend_locations = ['All Locations'] + sorted(
                        filtered_data['location'].dropna().unique().tolist()
                    )
                    selected_trend_location = st.selectbox(
                        "Select Location",
                        options=trend_locations,
                        index=0,
                        key="lead_time_trend_location",
                    )
                    if selected_trend_location == 'All Locations':
                        trend_df = filtered_data.copy()
                    else:
                        trend_df = filtered_data[
                            filtered_data['location'] == selected_trend_location
                        ].copy()
                else:
                    trend_df = filtered_data.copy()
                trend_df['month'] = trend_df['visit_date'].dt.to_period('M').dt.to_timestamp()

                # Exclude current incomplete month
                current_month = pd.Timestamp.now().to_period('M').to_timestamp()
                trend_df = trend_df[trend_df['month'] < current_month]

                if len(trend_df) > 0 and trend_df['month'].nunique() > 1:
                    category_order = ["Same day", "1-3 days", "4-7 days", "1-2 weeks", "2+ weeks"]
                    category_colors = {
                        "Same day": "#e74c3c",
                        "1-3 days": "#f39c12",
                        "4-7 days": "#3498db",
                        "1-2 weeks": "#2ecc71",
                        "2+ weeks": "#9b59b6",
                    }

                    # Count per month per category, then convert to %
                    monthly_cats = trend_df.groupby(['month', 'interval_category']).size().reset_index(name='count')
                    monthly_totals = monthly_cats.groupby('month')['count'].sum().reset_index(name='total')
                    monthly_cats = monthly_cats.merge(monthly_totals, on='month')
                    monthly_cats['pct'] = (monthly_cats['count'] / monthly_cats['total'] * 100).round(1)

                    # Ensure all categories exist for each month
                    monthly_cats['interval_category'] = pd.Categorical(
                        monthly_cats['interval_category'],
                        categories=category_order,
                        ordered=True,
                    )

                    fig_mix = px.area(
                        monthly_cats.sort_values(['month', 'interval_category']),
                        x='month',
                        y='pct',
                        color='interval_category',
                        category_orders={'interval_category': category_order},
                        color_discrete_map=category_colors,
                        labels={
                            'month': 'Month',
                            'pct': '% of Bookings',
                            'interval_category': 'Lead Time',
                        },
                        groupnorm='',
                    )
                    fig_mix.update_layout(
                        height=400,
                        margin=dict(t=20),
                        yaxis=dict(title='% of Bookings', range=[0, 100]),
                        legend=dict(
                            orientation='h',
                            yanchor='bottom',
                            y=1.02,
                            xanchor='right',
                            x=1,
                            title=None,
                        ),
                        hovermode='x unified',
                        plot_bgcolor='rgba(0,0,0,0)',
                    )
                    st.plotly_chart(fig_mix, use_container_width=True)

                    st.caption(
                        "Shows how the mix of same-day vs planned bookings changes over time. "
                        "If the red area (same-day) is growing, customers are becoming more spontaneous."
                    )
                else:
                    st.caption("Select a date range spanning 2+ months to see booking behavior trends.")

                # --- Location breakdown ---
                if has_location:
                    st.markdown("#### Breakdown by Location")
                    st.markdown("Compare booking behavior across different locations.")

                    with st.expander("Understanding Average vs Median", expanded=False):
                        st.markdown("""
                        - **Average** - Includes all bookings, including customers who book far in advance (e.g., 30 days ahead)
                        - **Median** - Shows what a typical customer actually does, ignoring extreme values

                        **Example:** If most customers book 0-2 days ahead, but a few book 30 days ahead:
                        - Average might be 5 days (pulled up by advance planners)
                        - Median would be 1 day (the typical customer)

                        **What to look for:** A large gap between Average and Median means you have mostly last-minute bookers
                        with some advance planners. A small gap means consistent booking behavior.
                        """)

                    location_stats = calculate_location_stats(
                        tuple(filtered_data.index.tolist()),
                        tuple(filtered_data['location'].tolist()),
                        tuple(filtered_data['interval_days'].tolist())
                    )

                    location_stats_config = {
                        'Total Bookings': st.column_config.NumberColumn('Total Bookings', help='Number of bookings for this location'),
                        'Avg Lead Time (days)': st.column_config.NumberColumn('Avg Lead Time (days)', help='Average days between booking and visit'),
                        'Median Lead Time (days)': st.column_config.NumberColumn('Median Lead Time (days)', help='Typical days between booking and visit (ignoring outliers)'),
                        'Same-Day %': st.column_config.NumberColumn('Same-Day %', help='Percentage of bookings made on the day of the visit', format="%.1f%%"),
                    }
                    st.dataframe(location_stats, use_container_width=True, column_config=location_stats_config)

                # --- Key Takeaways toggle ---
                with st.expander(takeaway_title):
                 if not show_takeaways:
                    st.caption(
                        f"Select at least 3 months of data for meaningful takeaways. "
                        f"Current range: {_bp_date_range_days} days. "
                        f"For the best insights, select the full season "
                        f"(September\u2013April)."
                    )
                 else:

                    # 1. Marketing decision window
                    short_lead = (filtered_data['interval_days'] <= 3).sum()
                    short_lead_pct = short_lead / total_bookings * 100
                    week_lead = (filtered_data['interval_days'] <= 7).sum()
                    week_lead_pct = week_lead / total_bookings * 100

                    st.info(
                        f"**{short_lead_pct:.0f}% of bookings are made within 3 days "
                        f"of the visit** ({week_lead_pct:.0f}% within a week). "
                        f"Your marketing needs to trigger same-week decisions, not "
                        f"next-month planning. Email campaigns should go out "
                        f"Monday\u2013Tuesday to capture the week's bookings. "
                        f"Promoting events 2+ weeks ahead will only reach the "
                        f"{100 - week_lead_pct:.0f}% who plan that far."
                    )

                    # 2. Spontaneity trend (if enough months)
                    if 'month' not in filtered_data.columns:
                        filtered_data_trend = filtered_data.copy()
                        filtered_data_trend['month'] = filtered_data_trend['visit_date'].dt.to_period('M').dt.to_timestamp()
                    else:
                        filtered_data_trend = filtered_data

                    monthly_same_day = filtered_data_trend.groupby(
                        filtered_data_trend['visit_date'].dt.to_period('M')
                    ).apply(
                        lambda g: (g['interval_days'] == 0).mean() * 100
                    )
                    if len(monthly_same_day) >= 3:
                        first_half_sd = monthly_same_day.iloc[:len(monthly_same_day) // 2].mean()
                        second_half_sd = monthly_same_day.iloc[len(monthly_same_day) // 2:].mean()
                        sd_delta = second_half_sd - first_half_sd
                        sd_trend = "more" if sd_delta > 0 else "less"

                        if abs(sd_delta) >= 2:
                            st.info(
                                f"**Customers are becoming {sd_trend} spontaneous.** "
                                f"Same-day bookings moved from **{first_half_sd:.0f}%** "
                                f"to **{second_half_sd:.0f}%** over the season. "
                                + (
                                    "As the season progresses, customers book more "
                                    "last-minute. Ensure same-day availability stays "
                                    "visible on your booking page."
                                    if sd_delta > 0
                                    else "Customers are planning further ahead later "
                                    "in the season \u2014 good for predictability, "
                                    "but ensure advance booking is easy and visible."
                                )
                            )

                    # 3. Location spread in lead time
                    if has_location:
                        loc_same_day = filtered_data.groupby('location').apply(
                            lambda g: (g['interval_days'] == 0).mean() * 100
                        ).sort_values(ascending=False)

                        if len(loc_same_day) >= 2:
                            highest_sd_loc = loc_same_day.index[0].replace("Northern Sauna ", "")
                            highest_sd_pct = loc_same_day.iloc[0]
                            lowest_sd_loc = loc_same_day.index[-1].replace("Northern Sauna ", "")
                            lowest_sd_pct = loc_same_day.iloc[-1]
                            sd_spread = highest_sd_pct - lowest_sd_pct

                            if sd_spread >= 5:
                                st.info(
                                    f"**Booking behaviour varies by location.** "
                                    f"**{highest_sd_loc}** has **{highest_sd_pct:.0f}%** "
                                    f"same-day bookings vs **{lowest_sd_pct:.0f}%** at "
                                    f"**{lowest_sd_loc}** \u2014 a {sd_spread:.0f} pp "
                                    f"(percentage point) spread. Locations with high "
                                    f"spontaneous bookings need real-time availability "
                                    f"on the booking page; locations with planners "
                                    f"benefit from advance promotions."
                                )


            # ---- Tab 2: Timing ----
            with tab_timing:
                if has_location:
                    # Location filter for heatmap
                    heatmap_locations = ['All Locations'] + sorted(filtered_data['location'].dropna().unique().tolist())
                    selected_heatmap_location = st.selectbox(
                        "Select Location",
                        options=heatmap_locations,
                        index=0,
                        key="booking_heatmap_location_filter"
                    )

                    # Filter data based on location selection
                    if selected_heatmap_location == 'All Locations':
                        heatmap_hours = filtered_data['booking_hour'].tolist()
                        heatmap_dows = filtered_data['booking_dow'].tolist()
                    else:
                        loc_mask = filtered_data['location'] == selected_heatmap_location
                        heatmap_hours = filtered_data.loc[loc_mask, 'booking_hour'].tolist()
                        heatmap_dows = filtered_data.loc[loc_mask, 'booking_dow'].tolist()

                    if len(heatmap_hours) > 0:
                        heatmap_pivot, peak_hour, peak_day, evening_pct = calculate_heatmap_data(
                            tuple(heatmap_hours), tuple(heatmap_dows)
                        )

                        # Compute weekend vs weekday split
                        if selected_heatmap_location == 'All Locations':
                            timing_data = filtered_data
                        else:
                            timing_data = filtered_data[filtered_data['location'] == selected_heatmap_location]
                        weekend_mask = timing_data['booking_dow'].isin(['Saturday', 'Sunday'])
                        weekend_pct = weekend_mask.sum() / len(timing_data) * 100 if len(timing_data) > 0 else 0

                        # KPIs at top
                        col1, col2, col3, col4 = st.columns(4)
                        with col1:
                            st.metric("Peak Booking Hour", f"{peak_hour}:00")
                        with col2:
                            st.metric("Peak Booking Day", peak_day)
                        with col3:
                            st.metric("Evening Bookings (18:00+)", f"{evening_pct:.1f}%")
                        with col4:
                            st.metric("Weekend Bookings", f"{weekend_pct:.1f}%",
                                      help="Percentage of bookings created on Saturday or Sunday.")

                        # Heatmap
                        st.markdown("#### When Do Customers Book?")

                        heatmap_display = heatmap_pivot.replace(0, np.nan)

                        fig_heatmap = px.imshow(
                            heatmap_display,
                            labels=dict(x='Day of Week', y='Hour of Day', color='Bookings'),
                            aspect='auto',
                            color_continuous_scale='YlOrRd'
                        )
                        fig_heatmap.update_yaxes(tickvals=list(range(0, 24, 2)))
                        st.plotly_chart(fig_heatmap, use_container_width=True)

                        with st.expander("Marketing Insight: How to use this data", expanded=False):
                            st.markdown("""
                            **This heatmap reveals when customers actually make booking decisions**, which directly impacts how you should schedule and allocate marketing spend.

                            | Booking Pattern | Marketing Action |
                            |-----------------|------------------|
                            | **Peak booking hours** | Increase ad bids during these hours, ensure ads are running |
                            | **Peak booking days** | Allocate more daily budget to these days |
                            | **Low activity periods** | Reduce ad spend, avoid wasting budget |
                            | **High evening bookings** | Schedule Meta/Google ads for evening delivery |

                            **Practical Applications:**
                            - **Google Ads**: Use ad scheduling to increase bids +20-30% during peak booking hours
                            - **Meta Ads**: Set dayparting to prioritize delivery when customers are actively booking
                            - **Email campaigns**: Send marketing emails to arrive 1-2 hours before peak booking times
                            - **Customer support**: Staff live chat during high-booking periods to capture conversions

                            **Example:** If peak booking is Sunday at 20:00 with 45% evening bookings → Schedule ads heavily for Sunday evenings, reduce weekday morning spend, and optimize checkout for mobile (evening = phone users).
                            """)

                        # Same-day booking by hour
                        same_day_data = timing_data[timing_data['interval_days'] == 0]
                        if len(same_day_data) > 10:
                            st.markdown("#### When Do Same-Day Bookers Book?")
                            st.caption("Distribution of booking creation hour for customers who book and visit on the same day.")

                            hourly_counts = same_day_data.groupby('booking_hour').size().reindex(range(24), fill_value=0)
                            hourly_df = pd.DataFrame({
                                'Hour': [f"{h}:00" for h in range(24)],
                                'Bookings': hourly_counts.values,
                            })
                            # Find peak hour for same-day
                            peak_sd_hour = hourly_counts.idxmax()
                            peak_sd_count = hourly_counts.max()
                            total_sd = hourly_counts.sum()
                            morning_pct = hourly_counts[6:12].sum() / total_sd * 100
                            afternoon_pct = hourly_counts[12:18].sum() / total_sd * 100

                            fig_sd = px.bar(
                                hourly_df,
                                x='Hour',
                                y='Bookings',
                                labels={'Bookings': 'Same-Day Bookings'},
                            )
                            fig_sd.update_traces(marker_color='#ff7f0e')
                            fig_sd.update_layout(
                                height=300,
                                margin=dict(t=20, b=40),
                                xaxis=dict(tickangle=-45, dtick=2),
                            )
                            st.plotly_chart(fig_sd, use_container_width=True)

                            col_a, col_b, col_c = st.columns(3)
                            with col_a:
                                st.metric("Peak Same-Day Hour", f"{peak_sd_hour}:00")
                            with col_b:
                                st.metric("Morning (6-12h)", f"{morning_pct:.0f}%")
                            with col_c:
                                st.metric("Afternoon (12-18h)", f"{afternoon_pct:.0f}%")

                        # --- Key Takeaways toggle ---
                        with st.expander(takeaway_title):
                         if not show_takeaways:
                            st.caption(
                                f"Select at least 3 months of data for meaningful takeaways. "
                                f"Current range: {_bp_date_range_days} days. "
                                f"For the best insights, select the full season "
                                f"(September\u2013April)."
                            )
                         else:

                            # 1. Ad spend timing window
                            st.info(
                                f"**Peak booking time: {peak_day} at {peak_hour}:00.** "
                                f"**{evening_pct:.0f}%** of booking decisions happen "
                                f"after 18:00 (evening). Focus ad delivery and email "
                                f"sends around this peak window. Reducing ad spend "
                                f"outside peak hours could save budget without "
                                f"losing bookings."
                            )

                            # 2. Weekend booking creation
                            st.info(
                                f"**{weekend_pct:.0f}% of bookings are created on "
                                f"weekends.** "
                                + (
                                    "Weekend is prime booking time \u2014 ensure ads "
                                    "run at full budget on Saturday and Sunday. "
                                    "Customers are in leisure mode and making plans."
                                    if weekend_pct >= 30
                                    else "Most booking decisions happen on weekdays. "
                                    "Focus ad budget Monday\u2013Friday and consider "
                                    "reducing weekend spend."
                                )
                            )

                            # 3. Same-day booking morning window
                            if len(same_day_data) > 10:
                                st.info(
                                    f"**Same-day bookers decide early:** "
                                    f"**{morning_pct:.0f}%** book in the morning "
                                    f"(6:00\u201312:00), **{afternoon_pct:.0f}%** in "
                                    f"the afternoon. A well-timed push notification or "
                                    f"social post at **{peak_sd_hour}:00** "
                                    f"could capture undecided customers before they "
                                    f"make other plans."
                                )

                else:
                    st.info("Location data is required for the booking timing heatmap.")


            # ---- Tab 3: Weather ----
            with tab_weather:
                # Use 12 months of data for weather (not the UI date range)
                end_dt_weather = pd.Timestamp(st.session_state.bookeo_end_date)
                start_dt_weather = end_dt_weather - timedelta(days=365)
                with st.spinner("Loading weather data (last 12 months)..."):
                    weather_bq = _query_bookings(
                        start_dt_weather.strftime("%Y-%m-%d"),
                        end_dt_weather.strftime("%Y-%m-%d"),
                        include_canceled=True,
                        date_column="visit_datetime",
                    )
                    weather_df1, weather_df2 = _transform_bq_to_bookeo_format(weather_bq)
                    weather_processed, _, _, _ = process_booking_data(
                        weather_df1, weather_df2,
                        id_col_1, date_col_1, id_col_2, visit_col_2, location_col,
                    )
                    data_with_temp = add_temperature_to_bookings(weather_processed)

                st.caption(
                    f"Based on the 12 months up to {end_dt_weather.strftime('%d %b %Y')}, "
                    "not the selected date range."
                )

                if 'temperature' in data_with_temp.columns and data_with_temp['temperature'].notna().any():
                    has_rain_data = data_with_temp['has_rain_data'].iloc[0] if 'has_rain_data' in data_with_temp.columns else False

                    # Add month column for later use
                    data_with_temp['month'] = data_with_temp['booking_date'].dt.strftime('%B')

                    # --- Location filter for weather ---
                    weather_has_location = 'location' in data_with_temp.columns and data_with_temp['location'].notna().any()
                    if weather_has_location:
                        weather_locations = ['All Locations'] + sorted(
                            data_with_temp['location'].dropna().unique().tolist()
                        )
                        selected_weather_location = st.selectbox(
                            "Select Location",
                            options=weather_locations,
                            index=0,
                            key="weather_location_filter",
                        )
                        if selected_weather_location != 'All Locations':
                            data_with_temp = data_with_temp[
                                data_with_temp['location'] == selected_weather_location
                            ].copy()

                    # --- Pre-compute weather impact data (needed for KPIs above charts) ---
                    min_days_threshold = 7
                    daily_bookings = None
                    condition_deviation = None
                    weather_colors = {}

                    if has_rain_data:
                        daily_bookings = data_with_temp.groupby('booking_date_only').agg({
                            'booking_id': 'count',
                            'temperature': 'first',
                            'rain_sum': 'first',
                            'snowfall_sum': 'first',
                            'weather_condition': 'first',
                        }).rename(columns={'booking_id': 'daily_bookings'})

                        daily_bookings['month'] = pd.to_datetime(daily_bookings.index).month
                        monthly_avg = daily_bookings.groupby('month')['daily_bookings'].mean()
                        daily_bookings['monthly_avg'] = daily_bookings['month'].map(monthly_avg)
                        daily_bookings['pct_vs_month'] = ((daily_bookings['daily_bookings'] / daily_bookings['monthly_avg']) - 1) * 100

                        condition_deviation = daily_bookings.groupby('weather_condition', observed=True).agg({
                            'pct_vs_month': 'mean',
                            'daily_bookings': ['mean', 'count'],
                            'temperature': 'mean',
                        })
                        condition_deviation.columns = ['% vs Monthly Avg', 'Avg Daily Bookings', 'Number of Days', 'Avg Temp (°C)']
                        condition_deviation = condition_deviation.round(1).reset_index()

                        total_days = condition_deviation['Number of Days'].sum()
                        condition_deviation['% of Days'] = (condition_deviation['Number of Days'] / total_days * 100).round(1)
                        condition_deviation['label'] = condition_deviation.apply(
                            lambda row: f"{row['weather_condition']}<br>({row['% vs Monthly Avg']:+.0f}%)", axis=1
                        )

                        weather_colors = {
                            'Snow': '#a8d8ea', 'Cold & Rainy': '#3b7dd8',
                            'Cold & Dry': '#6baed6', 'Mild & Rainy': '#74c476',
                            'Mild & Dry': '#31a354', 'Warm': '#fd8d3c',
                        }
                        condition_deviation['color'] = [weather_colors.get(str(c), '#1f77b4') for c in condition_deviation['weather_condition']]

                        # KPI values
                        rainy_mask = daily_bookings['rain_sum'] > 1
                        rainy_dev = daily_bookings.loc[rainy_mask, 'pct_vs_month'].mean() if rainy_mask.any() else 0
                        dry_dev = daily_bookings.loc[~rainy_mask, 'pct_vs_month'].mean() if (~rainy_mask).any() else 0

                        cold_mask = daily_bookings['temperature'] < 10
                        warm_mask = daily_bookings['temperature'] > 18
                        cold_dev = daily_bookings.loc[cold_mask, 'pct_vs_month'].mean() if cold_mask.any() else 0

                        # Best and worst weather
                        best_row = condition_deviation.loc[condition_deviation['% vs Monthly Avg'].idxmax()]
                        best_condition = str(best_row['weather_condition'])
                        best_pct = best_row['% vs Monthly Avg']

                        worst_row = condition_deviation.loc[condition_deviation['% vs Monthly Avg'].idxmin()]
                        worst_condition = str(worst_row['weather_condition'])
                        worst_pct = worst_row['% vs Monthly Avg']

                        # Rain effect label
                        rain_label = "Yes" if rainy_dev > 0 else "No"
                        rain_delta = f"{rainy_dev:+.1f}% bookings"

                        # Extra revenue on best weather days
                        avg_daily_bookings = daily_bookings['daily_bookings'].mean()
                        best_avg_daily = best_row['Avg Daily Bookings']
                        extra_bookings = best_avg_daily - avg_daily_bookings
                        # Estimate avg booking value from total data
                        if 'Total paid' in weather_df2.columns:
                            avg_bv = pd.to_numeric(weather_df2['Total paid'], errors='coerce').mean()
                        else:
                            avg_bv = 25  # fallback
                        extra_revenue = extra_bookings * avg_bv

                        # --- Display KPIs ---
                        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
                        with kpi1:
                            st.metric(
                                "Busiest Weather",
                                best_condition,
                                delta=f"{best_pct:+.1f}% more bookings",
                                help=f"Weather condition with the most bookings vs monthly average. {best_row['Number of Days']:.0f} days of data.",
                            )
                        with kpi2:
                            st.metric(
                                "Quietest Weather",
                                worst_condition,
                                delta=f"{worst_pct:+.1f}% bookings",
                                delta_color="inverse",
                                help=f"Weather condition with the fewest bookings vs monthly average. {worst_row['Number of Days']:.0f} days of data.",
                            )
                        with kpi3:
                            st.metric(
                                "Rain = More Bookings?",
                                rain_label,
                                delta=rain_delta,
                                help="Do rainy days (>1mm rainfall) bring more or fewer bookings than dry days?",
                            )
                        with kpi4:
                            st.metric(
                                f"Extra Revenue per {best_condition} Day",
                                f"\u20ac{extra_revenue:+,.0f}",
                                help=f"Estimated extra turnover on a {best_condition} day vs an average day. Based on {extra_bookings:+.0f} extra bookings \u00d7 \u20ac{avg_bv:.0f} avg booking value.",
                            )

                    # --- Monthly bookings + temperature trend ---
                    import plotly.graph_objects as go

                    data_with_temp['year_month'] = data_with_temp['booking_date'].dt.to_period('M').dt.to_timestamp()
                    monthly_weather = data_with_temp.groupby('year_month').agg(
                        bookings=('booking_id', 'count'),
                        avg_temp=('temperature', 'mean'),
                    ).reset_index().sort_values('year_month')

                    # Exclude current incomplete month
                    current_month = pd.Timestamp.now().to_period('M').to_timestamp()
                    monthly_weather = monthly_weather[monthly_weather['year_month'] < current_month]

                    if len(monthly_weather) > 1:
                        fig_monthly = go.Figure()

                        fig_monthly.add_trace(go.Bar(
                            x=monthly_weather['year_month'],
                            y=monthly_weather['bookings'],
                            name='Bookings',
                            marker_color='#3498db',
                            opacity=0.7,
                            yaxis='y',
                            hovertemplate='%{y:,} bookings<extra></extra>',
                        ))

                        fig_monthly.add_trace(go.Scatter(
                            x=monthly_weather['year_month'],
                            y=monthly_weather['avg_temp'],
                            name='Avg Temperature',
                            mode='lines+markers',
                            line=dict(color='#e67e22', width=2.5),
                            marker=dict(size=6),
                            yaxis='y2',
                            hovertemplate='%{y:.1f}°C<extra></extra>',
                        ))

                        fig_monthly.update_layout(
                            title='Monthly Bookings & Temperature',
                            height=400,
                            margin=dict(t=50, b=40),
                            yaxis=dict(
                                title='Bookings',
                                rangemode='tozero',
                                showgrid=True,
                                gridcolor='rgba(0,0,0,0.06)',
                            ),
                            yaxis2=dict(
                                title='Avg Temperature (\u00b0C)',
                                overlaying='y',
                                side='right',
                                showgrid=False,
                            ),
                            hovermode='x unified',
                            legend=dict(
                                orientation='h',
                                yanchor='bottom',
                                y=1.02,
                                xanchor='right',
                                x=1,
                            ),
                            plot_bgcolor='rgba(0,0,0,0)',
                        )

                        st.plotly_chart(fig_monthly, use_container_width=True)

                        st.caption(
                            "Blue bars = total bookings per month. "
                            "Orange line = average daily temperature. "
                            "Notice how bookings peak in colder months "
                            "\u2014 the bar chart below isolates the weather "
                            "effect from this seasonal pattern."
                        )

                    # --- Bar chart: Weather Impact (seasonality-controlled) ---
                    if has_rain_data:
                        st.markdown("#### Which weather drives more bookings?")

                        bar_data = condition_deviation[['weather_condition', '% vs Monthly Avg', 'Number of Days']].copy()
                        bar_data.columns = ['Weather Condition', '% vs Monthly Avg', 'Number of Days']
                        bar_data = bar_data.sort_values('% vs Monthly Avg', ascending=True)

                        bar_text = [f"{v:+.1f}%" for v in bar_data['% vs Monthly Avg']]
                        bar_colors = [
                            '#2ecc71' if v > 0 else '#e74c3c'
                            for v in bar_data['% vs Monthly Avg']
                        ]

                        fig_bar = px.bar(
                            bar_data,
                            y='Weather Condition',
                            x='% vs Monthly Avg',
                            text=bar_text,
                            orientation='h',
                            hover_data={'Number of Days': ':,'},
                            title=None,
                        )
                        fig_bar.update_traces(
                            marker_color=bar_colors,
                            textposition='outside',
                        )
                        fig_bar.add_vline(x=0, line_dash="dash", line_color="gray")
                        x_abs_max = max(
                            abs(bar_data['% vs Monthly Avg'].min()),
                            abs(bar_data['% vs Monthly Avg'].max()),
                        )
                        x_pad = max(x_abs_max * 0.3, 5)
                        fig_bar.update_layout(
                            height=max(300, len(bar_data) * 50 + 100),
                            margin=dict(t=50, r=80),
                            xaxis=dict(
                                title='% more or fewer bookings than average',
                                range=[-(x_abs_max + x_pad), x_abs_max + x_pad],
                            ),
                            yaxis_title="",
                            showlegend=False,
                        )
                        st.plotly_chart(fig_bar, use_container_width=True)

                        st.caption(
                            "Each bar shows how many more (or fewer) bookings "
                            "happen on days with that weather, compared to the "
                            "monthly average. This removes seasonal effects \u2014 "
                            "a +10% means 10% more bookings than other days in "
                            "the same month."
                        )

                    elif not has_rain_data:
                        # Fallback: temperature-only bar chart
                        daily_by_date = data_with_temp.groupby('booking_date_only').agg({
                            'booking_id': 'count',
                            'temp_category': 'first',
                            'temperature': 'first',
                        }).rename(columns={'booking_id': 'daily_bookings'})

                        daily_by_date['month'] = pd.to_datetime(daily_by_date.index).month
                        monthly_avg_fb = daily_by_date.groupby('month')['daily_bookings'].mean()
                        daily_by_date['monthly_avg'] = daily_by_date['month'].map(monthly_avg_fb)
                        daily_by_date['pct_vs_month'] = ((daily_by_date['daily_bookings'] / daily_by_date['monthly_avg']) - 1) * 100

                        temp_deviation = daily_by_date.groupby('temp_category', observed=True).agg({
                            'pct_vs_month': 'mean',
                            'daily_bookings': 'count',
                            'temperature': 'mean',
                        })
                        temp_deviation.columns = ['% vs Monthly Avg', 'Number of Days', 'Avg Temp (°C)']
                        temp_deviation = temp_deviation.round(1).reset_index()
                        temp_deviation = temp_deviation.sort_values('% vs Monthly Avg', ascending=True)

                        bar_text_fb = [f"{v:+.1f}%" for v in temp_deviation['% vs Monthly Avg']]
                        bar_colors_fb = [
                            '#2ecc71' if v > 0 else '#e74c3c'
                            for v in temp_deviation['% vs Monthly Avg']
                        ]

                        fig_bar_fb = px.bar(
                            temp_deviation,
                            y='temp_category',
                            x='% vs Monthly Avg',
                            text=bar_text_fb,
                            orientation='h',
                            hover_data={'Number of Days': ':,'},
                            title="Which temperature drives more bookings?",
                        )
                        fig_bar_fb.update_traces(
                            marker_color=bar_colors_fb,
                            textposition='outside',
                        )
                        fig_bar_fb.add_vline(x=0, line_dash="dash", line_color="gray")
                        fig_bar_fb.update_layout(
                            height=max(300, len(temp_deviation) * 50 + 100),
                            margin=dict(t=50, r=80),
                            xaxis_title='% more or fewer bookings than average',
                            yaxis_title="",
                            showlegend=False,
                        )
                        st.plotly_chart(fig_bar_fb, use_container_width=True)

                        st.caption(
                            "Each bar shows how many more (or fewer) bookings "
                            "happen on days with that temperature, compared to "
                            "the monthly average."
                        )

                    # --- Breakdown table ---
                    if has_rain_data:
                        st.markdown("#### Weather Breakdown")

                        table_data = condition_deviation[['weather_condition', 'Avg Daily Bookings', '% vs Monthly Avg', 'Number of Days']].copy()

                        # Add common months from booking-level data
                        common_months = []
                        for condition in table_data['weather_condition']:
                            cond_data = data_with_temp[data_with_temp['weather_condition'] == condition]
                            month_counts = cond_data['month'].value_counts()
                            if len(month_counts) > 0:
                                top_months = month_counts.head(2).index.tolist()
                                common_months.append(', '.join(top_months))
                            else:
                                common_months.append('N/A')
                        table_data['Common Months'] = common_months

                        # Format columns
                        table_data['vs Average'] = table_data['% vs Monthly Avg'].apply(lambda x: f"{x:+.1f}%")
                        table_data['Avg Daily Bookings'] = table_data['Avg Daily Bookings'].apply(lambda x: f"{x:.0f}")

                        table_data = table_data.rename(columns={'weather_condition': 'Weather'})
                        table_data = table_data.set_index('Weather')
                        table_data = table_data[['Avg Daily Bookings', 'vs Average', 'Common Months', 'Number of Days']]

                        weather_stats_config = {
                            'Avg Daily Bookings': st.column_config.TextColumn('Avg Daily Bookings', help='Average bookings per day with this weather'),
                            'vs Average': st.column_config.TextColumn('vs Average', help='% more or fewer bookings than the monthly average'),
                            'Common Months': st.column_config.TextColumn('When to Expect', help='Months when this weather is most common'),
                            'Number of Days': st.column_config.NumberColumn('Days of Data', help='How many days of this weather type in the period'),
                        }
                        st.dataframe(table_data, use_container_width=True, column_config=weather_stats_config)

                    else:
                        # Fallback: temperature-only breakdown table
                        st.markdown("#### Temperature Breakdown")

                        temp_stats = data_with_temp.groupby('temp_category', observed=True).agg({
                            'booking_id': 'count',
                            'interval_days': ['mean', 'median'],
                            'temperature': 'mean'
                        }).round(1)

                        temp_stats.columns = ['Bookings', 'Avg Lead Time', 'Median Lead Time', 'Avg Temp (°C)']

                        common_months = []
                        for category in temp_stats.index:
                            category_data = data_with_temp[data_with_temp['temp_category'] == category]
                            month_counts = category_data['month'].value_counts()
                            if len(month_counts) > 0:
                                top_months = month_counts.head(2).index.tolist()
                                common_months.append(', '.join(top_months))
                            else:
                                common_months.append('N/A')

                        temp_stats['Common Months'] = common_months
                        temp_stats['% of Total'] = (temp_stats['Bookings'] / temp_stats['Bookings'].sum() * 100).round(1)
                        temp_stats = temp_stats[['Bookings', '% of Total', 'Common Months', 'Avg Temp (°C)', 'Avg Lead Time', 'Median Lead Time']]

                        temp_stats_config = {
                            'Bookings': st.column_config.NumberColumn('Bookings', help='Number of bookings in this temperature range'),
                            '% of Total': st.column_config.NumberColumn('% of Total', help='Percentage of all bookings'),
                            'Common Months': st.column_config.TextColumn('Common Months', help='Months when this temperature range is most common'),
                            'Avg Temp (°C)': st.column_config.NumberColumn('Avg Temp (°C)', help='Average temperature at time of booking'),
                            'Avg Lead Time': st.column_config.NumberColumn('Avg Lead Time', help='Average days between booking and visit'),
                            'Median Lead Time': st.column_config.NumberColumn('Median Lead Time', help='Typical days between booking and visit'),
                        }
                        st.dataframe(temp_stats, use_container_width=True, column_config=temp_stats_config)

                    # --- Key Takeaways toggle ---
                    with st.expander(takeaway_title):
                     if not show_takeaways:
                        st.caption(
                            f"Select at least 3 months of data for meaningful takeaways. "
                            f"Current range: {_bp_date_range_days} days. "
                            f"For the best insights, select the full season "
                            f"(September\u2013April)."
                        )
                     else:

                        # 1. Weather is your friend (sauna-specific insight)
                        if has_rain_data and condition_deviation is not None:
                            best_cond = str(best_row['weather_condition'])
                            worst_cond = str(worst_row['weather_condition'])

                            st.info(
                                f"**Bad weather is good for business.** "
                                f"**{best_cond}** days drive **{best_pct:+.1f}%** "
                                f"more bookings than average, while **{worst_cond}** "
                                f"days see **{worst_pct:+.1f}%**. "
                                + (
                                    "Don't cut marketing spend on cold or rainy days "
                                    "\u2014 amplify it. A 'warm up today' push "
                                    "notification on bad weather mornings could "
                                    "capture spontaneous demand."
                                    if best_pct > 0 and ('Cold' in best_cond or 'Rain' in best_cond)
                                    else "Use weather forecasts to adjust your daily "
                                    "marketing spend and staffing levels."
                                )
                            )

                            # 2. Revenue per weather day
                            season_weeks_left = max(0, (
                                pd.Timestamp(f"{pd.Timestamp.now().year}-04-30")
                                - pd.Timestamp.now()
                            ).days // 7)
                            best_days_count = best_row['Number of Days']
                            total_weather_days = condition_deviation['Number of Days'].sum()
                            best_days_pct = best_days_count / total_weather_days * 100

                            st.info(
                                f"**Each {best_cond} day generates "
                                f"~\u20ac{extra_revenue:+,.0f} extra revenue** "
                                f"vs an average day ({extra_bookings:+.0f} extra "
                                f"bookings \u00d7 \u20ac{avg_bv:.0f} avg booking value). "
                                f"{best_cond} conditions occur on "
                                f"**{best_days_pct:.0f}%** of days during the "
                                f"season. Use weather forecasts to prepare: "
                                f"on {best_cond} days, ensure full staffing and "
                                f"consider a same-day social media post."
                            )

                        # 3. Temperature-bookings correlation
                        if len(monthly_weather) > 2:
                            coldest_month = monthly_weather.loc[
                                monthly_weather['avg_temp'].idxmin()
                            ]
                            warmest_month = monthly_weather.loc[
                                monthly_weather['avg_temp'].idxmax()
                            ]

                            st.info(
                                f"**Coldest month "
                                f"({coldest_month['year_month'].strftime('%B')}, "
                                f"{coldest_month['avg_temp']:.0f}\u00b0C) had "
                                f"{format_number(coldest_month['bookings'])} bookings** vs "
                                f"warmest month "
                                f"({warmest_month['year_month'].strftime('%B')}, "
                                f"{warmest_month['avg_temp']:.0f}\u00b0C) with "
                                f"{format_number(warmest_month['bookings'])}. "
                                + (
                                    "Colder months are your peak season \u2014 "
                                    "invest marketing budget heaviest in "
                                    "November\u2013February."
                                    if coldest_month['bookings'] > warmest_month['bookings']
                                    else "Surprisingly, warmer months had more bookings. "
                                    "Your customer base may not be purely weather-driven."
                                )
                            )

                else:
                    st.info("Weather data is not available for the selected date range.")


        else:
            st.warning("No data matches the selected filters. Try adjusting your date range or location selection.")

else:
    # No data loaded - show message to load from BigQuery
    st.info("**Get started:** Use the date selector above to load booking data from BigQuery.")



render_footer()
