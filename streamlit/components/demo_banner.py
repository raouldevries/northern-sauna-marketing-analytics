"""Demo-mode banner + footer.

Mounted on every page so the synthetic-data context is always visible.
Both helpers short-circuit when `DEMO_MODE` is not set, so live builds
get neither the banner nor the footer.
"""

from __future__ import annotations

import os

import streamlit as st


def _is_demo_mode() -> bool:
    return os.environ.get("DEMO_MODE", "").lower() == "true"


def render_demo_banner() -> None:
    """Render the persistent 'Demo mode' banner at the top of a page."""
    if not _is_demo_mode():
        return
    st.markdown(
        """
        <style>
        .ns-demo-banner {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.8rem;
            padding: 0.55rem 0.9rem;
            margin-bottom: 0.9rem;
            background: linear-gradient(90deg, #f6f1ea 0%, #fbf6ee 100%);
            border: 1px solid #e8ddc8;
            border-radius: 8px;
            color: #5a4720;
            font-size: 0.92rem;
            line-height: 1.4;
        }
        .ns-demo-banner__tag {
            background: #5a4720;
            color: #fbf6ee;
            font-size: 0.72rem;
            letter-spacing: 0.06em;
            text-transform: uppercase;
            padding: 0.18rem 0.55rem;
            border-radius: 999px;
            flex-shrink: 0;
        }
        .ns-demo-banner__msg {
            flex: 1;
        }
        </style>
        <div class="ns-demo-banner">
            <span class="ns-demo-banner__tag">Demo mode</span>
            <span class="ns-demo-banner__msg">
                You're viewing a public portfolio build &mdash; every number
                here is generated from <code>scripts/generate_demo_data.py</code>.
                No real customers, no real revenue.
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_footer() -> None:
    """Render the page footer with links to source + about-the-demo anchor."""
    if not _is_demo_mode():
        return
    st.markdown(
        """
        <style>
        .ns-demo-footer {
            margin-top: 3rem;
            padding-top: 1rem;
            border-top: 1px solid #ececec;
            color: #888;
            font-size: 0.82rem;
            line-height: 1.5;
            text-align: center;
        }
        .ns-demo-footer a {
            color: #5a4720;
            text-decoration: none;
            border-bottom: 1px dotted #c9b88a;
        }
        .ns-demo-footer a:hover {
            color: #3a2f15;
            border-bottom-style: solid;
        }
        </style>
        <div class="ns-demo-footer">
            Public portfolio demo &middot;
            <a href="https://github.com/raouldevries/northern-sauna-marketing-analytics"
               target="_blank" rel="noopener">source</a>
            &middot;
            <a href="https://github.com/raouldevries/northern-sauna-marketing-analytics#whats-not-in-the-public-demo"
               target="_blank" rel="noopener">about this demo</a>
        </div>
        """,
        unsafe_allow_html=True,
    )
