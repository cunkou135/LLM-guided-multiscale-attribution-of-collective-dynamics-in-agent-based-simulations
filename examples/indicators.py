"""Reviewed, illustrative post-processing functions; not causal estimators."""


def schelling_same_neighbor_fraction(data, config):
    """Fraction of occupied directed neighbor links joining same-kind agents."""
    group = data['agent_states'].groupby('step')[['same_neighbors', 'neighbors']].sum()
    return group.assign(same_fraction=group.same_neighbors / group.neighbors.replace(0, float('nan')))[['same_fraction']]


def deffuant_opinion_variance(data, config):
    """Population variance across agent opinions at each recorded step."""
    return data['agent_states'].groupby('step').opinion.var(ddof=0).to_frame('opinion_variance')
