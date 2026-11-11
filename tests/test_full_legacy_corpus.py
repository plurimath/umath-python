"""Full frozen source vectors; enabled only in native platform CI."""
import json,os
from pathlib import Path
import unittest
import umath as stage
from test_legacy_policy import ordered

def decode(node,text):
    if 'str'in node:return node['str']
    if 'sym'in node:return node['sym']
    if 'slice'in node:
        value=node['slice'];offset=node['byte_offset'];prefix=text.encode('utf-8')[:offset].decode('utf-8')
        assert len(prefix)==node['char_offset']
        return dict(offset=offset,length=len(value),line=prefix.count('\n')+1,column=len(prefix.rsplit('\n',1)[-1])+1,value=value)
    if 'array'in node:return [decode(value,text)for value in node['array']]
    if 'hash'in node:
        pairs=[(decode(key,text),decode(value,text))for key,value in node['hash']]
        assert len({key for key,_ in pairs})==len(pairs)
        return dict(pairs)
    if 'nil'in node:return None
    if 'bool'in node:return node['bool']
    if 'int'in node:return int(node['int'])
    raise AssertionError('unknown source tag '+str(node))

@unittest.skipUnless(os.environ.get('PLURIMATH_FULL_RAW_CORPUS')=='1','full corpus runs in native platform CI')
class FullLegacyCorpusTests(unittest.TestCase):
    def test_complete_frozen_raw_corpus(self):
        corpus=json.loads((Path(__file__).parent/'fixtures/full-raw.json').read_text())
        for row in corpus['cases']:
            with self.subTest(id=row['id']):
                source=row['input']['str'];decimal=row.get('options',{}).get('decimal','.')
                if 'refusal'in row['expected']:
                    with self.assertRaises(stage.ParseError)as error:stage.parse_legacy_raw(source,decimal=decimal)
                    actual=error.exception.grammar_byte_offset
                    self.assertEqual(actual,row['expected']['refusal']['byte_offset'])
                else:
                    result=stage.parse_legacy_raw(source,decimal=decimal)
                    self.assertEqual(result.text,row['expected']['preprocessed']['str'])
                    self.assertEqual(ordered(result.tree),ordered(decode(row['expected']['tree'],result.text)))
