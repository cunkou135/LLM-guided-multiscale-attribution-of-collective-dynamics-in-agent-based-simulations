# 模型来源、版本与许可

## Schelling

- Schelling, T. C. (1971). Dynamic models of segregation. *Journal of Mathematical Sociology*. [doi:10.1080/0022250X.1971.9989794](https://doi.org/10.1080/0022250X.1971.9989794)。原始理论包含多种设定；不能将任何现代网格示例简单等同为原始论文的唯一实现。
- 实际逐项选择的可运行参考是 [Mesa v3.5.2 Schelling 示例](https://github.com/mesa/mesa/tree/v3.5.2/mesa/examples/basic/schelling)，核查的是安装的 3.5.2 wheel 中 `model.py` 和 `agents.py`，不是 main 分支。Mesa 版权归 Core Mesa Team and contributors，Apache-2.0，原版权通知保留于根目录 `THIRD_PARTY_NOTICES`。本项目针对该参考规则重新实现，加入原始状态/事件采集、可配置边界与实验步数上限；Mesa 上游未提供本项目的日志和界面封装。
- [Wilensky, NetLogo Segregation](https://ccl.northwestern.edu/netlogo/models/Segregation) 是独立比较来源：其文档描述包裹边界、按邻居比例判断和在附近寻找空位；Mesa 默认非周期边界，随机从所有空格选择。两者并非同一动力学实现，本项目没有复制 NetLogo 代码，不将其作为数值逐步基准。

## Deffuant

- Deffuant, G., Neau, D., Amblard, F. & Weisbuch, G. (2000). Mixing beliefs among interacting agents. *Advances in Complex Systems* 3, 87–98. [doi:10.1142/S0219525900000078](https://doi.org/10.1142/S0219525900000078)。[公开作者稿](https://opencourse.inf.ed.ac.uk/sites/default/files/https/opencourse.inf.ed.ac.uk/dbba/2023/deffuantmixingbeliefsamonginteractingagents.pdf) §2.1（第 2–3 页）给出完全混合随机二元相遇、严格阈值及对称更新；§2.2（第 3 页）说明 [0,1] 均匀初始化，第 4 页图 1 说明每个图示时间单位采样 1000 对。出版社页面访问受限，但上述作者稿已核查。代码根据数学规则独立重新实现，并未复制指定 Deffuant 源码。
- Lorenz, J. (2007). Continuous opinion dynamics under bounded confidence: A survey. [doi:10.1142/S0129183107011789](https://doi.org/10.1142/S0129183107011789)。概念背景；本次未依据其全文做定量复现。
- 指定 DOI [10.1093/comnet/cnac055](https://doi.org/10.1093/comnet/cnac055) 的正确作者是 **Kan, Feng & Porter** (2023)，不是任务文字中的 Li & Porter。其 [作者公开稿](https://www.math.ucla.edu/~mason/papers/cnac055.pdf) 研究网络重连扩展，本项目未实现该扩展，不能据此宣称重现其网络实验。
- Grimm et al. (2020), ODD protocol second update, [doi:10.18564/jasss.4259](https://doi.org/10.18564/jasss.4259)，用于组织模型描述。

## 代码位置与差异表

行号对应当前版本，可用函数名查找；若代码改动应重新核验。

| 项目 | 来源 | 当前实现 | 差异与动力学影响 |
|---|---|---|---|
| Schelling 初始化 | Mesa `model.py` 的 `Schelling.__init__`，逐格两次随机判断 | `simulations/schelling/model.py:34` | 参数和随机过程一致；两类数量及总数是随机结果 |
| 邻居及满意 | Mesa `agents.py` 的 `assign_state` | `model.py:13`, `:18` | Moore 邻域，比例只算已占格；无邻居为 0；>= 阈值满意 |
| 更新顺序与迁移 | Mesa `model.py` 的 `step`、`agents.py` 的 `step` | `model.py:22`, `:45` | 随机顺序使用上一轮统一计算的满意状态，随机空格迁移，之后统一重算；完全占满时失败，与官方空位置限制一致 |
| 边界 | Mesa 示例默认非周期 | `model.py:38` 的 `torus` | 可配置周期边界是显式扩展，可改变动力学；默认 false，与参考一致 |
| 终止 | Mesa `Schelling.step` 全体满意时停止 | `model.py:48`，`simulations/common/runner.py:102` | 加入外部步数上限，不改变一次主体决策；极端空群体按空集合全体满意，保留一轮后停止 |
| 连续意见及随机配对 | Deffuant 作者稿 §2.1–2.2 | `simulations/deffuant/model.py:12`, `:22` | 初始化均匀 [0,1)；每次从总体抽两个不同主体，完全混合，无网络 |
| 阈值及双向公式 | 同上 §2.1 公式 1–2 | `model.py:25` 至 `:30` | 用严格 `< epsilon`，使用更新前双方值；`0 <= mu <= 0.5`（含无更新边界） |
| 时间与采样 | 论文一次交互为基本单位 | `model.py:22`，`simulations/common/runner.py:96`, `:102` | 可配置多次交互组成一次记录步，事件逐次保存，不改变规则；最大步数不是收敛判据 |
| 日志时间点 | 本项目采集要求 | `runner.py:91`, `:96`, `:102` 和 `trajectory_api.py:81` | 初态、采样步和最终步；事件在对应行为执行时记录；未抽样状态会在 manifest 标注 |

## 与旧稿及旧代码对照

任务开始时当前工作目录未发现旧论文 TeX/PDF、旧仿真源码或实验配置，因此无法判断旧稿是否确实存在搬迁偏好、稀疏网络或 backfire，也无法进行源码级一一比对。若旧稿使用这些扩展，其结果不能直接声称由当前标准模型复现。正式投稿前需取得旧稿和原代码，逐项补充对应及 Methods 修订。

本仓库项目代码采用 Apache-2.0；已检查本环境安装包的许可证元数据：Mesa 3.5.2 和 PyArrow 21.0.0 为 Apache-2.0，PyYAML 6.0.2、Solara 1.57.3 和 pytest 9.1.1 为 MIT，Pandas 2.2.3 与 NumPy 1.26.4 为 BSD 类许可证；Matplotlib 3.9.3 具有其自带的 Matplotlib 许可证。Mesa `[viz]` 的其他传递依赖各自适用其许可证，重新分发它们时仍须逐项核查。未复制 NetLogo 模型源码。
