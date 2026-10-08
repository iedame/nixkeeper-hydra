"""Why failed builds failed, from their logs (reasons.py,
cli.look_up_reasons, hydra.build_drv and hydra.build_log)."""

import io
import tempfile
import time
import unittest
import urllib.error
from unittest import mock

from nixkeeper_hydra import cli, digest, hydra, reasons

FINISHED = "2026-10-06T00:00:00+00:00"


def row(attr, status, build_id, finished=FINISHED):
    return {
        "attr": attr,
        "system": "x86_64-linux",
        "build": build_id,
        "status": status,
        "finished": finished,
        "name": f"{attr}-2.0",
        "lastSuccessBuild": "",
        "lastSuccessAt": "",
        "lastSuccessName": "",
    }


CMAKE4 = """\
-- The C compiler identification is GNU 14.3.0
CMake Error at CMakeLists.txt:1 (cmake_minimum_required):
  Compatibility with CMake < 3.5 has been removed from CMake.

  Update the VERSION argument <min> value.  Or, use the <min>...<max> syntax
  to tell CMake that the project requires at least <min> but has been updated
  to work with policies introduced by <max> or earlier.

  Or, add -DCMAKE_POLICY_VERSION_MINIMUM=3.5 to try configuring anyway.

-- Configuring incomplete, errors occurred!
"""

RUST = """\
\x1b[1m\x1b[91merror\x1b[0m\x1b[1m: cannot find `rustc_layout`\x1b[0m
\x1b[1m\x1b[91merror\x1b[0m: could not compile `rustix` (lib) due to 4 previous errors
\x1b[1m\x1b[33mwarning\x1b[0m: build failed, waiting for other jobs to finish...
"""

HASH = """\
error: hash mismatch in fixed-output derivation '/nix/store/abc-source.drv':
         specified: sha256-AAAA
            got:    sha256-BBBB
"""

PATCH = """\
applying patch /nix/store/xyz-fix-build.patch
patching file src/main.c
Hunk #1 FAILED at 12.
1 out of 1 hunk FAILED -- saving rejects to file src/main.c.rej
"""


class Classify(unittest.TestCase):
    def test_rules(self):
        self.assertEqual(reasons.classify(CMAKE4)[0], "cmake4")
        self.assertEqual(reasons.classify(HASH)[0], "hash")
        self.assertEqual(reasons.classify(PATCH)[0], "patch")

    def test_colours_dropped_and_the_lines_that_say_so(self):
        reason, lines = reasons.classify(RUST)
        self.assertEqual(reason, "compile")
        self.assertEqual(
            lines,
            "error: could not compile `rustix` (lib) due to 4 previous errors\n"
            "warning: build failed, waiting for other jobs to finish...",
        )

    def test_hints_must_all_be_there(self):
        """A CMake error without CMake 4's words is CMake's configure error,
        or nothing particular."""
        plain = "CMake Error at CMakeLists.txt:5 (find_package):\n  no Foo\n"
        self.assertEqual(reasons.classify(plain)[0], "other")
        configure = (
            plain
            + "cmake flags: -GNinja\n-- Configuring incomplete, errors occurred!\n"
        )
        self.assertEqual(reasons.classify(configure)[0], "cmake")

    def test_the_first_rule_in_order_wins(self):
        """Both a compile error and a missing file: the earlier rule says why."""
        both = "foo.c:3:1: error: oops\nerror: x: No such file or directory\n"
        self.assertEqual(reasons.classify(both)[0], "compile")

    def test_other_shows_the_last_error(self):
        log = "building\nerror: first\nmore\nerror: builder failed\n"
        self.assertEqual(reasons.classify(log), ("other", "error: builder failed"))
        self.assertEqual(reasons.classify(""), ("other", ""))
        # No line says error: how it ended.
        ended = "a\nb\n\nsed: no input files\n"
        self.assertEqual(reasons.classify(ended), ("other", "b\n\nsed: no input files"))

    def test_excerpt_cut(self):
        long = "x" * 500
        log = f"a.c:1:1: error: {long}\n" + "\n".join(f"line {i}" for i in range(9))
        reason, lines = reasons.classify(log)
        self.assertEqual(reason, "compile")
        first, *rest = lines.split("\n")
        self.assertEqual(len(first), reasons.EXCERPT_WIDTH)
        self.assertEqual(len(rest), reasons.EXCERPT_LINES - 1)


class Bookkeeping(unittest.TestCase):
    def test_wanted_failed_not_read_for_this_finish(self):
        rows = [
            row("ok", "ok", "1"),
            row("dep", "dependency", "2"),
            row("read", "failed", "3"),
            row("restarted", "failed", "4", finished="2026-10-07T00:00:00+00:00"),
            row("new", "failed", "5"),
        ]
        found = {"3": [FINISHED, "hash", ""], "4": [FINISHED, "patch", ""]}
        self.assertEqual(
            [r["attr"] for r in reasons.wanted(rows, found)], ["restarted", "new"]
        )

    def test_columns_and_counts(self):
        rows = [row("a", "failed", "1"), row("b", "failed", "2"), row("c", "ok", "3")]
        found = {"1": [FINISHED, "hash", "error: hash mismatch"]}
        for r in rows:
            r.update(reasons.columns(r, found))
        self.assertEqual(rows[0]["failedBecause"], "hash")
        self.assertEqual(rows[0]["failedExcerpt"], "error: hash mismatch")
        self.assertEqual(rows[1]["failedBecause"], "")
        self.assertEqual(
            reasons.counts(rows), {"known": 1, "pending": 1, "by": {"hash": 1}}
        )


class LookUp(unittest.TestCase):
    def test_reads_classifies_and_remembers(self):
        rows = [row("a", "failed", "1"), row("b", "failed", "2"), row("c", "ok", "3")]
        found = {"9": [FINISHED, "hash", ""]}  # a build no longer failing
        logs = {"/nix/store/a.drv": HASH, "/nix/store/b.drv": None}
        with (
            mock.patch.object(
                hydra,
                "build_drv",
                side_effect=lambda b: f"/nix/store/{'ab'[int(b) - 1]}.drv",
            ),
            mock.patch.object(hydra, "build_log", side_effect=logs.get),
        ):
            self.assertEqual(cli.look_up_reasons(rows, found, time.monotonic()), 2)
        self.assertEqual(found["1"][:2], [FINISHED, "hash"])
        self.assertEqual(found["2"], [FINISHED, reasons.NO_LOG, ""])
        self.assertNotIn("9", found)

    def test_at_most_so_many_and_gives_up_on_failures(self):
        rows = [row(f"p{i}", "failed", str(i)) for i in range(20)]
        with (
            mock.patch.object(cli, "MAX_LOGS", 3),
            mock.patch.object(hydra, "build_drv", return_value="/nix/store/x.drv"),
            mock.patch.object(hydra, "build_log", return_value=HASH) as read,
        ):
            cli.look_up_reasons(rows, {}, time.monotonic())
        self.assertEqual(read.call_count, 3)
        with (
            mock.patch.object(hydra, "build_drv", side_effect=OSError("down")) as asked,
            mock.patch("sys.stderr", io.StringIO()),
        ):
            self.assertEqual(cli.look_up_reasons(rows, {}, time.monotonic()), 0)
        self.assertEqual(asked.call_count, cli.MAX_FAILURES_IN_A_ROW)

    def test_published_with_counts_and_the_cache(self):
        rows = [row("a", "failed", "1"), row("b", "failed", "2")]
        because = {"1": [FINISHED, "patch", "Hunk #1 FAILED"]}
        with tempfile.TemporaryDirectory() as d, mock.patch("builtins.print"):
            cli.publish(d, rows, {}, {"eval": 8}, 0, 0, {}, 0, because)
            written, meta = digest.read(d)
            self.assertEqual(reasons.read(d), because)
        self.assertEqual(written[("a", "x86_64-linux")]["failedBecause"], "patch")
        self.assertEqual(
            written[("a", "x86_64-linux")]["failedExcerpt"], "Hunk #1 FAILED"
        )
        self.assertEqual(
            meta["reasons"], {"known": 1, "pending": 1, "by": {"patch": 1}}
        )


class Hydra(unittest.TestCase):
    def test_derivation_and_log(self):
        answer = io.BytesIO(
            b'{"id": 1, "drvpath": "/nix/store/abc-aerogramme-0.3.0.drv"}'
        )
        with (
            mock.patch.object(hydra.time, "sleep"),
            mock.patch.object(hydra.urllib.request, "urlopen", return_value=answer),
        ):
            self.assertEqual(hydra.build_drv(1), "/nix/store/abc-aerogramme-0.3.0.drv")
        log = io.BytesIO(b"0123456789" * 10)
        with (
            mock.patch.object(hydra.time, "sleep"),
            mock.patch.object(hydra, "LOG_KEEP", 25),
            mock.patch.object(hydra.urllib.request, "urlopen", return_value=log) as get,
        ):
            self.assertEqual(
                hydra.build_log("/nix/store/abc-x.drv"), "5678901234567890123456789"
            )
        self.assertTrue(get.call_args.args[0].full_url.endswith("/log/abc-x.drv"))

    def test_no_log_and_other_failures(self):
        gone = urllib.error.HTTPError("u", 404, "Not Found", {}, io.BytesIO(b""))
        with (
            mock.patch.object(hydra.time, "sleep"),
            mock.patch.object(hydra.urllib.request, "urlopen", side_effect=gone),
        ):
            self.assertIsNone(hydra.build_log("/nix/store/abc-x.drv"))
        other = urllib.error.HTTPError("u", 502, "Bad Gateway", {}, io.BytesIO(b""))
        with (
            mock.patch.object(hydra.time, "sleep"),
            mock.patch.object(hydra.urllib.request, "urlopen", side_effect=other),
            self.assertRaises(urllib.error.HTTPError),
        ):
            hydra.build_log("/nix/store/abc-x.drv")
        no_drv = io.BytesIO(b'{"id": 1}')
        with (
            mock.patch.object(hydra.time, "sleep"),
            mock.patch.object(hydra.urllib.request, "urlopen", return_value=no_drv),
            self.assertRaises(OSError),
        ):
            hydra.build_drv(1)


if __name__ == "__main__":
    unittest.main()
