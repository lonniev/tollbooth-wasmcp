"""Open-Meteo weather API client.

Open-Meteo is a free, open-source weather API that requires no API key.
Rate limit: 10,000 calls/day (non-commercial).
Docs: https://open-meteo.com/en/docs
"""

from __future__ import annotations

import httpx

_BASE = "https://api.open-meteo.com/v1"
_ARCHIVE_BASE = "https://archive-api.open-meteo.com/v1"
_TIMEOUT = 15.0


async def get_current(lat: float, lon: float) -> dict:
    """Fetch current weather conditions for a latitude/longitude.

    Returns temperature, wind speed, wind direction, and weather code.
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{_BASE}/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current_weather": "true",
            },
        )
        resp.raise_for_status()
        data = resp.json()
    return {
        "success": True,
        "latitude": data.get("latitude"),
        "longitude": data.get("longitude"),
        "current_weather": data.get("current_weather"),
        "timezone": data.get("timezone"),
    }


async def get_forecast(lat: float, lon: float, days: int = 7) -> dict:
    """Fetch a multi-day weather forecast (1-16 days).

    Returns daily high/low temperatures, precipitation, and weather codes.
    """
    days = max(1, min(days, 16))
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{_BASE}/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode",
                "forecast_days": days,
                "timezone": "auto",
            },
        )
        resp.raise_for_status()
        data = resp.json()
    return {
        "success": True,
        "latitude": data.get("latitude"),
        "longitude": data.get("longitude"),
        "forecast_days": days,
        "daily": data.get("daily"),
        "daily_units": data.get("daily_units"),
        "timezone": data.get("timezone"),
    }


async def get_historical(
    lat: float, lon: float, start: str, end: str
) -> dict:
    """Fetch historical weather data for a date range.

    Args:
        lat: Latitude (-90 to 90).
        lon: Longitude (-180 to 180).
        start: Start date (YYYY-MM-DD).
        end: End date (YYYY-MM-DD).

    Returns daily temperature, precipitation, and weather codes.
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{_ARCHIVE_BASE}/archive",
            params={
                "latitude": lat,
                "longitude": lon,
                "start_date": start,
                "end_date": end,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode",
                "timezone": "auto",
            },
        )
        resp.raise_for_status()
        data = resp.json()
    return {
        "success": True,
        "latitude": data.get("latitude"),
        "longitude": data.get("longitude"),
        "start_date": start,
        "end_date": end,
        "daily": data.get("daily"),
        "daily_units": data.get("daily_units"),
        "timezone": data.get("timezone"),
    }
