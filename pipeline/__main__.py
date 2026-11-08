"""Transcribe and align every clip concurrently. Run with `make run`."""

from __future__ import annotations

import asyncio
import json
import math
import os
import random
import tempfile
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
CLIPS_DIR = ROOT_DIR / "data/clips"
OUTPUT_PATH = ROOT_DIR / "output.json"
# WORDS_PER_CHUNK = 10
CONCURRENCY = 4
REQUEST_TIMEOUT_SECONDS = 60
MAX_REQUEST_RETRIES = 5
MAX_EMPTY_RETRIES = 3
DEFAULT_RUN_BUDGET_SECONDS = 900
OUTPUT_RESERVE_SECONDS = 1


class EmptyResponseError(ValueError):
    """The request succeeded but returned no usable transcript or alignment."""


def validate_word_timing(word: object) -> None:
    """Validate fields while preserving the server's timing and rounding values."""
    if not isinstance(word, dict):
        raise ValueError("each alignment word must be an object")
    text = word.get("word")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("each alignment word must contain nonempty text")
    start, end = word.get("start"), word.get("end")
    if any(
        type(value) not in (int, float) or not math.isfinite(value)
        for value in (start, end)
    ):
        raise ValueError("word timings must be finite numbers")


def parse_payload(response: httpx.Response, endpoint: str) -> dict:
    """Validate a successful response before accepting it as a clip result."""
    if not response.content.strip():
        raise EmptyResponseError("empty response body")
    payload = response.json()
    if (
        payload is None
        or payload == []
        or (isinstance(payload, str) and not payload.strip())
    ):
        raise EmptyResponseError("empty JSON response")
    if not isinstance(payload, dict):
        raise ValueError(f"{endpoint} did not return a JSON object")

    field, expected_type = (
        ("text", str) if endpoint == "/transcribe" else ("words", list)
    )
    value = payload.get(field)
    if value is None:
        raise EmptyResponseError(f"response is missing '{field}' content")
    if not isinstance(value, expected_type):
        raise ValueError(f"response '{field}' must be a {expected_type.__name__}")
    if not (value.strip() if isinstance(value, str) else value):
        raise EmptyResponseError(f"response has empty '{field}' content")
    if endpoint == "/align":
        for word in value:
            validate_word_timing(word)
    return payload


async def post_audio(
    client: httpx.AsyncClient,
    endpoint: str,
    path: Path,
    transcript: str | None = None,
) -> dict:
    """Use separate retry limits for empty content and HTTP/transport errors."""
    request_retries = 0
    empty_retries = 0
    while True:
        try:
            with path.open("rb") as audio:
                response = await client.post(
                    endpoint,
                    files={"file": (path.name, audio, "audio/wav")},
                    data={"transcript": transcript} if transcript is not None else None,
                )
            response.raise_for_status()
            return parse_payload(response, endpoint)
        except EmptyResponseError as exc:
            if empty_retries >= MAX_EMPTY_RETRIES:
                raise EmptyResponseError(
                    f"{exc} after {MAX_EMPTY_RETRIES} retries"
                ) from exc
            delay = 2**empty_retries
            empty_retries += 1
        except (httpx.HTTPStatusError, httpx.TransportError) as exc:
            if isinstance(exc, httpx.HTTPStatusError):
                status = exc.response.status_code
                if status != 429 and not 500 <= status < 600:
                    raise
            if request_retries >= MAX_REQUEST_RETRIES:
                raise
            delay = 2**request_retries
            request_retries += 1
            if isinstance(exc, httpx.HTTPStatusError):
                try:
                    retry_after = float(exc.response.headers.get("Retry-After", "0"))
                    if math.isfinite(retry_after):
                        delay = max(delay, retry_after)
                except ValueError:
                    pass
        # Stagger retries so rate-limited workers do not all retry together.
        await asyncio.sleep(delay + random.uniform(0, 0.5))


async def process_clip(
    client: httpx.AsyncClient, path: Path, *, result: dict | None = None
) -> dict:
    """Update the shared result after each stage, preserving text on cancellation."""
    if result is None:
        result = {"text": "", "status": "failed"}
    endpoint = "/transcribe"
    try:
        transcription = await post_audio(client, endpoint, path)
        text = transcription["text"]
        result["text"] = text

        endpoint = "/align"
        alignment = await post_audio(client, endpoint, path, transcript=text)
        result.update(status="ok", alignment=alignment["words"])
        result.pop("note", None)
    except (httpx.HTTPError, OSError, ValueError) as exc:
        result["note"] = f"{endpoint}: {type(exc).__name__}: {exc}"
    return result


async def run_pipeline(
    paths: list[Path],
    client: httpx.AsyncClient,
    *,
    concurrency: int = CONCURRENCY,
    budget_seconds: float = DEFAULT_RUN_BUDGET_SECONDS,
) -> dict:
    """Bound active clips and retain completed results when the budget expires."""
    if concurrency < 1:
        raise ValueError("concurrency must be positive")
    if not math.isfinite(budget_seconds) or budget_seconds <= 0:
        raise ValueError("budget_seconds must be positive and finite")
    semaphore = asyncio.Semaphore(concurrency)
    results = {
        path.stem: {"text": "", "status": "failed", "note": "run budget exceeded"}
        for path in paths
    }
    completed = 0

    async def worker(path: Path) -> None:
        nonlocal completed
        async with semaphore:
            await process_clip(client, path, result=results[path.stem])
            completed += 1
            if completed % 10 == 0 or completed == len(paths):
                print(f"processed {completed}/{len(paths)} clips", flush=True)

    try:
        await asyncio.wait_for(
            asyncio.gather(*(worker(path) for path in paths)),
            timeout=budget_seconds,
        )
    except asyncio.TimeoutError:
        pass  # Unfinished clips already have failure entries in the output.
    return results


# def chunk_words(words: list[dict]) -> list[dict]:
#     """Group words by tens with shared midpoints and the last word's final end.
#
#     Preserve supplied timings even when repeated timestamps give zero duration.
#     """
#     chunks = []
#     for offset in range(0, len(words), WORDS_PER_CHUNK):
#         group = words[offset : offset + WORDS_PER_CHUNK]
#         next_offset = offset + len(group)
#         end = group[-1]["end"]
#         if next_offset < len(words):
#             end = (end + words[next_offset]["start"]) / 2
#         chunks.append({
#             "start": chunks[-1]["end"] if chunks else group[0]["start"],
#             "end": end,
#             "text": " ".join(word["word"] for word in group),
#         })
#     return chunks


def write_results(results: dict, path: Path) -> None:
    """Replace the output only after a complete JSON file has been written."""
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary_path = Path(output.name)
            json.dump(results, output, indent=2, allow_nan=False)
            output.write("\n")
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


async def run(base_url: str, api_key: str, budget_seconds: float) -> dict:
    paths = sorted(CLIPS_DIR.glob("clip_*.wav"))
    if not paths:
        raise SystemExit(f"No clips found in {CLIPS_DIR}; run 'make setup' first.")
    async with httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=REQUEST_TIMEOUT_SECONDS,
        limits=httpx.Limits(max_connections=CONCURRENCY),
    ) as client:
        return await run_pipeline(paths, client, budget_seconds=budget_seconds)


def main() -> None:
    load_dotenv(ROOT_DIR / ".env")
    base_url = os.environ.get("ASR_BASE_URL", "").strip()
    api_key = os.environ.get("ASR_API_KEY", "").strip()
    if not base_url or not api_key or api_key == "paste-your-key-here":
        raise SystemExit("Set ASR_BASE_URL and ASR_API_KEY in .env before running.")
    try:
        budget_seconds = float(
            os.environ.get("RUN_BUDGET_SECONDS", DEFAULT_RUN_BUDGET_SECONDS)
        )
        if not math.isfinite(budget_seconds) or budget_seconds <= 0:
            raise ValueError
    except ValueError:
        raise SystemExit(
            "RUN_BUDGET_SECONDS must be a positive, finite number."
        ) from None
    # Leave time for client cleanup and writing output before make run finishes.
    reserve_seconds = min(OUTPUT_RESERVE_SECONDS, budget_seconds * 0.1)
    results = asyncio.run(run(base_url, api_key, budget_seconds - reserve_seconds))
    write_results(results, OUTPUT_PATH)
    # chunks = {
    #     clip_id: chunk_words(result.get("alignment", []))
    #     if result["status"] == "ok" else []
    #     for clip_id, result in results.items()
    # }
    # chunks_path = OUTPUT_PATH.with_name("chunks.json")
    # write_results(chunks, chunks_path)
    succeeded = sum(result["status"] == "ok" for result in results.values())
    print(f"wrote {len(results)} results to {OUTPUT_PATH} ({succeeded} succeeded)")
    # print(f"wrote {sum(len(rows) for rows in chunks.values())} chunks to {chunks_path}")


if __name__ == "__main__":
    main()
