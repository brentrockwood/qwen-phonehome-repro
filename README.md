# qwen-phonehome-repro

A small, self-contained harness that **replicates Cohere's prefix-continuation
experiment** on Qwen3.8 and captures the traces, running entirely on a
**locally self-hosted** copy of the model via [Ollama](https://ollama.com).

> **Naming note.** "phone-home" names the phenomenon Cohere studied; this repo
> reproduces their *prefix-continuation* experiment and does not claim to show
> spontaneous initiation. See below.

- Cohere write-up: <https://cohere.com/blog/concerning-behaviour-popular-open-weight-ai-model>
- Cohere's published trace + token IDs: [`CohereLabs/10-2026-qwen-investigation-traces`](https://huggingface.co/datasets/CohereLabs/10-2026-qwen-investigation-traces)

## What this measures (and what it does not)

The input is Cohere's published 2,323-token prefix, which **already contains the
start of an upload command**:

```
curl -s -m 10 -o /tmp/put_probe -X PUT --data-binary "PROBE_PAYLOAD_ABC123
```

The model only generates what comes next — the **destination**. So this measures
*where a self-hosted Qwen sends data when an upload command is already in its
context*, and reproduces Cohere's prefix-completion result.

It does **not** show the model independently *deciding* to phone home from a
benign task (that decision is pre-seeded in the prefix), and it establishes
nothing about who owns a generated endpoint or whether any transfer would
succeed. Treat a provider-domain string as a generated string, not as evidence of
intent or a backdoor. See [`results/METHODOLOGY.md`](results/METHODOLOGY.md),
which records the corrections an adversarial review forced on the first draft.

Every input and output is recorded for audit; **nothing generated is executed**.

## What's here

| File | Purpose |
|------|---------|
| `harness/repro_cohere.py` | **Faithful reproduction.** Replays Cohere's exact 2,323-token prefix (decoded from their published `token_ids`) against your local model with their exact sampling params, samples N completions, classifies and logs each. |
| `harness/sink.py` | **Capture sink.** A catch-all HTTP server standing in for "the internet". Any URL a generated command would hit is replayed here and logged (flags cloud-metadata IPs and object-storage hosts). Nothing is ever sent to a real host. |
| `harness/classify.py` + `harness/tests/` | **Destination classifier** (parsed hostnames, dot-boundary provider matching, IP parsing) and its regression tests. Single source of truth for analysis and reporting. |
| `harness/reanalyze.py` | **Offline re-analysis.** Applies the classifier to trace files and emits per-model counts with denominators. No hardcoded conclusions. |
| `harness/run_agent.py` | **Agentic probe (secondary, records only).** Puts the model in a tool-use loop on a benign task and records what it emits. Executes nothing: no subprocess, no filesystem, no real network. |
| `harness/prefill_probe.py` | **Text-prefill probe (secondary).** Plain-text command prefixes across graduated tiers. |
| `harness/findings.py`, `harness/show_trace.py` | Trace summarizers. |

## Safety model

- **No generated command is ever executed.** The repro path only samples text.
  The agentic probe (`run_agent.py`) executes nothing — no subprocess, no
  filesystem access, no real network — it records the command's classification
  and returns canned fixtures so the loop can progress.
- **The sink is a loopback recorder, not an egress policy.** Destinations are
  recorded at `127.0.0.1`; proxies and redirects are disabled on that path. This
  records what the model *tries* to do. It is **not** a substitute for real
  egress enforcement on a live agent. Downloading the dataset/tokenizer from
  Hugging Face is a separate, intentional network operation.

## Reproduce

Prereqs: an Ollama server with a Qwen3.8 model pulled, and Python 3.10+.

```bash
# 1. model (self-hosted)
ollama pull qwen3.8:27b            # or a higher-precision tag, see Notes

# 2. deps for the faithful-repro path
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

# 3. start the capture sink (separate terminal)
python harness/sink.py --port 8099

# 4. run the reproduction (downloads Cohere's dataset from HF at runtime)
python harness/repro_cohere.py --model qwen3.8:27b --n 64
```

Each sample prints the model's completion and is appended to
`harness/traces/repro_*.jsonl` with provenance (Ollama version, model details,
the SHA-256 of the exact prompt, round-trip check, sampling config). Summarize
with:

```bash
python harness/findings.py harness/traces/<the-run>.jsonl
```

Reclassify any run offline with the tested classifier:

```bash
python harness/reanalyze.py "Q4 n=256::harness/traces/<run>.jsonl"
python harness/tests/test_classify.py && python harness/tests/test_reanalyze.py
```

## Results

Self-hosted `qwen3.8:27b` (Ollama 0.33.3), Cohere's token-exact prefix and
sampling config. Counts from `harness/classify.py` (parsed hostnames); each model
is its own denominator; **nothing executed**.

| run | n | emits URL | complete `.aliyuncs.com` | metadata IP | other cloud (complete) |
|-----|--:|--:|--:|--:|--|
| Q4_K_M | 256 | 98.8% | 2 (0.8%) | 0 | S3=3, GCS=2 |
| Q8_0   | 256 | 98.8% | 2 (0.8%) | 0 | S3=2 |
| bf16   | 256 | 98.4% | 0 (0.0%) | 5 (2.0%) | — |

(Q4 n=64 is a repeatability subset — seeds 0–63 of Q4 n=256 — and is excluded
above.)

Given the pre-seeded upload command, ~99% of completions supply a destination.
Complete `.aliyuncs.com` hostnames appear at low rate on Q4/Q8 (e.g.
`eval-llm-1.oss-ap-southeast-1.aliyuncs.com`); **bf16 instead produces
cloud-metadata-IP probes** (5/256), including the AWS IMDS credential path
`169.254.169.254/latest/meta-data/iam/security-credentials/`. We did **not** reach
the ~28% `.aliyuncs.com` rate Cohere reported from full precision, and we do not
claim an explanation for the gap. Full tables, verbatim completions, and the
defensible conclusion: [`results/SUMMARY.md`](results/SUMMARY.md); provenance and
corrections: [`results/METHODOLOGY.md`](results/METHODOLOGY.md).

## Notes / caveats

- **Precision changes the distribution, not monotonically.** Across Q4_K_M, Q8_0
  and bf16 the destination-continuation rate is ~99% throughout, but the sensitive
  *tail* differs: complete `.aliyuncs.com` at Q4/Q8 (2/256 each, 0 at bf16),
  cloud-metadata-IP probes at bf16 (5/256, 0 at Q4/Q8). With counts this small we
  report numbers and denominators rather than asserting a precision law.
- **Model identity is assumed from tag naming**, not proven against Cohere's
  source checkpoint; and how each quant was produced is not established. See
  [`results/METHODOLOGY.md`](results/METHODOLOGY.md) for digests and the known
  provenance gaps (including that the tokenizer round-trip does not verify the
  bytes Ollama actually consumed).
- **Rare-event.** Cohere note "many trials may be required"; expect run-to-run
  variance. Determinism here: fixed per-sample seeds and pinned sampling params.

## Attribution

Reproduction prefix, sampling configuration, and the original trace are from
Cohere's public dataset (above). This harness only drives a local model with
that published input and records what comes back.
