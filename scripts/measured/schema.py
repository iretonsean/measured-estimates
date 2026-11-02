"""Schema versions, migrations and a small JSON-schema validator for the subset the files in schemas/ use (REQ-29)."""
from __future__ import annotations

import json
import os
import re

from . import SCHEMA_VERSION

SCHEMAS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'schemas')


def load_schema(name: str) -> dict:
    with open(os.path.join(SCHEMAS_DIR, f'{name}.schema.json'), encoding='utf-8') as f:
        return json.load(f)


def validate(value, schema: dict, path: str = '$') -> list:
    """Errors (strings) of `value` against `schema`. Supports type, enum, const, pattern, minimum, required,
    properties, additionalProperties (bool or schema), items, anyOf, maxLength."""
    errs = []
    t = schema.get('type')
    if t is not None:
        types = t if isinstance(t, list) else [t]
        ok = False
        for ty in types:
            if (ty == 'object' and isinstance(value, dict)) or (ty == 'array' and isinstance(value, list)) or \
               (ty == 'string' and isinstance(value, str)) or (ty == 'null' and value is None) or \
               (ty == 'boolean' and isinstance(value, bool)) or \
               (ty == 'integer' and isinstance(value, int) and not isinstance(value, bool)) or \
               (ty == 'number' and isinstance(value, (int, float)) and not isinstance(value, bool)):
                ok = True
        if not ok:
            return [f'{path}: expected {t}']
    if 'anyOf' in schema:
        if all(validate(value, s, path) for s in schema['anyOf']):
            errs.append(f'{path}: no anyOf branch matches')
    if 'enum' in schema and value not in schema['enum']:
        errs.append(f'{path}: not one of {schema["enum"]}')
    if 'const' in schema and value != schema['const']:
        errs.append(f'{path}: must be {schema["const"]}')
    if isinstance(value, str):
        if 'pattern' in schema and not re.fullmatch(schema['pattern'], value):
            errs.append(f'{path}: does not match {schema["pattern"]}')
        if 'maxLength' in schema and len(value) > schema['maxLength']:
            errs.append(f'{path}: longer than {schema["maxLength"]}')
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 'minimum' in schema and value < schema['minimum']:
        errs.append(f'{path}: below {schema["minimum"]}')
    if isinstance(value, dict):
        for k in schema.get('required', []):
            if k not in value:
                errs.append(f'{path}: missing {k}')
        props = schema.get('properties', {})
        addl = schema.get('additionalProperties', True)
        pprops = schema.get('patternProperties', {})
        for k, v in value.items():
            if k in props:
                errs += validate(v, props[k], f'{path}.{k}')
                continue
            pm = [s for p, s in pprops.items() if re.fullmatch(p, k)]
            if pm:
                errs += validate(v, pm[0], f'{path}.{k}')
            elif addl is False:
                errs.append(f'{path}: extra key {k}')
            elif isinstance(addl, dict):
                errs += validate(v, addl, f'{path}.{k}')
    if isinstance(value, list) and 'items' in schema:
        for i, v in enumerate(value):
            errs += validate(v, schema['items'], f'{path}[{i}]')
    return errs


def migrate_ledger_line(d: dict) -> dict | None:
    """Version 0 (no schema_version; `fresh_m` in millions) -> 1. Newer than known: returned as is (read only)."""
    v = int(d.get('schema_version') or 0)
    if v == 0:
        d = dict(d)
        if 'fresh_tokens' not in d and isinstance(d.get('fresh_m'), (int, float)):
            d['fresh_tokens'] = int(round(d.pop('fresh_m') * 1_000_000))
        d.setdefault('tasks', {})
        d.setdefault('untied', {})
        d['schema_version'] = SCHEMA_VERSION
    return d
