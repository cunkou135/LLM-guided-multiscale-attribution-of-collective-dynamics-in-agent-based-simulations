# 离线软件验收示例：不是真实 LLM 实验

这里保存 2026-11-06 实际运行得到的工程验收结果。`client_mode=offline_fixture_not_model_generated`。现象、变量和边来自 `causal_graph/tests/fixtures.py` 的显式人工测试替身，只用来检查软件接口和失败处理，不是科学候选机制、指标推荐或 LLM 质量证据。

Fish 使用原平台默认 2000 鱼/5 鲨鱼，种子 42、43；Covasim 使用原生 2.0.0、默认 1000 人，种子 8、9；每次 5 个真实更新步，未修改主体机制。两个场景分别生成 4 个测试节点，其中 1 个故意依赖不存在的字段；两条轨迹上共 6 次成功与 2 次预期失败。可执行图保留 3 节点、2 原始边。

`fish_offline_experiment/`、`covasim_offline_experiment/` 包含完整提示词、人工响应、解析与校验、函数、实际数值、JSON/GraphML、执行及恢复历史。所有成功时间序列与原始数据直接计算逐值比较。归档前逐项核对 `artifact_hashes.json`，并核对其 `software.source_sha256` 与当前方法源码一致。

`*_additional_raw_check/` 是人工审查测试函数访问 Fish 原始帧与 Covasim 事件的实际执行记录；`*_isolation_probe/` 是直接调用平台 Docker 接口的拒绝结果，原因是 Docker 不可用。没有以普通子进程代称安全隔离。可信执行审查仅批准这些已知人工测试函数，不批准任何未来 LLM 生成代码。

原始完整运行仍在本机 `causal_graph/results/acceptance_release_20261106/simulation_runs/`，没有将较大的原始日志提交到 Git。来源 manifest、配置参数、场景与数据哈希保存在 `*_input_audit.json`；可用以下命令重新生成独立运行及全部验收：

```powershell
python -m causal_graph.tests.validate_logs --output causal_graph/results/new_acceptance
```

新运行具有新的 UUID、时间和含 run_id 的数据字节哈希；比较时应使用原始数值、固定场景和执行定义，不能要求新 UUID 的整个 Parquet 文件字节等同。归档记录不改写历史绝对路径；复制到别处后的本地文件应按当前目录检查。
