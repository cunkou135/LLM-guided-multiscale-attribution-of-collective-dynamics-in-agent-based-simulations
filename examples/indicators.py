"""Reviewed, illustrative post-processing functions; not causal estimators."""


def schelling_same_neighbor_fraction(data, config):
    """Fraction of occupied directed neighbor links joining same-kind agents."""
    group = data['agent_states'].groupby('step')[['same_neighbors', 'neighbors']].sum()
    return group.assign(same_fraction=group.same_neighbors / group.neighbors.replace(0, float('nan')))[['same_fraction']]


def covasim_infectious_fraction(data, config):
    """Fraction of simulated people who are infectious at recorded steps."""
    return data['agent_states'].groupby('step').infectious.mean().to_frame('infectious_fraction')
