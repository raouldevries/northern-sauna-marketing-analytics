"""
Northern Sauna Analytics - Capacity Page
Occupancy analysis, empty slot opportunities, and visit patterns
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
import sys
sys.path.insert(0, '..')
from bq_data_loader import init_session_state, render_bookeo_settings
from components.demo_banner import render_demo_banner, render_footer  # noqa: E402
from utils import render_header, render_sidebar_nav
from features.revenue.formatters import format_euro, format_number

# Page configuration
st.set_page_config(
    page_title="Northern Sauna - Capacity",
    page_icon="\U0001f525",
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

# ---------------------------------------------------------------------------
# Capacity data: per-location timeslot capacity from Bookeo
# 75-min timeslots, drop_in_max = max people per slot
# daily_capacity = drop_in_max × slots_per_day
# ---------------------------------------------------------------------------
LOCATION_CAPACITY = {
    # Six demo locations across Nordic capitals + regional cities.
    "Northern Sauna Stockholm": {"drop_in_max": 8, "slots_per_day": 12},
    "Northern Sauna Helsinki": {"drop_in_max": 7, "slots_per_day": 11},
    "Northern Sauna Oslo": {"drop_in_max": 7, "slots_per_day": 11},
    "Northern Sauna Copenhagen": {"drop_in_max": 6, "slots_per_day": 10},
    "Northern Sauna Gothenburg": {"drop_in_max": 6, "slots_per_day": 10},
    "Northern Sauna Bergen": {"drop_in_max": 5, "slots_per_day": 9},
    # Live-build city-neighborhood entries kept as documentation of how the
    # location-normalization view splits multi-venue cities.
    "Northern Sauna Stockholm Östermalm": {"drop_in_max": 6, "slots_per_day": 11},
    "Northern Sauna Stockholm Södermalm": {"drop_in_max": 8, "slots_per_day": 12},
    "Northern Sauna Stockholm Waterfront": {"drop_in_max": 6, "slots_per_day": 10},
    "Northern Sauna Helsinki Kallio": {"drop_in_max": 6, "slots_per_day": 11},
    "Northern Sauna Helsinki Kamppi": {"drop_in_max": 6, "slots_per_day": 10},
    "Northern Sauna Oslo Grünerløkka": {"drop_in_max": 7, "slots_per_day": 10},
    "Northern Sauna Oslo Frogner": {"drop_in_max": 6, "slots_per_day": 11},
}

PRICE_PER_PERSON_FALLBACK = 17.50


def find_capacity_match(location_name):
    """Find matching LOCATION_CAPACITY entry (case-insensitive, partial)."""
    if not location_name:
        return None
    if location_name in LOCATION_CAPACITY:
        return location_name
    location_lower = location_name.lower()
    for cap_key in LOCATION_CAPACITY:
        if cap_key.lower() == location_lower:
            return cap_key
    for cap_key in LOCATION_CAPACITY:
        cap_stripped = cap_key.lower().replace("northern sauna ", "")
        loc_stripped = location_lower.replace("northern sauna ", "")
        if loc_stripped in cap_stripped or cap_stripped in loc_stripped:
            return cap_key
    return None


def get_daily_capacity(location_name):
    """Get daily capacity (max people per day) for a location."""
    cap_key = find_capacity_match(location_name)
    if cap_key:
        c = LOCATION_CAPACITY[cap_key]
        return c["drop_in_max"] * c["slots_per_day"]
    return None


render_header()

render_bookeo_settings(page_key="capacity")

st.markdown("## Capacity")
st.markdown("Occupancy rates, empty slot opportunities, and visit patterns for **drop-in bookings** (not group bookings)")

init_session_state()

if not st.session_state.get('authenticated', False):
    st.warning("Please log in to access this page.")
    st.page_link("app.py", label="Go to Login", icon=":material/login:")
    st.stop()

render_sidebar_nav("Capacity", ["Overview", "Opportunities", "Patterns"])

render_demo_banner()

# Main content
if st.session_state.df2 is None:
    st.info("**No data loaded.** Use the date selector above to load booking data from BigQuery.")
else:
    _loading = st.empty()
    _loading.info("Loading capacity analysis...")
    df2 = st.session_state.df2

    visit_col = "Start"
    location_col = "Location" if "Location" in df2.columns else None
    participants_col = "Participants" if "Participants" in df2.columns else None

    if location_col is None:
        st.warning("**Location column not found.** Capacity analysis requires location data.")
    else:
        # Prepare data
        cap_data = df2[[visit_col, location_col]].copy()
        cap_data.columns = ["visit_datetime", "location"]

        if participants_col:
            cap_data["participants"] = pd.to_numeric(
                df2[participants_col], errors="coerce"
            ).fillna(1)
        else:
            cap_data["participants"] = 1

        if "Total paid" in df2.columns:
            cap_data["revenue"] = pd.to_numeric(
                df2["Total paid"], errors="coerce"
            ).fillna(0)

        cap_data["visit_datetime"] = pd.to_datetime(
            cap_data["visit_datetime"], errors="coerce"
        )
        cap_data = cap_data[cap_data["visit_datetime"].notna()]

        # Keep only Northern Sauna locations
        cap_data = cap_data[
            cap_data["location"].str.lower().str.startswith("northern sauna")
        ].copy()

        # Calculate avg booking value from data
        if "revenue" in cap_data.columns and cap_data["revenue"].sum() > 0:
            avg_booking_value = cap_data["revenue"].mean()
        else:
            avg_booking_value = PRICE_PER_PERSON_FALLBACK

        if len(cap_data) == 0:
            st.warning("No valid capacity data found.")
        else:
            # Derived columns
            cap_data["date"] = cap_data["visit_datetime"].dt.date
            cap_data["hour"] = cap_data["visit_datetime"].dt.hour
            cap_data["day_name"] = cap_data["visit_datetime"].dt.day_name()
            cap_data["day_num"] = cap_data["visit_datetime"].dt.dayofweek  # 0=Mon
            cap_data["is_weekend"] = cap_data["day_num"] >= 5  # Sat-Sun

            # Date range label for takeaway titles
            _date_from = cap_data["visit_datetime"].min().strftime("%-d %b %Y")
            _date_to = cap_data["visit_datetime"].max().strftime("%-d %b %Y")
            takeaway_title = f"Key Takeaways ({_date_from} \u2013 {_date_to})"
            _cap_date_range_days = (
                cap_data["visit_datetime"].max() - cap_data["visit_datetime"].min()
            ).days
            MIN_DAYS_FOR_TAKEAWAYS = 90
            show_takeaways = _cap_date_range_days >= MIN_DAYS_FOR_TAKEAWAYS
            cap_data["year_week"] = (
                cap_data["visit_datetime"].dt.isocalendar().year.astype(str)
                + "-W"
                + cap_data["visit_datetime"].dt.isocalendar().week.astype(str).str.zfill(2)
            )

            # Match locations to capacity
            locations_with_cap = []
            for loc in cap_data["location"].unique():
                if get_daily_capacity(loc) is not None:
                    locations_with_cap.append(loc)

            cap_data_matched = cap_data[cap_data["location"].isin(locations_with_cap)]
            num_days = cap_data_matched["date"].nunique()
            num_weeks = cap_data_matched["year_week"].nunique()

            # --- Per-location daily occupancy ---
            daily_visits = cap_data_matched.groupby(["location", "date"]).agg(
                visitors=("participants", "sum"),
                is_weekend=("is_weekend", "first"),
                day_name=("day_name", "first"),
                day_num=("day_num", "first"),
            ).reset_index()

            daily_visits["daily_cap"] = daily_visits["location"].apply(get_daily_capacity)
            daily_visits["occupancy"] = (
                daily_visits["visitors"] / daily_visits["daily_cap"] * 100
            ).clip(upper=100)

            # Per-location summary
            loc_summary = []
            for loc in locations_with_cap:
                loc_data = daily_visits[daily_visits["location"] == loc]
                weekday_data = loc_data[~loc_data["is_weekend"]]
                weekend_data = loc_data[loc_data["is_weekend"]]
                daily_cap = get_daily_capacity(loc)

                avg_occ = loc_data["occupancy"].mean() if len(loc_data) > 0 else 0
                wd_occ = weekday_data["occupancy"].mean() if len(weekday_data) > 0 else 0
                we_occ = weekend_data["occupancy"].mean() if len(weekend_data) > 0 else 0
                avg_visitors = loc_data["visitors"].mean() if len(loc_data) > 0 else 0
                empty_per_day = max(0, daily_cap - avg_visitors)

                loc_summary.append({
                    "Location": loc,
                    "Daily Capacity": daily_cap,
                    "Avg Visitors/Day": round(avg_visitors),
                    "Weekday Occ (%)": round(wd_occ, 1),
                    "Weekend Occ (%)": round(we_occ, 1),
                    "Overall Occ (%)": round(avg_occ, 1),
                    "Empty Slots/Day": round(empty_per_day),
                })

            summary_df = pd.DataFrame(loc_summary).sort_values(
                "Overall Occ (%)", ascending=False
            )

            # --- Assumptions toggle ---
            with st.expander("Capacity assumptions"):
                st.markdown(
                    "All occupancy numbers are based on the following assumptions:\n\n"
                    f"- **Timeslot duration:** 75 minutes\n"
                    f"- **Avg booking value:** {format_euro(avg_booking_value, 2)} (from actual data)\n"
                    f"- **Weekend:** Saturday, Sunday\n\n"
                )

                assumptions_rows = []
                for loc_name, cap in LOCATION_CAPACITY.items():
                    daily_cap = cap["drop_in_max"] * cap["slots_per_day"]
                    assumptions_rows.append({
                        "Location": loc_name.replace("Northern Sauna ", ""),
                        "Max per Slot": cap["drop_in_max"],
                        "Slots per Day": cap["slots_per_day"],
                        "Max per Day": daily_cap,
                        "Max per Week": daily_cap * 7,
                    })

                assumptions_df = pd.DataFrame(assumptions_rows)
                st.dataframe(
                    assumptions_df,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Location": st.column_config.TextColumn("Location"),
                        "Max per Slot": st.column_config.NumberColumn(
                            "Max per Slot",
                            help="Maximum drop-in visitors per 75-min timeslot",
                        ),
                        "Slots per Day": st.column_config.NumberColumn(
                            "Slots per Day",
                            help="Number of 75-min timeslots per day",
                        ),
                        "Max per Day": st.column_config.NumberColumn(
                            "Max per Day",
                            help="Maximum visitors per day (max per slot \u00d7 slots)",
                        ),
                        "Max per Week": st.column_config.NumberColumn(
                            "Max per Week",
                            help="Maximum visitors per week (max per day \u00d7 7)",
                        ),
                    },
                )

            # ================================================================
            #  TABS
            # ================================================================
            _loading.empty()

            tab_overview, tab_opportunities, tab_patterns = st.tabs([
                "Overview", "Opportunities", "Patterns"
            ])

            # ==================== TAB 1: OVERVIEW ====================
            with tab_overview:

                total_visits = int(cap_data_matched["participants"].sum())
                avg_wd_occ = summary_df["Weekday Occ (%)"].mean()
                avg_we_occ = summary_df["Weekend Occ (%)"].mean()
                emptiest_loc = summary_df.loc[
                    summary_df["Overall Occ (%)"].idxmin(), "Location"
                ] if len(summary_df) > 0 else "N/A"
                emptiest_occ = summary_df["Overall Occ (%)"].min() if len(summary_df) > 0 else 0

                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric(
                        "Total Visits", format_number(total_visits),
                        help=f"Total visitors across {len(locations_with_cap)} locations over {num_days} days.",
                    )
                with col2:
                    st.metric(
                        "Avg Weekday Occupancy", f"{avg_wd_occ:.1f}%".replace(".", ","),
                        help="Average occupancy Mon-Thu across all locations.",
                    )
                with col3:
                    st.metric(
                        "Avg Weekend Occupancy", f"{avg_we_occ:.1f}%".replace(".", ","),
                        help="Average occupancy Fri-Sun across all locations.",
                    )
                with col4:
                    emptiest_short = emptiest_loc.replace("Northern Sauna ", "")
                    st.metric(
                        "Emptiest Location", emptiest_short,
                        delta=f"{emptiest_occ:.0f}% occupancy",
                        delta_color="inverse",
                        help=f"Location with lowest average occupancy: {emptiest_loc}.",
                    )

                # --- Occupancy by Location table ---
                st.markdown("#### Occupancy by Location")
                st.caption(
                    f"Based on {num_days} days of data. "
                    "Daily capacity = max people per timeslot \u00d7 timeslots per day."
                )

                display_df = summary_df.copy()
                display_df["Location"] = display_df["Location"].str.replace("Northern Sauna ", "", regex=False)

                def color_occupancy(val):
                    if isinstance(val, (int, float)):
                        if val >= 80:
                            return "background-color: #dcfce7"
                        elif val >= 50:
                            return "background-color: #fef3c7"
                        else:
                            return "background-color: #fee2e2"
                    return ""

                styled = display_df.style.applymap(
                    color_occupancy,
                    subset=["Weekday Occ (%)", "Weekend Occ (%)", "Overall Occ (%)"],
                )

                st.dataframe(
                    styled, use_container_width=True, hide_index=True,
                    column_config={
                        "Location": st.column_config.TextColumn("Location"),
                        "Daily Capacity": st.column_config.NumberColumn("Max/Day", help="Maximum visitors per day (drop-in max \u00d7 timeslots)"),
                        "Avg Visitors/Day": st.column_config.NumberColumn("Avg Visitors/Day", format="%d"),
                        "Weekday Occ (%)": st.column_config.NumberColumn("Weekday %", format="%.1f%%"),
                        "Weekend Occ (%)": st.column_config.NumberColumn("Weekend %", format="%.1f%%"),
                        "Overall Occ (%)": st.column_config.NumberColumn("Overall %", format="%.1f%%"),
                        "Empty Slots/Day": st.column_config.NumberColumn("Empty/Day", format="%d"),
                    },
                )
                st.caption("Green = 80%+ | Yellow = 50-80% | Red = below 50%")

                # --- Weekly Trend ---
                st.markdown("#### Weekly Occupancy Trend")

                weekly_visits = cap_data_matched.groupby(["year_week", "location"]).agg(
                    visitors=("participants", "sum"),
                ).reset_index()

                weekly_visits["daily_cap"] = weekly_visits["location"].apply(get_daily_capacity)
                # Weekly capacity = daily cap × 7
                weekly_visits["weekly_cap"] = weekly_visits["daily_cap"] * 7
                weekly_visits["occupancy"] = (
                    weekly_visits["visitors"] / weekly_visits["weekly_cap"] * 100
                ).clip(upper=100)

                trend_location = st.selectbox(
                    "Select Location",
                    options=["All Locations (Average)"] + locations_with_cap,
                    key="overview_trend_location",
                )

                if trend_location == "All Locations (Average)":
                    trend_plot = weekly_visits.groupby("year_week")["occupancy"].mean().reset_index()
                else:
                    trend_plot = weekly_visits[
                        weekly_visits["location"] == trend_location
                    ][["year_week", "occupancy"]]

                trend_plot = trend_plot.sort_values("year_week")

                fig_trend = px.line(
                    trend_plot,
                    x="year_week", y="occupancy",
                    markers=True,
                    labels={"year_week": "Week", "occupancy": "Occupancy (%)"},
                )
                fig_trend.update_traces(line_color="#3498db")
                fig_trend.update_layout(
                    height=400, margin=dict(t=20),
                    yaxis=dict(range=[0, 100]),
                    xaxis_tickangle=-45,
                )
                st.plotly_chart(fig_trend, use_container_width=True)

                # --- Key Takeaways toggle ---
                with st.expander(takeaway_title):
                 if not show_takeaways:
                    st.caption(
                        f"Select at least 3 months of data for meaningful takeaways. "
                        f"Current range: {_cap_date_range_days} days. "
                        f"For the best insights, select the full season "
                        f"(September\u2013April)."
                    )
                 else:

                    # 1. Weekday-Weekend Gap
                    wd_we_gap = abs(avg_we_occ - avg_wd_occ)
                    higher_period = "weekends" if avg_we_occ > avg_wd_occ else "weekdays"
                    lower_period = "weekdays" if higher_period == "weekends" else "weekends"
                    # Turnover from closing the gap by 10pp on weekdays
                    total_daily_cap = sum(
                        get_daily_capacity(loc) for loc in locations_with_cap
                    )
                    rev_per_pp = total_daily_cap * 0.01 * avg_booking_value * 7  # per week (all days)
                    rev_per_pp_weekdays = total_daily_cap * 0.01 * avg_booking_value * 5  # weekdays only
                    rev_10pp = rev_per_pp_weekdays * 10  # closing weekday gap

                    rev_10pp_season = rev_10pp * 35  # ~8 months season

                    st.info(
                        f"**Weekday-Weekend Gap: {wd_we_gap:.0f} percentage points.** "
                        f"Weekdays average **{avg_wd_occ:.0f}%** occupancy vs "
                        f"**{avg_we_occ:.0f}%** on weekends. "
                        f"Closing this gap by just 10 pp (percentage points) on "
                        f"{lower_period} would add ~**{format_euro(rev_10pp)}/week** "
                        f"({format_euro(rev_10pp_season)} per season, September-April)."
                    )

                    # 2. Location Spread
                    if len(summary_df) >= 2:
                        best_loc_row = summary_df.loc[summary_df["Overall Occ (%)"].idxmax()]
                        worst_loc_row = summary_df.loc[summary_df["Overall Occ (%)"].idxmin()]
                        best_loc = best_loc_row["Location"].replace("Northern Sauna ", "")
                        worst_loc = worst_loc_row["Location"].replace("Northern Sauna ", "")
                        best_occ = best_loc_row["Overall Occ (%)"]
                        worst_occ = worst_loc_row["Overall Occ (%)"]
                        loc_spread = best_occ - worst_occ

                        st.info(
                            f"**Location spread: {loc_spread:.0f} pp (percentage points).** "
                            f"Best performer **{best_loc}** runs at **{best_occ:.0f}%** "
                            f"while **{worst_loc}** sits at **{worst_occ:.0f}%**. "
                            f"Investigate what drives the gap \u2014 local marketing, "
                            f"visibility, or area demographics."
                        )

                    # 3. Trend Direction
                    if len(trend_plot) >= 4:
                        first_half = trend_plot["occupancy"].iloc[:len(trend_plot) // 2].mean()
                        second_half = trend_plot["occupancy"].iloc[len(trend_plot) // 2:].mean()
                        trend_delta = second_half - first_half
                        trend_dir = "risen" if trend_delta > 0 else "fallen"
                        trend_icon = "trending upward" if trend_delta > 0 else "trending downward"

                        if abs(trend_delta) >= 1:
                            st.info(
                                f"**Occupancy has {trend_dir} by {abs(trend_delta):.0f} pp (percentage points)** "
                                f"over the selected period ({trend_icon}). "
                                + (
                                    "Occupancy is building through the season \u2014 "
                                    "maintain what's working."
                                    if trend_delta > 0
                                    else "Occupancy is declining as the season progresses. "
                                    "This is common towards spring (March-April) as weather "
                                    "warms up \u2014 consider end-of-season promotions to "
                                    "maintain momentum."
                                )
                            )
                        else:
                            st.info(
                                "**Occupancy is flat** over the selected period "
                                "\u2014 no significant upward or downward trend."
                            )

                    # 4. The 1% = €X Metric
                    season_weeks = 35  # ~8 months (September-April)
                    st.info(
                        f"**Every 1 pp (percentage point) occupancy improvement = "
                        f"~{format_euro(rev_per_pp)}/week** "
                        f"across all {len(locations_with_cap)} locations "
                        f"(~{format_euro(rev_per_pp * season_weeks)} per season). "
                        f"Use this to evaluate the ROI (return on investment) of "
                        f"any initiative: a promo that lifts occupancy by 5 pp is "
                        f"worth ~{format_euro(rev_per_pp * 5)}/week "
                        f"({format_euro(rev_per_pp * 5 * season_weeks)} per season)."
                    )


            # ==================== TAB 2: OPPORTUNITIES ====================
            with tab_opportunities:

                # --- Per location × day-of-week breakdown ---
                day_loc = daily_visits.groupby(["location", "day_name", "day_num"]).agg(
                    avg_visitors=("visitors", "mean"),
                    avg_occupancy=("occupancy", "mean"),
                    days_count=("date", "count"),
                ).reset_index().sort_values(["location", "day_num"])

                day_loc["daily_cap"] = day_loc["location"].apply(get_daily_capacity)
                day_loc["empty_per_day"] = (
                    day_loc["daily_cap"] - day_loc["avg_visitors"]
                ).clip(lower=0)
                day_loc["revenue_opportunity"] = day_loc["empty_per_day"] * avg_booking_value

                # KPIs
                total_empty_per_week = day_loc["empty_per_day"].sum()  # sum across all loc × days
                total_rev_opportunity = day_loc["revenue_opportunity"].sum()

                # Emptiest day (across all locations)
                day_avg = day_loc.groupby("day_name")["avg_occupancy"].mean()
                emptiest_day = day_avg.idxmin() if len(day_avg) > 0 else "N/A"
                emptiest_day_occ = day_avg.min() if len(day_avg) > 0 else 0

                # Emptiest location × day combo
                if len(day_loc) > 0:
                    worst_row = day_loc.loc[day_loc["avg_occupancy"].idxmin()]
                    worst_combo = f"{worst_row['location'].replace('Northern Sauna ', '')} \u2014 {worst_row['day_name']}"
                    worst_combo_occ = worst_row["avg_occupancy"]
                else:
                    worst_combo = "N/A"
                    worst_combo_occ = 0

                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric(
                        "Empty Slots / Week",
                        format_number(total_empty_per_week),
                        help="Total unfilled capacity across all locations and days per week.",
                    )
                with col2:
                    st.metric(
                        "Turnover Opportunity / Week",
                        format_euro(total_rev_opportunity),
                        help=f"If all empty slots were filled at the avg booking value of {format_euro(avg_booking_value, 2)}.",
                    )
                with col3:
                    st.metric(
                        "Emptiest Day", emptiest_day,
                        delta=f"{emptiest_day_occ:.0f}% avg occupancy",
                        delta_color="inverse",
                        help="Day of the week with the lowest average occupancy across all locations.",
                    )
                with col4:
                    st.metric(
                        "Biggest Gap", worst_combo,
                        delta=f"{worst_combo_occ:.0f}% occupancy",
                        delta_color="inverse",
                        help="The location \u00d7 day combination with the lowest occupancy.",
                    )

                # --- Biggest Opportunities table ---
                st.markdown("#### Biggest Opportunities")
                st.caption(
                    "Ranked by estimated revenue if empty slots were filled at "
                    f"the avg booking value of {format_euro(avg_booking_value, 2)}."
                )

                opps = day_loc[[
                    "location", "day_name", "avg_occupancy",
                    "avg_visitors", "daily_cap", "empty_per_day",
                    "revenue_opportunity",
                ]].copy()
                opps = opps.sort_values("revenue_opportunity", ascending=False).head(20)
                opps["location"] = opps["location"].str.replace("Northern Sauna ", "", regex=False)
                opps["avg_occupancy"] = opps["avg_occupancy"].round(1)
                opps["avg_visitors"] = opps["avg_visitors"].round(1)
                opps["empty_per_day"] = opps["empty_per_day"].round(1)
                opps["revenue_opportunity"] = opps["revenue_opportunity"].apply(format_euro)

                opps = opps.rename(columns={
                    "location": "Location",
                    "day_name": "Day",
                    "avg_occupancy": "Occupancy (%)",
                    "avg_visitors": "Avg Visitors",
                    "daily_cap": "Capacity",
                    "empty_per_day": "Empty Slots",
                    "revenue_opportunity": "Turnover / Week",
                })

                st.dataframe(opps, use_container_width=True, hide_index=True)

                # --- Weekday occupancy breakdown ---
                st.markdown("#### Occupancy by Day of Week")
                st.caption(
                    "Which days are emptiest? Focus promotions on the red bars."
                )

                # Filter to weekdays only (Mon-Thu) for dal analysis
                weekday_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
                dal_data = day_loc[day_loc["day_name"].isin(weekday_names)].copy()

                if len(dal_data) > 0:
                    dal_data["location_short"] = dal_data["location"].str.replace(
                        "Northern Sauna ", "", regex=False
                    )
                    dal_data["day_name"] = pd.Categorical(
                        dal_data["day_name"],
                        categories=weekday_names,
                        ordered=True,
                    )

                    fig_dal = px.bar(
                        dal_data.sort_values(["day_name", "location_short"]),
                        x="day_name",
                        y="avg_occupancy",
                        color="location_short",
                        barmode="group",
                        labels={
                            "day_name": "Day",
                            "avg_occupancy": "Avg Occupancy (%)",
                            "location_short": "Location",
                        },
                        text=dal_data["avg_occupancy"].round(0).astype(int).astype(str) + "%",
                    )
                    fig_dal.update_traces(textposition="outside", textfont_size=9)
                    fig_dal.update_layout(
                        height=450, margin=dict(t=20),
                        yaxis=dict(range=[0, 100]),
                        legend=dict(
                            orientation="h", yanchor="bottom",
                            y=1.02, xanchor="right", x=1,
                            title=None,
                        ),
                    )
                    st.plotly_chart(fig_dal, use_container_width=True)

                # Also show Fri-Sun
                st.markdown("#### Weekend Occupancy by Day")

                weekend_names = ["Saturday", "Sunday"]
                we_data = day_loc[day_loc["day_name"].isin(weekend_names)].copy()

                if len(we_data) > 0:
                    we_data["location_short"] = we_data["location"].str.replace(
                        "Northern Sauna ", "", regex=False
                    )
                    we_data["day_name"] = pd.Categorical(
                        we_data["day_name"],
                        categories=weekend_names,
                        ordered=True,
                    )

                    fig_we = px.bar(
                        we_data.sort_values(["day_name", "location_short"]),
                        x="day_name",
                        y="avg_occupancy",
                        color="location_short",
                        barmode="group",
                        labels={
                            "day_name": "Day",
                            "avg_occupancy": "Avg Occupancy (%)",
                            "location_short": "Location",
                        },
                        text=we_data["avg_occupancy"].round(0).astype(int).astype(str) + "%",
                    )
                    fig_we.update_traces(textposition="outside", textfont_size=9)
                    fig_we.update_layout(
                        height=450, margin=dict(t=20),
                        yaxis=dict(range=[0, 100]),
                        legend=dict(
                            orientation="h", yanchor="bottom",
                            y=1.02, xanchor="right", x=1,
                            title=None,
                        ),
                    )
                    st.plotly_chart(fig_we, use_container_width=True)

                # --- Key Takeaways toggle ---
                with st.expander(takeaway_title):
                 if not show_takeaways:
                    st.caption(
                        f"Select at least 3 months of data for meaningful takeaways. "
                        f"Current range: {_cap_date_range_days} days. "
                        f"For the best insights, select the full season "
                        f"(September\u2013April)."
                    )
                 else:

                    # 1. Midday Weekday Opportunity
                    midday_mask = (
                        (~cap_data_matched["is_weekend"])
                        & (cap_data_matched["hour"] >= 10)
                        & (cap_data_matched["hour"] <= 15)
                    )
                    midday_data = cap_data_matched[midday_mask]

                    midday_visitors = midday_data["participants"].sum()
                    total_wd_visitors = cap_data_matched[
                        ~cap_data_matched["is_weekend"]
                    ]["participants"].sum()
                    midday_pct = (
                        midday_visitors / total_wd_visitors * 100
                        if total_wd_visitors > 0 else 0
                    )

                    midday_hours = 6  # 10, 11, 12, 13, 14, 15
                    slots_in_window = sum(
                        LOCATION_CAPACITY[find_capacity_match(loc)]["drop_in_max"]
                        for loc in locations_with_cap
                        if find_capacity_match(loc)
                    ) * midday_hours

                    num_weekdays_total = cap_data_matched[
                        ~cap_data_matched["is_weekend"]
                    ]["date"].nunique()
                    midday_avg_daily = (
                        midday_visitors / num_weekdays_total
                        if num_weekdays_total > 0 else 0
                    )
                    midday_empty_daily = max(0, slots_in_window - midday_avg_daily)
                    midday_rev_opportunity_week = midday_empty_daily * avg_booking_value * 5
                    midday_rev_opportunity_season = midday_rev_opportunity_week * 35  # ~8 months

                    st.info(
                        f"**Weekday midday slots (10:00-15:00) are underutilised.** "
                        f"Only **{midday_pct:.0f}%** of weekday visitors come during "
                        f"midday hours, leaving an estimated **{midday_empty_daily:.0f} "
                        f"empty slots per day** across all locations "
                        f"(**~{format_euro(midday_rev_opportunity_week)}/week**, "
                        f"~{format_euro(midday_rev_opportunity_season)} per season).\n\n"
                        f"**Who visits midday?** Understanding the profile of midday "
                        f"visitors (freelancers, retirees, remote workers, shift workers) "
                        f"is key to filling these slots. The booking data in BigQuery "
                        f"already contains the emails of everyone who has booked during "
                        f"low-occupancy hours \u2014 query for weekday 10:00-15:00 bookings "
                        f"to extract this list. Send this cohort a short targeted survey "
                        f"(5-7 questions via e.g. Google Forms or Tally.so) to learn their "
                        f"age, occupation, motivation, and price sensitivity. Incentivise "
                        f"with a small discount to boost response rate."
                    )

                    # 2. Peak Hour Saturation / Dynamic Pricing
                    evening_mask = (
                        (cap_data_matched["hour"] >= 17)
                        & (cap_data_matched["hour"] <= 21)
                    )
                    evening_data = cap_data_matched[evening_mask]

                    # Calculate evening occupancy per location per date
                    evening_daily = evening_data.groupby(
                        ["location", "date"]
                    )["participants"].sum().reset_index()
                    evening_daily["evening_cap"] = evening_daily["location"].apply(
                        lambda loc: (
                            LOCATION_CAPACITY[find_capacity_match(loc)]["drop_in_max"] * 5
                            if find_capacity_match(loc) else 0
                        )
                    )
                    evening_daily["evening_occ"] = (
                        evening_daily["participants"]
                        / evening_daily["evening_cap"].replace(0, np.nan)
                        * 100
                    ).clip(upper=100)
                    avg_evening_occ = (
                        evening_daily["evening_occ"].mean()
                        if len(evening_daily) > 0 else 0
                    )

                    if avg_evening_occ >= 75:
                        st.info(
                            f"**Evening slots (17:00-21:00) run at {avg_evening_occ:.0f}% "
                            f"occupancy.** You may be turning customers away at peak times. "
                            f"Consider **dynamic pricing** \u2014 a small premium on evening "
                            f"sessions funds off-peak discounts that shift demand to quieter "
                            f"midday/afternoon slots."
                        )
                    else:
                        st.info(
                            f"**Evening slots (17:00-21:00) average {avg_evening_occ:.0f}% "
                            f"occupancy.** There's still room to grow in peak hours. "
                            f"Focus on filling evenings before introducing off-peak "
                            f"discounts \u2014 after-work promotions or corporate wellness "
                            f"partnerships could help."
                        )


            # ==================== TAB 3: PATTERNS ====================
            with tab_patterns:

                # --- KPIs ---
                hourly = cap_data_matched.groupby("hour")["participants"].sum()
                peak_hour = hourly.idxmax() if len(hourly) > 0 else 0
                quietest_hour = hourly.idxmin() if len(hourly) > 0 else 0

                day_totals = cap_data_matched.groupby("day_name")["participants"].sum()
                peak_day = day_totals.idxmax() if len(day_totals) > 0 else "N/A"

                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric(
                        "Busiest Hour", f"{peak_hour}:00",
                        help="Hour with the most total visitors across all locations.",
                    )
                with col2:
                    st.metric(
                        "Quietest Hour", f"{quietest_hour}:00",
                        help="Hour with the fewest visitors \u2014 promotion opportunity.",
                    )
                with col3:
                    st.metric(
                        "Busiest Day", peak_day,
                        help="Day of the week with the most total visitors.",
                    )

                # --- Hourly Demand Curve ---
                st.markdown("#### Hourly Demand Curve")
                st.caption(
                    "Average visitors per hour \u2014 weekday vs weekend. "
                    "Shows exactly when demand drops off."
                )

                curve_location = st.selectbox(
                    "Select Location",
                    options=["All Locations"] + locations_with_cap,
                    key="patterns_curve_location",
                )

                if curve_location == "All Locations":
                    curve_data = cap_data_matched.copy()
                else:
                    curve_data = cap_data_matched[
                        cap_data_matched["location"] == curve_location
                    ].copy()

                # Avg visitors per hour per day type
                num_weekdays = curve_data[~curve_data["is_weekend"]]["date"].nunique()
                num_weekend_days = curve_data[curve_data["is_weekend"]]["date"].nunique()

                wd_hourly = (
                    curve_data[~curve_data["is_weekend"]]
                    .groupby("hour")["participants"].sum()
                    .reindex(range(24), fill_value=0)
                )
                we_hourly = (
                    curve_data[curve_data["is_weekend"]]
                    .groupby("hour")["participants"].sum()
                    .reindex(range(24), fill_value=0)
                )

                if num_weekdays > 0:
                    wd_hourly = wd_hourly / num_weekdays
                if num_weekend_days > 0:
                    we_hourly = we_hourly / num_weekend_days

                hourly_df = pd.DataFrame({
                    "Hour": [f"{h}:00" for h in range(24)],
                    "Weekday (Mon-Fri)": wd_hourly.values,
                    "Weekend (Sat-Sun)": we_hourly.values,
                })

                fig_curve = go.Figure()
                fig_curve.add_trace(go.Scatter(
                    x=hourly_df["Hour"], y=hourly_df["Weekday (Mon-Fri)"],
                    name="Weekday (Mon-Fri)",
                    mode="lines+markers",
                    line=dict(color="#3498db", width=2.5),
                    marker=dict(size=5),
                ))
                fig_curve.add_trace(go.Scatter(
                    x=hourly_df["Hour"], y=hourly_df["Weekend (Sat-Sun)"],
                    name="Weekend (Sat-Sun)",
                    mode="lines+markers",
                    line=dict(color="#e67e22", width=2.5),
                    marker=dict(size=5),
                ))
                fig_curve.update_layout(
                    height=400, margin=dict(t=20),
                    yaxis=dict(title="Avg Visitors", rangemode="tozero"),
                    xaxis=dict(title="Hour of Day"),
                    legend=dict(
                        orientation="h", yanchor="bottom",
                        y=1.02, xanchor="right", x=1,
                    ),
                    hovermode="x unified",
                    plot_bgcolor="rgba(0,0,0,0)",
                )
                st.plotly_chart(fig_curve, use_container_width=True)

                # --- Visit Heatmap ---
                st.markdown("#### Visit Heatmap")

                heatmap_location = st.selectbox(
                    "Select Location",
                    options=["All Locations"] + locations_with_cap,
                    key="patterns_heatmap_location",
                )

                with st.expander("How to read the heatmap"):
                    st.markdown(
                        "**Darker purple** = more visitors. "
                        "**Light/white** = few or no visitors \u2014 "
                        "these are your empty slots.\n\n"
                        "Look for:\n"
                        "- **Light rows** = quiet hours across all days "
                        "(promotion opportunity)\n"
                        "- **Light columns** = quiet days regardless of "
                        "time (staffing opportunity)\n"
                        "- **Dark clusters** = peak times needing full "
                        "capacity"
                    )

                if heatmap_location == "All Locations":
                    heatmap_data = cap_data_matched
                else:
                    heatmap_data = cap_data_matched[
                        cap_data_matched["location"] == heatmap_location
                    ]

                day_order = [
                    "Monday", "Tuesday", "Wednesday", "Thursday",
                    "Friday", "Saturday", "Sunday",
                ]

                visit_counts = heatmap_data.groupby(
                    ["day_name", "hour"]
                )["participants"].sum().reset_index()
                visit_counts.columns = ["Day", "Hour", "Visits"]

                if len(visit_counts) > 0:
                    peak_row = visit_counts.loc[visit_counts["Visits"].idxmax()]
                    st.caption(
                        f"Peak time: **{peak_row['Day']} at {int(peak_row['Hour']):02d}:00** "
                        f"with {format_number(int(peak_row['Visits']))} visits."
                    )

                all_combos = pd.MultiIndex.from_product(
                    [day_order, range(24)], names=["Day", "Hour"]
                ).to_frame(index=False)

                heatmap_grid = all_combos.merge(
                    visit_counts, on=["Day", "Hour"], how="left"
                ).fillna(0)
                heatmap_grid["Visits"] = heatmap_grid["Visits"].astype(int)

                heatmap_matrix = heatmap_grid.pivot(
                    index="Hour", columns="Day", values="Visits"
                )[day_order]

                fig_heatmap = go.Figure(data=go.Heatmap(
                    z=heatmap_matrix.values,
                    x=day_order,
                    y=[f"{h:02d}:00" for h in range(24)],
                    colorscale="Purples",
                    hovertemplate="%{x}<br>%{y}<br>%{z} visits<extra></extra>",
                    showscale=True,
                    colorbar=dict(title="Visits"),
                ))

                fig_heatmap.update_layout(
                    height=600, margin=dict(t=20),
                    xaxis=dict(side="bottom"),
                    yaxis=dict(autorange="reversed", title="Hour of Day"),
                )

                st.plotly_chart(fig_heatmap, use_container_width=True)

                # --- Key Takeaways toggle ---
                with st.expander(takeaway_title):
                 if not show_takeaways:
                    st.caption(
                        f"Select at least 3 months of data for meaningful takeaways. "
                        f"Current range: {_cap_date_range_days} days. "
                        f"For the best insights, select the full season "
                        f"(September\u2013April)."
                    )
                 else:

                    # 1. Demand concentration — peak vs quietest
                    peak_visitors = hourly.max() if len(hourly) > 0 else 0
                    quietest_visitors = hourly.min() if len(hourly) > 0 else 0
                    peak_ratio = (
                        peak_visitors / quietest_visitors
                        if quietest_visitors > 0 else 0
                    )

                    st.info(
                        f"**Demand is heavily concentrated.** The busiest hour "
                        f"(**{peak_hour}:00**) sees **{peak_ratio:.0f}x** more "
                        f"visitors than the quietest hour (**{quietest_hour}:00**). "
                        f"This sharp peak-to-trough ratio means there are large "
                        f"windows of underused capacity that targeted promotions "
                        f"or off-peak pricing could help fill."
                    )

                    # 2. Weekday vs weekend shape
                    wd_peak_hour = wd_hourly.idxmax() if wd_hourly.sum() > 0 else 0
                    we_peak_hour = we_hourly.idxmax() if we_hourly.sum() > 0 else 0

                    if wd_peak_hour != we_peak_hour:
                        st.info(
                            f"**Weekday and weekend demand peak at different times.** "
                            f"Weekdays peak at **{wd_peak_hour}:00**, weekends at "
                            f"**{we_peak_hour}:00**. This means staffing and slot "
                            f"availability could be optimised separately for each \u2014 "
                            f"e.g. later start times on weekdays if mornings are empty, "
                            f"or extended hours on weekends if demand runs later."
                        )
                    else:
                        st.info(
                            f"**Weekday and weekend demand both peak at {wd_peak_hour}:00.** "
                            f"The demand shape is similar across the week, which simplifies "
                            f"staffing \u2014 but also means off-peak hours are consistently "
                            f"quiet and could benefit from a standing promotion."
                        )

                    # 3. Busiest day insight
                    quietest_day = day_totals.idxmin() if len(day_totals) > 0 else "N/A"
                    peak_day_visitors = day_totals.max() if len(day_totals) > 0 else 0
                    quietest_day_visitors = day_totals.min() if len(day_totals) > 0 else 0
                    day_ratio = (
                        peak_day_visitors / quietest_day_visitors
                        if quietest_day_visitors > 0 else 0
                    )

                    st.info(
                        f"**{peak_day}** is the busiest day with **{day_ratio:.1f}x** "
                        f"more visitors than **{quietest_day}** (the quietest). "
                        f"Consider running {quietest_day}-specific promotions or "
                        f"events to level out weekly demand."
                    )




render_footer()
