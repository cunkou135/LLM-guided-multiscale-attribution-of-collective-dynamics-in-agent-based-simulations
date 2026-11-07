"""Execute explicitly reviewed functions away from the orchestration process.

This is process separation and timeout handling, NOT untrusted-code isolation.
"""
import importlib.util
import sys
from pathlib import Path

import pandas as pd
from simulations.common.trajectory_api import Trajectory

from .io import digest, read_json


def compute_reviewed(trajectory, function, required, config, contract=None, batch_size=0):
    """Execute declared finite-window observations without loading unrelated log columns.

    Chunking is allowed only by an explicit, scientifically reviewed time contract.
    Full-window/legacy functions keep their original single-call behavior.
    """
    if not contract or not batch_size:
        projected = {name: trajectory.read(name, columns=fields) for name, fields in required.items()}
        return function(projected, config)
    from observation_contract import validate_contract
    validate_contract(contract)
    axis = trajectory.available_steps(); pieces = []
    for start in range(0, len(axis), batch_size):
        core = axis[start:start + batch_size]
        lower = core[0] - contract['temporal_window_steps']
        data = {name: trajectory.read(name, start=lower, end=core[-1], columns=fields) for name, fields in required.items()}
        value = function(data, config)
        if not isinstance(value, (pd.Series, pd.DataFrame)): raise ValueError('Chunk output is not Series/DataFrame')
        if 'step' in value.index.names:
            keep = value.index.get_level_values('step').isin(core)
        elif isinstance(value, pd.DataFrame) and 'step' in value.columns:
            keep = value.step.isin(core)
        else: raise ValueError('Chunk output must retain its declared step coordinate')
        pieces.append(value.loc[keep])
    return pd.concat(pieces)


def main(path):
    request = read_json(path)
    code = Path(request['code_file'])
    if digest(code) != request['code_sha256']:
        raise ValueError('Reviewed code digest changed before execution')
    spec = importlib.util.spec_from_file_location('reviewed_indicator', code)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = compute_reviewed(Trajectory(request['run_dir']), module.compute_indicator,
        request['required'], request['config'], request.get('analysis_contract'), request.get('step_batch_size', 0))
    if isinstance(result, pd.Series):
        result = result.to_frame(name='value')
    result.to_parquet(request['output'])


if __name__ == '__main__':
    main(sys.argv[1])
