"""Explicit legacy mode against fixed source-producer expectations."""
import json
from pathlib import Path
import unittest
import umath as stage

def ordered(value):
    if isinstance(value,dict):
        if set(value)=={'offset','length','line','column','value'}:return value
        return [[key,ordered(child)]for key,child in value.items()]
    if isinstance(value,list):return [ordered(child)for child in value]
    return value

class LegacyPolicyTests(unittest.TestCase):
    def test_fixed_ruby_raw_trees_offsets_and_hash_order(self):
        rows=json.loads((Path(__file__).parent/'legacy-cases.json').read_text())['cases']
        for row in rows:
            with self.subTest(input=row['input']):
                if row['ok']:
                    result=stage.parse_legacy_raw(row['input'],decimal=row.get('decimal','.'))
                    self.assertEqual(ordered(result.tree),ordered(row['tree']))
                else:
                    with self.assertRaises(stage.ParseError)as raised:stage.parse_legacy_raw(row['input'],decimal=row.get('decimal','.'))
                    self.assertEqual(raised.exception.byte_offset,row['byte_offset'])
                    if 'grammar_byte_offset'in row:self.assertEqual(raised.exception.grammar_byte_offset,row['grammar_byte_offset'])
