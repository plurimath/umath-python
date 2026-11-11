"""Installed platform wheels parse through both ABIs without environment setup."""
import importlib
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import umath as stage
from parsanol import _ffi, ParsanolError

native = importlib.import_module('umath.native_library')
bridge = importlib.import_module('umath.model_bridge')
MODEL_ENV = 'UMATH_MODEL_CDYLIB'

class NativeWheelTests(unittest.TestCase):
    def test_no_override_raw_and_model_routes_share_the_packaged_library(self):
        with patch.dict(os.environ):
            os.environ.pop(MODEL_ENV, None)
            os.environ.pop('PARSANOL_CDYLIB', None)
            stage._artifacts.cache_clear()
            self.assertTrue(stage.parse_raw('x').bindings)
            self.assertIsInstance(stage.parse_model_json('x'), dict)
            context = stage._artifacts()[0].native_context
            self.assertEqual(str(context.library_path), native.packaged_library_path())
            self.assertEqual(bridge._library_path(), native.packaged_library_path())
            self.assertIsNone(os.environ.get(MODEL_ENV))
            self.assertIsNone(os.environ.get('PARSANOL_CDYLIB'))
            self.assertIsNone(_ffi._lib)
        stage._artifacts.cache_clear()

    def test_explicit_overrides_precede_packaged_discovery_and_bad_raw_path_fails(self):
        path = native.packaged_library_path()
        self.assertTrue(path)
        with patch.dict(os.environ, {MODEL_ENV:path, 'PARSANOL_CDYLIB':path}):
            with patch.object(native, 'packaged_library_path', side_effect=AssertionError('fallback used')):
                with patch.object(bridge, 'packaged_library_path', side_effect=AssertionError('fallback used')):
                    stage._artifacts.cache_clear()
                    self.assertTrue(stage.parse_raw('x').bindings)
                    self.assertIsInstance(stage.parse_model_json('x'), dict)
                    self.assertEqual(str(stage._artifacts()[0].native_context.library_path), path)
        with patch.dict(os.environ, {'PARSANOL_CDYLIB':str(Path(__file__).resolve().with_name('missing-native-library'))}):
            stage._artifacts.cache_clear()
            with self.assertRaises(ParsanolError): stage.parse_raw('x')
        stage._artifacts.cache_clear()

if __name__ == '__main__': unittest.main()
