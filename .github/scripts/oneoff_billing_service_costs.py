#!/usr/bin/env python3
"""One-off, bounded, read-only Google Cloud Billing service-cost attribution."""
import json
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
SELECT FORMAT_DATE('%Y-%m', DATE(usage_start_time)) AS month,
       service.description AS service,
       ROUND(SUM(cost), 2) AS gross,
       ROUND(SUM(IFNULL((SELECT SUM(credit.amount)
             FROM UNNEST(credits) AS credit), 0)), 2) AS credits
FROM `%s.%s.%s`
WHERE DATE(usage_start_time) BETWEEN '2026-09-01' AND '2026-10-10'
GROUP BY month, service
ORDER BY month DESC, gross DESC
LIMIT 100
""" % (PROJECT, DATASET, table)
    payload = {
        "query": sql, "useLegacySql": False, "maximumBytesBilled": str(CAP_BYTES),
        "useQueryCache": True, "timeoutMs": 30000, "maxResults": 100, "location": "EU"
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
    print("Cost by service/month, raw usage charges and credits, no tax reconciliation")
    totals = {}
    rows = result.get("rows") or []
    for row in rows:
        cells = row.get("f") or []
        if len(cells) != 4:
            continue
        month, service, gross, credits = [str(x.get("v") or "") for x in cells]
        service = " ".join(service.split())[:75].replace("|", "/")
        gross_value = float(gross)
        credit_value = float(credits or 0)
        totals[month] = totals.get(month, 0) + gross_value + credit_value
        print(f"{month} | {service} | gross {gross_value:.2f} | credits {credit_value:.2f} | net {gross_value + credit_value:.2f}")
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
