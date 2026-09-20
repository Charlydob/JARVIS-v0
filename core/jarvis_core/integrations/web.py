import logging
from typing import Any

import httpx

from jarvis_core.config import CoreSettings
from jarvis_core.tools import Tool, ToolRegistry


LOGGER = logging.getLogger("jarvis-core.web")


class TavilySearch:
    endpoint = "https://api.tavily.com/search"

    def __init__(self, api_key: str, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.api_key = api_key
        self.transport = transport

    async def search(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("query") or "").strip()
        if not query:
            return {"available": True, "error": "invalid_query", "message": "Falta la consulta web."}
        max_results = max(1, min(10, int(arguments.get("max_results") or 5)))
        topic = str(arguments.get("topic") or "general")
        domains = [str(value) for value in arguments.get("include_domains") or []][:10]
        payload = {
            "query": query,
            "search_depth": "basic",
            "chunks_per_source": 2,
            "max_results": max_results,
            "topic": topic if topic in {"general", "news"} else "general",
            "include_answer": False,
            "include_raw_content": False,
            "include_published_date": True,
            "include_domains": domains,
        }
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(15.0, connect=5.0), transport=self.transport,
            ) as client:
                response = await client.post(
                    self.endpoint,
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else "network"
            LOGGER.warning(
                "event=web_search_failure provider=tavily status=%s error_type=%s",
                status, type(exc).__name__,
            )
            return {
                "available": False, "error": "provider_unavailable",
                "message": "La búsqueda web no está disponible ahora mismo, señor.",
            }
        results = []
        for item in data.get("results") or []:
            if not isinstance(item, dict) or not item.get("url"):
                continue
            results.append({
                "title": str(item.get("title") or item["url"])[:300],
                "url": str(item["url"]),
                "content": str(item.get("content") or "")[:1600],
                "score": item.get("score"),
                "published_date": item.get("published_date"),
            })
        return {
            "available": True, "provider": "tavily", "query": query,
            "results": results, "count": len(results), "response_time": data.get("response_time"),
        }


def register_tools(registry: ToolRegistry) -> None:
    settings = CoreSettings()
    if settings.web_search_provider.casefold() != "tavily" or not settings.tavily_api_key.strip():
        LOGGER.info("event=web_search_not_registered provider=%s configured=false", settings.web_search_provider)
        return
    search = TavilySearch(settings.tavily_api_key.strip())
    registry.register(Tool(
        "web_search",
        "Busca información real y actual en la web mediante Tavily y devuelve fuentes estructuradas.",
        {"type": "object", "properties": {
            "query": {"type": "string"},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
            "topic": {"type": "string", "enum": ["general", "news"]},
            "include_domains": {"type": "array", "items": {"type": "string"}},
        }, "required": ["query"]},
        search.search,
    ))
