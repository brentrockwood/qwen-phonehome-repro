import copy
import hashlib
import json
import os
import stat
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from harness import repro_unprefilled as repro


PROMPT = "synthetic test prompt"
TOKEN = "hf_unit_test_secret"
VALID = dict(model=repro.MODEL,
             choices=[dict(index=0, text="completion", finish_reason="stop")],
             usage=dict(prompt_tokens=2122, completion_tokens=2, total_tokens=2124))


class ReproTests(unittest.TestCase):
    def connection(self, raw=VALID, status=200):
        conn = MagicMock()
        conn.getresponse.return_value.status = status
        conn.getresponse.return_value.read.return_value = json.dumps(raw).encode()
        return conn

    def test_exact_request(self):
        conn = self.connection()
        with patch.object(repro.http.client, "HTTPSConnection", return_value=conn) as factory:
            result = repro.dispatch(PROMPT, TOKEN)
        factory.assert_called_once_with("router.huggingface.co", timeout=180)
        args, kwargs = conn.request.call_args
        self.assertEqual(args, ("POST", "/featherless-ai/v1/completions"))
        self.assertEqual(json.loads(kwargs["body"]), dict(
            model="Qwen/Qwen3.8-Flash-Next", prompt=PROMPT,
            temperature=1.0, top_p=1.0, top_k=20, min_p=0.0,
            presence_penalty=0.0, frequency_penalty=0.0,
            repetition_penalty=1.0, max_tokens=2048))
        self.assertEqual(kwargs["headers"], {"Content-Type": "application/json",
                                             "Authorization": "Bearer " + TOKEN})
        self.assertEqual(result["outcome"], "success")
        self.assertEqual(result["usage"], VALID["usage"])
        conn.request.assert_called_once()
        conn.close.assert_called_once()

    def test_invalid_responses_and_redirects_never_retry(self):
        variants = [None, {}, dict(VALID, error="failure"), dict(VALID, model="other"),
                    dict(VALID, choices=[]), dict(VALID, choices=VALID["choices"] * 2),
                    dict(VALID, usage=dict(prompt_tokens=True, completion_tokens=2, total_tokens=3)),
                    dict(VALID, usage=dict(prompt_tokens=2122, completion_tokens=2, total_tokens=1))]
        for choice in ({"index": 0, "text": "x", "finish_reason": None},
                       {"index": 0, "text": None, "finish_reason": "stop"}):
            variants.append(dict(VALID, choices=[choice]))
        for status, raw in [(200, v) for v in variants] + [(s, VALID) for s in (302, 401, 429, 503)]:
            with self.subTest(status=status, raw=raw):
                conn = self.connection(raw, status)
                with patch.object(repro.http.client, "HTTPSConnection", return_value=conn):
                    result = repro.dispatch(PROMPT, TOKEN)
                self.assertEqual(result["outcome"], "unknown")
                self.assertNotIn("completion", result)
                conn.request.assert_called_once()
                if status != 200:
                    conn.getresponse.return_value.read.assert_not_called()

    def test_bad_json_duplicate_keys_and_transport_failure(self):
        for body in (b"not json", b'{"model":"x","model":"y"}', b"x" * (repro.MAX_RESPONSE + 1)):
            conn = self.connection()
            conn.getresponse.return_value.read.return_value = body
            with patch.object(repro.http.client, "HTTPSConnection", return_value=conn):
                self.assertEqual(repro.dispatch(PROMPT, TOKEN)["outcome"], "unknown")
            conn.request.assert_called_once()
        conn = self.connection()
        conn.request.side_effect = OSError(TOKEN)
        with patch.object(repro.http.client, "HTTPSConnection", return_value=conn):
            result = repro.dispatch(PROMPT, TOKEN)
        self.assertEqual(result["outcome"], "unknown")
        self.assertNotIn(TOKEN, json.dumps(result))
        conn.request.assert_called_once()

    def run_fixture(self, conn, output, n=3):
        with patch.object(repro, "PROMPT_SHA", hashlib.sha256(PROMPT.encode()).hexdigest()), \
             patch.object(repro, "provenance", return_value={}), \
             patch.object(repro.http.client, "HTTPSConnection", return_value=conn):
            return repro.run(PROMPT, n, output, TOKEN)

    def test_directory_synced_before_dispatch_and_failure_stops(self):
        for fail in (False, True):
            events = []

            def sync(fd):
                if stat.S_ISDIR(os.fstat(fd).st_mode):
                    events.append("directory")
                    if fail:
                        raise OSError("directory sync failed")

            def request(*args, **kwargs):
                self.assertIn("directory", events)
                events.append("dispatch")

            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as directory:
                conn = self.connection()
                conn.request.side_effect = request
                with patch.object(repro.os, "fsync", side_effect=sync):
                    if fail:
                        with self.assertRaises(OSError):
                            self.run_fixture(conn, Path(directory) / "run.jsonl", n=1)
                        conn.request.assert_not_called()
                    else:
                        self.assertTrue(self.run_fixture(conn, Path(directory) / "run.jsonl", n=1))
                        self.assertEqual(events, ["directory", "dispatch"])

    def test_unknown_preserved_and_stops(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run.jsonl"
            conn = self.connection({"error": TOKEN}, 503)
            self.assertFalse(self.run_fixture(conn, output))
            rows = [json.loads(line) for line in output.read_text().splitlines()]
            self.assertEqual([r.get("outcome") for r in rows], [None, "pending", "unknown"])
            self.assertEqual(rows[1]["attempt"], rows[2]["attempt"])
            self.assertNotIn(TOKEN, output.read_text())
            conn.request.assert_called_once()
            with self.assertRaises(FileExistsError):
                self.run_fixture(conn, output)
            conn.request.assert_called_once()

    def test_success_redacts_secret_and_records_completion(self):
        raw = copy.deepcopy(VALID)
        raw["choices"][0]["text"] = TOKEN + " Bearer private-value hf_another_secret"
        raw["private_metadata"] = TOKEN
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run.jsonl"
            self.assertTrue(self.run_fixture(self.connection(raw), output, n=1))
            text = output.read_text()
            self.assertNotIn(TOKEN, text)
            self.assertNotIn("private-value", text)
            self.assertNotIn("hf_another_secret", text)
            self.assertNotIn("private_metadata", text)
            self.assertTrue(json.loads(text.splitlines()[-1])["completion_redacted"])

    def test_interruption_leaves_pending(self):
        conn = self.connection()
        conn.request.side_effect = KeyboardInterrupt()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run.jsonl"
            with self.assertRaises(KeyboardInterrupt):
                self.run_fixture(conn, output)
            self.assertEqual(json.loads(output.read_text().splitlines()[-1])["outcome"], "pending")
            conn.request.assert_called_once()

    def test_wrong_prompt_hash_stops_before_request_or_output(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(repro, "dispatch") as dispatch:
            output = Path(directory) / "run.jsonl"
            with self.assertRaises(ValueError):
                repro.run(PROMPT, 1, output, TOKEN)
            dispatch.assert_not_called()
            self.assertFalse(output.exists())

    def test_wrong_source_hash_stops(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            source.write_bytes(b"wrong artifact")
            with self.assertRaises(ValueError):
                repro.reconstruct(source, source)

    def test_pinned_anonymous_downloads(self):
        with patch("huggingface_hub.hf_hub_download", side_effect=["parquet", "tokenizer"]) as download, \
             patch.object(repro, "reconstruct", return_value=PROMPT) as reconstruct:
            self.assertEqual(repro.prepare(), PROMPT)
        self.assertEqual(download.call_args_list[0].kwargs,
                         dict(repo_type="dataset", revision=repro.DATASET_REV, token=False))
        self.assertEqual(download.call_args_list[1].kwargs,
                         dict(revision=repro.TOKENIZER_REV, token=False))
        self.assertEqual(download.call_args_list[0].args, (repro.DATASET, repro.DATASET_FILE))
        self.assertEqual(download.call_args_list[1].args, (repro.MODEL, "tokenizer.json"))
        reconstruct.assert_called_once_with("parquet", "tokenizer")

    def test_prepare_only_no_credential_access_or_dispatch(self):
        def environment_get(key, default=None):
            if key == "HF_TOKEN":
                raise AssertionError("credential read")
            return default

        with patch.object(repro, "prepare", return_value=PROMPT), \
             patch.object(repro, "provenance", return_value={}), \
             patch.object(repro.os.environ, "get", side_effect=environment_get), \
             patch.object(repro, "run") as run, patch("builtins.print"):
            self.assertEqual(repro.main(["--prepare-only"]), 0)
            run.assert_not_called()

    def test_explicit_bounded_count_before_preparation(self):
        for argv in ([], ["--n", "0", "--output", "x"], ["--n", "65", "--output", "x"],
                     ["--n", "-1", "--output", "x"], ["--n", "1"],
                     ["--prepare-only", "--n", "1"]):
            with self.subTest(argv=argv), patch.object(repro, "prepare") as prepare, \
                 patch("sys.stderr"), self.assertRaises(SystemExit):
                repro.main(argv)
            prepare.assert_not_called()


if __name__ == "__main__":
    unittest.main()
