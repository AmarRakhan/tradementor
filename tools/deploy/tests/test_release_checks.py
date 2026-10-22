#!/usr/bin/env python3
"""Tests voor release_checks.py en voor de WIF-conditie uit setup-github-deploy-identity.sh."""
import copy
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHECKS = os.path.join(HERE, "..", "release_checks.py")
SETUP = os.path.join(HERE, "..", "setup-github-deploy-identity.sh")
LIVE = "421f3452e7f629b53cde83ce357e91644f24fc14"
NEW = "7cbe4bb93c9ca6603776b70083b3705b97e44c97"
IMG = "europe-west4-docker.pkg.dev/tradementor-production/tradementor/tradementor-api@sha256:" + "a" * 64


def run(*args):
    p = subprocess.run([sys.executable, CHECKS, *args], capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def write(obj):
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as fh:
        json.dump(obj, fh)
    return path


def revision(name, commit, image="img:old", extra_env=None, sa="runtime@x"):
    env = [{"name": "TRADEMENTOR_SOURCE_COMMIT", "value": commit},
           {"name": "ASTER_POSITION_LOSS_AUTO_HEDGE_EXECUTION_ENABLED", "value": "true"},
           {"name": "ASTER_KEY", "valueFrom": {"secretKeyRef": {"name": "k", "key": "latest"}}}]
    env += extra_env or []
    return {"metadata": {"name": name,
                         "labels": {"serving.knative.dev/service": "tradementor-api",
                                    "serving.knative.dev/revision": name},
                         "annotations": {"autoscaling.knative.dev/minScale": "1",
                                         "run.googleapis.com/cpu-throttling": "false",
                                         "serving.knative.dev/creator": "someone@" + name}},
            "spec": {"serviceAccountName": sa, "timeoutSeconds": 300, "containerConcurrency": 80,
                     "containers": [{"image": image, "env": env,
                                     "resources": {"limits": {"cpu": "1", "memory": "1Gi"}},
                                     "ports": [{"containerPort": 8080}]}]},
            "status": {"conditions": [{"type": "Ready", "status": "True"}]}}


def service(traffic):
    return {"status": {"url": "https://tradementor-api-x.run.app", "traffic": traffic,
                       "latestReadyRevisionName": traffic[0]["revisionName"],
                       "latestCreatedRevisionName": traffic[-1]["revisionName"]}}


class Inputs(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(run("inputs", NEW, LIVE, "refs/heads/main", "AmarRakhan/tradementor")[0], 0)

    def test_rejects(self):
        for args in [(NEW, LIVE, "refs/heads/other", "AmarRakhan/tradementor"),
                     (NEW, LIVE, "refs/heads/main", "evil/tradementor"),
                     (NEW[:39], LIVE, "refs/heads/main", "AmarRakhan/tradementor"),
                     (NEW, "main", "refs/heads/main", "AmarRakhan/tradementor"),
                     (NEW, NEW, "refs/heads/main", "AmarRakhan/tradementor"),
                     (NEW.upper(), LIVE, "refs/heads/main", "AmarRakhan/tradementor")]:
            self.assertEqual(run("inputs", *args)[0], 1, args)


class Environment(unittest.TestCase):
    def env(self, reviewers=("AmarRakhan",), self_review=False, custom=True):
        return {"name": "release",
                "protection_rules": [{"type": "required_reviewers", "prevent_self_review": self_review,
                                      "reviewers": [{"type": "User", "reviewer": {"login": r}} for r in reviewers]}],
                "deployment_branch_policy": {"protected_branches": not custom, "custom_branch_policies": custom}}

    def pol(self, *names):
        return {"branch_policies": [{"name": n, "type": "branch"} for n in names]}

    def test_ok(self):
        self.assertEqual(run("environment", write(self.env()), write(self.pol("main")), "AmarRakhan")[0], 0)

    def test_no_reviewer_is_allowed(self):
        e = self.env(); e["protection_rules"] = []
        rc, out, _ = run("environment", write(e), write(self.pol("main")), "AmarRakhan")
        self.assertEqual(rc, 0); self.assertIn("automatisch", out)

    def test_no_reviewer_still_requires_main_only(self):
        e = self.env(); e["protection_rules"] = []; e["deployment_branch_policy"] = None
        self.assertEqual(run("environment", write(e), write(self.pol()), "AmarRakhan")[0], 1)

    def test_other_reviewer(self):
        self.assertEqual(run("environment", write(self.env(("someone",))), write(self.pol("main")), "AmarRakhan")[0], 1)

    def test_self_review_blocks_amar(self):
        rc, _, err = run("environment", write(self.env(self_review=True)), write(self.pol("main")), "AmarRakhan")
        self.assertEqual(rc, 1); self.assertIn("self-review", err)

    def test_all_branches(self):
        e = self.env(); e["deployment_branch_policy"] = None
        self.assertEqual(run("environment", write(e), write(self.pol()), "AmarRakhan")[0], 1)

    def test_extra_branch(self):
        self.assertEqual(run("environment", write(self.env()), write(self.pol("main", "dev")), "AmarRakhan")[0], 1)

    def test_wildcard_branch(self):
        self.assertEqual(run("environment", write(self.env()), write(self.pol("*")), "AmarRakhan")[0], 1)


class Preflight(unittest.TestCase):
    def test_ok_and_outputs(self):
        svc = write(service([{"revisionName": "tradementor-api-cp605-421f3452", "percent": 100}]))
        rev = write(revision("tradementor-api-cp605-421f3452", LIVE))
        rc, out, _ = run("preflight", svc, rev, LIVE)
        self.assertEqual(rc, 0)
        self.assertIn("PREVIOUS_REVISION=tradementor-api-cp605-421f3452", out)
        self.assertIn("UPDATE_ENV_KEYS=TRADEMENTOR_SOURCE_COMMIT\n", out)

    def test_image_commit_key_updated_when_present(self):
        svc = write(service([{"revisionName": "r1", "percent": 100}]))
        rev = write(revision("r1", LIVE, extra_env=[{"name": "TRADEMENTOR_IMAGE_SOURCE_COMMIT", "value": LIVE}]))
        self.assertIn("UPDATE_ENV_KEYS=TRADEMENTOR_SOURCE_COMMIT TRADEMENTOR_IMAGE_SOURCE_COMMIT", run("preflight", svc, rev, LIVE)[1])

    def test_stale_request(self):
        svc = write(service([{"revisionName": "r1", "percent": 100}]))
        self.assertEqual(run("preflight", svc, write(revision("r1", NEW)), LIVE)[0], 1)

    def test_split_traffic(self):
        svc = write(service([{"revisionName": "r1", "percent": 90}, {"revisionName": "r2", "percent": 10}]))
        self.assertEqual(run("preflight", svc, write(revision("r1", LIVE)), LIVE)[0], 1)

    def test_wrong_revision_file(self):
        svc = write(service([{"revisionName": "r1", "percent": 100}]))
        self.assertEqual(run("preflight", svc, write(revision("r2", LIVE)), LIVE)[0], 1)

    def test_old_candidate_without_traffic_is_allowed(self):
        svc = write(service([{"revisionName": "r1", "percent": 100}, {"revisionName": "r0", "percent": 0, "tag": "x"}]))
        self.assertEqual(run("preflight", svc, write(revision("r1", LIVE)), LIVE)[0], 0)


class Candidate(unittest.TestCase):
    def setUp(self):
        self.live = revision("tradementor-api-cp605-421f3452", LIVE)
        self.cand = revision("tradementor-api-rel-7cbe4bb9-1234561", NEW, image=IMG)
        self.svc = service([{"revisionName": "tradementor-api-cp605-421f3452", "percent": 100},
                            {"revisionName": "tradementor-api-rel-7cbe4bb9-1234561", "percent": 0,
                             "tag": "rel-1-1", "url": "https://rel-1-1---x.run.app"}])

    def go(self, live=None, cand=None, svc=None, image=IMG):
        return run("candidate", write(live or self.live), write(cand or self.cand), write(svc or self.svc), NEW, "rel-1-1", image)

    def test_ok(self):
        rc, out, err = self.go()
        self.assertEqual(rc, 0, err)
        self.assertIn("CANDIDATE_URL=https://rel-1-1---x.run.app", out)

    def test_env_drift_is_refused_without_printing_values(self):
        c = copy.deepcopy(self.cand)
        c["spec"]["containers"][0]["env"][1]["value"] = "false"
        rc, _, err = self.go(cand=c)
        self.assertEqual(rc, 1)
        self.assertIn("ASTER_POSITION_LOSS_AUTO_HEDGE_EXECUTION_ENABLED", err)
        self.assertNotIn("false", err.replace("ENABLED", ""))

    def test_secret_ref_drift(self):
        c = copy.deepcopy(self.cand)
        c["spec"]["containers"][0]["env"][2]["valueFrom"]["secretKeyRef"]["key"] = "1"
        self.assertEqual(self.go(cand=c)[0], 1)

    def test_extra_env(self):
        c = copy.deepcopy(self.cand)
        c["spec"]["containers"][0]["env"].append({"name": "X", "value": "1"})
        self.assertEqual(self.go(cand=c)[0], 1)

    def test_service_account_drift(self):
        c = copy.deepcopy(self.cand); c["spec"]["serviceAccountName"] = "other@x"
        self.assertEqual(self.go(cand=c)[0], 1)

    def test_resources_drift(self):
        c = copy.deepcopy(self.cand); c["spec"]["containers"][0]["resources"]["limits"]["memory"] = "512Mi"
        self.assertEqual(self.go(cand=c)[0], 1)

    def test_scaling_annotation_drift(self):
        c = copy.deepcopy(self.cand); c["metadata"]["annotations"]["autoscaling.knative.dev/minScale"] = "0"
        self.assertEqual(self.go(cand=c)[0], 1)

    def test_creator_annotation_is_ignored(self):
        c = copy.deepcopy(self.cand); c["metadata"]["annotations"]["serving.knative.dev/creator"] = "github"
        self.assertEqual(self.go(cand=c)[0], 0)

    def test_wrong_image(self):
        self.assertEqual(self.go(image=IMG.replace("a" * 64, "b" * 64))[0], 1)

    def test_candidate_already_has_traffic(self):
        s = copy.deepcopy(self.svc); s["status"]["traffic"][1]["percent"] = 10
        self.assertEqual(self.go(svc=s)[0], 1)

    def test_commit_var_not_updated(self):
        c = revision("tradementor-api-rel-7cbe4bb9-1234561", LIVE, image=IMG)
        self.assertEqual(self.go(cand=c)[0], 1)


class HealthOpenapi(unittest.TestCase):
    def test_health(self):
        ok = {"status": "ready", "multiUser": True, "sourceCommit": NEW, "imageSourceCommit": NEW}
        self.assertEqual(run("health", write(ok), NEW)[0], 0)
        self.assertEqual(run("health", write({**ok, "imageSourceCommit": None}), NEW)[0], 0)
        for bad in [{**ok, "status": "degraded"}, {**ok, "sourceCommit": LIVE}, {**ok, "imageSourceCommit": LIVE},
                    {**ok, "multiUser": False}]:
            self.assertEqual(run("health", write(bad), NEW)[0], 1, bad)

    def test_openapi_superset(self):
        live = {"paths": {"/health": {}, "/v1/me/aster/profit-close-rounds/{round_id}/advance": {}}}
        cand = {"paths": {"/health": {}, "/v1/me/aster/profit-close-rounds/{round_id}/advance": {}, "/new": {}}}
        rc, out, _ = run("openapi", write(live), write(cand))
        self.assertEqual(rc, 0); self.assertIn("OPENAPI_NEW_PATHS=1", out)
        self.assertEqual(run("openapi", write(cand), write(live))[0], 1)

    def test_equal(self):
        self.assertEqual(run("equal", write({"bindings": [1], "etag": "a"}), write({"bindings": [1], "etag": "b"}))[0], 0)
        self.assertEqual(run("equal", write({"bindings": [1]}), write({"bindings": [2]}))[0], 1)


class RollbackTarget(unittest.TestCase):
    def test_ok(self):
        svc = write(service([{"revisionName": "new", "percent": 100}]))
        rc, out, err = run("rollback-target", svc, write(revision("tradementor-api-cp605-421f3452", LIVE)),
                           "tradementor-api-cp605-421f3452")
        self.assertEqual(rc, 0, err); self.assertIn("TARGET_SOURCE_COMMIT=" + LIVE, out)

    def test_not_ready(self):
        r = revision("old", LIVE); r["status"]["conditions"][0]["status"] = "False"
        self.assertEqual(run("rollback-target", write(service([{"revisionName": "new", "percent": 100}])), write(r), "old")[0], 1)

    def test_already_live(self):
        self.assertEqual(run("rollback-target", write(service([{"revisionName": "old", "percent": 100}])),
                             write(revision("old", LIVE)), "old")[0], 1)

    def test_other_service(self):
        r = revision("old", LIVE); r["metadata"]["labels"]["serving.knative.dev/service"] = "other"
        self.assertEqual(run("rollback-target", write(service([{"revisionName": "new", "percent": 100}])), write(r), "old")[0], 1)


def condition():
    text = open(SETUP).read()
    vals = dict(re.findall(r'^(REPO_ID|OWNER_ID|WF)="([^"]*)"', text, re.M))
    cond = re.search(r'^CONDITION="(.*)"$', text, re.M).group(1)
    for k, v in vals.items():
        cond = cond.replace("${%s}" % k, v)
    assert "${" not in cond
    return cond


def evaluate(cond, claims):
    """Minimale CEL-emulatie: alleen ==, &&, ||, haakjes, string-literals en assertion.<veld>."""
    expr = cond.replace("&&", " and ").replace("||", " or ")
    expr = re.sub(r"assertion\.([a-z_]+)", lambda m: f"claims.get({m.group(1)!r})", expr)
    return eval(expr, {"__builtins__": {}}, {"claims": claims})


class WifCondition(unittest.TestCase):
    def base(self, wf="release-backend.yml"):
        ref = f"AmarRakhan/tradementor/.github/workflows/{wf}@refs/heads/main"
        return {"repository_id": "1324367697", "repository_owner_id": "313542222", "ref": "refs/heads/main",
                "ref_type": "branch", "event_name": "workflow_dispatch", "environment": "release",
                "workflow_ref": ref, "job_workflow_ref": ref}

    def test_length(self):
        self.assertLess(len(condition()), 4096)

    def test_allowed(self):
        for wf in ("release-backend.yml", "release-backend-rollback.yml"):
            self.assertTrue(evaluate(condition(), self.base(wf)), wf)

    def test_refused(self):
        cases = {
            "andere branch": {"ref": "refs/heads/claude/x"},
            "tag": {"ref_type": "tag"},
            "push": {"event_name": "push"},
            "pull_request": {"event_name": "pull_request"},
            "zonder environment (plan-job)": {"environment": None},
            "environment production": {"environment": "production"},
            "andere repo-id (fork)": {"repository_id": "1"},
            "andere eigenaar": {"repository_owner_id": "2"},
            "ander workflowbestand": {"workflow_ref": "AmarRakhan/tradementor/.github/workflows/deploy-cloud-production.yml@refs/heads/main",
                                      "job_workflow_ref": "AmarRakhan/tradementor/.github/workflows/deploy-cloud-production.yml@refs/heads/main"},
            "workflow van andere branch": {"workflow_ref": "AmarRakhan/tradementor/.github/workflows/release-backend.yml@refs/heads/dev",
                                          "job_workflow_ref": "AmarRakhan/tradementor/.github/workflows/release-backend.yml@refs/heads/dev"},
            "herbruikbare workflow": {"job_workflow_ref": "evil/x/.github/workflows/y.yml@refs/heads/main"},
            "lookalike-bestand": {"workflow_ref": "AmarRakhan/tradementor/.github/workflows/release-backend.yml.bak@refs/heads/main",
                                  "job_workflow_ref": "AmarRakhan/tradementor/.github/workflows/release-backend.yml.bak@refs/heads/main"},
        }
        for name, change in cases.items():
            claims = {**self.base(), **change}
            self.assertFalse(evaluate(condition(), claims), name)


if __name__ == "__main__":
    unittest.main(verbosity=1)
