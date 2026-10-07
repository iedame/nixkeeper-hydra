"""Hydra's builds of a nixpkgs branch other than master, for the sets
updated there before they reach master: haskell-updates, where the Haskell
team updates haskellPackages (hackage2nix) and merges into master about
every two weeks. Its jobset's newest evaluation, digested beside master's
into data/<branch>.json.gz:

    {"format": 1, "jobset": "nixpkgs/haskell-updates", "eval": 1829685,
     "revision": "4e9d3032...", "fetchedAt": "2026-10-07T12:17:00+00:00",
     "builds": 8709, "counts": {"ok": 7777, "failed": 437, ...},
     "columns": ["attr", "system", "build", "status", "name"],
     "jobs": [["haskellPackages.Agda", "x86_64-linux", "347795412", "ok",
               "Agda-2.8.0.2"], ...]}

each job's build in that evaluation (sorted by attr and system), its status
as in builds.csv.gz, and what it builds: the branch's version. Read like
master's (cli.due): when there's a new evaluation (the jobset is evaluated
when the branch changes, every few days), while builds of it are queued,
or once a day. Its page is small (about 350 KB). A branch that can't be
read keeps its last file."""

import gzip
import json
import os
import sys
import tempfile
from collections import Counter

from . import hydra, page

FORMAT = 1
# Each branch: its Hydra jobset, and the fewest builds its page should have
# (about half of 2026-09-30's 8,709): fewer, the page was cut short.
BRANCHES = {"haskell-updates": ("nixpkgs/haskell-updates", 4000)}
COLUMNS = ("attr", "system", "build", "status", "name")


def path(directory, branch):
    return os.path.join(directory, f"{branch}.json.gz")


def read(directory, branch):
    """branch's file in directory, or None if there's none."""
    try:
        with gzip.open(path(directory, branch), "rt") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def write(directory, branch, body):
    os.makedirs(directory, exist_ok=True)
    data = json.dumps({"format": FORMAT, **body}, separators=(",", ":"))
    with open(path(directory, branch), "wb") as f:
        f.write(gzip.compress(data.encode(), compresslevel=9, mtime=0))


def update(directory, branch, now, due):
    """Bring branch's file up to date when due (cli.due: why it should be
    read now, or None) says so. True when it was written."""
    jobset, least = BRANCHES[branch]
    last = read(directory, branch)
    latest = hydra.latest_eval(jobset)
    why = due(latest, last, now)
    if not why:
        print(f"{branch}: evaluation {latest}, nothing new.")
        return False
    print(f"{branch}: reading evaluation {latest}: {why}...")
    with tempfile.TemporaryDirectory() as tmp:
        saved = os.path.join(tmp, "eval.html")
        hydra.download_eval(latest, saved)
        with open(saved, encoding="utf-8", errors="replace") as f:
            builds, revision = page.parse(f.read())
    if len(builds) < least:
        raise ValueError(
            f"only {len(builds):,} builds on its page (expected over {least:,})"
        )
    jobs = sorted(
        ([b.get(c) or "" for c in COLUMNS] for b in builds),
        key=lambda job: (job[0], job[1]),
    )
    counts = Counter(job[3] for job in jobs)
    write(
        directory,
        branch,
        {
            "jobset": jobset,
            "eval": latest,
            "revision": revision,
            "fetchedAt": now.isoformat(timespec="seconds"),
            "builds": len(jobs),
            "counts": dict(sorted(counts.items())),
            "columns": list(COLUMNS),
            "jobs": jobs,
        },
    )
    print(
        f"  {len(jobs):,} builds: "
        + ", ".join(f"{n:,} {status}" for status, n in sorted(counts.items()))
    )
    return True


def update_all(directory, now, due):
    """Each branch in BRANCHES, as update: one that fails keeps its last
    file, with a warning, and the master digest goes on."""
    for branch in BRANCHES:
        try:
            update(directory, branch, now, due)
        except (OSError, ValueError) as e:  # urllib's errors are OSErrors
            print(f"::warning::{branch}: {e}; kept the last", file=sys.stderr)
