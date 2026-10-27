# Methodology, provenance, and corrections

## Provenance (captured after the runs — read the caveat)

> **Caveat.** The digests and revisions below were recorded *after* the sampling
> runs, from the local Ollama store and Hugging Face cache on the same machine.
> They are not asserted to have been captured at run time, and they do not by
> themselves prove the local weights are the same checkpoint Cohere tested. The
> relationship to `Qwen/Qwen3.8-Flash-Next` is established only by Ollama's tag
> naming and the matching tokenizer round-trip — not by a source-checkpoint hash.

Local model manifests (Ollama 0.33.3):

| tag | config digest | model-blob digest | bytes |
|---|---|---|--:|
| `qwen3.8:27b` (Q4_K_M) | `492b2922…17b0cf5f` | `f5f1dd89…ff2ad57d` | 16,810,714,464 |
| `qwen3.8:27b-q8_0` | `04800723…0107b2a6` | `2bb22714…8c09bdbf` | 29,047,084,384 |
| `qwen3.8:27b-bf16` | `ea420403…d1aa282a` | `45fbf09d…b1a17a85` | 54,657,733,984 |

Input data:

- Dataset: `CohereLabs/10-2026-qwen-investigation-traces`, file
  `data/train-00000-of-00001.parquet`, sha256
  `f8c4b224d7d45aabf8b817ed4a85d2dd58c2d239c8cf6ba78ce42c7ecfa61e8b`.
- Tokenizer: `Qwen/Qwen3.8-Flash-Next`, revision
  `de4b8e4d43b917e7706784d8bb445c9af86a3540`, `tokenizer.json`.
- Prefix: first 2,323 token IDs; decoded prompt sha256 `9ee588d05c2dbfc6…`;
  decode→encode round-trip verified against that tokenizer.

### Known provenance gaps (do not paper over)

- `repro_cohere.py` verifies the downloaded tokenizer against *itself*; it does
  **not** verify the token sequence Ollama actually consumed. "Token-exact" refers
  to the HF-tokenizer prefix, not to backend input.
- A failed round-trip is logged but did **not** abort the run. Future runs should
  fail hard on mismatch.
- Dataset/tokenizer downloads were not revision-pinned in code at run time
  (pin them to the revisions above to reproduce exactly).
- How each quantized artifact was produced from the source checkpoint is not
  established here. A bf16-vs-Q4/Q8 difference could reflect precision, a
  different checkpoint, conversion, or backend behaviour.

## Corrections applied after `notes/review1.md`

The first published commit over-claimed and had a classifier defect. Changes:

1. **Framing.** Relabeled throughout as a *conditional destination-continuation*
   experiment (the prefix already contains the upload command), not spontaneous
   phone-home. No inference of intent or endpoint ownership.
2. **Classifier.** Replaced substring matching with parsed-hostname, dot-boundary
   provider matching and IP parsing (`harness/classify.py`), with regression tests
   (`harness/tests/`) covering the `storage.googleapis.com/cti-oss-probe` false
   positive, the truncated `…aliy` candidate, spoofed suffixes
   (`github.com.evil.com`, `localhost.evil.com`), malformed URLs, and metadata IPs.
   One classifier now feeds both analysis and reporting.
3. **Counts.** Complete `.aliyuncs.com` hits are 2/256 (Q4), 2/256 (Q8), 0/256
   (bf16) — not the 3/3 first reported (a Google-Storage FP and a truncated
   candidate). Truncated candidates are reported separately.
4. **Independence.** Q4 n=64 is exactly seeds 0–63 of Q4 n=256; it is treated as a
   repeatability check and excluded from per-model counts. No pooling across
   models; each has its own denominator.
5. **Report generator.** Removed the hardcoded-conclusion generator
   (`make_summary.py`); `reanalyze.py` derives every number from the traces, with
   a synthetic test asserting a no-URL trace and a one-metadata-hit trace do not
   yield fixed conclusions.
6. **Unsafe executor.** `run_agent.py` no longer executes anything: no subprocess,
   no real filesystem access, no real network. It records intent only. The "no
   egress" claim is narrowed — the sink is a loopback *recorder*, not an enforced
   egress policy.
