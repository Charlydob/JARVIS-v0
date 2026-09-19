"""Run a repeatable 20-case Spanish STT/VAD WebM/Opus acceptance corpus."""

import argparse
import asyncio
import io
import json
import sys
import time
import unicodedata
from pathlib import Path

import av
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from jarvis_core.config import CoreSettings
from jarvis_core.services import SpeechToTextService, normalized_transcript


PHRASES = (
    "Qué recordatorios tengo mañana.",
    "Qué recordatorios tengo hoy.",
    "En qué página voy.",
    "Anota que voy por la página 222.",
    "Cuándo tiene Laura guardia.",
)


def canonical(value: str) -> str:
    plain = unicodedata.normalize("NFKD", normalized_transcript(value))
    return "".join(character for character in plain if not unicodedata.combining(character))


def silence_frame(milliseconds: int, rate: int = 48_000) -> av.AudioFrame:
    frame = av.AudioFrame(format="s16", layout="mono", samples=round(rate * milliseconds / 1000))
    frame.sample_rate = rate
    for plane in frame.planes:
        plane.update(bytes(plane.buffer_size))
    return frame


def audio_to_webm(raw: bytes, leading_silence_ms: int, trailing_silence_ms: int = 3000) -> bytes:
    source = av.open(io.BytesIO(raw), mode="r")
    resampler = av.AudioResampler(format="s16", layout="mono", rate=48_000)
    frames = [silence_frame(leading_silence_ms)] if leading_silence_ms else []
    for decoded in source.decode(audio=0):
        converted = resampler.resample(decoded)
        frames.extend(converted if isinstance(converted, list) else [converted])
    flushed = resampler.resample(None)
    if flushed:
        frames.extend(flushed if isinstance(flushed, list) else [flushed])
    frames.append(silence_frame(trailing_silence_ms))

    target = io.BytesIO()
    output = av.open(target, mode="w", format="webm")
    stream = output.add_stream("libopus", rate=48_000)
    stream.layout = "mono"
    for frame in frames:
        frame.pts = None
        for packet in stream.encode(frame):
            output.mux(packet)
    for packet in stream.encode(None):
        output.mux(packet)
    output.close()
    return target.getvalue()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--wav-dir", type=Path, required=True)
    args = parser.parse_args()
    load_dotenv(args.env_file, override=True)
    settings = CoreSettings()
    stt = SpeechToTextService(settings)
    results = []

    for phrase_index, phrase in enumerate(PHRASES):
        spoken = (args.wav_dir / f"phrase-{phrase_index}.wav").read_bytes()
        for leading_silence_ms in (0, 500, 1500, 3000):
            audio = audio_to_webm(spoken, leading_silence_ms)
            started = time.perf_counter()
            transcript, language, metadata = await stt.transcribe(audio, "audio/webm;codecs=opus")
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            expected = canonical(phrase)
            actual = canonical(transcript)
            results.append({
                "phrase": phrase,
                "leading_silence_ms": leading_silence_ms,
                "bytes": len(audio),
                "language": language,
                "transcript": transcript,
                "exact": actual == expected,
                "duration_ms": duration_ms,
                **metadata,
            })

    exact = sum(1 for item in results if item["exact"])
    print(json.dumps({"passed": exact, "total": len(results), "results": results}, ensure_ascii=False))
    if exact != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
