"""Isolated local Faster-Whisper benchmark; install dependencies in a separate venv.

Manifest JSONL fields: audio_path, expected_text, language, category.
This script never downloads/uploads corpus data and never changes production settings.
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Result:
    audio_path: str
    category: str
    text: str
    latency_s: float
    duration_s: float
    realtime_factor: float | None
    avg_logprob: float | None
    max_no_speech_prob: float | None
    max_compression_ratio: float | None


def gpu_snapshot() -> dict:
    try:
        output = subprocess.check_output([
            "nvidia-smi", "--query-gpu=memory.used,memory.free,utilization.gpu",
            "--format=csv,noheader,nounits",
        ], text=True, timeout=5).strip().split(",")
        return {"used_mib": int(output[0]), "free_mib": int(output[1]), "utilization": int(output[2])}
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return {"available": False}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), required=True)
    parser.add_argument("--compute-type", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-free-vram-mib", type=int, default=1200)
    args = parser.parse_args()

    before = gpu_snapshot()
    if args.device == "cuda" and before.get("free_mib", 0) < args.minimum_free_vram_mib:
        raise SystemExit(f"unsafe GPU headroom: {before}; unload Ollama or choose CPU")
    from faster_whisper import WhisperModel

    load_started = time.perf_counter()
    model = WhisperModel(args.model, device=args.device, compute_type=args.compute_type)
    load_s = time.perf_counter() - load_started
    rows = [json.loads(line) for line in args.manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
    results = []
    for row in rows:
        started = time.perf_counter()
        segments, info = model.transcribe(row["audio_path"], language=row.get("language") or None, vad_filter=True)
        decoded = list(segments)
        latency = time.perf_counter() - started
        duration = float(getattr(info, "duration", 0) or 0)
        results.append(Result(
            row["audio_path"], row.get("category", "unknown"),
            " ".join(item.text.strip() for item in decoded).strip(), latency, duration,
            latency / duration if duration else None,
            statistics.fmean(item.avg_logprob for item in decoded) if decoded else None,
            max((item.no_speech_prob for item in decoded), default=None),
            max((item.compression_ratio for item in decoded), default=None),
        ))
    latencies = sorted(item.latency_s for item in results)
    report = {
        "model": args.model, "device": args.device, "compute_type": args.compute_type,
        "load_time_s": load_s, "gpu_before": before, "gpu_after": gpu_snapshot(),
        "count": len(results),
        "median_latency_s": statistics.median(latencies) if latencies else None,
        "p95_latency_s": latencies[min(len(latencies) - 1, round(.95 * (len(latencies) - 1)))] if latencies else None,
        "items": [asdict(item) for item in results],
        "accuracy_note": "WER and semantic accuracy require expected_text and an explicit scorer; no accuracy is invented.",
    }
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
