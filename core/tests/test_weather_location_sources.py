import asyncio
import json
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest

from jarvis_core.config import CoreSettings
from jarvis_core.integrations.weather import OpenMeteoForecast
from jarvis_core.intents import route_direct_intent
from jarvis_core.services import JarvisServices
from jarvis_core.tools import Tool


def test_weather_has_priority_over_explicit_web_search() -> None:
    intent = route_direct_intent(
        "¿Podrías buscar qué clima va a ser mañana en la ubicación en la que estoy yo ahora?",
        date(2026, 9, 20),
    )
    assert intent is not None
    assert intent.kind == "weather_forecast" and intent.tool == "weather_forecast"
    assert intent.arguments == {"scope": "tomorrow"}


@pytest.mark.asyncio
async def test_open_meteo_tomorrow_uses_daily_forecast_and_no_tavily(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.open-meteo.com"
        assert "temperature_2m_max" in request.url.params["daily"]
        return httpx.Response(200, json={
            "timezone": "Europe/Madrid",
            "current": {"temperature_2m": 22, "apparent_temperature": 21, "weather_code": 1, "precipitation": 0, "wind_speed_10m": 8},
            "daily": {
                "time": ["2026-09-20", "2026-09-21"],
                "weather_code": [1, 61], "temperature_2m_max": [26, 23], "temperature_2m_min": [15, 14],
                "precipitation_sum": [0, 4.2], "precipitation_probability_max": [5, 70],
                "wind_speed_10m_max": [18, 25],
            },
        })

    services = JarvisServices(CoreSettings(data_dir=tmp_path, tool_modules=""))
    forecast = OpenMeteoForecast(transport=httpx.MockTransport(handler))
    services.tools.register(Tool(
        "weather_forecast", "weather", {"type": "object", "properties": {
            "latitude": {"type": "number"}, "longitude": {"type": "number"}, "scope": {"type": "string"},
        }, "required": ["latitude", "longitude", "scope"]}, forecast.forecast,
    ))
    web_calls = 0

    async def web_search(_arguments: dict[str, Any]) -> dict[str, Any]:
        nonlocal web_calls
        web_calls += 1
        return {"available": True, "results": []}

    services.tools.register(Tool("web_search", "web", {"type": "object"}, web_search))
    result = await services.chat_stream({
        "message": "qué clima va a hacer mañana donde estoy", "latitude": 40.4, "longitude": -3.7,
        "conversation_id": "weather", "turn_id": "weather-1",
    }, lambda _chunk: asyncio.sleep(0))
    assert web_calls == 0
    assert "Mañana" in result["message"] and "70 %" in result["message"] and "23 °C" in result["message"]


@pytest.mark.asyncio
async def test_weather_without_coordinates_fails_closed(tmp_path: Path) -> None:
    services = JarvisServices(CoreSettings(data_dir=tmp_path, tool_modules=""))
    result = await services.chat_stream({
        "message": "qué tiempo hará mañana donde estoy", "turn_id": "weather-no-location",
    }, lambda _chunk: asyncio.sleep(0))
    assert result["message"] == "Necesito permiso de ubicación para responder a eso, señor."


@pytest.mark.asyncio
async def test_location_uses_reverse_geocoding_result(tmp_path: Path) -> None:
    services = JarvisServices(CoreSettings(data_dir=tmp_path, tool_modules=""))

    async def reverse(_latitude: float, _longitude: float) -> str:
        return "Madrid, Comunidad de Madrid, España"

    services._reverse_location = reverse  # type: ignore[method-assign]
    result = await services.chat_stream({
        "message": "¿dónde estoy?", "latitude": 40.4, "longitude": -3.7, "turn_id": "location-1",
    }, lambda _chunk: asyncio.sleep(0))
    assert "Madrid, Comunidad de Madrid, España" in result["message"]


@pytest.mark.asyncio
async def test_sources_are_stored_not_appended_and_second_can_open(tmp_path: Path) -> None:
    services = JarvisServices(CoreSettings(data_dir=tmp_path, tool_modules=""))
    calls = 0
    opened: list[str] = []

    async def search(arguments: dict[str, Any]) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        suffix = "a" if calls == 1 else "b"
        return {"available": True, "results": [
            {"title": f"Fuente {suffix}1", "url": f"https://example.com/{suffix}1", "content": "Dato técnico.", "domain": "example.com"},
            {"title": f"Fuente {suffix}2", "url": f"https://wikipedia.org/{suffix}2", "content": "Otro dato.", "domain": "wikipedia.org"},
        ]}

    async def open_url(arguments: dict[str, Any]) -> dict[str, Any]:
        opened.append(arguments["url"])
        return {"opened": True, "verified": True}

    async def synthesis(_messages, _context):
        yield "Respuesta contrastada y breve."

    services.tools.register(Tool("web_search", "search", {"type": "object"}, search))
    services.tools.register(Tool("pc_open_url", "open", {"type": "object"}, open_url))
    services.ollama.chat_stream = synthesis
    result = await services.chat_stream({
        "message": "investiga a fondo el MG90S", "conversation_id": "sources", "turn_id": "sources-1",
    }, lambda _chunk: asyncio.sleep(0))
    assert calls == 2
    assert result["message"] == "Respuesta contrastada y breve."
    assert "Fuentes consultadas" not in result["message"]
    await services.chat_stream({
        "message": "abre la segunda fuente", "conversation_id": "sources", "turn_id": "sources-2",
    }, lambda _chunk: asyncio.sleep(0))
    assert opened == ["https://wikipedia.org/a2"]
