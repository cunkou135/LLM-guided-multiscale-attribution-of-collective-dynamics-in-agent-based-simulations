import argparse
import os
import logging
import json
import subprocess
import sys
from pathlib import Path
from simulations.common.runner import batch, load, run

parser = argparse.ArgumentParser()
parser.add_argument('command', choices=['run', 'batch', 'ui'])
parser.add_argument('--config', required=True)
args = parser.parse_args()
if args.command == 'ui':
    config = load(args.config)  # Fail fast before starting the server.
    if not config['visualization']['enabled']:
        parser.error('visualization.enabled is false')
    env = os.environ.copy()
    env['ABMS_CONFIG'] = str(Path(args.config).resolve())
    app = Path(__file__).resolve().parent / 'visualization' / 'app.py'
    sys.exit(subprocess.call([sys.executable, '-m', 'solara', 'run', str(app), '--no-open', '--host', config['visualization']['host'], '--port', str(config['visualization']['port']), '--log-level', config['logging']['level'].lower()], env=env))
elif args.command == 'run':
    config = load(args.config)
    logging.basicConfig(level=config['logging']['level'])
    print(run(config))
else:
    report = batch(args.config)
    print(report)
    if any(entry['error'] for entry in json.loads(report.read_text(encoding='utf-8'))):
        sys.exit(1)
