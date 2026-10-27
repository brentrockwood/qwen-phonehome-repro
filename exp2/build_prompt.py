#!/usr/bin/env python3
"""Build and verify the condition-B prompt (upload command removed).

Condition B (per notes/before-curl-run-authorization.md): take Cohere's recorded
token sequence and cut immediately BEFORE the relevant `curl` upload command,
preserving all preceding context verbatim and supplying none of that command.

The cut is defined structurally: the upload command is the third occurrence of
the string "curl" in the decoded trace (the first is in the user task text —
"...monitoring for curl processes..."; the second is the `which curl wget ...`
inventory). We keep the largest token prefix containing only those first two.

Writes exp2/manifest.json with the prompt text, token count, SHA-256, cut index,
and an inventory of what the retained context already contains. No inference.
"""
import hashlib, json, os, sys

import pyarrow.parquet as pq
from tokenizers import Tokenizer
from huggingface_hub import hf_hub_download

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PARQUET = os.path.join(ROOT, "hf_dataset", "train-00000-of-00001.parquet")
TOK_REPO = "Qwen/Qwen3.8-Flash-Next"
A_PREFIX_LEN = 2323  # the original URL-prefilled control


def build():
    ids = pq.read_table(PARQUET).column("token_ids")[0].as_py()
    tok = Tokenizer.from_file(hf_hub_download(TOK_REPO, "tokenizer.json"))

    b_len = None
    for k in range(A_PREFIX_LEN, A_PREFIX_LEN - 120, -1):
        if tok.decode(ids[:k], skip_special_tokens=False).count("curl") <= 2:
            b_len = k
            break
    if b_len is None:
        raise SystemExit("could not locate the upload-curl boundary")

    prompt = tok.decode(ids[:b_len], skip_special_tokens=False)
    roundtrip = tok.encode(prompt, add_special_tokens=False).ids == ids[:b_len]
    if not roundtrip:
        raise SystemExit("ABORT: decode->encode of condition-B prompt does not round-trip")

    manifest = {
        "condition": "B (before upload curl command)",
        "source_dataset": "CohereLabs/10-2026-qwen-investigation-traces",
        "a_control_prefix_len": A_PREFIX_LEN,
        "b_cut_token_index": b_len,
        "tokens_removed_vs_A": A_PREFIX_LEN - b_len,
        "total_trace_tokens": len(ids),
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "roundtrip_ok": roundtrip,
        "prompt_tail_last_160_chars": prompt[-160:],
        "retained_already_contains": {
            "upload_curl_fragment (curl -s / put_probe / PROBE_PAYLOAD)":
                any(s in prompt for s in ("curl -s", "put_probe", "PROBE_PAYLOAD")),
            "which_curl_inventory": "which curl" in prompt,
            "resolv_conf_read": "resolv.conf" in prompt,
            "urls_present": __import__("re").findall(r"https?://[^\s\"'<>]+", prompt),
        },
        "boundary_note": (
            "B retains an OPEN bash tool-call performing recon (ls /tmp; which "
            "curl wget python3 jq; cat /etc/resolv.conf | head; echo '---';) and "
            "the model continues that command chain. B is primed with recon, not "
            "unprimed. No destination URL or payload is supplied before the cut."),
    }
    with open(os.path.join(HERE, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    return prompt, b_len, manifest


if __name__ == "__main__":
    prompt, b_len, m = build()
    print(json.dumps({k: v for k, v in m.items() if k != "prompt_tail_last_160_chars"}, indent=2))
    print("tail:", repr(m["prompt_tail_last_160_chars"]))
    print("wrote exp2/manifest.json")
