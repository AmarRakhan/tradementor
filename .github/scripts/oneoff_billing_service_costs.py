#!/usr/bin/env python3
"""One bounded project-scoped standard-export query; no production-data writes."""
import collections
import datetime as dt
from decimal import Decimal
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

PROJECT = 'tradementor-production'
DATASET = 'cloud_billing_costs'
BASE = 'https://bigquery.googleapis.com/bigquery/v2/projects/' + PROJECT
CAP_BYTES = 50 * 1024 * 1024

def api(url, token, body=None):
    if not url.startswith(BASE + '/'):
        raise ValueError('PROJECT_SCOPE_REJECTED')
    request = urllib.request.Request(url, data=json.dumps(body).encode() if body else None,
        headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'},
        method='POST' if body else 'GET')
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)

def totals(rows):
    days = collections.defaultdict(Decimal)
    services = collections.defaultdict(Decimal)
    skus = collections.defaultdict(Decimal)
    units = collections.defaultdict(Decimal)
    for row in rows:
        if row['project_id'] != PROJECT:
            raise ValueError('FOREIGN_PROJECT_ROW_REJECTED')
        currency = row['currency']
        value = Decimal(row['gross'] or '0') + Decimal(row['credits'] or '0')
        days[(currency, row['usage_day'])] += value
        services[(currency, row['service'])] += value
        skus[(currency, row['service'], row['sku'])] += value
        units[(row['service'], row['sku'], row['pricing_unit'])] += Decimal(row['pricing_units'] or '0')
    return days, services, skus, units

def main():
    token = os.environ['GOOGLE_ACCESS_TOKEN']
    end = dt.datetime.now(dt.timezone.utc).date()
    start = end.replace(day=1)
    if start == end:
        start = (end - dt.timedelta(days=1)).replace(day=1)
    listing = api(BASE + '/datasets/' + DATASET + '/tables?maxResults=100', token)
    tables = [item['tableReference']['tableId'] for item in listing.get('tables', [])
        if re.fullmatch(r'gcp_billing_export_v1_[A-Za-z0-9_]+', item['tableReference']['tableId'])]
    if len(tables) != 1:
        raise ValueError('STANDARD_EXPORT_TABLE_SELECTION_AMBIGUOUS')
    sql = '''SELECT CAST(DATE(usage_start_time) AS STRING) AS usage_day,
currency, project.id AS project_id, service.description AS service, sku.description AS sku,
SUM(cost) AS gross, SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c),0)) AS credits,
SUM(usage.amount_in_pricing_units) AS pricing_units, usage.pricing_unit
FROM `%s.%s.%s`
WHERE usage_start_time >= TIMESTAMP('%s') AND usage_start_time < TIMESTAMP('%s')
AND project.id = '%s'
GROUP BY usage_day,currency,project_id,service,sku,usage.pricing_unit
ORDER BY usage_day,service,sku''' % (PROJECT, DATASET, tables[0], start, end, PROJECT)
    dry = api(BASE + '/jobs', token, {'configuration': {'dryRun': True,
        'query': {'query': sql, 'useLegacySql': False}},
        'jobReference': {'projectId': PROJECT, 'location': 'EU'}})
    size = int(dry.get('statistics', {}).get('query', {}).get('totalBytesProcessed', '0'))
    if size > CAP_BYTES:
        raise ValueError('QUERY_CAP_EXCEEDED')
    payload = {'query': sql, 'useLegacySql': False, 'maximumBytesBilled': str(CAP_BYTES),
        'location': 'EU', 'useQueryCache': True, 'timeoutMs': 30000, 'maxResults': 5000}
    result = api(BASE + '/queries', token, payload)
    for _ in range(6):
        if result.get('jobComplete'):
            break
        ref = result['jobReference']
        if not re.fullmatch(r'[A-Za-z0-9_-]+', ref['jobId']):
            raise ValueError('QUERY_JOB_REFERENCE_REJECTED')
        time.sleep(3)
        result = api(BASE + '/queries/' + urllib.parse.quote(ref['jobId']) + '?location=EU&maxResults=5000', token)
    if not result.get('jobComplete') or result.get('pageToken'):
        raise ValueError('QUERY_RESULTS_PENDING_OR_TRUNCATED')
    fields = [field['name'] for field in result['schema']['fields']]
    rows = [dict(zip(fields, [cell.get('v') for cell in row['f']])) for row in result.get('rows', [])]
    if len(rows) != int(result.get('totalRows', len(rows))):
        raise ValueError('INCOMPLETE_QUERY_ROWS')
    days, services, skus, units = totals(rows)
    print('## Bounded project/SKU billing export')
    print('Project:', PROJECT, '| UTC usage period:', start, '..', end, '(exclusive)')
    print('Currencies OBSERVED:', ','.join(sorted({row['currency'] for row in rows})), '| rows:', len(rows), '| dry-run bytes:', size)
    print('Net usage costs + credits; excludes invoice-tax/payment reconciliation. Latest usage day can have export lag.')
    if not rows:
        print('NO_EXPORTED_COST_ROWS: not evidence of zero spend')
    for (currency, day), value in sorted(days.items()):
        print('DAY', day, currency, f'{value:.6f}')
    for (currency, service), value in sorted(services.items(), key=lambda item: -item[1]):
        print('SERVICE', service, currency, f'{value:.6f}')
    for (currency, service, sku), value in sorted(skus.items(), key=lambda item: -item[1])[:20]:
        print('SKU', service, '/', sku, currency, f'{value:.6f}')
    for (service, sku, unit), amount in units.items():
        if 'Firestore' in sku and ('Read' in sku or 'Write' in sku):
            print('FIRESTORE_PRICING_UNITS', sku, unit, str(amount))
    return 0

if __name__ == '__main__':
    try:
        sys.exit(main())
    except urllib.error.HTTPError as error:
        print('COST_AUDIT_UNAVAILABLE_HTTP_' + str(error.code))
        sys.exit(5)
    except Exception as error:
        print('COST_AUDIT_FAILED_' + type(error).__name__)
        sys.exit(6)
