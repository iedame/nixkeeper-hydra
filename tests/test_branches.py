import io
import tempfile
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
            mock.patch.object(hydra, "latest_eval", return_value=latest) as asked,
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
                mock.patch.object(hydra, "latest_eval", return_value=1829700),
                mock.patch.object(hydra, "download_eval"),
                mock.patch.object(page, "parse", return_value=(BUILDS, "x")),
            ):
                branches.update_all(d, NOW, cli.due)
            with mock.patch.object(hydra, "latest_eval", side_effect=OSError("down")):
                branches.update_all(d, NOW, cli.due)
            self.assertEqual(branches.read(d, "haskell-updates"), before)


if __name__ == "__main__":
    unittest.main()
