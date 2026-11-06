import numpy as np
import pytest
from simulations.schelling.extended import ExtendedSchelling


def create(seed=4, torus=False, **overrides):
    params = dict(width=12, height=12, density=.85, minority_pc=.5, radius=1,
                  torus=torus, seed=seed, homophily_mean=.45, homophily_std=.1,
                  homophily_min=0., homophily_max=1., relocation_radius=3,
                  relocation_policy='best_local_satisfactory')
    params.update(overrides)
    return ExtendedSchelling(**params)


def check_native_counts(model):
    for agent in model.agents:
        neighbors = list(agent.cell.get_neighborhood(radius=model.radius).agents)
        same = sum(n.kind == agent.kind for n in neighbors)
        assert agent.counts() == (len(neighbors), same, len(neighbors)-same)


@pytest.mark.parametrize('torus', [False, True])
def test_conservation_preference_and_incremental_counts(torus):
    events = []
    model = create(torus=torus, event=events.append)
    initial = {a.unique_id: a.theta for a in model.agents}
    for _ in range(5):
        check_native_counts(model)
        model.step()
        assert len(model.agents) == len(initial)
        assert len({a.cell.coordinate for a in model.agents}) == len(initial)
        assert {a.unique_id: a.theta for a in model.agents} == initial
        if not model.running:
            break
    check_native_counts(model)
    for e in events:
        dx, dy = abs(e['x_after']-e['x_before']), abs(e['y_after']-e['y_before'])
        if torus:
            dx, dy = min(dx, model.width-dx), min(dy, model.height-dy)
        assert max(dx, dy) <= model.relocation_radius
        if e['reason'] == 'local_improvement':
            assert e['similarity_after'] > e['similarity_before']
        elif e['reason'] == 'local_satisfactory':
            assert e['similarity_after'] >= e['theta_i']


def test_target_matches_brute_force_after_origin_vacated():
    model = create()
    for agent in model.agents:
        n, same, _ = agent.counts()
        current = same/n if n else 0
        if current >= agent.theta:
            continue
        scores = {}
        for cell in model.grid.all_cells:
            x, y = cell.coordinate
            sx, sy = agent.cell.coordinate
            if not cell.is_empty or max(abs(x-sx), abs(y-sy)) > model.relocation_radius:
                continue
            neighbors = [a for a in cell.get_neighborhood(radius=1).agents if a is not agent]
            scores[cell.coordinate] = sum(a.kind == agent.kind for a in neighbors)/len(neighbors) if neighbors else 0.
        eligible = {p: s for p, s in scores.items() if s >= agent.theta}
        if not eligible:
            eligible = {p: s for p, s in scores.items() if s > current}
        target, count, feasible, _ = model.destination(agent, current)
        assert count == len(scores) and feasible == len(eligible)
        if eligible:
            assert target in eligible and eligible[target] == max(eligible.values())
        else:
            assert target is None


def test_repeatability_and_truncated_sampling():
    a, b = create(homophily_mean=.1, homophily_std=.3), create(homophily_mean=.1, homophily_std=.3)
    assert list(a.states()) == list(b.states())
    theta = np.array([p.theta for p in a.agents])
    assert ((theta > 0) & (theta < 1)).all()
    for _ in range(3):
        a.step(); b.step()
        assert list(a.states()) == list(b.states())


def test_exhaustively_blocked_is_frozen_not_stable():
    events = []
    model = create(density=1., homophily_mean=1., homophily_std=0., event=events.append)
    model.step()
    assert not model.running and model.stop_reason == 'frozen'
    assert not all(a.happy for a in model.agents)
    assert any(e['reason'] == 'no_local_vacancy' for e in events)


def test_formal_grid_initialization():
    model = create(width=100, height=100, relocation_radius=8)
    assert len(model.grid.all_cells) == 10000
    assert len(model.agents) == int((model.occupancy >= 0).sum())
    assert all(0 <= a.theta <= 1 for a in model.agents)
