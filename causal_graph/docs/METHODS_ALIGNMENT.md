# 第一阶段代码与论文 Methods 对应

本轮实现依据用户确认的新方法规格。当前 `Nature Communication` 工作目录只有平台与历史平台副本，排除虚拟环境后没有论文正文 DOCX/TeX/PDF；因此**未完成与某份现有论文 Methods 原文的逐句核对，也不能声称完全一致**。不修改任何原论文。以下可用于撰写或核对 Methods。

|论文对象或步骤|代码实现|保存位置|
|---|---|---|
|固定想定 s，版本与哈希|inputs.inspect_run，复用 scenarios.protocol.load_scenario|inputs.json、experiment.json、scenario.md|
|候选宏观现象集合 E|generation.identify_phenomena|generation/phenomena/parsed.json 的 phenomena|
|每个现象的 V_micro ∪ V_meso ∪ V_macro|generation.define_indicators|generation/indicators/parsed.json，节点 scale 与 phenomenon_id|
|语义定义、数学定义与单位|indicators 的 description/mathematical_definition/units/computation_notes|完整候选图各节点及变量生成响应|
|LLM 自主生成计算代码|generation.generate_codes|generation/codes/parsed.json，indicator_code/<indicator_id>.py|
|从原始观测计算 Z(t)|indicator_runner.execute_indicator，复用 Trajectory.compute_isolated；明确审查后可用 compute|indicator_series/<run_id>/<indicator_id>.parquet，含实际 run_id/step/feature/value|
|原始候选边 A_e^0|generation.propose_edges|generation/edges/parsed.json 的 edges，逐边语义理由|
|T_e = (V_e, A_e^0)|graph_export.assemble_graph，按 phenomenon_id 取节点及对应边|candidate_graph.json，candidate_graph.graphml|
|结构校验|schemas.validate_stage / code_errors|generation/*/attempt_NNN/validation.json、structure_report.json|
|计算有效性校验|indicator_runner.check_result|execution_report.json 及完整执行尝试|
|可执行候选图|graph_export.executable_subgraph|executable_graph.json，全输入运行成功的诱导子图；per_run 保存逐运行版本|
|交给第二阶段的机器输入|nodes.node_id==indicator_id、edges.source/target、execution_report.series_file|executable_graph.json + execution_report.json + indicator_series/|
|可追溯模型调用|llm_client.LLMClient、generation.generate_stage|prompt、原始响应 envelope、配置摘要、实际模型标识、usage、时间；不记录密钥|

## 应从旧稿删除或改写的设定

1. 若旧稿将“预先固定的 28 个可执行观测指标”作为候选库，应改为：LLM 仅据固定自然语言想定自主提出宏观现象及三尺度变量，并生成每变量语义、数学定义和 Python 函数。不得把原库数量或名称写为本方法必选项。
2. 若旧稿让 LLM 读取原始轨迹、字段列表、模型源代码或人工参考机制，应改为场景文本与通用接口契约；实际字段及数据仅在 Python 执行阶段校验。
3. 若旧稿将常数、缺失或代码失败视为变量不重要或边无因果性，应改为计算状态；失败假设保存在原始候选图中，可执行图仅表示能计算。
4. 若旧稿在第一阶段报告 Granger、Bootstrap、显著性、时滞、因果强度或干预支持，应移动到后续相应阶段。本轮没有实现这些算法。
5. 若旧稿将 LLM 语义边称为“已识别/已验证因果网络”，应改称“未验证的跨尺度语义候选有向关系”。完整路径检查只是结构约束，不能识别真实机制。
6. 若旧稿声称所有生成代码均在隔离环境成功执行、或本轮完成真实 LLM 端到端验证，应依据真实实验重写：当前机器无 Docker，默认执行拒绝；日志验证使用明确审查的人工测试替身。按用户指示本轮仅保留 API 接口，未运行真实模型。

## 可用的方法描述框架

第一阶段依次调用同一已配置 LLM 生成现象、变量、函数和边。模型输入严格限于当前固定想定、通用约束及该生成链先前的语义定义。程序校验引用、尺度与完整路径，不修补或新增边。函数通过统一 Trajectory 接口读取原始观测，失败与有效性状态逐一登记；在完整原始图之外导出由成功计算节点诱导的可执行图。该图仅作为下一阶段时序关系检验的候选输入。

此框架仍需结合作者实际选择的模型、参数、重复实验设计和随后得到的真实 LLM 结果补充，不构成已经完成的方法效果验证。
