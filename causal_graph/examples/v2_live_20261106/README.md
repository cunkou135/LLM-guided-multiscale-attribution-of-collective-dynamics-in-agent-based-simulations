# 真实 DeepSeek Flash 生成记录（2.0）

这是 2026-11-06 实际供应商响应，不是人工测试替身。六类任务均返回模型标识 `deepseek-flash`。固定想定来自原运行目录，变量/代码任务使用完整真实公共 Schema；原模型结果未人工改写。

|场景|现象|变量（微/中/宏）|向上/向下/同层边|实现且通过结构检查|实际执行|
|---|---|---|---|---|---|
|Fish|2|6（2/2/2）|6/6/3|6|0，6 份未执行|
|Covasim|2|6（2/2/2）|7/7/6|6|0，6 份未执行|

两个候选图都包含反馈环。实际状态为 generated_only。无 Docker，隔离探测明确拒绝执行；不能据此声称指标数值或整个计算流水线已验证。可执行图是零节点空图。isolation_probes/ 保留真实拒绝记录。

fish/ 和 covasim/ 提供便于浏览的图、Schema 和结构报告。`*_complete_experiment.zip` 包含完整实验原文件，包括全部实际提示词、原始 SSE（含中断内容）、解析、检查点、代码、来源哈希、逐调用模型/用量/耗时、生成报告及命令行缓存恢复记录。压缩包内 artifact_hashes.json 核对原文件，外部 archive_sha256.json 核对压缩包。没有省略失败响应，也没有保存 API Key。

实际配置为 temperature=0.3、max_tokens=32768、reasoning_effort=low、timeout=600、max_retries=1、stream=true；每场景上限为 2 个现象、6 个变量、24 条合并边，仅做功能验证，不代表论文正式实验规模或参数最优。Fish 向上关系有一次不完整流，按上限重试后成功；其余语义输出均通过第一次结构检查。

测试使用运行 Fish `2a815b4dfe4f47b8ac2416fac04456e5`、Covasim `3249f90463154305aed53504106b3dae`，原始数据不随示例重复提交；来源哈希在 inputs.json。复制到其他机器后原绝对路径不会自动有效，需生成自己的仿真运行并通过标准 CLI 指定。

在本机具备这些原运行时，可用用户原配置文件重新生成新的独立实验（会产生真实 API 调用）：

```powershell
python causal_graph/examples/v2_live_20261106/test_supplied_config.py fish --output-root causal_graph/results/new_v2_real_test
python causal_graph/examples/v2_live_20261106/test_supplied_config.py covasim --output-root causal_graph/results/new_v2_real_test
```

该辅助脚本在进程内读取既有私有配置的密钥，只把无密钥 YAML 和安全审计写到输出目录。也可使用标准 CLI 与环境变量档案。不得将此记录的代码哈希自动批准给可信执行模式，未来执行仍须实际人工审查。
