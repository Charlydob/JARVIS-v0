import os
from typing import Any
from urllib.parse import urlsplit

from jarvis_core.tools import Tool, ToolRegistry


async def open_url(arguments: dict[str, Any]) -> dict[str, Any]:
    url = str(arguments.get("url") or "").strip()
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        return {"opened": False, "verified": False, "message": "Solo puedo abrir una URL http/https válida."}
    if os.name != "nt" or not hasattr(os, "startfile"):
        return {"opened": False, "verified": False, "message": "Esta acción local solo está disponible en Windows."}
    os.startfile(url)  # type: ignore[attr-defined]
    return {"opened": True, "verified": True, "url": url, "title": str(arguments.get("title") or "")}


def register_tools(registry: ToolRegistry) -> None:
    registry.register(Tool(
        "pc_open_url",
        "Abre una URL http/https concreta en el navegador predeterminado de Windows; no ejecuta comandos.",
        {"type": "object", "properties": {
            "url": {"type": "string"}, "title": {"type": "string"},
        }, "required": ["url"]},
        open_url,
    ))
