import io
import tempfile
import time
import unittest
from datetime import UTC, datetime, timedelta
from unittest import mock

from nixkeeper_hydra import branches, cli, hydra, page

NOW = datetime(2026, 10, 7, 12, 17, tzinfo=UTC)
# As page.parse gives them, from haskell-updates' evaluation 1829685.
BUILDS = [
    {
        "attr": "haskellPackages.Cabal-hooks",
        "system": "x86_64-linux",
        "build": "347795500",
        "status": "ok",
        "finished": "2026-09-30T16:00:00+00:00",
        "name": "Cabal-hooks-3.18",
    },
    {
        "attr": "haskellPackages.Agda",
        "system": "x86_64-linux",
        "build": "347795412",
        "status": "failed",
        "finished": "2026-09-30T15:00:00+00:00",
        "name": "Agda-2.8.0.2",
    },
    {
        "attr": "haskellPackages.new",
        "system": "x86_64-linux",
        "build": "347795999",
        "status": "queued",
        "finished": "",
        "name": "new-1.0",
    },
]


def saved(eval_id, path):
    """What download_eval does: the page, saved (page.parse is a stand-in)."""
    with open(path, "w") as f:
        f.write("")


class Update(unittest.TestCase):
    def setUp(self):
        for patcher in (
            mock.patch("builtins.print"),
            mock.patch("sys.stderr", io.StringIO()),
            mock.patch.dict(
                branches.BRANCHES, {"haskell-updates": ("nixpkgs/haskell-updates", 1)}
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_update(self, d, latest, builds=BUILDS, now=NOW):
        with (
            mock.patch.object(
                hydra, "latest_eval_dated", return_value=(latest, None)
            ) as asked,
            mock.patch.object(hydra, "download_eval", side_effect=saved) as downloaded,
            mock.patch.object(page, "parse", return_value=(builds, "4e9d3032")),
        ):
            wrote = branches.update(d, "haskell-updates", now, cli.due)
        asked.assert_called_once_with("nixpkgs/haskell-updates")
        return wrote, downloaded.called

    def test_written_sorted_with_its_versions(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.run_update(d, 1829685), (True, True))
            found = branches.read(d, "haskell-updates")
        self.assertEqual(
            (found["eval"], found["revision"], found["builds"]),
            (1829685, "4e9d3032", 3),
        )
        self.assertEqual(found["counts"], {"failed": 1, "ok": 1, "queued": 1})
        self.assertEqual(
            found["columns"], ["attr", "system", "build", "status", "name"]
        )
        self.assertEqual(
            found["jobs"][0],
            [
                "haskellPackages.Agda",
                "x86_64-linux",
                "347795412",
                "failed",
                "Agda-2.8.0.2",
            ],
        )

    def test_read_again_only_when_due(self):
        with tempfile.TemporaryDirectory() as d:
            self.run_update(d, 1829685)
            # The same evaluation an hour later: nothing new.
            later = NOW + timedelta(hours=1)
            self.assertEqual(self.run_update(d, 1829685, now=later), (False, False))
            # Its queued build, 6 hours later: read again.
            later = NOW + cli.QUEUED_EVERY
            self.assertEqual(self.run_update(d, 1829685, now=later), (True, True))
            # A new evaluation: at once.
            self.assertEqual(self.run_update(d, 1829700, now=later), (True, True))

    def test_a_short_page_or_a_failure_keeps_the_last(self):
        with tempfile.TemporaryDirectory() as d:
            self.run_update(d, 1829685)
            before = branches.read(d, "haskell-updates")
            with (
                mock.patch.dict(
                    branches.BRANCHES,
                    {"haskell-updates": ("nixpkgs/haskell-updates", 5)},
                ),
                mock.patch.object(
                    hydra,
                    "latest_eval_dated",
                    return_value=(1829700, "2026-10-14T07:18:17Z"),
                ),
                mock.patch.object(hydra, "download_eval"),
                mock.patch.object(page, "parse", return_value=(BUILDS, "x")),
            ):
                branches.update_all(d, NOW, cli.due)
            with mock.patch.object(
                hydra, "latest_eval_dated", side_effect=OSError("down")
            ):
                branches.update_all(d, NOW, cli.due)
            self.assertEqual(branches.read(d, "haskell-updates"), before)


if __name__ == "__main__":
    unittest.main()


class StagingNext(unittest.TestCase):
    """staging-next: all of nixpkgs, kept as its differences from master."""

    def setUp(self):
        for patcher in (
            mock.patch("builtins.print"),
            mock.patch.dict(
                branches.BRANCHES, {"staging-next": ("nixpkgs/staging-next", 1)}
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def job(self, attr, status, name):
        return {
            "attr": attr,
            "system": "x86_64-linux",
            "build": "1",
            "status": status,
            "finished": "",
            "name": name,
        }

    def test_only_what_differs_from_master(self):
        builds = [
            self.job("coreutils", "ok", "coreutils-9.12"),  # updated there
            self.job("bash", "ok", "bash-5.3p15"),  # as on master
            self.job("vim", "failed", "vim-9.2.1164"),  # fails there only
            self.job("new", "ok", "new-1.0"),  # master hasn't it
        ]
        master = {
            ("coreutils", "x86_64-linux"): {"status": "ok", "name": "coreutils-9.11"},
            ("bash", "x86_64-linux"): {"status": "ok", "name": "bash-5.3p15"},
            ("vim", "x86_64-linux"): {"status": "ok", "name": "vim-9.2.1164"},
        }
        with (
            tempfile.TemporaryDirectory() as d,
            mock.patch.object(
                hydra,
                "latest_eval_dated",
                return_value=(1830049, "2026-10-14T07:18:17Z"),
            ),
            mock.patch.object(hydra, "download_eval", side_effect=saved),
            mock.patch.object(page, "parse", return_value=(builds, "4dfbeb6a")),
        ):
            branches.update(d, "staging-next", NOW, cli.due, master, 1830315)
            found = branches.read(d, "staging-next")
        self.assertEqual([job[0] for job in found["jobs"]], ["coreutils", "new", "vim"])
        self.assertEqual(found["evaluatedAt"], "2026-10-14T07:18:17Z")
        self.assertEqual(
            (found["builds"], found["counts"], found["differentFrom"]),
            (4, {"failed": 1, "ok": 3}, 1830315),
        )

    def test_whole_without_masters_digest(self):
        builds = [self.job("bash", "ok", "bash-5.3p15")]
        with (
            tempfile.TemporaryDirectory() as d,
            mock.patch.object(
                hydra,
                "latest_eval_dated",
                return_value=(1830049, "2026-10-14T07:18:17Z"),
            ),
            mock.patch.object(hydra, "download_eval", side_effect=saved),
            mock.patch.object(page, "parse", return_value=(builds, "4dfbeb6a")),
        ):
            branches.update(d, "staging-next", NOW, cli.due, {}, None)
            found = branches.read(d, "staging-next")
        self.assertEqual(len(found["jobs"]), 1)
        self.assertNotIn("differentFrom", found)


class EvalDate(unittest.TestCase):
    def test_from_the_list_of_evaluations(self):
        # A row of https://hydra.nixos.org/jobset/nixpkgs/staging-next/evals
        html = (
            '<tr><td><a class="row-link" href="https://hydra.nixos.org/eval/'
            '1830224">1830224</a></td>          <td class="nowrap"><time '
            'data-timestamp="1791962297" datetime="2026-10-14T07:18:17Z" '
            'title="2026-10-14 07:18:17 (UTC)" class="date is-relative">2d ago'
            '</time></td></tr><tr><td><a class="row-link" href="https://'
            'hydra.nixos.org/eval/1830155">1830155</a></td><td class="nowrap">'
            '<time datetime="2026-10-13T05:41:52Z">3d ago</time></td></tr>'
        )
        with mock.patch.object(hydra, "_evals_page", return_value=html):
            self.assertEqual(
                hydra.latest_eval_dated("nixpkgs/staging-next"),
                (1830224, "2026-10-14T07:18:17Z"),
            )
            self.assertEqual(hydra.latest_eval("nixpkgs/staging-next"), 1830224)
        with mock.patch.object(hydra, "_evals_page", return_value='/eval/7">7<'):
            self.assertEqual(hydra.latest_eval_dated(), (7, None))


class StagingNextBlockers(unittest.TestCase):
    """Which dependency each staging-next job fails because of, for those
    that build on master (cli.look_up_staging_next_blocked)."""

    def setUp(self):
        patcher = mock.patch("builtins.print")
        patcher.start()
        self.addCleanup(patcher.stop)

    def master(self, attr, status, name, build="1"):
        return {
            "attr": attr,
            "system": "x86_64-linux",
            "status": status,
            "name": name,
            "build": build,
        }

    def test_named_and_written(self):
        jobs = [
            # Blocked there, builds on master: read.
            ["blender", "x86_64-linux", "11", "dependency", "blender-5.0.1"],
            # Blocked on master too: master's own blockers say it.
            ["krita", "x86_64-linux", "12", "dependency", "krita-6.0"],
            # Its own failure (staging-next breaks): no page to read.
            ["afew", "x86_64-linux", "13", "failed", "afew-4.0.2"],
            # The blocker's own job there, named by its attribute.
            ["rocmPackages.clang", "x86_64-linux", "99", "failed", "clang-22.0.0-rocm"],
        ]
        master = {
            (r["attr"], r["system"]): r
            for r in (
                self.master("blender", "ok", "blender-5.0.1"),
                self.master("krita", "dependency", "krita-6.0"),
                self.master("afew", "ok", "afew-4.0.2"),
            )
        }
        with tempfile.TemporaryDirectory() as d:
            branches.write(
                d,
                "staging-next",
                {
                    "jobset": "nixpkgs/staging-next",
                    "eval": 1830302,
                    "columns": list(branches.COLUMNS),
                    "jobs": jobs,
                },
            )
            with (
                mock.patch.object(hydra, "build_page", return_value="") as asked,
                mock.patch.object(
                    cli.blocked,
                    "failed_steps",
                    return_value=[["clang-22.0.0-rocm", 99]],
                ),
            ):
                got = cli.look_up_staging_next_blocked(d, master, time.monotonic(), 10)
            self.assertEqual(got, (1, 0))
            asked.assert_called_once_with("11")
            found = branches.read(d, "staging-next")
            # Known now: not read again.
            with mock.patch.object(hydra, "build_page") as again:
                cli.look_up_staging_next_blocked(d, master, time.monotonic(), 10)
            again.assert_not_called()
        self.assertEqual(found["columns"][-1], "blockedBy")
        by_attr = {j[0]: j[-1] for j in found["jobs"]}
        self.assertEqual(by_attr["blender"], "rocmPackages.clang")
        self.assertEqual((by_attr["krita"], by_attr["afew"]), ("", ""))
        self.assertEqual(found["blocked"], {"known": 1, "pending": 0})

    def test_no_pages_left_this_run(self):
        jobs = [["blender", "x86_64-linux", "11", "dependency", "blender-5.0.1"]]
        master = {
            ("blender", "x86_64-linux"): self.master("blender", "ok", "blender-5.0.1")
        }
        with tempfile.TemporaryDirectory() as d:
            branches.write(
                d, "staging-next", {"columns": list(branches.COLUMNS), "jobs": jobs}
            )
            with mock.patch.object(hydra, "build_page") as asked:
                got = cli.look_up_staging_next_blocked(d, master, time.monotonic(), 0)
            asked.assert_not_called()
            self.assertEqual(got, (0, 1))
            self.assertEqual(branches.read(d, "staging-next")["blocked"]["pending"], 1)
