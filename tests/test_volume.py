"""Volume initialization, help navigation and scoped IDs with temporary data."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from josly import Volume, initialize, Registry


class VolumeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.sources = self.root / 'source-schemas'; self.sources.mkdir()
        (self.sources / 'item.jsl').write_text('$S_item = o[s,t] { name:s details:$S_details }\n$S_details = o[s,t]')
        self.volume = self.root / '.vol'
        self.environment = {**os.environ, 'PYTHONPATH': str(ROOT.parent)}

    def call(self, *args, cwd=None):
        return subprocess.run([sys.executable, '-m', 'josly', *args], cwd=cwd or self.root,
                              env=self.environment, capture_output=True, text=True)

    def files(self):
        return {str(f.relative_to(self.root)):f.read_bytes() for f in self.root.rglob('*') if f.is_file()}

    def test_bare_root_groups_and_required_leaves_show_local_help_without_mutation(self):
        before=self.files()
        for args in [(), ('schemas',), ('schema',), ('query',), ('generate',),
                     ('query','read'), ('query','write'), ('generate','id'), ('schemas','show'),
                     ('schemas','relations','--help'), ('init','--help')]:
            with self.subTest(args=args):
                result=self.call(*args)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertIn('usage: josly',result.stdout)
                self.assertEqual(result.stderr,'')
        self.assertIn('Command tree:',self.call().stdout)
        self.assertEqual(before,self.files())

    def test_init_empty_volume_and_repeat_are_safe(self):
        result=self.call('init')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(json.loads(result.stdout)['initialized'])
        self.assertTrue((self.volume/'schemas').is_dir())
        self.assertTrue((self.volume/'data/json').is_dir())
        self.assertEqual(json.loads(self.call('schemas','list','--format','json').stdout),{})
        before=self.files()
        self.assertFalse(json.loads(self.call('init').stdout)['initialized'])
        self.assertEqual(before,self.files())

    def test_init_registers_sources_and_ids_use_target_schema_settings(self):
        mappings=self.root/'collections.json'
        mappings.write_text(json.dumps({'item':{'directory':'items','id_prefix':'obj'}}))
        result=self.call('init','--schemas-from',str(self.sources),'--collections',str(mappings))
        self.assertEqual(result.returncode,0,result.stderr)
        before=self.files()
        result=self.call('generate','id','--schema','item')
        self.assertEqual(result.returncode,0,result.stderr)
        value=json.loads(result.stdout)
        self.assertEqual(value['schema'],'item');self.assertRegex(value['id'],r'^obj_[0-9a-f]{32}$')
        error=self.call('generate','id','--schema','missing')
        self.assertEqual(error.returncode,2)
        self.assertEqual(before,self.files())
        graph=json.loads(self.call('schemas','relations').stdout)
        self.assertEqual(graph['collections']['item']['directory'],'items')
        self.assertEqual(graph['roots'],{'item':'$S_item'})
        self.assertIn({'from':'$S_item','to':'$S_details','relation':'references'},graph['relations'])

    def test_discovery_from_child_and_write_read_flow(self):
        initialize(self.volume,self.sources,{'item':{'directory':'items','id_prefix':'obj'}})
        child=self.root/'sub/project';child.mkdir(parents=True)
        self.assertEqual(Volume.discover(child).root,self.volume.resolve())
        changes=self.root/'changes.json';changes.write_text(json.dumps({'':{'name':'Fictional','details':{}}}))
        result=self.call('query','write','--schema','item','--id','obj-one','--operation','insert',
                         '--changes',str(changes),cwd=child)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue((self.volume/'data/json/items/obj-one.json').is_file())
        rows=json.loads(self.call('query','read','--schema','item','--fields','/name',cwd=child).stdout)
        self.assertEqual(rows[0]['values'],{'/name':'Fictional'})

    def test_invalid_schema_config_and_nonempty_targets_are_not_overwritten(self):
        (self.sources/'item.jsl').write_text('$S_item = $S_missing')
        with self.assertRaises(ValueError):initialize(self.volume,self.sources)
        self.assertFalse(self.volume.exists())
        self.volume.mkdir();(self.volume/'user.txt').write_text('Keep this file')
        with self.assertRaises(ValueError):initialize(self.volume)
        self.assertEqual((self.volume/'user.txt').read_text(),'Keep this file')
        self.assertEqual(len(list(self.volume.iterdir())),1)

    def test_invalid_paths_and_collection_settings_reject_escaping_or_collision(self):
        for settings in ({'item':{'directory':'../outside'}}, {'unknown':{'directory':'unknown'}},
                         {'item':{'id_prefix':'invalid/'}}, {'item':{'unknown_field':True}}):
            with self.subTest(settings=settings),self.assertRaises(ValueError):
                initialize(self.volume,self.sources,settings)
            self.assertFalse(self.volume.exists())
        initialize(self.volume,self.sources)
        config=self.volume/'volume.json';value=json.loads(config.read_text());value['data']='../outside'
        config.write_text(json.dumps(value))
        with self.assertRaises(ValueError):Volume(self.volume)
        self.assertFalse((self.root/'outside').exists())

    def test_existing_volume_schema_changes_are_not_overwritten_by_init(self):
        initialize(self.volume,self.sources)
        (self.volume/'schemas/item.jsl').write_text('$S_item = s')
        before=self.files()
        with self.assertRaises(ValueError):initialize(self.volume,self.sources)
        self.assertEqual(before,self.files())

    def test_legacy_extension_is_readable_but_ambiguous_twins_are_rejected(self):
        (self.sources/'item.jsl').rename(self.sources/'item.shape')
        self.assertIn('item',Registry(self.sources).roots)
        initialize(self.volume,self.sources)
        self.assertTrue((self.volume/'schemas/item.jsl').exists())
        (self.sources/'item.jsl').write_text('$S_item = s')
        with self.assertRaises(ValueError):Registry(self.sources)


if __name__=='__main__':unittest.main()
