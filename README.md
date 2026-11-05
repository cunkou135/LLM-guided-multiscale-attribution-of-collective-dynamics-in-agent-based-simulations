# ABMS Lab：Schelling 与 Covasim 双场景平台

平台提供 Mesa 3.5.2 的 Schelling 标准规则及原生 Covasim 2.0.0 的运行管理、浏览器界面、批量实验与原始轨迹。固定想定在 scenarios/，其文本、编号和 SHA-256 不随参数实验改变。LLM、因果发现、Bootstrap 和证据融合不在本项目范围内。

Covasim 默认配置是**未完成金县历史校准的 hybrid 演示**，没有 LTCF 层。论文的 Figure 3 小规模公开基准已作缓存对照；这不表示原研究的金县人口和疫情校准已经复现。模型、数据与许可来源见 [来源核查](docs/MODEL_SOURCES.md)。

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

## 执行

在仓库根目录运行，输出路径相对于当前工作目录：

```bash
python main.py run --config configs/schelling.yaml
python main.py run --config configs/covasim.yaml
python main.py batch --config configs/batch_schelling.yaml
python main.py batch --config configs/batch_covasim.yaml
python main.py ui --config configs/schelling.yaml
python main.py ui --config configs/covasim.yaml
python -m pytest -q
```

无头模式不会打开浏览器。界面命令启动后访问配置中的 host/port，默认为 http://127.0.0.1:8765 。单步、运行/暂停和重置由 Mesa SolaraViz 控制。滑块修改后 Reset 创建新运行；选择另一模型或 YAML 时停止服务并以对应命令重启。两模型的界面和无头模式使用同一运行会话；Covasim 每步实际调用原生引擎，页面不是轨迹回放。页面标明其未历史校准，并显示分层潜在接触边、疾病状态、参数和干预配置。正式实验建议无头执行。

YAML 控制 model、model_version、scenario_id、seed、steps、parameters、sampling、logging、output、visualization；Covasim 另含 engine。Schelling 参数沿用参考含义，density 是每格独立占用概率而非固定人数。Covasim 运行长度 steps 至少为2（原生2.0.0不接受n_days=0）；当前微观日志配置显式要求 pop_scale=1、rescale=false，避免动态重采样改变 UID 的纵向意义。任何声明都不会将其标成历史复现。

`logging` 中全部表开关为 true 且采样频率 1 是完整可观测模式。低资源模式可关闭 contacts/agent_states/events 或增大 sampling.frequency；清单记录缺失，不能拿低资源结果冒充完整微观数据。未成功传播尝试等原生不暴露的数据，即使完整模式也会标记缺失。

批量配置支持 seeds 列表，或 master_seed 与 replicates；grid 列出参数或 steps 的取值列表。每次独立运行有唯一目录，错误保留并继续其他组合，批次失败时命令退出 1。相同种子不保证不同参数条件有逐事件相同的随机序列。

## 读取与指标

```python
from simulations.common.trajectory_api import Trajectory
from examples.indicators import covasim_infectious_fraction

t = Trajectory('results/<run_id>')
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
