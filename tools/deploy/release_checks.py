#!/usr/bin/env python3
"""Controles voor de GitHub-releaseroute (release-backend.yml / release-backend-rollback.yml).

Alleen standaardbibliotheek. Elke subopdracht faalt met exit 1 en een duidelijke reden;
de workflow stopt dan vóór de volgende stap. Uitvoer op stdout is KEY=VALUE (voor GITHUB_ENV).
"""
from __future__ import annotations

import json
import re
import sys

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
COMMIT_KEYS = ("TRADEMENTOR_SOURCE_COMMIT", "TRADEMENTOR_IMAGE_SOURCE_COMMIT")
# Annotaties die Cloud Run per revisie zelf zet; alle andere moeten gelijk blijven.
VOLATILE_ANNOTATIONS = {
    "serving.knative.dev/creator",
    "serving.knative.dev/lastModifier",
    "serving.knative.dev/creationTimestamp",
    "serving.knative.dev/routes",
    "serving.knative.dev/routingStateModified",
    "run.googleapis.com/client-name",
    "run.googleapis.com/client-version",
    "run.googleapis.com/operation-id",
    "run.googleapis.com/urls",
    "client.knative.dev/user-image",
    "client.knative.dev/nonce",
}
VOLATILE_LABELS = {
    "serving.knative.dev/configuration",
    "serving.knative.dev/configurationGeneration",
    "serving.knative.dev/configurationUID",
    "serving.knative.dev/revision",
    "serving.knative.dev/revisionUID",
    "serving.knative.dev/route",
    "serving.knative.dev/service",
    "serving.knative.dev/serviceUID",
    "cloud.googleapis.com/location",
    "run.googleapis.com/startupProbeType",
    "client.knative.dev/nonce",
}


class CheckError(Exception):
    pass


def need(cond: bool, reason: str) -> None:
    if not cond:
        raise CheckError(reason)


def load(path: str):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def env_map(container: dict) -> dict:
    out = {}
    for item in container.get("env", []) or []:
        name = item.get("name")
        need(bool(name), "env-item zonder naam")
        need(name not in out, f"dubbele env-var {name}")
        out[name] = {k: v for k, v in item.items() if k != "name"}
    return out


def revision_shape(rev: dict) -> dict:
    """Alles van een revisie dat bij een release gelijk moet blijven (behalve image en commit-vars)."""
    spec = rev.get("spec", {})
    containers = spec.get("containers") or []
    need(len(containers) == 1, f"verwacht precies 1 container, gevonden {len(containers)}")
    c = dict(containers[0])
    c.pop("image", None)
    c.pop("name", None)
    env = env_map(c)
    c.pop("env", None)
    meta = rev.get("metadata", {})
    ann = {k: v for k, v in (meta.get("annotations") or {}).items() if k not in VOLATILE_ANNOTATIONS}
    labels = {k: v for k, v in (meta.get("labels") or {}).items() if k not in VOLATILE_LABELS}
    s = {k: v for k, v in spec.items() if k != "containers"}
    return {"spec": s, "container": c, "env": env, "annotations": ann, "labels": labels}


def cmd_inputs(source: str, expected_live: str, ref: str, repo: str) -> None:
    need(repo == "AmarRakhan/tradementor", f"verkeerde repository {repo}")
    need(ref == "refs/heads/main", f"workflow moet vanaf main draaien, niet {ref}")
    need(bool(SHA_RE.match(source)), "source_commit is geen 40-teken commit-SHA")
    need(bool(SHA_RE.match(expected_live)), "expected_live_commit is geen 40-teken commit-SHA")
    need(source != expected_live, "source_commit is gelijk aan wat al live staat")
    print("INPUTS_OK=true")


def cmd_environment(path: str, policies_path: str, reviewer: str) -> None:
    """Weigert als environment 'release' geen verplichte reviewer heeft of andere branches dan main toelaat."""
    env = load(path)
    need(env.get("name") == "release", "environment 'release' bestaat niet")
    reviewers = []
    for rule in env.get("protection_rules") or []:
        if rule.get("type") == "required_reviewers":
            for r in rule.get("reviewers") or []:
                login = (r.get("reviewer") or {}).get("login")
                if login:
                    reviewers.append(login)
            need(not rule.get("prevent_self_review"),
                 "'Prevent self-review' staat aan; dan kan Amar zijn eigen release niet goedkeuren")
    need(reviewer in reviewers,
         f"environment 'release' heeft geen verplichte reviewer {reviewer} (nu: {reviewers or 'geen'})")
    policy = env.get("deployment_branch_policy")
    need(isinstance(policy, dict) and policy.get("custom_branch_policies") is True,
         "environment 'release' moet 'Selected branches' gebruiken met alleen main")
    names = sorted((p.get("name"), p.get("type", "branch"))
                   for p in (load(policies_path).get("branch_policies") or []))
    need(names == [("main", "branch")], f"toegestane branches moeten precies ['main'] zijn, nu {names}")
    print("ENVIRONMENT_OK=true")


def cmd_preflight(service_path: str, live_rev_path: str, expected_live: str) -> None:
    svc = load(service_path)
    st = svc.get("status", {})
    live_rows = [r for r in st.get("traffic") or [] if (r.get("percent") or 0) > 0]
    need(len(live_rows) == 1 and live_rows[0].get("percent") == 100,
         f"verkeer staat niet op precies één revisie met 100%: {live_rows}")
    live = live_rows[0].get("revisionName")
    need(bool(live), "live revisienaam ontbreekt")
    # Een eerdere kandidaat zonder verkeer mag bestaan: de kandidaatcontrole vergelijkt
    # de nieuwe revisie altijd met de LIVE revisie, niet met de service-template.
    rev = load(live_rev_path)
    need(rev.get("metadata", {}).get("name") == live, "revisiedetails horen niet bij de live revisie")
    env = env_map((rev.get("spec", {}).get("containers") or [{}])[0])
    live_commit = (env.get("TRADEMENTOR_SOURCE_COMMIT") or {}).get("value")
    need(live_commit == expected_live,
         f"live commit is {live_commit}, verwacht {expected_live}; verzoek is verouderd")
    url = st.get("url") or ""
    need(url.startswith("https://"), "service-URL ontbreekt")
    sa = rev.get("spec", {}).get("serviceAccountName")
    need(bool(sa), "service account van de live revisie ontbreekt")
    print(f"PREVIOUS_REVISION={live}")
    print(f"PREVIOUS_SOURCE_COMMIT={live_commit}")
    print(f"SERVICE_URL={url}")
    print(f"RUNTIME_SERVICE_ACCOUNT={sa}")
    print("UPDATE_ENV_KEYS=" + " ".join(k for k in COMMIT_KEYS if k in env or k == COMMIT_KEYS[0]))


def cmd_candidate(live_rev_path: str, cand_rev_path: str, service_path: str, source: str, tag: str,
                  expected_image: str) -> None:
    live = revision_shape(load(live_rev_path))
    cand_rev = load(cand_rev_path)
    cand = revision_shape(cand_rev)
    expected_env = dict(live["env"])
    for key in COMMIT_KEYS:
        if key in expected_env or key == COMMIT_KEYS[0]:
            expected_env[key] = {"value": source}
    # Alleen namen tonen: logs van een publieke repo zijn openbaar, waarden kunnen gevoelig zijn.
    diff_keys = sorted(k for k in set(expected_env) | set(cand["env"]) if expected_env.get(k) != cand["env"].get(k))
    need(not diff_keys, f"env van de kandidaat wijkt af van live bij: {diff_keys}")
    for part in ("spec", "container", "annotations", "labels"):
        a, b = live[part], cand[part]
        keys = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
        need(not keys, f"{part} van de kandidaat wijkt af van live bij: {keys}")
    image = (cand_rev.get("spec", {}).get("containers") or [{}])[0].get("image", "")
    need(image == expected_image, f"kandidaat-image {image} is niet het zojuist gebouwde image {expected_image}")
    need(bool(SHA_RE.match(source)), "ongeldige commit")
    svc = load(service_path)
    rows = [r for r in svc.get("status", {}).get("traffic") or [] if r.get("tag") == tag]
    need(len(rows) == 1, f"tag {tag} niet gevonden")
    need((rows[0].get("percent") or 0) == 0, "kandidaat krijgt al verkeer")
    name = cand_rev.get("metadata", {}).get("name")
    need(rows[0].get("revisionName") == name, "tag wijst naar een andere revisie")
    print(f"CANDIDATE_REVISION={name}")
    print(f"CANDIDATE_URL={rows[0]['url']}")


def cmd_health(path: str, expected: str) -> None:
    h = load(path)
    need(h.get("status") == "ready", f"health status is {h.get('status')}")
    need(h.get("multiUser") is True, "multiUser is niet true")
    need(h.get("sourceCommit") == expected, f"sourceCommit {h.get('sourceCommit')} != {expected}")
    img = h.get("imageSourceCommit")
    need(img in (None, expected), f"imageSourceCommit {img} != {expected}")
    print("HEALTH_OK=true")


def cmd_openapi(live_path: str, cand_path: str) -> None:
    live = set((load(live_path).get("paths") or {}).keys())
    cand = set((load(cand_path).get("paths") or {}).keys())
    need(bool(live), "live openapi bevat geen paden")
    missing = sorted(live - cand)
    need(not missing, f"kandidaat mist {len(missing)} route(s) die live wel bestaan: {missing[:20]}")
    print(f"OPENAPI_LIVE_PATHS={len(live)}")
    print(f"OPENAPI_NEW_PATHS={len(cand - live)}")


def cmd_equal(a: str, b: str) -> None:
    ja, jb = load(a), load(b)
    for d in (ja, jb):
        if isinstance(d, dict):
            d.pop("etag", None)
    need(ja == jb, f"{a} en {b} verschillen")
    print("EQUAL=true")


def cmd_rollback_target(service_path: str, rev_path: str, target: str) -> None:
    svc = load(service_path)
    st = svc.get("status", {})
    rows = [r for r in st.get("traffic") or [] if (r.get("percent") or 0) > 0]
    need(len(rows) == 1 and rows[0].get("percent") == 100, f"verkeer is gesplitst: {rows}")
    current = rows[0]["revisionName"]
    need(current != target, f"{target} krijgt al 100% verkeer")
    rev = load(rev_path)
    need(rev.get("metadata", {}).get("name") == target, "revisiedetails horen niet bij het doel")
    need(rev.get("metadata", {}).get("labels", {}).get("serving.knative.dev/service") == "tradementor-api",
         "doelrevisie hoort niet bij tradementor-api")
    conds = {c.get("type"): c.get("status") for c in rev.get("status", {}).get("conditions") or []}
    need(conds.get("Ready") == "True", f"doelrevisie is niet Ready: {conds}")
    env = env_map((rev.get("spec", {}).get("containers") or [{}])[0])
    commit = (env.get("TRADEMENTOR_SOURCE_COMMIT") or {}).get("value")
    need(bool(commit and SHA_RE.match(commit)), "doelrevisie heeft geen TRADEMENTOR_SOURCE_COMMIT")
    print(f"CURRENT_REVISION={current}")
    print(f"TARGET_SOURCE_COMMIT={commit}")
    print(f"SERVICE_URL={st.get('url')}")


COMMANDS = {
    "inputs": (cmd_inputs, 4),
    "environment": (cmd_environment, 3),
    "preflight": (cmd_preflight, 3),
    "candidate": (cmd_candidate, 6),
    "health": (cmd_health, 2),
    "openapi": (cmd_openapi, 2),
    "equal": (cmd_equal, 2),
    "rollback-target": (cmd_rollback_target, 3),
}


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in COMMANDS:
        print(f"gebruik: {argv[0]} {{{','.join(COMMANDS)}}} ...", file=sys.stderr)
        return 2
    fn, n = COMMANDS[argv[1]]
    args = argv[2:]
    if len(args) != n:
        print(f"{argv[1]} verwacht {n} argumenten, kreeg {len(args)}", file=sys.stderr)
        return 2
    try:
        fn(*args)
    except CheckError as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        return 1
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"STOP: onverwachte vorm van de gegevens ({type(exc).__name__}: {exc})", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
