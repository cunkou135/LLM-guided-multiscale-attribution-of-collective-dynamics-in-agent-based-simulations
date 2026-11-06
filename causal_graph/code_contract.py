"""Conservative static access checks; runtime projection enforces declared columns."""
import ast


def check_required(required, schema):
    errors = []
    tables = schema['tables']
    for table, fields in required.items():
        if table not in tables:
            errors.append(f'{table}: table absent from common data schema')
        else:
            missing = set(fields) - set(tables[table]['fields'])
            if missing:
                errors.append(f'{table}: fields absent from common data schema: {sorted(missing)}')
    return errors


def analyze_access(code, required, schema):
    tree = ast.parse(code)
    aliases = {}
    derived = set()
    used = {}
    dynamic = []

    def literal(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [node.value]
        if isinstance(node, (ast.List, ast.Tuple)):
            values = []
            for item in node.elts:
                value = literal(item)
                if not value:
                    return None
                values.extend(value)
            return values
        return None

    def table_of(node):
        if isinstance(node, ast.Name):
            return aliases.get(node.id)
        if isinstance(node, ast.Subscript):
            if isinstance(node.value, ast.Name) and node.value.id == 'data':
                names = literal(node.slice)
                return names[0] if names and len(names) == 1 else None
            return table_of(node.value)
        if isinstance(node, ast.Attribute):
            return table_of(node.value)
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name) and node.func.value.id == 'data' and node.func.attr == 'get' and node.args:
                    names = literal(node.args[0])
                    return names[0] if names and len(names) == 1 else None
                # Concatenations/joins can mix sources: leave as unresolved rather than invent provenance.
                if node.func.attr not in {'merge', 'join', 'agg', 'aggregate', 'apply', 'transform',
                    'pivot', 'pivot_table', 'unstack', 'stack', 'mean', 'sum', 'var', 'std',
                    'median', 'min', 'max', 'count', 'size', 'nunique', 'value_counts',
                    'rename', 'assign', 'to_frame', 'reset_index'}:
                    return table_of(node.func.value)
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            table = table_of(node.value)
            for target in node.targets:
                if isinstance(target, ast.Name) and table:
                    aliases[target.id] = table
                elif isinstance(target, ast.Subscript) and table_of(target.value):
                    for field in literal(target.slice) or []:
                        derived.add((table_of(target.value), field))
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript):
            if isinstance(node.value, ast.Name) and node.value.id == 'data':
                table = table_of(node)
                if table:
                    used.setdefault(table, set())
                else:
                    dynamic.append('dynamic data-table lookup')
                continue
            table = table_of(node.value)
            fields = literal(node.slice)
            if isinstance(node.value, ast.Attribute) and node.value.attr in {'loc', 'iloc'}:
                fields = literal(node.slice.elts[1]) if isinstance(node.slice, ast.Tuple) and len(node.slice.elts) > 1 and node.value.attr == 'loc' else None
            if table and fields and isinstance(node.ctx, ast.Load):
                used.setdefault(table, set()).update(f for f in fields if (table, f) not in derived)
            elif table and fields is None:
                dynamic.append(f'{table}: dynamic indexing or boolean/positional selection')
        if isinstance(node, ast.Attribute):
            table = table_of(node.value)
            if table and node.attr in schema['tables'].get(table, {}).get('fields', {}):
                used.setdefault(table, set()).add(node.attr)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            table = table_of(node.func.value)
            if table and node.func.attr in {'groupby', 'sort_values', 'set_index', 'dropna', 'drop_duplicates'}:
                fields = literal(node.args[0]) if node.args else None
                if fields:
                    used.setdefault(table, set()).update(f for f in fields if (table, f) not in derived)
    errors = check_required(required, schema)
    for table, fields in used.items():
        if table not in required:
            errors.append(f'Code accesses undeclared table: {table}')
        else:
            missing = fields - set(required[table])
            if missing:
                errors.append(f'{table}: code accesses undeclared fields: {sorted(missing)}')
    return {'errors': errors, 'statically_observed_access': {k: sorted(v) for k, v in used.items()},
            'unresolved_access': sorted(set(dynamic)),
            'runtime_enforcement': 'Only declared table columns are supplied; static analysis is conservative, not proof of semantic correctness.'}
