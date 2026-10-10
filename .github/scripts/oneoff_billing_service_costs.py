#!/usr/bin/env python3
"""One-off, bounded, read-only Google Cloud Billing service-cost attribution."""
import json
from decimal import Decimal, InvalidOperation
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

PROJECT = "tradementor-production"
DATASET = "cloud_billing_costs"
API = "https://bigquery.googleapis.com/bigquery/v2/projects/"
CAP_BYTES = 50 * 1024 * 1024


def api_json(url, token, body=None):
    headers = {"Authorization": "Bearer " + token}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        url, data=(json.dumps(body).encode("utf-8") if body is not None else None),
        headers=headers, method="POST" if body is not None else "GET"
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.load(response)


def main():
    token = os.environ.get("GOOGLE_ACCESS_TOKEN", "")
    if not token:
        print("COST_AUDIT_AUTH_UNAVAILABLE")
        return 1
    listing = api_json(API + PROJECT + "/datasets/" + DATASET + "/tables?maxResults=100", token)
    candidates = [
        str(t.get("tableReference", {}).get("tableId", ""))
        for t in listing.get("tables", [])
    ]
    table = next((t for t in candidates
                  if t.startswith("gcp_billing_export_v1_") and
                  re.fullmatch(r"[A-Za-z0-9_]+", t)), None)
    if not table:
        print("STANDARD_EXPORT_TABLE_NOT_VISIBLE")
        return 2
    sql = """
SELECT CAST(DATE(usage_start_time) AS STRING) AS usage_day,
       service.description AS service,
       ROUND(SUM(cost), 2) AS gross,
       ROUND(SUM(IFNULL((SELECT SUM(credit.amount)
             FROM UNNEST(credits) AS credit), 0)), 2) AS credits
FROM `%s.%s.%s`
WHERE DATE(usage_start_time) BETWEEN '2026-09-01' AND '2026-10-10'
GROUP BY usage_day, service
ORDER BY usage_day DESC, gross DESC
LIMIT 500
""" % (PROJECT, DATASET, table)
    payload = {
        "query": sql, "useLegacySql": False, "maximumBytesBilled": str(CAP_BYTES),
        "useQueryCache": False, "timeoutMs": 30000, "maxResults": 500, "location": "EU"
    }
    result = api_json(API + PROJECT + "/queries", token, payload)
    if not result.get("jobComplete", False):
        job_id = str(result.get("jobReference", {}).get("jobId") or "")
        if not re.fullmatch(r"[A-Za-z0-9_\-]+", job_id):
            print("QUERY_PENDING_NO_VALID_JOB_REFERENCE")
            return 3
        url = API + PROJECT + "/queries/" + urllib.parse.quote(job_id) + "?location=EU&maxResults=100"
        for attempt in range(6):
            time.sleep(3)
            result = api_json(url, token)
            if result.get("jobComplete"):
                break
    if not result.get("jobComplete"):
        print("QUERY_STILL_RUNNING_NO_RESULTS")
        return 4
    print("COST_AUDIT_ONE_TIME | PERIOD 2026-09-01..2026-10-10 | BILLING_CURRENCY EUR")
    print("Cost by usage day/service, raw usage charges and credits; no tax reconciliation; October only if exported")
    totals = {}
    latest_day = ""
    earliest_day = "9999-99-99"
    october_rows = 0
    rows = result.get("rows") or []
    skipped = 0
    for row in rows:
        cells = row.get("f") or []
        if len(cells) != 4:
            continue
        usage_day, service, gross, credits = [str(x.get("v") if x.get("v") is not None else "") for x in cells]
        service = " ".join(service.split())[:75].replace("|", "/")
        try:
            gross_value = float(Decimal(gross))
            credit_value = float(Decimal(credits)) if credits else 0.0
        except (InvalidOperation, ValueError, TypeError):
            skipped += 1
            continue
        month = usage_day[:7]
        latest_day = max(latest_day, usage_day)
        earliest_day = min(earliest_day, usage_day)
        october_rows += int(month == "2026-10")
        totals[month] = totals.get(month, 0) + gross_value + credit_value
        print(f"{usage_day} | {service} | gross {gross_value:.2f} | credits {credit_value:.2f} | net {gross_value + credit_value:.2f}")
    print(f"COVERAGE_FIRST_DAY {earliest_day if rows else 'NONE'}")
    print(f"COVERAGE_LAST_DAY {latest_day or 'NONE'}")
    print(f"OCTOBER_SERVICE_DAY_ROWS {october_rows}")
    print(f"SKIPPED_UNPARSABLE_ROWS {skipped}")
    if not rows:
        print("NO_COST_ROWS_AVAILABLE")
    for month, total in sorted(totals.items()):
        print(f"MONTH_NET_TOTAL {month}: {total:.2f}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except urllib.error.HTTPError as error:
        try:
            status = (json.load(error).get("error") or {}).get("status") or "OTHER"
        except Exception:
            status = "UNREADABLE"
        print(f"COST_AUDIT_HTTP_{error.code}_{status}")
        sys.exit(5)
    except Exception as error:
        # Exception class only: no tokens, response data, SQL, IDs or account values.
        print("COST_AUDIT_FAILED_" + type(error).__name__)
        sys.exit(6)
