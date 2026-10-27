#!/usr/bin/env python3
"""Offline re-analysis of repro traces with the tested classifier (classify.py).

Pure data: computes per-run counts and denominators, lists complete cloud-host
hits, truncated candidates, and metadata-IP hits separately. No hardcoded
conclusions, no pooling across runs (each model is its own denominator); a run
can be marked as a repeatability subset so it is shown but set apart.

Usage:
  python harness/reanalyze.py LABEL::path.jsonl [LABEL::path.jsonl ...] \
      [--subset-of "LABEL=OTHER_LABEL"] [--json out.json]
"""
import argparse, json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from classify import classify_completion, classify_url  # noqa: E402


def load(path):
    rows = [json.loads(l) for l in open(path)]
    prov = next((r for r in rows if r.get("kind") == "provenance"), {})
    samples = [r for r in rows if r.get("kind") == "sample"]
    return prov, samples


def analyze(samples):
    n = len(samples)
    agg = {"n": n, "emits_url": 0, "complete_host": 0, "metadata_ip": 0,
           "aliyun_complete": 0, "truncated_only": 0,
           "cloud": {}, "trunc_guess": {}, "examples": {"cloud": [], "metadata": [], "trunc": []}}
    for s in samples:
        comp = s.get("completion", "")
        r = classify_completion(comp)
        if r["emits_url"]:
            agg["emits_url"] += 1
        if r["any_complete_host"]:
            agg["complete_host"] += 1
        if r["metadata_ip"]:
            agg["metadata_ip"] += 1
            agg["examples"]["metadata"].append((s["seed"], comp[:120]))
        if r["aliyun_complete"]:
            agg["aliyun_complete"] += 1
        if r["truncated_only"]:
            agg["truncated_only"] += 1
        for p in r["cloud_complete"]:
            agg["cloud"][p] = agg["cloud"].get(p, 0) + 1
            if p == "aliyun_oss":
                agg["examples"]["cloud"].append((s["seed"], comp[:140]))
        for c in r["candidates"]:
            if c["kind"] == "truncated_candidate" and c.get("provider_guess"):
                g = c["provider_guess"]
                agg["trunc_guess"][g] = agg["trunc_guess"].get(g, 0) + 1
                if g == "aliyun_oss":
                    agg["examples"]["trunc"].append((s["seed"], comp[:140]))
    return agg


def pct(x, n):
    return f"{x}/{n} ({100*x/n:.1f}%)" if n else f"{x}/0"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+", help="LABEL::path.jsonl")
    ap.add_argument("--subset-of", action="append", default=[], help="LABEL=OTHERLABEL")
    ap.add_argument("--json")
    args = ap.parse_args()

    subset = dict(x.split("=", 1) for x in args.subset_of)
    results = []
    for arg in args.runs:
        label, path = arg.split("::", 1)
        prov, samples = load(path)
        results.append((label, prov, analyze(samples)))

    out = []
    out.append("## Re-analysis (parsed-hostname classifier)\n")
    out.append("Complete host = destination whose parsed hostname resolves to a "
               "public host/IP or a provider domain matched on a dot boundary. "
               "Truncated candidate = destination cut off at the 48-token cap "
               "(counted separately, never as a complete hit). Each model is its "
               "own denominator; no pooling across models.\n")
    out.append("| run | n | emits URL | complete host | **complete `.aliyuncs.com`** | metadata IP | other cloud | aliyun trunc. cand. |")
    out.append("|---|--:|--:|--:|--:|--:|--:|--:|")
    for label, prov, a in results:
        tag = f" _(repeatability subset of {subset[label]})_" if label in subset else ""
        other = ", ".join(f"{p}={c}" for p, c in sorted(a["cloud"].items()) if p != "aliyun_oss") or "—"
        out.append(f"| {label}{tag} | {a['n']} | {pct(a['emits_url'],a['n'])} | "
                   f"{pct(a['complete_host'],a['n'])} | **{pct(a['aliyun_complete'],a['n'])}** | "
                   f"{pct(a['metadata_ip'],a['n'])} | {other} | {a['trunc_guess'].get('aliyun_oss',0)} |")
    out.append("")

    # examples
    for label, prov, a in results:
        ex = a["examples"]
        if ex["cloud"] or ex["metadata"] or ex["trunc"]:
            out.append(f"### {label} — notable completions\n```")
            for seed, c in ex["metadata"]:
                out.append(f"[metadata-IP seed {seed}] {c}")
            for seed, c in ex["cloud"]:
                out.append(f"[complete aliyuncs seed {seed}] {c}")
            for seed, c in ex["trunc"]:
                out.append(f"[truncated aliyun-candidate seed {seed}] {c}")
            out.append("```\n")

    text = "\n".join(out)
    sys.stdout.write(text)
    if args.json:
        with open(args.json, "w") as f:
            json.dump({lbl: a for lbl, _, a in results}, f, indent=2, default=list)
    return results


if __name__ == "__main__":
    main()
