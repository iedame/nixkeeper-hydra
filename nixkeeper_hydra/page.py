"""Reading Hydra's evaluation page (/eval/<id>?full=1): every job's build in
that evaluation, from its tables of jobs (aborted, newly failing, newly
succeeding, new, still failing, still succeeding, unfinished). Each row there
is a build: its status icon, id, job, finish time, name and the platform it
was built on.

The page is big (all of nixpkgs, about 220,000 jobs), so it's read with
regexes from positions in the one string, without copying its parts."""

import re
from datetime import UTC, datetime

# The tables of builds, by their tab's id; "removed" (jobs no longer in the
# evaluation, without builds), "inputs" and "errors" aren't.
BUILD_TABS = (
    "aborted",
    "now-fail",
    "now-succeed",
    "new",
    "still-fail",
    "still-succeed",
    "unfinished",
)
# The platforms nixkeeper asks Hydra about (nixpkgs no longer builds
# x86_64-darwin).
SYSTEMS = ("x86_64-linux", "aarch64-linux", "aarch64-darwin")

# Hydra's status icons, by their text. "Failed with output" is the package's
# own failure too. Anything else that finished (aborted, cancelled, timed out,
# log or output limit exceeded, ...) didn't finish building: "unfinished".
STATUSES = {
    "Succeeded": "ok",
    "Failed": "failed",
    "Failed with output": "failed",
    "Dependency failed": "dependency",
}

TAB = re.compile(r'id="tabs-([a-z-]+)"')
ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
TAG = re.compile(r"<[^>]+>")
ALT = re.compile(r'alt="([^"]*)"')
TIMESTAMP = re.compile(r'data-timestamp="([0-9]+)"')
REVISION = re.compile(r"copyToClipboard\('([0-9a-f]{40})'")


def text(cell):
    """A cell's text, without its tags and spaces."""
    return "".join(TAG.sub("", cell).split())


def build(cells, tab):
    """A table row's build: {"attr", "system", "build", "status",
    "finished", "name"}, or None for a platform nixkeeper doesn't ask about.
    status is ok, failed, dependency, unfinished, or queued when it hasn't
    finished yet (no finish time: Hydra's "Scheduled to be built" icon also
    starts with an S, like "Succeeded"). The platform is the job's, from the
    end of its name: the System column says where the build ran, which can
    be another (zsnes.x86_64-linux is built as i686-linux)."""
    job = text(cells[2])
    system = next((s for s in SYSTEMS if job.endswith(f".{s}")), None)
    if system is None:
        return None
    stamp = TIMESTAMP.search(cells[3])
    if tab == "unfinished" or not stamp:
        status, finished = "queued", ""
    else:
        alt = ALT.search(cells[0])
        status = STATUSES.get(alt.group(1) if alt else "", "unfinished")
        finished = datetime.fromtimestamp(int(stamp.group(1)), UTC).isoformat()
    return {
        "attr": job.removesuffix(f".{system}"),
        "system": system,
        "build": text(cells[1]),
        "status": status,
        "finished": finished,
        "name": text(cells[4]),
    }


def parse(html):
    """(builds, nixpkgs revision or None) from an evaluation page: builds
    are build()'s, each job once (on the first table it's in)."""
    tabs = [(m.group(1), m.end()) for m in TAB.finditer(html)]
    ends = [start for _, start in tabs[1:]] + [len(html)]
    builds, seen, revision = [], set(), None
    for (tab, start), end in zip(tabs, ends, strict=True):
        if tab == "inputs":
            m = REVISION.search(html, start, end)
            revision = m.group(1) if m else None
        if tab not in BUILD_TABS:
            continue
        for row in ROW.finditer(html, start, end):
            cells = CELL.findall(row.group(1))
            if len(cells) != 6:
                continue  # a header, or a "more jobs" row
            found = build(cells, tab)
            if found and (found["attr"], found["system"]) not in seen:
                seen.add((found["attr"], found["system"]))
                builds.append(found)
    return builds, revision
