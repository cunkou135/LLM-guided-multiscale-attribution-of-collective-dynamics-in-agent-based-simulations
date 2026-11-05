# 双场景平台开发验收报告

核查日期：2026-11-05。所有数字来自实际运行；原始结果留在本机 results/，可复现脚本及精选摘要进入仓库。未将未校准模拟称为真实金县疫情复现。

## 已完成内容与命令

- 固定想定 1.0 原文、manifest、SHA256SUMS 与代码固定哈希；每次运行校验两份文件。篡改拒绝、场景与模型匹配、输出来源信息均有自动测试。
- Schelling 沿用 Mesa 3.5.2 规则；Covasim 使用独立 Python 3.10.2 中的原生 2.0.0。配置、串行批量、结果目录、统一 Parquet 记录及查询和指标接口共用。Deffuant 源码及配置已移除。
- `python main.py run --config configs/schelling.yaml` 实际通过，默认种子在 8 步达到全体满意。`python main.py run --config configs/covasim.yaml` 实际执行 N=1000 的 60 日演示，本次结果 cbd74d90786241778eff9f3e998153b4 有61000条主体状态、481条感染事件、201条检测事件、4957条状态转移事件及保留层名的每日接触边。完整输出四张表；达到执行预算应记 max_steps，不等于疫情稳定。开发中发现曾将原生 complete 误标 stable，已修复并通过测试检查。
- `python main.py batch --config configs/batch_schelling.yaml` 批次 batch_61af099b04314334b4e78dcc9859f063.json，6 次成功。`python main.py batch --config configs/batch_covasim.yaml` 批次 batch_4f014d45c0e8431ea5d067f391f7a09c.json，4 次成功、0 错误。不同运行互不覆盖，测试覆盖某组合非法时继续保留其他成功运行。
- `python -m pytest -q` 检查状态、规则、种子重复、独立种子、完整和低资源日志、元数据、导出、动态指标、固定想定以及界面/无头一致性。本次最终实际输出为26 passed（50.53秒）；不能引用旧版平台的通过数。

## Schelling 对照

tests/test_reference.py 直接使用安装的 3.5.2 官方示例，在种子 2/42/97、12×12、density=.75、homophily=.4、非周期条件下，初态及后续 8 步所有主体 ID、类型、坐标、满意状态和停止状态一致。另测单格占用、人数守恒、孤立主体满意判断、周期边界与迁移。4×4 满格且不满意时原生空格选择会失败，保留 error manifest，未改行为绕过。

先前实际多种子检查中，默认非周期 20×20、density=.8、阈值 .2/.4 的 6 次运行均在 2–11 步稳定；同类邻居比例从 .496–.514 上升至 .566–.839。与 NetLogo 7.0.4 在相同周期 20×20、density=.8 条件下另做 12 次运行，同定义比例均上升；迁居方式、孤立主体判断和随机流不同，仅作定性比较。脚本与摘要保留在 experiments/。

## Covasim 公开基准与真实性

从 Zenodo 4699175 取到 v1.2.0 原归档，使用其中 Figure 3A-C 的公开缓存。`experiments/check_covasim_engine.py --reference-cache ...` 在独立环境中重跑 N=100、hybrid、初始感染1、种子8、125天（126个原生日更新）的 none/test/trace 三组。感染数依次 71/55/40；完整 infection_log 与 40 个最终个体字段逐值相同，29 条结果序列在 rtol=atol=1e-7 下匹配缓存；被动观测路径另逐日比较全部 40 字段，与原生直接运行一致。结果见 experiments/covasim_engine_validation.json。

缓存 version 属性为3.0.1，论文写2.0.0，当前 GitHub frozen依赖是2.1.2，原归档没有冻结文件。此版本差异完整保留；精确匹配的是以上已执行的小基准，不外推到所有历史结果。论文金县研究的225000人SynthPops缓存未在公开目录或归档中找到；未重新生成并验证同一人口和校准。因此当前通用Covasim配置始终标为 uncalibrated_demonstration、historical_reproduction=false，未复现原文全部金县疫情结果。

## 界面检查

两个 `python main.py ui --config ...` 均已在浏览器实际检查。Schelling 的空间图、单步、重置和参数更新通过；Covasim 的疾病状态图、感染/诊断时间序列、h/s/w/c接触层数、参数与干预配置可见，单步、连续、暂停、重置均有实际响应。Covasim 界面一次8步运行在重置后生成 interrupted 清单、场景哈希和四张表的校验值。两模型界面包装器与无头模式表格相同由测试验证。

实际边界失败记录：Covasim配置steps=1映射n_days=0，被原生引擎拒绝；现已在平台提前校验steps>=2，并修复失败时关闭管道可能掩盖原错误的问题。该失败未作为成功轨迹使用。

## 保留限制与人工确认

1. 当前环境不是原文 Python 3.8 冻结环境；金县历史人口、校准及全部原论文图表仍待专项复现。
2. 原生2.0.0没有提供全部失败传播尝试或同日重复检测的逐事件记录，也没有单独 isolated 布尔量。日志保留可观测事件，manifest 和 Schema 标记缺失，未推造传播链。
3. 大人口完整日接触日志会占用较多存储；writer 分批提交，但全规模人口性能未系统基准测试。低资源模式缺失明确登记。
4. 本机没有Docker，只验证隔离接口在无Docker时拒绝执行；容器执行未端到端验证。未经审查代码不得进入可信函数路径。
5. 浏览器断开、进程强杀及多用户/多线程并发未系统验证，正式实验使用无头串行模式并检查清单和哈希。后续论文Methods须明确默认演示与已验证公开基准的不同范围。
