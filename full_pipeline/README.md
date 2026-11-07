# 想定到候选图及最终图的完整流程

`full_pipeline` 只负责集成与恢复。第一部分直接调用 `causal_graph.generation` 的六阶段函数、原有结构校验、图合并导出和 `execute_indicator`；第二部分直接调用 `causal_discovery.pipeline.run_pipeline`。没有重新实现 LLM 生成、GRU、RNN-Granger、MMI-PID 或 M5，也没有改变模型动力学。

## 直接运行

使用现有 Python 3.12 环境和 Covasim 配置中指定的兼容解释器；不需要 Docker。若新建环境，安装仓库的 `.[test,full]` 可选依赖。本次开发与验收没有安装依赖。

```powershell
python -m full_pipeline --scenario scenarios/fish.md
python -m full_pipeline --scenario scenarios/v2/covasim.md
# 需要较小的接口验收预算时；统计门槛仍沿用第二部分原配置。
python -m full_pipeline --scenario scenarios/fish.md --config full_pipeline/examples/low_cost_acceptance.yaml
python -m full_pipeline --resume full_pipeline/results/<experiment_id>
```

只有新建实验时需要想定，恢复时使用实验目录中已经保存的原文。可选 `--review-file` 指定审核文件。Python 入口为 `full_pipeline.main.run_full_pipeline(scenario, ...)`，返回 JSON 兼容的报告。CLI 错误返回非零状态；`review_required` 是可恢复的正常暂停，不代表已经计算成功。

LLM 档案和参数自动读取 `causal_graph/configs/deepseek_flash.yaml`。密钥仍由该档案的 `api_key_env` 指定环境变量提供，命令行不接收 API Key，配置、请求记录及子进程环境均不保存或传递密钥。真实验收使用用户此前提供的私人配置文件在当前进程设置这个环境变量，仍按仓库档案调用 deepseek-flash；私人文件不进入 Git。

已有密钥保存在私人 JSON 时，可在 `stage1.credential_file` 指定该文件，或在 Git 忽略的 `full_pipeline/config.local.yaml` 中仅声明这个路径。环境变量优先，JSON 的 api_key 只读入当前进程；不会导出或覆盖仓库模型档案。当前工作区已经连接用户原有私人配置，因此无需在命令行重复输入密钥。

## 想定匹配和仿真预算

仅接受与 `scenarios/manifest.yaml` 中 Fish 或 Covasim 想定字节哈希完全相同的输入。改名、移动文件不影响识别；改动原文字节将明确拒绝，不使用相似模型代替，也不让 LLM 创建仿真器。可直接运行的两份输入副本位于 `examples/scenarios/`。

默认继承 `configs/fish.yaml` 与 `configs/covasim.yaml` 的模型版本、全部参数、日志定义和各自步数，Fish 与 Covasim 不共用一个时间长度。全流程只配置记录频率、步数和独立种子预算，不添加或改变既有模型中的干预设置。Covasim 仍是未做历史校准的原生 hybrid 演示，不能据此声称复现历史疫情。

默认初始种子为 11、22、33、44，预先声明补充种子 55、66、77、88，最多 8 个运行。是否补充只依据**已记录时钟覆盖及独立分区窗口数**，发生在指标生成和统计评价之前；不依据显著性选择种子，不修改模型参数。时钟覆盖不等于指标有足够动态信息，后续仍执行原 M1 完整检查。达到预算仍不足时如实报告，不复制观测、不广播常数、不跨种子构造历史。

仿真匹配缓存核对想定哈希、模型版本和源码哈希、参数、种子、步数、采样、日志及全部已验证原文件哈希。只有原 `inspect_run` 校验过且文件未变化的结果可以复用。schema 与运行检查另有检查点，恢复时校验哈希，避免反复读取全部大型日志。首次日志检查仍使用原有公共接口；不会通过跳过第一次校验批准未检查的日志。

## 只有两个正式图

```text
full_pipeline/results/<experiment_id>/
  input/scenario.md
  stage1_graph.json
  final_causal_graph.json
  pipeline_report.json
  internal/
    simulation/
    stage1/
    stage2/
    checkpoints/
    validation/
    logs/
```

`stage1_graph.json` 仅包含所有列出运行上**实际计算成功**的节点及其诱导候选边。它保留科学定义、尺度、现象、语义依据、边 ID、实际 Parquet 路径/哈希，并附加全流程来源信息；既有 `causal_graph` Schema 和输出不作修改。正式图的原有部分通过原 EXECUTABLE_SCHEMA 检查，附加 provenance 不影响现有 M1 读取。原始 LLM 响应、全部候选和失败节点只存在 internal 中。

`final_causal_graph.json` 来自原第二部分。weight 为主要时滞，单位仿真步。发布前再校验节点、M2 时滞来源、实际校准证据、校正阈值与 PID 联合完整性，并用保存的 M1–M4 结果重放 M5，要求图与重放结果一致。不会把协同量分摊为单边权重。零条接受边是允许的结果，不触发重新调用 LLM。

两个正式图之外的检查点、报告、模型、GraphML 和原始响应均为 internal 调试/复现材料。正式结果确需更新时，前一版本先按哈希保存在 internal/publication_history，历史响应和执行尝试不删除、不覆盖。

## 阶段检查、重试和依赖

每个任务按输入内容哈希分别保存版本和不可覆盖的 attempt 目录，记录实际函数、模块、开始/结束、输入、重试号、输出哈希、原始响应、实际修复提示词、校验和异常。缓存文件改变时直接拒绝恢复，不通过偷偷再调用 LLM 掩盖改动。

| 任务 | 复用及局部修复规则 |
| --- | --- |
| phenomena | 原有数量、唯一 ID/名称、描述完整性检查；检查重复描述 |
| indicators | 原有三尺度/现象覆盖与真实字段检查；检查完整定义、单位、说明及规范化重复公式 |
| code_变量ID | 每个变量独立调用原代码生成函数；语法、签名、字段访问、明显 I/O/进程操作检查；实际科学审核另行记录 |
| edges_upward / downward / intrascale | 三类任务独立；引用、方向和结构校验；合并复用原去重和来源保留逻辑 |
| execute_变量ID_运行ID | 复用原 reviewed 本地子进程、超时、异常捕获、数值和索引校验；保留每次返回结果及日志 |
| stage2 | 仅调用原第二部分；第一部分已就绪时直接复用其图和检查点 |

默认每个生成任务最多 3 次，跨 resume 累计，不因重启清零。JSON、Schema 和代码重试开关独立。错误记录区分格式、字段、定义、重复、代码、定义不一致、执行、节点引用、方向和完整性，并标注相应阶段与变量 ID。修复提示只含必要的本地约束和错误，不含真实边、真实时滞或统计结果。

变量定义变化会改变所有依赖代码和关系任务的输入身份；单个代码修复不改变定义时，其他代码和三类关系继续复用。某一方向修复不失效其他方向。实施错误可以请求对应代码修复；超时、内存预算、数据长度或常数等问题不能据此声称数学实现错误。达到上限保存 failed 并停止，不无限请求。

重复公式检查是保守的文本规范化，不能证明不同写法在数学上不同。数学一致性及观测单位必须另行审核；未被自动检测的同义公式仍是科学审核内容。

## 代码审核与恢复

默认不自动批准任何 LLM 代码。静态检查只检查其明确覆盖的语法、字段和明显不允许操作，**不是安全沙箱，也不是数学等价证明**。需要审核时状态为 review_required，具体定义和代码在 `internal/stage1/current_candidate.json`，待审项在 `review_request.json`。

将实际审核写到 `internal/stage1/review.json` 后恢复。以下为结构示例，哈希必须取自实际待审项，不能照抄为审批：

```json
{
  "reviewer": "真实审核者或明确标注的助手身份，不得冒充人工",
  "reviewed_at": "实际审核时间",
  "notes": "实际检查过程、约束与结论",
  "reviews": {
    "实际变量ID": {
      "code_sha256": "待审代码的实际SHA-256",
      "definition_sha256": "待审定义的实际SHA-256",
      "verdict": "approved",
      "checks": {
        "syntax": true,
        "fields": true,
        "mathematical_definition": true,
        "observation_unit": true,
        "time_index": true,
        "allowed_operations": true
      },
      "reason": "逐函数检查结论和必要限制"
    }
  }
}
```

审核绑定代码和科学定义双哈希，旧定义审核不能批准新定义。verdict=rejected 时写明具体 reason；该代码不会执行，仅在允许的次数内修复对应代码，再请求新审核。通过的记录转换为原 `trusted_reviewed` 接口，同时保存实际审核原文和兼容记录。实际审核身份可以明确标注为助手审核；系统不把它伪造成人工审批。原本地子进程仍保持超时、错误与执行日志，执行环境不含 API 凭据。

主体级或层级变量在第二部分中仍遵守原 M1 规则：必须有显式 entity_mode 或 feature/features 配置，不能默认平均主体，也不能将宏观量复制成主体样本。已成功计算的变量可能因此在 M1 被排除。可在全流程配置的 `stage2.overrides.data.node_overrides` 中预先声明适合研究问题的映射；修改已冻结实验的预算、模型或统计配置应新建实验。不会为了保留节点临时改变指标意义或降低统计门槛。

## 测试与验收

```powershell
python -m pytest -q full_pipeline/tests
python -m pytest -q
```

控制测试使用明确标记的 Mock LLM 和小型实际 Fish 日志，覆盖局部失败、持久重试上限、审核暂停、定义变化、内容篡改、第二部分独立恢复、数据不足、空图和有效节点零接受边。控制夹具不冒充真实 LLM 研究结果。

真实验收过程与节点/边、调用次数、种子、耗时及未解决问题见 [验收报告](docs/ACCEPTANCE_20261107.md)，结果在 `examples/acceptance_20261107/`。独立数值抽查脚本仅用于核对验收中实际生成的六个数学定义，未被生产流程导入，不能作为预置指标库或替代 LLM 输出。

原两个研究模块保持独立；它们的统计假设、分区方法、块 Bootstrap、MMI 定义、两两组合上限和结构因果解释边界继续适用。想定与代码审核通过不代表有足够统计功效，流程 completed 也不代表所有候选关系成立。
