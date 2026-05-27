"""Weather and location utility functions."""

import numpy as np
import pandas as pd
import requests

import streamlit as st


@st.cache_data
def get_temperature_data(start_date, end_date, latitude=52.37, longitude=4.89):
    """Fetch daily weather data (temperature, rain, snowfall) with fallback.

    Primary: Open-Meteo API (includes precipitation).
    Fallback: Meteostat library (temperature only, no API key needed).
    Default coordinates: Stockholm centre.
    """
    try:
        api_url = (
            f"https://archive-api.open-meteo.com/v1/archive"
            f"?latitude={latitude}&longitude={longitude}"
            f"&start_date={start_date.strftime('%Y-%m-%d')}"
            f"&end_date={end_date.strftime('%Y-%m-%d')}"
            f"&daily=temperature_2m_mean,rain_sum,snowfall_sum"
            f"&timezone=Europe%2FStockholm"
        )
        resp = requests.get(api_url, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        if "daily" in data:
            temp_df = pd.DataFrame({
                "date": pd.to_datetime(data["daily"]["time"]),
                "temperature": data["daily"].get("temperature_2m_mean"),
                "rain_sum": data["daily"].get("rain_sum"),
                "snowfall_sum": data["daily"].get("snowfall_sum"),
            })
            temp_df["_source"] = "open-meteo"
            return temp_df
    except Exception:
        pass

    try:
        from meteostat import Daily, Point

        location = Point(latitude, longitude)
        data = Daily(location, start_date, end_date)
        meteo_df = data.fetch()

        if meteo_df is not None and not meteo_df.empty and "tavg" in meteo_df.columns:
            meteo_df = meteo_df.reset_index()
            temp_df = pd.DataFrame({
                "date": pd.to_datetime(meteo_df["time"]),
                "temperature": meteo_df["tavg"],
            })
            temp_df["_source"] = "meteostat"
            temp_df = temp_df.dropna(subset=["temperature"])
            return temp_df
    except Exception:
        return None

    return None


def add_temperature_to_bookings(bookings_df):
    """Enrich bookings with daily weather data (temperature, rain, weather conditions).

    Merges weather on booking_date. Adds columns: temperature, temp_category,
    rain_category, weather_condition, has_rain_data.
    """
    if "booking_date" not in bookings_df.columns:
        return bookings_df

    start_date = bookings_df["booking_date"].min() - pd.Timedelta(days=1)
    end_date = bookings_df["booking_date"].max() + pd.Timedelta(days=1)

    if hasattr(start_date, "tzinfo") and start_date.tzinfo:
        start_date = start_date.tz_localize(None)
    if hasattr(end_date, "tzinfo") and end_date.tzinfo:
        end_date = end_date.tz_localize(None)

    today = pd.Timestamp.now().normalize()
    if end_date > today:
        end_date = today

    temp_df = get_temperature_data(start_date, end_date)
    if temp_df is None:
        return bookings_df

    bookings_with_temp = bookings_df.copy()
    bookings_with_temp["booking_date_only"] = bookings_with_temp["booking_date"].dt.date
    temp_df["date_only"] = temp_df["date"].dt.date

    merged = bookings_with_temp.merge(
        temp_df, left_on="booking_date_only", right_on="date_only", how="left"
    )
    merged = merged.drop(columns=["date", "date_only", "_source"], errors="ignore")

    merged["temp_category"] = pd.cut(
        merged["temperature"],
        bins=[-np.inf, 5, 10, 13, 16, 20, np.inf],
        labels=["Below 5°C", "5-10°C", "10-13°C", "13-16°C", "16-20°C", "Above 20°C"],
    )

    has_rain_data = (
        "rain_sum" in merged.columns
        and "snowfall_sum" in merged.columns
        and merged["rain_sum"].notna().any()
    )

    if has_rain_data:
        merged["rain_category"] = pd.cut(
            merged["rain_sum"].fillna(0),
            bins=[-0.01, 0, 5, 15, np.inf],
            labels=["Dry (0mm)", "Light (0.1-5mm)", "Moderate (5-15mm)", "Heavy (15+mm)"],
        )

        temp = merged["temperature"]
        rain = merged["rain_sum"].fillna(0)
        snow = merged["snowfall_sum"].fillna(0)
        has_temp = temp.notna()

        conditions = [
            has_temp & (snow >= 2),
            has_temp & (temp < 10) & (rain > 1),
            has_temp & (temp < 10) & (rain <= 1),
            has_temp & (temp >= 10) & (temp <= 18) & (rain > 1),
            has_temp & (temp >= 10) & (temp <= 18) & (rain <= 1),
            has_temp & (temp > 18),
        ]
        choices = ["Snow", "Cold & Rainy", "Cold & Dry", "Mild & Rainy", "Mild & Dry", "Warm"]
        merged["weather_condition"] = np.select(conditions, choices, default="")
        merged.loc[merged["weather_condition"] == "", "weather_condition"] = np.nan

        has_snow = (snow >= 2).any()
        condition_order = []
        if has_snow:
            condition_order.append("Snow")
        condition_order += ["Cold & Rainy", "Cold & Dry", "Mild & Rainy", "Mild & Dry", "Warm"]

        merged["weather_condition"] = pd.Categorical(
            merged["weather_condition"], categories=condition_order, ordered=True
        )

    merged["has_rain_data"] = has_rain_data
    return merged


def get_location_column(df):
    """Get the appropriate location column from a dataframe."""
    if df is None:
        return None

    if "Location" in df.columns:
        return "Location"
    elif "Activity" in df.columns:
        return "Activity"
    elif "Tour" in df.columns:
        return "Tour"
    return None


def get_available_locations(df, location_col=None):
    """Get sorted list of available locations from dataframe."""
    if df is None:
        return []

    if location_col is None:
        location_col = get_location_column(df)

    if location_col is None or location_col not in df.columns:
        return []

    locations = df[location_col].dropna().unique().tolist()
    return sorted(
        [loc for loc in locations if pd.notna(loc) and str(loc).lower().startswith("northern_sauna")]
    )
