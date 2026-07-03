"""Reference DPYC weather Operator on Spin/WASI — business logic only.

The Spin/WASI host is entirely `tollbooth-wasmcp` (`SpinOperatorHost`), so this
file is structurally identical to the FastMCP `tollbooth-sample` server: define
the domain tool identities, construct the host, decorate the domain tools, export.

Rule: `import tollbooth_wasmcp` FIRST — it installs the pre-init seams before the
tollbooth-dpyc wheel is imported.
"""

import tollbooth_wasmcp  # noqa: F401 — installs the pre-init seams (must precede the wheel)
from tollbooth_wasmcp import SpinOperatorHost

from tollbooth.tool_identity import ToolIdentity, capability_uuid

import weather

GET_CURRENT = "b7327eb8-92b4-5252-84e0-ba3f437a16ed"
GET_FORECAST = "b6d0e596-3aec-5a62-980b-7875aa04d079"
GET_HISTORICAL = "5608f3e9-44c4-5b28-9744-704af6d701f0"
_DOMAIN = {
    GET_CURRENT: ToolIdentity(tool_id=GET_CURRENT, capability="get_current_weather", category="read", intent="Get current weather conditions"),
    GET_FORECAST: ToolIdentity(tool_id=GET_FORECAST, capability="get_weather_forecast", category="write", intent="Get weather forecast"),
    GET_HISTORICAL: ToolIdentity(tool_id=GET_HISTORICAL, capability="get_historical_weather", category="heavy", intent="Get historical weather data"),
}

host = SpinOperatorHost(service_name="tollbooth-weather-wasm", slug="weather",
                        service_version="0.1.0", domain_tools=_DOMAIN)
tool = host.tool


@tool
@host.runtime.paid_tool(capability_uuid("get_current_weather"))
async def current(latitude: float, longitude: float, npub: str = "", dpop_token: str = "") -> dict:
    """Get current weather conditions for a location.

    Args:
        latitude: Latitude (-90 to 90).
        longitude: Longitude (-180 to 180).
        npub: Required. Your Nostr public key (npub1...) for credit billing.
        dpop_token: A kind-27235 Nostr event signed by npub for this tool.
    """
    return await weather.get_current(latitude, longitude)


@tool
@host.runtime.paid_tool(capability_uuid("get_weather_forecast"))
async def forecast(latitude: float, longitude: float, days: int = 7, npub: str = "", dpop_token: str = "") -> dict:
    """Get a multi-day weather forecast for a location.

    Args:
        latitude: Latitude (-90 to 90).
        longitude: Longitude (-180 to 180).
        days: Number of forecast days (1-16, default 7).
        npub: Required. Your Nostr public key (npub1...) for credit billing.
        dpop_token: A kind-27235 Nostr event signed by npub for this tool.
    """
    return await weather.get_forecast(latitude, longitude, days)


@tool
@host.runtime.paid_tool(capability_uuid("get_historical_weather"))
async def historical(latitude: float, longitude: float, start_date: str, end_date: str, npub: str = "", dpop_token: str = "") -> dict:
    """Get historical weather data for a location and date range.

    Args:
        latitude: Latitude (-90 to 90).
        longitude: Longitude (-180 to 180).
        start_date: Start date (YYYY-MM-DD).
        end_date: End date (YYYY-MM-DD).
        npub: Required. Your Nostr public key (npub1...) for credit billing.
        dpop_token: A kind-27235 Nostr event signed by npub for this tool.
    """
    return await weather.get_historical(latitude, longitude, start_date, end_date)


Tools = host.tools_export()
