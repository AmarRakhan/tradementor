#!/usr/bin/env python3
"""List failing test ids from JUnit XML files, one per line, sorted and de-duplicated.

usage: ci_failures.py OUT.txt REPORT.xml [REPORT.xml ...]
A missing or unparsable report is written as the single line "__REPORT_MISSING__ <path>" so a gate can never
mistake a crashed test run for a clean one. Standard library only (runs on any GitHub-hosted runner).
"""
import sys
import xml.etree.ElementTree as ET


def walk(node, path, out):
    tag = node.tag.split("}")[-1]
    if tag == "testsuite":
        name = node.get("name") or ""
        path = path + [name] if name else path
    if tag == "testcase":
        bad = any(child.tag.split("}")[-1] in ("failure", "error") for child in node)
        if bad:
            parts = [p for p in path if p] + [node.get("classname") or "", node.get("name") or ""]
            out.add("::".join(p for p in parts if p))
        return
    for child in node:
        walk(child, path, out)


def main(argv):
    if len(argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    target, reports = argv[1], argv[2:]
    failures = set()
    for report in reports:
        try:
            walk(ET.parse(report).getroot(), [], failures)
        except (OSError, ET.ParseError) as exc:
            failures.add(f"__REPORT_MISSING__ {report} ({type(exc).__name__})")
    with open(target, "w", encoding="utf-8") as handle:
        for line in sorted(failures):
            handle.write(line + "\n")
    print(f"{len(failures)} failing test id(s) -> {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
