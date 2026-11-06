# 模型来源、版本与许可

## Schelling

- Schelling, T. C. (1971). Dynamic models of segregation. *Journal of Mathematical Sociology*. [doi:10.1080/0022250X.1971.9989794](https://doi.org/10.1080/0022250X.1971.9989794)。原始理论包含多种设定；不能将任何现代网格示例简单等同为原始论文的唯一实现。
- 实际逐项选择的可运行参考是 [Mesa v3.5.2 Schelling 示例](https://github.com/mesa/mesa/tree/v3.5.2/mesa/examples/basic/schelling)，核查的是安装的 3.5.2 wheel 中 `model.py` 和 `agents.py`，不是 main 分支。Mesa 版权归 Core Mesa Team and contributors，Apache-2.0，原版权通知保留于根目录 `THIRD_PARTY_NOTICES`。本项目针对该参考规则重新实现，加入原始状态/事件采集、可配置边界与实验步数上限；Mesa 上游未提供本项目的日志和界面封装。
- [Wilensky, NetLogo Segregation](https://ccl.northwestern.edu/netlogo/models/Segregation) 是独立比较来源：本机 NetLogo 7.0.4 的模型源码显示包裹边界、在附近寻找空位；Mesa 默认非周期边界，随机从所有空格选择。NetLogo 的 `similar-nearby >= threshold * total-nearby` 在没有邻居时判断为满意；Mesa 在阈值大于 0 时判断为不满意。NetLogo 的 `percent-similar` 源码实际计算全部同类邻居数之和除以全部已占邻居数之和，与本项目同定义的有向邻居比例可比较（网页使用“平均”措辞可能令人误解）。两者并非同一动力学实现，本项目没有复制 NetLogo 代码，不将其作为数值逐步基准。

Schelling 的具体源码对应为：Mesa 示例 model.py:Schelling.__init__ 对应 simulations/schelling/model.py:Schelling.__init__（逐格独立占用和类型抽样）；agents.py:SchellingAgent.assign_state 对应 Resident.assign_state 与 counts（Moore 已占邻居比例、孤立主体为0）；agents.py:step 对应 Resident.step（上一轮满意状态控制迁居）；model.py:step 对应 Schelling.step（随机顺序、整轮后统一重算、全体满意停止）。日志由 states/summary 和 runner.RunSession.snapshot 在初态、采样步及末步采集。torus=true 是显式边界配置扩展，默认false与示例一致；最大步数是外部预算，不改变一次迁移决策。

## 本研究的 Schelling 扩展

`simulations/schelling/model.py`保留基准规则，`extended.py`实现schelling_extended。个体阈值拒绝抽样、有限Chebyshev迁居、原位置腾空后候选评分、优先满意/其次严格改善与冻结判断，均为本研究明确规定的实验设置。没有声称逐步复现另一篇扩展Schelling论文。它使用Mesa网格与调度组件，但决策机制与标准示例不同。完整规则、参数与验证范围见MODEL_SPECIFICATIONS和VALIDATION_REPORT。

## Covasim 与 NC 研究

平台固定原生 Covasim 2.0.0，在独立 Python 3.10 兼容环境中执行。该环境不是论文原始 Python 3.8 冻结环境。模型来源为 Kerr et al., PLOS Computational Biology (2021), doi:10.1371/journal.pcbi.1009149；历史案例为 Kerr et al., Nature Communications (2021), doi:10.1038/s41467-021-23276-9。

原文 Methods 说明 Covasim 2.0.0、Python 3.8、SynthPops 0.7.2；当前 TTQ GitHub 提交 3cedd27906035b929fbabd55d215d99e3b0f32ba 的 frozen 文件使用 Covasim 2.1.2。Zenodo 4699175 的 v1.2.0 归档未附冻结清单，其 setup.py 依赖未固定。缓存对象 version 属性为 3.0.1。必须保留这些版本差异，不据此猜测所有历史执行环境。

`experiments/check_covasim_engine.py` 按公开 Figure 3A-C 参数重新配置 none/test/trace 三组；本次每组完整 infection_log、40 个最终个体字段和 29 条结果序列与归档 fig3_transtrees.obj 匹配，且逐日观察接口不改变原生状态。该有限基准不是金县历史人口与疫情校准复现。

历史研究使用 225000 人 SynthPops 人口及 pop_scale=10、h/s/w/c/l 接触层、金县年龄与病例/死亡、SafeGraph 移动及专门校准。公开目录和归档提供 CSV 及部分缓存结果，但没有 create_sim.get_popfile 要求的 kc_rnr_seed0..4.ppl。现有演示明确为 hybrid 人口、未校准、没有 LTCF 层；其参数是公开声明的试验设置，不是虚构的金县校准结果。历史复现保持 false。

| 规则或接口 | 原生 2.0.0 源码 | 本项目位置 |
|---|---|---|
| 初始化、种子、人口 | covasim/sim.py:Sim.initialize, population.py:make_people | simulations/covasim/adapter.py:build_sim, CovasimAdapter.__init__ |
| 每日状态更新、接触、干预、传播 | sim.py:Sim.step | CovasimAdapter.step 直接调用原生 step |
| 感染来源、目标、日期和层 | people.py:People.infect, infection_log | CovasimAdapter.events 只读转交，不推造传播链 |
| 个体字段与状态日期 | defaults.py:PeopleMeta, people.py:People | CovasimAdapter.states 输出全部 40 字段 |
| 分层潜在接触网络 | people.py:update_contacts, base.py:Layer | CovasimAdapter.contacts 保留 p1/p2/beta 和原层名 |
| 检测与检疫干预 | interventions.py:test_prob, contact_tracing, change_beta, clip_edges | build_sim 将 YAML 转为原生干预对象 |
| 观察与运行组织 | 平台增加功能 | RemoteCovasim + runner.RunSession；所有表格及访问通过 trajectory_api.py |

Covasim 2.0.0 wheel 与 TTQ 归档均为 CC BY-SA 4.0，不能使用 Covasim 当前主分支的 MIT 许可替代旧版许可。旧引擎作为独立安装依赖，未改写或捆绑源码；本平台适配器独立实现。TTQ 配置按公开参数重新声明，未复制其源文件。依赖的原始许可证与版权必须保留。细节及实际安装失败记录见 COVASIM_SOURCE_AUDIT.md。

任务开始时当前项目未发现旧论文 TeX/PDF 或旧仿真源码，无法宣称旧稿源码级一致。已有 Deffuant 模型和配置按本次新范围移除，历史提交仍可在 Git 历史中审计。Mesa 的 Apache-2.0 通知保留于 THIRD_PARTY_NOTICES；其余依赖适用各自许可证。

## 用户提供的鱼群场景与界面参考

鱼群运动与鲨鱼场景迁移自用户提供的pt/collective_motion_lab。引擎文件逐字保留，来源哈希、原始配置/文本/样式文件哈希及本次逐帧行为基线进入experiments/validation/。界面的纸面/松绿/深海色与鱼形绘制参考同项目，不修改原目录，不移植其离线LLM与Reward程序。详细边界见FISH_MIGRATION.md。
