#!/usr/bin/env python3
"""Bounded existing Monitoring/Logging reads; never call application/exchange APIs."""
import collections
import datetime as dt
import json
import os
import urllib.error
import urllib.parse
import urllib.request

PROJECT = 'tradementor-production'
REGION = 'europe-west4'
END = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)
START = END - dt.timedelta(hours=24)
TOKEN = ''

def utc(value):
    return value.isoformat().replace('+00:00', 'Z')

def read(url, body=None):
    parsed = urllib.parse.urlsplit(url)
    allowed = (parsed.netloc == 'run.googleapis.com' and parsed.path == '/v2/projects/' + PROJECT + '/locations/' + REGION + '/services') or (parsed.netloc == 'monitoring.googleapis.com' and parsed.path == '/v3/projects/' + PROJECT + '/timeSeries') or (parsed.netloc == 'logging.googleapis.com' and parsed.path == '/v2/entries:list')
    if parsed.scheme != 'https' or not allowed or (body is not None and parsed.netloc != 'logging.googleapis.com'):
        raise ValueError('READ_SCOPE_REJECTED')
    if body is not None and body.get('resourceNames') != ['projects/' + PROJECT]:
        raise ValueError('LOGGING_PROJECT_SCOPE_REJECTED')
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None,
        headers={'Authorization': 'Bearer ' + TOKEN, 'Content-Type': 'application/json'},
        method='POST' if body else 'GET')
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.load(response)

def metric(metric_type, aligner='ALIGN_SUM'):
    params = {'filter': 'metric.type="' + metric_type + '"',
        'interval.startTime': utc(START), 'interval.endTime': utc(END),
        'aggregation.alignmentPeriod': '3600s', 'aggregation.perSeriesAligner': aligner,
        'pageSize': '1000', 'view': 'FULL'}
    raw = read('https://monitoring.googleapis.com/v3/projects/' + PROJECT + '/timeSeries?' + urllib.parse.urlencode(params))
    grouped = collections.defaultdict(list)
    for series in raw.get('timeSeries', []):
        resource = series.get('resource', {}).get('labels', {})
        labels = series.get('metric', {}).get('labels', {})
        key = resource.get('service_name') or resource.get('database_id') or 'project'
        if labels.get('type'):
            key += ':' + labels['type']
        for point in series.get('points', []):
            value = point.get('value', {})
            number = value.get('doubleValue', value.get('int64Value'))
            if number is not None:
                grouped[key].append(float(number))
    result = {key: ({'hourlyP95Min': round(min(values), 4), 'hourlyP95Max': round(max(values), 4)} if aligner == 'ALIGN_PERCENTILE_95' else round(sum(values), 3)) for key, values in grouped.items()}
    return {'metric': metric_type, 'groups': result, 'series': len(raw.get('timeSeries', [])), 'truncated': bool(raw.get('nextPageToken'))}

def safe_probe(name, operation):
    try:
        print(name + ' ' + json.dumps(operation(), separators=(',', ':')))
    except urllib.error.HTTPError as error:
        print(name + ' UNAVAILABLE_HTTP_' + str(error.code))
    except Exception as error:
        print(name + ' UNAVAILABLE_' + type(error).__name__)

def services():
    payload = read('https://run.googleapis.com/v2/projects/' + PROJECT + '/locations/' + REGION + '/services?pageSize=100')
    result = []
    for service in payload.get('services', []):
        template = service.get('template', {})
        result.append({'service': service['name'].split('/')[-1],
            'minMaxInstances': template.get('scaling', {}),
            'serviceScaling': service.get('scaling', {}),
            'concurrency': template.get('maxInstanceRequestConcurrency'),
            'containerResources': [c.get('resources', {}) for c in template.get('containers', [])]})
    return {'services': result, 'truncated': bool(payload.get('nextPageToken'))}

def route_sample():
    start = END - dt.timedelta(minutes=30)
    body = {'resourceNames': ['projects/' + PROJECT],
        'filter': 'resource.type="cloud_run_revision" AND logName="projects/' + PROJECT + '/logs/run.googleapis.com%2Frequests" AND timestamp>="' + utc(start) + '" AND timestamp<="' + utc(END) + '"',
        'pageSize': 5000, 'orderBy': 'timestamp desc'}
    payload = read('https://logging.googleapis.com/v2/entries:list', body)
    counts = collections.Counter()
    errors = collections.Counter()
    known = {'/v1/me/aster/status', '/v1/me/continuity', '/api/exchanges/aster', '/v1/me/portfolio/history'}
    entries = payload.get('entries', [])
    for entry in entries:
        request = entry.get('httpRequest', {})
        service = entry.get('resource', {}).get('labels', {}).get('service_name', 'unknown')
        path = urllib.parse.urlsplit(request.get('requestUrl', '')).path
        key = service + ' ' + (path if path in known else 'other')
        counts[key] += 1
        if int(request.get('status') or 0) >= 500:
            errors[key] += 1
    return {'minutes': 30, 'entries': len(entries), 'limit': 5000,
        'truncated': bool(payload.get('nextPageToken')), 'routeCounts': dict(counts), 'http5xx': dict(errors)}

def firestore_reads():
    value = metric('firestore.googleapis.com/document/read_ops_count')
    return value if value['series'] else metric('firestore.googleapis.com/document/read_count')

def main():
    global TOKEN
    TOKEN = os.environ['GOOGLE_ACCESS_TOKEN']
    print('\n## Bounded existing telemetry — no application/exchange calls')
    print('Project', PROJECT, '| UTC interval', utc(START), '..', utc(END))
    safe_probe('CLOUD_RUN_CONFIG', services)
    safe_probe('CLOUD_RUN_REQUESTS', lambda: metric('run.googleapis.com/request_count'))
    safe_probe('CLOUD_RUN_BILLABLE_SECONDS', lambda: metric('run.googleapis.com/container/billable_instance_time'))
    safe_probe('CLOUD_RUN_CPU_HOURLY_P95', lambda: metric('run.googleapis.com/container/cpu/utilizations', 'ALIGN_PERCENTILE_95'))
    safe_probe('FIRESTORE_READ_OPERATIONS', firestore_reads)
    safe_probe('FIRESTORE_WRITE_OPERATIONS', lambda: metric('firestore.googleapis.com/document/write_ops_count'))
    safe_probe('CLOUD_RUN_ROUTE_SAMPLE', route_sample)
    print('Missing/truncated telemetry is not zero usage; metric counts are not invoice reconciliation. No API polls, TTL, logging configuration, scaling, IAM or trading changes.')

if __name__ == '__main__':
    main()
