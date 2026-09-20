import logging
from typing import Any

import httpx

from jarvis_core.tools import Tool, ToolRegistry


LOGGER = logging.getLogger("jarvis-core.weather")


class OpenMeteoForecast:
    endpoint = "https://api.open-meteo.com/v1/forecast"

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.transport = transport

    async def forecast(self, arguments: dict[str, Any]) -> dict[str, Any]:
        latitude = float(arguments["latitude"])
        longitude = float(arguments["longitude"])
        scope = str(arguments.get("scope") or "current")
        period = str(arguments.get("period") or "")
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,apparent_temperature,weather_code,precipitation,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,wind_speed_10m_max",
            "hourly": "weather_code,temperature_2m,precipitation,precipitation_probability,wind_speed_10m",
            "timezone": "auto",
            "forecast_days": 7,
        }
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(12.0, connect=5.0), transport=self.transport,
            ) as client:
                response = await client.get(self.endpoint, params=params)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, TypeError, ValueError) as exc:
            LOGGER.warning("event=weather_failure provider=open-meteo error_type=%s", type(exc).__name__)
            return {
                "available": False,
                "provider": "open-meteo",
                "error": "provider_unavailable",
                "message": "La previsión meteorológica no está disponible ahora mismo, señor.",
            }

        daily = data.get("daily") if isinstance(data.get("daily"), dict) else {}
        times = daily.get("time") or []
        days = []
        fields = (
            "weather_code", "temperature_2m_max", "temperature_2m_min",
            "precipitation_sum", "precipitation_probability_max", "wind_speed_10m_max",
        )
        for index, day in enumerate(times):
            item: dict[str, Any] = {"date": day}
            for field in fields:
                values = daily.get(field) or []
                item[field] = values[index] if index < len(values) else None
            days.append(item)

        if scope == "tomorrow":
            selected_days = days[1:2]
        elif scope == "week":
            selected_days = days[:7]
        elif scope == "today":
            selected_days = days[:1]
        else:
            selected_days = []
        selected_hours: list[dict[str, Any]] = []
        if period == "afternoon" and times:
            hourly = data.get("hourly") if isinstance(data.get("hourly"), dict) else {}
            hourly_times = hourly.get("time") or []
            for index, timestamp in enumerate(hourly_times):
                if not str(timestamp).startswith(f"{times[0]}T"):
                    continue
                try:
                    hour = int(str(timestamp).split("T", 1)[1].split(":", 1)[0])
                except (IndexError, ValueError):
                    continue
                if 12 <= hour < 20:
                    selected_hours.append({
                        "time": timestamp,
                        **{
                            field: (hourly.get(field) or [])[index]
                            if index < len(hourly.get(field) or []) else None
                            for field in (
                                "weather_code", "temperature_2m", "precipitation",
                                "precipitation_probability", "wind_speed_10m",
                            )
                        },
                    })
        return {
            "available": True,
            "provider": "open-meteo",
            "scope": scope,
            "period": period or None,
            "timezone": data.get("timezone"),
            "current": data.get("current") or {},
            "days": selected_days,
            "hours": selected_hours,
            "count": len(selected_days) if selected_days else 1,
        }


def register_tools(registry: ToolRegistry) -> None:
    forecast = OpenMeteoForecast()
    registry.register(Tool(
        "weather_forecast",
        "Obtiene el tiempo actual o la previsión de Open-Meteo para coordenadas del dispositivo.",
        {"type": "object", "properties": {
            "latitude": {"type": "number"},
            "longitude": {"type": "number"},
            "scope": {"type": "string", "enum": ["current", "today", "tomorrow", "week"]},
            "period": {"type": "string", "enum": ["afternoon"]},
        }, "required": ["latitude", "longitude", "scope"]},
        forecast.forecast,
    ))
