# Transcription pipeline — the working environment

**The exercise itself is in the brief we sent you.** This file is reference for
the repo: how to set it up, what the service exposes, and what the tooling
reads. If the two ever disagree, the brief is right.

---

## Setup

```bash
make setup                # dependencies + the audio, ~250MB
make run                  # runs the skeleton, writes a placeholder output.json
make evaluate             # scores it, locally
```

Your `.env` came already filled in with your API key — there is nothing to
configure. If those three commands work, the whole loop works, and anything
that breaks later is yours to fix.

---

## The service

```
POST /transcribe    multipart audio file              ->  { "text": "..." }
POST /align         multipart audio file + transcript ->  { "words": [...] }
GET  /health
```

Base URL is in `.env.example`; your API key came by email. Both `/transcribe`
and `/align` need `Authorization: Bearer <ASR_API_KEY>`.

`/transcribe` takes one multipart field, `file`. `/align` takes two — `file`,
the audio, and `transcript`, the text to align — and returns word-level timings:

```json
{ "words": [ { "word": "okay", "start": 0.2, "end": 0.56 }, ... ] }
```

Times are seconds from the start of the clip.

> **Neither endpoint runs a model.** Both serve precomputed results, so
> transcription quality is fixed and there is nothing to tune on either side —
> no parameters to sweep, no aligner to improve. What the alignment timings are
> worth depends on the transcript you send with the audio, and that is the only
> lever you have.
>
> That is a statement about the *content* we serve. It is not a statement about
> how the service behaves.

There is no scoring endpoint. You measure yourself; see
[Measuring your run](#measuring-your-run) below.

---

## What's in the repo

```
data/clips/                142 call recordings (fetched by make setup)
data/dev_references.json   reference transcripts for 20 of them
data/dev_alignments.json   reference word timings for the same 20
scripts/evaluate.py        local scoring, run by make evaluate
pipeline/                  a runnable skeleton, yours to replace
Makefile                   make setup / make run / make evaluate / make clean
DECISIONS.md               template, please fill in
TRANSCRIPT.md              your agent session, if you used one
```

`data/dev_references.json` and `data/dev_alignments.json` are plain JSON
files sitting in `data/`, not something reserved for `scripts/evaluate.py` —
`make evaluate` is just the one thing that already reads them for you.

**Start in `pipeline/__main__.py`.** It's about ten lines: it lists the
clips and writes an `output.json`. It exists so the loop runs before you've
written anything, not to suggest a design — replace it. Everything else in
the repo (`Makefile`, `scripts/`, `requirements.txt`) is scaffolding around
that entry point; you shouldn't need to read through it to get going.

`.env` holds your API key, the base URL, and `RUN_BUDGET_SECONDS` — the
wall-clock limit `make run` has to finish inside. Your pipeline can read it if
it wants to make its own decisions about when to stop.

---

## What `make run` writes

The file contract, so your output and our tooling agree. The brief is
authoritative on what to put in them.

**`output.json`** — one entry per clip:

```json
{
  "clip_0001": {
    "text": "the transcript we should score",
    "status": "ok",
    "alignment": [
      { "word": "the", "start": 0.20, "end": 0.31 },
      { "word": "transcript", "start": 0.34, "end": 0.88 }
    ]
  }
}
```

| field | |
|---|---|
| key | The clip id, e.g. `clip_0001` |
| `text` | Your transcript |
| `status` | `"ok"` or `"failed"`. Only `"ok"` entries are scored for accuracy |
| `alignment` | Word timings from `/align`, as returned. Omit or leave empty if you have none |
| `note` | Optional, free text. Ignored by scoring — it's for you |

**`chunks.json`** — only if you attempt the bonus:

```json
{
  "clip_0001": [
    { "start": 0.20, "end": 7.90, "text": "okay yeah all good data like I said" }
  ]
}
```

**`run_meta.json`** is written for you by `make run`. It records how long the
run took, and `make evaluate` reads it to check the budget — so use `make run`
rather than invoking your pipeline directly if you want that number to be right.

Text normalisation is handled for you wherever accuracy is computed, so don't
spend time on formatting.

---

## Measuring your run

There is no scoring service. `make evaluate` scores `output.json` locally
against the references that ship with the repo:

- `data/dev_references.json` — transcripts for 20 of the clips
- `data/dev_alignments.json` — word timings for the same 20, in exactly the
  shape `/align` returns, so you can diff against them directly

It separates two kinds of number, and the difference matters. **Completeness and
the run budget it computes exactly**, over all 142 — those are the same figures
we will get. **Accuracy it estimates** from the 20 dev clips; a 20-clip sample
lands within about a third of the true value, which is enough to tell you your
pipeline works and not enough to tune against.

It also checks the shape of `output.json` and exits non-zero if something is
wrong with it — missing clips, an unrecognised `status`, a malformed alignment.

Read `scripts/evaluate.py`. Copy or replace it if you'd rather measure
differently; it exists so you have a feedback loop on day one, not to constrain
how you build one.

---

## If you can't get started

Tell us if `make setup` fails, the clip download fails, your key is rejected, or
`GET /health` doesn't answer. Those are ours, and losing forty minutes to one of
them tells us nothing useful about you.

`/health` is the check for that. It takes no key and does nothing clever, so if
it answers you are set up correctly and the service is reachable. What happens
after that is the exercise, and working through it is the job rather than
something to report.
