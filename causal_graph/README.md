# 第一阶段：LLM 跨尺度候选因果图

本模块从已完成仿真的固定自然语言想定出发，依次生成候选宏观现象、三尺度变量、数学定义、独立 Python 函数与语义有向边。随后通过已有 `Trajectory` 执行函数，保存真实时间序列及完整失败记录。**全部边均为未经统计验证的语义候选关系。** 不实现第二、第三阶段。

## 安装

从仓库根目录运行，平台使用 Python 3.12；Covasim 仍使用原平台配置的独立 Python 3.10 / 原生 2.0.0 环境，参见根 README。

```powershell
python -m pip install -e ".[test,causal]"
# 需要复用本次验证的第一阶段精确科学计算依赖时：
python -m pip install -r causal_graph/requirements-lock.txt
python -m causal_graph --help
```

精确版本文件覆盖本模块运行依赖及其 Python 依赖；平台依赖仍由根 pyproject.toml 管理。每次实验另外保存真实软件版本、源码 SHA-256 和 Git 状态。此配置不承诺不同服务端版本能逐字重复生成相同答案。

## 配置与调用

编辑 `causal_graph/configs/llm.yaml` 中相应档案的 `base_url`、`model`、`api_key_env`；示例地址和模型名不可用于真实调用。API Key 仅从用户设置的环境变量读取，不写入 YAML 或审计文件。不会自动更换模型。

```powershell
python -m causal_graph --config causal_graph/configs/llm.yaml --profile model_a --run-dir results/<run_id>
python -m causal_graph --profile model_b --run-id <run_id> --runs-root results
# 同模型、同想定版本的多个种子：
python -m causal_graph --profile model_a --run-dir results/<run_a> --run-dir results/<run_b>
```

`--output` 指定全新实验目录；默认保存到 `causal_graph/results/<profile>-<configuration-hash>/<unique-id>/`。已有目录不覆盖。换模型必须新建实验。退出码 0 表示计算全部通过或明确选择仅生成；2 表示图已输出但有指标失败；1 表示输入、生成或流水线失败。

所有供应商参数来自 YAML。`temperature/top_p: null` 表示不发送该参数。`reasoning_effort` 只在非空时发送。允许的 `extra_body` 为 `seed`、`response_format`、`max_completion_tokens`、`verbosity`、`chat_template_kwargs`、`enable_thinking`；配置 `max_completion_tokens` 后有记录地替代 `max_tokens`。其他字段明确拒绝；服务端不支持参数时保留错误原文，不自动删除参数重试。网络超时、408、429、5xx 可重试，400 等配置错误立即失败。原始供应商 envelope、实际 model、usage、响应 ID、每次耗时均保留；供应商未提供时为 null。

## 数据与提示词边界

输入目录必须含 `manifest.json`、`scenario.md`、`resolved_config.yaml`、`field_catalog.json` 和已登记的 Parquet 数据。校验运行完成状态、原始数据校验和、行级来源、实际时间边界以及固定注册场景版本/哈希。缺失的可选表不伪造；依赖该表的变量失败。

模型仅接收当前固定想定、通用任务/输出 Schema，以及当前生成链先前的现象和变量定义。**不传真实字段目录、轨迹、事件、模型源码、旧指标集合或人工参考图。** 代码阶段使用通用 `data` 契约：`data` 是表名到 DataFrame 的映射，函数通过 `required` 声明预计使用的原始表和列；运行时由公开 `Trajectory` 校验与读取。字段不存在即记录 `unavailable_data`，不自动找替代指标。具体接口见 [PIPELINE.md](docs/PIPELINE.md)。

## 执行与人工审查

默认复用平台 `Trajectory.compute_isolated`；提前准备 Docker 和镜像：

```powershell
docker build -t abms-indicator:1 causal_graph/sandbox
```

不存在 Docker/镜像或执行失败时不会回退到宿主执行。容器路径使用平台已有只读、禁网、非 root 与资源限制。当前验收机器没有 Docker，因此仅实际验证了拒绝执行，未宣称容器端到端通过。AST 检查只排除明显不合约代码，不能证明代码安全或数学定义正确。

需要人工审核时，先 `--generate-only`，检查 `indicator_code/*.py`、定义和来源调用。人工编写审查文件（系统不自动批准）：

```json
{
  "reviewer": "实际审查者",
  "reviewed_at": "实际审查时间",
  "notes": "实际审查范围与结论",
  "code_sha256": {"生成的indicator_id": "对应代码文件的64位SHA-256"}
}
```

然后明确选择可信模式并恢复同一实验：

```powershell
python -m causal_graph --profile model_a --run-dir results/<run_id> --generate-only --output causal_graph/results/my_experiment
python -m causal_graph --profile model_a --run-dir results/<run_id> --resume causal_graph/results/my_experiment --execution-mode trusted_reviewed --review-file reviewed.json
```

可信模式使用单独的有超时进程调用公开 `Trajectory.compute`，不把 API 凭据传给工作进程；**普通进程分离不是不可信代码沙箱**。仅应批准本人实际审查过的精确代码哈希。不能将修改后的代码覆盖原自动版本；另建人工修订记录，避免混淆研究归属。

## 输出、恢复和测试

完整原始结构见 `candidate_graph.json/.graphml`；共同可执行结构见 `executable_graph.json/.graphml`；每运行子图在 `per_run/<run_id>/`。指标序列为 `indicator_series/<run_id>/<indicator_id>.parquet`，含 `run_id, indicator_id, step, feature, value`。节点 `node_id == indicator_id`，后续阶段直接按 ID 和文件索引读取，无须重新解析自然语言。输出契约见 [OUTPUT_SCHEMA.md](docs/OUTPUT_SCHEMA.md)。

用同样输入和模型配置加 `--resume <experiment_dir>` 恢复。已经验证的模型生成调用复用缓存，不重复请求；中断步骤重试，执行阶段重新计算，旧执行尝试和调用历史保留。输入数据、模型、提示词、生成参数或源码发生变化时拒绝恢复。执行模式可以在明确审查后变更并登记。并发运行同一实验被锁拒绝；强制终止后的锁需先检查进程，再人工清理。

```powershell
python -m pytest causal_graph/tests -q
python -m pytest -q
# 独立的真实日志验收：2000鱼/5鲨鱼、1000人Covasim，各两个种子、5步：
python -m causal_graph.tests.validate_logs --output causal_graph/results/my_log_validation
```

测试不需要 API Key。`tests/fixtures.py` 的人工响应只用于软件接口测试，所有实验标记 `offline_fixture_not_model_generated`；不属于方法的指标库，不是 LLM 结果或科学机制证据。真实日志验收实际计算这些已审查的测试函数，并与原始数据计算逐值比较。按照用户本轮指示，仅保留真实 API 接口，不检查或运行真实 LLM。

相关材料：[需求评审](docs/REQUIREMENTS_REVIEW.md)、[方法对应](docs/METHODS_ALIGNMENT.md)、[中文验收报告](docs/VALIDATION_REPORT.md)。
