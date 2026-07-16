"""``--dry-run`` — hand-rolled structural validation, zero mutating calls.

A full JSON-Schema validator (the ``jsonschema`` package) is not worth a
new runtime dependency for schemas this flat. :func:`validate_body` checks
two things only:

- every key in ``schema["required"]`` is present in ``body``;
- for keys present in both, a rough type check of ``schema["properties"]``
  ``"type"`` (``string``/``integer``/``boolean``/``object``/``array``/
  ``null``) against the Python value's type, including the
  ``anyOf: [{type: X}, {type: "null"}]`` optional-field shape the live
  API's generated schemas use for optional fields.

Deliberately **not** implemented: ``pattern``/``format``/``enum``/
``minimum``/nested-object validation — the real API still fully validates
on any non-dry-run call, so an over-eager local validator would only give
a false sense of safety for constraints this module doesn't check.
"""

from __future__ import annotations

import json as jsonlib
from typing import Any

import typer

from . import openapi_client
from .errors import EXIT, CliError

_JSON_TYPE_TO_PY: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "object": dict,
    "array": list,
    "null": type(None),
}


def _allowed_types(prop_schema: dict[str, Any]) -> list[str]:
    """Collect the JSON-Schema ``type``(s) a property may take.

    Handles a bare ``"type": "X"``, and the ``anyOf: [{type: X}, {type:
    "null"}]`` shape the live API's generated schemas use for optional
    fields.

    Returns an **empty list** (= "don't shallow-check this field at all")
    whenever the property has a branch this module can't reduce to a
    literal type — a nested ``$ref`` (e.g. ``auth`` →
    ``ExternalMcpAuth``) or a bare ``{}`` "any" schema. Previously such a
    branch was silently dropped while sibling ``{type: "null"}`` branches
    were kept, so an optional-nested-object field like
    ``anyOf: [{$ref: ...}, {type: null}]`` collapsed to "must be null" and
    wrongly rejected a real dict body. Skipping matches this module's
    documented scope (rough type check only, no ``$ref`` resolution).
    """
    if "anyOf" in prop_schema:
        types: list[str] = []
        for branch in prop_schema["anyOf"]:
            if isinstance(branch, dict) and isinstance(branch.get("type"), str):
                types.append(branch["type"])
            else:
                # $ref / empty-schema / anything non-literal → the field
                # can hold a shape we can't validate shallowly; don't
                # constrain it to the remaining literal branches.
                return []
        return types
    if isinstance(prop_schema.get("type"), str):
        return [prop_schema["type"]]
    return []


def validate_body(schema: dict[str, Any], body: dict[str, Any]) -> list[str]:
    """Return human-readable validation errors; empty list means valid."""
    errors: list[str] = []
    required = schema.get("required", [])
    for key in required:
        if key not in body or body[key] is None:
            errors.append(f"missing required field: {key}")

    properties: dict[str, Any] = schema.get("properties", {})
    for key, value in body.items():
        prop_schema = properties.get(key)
        if not isinstance(prop_schema, dict):
            continue
        allowed = [t for t in _allowed_types(prop_schema) if t in _JSON_TYPE_TO_PY]
        if not allowed:
            continue
        py_types: tuple[type, ...] = ()
        for json_t in allowed:
            mapped = _JSON_TYPE_TO_PY[json_t]
            py_types += mapped if isinstance(mapped, tuple) else (mapped,)
        # `bool` is a subclass of `int`, so `isinstance(True, int)` is True.
        # Reject a bool where only integer/number is allowed — a JSON
        # `true`/`false` is not a valid number, and vice versa.
        if isinstance(value, bool) and "boolean" not in allowed:
            errors.append(
                f"field '{key}' expected type {'/'.join(allowed)}, got bool"
            )
            continue
        if not isinstance(value, py_types):
            errors.append(
                f"field '{key}' expected type {'/'.join(allowed)}, got {type(value).__name__}"
            )
    return errors


def run_dry_run(*, resource: str, verb: str, body: dict[str, Any]) -> None:
    """Fetch the matching schema, validate ``body``, print result, and exit.

    Called by a mutating command's ``--dry-run`` branch *before* it fires
    its real ``client.request(...)`` call. Always exits the process (0 for
    valid, 2 for invalid) — the caller never falls through to the real
    mutating call after this returns, because it never returns.
    """
    spec = openapi_client.fetch_openapi()
    match = openapi_client.resolve(spec, resource, verb)
    if match is None:
        # Route not found at all -- our hand-maintained ROUTES table has
        # drifted from the live API, or this (resource, verb) pair was
        # never wired up. Conservative fallback per the stuck-resource
        # policy: refuse rather than guess.
        raise CliError(EXIT.ERROR, "dry-run not supported for this command yet")

    body_schema = openapi_client.request_body_schema(spec, match["operation"])
    if body_schema is None:
        # The route exists but genuinely takes no request body (e.g.
        # `activate`/`pause`/`delete`/`sync`/`detach`) -- nothing to
        # validate, so the body is trivially valid.
        typer.echo(jsonlib.dumps({"valid": True, "body": body}, indent=2, default=str))
        raise typer.Exit(EXIT.OK)

    errors = validate_body(body_schema, body)
    if errors:
        typer.echo(jsonlib.dumps({"valid": False, "errors": errors}, indent=2), err=True)
        raise typer.Exit(EXIT.VALIDATION)

    typer.echo(jsonlib.dumps({"valid": True, "body": body}, indent=2, default=str))
    raise typer.Exit(EXIT.OK)
