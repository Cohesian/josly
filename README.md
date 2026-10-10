# Josly

Typed local JSON volumes, portable schemas and validated property queries.
Python 3.11+, standard-library runtime, macOS/Linux file locks.

## Install

Install the tagged version from [GitHub](https://github.com/Cohesian/josly)
(Python 3.11+ and Git required):

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install "josly @ git+https://github.com/Cohesian/josly.git@v0.2.1"
josly --version
josly
```

For local development:

```sh
git clone https://github.com/Cohesian/josly.git
cd josly
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
josly
```

`-e` uses local code. Reinstall after package/dependency/entry-point changes.
`python -m josly` is also available after installation. To follow the current main
branch instead of a tagged release, replace `@v0.2.1` with `@main`.
See [CHANGELOG.md](CHANGELOG.md) for release notes.

## Command tree

```text
josly
├── init
├── schemas                      # schema is an alias
│   ├── list
│   ├── show
│   ├── validate
│   └── relations
├── query
│   ├── read
│   ├── write
│   └── describe
└── generate
    └── id
```

`josly` alone displays the tree and root help. A bare group displays its local
commands. Every node accepts `--help`; a bare leaf needing arguments also displays
help. `init`, `schemas list` and `schemas relations` execute with their valid defaults.
Help, reads and generation do not create storage state. `query new-id` remains an
older unscoped compatibility alias; use `generate id --schema NAME` for new work.

```sh
josly schemas
josly schemas relations --help
josly query write --help
josly generate id --help
josly query describe
```

## Initialize a volume

```sh
josly init
```

This explicitly creates:

```text
.vol/
├── volume.json                  # Version, paths and optional collection settings
├── schemas/                     # .jsl definitions
└── data/json/                   # One enveloped JSON file per document
    └── <collection>/<id>.json
```

A default new volume has no schemas or records. Repeating `init` keeps an existing
volume. It never overwrites changed schemas/configuration or a nonempty unrelated
directory. Schema input is validated before initialization. Collection folders
materialize on first write.

To load all example schemas at initialization:

```sh
josly init --schemas-from examples/schemas
```

Use this as your first initialization, or target a separate folder with
`josly init demo/.vol --schemas-from examples/schemas`. Once initialized, you can
add/edit `.jsl` files in `.vol/schemas/`; each operation reloads the definitions.
Schema edits do not migrate existing records.

Josly discovers the nearest `.vol` from the current directory up through its
ancestors. `--volume PATH` selects one explicitly. Global options go **before** the
group. Advanced standalone queries can instead supply both `--schemas-dir PATH`
and `--store PATH`; no volume is then required. Schema-only operations need only
`--schemas-dir`. Paths are confined to the selected volume/adapter root.

## JSL schemas

**Josly Schema Language (JSL), v1**: `.jsl`, format identifier `jsl-v1`.
[The format contract](docs/jsl-v1.md) defines syntax and semantics.

```jsl
$S_person = o[s, t] {
  name: s
  active: b
  age?: i | n
  tags: a[s]
  attributes: o[s, t]
}
```

`i/f/s/b`: integer/float/string/bool; `t`: any; `n`: null. `a[T]` is an array,
`o[K,V]` a typed map. `$S_name` references a declared type. A file `person.jsl`
exposes `$S_person` as a collection root. Other declarations are shared types.
Legacy `.shape` files remain readable; initialization copies them as `.jsl`.
Two files exposing the same schema name are rejected.

```sh
josly schemas list
josly schemas show person
josly schemas validate person --file payload.json
josly schemas relations --format mermaid
```

`list` defaults to an aligned table showing each schema, its root type, collection
directory and source file. Shared type files have no collection. `show` defaults
to an indented definition with separate fields, retained comments and a type legend.
These views only format the display; they never rewrite `.jsl` files.

Types/references/literals/comments use terminal colors automatically. Redirected
output stays plain; `NO_COLOR` or `TERM=dumb` disables automatic color.
`--color always` explicitly forces it, and `--color never` disables it.

```sh
josly schemas show person --color always
josly schemas list --format json
josly schemas show person --format json
josly schemas show person --format text
```

Use `--format json` for scripts: this retains the schema document metadata and exact
original source text. `--format text` prints original definitions with filename
headers. Neither output uses colors. `--format pretty` explicitly selects the default
human view. These format/color options belong to `schemas list` and `schemas show`.

`relations` resolves actual `$S` type references and lists available collection
roots. References describe embedded structural dependencies. Application foreign
keys and workflow rules require application validation.

## Generate IDs

```sh
josly generate id --schema person
josly generate id --schema person --plain
```

The target must be a loaded collection root. The default prefix is its schema
name, such as `person_<32 hex digits>`. IDs are generated without registration,
reservation or storage mutation. An explicit `--prefix` can override the prefix.
Prefixes support 1–32 letters/digits/underscores, starting with a letter.

`init --collections FILE` accepts optional mappings together with `--schemas-from`:

```json
{
  "person": {"directory": "people", "id_prefix": "per"}
}
```

Settings live in `volume.json`. Root schemas must map to distinct directories.
Unknown/library-only schema mappings and unsafe names/prefixes are rejected.

## Read and write

After initializing the example volume:

```sh
josly query write --schema person --id example-1 --operation insert --changes examples/insert.json
josly query read --schema person --id example-1 --fields /name /contact/email
josly query write --schema person --id example-1 --operation update --changes examples/update.json --expected-revision 1
```

Stored envelopes contain `schema`, `id`, `revision`, `created_at`, `updated_at`
and the typed payload `data`. `query read` returns envelopes; `--fields /path ...`
returns a `values` pointer map instead of data. Missing fields are omitted; null
is preserved. No match is `[]`.

`--filter FILE` uses an array of AND conditions:

```json
[
  {"path": "/active", "op": "eq", "value": true},
  {"path": "/name", "op": "contains", "value": "example"}
]
```

Operators: eq, contains (case-sensitive substring or array member), in (equals
one member of an array), exists (presence; boolean value). Booleans differ from
numbers; missing differs from null. No wildcard traversal or executable filters.

Writes use a JSON object of pointer -> value changes. `""` selects the root.
Insert requires an absent target; update requires presence. The ID selects an
existing or new record, but creation happens only if the complete result is valid.
Existing documents require `--expected-revision`, rechecked under the lock.

Validate every path/value and the complete result. Declared records reject typo
field patches; dynamic maps support matching keys. Additional keys can be retained
inside complete objects according to the map value type. Replace nullable parents
explicitly. Overlapping parent/child changes are rejected. Arrays allow existing
index updates or append-at-length insertion; no gaps, shifting or deletion.
Identical updates retain a revision. Single-record replacement is atomic.

Runtime output is JSON stdout, except `schemas list/show`, which default to readable
text; select `--format json` for machine use. Runtime errors are JSON stderr with
exit 2. Help, plain IDs, schema text and Mermaid are text. Argument errors are argparse text.
`query describe` returns a machine contract without requiring schemas or a volume.

## Library and application boundary

```python
from josly import Volume, initialize

initialize("project/.vol", schemas_from="schemas")
volume = Volume("project/.vol")
identifier = volume.generate_id("person")["id"]
document = volume.queries().write("person", identifier, "insert", {"": payload})
```

`Registry`, `Queries`, `JsonAdapter` and `new_id` also remain available. Application
code can extend queries/adapters with domain validators. Keep domain rules, source
identity constraints and workflow policy in the consuming application; generic JSL
type checking alone does not implement those guarantees.

## Layout and limits

`jsl.py` is the parser; `shape.py` is an import compatibility shim. `volume.py`
manages initialization/configuration; `query.py` manages typed paths;
`storage.py` manages JSON and locks; `catalog.py` exposes tools/type references;
`display.py` renders schema tables, indentation and optional terminal colors.

No indexes, background jobs, cross-record transactions or migration engine. Queries
scan this small local store. Tests use fictional schemas and temporary volumes.
After installing locally, run from the repository root:

```sh
python -m unittest discover -s tests -v
```
