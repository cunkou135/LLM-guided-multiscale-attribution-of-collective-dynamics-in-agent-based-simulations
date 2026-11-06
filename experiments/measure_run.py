"""Measure one prescribed configuration without parameter search or trajectory padding."""
import argparse
import json
import os
from pathlib import Path
import threading
import time
import psutil
from simulations.common.runner import load, run


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    config = load(args.config)
    process = psutil.Process(os.getpid())
    peak = [process.memory_info().rss]
    stop = threading.Event()
    def sample():
        while not stop.wait(.02):
            total = process.memory_info().rss
            for child in process.children(recursive=True):
                try:
                    total += child.memory_info().rss
                except psutil.NoSuchProcess:
                    pass
            peak[0] = max(peak[0], total)
    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    started = time.perf_counter()
    try:
        directory = run(config)
    finally:
        elapsed = time.perf_counter() - started
        stop.set()
        sampler.join()
    manifest = json.loads((directory / 'manifest.json').read_text())
    import pyarrow.parquet as pq
    population = pq.read_table(directory / 'model_states.parquet', columns=['population'])['population'][0].as_py()
    report = dict(run_id=directory.name, model=config['model'], population=population,
                  requested_steps=config['steps'], actual_steps=manifest['actual_steps'],
                  stop_reason=manifest['status'], elapsed_seconds=elapsed, peak_rss_bytes=peak[0],
                  output_bytes=sum(p.stat().st_size for p in directory.iterdir() if p.is_file()),
                  config=args.config, git_commit=manifest['git_commit'], git_dirty=manifest['git_dirty'],
                  memory_method='20ms sampled RSS sum of parent and child processes; not allocator peak')
    result = directory / 'performance.json'
    result.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(result)


if __name__ == '__main__':
    main()
