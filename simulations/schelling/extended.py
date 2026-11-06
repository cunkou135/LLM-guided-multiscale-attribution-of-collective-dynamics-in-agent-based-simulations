"""Study-specific Schelling extension; the standard Mesa rule remains separate."""
import numpy as np
from mesa import Model
from mesa.discrete_space import OrthogonalMooreGrid
from simulations.schelling.model import Resident


class ExtendedResident(Resident):
    def __init__(self, model, cell, kind, theta):
        super().__init__(model, cell, kind)
        self.theta = theta

    def counts(self):
        x, y = self.cell.coordinate
        same = int(self.model.neighbor_counts[self.kind, x, y])
        other = int(self.model.neighbor_counts[1-self.kind, x, y])
        return same + other, same, other

    def assign_state(self):
        n, same, _ = self.counts()
        self.happy = (same / n if n else 0.) >= self.theta

    def step(self):
        model = self.model
        before = self.cell.coordinate
        n, same, other = self.counts()
        ratio = same / n if n else 0.
        happy_before = ratio >= self.theta
        target, candidates, feasible = None, 0, 0
        reason = 'satisfied'
        if not happy_before:
            target, candidates, feasible, reason = model.destination(self, ratio)
        if target is not None:
            model.relocate(self, target)
            model.moves += 1
        after = self.cell.coordinate
        n2, same2, other2 = self.counts()
        ratio2 = same2 / n2 if n2 else 0.
        self.happy = ratio2 >= self.theta
        model.event(dict(agent_id=self.unique_id, kind=self.kind, theta_i=self.theta,
                         event_type='activation', x_before=before[0], y_before=before[1],
                         x_after=after[0], y_after=after[1], neighbors=n, same_neighbors=same,
                         other_neighbors=other, neighbors_after=n2, same_neighbors_after=same2,
                         other_neighbors_after=other2, happy_before=happy_before, happy_after=self.happy,
                         moved=target is not None, attempted=not happy_before,
                         candidate_count=candidates, feasible_count=feasible,
                         similarity_before=ratio, similarity_after=ratio2, reason=reason))


class ExtendedSchelling(Model):
    def __init__(self, width, height, density, minority_pc, radius, torus, seed,
                 homophily_mean, homophily_std, homophily_min, homophily_max,
                 relocation_radius, relocation_policy, event=None):
        super().__init__(rng=seed)
        if relocation_policy != 'best_local_satisfactory':
            raise ValueError('Unsupported relocation policy')
        self.width, self.height = width, height
        self.radius, self.torus = radius, torus
        self.relocation_radius = relocation_radius
        self.event = event or (lambda row: None)
        self.grid = OrthogonalMooreGrid((width, height), torus=torus, capacity=1, random=self.random)
        self.occupancy = np.full((width, height), -1, dtype=np.int8)
        self.neighbor_counts = np.zeros((2, width, height), dtype=np.int16)
        self._coordinate_cache = {}
        for cell in self.grid.all_cells:
            if self.random.random() < density:
                kind = 1 if self.random.random() < minority_pc else 0
                theta = homophily_mean
                if homophily_std:
                    while True:
                        theta = self.random.gauss(homophily_mean, homophily_std)
                        if homophily_min <= theta <= homophily_max:
                            break
                elif not homophily_min <= theta <= homophily_max:
                    raise ValueError('Zero-variance preference must lie within bounds')
                ExtendedResident(self, cell, kind, theta)
                self.occupancy[cell.coordinate] = kind
                self._change_counts(cell.coordinate, kind, 1)
        self.agents.do('assign_state')
        self.moves = 0
        self.stop_reason = None

    def local_coordinates(self, x, y, radius, include_center=False):
        key = (x, y, radius, include_center)
        if key in self._coordinate_cache:
            return self._coordinate_cache[key]
        points = set()
        for a in range(x-radius, x+radius+1):
            for b in range(y-radius, y+radius+1):
                if self.torus:
                    points.add((a % self.width, b % self.height))
                elif 0 <= a < self.width and 0 <= b < self.height:
                    points.add((a, b))
        if not include_center:
            points.discard((x, y))
        array = np.asarray(sorted(points), dtype=np.intp).reshape(-1, 2)
        self._coordinate_cache[key] = (array[:, 0], array[:, 1])
        return self._coordinate_cache[key]

    def _change_counts(self, position, kind, delta):
        xs, ys = self.local_coordinates(*position, self.radius)
        self.neighbor_counts[kind, xs, ys] += delta

    def destination(self, agent, current_similarity):
        x, y = agent.cell.coordinate
        xs, ys = self.local_coordinates(x, y, self.relocation_radius)
        empty = self.occupancy[xs, ys] == -1
        xs, ys = xs[empty], ys[empty]
        count = len(xs)
        if not count:
            return None, 0, 0, 'no_local_vacancy'
        same = self.neighbor_counts[agent.kind, xs, ys].astype(np.int32)
        total = self.neighbor_counts[:, xs, ys].sum(axis=0, dtype=np.int32)
        dx, dy = np.abs(xs-x), np.abs(ys-y)
        if self.torus:
            dx, dy = np.minimum(dx, self.width-dx), np.minimum(dy, self.height-dy)
        # Evaluate after vacating the original home, before occupying the target.
        origin_is_neighbor = np.maximum(dx, dy) <= self.radius
        same -= origin_is_neighbor
        total -= origin_is_neighbor
        similarity = np.divide(same, total, out=np.zeros(count, dtype=float), where=total > 0)
        feasible = similarity >= agent.theta
        reason = 'local_satisfactory'
        if not feasible.any():
            feasible = similarity > current_similarity
            reason = 'local_improvement'
        n_feasible = int(feasible.sum())
        if not n_feasible:
            return None, count, 0, 'no_satisfactory_or_improving_location'
        best = similarity[feasible].max()
        ties = np.flatnonzero(feasible & (similarity == best)).tolist()
        index = self.random.choice(ties)
        return (int(xs[index]), int(ys[index])), count, n_feasible, reason

    def relocate(self, agent, target):
        origin = agent.cell.coordinate
        self._change_counts(origin, agent.kind, -1)
        self.occupancy[origin] = -1
        agent.cell = self.grid[target]
        self.occupancy[target] = agent.kind
        self._change_counts(target, agent.kind, 1)

    def step(self):
        self.moves = 0
        self.agents.shuffle_do('step')
        self.agents.do('assign_state')
        if all(a.happy for a in self.agents):
            self.stop_reason = 'stable'
        elif self.moves == 0:
            # Every unhappy resident exhaustively evaluated all local vacancies.
            # No move means the configuration was constant throughout the sweep.
            self.stop_reason = 'frozen'
        self.running = self.stop_reason is None

    def states(self):
        for a in self.agents:
            n, same, other = a.counts()
            x, y = a.cell.coordinate
            yield dict(agent_id=a.unique_id, event_type='state', kind=a.kind, theta_i=a.theta,
                       x=x, y=y, neighbors=n, same_neighbors=same, other_neighbors=other, happy=a.happy)

    def summary(self):
        return dict(population=len(self.agents), happy=sum(a.happy for a in self.agents),
                    same_neighbors=sum(a.counts()[1] for a in self.agents),
                    neighbors=sum(a.counts()[0] for a in self.agents), moves=self.moves)
