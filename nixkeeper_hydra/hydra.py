"""Asking Hydra: which evaluation of nixpkgs master is the newest (one small
request), and that evaluation's full page (one big one)."""

import gzip
import re
import shutil
import urllib.request

HYDRA_URL = "https://hydra.nixos.org"
# The jobset nixkeeper reads builds from: nixpkgs master ("trunk" is the same
# jobset, by its old name).
JOBSET = "nixpkgs/unstable"
USER_AGENT = "nixkeeper-hydra (+https://github.com/iedame/nixkeeper-hydra)"
EVAL = re.compile(r"/eval/([0-9]+)")


def latest_eval():
    """The id of the jobset's newest evaluation, from its list of evaluations
    (a small page). Not its latest-eval page: that's the newest evaluation
    whose builds have all finished, often a day or more behind."""
    req = urllib.request.Request(
        f"{HYDRA_URL}/jobset/{JOBSET}/evals", headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        html = resp.read().decode("utf-8", "replace")
    ids = [int(i) for i in EVAL.findall(html)]
    if not ids:
        raise OSError("Hydra's list of evaluations has none")
    return max(ids)


def download_eval(eval_id, path):
    """Save evaluation eval_id's full page (every job) to path. Hydra takes a
    few minutes to make it; it comes compressed when Hydra will."""
    req = urllib.request.Request(
        f"{HYDRA_URL}/eval/{eval_id}?full=1",
        headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"},
    )
    with urllib.request.urlopen(req, timeout=900) as resp, open(path, "wb") as out:
        body = resp
        if resp.headers.get("Content-Encoding") == "gzip":
            body = gzip.GzipFile(fileobj=resp)
        shutil.copyfileobj(body, out, 1 << 20)
