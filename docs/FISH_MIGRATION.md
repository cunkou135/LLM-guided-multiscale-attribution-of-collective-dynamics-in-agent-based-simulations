# 鱼群场景迁移与界面统一

本轮根据用户提供的pt/collective_motion_lab迁移鱼群与鲨鱼场景，并将全平台统一为原项目的米白纸面、松绿色控件、深海色画布。参考项目没有被改写。当前工作仓库是abms_lab，旁边pt/abms_lab是另一份运行中的副本，不在本次修改范围内。

## 原始规则保留

原文件simulation/fish.py逐字复制到simulations/fish/engine.py，SHA-256为a17aa7929ca719a63d0c4fffe7724c0c76a3a0868736846f5da51228f595ac86。复制文件不改初始化顺序、随机数调用、局部排斥/对齐/吸引、直接及社会受惊、持续期、转向限制或鲨鱼最近目标追逐规则。开放空间没有边界反弹、捕获及个体移除。

默认2000条鱼、5条鲨鱼、种子42、dt=0.08，原参数映射到configs/fish.yaml。平台最大步数1000只是外部运行预算，原模型内部规则没有增加停止或捕获机制。核心参数的标签、范围与选项从源config.yaml提取到fish_controls.yaml；显示配置独立在fish_display.yaml。根seed注入原引擎simulation.seed，原生参数仍使用原字段名。

原想定逐字复制为scenarios/fish.md，登记SCENARIO-FISH-001/1.0，SHA-256为f2714fa2fd10ebc949f2f91843387ad5965f6eca75a4cb60496a4f6c7642a936。该想定继承源场景文本，包含原来的背景和参数描述，不冒充Schelling/Covasim的2.0想定。原有四份固定文本及哈希保留。源文件带有的换行也保留，Git对这两个原始复制文件关闭文本换行转换。

迁移对象是仿真场景、参数和交互画布。原项目analysis指标库、候选因果森林、Reward及LLM生成流程未移植，继续遵守本平台先记录原始轨迹、再由后续算法提出变量与候选关系的边界。原生决策中的d/s/r/o/kappa/phi等字段按事实保留，不作为额外预先选定的因果图或指标库。

## 共用运行与数据入口

```bash
python main.py ui --config configs/fish.yaml
python main.py run --config configs/fish.yaml
python main.py batch --config configs/batch_fish.yaml
python main.py export --run-dir results/<run_id> --output figures/fish
```

start.py菜单新增第4项。页面也可随时从模型下拉框切换鱼群、Schelling或Covasim。鱼群参数在侧栏按组折叠并支持搜索，修改后重置生效；历史回放读取实际保存的帧。画布支持个体点击、邻域显示、平移缩放、镜头跟随、适应画面、空间网格和运动轨迹。鱼以有朝向的轮廓显示，鲨鱼使用更大的珊瑚色轮廓。原生行动分类沿用未受惊/直接受惊/社会受惊的配色含义。

核心适配器不修改引擎，只把输出交给RunSession和trajectory_api.py。agent_states保留鱼和鲨鱼真实UID、位置、朝向、速度、行动受惊类别、剩余步数和目标UID；events保留每次运动前后状态和完整个体决策JSON；contacts保留原生有向受惊邻居接触，不能当成成功社会传播因果边；raw_frames保存原生raw_frame完整JSON，包括全部随机抽样与decision_input。Trajectory.read_frame(step)精确恢复原始帧，不重新运行模型。

## 对照与验证范围

experiments/validation/fish_source_provenance.json记录源文件哈希。fish_behavior_baseline.json的22个原始帧直接来自本次用户给定源码，覆盖128条鱼、不同种子、5条/0条鲨鱼及默认2000条鱼的设置。迁移后的完整raw_frame逐帧哈希匹配；不是只比较终态或平均数。另检查实时检查点、无头轨迹、事件与接触表相同，读日志与绘图不消费引擎随机数。

这些测试验证迁移行为和工程接口，不是新参数搜索，也不证明原项目预设现象必然出现。源场景已经说明持续分裂等现象并非预先保证。界面使用相邻真实保存帧作显示插值，暂停及历史定位落到实际帧；插值不进入日志，也不改变模型时间和主体决策。

用户已取消演示录制，本次不要求生成视频或GIF。界面和状态通过真实浏览器检查，原有论文SVG/PNG导出独立保留。
