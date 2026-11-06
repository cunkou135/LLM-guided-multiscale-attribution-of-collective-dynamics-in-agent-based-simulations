# 固定想定版本协议

scenarios根目录的schelling.md和covasim.md保持1.0原始字节和旧路径，v2/目录另存本次任务逐字给定的2.0标题与正文。UTF-8、LF；Git属性固定换行。两版仅包含场景文本，不加入网格、人口、参数、预设指标或因果关系。manifest.yaml以场景编号下的versions映射登记，不覆盖旧记录。

| 编号 | 版本 | 文件 | SHA-256 |
|---|---|---|---|
| SCENARIO-SCHELLING-001 | 1.0 | schelling.md | 820cbcc69f941c2b468f31a7b1ef22488a4271423bd37bbbf232badda2992b3d |
| SCENARIO-COVASIM-001 | 1.0 | covasim.md | 7a477bf35fd70f0d9847cd260efd2f05f5d7ec1d6055aeb4f954e923412f8c6b |
| SCENARIO-SCHELLING-001 | 2.0 | v2/schelling.md | ecfa1373637c172b6e1ab2786a9d4b803ea9f58ae65963f2d883326dde85d4c7 |
| SCENARIO-COVASIM-001 | 2.0 | v2/covasim.md | 50bcd64c7fbd6ca511fa899e452450013a0a59db3ec235b5b7350ec53f381cde |

`load_scenario(scenario_id, version='2.0')`按版本返回对应文件；每次校验全部四份文件、manifest和SHA256SUMS，篡改直接拒绝。不得自动改哈希放过异常。默认研究配置显式选择2.0；标准参考配置显式选择1.0。兼容旧YAML：未写scenario_version时runner映射为1.0。历史清单已经记录自身版本，Trajectory直接读取历史日志，不套用新版本。

固定想定是后续LLM唯一的自然语言研究输入；YAML是仿真输入，日志是实际执行记录，图形与指标是后续产物。这些材料分别保存。运行表和清单包含scenario_id/version/sha256，目录复制本次scenario.md。文本版本正确不能替代模型机制或现实校准验证。

## 迁移鱼群想定

另登记SCENARIO-FISH-001/1.0，scenarios/fish.md按用户原文件逐字复制并保留换行；哈希f2714fa2fd10ebc949f2f91843387ad5965f6eca75a4cb60496a4f6c7642a936。它作为新增场景独立管理，未改变原两场景的1.0/2.0内容。所有正式启动同时校验原四份文本及本份文件，输出scenario.md复制实际文件字节。
