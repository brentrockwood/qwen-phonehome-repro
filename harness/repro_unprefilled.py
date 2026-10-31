#!/usr/bin/env python3
"""Reconstruct the pinned unprefilled prompt; optionally request raw completions."""
import argparse
from datetime import datetime, timezone
import hashlib
import http.client
import importlib.metadata
import json
import os
from pathlib import Path
import re
import sys

DATASET = "CohereLabs/10-2026-qwen-investigation-traces"
DATASET_REV = "028b7cd7d931586dbfa05463903be9d45c4924ac"
DATASET_FILE = "data/train-00000-of-00001.parquet"
DATASET_SHA = "f8c4b224d7d45aabf8b817ed4a85d2dd58c2d239c8cf6ba78ce42c7ecfa61e8b"
MODEL = "Qwen/Qwen3.8-Flash-Next"
TOKENIZER_REV = "de4b8e4d43b917e7706784d8bb445c9af86a3540"
TOKENIZER_SHA = "0997f410c57a1f4e53b09e4be8f4a172d90edd9564368fb0847030937229b9f3"
PROMPT_SHA = "6839272dd4f395dff60628562679814dd3d30ef1edbe9413ec56890a1bddf406"
HOST = "router.huggingface.co"
ENDPOINT = "/featherless-ai/v1/completions"
ROUTE = "https://" + HOST + ENDPOINT
SETTINGS = dict(model=MODEL, temperature=1.0, top_p=1.0, top_k=20,
                min_p=0.0, presence_penalty=0.0, frequency_penalty=0.0,
                repetition_penalty=1.0, max_tokens=2048)
MAX_N = 64
MAX_RESPONSE = 4 * 1024 * 1024


def require(condition):
    if not condition:
        raise ValueError("Verification failed")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_prompt(prompt):
    require(hashlib.sha256(prompt.encode("utf-8")).hexdigest() == PROMPT_SHA)


def reconstruct(parquet, tokenizer):
    import pyarrow.parquet as pq
    from tokenizers import Tokenizer

    require(sha(parquet) == DATASET_SHA and sha(tokenizer) == TOKENIZER_SHA)
    ids = pq.read_table(parquet, columns=["token_ids"]).column("token_ids")[0].as_py()
    tok = Tokenizer.from_file(str(tokenizer))
    serialized = tok.decode(ids, skip_special_tokens=False)
    header = "<|im_start|>assistant\n"
    prompt = serialized[:serialized.index(header) + len(header)]
    prefix = tok.encode(prompt, add_special_tokens=False).ids
    require(len(prefix) == 2122 and prefix == ids[:2122])
    require(tok.decode(prefix, skip_special_tokens=False) == prompt)
    verify_prompt(prompt)
    return prompt


def prepare():
    from huggingface_hub import hf_hub_download

    # Public artifacts only: never use a saved Hub credential for downloads.
    parquet = hf_hub_download(DATASET, DATASET_FILE, repo_type="dataset",
                              revision=DATASET_REV, token=False)
    tokenizer = hf_hub_download(MODEL, "tokenizer.json", revision=TOKENIZER_REV,
                                token=False)
    return reconstruct(parquet, tokenizer)


def provenance():
    return dict(dataset=DATASET, dataset_revision=DATASET_REV,
                dataset_file=DATASET_FILE, dataset_sha256=DATASET_SHA,
                tokenizer=MODEL, tokenizer_revision=TOKENIZER_REV,
                tokenizer_sha256=TOKENIZER_SHA, prompt_sha256=PROMPT_SHA,
                token_count=2122, assistant_content_supplied=False,
                route=ROUTE, settings=SETTINGS, harness_sha256=sha(__file__),
                python=sys.version.split()[0],
                packages={name: importlib.metadata.version(name) for name in
                          ("pyarrow", "tokenizers", "huggingface_hub")})


def redact(text, token):
    text = text.replace(token, "[REDACTED]") if token else text
    return re.sub(r"hf_[A-Za-z0-9_-]+|(?i:Bearer)\s+\S+", "[REDACTED]", text)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result)
        result[key] = value
    return result


def dispatch(prompt, token):
    result = {"outcome": "unknown"}
    connection = None
    try:
        # Direct TLS: no environment proxies, netrc, redirects, or retries.
        connection = http.client.HTTPSConnection(HOST, timeout=180)
        connection.request("POST", ENDPOINT,
                           body=json.dumps(dict(SETTINGS, prompt=prompt)).encode("utf-8"),
                           headers={"Content-Type": "application/json",
                                    "Authorization": "Bearer " + token})
        response = connection.getresponse()
        result["status_code"] = response.status
        require(response.status == 200)
        body = response.read(MAX_RESPONSE + 1)
        require(len(body) <= MAX_RESPONSE)
        raw = json.loads(body, object_pairs_hook=unique_object)
        require(isinstance(raw, dict) and "error" not in raw and raw.get("model") == MODEL)
        choices, usage = raw.get("choices"), raw.get("usage")
        require(isinstance(choices, list) and len(choices) == 1)
        choice = choices[0]
        require(isinstance(choice, dict) and type(choice.get("index")) is int and choice["index"] == 0)
        require(isinstance(choice.get("text"), str) and choice.get("finish_reason") in ("stop", "length"))
        keys = ("prompt_tokens", "completion_tokens", "total_tokens")
        require(isinstance(usage, dict) and all(type(usage.get(k)) is int and usage[k] >= 0 for k in keys))
        require(usage["prompt_tokens"] > 0 and usage["completion_tokens"] <= SETTINGS["max_tokens"])
        require(usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"])
        completion = redact(choice["text"], token)
        result.update(outcome="success", completion=completion,
                      completion_redacted=completion != choice["text"],
                      finish_reason=choice["finish_reason"],
                      usage={k: usage[k] for k in keys}, reported_model=MODEL)
    except Exception:
        # Do not persist bodies, headers or exception strings from failed requests.
        result["error"] = "Unverified response or transport failure; stop and review."
    finally:
        if connection is not None:
            connection.close()
    return result


def emit(stream, record):
    stream.write(json.dumps(record, ensure_ascii=True) + "\n")
    stream.flush()
    os.fsync(stream.fileno())


def run(prompt, n, output, token):
    require(type(n) is int and 1 <= n <= MAX_N)
    verify_prompt(prompt)
    require(bool(token) and token.isascii() and not any(c.isspace() for c in token))
    # Exclusive creation prevents accidental overwrite/resume of ambiguous attempts.
    with Path(output).open("x", encoding="utf-8") as stream:
        emit(stream, dict(kind="provenance", requested_attempts=n, **provenance()))
        # Persist the new filename as well as its contents before any request.
        directory = os.open(Path(output).parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        for attempt in range(1, n + 1):
            emit(stream, dict(kind="attempt", attempt=attempt, outcome="pending",
                              started_at=datetime.now(timezone.utc).isoformat()))
            result = dispatch(prompt, token)
            emit(stream, dict(kind="result", attempt=attempt, **result))
            if result["outcome"] != "success":
                return False
    return True


def count(value):
    try:
        n = int(value)
        require(1 <= n <= MAX_N)
        return n
    except ValueError:
        raise argparse.ArgumentTypeError("--n must be between 1 and 64") from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--n", type=count)
    parser.add_argument("--output", type=Path, help="New JSONL file; parent directory must exist")
    args = parser.parse_args(argv)
    if args.prepare_only:
        if args.n is not None or args.output is not None:
            parser.error("--prepare-only cannot be combined with --n or --output")
    elif args.n is None or args.output is None:
        parser.error("Inference requires explicit --n and --output")
    try:
        prompt = prepare()
        if args.prepare_only:
            print(json.dumps(provenance(), sort_keys=True))
            return 0
        if run(prompt, args.n, args.output, os.environ.get("HF_TOKEN", "")):
            return 0
    except (Exception, KeyboardInterrupt):
        pass
    print("Stopped. Review any JSONL attempts; no automatic recovery or retry.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
