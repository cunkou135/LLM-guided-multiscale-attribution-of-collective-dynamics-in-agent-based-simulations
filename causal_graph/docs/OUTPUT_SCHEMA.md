# 第一部分输出契约 2.0

机器结构在 schemas.py 的 SCHEMAS、GRAPH_SCHEMA、EXECUTABLE_SCHEMA；每个实验保存 schemas.json。模板版本为 observed-schema-three-directions/2.0，包版本为 2.0.0。旧 1.0 输出不自动转换或覆盖。

|文件|含义|
|---|---|
|experiment.json|实验 ID、模型与场景、Schema 版本/哈希、配置、依赖/源码/Git、调用历史与状态|
|inputs.json / scenario.md|真实来源目录、manifest、行数、时间范围、输入哈希与固定想定|
|data_schema.json|全部输入运行公共且类型一致的原始表/字段、字典说明、标识、时间粒度、关联键、缺失状态及已检查的 JSON 结构；无观测值|
|data_schema_audit.json|每运行 Schema、独有字段/类型/含义/嵌套结构差异和共同 Schema 哈希|
|generation/phenomena/|phenomena: phenomenon_id/name/description|
|generation/indicators/|indicators: indicator_id/phenomenon_id/name/scale/description/mathematical_definition/units/computation_notes/required_data|
|generation/codes/|codes: indicator_id/required/config/python_code/implementation_status/failure_reason|
|generation/edges_upward/、edges_downward/、edges_intrascale/|独立原始 edges 集合，可为空|
|generation/*/attempt_NNN/|实际 prompt、response、parsed、validation、input_provenance；transport 保存每次请求及完整原 envelope 或 SSE、用量、模型、耗时及错误|
|edge_merge_report.json|原始/去重数量与每个重复项来源|
|indicator_code/<id>.py|原始生成函数，仅已实现变量有文件，不写入人工替代代码|
|execution/<run>/<id>/attempt_NNN/|原始返回、执行模式、数据/代码/适配器哈希、审查（若有）和失败详情|
|indicator_series/<run>/<id>.parquet|run_id、indicator_id、step、feature、value；每运行独立|
|candidate_graph.json/.graphml|所有原始定义及候选关系，包括不可用和执行失败变量|
|executable_graph.json/.graphml|所有指定运行计算成功节点及原有边；excluded_nodes/edges 保存排除原因|
|per_run/<run>/executable_graph.*|单运行成功子图|
|structure_report.json|引用、方向、字段、代码与全部阶段结构检查|
|execution_report.json / pipeline_report.json|所有变量×运行状态、十二步状态；invocations 保存历史|
|artifact_hashes.json|产物 SHA-256（不自引用）；不存在的结果不会补造|

节点 node_id==indicator_id，保留全部定义与代码字段，额外 code_file/code_sha256/generation_call/execution。不可实现时 python_code/code_file/code_sha256 为 null，implementation_status=unavailable 且有具体原因；已实现时 failure_reason=null。execution 按 run_id 记录 success、failed、not_executed 及序列或错误。数据 Schema 以 type_observation 和 nullability_source 说明何者实际可确认，未知语义为 unknown；嵌套结构明确采样范围及非穷举。

原始边必含 edge_id、source、target、scale_direction（upward/downward/intra_scale）、semantic_rationale、relation_type=semantic_candidate。合并边额外保存 source_phenomenon、target_phenomenon、generation_sources（stage/call/original_edge_id/row_index）。相同端点只合并来源，不产生新作用；反向边独立保留。自环拒绝，循环不拒绝。不要求完整路径或单一现象内连接。

可执行图允许零节点或零边。第二部分直接读取 nodes/edges 和 execution 中的 series_file，按 (run_id, indicator_id, feature, step) 取数，不重新解析自然语言，不将不同种子拼接。边始终 evidence_status=unvalidated_semantic_candidates，不含 p 值、时滞、强度或干预证据。

原始 SSE 逐行保留；没有 [DONE] 或终止原因就视为中断，不把残缺 JSON 当完整响应。请求不记录 Authorization。精确 API Key 若出现在返回中会脱敏，配置仅保存环境变量名。人工修订须另存原版本及修改身份；不能覆盖原始代码后仍标作自动生成。
