# 轨迹及动态指标接口

每个 run 默认包含 `manifest.json`、`resolved_config.yaml`、`field_catalog.json`、`agent_states.parquet`、`events.parquet` 和 `model_states.parquet`。字段目录由实际 schema 生成，记录字段类型、含义和粒度。Parquet 使用可配置的 `zstd`、`snappy`、`gzip` 或 `none` 压缩，按批次写入，关闭时校验 schema、行数和 SHA-256。清单显式登记 recording_mode（full_observable 或 reduced）及 logging 开关；full_observable 仅指原生可观测字段完整，不表示不存在原生未暴露事件。目录结构和运行状态仍需核对 manifest；字段缺失不会被当成零。

各表公共字段：`run_id`、`model_name`、`model_version`、`seed`、`step`、`event_index`、`timestamp_or_sim_time`、`agent_id`、`event_type`。`step` 和 `timestamp_or_sim_time` 均为离散采样步，不是墙钟时间；`event_index` 为该运行累计事件序号，状态行记录采样时已发生的事件数量，模型行无 `agent_id`。初态为 step=0、event_index=0。状态按配置采样，最后完成步始终记录；事件在启用时每次尝试都保存。范围查询的起止均包含边界。

Schelling 的主体表有 `kind,x,y,neighbors,same_neighbors,other_neighbors,happy`。事件表每个激活一行，包含 `kind`、`x_before,y_before,x_after,y_after`、行为前后邻居数、`happy_before,happy_after,moved,reason`；满意状态在整轮末统一重算，所以 `happy_after` 是行为后存储状态而非新位置即时满意度。模型表包含人口、满意人数、同类邻居对计数及邻居总计数，邻居对按有向观察计数。

Covasim 主体表完整输出原生 40 个个体字段，详见 MODEL_SPECIFICATIONS。附加 simulation_day 表示原生时间，初态 -1，平台 step k 对应已执行 day k-1。原生感染日期、计划转移日期和实际转移事件不同，不能把已采样的未来疾病日期当成已经发生的事实。按盲测要求可另行限定提供给 LLM 的列，但原始日志保留未删减版本。

Covasim events 包含 infection、state_transition、test。感染事件 agent_id 是被感染者、partner_id 是来源，原生种子或输入感染来源可为 null；layer 保留原始层名。状态事件记录 state 与 before/after；检测事件根据最后检测日期变化记录，不能恢复原生未暴露的同日多次测试。没有独立 isolated 状态，不根据汇总量反造个体隔离事件。

Covasim contacts 每个采样步每条潜在接触边一行：agent_id、partner_id、layer、beta、simulation_day。beta 为原生边权，不等于整体传播概率。原始层保留，不能将边计数声称为成功接触；未成功传播尝试未被引擎公开。模型表是未按真实人口扩展的模拟主体人数与疾病状态计数，状态可能重叠。实际字段类型及含义由 field_catalog.json 提供。

`Trajectory(path).read(table, start=None, end=None, agent_id=None)` 返回独立的 Pandas 数据副本；`catalog` 提供 schema，`export(directory)` 复制全部已记录数据及配置、清单和字段目录。`compute(function, required, config)` 校验字段后用数据副本调用已审查的函数。示例 `examples/indicators.py` 中的两种指标分别计算按有向邻居关系加权的同类比例及感染主体比例；比例分母为 0 时为 NaN。

**安全边界。** `compute` 在主进程运行，只适用于可信、经过审查的函数，不能把 Python 内建权限限制称为沙箱。未经审查的文件可调用 `Trajectory.compute_isolated(code_file, required, config, image=..., timeout=...)`：它要求函数名为 `compute_indicator(data, config)`，返回 Pandas Series/DataFrame；传入需要的表及字段，并将这些表读为副本。该接口在 Docker 不存在时直接拒绝执行，使用只读挂载、禁网、非 root、只读根文件系统、丢弃 capabilities 和资源/时间/输出限制。不可信代码不能直接修改只读挂载的原始轨迹；Docker 与宿主共享内核，恶意代码仍可能利用内核漏洞，处理高度对抗性代码应在额外硬化的独立虚拟机内运行。隔离镜像只从本地调用，不自动拉取。

可选容器准备及调用：

```bash
docker build -t abms-indicator:1 sandbox
```

```python
result = t.compute_isolated('review_candidate.py',
                            {'agent_states': ['step', 'infectious']},
                            {'window': 3})
```

上述隔离接口在当前机器上因为未安装 Docker 未能运行端到端测试；只验证缺少 Docker 时拒绝在主进程执行。使用前必须在目标 Docker/操作系统上检查实际隔离设置、只读挂载和资源限制，不能将此接口视为已经过安全认证的沙箱。严格科研条件下请保留代码审查记录与输入输出摘要。
