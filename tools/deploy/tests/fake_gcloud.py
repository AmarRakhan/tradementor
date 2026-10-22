#!/usr/bin/env python3
"""Nep-gcloud voor de tests van setup-github-deploy-identity.sh. Strikt: onbekende opdrachten of vlaggen = exit 3.

State in $FAKE_STATE (JSON). Foutinjectie: $FAKE_FAIL = deel van de opdracht dat moet falen.
$FAKE_MUTATE_OLD=1 wijzigt de oude provider bij add-iam-policy-binding (gelijktijdige wijziging nabootsen).
"""
import json
import os
import sys

STATE = os.environ["FAKE_STATE"]
LOG = os.environ.get("FAKE_LOG")


def load():
    with open(STATE) as fh:
        return json.load(fh)


def save(st):
    with open(STATE, "w") as fh:
        json.dump(st, fh, indent=2, sort_keys=True)


def out(obj):
    print(json.dumps(obj, indent=2, sort_keys=True))


def die(code, msg):
    print(msg, file=sys.stderr)
    sys.exit(code)


def parse(argv):
    pos, flags = [], {}
    for a in argv:
        if a.startswith("--"):
            k, _, v = a[2:].partition("=")
            flags[k] = v
        else:
            pos.append(a)
    return pos, flags


def main():
    argv = sys.argv[1:]
    cmdline = " ".join(argv)
    if LOG:
        with open(LOG, "a") as fh:
            fh.write(cmdline + "\n")
    fail = os.environ.get("FAKE_FAIL")
    if fail and fail in cmdline:
        die(1, f"ERROR: (gcloud) injected failure for: {fail}")
    pos, flags = parse(argv)
    allowed = {"project", "quiet", "format", "location", "display-name", "description", "workload-identity-pool",
               "issuer-uri", "attribute-mapping", "attribute-condition", "role", "member"}
    unknown = set(flags) - allowed
    if unknown:
        die(3, f"unknown flags {unknown}")
    st = load()
    if pos[:3] == ["config", "get-value", "account"]:
        print(st.get("account", ""))
        return
    if pos[:2] == ["projects", "describe"]:
        if pos[2] != st["project_id"]:
            die(1, "NOT_FOUND")
        print(st["project_number"])
        return
    if "project" in flags and flags["project"] != st["project_id"]:
        die(1, "wrong project")
    if pos[:2] == ["iam", "service-accounts"]:
        verb, sa = pos[2], pos[3]
        if sa not in st["service_accounts"]:
            die(1, "NOT_FOUND: service account")
        acc = st["service_accounts"][sa]
        if verb == "describe":
            out({"email": sa, "disabled": acc.get("disabled", False)})
            return
        if verb == "get-iam-policy":
            out(acc["policy"])
            return
        if verb in ("add-iam-policy-binding", "remove-iam-policy-binding"):
            role, member = flags["role"], flags["member"]
            binds = acc["policy"].setdefault("bindings", [])
            b = next((x for x in binds if x["role"] == role and not x.get("condition")), None)
            if verb.startswith("add"):
                if b is None:
                    b = {"role": role, "members": []}
                    binds.append(b)
                if member not in b["members"]:
                    b["members"].append(member)
                if os.environ.get("FAKE_MUTATE_OLD"):
                    st["pools"]["github"]["providers"]["tradementor-production"]["attributeCondition"] += " && true"
            else:
                if b is None or member not in b["members"]:
                    die(1, "member not found")
                b["members"].remove(member)
                if not b["members"]:
                    binds.remove(b)
            acc["policy"]["etag"] = "e" + str(len(json.dumps(acc["policy"])))
            save(st)
            return
    if pos[:2] == ["iam", "workload-identity-pools"]:
        assert flags.get("location") == "global", "location must be global"
        if pos[2] == "providers":
            verb, name, pool = pos[3], pos[4], flags["workload-identity-pool"]
            p = st["pools"].get(pool)
            if p is None:
                die(1, "NOT_FOUND pool")
            prov = p["providers"].get(name)
            if verb == "describe":
                if prov is None:
                    die(1, "NOT_FOUND provider")
                out(prov)
                return
            if verb == "create-oidc":
                if prov is not None:
                    die(1, "ALREADY_EXISTS")
                mapping = dict(kv.split("=", 1) for kv in flags["attribute-mapping"].split(","))
                p["providers"][name] = {"name": name, "displayName": flags.get("display-name"), "state": "ACTIVE",
                                        "attributeCondition": flags["attribute-condition"],
                                        "attributeMapping": mapping, "oidc": {"issuerUri": flags["issuer-uri"]}}
                save(st)
                return
            if verb == "delete":
                if prov is None:
                    die(1, "NOT_FOUND provider")
                prov["state"] = "DELETED"
                save(st)
                return
        verb, name = pos[2], pos[3]
        p = st["pools"].get(name)
        if verb == "describe":
            if p is None:
                die(1, "NOT_FOUND pool")
            out({k: v for k, v in p.items() if k != "providers"})
            return
        if verb == "create":
            if p is not None:
                die(1, "ALREADY_EXISTS")
            st["pools"][name] = {"name": name, "displayName": flags["display-name"], "state": "ACTIVE",
                                 "description": flags.get("description", ""), "providers": {}}
            save(st)
            return
        if verb == "delete":
            if p is None:
                die(1, "NOT_FOUND pool")
            p["state"] = "DELETED"
            save(st)
            return
    die(3, f"unknown command: {cmdline}")


if __name__ == "__main__":
    main()
