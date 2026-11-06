# 真实模型测试报告：第一部分 2.0

日期：2026-11-06。模型请求与全部成功响应均为 **deepseek-flash**，未自动切换模型。

## 本轮新版结果

|检查|Fish|Covasim|
|---|---|---|
|输入真实运行|2a815b4dfe4f47b8ac2416fac04456e5|3249f90463154305aed53504106b3dae|
|真实 Schema|5 表、82 字段，含已检查 raw_frames 内部结构|4 表、113 字段|
|候选现象|2：鱼群分裂与多簇共存；群体整体拉伸|2：活动场所感染聚集；干预伴随接触与感染轨迹变化|
|三尺度变量|6：micro/meso/macro 各 2|6：micro/meso/macro 各 2|
|向上 / 向下 / 同层边|6 / 6 / 3|7 / 7 / 6|
|合并候选边|15|20|
|真实反馈环保留|是|是|
|生成代码且通过结构/字段检查|6 成功，0 失败，0 不可实现|6 成功，0 失败，0 不可实现|
|实际指标执行|0 成功、0 计算失败、6 未执行|0 成功、0 计算失败、6 未执行|
|可执行图节点|0|0|
|流程状态|generated_only|generated_only|

六类模型任务全部完成，JSON/签名/语法/字段声明/可识别访问及尺度检查通过；没有人工更改现象、变量、代码或边以取得成功。三类候选边分别生成，不通过综合调用重写。真实输出的反馈环未删除。

本轮是必要的端到端生成验证，不是完整数值计算验证。当前没有 Docker，两场景均实际调用默认隔离接口，返回 Docker unavailable，未回退到宿主执行。没有凭空生成序列，没有将 code implementation_status=implemented 当作计算已成功。真实函数的数值有效性、科学实现质量及跨随机种子计算仍需隔离环境或真正人工审查后验证。

## 配置、用量与耗时

使用现有私有配置中的连接与密钥，模型按用户指示为 deepseek-flash；新功能验证统一配置 temperature=0.3、max_tokens=32768、reasoning_effort=low、timeout=600 秒、max_retries=1、stream=true，并请求 usage。规模上限为 max_phenomena=2、max_indicators=6、max_edges=24，不作为正式实验规模或模型/参数优劣判断。

|成功响应阶段|Fish 秒|Covasim 秒|
|---|---|---|
|现象|28.09|9.06|
|变量|129.62|46.05|
|代码|38.27|306.08|
|向上边|22.36|23.23|
|向下边|18.30|28.20|
|同层边|27.08|22.03|

Fish 向上关系的首次流在约 182.8 秒中断，原始部分保留，重试后成功；因此向上阶段总耗时约 206.2 秒，不能仅用成功尝试耗时代表整个阶段。其他阶段无结构重生成。成功响应所报告 Token 合计：Fish input 33990、output 23545、total 57535；Covasim input 33939、output 42469、total 76408。这不包含供应商未报告用量的中断尝试，不能当作完整账单。

Covasim 有 5 条 required_data 与 required 声明差异警告，其中一条仅为字段顺序，其他主要为实现使用定义预计字段的子集。原定义未更改，两份声明和静态访问报告均保留，不将声明差异隐藏为完全相同。所有实际声明字段均在公共 Schema 内。

第一轮提示词没有实际 Schema；第二、三轮包含完整 Schema 且哈希一致；三类边任务未见其他方向边或生成代码。每任务保存 input_provenance.json、完整实际提示词、供应商原始 SSE、解析、校验、实际模型标识、usage 与耗时。密钥扫描通过，原配置未覆盖。

## 文件与可复查材料

本机完整结果为 `causal_graph/results/v2_live_20261106/fish/` 和 `covasim/`；各含 candidate_graph.json/.graphml、executable_graph.json/.graphml、data_schema.json、代码与全部过程记录。根 test_summary.json 为机器摘要，isolation_probes/ 为隔离拒绝记录。

公开归档在 `causal_graph/examples/v2_live_20261106/`：两份完整压缩包、便览图/Schema、无密钥配置、用量摘要和复现辅助脚本。归档前核对全部产物 SHA-256 与运行时记录的方法源码哈希；压缩包内保留原始字节与完整审计。

两个真实实验随后都用标准命令行 --resume --generate-only 成功恢复，未新增模型请求，六个检查点正确复用。恢复没有改变原始生成内容。

## 此前失败记录的区分

旧配置 deepseek-v4-pro 曾返回 HTTP 402 余额不足；随后 deepseek-flash 的旧方法测试遇到 IncompleteRead、不完整 SSE，以及完整规模 Fish 变量阶段的 180 秒预算超时。Covasim 旧代码生成阶段曾主动中止，没有已记录的明确 TimeoutError，不应误称其已触发同一超时。

这些旧输出保存在各 live_config_test_20261106、live_flash_test_20261106、live_flash_stream_20261106、live_flash_smoke_20261106 目录；方法重构后没有冒用旧检查点。新版使用独立目录、模板/图 Schema 2.0、真实 Schema 身份与上述统一配置。
