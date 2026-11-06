# 第一部分 2.0：十二步、六类独立模型任务

|步骤|函数|输入与输出|
|---|---|---|
|1 运行与固定想定检查|inputs.inspect_runs / inspect_run|完成运行目录；核对模型、版本、种子、参数、场景固定 SHA-256、数据哈希、实际时间与来源|
|2 公共数据 Schema|data_schema.build_data_schema|Trajectory.read/catalog；输出 data_schema.json 与 per-run 差异审计|
|3 宏观现象|generation.identify_phenomena|仅固定想定；输出 generation/phenomena/parsed.json|
|4 三尺度变量|generation.define_indicators|想定、现象、完整公共 Schema；输出语义、数学定义、单位、required_data|
|5 独立计算函数|generation.generate_codes|想定、变量定义、公共 Schema、统一契约；输出 required/config/python_code 及实现状态|
|6 向上边|generation.propose_upward_edges|想定及变量定义；micro→meso、meso→macro、micro→macro|
|7 向下边|generation.propose_downward_edges|相同想定及定义；macro→meso、meso→micro、macro→micro|
|8 同层边|generation.propose_intrascale_edges|相同想定及定义；同尺度不同节点间可单向或双向|
|9 本地合并|graph_export.merge_candidate_edges|三份原始边集合；只合并去重、记录来源与预算，不增加关系|
|10 校验及组装|schemas.validate_stage / graph_export.assemble_graph|严格 JSON、引用、尺度、自环、字段与代码检查；允许循环和孤立节点|
|11 执行与数值检查|indicator_runner.execute_indicator / check_result|原函数、声明字段及真实运行；独立序列、完整失败或未执行记录|
|12 导出与审计|graph_export.export_graphs / inputs.assert_unchanged|完整图、共同/逐运行可执行图、来源哈希与调用历史|

每一步保存输入、输出、开始结束时间及错误，六类调用均保存完整提示词、原始响应、解析和元数据。变量/代码提示词附完整 Schema 与版本/哈希；三个边任务不互相读取边。不存在第七次综合改图调用。

Schema 仅含数据结构、原数据字典含义和检查范围，不含原始观测值。共同字段按全部运行交集及类型一致性确定；嵌套 JSON 的检查范围明确标注为采样，并对不同运行仅保留共同路径。关联键是可供本地 join 的字段信息，不是因果证据；函数需处理空值、哨兵值、连接基数和时间窗口。Covasim 计划日期不等于已经发生的事件。

静态检查报告可识别的访问、未解析的动态访问以及 required_data/required 差异。运行时仅向函数提供声明列。AST 和字段校验不证明数学实现或科研含义正确，也不是沙箱。实现不可用时保留定义、原因与原边。

函数返回显式 step 的 Series/DataFrame；多列用 feature 区分。检查整数/实际时间索引、重复索引、有限数值及最少实际观测数。常数、高缺失发出警告；不做相关筛选。默认至少 3 个非缺失值是工程底线，不代表统计充分性。不同种子绝不拼接。

默认 Docker 缺失时拒绝执行。仅生成模式不执行可用函数；可信模式必须有人实际审查并批准精确 SHA-256。执行适配器只投影声明字段，原始模型代码不覆盖，适配器单独记录哈希。

检查点身份包含输入数据、模型档案、想定、公共 Schema SHA-256、模板、生成参数与源码。旧版身份不能在新版继续冒用；拒绝恢复也保存 proposed_identity 与错误，不覆盖原成功状态。原模型响应、解析哈希和代码修改均受到核对。历史执行追加 attempt_NNN，旧失败不删除。

## 本地科研计算路径

本项目不要求安装 Docker。明确审查与哈希批准后，--execution-mode trusted_reviewed 在独立 Python 子进程通过 Trajectory.compute 执行，保留完整输出日志与超时，不静默批准未知代码。--execute-only --resume 在本地执行分支允许执行器升级，但验证原全部检查点、输入与图语义并完全禁止 LLM 调用；原生成文件不会重写。传统生成恢复仍严格检查整个源版本。

审查失败和执行/结果失败分别记录。实体级 MultiIndex 按原观测单位保留；当前 Fish 两个微观函数因此得到各 2000 条独立主体序列，不转成群体均值。独立参考计算只用于验算，不用于产生指标结果或修补缺失值。核心生成算法和第二部分不改动。
