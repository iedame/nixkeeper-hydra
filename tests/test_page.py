import os
import unittest

from nixkeeper_hydra import page

SAMPLE = os.path.join(os.path.dirname(__file__), "eval-sample.html")


class Parse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(SAMPLE) as f:
            cls.builds, cls.revision = page.parse(f.read())
        cls.by_job = {(b["attr"], b["system"]): b for b in cls.builds}

    def test_revision(self):
        self.assertEqual(self.revision, "55ba7f49ef2962b42cbd126522b7df5f95037679")

    def test_a_build(self):
        self.assertEqual(
            self.by_job["archisteamfarm", "aarch64-darwin"],
            {
                "attr": "archisteamfarm",
                "system": "aarch64-darwin",
                "build": "347846413",
                "status": "dependency",
                "finished": "2026-10-03T01:19:10+00:00",
                "name": "archisteamfarm-6.3.9.6",
            },
        )

    def test_every_table_of_builds(self):
        # The fork this started from read from "still failing" on: newly
        # failing jobs, among others, were missed.
        tables = {
            "aborted": ("aclpubcheck", "aarch64-linux"),
            "now-fail": ("archisteamfarm", "aarch64-darwin"),
            "now-succeed": ("buildstream", "aarch64-linux"),
            "new": ("amule-api", "aarch64-darwin"),
            "still-fail": ("ac-library", "aarch64-darwin"),
            "still-succeed": ("CuboCore.coreaction", "x86_64-linux"),
            "unfinished": ("wesnoth", "aarch64-darwin"),
        }
        for table, job in tables.items():
            self.assertIn(job, self.by_job, table)

    def test_statuses(self):
        def status(attr, system):
            return self.by_job[attr, system]["status"]

        self.assertEqual(status("buildstream", "aarch64-linux"), "ok")
        self.assertEqual(status("ac-library", "aarch64-darwin"), "failed")
        # Aborted, timed out, a limit exceeded, ... or an icon not known here.
        self.assertEqual(status("aclpubcheck", "aarch64-linux"), "unfinished")
        self.assertEqual(status("flaky", "x86_64-linux"), "unfinished")

    def test_queued_has_no_finish_time(self):
        # Its icon ("Scheduled to be built") starts with an S, as
        # "Succeeded" does: the finish time tells them apart.
        queued = self.by_job["wesnoth", "aarch64-darwin"]
        self.assertEqual((queued["status"], queued["finished"]), ("queued", ""))

    def test_only_nixkeepers_platforms_and_no_removed_jobs(self):
        self.assertNotIn(("hello", "x86_64-darwin"), self.by_job)
        self.assertNotIn("cie-middleware-linux", {b["attr"] for b in self.builds})
        self.assertEqual(len(self.by_job), len(self.builds))  # each job once

    def test_the_jobs_platform_not_the_builds(self):
        # Built as i686-linux: still the x86_64-linux job.
        zsnes = self.by_job["zsnes", "x86_64-linux"]
        self.assertEqual((zsnes["build"], zsnes["status"]), ("347915570", "ok"))

    def test_nested_attributes_keep_their_path(self):
        self.assertIn(("CuboCore.coreaction", "aarch64-linux"), self.by_job)
