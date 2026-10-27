#!/usr/bin/env python3
"""Condition-B sampler: offline generation, no execution, no network to anywhere
but the inference server.

Pilot:  python exp2/run_ablation.py --mode pilot
Main :  python exp2/run_ablation.py --mode main --deadline-seconds 14400

Frozen config (per notes/before-curl-run-authorization.md): BF16 artifact,
temp 1.0 / top_p 1.0 / top_k 20 / min_p 0 / penalties off, num_predict 512,
num_ctx 8192, raw prompt (no template re-application). Full untruncated
responses are saved; each is auto-scored (triage only) by exp2/score.py.
Checkpoints are written to notes/before-curl-status.md and exp2/checkpoints.log
at least every 15 minutes.
"""
import argparse, json, os, subprocess, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from build_prompt import build  # noqa: E402
from score import score  # noqa: E402

OLLAMA = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
STATUS = os.path.join(ROOT, "notes", "before-curl-status.md")
CKPT_LOG = os.path.join(HERE, "checkpoints.log")
OPTS = {"temperature": 1.0, "top_p": 1.0, "top_k": 20, "min_p": 0.0,
        "repeat_penalty": 1.0, "presence_penalty": 0.0, "frequency_penalty": 0.0,
        "num_predict": 512, "num_ctx": 8192}


def git_commit():
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT).decode().strip()
    except Exception:
        return "unknown"


def provenance(model):
    out = {"ollama_version": None, "model_digest": None, "model_details": None}
    try:
        out["ollama_version"] = json.loads(urllib.request.urlopen(OLLAMA + "/api/version", timeout=5).read())["version"]
        req = urllib.request.Request(OLLAMA + "/api/show", data=json.dumps({"model": model}).encode())
        d = json.loads(urllib.request.urlopen(req, timeout=15).read())
        out["model_details"] = d.get("details")
    except Exception as e:
        out["prov_error"] = str(e)
    return out


def generate(model, prompt, seed):
    body = {"model": model, "prompt": prompt, "raw": True, "stream": False,
            "options": {**OPTS, "seed": seed}}
    req = urllib.request.Request(OLLAMA + "/api/generate", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.loads(r.read())
    return {
        "response": d.get("response", ""),
        "done_reason": d.get("done_reason"),
        "prompt_eval_count": d.get("prompt_eval_count"),
        "eval_count": d.get("eval_count"),
        "elapsed_s": round(time.monotonic() - t0, 2),
    }


def write_status(state, run_id, model, counts, started, deadline, last_success, candidates):
    now = time.time()
    remaining = max(0, deadline - now) if deadline else None
    lines = [
        f"# before-curl condition-B run — {state}",
        "",
        f"- run_id: `{run_id}`",
        f"- model: `{model}`  | harness commit: `{git_commit()}`",
        f"- prompt: condition B, 2294 tokens, sha256 `da87cfad…` (see exp2/manifest.json)",
        f"- config: num_predict {OPTS['num_predict']}, num_ctx {OPTS['num_ctx']}, temp 1.0/top_p 1.0/top_k 20",
        f"- started: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(started))}",
        (f"- deadline: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(deadline))}"
         f"  (remaining ~{int(remaining)//60} min)" if deadline else "- deadline: n/a (pilot)"),
        "",
        "## counts",
        f"- attempted: {counts['attempted']}",
        f"- succeeded: {counts['succeeded']} | failed/errors: {counts['failed']}",
        f"- capped (done_reason=length): {counts['capped']}",
        f"- **candidate introduced-uploads (triage, unconfirmed): {counts['candidates']}**",
        f"- read-only fetch: {counts['read_fetch']} | inventory: {counts['inventory']} | no-action: {counts['none']}",
        f"- metadata-IP URL occurrences: {counts['metadata']} | complete aliyuncs: {counts['aliyun']}",
        f"- last success: {time.strftime('%H:%M:%SZ', time.gmtime(last_success)) if last_success else 'n/a'}",
        "",
        "## candidate uploads (need human adjudication)",
    ]
    for c in candidates[-20:]:
        lines.append(f"- seed {c['seed']} [{c['payload']}/{c['destination']}/{c['http_method']}]: `{c['evidence'][:140]}`")
    if not candidates:
        lines.append("- none so far")
    lines += ["", "_Automated detection is triage, not ground truth. Candidate counts are not "
              "confirmed upload counts. Nothing generated was executed._", ""]
    with open(STATUS, "w") as f:
        f.write("\n".join(lines))
    with open(CKPT_LOG, "a") as f:
        f.write(json.dumps({"ts": now, "iso": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now)),
                            "state": state, **counts}) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen3.8:27b-bf16")
    ap.add_argument("--mode", choices=["pilot", "main"], required=True)
    ap.add_argument("--seed-start", type=int)
    ap.add_argument("--count", type=int, default=8)              # pilot
    ap.add_argument("--deadline-seconds", type=int, default=14400)  # main: 4h
    args = ap.parse_args()
    seed_start = args.seed_start if args.seed_start is not None else (10000 if args.mode == "pilot" else 20000)

    prompt, b_len, manifest = build()
    run_id = f"ablB_{args.mode}_{args.model.replace(':', '-')}_{int(time.time())}"
    tf = os.path.join(HERE, "traces", run_id + ".jsonl")

    def emit(**kw):
        with open(tf, "a") as f:
            f.write(json.dumps({"run_id": run_id, "ts": time.time(), **kw}, sort_keys=True) + "\n")

    started = time.time()
    deadline = (started + args.deadline_seconds) if args.mode == "main" else None
    emit(kind="provenance", mode=args.mode, model=args.model, seed_start=seed_start,
         harness_commit=git_commit(), prompt_sha256=manifest["prompt_sha256"],
         b_cut_token_index=b_len, options=OPTS, manifest=manifest,
         started_iso=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(started)),
         deadline_iso=(time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(deadline)) if deadline else None),
         **provenance(args.model))

    counts = {k: 0 for k in ("attempted", "succeeded", "failed", "capped", "candidates",
                             "read_fetch", "inventory", "none", "metadata", "aliyun")}
    candidates = []
    last_success = None
    last_ckpt = 0
    seed = seed_start
    while True:
        if args.mode == "pilot" and counts["attempted"] >= args.count:
            break
        if args.mode == "main" and time.time() >= deadline:
            break
        counts["attempted"] += 1
        try:
            g = generate(args.model, prompt, seed)
            sc = score(g["response"], g["done_reason"])
            counts["succeeded"] += 1
            last_success = time.time()
            if g["done_reason"] == "length":
                counts["capped"] += 1
            if sc["action_introduced"] == "read_only_fetch":
                counts["read_fetch"] += 1
            elif sc["action_introduced"] == "inventory":
                counts["inventory"] += 1
            elif sc["action_introduced"] == "none":
                counts["none"] += 1
            if sc["destination"] == "metadata_ip":
                counts["metadata"] += 1
            if sc["aliyun_complete"]:
                counts["aliyun"] += 1
            if sc["primary_positive"]:
                counts["candidates"] += 1
                candidates.append({"seed": seed, "payload": sc["payload"],
                                   "destination": sc["destination"], "http_method": sc["http_method"],
                                   "evidence": sc["evidence_span"]})
            emit(kind="sample", seed=seed, **g, score=sc)
        except Exception as e:
            counts["failed"] += 1
            emit(kind="error", seed=seed, error=str(e))
        seed += 1
        if time.time() - last_ckpt >= 900 or args.mode == "pilot":
            write_status("pilot" if args.mode == "pilot" else "main running",
                         run_id, args.model, counts, started, deadline, last_success, candidates)
            last_ckpt = time.time()

    finished = time.time()
    emit(kind="summary", counts=counts, candidates=candidates, started=started,
         finished=finished, duration_s=round(finished - started, 1))
    write_status("complete", run_id, args.model, counts, started, deadline, last_success, candidates)
    print(f"[{args.mode} done] attempted={counts['attempted']} succeeded={counts['succeeded']} "
          f"candidates={counts['candidates']} duration={int(finished-started)}s")
    print(f"trace -> {tf}")


if __name__ == "__main__":
    main()
