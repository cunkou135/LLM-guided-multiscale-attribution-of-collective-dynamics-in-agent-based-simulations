# 第一阶段流水线与错误处理

|步骤|输入|实现|输出与失败处理|
|---|---|---|---|
|1 固定想定|完成运行目录或 run_id|inputs.inspect_runs / inspect_run|核对 manifest、resolved_config、注册场景及字节哈希、Parquet 哈希、目录字段、行级来源和时间范围；不完整或混合版本直接拒绝|
|2 宏观现象|当前场景自然语言|generation.identify_phenomena|生成 phenomena，数量由模型确定且受 YAML 上限约束|
|3 变量定义|想定、本次现象|generation.define_indicators|indicators 含所属现象、三尺度、数学定义、单位、计算说明|
|4 计算函数|想定、本次定义、通用 data 契约|generation.generate_codes|每指标独立 compute_indicator(data, config)、required、config；保存原始代码|
|5 语义边|想定、本次语义定义|generation.propose_edges|semantic_candidate 边与逐边理由；不输入计算结果或统计证据|
|6 结构检查|四份结构化输出|schemas.validate_stage / graph_export.assemble_graph|严格 Schema、唯一性、引用、尺度方向、完整路径、签名、语法和基本代码约束；任一节点须位于完整 micro→meso→macro 路径|
|7 指标执行|通过检查的函数、实际轨迹|indicator_runner.execute_indicator|默认 Trajectory.compute_isolated；缺 Docker 拒绝，可信模式须明确批准代码哈希。失败逐指标保存，不影响其他指标计算|
|8 计算有效性|返回 Series/DataFrame|indicator_runner.check_result|唯一且明确的整数 step、实际记录时间、数值列、有限值、观测数；常数及高缺失警告，不做相关筛选|
|9 候选图导出|原始图与执行状态|graph_export.export_graphs|完整原始图、共同可执行诱导子图、每运行诱导子图；逐一记录失败节点与受影响的原始边|
|10 实验记录|所有步骤|pipeline.run_pipeline / io.save_json|前后输入哈希校验、软件版本、源码/Git、提示词、原始响应、执行尝试、图、时间及产物哈希清单|

## 实际数据契约

只通过 `simulations.common.trajectory_api.Trajectory` 访问数据。`required` 是 LLM 提议的表→字段映射，不包含模型事先提供的特定字段库。`Trajectory.compute` 和 `compute_isolated` 都把真实表副本作为 `data` 字典传入。约定表名为 `agent_states/events/contacts/raw_frames/model_states`；实际缺少某张表或某个字段时记录缺失，不补造。一个指标函数原样应用于所有输入随机种子，不针对运行重生成。

函数返回索引名为 `step` 的 Series，或含 `step` 列/索引的 DataFrame。多个数值列使用 `feature` 区分。最少非缺失观测数由 `min_observations` 控制（默认 3，只是工程底线，不代表足够做统计推断）；某一列不足即整个指标失败。无限值、重复/分数时间、未经记录时间点和非数值返回失败。常数不删除；缺失比例超过阈值仅警告。原始返回数据先保存，之后即便有效性失败仍可检查。返回值无时间说明时不会把默认整数索引猜作 step。

## 生成与恢复

每个阶段单独调用模型并保存 `prompt.json/response.txt/parsed.json/validation.json`。结构错误可按 YAML 重生成，重新请求仍使用相同想定与通用约束，不增加错误反馈、源码或真实答案。JSON 解析失败也保存原文和结构化错误。传输失败的每次供应商响应保留在 `transport` 下；不因错误格式丢弃 envelope。

每个通过校验的阶段保存内容与请求哈希 checkpoint。恢复检查完整原响应、解析对象、模型/输入/源码指纹；不匹配时拒绝而不覆盖原来的成功实验状态。执行尝试在 `execution/<run>/<indicator>/attempt_NNN/` 追加；恢复会重新执行指标，当前序列指向最新成功计算，历史返回值和失败详情不删除。`invocations` 保留每次调用报告。

## 解释边界

字段校验和正确返回仅表明数据可读及计算有效；不能自动证明公式的科学意义、是否误用了未来计划日期、实现是否完全符合定义，或候选边的真实性。基本 AST 检查不是程序形式化验证，也不能替代隔离和人工科学审查。第一阶段不会实现统计关系检验或干预验证。共同可执行图要求每个节点在每条输入运行中成功；失败可使完整路径断裂，断裂节点显式列出而不修补边。
