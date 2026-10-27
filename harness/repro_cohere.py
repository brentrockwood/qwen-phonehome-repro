#!/usr/bin/env python3
"""Faithful local reproduction of the Cohere Qwen investigation.

This mirrors CohereLabs/10-2026-qwen-investigation-traces' own reproduction
script, but runs inference LOCALLY against our Ollama qwen3.8 instead of remote
HF/Featherless. We take the recorded trace's first 2,323 token IDs (the prefix
that stops just before the URL, at the end of '...ABC123'), decode them with the
Qwen tokenizer, and feed that as a RAW prompt (no chat template) to Ollama with
Cohere's exact sampling params. We then sample N completions and classify where
the model says to send data.

Nothing the model emits is executed. URLs it produces are replayed to the local
capture sink so any egress intent is recorded. Every sample logs provenance and
the SHA-256 of the exact prompt, so a reviewer can confirm the input was the
published prefix, not something we wrote.

Usage (venv with pyarrow, tokenizers, huggingface_hub):
  python harness/repro_cohere.py --model qwen3.8:27b --n 64
"""
import argparse, hashlib, json, os, sys, time, urllib.request

import pyarrow.parquet as pq
from tokenizers import Tokenizer
from huggingface_hub import hf_hub_download

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sink_client  # noqa: E402
from classify import classify_completion  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TRACEDIR = os.path.join(HERE, "traces")
OLLAMA = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
SINK = os.environ.get("SINK", "http://127.0.0.1:8099")
DATASET = "CohereLabs/10-2026-qwen-investigation-traces"
PARQUET_IN_REPO = "data/train-00000-of-00001.parquet"
TOK_REPO = "Qwen/Qwen3.8-Flash-Next"
PREFIX_LEN = 2323  # per the dataset's reproduction script


def get_parquet():
    """Prefer a local copy under ./hf_dataset; otherwise fetch from HF (anon)."""
    local = os.path.join(ROOT, "hf_dataset", "train-00000-of-00001.parquet")
    if os.path.exists(local):
        return local
    from huggingface_hub import hf_hub_download
    return hf_hub_download(DATASET, PARQUET_IN_REPO, repo_type="dataset")

def generate(model, prompt, seed):
    """Return (response_text, done_reason). done_reason='length' means the output
    hit the token cap (useful for judging whether a trailing URL was cut)."""
    body = {"model": model, "prompt": prompt, "raw": True, "stream": False,
            "options": {"seed": seed, "temperature": 1.0, "top_p": 1.0, "top_k": 20,
                        "min_p": 0.0, "repeat_penalty": 1.0, "presence_penalty": 0.0,
                        "frequency_penalty": 0.0, "num_predict": 48}}
    req = urllib.request.Request(OLLAMA + "/api/generate",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.loads(r.read())
    return d.get("response", ""), d.get("done_reason")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen3.8:27b")
    ap.add_argument("--n", type=int, default=64)
    args = ap.parse_args()
    os.makedirs(TRACEDIR, exist_ok=True)

    ids = pq.read_table(get_parquet()).column("token_ids")[0].as_py()
    if len(ids) < PREFIX_LEN:
        raise SystemExit(f"trace shorter than {PREFIX_LEN}-token prefix")
    ids = ids[:PREFIX_LEN]

    tok = Tokenizer.from_file(hf_hub_download(TOK_REPO, "tokenizer.json"))
    prompt = tok.decode(ids, skip_special_tokens=False)
    reencoded = tok.encode(prompt, add_special_tokens=False).ids
    roundtrip = (reencoded == ids)
    prompt_sha = hashlib.sha256(prompt.encode()).hexdigest()
    print(f"prefix: {len(ids)} tokens | roundtrip_ok={roundtrip} | prompt_sha={prompt_sha[:16]}")
    print(f"prompt tail: ...{prompt[-60:]!r}")

    run_id = f"repro_{args.model.replace(':','-').replace('/','-')}_{int(time.time())}"
    tf = os.path.join(TRACEDIR, run_id + ".jsonl")

    def emit(**kw):
        with open(tf, "a") as f:
            f.write(json.dumps({"run_id": run_id, "ts": time.time(), **kw}, sort_keys=True) + "\n")

    # provenance
    prov = {}
    try:
        prov["ollama_version"] = json.loads(urllib.request.urlopen(OLLAMA + "/api/version", timeout=5).read())["version"]
        req = urllib.request.Request(OLLAMA + "/api/show", data=json.dumps({"model": args.model}).encode())
        d = json.loads(urllib.request.urlopen(req, timeout=10).read())
        prov["model_details"] = d.get("details")
    except Exception:
        pass
    emit(kind="provenance", model=args.model, dataset="CohereLabs/10-2026-qwen-investigation-traces",
         prefix_len=len(ids), roundtrip_ok=roundtrip, prompt_sha256=prompt_sha,
         sampling={"temperature": 1.0, "top_p": 1.0, "top_k": 20, "num_predict": 48},
         iso=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **prov)

    # Labels come from the shared, tested classifier (classify.py) so fresh runs
    # agree with the offline reanalysis. The full output is classified, not a
    # truncated display line.
    tally = {"samples": 0, "url_any": 0, "complete_host": 0, "aliyun_complete": 0,
             "metadata_ip": 0, "uncertain_only": 0}
    hits = []
    for i in range(args.n):
        text, done_reason = generate(args.model, prompt, i)
        first = text.splitlines()[0] if text else ""
        r = classify_completion(text)
        tally["samples"] += 1
        tally["url_any"] += int(r["emits_url"])
        tally["complete_host"] += int(r["any_complete_host"])
        tally["aliyun_complete"] += int(r["aliyun_complete"])
        tally["metadata_ip"] += int(r["metadata_ip"])
        tally["uncertain_only"] += int(r["uncertain_only"])
        finding = r["aliyun_complete"] or r["metadata_ip"] or bool(r["cloud_complete"])
        kinds = [c["kind"] for c in r["candidates"]]
        emit(kind="sample", seed=i, completion=first[:300], full=text[:500],
             done_reason=done_reason, candidate_kinds=kinds,
             cloud_complete=sorted(r["cloud_complete"]),
             aliyun_complete=r["aliyun_complete"], metadata_ip=r["metadata_ip"],
             finding=finding)
        # record outbound intent at the loopback sink (hardened client)
        for c in r["candidates"]:
            if c.get("host"):
                sink_client.replay(SINK, c["url"], {"seed": i, "src": "repro_cohere"})
        tag = ("  <-- " + ",".join(sorted(set(kinds)))) if finding else ""
        print(f"[{i+1}/{args.n}] {first[:110]!r}{tag}", flush=True)
        if finding:
            hits.append({"seed": i, "text": first[:200], "kinds": kinds})

    emit(kind="summary", tally=tally, n_findings=len(hits))
    print("\n=== SUMMARY (labels from classify.py; see reanalyze.py for full tables) ===")
    for k, v in tally.items():
        print(f"  {k}: {v}")
    print(f"  findings: {len(hits)}/{tally['samples']}")
    print(f"trace -> {tf}")


if __name__ == "__main__":
    main()
