# 两阶段代码集成修复

本次修改针对模块之间的调用顺序、数据接口和局部恢复。统一入口为 `python -m full_pipeline`。生产流程复用现有算法，代码集成不要求先完成一套新的正式数据实验。

## 实际执行顺序

1. 根据想定匹配已注册模型，复用已有运行或按配置调用原仿真器；通过公共 `Trajectory` 接口建立真实日志 Schema。
2. 独立调用宏观现象生成，再调用跨尺度变量生成。正式配置执行每尺度最低 4 个、目标 6 个、总预算 30 个的约束。
3. 变量定义同时声明 `analysis_contract`，明确原始观测单位、时间步长、特征、维度、缺失处理及送入第二部分的分析量。
4. 初次按小批量请求指标代码，各函数单独校验、审核和保存。复用原 `trusted_reviewed` 机制，不自动批准 LLM 代码。
5. 已审核函数由现有本地 Python 子进程执行，保留超时、异常和执行日志。对声明了有限过去窗口的函数，可按步分批读取，避免一次加载完整大表。
6. 直接调用原 M1 应用上述契约，检查时间索引、实体映射、输出维度及动态样本覆盖。
7. 对有效变量分别请求向上、向下、同层关系，复用现有合并和导出函数，发布 `stage1_graph.json`。
8. 将该图直接交给 `causal_discovery.pipeline.run_pipeline`，依次执行原 M1、M2、M3/M4 和 M5，发布 `final_causal_graph.json`。

保留原代码审核。删除了开发过程中额外增加的数值证明文件审核暂停点，不要求准备另一套证明材料才能继续生成边。已有检查点和审核记录继续用于恢复，不增加新的安全框架或容器环境。

## 具体修复

| 问题 | 修改后的行为 |
| --- | --- |
| 设置变量上限仍允许正式图只有 3 个节点 | 正式配置的提示词与 Schema 同时落实三尺度最低覆盖；小预算必须显式使用接口测试模式 |
| 执行结束后才发现变量不能进入第二部分 | 变量生成时声明分析契约；实际计算和 M1 接收先于候选边生成 |
| 个体指标被隐式聚合或误当作独立时间样本 | M1 读取预先声明的聚合、固定实体或向量映射，实体数量不作为时间样本数量 |
| 批次中一个函数出错导致其他代码重复请求 | 有效函数先独立保存；只有错误函数进入单独修复 |
| 数学定义错误与代码错误混为一类 | 定义问题局部更新指定 ID；实现问题只更新对应函数；保留其他现象和代码 |
| 准备好第一部分后恢复仍重复组装和执行 | 修复第一部分恢复身份被内层执行身份覆盖的问题，复用已就绪图 |
| 多父节点的单对齐改变 M2 的时间网格 | M3/M4 继续使用 M2 的共同时间网格，时滞保持仿真步单位 |
| 统计不显著可能引发重新生成 | 第二部分不调用 LLM；常数或样本不足明确记录，不按显著性重新生成 |

关键文件为 `full_pipeline/main.py`、`definition_repair.py`、`validators.py`、`stage_manager.py`，以及 `causal_graph` 的配置、提示词、Schema、生成与执行接口和 `causal_discovery/m1_data.py`、`pipeline.py`。`graph_export.py` 原有完整定义导出可直接保留契约，新增回归测试确认这一点，无需复制导出逻辑。仿真模型动力学及 M2–M5 的数学实现保持原样。

## 使用

```powershell
python -m full_pipeline --scenario scenarios/fish.md --config full_pipeline/config_research.yaml
python -m full_pipeline --scenario scenarios/v2/covasim.md --config full_pipeline/config_research.yaml
python -m full_pipeline --resume full_pipeline/results/<experiment_id>
```

正式配置预先固定 Fish 的 4 个种子、1000 步和 Covasim 的 8 个种子、60 步，第二部分沿用原统计设置。接口测试使用 `full_pipeline/examples/low_cost_acceptance.yaml`，不得作为丰富图科研验收结果。

## 验证范围

新增控制测试覆盖契约定义、实体映射、图导出保留契约、滚动窗口分批执行一致性、小批次代码局部修复、变量定义局部修复及第一部分恢复。新增贯通测试使用明确标记的 Mock LLM、实际小型 Fish 日志、实际指标子进程及现有 M1–M5，验证指标执行和 M1 先于三类关系生成，并验证恢复不重复请求。

这些是代码集成测试，不是新的真实 LLM 正式实验。历史三节点 Fish/Covasim 结果保留，不将其改称为本次丰富图结果；本次集成修改不新增真实 API 实验结论。

全量回归命令：`python -m pytest -q --tb=short --junitxml=full_pipeline/results/integration_regression_20261107.xml`。实际结果为 **204 passed，304.93 秒**；统一命令入口的 `--help` 也已成功运行。

真实运行进一步发现，重试提示此前只携带错误文字，没有携带上次失败的定义，无状态 API 因而无法准确修复。现已补充本任务上次响应，并明确标量原始特征、分析映射及完整覆盖的输入格式。对应全量回归再次得到 **204 passed，283.55 秒**，记录在 `full_pipeline/results/research_retry_context_regression.xml`。修正只改变对应任务的请求版本，保留历史响应、仿真、Schema 和已通过的宏观现象检查点。
