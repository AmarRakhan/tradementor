"""Read-only, sanitized Cloud Run build-601 revision presence probe.

Run only under existing trusted GitHub WIF observer identity. Never writes to GCP.
"""
import json
import subprocess
from typing import Any

PROJECT = 'tradementor-production'
REGION = 'europe-west4'
REVISIONS = {
    'web': 'amar-bot-v44-direct-install-v46-89ab74a0-1',
    'backend': 'tradementor-api-src-f87d6b20-124369',
}

def summarize_revision(data: dict[str, Any], expected: str) -> dict[str, Any]:
    metadata = data.get('metadata') or {}
    conditions = (data.get('status') or {}).get('conditions') or []
    ready = any(c.get('type') == 'Ready' and c.get('status') in ('True', True) for c in conditions)
    image = (((data.get('spec') or {}).get('containers') or [{}])[0]).get('image')
    return {'revision': expected, 'exists': metadata.get('name') == expected, 'ready': ready,
            'image_present': bool(image), 'outcome': 'PASS' if metadata.get('name') == expected and ready and image else 'NO_GO'}

def probe(executor=subprocess.run) -> dict[str, dict[str, Any]]:
    out = {}
    for label, revision in REVISIONS.items():
        cmd = ['gcloud', 'run', 'revisions', 'describe', revision, '--project', PROJECT, '--region', REGION, '--format=json']
        try:
            p = executor(cmd, check=False, capture_output=True, text=True, timeout=35)
            if p.returncode != 0:
                out[label] = {'revision': revision, 'outcome': 'NO_GO', 'reason': 'READ_UNAVAILABLE'}
            else:
                out[label] = summarize_revision(json.loads(p.stdout), revision)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            out[label] = {'revision': revision, 'outcome': 'NO_GO', 'reason': 'READ_UNAVAILABLE'}
    out['rollback'] = {'outcome': 'NOT_PROVEN', 'reason': 'revision presence and readiness alone do not prove end-to-end rollback compatibility'}
    return out

if __name__ == '__main__':
    print(json.dumps(probe(), sort_keys=True))
