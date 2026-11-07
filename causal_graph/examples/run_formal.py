"""New broad-inventory experiment; credentials stay in the process environment."""
import argparse
import json
import os
from pathlib import Path
import time

from causal_graph.config import load_llm, load_pipeline
from causal_graph.io import now, read_json
from causal_graph.llm_client import LLMClient
from causal_graph.pipeline import run_pipeline


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scene', choices=['fish', 'covasim'])
    parser.add_argument('--output-root', type=Path, required=True)
    parser.add_argument('--source-config', type=Path, help='Optional existing JSON file containing api_key; never copied')
    parser.add_argument('--resume-source-upgrade', action='store_true')
    args = parser.parse_args(argv)
    configs = Path(__file__).resolve().parents[1] / 'configs'
    llm = load_llm(configs / 'deepseek_flash_formal.yaml')
    settings = load_pipeline(configs / 'formal_rich.yaml')
    previous_key = os.environ.get(llm.api_key_env)
    if not previous_key and args.source_config:
        source = json.loads(args.source_config.read_text(encoding='utf-8-sig'))
        if source.get('base_url', llm.base_url).rstrip('/') != llm.base_url.rstrip('/'):
            raise ValueError('Source credential URL differs from the explicitly configured provider')
        os.environ[llm.api_key_env] = source['api_key']

    class ProgressClient(LLMClient):
        def complete(self, messages, directory):
            stage = json.loads(messages[1]['content'])['generation_task']
            print(f'{now()} {args.scene}: requesting {stage}', flush=True)
            started = time.monotonic()
            result = super().complete(messages, directory)
            print(f'{now()} {args.scene}: received {stage} ({time.monotonic()-started:.1f}s)', flush=True)
            return result

    run_id = {'fish': '2a815b4dfe4f47b8ac2416fac04456e5',
              'covasim': '3249f90463154305aed53504106b3dae'}[args.scene]
    output = args.output_root / args.scene
    args.output_root.mkdir(parents=True, exist_ok=True)
    try:
        result = run_pipeline([Path('results') / run_id], llm, settings, output,
                              client=ProgressClient(llm), resume=(output / 'experiment.json').exists(), generate_only=True,
                              resume_source_upgrade=args.resume_source_upgrade)
        print(f'{args.scene}: {read_json(result / "pipeline_report.json")["status"]}', flush=True)
    finally:
        if previous_key is None:
            os.environ.pop(llm.api_key_env, None)


if __name__ == '__main__':
    main()
