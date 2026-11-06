# 第一阶段输出契约（1.0）

机器可用 JSON Schema 定义在 `schemas.py` 的 `SCHEMAS`、`GRAPH_SCHEMA` 和 `EXECUTABLE_SCHEMA`，每次实验另外导出 `schemas.json`。生成 Schema 的对象均拒绝额外字段，尤其不会接受伪造的 p 值、强度、时滞和干预等级。

|文件|含义|
|---|---|
|experiment.json|实验 ID、场景及版本/哈希、供应商与模型配置、客户端模式、源码/依赖/Git、身份指纹、开始结束时间、调用历史|
|inputs.json|每条输入绝对路径、manifest、真实行数、实际快照/事件步及每个数据/元数据文件的 SHA-256|
|scenario.md|仅当前固定场景的文本副本；原始字节哈希在来源中保存（文本副本可能使用平台换行）|
|generation/phenomena/parsed.json|`phenomena: [{phenomenon_id, name, description}]`|
|generation/indicators/parsed.json|`indicators: [{indicator_id, phenomenon_id, name, scale, description, mathematical_definition, units, computation_notes}]`|
|generation/codes/parsed.json|`codes: [{indicator_id, required, config, python_code}]`|
|generation/edges/parsed.json|`edges: [{edge_id, source, target, semantic_rationale, relation_type}]`|
|generation/*/attempt_NNN/|完整实际提示词、原始响应、解析对象、结构检查、供应商 transport 请求/原始 envelope/用量/实际模型/耗时及错误|
|candidate_graph.json|完整候选图，含 schema_version、evidence_status、phenomena、nodes、edges；不因执行失败删除原节点/边|
|candidate_graph.graphml|与完整候选图一致的节点与边，供简单检查|
|indicator_code/<id>.py|实际模型生成代码，节点保存其 SHA-256 与来源调用|
|execution/<run>/<id>/attempt_NNN/|指标模式、来源数据哈希、代码哈希、审查记录（若有）、原始返回 Parquet、执行错误与数值检查|
|indicator_series/<run>/<id>.parquet|成功计算结果，列为 run_id, indicator_id, step（int64）, feature（string）, value（numeric，可缺失）|
|execution_report.json|所有输入运行×所有指标的最新状态，包括 success/failed/not_executed，无选择性删失败|
|executable_graph.json/.graphml|在所有输入运行均成功的节点及其原有边；额外保存 run_ids、execution_policy、excluded_nodes、excluded_edges、nodes_without_complete_path|
|per_run/<run>/executable_graph.json/.graphml|只要求本运行计算成功的子图|
|structure_report.json|通过的结构检查项目与各阶段原始调用路径；失败的逐尝试检查始终在 generation 内|
|pipeline_report.json|本次十步输入、输出、状态、错误及时间；完整历史在 invocations/<invocation_id>/|
|artifact_hashes.json|最终产物 SHA-256（清单本身不自引用）|

## 节点、路径和后续阶段读取

节点 `node_id == indicator_id`，其余字段保留所有定义、数学式、代码、`required/config`、`code_file/code_sha256/generation_call`。ID 限 ASCII 字母开头，后续字母、数字、下划线或连字符，最长 80 字符，不能包含路径。所有边 `relation_type="semantic_candidate"`。全图 `evidence_status="unvalidated_semantic_candidates"`。

对某现象 e，使用 `phenomenon_id` 过滤节点，取得 V_e；在这些节点间过滤 `edges` 得到 A_e^0，组成完整 T_e。不同现象不跨接。尺度仅为 micro、meso、macro；当前候选图只支持 micro→meso 和 meso→macro，不能把尺度层次当作统计时序或生物学结论。

第二阶段从 `executable_graph.json` 的 nodes/edges 读取机器结构，依据 `execution_report.json` 的 `series_file` 定位每个输入运行的数值，按 `(run_id, indicator_id, feature, step)` 对齐。不同运行不得拼成一条连续时间序列；多 feature 节点须显式选择或联合分析。不得把 `quality.constant` 或可执行状态解释为因果支持。`candidate_graph.json` 保留执行失败的完整假设以供失败审计。

## 保留与限制

原始请求日志不含 Authorization header，配置仅有密钥环境变量名。若供应商响应原文包含精确 API Key，会将该字符串替换为标记并优先避免泄露；不保存密钥。离线替身实验明确记录 client_mode，不填真实模型标识或伪造 token 用量。

代码与图不允许静默人工覆盖；若用户后续进行人工改稿，应另存原版本、修改记录和人工修订身份，不能仍标注纯 LLM 生成。当前模块不提供自动“修正成正确答案”的功能。
