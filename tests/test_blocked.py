"""Which dependency a build failed because of (blocked.py), and reading
them as the digest runs (cli.look_up_blocked, cli.publish)."""

import csv
import gzip
import io
import json
import os
import tempfile
import time
import unittest
from unittest import mock

from nixkeeper_hydra import blocked, branches, cli, digest, hydra

HERE = os.path.dirname(__file__)


def fixture(build_id):
    """A build's page as Hydra had it (its build steps only)."""
    with open(os.path.join(HERE, f"build-{build_id}.html")) as f:
        return f.read()


def row(attr, status, build_id, name=None, system="x86_64-linux"):
    return {
        "attr": attr,
        "system": system,
        "build": build_id,
        "status": status,
        "finished": "2026-10-06T00:00:00+00:00",
        "name": name or f"{attr}-1.0",
        "lastSuccessBuild": "",
        "lastSuccessAt": "",
        "lastSuccessName": "",
    }


class FailedSteps(unittest.TestCase):
    def test_propagated_from_another_build(self):
        # Two failed steps building the same thing: once, with its build.
        self.assertEqual(
            blocked.failed_steps(fixture(347086771)),
            [["openbabel-3.1.1-unstable-2024-12-21", 347421174]],
        )

    def test_the_derivation_not_an_output(self):
        # The step built mupdf-1.27.2-bin, -dev, ...: its derivation's name.
        self.assertEqual(
            blocked.failed_steps(fixture(347815300)), [["mupdf-1.27.2", 347816876]]
        )

    def test_a_download_no_package_builds(self):
        self.assertEqual(
            blocked.failed_steps(fixture(347089138)), [["SHA256SUMS.asc", 347308438]]
        )

    def test_failed_in_the_build_itself(self):
        # No other build to point at: the step's own log only.
        step = (
            '<div id="tabs-buildsteps"><table><tbody><tr><td>1</td>'
            "<td>Build of <tt>/nix/store/" + "a" * 32 + "-foo-1.0-dist</tt></td>"
            "<td>n/a</td><td>m</td>"
            '<td class="step-status"><span class="error">Failed</span>: '
            '(<a href="https://hydra.nixos.org/build/1/step/1/log">log</a>)</td>'
            "</tr></tbody></table></div>"
        )
        self.assertEqual(blocked.failed_steps(step), [["foo-1.0-dist", None]])

    def test_no_steps(self):
        self.assertEqual(blocked.failed_steps("<html>gone</html>"), [])


class Blocker(unittest.TestCase):
    ROWS = [
        row("openbabel", "failed", "347421174", "openbabel-3.1.1-unstable-2024-12-21"),
        row("mupdf", "failed", "9", "mupdf-1.27.2"),
        row("python3Packages.mupdf", "failed", "10", "mupdf-1.27.2"),
        row("mupdf", "failed", "11", "mupdf-1.27.2", system="aarch64-darwin"),
    ]

    def setUp(self):
        self.by_build, self.by_name = blocked.names(self.ROWS)

    def name(self, step, system="x86_64-linux"):
        return blocked.blocker(step, system, self.by_build, self.by_name)

    def test_by_its_build_when_that_job_builds_it(self):
        self.assertEqual(
            self.name(["openbabel-3.1.1-unstable-2024-12-21", 347421174]), "openbabel"
        )
        # The build it was first seen failing in is another package's: not
        # the blocker (pdfding needed the same broken pypdf).
        self.assertEqual(self.name(["anything-2.0", 347421174]), "anything-2.0")

    def test_a_generic_name_isnt_a_package(self):
        rows = [*self.ROWS, row("nixos-grub2-theme", "ok", "12", "source")]
        by_build, by_name = blocked.names(rows)
        self.assertEqual(
            blocked.blocker(["source", 5], "x86_64-linux", by_build, by_name), "source"
        )

    def test_by_name_on_the_same_platform_without_its_output(self):
        # The top-level attribute, not the set's that builds the same.
        self.assertEqual(self.name(["mupdf-1.27.2-bin", None]), "mupdf")
        self.assertEqual(self.name(["mupdf-1.27.2", None], "aarch64-darwin"), "mupdf")
        self.assertEqual(
            self.name(["mupdf-1.27.2", None], "aarch64-linux"), "mupdf-1.27.2"
        )

    def test_else_the_name(self):
        self.assertEqual(self.name(["SHA256SUMS.asc", None]), "SHA256SUMS.asc")

    def test_without_output(self):
        self.assertEqual(
            blocked.without_output("python3.14-foo-1.0-dist"), "python3.14-foo-1.0"
        )
        self.assertEqual(blocked.without_output("foo-1.0"), "foo-1.0")
        self.assertEqual(blocked.without_output("hello"), "hello")


class LookUp(unittest.TestCase):
    ROWS = [
        row("openbabel", "failed", "347421174", "openbabel-3.1.1-unstable-2024-12-21"),
        row("avogadro", "dependency", "347086771"),
        row("adenum", "dependency", "347815300"),
        row("ok", "ok", "1"),
    ]

    def test_reads_whats_new_retries_failures_drops_the_gone(self):
        found = {"5": [["gone-1.0", None]]}  # no longer a dependency failure
        pages = {"347086771": fixture(347086771)}

        def page_of(build):
            if build not in pages:
                raise OSError("down")
            return pages[build]

        with (
            mock.patch.object(hydra, "build_page", side_effect=page_of),
            mock.patch("sys.stderr", io.StringIO()),
        ):
            read, pending = cli.look_up_blocked(self.ROWS, found, time.monotonic())
        self.assertEqual((read, pending), (1, 1))  # adenum's: next run
        self.assertEqual(set(found), {"347086771"})

    def test_capped_a_run(self):
        with (
            mock.patch.object(cli, "MAX_PAGES", 1),
            mock.patch.object(hydra, "build_page", return_value=fixture(347815300)),
        ):
            read, pending = cli.look_up_blocked(self.ROWS, {}, time.monotonic())
        self.assertEqual((read, pending), (1, 1))

    def test_published_as_a_column(self):
        found = {
            "347086771": blocked.failed_steps(fixture(347086771)),
            "347815300": blocked.failed_steps(fixture(347815300)),
        }
        with tempfile.TemporaryDirectory() as d, mock.patch("builtins.print"):
            cli.publish(d, [dict(r) for r in self.ROWS], found, {"eval": 8}, 2, 0)
            with gzip.open(os.path.join(d, digest.BUILDS), "rt") as f:
                written = {r["attr"]: r["blockedBy"] for r in csv.DictReader(f)}
            with open(os.path.join(d, digest.META)) as f:
                meta = json.load(f)
            self.assertEqual(blocked.read(d), found)
        self.assertEqual(
            written,
            {
                "openbabel": "",
                "avogadro": "openbabel",
                "adenum": "mupdf-1.27.2",
                "ok": "",
            },
        )
        self.assertEqual(meta["blocked"], {"known": 2, "pending": 0})

    def test_a_run_with_nothing_new_still_reads_them(self):
        with tempfile.TemporaryDirectory() as d:
            digest.write(
                d,
                [dict(r) for r in self.ROWS],
                {"eval": 8, "fetchedAt": "2026-10-06T00:00:00+00:00"},
            )
            with (
                mock.patch.object(hydra, "latest_eval", return_value=8),
                mock.patch.object(branches, "update_all"),
                mock.patch.object(hydra, "download_eval") as dl,
                mock.patch.object(cli, "due", return_value=None),
                mock.patch.object(hydra, "build_page", return_value=fixture(347815300)),
                mock.patch("builtins.print"),
            ):
                self.assertEqual(cli.main([d]), 0)
            dl.assert_not_called()
            rows, meta = digest.read(d)
            self.assertEqual(
                rows[("adenum", "x86_64-linux")]["blockedBy"], "mupdf-1.27.2"
            )
            self.assertEqual(meta["eval"], 8)  # the same evaluation, still


if __name__ == "__main__":
    unittest.main()
