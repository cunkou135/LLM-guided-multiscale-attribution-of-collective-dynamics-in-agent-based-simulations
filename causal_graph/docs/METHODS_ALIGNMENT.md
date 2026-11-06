# 论文两个核心部分与实现对应（2.0）

第一部分为 LLM 跨尺度候选因果图生成，第二部分为后续时间序列因果判别。本轮仅实现第一部分，不设置独立干预验证阶段，也不实现第二部分的统计、方向或时滞算法。当前工作目录没有论文正文可逐句核对；本说明对应本轮用户确认的 Methods 规格，不声称与未提供的稿件完全一致。

|论文对象|实现|输出|
|---|---|---|
|固定想定及真实可用结构|inputs.inspect_runs、data_schema.build_data_schema|inputs.json、scenario.md、data_schema.json、data_schema_audit.json|
|候选现象集合 E|generation.identify_phenomena|generation/phenomena/parsed.json；仅想定输入|
|多尺度变量 V|generation.define_indicators|三尺度定义、数学式、单位、计算窗口与 required_data|
|可执行观测函数|generation.generate_codes|原始生成代码、required、config、implementation_status/failure_reason|
|向上集合 E_up|generation.propose_upward_edges|generation/edges_upward/parsed.json|
|向下集合 E_down|generation.propose_downward_edges|generation/edges_downward/parsed.json|
|同层集合 E_intra|generation.propose_intrascale_edges|generation/edges_intrascale/parsed.json|
|G_0=(V,E_up∪E_down∪E_intra)|graph_export.merge_candidate_edges / assemble_graph|candidate_graph.json/.graphml，去重及原始调用来源|
|真实观测序列 Z(t)|Trajectory.compute_isolated 或明确审查后的 compute；字段投影适配|indicator_series/<run>/<id>.parquet、execution_report.json|
|可执行候选结构|graph_export.executable_subgraph|executable_graph.json/.graphml、per_run/<run>/|
|第二部分输入|节点 ID 与序列 ID 严格一致；边含尺度分类和来源|读取可执行图与数值序列，不能把边当成已验证结果|

必须从旧稿更新的设定：不再禁止 Schema 进入变量/代码提示词；不再要求仅有 micro→meso→macro 完整路径；允许直接跨尺度、向下反馈、同层作用、循环和跨现象关系。仍禁止固定 28 指标库、人工参考图、原始数值/源码注入以及人工改图冒称 LLM 输出。

三类边任务分别判断，输入相同的想定与变量定义，互不查看其他方向的生成结果。本地去重不等于重新推断或筛选因果关系。数学聚合关系与动态作用必须在语义理由中区分，但当前均为待判别假设。不能报告第一部分已经获得 p 值、因果强度、时滞或干预支持。

实现不可用、执行失败、缺失和常数均作为计算状态；它们不证明候选关系成立或不成立。完整图保留失败节点/边，可执行图只是计算成功节点的诱导子图。真实 LLM 生成成功、代码结构有效与实际隔离执行成功是不同证据，报告分别计数。

## 执行实现更新

本轮只将已生成函数的执行落实为显式 trusted_reviewed 本地子进程；无须 Docker，不重新生成任何变量/边。生成模型、数学定义和原函数字节保持原样。--execute-only 验证检查点及图语义，执行软件版本与原生成版本分别保存。

主体级观测保留 entity_id。对逐事件量擅自做每步均值的实现，本次不作批准；运行级标量的原生广播结果保留但明确只有一个独立估计。真实局部协方差近奇异和未定义类别缺失均登记为验收问题，未通过改值、删列或放宽容差制造成功。完整图保留失败节点和原边，可执行图仅含实际计算并通过验收的节点。
