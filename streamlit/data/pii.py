"""PII masking utilities for Northern Sauna Analytics.

Provides functions to mask personally identifiable information (PII) in
DataFrames before display or transmission to external services.
"""

from __future__ import annotations

import hashlib

import pandas as pd

# Maps column names → PII type for both raw BigQuery columns and
# transformed page-layer column names (see data/queries.py for mapping).
PII_COLUMNS: dict[str, str] = {
    # Raw BigQuery column names (Ask the Data SQL results)
    "customer_email": "email",
    "customer_name": "name",
    "customer_phone": "phone",
    "raw_data": "redact",
    # Transformed page-layer column names (df1/df2 display)
    "Email address": "email",
    "First name": "first_name",
    "Last name": "last_name",
    "Phone": "phone",
}


def mask_email(email: str | None) -> str:
    """Mask email: j*****@example.com (max 5 stars)."""
    if not email or "@" not in str(email):
        return str(email) if email else ""
    local, domain = str(email).rsplit("@", 1)
    if len(local) <= 1:
        return f"*@{domain}"
    return f"{local[0]}{'*' * min(len(local) - 1, 5)}@{domain}"


def mask_name(name: str | None) -> str:
    """Mask name: John D. (first name + last initial)."""
    if not name:
        return ""
    parts = str(name).split()
    if len(parts) >= 2:
        return f"{parts[0]} {parts[-1][0]}."
    return str(name)


def mask_first_name(name: str | None) -> str:
    """Mask first name: J*** (first letter + stars)."""
    if not name:
        return ""
    s = str(name)
    if len(s) <= 1:
        return s
    return f"{s[0]}{'*' * min(len(s) - 1, 3)}"


def mask_last_name(name: str | None) -> str:
    """Mask last name: D. (initial + period)."""
    if not name:
        return ""
    return f"{str(name)[0]}."


def mask_phone(phone: str | None) -> str:
    """Mask phone: ********5678 (show last 4 digits)."""
    if not phone:
        return ""
    s = str(phone)
    if len(s) < 4:
        return s
    return f"{'*' * (len(s) - 4)}{s[-4:]}"


def hash_for_dedup(value: str) -> str:
    """Deterministic 12-char hex hash for deduplication without exposing PII."""
    return hashlib.sha256(value.lower().strip().encode()).hexdigest()[:12]


def mask_rows(rows: list[dict]) -> list[dict]:
    """Mask PII in query result rows (list[dict] format).

    Used by the orchestrator to mask PII before sending rows to the LLM.
    Uses PII_COLUMNS for column name matching with case-insensitive lookup.
    """
    pii_lower = {k.lower(): v for k, v in PII_COLUMNS.items()}
    maskers = {
        "email": mask_email,
        "name": mask_name,
        "first_name": mask_first_name,
        "last_name": mask_last_name,
        "phone": mask_phone,
        "redact": lambda _: "[REDACTED]",
    }
    masked = []
    for row in rows:
        clean = {}
        for k, v in row.items():
            pii_type = pii_lower.get(k.lower())
            if pii_type and v is not None:
                masker_fn = maskers.get(pii_type, lambda _: "[REDACTED]")
                clean[k] = masker_fn(v)
            else:
                clean[k] = v
        masked.append(clean)
    return masked


def mask_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of df with all recognized PII columns masked."""
    df = df.copy()
    maskers = {
        "email": mask_email,
        "name": mask_name,
        "first_name": mask_first_name,
        "last_name": mask_last_name,
        "phone": mask_phone,
        "redact": lambda _: "[REDACTED]",
    }
    for col, pii_type in PII_COLUMNS.items():
        if col in df.columns:
            fn = maskers.get(pii_type, lambda _: "[REDACTED]")
            df[col] = df[col].apply(
                lambda v, m=fn: m(v) if not pd.isna(v) else ""
            )
    return df
