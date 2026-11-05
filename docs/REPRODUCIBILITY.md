# 复现说明

使用 Python 3.12 和 Mesa 3.5.2，安装方法见 README。每个结果目录具有随机 `run_id`、完整 `resolved_config.yaml` 和 `manifest.json`；清单包含模型、种子、状态、实际步数、UTC 起止时间、Python/Mesa 版本、Git 提交、工作区是否有未提交更改，以及各 Parquet 文件 SHA-256。未处在 Git 仓库时提交号为 null。`git_dirty=true` 的结果不能单凭提交号精确还原源码，应另保存工作区差异；依赖传递版本也请单独用 `python -m pip freeze` 保存。

默认输出是三张 Parquet 文件和字段目录，运行 ID 为文件隔离标识，不参与模型随机数。相同配置和种子在相同软件环境内状态与事件应相同（除 run_id 和墙钟元数据）；自动化测试以表格比较。相同种子在不同参数配置下不保证随机事件一一对齐。Mesa 模型内部和日志/可视化使用同一核心，绘图和记录不调用模型随机数。

复现 Schelling 定性试验：`python -m experiments.validate_dynamics`，结果写 `results/validation_dynamics.json`，并为每次运行建立独立目录。各项参数、种子、固定预算和群组定义在脚本中；仓库中的 `experiments/validation_summary.json` 是一次实际运行摘要，其 run_id 对应原执行环境，不代表其他用户已经拥有原始目录。重跑生成新的 run_id。请不要只选表现良好的种子，也不要将有限步结果当作已经收敛。

可选 NetLogo 对照要求自行安装 NetLogo 7.0.4 和自带 Segregation 示例。Windows PowerShell 中将 `$nl` 设置为安装目录后，运行以下命令，再执行 Python 比较脚本；此步骤不修改也不复制 NetLogo 模型源码。其他操作系统须使用对应的 Java 路径。

```powershell
& "$nl\runtime\bin\java.exe" '-Dfile.encoding=UTF-8' "-Dnetlogo.extensions.dir=$nl\extensions" --add-exports=java.base/java.lang=ALL-UNNAMED --add-exports=java.desktop/sun.awt=ALL-UNNAMED --add-exports=java.desktop/sun.java2d=ALL-UNNAMED -cp "$nl\app\netlogo-7.0.4.jar" org.nlogo.headless.Main --model "$nl\models\Sample Models\Social Science\Segregation.nlogox" --setup-file experiments/netlogo_comparison.xml --experiment comparison --table results/netlogo_comparison.csv --threads 1 --min-pxcor 0 --max-pxcor 19 --min-pycor 0 --max-pycor 19
python -m experiments.compare_netlogo results/netlogo_comparison.csv
```

实际执行时，使用前先在当前 PowerShell 会话中设定 `$nl` 为本机 NetLogo 7.0.4 安装路径。两套模型的随机过程与规则差异见 MODEL_SOURCES；相同整数种子不表示相同初始布局。

`status=stable` 仅表示 Schelling 的参考停止条件；`max_steps` 表示达到外部上限；`interrupted` 表示界面中断或重置；`error` 表示失败且轨迹可能不完整。界面运行的最后记录在正常完成或重置时关闭；进程被强制终止、机器故障时，正在写入的 Parquet 文件可能未完成。只有检查了 manifest、校验和和状态之后才应将其用于分析。批量执行是串行且各运行互不覆盖。


## Covasim 环境及公开基准

主程序的 Python 3.12 与原生引擎的 Python 3.10 通过流式记录协议连接，两个环境的软件版本分别登记。完整实测引擎依赖见 requirements-covasim-compat-lock.txt，固定原生2.0.0，不以最新Covasim或Starsim替代。演示配置的种子、参数与干预都保存到resolved_config.yaml；没有历史校准就不会标记为历史复现。

获取并复查原文小规模公开基准：

```powershell
python -m experiments.fetch_ttq_reference
.\.covasim-venv\Scripts\python.exe -m experiments.check_covasim_engine --reference-cache results/reference/fig3_transtrees.obj
```

下载器校验整个Zenodo归档SHA-256和所选缓存SHA-256，不执行缓存；后一步加载出版社提供的已校验pickle，仅在独立引擎环境执行。不要对任意来源的pickle使用此命令。实际比对结果在results/covasim_engine_validation.json，一次已核查结果在experiments/中。公开缓存不随平台源码再分发，保留原始CC BY-SA来源和使用条件。

Covasim平台step0是首次原生日更新之前，simulation_day=-1；平台step1完成day0。运行预算steps与原生n_days不同，adapter设置n_days=steps-1。完整记录模式保留全部可观测个体和接触快照，低资源模式可关表或降频。关闭界面、强制终止或断电可能留下未完成Parquet，检查manifest状态和校验值后使用。


若旧版Python的pip因本机代理/TLS连接失败，可用主环境Python准备离线wheel，再交给Covasim环境安装。此次开发采用了这一路径；没有关闭证书校验或修改引擎源码。Windows示例：

```powershell
python -m pip download --no-deps --dest results/bootstrap pip
.\.covasim-venv\Scripts\python.exe -m pip install --no-index --find-links results/bootstrap --upgrade pip
python -m pip download --dest results/covasim_wheels --python-version 310 --platform win_amd64 --implementation cp --abi cp310 --only-binary=:all: -r requirements-covasim-compat-lock.txt
.\.covasim-venv\Scripts\python.exe -m pip install --no-index --find-links results/covasim_wheels -r requirements-covasim-compat-lock.txt
```

原生初始化后的所有默认参数及终态实际参数，分别保存为native_parameters.json及native_parameters_final.json并校验，疾病参数不只依靠默认版本推断。
