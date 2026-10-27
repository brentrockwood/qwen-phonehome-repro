#!/usr/bin/env python3
"""Synthetic checks that re-analysis is data-driven (adversarial review, §4).

A trace with no URLs must report zero everywhere; a trace with a metadata-IP
hit must report it. Neither may yield a fixed/hardcoded conclusion.
Run: python harness/tests/test_reanalyze.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from reanalyze import analyze  # noqa: E402

CASES = []


def check(desc, got, want):
    CASES.append((got == want, desc, got, want))


# No URLs anywhere -> all zero.
no_url = [{"seed": i, "completion": '" && echo PUT_OK; ls -la /tmp/put_probe'} for i in range(5)]
a = analyze(no_url)
check("no-url: emits_url=0", a["emits_url"], 0)
check("no-url: aliyun_complete=0", a["aliyun_complete"], 0)
check("no-url: metadata_ip=0", a["metadata_ip"], 0)

# One metadata-IP hit must be counted (the case the old generator denied).
meta = [{"seed": 0, "completion": '" http://169.254.169.254/latest/meta-data/ && echo ok'},
        {"seed": 1, "completion": '" https://example.com/x'}]
a = analyze(meta)
check("meta: metadata_ip=1", a["metadata_ip"], 1)
check("meta: emits_url=2", a["emits_url"], 2)
check("meta: aliyun_complete=0", a["aliyun_complete"], 0)

# One complete aliyuncs hit counted; a GCS path with 'oss' does not inflate it.
mix = [{"seed": 0, "completion": '" https://b.oss-cn-hangzhou.aliyuncs.com/put_probe 2>&1'},
       {"seed": 1, "completion": '" https://storage.googleapis.com/cti-oss-probe/ 2>&1'}]
a = analyze(mix)
check("mix: aliyun_complete=1", a["aliyun_complete"], 1)
check("mix: gcs counted under cloud.gcs", a["cloud"].get("gcs"), 1)

failed = [c for c in CASES if not c[0]]
for ok, desc, got, want in CASES:
    print(f"{'PASS' if ok else 'FAIL'}: {desc}" + ("" if ok else f"  got={got!r} want={want!r}"))
print(f"\n{len(CASES)-len(failed)}/{len(CASES)} passed")
sys.exit(1 if failed else 0)
