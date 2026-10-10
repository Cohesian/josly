"""Readable schema views; formatting never changes stored definitions."""
import os
import sys

from .jsl import TOKEN


TYPE_COLORS = {'i': '34', 'f': '34', 's': '34', 'b': '34', 't': '33', 'n': '35',
               'a': '34', 'o': '34'}


def color_enabled(mode='auto', *, stream=None, environ=None):
    if mode != 'auto':
        return mode == 'always'
    stream = sys.stdout if stream is None else stream
    environ = os.environ if environ is None else environ
    return stream.isatty() and 'NO_COLOR' not in environ and environ.get('TERM') != 'dumb'


def paint(value, code, colored):
    return f'\x1b[{code}m{value}\x1b[0m' if colored else value


def format_source(source):
    """Indent records and separate fields, retaining comments and literal text."""
    tokens = [match.group() for match in TOKEN.finditer(source) if not match.group().isspace()]
    lines, stack = [], []
    line, indent = '', 0

    def flush():
        nonlocal line
        if line:
            lines.append('  ' * indent + line.rstrip())
            line = ''

    for index, token in enumerate(tokens):
        next_token = tokens[index + 1] if index + 1 < len(tokens) else None
        following = tokens[index + 2] if index + 2 < len(tokens) else None
        is_field = next_token == ':' or (next_token == '?' and following == ':')
        is_declaration = token.startswith('$S_') and next_token == '='
        if token.startswith('#'):
            line += ('  ' if line else '') + token
            flush()
        elif token == '{':
            line = line.rstrip() + ' {'
            flush(); indent += 1; stack.append('{')
        elif token == '}':
            flush(); indent -= 1; stack.pop(); line = '}'
        elif token == '[':
            line += '['; stack.append('[')
        elif token == ']':
            line = line.rstrip() + ']'; stack.pop()
        elif token == ',':
            line = line.rstrip() + ','
            if stack and stack[-1] == '[':
                line += ' '
            else:
                flush()
        elif token == ':':
            line = line.rstrip() + ': '
        elif token in ('=', '|'):
            line = line.rstrip() + f' {token} '
        elif token == '?':
            line = line.rstrip() + '?'
        else:
            if is_field or is_declaration:
                flush()
                if is_declaration and lines and not lines[-1].lstrip().startswith('#'):
                    lines.append('')
            if line and not line.endswith((' ', '[')):
                line += ' '
            line += token
    flush()
    return '\n'.join(lines)


def highlight(source, colored):
    if not colored:
        return source

    def style(match):
        token = match.group()
        # A field named "s" or "a" is a key, not a primitive/composite type.
        tail = source[match.end():].lstrip()
        is_key = tail.startswith(':') or (tail.startswith('?') and tail[1:].lstrip().startswith(':'))
        if token.startswith('#'):
            code = '90'
        elif token.startswith('$S_'):
            code = '36'
        elif token.startswith('"') and not is_key:
            code = '32'
        elif token in TYPE_COLORS and not is_key:
            code = TYPE_COLORS[token]
        else:
            return token
        return paint(token, code, True)

    return TOKEN.sub(style, source)


def schema_list(documents, settings=None, *, colored=False):
    if not documents:
        return 'No schemas loaded.\nAdd .jsl definitions to the volume\'s schemas/ directory.'
    settings = settings or {}
    rows = [(name, doc['root_type'] or '(shared types)',
             settings.get(name, {}).get('directory', name) if doc['root_type'] else '—',
             doc['filename']) for name, doc in sorted(documents.items())]
    headers = ('Schema', 'Root type', 'Collection', 'File')
    widths = [max(len(row[index]) for row in [headers, *rows]) for index in range(len(headers))]
    roots = sum(bool(doc['root_type']) for doc in documents.values())
    title = f'{len(rows)} schema{"s" if len(rows) != 1 else ""} · {roots} collection{"s" if roots != 1 else ""}'
    lines = [paint(title, '1', colored), '',
             paint('  '.join(value.ljust(width) for value, width in zip(headers, widths)), '1', colored),
             paint('  '.join('─' * width for width in widths), '90', colored)]
    for row in rows:
        lines.append('  '.join(paint(value.ljust(width), '36' if index == 1 and value.startswith('$S_') else '0', colored)
                               for index, (value, width) in enumerate(zip(row, widths))))
    lines.extend(['', 'Use josly schemas show NAME to inspect a definition.'])
    return '\n'.join(lines)


def schema_show(name, document, settings=None, *, colored=False):
    settings = settings or {}
    root = document['root_type']
    lines = [paint(f'Schema: {name}', '1', colored), f'File: {document["filename"]}']
    if root:
        lines.extend([f'Root: {paint(root, "36", colored)}',
                      f'Collection: {settings.get(name, {}).get("directory", name)}'])
    else:
        lines.append('Kind: shared types (no collection root)')
    lines.extend(['', highlight(format_source(document['text']), colored), '',
                  'Types: ' + ' · '.join(paint(token, TYPE_COLORS[token], colored) + ' ' + label
                      for token, label in [('i', 'integer'), ('f', 'float'), ('s', 'string'),
                                           ('b', 'bool'), ('t', 'any'), ('n', 'null')]),
                  'Containers: a[T] array · o[K, V] map · $S_name reference · ? optional'])
    return '\n'.join(lines)
