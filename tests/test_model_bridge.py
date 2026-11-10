"""Focused installed-package tests against a real canonical stage library.

Set UMATH_MODEL_CDYLIB to the separately built platform library. Cases are
pinned upstream producer output, not Python model construction fixtures.
"""
import importlib
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import umath as stage
bridge = importlib.import_module('umath.model_bridge')
ENV = 'UMATH_MODEL_CDYLIB'

class ModelBridgeTests(unittest.TestCase):
    def test_native_models(self):
        rows = json.loads(Path(__file__).with_name('model-cases.json').read_text(encoding="utf-8"))
        for row in rows:
            with self.subTest(source=row['input']):
                self.assertEqual(stage.parse_model_json(row['input'], decimal=row['decimal']), row['model'])

    def test_native_rejection(self):
        with self.assertRaises(stage.ModelParseError) as error:
            stage.parse_model_json('a)')
        self.assertIsInstance(error.exception.error, dict)
        self.assertTrue(error.exception.error.get('category'))

    def test_input_boundary(self):
        for source in [None, 7, b'x']:
            with self.assertRaises(TypeError): stage.parse_model_json(source)
        with self.assertRaises(UnicodeEncodeError): stage.parse_model_json('\ud800')
        with self.assertRaises(ValueError): stage.parse_model_json('x\0y')
        with self.assertRaises(ValueError): stage.parse_model_json('x', decimal='bad')

    def test_missing_and_relative_library(self):
        with patch.dict(os.environ, {ENV:''}):
            with patch.object(bridge, 'packaged_library_path', return_value=None):
                with self.assertRaises(stage.ModelRuntimeUnavailable): stage.parse_model_json('x')
        with patch.dict(os.environ, {ENV:'relative-library.so'}):
            with self.assertRaises(stage.ModelRuntimeUnavailable): stage.parse_model_json('x')
        with patch.dict(os.environ, {ENV:str(Path(__file__).resolve().with_name('missing-canonical-stage-library'))}):
            with self.assertRaises(stage.ModelRuntimeUnavailable): stage.parse_model_json('x')

    def test_actual_version_and_unsupported_version_guard(self):
        library = bridge._load(bridge._library_path())
        version = getattr(library, 'umath_abi_version')
        self.assertEqual(version(), 1)
        # Exercise the compatibility guard with the actual loaded CDLL.
        # No model result from this altered version is accepted.
        with patch.object(library, 'umath_abi_version', lambda: 2):
            with patch.object(bridge.ctypes, 'CDLL', return_value=library):
                with self.assertRaises(stage.ModelRuntimeUnavailable):
                    bridge._load(bridge._library_path() + '.unsupported-version-probe')

    def test_owned_native_result_freed_once_on_success_and_decode_failure(self):
        library = bridge._load(bridge._library_path())
        free = getattr(library, 'umath_free_json_v1')
        calls = []
        def release(pointer):
            calls.append(pointer.value)
            free(pointer)
        with patch.object(library, 'umath_free_json_v1', release):
            stage.parse_model_json('x')
            self.assertEqual(len(calls), 1)
            # The allocation and free are real native operations; only the
            # Python read is corrupted to exercise the decoding exception.
            with patch.object(bridge.ctypes, 'string_at', return_value=b'\xff'):
                with self.assertRaises(stage.ModelRuntimeUnavailable): stage.parse_model_json('x')
            self.assertEqual(len(calls), 2)
        self.assertTrue(all(calls))

if __name__ == '__main__': unittest.main()
