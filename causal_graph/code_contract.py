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

    class AccessVisitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node):
            saved_aliases, saved_derived = aliases.copy(), derived.copy()
            # Helpers have local names; nested functions may capture outer frames.
            for arg in node.args.args:
                aliases.pop(arg.arg, None)
            for statement in node.body:
                self.visit(statement)
            aliases.clear(); aliases.update(saved_aliases)
            derived.clear(); derived.update(saved_derived)

        def visit_Assign(self, node):
            # Read the RHS with the current bindings before replacing a local name.
            self.visit(node.value)
            table = table_of(node.value)
            for target in node.targets:
                if isinstance(target, ast.Name):
                    if table:
                        aliases[target.id] = table
                    elif target.id in aliases:
                        aliases.pop(target.id)
                        dynamic.append(f'{target.id}: transformed/mixed frame; runtime projection required')
                elif isinstance(target, ast.Subscript):
                    self.visit(target.value)
                    for field in literal(target.slice) or []:
                        source = table_of(target.value)
                        if source:
                            derived.add((source, field))

        def visit_AnnAssign(self, node):
            if node.value is not None:
                self.visit_Assign(ast.Assign(targets=[node.target], value=node.value))

        def visit_AugAssign(self, node):
            if isinstance(node.target, ast.Subscript):
                table = table_of(node.target.value)
                if table:
                    used.setdefault(table, set()).update(literal(node.target.slice) or [])
            self.generic_visit(node)

        def visit_Subscript(self, node):
            if isinstance(node.value, ast.Name) and node.value.id == 'data':
                table = table_of(node)
                if table:
                    used.setdefault(table, set())
                else:
                    dynamic.append('dynamic data-table lookup')
            else:
                table = table_of(node.value)
                fields = literal(node.slice)
                if isinstance(node.value, ast.Attribute) and node.value.attr in {'loc', 'iloc'}:
                    fields = literal(node.slice.elts[1]) if isinstance(node.slice, ast.Tuple) and len(node.slice.elts) > 1 and node.value.attr == 'loc' else None
                if table and fields and isinstance(node.ctx, ast.Load):
                    used.setdefault(table, set()).update(f for f in fields if (table, f) not in derived)
                elif table and fields is None:
                    dynamic.append(f'{table}: dynamic indexing or boolean/positional selection')
            self.generic_visit(node)

        def visit_Attribute(self, node):
            table = table_of(node.value)
            if table and node.attr in schema['tables'].get(table, {}).get('fields', {}):
                used.setdefault(table, set()).add(node.attr)
            self.generic_visit(node)

        def visit_Call(self, node):
            if isinstance(node.func, ast.Attribute):
                table = table_of(node.func.value)
                if table and node.func.attr in {'groupby', 'sort_values', 'set_index', 'dropna', 'drop_duplicates'}:
                    fields = literal(node.args[0]) if node.args else None
                    for keyword in node.keywords:
                        if keyword.arg in {'by', 'keys', 'subset'}:
                            fields = literal(keyword.value)
                    if fields:
                        used.setdefault(table, set()).update(f for f in fields if (table, f) not in derived)
            self.generic_visit(node)

    AccessVisitor().visit(tree)
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
