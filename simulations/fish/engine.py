"""Synchronous simple fish rules. No metrics, graph, storage or UI imports."""
from __future__ import annotations
import copy
import numpy as np
import mesa
from scipy.spatial import cKDTree


def unit(v):
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-12)


def angle(x):
    return (x + np.pi) % (2 * np.pi) - np.pi


def speeds(rng, mean, std, n):
    """Arithmetic mean/std, converted to the underlying normal distribution."""
    variance = np.log1p((std / mean) ** 2)
    return rng.lognormal(np.log(mean) - variance / 2, np.sqrt(variance), n)


class Individual(mesa.Agent):
    def __init__(self, model, position, heading):
        super().__init__(model)
        self.position = np.array(position, dtype=float)
        self.heading = float(heading)


class FishModel(mesa.Model):
    protocol_version = "fish-3.0"

    def __init__(self, settings):
        super().__init__(rng=settings['simulation']['seed'])
        self.settings = copy.deepcopy(settings)
        self.mode, self.elapsed, self.epoch, self.captured = 'fish', 0., 1, 0
        p, f = settings['population'], settings['fish']
        n = p['count']
        if p['distribution'] == 'disk':
            theta = self.rng.uniform(-np.pi, np.pi, n)
            radius = p['spawn_radius'] * np.sqrt(self.rng.random(n))
            xy = np.c_[radius * np.cos(theta), radius * np.sin(theta)]
        else:
            xy = self.rng.uniform(-p['spawn_radius'], p['spawn_radius'], (n, 2))
        xy += [p['spawn_x'], p['spawn_y']]
        headings = np.deg2rad(p['initial_heading_deg'] + self.rng.uniform(-p['heading_spread_deg'], p['heading_spread_deg'], n))
        self.flock = [Individual(self, x, h) for x, h in zip(xy, headings)]
        pc = settings['predator']
        az = np.deg2rad(pc['spawn_angle_deg']) + np.linspace(-.65, .65, f['N_p'])
        self.predators = [Individual(self, self.center() + pc['spawn_distance'] * np.array([np.cos(a), np.sin(a)]), a + np.pi) for a in az]
        self.remaining = np.zeros(n, dtype=int)
        self.source = np.zeros(n, dtype=int)
        self.escape = np.c_[np.cos(headings), np.sin(headings)]
        self.targets = np.full(len(self.predators), -1, dtype=int)
        self.velocity = np.zeros((n, 2))
        self.decisions = {k: [0] * n for k in ['d','s','r','o','kappa','trigger_d','trigger_s','remaining']}
        self.decisions['phi'] = [None] * n
        self.shark_decisions = {'h': [0]*len(self.predators), 'z': [0]*len(self.predators), 'target': self.targets.tolist()}
        self.contacts = []
        self.last_input = None

    def center(self):
        return np.mean([a.position for a in self.flock], axis=0)

    def apply_settings(self, settings):
        self.settings = copy.deepcopy(settings)

    def step(self):
        cfg, f = self.settings, self.settings['fish']
        dt = cfg['simulation']['dt']
        x = np.array([a.position for a in self.flock])
        theta = np.array([a.heading for a in self.flock])
        heads = np.c_[np.cos(theta), np.sin(theta)]
        sharks = np.array([p.position for p in self.predators]).reshape(-1, 2)
        n = len(x)
        pairs = cKDTree(x).query_pairs(f['R_s'], output_type='ndarray')
        i = np.r_[pairs[:, 0], pairs[:, 1]]
        j = np.r_[pairs[:, 1], pairs[:, 0]]
        delta = x[j] - x[i]
        dist = np.linalg.norm(delta, axis=1)
        rep = dist < f['r_r']
        ali = (dist >= f['r_r']) & (dist < f['r_a'])
        att = dist >= f['r_a']
        def summed(v, mask):
            keys,values=i[mask],v[mask]
            return np.column_stack([np.bincount(keys,weights=values[:,axis],minlength=n) for axis in range(2)])
        counts = np.bincount(i, minlength=n)
        rep_counts = np.bincount(i[rep], minlength=n)
        directions=unit(delta)
        social = unit(summed(heads[j], ali)) + unit(summed(directions, att))
        repel = -summed(directions, rep)
        social[rep_counts > 0] = repel[rep_counts > 0]
        absent = np.linalg.norm(social, axis=1) < 1e-12
        social[absent] = heads[absent]
        social = unit(social)
        # Read only preceding-step fright states. An expiring episode is not reset.
        old_source = self.source.copy()
        old_active = self.remaining > 0
        nearest = np.full(n, -1, dtype=int)
        direct = np.zeros(n, dtype=bool)
        if len(sharks):
            distances = np.linalg.norm(x[:, None] - sharks, axis=2)
            nearest = distances.argmin(axis=1)
            direct = distances[np.arange(n), nearest] <= f['R_p']
        contact = (dist <= f['r_a']) & old_active[j]
        eligible = ~old_active
        social_count = np.bincount(i[contact], minlength=n)
        draw = self.rng.random(n)
        td = eligible & direct
        ts = eligible & ~direct & (social_count > 0) & (draw < f['p_s'])
        self.source[eligible] = 0
        self.source[td], self.source[ts] = 1, 2
        self.remaining[td | ts] = f['tau_f']
        active = self.remaining > 0
        follow = unit(summed(heads[j], contact))
        valid_follow = np.linalg.norm(follow, axis=1) > 1e-12
        self.escape[ts & valid_follow] = follow[ts & valid_follow]
        self.escape[ts & ~valid_follow] = heads[ts & ~valid_follow]
        if direct.any():
            self.escape[direct] = unit(x[direct] - sharks[nearest[direct]])
        phi = np.arccos(np.clip(np.sum(self.escape * social, axis=1), -1, 1))
        valid_phi = active & (np.linalg.norm(self.escape, axis=1) > 1e-12)
        desired = social.copy()
        desired[active] = f['w']*self.escape[active] + (1-f['w'])*social[active]
        target = np.where(np.linalg.norm(desired, axis=1) > 1e-12, np.arctan2(desired[:,1], desired[:,0]), theta)
        noise = self.rng.normal(0, np.deg2rad(f['eta_theta']), n)
        requested = angle(target + noise - theta)
        limit = np.deg2rad(f['Omega']) * dt
        new_theta = angle(theta + np.clip(requested, -limit, limit))
        speed = speeds(self.rng, f['mu_f'], f['sigma_f'], n)
        position_noise = self.rng.normal(0, f['eta_x'], (n, 2))
        dx = np.c_[np.cos(new_theta), np.sin(new_theta)]*speed[:,None]*dt + position_noise
        self.velocity = dx / dt
        self.decisions = {'d': (active & (self.source==1)).astype(int).tolist(),
                          's': (active & (self.source==2)).astype(int).tolist(),
                          'r': (rep_counts>0).astype(int).tolist(), 'o': (counts==0).astype(int).tolist(),
                          'kappa': (np.abs(requested)>limit).astype(int).tolist(),
                          'phi': [float(v) if ok else None for v,ok in zip(phi,valid_phi)],
                          'trigger_d': td.astype(int).tolist(), 'trigger_s': ts.astype(int).tolist(),
                          'remaining': self.remaining.tolist(), 'nearest_shark': nearest.tolist(),
                          'requested_turn': requested.tolist(), 'speed': speed.tolist(),
                          'angle_noise': noise.tolist(), 'position_noise': position_noise.tolist(),
                          'social_direction': social.tolist(), 'escape_direction': self.escape.tolist(),
                          'social_draw': draw.tolist(), 'eligible': eligible.astype(int).tolist()}
        # Each row is recipient index, source index, source episode type at decision time.
        self.contacts = np.c_[i[contact],j[contact],old_source[j[contact]]].tolist()
        h,z,targets,shark_speed,shark_noise = [],[],[],[],[]
        for k,p in enumerate(self.predators):
            ds = np.linalg.norm(x-p.position,axis=1)
            near = int(np.argmin(ds)); found = ds[near] <= f['R_h']
            target_id = int(self.flock[near].unique_id) if found else -1
            target_angle = np.arctan2(*(x[near]-p.position)[::-1]) if found else p.heading
            eps = self.rng.normal(0,np.deg2rad(f['eta_theta']))
            turn_limit = np.deg2rad(cfg['predator']['max_turn_deg'])*dt
            p.heading = float(angle(p.heading + np.clip(angle(target_angle+eps-p.heading),-turn_limit,turn_limit)))
            sp = float(speeds(self.rng,f['mu_p'],f['sigma_p'],1)[0])
            p.position += np.array([np.cos(p.heading),np.sin(p.heading)])*sp*dt
            h.append(int(found)); z.append(int(target_id>=0 and self.targets[k]>=0 and target_id!=self.targets[k]))
            targets.append(target_id); shark_speed.append(sp); shark_noise.append(float(eps))
        self.shark_decisions = {'h':h,'z':z,'target':targets,'speed':shark_speed,'angle_noise':shark_noise}
        self.targets = np.array(targets,dtype=int)
        self.last_input = {'time':self.elapsed,'positions':x.tolist(),'headings':theta.tolist(),'shark_positions':sharks.tolist(),
                           'source':old_source.tolist(),'active':old_active.astype(int).tolist()}
        for a,pos,heading in zip(self.flock,x+dx,new_theta):
            a.position, a.heading = pos,float(heading)
        self.remaining = np.maximum(0,self.remaining-1)
        self.elapsed += dt

    def observation_frame(self):
        """Read-only short-lived analysis input, omitting raw decision provenance."""
        return {'step':self.steps,'time':self.elapsed,
                'ids':[a.unique_id for a in self.flock],
                'positions':np.array([a.position for a in self.flock]),
                'headings':np.array([a.heading for a in self.flock]),'velocities':self.velocity,
                'shark_ids':[a.unique_id for a in self.predators],
                'shark_positions':np.array([a.position for a in self.predators]).reshape(-1,2),
                'decisions':self.decisions,'shark_decisions':self.shark_decisions}

    def raw_frame(self):
        """Lossless, JSON-compatible boundary. Decisions describe [time-dt,time]."""
        return {'schema_version':3,'protocol':self.protocol_version,'step':self.steps,'time':self.elapsed,
                'ids':[a.unique_id for a in self.flock], 'positions':[a.position.tolist() for a in self.flock],
                'headings':[a.heading for a in self.flock], 'velocities':self.velocity.tolist(),
                'shark_ids':[a.unique_id for a in self.predators],
                'shark_positions':[a.position.tolist() for a in self.predators],
                'shark_headings':[a.heading for a in self.predators],
                'decisions':{k:[r.copy() if isinstance(r,list) else r for r in v] for k,v in self.decisions.items()},
                'shark_decisions':{k:v.copy() for k,v in self.shark_decisions.items()},
                'contacts':self.contacts,'decision_input':self.last_input}
