"""Which dependency a build failed because of: Hydra's "Dependency failed"
says only that one did. Its build page lists the build's steps, the failed
one with the store path it was building and, when the failure came from
another build, that build ("propagated from build N"). That's how zh.fail
finds the dependencies that stop the most builds; the API doesn't say.

Each build is read once (blocked.json keeps what was found, by build id:
a build Hydra doesn't redo keeps its id from one evaluation to the next),
and its blocker named as nixkeeper's rows are (blocker). "Propagated from
build N" is where the failure was first seen: N's job names the blocker
when it builds that very derivation, but it may be another package that
needed the same dependency. Else a job of the same platform building a
derivation of that name, else the name itself (a source download, say,
which is no package)."""

import json
import os
import re

CACHE = "blocked.json"

STEPS = re.compile(r'id="tabs-buildsteps".*?</table>', re.S)
ROW = re.compile(r"<tr>(.*?)</tr>", re.S)
CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
# What a step built: its derivation ("Build of '<hash>-<name>.drv' failed"),
# else its first output (/nix/store/<hash>-<name>-bin); and, for a step that
# failed in another build, which one.
DRV = re.compile(r"Build of &#39;[0-9a-z]{32}-(.+?)\.drv&#39;")
STORE = re.compile(r"/nix/store/[0-9a-z]{32}-([^<,\s]+)")
PROPAGATED = re.compile(r'/build/([0-9]+)">build [0-9]+</a>')
FAILED = re.compile(r">Failed<|Cached failure")
# A package's derivation name: name-version (python3.14-pypdf-6.19.0), not a
# generic one many derivations share ("source").
VERSIONED = re.compile(r"-[0-9]")
# A derivation's outputs, as store names end in them (python3.14-foo-1.0-dist).
OUTPUTS = (
    "bin",
    "data",
    "debug",
    "dev",
    "devdoc",
    "dist",
    "doc",
    "info",
    "lib",
    "man",
    "out",
    "static",
)


def failed_steps(page):
    """[[name, build]] for each failed step of a build's page, in its order
    (newest step first), one per store name: what it was building (without
    the store hash) and the build it failed in when that's another one
    (else None)."""
    steps = STEPS.search(page)
    found = {}
    for row in ROW.findall(steps.group(0) if steps else ""):
        cells = CELL.findall(row)
        if len(cells) != 5 or not FAILED.search(cells[4]):
            continue
        path = DRV.search(cells[4]) or STORE.search(cells[1])
        if not path:
            continue
        build = PROPAGATED.search(cells[4])
        name = path.group(1)
        if name not in found or (build and not found[name]):
            found[name] = int(build.group(1)) if build else None
    return [[name, build] for name, build in found.items()]


def without_output(name):
    """name without the output it ends in (python3.14-foo-1.0 for
    python3.14-foo-1.0-dist), or itself."""
    head, _, tail = name.rpartition("-")
    return head if head and tail in OUTPUTS else name


def plainest(attrs):
    """Of attributes building the same thing, the one to name it by: the
    fewest dots (top level first), then the shortest, then by name."""
    return min(attrs, key=lambda a: (a.count("."), len(a), a))


def names(rows):
    """({build id: (attr, name)}, {(name, system): attr}) of the digest's
    rows, to name a blocker by."""
    by_build, by_name = {}, {}
    for r in rows:
        if r["build"]:
            by_build[int(r["build"])] = (r["attr"], r["name"])
        key = (r["name"], r["system"])
        if r["name"]:
            by_name[key] = (
                plainest([by_name[key], r["attr"]]) if key in by_name else r["attr"]
            )
    return by_build, by_name


def blocker(step, system, by_build, by_name):
    """What a failed step ([name, build]) is, as nixkeeper names packages:
    the attribute of the build it failed in when that build's job builds
    that derivation, else of a job of system building a derivation of that
    name (with or without the output it ends in; a versioned one only), else
    the name."""
    name, build = step
    candidates = (name, without_output(name))
    # The build it failed in, when that's this derivation's own job: exact
    # (pkgsRocm.spfft, not the plain spfft of the same name).
    attr, built = by_build.get(build) or (None, None)
    if attr and built in candidates:
        return attr
    if VERSIONED.search(name):
        for candidate in candidates:
            if (candidate, system) in by_name:
                return by_name[(candidate, system)]
    return name


def blocked_by(row, found, by_build, by_name):
    """A dependency-failed row's blockedBy column: its blockers (blocker),
    space-separated, in order; empty when its page wasn't read yet."""
    steps = found.get(row["build"]) or []
    seen = []
    for step in steps:
        name = blocker(step, row["system"], by_build, by_name)
        if name not in seen:
            seen.append(name)
    return " ".join(seen)


def read(directory):
    """blocked.json: {build id (a string): [[name, build], ...]}, or {}."""
    try:
        with open(os.path.join(directory, CACHE)) as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {}


def write(directory, found):
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, CACHE), "w") as f:
        json.dump(found, f, separators=(",", ":"), sort_keys=True)
        f.write("\n")
