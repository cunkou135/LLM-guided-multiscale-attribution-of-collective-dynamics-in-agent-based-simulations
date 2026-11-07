# 群体动力学实验室：Schelling、Covasim与鱼群

平台提供100×100异质偏好/有限迁居的扩展Schelling、Mesa 3.5.2标准Schelling，以及原生Covasim 2.0.0。支持实时交互、真实历史回放、批量干预、完整轨迹与论文图版导出。固定想定1.0原文保持原路径和哈希，新增scenarios/v2/下2.0版，默认研究配置使用2.0；其文本、编号和SHA-256不随参数实验改变。独立的 causal_graph 模块提供第一阶段 LLM 候选结构生成。新增 [causal_discovery 第二部分](causal_discovery/README.md)读取已执行指标，提供独立 GRU 时滞、RNN-Granger、简单 MMI-PID 和统一 JSON 图整合；结果表达观测预测依赖及联合信息，不能直接视为结构因果真值。

Covasim 默认配置是**未完成金县历史校准的 hybrid 演示**，没有 LTCF 层。论文的 Figure 3 小规模公开基准已作缓存对照；这不表示原研究的金县人口和疫情校准已经复现。模型、数据与许可来源见 [来源核查](docs/MODEL_SOURCES.md)。

新增 [full_pipeline 全流程入口](full_pipeline/README.md)：`python -m full_pipeline --scenario scenarios/fish.md`。它自动匹配已注册想定、准备独立种子仿真、调用两个既有研究模块，并发布 `stage1_graph.json` 与 `final_causal_graph.json`。支持分阶段审核、局部修复及 `--resume`；审核未完成或统计数据不足时保留明确状态和原因。

## 安装

主环境使用 Python 3.12：

```bash
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1
# Linux/macOS: source .venv/bin/activate
python -m pip install -e ".[test]"
```

Covasim 使用独立 Python 3.10 兼容环境。本次实测 Python 3.10.2；它不是论文原始 Python 3.8 冻结环境。Windows 已安装 Python 3.10 时：

```powershell
py -3.10 -m venv .covasim-venv
.\.covasim-venv\Scripts\python.exe -m pip install -r requirements-covasim-compat-lock.txt
```

Linux/macOS 可用 `python3.10 -m venv .covasim-venv` 和 `.covasim-venv/bin/python`；相应修改 YAML 中 `engine.python`。跨系统安装锁定依赖的可用性仍需在目标系统验证。精确实测依赖保存在 requirements-covasim-compat-lock.txt，最小直接依赖在 requirements-covasim-compat.txt。两个环境通过子进程传输记录，Covasim 没有改写为 Mesa 模型。

## 鱼群场景与新界面

界面采用用户提供collective_motion_lab的米白、松绿和深海色风格。新增原生鱼群与鲨鱼场景，默认2000条鱼、5条鲨鱼；模型源码逐字保留，接入同一运行、批量、轨迹和历史回放接口。详见[迁移说明](docs/FISH_MIGRATION.md)。原有Schelling和Covasim规则与独立论文图版继续保留。

```bash
python main.py ui --config configs/fish.yaml
python main.py run --config configs/fish.yaml
python main.py batch --config configs/batch_fish.yaml
```

## 执行

在仓库根目录运行，输出路径相对于当前工作目录：

```bash
python start.py  # 统一菜单入口
python main.py run --config configs/schelling.yaml
python main.py run --config configs/schelling_standard.yaml
python main.py run --config configs/covasim.yaml
python main.py batch --config configs/batch_schelling.yaml
python main.py batch --config configs/batch_covasim.yaml
python main.py ui --config configs/schelling.yaml
python main.py ui --config configs/covasim.yaml
python -m pytest -q
```

默认研究模型为schelling_extended，100×100、最多300轮、偏好截断正态(.45,.10)、局部Chebyshev半径8，优先最高相似度满意位置，其次最高严格改善位置。每次激活根据当前邻居决定；真实stable/frozen可以提前停止，不补造300步。标准schelling_standard保持官方参考的上一轮满意状态与全局随机迁居，仍独立验证。

无头模式不会加载可视化页面。界面命令启动后访问[本地页面](http://127.0.0.1:8765)，支持两模型切换、单步、运行/暂停、参数重置、已保存时间轴与历史目录回放。Schelling支持100×100空间缩放、平移、居民点击、初始/当前/历史对照和迁居高亮；Covasim默认主界面是1000个真实UID的动态主体网络：原生状态着色、真实接触层筛选、感染脉冲、主体点击与搜索、稳定布局及浏览器截帧。统计图收起在辅助分析区，论文图版保持独立模式。历史模式只读日志。详见[可视化说明](docs/VISUALIZATION.md)。

勾选Publication Mode可预览并导出SVG、300/600DPI PNG，或离线导出：

```bash
python main.py export --run-dir results/<run_id> --output figures/<run_id> --figure-config configs/figures.yaml
```

configs/population.yaml管理主体网络与动画显示参数；configs/figures.yaml支持4:3/16:9、画布尺寸、字体、真实窗口及局部网络筛选。导出附带图版数据与来源清单，样例见[实际验收材料](experiments/validation/README.md)。图形展示不构成预设的论文指标库或候选因果图。

YAML 控制 model、model_version、scenario_id、scenario_version、seed、steps、parameters、sampling、logging、output、visualization；Covasim 另含 engine。Schelling 参数沿用参考含义，density 是每格独立占用概率而非固定人数。Covasim 运行长度 steps 至少为2（原生2.0.0不接受n_days=0）；当前微观日志配置显式要求 pop_scale=1、rescale=false，避免动态重采样改变 UID 的纵向意义。任何声明都不会将其标成历史复现。

`logging` 中全部表开关为 true 且采样频率 1 是完整可观测模式。低资源模式可关闭 contacts/agent_states/events 或增大 sampling.frequency；清单记录缺失，不能拿低资源结果冒充完整微观数据。未成功传播尝试等原生不暴露的数据，即使完整模式也会标记缺失。

批量配置支持seeds列表，或master_seed与replicates；grid列出参数或steps的取值列表。支持现有嵌套字段的点路径和列表索引，例如：

```yaml
base_config: covasim.yaml
seeds: [8, 9]
grid:
  interventions.0.symp_prob: [0.15]
  interventions.1.trace_probs.h: [0.7]
```

也可加parameters.前缀；未知路径与相互重叠的路径会报错。此示例是固定参数独立重复，不进行自动配置寻优。每次独立运行有唯一目录，错误保留并继续其他组合，批次失败时命令退出 1。相同种子不保证不同参数条件有逐事件相同的随机序列。

## 读取与指标

```python
from simulations.common.trajectory_api import Trajectory
from examples.indicators import covasim_infectious_fraction

t = Trajectory('results/<run_id>')
print(t.available_steps())
snapshot = t.read_snapshot(t.available_steps()[-1])
print(t.catalog)
agent = t.read('agent_states', start=0, end=10, agent_id=0)
events = t.read('events', agent_id=0)
contacts = t.read('contacts', start=1, end=1, agent_id=0)
series = t.compute(covasim_infectious_fraction,
                   {'agent_states': ['step', 'infectious']})
t.export('exported_trajectory')
```

全部日志、字段查询、导出和指标入口在 trajectory_api.py。compute 只接受经过审查的可信函数，传入数据副本；不可信代码必须用独立受限环境，compute_isolated 在没有 Docker 时拒绝执行，容器路径本机尚未端到端验证。参见 [数据 Schema](docs/DATA_SCHEMA.md)。

实验、测试与限制详见 [验收报告](docs/VALIDATION_REPORT.md)、[复现说明](docs/REPRODUCIBILITY.md)、[ODD 规格](docs/MODEL_SPECIFICATIONS.md)、[固定想定协议](docs/SCENARIO_PROTOCOL.md)。results/ 默认不上传，experiments/ 中提供公开可复查的脚本与本次结果摘要。Deffuant 的代码与配置已移除，历史版本可从 Git 历史审计。
# 第一部分跨尺度候选图方法

独立 [`causal_graph`](causal_graph/README.md) 2.0：固定想定识别现象，结合实际公共数据 Schema 自主生成三尺度变量及计算代码，分别调用 LLM 判断向上、向下和同层候选边，再本地合并；允许反馈环、跨现象联系与孤立节点。使用现有 Trajectory 计算，输出完整/可执行 JSON 与 GraphML、独立运行时间序列及审计。安装 `python -m pip install -e ".[test,causal]"`，入口 `python -m causal_graph --help`。论文第二部分为以后进行的数据因果判别；本轮不实现统计检验，也不设置独立干预验证阶段。


本地科研执行不要求 Docker：明确审查生成代码后，使用 trusted_reviewed 与 --execute-only --resume，在现有 Python 子进程中计算，保留 SHA-256 审核、日志和失败状态，不重新调用 LLM。当前原 12 个函数中 8 项通过、4 项未通过；详见 [本地执行验收](causal_graph/docs/LOCAL_EXECUTION_REPORT.md) 与 [全部真实因果图视图](causal_graph/examples/local_execution_20261106/graphs/index.html)。

丰富候选空间的新档案上限为 8 个现象、72 个变量、720 条边，使用 JSON 输出及每批 12 个变量的函数生成，另存新实验；见 [丰富候选图实验说明](causal_graph/docs/FORMAL_RICH_EXPERIMENT.md)。图形支持自动紧凑布局、大字号、方向/现象分图、完整邻接矩阵及交互缩放，原 6 变量结果保持保留。

真实丰富候选图现为 Fish 72 变量/495 边、Covasim 67 变量/454 边：[全部新图](causal_graph/examples/formal_rich_20261106/graphs/index.html)、[生成验收](causal_graph/docs/RICH_GENERATION_ACCEPTANCE.md)。新函数尚未做数学与执行验收，与原 12 个函数结果分别记录。
