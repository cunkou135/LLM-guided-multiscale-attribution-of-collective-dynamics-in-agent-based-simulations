"""Run with the separate Covasim Python to check passive adapter equivalence.

Uses the public NC Figure 3A-C parameter setting (not historical calibration).
No reference source is copied; all dynamics come from native Covasim 2.0.0.
"""
import json
from pathlib import Path
import numpy as np
from simulations.covasim.adapter import CovasimAdapter, build_sim


def main():
    import argparse
    import covasim as cv
    parser = argparse.ArgumentParser()
    parser.add_argument('--reference-cache', help='Trusted publisher fig3_transtrees.obj only; pickle loading executes code')
    args = parser.parse_args()
    cached = cv.load(args.reference_cache)[1] if args.reference_cache else None
    outputs = []
    for policy in ('none', 'test', 'trace'):
        interventions = []
        if policy in ('test', 'trace'):
            interventions.append(dict(type='test_prob', start_day=20, symp_prob=.15,
                                      symp_quar_prob=1., asymp_quar_prob=1., quar_policy='start'))
        if policy == 'trace':
            interventions.append(dict(type='contact_tracing', start_day=20,
                                      trace_probs=dict(h=.7, s=.1, w=.1, c=0.)))
        config = dict(steps=126, seed=8, parameters=dict(pop_size=100, pop_type='hybrid', pop_infected=1,
                      iso_factor=dict(h=.3, s=0., w=0., c=.1),
                      quar_factor=dict(h=.8, s=0., w=0., c=.3), interventions=interventions))
        reference = build_sim(config)
        reference.initialize()
        expected = []
        for _ in range(config['steps']):
            reference.step()
            expected.append({key: reference.people[key].copy() for key in reference.people.meta.all_states})
        actual = CovasimAdapter(config)
        list(actual.events())
        for step in range(config['steps']):
            actual.step()
            # Invoke all observation pathways to detect accidental random draws.
            list(actual.states())
            list(actual.contacts())
            list(actual.events())
            actual.summary()
            for key, values in expected[step].items():
                np.testing.assert_equal(actual.sim.people[key], values)
        assert actual.sim.people.infection_log == reference.people.infection_log
        reference_comparison = None
        if cached is not None:
            published = cached[policy]
            np.testing.assert_equal(reference.people.infection_log, published.people.infection_log)
            for key in reference.people.meta.all_states:
                np.testing.assert_equal(reference.people[key], published.people[key])
            reference.finalize()
            keys = [key for key in reference.results if key.startswith(('n_', 'new_', 'cum_')) and key in published.results]
            for key in keys:
                np.testing.assert_allclose(reference.results[key].values, published.results[key].values, rtol=1e-7, atol=1e-7)
            reference_comparison = dict(cached_version_attribute=published.version, infection_log_exact=True,
                                        final_individual_fields_exact=True, result_series_compared=len(keys))
        outputs.append(dict(policy=policy, days=config['steps'], state_fields=len(expected[0]),
                            infections=len(reference.people.infection_log), final=actual.summary(),
                            published_cache_comparison=reference_comparison,
                            passive_adapter_matches_native=True))
    result = Path('results/covasim_engine_validation.json')
    result.parent.mkdir(exist_ok=True, parents=True)
    result.write_text(json.dumps(outputs, indent=2), encoding='utf-8')
    print(result)


if __name__ == '__main__':
    main()
