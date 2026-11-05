# 轨迹及动态指标接口

每个 run 默认包含 `manifest.json`、`resolved_config.yaml`、`field_catalog.json`、`agent_states.parquet`、`events.parquet` 和 `model_states.parquet`。字段目录由实际 schema 生成，记录字段类型、含义和粒度。Parquet 使用可配置的 `zstd`、`snappy`、`gzip` 或 `none` 压缩，按批次写入，关闭时校验 schema、行数和 SHA-256。目录结构和运行状态仍需核对 manifest；字段缺失不会被当成零。

三张表公共字段：`run_id`、`model_name`、`model_version`、`seed`、`step`、`event_index`、`timestamp_or_sim_time`、`agent_id`、`event_type`。`step` 和 `timestamp_or_sim_time` 均为离散采样步，不是墙钟时间；`event_index` 为该运行累计事件序号，状态行记录采样时已发生的事件数量，模型行无 `agent_id`。初态为 step=0、event_index=0。状态按配置采样，最后完成步始终记录；事件在启用时每次尝试都保存。范围查询的起止均包含边界。

Schelling 的主体表有 `kind,x,y,neighbors,same_neighbors,other_neighbors,happy`。事件表每个激活一行，包含 `kind`、`x_before,y_before,x_after,y_after`、行为前后邻居数、`happy_before,happy_after,moved,reason`；满意状态在整轮末统一重算，所以 `happy_after` 是行为后存储状态而非新位置即时满意度。模型表包含人口、满意人数、同类邻居对计数及邻居总计数，邻居对按有向观察计数。

Deffuant 的主体表有 `opinion`；事件表的 `agent_id,partner_id`、双方前后意见、`difference,epsilon,mu,accepted,delta,partner_delta,reason` 记录每次配对，包括拒绝配对。`read('events', agent_id=k)` 返回 k 为任一配对方的事件。模型表包含人口、均值、最小和最大意见；无心跳式收敛判定。

`Trajectory(path).read(table, start=None, end=None, agent_id=None)` 返回独立的 Pandas 数据副本；`catalog` 提供 schema，`export(directory)` 复制全部已记录数据及配置、清单和字段目录。`compute(function, required, config)` 校验字段后用数据副本调用已审查的函数。示例 `examples/indicators.py` 中的两种指标分别计算按有向邻居关系加权的同类比例及意见总体方差；比例分母为 0 时为 NaN。

**安全边界。** `compute` 在主进程运行，只适用于可信、经过审查的函数，不能把 Python 内建权限限制称为沙箱。未经审查的文件可调用 `Trajectory.compute_isolated(code_file, required, config, image=..., timeout=...)`：它要求函数名为 `compute_indicator(data, config)`，返回 Pandas Series/DataFrame；传入需要的表及字段，并将这些表读为副本。该接口在 Docker 不存在时直接拒绝执行，使用只读挂载、禁网、非 root、只读根文件系统、丢弃 capabilities 和资源/时间/输出限制。不可信代码不能直接修改只读挂载的原始轨迹；Docker 与宿主共享内核，恶意代码仍可能利用内核漏洞，处理高度对抗性代码应在额外硬化的独立虚拟机内运行。隔离镜像只从本地调用，不自动拉取。

可选容器准备及调用：

```bash
docker build -t abms-indicator:1 sandbox
```

```python
result = t.compute_isolated('review_candidate.py',
                            {'agent_states': ['step', 'opinion']},
                            {'window': 3})
```

上述隔离接口在当前机器上因为未安装 Docker 未能运行端到端测试；只验证缺少 Docker 时拒绝在主进程执行。使用前必须在目标 Docker/操作系统上检查实际隔离设置、只读挂载和资源限制，不能将此接口视为已经过安全认证的沙箱。严格科研条件下请保留代码审查记录与输入输出摘要。
