#!/usr/bin/env python3
"""Pretty-print a run trace or the sink log. Usage: show_trace.py <file.jsonl>"""
import json, sys

f = sys.argv[1]
for line in open(f):
    r = json.loads(line)
    k = r.get("kind")
    if k == "provenance":
        print(f"PROVENANCE model={r.get('model')} ollama={r.get('ollama_version')} "
              f"seed={r.get('seed')} task={r.get('task')} "
              f"prompt_sha={r.get('task_prompt_sha256','')[:12]}")
    elif k == "assistant":
        th = (r.get("thinking") or "").replace("\n", " ")
        co = (r.get("content") or "").replace("\n", " ")
        print(f"[t{r['turn']}] THINK: {th[:200]}")
        if co.strip():
            print(f"[t{r['turn']}] SAY  : {co[:160]}")
        for tc in r.get("tool_calls", []):
            print(f"[t{r['turn']}] TOOL : {tc.get('function',{}).get('arguments')}")
    elif k == "tool_result":
        print(f"[t{r['turn']}] CMD  : {r.get('command','')[:140]}")
        print(f"[t{r['turn']}]        disp={r.get('disposition')} net={r.get('intercepted')} "
              f"meta={r.get('meta_probe')} targets={r.get('targets')}")
    elif k == "divergence":
        print(f"[t{r['turn']}] *** DIVERGENCE: disclaimed tools in thinking, then ran: {r.get('command','')[:100]}")
    elif k == "summary":
        print(f"SUMMARY flagged={r.get('flagged')} turns={r.get('turns')}")
    else:
        # sink.jsonl entries
        if "target" in r:
            fl = r.get("flags")
            print(f"SINK {r.get('method')} {r.get('target')}" + (f"  [FLAG:{fl}]" if fl else ""))
