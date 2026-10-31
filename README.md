# qwen-phonehome-repro

Reproduction experiments for Cohere's report of unsolicited upload behavior in
Qwen models. This repository separates two different questions:

| Experiment | Question | Observed result |
|---|---|---|
| [Unprefilled Flash-Next](results/flash-next-unprefilled/README.md) | Does the model initiate an upload from Cohere's published prompt, without an assistant prefill? | No unsolicited upload/phone-home behavior observed in **71,518 reviewed successful responses**. **30 unknown outcomes** are excluded from that conclusion. |
| [Local prefix continuation](results/SUMMARY.md) | Given the beginning of an upload command, what destination does the model generate next? | Destination distributions across three locally hosted Qwen variants; not evidence of spontaneous initiation. |

The unprefilled experiment uses `Qwen/Qwen3.8-Flash-Next` through Hugging Face's
Featherless route. The prefix-continuation experiment runs locally through
[Ollama](https://ollama.com). Neither executes generated commands.

> **Naming note.** "phone-home" names the phenomenon under investigation, not a
> finding that these experiments established it.

- Cohere write-up: <https://cohere.com/blog/concerning-behaviour-popular-open-weight-ai-model>
- Cohere's published trace + token IDs: [`CohereLabs/10-2026-qwen-investigation-traces`](https://huggingface.co/datasets/CohereLabs/10-2026-qwen-investigation-traces)

## Unprefilled Flash-Next results

The [results package](results/flash-next-unprefilled/README.md) contains the
observed outputs, denominators, review method, and limitations. The
[reproduction guide](results/flash-next-unprefilled/REPRODUCE.md) reconstructs the
exact 2,122-token input and sampling settings for new trials. These are repeated
single-completion samples, not an executing agent or a multi-turn rollout.
A negative result at this scale does not rule out rarer behavior or establish
that the hosted model matches Cohere's original weights and serving stack.

## How to read the local prefix-continuation results

The earlier local experiment asks a narrow question: **if a model is given most of an upload
command, what destination does it generate next?** It does not test whether the
model independently chooses to upload anything.

We replayed Cohere's published 2,323-token prefix — which already contains the
start of an upload command —

```
curl -s -m 10 -o /tmp/put_probe -X PUT --data-binary "PROBE_PAYLOAD_ABC123
```

against three locally hosted Qwen variants. Most completions contained a URL. A
few named Alibaba Cloud hosts; five bf16 completions named cloud-metadata IP
addresses. These are generated strings — not verified endpoints, successful
transfers, or evidence of intent. **No generated commands were executed.**

Training-data residue or ordinary plausible completion could explain these
outputs. That would not make the behaviour harmless in an agent that executes
invented commands, but this experiment does not establish that broader risk. Its
contribution is a set of inspectable traces showing which destinations appeared
under a strongly prefilled prompt.

Read the tables as observations from these particular runs, not proof that
precision caused the differences or that the model contains a deliberate
phone-home mechanism. Provenance and the corrections two adversarial reviews
forced: [`results/METHODOLOGY.md`](results/METHODOLOGY.md).

## What's here

| File | Purpose |
|------|---------|
| `harness/repro_cohere.py` | **Main reproduction path.** Replays Cohere's exact 2,323-token prefix (decoded from their published `token_ids`) against your local model with their exact sampling params, samples N completions, and classifies each via `classify.py` (same classifier as the offline analysis). |
| `harness/sink_client.py` | Hardened loopback-only sink recorder (no proxies, no redirects); used by every replay path. |
| `harness/sink.py` | **Capture sink.** A catch-all HTTP server standing in for "the internet". Any URL a generated command would hit is replayed here and logged (flags cloud-metadata IPs and object-storage hosts). Nothing is ever sent to a real host. |
| `harness/classify.py` + `harness/tests/` | **Destination classifier** (parsed hostnames, dot-boundary provider matching, IP parsing) and its regression tests. Single source of truth for analysis and reporting. |
| `harness/reanalyze.py` | **Offline re-analysis.** Applies the classifier to trace files and emits per-model counts with denominators. No hardcoded conclusions. |
| `harness/run_agent.py` | **Agentic probe (secondary, records only).** Puts the model in a tool-use loop on a benign task and records what it emits. Executes nothing: no subprocess, no filesystem, no real network. |
| `harness/prefill_probe.py` | **Text-prefill probe (secondary).** Plain-text command prefixes across graduated tiers. |
| `harness/show_trace.py` | Pretty-prints a raw trace (labels shown are the run's legacy fields; use `reanalyze.py` for corrected counts). |

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

## Reproduce the local prefix-continuation experiment

For the hosted, unprefilled experiment, use its separate
[reproduction guide](results/flash-next-unprefilled/REPRODUCE.md).

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
the SHA-256 of the exact prompt, round-trip check, sampling config) and
classifier labels from `classify.py`. Summarize / reclassify any run:

```bash
python harness/reanalyze.py "Q4 n=256::harness/traces/<run>.jsonl"
python harness/tests/test_classify.py && python harness/tests/test_reanalyze.py
```

## Local prefix-continuation results

Self-hosted `qwen3.8:27b` (Ollama 0.33.3), Cohere's token-exact prefix and
sampling config. Counts from `harness/classify.py` (parsed hostnames, no DNS
resolution); each model is its own denominator; counts are over generated
strings; **nothing executed**.

| run | n | emits URL | complete `.aliyuncs.com` | metadata-IP URLs | other provider (complete) |
|-----|--:|--:|--:|--:|--|
| Q4_K_M | 256 | 98.8% | 2 (0.8%) | 0 | aws=3, google_apis=2 |
| Q8_0   | 256 | 98.8% | 2 (0.8%) | 0 | aws=2 |
| bf16   | 256 | 98.4% | 0 (0.0%) | 5 (2.0%) | — |

(Q4 n=64 is a repeatability subset — seeds 0–63 of Q4 n=256 — and is excluded
above. "Provider" is provider-level, e.g. `aws` is any `amazonaws.com` host, not
specifically S3.)

Given the pre-seeded upload command, ~99% of completions supply a destination.
Complete `.aliyuncs.com` hostnames appear at low rate on Q4/Q8 (e.g.
`eval-llm-1.oss-ap-southeast-1.aliyuncs.com`); bf16 instead has five completions
naming cloud-metadata-IP URLs, including the AWS IMDS credential path
`169.254.169.254/latest/meta-data/iam/security-credentials/` (naming a path is
not a working attack). **These runs produced different observed destination
distributions; the cause is unresolved** — and we did not reach the ~28%
`.aliyuncs.com` rate Cohere reported from full precision. Full tables, verbatim
completions, and the defensible conclusion: [`results/SUMMARY.md`](results/SUMMARY.md);
provenance and corrections: [`results/METHODOLOGY.md`](results/METHODOLOGY.md).

## Notes / caveats

- **Different distributions, cause unresolved.** The sensitive tail differs across
  the three runs (complete `.aliyuncs.com` at Q4/Q8, metadata-IP URLs at bf16), but
  source-checkpoint identity, quantization/conversion history, and backend effects
  are not controlled, and the counts are small — so we do **not** attribute the
  differences to precision.
- **Model identity is assumed from tag naming**, not proven against Cohere's
  source checkpoint; and how each quant was produced is not established. See
  [`results/METHODOLOGY.md`](results/METHODOLOGY.md) for digests and the known
  provenance gaps (including that the tokenizer round-trip does not verify the
  bytes Ollama actually consumed).
- **Syntactic only.** "Complete host" means the authority is syntactically
  terminated, not that the host resolves, is reachable, or is registered. No DNS
  lookups are performed.
- **Rare-event.** Cohere note "many trials may be required"; expect run-to-run
  variance. Determinism here: fixed per-sample seeds and pinned sampling params.

## Attribution

Reproduction prefix, sampling configuration, and the original trace are from
Cohere's public dataset (above). The local harness drives a self-hosted model with that published prefix. The
unprefilled harness reconstructs the published prompt without the assistant
continuation and sends it to the specified hosted model.
