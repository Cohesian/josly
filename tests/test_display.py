"""Human schema views retain semantics and explicit machine/raw output."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from josly import initialize
from josly.display import color_enabled, format_source, highlight
from josly.jsl import Parser


class SchemaDisplayTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.schemas = self.root / 'schemas'; self.schemas.mkdir()
        self.source = '''# Keep comments and literal punctuation.
$S_item=o[s,t]{name:s # Display name
details:$S_details optional?:a[o[s,t]{"a":s value:"literal # : { , \\\"quoted\\\""}]|n}
'''
        (self.schemas / 'item.jsl').write_text(self.source)
        (self.schemas / 'common.jsl').write_text('$S_details=o[s,t]{active:b}')
        self.volume = self.root / '.vol'
        initialize(self.volume, self.schemas, {'item': {'directory': 'items'}})

    def call(self, *args):
        result = subprocess.run([sys.executable, '-m', 'josly', '--volume', str(self.volume), *args],
                                env={**os.environ, 'PYTHONPATH': str(ROOT.parent)},
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def snapshot(self):
        return {str(file.relative_to(self.volume)): file.read_bytes()
                for file in self.volume.rglob('*') if file.is_file()}

    def test_default_views_are_readable_and_do_not_change_the_volume(self):
        before = self.snapshot()
        listing = self.call('schemas', 'list')
        self.assertIn('2 schemas · 1 collection', listing)
        self.assertIn('(shared types)', listing)
        self.assertLess(listing.index('common.jsl'), listing.index('item.jsl'))
        shown = self.call('schemas', 'show', 'item')
        self.assertIn('Collection: items', shown)
        self.assertIn('  name: s  # Display name\n', shown)
        self.assertIn('    value:', shown)
        self.assertNotIn('\x1b[', listing + shown)
        self.assertEqual(before, self.snapshot())

    def test_explicit_json_and_text_retain_original_schema_source(self):
        shown = json.loads(self.call('schemas', 'show', 'item', '--format', 'json', '--color', 'always'))
        self.assertEqual(shown['item']['text'], self.source)
        self.assertEqual(list(json.loads(self.call('schemas', 'list', '--format', 'json'))), ['common', 'item'])
        raw = self.call('schemas', 'show', 'item', '--format', 'text', '--color', 'always')
        self.assertEqual(raw, '# item.jsl\n' + self.source.rstrip() + '\n')
        self.assertNotIn('\x1b[', raw)

    def test_pretty_format_and_highlighting_preserve_types_comments_and_literals(self):
        formatted = format_source(self.source)
        self.assertEqual(Parser(formatted).declarations(), Parser(self.source).declarations())
        self.assertIn('# Keep comments and literal punctuation.', formatted)
        self.assertIn('literal # : { ,', formatted)
        colored = highlight(formatted, True)
        self.assertIn('\x1b[36m$S_item\x1b[0m', colored)
        self.assertIn('\x1b[34ms\x1b[0m', colored)
        self.assertEqual(re.sub(r'\x1b\[[0-9;]*m', '', colored), formatted)

    def test_color_is_explicit_or_terminal_only(self):
        class Stream:
            def __init__(self, terminal): self.terminal = terminal
            def isatty(self): return self.terminal

        self.assertTrue(color_enabled(stream=Stream(True), environ={}))
        for terminal, environment in [(False, {}), (True, {'NO_COLOR': ''}), (True, {'TERM': 'dumb'})]:
            self.assertFalse(color_enabled(stream=Stream(terminal), environ=environment))
        self.assertTrue(color_enabled('always', stream=Stream(False), environ={'NO_COLOR': ''}))
        self.assertFalse(color_enabled('never', stream=Stream(True), environ={}))
        forced = self.call('schemas', 'show', 'item', '--color', 'always')
        plain = self.call('schemas', 'show', 'item', '--color', 'never')
        self.assertEqual(re.sub(r'\x1b\[[0-9;]*m', '', forced), plain)
        self.assertIn('--color', self.call('schemas', 'show', '--help'))


if __name__ == '__main__':
    unittest.main()
