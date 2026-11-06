# 第一阶段方法代码中文验收报告

日期：2026-11-06。工作仓库 `abms_lab`；开发前本地与 fetch 后 GitHub 最新 main 同为 `5d3ee5372b4fbb22fb0803ba6f521ed0cba70d18`。最终发布提交以 Git 历史及交付回复为准。实验在提交前执行，manifest/experiment 记录当时基准提交和 dirty 状态，未伪装成提交后运行；方法源码逐文件 SHA-256 已核对归档。

## 已交付功能

- 独立 `causal_graph` 包、`python -m causal_graph` 入口、双模型档案 YAML 与严格配置校验。
- 四次可检查的模型生成步骤：候选现象、三尺度变量与数学定义、每指标 Python 函数、语义边。没有固定 28 指标库或预设科学答案。
- 仅向模型提供固定想定、通用约束/Schema 与本次此前生成的语义定义；不传实际字段目录、日志、源码或旧候选图。
- 输入完整性/场景固定版本及 SHA-256/数据校验和/行级来源校验；支持 run_id、目录及同场景多个轨迹。
- JSON Schema、唯一性、引用、尺度方向、完整路径、签名与语法检查；非法响应、重生成和失败原文保留。
- 默认公开 Trajectory Docker 隔离接口；明确审查及代码哈希批准后可选可信进程模式；默认不回退。
- 真实指标时间序列、数值/时间/缺失/常数检查；完整原始候选图、共同可执行图、每运行子图及 JSON/GraphML。
- 调用配置、完整提示词、原始供应商响应、实际模型标识/usage/耗时（若供应商提供）、代码及数据哈希、执行状态、十步报告、中断恢复和逐尝试历史。
- README、安装说明、可复现命令、Schema、方法对应与明确标记的离线示例。

## 实际测试结果

|检查|真实结果|证据|
|---|---|---|
|开发前原平台回归|48 passed，89.95 秒|docs/validation/baseline_pytest.xml|
|首次完成的新模块测试|56 passed，9.25 秒|开发时实际 pytest 输出；随后增加真实日志与超时检查|
|最终全套回归|107 passed，109.74 秒，0 失败|docs/validation/full_regression_final.xml|
|其中新增测试|59 项，包含实际 Fish/Covasim 日志、缺失字段、可信执行、超时/异常、结构错误、配置、模型切换、HTTP 离线替身、原文保存、恢复和图导出|causal_graph/tests/|
|独立双种子真实日志验收|passed；Fish/Covasim 各 6 次测试函数成功、2 次预期缺字段失败|examples/offline_acceptance_20261106/validation_summary.json|
|额外原始数据访问|Fish raw_frames、Covasim events 的已审查测试函数实际执行成功，与直接读取值相同|示例中的 *_additional_raw_check/|
|隔离能力实测|调用 compute_isolated 明确失败：Docker unavailable；未执行不可信代码|示例中的 *_isolation_probe/|
|安装与入口|可编辑安装成功；独立命令行帮助正常；科学依赖可导入|实际 pip install、--help 与运行记录|
|产物与源码追溯|两份示例逐项产物哈希通过，方法源码 SHA-256 与归档 software.source_sha256 一致|artifact_hashes.json、experiment.json|

最终回归命令：

```powershell
python -m pytest -q --junitxml=causal_graph/results/full_regression_final.xml
```

独立验收命令（不需要 API Key，不会调用真实模型）：

```powershell
python -m causal_graph.tests.validate_logs --output causal_graph/results/acceptance_release_20261106
```

该输出目录已存在时应改为新目录名，不覆盖历史实验。

## 本次新建的真实运行

|模型|种子|run_id|规模|真实更新步|
|---|---|---|---|---|
|Fish/fish-3.0|42|24795f0cb68a4c7e8817283112c75322|2000 鱼、5 鲨鱼|5|
|Fish/fish-3.0|43|6ac1b06bafbf43a7b699c9e0914e2ea0|2000 鱼、5 鲨鱼|5|
|Covasim/2.0.0|8|85b0484a757140c9a5ec99924b2f8ef1|1000 人、原生 hybrid|5|
|Covasim/2.0.0|9|5c3641986b124557bcf5d88d16c1eb6e|1000 人、原生 hybrid|5|

Fish 整套双种子工程验收约 11.719 秒，Covasim 约 22.234 秒，包含运行、日志检查、生成替身、可信执行与输出；不是 LLM 性能或仿真性能基准。Schelling 保留兼容性测试，且实际检查已有 8 快照运行。混合 Fish/Covasim 输入会在生成前拒绝。

所有场景均复用原平台 `RunSession/run` 与 `Trajectory`；没有修改 simulations、scenarios、logging 的核心规则。5 步是工程验证预算，不能称为默认 1000 步鱼群或 60 天 Covasim 的完整科学实验。既有 20 步 Fish 和 60 步 Covasim 原始日志另在需求评审阶段核对，见 existing_inputs_audit.json。

## 修复过的开发问题

首次新测试发现 2 个失败：Series 转长表时数值列名 `value` 与 Pandas melt 参数冲突；已改为明确构造长表，并完成回归。首次全目录收集发现 4 个模块名冲突：运行产物中的 `test_*.py` 被 pytest 误收集；已将 pytest 默认范围限定为正式测试目录，同时从安装包排除运行与示例目录，避免生成代码被测试或打包工具误加载。所有最终结果以上表真实复跑为准。

可信工作进程禁用代码缓存写入，源码/归档设置字节保留，避免跨平台换行或临时缓存破坏代码与产物的哈希审计。中断调用、非法 JSON、缺字段、代码异常、超时及审查哈希不匹配均有自动化验证；失败记录不通过补零、指标替换或新增边消除。

## 验收边界

按用户本轮指示，只留好真实 LLM API 配置与调用接口，**未进行真实供应商/模型端到端验证**。HTTP 行为采用离线响应测试；原始示例 `actual_model=null`，不伪造模型标识、token 或生成结果。示例中的人工响应、变量和图只验证软件契约，不是科学发现、第一阶段方法效果或模型优劣证据。

当前机器无 Docker，因此容器成功执行与安全隔离效果尚未端到端验证。默认模式已实际验证拒绝执行。可信模式仅用于已逐份审查的人工测试代码；普通子进程、超时和 AST 检查不等同安全沙箱。科学指标定义、公式实现与模型生成质量仍需真实研究实验及人工审读；通过数值检查不证明因果关系。

工作目录没有可核对的当前论文正文，因此 METHODS_ALIGNMENT.md 给出对象对应和旧设定应改写项目，未声称与某份稿件逐句完全一致。本轮没有实现或修改第二、第三阶段算法。
