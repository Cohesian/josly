"""Schema-backed reads and atomic single-ID patches; no code evaluation."""
import copy
import json
import math

from .storage import JsonAdapter, identifier, digest, now
from .jsl import Registry, pointer_tokens

MISSING = object()


def ensure_json(value):
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("The JSON adapter requires string object keys.")
        for child in value.values():
            ensure_json(child)
    elif isinstance(value, list):
        for child in value:
            ensure_json(child)
    elif type(value) not in (str, int, float, bool, type(None)):
        raise ValueError("Unsupported JSON value.")
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError("JSON numbers must be finite.")


def get_path(data, path):
    value = data
    for token in pointer_tokens(path):
        if isinstance(value, dict):
            value = value.get(token, MISSING)
        elif isinstance(value, list) and token.isdigit() and str(int(token)) == token and int(token) < len(value):
            value = value[int(token)]
        else:
            return MISSING
        if value is MISSING:
            return MISSING
    return value


def apply_changes(document, changes, operation, registry, schema, *, check_root=True):
    if operation not in ('insert', 'update') or not isinstance(changes, dict) or not changes:
        raise ValueError("Supply insert/update and a nonempty object of JSON Pointer -> value changes.")
    paths = [pointer_tokens(path) for path in changes]
    for index, path in enumerate(paths):
        for other in paths[index + 1:]:
            if path == other[:len(path)] or other == path[:len(other)]:
                raise ValueError("Overlapping parent/child changes are ambiguous.")
    candidate = MISSING if document is MISSING else copy.deepcopy(document)
    for path, new_value in changes.items():
        spec = registry.path_type(schema, path, declared_only=True)
        if path or check_root:
            registry.check(spec, new_value, path)
        ensure_json(new_value)
        tokens = pointer_tokens(path)
        existing = MISSING if candidate is MISSING else get_path(candidate, path)
        if operation == 'insert' and existing is not MISSING:
            raise ValueError("insert requires an absent path: " + (path or '/'))
        if operation == 'update' and existing is MISSING:
            raise ValueError("update requires an existing path: " + (path or '/'))
        if not tokens:
            candidate = copy.deepcopy(new_value)
            continue
        if candidate is MISSING:
            candidate = {}
        parent = candidate
        for token in tokens[:-1]:
            if isinstance(parent, dict):
                if token not in parent and operation == 'insert':
                    parent[token] = {}
                if token not in parent or parent[token] is None:
                    raise ValueError("Supply the missing/nullable parent object explicitly: " + path)
                parent = parent[token]
            elif isinstance(parent, list) and token.isdigit() and int(token) < len(parent):
                parent = parent[int(token)]
            else:
                raise ValueError("Invalid path parent: " + path)
        leaf = tokens[-1]
        if isinstance(parent, dict):
            parent[leaf] = copy.deepcopy(new_value)
        elif isinstance(parent, list) and leaf.isdigit():
            index = int(leaf)
            if operation == 'insert' and index == len(parent):
                parent.append(copy.deepcopy(new_value))
            elif operation == 'update' and index < len(parent):
                parent[index] = copy.deepcopy(new_value)
            else:
                raise ValueError("Arrays support update of existing indices or insert at length.")
        else:
            raise ValueError("Invalid path target: " + path)
    return candidate


class Queries:
    def __init__(self, root, schemas_directory=None, *, adapter=None, registry=None):
        self.adapter = adapter if adapter is not None else JsonAdapter(root)
        self.registry = registry if registry is not None else Registry(schemas_directory)

    def read(self, schema, record_id=None, fields=None, conditions=None):
        self.registry.root(schema)
        fields = fields or []
        for path in fields:
            self.registry.path_type(schema, path)
        conditions = [] if conditions is None else conditions
        if not isinstance(conditions, list):
            raise ValueError("Filters are an array of AND conditions.")
        for condition in conditions:
            if not isinstance(condition, dict) or condition.get('op') not in ('eq', 'contains', 'in', 'exists'):
                raise ValueError("Filter operations: eq, contains, in, exists.")
            self.registry.path_type(schema, condition.get('path'))
            if 'value' not in condition:
                raise ValueError("Each filter requires value.")
            if condition['op'] == 'exists' and type(condition['value']) is not bool:
                raise ValueError("exists requires a boolean value.")
            if condition['op'] == 'in' and not isinstance(condition['value'], list):
                raise ValueError("in requires an array value.")
            ensure_json(condition['value'])
        if record_id is not None:
            identifier(record_id)
            documents = [self.adapter.get(schema, record_id)] if self.adapter.path(schema, record_id).exists() else []
        else:
            documents = self.adapter.scan(schema)
        def equal(left, right):
            return left is not MISSING and json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)
        def match(data, condition):
            value, wanted = get_path(data, condition['path']), condition['value']
            op = condition['op']
            if op == 'exists':
                return (value is not MISSING) == wanted
            if op == 'eq':
                return equal(value, wanted)
            if op == 'in':
                return any(equal(value, option) for option in wanted)
            return ((isinstance(value, str) and isinstance(wanted, str) and wanted in value)
                    or (isinstance(value, list) and any(equal(item, wanted) for item in value)))
        output = []
        for document in documents:
            ensure_json(document['data'])
            self.registry.validate(schema, document['data'])
            if not all(match(document['data'], condition) for condition in conditions):
                continue
            if fields:
                data = document['data']
                document = {key: document[key] for key in ('schema', 'id', 'revision', 'created_at', 'updated_at')}
                document['values'] = {path: copy.deepcopy(value) for path in fields
                                      if (value := get_path(data, path)) is not MISSING}
            output.append(document)
        return output

    def write(self, schema, record_id, operation, changes, expected_revision=None):
        identifier(record_id)
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 0):
            raise ValueError("expected_revision must be a nonnegative integer.")
        self.registry.root(schema)
        path = self.adapter.path(schema, record_id)
        previous = self.adapter.get(schema, record_id) if path.exists() else None
        def candidate(old):
            value = apply_changes(old['data'] if old else MISSING, changes, operation, self.registry, schema)
            self.registry.validate(schema, value)
            ensure_json(value)
            return value
        candidate(previous)  # Reject invalid new documents before creating locks/directories.
        with self.adapter.lock(schema, record_id):
            previous = self.adapter.get(schema, record_id) if path.exists() else None
            revision = previous['revision'] if previous else 0
            if previous and expected_revision is None:
                raise ValueError("An existing document requires expected_revision.")
            if expected_revision is not None and expected_revision != revision:
                raise ValueError("Revision conflict; read the current document first.")
            value = candidate(previous)
            if previous and digest(value) == digest(previous['data']):
                return previous
            date = now()
            return self.adapter.put(schema, record_id, value, revision + 1,
                                    previous['created_at'] if previous else date, date)
