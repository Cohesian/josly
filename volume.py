"""Explicitly initialized local volumes: configuration, schemas and JSON data."""
import os
from pathlib import Path
import re
import shutil
import tempfile

from .jsl import Registry
from .query import Queries
from .storage import JsonAdapter, new_id, now, read_json, write_json

FORMAT = 'josly-volume-v1'


def confined(root, relative):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError('Volume paths must be nonempty relative paths.')
    path = (root / relative).resolve()
    if root not in path.parents:
        raise ValueError('Volume path escapes its root.')
    return path


def validate_collections(collections):
    if not isinstance(collections, dict):
        raise ValueError('collections must be a schema -> settings object.')
    for schema, settings in collections.items():
        JsonAdapter._key(schema)
        if not isinstance(settings, dict) or set(settings) - {'directory', 'id_prefix'}:
            raise ValueError('Collection settings support directory and id_prefix.')
        JsonAdapter._key(settings.get('directory', schema))
        prefix = settings.get('id_prefix', schema)
        if not isinstance(prefix, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,31}', prefix):
            raise ValueError('Collection ID prefixes need 1..32 letters/digits/underscores, starting with a letter.')
    return collections


class Volume:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.config = read_json(self.root / 'volume.json')
        if not isinstance(self.config, dict) or self.config.get('format') != FORMAT:
            raise ValueError('Unsupported Josly volume configuration.')
        self.schemas = confined(self.root, self.config.get('schemas'))
        self.data = confined(self.root, self.config.get('data'))
        if self.schemas == self.data or self.schemas in self.data.parents or self.data in self.schemas.parents:
            raise ValueError('Schema and data directories must be separate.')
        self.collections = validate_collections(self.config.get('collections', {}))
        if not self.schemas.is_dir():
            raise ValueError('The volume schema directory is missing.')

    @classmethod
    def discover(cls, start=None):
        directory = Path(start or Path.cwd()).resolve()
        for parent in (directory, *directory.parents):
            candidate = parent / '.vol'
            if candidate.exists():
                return cls(candidate)
        return None

    def registry(self):
        registry = Registry(self.schemas, allow_empty=True)
        unknown = set(self.collections) - set(registry.roots)
        if unknown:
            raise ValueError('Collection settings reference unknown/library-only schemas: ' + ', '.join(sorted(unknown)))
        folders = [self.collections.get(name, {}).get('directory', name) for name in registry.roots]
        if len(set(folders)) != len(folders):
            raise ValueError('Different schema roots cannot share a collection directory.')
        return registry

    def queries(self, *, store=None, registry=None):
        adapter = JsonAdapter(store or self.data, collections={name: settings.get('directory', name)
                                for name, settings in self.collections.items()})
        return Queries(adapter.root, adapter=adapter, registry=registry or self.registry())

    def generate_id(self, schema, prefix=None):
        self.registry().root(schema)
        prefix = prefix if prefix is not None else self.collections.get(schema, {}).get('id_prefix', schema)
        return {'schema': schema, 'id': new_id(prefix)}


def initialize(root=None, schemas_from=None, collections=None):
    target = Path(root or Path.cwd() / '.vol').resolve()
    requested = validate_collections(collections or {})
    source = Registry(schemas_from) if schemas_from is not None else None
    if source:
        unknown = set(requested) - set(source.roots)
        folders = [requested.get(name, {}).get('directory', name) for name in source.roots]
        if unknown or len(set(folders)) != len(folders):
            raise ValueError('Collection settings must match distinct loaded schema roots.')
    elif requested:
        raise ValueError('Collection settings require --schemas-from.')
    if (target / 'volume.json').is_file():
        existing = Volume(target)
        existing.registry()
        if collections is not None and requested != existing.collections:
            raise ValueError('init does not overwrite existing collection settings.')
        if source and {name: d['text'] for name, d in source.documents.items()} != {
                name: d['text'] for name, d in existing.registry().documents.items()}:
            raise ValueError('init does not overwrite existing schemas.')
        return {'initialized': False, 'volume': str(target), 'schemas': str(existing.schemas), 'data': str(existing.data)}
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ValueError('The initialization target must be empty or an existing Josly volume.')
    # Validate every input before writing a staged volume.
    configuration = {'format': FORMAT, 'schema_format': 'jsl-v1', 'created_at': now(),
                     'schemas': 'schemas', 'data': 'data/json', 'collections': requested}
    target.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix='.josly-init-', dir=target.parent))
    try:
        (staged / 'schemas').mkdir()
        (staged / 'data/json').mkdir(parents=True)
        if source:
            for name, document in source.documents.items():
                (staged / 'schemas' / (name + '.jsl')).write_text(document['text'], encoding='utf-8')
        write_json(staged / 'volume.json', configuration)
        Volume(staged).registry()
        os.rename(staged, target)
    finally:
        if staged.exists():
            shutil.rmtree(staged)
    return {'initialized': True, 'volume': str(target), 'schemas': str(target / 'schemas'),
            'data': str(target / 'data/json')}
