"""
Northern Sauna Analytics - Customers Page
Customer value, lifetime value, segmentation, and location loyalty
"""

import sys  # noqa: I001
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, '..')
from bq_data_loader import init_session_state, render_bookeo_settings  # noqa: E402, I001
from features.revenue.formatters import (  # noqa: E402
    format_euro, format_number, section_gap, style_dataframe_right_align,
)
from data.bq_client import _BQ_TO_STREAMLIT_LOCATION  # noqa: E402
from features.revenue.queries import (  # noqa: E402
    _get_clv_inputs, _get_clv_inputs_by_location,
    _get_location_loyalty, _get_period_summary, _get_prev_customer_metrics,
)
from components.demo_banner import render_demo_banner, render_footer  # noqa: E402
from utils import render_header, render_sidebar_nav  # noqa: E402

# Page configuration
st.set_page_config(
    page_title="Northern Sauna - Customers",
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
render_bookeo_settings(page_key="customers", date_column="booking_created_at")

st.markdown("## Customer Analysis")
st.markdown("Customer value, lifetime value, and location loyalty")

# Initialize session state using centralized function
init_session_state()

# Check authentication
if not st.session_state.get('authenticated', False):
    st.warning("Please log in to access this page.")
    st.page_link("app.py", label="Go to Login", icon=":material/login:")
    st.stop()

render_sidebar_nav("Customers", ["Overview", "Customer Profile", "Lifetime Value", "Location Loyalty"])

render_demo_banner()

# Main content
if st.session_state.df1 is None or st.session_state.df2 is None:
    st.info("**No data loaded.** Use the date selector above to load booking data from BigQuery.")
else:
    df = st.session_state.df2.copy()

    date_col = "Created" if "Created" in df.columns else "Start"
    revenue_col = "Total paid" if "Total paid" in df.columns else (
        "Total gross" if "Total gross" in df.columns else None
    )
    email_col = "Email address" if "Email address" in df.columns else None
    location_col = "Location" if "Location" in df.columns else None
    private_col = "Private event" if "Private event" in df.columns else None
    participants_col = "Participants" if "Participants" in df.columns else None

    if revenue_col is None:
        st.warning("**Turnover column not found in data.**")
    elif email_col is None:
        st.warning("**Email column not found — customer analysis requires email data.**")
    else:
        # ================================================================
        #  DATA COMPUTATION
        # ================================================================
        _loading = st.empty()
        _loading.status("Loading customer analysis...", state="running")

        df["revenue"] = pd.to_numeric(df[revenue_col], errors="coerce").fillna(0)
        df["booking_date"] = pd.to_datetime(df[date_col], errors="coerce")
        if participants_col:
            df["participants"] = pd.to_numeric(df[participants_col], errors="coerce").fillna(0)

        # Filter to selected date range
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

        # Period-over-period
        start_dt = pd.Timestamp(st.session_state.bookeo_start_date)
        end_dt = pd.Timestamp(st.session_state.bookeo_end_date)
        period_days = (end_dt - start_dt).days + 1
        prev_end = start_dt - timedelta(days=1)
        prev_start = prev_end - timedelta(days=period_days - 1)

        prev = _get_period_summary(
            prev_start.strftime("%Y-%m-%d"),
            prev_end.strftime("%Y-%m-%d"),
        )

        # --- Customer value data ---
        has_customer_data = False
        customer_value = None
        total_customers = 0
        repeat_pct = 0
        avg_bookings_per_customer = 0
        retention_rate = 0.3
        cohort_size = 0
        first_month_start = None
        segment_order = ["New", "Regular", "VIP"]
        prev_repeat_pct = None
        prev_avg_bookings_per_customer = None
        prev_retention_pct = None

        customer_data = df[df[email_col].notna() & (df[email_col] != "")].copy()

        if len(customer_data) > 0:
            has_customer_data = True
            customer_value = customer_data.groupby(email_col).agg(
                bookings=("revenue", "count"),
                lifetime_value=("revenue", "sum"),
                first_booking=("booking_date", "min"),
                is_member=("Member", "any"),
            ).reset_index().rename(columns={email_col: "email"})

            total_customers = len(customer_value)

            # Repeat Customer % and Avg Bookings/Customer
            repeat_count = (customer_value["bookings"] >= 2).sum()
            repeat_pct = repeat_count / total_customers * 100 if total_customers > 0 else 0
            avg_bookings_per_customer = (
                total_bookings / total_customers
                if total_customers > 0 else 0
            )

            # Previous period: compute same metrics
            if prev["unique_customers"] > 0:
                prev_avg_bookings_per_customer = prev["bookings"] / prev["unique_customers"]
                prev_cust = _get_prev_customer_metrics(
                    prev_start.strftime("%Y-%m-%d"),
                    prev_end.strftime("%Y-%m-%d"),
                )
                prev_repeat_pct = prev_cust["repeat_pct"]
                prev_retention_pct = prev_cust["retention_pct"]

            # Retention Rate
            min_date = customer_data["booking_date"].min()
            max_date = customer_data["booking_date"].max()

            first_month_start = min_date.replace(day=1)
            if min_date.day > 1:
                first_month_start = first_month_start + pd.DateOffset(months=1)

            first_month_end = (
                first_month_start + pd.DateOffset(months=1) - pd.Timedelta(days=1)
            )
            retention_window_end = (
                first_month_start + pd.DateOffset(months=13) - pd.Timedelta(days=1)
            )

            customer_first = (
                customer_data.groupby(email_col)["booking_date"].min().reset_index()
            )
            customer_first.columns = ["email", "first_booking"]

            cohort = customer_first[
                (customer_first["first_booking"] >= first_month_start)
                & (customer_first["first_booking"] <= first_month_end)
            ]["email"].tolist()

            cohort_size = len(cohort)

            if cohort_size > 0:
                cohort_bookings = customer_data[customer_data[email_col].isin(cohort)].copy()
                cohort_bookings["rank"] = cohort_bookings.groupby(email_col)[
                    "booking_date"
                ].rank(method="first")
                second = cohort_bookings[cohort_bookings["rank"] == 2]
                returning = (second["booking_date"] <= retention_window_end).sum()
                retention_rate = returning / cohort_size
            else:
                retention_rate = 0.3

            # Segment categorization
            def categorize_segment(bookings):
                if bookings >= 5:
                    return "VIP"
                elif bookings >= 2:
                    return "Regular"
                else:
                    return "New"

            customer_value["segment"] = customer_value["bookings"].apply(categorize_segment)
            customer_value["segment"] = pd.Categorical(
                customer_value["segment"], categories=segment_order, ordered=True
            )

            # Segment summary
            seg_summary = customer_value.groupby("segment", observed=True).agg(
                Customers=("email", "count"),
                Members=("is_member", "sum"),
                Total_Revenue=("lifetime_value", "sum"),
                Avg_Revenue=("lifetime_value", "mean"),
                Avg_Bookings=("bookings", "mean"),
            ).reset_index().rename(columns={"segment": "Segment"})
            seg_summary["Members"] = seg_summary["Members"].astype(int)
            seg_summary["% of Members"] = (
                seg_summary["Members"] / seg_summary["Customers"] * 100
            ).round(1)
            seg_summary["% of Customers"] = (
                seg_summary["Customers"] / total_customers * 100
            ).round(1)
            seg_summary["% of Turnover"] = (
                seg_summary["Total_Revenue"] / total_revenue * 100
            ).round(1)

            # CLV computation (12-month rolling window, parallel queries)
            clv_end_str = end_dt.strftime("%Y-%m-%d")
            prev_end_str = prev_end.strftime("%Y-%m-%d")

            with ThreadPoolExecutor(max_workers=2) as executor:
                clv_future = executor.submit(_get_clv_inputs, clv_end_str)
                prev_clv_future = executor.submit(_get_clv_inputs, prev_end_str)
                clv_inputs = clv_future.result()
                prev_clv_inputs = prev_clv_future.result()

            clv_aov = clv_inputs["aov"]
            clv_annual_frequency = clv_inputs["mean_annual_frequency"]
            clv_monthly_frequency = clv_annual_frequency / 12
            clv_retention_rate = clv_inputs["retention_rate"]
            clv_monthly_retention = clv_retention_rate ** (1 / 12)
            clv_num_cohorts = clv_inputs["num_cohorts"]
            clv_window_start = clv_inputs["window_start"]

            # Compute CLV for all horizons (1, 2, 3 years)
            clv_by_horizon = {}
            for years in (1, 2, 3):
                months = years * 12
                clv_by_horizon[years] = sum(
                    clv_aov * clv_monthly_frequency * (clv_monthly_retention ** m)
                    for m in range(months)
                )

            # Previous period CLV
            prev_clv_by_horizon = {1: None, 2: None, 3: None}
            prev_clv_aov = None
            prev_clv_annual_frequency = None
            prev_clv_retention_rate = None
            if prev_clv_inputs["total_customers"] > 0 and prev_clv_inputs["aov"] > 0:
                prev_clv_aov = prev_clv_inputs["aov"]
                prev_clv_annual_frequency = prev_clv_inputs["mean_annual_frequency"]
                prev_clv_monthly_freq = prev_clv_annual_frequency / 12
                prev_clv_retention_rate = prev_clv_inputs["retention_rate"]
                prev_clv_monthly_ret = prev_clv_retention_rate ** (1 / 12)
                for years in (1, 2, 3):
                    months = years * 12
                    prev_clv_by_horizon[years] = sum(
                        prev_clv_aov * prev_clv_monthly_freq * (prev_clv_monthly_ret ** m)
                        for m in range(months)
                    )

            # CLV by segment (computed for all horizons)
            seg_clv_by_horizon = {1: [], 2: [], 3: []}
            for seg in clv_inputs.get("segments", []):
                seg_mf = seg["mean_frequency"] / 12
                seg_mr = seg["retention_rate"] ** (1 / 12)
                seg_clvs = {}
                for years in (1, 2, 3):
                    months = years * 12
                    seg_clvs[years] = sum(
                        seg["aov"] * seg_mf * (seg_mr ** m) for m in range(months)
                    )
                for years in (1, 2, 3):
                    seg_clv_by_horizon[years].append({
                        "Segment": seg["segment"],
                        "Customers": seg["customers"],
                        "AOV": seg["aov"],
                        "Retention": seg["retention_rate"],
                        "CLV": seg_clvs[years],
                    })

        # --- Private event data ---
        pe_computed = False
        private_count = 0
        if private_col and private_col in df.columns:
            pe_data = df.copy()
            pe_data["is_private"] = pe_data[private_col].fillna(False)
            if pe_data["is_private"].dtype == object:
                pe_data["is_private"] = pe_data["is_private"].astype(str).str.lower().isin(
                    ["yes", "true", "1", "ja"]
                )

            private_count = pe_data["is_private"].sum()
            regular_count_pe = len(pe_data) - private_count

            if private_count > 0:
                pe_computed = True
                private_rev = pe_data[pe_data["is_private"]]["revenue"]
                regular_rev_pe = pe_data[~pe_data["is_private"]]["revenue"]
                avg_rev_private = private_rev.mean()
                avg_rev_regular = regular_rev_pe.mean()
                private_pct = private_count / len(pe_data) * 100
                rev_diff_pct = (
                    (avg_rev_private - avg_rev_regular) / avg_rev_regular * 100
                    if avg_rev_regular > 0 else 0
                )

        # ================================================================
        #  DISPLAY
        # ================================================================
        _loading.empty()

        def _delta(pct):
            if pct is None:
                return None
            return f"{pct:+.1f}%".replace(".", ",")

        if not has_customer_data:
            st.info(
                "No valid email addresses found for customer analysis."
            )
        else:
            tab_overview, tab_profile, tab_clv, tab_loyalty = st.tabs([
                "Overview", "Customer Profile", "Lifetime Value", "Location Loyalty"
            ])

            # ==================== TAB 1: OVERVIEW ====================
            with tab_overview:

                # --- Customer KPIs ---
                st.markdown("### Customer Overview")

                new_customers = total_customers - repeat_count
                returning_customers = repeat_count
                avg_rev_per_customer = (
                    total_revenue / total_customers
                    if total_customers > 0 else 0
                )

                # Previous period deltas
                prev_total_cust = prev["unique_customers"]
                prev_new_cust = None
                prev_returning_cust = None
                prev_avg_rev_cust = None
                if prev_total_cust > 0:
                    prev_avg_rev_cust = prev["turnover"] / prev_total_cust
                    if prev_repeat_pct is not None:
                        prev_returning_cust = int(
                            round(prev_total_cust * prev_repeat_pct / 100)
                        )
                        prev_new_cust = prev_total_cust - prev_returning_cust

                total_cust_delta = (
                    (total_customers - prev_total_cust) / prev_total_cust * 100
                    if prev_total_cust > 0 else None
                )
                new_cust_delta = (
                    (new_customers - prev_new_cust) / prev_new_cust * 100
                    if prev_new_cust and prev_new_cust > 0 else None
                )
                returning_cust_delta = (
                    (returning_customers - prev_returning_cust)
                    / prev_returning_cust * 100
                    if prev_returning_cust and prev_returning_cust > 0
                    else None
                )
                avg_rev_cust_delta = (
                    (avg_rev_per_customer - prev_avg_rev_cust)
                    / prev_avg_rev_cust * 100
                    if prev_avg_rev_cust and prev_avg_rev_cust > 0
                    else None
                )

                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric(
                        "Total Customers",
                        format_number(total_customers),
                        delta=_delta(total_cust_delta),
                        help=(
                            "Unique customers (by email) who "
                            "booked in this period. "
                            f"Previous: "
                            f"{format_number(prev_total_cust) if prev_total_cust else 'N/A'}."
                        )
                    )
                with col2:
                    st.metric(
                        "New Customers",
                        format_number(new_customers),
                        delta=_delta(new_cust_delta),
                        help=(
                            "Customers who booked exactly once "
                            "in this period \u2014 first-timers "
                            "or one-time visitors. "
                            f"Previous: "
                            f"{format_number(prev_new_cust) if prev_new_cust is not None else 'N/A'}."
                        )
                    )
                with col3:
                    returning_pct = (
                        returning_customers / total_customers * 100
                        if total_customers > 0 else 0
                    )
                    prev_returning_pct = (
                        prev_returning_cust / prev_total_cust * 100
                        if prev_returning_cust is not None and prev_total_cust > 0
                        else None
                    )
                    returning_pct_delta = (
                        (returning_pct - prev_returning_pct)
                        / prev_returning_pct * 100
                        if prev_returning_pct and prev_returning_pct > 0
                        else None
                    )
                    st.metric(
                        "Returning Customers",
                        f"{returning_pct:.1f}%".replace(".", ","),
                        delta=_delta(returning_pct_delta),
                        help=(
                            f"{format_number(returning_customers)} of "
                            f"{format_number(total_customers)} customers "
                            "booked 2+ times in this period. "
                            f"Previous: "
                            f"{f'{prev_returning_pct:.1f}%'.replace('.', ',') if prev_returning_pct is not None else 'N/A'}."
                        )
                    )
                with col4:
                    st.metric(
                        "Avg Turnover / Customer",
                        format_euro(avg_rev_per_customer, 2),
                        delta=_delta(avg_rev_cust_delta),
                        help=(
                            "Total turnover divided by unique "
                            "customers. How much each customer "
                            "is worth in this period. "
                            f"Previous: "
                            f"{format_euro(prev_avg_rev_cust, 2) if prev_avg_rev_cust else 'N/A'}."
                        )
                    )

                with st.expander("How to read these metrics"):
                    st.markdown(
                        "These four numbers tell the story of "
                        "your customer base:\n\n"
                        "- **Total Customers** \u2014 how many "
                        "unique people booked in this period?\n"
                        "- **New Customers** \u2014 how many "
                        "visited only once? These are either "
                        "first-timers or people who haven\u2019t "
                        "come back yet.\n"
                        "- **Returning Customers** \u2014 how "
                        "many booked 2+ times? This is your "
                        "loyal base. Growing this number means "
                        "your retention is working.\n"
                        "- **Avg Turnover / Customer** \u2014 "
                        "total turnover divided by customers. "
                        "If this goes up, each customer is "
                        "spending more (higher booking value or "
                        "more visits).\n\n"
                        "The green/red percentages compare to "
                        f"the previous period "
                        f"({prev_start.strftime('%d %b')}"
                        f" \u2013 {prev_end.strftime('%d %b %Y')}). "
                        "Hover over **?** to see the previous "
                        "value."
                    )

                # --- Customer Segments ---
                section_gap()
                st.markdown("### Customer Segments")
                st.caption("VIP (5+ bookings) | Regular (2-4) | New (1 booking)")

                seg_display = seg_summary.copy()
                seg_display["Customers"] = seg_display["Customers"].apply(format_number)
                seg_display["Members"] = seg_display["Members"].apply(format_number)
                seg_display["% of Members"] = seg_display["% of Members"].apply(
                    lambda x: f"{x:.1f}%".replace(".", ",")
                )
                seg_display["Total_Revenue"] = seg_display["Total_Revenue"].apply(format_euro)
                seg_display["Avg_Revenue"] = seg_display["Avg_Revenue"].apply(
                    lambda x: format_euro(x, 2)
                )
                seg_display["Avg_Bookings"] = seg_display["Avg_Bookings"].apply(
                    lambda x: f"{x:.1f}".replace(".", ",")
                )
                seg_display["% of Customers"] = seg_display["% of Customers"].apply(
                    lambda x: f"{x:.1f}%".replace(".", ",")
                )
                seg_display["% of Turnover"] = seg_display["% of Turnover"].apply(
                    lambda x: f"{x:.1f}%".replace(".", ",")
                )

                seg_display = seg_display.rename(columns={
                    "Total_Revenue": "Total Turnover",
                    "Avg_Revenue": "Avg Turnover",
                    "Avg_Bookings": "Avg Bookings",
                })
                seg_cols_display = [
                    "Segment", "Customers", "% of Customers", "Members", "% of Members",
                    "Avg Bookings", "Total Turnover", "% of Turnover", "Avg Turnover",
                ]
                styled_seg = style_dataframe_right_align(
                    seg_display[seg_cols_display], exclude_cols=["Segment"]
                )
                st.dataframe(styled_seg, use_container_width=True, hide_index=True)

                section_gap()

                seg_bar_data = seg_summary[["Segment", "% of Customers", "% of Turnover"]].melt(
                    id_vars="Segment", var_name="Metric", value_name="Percentage"
                )
                fig_seg_bar = px.bar(
                    seg_bar_data,
                    x="Segment",
                    y="Percentage",
                    color="Metric",
                    barmode="group",
                    title="Customer % vs Turnover % by Segment",
                    labels={"Percentage": "%"},
                    color_discrete_map={
                        "% of Customers": "#3498db",
                        "% of Turnover": "#2ecc71",
                    },
                    text=seg_bar_data["Percentage"].apply(
                        lambda x: f"{x:.1f}%".replace(".", ",")
                    ),
                )
                fig_seg_bar.update_traces(textposition="outside")
                fig_seg_bar.update_layout(height=400, margin=dict(t=50))
                st.plotly_chart(fig_seg_bar, use_container_width=True)

                fig_seg_aov = px.bar(
                    seg_summary,
                    x="Segment",
                    y="Avg_Revenue",
                    title="Avg Turnover per Customer by Segment",
                    labels={"Avg_Revenue": "Avg Turnover (\u20ac)"},
                    text=seg_summary["Avg_Revenue"].apply(lambda x: format_euro(x)),
                    color="Segment",
                    color_discrete_map={
                        "New": "#3498db", "Regular": "#f39c12", "VIP": "#9b59b6"
                    },
                )
                fig_seg_aov.update_traces(textposition="outside")
                fig_seg_aov.update_layout(
                    height=400, showlegend=False, margin=dict(t=50)
                )
                st.plotly_chart(fig_seg_aov, use_container_width=True)

                st.caption(
                    "When the green bar is much taller than "
                    "blue, that segment punches above its "
                    "weight in turnover."
                )

                # --- Returning Customers by Location ---
                if location_col and location_col in df.columns:
                    section_gap()
                    st.markdown("### Returning Customers by Location")

                    loc_total = df.groupby(location_col)[email_col].nunique().reset_index()
                    loc_total.columns = ["Location", "Total Customers"]

                    loc_visits = df.groupby([location_col, email_col]).size().reset_index(name="visits")
                    loc_repeat = loc_visits[loc_visits["visits"] >= 2].groupby(location_col)[email_col].nunique().reset_index()
                    loc_repeat.columns = ["Location", "Returning"]

                    loc_stats = loc_total.merge(loc_repeat, on="Location", how="left").fillna(0)
                    loc_stats["Returning"] = loc_stats["Returning"].astype(int)
                    loc_stats["Return Rate (%)"] = (
                        loc_stats["Returning"] / loc_stats["Total Customers"] * 100
                    ).round(1)
                    loc_stats = loc_stats.sort_values("Total Customers", ascending=False)

                    # Total row
                    _tot_cust = loc_stats["Total Customers"].sum()
                    _tot_ret = loc_stats["Returning"].sum()
                    _tot_rate = round(_tot_ret / _tot_cust * 100, 1) if _tot_cust > 0 else 0
                    loc_stats = pd.concat([loc_stats, pd.DataFrame([{
                        "Location": "Total",
                        "Total Customers": _tot_cust,
                        "Returning": _tot_ret,
                        "Return Rate (%)": _tot_rate,
                    }])], ignore_index=True)

                    st.dataframe(
                        loc_stats,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Total Customers": st.column_config.NumberColumn("Total Customers"),
                            "Returning": st.column_config.NumberColumn("Returning", help="Customers who booked 2+ times at this location"),
                            "Return Rate (%)": st.column_config.NumberColumn("Return Rate (%)", format="%.1f"),
                        },
                    )

                    with st.expander("Why is this lower than the overall Returning Customers %?"):
                        st.markdown(
                            f"The overall **Returning Customers ({returning_pct:.1f}%)** counts anyone "
                            "who booked **2+ times across all Northern Sauna locations**. "
                            "The per-location Return Rate only counts customers who came back "
                            "to **that same location** 2+ times.\n\n"
                            "The difference shows that many repeat customers try different locations "
                            "rather than revisiting the same one — a sign of strong brand loyalty "
                            "across the network, not just to a single spot."
                        )

                # --- Key Takeaways ---
                section_gap()
                with st.expander("Key Takeaways"):
                    # Returning customer opportunity
                    if returning_pct is not None and returning_pct < 40:
                        st.info(
                            f"**Only {returning_pct:.0f}% of customers return.** "
                            f"That means {format_number(new_customers)} people visited once and never came back. "
                            "A post-visit email with a small discount could turn even 5% of them "
                            "into repeat visitors — that's "
                            f"**{format_number(int(new_customers * 0.05))} extra bookings**."
                        )
                    elif returning_pct is not None:
                        st.info(
                            f"**{returning_pct:.0f}% of customers return** — strong repeat base. "
                            "Focus on increasing their visit frequency rather than only "
                            "acquiring new customers."
                        )

                    # VIP concentration
                    if seg_summary is not None and len(seg_summary) > 0:
                        vip_row = seg_summary[seg_summary["Segment"] == "VIP"]
                        new_row = seg_summary[seg_summary["Segment"] == "New"]
                        if len(vip_row) > 0 and len(new_row) > 0:
                            vip_rev_share = vip_row["% of Turnover"].iloc[0]
                            vip_cust_share = vip_row["% of Customers"].iloc[0]
                            new_cust_share = new_row["% of Customers"].iloc[0]
                            if vip_rev_share > vip_cust_share * 2:
                                st.info(
                                    f"**VIPs are {vip_cust_share:.0f}% of customers but "
                                    f"drive {vip_rev_share:.0f}% of turnover.** "
                                    "Losing even a few VIPs hits hard. Consider a loyalty "
                                    "program or personal outreach to keep them engaged."
                                )
                            if new_cust_share > 60:
                                st.info(
                                    f"**{new_cust_share:.0f}% of customers are first-timers.** "
                                    "Your acquisition is working, but the real growth unlock is "
                                    "converting them into Regulars. A 'second visit' incentive "
                                    "has the highest ROI right now."
                                )

                    # Revenue per customer
                    if avg_rev_per_customer > 0:
                        st.info(
                            f"**Average customer spends {format_euro(avg_rev_per_customer)}.** "
                            "To grow turnover, you can either get more customers (acquisition) "
                            "or increase spend per customer (upselling, memberships, group bookings)."
                        )



            # ==================== TAB 2: CUSTOMER PROFILE ====================
            with tab_profile:

                # --- Group Size Distribution ---
                if participants_col and "participants" in df.columns:
                    st.markdown("### Group Size Distribution")
                    st.caption("How many participants typically book together?")

                    p_clean = df["participants"].dropna()
                    p_clean = p_clean[p_clean > 0]

                    if len(p_clean) > 0:
                        avg_size = p_clean.mean()
                        median_size = p_clean.median()
                        mode_vals = p_clean.mode()
                        mode_size = mode_vals.iloc[0] if len(mode_vals) > 0 else 0

                        gs_cols = st.columns(4)
                        with gs_cols[0]:
                            st.metric("Avg Group Size", f"{avg_size:.1f}")
                        with gs_cols[1]:
                            st.metric("Median", f"{median_size:.0f}")
                        with gs_cols[2]:
                            st.metric("Most Common", f"{mode_size:.0f}")
                        with gs_cols[3]:
                            st.metric("Max", f"{p_clean.max():.0f}")

                        fig_hist = px.histogram(
                            p_clean,
                            nbins=min(20, int(p_clean.max())),
                            labels={"value": "Participants", "count": "Bookings"},
                            color_discrete_sequence=["#FF6B35"],
                        )
                        fig_hist.update_layout(
                            xaxis_title="Number of Participants",
                            yaxis_title="Number of Bookings",
                            bargap=0.1,
                            showlegend=False,
                            height=350,
                            margin=dict(t=10, r=20),
                        )
                        st.plotly_chart(fig_hist, use_container_width=True)

                        conditions = [
                            p_clean == 1, p_clean == 2,
                            (p_clean >= 3) & (p_clean <= 4),
                            (p_clean >= 5) & (p_clean <= 6),
                            (p_clean >= 7) & (p_clean <= 10),
                            p_clean >= 11,
                        ]
                        choices = [
                            "1 (Solo)", "2 (Couple)", "3-4 (Small group)",
                            "5-6 (Medium group)", "7-10 (Large group)",
                            "11+ (Extra large)",
                        ]
                        cats = pd.Categorical(
                            np.select(conditions, choices, default="Unknown"),
                            categories=choices, ordered=True,
                        )
                        cat_df = pd.DataFrame({
                            "Participants": p_clean.values,
                            "Category": cats,
                        })
                        cat_stats = cat_df.groupby("Category", observed=True).agg(
                            Bookings=("Participants", "count"),
                            Total_Participants=("Participants", "sum"),
                        ).reset_index()
                        cat_stats["% of Bookings"] = (
                            cat_stats["Bookings"] / cat_stats["Bookings"].sum() * 100
                        ).round(1)
                        cat_stats["% of Participants"] = (
                            cat_stats["Total_Participants"]
                            / cat_stats["Total_Participants"].sum() * 100
                        ).round(1)

                        col_pie, col_table = st.columns(2)
                        with col_pie:
                            fig_pie = px.pie(
                                cat_stats, values="Bookings", names="Category",
                                color_discrete_sequence=px.colors.sequential.Oranges_r,
                            )
                            fig_pie.update_layout(height=350, margin=dict(t=10))
                            st.plotly_chart(fig_pie, use_container_width=True)
                        with col_table:
                            st.dataframe(
                                cat_stats.rename(columns={
                                    "Total_Participants": "Total Participants",
                                }),
                                use_container_width=True,
                                hide_index=True,
                            )

                # --- Private Events ---
                if private_col and private_col in df.columns:
                    section_gap()
                    st.markdown("### Private Events")
                    st.caption("How do private events compare to regular bookings?")

                    if pe_computed:
                        col1, col2, col3, col4 = st.columns(4)
                        with col1:
                            st.metric("Private Events", format_number(private_count))
                        with col2:
                            st.metric(
                                "% of Total Bookings",
                                f"{private_pct:.1f}%".replace(".", ","),
                            )
                        with col3:
                            st.metric("Avg Turnover (Private)", format_euro(avg_rev_private))
                        with col4:
                            st.metric(
                                "vs Regular",
                                f"{rev_diff_pct:+.0f}%",
                                delta_color="normal",
                                help=(
                                    "How much more (or less) "
                                    "private events generate "
                                    "vs regular bookings."
                                )
                            )

                        section_gap()

                        pe_compare = pd.DataFrame([
                            {
                                "Type": "Private Event",
                                "Bookings": format_number(private_count),
                                "Avg Turnover": format_euro(avg_rev_private, 2),
                                "Total Turnover": format_euro(private_rev.sum()),
                            },
                            {
                                "Type": "Regular Booking",
                                "Bookings": format_number(regular_count_pe),
                                "Avg Turnover": format_euro(avg_rev_regular, 2),
                                "Total Turnover": format_euro(regular_rev_pe.sum()),
                            },
                        ])
                        if "participants" in pe_data.columns:
                            private_parts = (
                                pe_data[pe_data["is_private"]]
                                ["participants"].mean()
                            )
                            regular_parts = (
                                pe_data[~pe_data["is_private"]]
                                ["participants"].mean()
                            )
                            pe_compare["Avg Group Size"] = [
                                f"{private_parts:.1f}".replace(".", ","),
                                f"{regular_parts:.1f}".replace(".", ","),
                            ]
                        styled_pe = style_dataframe_right_align(
                            pe_compare, exclude_cols=["Type"]
                        )
                        st.dataframe(styled_pe, use_container_width=True, hide_index=True)

                        bar_data = pd.DataFrame({
                            "Type": ["Private Event", "Regular Booking"],
                            "Avg Turnover": [avg_rev_private, avg_rev_regular],
                        }).sort_values("Avg Turnover", ascending=True)
                        fig_pe = px.bar(
                            bar_data,
                            x="Avg Turnover",
                            y="Type",
                            orientation="h",
                            title="Average Turnover Comparison",
                            text=bar_data["Avg Turnover"].apply(lambda x: format_euro(x)),
                            color="Type",
                            color_discrete_map={
                                "Private Event": "#9b59b6",
                                "Regular Booking": "#3498db",
                            },
                        )
                        fig_pe.update_traces(textposition="outside")
                        fig_pe.update_layout(
                            showlegend=False,
                            height=250,
                            margin=dict(t=50, r=80),
                            xaxis_title="Avg Turnover (\u20ac)",
                            yaxis_title="",
                        )
                        st.plotly_chart(fig_pe, use_container_width=True)
                    else:
                        st.info("No private events found in the selected period.")

                # --- Key Takeaways ---
                section_gap()
                with st.expander("Key Takeaways"):
                    # Group size insight
                    if participants_col and "participants" in df.columns:
                        p_clean_tk = df["participants"].dropna()
                        p_clean_tk = p_clean_tk[p_clean_tk > 0]
                        if len(p_clean_tk) > 0:
                            solo_pct = (p_clean_tk == 1).sum() / len(p_clean_tk) * 100
                            couple_pct = (p_clean_tk == 2).sum() / len(p_clean_tk) * 100
                            group_pct = 100 - solo_pct - couple_pct

                            if solo_pct > 50:
                                st.info(
                                    f"**{solo_pct:.0f}% of bookings are solo visitors.** "
                                    "Your pricing is optimized for individuals. To grow turnover per "
                                    "booking, consider group discounts or 'bring a friend' promotions "
                                    "— converting solos into couples doubles revenue per session."
                                )
                            elif couple_pct > 30:
                                st.info(
                                    f"**{couple_pct:.0f}% of bookings are couples.** "
                                    "Couples are your core segment. Consider couple packages, "
                                    "date-night promotions, or gift cards marketed as partner gifts."
                                )
                            if group_pct > 15:
                                st.info(
                                    f"**{group_pct:.0f}% of bookings are groups of 3+.** "
                                    "Groups spend more per booking. Marketing to friend groups, "
                                    "team outings, and birthday parties could grow this segment."
                                )

                    # Private events insight
                    if pe_computed and private_count > 0:
                        st.info(
                            f"**Private events are {private_pct:.1f}% of bookings but average "
                            f"{format_euro(avg_rev_private)} vs {format_euro(avg_rev_regular)} for regular "
                            f"({rev_diff_pct:+.0f}% more).** "
                            "Each private event is worth "
                            f"~{avg_rev_private / avg_rev_regular:.0f}x a regular booking. "
                            "Even a small increase in private event bookings "
                            "significantly boosts turnover."
                        )



            # ==================== TAB 3: LIFETIME VALUE ====================
            with tab_clv:

                st.markdown("### Customer Lifetime Value (CLV)")

                clv_years = st.segmented_control(
                    "CLV horizon",
                    options=[1, 2, 3],
                    format_func=lambda y: f"{y}-Year",
                    default=2,
                    key="clv_horizon",
                )
                clv_value = clv_by_horizon[clv_years]
                prev_clv_value = prev_clv_by_horizon[clv_years]
                seg_clv_df = (
                    pd.DataFrame(seg_clv_by_horizon[clv_years])
                    if seg_clv_by_horizon[clv_years] else None
                )

                clv_delta_pct = (
                    (clv_value - prev_clv_value) / prev_clv_value * 100
                    if prev_clv_value and prev_clv_value > 0 else None
                )
                aov_clv_delta_pct = (
                    (clv_aov - prev_clv_aov) / prev_clv_aov * 100
                    if prev_clv_aov and prev_clv_aov > 0 else None
                )
                freq_delta_pct = (
                    (clv_annual_frequency - prev_clv_annual_frequency)
                    / prev_clv_annual_frequency * 100
                    if prev_clv_annual_frequency and prev_clv_annual_frequency > 0
                    else None
                )
                ret_delta_pct = (
                    (clv_retention_rate - prev_clv_retention_rate)
                    / prev_clv_retention_rate * 100
                    if prev_clv_retention_rate and prev_clv_retention_rate > 0
                    else None
                )

                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric(
                        f"{clv_years}-Year CLV",
                        format_euro(clv_value, 2),
                        delta=_delta(clv_delta_pct),
                        help=(
                            "Predicted turnover per customer "
                            f"over {clv_years} year{'s' if clv_years > 1 else ''}, "
                            "with monthly retention decay. "
                            f"Based on the 12 months up to {clv_end_str}. "
                            f"Previous: "
                            f"{format_euro(prev_clv_value, 2) if prev_clv_value else 'N/A'}."
                        )
                    )
                with col2:
                    st.metric(
                        "Avg Booking Value",
                        format_euro(clv_aov, 2),
                        delta=_delta(aov_clv_delta_pct),
                        help=(
                            "Average booking value from "
                            f"the 12 months up to {clv_end_str}. "
                            f"Previous: "
                            f"{format_euro(prev_clv_aov, 2) if prev_clv_aov else 'N/A'}."
                        )
                    )
                with col3:
                    prev_freq_str = (
                        f"{prev_clv_annual_frequency:.2f}"
                        .replace(".", ",")
                        if prev_clv_annual_frequency
                        else "N/A"
                    )
                    st.metric(
                        "Annual Frequency",
                        f"{clv_annual_frequency:.2f}".replace(".", ","),
                        delta=_delta(freq_delta_pct),
                        help=(
                            "Average bookings per customer per "
                            f"year (12 months up to {clv_end_str}). "
                            f"Previous: {prev_freq_str}."
                        )
                    )
                with col4:
                    prev_ret_clv_str = (
                        f"{prev_clv_retention_rate:.1%}"
                        .replace(".", ",")
                        if prev_clv_retention_rate
                        else "N/A"
                    )
                    st.metric(
                        "12-Month Retention",
                        f"{clv_retention_rate:.1%}".replace(".", ","),
                        delta=_delta(ret_delta_pct),
                        help=(
                            "Of customers who visited for the "
                            "first time, what % came back within "
                            "12 months? "
                            f"Previous: {prev_ret_clv_str}."
                        )
                    )

                with st.expander("How to read these metrics"):
                    clv_years_label = (
                        f"{clv_years} year" if clv_years == 1
                        else f"{clv_years} years"
                    )
                    st.markdown(
                        f"**What does CLV tell you?** How much "
                        f"turnover one customer brings in over "
                        f"{clv_years_label}. Use it to decide "
                        "how much you can spend to get a new "
                        "customer.\n\n"
                        "**Example:** Say you spend \u20ac5.000 on "
                        "ads and get 100 new customers. Not all "
                        "of them will come back \u2014 roughly 69 "
                        "will visit once, 24 will return a few "
                        "times, and 7 will become regulars. The "
                        f"CLV ({format_euro(clv_value, 2)}) is "
                        "the average across all 100, including "
                        "the one-timers. So 100 new customers "
                        f"\u00d7 {format_euro(clv_value, 2)} = "
                        f"**{format_euro(clv_value * 100)}** "
                        f"expected turnover over "
                        f"{clv_years_label}.\n\n"
                        "---\n\n"
                        "**How is it calculated?**\n\n"
                        "> CLV = Avg Booking Value "
                        "\u00d7 Annual Frequency "
                        "\u00d7 Retention\n\n"
                        "Three things drive it:\n\n"
                        f"- **Avg Booking Value** "
                        f"({format_euro(clv_aov, 2)}) "
                        "\u2014 how much a customer spends "
                        "per visit\n"
                        f"- **Annual Frequency** "
                        f"({f'{clv_annual_frequency:.2f}'.replace('.', ',')} "
                        "visits/year) "
                        "\u2014 how often a customer visits "
                        "per year on average\n"
                        f"- **12-Month Retention** "
                        f"({f'{clv_retention_rate:.1%}'.replace('.', ',')}) "
                        "\u2014 what percentage of new "
                        "customers come back within a year\n\n"
                        "The formula projects these forward "
                        f"month by month over {clv_years_label}. "
                        "Each month, fewer customers remain "
                        "(retention shrinks the number), so "
                        "later months contribute less. This "
                        "gives a realistic estimate \u2014 not "
                        "everyone stays for the full "
                        f"{clv_years_label}.\n\n"
                        "---\n\n"
                        "**About the data:** These numbers are "
                        "based on the 12 months up to "
                        f"{clv_end_str} "
                        f"({clv_window_start} \u2013 {clv_end_str})"
                        " \u2014 not the date range you selected "
                        "above. This avoids distortion from "
                        "picking a short or seasonal period.\n\n"
                        "The green/red percentages compare to "
                        "an earlier 12-month period. Hover over "
                        "the **?** next to each metric to see "
                        "the previous value.\n\n"
                        "**If CLV is dropping**, check which "
                        "of these three numbers went down \u2014 "
                        "that tells you exactly where to focus."
                    )

                # --- CLV by Location ---
                if location_col and location_col in df.columns:
                    section_gap()
                    st.markdown("### CLV by Location")

                    # Build reverse map: UI name -> tuple of BQ names
                    ui_locations = sorted(
                        df[location_col].dropna().unique().tolist()
                    )
                    _streamlit_to_bq = {}
                    for bq_name, ui_name in _BQ_TO_STREAMLIT_LOCATION.items():
                        _streamlit_to_bq.setdefault(ui_name, set()).add(bq_name)
                    for ui_name in ui_locations:
                        if ui_name not in _streamlit_to_bq:
                            _streamlit_to_bq[ui_name] = {ui_name}

                    # Fetch all locations in parallel
                    with ThreadPoolExecutor(max_workers=len(ui_locations)) as executor:
                        loc_futures = {
                            ui_name: executor.submit(
                                _get_clv_inputs_by_location,
                                clv_end_str,
                                tuple(sorted(_streamlit_to_bq[ui_name])),
                            )
                            for ui_name in ui_locations
                        }
                        loc_results = {
                            ui_name: fut.result()
                            for ui_name, fut in loc_futures.items()
                        }

                    loc_clv_rows = []
                    for ui_name, loc_inputs in loc_results.items():
                        if loc_inputs["total_customers"] == 0:
                            continue
                        loc_aov = loc_inputs["aov"]
                        loc_freq = loc_inputs["mean_annual_frequency"]
                        loc_ret = loc_inputs["retention_rate"]
                        loc_monthly_freq = loc_freq / 12
                        loc_monthly_ret = loc_ret ** (1 / 12)
                        months = clv_years * 12
                        loc_clv = sum(
                            loc_aov * loc_monthly_freq * (loc_monthly_ret ** m)
                            for m in range(months)
                        )
                        loc_clv_rows.append({
                            "Location": ui_name,
                            "Customers": loc_inputs["total_customers"],
                            "Avg Booking Value": loc_aov,
                            "Annual Frequency": loc_freq,
                            "Retention": loc_ret,
                            f"{clv_years}-Year CLV": loc_clv,
                        })

                    if loc_clv_rows:
                        loc_clv_df = pd.DataFrame(loc_clv_rows).sort_values(
                            f"{clv_years}-Year CLV", ascending=False
                        )

                        loc_display = loc_clv_df.copy()
                        loc_display["Customers"] = loc_display["Customers"].apply(format_number)
                        loc_display["Avg Booking Value"] = loc_display["Avg Booking Value"].apply(
                            lambda x: format_euro(x, 2)
                        )
                        loc_display["Annual Frequency"] = loc_display["Annual Frequency"].apply(
                            lambda x: f"{x:.2f}".replace(".", ",")
                        )
                        loc_display["Retention"] = loc_display["Retention"].apply(
                            lambda x: f"{x:.1%}".replace(".", ",")
                        )
                        clv_col = f"{clv_years}-Year CLV"
                        loc_display[clv_col] = loc_display[clv_col].apply(
                            lambda x: format_euro(x, 2)
                        )

                        styled_loc = style_dataframe_right_align(
                            loc_display, exclude_cols=["Location"]
                        )
                        st.dataframe(styled_loc, use_container_width=True, hide_index=True)
                    else:
                        st.info("No location data available for CLV calculation.")

                # --- CLV by Segment ---
                section_gap()
                st.markdown("### CLV by Segment")

                if seg_clv_df is not None and len(seg_clv_df) > 0:
                    seg_clv_display = seg_clv_df.copy()
                    seg_clv_display["Customers"] = (
                        seg_clv_display["Customers"]
                        .apply(format_number)
                    )
                    seg_clv_display = seg_clv_display.rename(columns={"AOV": "Avg Booking Value"})
                    seg_clv_display["Avg Booking Value"] = (
                        seg_clv_display["Avg Booking Value"]
                        .apply(lambda x: format_euro(x, 2))
                    )
                    seg_clv_display["Retention"] = seg_clv_display["Retention"].apply(
                        lambda x: f"{x:.1%}".replace(".", ",")
                    )
                    clv_col_label = f"{clv_years}-Year CLV"
                    seg_clv_display = seg_clv_display.rename(columns={"CLV": clv_col_label})
                    seg_clv_display[clv_col_label] = seg_clv_display[clv_col_label].apply(
                        lambda x: format_euro(x, 2)
                    )

                    styled_clv = style_dataframe_right_align(
                        seg_clv_display, exclude_cols=["Segment"]
                    )
                    st.dataframe(styled_clv, use_container_width=True, hide_index=True)

                    section_gap()

                    col1, col2 = st.columns(2)
                    with col1:
                        fig_clv = px.bar(
                            seg_clv_df,
                            x="Segment",
                            y="CLV",
                            title=f"{clv_years}-Year CLV by Segment",
                            labels={"CLV": "CLV (\u20ac)"},
                            text=seg_clv_df["CLV"].apply(lambda x: format_euro(x)),
                            color="Segment",
                            color_discrete_map={
                                "New": "#3498db", "Regular": "#f39c12", "VIP": "#9b59b6"
                            },
                        )
                        fig_clv.update_traces(textposition="outside")
                        fig_clv.update_layout(
                            height=400, showlegend=False, margin=dict(t=50)
                        )
                        st.plotly_chart(fig_clv, use_container_width=True)

                    with col2:
                        fig_ret = px.bar(
                            seg_clv_df,
                            x="Segment",
                            y="Retention",
                            title="Retention Rate by Segment",
                            text=seg_clv_df["Retention"].apply(
                                lambda x: f"{x:.1%}".replace(".", ",")
                            ),
                            color="Segment",
                            color_discrete_map={
                                "New": "#3498db", "Regular": "#f39c12", "VIP": "#9b59b6"
                            },
                        )
                        fig_ret.update_traces(textposition="outside")
                        fig_ret.update_layout(
                            height=400, showlegend=False, margin=dict(t=50)
                        )
                        st.plotly_chart(fig_ret, use_container_width=True)

                    st.caption(
                        "Big CLV gap between segments? "
                        "Moving Regulars to VIP has the "
                        "highest ROI."
                    )

                # --- Key Takeaways ---
                section_gap()
                with st.expander("Key Takeaways"):
                    if clv_by_horizon and 1 in clv_by_horizon:
                        clv_1y = clv_by_horizon[1]
                        st.info(
                            f"**Each customer is worth {format_euro(clv_1y)} over 1 year** "
                            f"(based on {format_euro(clv_aov)} avg booking, "
                            f"{clv_annual_frequency:.1f} visits/year, "
                            f"{clv_retention_rate:.0f}% retention). "
                            "This is your break-even ceiling for customer acquisition cost."
                        )

                    if clv_retention_rate is not None:
                        if clv_retention_rate < 30:
                            st.info(
                                f"**Retention is {clv_retention_rate:.0f}% — most customers "
                                "don't come back within 12 months.** "
                                "A 5% retention improvement is worth more than a 5% increase "
                                "in new customers, because retained customers already know you."
                            )
                        elif clv_retention_rate >= 30:
                            st.info(
                                f"**{clv_retention_rate:.0f}% retention rate.** "
                                "Healthy for a seasonal experience business. "
                                "Focus on keeping this stable while growing frequency."
                            )

                    if clv_annual_frequency is not None and clv_annual_frequency < 2:
                        st.info(
                            f"**Customers visit {clv_annual_frequency:.1f}x per year on average.** "
                            "Even pushing this to 2x would roughly double CLV. "
                            "Seasonal reminders ('winter is back — book your session') "
                            "and membership plans are the levers."
                        )



            # ==================== TAB 4: LOCATION LOYALTY ====================
            with tab_loyalty:

                if location_col is None or location_col not in df.columns:
                    st.info("Location data not available for loyalty analysis.")
                else:
                    # Use df1 filtered to selected date range for customer frequency
                    df_all = st.session_state.df1.copy()
                    df_all["email"] = df_all[email_col] if email_col in df_all.columns else None
                    df_all["location"] = df_all[location_col] if location_col in df_all.columns else None
                    df_all = df_all[df_all["email"].notna() & (df_all["email"] != "")]

                    # Filter to selected date range (consistent with Overview tab)
                    _loc_date_col = date_col if date_col in df_all.columns else None
                    if _loc_date_col:
                        df_all["_booking_date"] = pd.to_datetime(df_all[_loc_date_col], errors="coerce")
                        _loc_start = pd.Timestamp(st.session_state.bookeo_start_date)
                        _loc_end = pd.Timestamp(st.session_state.bookeo_end_date)
                        if df_all["_booking_date"].dt.tz is not None:
                            _loc_start = _loc_start.tz_localize(df_all["_booking_date"].dt.tz)
                            _loc_end = _loc_end.tz_localize(df_all["_booking_date"].dt.tz)
                        df_all = df_all[
                            (df_all["_booking_date"] >= _loc_start)
                            & (df_all["_booking_date"] <= _loc_end)
                        ].copy()

                    if "Total paid" in df_all.columns:
                        df_all["revenue"] = pd.to_numeric(df_all["Total paid"], errors="coerce").fillna(0)
                    else:
                        df_all["revenue"] = 0

                    # Customer frequency from all bookings
                    customer_frequency = df_all.groupby("email").agg(
                        bookings=("email", "count"),
                        total_revenue=("revenue", "sum"),
                    ).reset_index()

                    total_cust = len(customer_frequency)
                    recurring_customers_loc = len(
                        customer_frequency[customer_frequency["bookings"] > 1]
                    )

                    # Location-specific metrics
                    num_locations = df_all["location"].nunique()
                    customers_per_location = (
                        df_all.groupby("location")["email"].nunique()
                    )
                    avg_customers_per_location = float(customers_per_location.mean())

                    # Multi-location customers
                    cust_locations = df_all.groupby("email")["location"].nunique()
                    multi_location_count = int((cust_locations > 1).sum())
                    multi_location_pct = (
                        multi_location_count / total_cust * 100
                        if total_cust > 0 else 0
                    )

                    # KPIs
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric(
                            "Locations",
                            format_number(num_locations),
                            help="Number of active Northern Sauna locations."
                        )
                    with col2:
                        st.metric(
                            "Avg Customers / Location",
                            format_number(int(round(avg_customers_per_location))),
                            help=(
                                "Average unique customers per location. "
                                "Customers who visit multiple locations "
                                "are counted at each."
                            )
                        )
                    with col3:
                        st.metric(
                            "Multi-Location Visitors",
                            format_number(multi_location_count),
                            help=(
                                "Customers who booked at more than "
                                "one location."
                            )
                        )
                    with col4:
                        st.metric(
                            "Cross-Location %",
                            f"{multi_location_pct:.1f}%".replace(".", ","),
                            help=(
                                "Percentage of all customers who "
                                "visited multiple locations. Higher = "
                                "stronger brand loyalty across the "
                                "network."
                            )
                        )

                    # Location loyalty analysis (BQ-backed, all-time history)
                    section_gap()
                    st.markdown("### Location Loyalty Among Repeat Customers")

                    loyalty_data = _get_location_loyalty(
                        start_dt.strftime("%Y-%m-%d"),
                        end_dt.strftime("%Y-%m-%d"),
                    )
                    loyalty_distribution = pd.DataFrame(loyalty_data["distribution"])
                    loyalty_distribution.columns = ["Loyalty Type", "Customers"]
                    loyalty_distribution["Loyalty Type"] = pd.Categorical(
                        loyalty_distribution["Loyalty Type"],
                        categories=["Single location", "2 locations", "3+ locations"],
                        ordered=True,
                    )

                    col1, col2 = st.columns([3, 2])
                    with col1:
                        fig_loyalty = px.pie(
                            loyalty_distribution,
                            values="Customers",
                            names="Loyalty Type",
                            hole=0.4,
                        )
                        fig_loyalty.update_layout(
                            height=400,
                            showlegend=True,
                            legend=dict(
                                orientation="h",
                                yanchor="bottom",
                                y=-0.2,
                                xanchor="center",
                                x=0.5,
                            ),
                            margin=dict(t=20, b=80),
                        )
                        st.plotly_chart(fig_loyalty, use_container_width=True)
                    with col2:
                        st.dataframe(
                            loyalty_distribution,
                            use_container_width=True,
                            hide_index=True,
                        )

                    with st.expander("How to read this chart"):
                        st.markdown(
                            "**What does it show?** Of all customers who booked 2+ times "
                            "(non-canceled) in the selected date range, how many different "
                            "Northern Sauna locations did they visit?\n\n"
                            "**Single location** — loyal to one spot. These customers "
                            "return but don't explore. Consider cross-promoting other "
                            "locations to them.\n\n"
                            "**2 locations / 3+** — brand-loyal explorers. They like Northern Sauna, "
                            "not just one location. Great candidates for memberships.\n\n"
                            "**Tip:** Compare different date ranges to see if customers "
                            "are becoming more or less adventurous over time."
                        )

                    # Repeat customers by location
                    section_gap()
                    st.markdown("### Repeat Customers by Location")

                    location_total = df_all.groupby("location")["email"].nunique().reset_index()
                    location_total.columns = ["Location", "Total Customers"]

                    # Count customers who visited this specific location 2+ times
                    loc_cust_counts = df_all.groupby(["location", "email"]).size().reset_index(name="visits")
                    location_recurring = loc_cust_counts[loc_cust_counts["visits"] >= 2].groupby("location")["email"].nunique().reset_index()
                    location_recurring.columns = ["Location", "Repeat Customers"]

                    location_stats = location_total.merge(location_recurring, on="Location", how="left").fillna(0)
                    location_stats["Repeat Customers"] = location_stats["Repeat Customers"].astype(int)
                    location_stats["Repeat Rate (%)"] = (
                        location_stats["Repeat Customers"] / location_stats["Total Customers"] * 100
                    ).round(1)

                    location_display = location_stats.sort_values("Repeat Customers", ascending=False)

                    # Add total row
                    total_loc_cust = location_display["Total Customers"].sum()
                    total_loc_rec = location_display["Repeat Customers"].sum()
                    avg_rate = location_stats["Repeat Rate (%)"].mean().round(1)

                    total_row = pd.DataFrame({
                        "Location": ["Total"],
                        "Total Customers": [total_loc_cust],
                        "Repeat Customers": [total_loc_rec],
                        "Repeat Rate (%)": [avg_rate],
                    })
                    location_display = pd.concat([location_display, total_row], ignore_index=True)

                    st.dataframe(
                        location_display,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Location": st.column_config.TextColumn("Location"),
                            "Total Customers": st.column_config.NumberColumn(
                                "Total Customers",
                                help="Unique customers who booked at this location",
                            ),
                            "Repeat Customers": st.column_config.NumberColumn(
                                "Repeat Customers",
                                help="Customers with more than one booking",
                            ),
                            "Repeat Rate (%)": st.column_config.NumberColumn(
                                "Repeat Rate (%)",
                                help="Percentage of customers who returned",
                            ),
                        },
                    )

                    # Key Takeaways
                    section_gap()
                    with st.expander("Key Takeaways"):
                        # VIP concentration
                        vip_cust = customer_frequency[customer_frequency["bookings"] >= 7]
                        if len(vip_cust) > 0:
                            vip_count = len(vip_cust)
                            vip_pct = vip_count / total_cust * 100
                            vip_revenue = vip_cust["total_revenue"].sum()
                            total_rev = customer_frequency["total_revenue"].sum()
                            vip_rev_pct = vip_revenue / total_rev * 100 if total_rev > 0 else 0
                            if vip_rev_pct > vip_pct * 1.5:
                                st.info(
                                    f"**Your top {vip_pct:.1f}% of customers generate "
                                    f"{vip_rev_pct:.0f}% of turnover.** "
                                    f"These {format_number(vip_count)} regulars are your most valuable asset. "
                                    "A personal thank-you, priority booking, or seasonal gift "
                                    "keeps them coming back."
                                )

                        # Repeat rate variation
                        if len(location_stats) > 1:
                            best_loc = location_stats.sort_values("Repeat Rate (%)", ascending=False).iloc[0]
                            worst_loc = location_stats.sort_values("Repeat Rate (%)", ascending=True).iloc[0]
                            spread = best_loc["Repeat Rate (%)"] - worst_loc["Repeat Rate (%)"]
                            if spread > 5:
                                st.info(
                                    f"**Repeat rates vary by location:** "
                                    f"{best_loc['Location'].replace('Northern Sauna ', '')} has "
                                    f"{best_loc['Repeat Rate (%)']:.0f}% vs "
                                    f"{worst_loc['Location'].replace('Northern Sauna ', '')} at "
                                    f"{worst_loc['Repeat Rate (%)']:.0f}%. "
                                    "What's the high-performer doing differently? "
                                    "Staff, ambiance, or local demographics — "
                                    "understanding the gap is worth investigating."
                                )

                        # Avg bookings for repeat customers
                        repeat_only = customer_frequency[customer_frequency["bookings"] > 1]
                        if len(repeat_only) > 0:
                            avg_repeat_bookings = repeat_only["bookings"].mean()
                            st.info(
                                f"**Repeat customers average {avg_repeat_bookings:.1f} bookings.** "
                                f"Your most loyal visitor has {customer_frequency['bookings'].max()} bookings. "
                                "A membership plan targeting customers with 3+ visits could lock in "
                                "recurring revenue and boost frequency."
                            )




render_footer()
