最新丰富候选生成：Fish 72 变量/495 边、Covasim 67 变量/454 边，143 项回归通过；新增函数未执行。详见 [丰富生成验收](RICH_GENERATION_ACCEPTANCE.md)。下文原 12 个函数的本地执行验收与这批新候选分开。

# 第一部分方法 2.0 中文验收报告

> 最新本地执行验收：在用户授权下已使用现有 Python 执行原函数，无 Docker、无新 LLM 调用。12 项中 8 项通过，2 项审核拒绝、2 项结果验收未通过。原生成及 35 条关系保留，可执行图现为 Fish 5 节点/9 边、Covasim 3 节点/3 边。详见 [本地执行验收报告](LOCAL_EXECUTION_REPORT.md)；下文为原生成阶段的历史验收。

日期：2026-11-06。基准及开发前远端最新提交为 99d081a4050e1bbbd53975e7260b9f3654e9c671。保留本会话已有传输修复和旧实验，没有覆盖仿真源码、固定想定或原始日志。初版验收原文保留于 validation/v1_validation_99d081a.md；本报告描述新版。

## 实现及论文边界

第一部分生成候选图，第二部分以后做数据因果判别；不再设置独立干预阶段。本轮没有实现时滞估计、显著性筛选、Granger、Bootstrap、因果强度、主动实验或参数干预。

十二步：运行/想定检查 → 从真实记录构建公共 Schema → 现象 → 变量/数学定义 → Python 函数 → 向上边 → 向下边 → 同层边 → 本地合并 → 结构/代码检查 → 执行及数值检查 → 完整图/可执行图/独立序列与来源导出。

正常六类独立 LLM 任务；第一类仅想定，变量/代码类含完整真实 Schema，三类关系不互看边、不经第七次综合调用。候选图允许直接跨尺度、跨现象、双向关系、反馈环和孤立节点；自环拒绝，重复端点去重并保留全部来源。没有补边或为完整路径删除节点。

公共 Schema 来源于 Trajectory 的实际字段、类型和数据字典；不同运行字段或类型差异单独审计，不把独有字段当公共字段。嵌套 JSON 只报告实际检查范围的结构，明确非穷举；未知语义如实保留。字段声明、可识别的代码访问和运行时字段投影分别检查，required_data/required 差异不隐藏。

## 实际自动化验收

|检查|实际结果|证据|
|---|---|---|
|重构前基线（含原 107 项）|114 passed|validation/pre_v2_baseline_114.xml|
|重构后首轮模块测试|66 passed，26.55 秒|实际 pytest 记录，随后新增 Schema/反馈与恢复测试|
|新规则全套首轮回归|126 passed，109.97 秒|causal_graph/results/v2_regression.xml|
|最终全套回归|126 passed，112.80 秒，0 失败|validation/v2_regression_126.xml|
|Fish/Covasim 双种子真实日志离线验收|passed；每模型 6 次已审查测试函数成功，2 次预期不可实现记录；原始帧/事件检查通过|causal_graph/results/v2_offline_release_20261106/validation_summary.json|
|真实模型六任务|两个场景全部完成；逐调用返回 deepseek-flash|LIVE_LLM_TEST_REPORT.md、examples/v2_live_20261106/|
|独立 CLI 缓存恢复|两个真实实验均 --resume --generate-only 成功，未新增 API 请求|每实验第二个 invocation|
|默认隔离边界|实际调用后拒绝执行：Docker unavailable，无宿主回退|真实示例 isolation_probes/|
|历史兼容及追溯|旧 1.0 归档未改；模型/想定/Schema/源码变化拒绝错误复用；图和产物哈希核对|测试、原始归档与 artifact_hashes|

自动化覆盖字段交集和类型差异、实际 Fish/Covasim 字段及嵌套结构、第一轮提示词边界、第二三轮完整 Schema、字段声明及实际访问、三类方向、直接跨尺度、双向/循环/孤立节点、自环、重复来源、无效引用、代码不可实现、执行失败保边、多种子独立计算、Schema 身份变化与恢复、JSON/GraphML、原文/用量/传输失败保存。没有删除失败用例以通过测试；原完整路径和重复端点规则按用户新规格更新为对应的新行为断言。

## 真实模型结果与执行限制

|场景|现象|变量|向上/向下/同层边|通过生成代码检查|实际指标执行|
|---|---|---|---|---|---|
|Fish|2|6，三尺度各 2|6 / 6 / 3|6 成功，0 失败|0 成功，6 未执行|
|Covasim|2|6，三尺度各 2|7 / 7 / 6|6 成功，0 失败|0 成功，6 未执行|

真实配置：deepseek-flash，temperature=0.3，max_tokens=32768，reasoning_effort=low，timeout=600，max_retries=1，stream=true。功能验证仅设上限 2 现象/6 变量/24 合并边，不作正式实验规模或模型性能比较。全部原结果由真实模型生成且未经人工改写。两图均保留实际反馈环。

当前结果状态为 generated_only。没有 Docker，所以未执行这 12 个真实模型生成函数，也未生成对应真实数值序列；可执行图各为零节点。不能把结构有效或实现状态 implemented 称为计算已验证。两次实际隔离探测明确拒绝执行，不是函数计算失败。未来数值验收需要隔离环境或真正的人工审查及精确代码哈希批准。

离线双种子执行使用明确标注的人工测试替身，只证明软件契约和真实数据访问；不冒充上述 LLM 代码执行。数学定义及实现科研质量也不由 AST/字段检查自动证明。所有候选边仍为未经统计验证的语义假设。

## 核心改动

- inputs.py：保留原检查并增加参数来源、整数时间及重复模型快照校验。
- data_schema.py（新增）：实际公共字段、原字典、嵌套 JSON 结构、多运行差异及 Schema 哈希。
- prompts.py、schemas.py：2.0 六类任务、required_data、实现状态、三类方向与非 DAG 结构。
- code_contract.py（新增）：静态实际访问、声明字段及未解析访问报告。
- generation.py、pipeline.py：六类独立调用、十二步状态、Schema 身份、恢复与完整来源。
- graph_export.py：三类边合并/去重来源、反馈/孤立节点、逐运行状态与诱导子图。
- indicator_runner.py、trusted_worker.py：仅投影声明列，保留原生成代码和适配器哈希；不改变安全默认。
- config.py、llm_client.py、streaming.py：可选 SSE、完整/残缺响应保留、连接中断重试及严格配置。

## 复现、归档与提交

```powershell
python -m pytest -q --junitxml=causal_graph/results/v2_regression_final.xml
python -m causal_graph.tests.validate_logs --output causal_graph/results/new_v2_offline
python -m causal_graph --config causal_graph/configs/deepseek_flash.yaml --pipeline-config causal_graph/results/v2_live_20261106/pipeline.yaml --run-dir results/<run_id> --generate-only
```

真实调用本机完整输出在 causal_graph/results/v2_live_20261106/{fish,covasim}/；公开便览和完整压缩归档在 causal_graph/examples/v2_live_20261106/，包含原始 SSE、所有提示词、解析、代码、Schema、调用元数据、检查点、图和缓存恢复。压缩前核对全部产物哈希及方法源码哈希；不含真实密钥。详细每阶段耗时、Token 与旧失败记录区分见 LIVE_LLM_TEST_REPORT.md。

实验在提交前真实执行，元数据保留当时基准提交、dirty 状态和逐文件源码 SHA-256；没有伪装成最终提交后复跑。最终提交以 Git 和交付回复为准。工作区没有可逐句核对的论文正文，方法文档对应本轮确认的两部分结构，不宣称已与未提供稿件逐句一致。
