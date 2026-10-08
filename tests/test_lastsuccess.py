"""A failing job's last successful build, asked of Hydra for those the
digest doesn't know (lastsuccess.py, cli.look_up_last_success,
hydra.last_success)."""

import io
import tempfile
import time
import unittest
import urllib.error
from unittest import mock

from nixkeeper_hydra import cli, digest, hydra, lastsuccess


def row(attr, status, build_id, last=""):
    return {
        "attr": attr,
        "system": "x86_64-linux",
        "build": build_id,
        "status": status,
        "finished": "2026-10-06T00:00:00+00:00",
        "name": f"{attr}-2.0",
        "lastSuccessBuild": last,
        "lastSuccessAt": "2026-07-07T09:45:16+00:00" if last else "",
        "lastSuccessName": f"{attr}-1.0" if last else "",
    }


WARZONE = {
    "build": "333199176",
    "at": "2026-07-07T09:45:16+00:00",
    "name": "warzone2100-4.7.0",
}


class Wanted(unittest.TestCase):
    def test_only_failing_without_one_known(self):
        rows = [
            row("ok", "ok", "1"),
            row("known", "failed", "2", last="9"),
            row("ask", "failed", "3"),
            row("blocked", "dependency", "4"),
            row("never", "unfinished", "5"),
            row("never-again", "failed", "6"),  # rebuilt since "never"
        ]
        never = {"never x86_64-linux": "5", "never-again x86_64-linux": "1"}
        self.assertEqual(
            [r["attr"] for r in lastsuccess.wanted(rows, never)],
            ["ask", "blocked", "never-again"],
        )
        self.assertEqual(
            lastsuccess.counts(rows, never), {"known": 1, "never": 1, "pending": 3}
        )


class LookUp(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch("sys.stderr", io.StringIO())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_fills_the_row_and_remembers_never(self):
        rows = [
            row("warzone2100", "failed", "347295012"),
            row("hopeless", "failed", "7"),
        ]
        never = {}
        answers = {"warzone2100": WARZONE, "hopeless": None}
        with mock.patch.object(
            hydra, "last_success", side_effect=lambda attr, system: answers[attr]
        ):
            self.assertEqual(cli.look_up_last_success(rows, never, time.monotonic()), 2)
        self.assertEqual(
            {k: rows[0][k] for k in digest.COLUMNS if k.startswith("lastSuccess")},
            {
                "lastSuccessBuild": "333199176",
                "lastSuccessAt": "2026-07-07T09:45:16+00:00",
                "lastSuccessName": "warzone2100-4.7.0",
            },
        )
        self.assertEqual(never, {"hopeless x86_64-linux": "7"})
        # Asked once: the next run has nothing to ask.
        self.assertEqual(lastsuccess.wanted(rows, never), [])

    def test_capped_and_stopped(self):
        rows = [row(f"p{i}", "failed", str(i)) for i in range(20)]
        with (
            mock.patch.object(cli, "MAX_LOOKUPS", 3),
            mock.patch.object(hydra, "last_success", return_value=None) as asked,
        ):
            cli.look_up_last_success(rows, {}, time.monotonic())
        self.assertEqual(asked.call_count, 3)
        with mock.patch.object(
            hydra, "last_success", side_effect=OSError("down")
        ) as asked:
            self.assertEqual(cli.look_up_last_success(rows, {}, time.monotonic()), 0)
        self.assertEqual(asked.call_count, cli.MAX_FAILURES_IN_A_ROW)

    def test_published_with_counts_and_the_cache(self):
        rows = [
            row("a", "failed", "1", last="9"),
            row("b", "failed", "2"),
            row("ok", "ok", "3"),
        ]
        never = {"b x86_64-linux": "2", "gone x86_64-linux": "5"}
        with tempfile.TemporaryDirectory() as d, mock.patch("builtins.print"):
            cli.publish(d, rows, {}, {"eval": 8}, 0, 0, never, 1)
            _, meta = digest.read(d)
            # A job no longer failing (gone) isn't remembered any more.
            self.assertEqual(lastsuccess.read(d), {"b x86_64-linux": "2"})
        self.assertEqual(meta["lastSuccess"], {"known": 1, "never": 1, "pending": 0})


class Hydra(unittest.TestCase):
    def test_answer_and_never(self):
        build = io.BytesIO(
            b'{"id": 333199176, "stoptime": 1783417516, "nixname": "warzone2100-4.7.0"}'
        )
        with (
            mock.patch.object(hydra.time, "sleep"),
            mock.patch.object(hydra.urllib.request, "urlopen", return_value=build),
        ):
            self.assertEqual(hydra.last_success("warzone2100", "x86_64-linux"), WARZONE)
        none = urllib.error.HTTPError(
            "u",
            404,
            "Not Found",
            {},
            io.BytesIO(b'{"error":"There is no successful build to redirect to."}'),
        )
        with (
            mock.patch.object(hydra.time, "sleep"),
            mock.patch.object(hydra.urllib.request, "urlopen", side_effect=none),
        ):
            self.assertIsNone(hydra.last_success("hopeless", "x86_64-linux"))
        other = urllib.error.HTTPError("u", 502, "Bad Gateway", {}, io.BytesIO(b""))
        with (
            mock.patch.object(hydra.time, "sleep"),
            mock.patch.object(hydra.urllib.request, "urlopen", side_effect=other),
            self.assertRaises(urllib.error.HTTPError),
        ):
            hydra.last_success("p", "x86_64-linux")


if __name__ == "__main__":
    unittest.main()
