# 轨迹及动态指标接口

每个 run 默认包含 `manifest.json`、`resolved_config.yaml`、`field_catalog.json`、`agent_states.parquet`、`events.parquet` 和 `model_states.parquet`。字段目录由实际 schema 生成，记录字段类型、含义和粒度。Parquet 使用可配置的 `zstd`、`snappy`、`gzip` 或 `none` 压缩，按批次写入，关闭时校验 schema、行数和 SHA-256。清单显式登记 recording_mode（full_observable 或 reduced）及 logging 开关；full_observable 仅指原生可观测字段完整，不表示不存在原生未暴露事件。目录结构和运行状态仍需核对 manifest；字段缺失不会被当成零。

各表公共字段：`run_id`、`model_name`、`model_version`、`seed`、`step`、`event_index`、`timestamp_or_sim_time`、`agent_id`、`event_type`。`step` 和 `timestamp_or_sim_time` 均为离散采样步，不是墙钟时间；`event_index` 为该运行累计事件序号，状态行记录采样时已发生的事件数量，模型行无 `agent_id`。初态为 step=0、event_index=0。状态按配置采样，最后完成步始终记录；事件在启用时每次尝试都保存。范围查询的起止均包含边界。

标准Schelling的主体表有 `kind,x,y,neighbors,same_neighbors,other_neighbors,happy`。事件表每个激活一行，包含 `kind`、`x_before,y_before,x_after,y_after`、行为前后邻居数、`happy_before,happy_after,moved,reason`；满意状态在整轮末统一重算，所以 `happy_after` 是行为后存储状态而非新位置即时满意度。模型表包含人口、满意人数、同类邻居对计数及邻居总计数，邻居对按有向观察计数。

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

Covasim另保存native_parameters.json与native_parameters_final.json，使用原生Sim.to_json导出初始化后和执行结束时的全部实际参数（含疾病持续时间、概率、接触层和干预默认值）；它们也计入manifest的SHA-256并由export复制，避免只保存显式YAML而遗漏原生默认配置。

## 扩展Schelling与回放接口

schelling_extended主体状态保留标准字段，新增float64的theta_i。激活日志增加theta_i、attempted（bool）、candidate_count与feasible_count（int64）、similarity_before与similarity_after（float64）。happy_before是在本次激活时根据当前邻居重算；happy_after是自身行动后的即时结果。它与标准版本使用上一轮存储满意度的含义不同。模型状态新增本轮实际moves。事件原因见MODEL_SPECIFICATIONS；未尝试搬迁、搜索失败和实际搬迁均保留一行。每轮主体状态与事件都保留实际坐标，能够重建空间占用。

`configuration()`和`metadata()`分别读取实际保存配置及清单；`available_steps()`仅返回实际已保存采样步；`read_snapshot(step)`对未保存时间点报错，不插值或再次仿真。`source_fingerprints()`返回日志SHA-256。图形、历史回放和后续指标均通过本文件访问数据。

实时界面额外保存checkpoints/中的闭合Parquet文件，按完整采样轮提交主体、事件、接触和模型状态，临时文件原子替换后才能读取。采样频率大于1时，事件保留其实际发生步。未完成运行读取这些快照，最终清单存在后读取正式Parquet。Covasim的contacts也保存实时闭合快照；模型状态检查点最后提交，作为完整帧的可读标记。主网络读取对应时点实际接触，传播动画单独读取感染事件；最终潜在接触表仍按原模式写入。run_metadata.json允许实时阶段显示来源；正式运行状态以manifest.json为准。强制终止可能损坏尚未关闭的正式文件，检查点不等于完整运行验收。

figure_manifest.json记录run_id、场景编号/版本/哈希、时间窗口、全部图形配置、导出程序版本/提交、来源文件SHA-256和figure_data.json的SHA-256。图版数据仅是展示产物，不注册论文因果变量。可视化默认需要agent_states、events、model_states全部启用；关闭后不会用零替代缺失值。

## 迁移鱼群协议fish-3.0

fish使用agent_states、events、contacts、raw_frames、model_states五张表。role区分fish/shark；位置与朝向是原生模型单位。fright对应原项目画面使用的本次行动类别，remaining是更新后的剩余持续步数，两者不能混为同一时刻的状态定义。target_id=-1表示鲨鱼无目标。决策JSON保存全部个体原生字段，raw_frames.frame_json额外无损保存原始整体帧与decision_input；read_frame(step)为统一访问入口。contacts的agent_id是受体UID、partner_id是步初处于受惊状态的邻居UID，source_episode为步初事件类别。它是原生受惊邻居接触记录，不保证受体实际触发社会受惊。
