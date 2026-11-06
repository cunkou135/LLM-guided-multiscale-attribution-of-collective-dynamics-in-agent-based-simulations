# 第一部分重构需求评审（2.0）

开发前 fetch 后本地和 origin/main 均为 99d081a4050e1bbbd53975e7260b9f3654e9c671。工作区已有本会话真实 API 测试引入的传输修复、配置与文档修改，均保留整合。未修改 simulations、固定 scenarios 或原始日志；历史实验与原始响应不覆盖。

重构前真实回归为 114 passed（含基准 107 项及 7 项流式传输测试），见 validation/pre_v2_baseline_114.xml。传输曾发生 402 余额不足、IncompleteRead、流中断及变量生成超时，均留在各原实验目录；不能把它们当成功生成。

既有接口复用 simulations.common.trajectory_api.Trajectory 的 metadata/configuration/catalog/read/available_steps/source_fingerprints/compute/compute_isolated；不重建仿真平台。Fish 为 fish-3.0，默认 2000 鱼/5 鲨鱼；Covasim 为原生 2.0.0、独立 Python 3.10，记录实际个体状态、事件和接触。

固定输入实查：Fish 运行 2a815b4dfe4f47b8ac2416fac04456e5（21 快照），想定 1.0、SHA-256 f2714fa2fd10ebc949f2f91843387ad5965f6eca75a4cb60496a4f6c7642a936；Covasim 运行 3249f90463154305aed53504106b3dae（61 快照），想定 2.0、SHA-256 50bcd64c7fbd6ca511fa899e452450013a0a59db3ec235b5b7350ec53f381cde。此前原始数据审计在 validation/existing_inputs_audit.json。

本轮必须改变原先的两个约束：变量/代码阶段要获得完整真实公共 Schema；候选图不再限制向上完整路径。新增 Schema 与数据字典/嵌套 JSON 检查、字段需求一致性、三类独立边调用、去重来源、循环/孤立节点支持，并升级输出和检查点身份。

算法仍不读取模型决策源码作为提示词，不传原始日志数值，不加入固定指标或参考答案。第一轮仍只依据固定想定。三类边任务不互看边；本地不推断新增关系。

当前机器无 Docker，默认策略保持拒绝不可信执行。真实 API 功能验证可采用 generate-only，生成与实际计算分别报告；可信模式需要真正的人工审查与代码哈希批准。现有 API Key 只在测试进程中从用户已有配置读取，不再次索要、不记录、不提交。

论文工作目录未发现可逐句核对的正文，方法文档依据本轮用户确定的两部分结构；不声称与未提供的稿件完全一致。
