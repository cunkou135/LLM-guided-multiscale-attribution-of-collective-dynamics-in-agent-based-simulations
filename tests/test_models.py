import pytest
from simulations.schelling.model import Resident, Schelling


def test_schelling_invariants():
    m = Schelling(20, 20, .8, .5, .4, 1, False, 42)
    n = len(m.agents)
    for _ in range(5):
        m.step()
        assert len(m.agents) == n
        assert len({a.cell.coordinate for a in m.agents}) == n
        for a in m.agents:
            total, same, _ = a.counts()
            assert a.happy == ((same / total if total else 0) >= .4)



@pytest.mark.parametrize('torus,expected', [(True, 1), (False, 0)])
def test_schelling_boundary_and_isolated_satisfaction(torus, expected):
    model = Schelling(4, 4, 0, .5, .4, 1, torus, 1)
    a = Resident(model, model.grid[(0, 0)], 0)
    Resident(model, model.grid[(3, 0)], 0)
    a.assign_state()
    assert a.counts()[0] == expected
    assert a.happy == bool(expected)



def test_schelling_migration_and_satisfied_inaction():
    destinations = set()
    for seed in range(30):
        events = []
        model = Schelling(5, 5, 0, .5, .5, 1, False, seed, events.append)
        a = Resident(model, model.grid[(2, 2)], 0)
        a.assign_state()
        assert not a.happy
        model.step()
        event = events[0]
        assert event['moved'] and (event['x_after'], event['y_after']) != (2, 2)
        destinations.add((event['x_after'], event['y_after']))
    assert any(max(abs(x-2), abs(y-2)) > 1 for x, y in destinations)
    events = []
    model = Schelling(5, 5, 0, .5, 0, 1, False, 1, events.append)
    a = Resident(model, model.grid[(2, 2)], 0)
    a.assign_state()
    model.step()
    assert a.cell.coordinate == (2, 2) and not events[0]['moved']
