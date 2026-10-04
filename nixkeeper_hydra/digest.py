"""The digest nixkeeper reads (data/): builds.csv.gz, every job of the newest
evaluation with its newest finished build (from that evaluation, or for a
build still queued there, an earlier one) and, when that isn't a success,
the last successful build this digest has seen; and meta.json, which
evaluation that is.

builds.csv.gz's columns:

    attr, system          the job (wesnoth, x86_64-linux)
    build                 its build's id (https://hydra.nixos.org/build/<id>)
    status                ok, failed, dependency, unfinished, or queued (a
                          job new to the digest, not built yet)
    finished              when it finished (ISO 8601, UTC); empty if queued
    name                  what it builds (wesnoth-1.18.8)
    lastSuccessBuild,     for a build that isn't ok: the job's last
    lastSuccessAt,        successful build, when it finished, and its name;
    lastSuccessName       empty when the digest hasn't seen one (it only
                          knows those since it started)

sorted by attr and system. The file is the same, byte for byte, when the
builds are: unchanged data isn't published again."""

import csv
import gzip
import io
import json
import os

FORMAT = 1
BUILDS = "builds.csv.gz"
META = "meta.json"
COLUMNS = (
    "attr",
    "system",
    "build",
    "status",
    "finished",
    "name",
    "lastSuccessBuild",
    "lastSuccessAt",
    "lastSuccessName",
)


def last_success(build, before):
    """build's last-success columns, from the job's row in the previous
    digest (before; None if it had none): that row itself if it was ok, else
    what it carried; empty for an ok build (it's its own last success)."""
    if build["status"] == "ok" or not before:
        return {"lastSuccessBuild": "", "lastSuccessAt": "", "lastSuccessName": ""}
    if before["status"] == "ok":
        return {
            "lastSuccessBuild": before["build"],
            "lastSuccessAt": before["finished"],
            "lastSuccessName": before["name"],
        }
    return {
        k: before[k] for k in ("lastSuccessBuild", "lastSuccessAt", "lastSuccessName")
    }


def merge(builds, previous):
    """The digest's rows: each job's newest finished build, with its last
    success, sorted. builds: page.parse's, from the newest evaluation, whose
    builds may still be queued; previous: the last digest's rows by (attr,
    system). A job whose build is queued keeps the last digest's row, its
    newest finished build (as Hydra's latest builds would say), when there
    is one; only a job new to the digest stays queued."""
    rows = []
    for b in builds:
        before = previous.get((b["attr"], b["system"]))
        if b["status"] == "queued" and before and before["status"] != "queued":
            rows.append(before)
        else:
            rows.append({**b, **last_success(b, before)})
    return sorted(rows, key=lambda r: (r["attr"], r["system"]))


def write(directory, rows, meta):
    """Write builds.csv.gz and meta.json to directory."""
    os.makedirs(directory, exist_ok=True)
    text = io.StringIO()
    writer = csv.DictWriter(text, COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    # mtime=0: the same rows give the same bytes.
    with open(os.path.join(directory, BUILDS), "wb") as f:
        f.write(gzip.compress(text.getvalue().encode(), compresslevel=9, mtime=0))
    with open(os.path.join(directory, META), "w") as f:
        json.dump({"format": FORMAT, **meta}, f, indent=2, sort_keys=True)
        f.write("\n")


def read(directory):
    """(rows by (attr, system), meta) of the digest in directory, or ({}, {})
    if there's none yet."""
    try:
        with open(os.path.join(directory, META)) as f:
            meta = json.load(f)
        with gzip.open(os.path.join(directory, BUILDS), "rt", newline="") as f:
            rows = {(r["attr"], r["system"]): r for r in csv.DictReader(f)}
    except FileNotFoundError:
        return {}, {}
    return rows, meta
