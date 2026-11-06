"""Execute explicitly reviewed functions away from the orchestration process.

This is process separation and timeout handling, NOT untrusted-code isolation.
"""
import importlib.util
import sys
from pathlib import Path

import pandas as pd
from simulations.common.trajectory_api import Trajectory

from .io import digest, read_json


def main(path):
    request = read_json(path)
    code = Path(request['code_file'])
    if digest(code) != request['code_sha256']:
        raise ValueError('Reviewed code digest changed before execution')
    spec = importlib.util.spec_from_file_location('reviewed_indicator', code)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = Trajectory(request['run_dir']).compute(module.compute_indicator, request['required'], request['config'])
    if isinstance(result, pd.Series):
        result = result.to_frame(name='value')
    result.to_parquet(request['output'])


if __name__ == '__main__':
    main(sys.argv[1])
