# 可复查的实际运行产物

`demo_final_causal_graph.json` 为真实执行 M1–M5 得到的示例结果：6 个有效节点、4 条带估计时滞的边。`verification.json` 保存额外的数据、模型及图完整性核验结果；`full_regression.xml` 保存全部 179 项测试用例。

`acceptance_bundle.zip` 包含独立模块 demo/数组输入的实际 JSON 输出、实际 GRU 参数 `.pt`、每轮训练记录、完整集成示例输入与审核、Fish/Covasim 真实输入准入报告、丰富实验空图报告、环境版本和 16 条命令日志。M5 的独立人工证据夹具明确标记，不能作为算法估计结果；集成示例证据均来自真实计算。

`SHA256SUMS` 用于核对发布产物。归档中的绝对路径记录原验收机器位置；在其他位置复现时会生成新的路径和哈希。原始真实观测未复制进本归档，仍保留于第一部分既有归档中；对应输入哈希记录在审核报告中。

从仓库根目录运行：

```powershell
python causal_discovery/examples/run_acceptance.py
python -m pytest -q --junitxml=causal_discovery/results/full_regression.xml
python causal_discovery/examples/verify_acceptance.py
```

数组输入见上级 `inputs/`；方法、使用条件和参数详见 [中文说明](../../README.md)，逐项核对见 [验收报告](../../docs/ACCEPTANCE_20261107.md)。Fish 和 Covasim 的当前数据不满足正式统计分析条件，归档没有用合成数据替代真实数据，也没有强制输出真实场景的因果结论。
