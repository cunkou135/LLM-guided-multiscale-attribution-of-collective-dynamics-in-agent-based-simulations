# 第一阶段需求评审（2026-11-06）

## 已实际核查的代码与输入

基线 HEAD 与 fetch 后 origin/main 均为 5d3ee5372b4fbb22fb0803ba6f521ed0cba70d18，原工作区干净。当前根目录 abms_lab 是指定 GitHub 仓库；旁边 pt 是另外的历史副本，不用于本次开发。GitNexus 现有索引仅包含 Mesa 与 Repast，没有本仓库，因此以实际源码、日志和测试为依据。

实际模型：fish/fish-3.0（迁移原生引擎），covasim/2.0.0（Python 3.10 独立环境），schelling_standard/1 与 schelling_extended/2.0（Mesa 3.5.2）。不修改这些实现。

实际读取并核对三个已有运行的所有 Parquet SHA-256 与 manifest，一致：

|模型|run_id|固定想定版本|实际状态快照|主体行|事件行|接触行|
|---|---|---|---|---|---|---|
|Fish|2a815b4dfe4f47b8ac2416fac04456e5|1.0|21（0–20）|42105|40100|393665|
|Covasim|3249f90463154305aed53504106b3dae|2.0|61（0–60）|61000|5639|1078175|
|Schelling extended|3b1b5e8b6f9a41d695988be12ab8c060|2.0|8（0–7，frozen）|67992|59493|不适用|

Fish raw_frames 21 行，实际通过 read_frame(0) 回读原始字典，保留 decision_input/decisions/contacts 等字段。Covasim 实际事件为 481 次 infection、4957 次 state_transition、201 次 test；contacts 层为 h/s/w/c。不是未成功传播尝试。Covasim step 0 是 simulation_day -1，禁止将未来计划日期当作已发生事件。

固定想定来自 scenarios.protocol.load_scenario 注册表：Fish 1.0 SHA-256 f2714fa2fd10ebc949f2f91843387ad5965f6eca75a4cb60496a4f6c7642a936；Covasim 2.0 SHA-256 50bcd64c7fbd6ca511fa899e452450013a0a59db3ec235b5b7350ec53f381cde。与运行目录 scenario.md 字节哈希一致；只将当前场景文本交给 LLM。

## 复用接口与边界

唯一数据访问入口 simulations.common.trajectory_api.Trajectory：metadata、configuration、catalog、read、available_steps、source_fingerprints、compute、compute_isolated。compute 接收经过审查的函数、required 表字段映射、config，data 是表名到 Pandas DataFrame 的映射；compute_isolated 接收代码文件，同一函数签名，Docker 默认拒绝回退。

compute_isolated 已有禁网、只读挂载、非 root、能力剥离与资源限制。当前机器未找到 Docker；原报告也只验证缺少 Docker 时拒绝执行。新模块必须实际调用并记录该限制，不将普通子进程或 AST 检查称为隔离。可信模式必须显式选择并提供代码 SHA-256、审查者及审查说明；不会由流水线自动批准。

## 开发前验证

开发前原平台 tests 已实际重新执行：48 passed，89.95 秒，证据为 docs/validation/baseline_pytest.xml。该结果不是从旧报告抄录。测试覆盖单次 Fish/Covasim 的真实运行及日志读取；本轮另保存真实日志审计和双种子指标执行证据，见 VALIDATION_REPORT.md。未发现阻断性的仿真或数据接口错误。

在当前论文工作目录（排除环境及历史平台副本）未发现论文 DOCX/TeX/PDF 正文；不得声称已经核对到旧稿。METHODS_ALIGNMENT.md 必须明确该限制，并列出固定 28 指标等旧设定与本次要求的差异。此次需求文本是实现规格，论文文件不改写。

## 本次实现范围

独立 causal_graph 包：固定场景验证 → LLM 现象 → 三尺度变量及数学定义 → 独立计算代码 → 语义候选边 → 严格 Schema/引用/路径/代码检查 → 隔离执行或明确审查的可信执行 → 数值完整性报告 → 原始图与可执行子图 → 完整实验溯源。

LLM 不接收实际 field_catalog、日志、源码、已有指标、人工图或数据反馈。通用 data 契约可用于指定预计需要的表字段；缺失时记录失败，不自动映射或伪造。离线测试中的人工响应仅标为测试替身，不作为 LLM 科学结果。

不实现统计边筛选、Granger、Bootstrap、时滞估计、参数干预或因果确认。可执行图只删除计算失败节点及其原有边，完整失败记录保留；多个运行的共同可执行图要求每条运行均成功，另提供每运行子图。
