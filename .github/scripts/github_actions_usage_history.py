#!/usr/bin/env python3
"""One-off GitHub-only history audit. No Google/exchange access or mutations."""
import concurrent.futures
import datetime as dt
import json
import math
import os
import pathlib
import re
import sys
import time
import urllib.request

REPO = 'AmarRakhan/tradementor'
API = 'https://api.github.com'
UTC = dt.timezone.utc
QUERY = '''query($ids:[ID!]!) { nodes(ids:$ids) { ... on CheckSuite {
id checkRuns(first:100,filterBy:{checkType:ALL}) {
nodes { id name startedAt completedAt conclusion status detailsUrl }
pageInfo { hasNextPage endCursor }
} } } }'''
NEXT = '''query($id:ID!,$after:String!) { node(id:$id) { ... on CheckSuite {
id checkRuns(first:100,after:$after,filterBy:{checkType:ALL}) {
nodes { id name startedAt completedAt conclusion status detailsUrl }
pageInfo { hasNextPage endCursor }
} } } }'''

def stamp(value):
    return dt.datetime.fromisoformat(value.replace('Z', '+00:00'))

def job_minutes(job):
    if job.get('conclusion') == 'SKIPPED' or not job.get('startedAt') or not job.get('completedAt'):
        return 0
    seconds = max(0, (stamp(job['completedAt']) - stamp(job['startedAt'])).total_seconds())
    return math.ceil(seconds / 60)

def projected_pro_usd(minutes_per_day, artifact_gib=0):
    return 4 + max(0, minutes_per_day * 30 - 3000) * 0.006 + max(0, artifact_gib - 1) * 0.25

class Reader:
    def __init__(self, token):
        self.token = token
        self.deadline = time.monotonic() + 480

    def get(self, path, body=None):
        if time.monotonic() > self.deadline:
            raise RuntimeError('BOUNDED_AUDIT_DEADLINE')
        if not (path.startswith('/repos/' + REPO + '/') or path == '/graphql'):
            raise RuntimeError('REPOSITORY_SCOPE_REJECTED')
        if body is not None and (path != '/graphql' or not body.get('query', '').startswith('query(')):
            raise RuntimeError('ONLY_READ_ONLY_GRAPHQL_QUERY_ALLOWED')
        req = urllib.request.Request(API + path, data=json.dumps(body).encode() if body else None,
            headers={'Authorization': 'Bearer ' + self.token, 'Accept': 'application/vnd.github+json',
                     'Content-Type': 'application/json', 'X-GitHub-Api-Version': '2022-11-28'},
            method='POST' if body else 'GET')
        with urllib.request.urlopen(req, timeout=25) as result:
            payload = json.load(result)
        if isinstance(payload, dict) and payload.get('errors'):
            raise RuntimeError('GRAPHQL_QUERY_REJECTED')
        return payload

def collect(reader):
    snapshot = dt.datetime.now(UTC)
    first = reader.get('/repos/' + REPO + '/actions/runs?per_page=100&page=1')
    total = first['total_count']
    if total > 40000:
        raise RuntimeError('RUN_HISTORY_CAP_EXCEEDED')
    raw = first['workflow_runs']
    pages = math.ceil(total / 100)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for result in pool.map(lambda p: reader.get('/repos/' + REPO + '/actions/runs?per_page=100&page=' + str(p)), range(2, pages + 1)):
            raw.extend(result['workflow_runs'])
    runs = {r['id']: r for r in raw if stamp(r['created_at']) <= snapshot}
    suite_ids = list(dict.fromkeys(r['check_suite_node_id'] for r in runs.values() if r.get('check_suite_node_id')))
    jobs = {}
    missing_nodes = 0
    def add(node):
        nonlocal missing_nodes
        if not node:
            missing_nodes += 1
            return
        connection = node['checkRuns']
        for page in range(10):
            for job in connection['nodes']:
                match = re.fullmatch(r'https://github.com/AmarRakhan/tradementor/actions/runs/(\d+)/job/(\d+)', job.get('detailsUrl') or '')
                if match and int(match[1]) in runs:
                    jobs[job['id']] = {**job, 'runId': int(match[1])}
            if not connection['pageInfo']['hasNextPage']:
                return
            connection = reader.get('/graphql', {'query': NEXT, 'variables': {'id': node['id'], 'after': connection['pageInfo']['endCursor']}})['data']['node']['checkRuns']
        raise RuntimeError('CHECK_RUN_PAGINATION_CAP_EXCEEDED')
    batches = [suite_ids[i:i + 100] for i in range(0, len(suite_ids), 100)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for result in pool.map(lambda ids: reader.get('/graphql', {'query': QUERY, 'variables': {'ids': ids}}), batches):
            for node in result['data']['nodes']:
                add(node)
    if missing_nodes:
        raise RuntimeError('INCOMPLETE_CHECK_SUITE_HISTORY_' + str(missing_nodes))
    finished = [j for j in jobs.values() if j.get('completedAt') and stamp(j['completedAt']) <= snapshot]
    begun = min(stamp(r['created_at']) for r in runs.values())
    elapsed = (snapshot - begun).total_seconds() / 86400
    midnight = snapshot.replace(hour=0, minute=0, second=0, microsecond=0)
    windows = [('whole_project', begun, snapshot, elapsed),
               ('last_30_complete_utc_days', midnight - dt.timedelta(days=30), midnight, 30),
               ('last_7_complete_utc_days', midnight - dt.timedelta(days=7), midnight, 7),
               ('last_24_hours', snapshot - dt.timedelta(days=1), snapshot, 1)]
    summaries = []
    for name, start, end, days in windows:
        selected = [j for j in finished if j.get('startedAt') and start <= stamp(j['startedAt']) < end]
        minutes = sum(job_minutes(j) for j in selected)
        summaries.append({'window': name, 'fromUtc': start.isoformat(), 'toUtc': end.isoformat(),
            'days': round(days, 4), 'jobs': len(selected), 'roundedJobMinutes': minutes,
            'minutesPer24h': round(minutes / days, 2), 'proScenarioMonthlyUsdBeforeStorageTax': round(projected_pro_usd(minutes / days), 2)})
    workflows = {}
    for job in finished:
        name = runs[job['runId']]['name']
        workflows[name] = workflows.get(name, 0) + job_minutes(job)
    return {'repo': REPO, 'snapshotUtc': snapshot.isoformat(), 'firstRunUtc': begun.isoformat(),
        'runCount': len(runs), 'listedTotalAtStart': total, 'suiteCount': len(suite_ids),
        'completedCheckRuns': len(finished), 'windows': summaries,
        'topWorkflowMinutes': dict(sorted(workflows.items(), key=lambda item: -item[1])[:15]),
        'limits': 'Completed job timestamps, rounded per job. Includes retries, parallel jobs and executed failures/cancellations; excludes skipped/unfinished jobs. Dates attributed to job start. Not owner billing data; runner OS, private runner performance, shared allowance, storage, tax and plan still need verification.'}

def main():
    if os.environ.get('GITHUB_REPOSITORY') != REPO:
        raise RuntimeError('REPOSITORY_SCOPE_REJECTED')
    report = collect(Reader(os.environ['GH_TOKEN']))
    output = pathlib.Path(sys.argv[1])
    output.write_text(json.dumps(report, indent=2))
    print('## Historical GitHub Actions usage — read-only')
    print('Repository:', REPO, '| runs:', report['runCount'], '| first run:', report['firstRunUtc'])
    print('\n| Period | Job minutes | Minutes/day | Pro scenario USD/month* |\n|---|---:|---:|---:|')
    for row in report['windows']:
        print('|', row['window'], '|', row['roundedJobMinutes'], '|', row['minutesPer24h'], '|', row['proScenarioMonthlyUsdBeforeStorageTax'], '|')
    print('\n*30-day projection: $4 Pro + excess above 3,000 minutes at $0.006/minute; assumes standard Linux runners. Storage/tax and account plan not included.')
    print('\nTop workflows:', json.dumps(report['topWorkflowMinutes']))
    print('\nCoverage and limitations:', report['limits'])

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('HISTORY_AUDIT_BLOCKED:', type(exc).__name__, str(exc)[:180])
        raise SystemExit(1)
