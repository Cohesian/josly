"""Local help at every node; explicit volumes and generic JSON document tools."""
import argparse
import json
from pathlib import Path
import sys

from . import __version__
from .catalog import describe, relations
from .display import color_enabled, schema_list, schema_show
from .query import Queries, ensure_json
from .jsl import Registry
from .storage import new_id, read_json
from .volume import Volume, initialize

TREE = '''Command tree:
  init                         Initialize a local .vol
  schemas
    list                       Loaded schema documents
    show                       One schema definition
    validate                   Validate a JSON payload
    relations                  Declared type references and collection roots
  query
    read                       Filter and project documents
    write                      Insert/update property paths
    describe                   Machine-readable tool contract
    new-id                     Legacy unscoped generator
  generate
    id                         Generate an ID for a target schema

Run a group alone or add --help at any node for local information.'''


def parser():
    options = {'formatter_class': argparse.RawDescriptionHelpFormatter}
    cli = argparse.ArgumentParser(prog='josly', description='Josly — typed local JSON volumes.', epilog=TREE, **options)
    cli.add_argument('--version', action='version', version=f'josly {__version__}')
    cli.add_argument('--volume', type=Path, help='Volume path; otherwise find the nearest ancestor .vol.')
    cli.add_argument('--store', type=Path, help='Explicit JSON adapter root for standalone queries.')
    cli.add_argument('--schemas-dir', type=Path, help='Explicit directory of .jsl definitions.')
    groups = cli.add_subparsers(dest='group')
    p = groups.add_parser('init', help='Initialize a local volume.', description='Create .vol with schemas, JSON data and volume.json. Existing volumes are kept.', **options)
    p.add_argument('path', nargs='?', type=Path, help='Defaults to ./.vol; --volume also selects the target.')
    p.add_argument('--schemas-from', type=Path, help='Validate and copy schema definitions into the volume.')
    p.add_argument('--collections', type=Path, help='JSON schema -> {directory, id_prefix} settings.')
    schema_node = groups.add_parser('schemas', aliases=['schema'], help='Inspect and validate schema definitions.',
        description='JSL definitions expose collection roots; $S references connect declared types.', **options)
    schema_node.set_defaults(group='schemas')
    schema_ops = schema_node.add_subparsers(dest='operation')
    p = schema_ops.add_parser('list', help='Read loaded schema documents.', description='List .jsl definitions and their root types.', **options)
    schema_view_options(p)
    p = schema_ops.add_parser('show', help='Read one schema document.', description='Show an indented schema with type colors, or request the original text/JSON.', **options)
    p.add_argument('name'); schema_view_options(p)
    p = schema_ops.add_parser('validate', help='Validate a JSON payload.', description='Validate a complete typed payload without storing it.', **options)
    p.add_argument('name'); p.add_argument('--file', type=Path, required=True)
    p = schema_ops.add_parser('relations', help='Show type references and collection roots.',
        description='Resolve $S references across loaded files. Collection roots match filenames; references describe containment, not foreign keys.', **options)
    p.add_argument('--format', choices=('json', 'mermaid'), default='json')
    query_node = groups.add_parser('query', help='Read and write typed documents.', description='Paths are JSON Pointers into the typed payload. Existing writes require the current revision.', **options)
    query_ops = query_node.add_subparsers(dest='operation')
    query_ops.add_parser('describe', help='Read the machine-readable tool contract.', **options)
    p = query_ops.add_parser('read', help='Read/filter/project documents.', description='Return envelopes or pointer projections. Filters use AND conditions: eq, contains, in, exists.', **options)
    p.add_argument('--schema', required=True); p.add_argument('--id')
    p.add_argument('--fields', nargs='+', help='JSON Pointers relative to the typed payload.')
    p.add_argument('--filter', type=Path, help='JSON array of path/op/value conditions.')
    p = query_ops.add_parser('write', help='Insert/update one document by property paths.',
        description="Changes are a pointer -> value object; '' selects the root. insert requires absence; update requires presence. The complete result is validated.", **options)
    p.add_argument('--schema', required=True); p.add_argument('--id', required=True)
    p.add_argument('--operation', choices=('insert', 'update'), required=True)
    p.add_argument('--changes', type=Path, required=True)
    p.add_argument('--expected-revision', type=int)
    p = query_ops.add_parser('new-id', help='Compatibility alias for unscoped ID generation.', **options)
    p.add_argument('--prefix'); p.add_argument('--plain', action='store_true')
    generate_node = groups.add_parser('generate', help='Generate schema-scoped values.', description='Generators read schema/configuration but do not register or reserve anything.', **options)
    generate_ops = generate_node.add_subparsers(dest='operation')
    p = generate_ops.add_parser('id', help='Generate an ID for a known schema.', description='Require a collection root. Prefix comes from volume settings or schema name; no storage mutation.', **options)
    p.add_argument('--schema', required=True); p.add_argument('--prefix')
    p.add_argument('--plain', action='store_true')
    return cli


def schema_view_options(command):
    command.add_argument('--format', choices=('pretty', 'json', 'text'), default='pretty',
                         help='pretty (default): readable view; json: machine data; text: original definitions.')
    command.add_argument('--color', choices=('auto', 'always', 'never'), default='auto',
                         help='Color for pretty views; auto uses a terminal and respects NO_COLOR and TERM=dumb.')


def local_help(cli, arguments):
    """Show help for a bare group or bare command that needs arguments."""
    node, position = cli, 0
    while position < len(arguments):
        token = arguments[position]
        flag = token.split('=', 1)[0]
        action = node._option_string_actions.get(flag)
        if action and flag in ('--volume', '--store', '--schemas-dir'):
            position += 1 if '=' in token else 2
            if position > len(arguments):
                return None  # Let argparse report a missing option value.
            continue
        sub = next((a for a in node._actions if isinstance(a, argparse._SubParsersAction)), None)
        if sub and token in sub.choices:
            node = sub.choices[token]; position += 1
        else:
            return None
    has_children = any(isinstance(a, argparse._SubParsersAction) for a in node._actions)
    needs_arguments = any(a.required for a in node._actions)
    return node if node is cli or has_children or needs_arguments else None


def context(args, needs_data=False):
    volume = Volume(args.volume) if args.volume is not None else (
        None if args.schemas_dir is not None else Volume.discover())
    if args.schemas_dir is not None:
        registry = Registry(args.schemas_dir, allow_empty=True)
    elif volume is not None:
        registry = volume.registry()
    else:
        raise ValueError('No Josly volume found. Run josly init or supply --schemas-dir and --store.')
    if needs_data:
        if volume is not None:
            queries = volume.queries(store=args.store, registry=registry)
        elif args.store is not None:
            queries = Queries(args.store, registry=registry)
        else:
            raise ValueError('Standalone data queries require --store; otherwise run josly init.')
        return volume, registry, queries
    return volume, registry, None


def execute(args):
    if args.group == 'init':
        if args.path is not None and args.volume is not None:
            raise ValueError('Choose either init PATH or --volume PATH.')
        return initialize(args.path or args.volume, args.schemas_from,
                          read_json(args.collections) if args.collections else None)
    if args.group == 'query' and args.operation == 'describe':
        return describe(parser())
    if args.group == 'query' and args.operation == 'new-id':
        return {'id': new_id(args.prefix)}
    volume, registry, queries = context(args, needs_data=args.group == 'query')
    if args.group == 'generate':
        registry.root(args.schema)
        prefix = args.prefix if args.prefix is not None else (
            volume.collections.get(args.schema, {}).get('id_prefix', args.schema) if volume else args.schema)
        return {'schema': args.schema, 'id': new_id(prefix)}
    if args.group == 'schemas':
        if args.operation == 'relations':
            return relations(registry, args.format, volume.collections if volume else None)
        if args.operation == 'validate':
            value = read_json(args.file); ensure_json(value)
            registry.validate(args.name, value)
            return {'valid': True, 'schema': args.name}
        documents = registry.documents
        if args.operation == 'show':
            if args.name not in documents:
                raise ValueError('Unknown schema: ' + args.name)
            documents = {args.name: documents[args.name]}
        if args.format == 'text':
            return '\n\n'.join(f"# {doc['filename']}\n{doc['text'].rstrip()}" for doc in documents.values())
        if args.format == 'pretty':
            settings = volume.collections if volume else None
            colored = color_enabled(args.color)
            if args.operation == 'show':
                return schema_show(args.name, documents[args.name], settings, colored=colored)
            return schema_list(documents, settings, colored=colored)
        return documents
    if args.operation == 'read':
        return queries.read(args.schema, args.id, args.fields, read_json(args.filter) if args.filter else None)
    return queries.write(args.schema, args.id, args.operation, read_json(args.changes), args.expected_revision)


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    cli = parser()
    help_node = local_help(cli, arguments)
    if help_node is not None:
        help_node.print_help()
        return
    args = cli.parse_args(arguments)
    try:
        result = execute(args)
    except (ValueError, KeyError, TypeError, IndexError, OSError) as exc:
        print(json.dumps({'ok': False, 'error': {'type': type(exc).__name__, 'message': str(exc)}},
                         ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
    if isinstance(result, str):
        print(result)
    elif getattr(args, 'plain', False):
        print(result['id'])
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
