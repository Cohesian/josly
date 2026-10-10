"""Interpret the documented JSL subset without evaluating source code."""
import json
import math
from pathlib import Path
import re

TOKEN = re.compile(r'\s+|\#[^\n]*|"(?:[^"\\]|\\.)*"|\$S_\w+|[A-Za-z_]\w*|[\[\]{},:=?|]')


class Parser:
    def __init__(self, text):
        self.tokens = []
        position = 0
        while position < len(text):
            match = TOKEN.match(text, position)
            if not match:
                raise ValueError(f"Invalid JSL syntax near {text[position:position + 25]!r}")
            token = match.group()
            if not token.isspace() and not token.startswith('#'):
                self.tokens.append(token)
            position = match.end()
        self.position = 0

    def take(self, expected=None):
        if self.position == len(self.tokens):
            raise ValueError("Unexpected end of JSL definition.")
        token = self.tokens[self.position]
        if expected is not None and token != expected:
            raise ValueError(f"Expected {expected!r}, found {token!r}.")
        self.position += 1
        return token

    def accept(self, token):
        if self.position < len(self.tokens) and self.tokens[self.position] == token:
            self.position += 1
            return True
        return False

    def expression(self):
        options = [self.atom()]
        while self.accept('|'):
            options.append(self.atom())
        return options[0] if len(options) == 1 else ('union', options)

    def atom(self):
        token = self.take()
        if token.startswith('$S_'):
            return ('reference', token)
        if token.startswith('"'):
            return ('literal', json.loads(token))
        if token in ('i', 'f', 's', 'b', 't', 'n'):
            return (token,)
        if token == 'a':
            self.take('[')
            value = self.expression()
            self.take(']')
            return ('array', value)
        if token == 'o':
            self.take('[')
            key = self.expression()
            self.take(',')
            value = self.expression()
            self.take(']')
            fields = {}
            if self.accept('{'):
                while not self.accept('}'):
                    name = self.take()
                    if not name.startswith('"') and not re.fullmatch(r'[A-Za-z_]\w*', name):
                        raise ValueError("JSL field names must be identifiers or quoted strings.")
                    name = json.loads(name) if name.startswith('"') else name
                    optional = self.accept('?')
                    self.take(':')
                    if name in fields:
                        raise ValueError("Duplicate JSL field: " + name)
                    fields[name] = (self.expression(), optional)
                    self.accept(',')
            return ('map', key, value, fields)
        raise ValueError("Unsupported JSL type: " + token)

    def declarations(self):
        result = {}
        while self.position < len(self.tokens):
            name = self.take()
            if not name.startswith('$S_') or name in result:
                raise ValueError("Invalid or duplicate JSL declaration: " + name)
            self.take('=')
            result[name] = self.expression()
        return result


def pointer_tokens(path):
    if not isinstance(path, str) or (path and not path.startswith('/')):
        raise ValueError("Paths must be JSON Pointers: '' or /field/child.")
    if re.search(r'~(?![01])', path):
        raise ValueError("Invalid JSON Pointer escape.")
    return [part.replace('~1', '/').replace('~0', '~') for part in path[1:].split('/')] if path else []


class Registry:
    def __init__(self, directory=None, *, allow_empty=False):
        self.directory = Path(directory) if directory else Path.cwd() / 'schemas'
        self.types, self.documents, self.roots = {}, {}, {}
        for path in sorted([*self.directory.glob('*.jsl'), *self.directory.glob('*.shape')]):
            if not re.fullmatch(r'[a-z][a-z0-9_]*', path.stem):
                raise ValueError("Invalid schema filename.")
            if path.stem in self.documents:
                raise ValueError('Multiple schema files expose the same name: ' + path.stem)
            text = path.read_text(encoding='utf-8')
            definitions = Parser(text).declarations()
            if set(definitions) & set(self.types):
                raise ValueError("A JSL type was declared in more than one file.")
            self.types.update(definitions)
            root = '$S_' + path.stem
            self.documents[path.stem] = {'format': 'jsl-v1' if path.suffix == '.jsl' else 'shape-v1',
                                          'filename': path.name, 'text': text,
                                          'root_type': root if root in definitions else None}
            if root in definitions:
                self.roots[path.stem] = root
        if not self.documents and not allow_empty:
            raise ValueError("No .jsl schemas loaded.")
        for name, spec in self.types.items():
            self._references(spec, {name})

    def _references(self, spec, seen):
        kind = spec[0]
        if kind == 'reference':
            name = spec[1]
            if name not in self.types:
                raise ValueError("Undefined JSL type: " + name)
            if name in seen:
                raise ValueError("Recursive JSL types are not supported in v1: " + name)
            self._references(self.types[name], seen | {name})
        elif kind in ('array',):
            self._references(spec[1], seen)
        elif kind == 'union':
            for option in spec[1]:
                self._references(option, seen)
        elif kind == 'map':
            for child in [spec[1], spec[2], *(value[0] for value in spec[3].values())]:
                self._references(child, seen)

    def root(self, schema):
        if schema not in self.roots:
            raise ValueError("Unknown or library-only schema: " + schema)
        return self.types[self.roots[schema]]

    def expand(self, spec):
        while spec[0] == 'reference':
            spec = self.types[spec[1]]
        return spec

    def validate(self, schema, value):
        self.check(self.root(schema), value, '')
        return value

    def check(self, spec, value, path):
        spec = self.expand(spec)
        kind = spec[0]
        fail = lambda: ValueError(f"{path or '/'}: expected {kind}.")
        if kind == 't':
            return
        if kind == 'union':
            for option in spec[1]:
                try:
                    self.check(option, value, path)
                    return
                except ValueError:
                    pass
            raise fail()
        if kind == 'literal':
            if type(value) is not type(spec[1]) or value != spec[1]:
                raise ValueError(f"{path or '/'}: expected literal {spec[1]!r}.")
        elif kind == 'n':
            if value is not None:
                raise fail()
        elif kind == 's':
            if not isinstance(value, str):
                raise fail()
        elif kind == 'b':
            if type(value) is not bool:
                raise fail()
        elif kind == 'i':
            if type(value) is not int:
                raise fail()
        elif kind == 'f':
            if type(value) not in (int, float) or (type(value) is float and not math.isfinite(value)):
                raise fail()
        elif kind == 'array':
            if not isinstance(value, list):
                raise fail()
            for index, item in enumerate(value):
                self.check(spec[1], item, f'{path}/{index}')
        elif kind == 'map':
            if not isinstance(value, dict):
                raise fail()
            for name, (child, optional) in spec[3].items():
                if name not in value and not optional:
                    raise ValueError(f"{path}/{name}: required field is absent.")
            for key, item in value.items():
                self.check(spec[1], key, path)
                self.check(spec[3].get(key, (spec[2], True))[0], item, f'{path}/{key}')

    def path_type(self, schema, path, *, declared_only=False):
        specs = [self.root(schema)]
        for token in pointer_tokens(path):
            children = []
            pending = list(specs)
            while pending:
                spec = self.expand(pending.pop())
                if spec[0] == 'union':
                    pending.extend(spec[1])
                elif spec[0] == 'map':
                    try:
                        self.check(spec[1], token, path)
                    except ValueError:
                        continue
                    if token in spec[3]:
                        children.append(spec[3][token][0])
                    elif not spec[3] or not declared_only:
                        children.append(spec[2])
                elif spec[0] == 'array' and re.fullmatch(r'0|[1-9]\d*', token):
                    children.append(spec[1])
                elif spec[0] == 't':
                    children.append(spec)
            if not children:
                raise ValueError("Path does not match the schema: " + path)
            specs = children
        return specs[0] if len(specs) == 1 else ('union', specs)
