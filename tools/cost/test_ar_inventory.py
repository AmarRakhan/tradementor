"""Offline tests for the read-only Artifact Registry inventory (fake gcloud; no network)."""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import ar_inventory as ar  # noqa: E402

NOW = dt.datetime(2026, 10, 22, tzinfo=dt.timezone.utc)
HOST = "europe-west4-docker.pkg.dev/tradementor-production/tradementor"


def img(pkg, digest, days_old, size=1_000_000_000, tags=""):
    created = (NOW - dt.timedelta(days=days_old)).strftime("%Y-%m-%dT%H:%M:%S.123456789Z")
    return {"package": f"{HOST}/{pkg}", "version": digest, "tags": tags, "createTime": created,
            "metadata": {"imageSizeBytes": str(size)}}


def rev(service, name, digest, created, tag_image=None):
    image = tag_image or f"{HOST}/x@{digest}"
    return {"metadata": {"name": name, "creationTimestamp": created, "labels": {"serving.knative.dev/service": service}},
            "spec": {"containers": [{"image": image}]}, "status": {"imageDigest": f"{HOST}/x@{digest}" if digest else ""}}


class ClassifyTests(unittest.TestCase):
    def setUp(self):
        self.images = [img("tradementor-api", "sha256:live", 1), img("tradementor-api", "sha256:rb1", 3),
                       img("tradementor-api", "sha256:old", 90), img("aavansh-trading-web", "sha256:other", 60),
                       img("tradementor-api", "sha256:new", 2), img("strategy2-test-live-api", "sha256:tagged", 80, tags="abc123"),
                       img("zec-diag", "sha256:job", 70)]
        self.revs = [rev("tradementor-api", "api-605", "sha256:live", "2026-10-22T00:00:00Z"),
                     rev("tradementor-api", "api-604", "sha256:rb1", "2026-10-21T00:00:00Z"),
                     rev("aavansh-trading-v1", "aav-1", "sha256:other", "2026-09-17T00:00:00Z"),
                     rev("tradementor-api-staging", "stg-1", "", "2026-09-01T00:00:00Z",
                         tag_image=f"{HOST}/strategy2-test-live-api:abc123")]
        self.services = [{"status": {"traffic": [{"revisionName": "api-605", "percent": 100}]}}]
        self.jobs = [{"spec": {"template": {"spec": {"template": {"spec": {"containers": [{"image": f"{HOST}/zec-diag@sha256:job"}]}}}}}}]

    def run_classify(self, **kw):
        rows = ar.classify(self.images, self.revs, self.services, self.jobs, now=NOW, keep_days=30, rollback_revisions=5, **kw)
        return {r["digest"]: r["class"] for r in rows}

    def test_classes(self):
        c = self.run_classify()
        self.assertEqual(c["sha256:live"], "KEEP_LIVE")
        self.assertEqual(c["sha256:rb1"], "KEEP_ROLLBACK")
        self.assertEqual(c["sha256:other"], "KEEP_REFERENCED")      # any existing revision keeps its image
        self.assertEqual(c["sha256:tagged"], "KEEP_REFERENCED")     # referenced by tag, not digest
        self.assertEqual(c["sha256:job"], "KEEP_REFERENCED")        # Cloud Run job image
        self.assertEqual(c["sha256:new"], "KEEP_RECENT")
        self.assertEqual(c["sha256:old"], "CANDIDATE")

    def test_refuses_any_mutating_command(self):
        for bad in (["artifacts", "docker", "images", "delete", "x"], ["artifacts", "repositories", "set-cleanup-policies", "list"]):
            with self.assertRaises(SystemExit):
                ar.gcloud_json(bad, runner=lambda cmd: "[]")

    def test_end_to_end_with_fake_gcloud_writes_manifests_and_runs_only_reads(self):
        seen = []

        def fake(cmd):
            seen.append(cmd)
            joined = " ".join(cmd)
            if "repositories list" in joined:
                return json.dumps([{"name": "projects/tradementor-production/locations/europe-west4/repositories/tradementor",
                                    "format": "DOCKER", "sizeBytes": "310000000000"}])
            if "docker images list" in joined:
                return json.dumps(self.images)
            if "revisions list" in joined:
                return json.dumps(self.revs)
            if "services list" in joined:
                return json.dumps(self.services)
            if "jobs list" in joined:
                return json.dumps(self.jobs)
            raise AssertionError(joined)
        with tempfile.TemporaryDirectory() as out:
            self.assertEqual(ar.main(["--out", out], runner=fake), 0)
            cand = open(os.path.join(out, "delete-candidates.txt")).read().split()
            keep = open(os.path.join(out, "keep-manifest.txt")).read()
        self.assertEqual(cand, [f"{HOST}/tradementor-api@sha256:old"])
        self.assertIn("sha256:live", keep)
        self.assertTrue(all(any(v in c for v in ("list", "describe")) and "delete" not in c for c in seen))


if __name__ == "__main__":
    unittest.main()
