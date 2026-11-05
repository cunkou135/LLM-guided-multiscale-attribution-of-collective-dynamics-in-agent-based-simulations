import pytest
from simulations.deffuant.model import Deffuant
from simulations.schelling.model import Resident, Schelling


def test_deffuant_events():
    events = []
    m = Deffuant(30, 0.2, 0.5, 500, 12, events.append)
    m.step()
    assert len(events) == 500
    for e in events:
        assert e['agent_id'] != e['partner_id']
        assert e['accepted'] == (e['difference'] < e['epsilon'])
        assert e['opinion_before'] + e['partner_opinion_before'] == pytest.approx(e['opinion_after'] + e['partner_opinion_after'])
        if not e['accepted']:
            assert e['opinion_before'] == e['opinion_after']
        else:
            assert e['opinion_after'] == pytest.approx(e['opinion_before'] + e['mu'] * (e['partner_opinion_before'] - e['opinion_before']))
            assert e['partner_opinion_after'] == pytest.approx(e['partner_opinion_before'] + e['mu'] * (e['opinion_before'] - e['partner_opinion_before']))
    assert all(0 <= a.opinion <= 1 for a in m.agents)


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


def test_deffuant_confidence_boundary_and_simultaneous_update():
    events = []
    m = Deffuant(2, .25, .5, 1, 5, events.append)
    a, b = list(m.agents)
    a.opinion, b.opinion = .25, .5
    m.step()
    assert not events[-1]['accepted'] and (a.opinion, b.opinion) == (.25, .5)
    b.opinion = .375
    m.step()
    assert events[-1]['accepted'] and a.opinion == b.opinion == .3125


def test_random_pairs_are_distinct_and_cover_complete_population():
    events = []
    m = Deffuant(8, .2, .3, 3000, 123, events.append)
    m.step()
    pairs = {tuple(sorted((e['agent_id'], e['partner_id']))) for e in events}
    assert len(pairs) == 28


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
