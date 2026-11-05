"""Compare exact sampled states against the installed Mesa 3.5.2 example."""
import pytest
from mesa.examples.basic.schelling.model import Schelling as Official, SchellingScenario
from simulations.schelling.model import Schelling


@pytest.mark.parametrize('seed', [2, 42, 97])
def test_schelling_official_trajectory(seed):
    scenario = SchellingScenario(width=12, height=12, density=.75, minority_pc=.5, homophily=.4, radius=1, rng=seed)
    ref = Official(scenario=scenario)
    actual = Schelling(12, 12, .75, .5, .4, 1, False, seed)
    def states(model, official):
        return sorted((a.unique_id, a.cell.coordinate, a.type if official else a.kind, a.happy) for a in model.agents)
    assert states(actual, False) == states(ref, True)
    for _ in range(8):
        ref.step()
        actual.step()
        assert states(actual, False) == states(ref, True)
        assert actual.running == ref.running
