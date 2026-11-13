"""Pin and generation verification; tampered inputs must be refused before replay."""
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

script = Path(__file__).resolve().parents[1] / "corpus_replay.py"
spec = importlib.util.spec_from_file_location("corpus_replay", script)
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)

PAYLOAD = """schema: plurimath-stage/unicode/cases/1
group: raw-sample
boundary: raw-tree
cases:
- id: sample-one.raw
  input:
    str: '1'
  expected:
    preprocessed:
      str: '1'
    tree:
      str: '1'
- id: sample-two.raw
  input:
    str: '2'
  expected:
    refusal:
      byte_offset: 0
"""


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


class GenerationVerificationTests(unittest.TestCase):
    def build(self, mutate=None):
        root = Path(self.tmp.name) / "suite"
        generation = root / "stages/unicode/generations/000001"
        payload = generation / "payloads/raw-sample.yaml"
        payload.parent.mkdir(parents=True)
        payload.write_text(PAYLOAD, encoding="utf-8")
        data = payload.read_bytes()
        dump(generation / "provenance.yaml", {
            "schema": "plurimath-stage/provenance/1", "language": "unicode", "generation": 1,
            "payloads": [{"path": "payloads/raw-sample.yaml", "bytes": len(data),
                          "sha256": hashlib.sha256(data).hexdigest(),
                          "rows": ["sample-one.raw", "sample-two.raw"]}]})
        digest, _ = replay.snapshot_digest(generation)
        dump(root / "generations/unicode.yaml", {
            "schema": "plurimath-stage/ledger/1", "language": "unicode", "layout": 1,
            "entries": [{"generation": 1, "path": "stages/unicode/generations/000001",
                         "snapshot_digest": digest, "payloads": 1, "rows": 2}]})
        if mutate:
            mutate(root, generation)
        git = lambda *args: subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
        git("init", "-q")
        git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "add", "-A", ".")
        git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
            "commit", "-q", "-m", "fixture")
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True,
                                text=True).stdout.strip()
        pin = {"schema": "plurimath-stage/pin/1", "repository": replay.REPOSITORY, "commit": commit,
               "language": "unicode", "generation": 1, "snapshot_digest": digest}
        return root, pin

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_untampered_generation_verifies(self):
        root, pin = self.build()
        verified = replay.verify(root, pin)
        self.assertEqual([path for path, _ in verified["documents"]], ["payloads/raw-sample.yaml"])

    def refuses(self, mutate=None, pin_change=None, message=""):
        root, pin = self.build(mutate)
        if pin_change:
            pin_change(pin)
        with self.assertRaisesRegex(replay.ReplayError, message):
            replay.verify(root, pin)

    def test_payload_byte_tamper_is_refused(self):
        def edit(root, generation):
            path = generation / "payloads/raw-sample.yaml"
            path.write_text(path.read_text(encoding="utf-8").replace("'1'", "'7'"), encoding="utf-8")
        self.refuses(edit, message="snapshot digest")

    def test_unlisted_file_is_refused(self):
        self.refuses(lambda root, generation: (generation / "payloads/extra.yaml").write_text("x\n"),
                     message="snapshot digest")

    def test_other_commit_is_refused(self):
        self.refuses(pin_change=lambda pin: pin.update(commit="0" * 40), message="checkout is at")

    def test_other_generation_is_refused(self):
        self.refuses(pin_change=lambda pin: pin.update(generation=2), message="0 entries")

    def test_other_digest_is_refused(self):
        self.refuses(pin_change=lambda pin: pin.update(snapshot_digest="sha256:" + "0" * 64),
                     message="ledger snapshot digest")

    def test_consistent_retamper_is_still_caught_by_provenance(self):
        # Rewrite a payload and re-seal the digest everywhere: provenance bytes/SHA must still refuse it.
        root, pin = self.build()
        generation = root / "stages/unicode/generations/000001"
        path = generation / "payloads/raw-sample.yaml"
        path.write_text(PAYLOAD.replace("'2'", "'3'"), encoding="utf-8")
        digest, _ = replay.snapshot_digest(generation)
        ledger = yaml.safe_load((root / "generations/unicode.yaml").read_text(encoding="utf-8"))
        ledger["entries"][0]["snapshot_digest"] = digest
        dump(root / "generations/unicode.yaml", ledger)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c",
                        "commit.gpgsign=false", "commit", "-qam", "tamper"], cwd=root, check=True)
        pin["commit"] = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True,
                                       text=True).stdout.strip()
        pin["snapshot_digest"] = digest
        with self.assertRaisesRegex(replay.ReplayError, "bytes or SHA-256"):
            replay.verify(root, pin)

    def test_dropped_row_is_refused(self):
        def drop(root, generation):
            provenance = generation / "provenance.yaml"
            data = yaml.safe_load(provenance.read_text(encoding="utf-8"))
            data["payloads"][0]["rows"] = ["sample-one.raw"]
            dump(provenance, data)
            digest, _ = replay.snapshot_digest(generation)
            ledger = yaml.safe_load((root / "generations/unicode.yaml").read_text(encoding="utf-8"))
            ledger["entries"][0]["snapshot_digest"] = digest
            dump(root / "generations/unicode.yaml", ledger)
        root, pin = self.build(drop)
        pin["snapshot_digest"] = yaml.safe_load((root / "generations/unicode.yaml").read_text())["entries"][0]["snapshot_digest"]
        with self.assertRaisesRegex(replay.ReplayError, "row IDs differ"):
            replay.verify(root, pin)

    def test_pin_shape_is_strict(self):
        path = Path(self.tmp.name) / "pin.yml"
        good = {"schema": "plurimath-stage/pin/1", "repository": replay.REPOSITORY, "commit": "a" * 40,
                "language": "unicode", "generation": 5, "snapshot_digest": "sha256:" + "b" * 64}
        dump(path, good)
        self.assertEqual(replay.load_pin(path), good)
        for change in ({"language": "latex"}, {"commit": "abc"}, {"generation": True}, {"extra": 1},
                       {"repository": "https://github.com/someone/fork"}):
            dump(path, {**good, **change})
            with self.subTest(change=change), self.assertRaises(replay.ReplayError):
                replay.load_pin(path)

    def test_unsafe_paths_are_refused(self):
        for bad in ("../x", "/abs", "a/./b", "a\\b"):
            with self.subTest(path=bad), self.assertRaises(replay.ReplayError):
                replay._safe(bad)


if __name__ == "__main__":
    unittest.main()
