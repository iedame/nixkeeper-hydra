import gzip
import json
import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from unittest import mock

from nixkeeper_hydra import cli, digest, hydra, page

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
EMPTY = {"lastSuccessBuild": "", "lastSuccessAt": "", "lastSuccessName": ""}


def build(attr, status, build_id, finished="2026-10-03T00:00:00+00:00", name=None):
    return {
        "attr": attr,
        "system": "x86_64-linux",
        "build": build_id,
        "status": status,
        "finished": "" if status == "queued" else finished,
        "name": name or f"{attr}-1.0",
    }


class Merge(unittest.TestCase):
    def test_last_success(self):
        before = {
            ("a", "x86_64-linux"): {**build("a", "ok", "10", name="a-1.0"), **EMPTY},
            ("b", "x86_64-linux"): {
                **build("b", "failed", "20"),
                "lastSuccessBuild": "5",
                "lastSuccessAt": "2026-09-01T00:00:00+00:00",
                "lastSuccessName": "b-0.9",
            },
        }
        rows = digest.merge(
            [
                build("a", "failed", "11", name="a-1.1"),  # was ok: that's it
                build("b", "dependency", "21"),  # carried on
                build("c", "failed", "30"),  # never seen: unknown
                build("d", "ok", "40"),  # its own last success
            ],
            before,
        )
        self.assertEqual(
            [(r["attr"], r["lastSuccessBuild"], r["lastSuccessName"]) for r in rows],
            [("a", "10", "a-1.0"), ("b", "5", "b-0.9"), ("c", "", ""), ("d", "", "")],
        )
        self.assertEqual(rows[0]["lastSuccessAt"], "2026-10-03T00:00:00+00:00")

    def test_queued_keeps_the_newest_finished_build(self):
        before = {
            ("a", "x86_64-linux"): {**build("a", "failed", "10"), **EMPTY},
            ("q", "x86_64-linux"): {**build("q", "queued", "11"), **EMPTY},
        }
        rows = digest.merge(
            [
                build("a", "queued", "12"),  # still building: the last one holds
                build("n", "queued", "13"),  # new to the digest: queued
                build("q", "queued", "14"),  # never finished yet: queued
            ],
            before,
        )
        self.assertEqual(
            [(r["attr"], r["build"], r["status"]) for r in rows],
            [("a", "10", "failed"), ("n", "13", "queued"), ("q", "14", "queued")],
        )


class LatestEval(unittest.TestCase):
    def test_the_newest_listed(self):
        html = (
            b'<a href="https://hydra.nixos.org/eval/1829817">1829817</a>'
            b'<a href="https://hydra.nixos.org/eval/1829803">1829803</a>'
        )
        resp = mock.MagicMock()
        resp.__enter__.return_value.read.return_value = html
        with mock.patch("urllib.request.urlopen", return_value=resp) as urlopen:
            self.assertEqual(hydra.latest_eval(), 1829817)
        self.assertEqual(
            urlopen.call_args.args[0].full_url,
            "https://hydra.nixos.org/jobset/nixpkgs/unstable/evals",
        )

    def test_none_listed(self):
        resp = mock.MagicMock()
        resp.__enter__.return_value.read.return_value = b"<html></html>"
        with (
            mock.patch("urllib.request.urlopen", return_value=resp),
            self.assertRaises(OSError),
        ):
            hydra.latest_eval()


class WriteRead(unittest.TestCase):
    def test_round_trip_and_same_bytes(self):
        rows = digest.merge([build("b", "ok", "2"), build("a", "queued", "1")], {})
        meta = {"eval": 7, "fetchedAt": NOW.isoformat()}
        with tempfile.TemporaryDirectory() as d:
            digest.write(d, rows, meta)
            with open(os.path.join(d, digest.BUILDS), "rb") as f:
                first = f.read()
            digest.write(d, rows, meta)
            with open(os.path.join(d, digest.BUILDS), "rb") as f:
                self.assertEqual(f.read(), first)
            read, read_meta = digest.read(d)
            with gzip.open(os.path.join(d, digest.BUILDS), "rt") as f:
                header = f.readline().strip()
        self.assertEqual(header, ",".join(digest.COLUMNS))
        self.assertEqual(read_meta, {"format": digest.FORMAT, **meta})
        self.assertEqual(read["a", "x86_64-linux"]["status"], "queued")
        self.assertEqual(list(read), [("a", "x86_64-linux"), ("b", "x86_64-linux")])

    def test_none_yet(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(digest.read(d), ({}, {}))


class Due(unittest.TestCase):
    def meta(self, hours_ago, queued=0, eval_id=7):
        fetched = (NOW - timedelta(hours=hours_ago)).isoformat()
        return {"eval": eval_id, "fetchedAt": fetched, "counts": {"queued": queued}}

    def test_due(self):
        self.assertEqual(cli.due(7, {}, NOW), "no digest yet")
        self.assertIn("evaluation 8", cli.due(8, self.meta(1), NOW))
        self.assertIsNone(cli.due(7, self.meta(1, queued=5), NOW))
        self.assertIn("still queued", cli.due(7, self.meta(6, queued=5), NOW))
        self.assertIsNone(cli.due(7, self.meta(23), NOW))
        self.assertIn("a day", cli.due(7, self.meta(24), NOW))


class Main(unittest.TestCase):
    def run_main(self, d, builds, latest=8):
        def download(eval_id, path):
            with open(path, "w") as f:
                f.write("page")

        with (
            mock.patch.object(hydra, "latest_eval", return_value=latest),
            mock.patch.object(hydra, "download_eval", side_effect=download) as dl,
            mock.patch.object(page, "parse", return_value=(builds, "abc")),
            mock.patch.object(cli, "MIN_BUILDS", 2),
            mock.patch("builtins.print"),
        ):
            return cli.main([d]), dl

    def test_writes_the_digest(self):
        with tempfile.TemporaryDirectory() as d:
            code, dl = self.run_main(
                d, [build("a", "ok", "1"), build("b", "failed", "2")]
            )
            dl.assert_called_once()
            self.assertEqual(code, 0)
            with open(os.path.join(d, digest.META)) as f:
                meta = json.load(f)
            self.assertEqual(
                (meta["eval"], meta["revision"], meta["builds"]), (8, "abc", 2)
            )
            self.assertEqual(meta["counts"], {"failed": 1, "ok": 1})
            # The same evaluation an hour later: nothing new, not read again.
            code, dl = self.run_main(d, [])
            dl.assert_not_called()

    def test_too_few_builds_are_not_published(self):
        with tempfile.TemporaryDirectory() as d:
            code, _ = self.run_main(d, [build("a", "ok", "1")])
            self.assertEqual(code, 1)
            self.assertEqual(os.listdir(d), [])
