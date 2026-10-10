# Changelog

## 0.2.1 — 2026-10-10

First public GitHub release of Josly.

- Local `.vol/` workspaces containing portable `.jsl` schemas and JSON records.
- Josly Schema Language v1: primitive types, arrays, typed maps, optional fields,
  unions, literals and named type references.
- Validated insert/update operations using JSON Pointer paths, revision checks,
  atomic single-record writes and file locks.
- Filtered reads and field projections with explicit missing/null semantics.
- Schema-scoped ID generation without reservation or storage mutation.
- Local CLI help, schema validation, relations and machine-readable tool contracts.
- Readable schema tables and indented definitions with optional terminal colors;
  explicit JSON/raw formats retain original source text.

Requires Python 3.11+ on macOS/Linux. No runtime dependencies.
