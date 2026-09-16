"""Summarise exported [db-transfer] Render log lines, without database queries.

Usage: python tools/db_transfer_report.py worker-and-api.log
Estimates are consumed value bytes, NOT provider egress. Keep both service logs.
"""
import collections
import json
import sys

totals=collections.defaultdict(lambda:collections.Counter())
families=collections.defaultdict(lambda:collections.Counter())
for path in sys.argv[1:]:
    with open(path,encoding="utf-8") as source:
        for line in source:
            if "[db-transfer] " not in line:
                continue
            try:
                event=json.loads(line.split("[db-transfer] ",1)[1])
            except (ValueError,TypeError):
                continue
            key=(event["hour"][:10],event["role"],event["revision"])
            totals[key].update(event["totals"])
            for family,counts in event.get("top",[]):
                families[(key[0],family)].update(counts)
print("CONSUMED VALUE MB — NOT BILLED EGRESS; missing service logs mean incomplete coverage")
for (day,role,revision),counts in sorted(totals.items()):
    print(day,role,revision[:8],round(counts["row_bytes"]/1e6,3),"MB",
          counts["connections"],"connections",counts["calls"],"calls",counts["errors"],"errors")
print("Top families (top-eight log excerpts; totals above include all families)")
for (day,family),counts in sorted(families.items(),key=lambda x:x[1]["row_bytes"],reverse=True)[:20]:
    print(day,family,round(counts["row_bytes"]/1e6,3),"MB")
