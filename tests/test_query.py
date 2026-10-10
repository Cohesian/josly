"""Josly contract tests with fictional schemas and temporary stores."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from josly import Queries, Registry

SAMPLE = '''
$S_sample = o[s, t] {
  name: s
  count: i
  enabled: b
  tags: a[s]
  optional?: s | n
  extras: o[s, t]
}
'''


class JoslyQueryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.directory = Path(tmp.name)
        self.schemas = self.directory / 'schemas'
        self.schemas.mkdir()
        (self.schemas / 'sample.jsl').write_text(SAMPLE)
        self.root = self.directory / 'json'
        self.query = Queries(self.root, self.schemas)
        self.value = {'name': 'Fictional', 'count': 1, 'enabled': True, 'tags': ['gasista'],
                      'optional': None, 'extras': {'a/b~c': 3}}

    def create(self):
        return self.query.write('sample', 'sample-1', 'insert', {'': self.value})

    def test_read_does_not_create_store_and_invalid_filters_fail_before_scan(self):
        self.assertEqual(self.query.read('sample'), [])
        with self.assertRaises(ValueError):
            self.query.read('sample', conditions=[{'path': '/count', 'op': 'eval', 'value': 'anything'}])
        self.assertFalse(self.root.exists())

    def test_create_read_filter_project_and_update_same_id(self):
        first = self.create()
        self.assertEqual(first['revision'], 1)
        self.assertEqual(first['data'], self.value)
        result = self.query.read('sample', fields=['/name', '/optional', '/extras/a~1b~0c'], conditions=[
            {'path': '/name', 'op': 'contains', 'value': 'Fict'},
            {'path': '/tags', 'op': 'contains', 'value': 'gasista'},
            {'path': '/count', 'op': 'in', 'value': [1, 2]}])
        self.assertEqual(result[0]['values'], {'/name': 'Fictional', '/optional': None, '/extras/a~1b~0c': 3})
        second = self.query.write('sample', 'sample-1', 'update', {'/count': 2}, 1)
        self.assertEqual(second['revision'], 2)
        self.assertEqual(second['created_at'], first['created_at'])
        same = self.query.write('sample', 'sample-1', 'update', {'/count': 2}, 2)
        self.assertEqual(same, second)
        self.assertEqual(self.query.read('sample', 'sample-1')[0], second)
        self.assertEqual(self.query.read('sample', 'missing'), [])

    def test_absent_is_distinct_from_null_and_insert_from_update(self):
        self.create()
        with self.assertRaises(ValueError):
            self.query.write('sample', 'sample-1', 'insert', {'/optional': 'exists'}, 1)
        with self.assertRaises(ValueError):
            self.query.write('sample', 'sample-1', 'update', {'/extras/missing': 'absent'}, 1)
        self.query.write('sample', 'sample-1', 'insert', {'/extras/missing': None}, 1)
        self.assertEqual(len(self.query.read('sample', conditions=[
            {'path': '/extras/missing', 'op': 'exists', 'value': True}])), 1)
        self.assertEqual(self.query.read('sample', conditions=[
            {'path': '/extras/absent', 'op': 'eq', 'value': None}]), [])
        self.assertEqual(self.query.read('sample', fields=['/extras/absent'])[0]['values'], {})

    def test_types_required_fields_and_paths_are_validated_before_new_write(self):
        invalid = [
            {'': {**self.value, 'count': True}},
            {'': {**self.value, 'enabled': 1}},
            {'': {**self.value, 'tags': [3]}},
            {'': {key: value for key, value in self.value.items() if key != 'name'}},
            {'/count': 3},
            {'/typo': 3},
            {'/count/child': 3},
            {'/extras/a~2b': 3},
            {'/extras': {}, '/extras/a': 1},
            {'': {**self.value, 'extras': {1: 'not a JSON key'}}},
            {'': {**self.value, 'extras': {'nan': float('nan')}}},
        ]
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.query.write('sample', 'sample-1', 'insert', changes)
            self.assertFalse(self.root.exists())
        with self.assertRaises(ValueError):
            self.query.write('sample', '../escape', 'insert', {'': self.value})
        self.assertFalse(self.root.exists())

    def test_failed_existing_changes_leave_record_bytes_unchanged(self):
        self.create()
        file = self.root / 'sample/sample-1.json'
        before = file.read_bytes()
        for changes, revision in [({'/count': 'bad'}, 1), ({'/count': 2}, None), ({'/count': 2}, 0),
                                  ({'/tags/-1': 'bad'}, 1), ({'/tags/01': 'bad'}, 1)]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.query.write('sample', 'sample-1', 'update', changes, revision)
            self.assertEqual(file.read_bytes(), before)

    def test_invalid_revision_values_do_not_create_a_record(self):
        for revision in (True, -1, '1', 1.0):
            with self.subTest(revision=revision), self.assertRaises(ValueError):
                self.query.write('sample', 'sample-1', 'insert', {'': self.value}, revision)
            self.assertFalse(self.root.exists())

    def test_malformed_storage_envelopes_are_rejected_on_read(self):
        self.create()
        file = self.root / 'sample/sample-1.json'
        document = json.loads(file.read_text())
        for corrupt in ([], {**document, 'schema': 'other'}, {**document, 'revision': True}):
            file.write_text(json.dumps(corrupt))
            with self.subTest(corrupt=corrupt), self.assertRaises(ValueError):
                self.query.read('sample')

    def test_arrays_append_at_length_only_and_dynamic_maps_accept_new_keys(self):
        self.create()
        with self.assertRaises(ValueError):
            self.query.write('sample', 'sample-1', 'insert', {'/tags/2': 'gap'}, 1)
        second = self.query.write('sample', 'sample-1', 'insert', {'/tags/1': 'new', '/extras/deep/leaf': True}, 1)
        self.assertEqual(second['data']['tags'], ['gasista', 'new'])
        self.assertEqual(second['data']['extras']['deep']['leaf'], True)
        third = self.query.write('sample', 'sample-1', 'update', {'/tags/0': 'changed'}, 2)
        self.assertEqual(third['data']['tags'], ['changed', 'new'])

    def test_any_values_preserve_bool_number_difference(self):
        self.value['extras']['typed'] = True
        self.create()
        changed = self.query.write('sample', 'sample-1', 'update', {'/extras/typed': 1}, 1)
        self.assertEqual(changed['revision'], 2)
        self.assertIs(type(changed['data']['extras']['typed']), int)
        self.assertEqual(self.query.read('sample', conditions=[{'path': '/count', 'op': 'eq', 'value': True}]), [])

    def test_nullable_parent_must_be_replaced_explicitly(self):
        self.value['extras']['nullable'] = None
        self.create()
        with self.assertRaises(ValueError):
            self.query.write('sample', 'sample-1', 'insert', {'/extras/nullable/leaf': 'x'}, 1)
        changed = self.query.write('sample', 'sample-1', 'update', {'/extras/nullable': {'leaf': 'x'}}, 1)
        self.assertEqual(changed['data']['extras']['nullable'], {'leaf': 'x'})

    def test_concurrent_updates_accept_one_revision_only(self):
        self.create()
        def attempt(value):
            try:
                return self.query.write('sample', 'sample-1', 'update', {'/count': value}, 1)['revision']
            except ValueError:
                return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(attempt, [2, 3]))
        self.assertEqual(sorted(results, key=str), [2, 'conflict'])
        self.assertEqual(self.query.read('sample', 'sample-1')[0]['revision'], 2)

    def test_symlink_collection_cannot_escape_store(self):
        outside = self.directory / 'outside'
        outside.mkdir(); self.root.mkdir()
        (self.root / 'sample').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.create()
        self.assertEqual(list(outside.iterdir()), [])

    def test_registry_supports_maps_literals_unions_and_any(self):
        (self.schemas / 'other.jsl').write_text('''
$S_other = o[i, a["ok" | n | $S_number]]
$S_number = i | f
''')
        registry = Registry(self.schemas)
        registry.validate('other', {1: ['ok', None, 2, 2.5]})
        with self.assertRaises(ValueError):
            registry.validate('other', {'1': ['ok']})
        with self.assertRaises(ValueError):
            registry.validate('other', {1: ['wrong']})
        self.assertEqual(registry.documents['sample']['root_type'], '$S_sample')

    def test_bad_schema_references_and_code_are_rejected(self):
        for source in ['$S_sample = $S_missing', '$S_sample = a[$S_sample]',
                       '$S_sample = __import__("os")', '$S_sample = o[s,t] { x:i x:s }',
                       '$S_sample = o[s,t] { [:s }']:
            (self.schemas / 'sample.jsl').write_text(source)
            with self.subTest(source=source), self.assertRaises(ValueError):
                Registry(self.schemas)

    def test_cli_has_two_groups_and_runs_nested_reads_writes_schemas(self):
        cli = [sys.executable, '-m', 'josly', '--store', str(self.root),
               '--schemas-dir', str(self.schemas)]
        def call(*args):
            return subprocess.run([*cli, *args], text=True, capture_output=True)
        help_result = call('--help')
        self.assertIn('init', help_result.stdout)
        self.assertIn('generate', help_result.stdout)
        self.assertIn('write', call('query', '--help').stdout)
        self.assertNotIn('persist-package', call('query', '--help').stdout)
        catalog = json.loads(call('query', 'describe').stdout)
        commands = {c['path']: c for c in catalog['commands']}
        self.assertFalse(commands['query read']['writes_store'])
        self.assertTrue(commands['query write']['writes_store'])
        self.assertEqual(list(json.loads(call('schemas', 'list', '--format', 'json').stdout)), ['sample'])
        self.assertIn('$S_sample', call('schemas', 'show', 'sample', '--format', 'text').stdout)
        self.assertFalse(self.root.exists())
        changes = self.directory / 'changes.json'
        changes.write_text(json.dumps({'': self.value}))
        result = call('query', 'write', '--schema', 'sample', '--id', 'sample-1', '--operation', 'insert',
                      '--changes', str(changes))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['revision'], 1)
        result = call('query', 'read', '--schema', 'sample', '--id', 'sample-1', '--fields', '/name')
        self.assertEqual(json.loads(result.stdout)[0]['values'], {'/name': 'Fictional'})
        payload = self.directory / 'payload.json'
        payload.write_text(json.dumps(self.value))
        result = call('schemas', 'validate', 'sample', '--file', str(payload))
        self.assertEqual(json.loads(result.stdout), {'valid': True, 'schema': 'sample'})

    def test_generic_engine_has_no_reserved_domain_schema_names(self):
        for name in ('professional', 'analysis', 'ranking', 'process'):
            (self.schemas / (name + '.jsl')).write_text('$S_' + name + ' = o[s,t] { value:i }')
        query = Queries(self.root, self.schemas)
        for name in ('professional', 'analysis', 'ranking', 'process'):
            doc = query.write(name, 'plain-id', 'insert', {'': {'value': 1}})
            self.assertEqual(doc['data'], {'value': 1})
            self.assertTrue((self.root / name / 'plain-id.json').exists())

    def test_id_generation_and_catalog_need_neither_schemas_nor_store(self):
        cli = [sys.executable, '-m', 'josly', '--store', str(self.root),
               '--schemas-dir', str(self.directory / 'missing')]
        result = subprocess.run([*cli, 'query', 'new-id', '--prefix', 'item', '--plain'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout.strip(), r'^item_[0-9a-f]{32}$')
        result = subprocess.run([*cli, 'query', 'describe'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['tool'], 'josly')
        self.assertFalse(self.root.exists())

    def test_relations_follow_actual_type_references(self):
        (self.schemas / 'nested.jsl').write_text('$S_nested = a[$S_sample]')
        cli = [sys.executable, '-m', 'josly', '--store', str(self.root), '--schemas-dir', str(self.schemas)]
        result = subprocess.run([*cli, 'schemas', 'relations'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        graph = json.loads(result.stdout)
        self.assertEqual(graph['relations'], [{'from': '$S_nested', 'to': '$S_sample', 'relation': 'references'}])
        self.assertEqual(graph['kind'], 'declared_type_references')
        result = subprocess.run([*cli, 'schemas', 'relations', '--format', 'mermaid'], capture_output=True, text=True)
        self.assertTrue(result.stdout.startswith('flowchart LR'))
        self.assertFalse(self.root.exists())


if __name__ == '__main__':
    unittest.main()
