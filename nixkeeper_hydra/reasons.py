"""Why a build failed, from its log: a reason ("cmake4", "hash", "patch",
...) and the few lines that say so. Each failed build's log is read once
(reasons.json keeps what was found, by build id with when it finished: a
build Hydra doesn't redo keeps its id from one evaluation to the next, and
a restarted one finishes again, so it's read again).

The rules come from nixpkgs-failure-dashboard's classifier
(https://github.com/Sigmanificient/nixpkgs-failure-dashboard, app/tagging.py
and app/classify.py, MIT License, Copyright (c) 2026 Sigmanificient), under
nixkeeper's own reason names: each is a pattern, and hints that must all be
somewhere in the log too; the log is read from its end, and the first rule
that matches, in order, says why. A log no rule explains is "other"."""

import json
import os
import re
from dataclasses import dataclass, field

CACHE = "reasons.json"
# A terminal's colours and links, which build logs keep (rustc's errors,
# GCC's links to its warnings' documentation).
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
# The lines kept to say why: the one a rule matched and those after it,
# each cut to so many characters.
EXCERPT_LINES = 3
EXCERPT_WIDTH = 200
# A reason for a log Hydra doesn't have (gone, or never kept).
NO_LOG = "noLog"
OTHER = "other"


@dataclass(frozen=True)
class Rule:
    reason: str
    pattern: str
    hints: tuple[str, ...] = field(default=())


RULES = (
    Rule(
        "autotools",
        r"aclocal: error: couldn't open directory '.*': No such file or directory",
        ("error: aclocal failed with exit status: 1",),
    ),
    Rule(
        "boost",
        r"CMake Error at",
        ("(requested version 1.89.0)", "lib/cmake/Boost-1.89.0"),
    ),
    # CMake 4 dropped compatibility with projects asking for CMake < 3.5.
    Rule(
        "cmake4",
        r"CMake Error at",
        (
            "Compatibility with CMake < 3.5 has been removed",
            "add -DCMAKE_POLICY_VERSION_MINIMUM=3.5 to try configuring anyway",
        ),
    ),
    Rule(
        "cmake",
        r"CMake Error at",
        (
            "cmake flags:",
            "CMakeLists.txt",
            "-- Configuring incomplete, errors occurred!",
        ),
    ),
    Rule(
        "patchelf",
        r"auto-patchelf: \d+ dependencies could not be satisfied",
        (
            "auto-patchelf could not satisfy dependency",
            "auto-patchelf failed to find all the required dependencies",
        ),
    ),
    Rule(
        "pythonImport",
        r"(ImportError: cannot import name '.*' from '.*'"
        r"|ModuleNotFoundError: No module named '.*')",
        ("<module>",),
    ),
    Rule(
        "pythonDeps",
        r"(not installed)|(not satisfied by version)",
        ("Checking runtime dependencies", "Executing pythonRuntimeDepsCheck"),
    ),
    Rule(
        "pythonBuild",
        r"Traceback \(most recent call last\):",
        (
            "FileNotFoundError: [Errno 2]",
            "No such file or directory: 'setup.py'",
            "exec(compile(getattr(tokenize",
        ),
    ),
    Rule(
        "pythonBuild",
        r"(BackendUnavailable|ERROR Backend .* is not available)",
        ("Executing pypaBuildPhase", "pyproject_hooks._impl.BackendUnavailable"),
    ),
    Rule(
        "pythonDeps",
        r"ERROR Missing dependencies:",
        ("Creating a wheel...", "pypa build flags"),
    ),
    Rule(
        "tests",
        r"=========+.*(errors?|failed)",
        ("==== short test summary info ====",),
    ),
    Rule(
        "pythonBuild",
        r"error: .* should use `buildPythonPackage` or `toPythonModule` if it is "
        r"to be part of the Python packages set.",
    ),
    Rule(
        "pythonMetadata",
        r"but \.dist-info/METADATA specifies version",
        ("Executing pythonMetadataCheckPhase", "pyprojectVersionPatchHook"),
    ),
    Rule(
        "pythonMetadata",
        r"importlib.metadata.PackageNotFoundError: No package metadata was found "
        r"for",
        ("pythonMetadataCheckPhase",),
    ),
    # Not in the dashboard's (2026-10-08, from a sample of Hydra's failed
    # builds): a header the compiler can't find, C++ and fatal errors,
    # Rust's, the linker's, and tests other than pytest's.
    Rule("header", r"fatal error: .*(file not found|No such file or directory)"),
    Rule(
        "compile",
        r"\S+\.(c|h|cc|cpp|cxx|c\+\+|hh|hpp|hxx|ipp|tcc|m|mm|cu|hs):\d+:\d+: "
        r"(fatal )?error:",
    ),
    Rule("compile", r"error: could not compile `[^`]+`"),
    Rule(
        "link",
        r"(collect2: error: ld returned \d+ exit status|ld(\.lld)?: error: "
        r"|undefined reference to `|clang(\+\+)?: error: linker command failed"
        r"|ERROR: modpost: .* undefined!)",
    ),
    Rule("tests", r"^FAILED \((failures|errors)=\d+", ("Ran ",)),
    Rule("tests", r"Test suite \S+: FAIL"),
    Rule("tests", r"^FAILED \S+::\S+"),
    Rule("tests", r"error: test failed, to rerun pass"),
    Rule(
        "haskellDeps",
        r"Error: \[Cabal-8010\]",
        ("Encountered missing or private dependencies:",),
    ),
    Rule("npm", r"npm error", ("package-lock.json",)),
    Rule(
        "npm",
        r"ERROR: npm failed to install dependencies",
        ("npm error", "Here are a few things you can try", "--legacy-peer-deps"),
    ),
    Rule(
        "lisp",
        r"BUILD FAILED: Can't create directory /homeless-shelter",
        ("; compilation unit aborted",),
    ),
    Rule("lisp", r"; compilation unit aborted", ("SBCL is free software",)),
    Rule("lisp", r"BUILD FAILED: Component .* not found", ("SBCL is free software",)),
    # Writing to $HOME, which builds don't have (/homeless-shelter).
    Rule(
        "home",
        r"(?i)(/homeless-shelter\S*:? .*(permission denied|read-only file system"
        r"|no such file or directory|can't create)|(permission denied|read-only "
        r"file system|no such file or directory).*/homeless-shelter)",
    ),
    Rule(
        "header",
        r": No such file or directory",
        ("#include <", "compilation terminated."),
    ),
    Rule(
        "download",
        r"error: cannot download .* from any mirror",
        ("curl: (", "Warning: Problem"),
    ),
    Rule(
        "hash",
        r"error: hash mismatch in fixed-output derivation",
        ("specified: ", "got: "),
    ),
    Rule(
        "patch",
        r"(hunks? FAILED -- saving rejects|\d+ out of \d+ hunk ignored)",
        ("Hunk #", "applying patch"),
    ),
    Rule(
        "patch",
        r"(hunks ignored -- saving rejects|\d+ out of \d+ hunk ignored)",
        ("Skipping patch", "applying patch"),
    ),
    Rule("substitute", r"substituteStream\(\) in derivation", ("ERROR:",)),
    Rule("substitute", r"substitute\(\): ERROR:", ("does not exist",)),
    Rule("missingFile", r"No such file or directory", ("error:",)),
    Rule(
        "symlinks",
        r"ERROR: noBrokenSymlinks: found \d+ dangling symlinks, \d+ reflexive "
        r"symlinks and \d+ unreadable symlinks",
    ),
    # Hydra's side, not the package's.
    Rule(
        "disk",
        r"note: build failure may have been caused by lack of free disk space",
    ),
)
_COMPILED = tuple((rule, re.compile(rule.pattern)) for rule in RULES)
# Any error at all: the line to show for a log no rule explains (a Python
# exception, "error:", "fatal:").
ANY_ERROR = re.compile(r"(?i)(error:|exception:|fatal:)")


def excerpt(lines, at):
    """The lines that say why: lines[at] and up to EXCERPT_LINES - 1 after
    it, each cut to EXCERPT_WIDTH characters, without trailing blanks."""
    kept = [line.rstrip()[:EXCERPT_WIDTH] for line in lines[at : at + EXCERPT_LINES]]
    while kept and not kept[-1]:
        kept.pop()
    return "\n".join(kept)


def classify(log):
    """(reason, excerpt) for a failed build's log (text): the first rule
    whose pattern is on some line, nearest the end, and whose hints are all
    in the log; else "other", with the last line that has an error, or the
    log's last lines."""
    text = ANSI.sub("", log)
    lines = text.splitlines()
    for rule, pattern in _COMPILED:
        if any(hint not in text for hint in rule.hints):
            continue
        for at in range(len(lines) - 1, -1, -1):
            if pattern.search(lines[at]):
                return rule.reason, excerpt(lines, at)
    for at in range(len(lines) - 1, -1, -1):
        if ANY_ERROR.search(lines[at]):
            return OTHER, excerpt(lines, at)
    # No line says error: how it ended, its last lines.
    last = max((at for at, line in enumerate(lines) if line.strip()), default=None)
    if last is None:
        return OTHER, ""
    return OTHER, excerpt(lines, max(0, last - EXCERPT_LINES + 1))


def wanted(rows, found):
    """The failed rows whose log to read: not read for this build as it
    finished (found: read's)."""
    return [
        r
        for r in rows
        if r["status"] == "failed"
        and r["build"]
        and (found.get(r["build"]) or [None])[0] != r["finished"]
    ]


def columns(row, found):
    """A row's failedBecause and failedExcerpt: what its log said, for a
    failed build read as it finished; else empty."""
    seen = found.get(row["build"]) if row["status"] == "failed" else None
    if not seen or seen[0] != row["finished"]:
        return {"failedBecause": "", "failedExcerpt": ""}
    return {"failedBecause": seen[1], "failedExcerpt": seen[2]}


def counts(rows):
    """{"known", "pending", "by": {reason: failed jobs}} among the failed
    rows, from their columns."""
    failed = [r for r in rows if r["status"] == "failed"]
    by = {}
    for r in failed:
        if r.get("failedBecause"):
            by[r["failedBecause"]] = by.get(r["failedBecause"], 0) + 1
    known = sum(by.values())
    return {
        "known": known,
        "pending": len(failed) - known,
        "by": dict(sorted(by.items(), key=lambda kv: (-kv[1], kv[0]))),
    }


def read(directory):
    """reasons.json: {build id: [finished, reason, excerpt]}, or {}."""
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
