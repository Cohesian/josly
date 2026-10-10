# Josly workspace

You maintain Josly, a generic Python library and CLI for typed local JSON data.

## Responsibilities

- `jsl.py`: parse and validate Josly Schema Language v1 (`.jsl`).
- `query.py`: filter, project and validate property patches.
- `storage.py`: IDs, JSON envelopes, confined paths, atomic writes and locks.
- `volume.py`: explicit initialization and confined configuration paths.
- `cli.py`: local help; init/schemas/query/generate; explicit JSON machine output.
- `display.py`: readable schema tables/definitions and optional terminal colors.
- `catalog.py`: describe tools and actual declared type references.
- Keep the format contract in `docs/jsl-v1.md` and usage in `README.md`.

## Rules

Keep all domain policy outside this package. Schema/collection names are generic;
no professional, trade, provider, capture, analysis or ranking special cases.
Applications supply schemas and may extend Registry/Queries/JsonAdapter with policy.

Validate paths, values and the complete result before committing. Existing records
require the current revision, rechecked under a lock. Insert requires absence,
update presence. Preserve null versus missing and bool versus number. Never eval
schema or filter text. Reads and ID generation must not create storage state.
Schema views must not rewrite definitions or discard source metadata. Preserve the
original text in JSON/raw output. Pretty views may reindent it without changing
types, comments or literals. Default colors require a terminal and respect NO_COLOR;
explicit JSON/text formats must stay free of terminal formatting.

Generate IDs for loaded schema roots without registration or reservation.
init alone may create volume state; bare help must never mutate it. JSON values use string object
keys and finite numbers. Keep arrays explicit: existing-index update or append at
length. Document limits; do not invent transactions, indexes or domain guarantees.

Use the local `pyproject.toml`; standard-library runtime, Python 3.11+. Tests use
fictional schemas and temporary stores. Do not package live data or sibling apps.
Do not install globally, publish, browse or contact anyone as an implicit side effect.
