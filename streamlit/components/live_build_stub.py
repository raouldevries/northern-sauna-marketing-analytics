"""Reusable text-only stub for pages that only run in the live build.

Used by `pages/8_reviews.py` and `pages/12_ai_assistant.py` to render a
consistent "Live build only" placeholder in the public demo — the demo
cannot supply the underlying data dependency (real GMB reviews / a
configured Anthropic API key against the live BQ schema), so the stub
explains what the page does in the live build and why it can't run here.
"""

from __future__ import annotations

import streamlit as st


def render_live_build_stub(
    title: str,
    description_paragraphs: list[str],
    why_not_live: str,
) -> None:
    """Render a text-only Live-build-only placeholder."""
    st.markdown(
        """
        <style>
        .live-build-badge {
            display: inline-block;
            background: #f3f3f3;
            color: #555;
            border: 1px solid #e0e0e0;
            border-radius: 999px;
            padding: 0.2rem 0.7rem;
            font-size: 0.78rem;
            letter-spacing: 0.04em;
            text-transform: uppercase;
            margin-bottom: 0.8rem;
        }
        .live-build-footer {
            margin-top: 1.6rem;
            padding: 1rem 1.2rem;
            background: #fafafa;
            border-left: 3px solid #ccc;
            color: #444;
            font-size: 0.92rem;
            line-height: 1.5;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        '<span class="live-build-badge">Live build only</span>',
        unsafe_allow_html=True,
    )
    st.title(title)

    for paragraph in description_paragraphs:
        st.markdown(paragraph)

    st.markdown(
        f'<div class="live-build-footer">'
        f"<strong>Why isn't this live in the demo?</strong><br>{why_not_live}"
        f"</div>",
        unsafe_allow_html=True,
    )
