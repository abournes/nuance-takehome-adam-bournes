"""Transcribe and align every clip concurrently. Run with `make run`."""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import random

import httpx
from dotenv import load_dotenv

ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent
CLIPS_DIR = ROOT_DIR / "data/clips"
OUTPUT_PATH = ROOT_DIR / "output.json"
CONCURRENCY = 4
REQUEST_TIMEOUT_SECONDS = 60
MAX_ATTEMPTS = 6


async def post_audio(
    client: httpx.AsyncClient,
    endpoint: str,
    path: pathlib.Path,
    transcript: str | None = None,
) -> dict:
    """Upload fresh audio on each attempt; retry only transient API failures."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        delay = 2 ** (attempt - 1)
        try:
            with path.open("rb") as audio:
                response = await client.post(
                    endpoint,
                    files={"file": (path.name, audio, "audio/wav")},
                    data={"transcript": transcript} if transcript is not None else None,
                )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError(f"{endpoint} did not return a JSON object")
            return payload
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if (status != 429 and not 500 <= status < 600) or attempt == MAX_ATTEMPTS:
                raise
            try:
                delay = max(delay, float(exc.response.headers.get("Retry-After", "0")))
            except ValueError:
                pass
        except httpx.TransportError:
            if attempt == MAX_ATTEMPTS:
                raise
        # Stagger retries so rate-limited workers do not all retry together.
        await asyncio.sleep(delay + random.uniform(0, 0.5))


async def process_clip(client: httpx.AsyncClient, path: pathlib.Path) -> dict:
    """Keep the per-clip stages sequential, preserving text if alignment fails."""
    result = {"text": "", "status": "failed"}
    endpoint = "/transcribe"
    try:
        transcription = await post_audio(client, endpoint, path)
        text = transcription.get("text")
        if not isinstance(text, str):
            raise ValueError("response is missing a string 'text' field")
        result["text"] = text

        endpoint = "/align"
        alignment = await post_audio(client, endpoint, path, transcript=text)
        words = alignment.get("words")
        if not isinstance(words, list):
            raise ValueError("response is missing a 'words' list")
        result.update(status="ok", alignment=words)
    except (httpx.HTTPError, OSError, ValueError) as exc:
        result["note"] = f"{endpoint}: {type(exc).__name__}: {exc}"
    return result


async def run_pipeline(
    paths: list[pathlib.Path],
    client: httpx.AsyncClient,
    *,
    concurrency: int = CONCURRENCY,
    budget_seconds: float = 900,
) -> dict:
    """Bound active clips and retain completed results when the budget expires."""
    if concurrency < 1 or budget_seconds <= 0:
        raise ValueError("concurrency and budget_seconds must be positive")
    semaphore = asyncio.Semaphore(concurrency)
    results = {
        path.stem: {"text": "", "status": "failed", "note": "run budget exceeded"}
        for path in paths
    }
    completed = 0

    async def worker(path: pathlib.Path) -> None:
        nonlocal completed
        async with semaphore:
            results[path.stem] = await process_clip(client, path)
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
    budget_seconds = float(os.environ.get("RUN_BUDGET_SECONDS", "900"))
    # Leave time for client cleanup and writing output before make run finishes.
    results = asyncio.run(run(base_url, api_key, max(0.1, budget_seconds - 1)))
    OUTPUT_PATH.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    succeeded = sum(result["status"] == "ok" for result in results.values())
    print(f"wrote {len(results)} results to {OUTPUT_PATH} ({succeeded} succeeded)")


if __name__ == "__main__":
    main()
