# ABMS Lab：标准多主体仿真实验平台

本项目为多尺度机制归因研究提供两类经典仿真及可追溯原始轨迹：Mesa 3.5.2 Schelling 居住隔离示例对应实现，和完全混合的 Deffuant–Weisbuch 有界信任模型。主体由经典规则驱动。本项目不实现大语言模型、因果图、统计检验或主动实验调度；仿真结果及描述性指标本身不构成因果证据。

规则、许可和差异参见 [模型来源](docs/MODEL_SOURCES.md)、[ODD 规格](docs/MODEL_SPECIFICATIONS.md)，实际检查及其限制见 [验证报告](docs/VALIDATION_REPORT.md)。

## 安装

在 Python 3.12 的隔离环境中，从项目根目录运行：

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[test]"
python -m pytest -q
```

本项目固定 Mesa 3.5.2，其他依赖范围见 `pyproject.toml`。如需跨机器精确复现，应另存 `python -m pip freeze` 的环境清单；该项目并未锁定全部传递依赖。无需密钥或私有服务。

## 运行和配置

所有命令在项目根目录执行；`output.directory` 相对于当前工作目录。单次和串行批量模式不会打开浏览器：

```bash
python main.py run --config configs/schelling.yaml
python main.py run --config configs/deffuant.yaml
python main.py batch --config configs/batch_schelling.yaml
python main.py batch --config configs/batch_deffuant.yaml
python -m experiments.validate_dynamics
```

单次运行打印唯一结果目录；批量运行打印 JSON 报告路径，某次失败不阻止其他组合，报告记录全部种子、参数和错误，存在失败时命令退出码为 1。批量配置可使用 `seeds: [11, 22]`，或改成 `master_seed: 123` 和 `replicates: 2`；`grid` 中列出模型参数及可选 `steps` 的列表，生成笛卡尔积。相同种子可配对不同参数，但**不保证**不同条件消费相同随机事件。

配置包含 `model`、`model_version`、`seed`、`steps`、`parameters`、`sampling`、`logging`、`output`、`visualization`；未知字段及不合法的类型/取值会被拒绝。`steps` 是上限，Schelling 满足稳定条件时提前停止。`sampling.frequency` 控制状态快照间隔，初态和最后状态总会保存；事件默认每次完整保存。关闭数据类别或降低采样频率会在 manifest 标注缺失。Schelling 的 density 是每个格子独立占用的概率，实际数量不固定；若完全占满且存在不满意主体，官方随机空格搬迁无法执行，此运行会记录错误。Deffuant 的一步包含 `interactions_per_step` 次随机配对。

## 可视化

```bash
python main.py ui --config configs/schelling.yaml
python main.py ui --config configs/deffuant.yaml
```

分别启动后访问配置中 `visualization.host:visualization.port`，默认为 <http://127.0.0.1:8765>。控制栏提供单步、连续、暂停、重置；拖动参数滑块后点击 Reset 创建新运行。选模型或载入另一份 YAML 时，停止服务并以新配置重启。Reset 会结束并保存上次运行；完成上限或稳定条件也会自动保存。未正常退出的服务或浏览器断线可能留下未完成日志，正式实验建议使用无头模式并检查 manifest。默认监听回环地址；不要随意对公网开放。

## 读取日志与示例指标

```python
from simulations.common.trajectory_api import Trajectory
from examples.indicators import schelling_same_neighbor_fraction

t = Trajectory('results/<run_id>')
states = t.read('agent_states', start=0, end=10, agent_id=1)
events = t.read('events', start=1, end=10, agent_id=1)
print(t.catalog)  # 实际字段、数据类型和粒度
series = t.compute(schelling_same_neighbor_fraction,
                   {'agent_states': ['step', 'same_neighbors', 'neighbors']})
t.export('exported_trajectory')
```

`compute` 只接受已审查的可信函数，操作内存副本，并非安全沙箱。未经审查的指标必须使用 `compute_isolated` 与预先配置的 Docker 隔离环境，或更强的独立虚拟机；本机没有 Docker，容器执行尚未实测。配置方法和限制见 [数据接口](docs/DATA_SCHEMA.md)。

## 目录

`configs/` 配置；`simulations/` 模型及唯一日志接口；`visualization/` Solara 界面；`tests/` 测试；`examples/` 指标示例；`experiments/` 定性验证脚本及一次结果摘要；`results/` 本地运行输出，默认不提交。详见 [复现说明](docs/REPRODUCIBILITY.md)。
