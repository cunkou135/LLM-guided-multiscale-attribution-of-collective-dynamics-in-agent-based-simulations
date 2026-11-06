# 2.0实际开发验收材料

此目录保留实际默认运行、性能、测试结果与真实图版，不使用占位轨迹。完整说明见../../docs/VALIDATION_REPORT.md。

- runs/3b1b5e8b6f9a41d695988be12ab8c060：扩展Schelling默认100×100，种子42，8499人，第7轮frozen。
- runs/3249f90463154305aed53504106b3dae：原生Covasim2.0.0默认1000人，种子8，60步max_steps；包含原生初始化/终态参数及完整潜在接触表。
- figures/schelling和figures/covasim_v2：本次2.0正式示例，4:3，SVG/PNG300/600DPI、预览、图版数据和来源清单。
- figures/*_16x9：同两次实际运行的16:9导出，没有再次模拟。
- figures/covasim：开发期间使用旧版1.0轨迹的早期示例，保留作为历史材料；本次交付使用covasim_v2。
- *_model_states.csv与*_data_profile.md：统一Trajectory接口读出的状态汇总及数据剖析。自动相关性提示只用于格式诊断，不是因果检验或论文结论。
- performance_*.json：单次实际测量，墙钟含日志写入，内存是20ms采样的父子进程RSS之和，不是分配器精确峰值。
- pytest.xml：最终40项测试结果。covasim_engine_validation.json为重跑的公开小基准；batch_schelling.json为默认固定参数、两种子批次功能检查。
- figure_layout_audit.json：两种画幅的程序布局检查。BASELINE_VALIDATION_REPORT.md保留升级前报告，其26项通过数属于旧基准。

运行和图版清单中的git_commit为执行当时的开发基准，git_dirty=true如实保留；本次最终提交保存实现代码与验收材料，不能将这些运行伪称为提交后执行。main_environment.txt是本机整个主环境的pip freeze记录，含其他软件及非便携本地构建路径；安装以pyproject和独立引擎锁定文件为准。


## 2026-11-06鱼群迁移与界面统一

新增fish_source_provenance.json及22帧fish_behavior_baseline.json；源引擎逐字保留，迁移后逐帧哈希匹配。48项完整测试及最终界面检查详见docs/VALIDATION_REPORT.md。runs/2a815b4dfe4f47b8ac2416fac04456e5包含2000条鱼、5条鲨鱼的20步实际记录；figures/fish包含其论文图版。ui/fish_scene.png是浏览器实际场景的单张截图，未生成演示视频/GIF。fish_batch_smoke.yaml为固定参数、两个种子的最小批量入口检查，不构成参数搜索。
