# Nexsets & transforms

Paths relative to `${EXPRESS_PUBLIC_API_BASE}/nexla`.

- `GET /nexsets?flow_id=&parent_id=&…`
- `GET /nexsets/{id}` — includes `samples` (top 5) and `output_schema`.
- `POST /transforms/test` — dry-run a transform against sample input before committing. Body: `{language: "python"|"sql", code, options?, input: [...records], parent_nexset_id?}`. Iterate here first.
- `POST /nexsets/{parent_id}/transform` — derive a child nexset. Body: `{name, language, code, options?, auto_activate?}`. The platform infers schema — **don't** pass schema or samples.

## Python transforms (Jython 2.7)

Run per-record: `def transform(input, metadata, args): ...`. Nexla executes Python on the JVM, so **use Jython 2.7 syntax**:

- No f-strings — use `"%s" % x` or `"{}".format(x)`.
- `print` is a statement (or `from __future__ import print_function`).
- No type hints, walrus, or match statements.
- Stdlib is the JVM-shimmed subset: `re`, `json`, `datetime`, `math`, `string` work; native C extensions (numpy, pandas, requests) do **not**.
- Tolerate both `str` and `unicode`; prefer `.decode("utf-8")` for bytes.
- JSON arrays can arrive as JVM-backed/list-like values, so `isinstance(value, list)` can be false even when `len(value)` and iteration work. For array fields, prefer `try: count = len(value)` or iterate in a `try/except` block instead of requiring a native Python `list`.

```bash
curl -s -X POST "$API/nexsets/$NEXSET_ID/transform" "${H[@]}" -d '{
  "name": "Customers (uppercased)", "language": "python",
  "code": "def transform(input, metadata, args):\n    o = input.copy()\n    ln = o.get(\"last_name\")\n    if isinstance(ln, basestring): o[\"last_name\"] = ln.upper()\n    return o"
}'
```

## SQL transforms (Flink SQL)

Reference the parent as `{nexset_this}`. Use `options: {aggregation_window: "default"}` for aggregations.

```bash
curl -s -X POST "$API/nexsets/$NEXSET_ID/transform" "${H[@]}" -d '{
  "name": "Counts by country", "language": "sql",
  "code": "SELECT country, COUNT(*) AS n FROM {nexset_this} GROUP BY country",
  "options": {"aggregation_window": "default"}
}'
```

Transforms chain — a flow's DAG can have multiple transform steps and branches.
