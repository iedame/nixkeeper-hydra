"""Asking Hydra: which evaluation of a jobset (nixpkgs master's, by default)
is the newest (one small request), that evaluation's full page (one big
one), a build's page, and a job's last successful build."""

import gzip
import http.client
import json
import re
import shutil
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime

HYDRA_URL = "https://hydra.nixos.org"
# The jobset nixkeeper reads builds from: nixpkgs master ("trunk" is the same
# jobset, by its old name).
JOBSET = "nixpkgs/unstable"
USER_AGENT = "nixkeeper-hydra (+https://github.com/iedame/nixkeeper-hydra)"
EVAL = re.compile(r"/eval/([0-9]+)")
# The longest a whole answer may take to arrive, in seconds: urlopen's
# timeout only bounds each wait for the next bytes, so a server sending a
# little at a time could hold the run until its job's time limit. The list
# of evaluations is small; the full evaluation page takes Hydra minutes to
# make and to send (a run, download included, takes about 3).
LIST_DEADLINE = 60
EVAL_DEADLINE = 1200


class Deadline:
    """A response read as it arrives, with TimeoutError once
    time.monotonic() is past deadline, however steadily it trickles in.
    read(size) still gives size bytes (fewer only at the end), as gzip
    expects."""

    def __init__(self, resp, deadline):
        self.resp = resp
        self.deadline = deadline

    def read(self, size=-1):
        if not isinstance(self.resp, http.client.HTTPResponse):
            return self.resp.read(size)  # not from a socket (a test's)
        chunks, got = [], 0
        while size is None or size < 0 or got < size:
            if time.monotonic() > self.deadline:
                raise TimeoutError("the answer took too long to arrive")
            want = 65536 if size is None or size < 0 else min(65536, size - got)
            chunk = self.resp.read1(want)  # what has arrived, at most want
            if not chunk:
                break
            chunks.append(chunk)
            got += len(chunk)
        return b"".join(chunks)

    def readall(self):
        return self.read()


def latest_eval(jobset=JOBSET):
    """The id of jobset's newest evaluation, from its list of evaluations
    (a small page). Not its latest-eval page: that's the newest evaluation
    whose builds have all finished, often a day or more behind."""
    req = urllib.request.Request(
        f"{HYDRA_URL}/jobset/{jobset}/evals", headers={"User-Agent": USER_AGENT}
    )
    deadline = time.monotonic() + LIST_DEADLINE
    with urllib.request.urlopen(req, timeout=60) as resp:
        html = Deadline(resp, deadline).readall().decode("utf-8", "replace")
    ids = [int(i) for i in EVAL.findall(html)]
    if not ids:
        raise OSError("Hydra's list of evaluations has none")
    return max(ids)


# Seconds from one build page's request to the next: Hydra is asked
# politely, a page at a time.
PAUSE = 1.0
_last = 0.0


def _pace():
    """Wait until PAUSE has passed since the last request of a page or a
    job (the run's small requests, one at a time)."""
    global _last
    wait = _last + PAUSE - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last = time.monotonic()


def build_page(build_id):
    """A build's page (its steps: which failed, blocked.failed_steps), at
    most one a PAUSE; raises on failure (the build is tried again next
    run)."""
    _pace()
    req = urllib.request.Request(
        f"{HYDRA_URL}/build/{build_id}", headers={"User-Agent": USER_AGENT}
    )
    deadline = time.monotonic() + LIST_DEADLINE
    with urllib.request.urlopen(req, timeout=60) as resp:
        return Deadline(resp, deadline).readall().decode("utf-8", "replace")


def download_eval(eval_id, path):
    """Save evaluation eval_id's full page (every job) to path. Hydra takes a
    few minutes to make it; it comes compressed when Hydra will."""
    req = urllib.request.Request(
        f"{HYDRA_URL}/eval/{eval_id}?full=1",
        headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"},
    )
    deadline = time.monotonic() + EVAL_DEADLINE
    with urllib.request.urlopen(req, timeout=900) as resp, open(path, "wb") as out:
        body = Deadline(resp, deadline)
        if resp.headers.get("Content-Encoding") == "gzip":
            body = gzip.GzipFile(fileobj=body)
        shutil.copyfileobj(body, out, 1 << 20)


def last_success(attr, system, jobset=JOBSET):
    """A job's last successful build in jobset: {"build": id, "at": when it
    finished (ISO 8601, UTC), "name": what it built}, or None when Hydra has
    none ("There is no successful build to redirect to."). Hydra's
    /job/.../latest redirects to that build, whose JSON says the rest. At
    most one a PAUSE; raises on any other failure (asked again next run)."""
    _pace()
    req = urllib.request.Request(
        f"{HYDRA_URL}/job/{jobset}/{attr}.{system}/latest",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    deadline = time.monotonic() + LIST_DEADLINE
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            build = json.loads(Deadline(resp, deadline).readall())
    except urllib.error.HTTPError as e:
        try:
            if e.code == 404 and "no successful build" in e.read().decode(
                "utf-8", "replace"
            ):
                return None
        finally:
            e.close()
        raise
    stoptime = build.get("stoptime")
    if not build.get("id") or not stoptime:
        raise OSError(f"{attr}.{system}: Hydra's last success has no id or time")
    return {
        "build": str(build["id"]),
        "at": datetime.fromtimestamp(stoptime, UTC).isoformat(),
        "name": build.get("nixname") or "",
    }
