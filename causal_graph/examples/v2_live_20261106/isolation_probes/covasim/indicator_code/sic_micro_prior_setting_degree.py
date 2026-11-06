import numpy as np
import pandas as pd


def _infection_mask(df, config):
    event_types = config.get("infection_event_types") or []
    states = config.get("infection_states") or []
    mask = pd.Series(False, index=df.index)
    if event_types:
        mask = mask | df["event_type"].isin(event_types).fillna(False).astype(bool)
    if states:
        mask = mask | df["state"].isin(states).fillna(False).astype(bool)
    return mask


def _is_null(value):
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def compute_indicator(data, config):
    events = data["events"]
    contacts = data["contacts"]
    window = int(config.get("window", 5))
    aggregation = str(config.get("aggregation", "mean"))

    ev = events.loc[_infection_mask(events, config), ["run_id", "step", "agent_id", "layer"]]
    ev = ev.dropna(subset=["step"])
    if ev.empty:
        return pd.Series(dtype="float64", index=pd.Index([], name="step", dtype="int64"), name="value")

    con = contacts[["run_id", "step", "layer", "agent_id", "partner_id"]].dropna(
        subset=["run_id", "step", "layer", "agent_id", "partner_id"]
    )
    con = con[con["agent_id"] != con["partner_id"]]

    fwd = con.rename(columns={"agent_id": "a", "partner_id": "p"})[["run_id", "layer", "step", "a", "p"]]
    bwd = con.rename(columns={"partner_id": "a", "agent_id": "p"})[["run_id", "layer", "step", "a", "p"]]
    edges = pd.concat([fwd, bwd], ignore_index=True)

    edge_groups = {}
    for key, g in edges.groupby(["run_id", "layer"], sort=False):
        g = g.sort_values("step")
        edge_groups[key] = (
            g["step"].to_numpy(dtype="int64"),
            g["a"].to_numpy(),
            g["p"].to_numpy(),
        )

    out_steps = []
    out_values = []
    for run_id, step, agent_id, layer in ev.itertuples(index=False):
        if _is_null(layer) or _is_null(agent_id):
            out_steps.append(step)
            out_values.append(np.nan)
            continue
        entry = edge_groups.get((run_id, layer))
        if entry is None:
            out_steps.append(step)
            out_values.append(0.0)
            continue
        steps_arr, a_arr, p_arr = entry
        lo = int(np.searchsorted(steps_arr, step - window, side="left"))
        hi = int(np.searchsorted(steps_arr, step - 1, side="right"))
        if hi <= lo:
            out_steps.append(step)
            out_values.append(0.0)
            continue
        sel_p = p_arr[lo:hi]
        sel_a = a_arr[lo:hi]
        partners = pd.unique(sel_p[sel_a == agent_id])
        out_steps.append(step)
        out_values.append(float(len(partners)))

    frame = pd.DataFrame({"step": out_steps, "value": out_values})
    series = frame.groupby("step")["value"].agg(aggregation).sort_index()
    series.index = series.index.astype("int64")
    series.index.name = "step"
    series.name = "value"
    return series
