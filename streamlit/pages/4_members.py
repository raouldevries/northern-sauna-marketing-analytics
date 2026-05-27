"""
Northern Sauna Analytics - Members Page
Membership analysis, member vs non-member comparison, and turnover insights
"""

import itertools
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import sys
sys.path.insert(0, '..')
from bq_data_loader import init_session_state, render_bookeo_settings
from components.demo_banner import render_demo_banner, render_footer  # noqa: E402
from utils import render_header, render_sidebar_nav
from features.revenue.formatters import format_euro, format_number

# Page configuration
st.set_page_config(
    page_title="Northern Sauna - Members",
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
render_bookeo_settings(page_key="members")

st.markdown("## Members")
st.markdown("Membership analysis, member vs non-member comparison, and loyalty")

# Initialize session state using centralized function
init_session_state()

# Check authentication
if not st.session_state.get('authenticated', False):
    st.warning("Please log in to access this page.")
    st.page_link("app.py", label="Go to Login", icon=":material/login:")
    st.stop()

render_sidebar_nav("Members", ["Overview", "Cohorts", "Behavior", "Retention & Loyalty"])

render_demo_banner()

# Main content
if st.session_state.df1 is None or st.session_state.df2 is None:
    st.info("**No data loaded.** Use the date selector above to load booking data from BigQuery.")
else:
    _loading = st.empty()
    _loading.info("Loading member analysis...")
    df2 = st.session_state.df2  # non-canceled bookings

    # Check that Member column exists
    if "Member" not in df2.columns:
        st.warning("Member data not available. The 'Member' column is missing from the dataset.")
        st.stop()

    # --- Split into member / non-member ---
    members_df = df2[df2["Member"]].copy()
    non_members_df = df2[~df2["Member"]].copy()

    # --- Pre-compute shared metrics ---
    unique_members = members_df["Email address"].nunique() if len(members_df) > 0 else 0
    unique_non_members = non_members_df["Email address"].nunique() if len(non_members_df) > 0 else 0
    avg_member_rev = members_df["Total paid"].mean() if len(members_df) > 0 else 0
    avg_non_member_rev = non_members_df["Total paid"].mean() if len(non_members_df) > 0 else 0
    total_member_rev = members_df["Total paid"].sum() if len(members_df) > 0 else 0
    total_non_member_rev = non_members_df["Total paid"].sum() if len(non_members_df) > 0 else 0
    bookings_per_member = len(members_df) / unique_members if unique_members > 0 else 0
    bookings_per_non_member = len(non_members_df) / unique_non_members if unique_non_members > 0 else 0
    rev_per_member = total_member_rev / unique_members if unique_members > 0 else 0
    rev_per_non_member = total_non_member_rev / unique_non_members if unique_non_members > 0 else 0
    member_pct = len(members_df) / len(df2) * 100 if len(df2) > 0 else 0

    # Date range label for takeaway titles
    date_from = df2["Start"].min().strftime("%-d %b %Y")
    date_to = df2["Start"].max().strftime("%-d %b %Y")
    takeaway_title = f"Key Takeaways ({date_from} \u2013 {date_to})"
    date_range_days = (df2["Start"].max() - df2["Start"].min()).days
    MIN_DAYS_FOR_TAKEAWAYS = 90
    show_takeaways = date_range_days >= MIN_DAYS_FOR_TAKEAWAYS

    # ================================================================
    #  TABS
    # ================================================================

    _loading.empty()

    tab_overview, tab_cohorts, tab_behavior, tab_loyalty = st.tabs([
        "Overview", "Cohorts", "Behavior", "Retention & Loyalty"
    ])

    # ==================== TAB 1: OVERVIEW ====================
    with tab_overview:

        # --- KPIs ---
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric(
                "Unique Members",
                format_number(unique_members),
                delta=f"{member_pct:.1f}% of bookings".replace(".", ","),
                delta_color="off",
                help="Distinct member email addresses in the selected period.",
            )
        with col2:
            freq_uplift = (
                (bookings_per_member / bookings_per_non_member - 1) * 100
                if bookings_per_non_member > 0 else 0
            )
            st.metric(
                "Bookings per Member",
                f"{bookings_per_member:.1f}",
                delta=f"{freq_uplift:+.0f}% vs non-member",
                help=(
                    f"Non-members average {bookings_per_non_member:.1f} bookings. "
                    "Members visit more often."
                ),
            )
        with col3:
            rev_uplift = (
                (rev_per_member / rev_per_non_member - 1) * 100
                if rev_per_non_member > 0 else 0
            )
            st.metric(
                "Turnover per Member",
                format_euro(rev_per_member),
                delta=f"{rev_uplift:+.0f}% vs non-member",
                help=(
                    f"Non-members: {format_euro(rev_per_non_member)}. "
                    "Total turnover from a member divided by unique members."
                ),
            )
        with col4:
            avg_val_diff = avg_member_rev - avg_non_member_rev
            avg_val_delta = (
                (avg_member_rev / avg_non_member_rev - 1) * 100
                if avg_non_member_rev > 0 else 0
            )
            st.metric(
                "Avg Booking Value",
                format_euro(avg_member_rev, 2),
                delta=f"{avg_val_delta:+.0f}% vs non-member",
                help=(
                    f"Non-members: {format_euro(avg_non_member_rev, 2)}. "
                    "Members may have a lower booking value due to membership discounts."
                ),
            )

        # --- Insights ---
        freq_ratio = bookings_per_member / bookings_per_non_member if bookings_per_non_member > 0 else 0
        rev_ratio = rev_per_member / rev_per_non_member if rev_per_non_member > 0 else 0
        val_direction = "lower" if avg_val_diff < 0 else "higher"

        with st.expander("Member Insights"):
            st.markdown(
                f"- **Booking Frequency:** Members book "
                f"{freq_ratio:.1f}x more often than non-members "
                f"({bookings_per_member:.1f} vs "
                f"{bookings_per_non_member:.1f} bookings per customer)\n"
                f"- **Avg Booking Value:** Member bookings are "
                f"{format_euro(abs(avg_val_diff), 2)} {val_direction} than "
                f"non-member bookings ({format_euro(avg_member_rev, 2)} vs "
                f"{format_euro(avg_non_member_rev, 2)})\n"
                f"- **Turnover per Customer:** Members generate "
                f"{format_euro(rev_per_member, 2)} vs "
                f"{format_euro(rev_per_non_member, 2)} per non-member "
                f"({rev_ratio:.1f}x)\n\n"
                + ("Members book at a lower avg value but higher frequency "
                   "\u2014 the membership discount is driving repeat visits."
                   if avg_val_diff < 0
                   else "Members both visit more often and spend more per visit "
                   "\u2014 strong membership value proposition.")
            )

        # --- Member vs Non-Member Comparison Charts ---
        st.markdown("#### Member vs Non-Member")

        col1, col2 = st.columns(2)
        with col1:
            comparison_avg = pd.DataFrame({
                "Category": ["Member", "Non-Member"],
                "Avg Booking Value": [avg_member_rev, avg_non_member_rev],
            })
            fig_avg = px.bar(
                comparison_avg,
                x="Category",
                y="Avg Booking Value",
                labels={"Avg Booking Value": "Avg Value (\u20ac)"},
                text=comparison_avg["Avg Booking Value"].apply(lambda x: format_euro(x, 2)),
            )
            fig_avg.update_traces(
                marker_color=["#1f77b4", "#ff7f0e"],
                textposition="outside",
            )
            fig_avg.update_layout(height=400, showlegend=False, margin=dict(t=20))
            st.plotly_chart(fig_avg, use_container_width=True)

        with col2:
            comparison_rev = pd.DataFrame({
                "Category": ["Member", "Non-Member"],
                "Turnover": [total_member_rev, total_non_member_rev],
            })
            fig_rev = px.pie(
                comparison_rev,
                values="Turnover",
                names="Category",
                color_discrete_sequence=["#1f77b4", "#ff7f0e"],
            )
            fig_rev.update_layout(height=400)
            st.plotly_chart(fig_rev, use_container_width=True)

        # --- Conversion Funnel ---
        st.markdown("#### Visitor \u2192 Repeat \u2192 Member Funnel")
        st.caption(
            "How many first-time visitors return, and how many eventually "
            "become members? Based on the full selected period."
        )

        # Count unique customers at each stage
        all_customers = df2.groupby("Email address").agg(
            total_bookings=("Start", "count"),
            is_member=("Member", "any"),
            first_visit=("Start", "min"),
            last_visit=("Start", "max"),
        ).reset_index()

        total_unique = len(all_customers)
        one_timers = (all_customers["total_bookings"] == 1).sum()
        repeat_visitors = (all_customers["total_bookings"] >= 2).sum()
        became_members = all_customers["is_member"].sum()

        funnel_data = pd.DataFrame({
            "Stage": [
                "All Visitors",
                "Returning Customers (2+ bookings)",
                "Members",
            ],
            "Count": [total_unique, repeat_visitors, became_members],
        })

        fig_funnel = go.Figure(go.Funnel(
            y=funnel_data["Stage"],
            x=funnel_data["Count"],
            textinfo="value+percent initial",
            texttemplate="%{value:,} (%{percentInitial:.1%})",
            marker=dict(
                color=["#3498db", "#2ecc71", "#1f77b4"],
            ),
            connector=dict(line=dict(color="#e0e0e0", width=1)),
        ))
        fig_funnel.update_layout(
            height=300,
            margin=dict(t=20, b=20),
            funnelmode="stack",
        )
        st.plotly_chart(fig_funnel, use_container_width=True)

        # Funnel metrics
        repeat_rate = repeat_visitors / total_unique * 100 if total_unique > 0 else 0
        member_rate = became_members / total_unique * 100 if total_unique > 0 else 0
        repeat_to_member = (
            became_members / repeat_visitors * 100 if repeat_visitors > 0 else 0
        )
        drop_off = one_timers / total_unique * 100 if total_unique > 0 else 0

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric(
                "Single Visit (so far)", f"{drop_off:.0f}%",
                help=f"{format_number(one_timers)} customers have booked exactly once so far. Many may return — 12-month retention on the Customers page shows the true return rate.",
            )
        with col2:
            st.metric(
                "Returning Customers", f"{repeat_rate:.0f}%",
                help=f"{format_number(repeat_visitors)} customers booked 2+ times in this period.",
            )
        with col3:
            st.metric(
                "Member Conversion", f"{member_rate:.1f}%",
                help=f"{format_number(became_members)} of {format_number(total_unique)} unique visitors are members.",
            )
        with col4:
            st.metric(
                "Repeat \u2192 Member", f"{repeat_to_member:.0f}%",
                help=f"Of repeat visitors, {repeat_to_member:.0f}% are members.",
            )

        # --- Booking Trend ---
        st.markdown("#### Membership Growth")

        df2_trend = df2.copy()
        date_span = (df2_trend["Start"].max() - df2_trend["Start"].min()).days
        if date_span <= 180:
            freq_label = "Week"
            df2_trend["Period"] = df2_trend["Start"].dt.to_period("W").apply(
                lambda p: p.start_time
            )
            current_period = pd.Timestamp.now().to_period("W").start_time
        else:
            freq_label = "Month"
            df2_trend["Period"] = df2_trend["Start"].dt.to_period("M").dt.to_timestamp()
            current_period = pd.Timestamp.now().to_period("M").to_timestamp()

        df2_trend = df2_trend[df2_trend["Period"] < current_period]

        trend_data = (
            df2_trend.groupby(["Period", "Member"]).size().reset_index(name="Bookings")
        )
        trend_data["Type"] = trend_data["Member"].map({True: "Member", False: "Non-Member"})

        col1, col2 = st.columns(2)
        with col1:
            fig_trend = px.line(
                trend_data,
                x="Period",
                y="Bookings",
                color="Type",
                title=f"Bookings by {freq_label}",
                labels={"Bookings": "Number of Bookings", "Period": freq_label},
                color_discrete_map={"Member": "#1f77b4", "Non-Member": "#ff7f0e"},
                markers=True,
            )
            fig_trend.update_layout(height=400, margin=dict(t=50))
            st.plotly_chart(fig_trend, use_container_width=True)

        with col2:
            period_total = df2_trend.groupby("Period").size().reset_index(name="Total")
            period_members = (
                df2_trend[df2_trend["Member"]]
                .groupby("Period").size().reset_index(name="Members")
            )
            period_pct = period_total.merge(period_members, on="Period", how="left")
            period_pct["Members"] = period_pct["Members"].fillna(0)
            period_pct["Member %"] = (
                period_pct["Members"] / period_pct["Total"] * 100
            ).round(1)

            fig_pct = px.line(
                period_pct,
                x="Period",
                y="Member %",
                title=f"Member Bookings as % of Total Bookings by {freq_label}",
                labels={"Member %": "Member % of Bookings", "Period": freq_label},
                markers=True,
            )
            fig_pct.update_traces(line_color="#1f77b4")
            fig_pct.update_layout(
                height=400,
                margin=dict(t=50),
                yaxis=dict(range=[0, max(period_pct["Member %"].max() * 1.2, 5)]),
            )
            st.plotly_chart(fig_pct, use_container_width=True)

        # --- Key Takeaways toggle ---
        with st.expander(takeaway_title):
         if not show_takeaways:
            st.caption(
                f"Select at least 3 months of data for meaningful takeaways. "
                f"Current range: {date_range_days} days. "
                f"For the best insights, select the full season (September\u2013April)."
            )
         else:

            # Season context: Northern Sauna sauna season runs September-April (~8 months)
            SEASON_MONTHS = 8
            membership_fee = 25.0
            member_session_price = 12.50
            non_member_session_price = 17.50
            discount_per_visit = non_member_session_price - member_session_price
            breakeven_visits = membership_fee / discount_per_visit

            # Estimate season visits from the selected date range
            date_range_days = (df2["Start"].max() - df2["Start"].min()).days
            season_days = SEASON_MONTHS * 30  # ~240 days
            if date_range_days > 0 and date_range_days < season_days:
                season_factor = season_days / date_range_days
            else:
                season_factor = 1.0
            est_season_visits = bookings_per_member * season_factor

            # 1. Membership economics / breakeven
            # Net: discount × visits - fee
            net_discount_cost = (discount_per_visit * est_season_visits) - membership_fee
            member_profitable = net_discount_cost < 0

            if member_profitable:
                st.info(
                    f"**Membership pricing is profitable.** Members average "
                    f"**{bookings_per_member:.1f} bookings** in this period "
                    f"(~{est_season_visits:.0f} projected per season). The breakeven "
                    f"is **{breakeven_visits:.0f} visits per season** (where the "
                    f"{format_euro(discount_per_visit, 2)}/session discount exceeds the "
                    f"{format_euro(membership_fee)} annual fee). Your members are below "
                    f"breakeven \u2014 the fee income exceeds the total discount "
                    f"given. Consider promoting membership more aggressively, "
                    f"especially early in the season (September-October) when "
                    f"members have the most months to get value."
                )
            else:
                st.info(
                    f"**Members visit well beyond breakeven.** Members average "
                    f"**{bookings_per_member:.1f} bookings** in this period "
                    f"(~{est_season_visits:.0f} projected per season). Breakeven "
                    f"is **{breakeven_visits:.0f} visits per season**, so each "
                    f"member receives ~{format_euro(net_discount_cost)} more in discounts "
                    f"than the {format_euro(membership_fee)} fee covers. However, these "
                    f"visits might not have happened without the membership \u2014 "
                    f"the frequency uplift of **{freq_ratio:.1f}x** vs non-members "
                    f"suggests the discount is driving incremental revenue."
                )

            # 2. Turnover concentration
            total_rev = total_member_rev + total_non_member_rev
            member_rev_share = (
                total_member_rev / total_rev * 100 if total_rev > 0 else 0
            )
            member_customer_share = (
                unique_members / (unique_members + unique_non_members) * 100
                if (unique_members + unique_non_members) > 0 else 0
            )

            st.info(
                f"**Members are {member_customer_share:.0f}% of customers but "
                f"generate {member_rev_share:.0f}% of revenue.** "
                + (
                    "Members punch above their weight \u2014 each member "
                    "is worth more than each non-member. Protect this base "
                    "from churn. Since the season is only 8 months, losing a "
                    "member mid-season means lost revenue you can't recover "
                    "until next September."
                    if member_rev_share > member_customer_share
                    else "Members generate a smaller revenue share than their "
                    "customer share, likely due to the \u20ac5.00 session discount. "
                    "The value is in their frequency and loyalty, not per-visit revenue."
                )
            )

            # 3. Conversion potential — non-members with 2+ bookings
            non_member_freq = (
                non_members_df.groupby("Email address").size()
                .reset_index(name="bookings")
            )
            warm_leads = non_member_freq[non_member_freq["bookings"] >= 2]
            warm_lead_count = len(warm_leads)
            very_warm = non_member_freq[non_member_freq["bookings"] >= 3]
            very_warm_count = len(very_warm)
            past_breakeven = non_member_freq[
                non_member_freq["bookings"] >= breakeven_visits
            ]
            past_breakeven_count = len(past_breakeven)

            st.info(
                f"**{format_number(warm_lead_count)} non-members have booked 2+ times** "
                f"({format_number(very_warm_count)} have booked 3+ times) in this period. "
                f"**{format_number(past_breakeven_count)}** have already booked "
                f"{breakeven_visits:.0f}+ times \u2014 they would have saved money "
                f"with a {format_euro(membership_fee)} membership. Their emails are in "
                f"BigQuery \u2014 send them a targeted membership offer. "
                f"**Timing matters:** pitch early in the season (September-October) "
                f"so they have the full 8 months to benefit. A mid-season pitch "
                f"(January+) is harder to justify since fewer months remain."
            )

            # 4. Penetration trend
            if len(period_pct) >= 4:
                first_half_pct = period_pct["Member %"].iloc[:len(period_pct) // 2].mean()
                second_half_pct = period_pct["Member %"].iloc[len(period_pct) // 2:].mean()
                pct_delta = second_half_pct - first_half_pct
                trend_dir = "growing" if pct_delta > 0 else "shrinking"

                if abs(pct_delta) >= 0.5:
                    st.info(
                        f"**Member penetration is {trend_dir}** \u2014 member share "
                        f"moved from **{first_half_pct:.1f}%** to **{second_half_pct:.1f}%** "
                        f"of bookings over the period. "
                        + (
                            "Momentum is positive \u2014 the membership offering is "
                            "gaining traction this season."
                            if pct_delta > 0
                            else "Investigate: are fewer new members signing up, "
                            "or are existing members visiting less as the season "
                            "progresses?"
                        )
                    )
                else:
                    st.info(
                        f"**Member penetration is stable** at ~{second_half_pct:.1f}% "
                        f"of bookings. To grow this, target the {format_number(warm_lead_count)} "
                        f"repeat non-members identified above \u2014 ideally before "
                        f"the season ends in April."
                    )

            # 5. End-of-season savings email
            # Calculate what each non-member would have saved with membership
            non_member_visits = non_member_freq.copy()
            non_member_visits["would_have_paid"] = (
                non_member_visits["bookings"] * non_member_session_price
            )
            non_member_visits["with_membership"] = (
                non_member_visits["bookings"] * member_session_price + membership_fee
            )
            non_member_visits["savings"] = (
                non_member_visits["would_have_paid"]
                - non_member_visits["with_membership"]
            )
            would_have_saved = non_member_visits[non_member_visits["savings"] > 0]
            savers_count = len(would_have_saved)
            avg_savings = (
                would_have_saved["savings"].mean() if savers_count > 0 else 0
            )
            total_savings = (
                would_have_saved["savings"].sum() if savers_count > 0 else 0
            )

            if savers_count > 0:
                st.info(
                    f"**End-of-season campaign opportunity:** "
                    f"**{format_number(savers_count)} customers without a membership** visited "
                    f"enough this season that a membership would have saved them "
                    f"money. On average they'd have saved **{format_euro(avg_savings)}** each "
                    f"({format_euro(total_savings)} total). Send them a personalised "
                    f"email: *\"You visited X times this season and paid \u20acY. "
                    f"With a \u20ac25 membership you would have paid \u20acZ \u2014 "
                    f"saving \u20acW. Don't miss out next season.\"* "
                    f"Their visit counts and emails are in BigQuery."
                )


    # ==================== TAB 2: COHORTS ====================
    with tab_cohorts:
        st.markdown("### Member Cohorts by Sign-up Month")
        st.caption(
            "When did members first appear as a member in the booking data? "
            "Earlier sign-ups have more time to visit and justify the membership fee."
        )

        member_bookings = df2[df2["Member"]].copy()
        if len(member_bookings) > 0:
            member_first = (
                member_bookings.groupby("Email address")
                .agg(
                    first_member_booking=("Start", "min"),
                    total_bookings=("Start", "count"),
                    total_spent=("Total paid", "sum"),
                )
                .reset_index()
            )
            member_first["Cohort"] = member_first["first_member_booking"].dt.to_period("M").dt.to_timestamp()

            cohort_summary = (
                member_first.groupby("Cohort")
                .agg(
                    members=("Email address", "count"),
                    avg_bookings=("total_bookings", "mean"),
                    median_bookings=("total_bookings", "median"),
                    avg_spent=("total_spent", "mean"),
                )
                .reset_index()
            )
            cohort_summary["Label"] = cohort_summary["Cohort"].dt.strftime("%b %Y")

            if len(cohort_summary) > 1:
                col1, col2 = st.columns(2)
                with col1:
                    fig_cohort = px.bar(
                        cohort_summary,
                        x="Label",
                        y="avg_bookings",
                        title="Avg Bookings per Member by Sign-up Month",
                        labels={"avg_bookings": "Avg Bookings", "Label": "Sign-up Month"},
                        text=cohort_summary["avg_bookings"].apply(lambda x: f"{x:.1f}"),
                    )
                    fig_cohort.update_traces(marker_color="#1f77b4", textposition="outside")
                    fig_cohort.update_layout(height=450, margin=dict(t=80))
                    st.plotly_chart(fig_cohort, use_container_width=True)

                with col2:
                    fig_cohort_rev = px.bar(
                        cohort_summary,
                        x="Label",
                        y="avg_spent",
                        title="Avg Turnover per Member by Sign-up Month",
                        labels={"avg_spent": "Avg Turnover", "Label": "Sign-up Month"},
                        text=cohort_summary["avg_spent"].apply(lambda x: format_euro(x)),
                    )
                    fig_cohort_rev.update_traces(marker_color="#2ecc71", textposition="outside")
                    fig_cohort_rev.update_layout(height=450, margin=dict(t=80))
                    st.plotly_chart(fig_cohort_rev, use_container_width=True)

                _breakeven_visits = 25.0 / 5.0  # €25 fee ÷ €5 discount

                cohort_display = cohort_summary[["Label", "members", "avg_bookings", "median_bookings", "avg_spent"]].copy()
                cohort_display.columns = ["Sign-up Month", "Members", "Avg Bookings", "Median Bookings", "Avg Turnover"]
                cohort_display["Avg Bookings"] = cohort_display["Avg Bookings"].round(1)
                cohort_display["Median Bookings"] = cohort_display["Median Bookings"].round(1)
                cohort_display["Breakeven?"] = cohort_display["Avg Bookings"].apply(
                    lambda x: f"Yes ({x / _breakeven_visits:.1f}x)" if x >= _breakeven_visits else f"No ({x / _breakeven_visits * 100:.0f}%)"
                )
                cohort_display["Avg Turnover"] = cohort_display["Avg Turnover"].apply(lambda x: format_euro(x))

                st.dataframe(cohort_display, use_container_width=True, hide_index=True)
            else:
                st.info("Not enough cohort data \u2014 need members from at least 2 different months.")

        # --- Cohort Key Takeaways ---
        with st.expander(takeaway_title):
         if not show_takeaways:
            st.caption(
                f"Select at least 3 months of data for meaningful takeaways. "
                f"Current range: {date_range_days} days."
            )
         else:
            st.info(
                "**Membership Business Case**\n\n"
                "- **Longest-tenured members** \u2014 The Sep/Oct cohort represents members "
                "who signed up earliest in the season. They appear as the first bars in the chart "
                "and have had the most time to accumulate visits.\n"
                "- **How often did they go?** \u2014 The Avg Bookings column shows exactly how many "
                "times each cohort visited during the selected period.\n"
                "- **Breakeven column** \u2014 Members pay \u20ac25/season and get a \u20ac5 discount "
                "per visit (\u20ac12.50 vs \u20ac17.50). Breakeven is at **5 visits** "
                "(\u20ac25 \u00f7 \u20ac5). "
                "**'Yes'** means the member visited more than 5 times \u2014 they save more in "
                "discounts than the \u20ac25 fee costs. From Northern Sauna\u2019s perspective, these cohorts "
                "cost more in discounts than the fee covers. However, the higher visit frequency "
                "(see the bookings chart) suggests these visits wouldn\u2019t have happened without "
                "the membership \u2014 so the incremental turnover likely outweighs the discount cost. "
                "**'No'** means the member visited fewer than 5 times \u2014 the \u20ac25 fee more "
                "than covers the discounts given. These cohorts are directly profitable for Northern Sauna."
            )

            if len(member_bookings) > 0 and len(cohort_summary) > 1:
                # Breakeven analysis per cohort
                membership_fee = 25.0
                discount_per_visit = 5.0
                breakeven_visits = membership_fee / discount_per_visit

                earliest = cohort_summary.iloc[0]
                latest = cohort_summary.iloc[-1]

                st.info(
                    f"**Earliest cohort ({earliest['Label']}):** {earliest['members']:.0f} members, "
                    f"avg {earliest['avg_bookings']:.1f} bookings, avg turnover {format_euro(earliest['avg_spent'])}. "
                    + (
                        f"Above the {breakeven_visits:.0f}-visit breakeven \u2014 these members "
                        "save more than the \u20ac25 fee costs."
                        if earliest['avg_bookings'] > breakeven_visits
                        else f"Below the {breakeven_visits:.0f}-visit breakeven \u2014 the fee "
                        "covers the discounts given."
                    )
                    + f"\n\n**Latest cohort ({latest['Label']}):** {latest['members']:.0f} members, "
                    f"avg {latest['avg_bookings']:.1f} bookings. "
                    + (
                        "Even late sign-ups visit frequently enough to exceed breakeven."
                        if latest['avg_bookings'] > breakeven_visits
                        else "Late sign-ups have fewer visits \u2014 expected since they had less time. "
                        "Consider a pro-rated membership fee for mid-season sign-ups."
                    )
                )

                # Which month is the cutoff?
                for _, row in cohort_summary.iterrows():
                    if row["avg_bookings"] < breakeven_visits:
                        st.info(
                            f"**Breakeven cutoff:** Members signing up from **{row['Label']}** onwards "
                            f"average fewer than {breakeven_visits:.0f} visits. After this month, "
                            "consider a reduced membership fee or focus on converting these "
                            "customers next season instead."
                        )
                        break


    # ==================== TAB 3: BEHAVIOR ====================
    with tab_behavior:

        # --- KPIs ---
        has_lead_time = "Created" in df2.columns and "Start" in df2.columns
        if has_lead_time:
            df2_lt = df2.copy()
            df2_lt["Lead Days"] = (df2_lt["Start"] - df2_lt["Created"]).dt.days
            df2_lt = df2_lt[df2_lt["Lead Days"] >= 0]

            avg_lead_member = (
                df2_lt[df2_lt["Member"]]["Lead Days"].mean()
                if df2_lt["Member"].any() else 0
            )
            avg_lead_non = (
                df2_lt[~df2_lt["Member"]]["Lead Days"].mean()
                if (~df2_lt["Member"]).any() else 0
            )
            same_day_member = (
                (df2_lt[df2_lt["Member"]]["Lead Days"] == 0).mean() * 100
                if df2_lt["Member"].any() else 0
            )
            same_day_non = (
                (df2_lt[~df2_lt["Member"]]["Lead Days"] == 0).mean() * 100
                if (~df2_lt["Member"]).any() else 0
            )

            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric(
                    "Avg Lead Time (Member)",
                    f"{avg_lead_member:.1f} days",
                    help="Average days between booking and visit for members.",
                )
            with col2:
                st.metric(
                    "Avg Lead Time (Non-Member)",
                    f"{avg_lead_non:.1f} days",
                    help="Average days between booking and visit for non-members.",
                )
            with col3:
                st.metric(
                    "Same-Day % (Member)",
                    f"{same_day_member:.1f}%",
                    help="% of member bookings made on the same day as the visit.",
                )
            with col4:
                st.metric(
                    "Same-Day % (Non-Member)",
                    f"{same_day_non:.1f}%",
                    help="% of non-member bookings made on the same day.",
                )

        # --- Lead Time Distribution ---
        if has_lead_time:
            st.markdown("#### Booking Lead Time")
            st.caption("Do members book more spontaneously or further in advance?")

            col1, col2 = st.columns(2)
            with col1:
                fig_lt_m = px.histogram(
                    df2_lt[df2_lt["Member"] & (df2_lt["Lead Days"] <= 30)],
                    x="Lead Days",
                    title="Member Lead Time",
                    nbins=30,
                )
                fig_lt_m.update_traces(marker_color="#1f77b4")
                fig_lt_m.update_layout(height=350, margin=dict(t=50))
                st.plotly_chart(fig_lt_m, use_container_width=True)
            with col2:
                fig_lt_nm = px.histogram(
                    df2_lt[~df2_lt["Member"] & (df2_lt["Lead Days"] <= 30)],
                    x="Lead Days",
                    title="Non-Member Lead Time",
                    nbins=30,
                )
                fig_lt_nm.update_traces(marker_color="#ff7f0e")
                fig_lt_nm.update_layout(height=350, margin=dict(t=50))
                st.plotly_chart(fig_lt_nm, use_container_width=True)

        # --- Day & Time Patterns ---
        if "Start" in df2.columns:
            st.markdown("#### Day & Time Patterns")
            st.caption("When do members visit vs non-members?")

            df2_dt = df2.copy()
            df2_dt["Hour"] = df2_dt["Start"].dt.hour
            df2_dt["Day Num"] = df2_dt["Start"].dt.dayofweek
            df2_dt["Weekend"] = df2_dt["Day Num"] >= 5

            member_weekend_pct = (
                df2_dt[df2_dt["Member"]]["Weekend"].mean() * 100
                if df2_dt["Member"].any() else 0
            )
            non_member_weekend_pct = (
                df2_dt[~df2_dt["Member"]]["Weekend"].mean() * 100
                if (~df2_dt["Member"]).any() else 0
            )

            col1, col2 = st.columns(2)
            with col1:
                st.metric(
                    "Weekend Visits (Member)",
                    f"{member_weekend_pct:.1f}%",
                    help="% of member bookings on Saturday/Sunday.",
                )
            with col2:
                st.metric(
                    "Weekend Visits (Non-Member)",
                    f"{non_member_weekend_pct:.1f}%",
                    help="% of non-member bookings on Saturday/Sunday.",
                )

            day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            col1, col2 = st.columns(2)
            for col, member_flag, label, colorscale in [
                (col1, True, "Member", "Blues"),
                (col2, False, "Non-Member", "Oranges"),
            ]:
                subset = df2_dt[df2_dt["Member"] == member_flag]
                if len(subset) == 0:
                    continue
                heat = (
                    subset.groupby(["Day Num", "Hour"]).size()
                    .reset_index(name="Bookings")
                )
                full_grid = pd.DataFrame(
                    list(itertools.product(range(7), range(24))),
                    columns=["Day Num", "Hour"],
                )
                heat = full_grid.merge(heat, on=["Day Num", "Hour"], how="left")
                heat["Bookings"] = heat["Bookings"].fillna(0).astype(int)
                heat_pivot = heat.pivot(
                    index="Day Num", columns="Hour", values="Bookings"
                ).sort_index()

                fig_heat = px.imshow(
                    heat_pivot.values,
                    x=[f"{h}:00" for h in range(24)],
                    y=day_labels,
                    color_continuous_scale=colorscale,
                    title=f"{label} Bookings",
                    labels={"color": "Bookings", "x": "Hour", "y": "Day"},
                    aspect="auto",
                )
                fig_heat.update_layout(height=350, margin=dict(t=50, b=30))
                with col:
                    st.plotly_chart(fig_heat, use_container_width=True)

        # --- Product / Activity Mix ---
        if "Activity" in df2.columns:
            st.markdown("#### Product / Activity Mix")
            st.caption("Do members book different products than non-members?")

            act_comp = (
                df2.groupby(["Activity", "Member"]).size()
                .reset_index(name="Bookings")
            )
            act_comp["Type"] = act_comp["Member"].map(
                {True: "Member", False: "Non-Member"}
            )
            top_activities = df2["Activity"].value_counts().head(10).index.tolist()
            act_top = act_comp[act_comp["Activity"].isin(top_activities)]

            fig_act = px.bar(
                act_top.sort_values(["Activity", "Type"]),
                x="Bookings",
                y="Activity",
                color="Type",
                orientation="h",
                barmode="group",
                title="Top 10 Activities: Member vs Non-Member",
                color_discrete_map={"Member": "#1f77b4", "Non-Member": "#ff7f0e"},
            )
            fig_act.update_layout(height=500, margin=dict(t=50, l=200))
            st.plotly_chart(fig_act, use_container_width=True)

        # --- Group Size ---
        if "Participants" in df2.columns:
            st.markdown("#### Group Size")
            st.caption("Do members bring more people per booking?")

            avg_part_member = members_df["Participants"].mean() if len(members_df) > 0 else 0
            avg_part_non = non_members_df["Participants"].mean() if len(non_members_df) > 0 else 0

            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric(
                    "Avg Group Size (Member)", f"{avg_part_member:.1f}",
                    help="Average participants per member booking.",
                )
            with col2:
                st.metric(
                    "Avg Group Size (Non-Member)", f"{avg_part_non:.1f}",
                    help="Average participants per non-member booking.",
                )
            with col3:
                total_member_participants = members_df["Participants"].sum()
                total_participants = df2["Participants"].sum()
                member_participant_share = (
                    total_member_participants / total_participants * 100
                    if total_participants > 0 else 0
                )
                st.metric(
                    "Member Participant Share", f"{member_participant_share:.1f}%",
                    help="% of all participants that come from member bookings.",
                )

        # --- Key Takeaways toggle ---
        with st.expander(takeaway_title):
         if not show_takeaways:
            st.caption(
                f"Select at least 3 months of data for meaningful takeaways. "
                f"Current range: {date_range_days} days. "
                f"For the best insights, select the full season (September\u2013April)."
            )
         else:

            # 1. Spontaneity — same-day booking implications
            if has_lead_time:
                st.info(
                    f"**Members book more spontaneously.** "
                    f"**{same_day_member:.0f}%** of member bookings are same-day "
                    f"vs **{same_day_non:.0f}%** for non-members. "
                    + (
                        "Members use their membership like a gym pass \u2014 "
                        "they decide to go and book immediately. This means "
                        "**last-minute slot availability is critical** for member "
                        "satisfaction. If popular slots fill up days ahead, "
                        "members can't use their membership \u2014 especially "
                        "risky during the busy winter months (November-February) "
                        "when demand peaks."
                        if same_day_member > same_day_non
                        else "Members actually plan further ahead than non-members. "
                        "This suggests memberships attract planners, not impulse visitors."
                    )
                )

            # 2. Off-peak vs peak — do members help balance capacity?
            if "Start" in df2.columns:
                member_hours = members_df["Start"].dt.hour
                non_member_hours = non_members_df["Start"].dt.hour

                member_offpeak_pct = (
                    ((member_hours >= 10) & (member_hours <= 15)).mean() * 100
                    if len(member_hours) > 0 else 0
                )
                non_member_offpeak_pct = (
                    ((non_member_hours >= 10) & (non_member_hours <= 15)).mean() * 100
                    if len(non_member_hours) > 0 else 0
                )

                st.info(
                    f"**Off-peak usage (10:00-15:00):** Members book "
                    f"**{member_offpeak_pct:.0f}%** of their sessions off-peak "
                    f"vs **{non_member_offpeak_pct:.0f}%** for non-members. "
                    + (
                        "Members disproportionately fill off-peak slots \u2014 "
                        "the membership discount is effectively shifting demand "
                        "away from peak hours, helping balance capacity. "
                        "This is especially valuable during the busy winter months "
                        "when evening slots fill up fastest."
                        if member_offpeak_pct > non_member_offpeak_pct + 3
                        else (
                            "Members compete for the same peak slots as non-members. "
                            "Consider an off-peak membership bonus (e.g. extra "
                            "discount for weekday midday sessions) to shift member "
                            "demand to quieter hours during the season."
                            if member_offpeak_pct < non_member_offpeak_pct - 3
                            else "Members and non-members use similar time slots. "
                            "An off-peak membership bonus could help fill the quiet "
                            "midday hours that are consistently empty across the season."
                        )
                    )
                )

            # 3. Group size as referral channel
            if "Participants" in df2.columns:
                guests_per_member_booking = max(0, avg_part_member - 1)
                guests_per_non_member = max(0, avg_part_non - 1)

                st.info(
                    f"**Members bring {avg_part_member:.1f} people per booking** "
                    f"(vs {avg_part_non:.1f} for non-members). "
                    + (
                        f"Members bring more guests \u2014 an average of "
                        f"**{guests_per_member_booking:.1f} guests** per visit who "
                        f"pay full price (\u20ac17.50). Members act as referral channels. "
                        f"Consider a 'bring a friend' bonus to amplify this."
                        if avg_part_member > avg_part_non + 0.1
                        else (
                            "Members tend to visit solo more often. The membership "
                            "discount only applies to them personally (membership is "
                            "non-transferable), so this is expected. A 'bring a friend' "
                            "deal could encourage members to introduce new customers."
                            if avg_part_member < avg_part_non - 0.1
                            else "Group sizes are similar for members and non-members."
                        )
                    )
                )


    # ==================== TAB 3: RETENTION & LOYALTY ====================
    with tab_loyalty:

        # --- KPIs ---
        has_location = "Location" in df2.columns

        if has_location:
            member_loc_counts = (
                members_df.groupby("Email address")["Location"]
                .nunique().reset_index(name="Locations Visited")
            )
            non_member_loc_counts = (
                non_members_df.groupby("Email address")["Location"]
                .nunique().reset_index(name="Locations Visited")
            )
            avg_locs_member = (
                member_loc_counts["Locations Visited"].mean()
                if len(member_loc_counts) > 0 else 0
            )
            avg_locs_non = (
                non_member_loc_counts["Locations Visited"].mean()
                if len(non_member_loc_counts) > 0 else 0
            )
            multi_loc_members = (
                (member_loc_counts["Locations Visited"] > 1).sum()
                if len(member_loc_counts) > 0 else 0
            )
            multi_loc_pct = (
                multi_loc_members / len(member_loc_counts) * 100
                if len(member_loc_counts) > 0 else 0
            )

            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric(
                    "Avg Locations (Member)", f"{avg_locs_member:.1f}",
                    help="Average distinct locations visited per member.",
                )
            with col2:
                st.metric(
                    "Avg Locations (Non-Member)", f"{avg_locs_non:.1f}",
                    help="Average distinct locations visited per non-member.",
                )
            with col3:
                st.metric(
                    "Multi-Location Members",
                    format_number(multi_loc_members),
                    delta=f"{multi_loc_pct:.1f}% of members".replace(".", ","),
                    delta_color="off",
                    help="Members who visited more than one location.",
                )
            with col4:
                loc_uplift = (
                    (avg_locs_member / avg_locs_non - 1) * 100
                    if avg_locs_non > 0 else 0
                )
                st.metric(
                    "Location Loyalty Uplift",
                    f"{loc_uplift:+.0f}%",
                    help="How many more locations members visit vs non-members.",
                )

        # --- Members by Location ---
        if has_location:
            st.markdown("#### Members by Location")

            location_stats = df2.groupby("Location").agg(
                member_bookings=("Member", "sum"),
                non_member_bookings=("Member", lambda x: (~x).sum()),
                total_gross=("Total paid", "sum"),
            ).reset_index()

            member_rev_by_loc = (
                members_df.groupby("Location")["Total paid"].mean().reset_index()
            )
            member_rev_by_loc.columns = ["Location", "Avg Member Rev"]

            non_member_rev_by_loc = (
                non_members_df.groupby("Location")["Total paid"].mean().reset_index()
            )
            non_member_rev_by_loc.columns = ["Location", "Avg Non-Member Rev"]

            location_stats = location_stats.merge(member_rev_by_loc, on="Location", how="left")
            location_stats = location_stats.merge(non_member_rev_by_loc, on="Location", how="left")
            location_stats["Avg Member Rev"] = location_stats["Avg Member Rev"].fillna(0)
            location_stats["Avg Non-Member Rev"] = location_stats["Avg Non-Member Rev"].fillna(0)
            location_stats["Member %"] = (
                location_stats["member_bookings"]
                / (location_stats["member_bookings"] + location_stats["non_member_bookings"])
                * 100
            ).round(1)
            location_stats = location_stats.sort_values("member_bookings", ascending=False)

            location_display = location_stats.rename(columns={
                "member_bookings": "Member Bookings",
                "non_member_bookings": "Non-Member Bookings",
            })[
                ["Location", "Member Bookings", "Non-Member Bookings",
                 "Member %", "Avg Member Rev", "Avg Non-Member Rev"]
            ]

            loc_config = {
                "Location": st.column_config.TextColumn("Location"),
                "Member Bookings": st.column_config.NumberColumn("Member Bookings"),
                "Non-Member Bookings": st.column_config.NumberColumn("Non-Member Bookings"),
                "Member %": st.column_config.NumberColumn("Member %", format="%.1f%%"),
                "Avg Member Rev": st.column_config.NumberColumn("Avg Member Rev", format="\u20ac%.2f"),
                "Avg Non-Member Rev": st.column_config.NumberColumn("Avg Non-Member Rev", format="\u20ac%.2f"),
            }
            st.dataframe(
                location_display, use_container_width=True,
                hide_index=True, column_config=loc_config,
            )

        # --- Location Loyalty Distribution ---
        if has_location:
            st.markdown("#### Location Loyalty")
            st.caption("Do members visit more locations than non-members?")

            col1, col2 = st.columns(2)
            with col1:
                loc_dist_m = (
                    member_loc_counts["Locations Visited"]
                    .value_counts().sort_index().reset_index()
                )
                loc_dist_m.columns = ["Locations", "Members"]
                fig_loc_m = px.bar(
                    loc_dist_m, x="Locations", y="Members",
                    title="Member: Locations per Customer",
                    text="Members",
                )
                fig_loc_m.update_traces(marker_color="#1f77b4", textposition="outside")
                fig_loc_m.update_layout(height=350, margin=dict(t=50))
                st.plotly_chart(fig_loc_m, use_container_width=True)

            with col2:
                loc_dist_nm = (
                    non_member_loc_counts["Locations Visited"]
                    .value_counts().sort_index().reset_index()
                )
                loc_dist_nm.columns = ["Locations", "Non-Members"]
                fig_loc_nm = px.bar(
                    loc_dist_nm, x="Locations", y="Non-Members",
                    title="Non-Member: Locations per Customer",
                    text="Non-Members",
                )
                fig_loc_nm.update_traces(marker_color="#ff7f0e", textposition="outside")
                fig_loc_nm.update_layout(height=350, margin=dict(t=50))
                st.plotly_chart(fig_loc_nm, use_container_width=True)

        # --- Promotion & Coupon Usage ---
        promo_col = "Promotion" if "Promotion" in df2.columns else None
        coupon_col = "Coupons" if "Coupons" in df2.columns else None

        if promo_col:
            st.markdown("#### Promotion & Coupon Usage")
            st.caption("Do members stack promotions on top of membership discounts?")

            member_has_promo = (
                members_df[promo_col].notna() & (members_df[promo_col] != "")
            ).sum()
            member_promo_pct = (
                member_has_promo / len(members_df) * 100 if len(members_df) > 0 else 0
            )
            non_member_has_promo = (
                non_members_df[promo_col].notna() & (non_members_df[promo_col] != "")
            ).sum()
            non_member_promo_pct = (
                non_member_has_promo / len(non_members_df) * 100
                if len(non_members_df) > 0 else 0
            )

            member_coupon_pct = 0.0
            non_member_coupon_pct = 0.0
            if coupon_col:
                member_has_coupon = (
                    members_df[coupon_col].notna() & (members_df[coupon_col] != "")
                ).sum()
                member_coupon_pct = (
                    member_has_coupon / len(members_df) * 100
                    if len(members_df) > 0 else 0
                )
                non_member_has_coupon = (
                    non_members_df[coupon_col].notna()
                    & (non_members_df[coupon_col] != "")
                ).sum()
                non_member_coupon_pct = (
                    non_member_has_coupon / len(non_members_df) * 100
                    if len(non_members_df) > 0 else 0
                )

            promo_comparison = pd.DataFrame({
                "Metric": ["Promotion Usage", "Coupon Usage"],
                "Member %": [member_promo_pct, member_coupon_pct],
                "Non-Member %": [non_member_promo_pct, non_member_coupon_pct],
            })

            fig_promo = px.bar(
                promo_comparison.melt(
                    id_vars="Metric", var_name="Type", value_name="Usage %"
                ),
                x="Metric", y="Usage %", color="Type",
                barmode="group", text="Usage %",
                color_discrete_map={
                    "Member %": "#1f77b4", "Non-Member %": "#ff7f0e",
                },
            )
            fig_promo.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
            fig_promo.update_layout(height=400, margin=dict(t=20))
            st.plotly_chart(fig_promo, use_container_width=True)

        # --- Key Takeaways toggle ---
        with st.expander(takeaway_title):
         if not show_takeaways:
            st.caption(
                f"Select at least 3 months of data for meaningful takeaways. "
                f"Current range: {date_range_days} days. "
                f"For the best insights, select the full season (September\u2013April)."
            )
         else:

            # 1. Cross-location engagement as churn indicator
            if has_location:
                single_loc_pct = 100 - multi_loc_pct

                st.info(
                    f"**{multi_loc_pct:.0f}% of members visit multiple locations** "
                    f"\u2014 these are deeply engaged and likely to renew next season. "
                    f"The remaining **{single_loc_pct:.0f}%** stick to one location "
                    f"and are more convenience-driven. Since membership is regional "
                    f"(Stockholm, Helsinki, or Oslo), encourage single-location members "
                    f"to try other locations in their region. A 'location passport' "
                    f"challenge during the season could drive this."
                )

            # 2. Promo stacking — margin erosion
            if promo_col:
                st.info(
                    f"**{member_promo_pct:.1f}% of member bookings also use a "
                    f"promotion** (vs {non_member_promo_pct:.1f}% for non-members). "
                    + (
                        "Members are double-dipping \u2014 they already receive a "
                        "\u20ac5.00 discount per session from their membership. "
                        "Stacking a promotion on top further erodes margin without "
                        "adding loyalty (they're already members). Consider excluding "
                        "members from certain promotions, or offering member-exclusive "
                        "perks instead of price discounts."
                        if member_promo_pct > 10
                        else "Promo stacking is minimal \u2014 members are not "
                        "excessively combining their membership discount with promotions."
                    )
                )

            # 3. Location with lowest member penetration
            if has_location and len(location_stats) > 0:
                # Filter to Northern Sauna locations only
                local_locs = location_stats[
                    location_stats["Location"].str.lower().str.startswith("northern sauna")
                ]
                if len(local_locs) >= 2:
                    lowest_loc = local_locs.loc[local_locs["Member %"].idxmin()]
                    highest_loc = local_locs.loc[local_locs["Member %"].idxmax()]
                    lowest_name = lowest_loc["Location"].replace("Northern Sauna ", "")
                    highest_name = highest_loc["Location"].replace("Northern Sauna ", "")

                    st.info(
                        f"**Biggest conversion opportunity: {lowest_name}** "
                        f"at only **{lowest_loc['Member %']:.0f}%** member penetration "
                        f"(vs **{highest_loc['Member %']:.0f}%** at {highest_name}). "
                        f"Investigate why \u2014 is it a newer location, tourist-heavy, "
                        f"or simply undermarketed for membership? "
                        f"Staff at {lowest_name} could actively pitch membership "
                        f"at checkout, especially early in the season "
                        f"(September-October) when the value proposition is strongest."
                    )

            # 4. Dormant members — silent churn detection
            dormant_days = 60
            cutoff_date = df2["Start"].max() - pd.Timedelta(days=dormant_days)
            season_start = df2["Start"].min()

            # Members active early in season but not in last 60 days
            member_activity = members_df.groupby("Email address").agg(
                first_booking=("Start", "min"),
                last_booking=("Start", "max"),
                total_bookings=("Start", "count"),
            ).reset_index()

            # Active early (first booking in first half of data range)
            mid_season = season_start + (df2["Start"].max() - season_start) / 2
            dormant = member_activity[
                (member_activity["first_booking"] < mid_season)
                & (member_activity["last_booking"] < cutoff_date)
                & (member_activity["total_bookings"] >= 2)
            ]
            dormant_count = len(dormant)

            if dormant_count > 0:
                avg_dormant_days = (
                    (df2["Start"].max() - dormant["last_booking"]).dt.days.mean()
                )
                st.warning(
                    f"**{format_number(dormant_count)} members are going silent.** "
                    f"These members were active earlier this season but haven't "
                    f"booked in **{avg_dormant_days:.0f}+ days**. They had 2+ "
                    f"bookings before going quiet \u2014 this is a churn signal. "
                    f"The season ends in April. Send a re-engagement email now: "
                    f"*\"We haven't seen you in a while \u2014 your membership is "
                    f"still active. Book your next session before the season ends.\"* "
                    f"Their emails are in BigQuery."
                )




render_footer()
