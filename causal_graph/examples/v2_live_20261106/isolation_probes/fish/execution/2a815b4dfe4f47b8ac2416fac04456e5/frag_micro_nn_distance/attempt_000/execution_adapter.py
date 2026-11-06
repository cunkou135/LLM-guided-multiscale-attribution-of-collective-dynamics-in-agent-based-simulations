import numpy as np
import pandas as pd
from scipy.spatial.distance import cdist


def compute_indicator(data, config):
    st = data['agent_states'][['run_id', 'step', 'agent_id', 'role', 'x', 'y']].copy()
    role = st['role'].astype(str).str.lower()
    st = st[role == str(config.get('role_filter', 'fish')).lower()]
    st = st.dropna(subset=['agent_id', 'x', 'y'])

    steps = []
    aids = []
    vals = []

    for (rid, step), g in st.groupby(['run_id', 'step'], sort=True):
        ids = g['agent_id'].astype('int64').to_numpy()
        p = g[['x', 'y']].to_numpy(dtype=float)
        n = len(ids)

        if n < 2:
            d = np.full(n, np.nan)
        else:
            D = cdist(p, p, metric='euclidean')
            np.fill_diagonal(D, np.inf)
            d = D.min(axis=1)
            d[~np.isfinite(d)] = np.nan

        steps.extend([step] * n)
        aids.extend(ids.tolist())
        vals.extend(d.tolist())

    out = pd.DataFrame({'step': steps, 'agent_id': aids, 'value': vals})
    out = out.set_index(['step', 'agent_id'])
    return out


_stage1_original = compute_indicator
def compute_indicator(data, config):
    required = {'agent_states': ['run_id', 'step', 'agent_id', 'role', 'x', 'y']}
    projected = {name: data[name].loc[:, fields].copy(deep=True) for name, fields in required.items()}
    return _stage1_original(projected, config)
