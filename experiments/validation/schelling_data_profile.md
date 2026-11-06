# Data profile: experiments\validation\schelling_model_states.csv

**Shape:** 8 rows × 17 cols

## Columns

| Column | Type | n | missing | summary |
|---|---|---|---|---|
| `scenario_id` | categorical | 8 | 0 | 1 levels: SCENARIO-SCHELLING-001(8); min_group_n=8 |
| `scenario_version` | ordinal | 8 | 0 | 1 levels: 2.0(8); min_group_n=8 |
| `scenario_sha256` | categorical | 8 | 0 | 1 levels: ecfa1373637c172b6e1ab2786a9d4b803ea9f58ae65963f2d883326dde85d4c7(8); min_group_n=8 |
| `run_id` | categorical | 8 | 0 | 1 levels: 3b1b5e8b6f9a41d695988be12ab8c060(8); min_group_n=8 |
| `model_name` | categorical | 8 | 0 | 1 levels: schelling_extended(8); min_group_n=8 |
| `model_version` | ordinal | 8 | 0 | 1 levels: 2.0(8); min_group_n=8 |
| `seed` | ordinal | 8 | 0 | 1 levels: 42(8); min_group_n=8 |
| `step` | continuous | 8 | 0 | mean=3.5, sd=2.45, range=[0, 7], skew=0.00 (approximately symmetric) |
| `event_index` | continuous | 8 | 0 | mean=2.97e+04, sd=2.08e+04, range=[0, 5.95e+04], skew=0.00 (approximately symmetric) |
| `timestamp_or_sim_time` | continuous | 8 | 0 | mean=3.5, sd=2.45, range=[0, 7], skew=0.00 (approximately symmetric) |
| `agent_id` | boolean | 0 | 8 (100%) | 0 levels: ; min_group_n=0 |
| `event_type` | categorical | 8 | 0 | 1 levels: model_states(8); min_group_n=8 |
| `population` | ordinal | 8 | 0 | 1 levels: 8499(8); min_group_n=8 |
| `happy` | ordinal | 8 | 0 | 7 levels: 8497(2), 4959(1), 8228(1), 8461(1), 8490(1) +2 more; min_group_n=1 |
| `same_neighbors` | ordinal | 8 | 0 | 7 levels: 50808(2), 28378(1), 48238(1), 50422(1), 50730(1) +2 more; min_group_n=1 |
| `neighbors` | ordinal | 8 | 0 | 7 levels: 57450(2), 56984(1), 57186(1), 57390(1), 57464(1) +2 more; min_group_n=1 |
| `moves` | ordinal | 8 | 0 | 7 levels: 0(2), 2875(1), 310(1), 46(1), 7(1) +2 more; min_group_n=1 |

## Correlations (Pearson, sorted by |r|)
- `step` ↔ `event_index` : r = 1.000 (very strong)
- `step` ↔ `timestamp_or_sim_time` : r = 1.000 (very strong)
- `event_index` ↔ `timestamp_or_sim_time` : r = 1.000 (very strong)

## Warnings
- 列 'scenario_id' 至少有一个类别 n<10 — 小样本必须展示原始数据点，不要只画均值柱状图。
- 列 'scenario_version' 至少有一个类别 n<10 — 小样本必须展示原始数据点，不要只画均值柱状图。
- 列 'scenario_sha256' 至少有一个类别 n<10 — 小样本必须展示原始数据点，不要只画均值柱状图。
- 列 'run_id' 至少有一个类别 n<10 — 小样本必须展示原始数据点，不要只画均值柱状图。
- 列 'model_name' 至少有一个类别 n<10 — 小样本必须展示原始数据点，不要只画均值柱状图。
- 列 'model_version' 至少有一个类别 n<10 — 小样本必须展示原始数据点，不要只画均值柱状图。
- 列 'seed' 至少有一个类别 n<10 — 小样本必须展示原始数据点，不要只画均值柱状图。
- 列 'agent_id' 缺失率 100% — 画图前考虑是否填补、剔除、或在图注中交代。
- 列 'event_type' 至少有一个类别 n<10 — 小样本必须展示原始数据点，不要只画均值柱状图。
- 列 'population' 至少有一个类别 n<10 — 小样本必须展示原始数据点，不要只画均值柱状图。
- 列 'happy' 至少有一个类别 n<10 — 小样本必须展示原始数据点，不要只画均值柱状图。
- 列 'same_neighbors' 至少有一个类别 n<10 — 小样本必须展示原始数据点，不要只画均值柱状图。
- 列 'neighbors' 至少有一个类别 n<10 — 小样本必须展示原始数据点，不要只画均值柱状图。
- 列 'moves' 至少有一个类别 n<10 — 小样本必须展示原始数据点，不要只画均值柱状图。

## Chart suggestions (preliminary)
- 分类 vs 连续，样本量充足 → 箱线图 / 小提琴图，或带误差棒的柱状图（误差棒说明 SD/SEM/CI）
- ≥3 个连续变量 → 相关性热力图（['step', 'event_index', 'timestamp_or_sim_time']）或 pairplot 散点矩阵
- 分类维度组合数 = 2401（scenario_id, scenario_version, scenario_sha256, run_id, model_name, model_version, seed, agent_id, event_type, population, happy, same_neighbors, neighbors, moves 全交叉），**一张图塞不下**——建议按某一维拆成多面板，或选择子集。

> 这是基于数据形态的**初步建议**。最终图型选择必须结合**论证目标**（你想说什么）—— 详见 `references/chart_selection.md`。