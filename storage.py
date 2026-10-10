"""JSON infrastructure: envelopes, confined paths, atomic replacement and local locks."""
import copy
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import uuid
from contextlib import contextmanager


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def new_id(prefix=None):
    if prefix is not None and not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,31}', prefix):
        raise ValueError('An ID prefix must be 1..32 letters/digits/underscores, starting with a letter.')
    return (prefix + '_' if prefix is not None else '') + uuid.uuid4().hex


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', value):
        raise ValueError('An ID must be 1..128 safe filename characters, without slashes.')
    return value


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.writing-')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path, value):
    encoded = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()
    atomic_write(path, encoded)


class JsonAdapter:
    def __init__(self, root, *, collections=None):
        self.root = Path(root).resolve()
        self.collections = dict(collections or {})
        for key, folder in self.collections.items():
            self._key(key); self._key(folder)

    @staticmethod
    def _key(value):
        if not isinstance(value, str) or not re.fullmatch(r'[a-z][a-z0-9_]*', value):
            raise ValueError('Schema and collection keys use lowercase letters/digits/underscores.')
        return value

    def path(self, schema, record_id):
        folder = self.collections.get(self._key(schema), schema)
        path = self.root / folder / (identifier(record_id) + '.json')
        if self.root not in path.resolve().parents:
            raise ValueError('Record path escapes the store.')
        return path

    def get(self, schema, record_id):
        document = read_json(self.path(schema, record_id))
        if (not isinstance(document, dict) or document.get('schema') != schema
                or document.get('id') != record_id or 'data' not in document
                or type(document.get('revision')) is not int or document['revision'] < 1
                or not isinstance(document.get('created_at'), str)
                or not isinstance(document.get('updated_at'), str)):
            raise ValueError('Stored document has invalid schema/ID metadata.')
        return document

    def scan(self, schema):
        folder = self.root / self.collections.get(self._key(schema), schema)
        return [self.get(schema, path.stem) for path in sorted(folder.glob('*.json'))]

    def put(self, schema, record_id, data, revision, created_at, updated_at):
        document = {'schema': schema, 'id': identifier(record_id), 'revision': revision,
                    'created_at': created_at, 'updated_at': updated_at, 'data': copy.deepcopy(data)}
        write_json(self.path(schema, record_id), document)
        return document

    @contextmanager
    def lock(self, schema, record_id):
        key = digest({'schema': self._key(schema), 'id': identifier(record_id)})
        path = self.root / '.locks' / (key + '.lock')
        if self.root not in path.resolve().parents:
            raise ValueError('Lock path escapes the store.')
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            yield
