IPTV 自动订阅系统开发进度

文档版本：3.18
配套规范：MASTER_PLAN 3.53
最后更新：2026-11-11

本文件只记录真实开发进度、实际测试结果、接口状态和待办。

- "MASTER_PLAN.md" 是唯一核心开发依据和技术验收标准。
- "CORE_FLOW.md" 用于指导程序职责和调用顺序。
- "PROGRESS.md" 只记录实际进度，不另行定义技术规则。
- 未实际执行或没有可靠证据的测试不得标记为通过。

---

一、当前项目状态

项目| 当前状态
MASTER_PLAN| 3.53 已冻结，是唯一技术规范和验收依据
CORE_FLOW| 已建立，与当前程序调用流程一致
五阶段业务流程| 已实现，持续进行必要边界审查
models.py| 接口字段正式冻结
核心业务程序| 已实现，继续按实际问题审查
GitHub Actions| test、formal 均有成功记录
单元测试| 第48次运行238项全部通过
最近测试模式| 第48次运行成功，业务运行完整
最近正式运行| 第36次运行，工作流成功但业务不完整
当前正式订阅| 第36次正式运行发布10个频道

项目已完成从来源采集、整理、IPv4验证、频道筛选、M3U生成到GitHub发布的端到端自动化流程。

第36次正式运行：共得到146个候选，10个通过，2个因单候选验证预算耗尽而未完成，最终发布10个频道。GitHub Actions工作流成功，但业务日志中的“运行是否不完整”为True，不能将工作流成功等同于业务完整。

第48次测试运行：不是正式发布。238项单元测试全部通过；业务测试中146个候选全部完成验证，10个通过并生成10个测试频道，业务运行完整，退出码为0。

当前最近一次正式运行仍为第36次。第48次为test模式，formal任务按设计跳过，不覆盖正式订阅文件，也不执行Git发布。

二、程序进度

程序| 当前进度与已核对职责
sources.py| 已实现来源整理、人工来源读取、索引解析
collector.py| 已实现两轮来源下载、并发和预算控制；外层截止时间取消时的部分字节处理已审查
normalizer.py| 已实现M3U/TXT解析、候选规范化、去重、名额分配和整理预算控制
network.py| 已实现IPv4网络请求、安全检查、响应读取限制、HTTP错误诊断及本轮必要安全边界回归测试
validator.py| 已实现检测编排、TS/HLS验证、检测阶段预算耗尽、外部取消及HLS HTTP状态诊断测试
filter.py| 已实现频道筛选、去重和M3U生成；展示名称处理及相关测试已核对
publisher.py| 已实现文件质量检查、原子替换、Git发布和共享发布预算控制
main.py| 已实现统一调度完整运行流程；两轮采集、阶段异常停止、发布退出码及筛选交接专项测试已通过
config.py| 已实现主要运行配置；预算参数用途和未直接引用项已完成本轮审查
GitHub Actions| 已验证手动test、手动formal均有成功记录；每日定时配置与规范一致

本节记录的是已实现职责和已有验证，不代表所有上游直播源均可播放。来源质量问题按第四、八、九节记录，不因此重复修改已经通过的程序逻辑。

三、models.py 接口冻结记录

已完成以下工作：

1. 检查models.py与全部生产程序的数据交接关系。
2. 审查模型字段名称、类型、默认值和使用情况。
3. 检查跨程序数据结构是否存在重复定义。
4. tests/test_models.py实际执行成功。
5. 26项模型单元测试全部通过。

当前正式冻结models.py接口字段。

冻结后，任何接口字段变更都必须先审查全部生产程序和测试文件，再执行模型单元测试。

不得为了增加测试而随意修改models.py。

---

四、GitHub Actions实际运行记录

4.1 已确认的正式运行

第4次正式运行：

- run ID：42847011439
- 结果：success
- 整理候选：87
- 验证通过：37
- 未完成：0
- 正式发布：37频道
- 退出码：0

正式文件：

"output/iptv.m3u"

发布提交SHA：

"01ffbdabbd251fdb8b7949317945ec54954dfa21"

已核对远端main分支SHA与正式发布提交SHA一致。

订阅直链：

https://raw.githubusercontent.com/womomo8/IPTV-Auto/main/output/iptv.m3u

4.2 第19次测试运行

- run ID：42865141744
- job ID：130001368407
- 结果：success
- 单元测试：162项全部通过
- 测试模式退出码：0
- 正式发布：跳过

运行记录：

https://github.com/womomo8/IPTV-Auto/actions/runs/42865141744

4.3 第20次测试运行

- run ID：42866828584
- 单元测试：165项全部通过
- 测试模式退出码：0
- 正式发布：跳过

新增main.py独立测试，覆盖：

1. 自动来源下载配额根据实际启动的索引下载数量计算。
2. 人工直播地址不占用来源下载配额。
3. 非法运行模式返回输入错误。

运行记录：

https://github.com/womomo8/IPTV-Auto/actions/runs/42866828584

4.4 第21次测试运行

- run ID：42867789712
- job ID：130010680675
- 分支：main
- 结果：success
- 测试模式退出码：0
- 正式发布：跳过

单元测试：

项目| 结果
执行命令| "python -m unittest discover -s tests -v"
测试数量| 191
通过数量| 191
失败数量| 0
总耗时| 2.192秒

新增network.py独立测试，覆盖：

- URL合法性检查。
- 公网IPv4解析。
- 混合公网与私有DNS结果拒绝。
- IPv4固定解析器。
- HTTP响应头限制。
- 压缩响应拒绝。
- 实际远端IP检查。
- 响应读取大小限制。
- 部分读取数据保留。
- 取消传播。
- 非法超时和读取限制。
- 非法URL不重试。

IPTV测试模式：

项目| 结果
尝试下载来源| 3
整理后候选| 87
验证结果数| 87
完成验证候选| 82
验证通过候选| 29
验证失败候选| 53
未完成候选| 5
发布频道| 29
运行是否不完整| True
退出码| 0

本次测试通过191项单元测试，并完成端到端测试模式运行。

5条候选未完成验证，因此本次运行被标记为不完整。29条已通过筛选的频道进入测试输出。

测试模式没有执行正式发布，没有覆盖正式订阅文件，也没有推送Git。

本次测试曾出现AsyncMock未等待的RuntimeWarning，后续在第22次运行中修正并验证。

运行记录：

https://github.com/womomo8/IPTV-Auto/actions/runs/42867789712

4.5 第22次测试运行

- run ID：42868813557
- job ID：130014243829
- 分支：main
- 结果：success
- 测试模式退出码：0
- 正式发布：跳过

单元测试：

项目| 结果
执行命令| "python -m unittest discover -s tests -v"
测试数量| 191
通过数量| 191
失败数量| 0
总耗时| 2.168秒

网络测试警告修复结果：

- 修正DNS测试中的异步模拟方式。
- 保留DNS异步调用的等待验证。
- 本次日志未发现AsyncMock未等待的RuntimeWarning。
- 未修改network.py网络功能代码。

IPTV测试模式：

项目| 结果
尝试下载来源| 3
整理后候选| 87
已验证候选| 87
验证通过候选| 38
未完成候选| 0
发布频道| 38
运行是否不完整| False
退出码| 0

本次运行确认：

1. 191项单元测试全部通过。
2. AsyncMock未等待警告已经消失。
3. IPTV测试模式完整结束。
4. 38条频道通过筛选并写入测试输出。
5. 正式发布任务跳过，没有覆盖正式订阅文件，也没有推送Git。

运行记录：

https://github.com/womomo8/IPTV-Auto/actions/runs/42868813557

4.6 第35次测试运行

- run ID：42938579173
- job ID：130254635161
- 分支：main
- 结果：success
- 测试模式退出码：0
- 正式发布：跳过

单元测试：

项目| 结果
执行命令| "python -m unittest discover -s tests -v"
测试数量| 215
通过数量| 215
失败数量| 0
总耗时| 2.227秒

本次新增网络HTTP错误诊断测试，验证HTTP响应状态和错误消息可以被记录。

IPTV测试模式：

项目| 结果
整理后候选| 146
已验证候选| 146
验证通过候选| 10
未完成候选| 0
最终有效频道| 10
运行是否不完整| False
退出码| 0

来源检测记录：

来源| 候选数量| 通过| 失败
人工TXT来源| 100| 0| 100
自动订阅来源A| 1| 0| 1
自动订阅来源B| 45| 10| 35

人工TXT来源100条候选的失败原因：

- 98条：HTTP响应错误，状态诊断显示status=400，响应内容出现不符合HTTP状态行格式的HTML。
- 2条：MPEG-TS同步检查失败。

自动订阅来源B的45条候选中，10条通过验证。

本次运行确认：

1. 215项单元测试全部通过。
2. HTTP错误状态和消息诊断已生效。
3. IPTV测试模式完整结束。
4. 最终筛选出10条有效频道。
5. 正式发布任务跳过，没有覆盖正式订阅文件，也没有推送Git。

注意：

- 人工TXT来源的100条候选全部未通过。
- HTTP错误诊断只是帮助定位问题，并没有修复这些直播地址。

运行记录：

https://github.com/womomo8/IPTV-Auto/actions/runs/42938579173

4.7 第36次正式运行

- run ID：42941373602
- job ID：130263733278
- 分支：main
- workflow：IPTV Auto Update
- 触发方式：workflow_dispatch
- 工作流结论：success
- 业务运行模式：formal
- 正式发布：执行，发布10个频道

单元测试：

项目| 结果
执行命令| "python -m unittest discover -s tests -v"
测试数量| 215
通过数量| 215
失败数量| 0
总耗时| 2.226秒

正式业务运行：

项目| 结果
整理后候选| 146
验证结果数| 146
完成验证候选| 144
验证通过候选| 10
验证失败候选| 134
未完成候选| 2
正式发布频道| 10
运行是否不完整| True
业务退出码| 0

来源检测记录：

来源| 候选数量| 通过| 失败| 未完成
人工TXT来源| 100| 0| 98| 2
自动订阅来源A| 1| 0| 1| 0
自动订阅来源B| 45| 10| 35| 0
合计| 146| 10| 134| 2

本次运行日志记录的主要失败情况：

- 人工TXT来源：96条超时、2条MPEG-TS同步检查失败；另有2条因单候选验证预算耗尽而未完成。
- 自动订阅来源A：1条HLS playlist request failed。
- 自动订阅来源B：存在HLS分片MPEG-TS同步检查失败、超时、网络请求错误及HLS请求失败等情况。

自动订阅来源A的实际地址：

"https://raw.githubusercontent.com/zwc456baby/iptv_alive/master/live.m3u"

该文件中第一条频道记录格式有效，解析器成功解析并产生1条候选。文件尾部另有一条不完整的EXTINF记录，缺少频道名。Actions日志显示第6行存在缺少EXTINF信息的异常记录，解析器发出警告并跳过，没有影响前面有效记录的解析。现有日志没有记录第6行的具体文本内容，因此不对其内容作进一步描述。

因此，本次自动订阅来源A的问题不能归类为“M3U解析器整体故障”：

1. M3U解析功能已经实现。
2. 第一条有效频道记录解析成功。
3. 上游文件尾部存在格式异常记录。
4. 唯一有效候选在后续HLS播放验证阶段失败，日志原因为"HLS playlist request failed"。
5. 现有日志不足以进一步确认该请求失败的具体根因，不作推测。

本次运行确认：

1. 215项单元测试全部通过。
2. 正式运行整理出146条候选。
3. 10条候选通过验证并进入正式订阅。
4. 2条候选未完成验证，业务日志将本次运行标记为不完整。
5. GitHub Actions工作流结论为success，但这不代表业务运行完整。
6. 正式输出文件为"output/iptv.m3u"，包含10个频道。

运行记录：

https://github.com/womomo8/IPTV-Auto/actions/runs/42941373602

4.8 第37次测试运行

- run ID：42944181785
- 分支：main
- 提交SHA："be799f6acfab0e3331ed21d4867f4185d2a3dad6"
- 提交信息：Update test_validator.py
- 结果：success
- 测试模式：成功
- 正式发布：跳过

本次新增validator.py检测阶段预算耗尽专项测试：

"test_detection_budget_preserves_completed_results_and_marks_pending"

测试确认：

1. 已完成的验证结果得到保留。
2. 尚未完成的候选被标记为未完成。
3. 阶段预算耗尽后不再启动排队中的候选。
4. 已启动的验证任务被取消并完成清理。

本次运行通过全量单元测试。

注意：第37次提交中尚未包含外部取消传播专项测试。该测试在后续提交中加入，不能将其归入第37次运行的测试证据。

运行记录：

https://github.com/womomo8/IPTV-Auto/actions/runs/42944181785

4.9 第38次测试运行

- run ID：42945717334
- 分支：main
- 提交SHA："7fe8b81e380d86af64ac5224db98542d729f118b"
- 提交信息：Update test_main.py
- 结果：success
- test job：success
- formal job：skipped

单元测试：

项目| 结果
执行命令| "python -m unittest discover -s tests -v"
当前测试方法总数| 219
测试结果| 全部通过
失败数量| 0

219项测试方法数量由第38次提交对应的12个测试文件逐个核对统计；Actions运行记录确认test job成功。

本次运行包含此前加入的validator外部取消测试，以及本次新增的main.py专项测试。

validator外部取消专项测试：

"test_external_cancellation_propagates_and_cancels_active_work"

测试确认：

1. 外部取消信号正确传播。
2. 正在执行的验证任务得到取消。
3. 排队中的候选不会在取消后启动。
4. 活动任务清理完成。

main.py新增专项测试：

"test_stage_failure_stops_following_stages"

确认阶段发生不可恢复异常时，停止后续阶段并返回退出码2。

"test_publish_failure_exit_codes_are_propagated"

确认正式发布失败时，正确传递退出码3和退出码4。

原有main.py测试继续保留，包括：

- 自动来源下载名额按实际启动的索引下载数量计算。
- 人工单条直播地址不占用下载名额。
- 非法运行模式返回输入错误。
- 来源验证结果统计。
- 失败原因日志数量限制。

两轮采集调度测试没有重复增加。

本次运行确认：

1. 219项单元测试全部通过。
2. test job成功。
3. IPTV测试模式步骤成功。
4. formal job按test模式工作流设计跳过。
5. 本次运行没有执行正式发布，不能作为新的正式订阅发布记录。

运行记录：

https://github.com/womomo8/IPTV-Auto/actions/runs/42945717334

4.10 第39次测试运行

- run ID：42949633025
- job ID：130290647053
- 分支：main
- 提交SHA："28bdab7b4d7f4fb8addecd0c88be47257fbda94f"
- 提交信息：Update test_main.py
- 结果：success
- test job：success
- formal job：skipped

本次测试对应的代码交接修复分两次提交完成：

1. 前一提交 "b85e8b2109b2b9c8c15050610d5c363433bcd76e"（Update main.py）：main.py在调用filter.py前，只保留验证已完成且通过的结果。
2. 本次提交 "28bdab7b4d7f4fb8addecd0c88be47257fbda94f"（Update test_main.py）：新增主流程集成测试，验证失败和未完成的结果不会传入filter.py。

新增专项测试：

"test_only_completed_passed_results_are_sent_to_filter"

测试确认：

- 已完成且通过的验证结果会传入filter.py。
- 已完成但失败的验证结果不会传入filter.py。
- 未完成的验证结果不会传入filter.py。
- 主流程调用filter.py时，实际参数只包含通过验证的结果。

单元测试：

项目| 结果
执行命令| "python -m unittest discover -s tests -v"
测试数量| 220
通过数量| 220
失败数量| 0
总耗时| 2.350秒

Actions日志确认新增专项测试实际执行，220项测试全部通过。

IPTV测试模式：

- test job中的IPTV测试模式步骤成功。
- formal job按test模式工作流设计跳过。
- 本次没有执行正式发布，不改变第36次正式发布记录。

本次运行确认：

1. main.py到filter.py的验证结果交接已修正。
2. 新增主流程集成测试实际通过。
3. 220项单元测试全部通过。
4. 测试模式成功。
5. 没有执行正式发布。

运行记录：

https://github.com/womomo8/IPTV-Auto/actions/runs/42949633025

4.11 第40次测试运行

- run ID：42951880761
- job ID：130297841779
- 分支：main
- 提交SHA："7f798f26c9920afee64146b2014fddcebf4c8c1b"
- 提交信息：Update test_network.py
- 结果：success
- test job：success
- formal job：skipped

本次新增network.py网络请求与重定向安全集成回归测试：

"test_redirect_rechecks_dns_and_preserves_network_security"

测试覆盖：

1. 第一个主机发生重定向后，第二个主机重新执行DNS解析。
2. 环境代理不参与请求（trust_env=False）。
3. 连接器固定使用IPv4，并关闭DNS缓存。
4. 自动重定向关闭，由程序逐跳处理。
5. HTTPS请求明确启用TLS证书验证。
6. 检查每一跳连接的实际远端IP。
7. 请求连接器得到关闭清理。

单元测试：

项目| 结果
执行命令| "python -m unittest discover -s tests -v"
测试数量| 221
通过数量| 221
失败数量| 0

Actions日志确认新增专项测试实际执行并显示"ok"，完整单元测试221项全部通过。

IPTV测试模式业务结果：

项目| 结果
尝试下载来源| 4
整理后候选| 146
验证结果数| 146
完成验证候选| 139
验证通过候选| 9
验证失败候选| 130
未完成候选| 7
发布频道| 9
运行是否不完整| True
退出码| 0

业务日志显示：

- 人工TXT来源100条候选：通过0条、失败93条、未完成7条。
- 自动订阅来源A：1条候选，验证失败，原因记录为"HLS playlist request failed"。
- 自动订阅来源B：45条候选，通过9条、失败36条。
- 检测阶段有7条候选因单候选验证预算耗尽而未完成。

本次运行确认：

1. 新增网络重定向安全集成测试实际通过。
2. 221项单元测试全部通过。
3. IPTV测试模式步骤成功，业务退出码为0。
4. 由于7条候选未完成验证，本次业务运行标记为不完整。
5. formal job按test模式工作流设计跳过。
6. 本次没有执行正式发布，不改变第36次正式发布记录。

本次测试只证明所覆盖的网络请求与重定向安全行为通过回归测试，不代表已完成network.py所有剩余安全边界审查。

运行记录：

https://github.com/womomo8/IPTV-Auto/actions/runs/42951880761

4.12 采集截止时间取消时部分字节保留问题审查

审查对象：collector.py、network.py、models.py、normalizer.py、sources.py及相关测试。

核对结果：

1. network.py普通响应读取中断时，会将已读取字节放入NetworkResult，并记录读取中断原因。
2. network.py收到外层CancelledError时会继续传播取消信号；读取函数中的临时字节不会进入NetworkResult。
3. collector.py在共享采集截止时间到达后取消未完成任务，并为已启动且被取消的任务生成success=False、truncated=True、content为空的DownloadResult。
4. normalizer.py会跳过success=False或truncated=True的订阅下载，不解析其中的部分内容。
5. sources.py会跳过success=False或truncated=True的索引下载，不解析其中的部分内容。
6. MASTER_PLAN 3.53第5.4节要求预算耗尽时停止新下载、取消未完成下载并记录正常预算截断，没有要求外层取消必须保留部分字节。
7. DownloadResult接口允许表示部分内容，但没有规定外层截止时间取消时必须保留已读取字节。

审查结论：

- 外层截止时间取消后不保留部分字节，是当前明确的截断处理方式。
- 下游程序会跳过失败或截断结果，部分字节不会进入候选池或索引来源清单。
- 未发现与MASTER_PLAN 3.53冲突或影响现行业务流程的功能缺陷。
- 不修改collector.py、network.py、models.py及下游程序。
- 本次为代码和接口静态审查，没有代码变化，因此不重复执行221项单元测试。

---

4.13 第46次测试运行

- run ID：42959836161
- job ID：130323494124
- 分支：main
- 提交SHA："44d08b71b5e10db0aa7b8902f896863d26a7d257"
- 提交信息：Update test_validator.py
- 结果：success
- test job：success
- formal job：skipped

本次运行验证validator.py的HLS HTTP错误状态诊断修复，并执行完整单元测试。

单元测试：

项目| 结果
执行命令| "python -m unittest discover -s tests -v"
测试数量| 231
通过数量| 231
失败数量| 0
执行耗时| 2.359秒

IPTV测试模式业务结果：

项目| 结果
整理后候选| 146
已验证候选| 146
验证通过候选| 10
验证失败候选| 136
未完成候选| 0
最终有效频道| 10
运行是否不完整| False
退出码| 0

本次运行确认：

1. 完整单元测试231项全部通过。
2. validator.py新增的HLS HTTP状态码错误诊断回归测试包含在本次测试中，完整测试套件通过。
3. 146条候选全部完成验证，其中10条通过、136条失败、0条未完成。
4. IPTV测试模式业务运行标记为完整，退出码为0。
5. formal job按test模式工作流设计跳过，本次没有执行正式发布。
6. 本次结果不改变第36次正式发布记录，也不代表136条验证失败的频道已恢复可播放。

运行记录：

https://github.com/womomo8/IPTV-Auto/actions/runs/42959836161

4.14 第48次测试运行

- Run ID：42964207840
- Job ID：130337535989
- 分支：main
- Commit SHA：04fe0663fab098e62075f8869a4e01d4aebb6508
- Commit message：Update test_network.py
- 触发方式：workflow_dispatch
- 运行模式：test
- 工作流结果：success
- test任务：success
- formal任务：skipped（按test模式设计跳过）
- Actions记录：https://github.com/womomo8/IPTV-Auto/actions/runs/42964207840

单元测试命令：python -m unittest discover -s tests -v

单元测试结果：

- 测试总数：238
- 通过：238
- 失败：0
- 用时：2.519秒

本次新增并实际执行的网络安全边界回归测试包括：

- HTTP响应头单行长度限制
- HTTP响应头总大小限制
- 重试过程沿用同一个绝对截止时间
- TLS证书校验错误不进行重试
- 拒绝不属于已验证DNS结果的远端IP
- 达到重定向上限后停止

IPTV业务测试结果：

- 尝试下载来源数：4
- 整理后候选数：146
- 完成验证候选数：146
- 验证通过：10
- 验证失败：136
- 未完成：0
- 最终测试频道数：10
- 运行是否不完整：False
- 退出码：0

本次确认：

1. 238项单元测试全部通过，新增网络安全测试实际执行。
2. 146个候选均完成验证，10个通过并进入测试输出。
3. 业务运行完整，退出码为0。
4. 本次为test模式，formal任务跳过；没有正式发布、没有覆盖正式订阅文件、没有执行Git推送。
5. 第48次测试运行不改变第36次仍为最近正式运行的记录。

五、GitHub Actions工作流规则

当前".github/workflows/iptv.yml"已加入单元测试：

"python -m unittest discover -s tests -v"

执行顺序：

- 手动test：模型及业务单元测试 → IPTV测试模式。
- 手动formal：模型及业务单元测试 → IPTV正式模式。
- 每日自动运行：模型及业务单元测试 → IPTV正式模式。

单元测试失败时，后续业务步骤不会继续执行。

当前工作流cron：

"17 22 * * *"

对应北京时间每天06:17自动运行。

定时任务时间已经核对确认，不存在配置偏差：

- "MASTER_PLAN.md" 3.53 第十七章明确规定：北京时间每天06:17。
- GitHub Actions cron "17 22 * * *" 对应北京时间每天06:17。
- 两者完全一致。
- 每日自动运行时间为已确认配置，不是待修正事项。
- 不得将06:00作为本项目当前定时运行目标。

工作流当前设置"timeout-minutes: 22"，该值直接写在YAML中，没有读取config.py中的"GITHUB_ACTIONS_TIMEOUT_MINUTES"。

---

六、配置项和预算审查记录

6.1 实际配置核对

已检查以下生产文件中的实际有效配置：collector.py、filter.py、main.py、network.py、normalizer.py、publisher.py、sources.py、validator.py。

核对范围包括来源下载数量和两轮预算、并发/队列/单来源超时、来源大小限制、HTTP/HTTPS及端口限制、DNS/TCP/网络读取超时、重试与重定向、HTTP响应头限制、候选预算/并发/队列、TS/HLS限制、整理/筛选/发布预算、正式与测试输出路径、人工及自动来源配置。

FILTER_BUDGET_SECONDS 已在生产流程中使用，不属于未引用配置。

6.2 固定安全策略与预算参数

参数| 当前情况| 审查结论
IP_VERSION| config.py中没有此配置；network.py固定使用IPv4| 固定安全策略，不提供运行时切换
VERIFY_TLS| config.py中没有此配置；HTTPS始终验证证书| 固定安全策略，不提供关闭校验的开关
GITHUB_ACTIONS_TIMEOUT_MINUTES| config.py中没有此配置；Actions YAML直接设置22分钟| 工作流层超时设置
CLEANUP_BUDGET_SECONDS| 清理预算60秒，记录实际清理耗时，没有独立强制取消| 保留并如实记录限制
STAGE_BUDGET_TOTAL_SECONDS| 阶段预算合计18分钟| 已由预算测试核对
STARTUP_RESERVE_SECONDS| 启动预留60秒| 已由预算测试核对
NORMAL_RUN_TARGET_SECONDS| 正常运行目标19分钟| 已由预算测试核对

上述参数不能仅因生产代码未直接读取就删除。IPv4和TLS属于固定安全策略。

6.3 MASTER_PLAN 3.53第18节阶段预算核对

阶段| 预算
collection| 180秒
organize| 30秒
validation| 660秒
filter| 30秒
publish| 120秒
cleanup| 60秒
阶段预算合计| 1080秒
启动预留| 60秒
正常运行目标| 1140秒（19分钟）
Actions硬超时| 22分钟

核对结论：

- collection使用共享截止时间和预算。
- organize通过协作式预算检查控制。
- validation同时具有阶段预算和单候选预算。
- filter具有预算控制。
- publish的文件操作、Git推送和远端验证共享2分钟截止时间。
- cleanup记录实际耗时，没有独立硬截止取消。
- 预算测试覆盖配置数值关系和已实现的控制逻辑。

本轮决定：

1. 不增加全局倒计时调度器。
2. 不为让所有常量都被生产代码直接读取而增加复杂调度逻辑。
3. 保留阶段预算、发布共享截止时间、清理预算参数及耗时记录。
4. 不删除用于治理和验收的预算参数。
5. 当前未发现需要立即修改的生产预算问题。

预算测试能够证明配置关系及已实现控制逻辑，不代表每个阶段都具备独立强制取消能力。

七、业务独立测试范围审查

7.1 测试文件

- tests/test_models.py
- tests/test_sources.py
- tests/test_collector.py
- tests/test_normalizer.py
- tests/test_normalizer_budget.py
- tests/test_filter.py
- tests/test_publisher.py
- tests/test_publisher_budget.py
- tests/test_validator.py
- tests/test_main.py
- tests/test_main_budget.py
- tests/test_network.py

第48次运行共238项单元测试，全部通过。

7.2 覆盖范围

测试覆盖URL规范化和来源去重/优先级、索引解析和无效来源、下载失败/大小限制/取消/部分读取、M3U/TXT解析和候选规范化/名额分配、URL去重和排序、频道ID/名称/分组去重、TS/HLS规则、IPv4边界、混合DNS结果拒绝、网络响应及响应头限制、远端IP验证和取消、HTTP错误与诊断、重试截止时间一致性、TLS错误不重试、重定向上限、M3U格式和输出质量、零频道及旧文件保护、测试隔离、Git发布和远端SHA、两轮来源调度和配额、整理预算、发布共享预算、异步DNS等待、验证阶段预算、外部取消、main阶段停止和退出码、验证结果交接、阶段预算配置及清理耗时。

7.3 已有专项验证记录

- validator检测阶段预算耗尽：第37次运行。
- validator外部取消传播：第38次运行。
- main两轮采集调度：已有测试通过记录。
- main阶段异常停止及退出码2：第38次运行。
- main发布退出码3/4：第38次运行。
- main仅将已完成且通过的结果交给filter：第39次运行。
- network每次重定向重新解析DNS并执行安全约束：第40次运行。
- validator HLS HTTP状态诊断：第46次运行。
- network网络安全边界回归测试：第48次运行。

以上已有实际运行记录的专项测试，不因整理进度文档而重复运行；只有相关代码发生变化时才按需复测。

7.4 本轮审查结论

- network.py必要安全边界审查完成，本轮无需修改生产代码。
- filter.py频道展示名称、去重和M3U输出已核对，本轮无需修改生产代码。
- 预算参数与MASTER_PLAN的对应关系已核对。
- 未发现需要增加重复测试文件或无必要测试模块的理由。

测试通过只证明相应测试覆盖范围内的行为，不代表上游所有直播源可用，也不代表已在中国大陆真实网络环境逐路验证。

八、当前待办

1. 分析人工TXT来源的失败原因，依据最新日志区分HTTP响应异常、超时、TS验证失败及预算耗尽；不得把网络响应异常误判为解析器问题。
2. 分析自动来源A的上游M3U尾部异常记录，以及有效候选的HLS验证失败；解析器已通过现有测试，不得无证据重复修改。
3. 分析自动来源B的验证失败候选，区分上游失效URL、HTTP错误和流内容验证失败。
4. 不改变现有架构，继续核对采集和验证结果是否符合MASTER_PLAN。
5. 完成仍有必要的整体接口、配置、调用流程和工作流一致性复核。

执行要求：

- 修改前必须查看实际代码、运行日志和Actions证据。
- 已通过且相关代码未变化的测试不重复运行。
- 不因上游直播源失效而随意修改解析器。
- 不增加评分、数据库或无必要的持久化文件。
- 不增加没有整体必要的程序或模块。
- 每次代码修改前说明证据、原因和影响，并提供完整替换文件。
- 正式运行与测试运行必须分开记录。
- 本轮已完成的配置/预算、网络安全边界、filter审查不再列为待办。

九、已知问题

1. 人工TXT来源历史表现不稳定，不同运行出现HTTP超时、HTTP 400、响应状态行格式异常或返回HTML，以及TS同步验证失败；目前不能认定来源已修复。
2. 自动来源A的上游M3U尾部存在不完整记录，现有解析器会跳过异常记录。有效候选后续HLS验证仍有请求失败及HTTP 403，根因尚未确认。
3. 自动来源B仍有较多候选验证失败，需要结合最新日志逐项区分上游失效、HTTP错误和流内容问题。
4. 第36次正式运行有2个候选因单候选验证预算耗尽而未完成；虽然发布10个频道，业务状态仍为不完整。
5. collector.py在外层截止时间取消时不会保留尚未完整读取的部分数据。已按MASTER_PLAN 3.53第5.4节审查：失败或截断结果由下游跳过。
6. 部分预算参数不直接控制生产代码的独立强制取消；其用途和限制已审查并记录，本轮不改。
7. cleanup阶段没有独立强制截止时间；当前记录实际耗时，不引入全局调度器。

定时配置：

- 每日北京时间06:17自动运行。
- GitHub Actions cron：17 22 * * *（UTC）。
- 与MASTER_PLAN第17节一致，配置正确，不属于当前问题或待办。

运行状态必须区分：

- 第36次：工作流成功，但业务日志标记运行不完整True；仍是最近一次正式运行。
- 第48次：工作流成功，test模式业务完整，运行不完整False；formal任务跳过，不是正式发布。

不得将工作流成功、单元测试通过、测试模式业务完整、正式发布成功和中国大陆真实播放验证混为一谈。

十、更新规则

1. 每完成一项实际工作，记录真实结果。
2. 每次测试记录运行方式、结果和证据。
3. 静态检查、单元测试、端到端运行和实际播放测试分别记录。
4. 失败记录原因，不得标记为成功。
5. 与MASTER_PLAN冲突时，以MASTER_PLAN为准。
6. models.py接口冻结后，所有接口变更必须经过审查和测试。
7. 不增加没有实际必要的程序、模块和持久化文件。
8. 不重复执行已经有充分证据通过的测试，除非相关代码发生变化。
9. 进度记录必须与GitHub实际运行记录一致。
10. 工作流成功不等于业务运行完整；两种状态必须分别记录。
11. 不把上游来源内容异常或播放验证失败误记为M3U/TXT解析器故障。
12. 每日自动运行时间以MASTER_PLAN.md为准；当前正式时间为北京时间每天06:17，对应UTC前一日22:17。不得凭记忆改成其他时间。
13. 测试方法数量、测试运行次数和业务运行次数必须分别记录，不得混为一谈。
14. 已完成专项测试必须记录对应提交和Actions运行证据，不能只凭对话记忆更新状态。
15. main.py向filter.py交接时，只能传入completed=True且passed=True的验证结果；必须保留对应主流程集成测试证据。
