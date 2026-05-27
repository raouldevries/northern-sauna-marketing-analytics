"""How Northern Sauna AI works — explainer page linked from the Northern Sauna AI empty state.

Hidden from the main sidebar nav (not registered in `utils.render_sidebar_nav`).
Only reachable via `st.switch_page` from `12_ai_assistant.py`'s welcome screen.
"""

import streamlit as st
from components.demo_banner import render_demo_banner, render_footer  # noqa: E402
from utils import render_sidebar_nav

st.set_page_config(
    page_title="How Northern Sauna AI works",
    page_icon=":material/auto_awesome:",
    layout="wide",
)

if not st.session_state.get("authenticated", False):
    st.switch_page("app.py")

# --- Stylesheet (mirrors 12_ai_assistant.py's narrow content column) ---
st.markdown(
    """
<style>
/* Hide default Streamlit nav, hamburger, footer */
[data-testid="stSidebarNav"] { display: none; }
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }

/* Centred narrow content column to match the Northern Sauna AI page */
.main .block-container {
    max-width: 42rem;
    margin-left: auto;
    margin-right: auto;
    padding-left: 2rem;
    padding-right: 2rem;
    padding-top: 2rem;
    padding-bottom: 6rem;
}

/* "Back" link styling — small, muted, sits above the title */
.st-key-back_link {
    margin-bottom: 0.5rem;
}
.st-key-back_link a {
    color: #888 !important;
    font-size: 0.9rem !important;
    text-decoration: none !important;
}
.st-key-back_link a:hover {
    color: #333 !important;
    text-decoration: underline !important;
}

/* Title spacing */
h1 { margin-top: 0.25rem !important; margin-bottom: 1rem !important; }

/* Lead paragraph */
.ns-ai-about-lead {
    color: #444;
    font-size: 1.02rem;
    line-height: 1.55;
    margin-bottom: 1.5rem;
}

/* Tight expander spacing */
[data-testid="stExpander"] {
    margin: 0.5rem 0;
}
</style>
""",
    unsafe_allow_html=True,
)

# --- Sidebar (same as Northern Sauna AI so the page feels like a sub-page) ---
render_sidebar_nav("Northern Sauna AI")

render_demo_banner()

# --- Back link ---
with st.container(key="back_link"):
    st.page_link("pages/12_ai_assistant.py", label="← Back to Northern Sauna AI")

# --- Title + lead ---
st.title("How Northern Sauna AI works")

st.markdown(
    '<p class="ns-ai-about-lead">'
    "Northern Sauna AI lets you ask plain-English questions about your bookings, "
    "marketing, and SEO data. It turns each question into a query against "
    "the same BigQuery warehouse the dashboards use, runs it, and shows "
    "you the result with a written summary. No SQL knowledge required — "
    "but the answers come from the same source of truth as everything "
    "else in this app."
    "</p>",
    unsafe_allow_html=True,
)

# --- Sections ---

with st.expander("What you can ask"):
    st.markdown(
        """
**Data sources covered**

- **Bookings** — every Bookeo booking (location, status, revenue, participants, dates)
- **Google Ads** — campaign, ad-group, ad, RSA asset, PMax asset, and image performance
- **Meta Ads** (Facebook / Instagram) — campaign and ad-level metrics, demographic breakdowns
- **Google Search Console** — organic search queries, impressions, clicks, position
- **GA4** (website analytics) — sessions, traffic sources, devices, geography, page-level metrics

**Example questions**

- "How many bookings did we have last month, by location?"
- "What's our revenue trend over the past 3 months, weekly?"
- "Which Google Ads campaigns had the best ROAS in the last 30 days?"
- "Top 10 search queries driving organic traffic this month"
- "Compare Google Ads vs Meta Ads spend and clicks for Q1"
- "Best Google Ads image creatives by conversions, last 14 days"

**Tips for better answers**

- Be **specific about the date range** ("in March 2026" beats "recently").
- Name the **location** if you have one in mind ("Northern Sauna Södermalm", "Helsinki Kamppi").
- Specify the **metric** you want (bookings, revenue, ROAS, CTR…).
- One question at a time — multi-part questions are harder for the model to handle cleanly.
        """
    )

with st.expander("How it works behind the scenes"):
    st.markdown(
        """
1. **You ask a question** in the chat box, in plain English.
2. **Northern Sauna AI translates the question into SQL.** It uses an Anthropic Claude model with
   a complete map of your tables, columns, and business rules (currency, status values,
   location names, the canonical "bookings" definition, …). The model picks the right
   table or view for the question and writes a parametrised query.
3. **The SQL is checked before it runs.** A safety layer rejects anything that looks
   unsafe: queries without a date filter on partitioned tables, queries on PII columns,
   anything that isn't a `SELECT`, anything outside the tables Northern Sauna AI is allowed to
   read.
4. **BigQuery runs the query** against the live warehouse, with a 10 GB scan cap per
   query as a hard cost ceiling.
5. **You see the result** — a table or chart, plus a short written summary of what the
   numbers mean. The generated SQL is also shown so you can spot a questionable
   interpretation before trusting the answer.
        """
    )

with st.expander("Why the answers are reliable"):
    st.markdown(
        """
A few investments make Northern Sauna AI's answers more trustworthy than a generic
LLM-on-a-database setup.

**PII protection.** Customer names, email addresses, phone numbers, and the raw Bookeo
JSON payload are tagged in a central catalog and **blocked at the SQL layer**. Even if
someone explicitly asks "list customer emails for the last 100 bookings", the validator
refuses the query before it runs. The model never sees these columns in its schema
either, so it has no way to suggest them.

**Cost protection.** Every query has a 10 GB scan limit and partitioned tables
(bookings, Search Console, Meta Ads, the Google Ads creative views) require a date
filter. A question that would otherwise sweep multiple years of data is rejected with
a hint to narrow the range.

**Schema accuracy.** A drift audit checks daily that the AI's understanding of your
data matches what's actually in BigQuery. If a column is added, removed, or has its
type changed, the audit catches it and prevents Northern Sauna AI from quietly drifting out of
sync with your warehouse.

**Eval-driven improvements.** A benchmark of known questions with verified expected
answers runs against every prompt or model change. Anything that lowers the
answer-correctness rate gets caught before it ships. Critical changes also go through
an external code review (an "audit-loop" that runs an independent model against the
diff) so two layers of review catch regressions the team would miss.

**Conversation logging.** Every question, the SQL generated, and the result are logged.
If you ever say "this answer was wrong", we can replay exactly what the model saw and
why it answered the way it did.
        """
    )

with st.expander("Limits & gotchas"):
    st.markdown(
        """
Northern Sauna AI is a tool, not an oracle. Things to keep in mind:

- **The model can be wrong.** For numbers that you'll act on, sanity-check against
  the dashboard pages (Overview, Turnover, Bookings, Marketing). The generated SQL is
  shown alongside the answer for that reason — if it doesn't match the question, treat
  the result with caution.
- **Some data sources have known gaps.** Meta Ads sync has been paused since April 2026
  (so recent Meta numbers are stale). Google My Business (reviews, locations) is
  waiting on API access. These show up as "no data" rather than wrong data, but it's
  worth knowing.
- **Date ranges that span many months may be slow** on the first query while BigQuery
  warms up.
- **"Why" questions get descriptive, not causal answers.** "Why did sales drop last
  week" returns *what* changed, not *why* it changed — root-cause analysis still
  requires you.
- **Demand Gen video campaigns are seasonally paused** (typically April–September).
  Zero rows on a recent window is expected, not a bug.
- **Location attribution is a heuristic** for the marketing-by-location view. Campaign
  names without a location keyword are excluded from per-location ad spend numbers.
        """
    )

with st.expander("Wrong answer? Let us know"):
    st.markdown(
        """
If you spot an answer that looks wrong, click the **Feedback** button in
the sidebar (bottom-left). Describe what you asked and what looked off.

Feedback gets reviewed and, when the question is a clear case, added to
the benchmark set so the same kind of mistake is caught automatically the
next time the prompt or the model changes.
        """
    )

# --- Bottom back link ---
st.markdown('<div style="height: 2rem;"></div>', unsafe_allow_html=True)
with st.container(key="back_link_bottom"):
    st.page_link("pages/12_ai_assistant.py", label="← Back to Northern Sauna AI")

render_footer()
