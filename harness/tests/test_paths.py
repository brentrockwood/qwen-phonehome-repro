#!/usr/bin/env python3
"""Integration checks that the fixes reached the MAIN paths, not just offline
analysis (adversarial review 2, acceptance #1 and #2).
Run: python harness/tests/test_paths.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import repro_cohere          # noqa: E402  (imports without network)
import prefill_probe         # noqa: E402
import sink_client           # noqa: E402
from classify import classify_completion  # noqa: E402

CASES = []


def check(desc, got, want):
    CASES.append((got == want, desc, got, want))


# #1: the sampling path uses the shared, tested classifier...
check("repro_cohere uses shared classifier",
      repro_cohere.classify_completion is classify_completion, True)
# ...and therefore does not recreate the Google-path false positive on fresh runs.
r = repro_cohere.classify_completion('" https://storage.googleapis.com/cti-oss-probe/ 2>&1')
check("sampling path: googleapis is not aliyun", r["aliyun_complete"], False)

# #2: every replay path goes through the hardened sink client...
check("repro_cohere replays via sink_client", hasattr(repro_cohere, "sink_client"), True)
check("prefill_probe replays via sink_client", hasattr(prefill_probe, "sink_client"), True)
# ...which refuses a non-loopback sink WITHOUT sending traffic.
check("loopback accepted", sink_client.is_loopback("http://127.0.0.1:8099"), True)
check("remote sink not loopback", sink_client.is_loopback("http://evil.example.com:8099"), False)
msg = sink_client.replay("http://evil.example.com:8099", "http://x.oss.aliyuncs.com/p", {})
check("replay to remote sink is refused", msg.startswith("refused"), True)
# redirects are refused by construction: the opener carries a no-redirect handler.
check("sink opener blocks redirects", any(
    type(h).__name__ == "_NoRedirect" for h in sink_client._OPENER.handlers), True)

# R3 §2: malformed destination / sink return a status string, never raise.
def _no_raise(desc, fn):
    try:
        r = fn()
        check(desc, isinstance(r, str), True)
    except Exception as e:
        check(desc, f"raised {e!r}", "a status string")

_no_raise("malformed URL returns a string, not an exception",
          lambda: sink_client.replay("http://127.0.0.1:8099", "https://[", {}))
_no_raise("malformed sink returns a string, not an exception",
          lambda: sink_client.replay("http://[", "http://x.aliyuncs.com/p", {}))

failed = [c for c in CASES if not c[0]]
for ok, desc, got, want in CASES:
    print(f"{'PASS' if ok else 'FAIL'}: {desc}" + ("" if ok else f"  got={got!r} want={want!r}"))
print(f"\n{len(CASES)-len(failed)}/{len(CASES)} passed")
sys.exit(1 if failed else 0)
