# 第一部分：真实数据 Schema 驱动的 LLM 候选因果图（2.0）

丰富候选图使用 `configs/formal_rich.yaml`（最多 8 个现象、72 个变量、720 条边）与 `configs/deepseek_flash_formal.yaml`。该设置不要求固定各尺度数量，不为增加复杂度强行补边；新实验与旧 6 变量测试结果分别保存。参数、真实生成结果和大图展示方式见 [丰富候选图实验说明](docs/FORMAL_RICH_EXPERIMENT.md)。

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

本项目的本地科研执行路径不要求 Docker 或容器。先生成、逐份审查代码并批准精确 SHA-256，再显式选择 configs/local_trusted.yaml 或 --execution-mode trusted_reviewed，在当前 Python 环境的独立子进程中计算。原隔离接口保留为兼容选项，但本次不使用、不安装。

可先 --generate-only 保存原始代码。审核文件包含 reviewer、reviewed_at、notes、code_sha256（通过代码的精确 SHA-256），可选 rejections 为未通过函数记录具体原因及哈希。未批准、哈希变化或被拒绝的函数不执行。本次审核由用户明确授权的 Codex 逐份完成，记录实际审核身份，不冒称人工签名。子进程保留超时、完整 stdout/stderr、请求配置、返回值及异常；它是可信代码执行方式，不宣称安全沙箱。

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

## 只恢复本地计算，不调用模型

--execute-only 必须配合 --resume，禁止模型调用。它复用并验证全部六类检查点，确认原变量、数学定义、函数和边未变化；允许执行器源码升级，原生成身份和源码记录保留，另存当前 execution_software.json。输入、模型配置、想定、数据 Schema、模板、生成上限或原始响应变化仍拒绝复用；缺少检查点直接失败，不补发模型请求。

本次原实验的完整运行命令（没有 API Key 也可恢复，复用旧生成上限配置）：

```powershell
python -m causal_graph --config causal_graph/results/v2_live_20261106/llm.yaml --pipeline-config causal_graph/results/local_execution_final_20261106/pipeline_local.yaml --run-dir results/2a815b4dfe4f47b8ac2416fac04456e5 --resume causal_graph/results/v2_live_20261106/fish --execute-only --review-file causal_graph/results/local_execution_final_20261106/fish/review.json
python -m causal_graph.tests.validate_reviewed --audit-root causal_graph/results/new_reviewed_validation
```

后一个命令重做 12 份固定原代码的审查记录、执行及独立数学验算，不调用 LLM；审查规则只适用于这批已发布的精确源文件，不能自动批准未来代码。普通 --resume 仍执行原来的严格源码一致性检查。审核需结合数学定义；config 的新增聚合说明不能静默改变原定义的观测单位。

微观输出支持 (step, agent_id) 等命名 MultiIndex，保存为包含 entity_id 的长表；不擅自取均值。entity_id 为原主体键的 JSON 对象字符串。后续按 (run_id, indicator_id, entity_id, feature, step) 读取，不能将不同主体混成重复时间或把主体编号当测量值。

独立验算是检查，绝不替代模型函数输出。当前 12 个指标中 8 个通过、2 个审核拒绝、2 个结果验收未通过；严格数值容差和原始缺失列保留。报告详见 docs/LOCAL_EXECUTION_REPORT.md。

## 可视化所有真实因果图

```powershell
python -m causal_graph.visualize_graphs --experiment causal_graph/results/v2_live_20261106/fish --experiment causal_graph/results/v2_live_20261106/covasim --output causal_graph/results/new_graph_views
```

导出每场景的完整候选图、可执行图、三类方向分图和逐运行图，共 12 个 SVG/PNG；overview.png 对照四个主图，index.html 可切换视图并点选定义/边理由。绘图不修改原图，不添加关系；边颜色/线型只表示方向类别。执行失败节点在完整图中仍保留并标注，所有边仍未经统计因果检验。图形依赖使用本机现有 Matplotlib/Pillow，另提供可选安装项 .[graphs]。

绘图现默认优先使用本机已有 Graphviz 自动紧凑布局，节点字体 14 点，提供 DOT/SVG/PNG/PDF。`--layout matplotlib` 可使用后备路径。大于 12 节点时增加按现象分图和完整有向邻接矩阵；HTML 支持缩放及点选相邻关系，保留原始字号。概览仅用于导航，论文阅读和导出应使用独立分图。

本轮真实生成已完成 Fish 72 变量/495 边、Covasim 67 变量/454 边，共 30 个新视图；另提供旧结果 12 个紧凑视图。[查看新图](examples/formal_rich_20261106/graphs/index.html)，[查看验收](docs/RICH_GENERATION_ACCEPTANCE.md)。新增 139 个函数本轮未执行。
