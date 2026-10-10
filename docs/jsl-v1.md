# Josly Schema Language (JSL) v1

Format identifier: `jsl-v1`. Extension: `.jsl`. Encoding: UTF-8.
The notation declares types independently of an application or storage engine.
Josly implements the structural subset documented here.

## Types

| Syntax | Meaning |
|---|---|
| `i` | Integer, excluding booleans |
| `f` | Finite float or integer, excluding booleans |
| `s` | String |
| `b` | Boolean |
| `t` | Any type, including null |
| `n` | Null |
| `a[T]` | Array of T |
| `o[K,V]` | Map with keys of K and values of V |
| `o[s,t] { field:T ... }` | Map with declared fields refining value types |
| `field?: T` | Optional key |
| `T \| U` | Union |
| `"value"` | Exact string literal |
| `$S_name` | Named type reference |
| `# text` | Comment through end of line |

Declarations use `$S_name = T`. A file `name.jsl` exposes `$S_name` as its root,
if that declaration appears in the file. Other declarations are shared types.
Definitions are resolved across all loaded files; duplicate, unresolved and
recursive definitions are rejected in v1. Filenames use lowercase ASCII identifiers.
Whitespace and commas between field declarations are optional separators.

```jsl
$S_details = o[s, t] {
  note?: s | n
}

$S_example = o[s, t] {
  title: s
  values: a[i | s]
  counts: o[s, i]
  details: $S_details
}
```

Required keys must exist. Optional keys may be absent. Nullability is independent
of optionality: `note?: s` allows absence but not null; `note: s | n` requires the
key and allows null. Unlisted map keys follow V; declared fields refine their value
type. All keys must still satisfy K. No implicit coercion occurs.

## Structural grammar

```text
file         := declaration*
declaration  := reference "=" type
type         := atom ("|" atom)*
atom         := primitive | reference | json_string
              | "a[" type "]"
              | "o[" type "," type "]" fields?
fields       := "{" (field ","?)* "}"
field        := (identifier | json_string) "?"? ":" type
primitive    := "i" | "f" | "s" | "b" | "t" | "n"
reference    := "$S_" identifier
```

Strings use JSON quoting and escapes. Current support includes string literals,
not numeric/boolean literal types, constraints, functions or executable expressions.
Domain constraints in comments remain documentation until an application validates
them. There is no code evaluation.

## JSON adapter and property paths

The type layer can express integer-keyed maps such as `o[i,s]`. The JSON adapter
requires string object keys, JSON-compatible values and finite numbers; integer
keys need explicit representation conversion before storage. `t` does not bypass
those adapter constraints.

Queries use JSON Pointer: `""` selects the root, `/field/child` selects nested data,
`~1` escapes `/`, and `~0` escapes `~`. Array indices are canonical nonnegative decimal
integers. These paths apply to the typed payload, not the storage envelope.

A patch into a record with named fields must use a declared field. Dynamic maps
allow new keys satisfying K/V. Complete objects can preserve extra keys according
to V. The path's type and the complete resulting document are both validated.
This is a query policy, not an additional type construct.

## Versioning

`jsl-v1` identifies this supported contract. New syntax or changed semantics that
are incompatible need another format version. Applications choose schemas and
perform data migrations explicitly; a schema file alone does not migrate records.
The public name is Josly Schema Language; new files use `.jsl`. The runtime can
read legacy `.shape` definitions with the same type syntax. Initialization
normalizes their extension to `.jsl`. Duplicate schema filenames are rejected.
