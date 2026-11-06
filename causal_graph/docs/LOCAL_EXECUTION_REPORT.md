# 本地可信执行验收报告（2026-11-06）

## 结果

没有安装或使用 Docker、容器、额外执行环境；使用当前 Python 3.12 独立子进程和原 Trajectory 接口。没有读取 API Key 或调用 LLM。原 Fish/Covasim 的 12 个函数、变量数学定义、原始响应与全部 35 条候选关系保持原样，逐文件 SHA-256 在执行前后核对通过。

|场景|函数总数|审查批准|审查拒绝（未执行）|实际子进程返回|验收通过|结果验收未通过|可执行图|
|---|---|---|---|---|---|---|---|
|Fish|6|6|0|6|5|1|5 节点 / 9 边|
|Covasim|6|4|2|4|3|1|3 节点 / 3 边|
|合计|12|10|2|10|8|2|8 个可执行节点|

因此，12 个指标中 8 个通过，4 个未通过（2 个审核拒绝、2 个实际结果未通过）。实际函数进程没有异常或超时；两项结果问题不是 Python 进程崩溃。审核拒绝项没有被批准或执行，也没有用其他指标代替。

## 四项未通过及具体原因

1. Covasim `sic_micro_prior_setting_degree`：定义要求逐感染事件 D(e)，原函数却返回每步均值，改变了观测单位，丢失事件级变化；原配置中的补充聚合说明不能替代原定义。未批准、未执行。另缺少定义中的负值哨兵显式排除，但本轨迹 contacts 主体 ID 均非负，未触发该附加问题。
2. Covasim `icts_micro_quarantine_contact_ratio`：定义要求逐隔离起始事件的比值，原函数也改为每步均值。缺失 before 被填 false 的处理还可能与原缺失规则不一致。未批准、未执行。
3. Covasim `sic_meso_layer_infection_contact_ratio`：函数实际返回 61 步、5 列。c/h/s/w 各有 61 个有效数值，`seed_infection` 列没有接触分母，61 个值全部 NaN。整项指标未满足每 feature 至少 3 个有效观察的原验证要求。没有删除该列来制造成功；完整原返回、244 个有效数值及缺失均保留。独立公式检查显示值本身符合 I/C 及零分母未定义规则，失败是完整输出的有效观察不足。
4. Fish `elong_meso_local_eigen_ratio`：21 步中 19 个有限值，初始两步无有效接触邻域为 NaN。第 13 步原函数值 21740757.806902323，独立参考为 21740750.81195394，绝对差 6.99494838、相对差约 3.2174e-7，超过预设 rtol=1e-7、atol=1e-9。该帧主体 1532 的三点邻域近共线，协方差特征值约 1.7253e-10 与 4.8800，条件数约 2.8285e10，计算对舍入和邻点顺序敏感。保留原值、失败和诊断；没有放宽容差、截断极值或修改生成代码。

两个被拒绝的微观函数不能通过把每步均值复制回事件来修补，那会捏造事件级观测。本轮不改写它们。

## 八项通过结果

|指标|实际输出|独立验算|
|---|---|---|
|Fish frag_micro_nn_distance|2000 主体 × 21 步 = 42000 值|独立 KD-tree，与生成函数距离矩阵结果一致|
|Fish frag_meso_contact_component_count|21 值|独立稀疏图连通分量，与原 union-find 一致|
|Fish frag_macro_largest_component_fraction|21 值|连通分量人口比例一致|
|Fish elong_micro_axis_alignment|2000 主体 × 21 步 = 42000 值|独立 SVD 主轴，最大绝对差约 3.37e-14|
|Fish elong_macro_global_eigen_ratio|21 值|独立奇异值比，最大绝对差约 1.78e-15|
|Covasim sic_macro_layer_entropy|61 步、57 个有限值|独立熵计算一致，空事件窗口保持 NaN|
|Covasim icts_meso_layer_contact_change|61 步 × 4 层 = 244 值|独立按层前后窗口和中位数一致|
|Covasim icts_macro_city_contact_change_on_quarantine_increase|61 值|独立差分分组均值一致|

最后两个 Covasim 函数按原生成 config 将全程统计量广播到时间轴，均为原始数据计算的标量，不是人为固定值；每 feature 只有一个独立估计，不能当成 61 个独立时序观察。常数警告与 quantity_scope=run_level_scalar_broadcast 明确保留。

初次独立核验曾误将事件的 seed_infection 标签纳入“接触层中位数”参考坐标，后来按原定义仅使用 contacts 层修正参考脚本；原生成代码、配置和数值未变。第一次核验在 local_execution_20261106/ 中保留，最终以 local_execution_final_20261106/ 为准。该修正没有改变严格容差，也没有隐藏真正的全缺失 seed 比值问题。

## 执行改动与审核

- 复用 trusted_reviewed；审核文件包含审核身份、时间、批准函数精确 SHA-256，以及未通过函数原因/哈希。审核由 Codex 按用户明确授权逐份完成，没有伪称人工签名。这里只批准已逐行检查的固定原函数，未来代码不能自动沿用批准。
- 新增 --execute-only --resume。原模型、想定、输入、数据 Schema、模板及生成配置仍一致；只允许执行器源码升级。六类检查点及完整图语义逐一验证，没有模型请求，也没有重新生成变量或边。
- 原生成 identity/software 继续保留；每次本地恢复另存 execution_software.json、输入候选图快照、审核配置和执行日志。
- worker_request.json、process.json、process_result.json、stdout.log、stderr.log、returned_result.parquet 均保留。独立子进程不继承模型密钥环境，执行超时仍受限制。
- 修复结果适配器：具名 (step, agent_id) MultiIndex 保留为 entity_id 长表，不取人口均值，检查每主体时间唯一性与有效数量。标量旧格式保持兼容。
- 独立公式参考只用于验算，没有写入或替代任何指标输出。失败值和原始缺失列完整保留；可执行图严格按最终状态过滤。

## 输出与可视化

原实验继续在 `causal_graph/results/v2_live_20261106/fish/`、`covasim/`，已更新 execution_report.json、indicator_series、executable_graph.json/.graphml、per_run 子图、过程状态及产物哈希。完整候选图依然是 Fish 6 节点/15 边、Covasim 6 节点/20 边；只更新执行状态，不改变原假设。

审核、公式核验和失败诊断在 `causal_graph/results/local_execution_final_20261106/`。公开包为 `causal_graph/examples/local_execution_20261106/`，含两份完整更新实验压缩包、批准/拒绝记录、原始结果、数值审查、无密钥配置和图。

可视化共 12 视图：每模型完整候选图、可执行图、向上/向下/同层分图及逐运行图。提供 SVG、PNG、四主图 overview.png 和可点选定义/边理由的 index.html。失败节点在完整图用灰色虚线边框标识；可执行图只绘实际通过节点。每个图记录真实来源哈希，绘图不修改图语义。所有边仍是未经统计验证的语义假设，不因执行成功变成因果证据。

## 自动化与复现

针对性执行测试 26 项通过；新增实体输出、拒绝执行、仅恢复禁止 LLM、来源升级和缺失检查点测试。全套回归 132 项通过、0 失败；图导出及本地执行针对性复核 6 项通过。JUnit 见 docs/validation/local_execution_regression_132.xml。程序超时与异常日志也有真实子进程测试。没有通过改动原函数、删掉缺失特征或放宽容差消除验收失败。

```powershell
python -m pytest -q
python -m causal_graph.tests.validate_reviewed --audit-root causal_graph/results/new_reviewed_check
python -m causal_graph.visualize_graphs --experiment causal_graph/results/v2_live_20261106/fish --experiment causal_graph/results/v2_live_20261106/covasim --output causal_graph/results/new_views
```

本次不修改仿真动力学、固定想定、原始日志、候选图生成算法或第二部分。Docker 并非本项目本地执行依赖；默认不会悄悄执行未经审查的代码，后续使用显式本地可信配置和审核文件即可。
