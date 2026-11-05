# 复现说明

使用 Python 3.12 和 Mesa 3.5.2，安装方法见 README。每个结果目录具有随机 `run_id`、完整 `resolved_config.yaml` 和 `manifest.json`；清单包含模型、种子、状态、实际步数、UTC 起止时间、Python/Mesa 版本、Git 提交、工作区是否有未提交更改，以及各 Parquet 文件 SHA-256。未处在 Git 仓库时提交号为 null。`git_dirty=true` 的结果不能单凭提交号精确还原源码，应另保存工作区差异；依赖传递版本也请单独用 `python -m pip freeze` 保存。

默认输出是三张 Parquet 文件和字段目录，运行 ID 为文件隔离标识，不参与模型随机数。相同配置和种子在相同软件环境内状态与事件应相同（除 run_id 和墙钟元数据）；自动化测试以表格比较。相同种子在不同参数配置下不保证随机事件一一对齐。Mesa 模型内部和日志/可视化使用同一核心，绘图和记录不调用模型随机数。

复现定性试验：`python -m experiments.validate_dynamics`，结果写 `results/validation_dynamics.json`，并为每次运行建立独立目录。各项参数、种子、固定预算和群组定义在脚本中；仓库中的 `experiments/validation_summary.json` 是一次实际运行摘要，其 run_id 对应原执行环境，不代表其他用户已经拥有原始目录。重跑生成新的 run_id。请不要只选表现良好的种子，也不要将有限步结果当作已经收敛。

可选 NetLogo 对照要求自行安装 NetLogo 7.0.4 和自带 Segregation 示例。Windows PowerShell 中将 `$nl` 设置为安装目录后，运行以下命令，再执行 Python 比较脚本；此步骤不修改也不复制 NetLogo 模型源码。其他操作系统须使用对应的 Java 路径。

```powershell
& "$nl\runtime\bin\java.exe" '-Dfile.encoding=UTF-8' "-Dnetlogo.extensions.dir=$nl\extensions" --add-exports=java.base/java.lang=ALL-UNNAMED --add-exports=java.desktop/sun.awt=ALL-UNNAMED --add-exports=java.desktop/sun.java2d=ALL-UNNAMED -cp "$nl\app\netlogo-7.0.4.jar" org.nlogo.headless.Main --model "$nl\models\Sample Models\Social Science\Segregation.nlogox" --setup-file experiments/netlogo_comparison.xml --experiment comparison --table results/netlogo_comparison.csv --threads 1 --min-pxcor 0 --max-pxcor 19 --min-pycor 0 --max-pycor 19
python -m experiments.compare_netlogo results/netlogo_comparison.csv
```

实际执行时，使用前先在当前 PowerShell 会话中设定 `$nl` 为本机 NetLogo 7.0.4 安装路径。两套模型的随机过程与规则差异见 MODEL_SOURCES；相同整数种子不表示相同初始布局。

`status=stable` 仅表示 Schelling 的参考停止条件；`max_steps` 表示达到外部上限；`interrupted` 表示界面中断或重置；`error` 表示失败且轨迹可能不完整。界面运行的最后记录在正常完成或重置时关闭；进程被强制终止、机器故障时，正在写入的 Parquet 文件可能未完成。只有检查了 manifest、校验和和状态之后才应将其用于分析。批量执行是串行且各运行互不覆盖。
