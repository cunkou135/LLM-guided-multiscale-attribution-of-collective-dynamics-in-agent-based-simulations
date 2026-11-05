# 固定想定协议

`scenarios/schelling.md` 与 `scenarios/covasim.md` 为任务给定的 1.0 原文，UTF-8、LF 换行。文件仅含原始标题和正文；编号、版本、建立日期及性质在 manifest.yaml，文件字节 SHA-256 同时登记在 SHA256SUMS 和 protocol.py。Git 属性强制 Markdown 使用 LF，防止跨平台检出改变哈希。

`scenarios.protocol.load_scenario(scenario_id)` 每次校验两份文件与登记信息。内容或登记版本发生差异就抛出异常，报告文件、预期和实际哈希；即使请求另一份想定，也拒绝放过被改动的材料。不得自动重写或更新登记值来使实验通过。新场景须建立新编号与版本，当前两份原文保持不变。

固定想定描述背景；YAML 是执行参数；结果目录是仿真日志；后续指标、图及因果检验是分析产物。不得把参考图、检验结果或干预响应加入原文。Covasim 的历史背景不意味着所有使用该背景的仿真已校准或重现历史疫情。

运行清单及表格记录 scenario_id、scenario_version、scenario_sha256，结果目录保存本次使用的 scenario.md。两个模型均接入此流程；Covasim 默认运行另外标注未历史校准，哈希正确并不能替代模型校准验证。
