"""European number/currency formatters and DataFrame styling for revenue pages."""

import pandas as pd

import streamlit as st


def format_euro(value, decimals=0):
    """Format a number as Euro with European notation."""
    if pd.isna(value):
        return "€0"
    if decimals == 0:
        formatted = f"{value:,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")
    else:
        formatted = f"{value:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"€{formatted}"


def format_number(value, decimals=0):
    """Format a number with European notation."""
    if pd.isna(value):
        return "0"
    if decimals == 0:
        return f"{value:,.0f}".replace(",", ".")
    else:
        return f"{value:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def format_number_adaptive(value, decimals=1):
    """Format a number as integer when whole, else with N decimals.

    Useful for weighted aggregates that may be fractional (e.g. a cluster
    ad-set that splits one conversion across N locations) but are usually
    whole at the per-location aggregate level.
    """
    if pd.isna(value):
        return "0"
    rounded = round(float(value), decimals)
    if rounded == int(rounded):
        return f"{int(rounded):,}".replace(",", ".")
    return f"{rounded:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def format_pct(value, decimals=1):
    """Format a percentage with European decimal notation."""
    if pd.isna(value):
        return "0%"
    return f"{value:.{decimals}f}%".replace(".", ",")


def format_roas(value, decimals=1):
    """Format a ROAS multiple as `5,0x` with European decimal notation."""
    if pd.isna(value):
        return "0x"
    return f"{value:.{decimals}f}x".replace(".", ",")


def format_dataframe_nl(
    df,
    euro_cols=None,
    int_cols=None,
    pct_cols=None,
    euro_decimal_cols=None,
    roas_cols=None,
    adaptive_num_cols=None,
):
    """Apply Dutch number formatting to a DataFrame for display.

    Args:
        df: DataFrame to format (returns a copy)
        euro_cols: columns formatted as €1.234 (no decimals)
        int_cols: columns formatted as 1.234 (integer with dot separator)
        pct_cols: columns formatted as 3,4 (1 decimal, comma)
        euro_decimal_cols: columns formatted as €12,34 (2 decimals)
        roas_cols: columns formatted as 5,0x (1 decimal, comma, "x" suffix)
        adaptive_num_cols: columns formatted as integer when whole, else
            N decimals — for weighted aggregates that may be fractional.
    """
    fmt = df.copy()
    for col in (euro_cols or []):
        if col in fmt.columns:
            fmt[col] = fmt[col].apply(format_euro)
    for col in (int_cols or []):
        if col in fmt.columns:
            fmt[col] = fmt[col].apply(format_number)
    for col in (pct_cols or []):
        if col in fmt.columns:
            fmt[col] = fmt[col].apply(format_pct)
    for col in (euro_decimal_cols or []):
        if col in fmt.columns:
            fmt[col] = fmt[col].apply(lambda x: format_euro(x, 2))
    for col in (roas_cols or []):
        if col in fmt.columns:
            fmt[col] = fmt[col].apply(format_roas)
    for col in (adaptive_num_cols or []):
        if col in fmt.columns:
            fmt[col] = fmt[col].apply(format_number_adaptive)
    return fmt


def style_dataframe_right_align(df, exclude_cols=None):
    """Apply right-alignment styling to all columns except specified ones."""
    if exclude_cols is None:
        exclude_cols = []

    def right_align(col):
        if col.name in exclude_cols:
            return ['text-align: left'] * len(col)
        return ['text-align: right'] * len(col)

    return df.style.apply(right_align)


def section_gap():
    """Add consistent vertical spacing between sections within a tab."""
    st.markdown("<div style='height: 2rem'></div>", unsafe_allow_html=True)
