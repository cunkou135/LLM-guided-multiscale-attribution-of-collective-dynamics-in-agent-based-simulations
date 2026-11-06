# Data profile: experiments\validation\covasim_v2_model_states.csv

**Shape:** 61 rows × 26 cols

## Columns

| Column | Type | n | missing | summary |
|---|---|---|---|---|
| `scenario_id` | categorical | 61 | 0 | 1 levels: SCENARIO-COVASIM-001(61); min_group_n=61 |
| `scenario_version` | ordinal | 61 | 0 | 1 levels: 2.0(61); min_group_n=61 |
| `scenario_sha256` | categorical | 61 | 0 | 1 levels: 50bcd64c7fbd6ca511fa899e452450013a0a59db3ec235b5b7350ec53f381cde(61); min_group_n=61 |
| `run_id` | categorical | 61 | 0 | 1 levels: 3249f90463154305aed53504106b3dae(61); min_group_n=61 |
| `model_name` | categorical | 61 | 0 | 1 levels: covasim(61); min_group_n=61 |
| `model_version` | categorical | 61 | 0 | 1 levels: 2.0.0(61); min_group_n=61 |
| `seed` | ordinal | 61 | 0 | 1 levels: 8(61); min_group_n=61 |
| `step` | continuous | 61 | 0 | mean=30, sd=17.8, range=[0, 60], skew=-0.00 (approximately symmetric) |
| `event_index` | continuous | 61 | 0 | mean=2.55e+03, sd=2.09e+03, range=[10, 5.64e+03], skew=0.13 (approximately symmetric); -> log axis |
| `timestamp_or_sim_time` | continuous | 61 | 0 | mean=30, sd=17.8, range=[0, 60], skew=-0.00 (approximately symmetric) |
| `agent_id` | boolean | 0 | 61 (100%) | 0 levels: ; min_group_n=0 |
| `event_type` | categorical | 61 | 0 | 1 levels: model_states(61); min_group_n=61 |
| `simulation_day` | continuous | 61 | 0 | mean=29, sd=17.8, range=[-1, 59], skew=-0.00 (approximately symmetric) |
| `population` | ordinal | 61 | 0 | 1 levels: 1000(61); min_group_n=61 |
| `susceptible` | continuous | 61 | 0 | mean=720, sd=177, range=[519, 990], skew=0.34 (approximately symmetric) |
| `exposed` | continuous | 61 | 0 | mean=108, sd=69.9, range=[10, 230], skew=0.21 (approximately symmetric) |
| `infectious` | continuous | 61 | 0 | mean=70.8, sd=49.3, range=[0, 165], skew=0.30 (approximately symmetric) |
| `symptomatic` | continuous | 61 | 0 | mean=45.5, sd=32.1, range=[0, 106], skew=0.34 (approximately symmetric) |
| `severe` | continuous | 61 | 0 | mean=4.66, sd=4.04, range=[0, 13], skew=0.74 (moderately skewed) |
| `critical` | ordinal | 61 | 0 | 6 levels: 1(24), 0(16), 3(11), 4(7), 2(2) +1 more; min_group_n=1 |
| `tested` | continuous | 61 | 0 | mean=82.4, sd=79.9, range=[0, 201], skew=0.25 (approximately symmetric) |
| `diagnosed` | continuous | 61 | 0 | mean=82.4, sd=79.9, range=[0, 201], skew=0.25 (approximately symmetric) |
| `recovered` | continuous | 61 | 0 | mean=173, sd=168, range=[0, 449], skew=0.39 (approximately symmetric) |
| `dead` | boolean | 61 | 0 | 1 levels: 0(61); min_group_n=61 |
| `known_contact` | continuous | 61 | 0 | mean=194, sd=179, range=[0, 440], skew=0.14 (approximately symmetric) |
| `quarantined` | continuous | 61 | 0 | mean=83.5, sd=75.4, range=[0, 199], skew=0.21 (approximately symmetric) |

## Correlations (Pearson, sorted by |r|)
- `step` ↔ `timestamp_or_sim_time` : r = 1.000 (very strong)
- `step` ↔ `simulation_day` : r = 1.000 (very strong)
- `timestamp_or_sim_time` ↔ `simulation_day` : r = 1.000 (very strong)
- `tested` ↔ `diagnosed` : r = 1.000 (very strong)
- `tested` ↔ `known_contact` : r = 0.997 (very strong)
- `diagnosed` ↔ `known_contact` : r = 0.997 (very strong)
- `event_index` ↔ `known_contact` : r = 0.996 (very strong)
- `tested` ↔ `recovered` : r = 0.995 (very strong)
- `diagnosed` ↔ `recovered` : r = 0.995 (very strong)
- `event_index` ↔ `tested` : r = 0.993 (very strong)
- ... +81 more pairs

## Warnings
- 列 'agent_id' 缺失率 100% — 画图前考虑是否填补、剔除、或在图注中交代。
- 列 'critical' 至少有一个类别 n<10 — 小样本必须展示原始数据点，不要只画均值柱状图。

## Chart suggestions (preliminary)
- 分类 vs 连续，样本量充足 → 箱线图 / 小提琴图，或带误差棒的柱状图（误差棒说明 SD/SEM/CI）
- ≥3 个连续变量 → 相关性热力图（['step', 'event_index', 'timestamp_or_sim_time', 'simulation_day', 'susceptible']）或 pairplot 散点矩阵
- event_index 跨数个量级（10 ~ 5.64e+03）→ 用对数 y 轴

> 这是基于数据形态的**初步建议**。最终图型选择必须结合**论证目标**（你想说什么）—— 详见 `references/chart_selection.md`。