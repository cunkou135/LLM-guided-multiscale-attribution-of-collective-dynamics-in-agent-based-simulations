# 第二部分：时滞预测关系判别

本模块直接读取第一部分的 `executable_graph.json` 和节点 execution 指向的真实 Parquet 文件。依次执行数据适配、GRU 时滞选择、单父节点 RNN-Granger、多父节点两来源 MMI-PID、统一图整合。输出表达观测时间序列中的有向预测依赖和联合信息，不等同于结构因果真值。第一部分的生成算法、仿真模型和原始观测不作修改。本模块不调用 LLM，不运行仿真，也不需要 Docker。

## 环境与入口

使用现有 Python 3.12 环境；需要 NumPy、Pandas、PyArrow、PyYAML、PyTorch 和 jsonschema。仓库提供可选依赖 `discovery`，需要新建环境时可运行 `python -m pip install -e ".[test,discovery]"`。本次验收直接使用现有 Windows 环境，没有安装依赖，GRU 使用 CPU、单线程和确定性计算。

```powershell
python -m causal_discovery.pipeline --demo
python -m causal_discovery.pipeline --input path/to/executable_graph.json --output path/to/final_causal_graph.json
# 可选 YAML 只需提供覆盖项；未声明项使用 config.yaml。
python -m causal_discovery.pipeline --input path/to/executable_graph.json --config analysis.yaml --output results/final_causal_graph.json
python -m causal_discovery --demo
```

每次正式运行只有一个正式图文件 `final_causal_graph.json`；示例模式默认名为 `demo_final_causal_graph.json`。同目录的 `<文件名>_audit/` 保存 M1–M5 结果、数据处理原因、候选边处置、分组路由、参数、训练轨迹及实际 `.pt` 模型。JSON 包含观测文件哈希和算法源码哈希；输入图与已读取观测在执行末尾重新核对 SHA-256。

## 五个可独立运行的模块

五个 m 文件均不导入其他 m 文件。`_common.py` 提供 I/O、窗口划分和校准；`_rnn.py` 提供小型 GRU。只有 pipeline 负责调用五个模块。

| 文件 | 公开函数 | 数组输入 | JSON 输出 |
| --- | --- | --- | --- |
| m1_data.py | `align_arrays(x,y,steps=None)`；`adapt_graph(path,config=None)`；`align_target(data,target,parents)` | x、y、steps 或第一部分图 | 对齐数据、有效节点/边、运行分组、变换和失败原因 |
| m2_lag_rnn.py | `estimate_lags(y,parents,steps=None,target='Y',config=None,artifact_dir=None)` | y，`{来源ID: 数组}` | parent_lags、primary_lags、自记忆证据、稳定性、训练记录 |
| m3_granger.py | `test_granger(x,y,source_lags=None,...)` | x、y、候选时滞 | 样本外增益、主要时滞、真实校准记录及 supported/rejected/inconclusive |
| m4_pid.py | `mmi_pid(x1,x2,y,condition=None,...)`；`lagged_mmi_pid(x1,x2,y,source_lags,...)` | 两来源、目标、时滞 | I1、I2、I12、R、U1、U2、S（bit）、联合预测证据 |
| m5_graph.py | `integrate_graph(graph,data,lag_results,granger_results,pid_results,config=None)` | 前四模块结果，M1 有效节点 | `{graph,audit}`；CLI 将图和审核分别保存 |

参数签名中的 `...` 表示文件内有类型注释的可选关键字参数。M2–M4 的数值数组可为 `时间×特征`，也可为 `{run_id: 数组}`；steps 可按运行提供。JSON 会将非有限结果写为 null，但不会以 null 补造观测。

```powershell
python -m causal_discovery.m1_data --demo --output causal_discovery/results/m1.json
python -m causal_discovery.m2_lag_rnn --demo
python -m causal_discovery.m3_granger --demo
python -m causal_discovery.m4_pid --demo
python -m causal_discovery.m5_graph --demo

python -m causal_discovery.m1_data --input causal_discovery/examples/inputs/m1_data.json --output causal_discovery/results/m1_input.json
python -m causal_discovery.m2_lag_rnn --input causal_discovery/examples/inputs/m2_lag_rnn.json --output causal_discovery/results/m2_input.json
python -m causal_discovery.m3_granger --input causal_discovery/examples/inputs/m3_granger.json --output causal_discovery/results/m3_input.json
python -m causal_discovery.m4_pid --input causal_discovery/examples/inputs/m4_pid.json --output causal_discovery/results/m4_input.json
python -m causal_discovery.m4_pid --input causal_discovery/examples/inputs/m4_xor_static.json
python -m causal_discovery.m5_graph --input causal_discovery/examples/inputs/m5_graph.json --output causal_discovery/results/m5_input.json
```

`examples/inputs/` 提供可直接替换的数组。M2、M3 输入有 2400 个时间点；M4 动态输入有 6000 个时间点。静态四行 XOR 只验证信息分解，输出 decomposed 且 p=null，不能用四行数据声称统计支持。M5 独立示例使用明确标注的人工证据夹具，验证整合规则；M5 本身不估计数值证据。集成示例所有证据均来自实际 M1–M4 计算，未向时滞估计器传入生成时滞。

## M1：观测单位和时间轴

Parquet 读取 run_id、indicator_id、step、feature、value 和必要的 entity_id。各运行独立组织，不把运行拼接成连续时间。重复坐标、无穷数、非整数时间、过量缺失、常数特征、运行级标量广播、数据不足和观测哈希不符均记录原因。缺失不插补；滞后窗口必须具有完整的等间距历史，跨缺口的窗口会被排除。没有通过关系的有效节点可以保留为孤立节点。

主体记录必须显式选择聚合或映射。不会默认求均值，也不会将一个宏观目标复制为数千个独立样本。支持 `entity_mode: aggregate`（mean/median/sum）、`select`（固定 entity_id）、`features`（指定 entity_ids 形成一个向量）。多个 feature 必须显式选择。每次变换记录公式、特征顺序、观测单位及主体数量。实体向量和系统量对齐后每个运行、每个时刻仍然只有一行。

例如，预先决定研究总体主体均值时配置：

```yaml
data:
  node_overrides:
    my_micro_indicator:
      entity_mode: aggregate
      aggregation: mean
      aggregation_missing: propagate
      features: [value]
    my_layer_indicator:
      features: [c, h, s, w]
```

`observed` 缺失策略表示仅对已观测主体求聚合，必须显式配置并解释变化的总体；默认 propagate 传播缺失。原节点数学定义原样保留，新增 `analysis_transformations` 说明实际分析量，不能把聚合后的系统量解释为单个主体作用。

## M2–M3：GRU 与时滞

小型单层 GRU 预测 `Y_t=f(Y历史, 全部候选父节点历史)`。输入和目标只用训练数据标准化。最大候选历史为 `rnn.max_lag` 个记录间隔；输出 lags 和边权乘以实际 step_size，单位为仿真步。隐藏状态不解释为时滞。

M2 在独立 validation 数据上逐来源、逐时滞遮蔽输入，比较预测损失变化。遮蔽使用训练均值对应的标准化零值，只用于模型消融，不修改或填补观测。按预设绝对增益、相对增益、种子支持比例和主要时滞离散度报告 estimated、unstable、not_supported；长度不足单独报告 insufficient_data。相邻时滞可共同保留。目标自身时滞在独立 confirmation 分区再校准，最终自记忆边还需通过 M5 的校正。

M3 使用两套相同架构、参数总数、初始化种子、最大轮数、优化器与早停规则的 GRU：受限模型仅保留目标历史输入，完整模型加入来源的 M2 候选时滞。实际早停轮数、每轮训练/验证损失及参数均保存。受限输入通道通过掩码禁用，因此有效输入不同，但模型总参数容量一致。判别量是独立 test 数据上 `Delta=MSE受限-MSE完整`，使用训练标准化后的目标单位。独立调用未指定 primary_lag 时只在 validation 中选择；pipeline 使用 M2 估计。未选择出来源时滞时返回 inconclusive。

## 划分、校准和多重检验

四个分区为 train、validation（时滞选择及训练早停）、confirmation（自记忆确认）、test（M3/M4 最终评价）。至少四个运行时优先按独立随机种子分组，也可显式提供 `split.run_roles`。更少运行时按时间顺序划分，每个窗口的完整历史必须位于同一运行和同一分区，边界清除 max_lag 个目标位置。时间划分不等同于新随机种子，输出明确标注这一局限。默认最少窗口为 128/48/48/64；M1 还要求至少 256 个有限动态观测。这些是准入下限，不是对统计功效的保证。

校准使用固定样本外预测分数差的**中心化移动块 Bootstrap**：块不跨运行，多测试运行时先重采样运行，再在运行内抽连续块，各运行均等权重。检验零假设是“固定预测器的期望样本外增益不大于零”。M3 使用平方损失差；M4 使用 log2 预测分数差。记录 block_length、重采样数、有限样本、种子和区间，`p=(1+零分布中不小于观测值的次数)/(B+1)`，不填零。默认 B=499，最小可分辨 p 为 0.002；检验数量较大时需要预先增大 B。

该校准是时间相关预测分数检验，依赖分数差的弱平稳性、弱依赖/混合性，以及独立种子运行假设，不是精确条件独立性检验。四个时间块均值漂移诊断只排除明显违例，不能证明假设成立。`assume_weak_stationarity: false`、诊断失败或样本不足时 p=null、p_value_valid=false，结果为 inconclusive。少量独立运行和固定块长度下的有限样本校准仍有不确定性。未采用任意循环移位来源作为条件零假设替代，因为它还会改变来源与目标历史的依赖关系。

M5 默认对全部实际有效的校准 p 值统一作 Benjamini–Yekutieli（BY）校正，包含自记忆、Granger 和 PID 各分数对比，较保守。相关或重复对比也保留在预定检验族中；缺失 p 不加入检验族且永不自动接受。可预先配置 bh 或 none，但 BH 需要独立或正相关条件，none 不控制多重检验。校正无法修复基础校准假设的违例。

## M4：条件 MMI-PID

设 A、B 为 M2 所选时滞来源向量，C 为目标自身全部配置历史，Z 为当前目标。计算经验条件互信息 I1=I(Z;A|C)、I2=I(Z;B|C)、I12=I(Z;A,B|C)。按任务指定的 MMI 定义，R=min(I1,I2)，U1=I1−R，U2=I2−R，S=I12−max(I1,I2)，单位 bit。动态运行先各运行计算 CMI，再等权平均，避免混合不同运行产生信息。连续变量仅按训练数据分位点分箱；小整数状态可直接保留类别。高维直方图有偏且易稀疏，默认限制状态空间和训练上下文覆盖率，未覆盖时不声称显著。

另用训练数据拟合带固定 Dirichlet 伪计数的条件直方图，在 test 上评价边际、联合及联合相对每个单来源预测器的 log2 增益。伪计数仅平滑预测概率，不生成观测。分解值和预测增益是不同量，均单独保存。协同支持需要联合预测器同时优于两个单来源，采用 intersection-union 检验 `p协同=max(p联合相对来源1,p联合相对来源2)`，并要求 S 和增益达到预设下限。validation 上较好单来源仅为诊断，不替代两个对比。

MMI 较弱来源独特信息为零是定义结果，不能由此删除来源。冗余关系可依据各自边际预测证据保留。超过两个父节点按 ID 字典序、固定 max_pairs 上限执行两两分析，记录全部省略组合；不搜索三阶及更高阶协同，不实现 BROJA、SURD 或神经 PID。

## M5：最终图与联合关系

按 M1 清理后的**外部候选入度**路由：1 个父节点用 M3，至少 2 个用 M4；自记忆只用 M2。所有有效节点和科学字段保留，原候选外部边 ID、尺度分类、数学定义与来源保留。唯一新增的候选外关系是有统计支持的 self_memory 自环。无效节点及全部关联边删除，原因写独立审核。inconclusive 表示不能判断，未接受不表示关系不存在。

`weight` 为实际主要时滞的正整数，`lags` 保留其他受支持候选；没有把信息量当作边权。PID 协同整体作为联合组保存，两条原成员边共享 joint_group_id 和 joint_sources，分别具有自己的时滞。纯联合支持标为 joint_only，不能解读为每条边均独立有效。同一端点若同时有边际和联合支持，在一个 edge 的 evidence 内并存；不将协同值分摊给成员边。必要节点或候选成员缺失时整个联合组不能保留。JSON Schema 及附加语义检查验证 ID、端点、正整数时滞、自环类别和联合组完整性，允许反馈环与孤立节点。

## 已执行验收与复现

详见 [验收报告](docs/ACCEPTANCE_20261107.md)。示例实际结果、模型、命令日志及真实输入审核位于 [验收包](examples/acceptance_20261107/README.md)。

```powershell
python -m pytest -q causal_discovery/tests
python -m pytest -q
python causal_discovery/examples/run_acceptance.py
```

真实 Fish/Covasim 输入须先保留或解压第一部分原始执行归档 `causal_graph/examples/local_execution_20261106/*_complete_local_experiment.zip` 至 `causal_graph/results/v2_live_20261106/<场景>/`。不得复制或扩充时间点以通过准入。Fish 主体聚合与 Covasim 特征选择示例为 `examples/real_fish_config.yaml`、`examples/real_covasim_config.yaml`，其中仅明确观测变换，未降低检验门槛。更丰富的第一部分生成实验尚无已执行指标时，其空 executable_graph 会诚实返回 empty_input_graph。

方法参考：[PyTorch GRU](https://docs.pytorch.org/docs/stable/generated/torch.nn.GRU.html)、[Künsch，1989，移动块重采样](https://doi.org/10.1214/aos/1176347265)、[Diebold 与 Mariano，预测精度比较](https://www.nber.org/papers/t0169)、[Barrett，2015，MMI 的一种理论来源](https://arxiv.org/abs/1411.2832)、[Benjamini 与 Yekutieli，2001，多重检验](https://www.math.tau.ac.il/~ybenja/MyPapers/benjamini_yekutieli_ANNSTAT2001.pdf)。本项目按任务指定将 MMI 定义用于离散直方图，不声称该选择在所有离散系统中均具有唯一的协同解释。
