# 两套真实全流程结果

fish/ 和 covasim/ 分别包含：

- scenario.md：与注册原文哈希一致的实际输入。
- stage1_graph.json：实际 LLM 生成、经过逐函数审核并计算成功的候选图。
- final_causal_graph.json：原第二部分实际计算并验证的最终图。
- pipeline_report.json：实际节点/边、调用、重试、种子、时间和失败/排除原因。
- independent_numeric_checks.json：从真实原始日志独立抽查生成指标的结果。
- internal_audit.zip：原始响应、审核、全部尝试、指标 Parquet、实际 GRU 参数及统计证据。

verification.json 汇总图、审核、权重模型和数值复核；full_regression.xml 保存192项测试；SHA256SUMS 校验发布文件。

两套实验各有3个可执行节点、6条候选边；最终 Fish 2节点1条自记忆边，Covasim 1节点1条自记忆边。两者均没有外部边获接受；没有为了显著性重新生成候选。真实数据的主体和多特征准入限制详见 [验收报告](../../docs/ACCEPTANCE_20261107.md)。

原始大型仿真日志未重复上传，仍保留在本地实验目录中，归档记录其 SHA-256。绝对路径记录的是验收机器位置。重新生成实验会产生新的运行 ID 和新的 LLM 响应；本归档用于核对实际产物，不承诺重新调用模型得到字节相同结果。
