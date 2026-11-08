"""Score your output.json locally. `make evaluate` runs this.

There is no scoring service. Everything you need to measure yourself is in
this repo, and this script is the same arithmetic we will run when we grade
you -- the only difference is the size of the reference set.

Two kinds of number come out of it, and the difference matters:

  EXACT       completeness, alignment completeness, run budget. Computed over
              all the clips, from your own output. These are the same numbers
              we will get.

  ESTIMATED   accuracy, over the 20 clips in data/dev_references.json and
              data/dev_alignments.json. We grade accuracy over all of them, so
              treat these as a signal, not a score. A 20-clip sample typically
              lands within about a third of the true value -- good enough to
              catch a broken pipeline, not good enough to tune against.

You are welcome to read, copy or replace this file. It is here so you have a
feedback loop on day one, not to constrain how you build one.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import sys

OUTPUT = pathlib.Path("output.json")
RUN_META = pathlib.Path("run_meta.json")
CLIPS_DIR = pathlib.Path("data/clips")
CHUNKS = pathlib.Path("chunks.json")
DEV_REFERENCES = pathlib.Path("data/dev_references.json")
DEV_ALIGNMENTS = pathlib.Path("data/dev_alignments.json")

#: A word onset counts as correct within this many seconds of the reference.
ONSET_TOLERANCE_S = 0.3

_BRACKETED = re.compile(r"[\[\(<][^\]\)>]*[\]\)>]")
_PUNCT = re.compile(r"[^\w']+")


def die(message: str) -> None:
    sys.exit(f"evaluate: {message}")


def load_json(path: pathlib.Path, hint: str):
    if not path.exists():
        die(f"{path} not found -- {hint}")
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        die(f"{path} is not valid JSON: {exc}")


def normalize(text: str) -> str:
    """Same normalisation we score with: Whisper's English normaliser, plus
    stripping `[bracketed]` audio events from the reference side."""
    from whisper_normalizer.english import EnglishTextNormalizer

    if not text:
        return ""
    return " ".join(EnglishTextNormalizer()(_BRACKETED.sub(" ", text)).split())


# ---------------------------------------------------------------------------
# shape checks -- these catch the mistakes that cost the most
# ---------------------------------------------------------------------------


def check_shape(results: dict, clip_ids: set[str]) -> list[str]:
    problems = []
    if not isinstance(results, dict):
        die("output.json must be a JSON object keyed by clip id")

    missing = clip_ids - set(results)
    unknown = set(results) - clip_ids
    if missing:
        problems.append(
            f"{len(missing)} clips missing from output.json, e.g. "
            f"{sorted(missing)[:3]}"
        )
    if unknown:
        problems.append(
            f"{len(unknown)} key{'' if len(unknown) == 1 else 's'} "
            f"{'is' if len(unknown) == 1 else 'are'} not a clip id, e.g. "
            f"{sorted(unknown)[:3]}"
        )

    bad_status = bad_align = 0
    for entry in results.values():
        if not isinstance(entry, dict):
            bad_status += 1
            continue
        if str(entry.get("status", "")).lower() not in {"ok", "failed"}:
            bad_status += 1
        alignment = entry.get("alignment")
        if alignment is not None and not isinstance(alignment, list):
            bad_align += 1
    if bad_status:
        problems.append(
            f'{bad_status} entr{"y has" if bad_status == 1 else "ies have"} a '
            'status that is not "ok" or "failed"'
        )
    if bad_align:
        problems.append(
            f"{bad_align} entr{'y has' if bad_align == 1 else 'ies have'} an "
            "alignment that is not a list"
        )
    return problems


# ---------------------------------------------------------------------------
# accuracy, over the dev clips only
# ---------------------------------------------------------------------------


def dev_wer(results: dict, references: dict) -> tuple[float | None, int]:
    import jiwer

    refs, hyps = [], []
    for clip_id, reference in references.items():
        entry = results.get(clip_id)
        if not isinstance(entry, dict) or str(entry.get("status", "")).lower() != "ok":
            continue
        r = normalize(reference)
        if not r.strip():
            continue
        refs.append(r)
        hyps.append(normalize(entry.get("text") or ""))
    if not refs:
        return None, 0
    return jiwer.wer(refs, hyps), len(refs)


def onset_accuracy(results: dict, dev_alignments: dict) -> tuple[float | None, int]:
    """Fraction of reference word onsets placed within the tolerance.

    Scored against the reference length, so padding an alignment with extra
    words cannot inflate it and dropping words cannot hide the loss.
    """
    from difflib import SequenceMatcher

    hits = total = 0
    for clip_id, truth in dev_alignments.items():
        entry = results.get(clip_id)
        total += len(truth)
        if not isinstance(entry, dict):
            continue
        submitted = entry.get("alignment")
        if not isinstance(submitted, list) or not submitted:
            continue

        ref_keys = [_PUNCT.sub("", w["word"].lower()) for w in truth]
        sub = [w for w in submitted if isinstance(w, dict)]
        sub_keys = [_PUNCT.sub("", str(w.get("word", "")).lower()) for w in sub]

        matcher = SequenceMatcher(a=sub_keys, b=ref_keys, autojunk=False)
        for i, j, n in matcher.get_matching_blocks():
            for k in range(n):
                try:
                    start = float(sub[i + k].get("start"))
                except (TypeError, ValueError):
                    continue
                if abs(start - float(truth[j + k]["start"])) <= ONSET_TOLERANCE_S:
                    hits += 1
    if not total:
        return None, 0
    return hits / total, total


def report_chunks() -> None:
    """Sanity-check chunks.json if the bonus was attempted.

    Not scored, and not compared against any reference -- there is no single
    right segmentation. These are self-consistency checks: chunks in order, not
    overlapping, and actually carrying text.
    """
    if not CHUNKS.exists():
        return
    try:
        chunks = json.loads(CHUNKS.read_text())
    except json.JSONDecodeError as exc:
        print(f"\nBONUS -- chunks.json is not valid JSON: {exc}")
        return
    if not isinstance(chunks, dict):
        print("\nBONUS -- chunks.json should be an object keyed by clip id")
        return

    spans, empty, overlaps, backwards = [], 0, 0, 0
    for rows in chunks.values():
        if not isinstance(rows, list):
            continue
        last_end = None
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                start, end = float(row.get("start")), float(row.get("end"))
            except (TypeError, ValueError):
                continue
            if end <= start:
                backwards += 1
                continue
            spans.append(end - start)
            if not str(row.get("text", "")).strip():
                empty += 1
            if last_end is not None and start < last_end - 1e-6:
                overlaps += 1
            last_end = end

    n_clips = sum(1 for v in chunks.values() if isinstance(v, list) and v)
    print(f"\nBONUS -- chunks.json, not scored")
    if not spans:
        print("  no usable chunks found")
        return
    spans.sort()
    print(f"  {len(spans)} chunks over {n_clips} clips   "
          f"({len(spans) / n_clips:.1f} per clip)")
    print(f"  duration  median {spans[len(spans) // 2]:.1f}s  "
          f"min {spans[0]:.1f}s  max {spans[-1]:.1f}s  "
          f"total {sum(spans) / 60:.1f} min")
    for label, count in (("with empty text", empty),
                         ("overlapping the previous chunk", overlaps),
                         ("where end <= start", backwards)):
        if count:
            print(f"  {count} chunk{'' if count == 1 else 's'} {label}")


# ---------------------------------------------------------------------------


def main() -> None:
    results = load_json(OUTPUT, "run 'make run' first")
    if isinstance(results, dict) and "results" in results:
        results = results["results"]
    references = load_json(DEV_REFERENCES, "it ships with this repo")
    dev_alignments = load_json(DEV_ALIGNMENTS, "it ships with this repo")

    clip_ids = {p.stem for p in CLIPS_DIR.glob("clip_*.wav")}
    if not clip_ids:
        die(f"no clips in {CLIPS_DIR} -- run 'make setup'")
    total_clips = len(clip_ids)

    problems = check_shape(results, clip_ids)

    n_ok = sum(
        1
        for e in results.values()
        if isinstance(e, dict) and str(e.get("status", "")).lower() == "ok"
    )
    n_aligned = sum(
        1
        for e in results.values()
        if isinstance(e, dict)
        and str(e.get("status", "")).lower() == "ok"
        and isinstance(e.get("alignment"), list)
        and e["alignment"]
    )

    budget = float(os.environ.get("RUN_BUDGET_SECONDS", 0) or 0)
    run_seconds = None
    if RUN_META.exists():
        try:
            run_seconds = float(json.loads(RUN_META.read_text())["run_seconds"])
        except (KeyError, ValueError, json.JSONDecodeError):
            pass

    wer, n_wer = dev_wer(results, references)
    onset, n_onset = onset_accuracy(results, dev_alignments)

    print()
    print("EXACT -- all clips, and what we will measure too")
    print(f"  completeness             {n_ok / total_clips:.4f}   ({n_ok}/{total_clips} marked ok)")
    print(f"  alignment_completeness   {n_aligned / total_clips:.4f}   ({n_aligned}/{total_clips} with an alignment)")
    if run_seconds is None:
        print("  run budget               no run_meta.json -- run 'make run'")
    elif budget:
        verdict = "OK" if run_seconds <= budget else "OVER BUDGET"
        print(f"  run budget               {run_seconds:.0f}s of {budget:.0f}s   {verdict}")
    else:
        print(f"  run budget               {run_seconds:.0f}s (RUN_BUDGET_SECONDS unset)")

    print()
    print(f"ESTIMATED -- {len(references)} dev clips only, not your grade")
    if wer is None:
        print("  wer                      no scoreable dev clips marked ok")
    else:
        print(f"  wer                      {wer:.4f}   (over {n_wer} clips)")
    if onset is None:
        print("  alignment onset accuracy no dev alignments to compare")
    else:
        print(f"  alignment onset accuracy {onset:.4f}   (within {ONSET_TOLERANCE_S}s, over {n_onset} words)")

    report_chunks()

    if problems:
        print()
        print("PROBLEMS WITH output.json")
        for p in problems:
            print(f"  - {p}")

    print()
    if problems:
        sys.exit(1)


if __name__ == "__main__":
    main()
