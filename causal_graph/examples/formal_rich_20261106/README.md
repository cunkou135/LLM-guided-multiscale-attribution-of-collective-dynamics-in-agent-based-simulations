# 真实 LLM 丰富候选图

用户授权另建实验；模型为 deepseek-flash，旧 6 变量结果保留。

|场景|现象|变量（微观/中观/宏观）|候选边（向上/向下/同层）|
|---|---:|---|---|
|Fish|8|72（24/24/24）|495（172/116/207）|
|Covasim|8|67（21/21/25）|454（98/121/235）|

139 份新函数只通过语法、签名和真实字段契约检查，本轮均未执行，数学等价尚待审查；可执行图为空。949 条边都是未验证的语义候选关系。

[查看全部 30 个视图](graphs/index.html)。包含完整图、方向分图、现象分图与矩阵，提供 SVG/PNG/PDF，Graphviz 图另附 DOT。完整密集图仍有交叉；分图、矩阵和交互相邻突出显示用于细读。矩阵行是来源、列是目标，按 micro/meso/macro 排列；编号映射见 fish/node_labels.json、covasim/node_labels.json。

两份 complete_experiment.zip 包含完整真实响应、全部成功/失败批次、函数和代码 SHA-256、检查点、恢复版本及 JSON/GraphML 图。preliminary_failed_experiments.zip 保存首次扩大规模失败，不作为完整成功实验。archive_sha256.json 可校验压缩包。

summary.json 保存实际调用数、原始失败数及用量，不隐藏重试。code_structure_recheck.json 保留字段契约差异警告，source_versions.json 与 layout_validation.json 分别记录源码对照和绘图检查。

在仓库根目录执行 `python -m causal_graph.examples.formal_rich_20261106.verify_archives` 可只读核对全部变量定义、函数、关系与真实响应，无 API 调用或指标执行。说明见 [验收报告](../../docs/RICH_GENERATION_ACCEPTANCE.md) 与 [配置说明](../../docs/FORMAL_RICH_EXPERIMENT.md)。
