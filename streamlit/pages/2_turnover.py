"""
Northern Sauna Analytics - Turnover Page
Turnover trends, location breakdown, and pricing analysis
"""

import sys  # noqa: I001
from datetime import timedelta

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, '..')
from bq_data_loader import apply_btw_toggle, init_session_state, render_bookeo_settings  # noqa: E402, I001
from features.revenue.formatters import (  # noqa: E402
    format_euro, format_number, section_gap, style_dataframe_right_align,
)
from features.revenue.queries import _get_period_summary  # noqa: E402
from components.demo_banner import render_demo_banner, render_footer  # noqa: E402
from utils import render_header, render_sidebar_nav  # noqa: E402

# Page configuration
st.set_page_config(
    page_title="Northern Sauna - Turnover",
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

render_header()

# BigQuery data settings (under header)
render_bookeo_settings(page_key="revenue", date_column="booking_created_at")

st.markdown("## Turnover Analysis")
st.markdown("Booking turnover from Bookeo \u2014 trends, locations, and pricing")

# Initialize session state using centralized function
init_session_state()

# Check authentication
if not st.session_state.get('authenticated', False):
    st.warning("Please log in to access this page.")
    st.page_link("app.py", label="Go to Login", icon=":material/login:")
    st.stop()

render_sidebar_nav("Turnover")

render_demo_banner()

# Main content
if st.session_state.df1 is None or st.session_state.df2 is None:
    st.info("**No data loaded.** Use the date selector above to load booking data from BigQuery.")
else:
    # FIX #2: Use df2 (non-cancelled) for revenue — cancelled bookings have 0 paid
    _loading = st.empty()
    _loading.info("Loading turnover analysis...")
    df = st.session_state.df2.copy()

    # Created = booking date (when payment was collected)
    # Start = visit date (when the sauna visit happens)
    # BQ query filters on booking_created_at, so trends use Created
    date_col = "Created" if "Created" in df.columns else "Start"
    visit_col = "Start" if "Start" in df.columns else date_col
    revenue_col = "Total paid" if "Total paid" in df.columns else (
        "Total gross" if "Total gross" in df.columns else None
    )
    email_col = "Email address" if "Email address" in df.columns else None
    location_col = "Location" if "Location" in df.columns else None
    source_col = "Source" if "Source" in df.columns else None
    private_col = "Private event" if "Private event" in df.columns else None
    participants_col = "Participants" if "Participants" in df.columns else None

    if revenue_col is None:
        st.warning("**Turnover column not found in data.**")
    else:
        # ================================================================
        #  DATA COMPUTATION — all metrics computed before tabs
        # ================================================================

        df["revenue"] = pd.to_numeric(df[revenue_col], errors="coerce").fillna(0)
        df["booking_date"] = pd.to_datetime(df[date_col], errors="coerce")
        df["visit_date"] = pd.to_datetime(df[visit_col], errors="coerce")
        if participants_col:
            df["participants"] = pd.to_numeric(df[participants_col], errors="coerce").fillna(0)

        # Filter to selected date range (data may have been loaded by a
        # different date column on the Overview page)
        range_start = pd.Timestamp(st.session_state.bookeo_start_date)
        range_end = pd.Timestamp(st.session_state.bookeo_end_date)
        if df["booking_date"].dt.tz is not None:
            range_start = range_start.tz_localize(df["booking_date"].dt.tz)
            range_end = range_end.tz_localize(df["booking_date"].dt.tz)
        df = df[
            (df["booking_date"] >= range_start)
            & (df["booking_date"] <= range_end)
        ].copy()

        total_revenue = df["revenue"].sum()
        total_bookings = len(df)
        avg_booking_value = df["revenue"].mean()
        unique_customers = df[email_col].nunique() if email_col and email_col in df.columns else 0
        # --- Period-over-period delta ---
        start_dt = pd.Timestamp(st.session_state.bookeo_start_date)
        end_dt = pd.Timestamp(st.session_state.bookeo_end_date)
        period_days = (end_dt - start_dt).days + 1
        prev_end = start_dt - timedelta(days=1)
        prev_start = prev_end - timedelta(days=period_days - 1)

        prev = _get_period_summary(
            prev_start.strftime("%Y-%m-%d"),
            prev_end.strftime("%Y-%m-%d"),
        )
        turnover_delta_pct = (
            (total_revenue - prev["turnover"]) / prev["turnover"] * 100
            if prev["turnover"] > 0 else None
        )
        aov_delta_pct = (
            (avg_booking_value - prev["aov"]) / prev["aov"] * 100
            if prev["aov"] > 0 else None
        )
        bookings_delta_pct = (
            (total_bookings - prev["bookings"]) / prev["bookings"] * 100
            if prev["bookings"] > 0 else None
        )
        customers_delta_pct = (
            (unique_customers - prev["unique_customers"]) / prev["unique_customers"] * 100
            if prev["unique_customers"] > 0 else None
        )

        # --- Trend data ---
        trend_date_col = "booking_date"
        df_trend = df[df[trend_date_col].notna()].copy()

        date_span = (
            (df_trend[trend_date_col].max()
             - df_trend[trend_date_col].min()).days
            if len(df_trend) > 0 else 0
        )
        if date_span < 60:
            freq_label = "Day"
            df_trend["Period"] = df_trend[trend_date_col].dt.normalize()
            if df_trend["Period"].dt.tz is not None:
                df_trend["Period"] = df_trend["Period"].dt.tz_localize(None)
            current_period = pd.Timestamp.now().normalize()
        elif date_span <= 180:
            freq_label = "Week"
            df_trend["Period"] = df_trend[trend_date_col].dt.to_period("W").apply(
                lambda p: p.start_time
            )
            current_period = pd.Timestamp.now().to_period("W").start_time
        else:
            freq_label = "Month"
            df_trend["Period"] = df_trend[trend_date_col].dt.to_period("M").dt.to_timestamp()
            current_period = pd.Timestamp.now().to_period("M").to_timestamp()

        # Exclude current incomplete period
        df_trend = df_trend[df_trend["Period"] < current_period]

        # Trim incomplete first/last periods caused by date range boundaries
        if len(df_trend) > 0 and freq_label in ("Week", "Month"):
            selected_start = pd.Timestamp(st.session_state.bookeo_start_date)
            selected_end = pd.Timestamp(st.session_state.bookeo_end_date)
            first_period = df_trend["Period"].min()
            last_period = df_trend["Period"].max()
            if first_period < selected_start.normalize():
                df_trend = df_trend[df_trend["Period"] > first_period]
            if freq_label == "Week":
                last_period_end = last_period + pd.Timedelta(days=6)
            else:
                last_period_end = last_period + pd.offsets.MonthEnd(1)
            if selected_end.normalize() < last_period_end:
                df_trend = df_trend[df_trend["Period"] < last_period]

        trend_data = None
        if len(df_trend) > 0:
            trend_data = df_trend.groupby("Period").agg(
                Revenue=("revenue", "sum"),
                Bookings=("revenue", "count"),
                AOV=("revenue", "mean"),
            ).reset_index()

        # --- Source data ---
        source_rev = None
        if source_col and source_col in df.columns:
            df_source = df.copy()
            df_source["source_clean"] = df_source[source_col].fillna("").str.strip()
            df_source.loc[df_source["source_clean"] == "", "source_clean"] = "Unknown"

            source_rev = df_source.groupby("source_clean").agg(
                Revenue=("revenue", "sum"),
                Bookings=("revenue", "count"),
                AOV=("revenue", "mean"),
            ).reset_index().rename(columns={"source_clean": "Source"})
            source_rev = source_rev.sort_values("Revenue", ascending=False)
            source_rev["% of Total"] = (
                (source_rev["Revenue"] / total_revenue * 100).round(1) if total_revenue > 0 else 0
            )

        # --- Location data ---
        loc_rev = None
        if location_col and location_col in df.columns:
            loc_agg = {
                "Revenue": ("revenue", "sum"),
                "Bookings": ("revenue", "count"),
                "AOV": ("revenue", "mean"),
            }
            if "participants" in df.columns:
                loc_agg["Participants"] = ("participants", "sum")

            loc_rev = df.groupby(location_col).agg(**loc_agg).reset_index().rename(
                columns={location_col: "Location"}
            )
            loc_rev = loc_rev.sort_values("Revenue", ascending=False)
            loc_rev["% of Turnover"] = (loc_rev["Revenue"] / total_revenue * 100).round(1)
            if "Participants" in loc_rev.columns:
                loc_rev["Rev/Participant"] = np.where(
                    loc_rev["Participants"] > 0,
                    loc_rev["Revenue"] / loc_rev["Participants"],
                    0
                )

        # ================================================================
        #  DISPLAY
        # ================================================================

        def _delta(pct):
            if pct is None:
                return None
            return f"{pct:+.1f}%".replace(".", ",")

        _loading.empty()

        # --- KPIs ---
        st.markdown("### Turnover Overview")

        st.session_state.btw_mode = st.segmented_control(
            "BTW",
            ["Excl. BTW", "Incl. BTW"],
            default=st.session_state.get("btw_mode", "Excl. BTW"),
            key="turnover_btw_toggle",
            label_visibility="collapsed",
        ) or st.session_state.get("btw_mode", "Excl. BTW")
        apply_btw_toggle()
        # Recompute revenue from toggled session data
        _toggled_df = st.session_state.df2
        df["revenue"] = pd.to_numeric(_toggled_df.loc[df.index, revenue_col], errors="coerce").fillna(0)
        total_revenue = df["revenue"].sum()
        avg_booking_value = df["revenue"].mean()

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric(
                "Total Turnover",
                format_euro(total_revenue),
                delta=_delta(turnover_delta_pct),
                help=(
                    "Total amount paid by customers via Bookeo "
                    "(omzet). Excludes cancelled bookings. "
                    f"Delta: vs {prev_start.strftime('%d %b')}"
                    f" – {prev_end.strftime('%d %b %Y')} "
                    f"({format_euro(prev['turnover'])})."
                )
            )
        with col2:
            st.metric(
                "Avg Booking Value",
                format_euro(avg_booking_value, 2),
                delta=_delta(aov_delta_pct),
                help=(
                    "Turnover divided by number of bookings. "
                    "How much each booking brings in on "
                    "average (ABV). "
                    f"Delta: vs {prev_start.strftime('%d %b')}"
                    f" – {prev_end.strftime('%d %b %Y')} "
                    f"({format_euro(prev['aov'], 2)})."
                )
            )
        with col3:
            st.metric(
                "Bookings",
                format_number(total_bookings),
                delta=_delta(bookings_delta_pct),
                help=(
                    "Total number of non-cancelled bookings "
                    "in the selected period. "
                    f"Delta: vs {prev_start.strftime('%d %b')}"
                    f" – {prev_end.strftime('%d %b %Y')} "
                    f"({format_number(prev['bookings'])})."
                )
            )
        with col4:
            st.metric(
                "Unique Customers",
                format_number(unique_customers),
                delta=_delta(customers_delta_pct),
                help=(
                    "Distinct customers (by email) who booked "
                    "in this period. "
                    f"Delta: vs {prev_start.strftime('%d %b')}"
                    f" – {prev_end.strftime('%d %b %Y')} "
                    f"({format_number(prev['unique_customers'])})."
                )
            )

        with st.expander("How to read these metrics"):
            st.markdown(
                "The green/red percentages show how each "
                "number changed compared to the previous "
                f"period ({prev_start.strftime('%d %b')}"
                f" \u2013 {prev_end.strftime('%d %b %Y')}). "
                "Hover over the **?** icon next to each "
                "metric to see the previous value.\n\n"
                "**Note:** The date range selects bookings "
                "created (and paid) in that period. "
                "This shows when revenue was collected, "
                "not when the visit takes place.\n\n"
                "**Metrics:**\n\n"
                "- **Total Turnover** \u2014 \"Total paid\" from Bookeo "
                "(actual payments collected via Mollie), "
                "excluding cancellations\n"
                "- **Avg Booking Value** \u2014 total turnover "
                "\u00f7 number of bookings\n"
                "- **Bookings** \u2014 total non-cancelled bookings\n"
                "- **Unique Customers** \u2014 distinct customers "
                "(by email) who booked\n"
                "- **Rev/Participant** \u2014 turnover \u00f7 total "
                "participants at a location (compare across "
                "locations to spot pricing opportunities)\n\n"
                "**What to look for:** If bookings are "
                "growing but unique customers are flat, "
                "your existing customers are visiting "
                "more often (good!). "
                "If customers are growing but turnover "
                "is flat, new customers are spending "
                "less than regulars.\n\n"
                "**Turnover trend** auto-aggregates: daily "
                "(<60 days), weekly (60\u2013180 days), monthly "
                "(>180 days). Excludes the current "
                "incomplete period."
            )

        # --- Trend ---
        section_gap()
        st.markdown("### Turnover Trend")

        if trend_data is not None and len(trend_data) > 0:
            fig_trend = go.Figure()

            fig_trend.add_trace(go.Scatter(
                x=trend_data["Period"],
                y=trend_data["Revenue"],
                name="Turnover (€)",
                mode="lines+markers",
                line=dict(color="#2ecc71", width=2.5, shape="spline"),
                marker=dict(size=5),
                fill="tozeroy",
                fillcolor="rgba(46,204,113,0.10)",
                yaxis="y",
                hovertemplate="€%{y:,.0f}<extra>Turnover</extra>",
            ))

            fig_trend.update_layout(
                height=400,
                margin=dict(t=20, b=40, l=60, r=60),
                yaxis=dict(
                    title="Turnover (€)",
                    showgrid=True,
                    gridcolor="rgba(255,255,255,0.06)",
                    rangemode="tozero",
                ),
                hovermode="x unified",
                plot_bgcolor="rgba(0,0,0,0)",
                showlegend=False,
            )

            st.plotly_chart(fig_trend, use_container_width=True)

        # --- Turnover by Source ---
        if source_rev is not None:
            section_gap()
            st.markdown("### Turnover by Booking Source")
            st.caption("Where does turnover come from? Informs marketing spend allocation.")

            source_display = source_rev.copy()
            source_display = source_display.rename(columns={"Revenue": "Turnover"})
            source_display["Turnover"] = source_display["Turnover"].apply(format_euro)
            source_display = source_display.rename(columns={"AOV": "Avg Booking Value"})
            source_display["Avg Booking Value"] = (
                source_display["Avg Booking Value"]
                .apply(lambda x: format_euro(x, 2))
            )
            source_display["% of Total"] = source_display["% of Total"].apply(
                lambda x: f"{x:.1f}%".replace(".", ",")
            )
            source_display["Bookings"] = source_display["Bookings"].apply(format_number)

            cols = [
                "Source", "Turnover", "% of Total",
                "Bookings", "Avg Booking Value",
            ]
            styled_source = style_dataframe_right_align(
                source_display[cols],
                exclude_cols=["Source"]
            )
            st.dataframe(styled_source, use_container_width=True, hide_index=True)

            source_chart = source_rev.sort_values("Revenue", ascending=True)
            fig_source = px.bar(
                source_chart,
                x="Revenue",
                y="Source",
                orientation="h",
                title="Turnover by Source",
                labels={"Revenue": "Turnover (€)"},
                text=source_chart["Revenue"].apply(lambda x: format_euro(x)),
            )
            fig_source.update_traces(marker_color="#2ecc71", textposition="outside")
            fig_source.update_layout(
                height=max(250, len(source_chart) * 40 + 100),
                margin=dict(t=50, r=80),
                yaxis_title="",
            )
            st.plotly_chart(fig_source, use_container_width=True)

        # --- Turnover by Location ---
        if loc_rev is not None:
            section_gap()
            st.markdown("### Turnover by Location")

            loc_display = loc_rev.copy()
            loc_display = loc_display.rename(columns={"Revenue": "Turnover"})
            loc_display["Turnover"] = loc_display["Turnover"].apply(format_euro)
            loc_display = loc_display.rename(columns={"AOV": "Avg Booking Value"})
            loc_display["Avg Booking Value"] = (
                loc_display["Avg Booking Value"]
                .apply(lambda x: format_euro(x, 2))
            )
            loc_display["% of Turnover"] = loc_display["% of Turnover"].apply(
                lambda x: f"{x:.1f}%".replace(".", ",")
            )
            loc_display["Bookings"] = loc_display["Bookings"].apply(format_number)

            display_cols = [
                "Location", "Turnover", "% of Turnover",
                "Bookings", "Avg Booking Value",
            ]
            if "Rev/Participant" in loc_display.columns:
                loc_display["Rev/Participant"] = loc_display["Rev/Participant"].apply(
                    lambda x: format_euro(x, 2)
                )
                display_cols.append("Rev/Participant")

            styled_loc = style_dataframe_right_align(
                loc_display[display_cols],
                exclude_cols=["Location"]
            )
            st.dataframe(styled_loc, use_container_width=True, hide_index=True)

            loc_chart = loc_rev.copy()
            loc_chart["Location"] = loc_chart["Location"].str.replace("Northern Sauna ", "", regex=False)

            fig_rev_loc = px.bar(
                loc_chart.sort_values("Revenue"),
                x="Revenue",
                y="Location",
                orientation="h",
                title="Turnover by Location",
                labels={"Revenue": "Turnover (€)"},
                color="Revenue",
                color_continuous_scale=[[0, "#1a7a42"], [1, "#2ecc71"]],
            )
            fig_rev_loc.update_traces(
                text=loc_chart.sort_values("Revenue")["Revenue"].apply(
                    lambda v: f"€{v/1000:.0f}k" if v >= 1000 else f"€{v:.0f}"
                ),
                textposition="outside",
                textfont_size=12,
            )
            fig_rev_loc.update_layout(
                height=max(350, len(loc_chart) * 32),
                margin=dict(t=50, r=80),
                coloraxis_showscale=False,
                xaxis_title="Turnover (€)",
                yaxis_title="",
            )
            st.plotly_chart(fig_rev_loc, use_container_width=True)

            if "Rev/Participant" in loc_rev.columns:
                st.caption(
                    "Compare Rev/Participant across locations"
                    " in the table above to spot pricing"
                    " opportunities."
                )
            else:
                st.caption("Add participant data to compare Rev/Participant across locations.")

        # --- Turnover per Participant by Location ---
        if (
            loc_rev is not None
            and "Total paid" in df.columns
            and "Participants" in df.columns
            and location_col in df.columns
        ):
            section_gap()
            st.markdown("### Turnover per Participant by Location")
            st.caption("Which locations generate the highest turnover efficiency?")

            loc_eff = df[[location_col, "Total paid", "Participants"]].dropna()
            loc_eff = loc_eff[
                (loc_eff["Total paid"] > 0) & (loc_eff["Participants"] > 0)
            ]

            if len(loc_eff) > 0:
                metrics = loc_eff.groupby(location_col).agg(
                    avg_revenue=("Total paid", "mean"),
                    total_revenue=("Total paid", "sum"),
                    avg_participants=("Participants", "mean"),
                    total_participants=("Participants", "sum"),
                ).reset_index()
                metrics["revenue_per_participant"] = (
                    metrics["total_revenue"] / metrics["total_participants"]
                )
                metrics["booking_count"] = (
                    loc_eff.groupby(location_col).size().values
                )

                fig_bubble = px.scatter(
                    metrics,
                    x="avg_participants",
                    y="avg_revenue",
                    size="booking_count",
                    color=location_col,
                    hover_data=["revenue_per_participant", "booking_count"],
                    labels={
                        "avg_participants": "Avg Participants per Booking",
                        "avg_revenue": "Avg Turnover per Booking",
                        "booking_count": "Total Bookings",
                    },
                )
                fig_bubble.update_layout(
                    showlegend=True,
                    height=450,
                    margin=dict(t=20, r=20),
                )
                st.plotly_chart(fig_bubble, use_container_width=True)

        # --- Key Takeaways ---
        section_gap()

        # Date range for takeaway title
        _rev_date_from = df["booking_date"].min().strftime("%-d %b %Y")
        _rev_date_to = df["booking_date"].max().strftime("%-d %b %Y")
        _rev_takeaway_title = f"Key Takeaways ({_rev_date_from} \u2013 {_rev_date_to})"
        _rev_date_range_days = (df["booking_date"].max() - df["booking_date"].min()).days
        _show_takeaways = _rev_date_range_days >= 90

        with st.expander(_rev_takeaway_title):
         if not _show_takeaways:
            st.caption(
                f"Select at least 3 months of data for meaningful takeaways. "
                f"Current range: {_rev_date_range_days} days. "
                f"For the best insights, select the full season "
                f"(September\u2013April)."
            )
         else:

            # 1. Turnover growth decomposition
            rev_per_customer = (
                total_revenue / unique_customers if unique_customers > 0 else 0
            )

            # Identify the main growth driver
            deltas = {
                "bookings": bookings_delta_pct,
                "avg booking value": aov_delta_pct,
                "unique customers": customers_delta_pct,
            }
            valid_deltas = {k: v for k, v in deltas.items() if v is not None}

            if valid_deltas and turnover_delta_pct is not None:
                biggest_driver = max(valid_deltas, key=lambda k: abs(valid_deltas[k]))
                driver_pct = valid_deltas[biggest_driver]
                direction = "up" if turnover_delta_pct > 0 else "down"

                st.info(
                    f"**Turnover is {direction} {abs(turnover_delta_pct):.0f}% "
                    f"vs the prior period.** The biggest driver is "
                    f"**{biggest_driver}** ({driver_pct:+.0f}%). "
                    + (
                        "More customers are booking \u2014 acquisition is "
                        "working. Focus on retaining them for repeat visits."
                        if biggest_driver == "unique customers" and driver_pct > 0
                        else (
                            "Existing customers are booking more often \u2014 "
                            "strong loyalty signal."
                            if biggest_driver == "bookings" and driver_pct > 0
                            else (
                                "Average booking value is rising \u2014 "
                                "customers are spending more per visit."
                                if biggest_driver == "avg booking value" and driver_pct > 0
                                else f"Investigate what's driving the decline "
                                f"in {biggest_driver}."
                            )
                        )
                    )
                )

            # 2. Turnover per customer (season value)
            st.info(
                f"**Average turnover per customer this season: "
                f"{format_euro(rev_per_customer)}** "
                f"(total turnover \u00f7 unique customers). "
                f"Note: this is pulled down by the ~65% who booked only once. "
                f"For a forward-looking projection that accounts for retention "
                f"and repeat visits, see the CLV (Customer Lifetime Value) tab "
                f"on the Customers page.\n\n"
                f"As a rough CPA (cost per acquisition) benchmark: acquiring "
                f"one new customer is justified up to "
                f"~{format_euro(rev_per_customer * 0.3)} in ad spend "
                f"(30% of single-season value)."
            )

            # 3. Location concentration
            if loc_rev is not None and len(loc_rev) >= 2:
                top_loc = loc_rev.iloc[0]
                top_loc_name = top_loc["Location"].replace("Northern Sauna ", "")
                top_loc_pct = top_loc["% of Turnover"]
                bottom_loc = loc_rev.iloc[-1]
                bottom_loc_name = bottom_loc["Location"].replace("Northern Sauna ", "")
                bottom_loc_pct = bottom_loc["% of Turnover"]

                st.info(
                    f"**{top_loc_name} generates {top_loc_pct:.0f}% of total "
                    f"turnover** while {bottom_loc_name} contributes only "
                    f"{bottom_loc_pct:.0f}%. "
                    + (
                        f"Turnover is heavily concentrated \u2014 if "
                        f"{top_loc_name} underperforms, the impact on "
                        f"total turnover is significant. Consider "
                        f"investing in growth at lower-performing locations "
                        f"to diversify."
                        if top_loc_pct >= 20
                        else "Turnover is well distributed across locations."
                    )
                )

            # 4. AOV compression check
            if aov_delta_pct is not None and bookings_delta_pct is not None:
                if aov_delta_pct < -3 and bookings_delta_pct > 0:
                    st.info(
                        f"**Average booking value is declining "
                        f"({aov_delta_pct:+.0f}%) while bookings grow "
                        f"({bookings_delta_pct:+.0f}%).** This may indicate "
                        f"membership discounts or promotions are diluting "
                        f"per-booking revenue. Check if the volume increase "
                        f"compensates \u2014 total turnover "
                        + (
                            f"is still up ({turnover_delta_pct:+.0f}%), "
                            f"so the trade-off is working."
                            if turnover_delta_pct and turnover_delta_pct > 0
                            else f"is also declining ({turnover_delta_pct:+.0f}%), "
                            f"meaning volume isn't compensating for the lower "
                            f"booking value."
                        )
                    )

            # 5. Peak revenue month
            if trend_data is not None and len(trend_data) >= 3 and freq_label == "Month":
                peak_month_row = trend_data.loc[trend_data["Revenue"].idxmax()]
                peak_month_name = peak_month_row["Period"].strftime("%B %Y")
                peak_month_rev = peak_month_row["Revenue"]
                avg_month_rev = trend_data["Revenue"].mean()
                peak_vs_avg = (peak_month_rev / avg_month_rev - 1) * 100

                st.info(
                    f"**Peak revenue month: {peak_month_name}** with "
                    f"{format_euro(peak_month_rev)} ({peak_vs_avg:+.0f}% vs "
                    f"average month). Invest marketing budget heaviest in "
                    f"the months leading up to your peak \u2014 that's when "
                    f"demand is building and conversion rates are highest."
                )



render_footer()
