"""`python3 -m nixkeeper_hydra [DATA_DIR]`: bring the digest in DATA_DIR
(default data/) up to date with Hydra's newest evaluation of nixpkgs master,
downloading its page only when that can bring something new (due)."""

import os
import sys
import tempfile
import time
from collections import Counter
from datetime import UTC, datetime, timedelta

from . import digest, hydra, page

# While builds of the evaluation are still queued, its page is read again
# this often, for their results; and at least this often anyway, for builds
# Hydra restarted (same build, new result).
QUEUED_EVERY = timedelta(hours=6)
ANYWAY_EVERY = timedelta(hours=24)
# Fewer builds than this means the page was cut short, or Hydra changed it:
# nothing is published (nixkeeper then asks Hydra itself).
MIN_BUILDS = 100_000


def due(latest, meta, now):
    """Why the page should be read now, or None: never read yet, a newer
    evaluation, builds of this one still queued (every QUEUED_EVERY), or
    ANYWAY_EVERY since it was."""
    if not meta:
        return "no digest yet"
    if meta.get("eval") != latest:
        return f"evaluation {latest} (the digest has {meta.get('eval')})"
    age = now - datetime.fromisoformat(meta["fetchedAt"])
    queued = (meta.get("counts") or {}).get("queued", 0)
    if queued and age >= QUEUED_EVERY:
        return f"{queued} builds were still queued"
    if age >= ANYWAY_EVERY:
        return "a day since it was read"
    return None


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    directory = argv[0] if argv else "data"
    now = datetime.now(UTC)
    previous, meta = digest.read(directory)
    latest = hydra.latest_eval()
    why = due(latest, meta, now)
    if not why:
        print(f"Evaluation {latest}: nothing new since {meta['fetchedAt']}.")
        return 0
    print(f"Reading evaluation {latest}: {why}...")
    started = time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "eval.html")
        hydra.download_eval(latest, path)
        size = os.path.getsize(path)
        with open(path, encoding="utf-8", errors="replace") as f:
            builds, revision = page.parse(f.read())
    took = time.monotonic() - started
    print(f"  {size / 1e6:.0f} MB, {len(builds):,} builds, in {took:.0f} s")
    if len(builds) < MIN_BUILDS:
        print(
            f"::error::Only {len(builds):,} builds on evaluation {latest}'s page "
            f"(expected over {MIN_BUILDS:,}): not published.",
            file=sys.stderr,
        )
        return 1
    rows = digest.merge(builds, previous)
    counts = Counter(r["status"] for r in rows)
    known = sum(1 for r in rows if r["status"] != "ok" and r["lastSuccessBuild"])
    digest.write(
        directory,
        rows,
        {
            "eval": latest,
            "revision": revision,
            "fetchedAt": now.isoformat(timespec="seconds"),
            "builds": len(rows),
            "counts": dict(sorted(counts.items())),
        },
    )
    print(
        "  "
        + ", ".join(f"{n:,} {status}" for status, n in sorted(counts.items()))
        + f"; last success known for {known:,} of {len(rows) - counts['ok']:,} not ok"
    )
    return 0
