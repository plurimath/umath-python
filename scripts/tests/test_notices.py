"""Source notice checks only; no canonical native runtime is simulated."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

script = Path(__file__).resolve().parents[1] / "ci.py"
spec = importlib.util.spec_from_file_location("stage_ci", script)
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


class NativeNoticeTests(unittest.TestCase):
    def test_workspace_texts_and_spdx_only_remain_explicit(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source"
            source.mkdir()
            nested = source / "crate"
            nested.mkdir()
            (source / "LICENSE").write_bytes(b"actual workspace license\n")
            empty = root / "registry"
            empty.mkdir()
            (empty / "Cargo.toml").write_text('[package]\nname="metadata-only"\n')
            packages = [
                {"id":"path+crate", "name":"crate", "version":"1", "source":None,
                 "manifest_path":str(nested / "Cargo.toml"), "license":"MIT"},
                {"id":"registry+crate", "name":"crate", "version":"1", "source":"registry+https://github.com/rust-lang/crates.io-index",
                 "manifest_path":str(empty / "Cargo.toml"), "license":"BSD-2-Clause"},
            ]
            out = root / "notices"
            out.mkdir()
            entries = ci.collect_notices({"packages":packages}, source, "a" * 40, out)
            self.assertEqual(len({entry["directory"] for entry in entries}), 2)
            self.assertFalse(entries[0]["spdx_only"])
            self.assertTrue(entries[1]["spdx_only"])
            self.assertIn("repository-LICENSE", entries[0]["notice_files"])
            self.assertIn("SOURCE-LICENSE.json", entries[1]["notice_files"])
            for entry in entries:
                for name, expected in entry["notice_files"].items():
                    self.assertEqual(ci.digest(out / entry["directory"] / name), expected)

    def test_unadmitted_local_dependency_refuses(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source"
            source.mkdir()
            external = root / "external"
            external.mkdir()
            package = {"id":"outside", "name":"outside", "version":"1", "source":None,
                       "manifest_path":str(external / "Cargo.toml"), "license":"MIT"}
            with self.assertRaisesRegex(RuntimeError, "unadmitted local"):
                ci.collect_notices({"packages":[package]}, source, "a" * 40, root / "unused")
