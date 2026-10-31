# Reproduce the unprefilled input

This public harness reconstructs the original system/user prompt from CohereLabs' published trace and stops immediately after `<|im_start|>assistant\n`. It supplies **no assistant content**, including no `<think>` prefix. The input is 2,122 tokens, not the 2,323-token assistant-prefilled prefix used in Cohere's reproduction example.

## Fresh checkout

From the repository root, on Linux or macOS with Python 3.10 or newer:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest harness.tests.test_repro_unprefilled
python harness/repro_unprefilled.py --prepare-only
```

Preparation intentionally downloads two public resources through `huggingface_hub`, anonymously (`token=False`), or uses its cache. It verifies both file hashes, reconstructs the prompt, checks its token round trip and hash, and prints provenance. It does not load model weights or perform inference. No private experiment files or pre-existing artifacts are required. Publication checks downloaded both pinned resources anonymously into an empty cache and verified the 2,122-token prompt and all three hashes; no inference was requested.

For inference, provide `HF_TOKEN` in the environment through your own secure mechanism. The harness does not read saved credentials or credential files. Then, explicitly choose an attempt count and a **new** output file:

```sh
python harness/repro_unprefilled.py --n 1 --output unprefilled.jsonl
```

Inference uses the legacy raw-completions route:

```text
https://router.huggingface.co/featherless-ai/v1/completions
```

It sends `model=Qwen/Qwen3.8-Flash-Next`, the verified prompt, and exactly these settings:

```json
{
  "temperature": 1.0,
  "top_p": 1.0,
  "top_k": 20,
  "min_p": 0.0,
  "presence_penalty": 0.0,
  "frequency_penalty": 0.0,
  "repetition_penalty": 1.0,
  "max_tokens": 2048
}
```

There is no chat template, seed, stop override, or assistant prefill. `--n` is required for inference and bounded to 1–64 attempts. Calls run sequentially in one worker; there are no automatic retries. Inference uses standard-library direct HTTPS with TLS verification, no environment proxy, and no redirect following. Anonymous Hub resource downloads may use Hub/CDN redirects; the no-redirect rule applies to authenticated inference.

## Pinned inputs and attribution

The pins below match the source artifacts used to construct this experiment's input, rather than mutable `main` branches.

| Resource | Repository | Revision | File |
| --- | --- | --- | --- |
| CohereLabs trace | `CohereLabs/10-2026-qwen-investigation-traces` | `028b7cd7d931586dbfa05463903be9d45c4924ac` | `data/train-00000-of-00001.parquet` |
| Qwen tokenizer | `Qwen/Qwen3.8-Flash-Next` | `de4b8e4d43b917e7706784d8bb445c9af86a3540` | `tokenizer.json` |

Expected SHA-256 values:

```text
dataset:   f8c4b224d7d45aabf8b817ed4a85d2dd58c2d239c8cf6ba78ce42c7ecfa61e8b
tokenizer: 0997f410c57a1f4e53b09e4be8f4a172d90edd9564368fb0847030937229b9f3
prompt:    6839272dd4f395dff60628562679814dd3d30ef1edbe9413ec56890a1bddf406
```

The prompt comes from the first Parquet row's `token_ids`, decoded with special tokens retained and cut at the first assistant header. Re-encoding without added special tokens must produce exactly the first 2,122 original IDs. The prompt hash covers UTF-8 bytes, including the final newline.

Sources and terms:

- [CohereLabs dataset at the pinned revision](https://huggingface.co/datasets/CohereLabs/10-2026-qwen-investigation-traces/tree/028b7cd7d931586dbfa05463903be9d45c4924ac). Its reproduction README credits the [Cohere investigation](https://cohere.com/blog/concerning-behaviour-popular-open-weight-ai-model). The inspected dataset README does not declare a license; public availability is not a redistribution license.
- [Qwen repository at the tokenizer revision](https://huggingface.co/Qwen/Qwen3.8-Flash-Next/tree/de4b8e4d43b917e7706784d8bb445c9af86a3540). Check its upstream license and terms before reuse or redistribution; this harness does not independently establish a license grant for the tokenizer.

Neither artifact nor its token IDs are bundled here. Downloads retain their upstream terms; this repository does not relicense them. Review those terms before publishing downloaded inputs or generated artifacts.

## Output and limits

JSONL starts with provenance: source pins/hashes, prompt hash/token count, route, settings, harness hash, Python version, and dependency versions. The new output file's parent directory is also synced before any request; unsupported directory-sync operations stop before dispatch. Each attempt has a flushed and `fsync`-ed `pending` row **before** dispatch and a corresponding result row afterward. Interpret these as events keyed by attempt number, not separate samples. A pending row without a result is unresolved, not a negative finding.

A successful result includes completion text, finish reason, usage counts, and the reported model name. Validation requires a single indexed text choice, `stop` or `length`, matching reported model, and consistent nonnegative integer usage. A length finish is valid but may truncate the answer. Unknown response formats, errors, redirects, timeouts, and malformed responses stop the run with a nonzero exit status and an `unknown` result where possible. Interruptions can leave only `pending`. No failures are counted as negative findings; the harness does not classify behavior.

Output files are never overwritten or resumed. Review unresolved attempts before manually launching another run; a lost response may still correspond to completed inference. Do not run multiple independent copies if you intend a single sequential experiment. Filesystem failure or sudden power loss can prevent the last event from being saved.

Only selected validated response fields are saved. Error bodies, headers, exception strings, account metadata, and credentials are not logged. Completion text is redacted if it contains the supplied credential or recognizable HF/Bearer credentials, with `completion_redacted` recording the change. Treat generated text as untrusted: no generated commands execute, no generated URLs are fetched, and no sink is contacted. Review output before sharing it.

These checks verify the two downloaded input files and exact prompt—not all downloaded software, model weights, server-side tokenizer, or provider implementation. A matching response model name is not proof of served weight identity. Dependency versions are recorded, not locked. Provider availability and acceptance of this legacy endpoint may change; output is stochastic and exact generated text is not guaranteed. Tests mock inference; they do not establish live endpoint compatibility.
