# Reproduction helper: output goes to a new explicit directory; no key is stored.
import argparse
import json
import os
from pathlib import Path
import time

from causal_graph.config import load_llm, load_pipeline
from causal_graph.io import now, read_json, save_json
from causal_graph.llm_client import LLMClient
from causal_graph.pipeline import run_pipeline

parser=argparse.ArgumentParser()
parser.add_argument('scene',choices=['fish','covasim'])
parser.add_argument('--output-root',type=Path,required=True)
parser.add_argument('--source-config',type=Path,default=Path(r'E:/work/jk项目/博士生项目/演示案例_20261027/llm_config.json'))
args=parser.parse_args()
root=Path(__file__).resolve().parent
source=args.source_config
output_root=args.output_root.resolve()
output_root.mkdir(parents=True,exist_ok=True)
original=json.loads(source.read_text(encoding='utf-8-sig'))
os.environ['STAGE1_SUPPLIED_CONFIG_API_KEY']=original['api_key']
config=load_llm(root/'llm.yaml')
settings=load_pipeline(root/'pipeline.yaml')
run_id={'fish':'2a815b4dfe4f47b8ac2416fac04456e5','covasim':'3249f90463154305aed53504106b3dae'}[args.scene]

class ProgressClient(LLMClient):
 def complete(self,messages,directory):
  stage=json.loads(messages[1]['content'])['generation_task']
  print(f'{now()} {args.scene}: requesting {stage}',flush=True)
  started=time.monotonic()
  result=super().complete(messages,directory)
  print(f'{now()} {args.scene}: received {stage} ({time.monotonic()-started:.2f}s)',flush=True)
  return result

start=now()
try:
 output=run_pipeline([Path('results')/run_id],config,settings,output_root/args.scene,client=ProgressClient(config),resume=(output_root/args.scene/"experiment.json").exists(),generate_only=True)
 report=read_json(output/'pipeline_report.json')
 print(f'{args.scene}: {report["status"]}',flush=True)
except Exception as exc:
 save_json(output_root/f'{args.scene}_test_failure.json',{'started_at':start,'ended_at':now(),'error':str(exc)})
 raise
finally:
 os.environ.pop('STAGE1_SUPPLIED_CONFIG_API_KEY',None)
