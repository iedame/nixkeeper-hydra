"""A failing job's last successful build, for those the digest doesn't know:
it learns one by seeing the job succeed and then fail (digest.last_success),
so a job already failing when the digest started (2026-10-04), or new to it
and failing from the start, had none. Hydra says, a job at a time
(hydra.last_success); the answer goes into the row's lastSuccess* columns,
which every later digest carries on (digest.merge), so each job is asked
once. A job that never succeeded says so in its row (lastSuccessAt
"never", NEVER), so readers needn't ask Hydra either, and is remembered
(last-success.json, by job, with the build it was asked about): asked again
only once its build changes, as Hydra built it again and it may have
worked in between."""

import json
import os

CACHE = "last-success.json"
NOT_OK = ("failed", "dependency", "unfinished")
# lastSuccessAt of a job Hydra says never succeeded (its build and name empty).
NEVER = "never"


def job(row):
    return f"{row['attr']} {row['system']}"


def read(directory):
    """{job: the build it was asked about} of the jobs Hydra says never
    succeeded (job: "attr system")."""
    try:
        with open(os.path.join(directory, CACHE)) as f:
            return json.load(f).get("never", {})
    except FileNotFoundError:
        return {}


def write(directory, never):
    with open(os.path.join(directory, CACHE), "w") as f:
        json.dump({"never": dict(sorted(never.items()))}, f, indent=1, sort_keys=True)
        f.write("\n")


def wanted(rows, never):
    """The rows to ask Hydra about: not ok, no last success known, and not
    known to have never succeeded for this very build."""
    return [
        r
        for r in rows
        if r["status"] in NOT_OK
        and not r.get("lastSuccessBuild")
        and never.get(job(r)) != r["build"]
    ]


def counts(rows, never):
    """{"known", "never", "pending"} among the rows that aren't ok."""
    not_ok = [r for r in rows if r["status"] in NOT_OK]
    known = sum(1 for r in not_ok if r.get("lastSuccessBuild"))
    gone = sum(
        1
        for r in not_ok
        if not r.get("lastSuccessBuild") and never.get(job(r)) == r["build"]
    )
    return {"known": known, "never": gone, "pending": len(not_ok) - known - gone}


def mark_never(rows, never):
    """Write "never" into the rows never remembers for their current build
    (those asked before the marker, or whose row lost it)."""
    for r in rows:
        if (
            r["status"] in NOT_OK
            and not r.get("lastSuccessBuild")
            and never.get(job(r)) == r["build"]
        ):
            r["lastSuccessAt"] = NEVER


def fill(row, found):
    """Put Hydra's answer (hydra.last_success's) into row: its last success,
    or for None, that it never succeeded."""
    row["lastSuccessBuild"] = found["build"] if found else ""
    row["lastSuccessAt"] = found["at"] if found else NEVER
    row["lastSuccessName"] = found["name"] if found else ""
