# Covasim 来源核查工作记录

核查日期：2026-11-05。该文件记录开发中的证据，尚不代表完成历史复现。

- 用户提供的 Nature Communications 原文 Methods（PDF 文本：Model）明确写出 Covasim 2.0.0、Python 3.8；Population and network model 写出 SynthPops 0.7.2。该研究使用人口/年龄、诊断死亡、SafeGraph 移动、长期护理机构及隔离检疫的专用校准。
- 用户提供的 PLOS 原文 Software tests 一节提到 2.1.1 版测试覆盖率，因此模型论文不能被误认为与 NC 所用版本完全相同。PLOS 原文 Source code 说明当时使用 CC BY-SA 4.0；不能用当前主分支的 MIT 许可替代旧版本许可核查。
- https://github.com/covasim/controlling-covid19-ttq 当前取到提交 `3cedd27906035b929fbabd55d215d99e3b0f32ba`；requirements_frozen.txt 为 Covasim 2.1.2、Numba 0.53.1、NumPy 1.20.2、Sciris 1.1.1 等。README 指定 Ubuntu 18.04/20.04 + Python 3.8。这与论文中的 2.0.0 不同，尚须明确区分归档与当前公开仓库。
- 该仓库 LICENSE 为 CC BY-SA 4.0，版权归 Institute for Disease Modeling。当前项目尚未复制其源码，后续若移植须保留许可及修改说明。
- inputs 提供年龄分箱、疫情时序、移动和 SCAN 患病率 CSV；未直接提供 create_sim.get_popfile 所需的 kc_rnr_seed0..4.ppl。cache_populations.py 描述使用 SynthPops 生成 225000 人、5 个种子人口，映射 LTCF 为 l；create_sim 使用 pop_scale=10、2020-01-27 开始、h/s/w/c/l 层及校准干预。生成新人口不能声称等同于原作者缓存。
- fig3_theoretical/run_fig3a.py 提供不依赖金县人口缓存的公开基准：N=100、hybrid、初始感染 1、种子 8、125 天，none/test/trace 三种干预。它调用 version='2.0.0' 参数；可作为原生引擎与平台日志观测是否影响模拟的优先验证入口，但不等于金县历史校准。
- 当前机器 Python 3.12 与 3.10 可用，正在为 2.0.0 建立独立 3.10 兼容环境；这不是论文冻结的 3.8 环境，未经结果对照不能称为完整环境复现。下载/安装失败记录会保留于验收说明。
- 取得 Zenodo 4699175 实际归档（amath-idm/controlling-covid19-ttq-v1.2.0.zip，17853737 字节，归档目录提交前缀 f04550f）。归档 README 指定 Python 3.8，未发现同级 requirements_frozen.txt；当前 GitHub 的 frozen 文件不能直接冒称归档文件。仍需核查归档 setup.py 和专用配置。
- 已核查归档 setup.py：声明 Python 3.8，但 install_requires 的 Covasim、Sciris、NumPy 等均未固定版本；归档未包含 .ppl 人口缓存。因此不能将直接安装归档认定为已经恢复论文冻结环境。
- 实际安装 Covasim 2.0.0 wheel SHA-256 为 a077b79498ba7a7c2ea9d5818bb1c4feac263cd875e51c634b6f414913bef014；wheel 内 LICENSE 确认为 CC BY-SA 4.0。Python 3.10 兼容依赖安装成功，首次导入在 Sciris 1.1.1 + Matplotlib 3.10.9 上因 register_cmap 已移除而失败；正在固定兼容的 Matplotlib 3.6.3 后重试，未修改引擎源码。
- 固定 Matplotlib 3.6.3 后实际运行通过。`experiments/check_covasim_engine.py` 在 none/test/trace 三组 Figure 3 参数下分别运行原生调用与适配器观测路径，各 126 个日更新，对全部 40 个个体字段逐日比较并对照完整 infection_log，全部相同。真实结果见 experiments/covasim_engine_validation.json，实际依赖见 requirements-covasim-compat-lock.txt。该测试只证明兼容环境内适配器未改变原生运行，不是与作者缓存结果的匹配，也不是金县历史校准。


## 最终补充证据

公开归档中的Figure3缓存已实际加载并对照（仅在独立环境中加载已知出版社pickle）。与本次2.0.0重跑的完整感染日志、40个最终字段及29条结果序列均匹配。缓存内version属性为3.0.1，不能当作2.0.0完整环境的直接证明；本项目保留这一差异。此前“尚未对照作者缓存”的开发阶段状态已由这次对照替代。仍未完成金县历史人口和校准复现。

归档SHA-256: e09210384c07ad57c62e5abc920163c7165b0cc6a9d5db1276b6324cac35d0ba。
Figure3缓存SHA-256: 8f562e6823ca38f7f4db601ee51985c2825eeaa841c9f2707c853a02bcecfa34。
