"""`python3 -m nixkeeper_hydra [DATA_DIR]`: bring the digest in DATA_DIR
(default data/) up to date with Hydra's newest evaluation of nixpkgs master,
downloading its page only when that can bring something new (due); and the
branches' beside it (branches.py: haskell-updates), likewise."""

import os
import sys
import tempfile
import time
from collections import Counter
from datetime import UTC, datetime, timedelta

from . import blocked, branches, digest, hydra, lastsuccess, page

# While builds of the evaluation are still queued, its page is read again
# this often, for their results; and at least this often anyway, for builds
# Hydra restarted (same build, new result).
QUEUED_EVERY = timedelta(hours=6)
ANYWAY_EVERY = timedelta(hours=24)
# Fewer builds than this means the page was cut short, or Hydra changed it:
# nothing is published (nixkeeper then asks Hydra itself).
MIN_BUILDS = 100_000
# Build pages read a run (which dependency failed, blocked.py), a second
# apart: the rest wait for the next run. So many failures in a row: Hydra
# isn't answering, the rest wait too.
MAX_PAGES = 1500
MAX_MINUTES = 40
MAX_FAILURES_IN_A_ROW = 10
# Jobs asked their last successful build a run (lastsuccess.py), a second
# apart, within the same MAX_MINUTES: the 4,805 the digest lacked on
# 2026-10-07 take a few runs; after that, a handful a new evaluation.
MAX_LOOKUPS = 1500


def look_up_blocked(rows, found, started):
    """Read the pages of the dependency-failed builds found (blocked.json's)
    doesn't know yet, at most MAX_PAGES and MAX_MINUTES since started, into
    found; drop what it has on builds that aren't any more. Returns how many
    were read and how many are still to read."""
    current = {r["build"] for r in rows if r["status"] == "dependency"}
    for build in set(found) - current:
        del found[build]
    wanted = sorted(current - set(found))
    read = in_a_row = 0
    for build in wanted[:MAX_PAGES]:
        if time.monotonic() - started > MAX_MINUTES * 60:
            break
        if in_a_row >= MAX_FAILURES_IN_A_ROW:
            print(
                "::warning::Hydra stopped answering for build pages.", file=sys.stderr
            )
            break
        try:
            found[build] = blocked.failed_steps(hydra.build_page(build))
            read += 1
            in_a_row = 0
        except OSError as e:  # urllib's errors are OSErrors
            print(f"  build {build}: {e}", file=sys.stderr)
            in_a_row += 1
    return read, len(current - set(found))


def look_up_last_success(rows, never, started):
    """Ask Hydra the last successful build of the rows lastsuccess.wanted
    picks, at most MAX_LOOKUPS and MAX_MINUTES since started: the answer
    goes into the row (lastSuccessAt "never" when there's none), and "never"
    into never too. Returns how many were asked."""
    asked = in_a_row = 0
    for row in lastsuccess.wanted(rows, never)[:MAX_LOOKUPS]:
        if time.monotonic() - started > MAX_MINUTES * 60:
            break
        if in_a_row >= MAX_FAILURES_IN_A_ROW:
            print(
                "::warning::Hydra stopped answering for last successes.",
                file=sys.stderr,
            )
            break
        try:
            found = hydra.last_success(row["attr"], row["system"])
        except (OSError, ValueError) as e:  # urllib's errors are OSErrors
            print(f"  {row['attr']}.{row['system']}: {e}", file=sys.stderr)
            in_a_row += 1
            continue
        in_a_row = 0
        asked += 1
        lastsuccess.fill(row, found)
        if found:
            never.pop(lastsuccess.job(row), None)
        else:
            never[lastsuccess.job(row)] = row["build"]
    return asked


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


def publish(directory, rows, found, meta, read, pending, never, asked):
    """Write the digest: rows with their blockedBy (from found), meta with
    how many dependency failures are known and still to read, and how many
    last successes are known, never were, and are still to ask (never,
    asked: look_up_last_success's)."""
    by_build, by_name = blocked.names(rows)
    for r in rows:
        r["blockedBy"] = (
            blocked.blocked_by(r, found, by_build, by_name)
            if r["status"] == "dependency"
            else ""
        )
    known = sum(1 for r in rows if r["blockedBy"])
    meta = {k: v for k, v in meta.items() if k != "format"}
    meta["blocked"] = {"known": known, "pending": pending}
    # Jobs that succeed again, or left the evaluation, needn't be remembered.
    current = {
        lastsuccess.job(r): r["build"]
        for r in rows
        if r["status"] in lastsuccess.NOT_OK
    }
    for job in [j for j in never if j not in current]:
        del never[job]
    lastsuccess.mark_never(rows, never)
    meta["lastSuccess"] = lastsuccess.counts(rows, never)
    blocked.write(directory, found)
    lastsuccess.write(directory, never)
    digest.write(directory, rows, meta)
    print(
        f"  dependency failures: {read:,} read now, {known:,} known, "
        f"{pending:,} to read"
    )
    ls = meta["lastSuccess"]
    print(
        f"  last successes: {asked:,} asked now, {ls['known']:,} known, "
        f"{ls['never']:,} never, {ls['pending']:,} to ask"
    )


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    directory = argv[0] if argv else "data"
    now = datetime.now(UTC)
    started = time.monotonic()
    previous, meta = digest.read(directory)
    found = blocked.read(directory)
    never = lastsuccess.read(directory)
    # The branches first, on their own: a failure keeps their last files.
    branches.update_all(directory, now, due)
    latest = hydra.latest_eval()
    why = due(latest, meta, now)
    if not why:
        # Nothing new on the evaluation, but its dependency failures may
        # still be to read (the first runs, or a capped one).
        rows = sorted(previous.values(), key=lambda r: (r["attr"], r["system"]))
        read, pending = look_up_blocked(rows, found, started)
        asked = look_up_last_success(rows, never, started)
        if not read and not asked:
            print(f"Evaluation {latest}: nothing new since {meta['fetchedAt']}.")
            return 0
        publish(directory, rows, found, meta, read, pending, never, asked)
        return 0
    print(f"Reading evaluation {latest}: {why}...")
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
    read, pending = look_up_blocked(rows, found, started)
    asked = look_up_last_success(rows, never, started)
    known = sum(1 for r in rows if r["status"] != "ok" and r["lastSuccessBuild"])
    publish(
        directory,
        rows,
        found,
        {
            "eval": latest,
            "revision": revision,
            "fetchedAt": now.isoformat(timespec="seconds"),
            "builds": len(rows),
            "counts": dict(sorted(counts.items())),
        },
        read,
        pending,
        never,
        asked,
    )
    print(
        "  "
        + ", ".join(f"{n:,} {status}" for status, n in sorted(counts.items()))
        + f"; last success known for {known:,} of {len(rows) - counts['ok']:,} not ok"
    )
    return 0
