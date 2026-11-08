"""Entry point for your pipeline. `make run` executes this.

As shipped it writes a valid `output.json` placeholder, so you can run
`make run` and `make evaluate` before writing anything and see the loop work end
to end. It scores zero. Replace it with something that transcribes.
"""

from __future__ import annotations

import json
import pathlib

CLIPS_DIR = pathlib.Path("data/clips")
OUTPUT_PATH = pathlib.Path("output.json")


def main() -> None:
    results = {
        path.stem: {"text": None, "status": "failed", "note": "pipeline not implemented"}
        for path in sorted(CLIPS_DIR.glob("clip_*.wav"))
    }
    OUTPUT_PATH.write_text(json.dumps(results, indent=2))
    print(f"wrote {len(results)} results to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
