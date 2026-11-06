"""Artificial interface fixtures, NOT LLM results or scientific hypotheses.

These definitions deliberately use generic numeric-column aggregations. Their edges
only exercise shape/path validation, and carry no mechanistic interpretation.
"""
import json

from causal_graph.io import save_json


def fixture_outputs(field='agent_id', failing=False):
    phenomena = [{'phenomenon_id': 'test_E', 'name': 'OFFLINE INTERFACE TEST ONLY',
                  'description': 'Artificial test double; not a model-generated scientific phenomenon.'}]
    indicators, codes = [], []
    for iid, scale, aggregation in [('test_a', 'micro', 'mean'), ('test_b', 'meso', 'var'), ('test_c', 'macro', 'sum')]:
        indicators.append({'indicator_id': iid, 'phenomenon_id': 'test_E', 'name': f'Test-only {aggregation}',
                           'scale': scale, 'description': f'Interface-test {aggregation} of raw {field}.',
                           'mathematical_definition': f'{aggregation}({field}_i(t)) over recorded agents at step t',
                           'units': 'test units', 'computation_notes': 'No scientific scale interpretation; fixture only.'})
        codes.append({'indicator_id': iid, 'required': {'agent_states': ['step', field]}, 'config': {},
                      'python_code': 'def compute_indicator(data, config):\n'
                      f"    return data['agent_states'].groupby('step')['{field}'].{aggregation}()\n"})
    edges = [{'edge_id': 'test_ab', 'source': 'test_a', 'target': 'test_b', 'relation_type': 'semantic_candidate',
              'semantic_rationale': 'Artificial structural fixture, no scientific claim.'},
             {'edge_id': 'test_bc', 'source': 'test_b', 'target': 'test_c', 'relation_type': 'semantic_candidate',
              'semantic_rationale': 'Artificial structural fixture, no scientific claim.'}]
    if failing:
        indicators.append({**indicators[0], 'indicator_id': 'test_missing', 'name': 'Intentionally unavailable test variable'})
        codes.append({'indicator_id': 'test_missing', 'required': {'agent_states': ['step', 'intentionally_absent']},
                      'config': {}, 'python_code': "def compute_indicator(data, config):\n    return data['agent_states'].groupby('step')['intentionally_absent'].mean()\n"})
        edges.append({**edges[0], 'edge_id': 'test_missing_b', 'source': 'test_missing'})
    return {'phenomena': {'phenomena': phenomena}, 'indicators': {'indicators': indicators},
            'codes': {'codes': codes}, 'edges': {'edges': edges}}


class OfflineClient:
    mode = 'offline_fixture_not_model_generated'

    def __init__(self, outputs=None):
        self.outputs = outputs or fixture_outputs()
        self.calls = []

    def complete(self, messages, directory):
        directory.mkdir(parents=True, exist_ok=False)
        user = json.loads(messages[1]['content'])
        stage = next(iter(user['output_schema']['properties']))
        self.calls.append((stage, messages))
        save_json(directory / 'request.json', {'messages': messages, 'fixture_only': True})
        raw = json.dumps(self.outputs[stage], ensure_ascii=False)
        (directory / 'response.txt').write_text(raw, encoding='utf-8')
        save_json(directory / 'response_metadata.json', {'actual_model': None, 'usage': None,
                                                       'fixture_only': True, 'client_mode': self.mode})
        return raw
