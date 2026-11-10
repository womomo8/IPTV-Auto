
# IPTV 自动订阅系统开发进度

文档版本：2.9
配套规范：MASTER_PLAN 3.52
最后更新：2026-11-10

本文件只记录真实开发进度、实际测试结果和待办。
不得把未执行的测试标记为通过，不得把未完成的功能标记为完成。
与 MASTER_PLAN 冲突时，以 MASTER_PLAN 为准。

---

## 一、当前状态

| 项目 | 状态 |
|---|---|
| 规范状态 | MASTER_PLAN 3.52 已冻结 |
| 流程文档 | CORE_FLOW 1.0 |
| models.py | 字段语义静态核对完成，接口尚未正式冻结 |
| config.py | 静态核对完成，实际测试推迟 |
| network.py | 静态核对完成，实际测试未执行 |
| sources.py | 静态接口核对完成，实际测试未执行 |
| collector.py | 静态接口核对完成，实际测试未执行 |
| normalizer.py | 静态接口核对完成，实际测试未执行 |
| validator.py | 静态接口核对完成，实际测试未执行 |
| filter.py | 静态接口核对完成，实际测试未执行 |
| publisher.py | 静态接口核对完成，实际测试未执行 |
| main.py | 静态调用关系核对完成，实际测试未执行 |
| tests/test_models.py | 完整文件已提交，静态核对通过，Python测试未执行 |
| GitHub Actions 工作流 | 文件静态核对完成，修正提交后的运行结果待确认 |
| models.py 接口冻结 | 待后期实际测试及最终确认 |
| Python 实际测试 | 尚未执行 |
| 正式订阅发布 | 尚未执行 |

当前开发阶段：

各业务程序和统一调度程序已完成代码编写及静态核对。models.py 的字段定义、字段类型、默认值及程序间使用情况已经完成一轮静态语义核对。

当前没有直接修改模型字段。接口冻结仍须等待后期实际测试和最终检查。

说明：

1. MASTER_PLAN 3.52 是唯一完整技术规范和验收依据。
2. CORE_FLOW 1.0 用于遵循程序职责和实际调用顺序。
3. models.py 和 config.py 的实际测试按当前安排推迟到后期统一执行。
4. 各业务程序已完成静态接口核对，但尚未执行实际测试。
5. 未完成实际测试的程序不得标记为已测试。
6. models.py 正式冻结前，其他程序必须使用现有模型定义，不得自行重复定义接口结构。
7. GitHub Actions 工作流文件静态核对通过，不代表实际运行成功。
8. 旧工作流失败记录对应旧提交；修正提交后的新运行结果尚未确认。
9. tests/test_models.py 已核对完整文件、测试类缩进及文件入口；该核对不等于执行测试。
10. network.py 已完成响应体读取上限边界修正，实际网络行为仍待测试。
11. models.py 全部字段已完成一轮静态使用情况核对，暂不删除字段，不提前冻结接口。

---

## 二、程序开发进度

| 流程顺序 | 文件 | 状态 | 接口检查 | 功能测试 | 备注 |
|---|---|---|---|---|---|
| 1 | sources.py | 待测试 | 静态核对完成 | 未执行 | 来源整理、人工来源读取、索引解析 |
| 2 | collector.py | 待测试 | 静态核对完成 | 未执行 | 实际下载，不负责解析索引 |
| 3 | normalizer.py | 待测试 | 静态核对完成 | 未执行 | M3U解析、候选规范化、去重和名额分配 |
| 4 | network.py | 待测试 | 静态核对完成 | 未执行 | 统一 IPv4 网络请求服务 |
| 5 | validator.py | 待测试 | 静态核对完成 | 未执行 | 检测编排、TS/HLS验证，调用 network.py |
| 6 | filter.py | 待测试 | 静态核对完成 | 未执行 | 验证结果筛选、地址去重、频道去重、生成 M3U |
| 7 | publisher.py | 待测试 | 静态核对完成 | 未执行 | 文件质量保护、原子替换、Git 发布 |
| 8 | main.py | 待测试 | 静态调用关系核对完成 | 未执行 | 两轮采集及完整运行流程统一调度 |
| 9 | GitHub Actions 工作流 | 进行中 | 静态核对完成 | 新提交运行待确认 | 每日自动、手动正式、手动测试 |
| 10 | 自动化测试 | 未开始 | 测试文件静态核对完成 | 未执行 | 后期统一执行测试清单 |

共享基础文件：

| 文件 | 状态 | 说明 |
|---|---|---|
| models.py | 待测试 | 程序间数据结构唯一来源，字段语义静态核对完成，接口尚未冻结 |
| config.py | 待测试 | 统一运行参数、预算、并发、网络设置和人工来源配置 |

状态取值：未开始 / 进行中 / 待测试 / 测试中 / 已测试 / 已阻塞。

---

## 三、models.py 字段语义核对记录

本轮依据 GitHub main 分支的 models.py、各业务程序及 tests/test_models.py 进行静态核对。

| 模型 | 字段使用情况 | 核对结论 |
|---|---|---|
| SourceRecord | url、kind、order 被来源整理、采集及调度程序使用；name 暂无生产和读取位置 | name 暂无实际用途，暂时保留 |
| DownloadResult | source、success、content、status_code、error、bytes_received、truncated 均有实际用途 | 字段用途明确 |
| IndexParseResult | index_source、sources 被主程序使用；invalid_count、messages 保存解析诊断信息 | 诊断字段暂时保留 |
| Candidate | url、name、source_kind、source_order、item_order、tvg_id、group_title 有实际用途；source_url 可保留来源追踪信息 | tvg_name 暂无下游使用；source_url 暂时保留 |
| NetworkResult | success、content、status_code、error、content_type、final_url 被验证程序使用；其他字段保留请求和网络诊断信息 | 不因暂时没有下游读取而删除诊断字段 |
| ValidationResult | candidate、passed、completed 被筛选及调度程序使用；stream_type、reason 提供验证结果信息 | 诊断字段暂时保留 |
| FilterResult | m3u_content、channel_count 被发布程序及主程序使用 | 字段用途明确 |
| PublishResult | success、exit_code、error 被主程序使用；target_path、git_pushed、remote_verified 表达发布状态 | 发布状态字段暂时保留 |
| StageResult | stage_name、elapsed_seconds、success、incomplete、message 被主程序汇总和记录 | 字段用途明确 |
| RunSummary | 所有字段由主程序生成并由日志汇总程序读取 | 字段用途明确 |

### 重点字段说明

1. SourceRecord.name：
   当前来源整理程序没有填入该字段，其他程序也没有读取该字段。暂时保留，待最终接口确认。

2. Candidate.tvg_name：
   normalizer.py 会解析订阅中的 tvg-name 属性并写入该字段，但 filter.py 不使用它。
   MASTER_PLAN 3.52 第十五节规定，最终输出的 tvg-name 使用清理后的展示名称。因此当前字段没有实际输出作用，暂时不修改模型和解析程序。

3. Candidate.source_url：
   当前没有下游直接读取，但能够保留候选所属订阅来源信息，有利于后续定位问题，暂时保留。

4. NetworkResult：
   requested_url、remote_ip、bytes_received、redirects 等字段部分没有被 validator.py 直接读取，但属于网络请求结果和诊断信息，不应简单视为无用字段。

5. IndexParseResult：
   invalid_count、messages 暂无主程序下游读取，但 sources.py 会记录解析错误日志，结果对象本身也保留解析诊断信息。

6. ValidationResult：
   stream_type、reason 暂无筛选程序直接读取，但用于表达检测类型和失败原因，暂时保留。

7. PublishResult：
   target_path、git_pushed、remote_verified 等字段用于表达发布结果及远端确认状态，暂时保留。

### 本轮结论

- 十种模型均为 frozen dataclass。
- 没有发现程序自行重复定义共享接口结构的情况。
- 暂未发现必须立即删除或修改的模型字段。
- 暂不修改 models.py。
- 暂不冻结接口。
- 后期实际测试和最终接口确认完成后，再统一决定是否精简字段。

---

## 四、测试记录

只有实际执行过的测试才能记录在此。

当前尚未执行任何 Python 代码测试。

| 日期 | 测试项 | 测试方式 | 结果 | 备注 |
|---|---|---|---|---|
| - | - | - | - | 尚未执行 |

### 静态核对记录

| 日期 | 核对项 | 结果 | 说明 |
|---|---|---|---|
| 2026-11-10 | models.py 与九个程序交接模型对应关系 | 初步核对完成 | 未发现交接模型缺失 |
| 2026-11-10 | tests/test_models.py 泛型元组类型判断 | 已修正代码 | 使用 get_origin 和 get_args 检查泛型元组，尚未执行测试 |
| 2026-11-10 | tests/test_models.py 完整性及缩进 | 静态核对通过 | 测试类和方法缩进正确，文件入口完整 |
| 2026-11-10 | models.py 字段类型、默认值、不可变和状态约束 | 静态核对完成 | 实际测试仍待执行 |
| 2026-11-10 | MASTER_PLAN 3.52 字段语义 | 静态核对完成 | 完成十种模型字段使用情况核对，暂不删除字段 |
| 2026-11-10 | network.py 响应体读取上限及 EOF 边界 | 静态核对通过 | 已知长度和未知长度分别判断；实际测试未执行 |
| 2026-11-10 | collector.py 下载中断部分内容保留 | 静态核对完成 | 读取异常路径可保留部分内容；外层总超时取消时仍有部分内容丢失风险 |
| 2026-11-10 | Candidate.tvg_name 输出语义 | 静态核对完成 | MASTER_PLAN 规定最终 tvg-name 使用清理后的展示名称；当前字段没有下游输出作用 |
| 2026-11-10 | SourceRecord.name 使用情况 | 静态核对完成 | 当前没有生产和读取位置，暂时保留 |
| 2026-11-10 | NetworkResult、ValidationResult、PublishResult 诊断字段 | 静态核对完成 | 部分字段没有下游直接读取，但保留其结果表达和诊断价值 |

### 工作流运行记录

| 日期 | 测试项 | 测试方式 | 结果 | 证据/日志 | 备注 |
|---|---|---|---|---|---|
| 2026-11-10 | 首次 GitHub Actions 工作流运行 | push 触发 | 失败 | run ID 42836691565；旧提交 64b417793bdf19229fc140c12709e0b0237e7479 | 旧版工作流运行记录 |
| 2026-11-10 | 修正后的工作流文件 | GitHub main 分支文件静态核对 | 通过 | 修正提交 21e570930fec0d7418f7e194c5a6b63af96e2b8a | 文件结构核对通过 |
| 2026-11-10 | 修正提交后的工作流运行 | GitHub Actions 运行记录查询 | 尚无新运行记录 | 当前查询仅发现旧运行 ID 42836691565 | 工作流未配置 push 触发，不能据此认定修正失败或成功 |

静态核对不等于 Python 实际测试，也不等于 GitHub Actions 运行成功。

---

## 五、当前待办

1. 完成 models.py 接口冻结前的最终检查。
2. 后期统一执行 models.py 的实际测试。
3. 核对 tests/test_models.py 测试覆盖范围，确保测试项目与模型约束对应。
4. 根据最终字段审查结果，决定是否精简 SourceRecord.name、Candidate.tvg_name 等暂时没有实际下游用途的字段。
5. 如修改模型字段，必须同步检查所有生产、消费程序及 tests/test_models.py。
6. 所有模型检查通过后，正式冻结 models.py 接口字段。
7. 后续程序只能导入和使用 models.py 中的类型，不得自行定义重复接口结构。
8. 如确实需要修改已冻结接口，必须记录变更原因、影响范围以及需要同步调整的程序。
9. 确认修正提交后的 GitHub Actions 运行记录，核实工作流是否成功加载并触发。
10. 如果出现新的运行失败，先读取具体失败日志，再按 MASTER_PLAN 修正。
11. 后期统一执行所有程序的实际测试。
12. 后续测试重点检查 network.py 外层总超时取消时，已读取部分内容是否能够按预期保留。

接口结构性契约以 CORE_FLOW.md 第八节为参考；
字段语义和验收要求以 MASTER_PLAN 3.52 为准；
最终 Python 类型统一定义在 models.py。

---

## 六、已知问题

| 编号 | 问题 | 影响 | 状态 | 处理 |
|---|---|---|---|---|
| 1 | models.py 尚未执行 Python 实际测试 | 接口暂不能正式冻结 | 待测试 | 后期统一执行 |
| 2 | config.py 尚未执行 Python 实际测试 | 配置模块尚未验证 | 待测试 | 后期统一执行 |
| 3 | network.py 尚未执行 Python 实际测试 | 网络模块尚未验证运行行为 | 待测试 | 后期统一执行 |
| 4 | sources.py 尚未执行 Python 实际测试 | 来源整理和索引解析运行行为尚未验证 | 待测试 | 后期统一执行 |
| 5 | collector.py 尚未执行 Python 实际测试 | 下载、并发和预算截断运行行为尚未验证 | 待测试 | 后期统一执行 |
| 6 | normalizer.py 尚未执行 Python 实际测试 | M3U解析、去重和名额分配运行行为尚未验证 | 待测试 | 后期统一执行 |
| 7 | validator.py 尚未执行 Python 实际测试 | TS/HLS验证、并发和预算截断运行行为尚未验证 | 待测试 | 后期统一执行 |
| 8 | filter.py 尚未执行 Python 实际测试 | 筛选、地址去重、频道去重和M3U生成行为尚未验证 | 待测试 | 后期统一执行 |
| 9 | publisher.py 尚未执行 Python 实际测试 | 文件检查、原子替换和Git发布运行行为尚未验证 | 待测试 | 后期统一执行 |
| 10 | main.py 尚未执行 Python 实际测试 | 两轮采集和完整调度运行行为尚未验证 | 待测试 | 后期统一执行 |
| 11 | 首次 GitHub Actions 工作流运行失败 | 旧提交未能正常完成工作流运行 | 已修正文件，待确认新运行 | 已替换 iptv.yml；核对修正提交及文件内容 |
| 12 | 修正提交后的 GitHub Actions 运行记录尚未出现 | 暂不能确认工作流实际运行状态 | 待确认 | 检查 GitHub Actions 新运行记录及日志 |
| 13 | models.py 接口尚未正式冻结 | 后续程序接口暂不能视为最终冻结版本 | 待完成 | 完成最终字段检查和模型测试后冻结 |
| 14 | network.py 外层总超时取消时，部分已读取字节可能无法保留 | 可能影响下载中断时的部分内容记录 | 待后续测试和评估 | 当前读取异常路径可保留部分内容；外层总超时取消路径尚未解决 |

---

## 七、变更记录

| 日期 | 变更内容 | 影响文件 | 测试结果 |
|---|---|---|---|
| 初始化 | 创建进度文件，记录规范冻结和代码未开始状态 | PROGRESS.md | 不适用 |
| 2026-11-10 | 明确 models.py 为跨程序数据结构唯一来源 | PROGRESS.md | 文档更新 |
| 2026-11-10 | 编写第一版共享数据模型 | models.py | 尚未执行代码测试 |
| 2026-11-10 | 增加 candidates_incomplete 字段 | models.py | 已核对文件；尚未执行代码测试 |
| 2026-11-10 | 完成九类程序交接的静态接口核对 | PROGRESS.md | 静态核对；Python测试未执行 |
| 2026-11-10 | 修正 CORE_FLOW 中与 MASTER_PLAN 冲突的预算截断表述 | CORE_FLOW.md | 已核对文件；未涉及代码测试 |
| 2026-11-10 | 为 ValidationResult 增加未完成结果不得通过的约束 | models.py | 已核对文件；尚未执行代码测试 |
| 2026-11-10 | 完善 DownloadResult 和 PublishResult 状态约束及测试代码 | models.py、tests/test_models.py、PROGRESS.md | 测试代码已编写；Python实际测试尚未执行 |
| 2026-11-10 | 编写统一配置模块 | config.py | 已提交并核对；实际测试未执行 |
| 2026-11-10 | 新增统一 IPv4 网络请求模块 | network.py | 静态接口核对完成；实际测试未执行 |
| 2026-11-10 | 新增来源管理模块 | sources.py | 静态接口核对完成；实际测试未执行 |
| 2026-11-10 | 新增采集下载模块 | collector.py | 静态接口核对完成；实际测试未执行 |
| 2026-11-10 | 新增候选整理模块 | normalizer.py | 静态接口核对完成；实际测试未执行 |
| 2026-11-10 | 新增候选验证模块 | validator.py | 静态接口核对完成；实际测试未执行 |
| 2026-11-10 | 新增筛选模块 | filter.py | 静态接口核对完成；实际测试未执行 |
| 2026-11-10 | 完成发布模块 | publisher.py | 静态接口核对完成；实际测试未执行 |
| 2026-11-10 | 完成统一调度程序 | main.py | 静态调用关系核对完成；实际测试未执行 |
| 2026-11-10 | 新增 GitHub Actions 工作流 | .github/workflows/iptv.yml | 首次运行失败 |
| 2026-11-10 | 修正工作流文件结构和 YAML 层级 | .github/workflows/iptv.yml | 静态核对完成；新运行结果待确认 |
| 2026-11-10 | 修正模型测试中的泛型元组类型判断 | tests/test_models.py | 已核对提交文件；Python实际测试尚未执行 |
| 2026-11-10 | 修复模型测试文件缩进和入口判断 | tests/test_models.py | GitHub main 分支静态核对通过；Python测试尚未执行 |
| 2026-11-10 | 修正 network.py 未知 Content-Length 响应达到读取上限时的 EOF 判断 | network.py | 已提交并核对 main 分支；实际测试未执行 |
| 2026-11-10 | 完成 models.py 十种模型字段语义及下游使用情况核对 | PROGRESS.md | 静态核对完成；未修改模型字段，未冻结接口 |
| 2026-11-10 | 更新模型字段语义审查结果和后续待办 | PROGRESS.md | 文档更新；未涉及 Python 测试 |

---

## 八、更新规则

1. 每完成一个程序，更新对应状态。
2. 每执行一次测试，记录日期、测试项、结果和证据。
3. 测试失败必须记录失败原因，不得标记为通过。
4. 未实际执行的功能不得标记为已完成。
5. 发现与 MASTER_PLAN 冲突时，先以 MASTER_PLAN 为准修正，再更新本文件。
6. CORE_FLOW 负责指导程序调用顺序和职责边界。
7. 本文件只记录真实开发进度、接口落实情况和待办，不重复定义具体 Python 类、字段或技术实现。
