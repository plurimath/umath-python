"""Fixed native raw boundary fixtures, including explicit reporter differences."""
import json
import os
from pathlib import Path
import unittest
import umath as stage

class RawBoundaryTests(unittest.TestCase):
    def test_pinned_raw_fixtures(self):
        rows = json.loads(Path(__file__).with_name("raw-cases.json").read_text(encoding="utf-8"))
        for case in rows:
            with self.subTest(source=case["input"], decimal=case.get("decimal", ".")):
                if case["ok"]:
                    result = stage.parse_raw(case["input"], decimal=case.get("decimal", "."))
                    self.assertEqual(result.tree, case["tree"])
                else:
                    with self.assertRaises(stage.ParseError) as failure:
                        stage.parse_raw(case["input"], decimal=case.get("decimal", "."))
                    expected = case.get("native_error", case)
                    self.assertEqual(failure.exception.byte_offset, expected["byte_offset"])
                    self.assertEqual(failure.exception.char_offset, expected["char_offset"])
                    if "native_error" in case:
                        self.assertNotEqual(failure.exception.byte_offset, case["byte_offset"])

    def test_raw_argument_boundary(self):
        with self.assertRaises(TypeError): stage.parse_raw(None)
        with self.assertRaises(ValueError): stage.parse_raw("x", decimal="bad")
        with self.assertRaises(ValueError): stage.parse_raw("x\0y")
        with self.assertRaises(UnicodeEncodeError): stage.parse_raw("\ud800")

if __name__ == "__main__": unittest.main()
