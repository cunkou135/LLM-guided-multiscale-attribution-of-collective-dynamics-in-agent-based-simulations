"""Well-mixed symmetric bounded-confidence model."""
from mesa import Agent, Model


class Person(Agent):
    def __init__(self, model, opinion):
        super().__init__(model)
        self.opinion = opinion


class Deffuant(Model):
    def __init__(self, population, epsilon, mu, interactions_per_step, seed, event=None, initial_distribution='uniform_0_1'):
        super().__init__(rng=seed)
        if initial_distribution != 'uniform_0_1':
            raise ValueError('Only uniform_0_1 is supported')
        self.epsilon, self.mu = epsilon, mu
        self.interactions_per_step = interactions_per_step
        self.event = event or (lambda row: None)
        for _ in range(population):
            Person(self, self.random.random())

    def step(self):
        for _ in range(self.interactions_per_step):
            a, b = self.random.sample(list(self.agents), 2)
            x, y = a.opinion, b.opinion
            accepted = abs(x - y) < self.epsilon
            if accepted:
                a.opinion = x + self.mu * (y - x)
                b.opinion = y + self.mu * (x - y)
            self.event(dict(agent_id=a.unique_id, partner_id=b.unique_id, event_type="pair", opinion_before=x, partner_opinion_before=y, opinion_after=a.opinion, partner_opinion_after=b.opinion, difference=abs(x-y), epsilon=self.epsilon, mu=self.mu, accepted=accepted, delta=a.opinion-x, partner_delta=b.opinion-y, reason="within_bound" if accepted else "outside_bound"))

    def states(self):
        return (dict(agent_id=a.unique_id, event_type="state", opinion=a.opinion) for a in self.agents)

    def summary(self):
        x = [a.opinion for a in self.agents]
        return dict(population=len(x), mean_opinion=sum(x)/len(x), min_opinion=min(x), max_opinion=max(x))
