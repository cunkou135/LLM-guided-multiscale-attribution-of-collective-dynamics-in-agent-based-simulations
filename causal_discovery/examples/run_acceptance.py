"""Reproduce actual independent CLIs and the integrated demo; no LLM or simulations.

Run from the repository root: python causal_discovery/examples/run_acceptance.py
"""
import argparse
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from causal_discovery._common import save_json, settings, sha256
from causal_discovery.m2_lag_rnn import demo_arrays as lag_arrays
from causal_discovery.m3_granger import demo_arrays as granger_arrays
from causal_discovery.m4_pid import demo_arrays as pid_arrays
from causal_discovery.m5_graph import demo_payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'causal_discovery/results/acceptance_20261107')
    args = parser.parse_args(); directory = args.output.resolve(); directory.mkdir(parents=True, exist_ok=True)
    inputs = ROOT / 'causal_discovery/examples/inputs'; cfg = settings(); d = cfg['demo']
    payloads = {'m1_data': {'x': [1, 2, 3, 4, 5, 6], 'y': [2, 3, 4, 5, 6, 7], 'steps': [0, 1, 2, 3, 4, 5]},
                'm2_lag_rnn': lag_arrays(d['m2_seed'], d['m2_length']),
                'm3_granger': granger_arrays(d['m3_seed'], d['m3_length']),
                'm4_pid': pid_arrays(d['m4_seed'], d['m4_length']), 'm5_graph': demo_payload()}
    save_json(inputs / 'm4_xor_static.json', {'static': True, 'x1': [0, 0, 1, 1], 'x2': [0, 1, 0, 1], 'y': [0, 1, 1, 0]})
    commands = []
    for module, payload in payloads.items():
        save_json(inputs / f'{module}.json', payload)
        for mode in ('demo', 'input'):
            command = [sys.executable, '-m', f'causal_discovery.{module}', '--' + mode]
            if mode == 'input': command.append(str(inputs / f'{module}.json'))
            command += ['--output', str(directory / 'independent' / f'{module}_{mode}.json')]
            commands.append(command)
    commands.append([sys.executable, '-m', 'causal_discovery.m4_pid', '--input', str(inputs / 'm4_xor_static.json'),
                     '--output', str(directory / 'independent/m4_xor_static.json')])
    commands.append([sys.executable, '-m', 'causal_discovery.pipeline', '--demo', '--output', str(directory / 'demo_final_causal_graph.json')])
    for scene in ('fish', 'covasim'):
        source = ROOT / 'causal_graph/results/v2_live_20261106' / scene / 'executable_graph.json'
        if not source.exists():
            raise FileNotFoundError(f'Real acceptance needs the existing first-part archive extracted at {source.parent}')
        commands.append([sys.executable, '-m', 'causal_discovery.pipeline', '--input', str(source),
                         '--config', str(ROOT / f'causal_discovery/examples/real_{scene}_config.yaml'),
                         '--output', str(directory / scene / 'final_causal_graph.json')])
        rich = ROOT / 'causal_graph/results/formal_rich_json_20261106' / scene / 'executable_graph.json'
        if rich.exists():
            commands.append([sys.executable, '-m', 'causal_discovery.pipeline', '--input', str(rich),
                             '--output', str(directory / f'rich_{scene}' / 'final_causal_graph.json')])
    log = []
    for i, command in enumerate(commands):
        started = time.monotonic()
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=600)
        record = {'command': command, 'exit_code': result.returncode, 'elapsed_seconds': time.monotonic() - started,
                  'stdout': result.stdout, 'stderr': result.stderr}
        log.append(record); save_json(directory / 'commands.json', log)
        print(f'{i + 1}/{len(commands)}: {command[2]} ({result.returncode})', flush=True)
        if result.returncode: raise RuntimeError(json.dumps(record, ensure_ascii=False))
    save_json(directory / 'environment.json', {'python': sys.version, 'packages': {
        name: importlib.metadata.version(name) for name in ('numpy', 'pandas', 'pyarrow', 'scipy', 'torch', 'jsonschema', 'pytest', 'PyYAML')},
        'source_sha256': {str(p.relative_to(ROOT)): sha256(p) for p in (ROOT / 'causal_discovery').glob('*.py')}})


if __name__ == '__main__': main()
