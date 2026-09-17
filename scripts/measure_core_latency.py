"""Small live benchmark for the local Core; uses a temporary conversation database."""

import argparse
import asyncio
import json
import logging
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--core-path", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--include-write", action="store_true")
    parser.add_argument("--scenario", choices=("normal", "books", "reminders", "write"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")
    load_dotenv(args.env_file, override=True)
    sys.path.insert(0, str(args.core_path.resolve()))

    from jarvis_core.config import CoreSettings
    from jarvis_core.services import JarvisServices

    prompts = {
        "normal": "¿Cómo estás? Responde en una frase.",
        "books": "¿Por qué página voy en el libro actual?",
        "reminders": "¿Qué recordatorios tengo hoy?",
    }
    if args.include_write or args.scenario == "write":
        prompts["write"] = "Recuérdame el 31 de diciembre de 2099 a las 23:57 que esto es una prueba temporal de JARVIS."
    if args.scenario:
        prompts = {args.scenario: prompts[args.scenario]}

    with tempfile.TemporaryDirectory(prefix="jarvis-latency-") as data_dir:
        services = JarvisServices(CoreSettings(data_dir=Path(data_dir)))
        results = []
        async def ignore(_chunk: str) -> None:
            return None
        await services.chat_stream(
            {"message": "Responde solo: listo", "conversation_id": f"warm-{uuid4()}"}, ignore
        )
        for scenario, message in prompts.items():
            started = time.perf_counter()
            first = None

            async def on_chunk(_chunk: str) -> None:
                nonlocal first
                if first is None:
                    first = time.perf_counter()

            response = await services.chat_stream(
                {"message": message, "conversation_id": f"bench-{uuid4()}"}, on_chunk
            )
            ended = time.perf_counter()
            results.append({
                "scenario": scenario,
                "ttft_ms": round(((first or ended) - started) * 1000, 1),
                "total_ms": round((ended - started) * 1000, 1),
                "language": response.get("language"),
                "answer": str(response.get("message", ""))[:160],
            })
        print(json.dumps(results, ensure_ascii=False))
        services.storage.close()


if __name__ == "__main__":
    asyncio.run(main())
