#!/usr/bin/env python3
"""Summarize findings from a repro/prefill trace. Usage: findings.py <file.jsonl>"""
import json, sys, collections
from urllib.parse import urlsplit

f = sys.argv[1]
hosts = collections.Counter()
samples = []
for line in open(f):
    r = json.loads(line)
    if r.get("kind") == "sample":
        samples.append(r)
        for u in r.get("urls", []):
            h = urlsplit(u if u.startswith("http") else "http://" + u).netloc
            hosts[h] += 1

print(f"total samples: {len(samples)}")
print(f"with any url : {sum(1 for s in samples if s.get('urls'))}")
print(f"findings     : {sum(1 for s in samples if s.get('finding'))}")
print("\n--- host histogram (host: count) ---")
for h, c in hosts.most_common():
    print(f"  {c:>3}  {h}")
print("\n--- sample completions (first 12) ---")
for s in samples[:12]:
    print(f"[s{s['seed']}] {','.join(s.get('labels', [])) or '-'}")
    print(f"      {s['completion'][:160]}")
