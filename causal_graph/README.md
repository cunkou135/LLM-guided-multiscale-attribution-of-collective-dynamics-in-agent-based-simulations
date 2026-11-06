# 第一部分：真实数据 Schema 驱动的 LLM 候选因果图（2.0）

研究分为两个核心部分：本模块生成未经统计验证的语义候选图，第二部分以后使用独立的数学方法判别候选关系。本轮不实现时滞估计、显著性筛选、Granger、Bootstrap、主动实验或参数干预。

## 安装与命令

从仓库根目录使用 Python 3.12；原生 Covasim 仍使用平台原有 Python 3.10 / Covasim 2.0.0 环境。

```powershell
python -m pip install -e ".[test,causal]"
python -m causal_graph --help
python -m causal_graph --config causal_graph/configs/llm.yaml --profile model_a --run-dir results/<run_id>
python -m causal_graph --config causal_graph/configs/deepseek_flash.yaml --run-id <run_id> --runs-root results --generate-only
python -m causal_graph --profile model_a --run-dir results/<run_a> --run-dir results/<run_b>
```

编辑 YAML 的供应商地址、模型和密钥环境变量名。示例 `model_a/model_b` 为占位符；`deepseek_flash.yaml` 为用户指定模型的无密钥档案，密钥环境变量为 `DEEPSEEK_API_KEY`。没有自动模型切换。精确科学依赖见 requirements-lock.txt，实验保存真实软件版本、源码 SHA-256 和 Git 状态。

## 方法与真实数据边界

十二步流程：输入完整性检查 → 真实公共数据 Schema → 宏观现象 → 三尺度变量及数学定义 → 独立 Python 函数 → 向上边 → 向下边 → 同层边 → 本地合并 → 结构/代码检查 → 指标执行及有效性检查 → 图与来源导出。

正常为六类 LLM 任务。现象生成仅接收当前固定想定、通用说明和输出 Schema；变量和代码生成额外接收完整实际数据 Schema。三类边分别只依据想定和本次变量定义独立判断，不查看其他方向的候选边，也不追加综合改图调用。

数据仅通过公开 Trajectory 接口读取。data_schema.json 保存所有输入运行共同具备且类型一致的字段、原字典含义、记录粒度、标识和关联字段；独有字段、类型或说明差异在 data_schema_audit.json 中记录。嵌套 JSON 检查实际首/中/末记录及每层最多 8 个数组元素，给出观察到的键和类型，明确非穷举；不将原始数值或整条日志发送给模型。未知语义和无法从公开接口确认的约束明确标注，不补造。

变量由 LLM 自主选择，没有固定指标库。required_data 记录定义需求；函数 required 记录实现需求，二者差异形成警告。原始字段不存在或可识别的实际访问未声明时校验失败。运行时投影只提供 required 声明的列；静态分析不能证明代码数学意义正确。

候选图 G_0=(V,E_up ∪ E_down ∪ E_intra)。允许 micro→macro、macro→micro、跨现象关系、双向边、循环及孤立节点；不强制 DAG、树或完整向上路径。自环和错误尺度分类被拒绝。重复端点仅本地去重，保留每个来源；不人为补边。max_edges 为合并图总上限，每类任务预算为 floor(max_edges/3)。

## 执行、恢复及输出

默认调用已有 Trajectory.compute_isolated，必须预先具备 Docker 及镜像：

```powershell
docker build -t abms-indicator:1 causal_graph/sandbox
```

没有 Docker 时不回退到宿主 Python。可先 --generate-only 保存模型原始代码。可信模式需要实际人工审查和精确哈希批准：review-file 包含 reviewer、reviewed_at、notes、code_sha256（指标 ID 到代码 SHA-256 的映射），然后明确使用 --execution-mode trusted_reviewed --review-file <file>。普通工作进程、AST 检查与超时不是不可信代码沙箱。无法实现的定义保留 implementation_status=unavailable、failure_reason，不生成替代函数。

candidate_graph.json/.graphml 保留全部假设、实现及逐运行状态；executable_graph.json/.graphml 只保留所有指定运行都计算成功的节点及原有边；per_run/<run_id>/ 保留每运行子图。成功序列为 indicator_series/<run_id>/<indicator_id>.parquet，包含 run_id、indicator_id、step、feature、value。节点 node_id==indicator_id，执行成功不等于因果关系获得验证。

--output 指定全新目录；默认按档案与配置哈希隔离。--resume <experiment_dir> 复用有效生成检查点并追加执行历史；输入、模型配置、实际 Schema、模板版本或源码改变时拒绝错误复用。2.0 不改写旧实验；1.0 的来源仍可按历史 Git 提交和原输出追溯。退出码 0 表示完整计算通过或明确仅生成，2 表示完成导出但有指标失败，1 表示流水线失败。

## API 传输与验证

YAML 支持 temperature、top_p、max_tokens、timeout、max_retries、reasoning_effort。null 表示不发送相应可选参数。extra_body 允许 seed、response_format、max_completion_tokens、verbosity、chat_template_kwargs、enable_thinking、stream_options；未知参数拒绝，供应商不支持的参数保留错误而不悄悄删除。max_completion_tokens 明确替代 max_tokens。

stream:true 可接收 SSE，原始流逐行保存，只有收到完整 [DONE] 与 finish_reason 才接受正文；缺失终止标记、中断及残缺响应保留并按上限重试。timeout 针对每次请求，包含流接收总预算；重试和六类调用分别计时。400/402 等明确配置或账户错误不自动重试；408/429/5xx、连接中断可重试。具体流格式参见 [DeepSeek 官方文档](https://api-docs.deepseek.com/api/create-chat-completion/)。密钥只在环境中读取，原始请求审计不包含 Authorization header。

```powershell
python -m pytest -q
python -m causal_graph.tests.validate_logs --output causal_graph/results/new_offline_validation
```

离线测试替身与真实模型测试严格区分。当前真实调用证据及执行限制见 [验收报告](docs/VALIDATION_REPORT.md) 和 [真实模型测试报告](docs/LIVE_LLM_TEST_REPORT.md)；方法、步骤、格式分别见 docs/METHODS_ALIGNMENT.md、PIPELINE.md、OUTPUT_SCHEMA.md。
