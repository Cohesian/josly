"""Machine-readable tool contracts and declared type references."""
import argparse
import json

PROTOCOL = {'name': 'Josly Schema Language', 'version': 1, 'format': 'jsl-v1', 'extension': '.jsl'}


def references(spec):
    kind = spec[0]
    if kind == 'reference':
        return {spec[1]}
    if kind == 'array':
        return references(spec[1])
    if kind == 'union':
        return set().union(*(references(child) for child in spec[1]))
    if kind == 'map':
        return set().union(*(references(child) for child in
                            [spec[1], spec[2], *(field[0] for field in spec[3].values())]))
    return set()


def relations(registry, output_format='json', settings=None):
    settings = settings or {}
    edges = [{'from': name, 'to': target, 'relation': 'references'}
             for name, spec in sorted(registry.types.items()) for target in sorted(references(spec))]
    if output_format == 'mermaid':
        ids = {name: f'type{index}' for index, name in enumerate(sorted(registry.types))}
        return '\n'.join(['flowchart LR',
            *(f'  {node}[{json.dumps(name)}]' for name, node in ids.items()),
            *(f'  {ids[edge["from"]]} --> {ids[edge["to"]]}' for edge in edges)])
    return {'protocol': PROTOCOL, 'kind': 'declared_type_references',
            'roots': dict(registry.roots), 'types': sorted(registry.types), 'relations': edges,
            'collections': {name: {'type': root, 'directory': settings.get(name, {}).get('directory', name),
                                   'id_prefix': settings.get(name, {}).get('id_prefix', name)}
                            for name, root in registry.roots.items()}}


def describe(parser):
    commands = []
    def visit(command, path):
        children = [a for a in command._actions if isinstance(a, argparse._SubParsersAction)]
        if children:
            for action in children:
                for name, child in action.choices.items():
                    visit(child, [*path, name])
            return
        commands.append({'path': ' '.join(path), 'writes_store': path == ['query', 'write'], 'writes_volume': path == ['init'],
            'arguments': [{'name': a.dest, 'flags': a.option_strings, 'required': a.required,
                           'choices': list(a.choices) if a.choices is not None else None}
                          for a in command._actions if a.dest != 'help']})
    visit(parser, [])
    return {'tool': 'josly', 'contract_version': 1, 'schema_protocol': PROTOCOL,
            'global_arguments': ['--volume PATH', '--store PATH', '--schemas-dir PATH (before the group)'],
            'commands': commands,
            'success': 'JSON stdout; schemas list/show default to pretty text. Use --format json for scripts. Help, plain IDs, text and Mermaid are text.',
            'failure': 'JSON stderr and exit 2; argparse usage errors are text'}
