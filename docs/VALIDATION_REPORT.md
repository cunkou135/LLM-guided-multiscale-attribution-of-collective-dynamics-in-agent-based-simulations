# 验证报告

本报告记录 2026-11-05 在 Python 3.12.3、Mesa 3.5.2 的实际检查。以下是实现验证及定性动力学检查，并不证明因果结构或精确复现全部原论文实验。具体测试可以从仓库重新运行；不能以这里的数字代替新运行的结果。

## 自动化与参考实现

`python -m pytest -q`：本次记录为 **29 passed**。`tests/test_reference.py` 对 Mesa 3.5.2 官方 Schelling 示例的初态和后续 8 步，逐主体比较 ID、坐标、类型、满意状态及停止状态，种子 2、42、97，参数为 12×12、密度 0.75、阈值 0.4、半径 1、非周期；所有比较通过。这是有限配置的逐步比较，不覆盖全部参数或周期边界。`tests/test_models.py` 检查空间单格约束、人数守恒、满意公式、周期和非周期边缘相邻、迁移及满意主体不迁移、随机成对的覆盖、严格阈值、同时更新、意见和守恒和范围。`tests/test_trajectory.py` 检查同种子可重复、异种子变化、采样、空表、元数据、批量失败不中断及查询；`tests/test_visualization.py` 比较两模型界面包装器和无头模式的状态和事件。

在 4×4、density=1、homophily=1 的有异类初始条件下，实际触发 `ValueError: Grid is completely full. No empty cells available. Cannot select a random empty cell.`，保留 `status=error` 的 manifest；这与官方随机空格迁居对空格的要求一致，不能当作有效完成运行。周期边界检查覆盖了边缘相邻行为，但不是对所有网格大小和邻域半径的穷举；它是显式配置扩展，不是官方默认。

## 无头实验与定性动力学

更新后的 `python main.py batch --config configs/batch_schelling.yaml` 和 `python main.py batch --config configs/batch_deffuant.yaml` 各执行 6 组，批次报告分别为 `batch_3906fbad1cb44415b2a6e712ffc4474f.json` 和 `batch_8068dff3b89f498184b13b5446a553c7.json`，均报告 0 个错误；结果位于执行机器的 `results/`，不会自动提交。`python -m experiments.validate_dynamics` 生成 24 条轨迹的摘要，完整参数及 run_id 在 `experiments/validation_summary.json`，重新运行的方法和定义在 `experiments/validate_dynamics.py`。

Schelling 使用 20×20、密度 0.8、阈值分别 0.2、0.4、种子 11/22/33，最多 40 步。非周期默认条件下 6 次均在 2–11 步结束，不满意比例从 0.062–0.329 降为 0；同类邻居有向比例从 0.496–0.514 增至 0.566–0.839。相同种子下 0.4 阈值的末态比例均高于 0.2。Mesa 官方示例的动态等价由上述逐步测试支持。

另以 NetLogo 7.0.4 自带 Segregation 模型实际无头运行，并将两模型均设为 20×20、周期边界、密度 0.8、阈值 0.2/0.4、各 3 个种子、最多 40 步。以源码核实的同一公式“同类邻居数总和 / 已占邻居数总和”比较：阈值 0.2 时 Mesa 末态为 0.542–0.614，NetLogo 为 0.542–0.571；阈值 0.4 时 Mesa 为 0.792–0.823，NetLogo 为 0.807–0.847。所有 12 次末态不满意比例为 0，均观测到同类比例上升。两模型的迁居方式和无邻居满意判断不同，种子对应的伪随机流也不同；这些数据只支持定性比较，不能声称逐轨迹复现。详细值和重跑入口见 `experiments/netlogo_mesa_summary.json`、`netlogo_comparison.xml`、`compare_netlogo.py`；未复制 NetLogo 源代码。

Deffuant 使用 N=100、均匀初始意见、种子 11/22/33、每步 100 次配对、共 150 步，epsilon 为 0.1、0.3、0.6，mu 为 0.25、0.5。将末态排序后，以相邻意见间距大于 0.02 分组：epsilon=0.1 时各组数为 5–6；epsilon=0.3 时为 2–3；epsilon=0.6 时均为 1。举例，mu=0.25 时三个种子的平均意见方差，在 step 0/50/100/150 分别为：epsilon=0.1 时 0.08265/0.07700/0.07699/0.07699；epsilon=0.3 时 0.08265/0.02614/0.02613/0.02613；epsilon=0.6 时 0.08265/0.00000/0.00000/0.00000（均四舍五入到五位小数）。该 0.02 是本次观测规则，依赖固定时刻和阈值，不能等同于严格稳态簇数。与原论文作者稿 §2.2 报告的较低阈值多组、较高阈值趋于一致的趋势定性相符；样本量、随机流和时间不同，未进行精确数值复现，也未声称所有运行达到收敛。mu 的影响不应根据这少量有限步结果作统计推断。

## 浏览器和安全限制

使用本地 Solara 服务实际打开两模型。Schelling 检查了图形、单步、重置，以及将 homophily 从 0.4 调为 0.5 后重置并显示更新配置；Deffuant 检查意见直方图、单步、连续运行、暂停、重置。Schelling 单步运行和 Deffuant 24 步运行在重置后分别生成 `interrupted` 清单和带校验值的轨迹。不同浏览器、长时间运行、断网/断电以及并发用户尚未系统验证；不推荐在界面中启用多线程来运行正式实验。

本机找不到 Docker。隔离接口只验证了 Docker 不可用时拒绝执行，不声称 Docker 端到端、安全逃逸防护或资源上限经过实测。建议在独立隔离环境补测。当前工作目录未发现旧论文或旧代码，因此无法作旧版源码/结果对照；详见 MODEL_SOURCES。
