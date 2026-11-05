"""Schelling dynamics corresponding to Mesa 3.5.2's example."""
from mesa import Model
from mesa.discrete_space import CellAgent, OrthogonalMooreGrid


class Resident(CellAgent):
    def __init__(self, model, cell, kind):
        super().__init__(model)
        self.cell = cell
        self.kind = kind
        self.happy = False

    def counts(self):
        neighbors = list(self.cell.get_neighborhood(radius=self.model.radius).agents)
        same = sum(a.kind == self.kind for a in neighbors)
        return len(neighbors), same, len(neighbors) - same

    def assign_state(self):
        total, same, _ = self.counts()
        self.happy = (same / total if total else 0.0) >= self.model.homophily

    def step(self):
        before = self.cell.coordinate
        n, same, other = self.counts()
        was_happy = self.happy
        if not was_happy:
            self.cell = self.model.grid.select_random_empty_cell()
        after = self.cell.coordinate
        n2, same2, other2 = self.counts()
        self.model.event(dict(agent_id=self.unique_id, kind=self.kind, event_type="activation", x_before=before[0], y_before=before[1], x_after=after[0], y_after=after[1], neighbors=n, same_neighbors=same, other_neighbors=other, neighbors_after=n2, same_neighbors_after=same2, other_neighbors_after=other2, happy_before=was_happy, happy_after=self.happy, moved=not was_happy, reason="satisfied" if was_happy else "unsatisfied"))


class Schelling(Model):
    def __init__(self, width, height, density, minority_pc, homophily, radius, torus, seed, event=None):
        super().__init__(rng=seed)
        self.homophily, self.radius = homophily, radius
        self.event = event or (lambda row: None)
        self.grid = OrthogonalMooreGrid((width, height), torus=torus, random=self.random, capacity=1)
        for cell in self.grid.all_cells:
            if self.random.random() < density:
                Resident(self, cell, 1 if self.random.random() < minority_pc else 0)
        self.agents.do("assign_state")
        self.running = True

    def step(self):
        self.agents.shuffle_do("step")
        self.agents.do("assign_state")
        self.running = any(not a.happy for a in self.agents)

    def states(self):
        for a in self.agents:
            n, same, other = a.counts()
            yield dict(agent_id=a.unique_id, event_type="state", kind=a.kind, x=a.cell.coordinate[0], y=a.cell.coordinate[1], neighbors=n, same_neighbors=same, other_neighbors=other, happy=a.happy)

    def summary(self):
        states = list(self.states())
        return dict(population=len(states), happy=sum(s['happy'] for s in states), same_neighbors=sum(s['same_neighbors'] for s in states), neighbors=sum(s['neighbors'] for s in states))
