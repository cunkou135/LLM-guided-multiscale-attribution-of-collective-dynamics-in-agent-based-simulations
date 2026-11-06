"""Independent entry point; configuration never silently selects another model."""
import argparse
from dataclasses import replace
from pathlib import Path
import re
import sys
import uuid

from .config import load_llm, load_pipeline
from .indicator_runner import load_approvals
from .inputs import resolve_runs
from .io import object_digest, read_json
from .pipeline import run_pipeline, PipelineFailure


def main(argv=None):
    defaults = Path(__file__).resolve().parent / 'configs'
    parser = argparse.ArgumentParser(description='First-part candidate causal graphs and reviewed local indicator execution')
    parser.add_argument('--config', type=Path, default=defaults / 'llm.yaml')
    parser.add_argument('--pipeline-config', type=Path, default=defaults / 'pipeline.yaml')
    parser.add_argument('--profile')
    parser.add_argument('--run-dir', type=Path, action='append', default=[])
    parser.add_argument('--run-id', action='append', default=[])
    parser.add_argument('--runs-root', type=Path, default=Path('results'))
    parser.add_argument('--output', type=Path, help='New experiment directory; never overwrite')
    parser.add_argument('--output-root', type=Path, default=Path('causal_graph/results'))
    parser.add_argument('--resume', type=Path, help='Resume an existing experiment; repeat identical run/model configuration')
    parser.add_argument('--generate-only', action='store_true', help='Generate hypotheses/code for review without execution')
    parser.add_argument('--execute-only', action='store_true', help='Resume reviewed calculations from existing checkpoints; never call the LLM')
    parser.add_argument('--execution-mode', choices=['isolated', 'trusted_reviewed'])
    parser.add_argument('--review-file', type=Path, help='Code review identity, decisions and exact approved source SHA-256 values')
    args = parser.parse_args(argv)
    try:
        if args.output and args.resume:
            raise ValueError('--output and --resume are mutually exclusive')
        if args.execute_only and (not args.resume or args.generate_only):
            raise ValueError('--execute-only requires --resume and cannot use --generate-only')
        llm = load_llm(args.config, args.profile)
        settings = load_pipeline(args.pipeline_config)
        if args.execution_mode:
            settings = replace(settings, execution_mode=args.execution_mode)
        approvals = load_approvals(args.review_file)
        if settings.execution_mode == 'trusted_reviewed' and not args.generate_only and approvals is None:
            raise ValueError('trusted_reviewed requires --review-file with explicit code review and code hashes')
        paths = resolve_runs(args.run_dir, args.run_id, args.runs_root)
        group = re.sub('[^A-Za-z0-9_-]', '_', llm.profile)[:60] + '-' + object_digest(llm.summary())[:12]
        output = args.resume or args.output or args.output_root / group / uuid.uuid4().hex
        result = run_pipeline(paths, llm, settings, output, resume=bool(args.resume),
                              generate_only=args.generate_only, approvals=approvals, execute_only=args.execute_only)
        report = read_json(result / 'pipeline_report.json')
        print(f'{report["status"]}: {result}')
        return 2 if report['status'] == 'completed_with_failures' else 0
    except (ValueError, OSError, PipelineFailure) as exc:
        print(f'Stage one failed: {exc}', file=sys.stderr)
        return 1
