IPTV 自动订阅系统开发进度

文档版本：3.14
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
MASTER_PLAN 3.53| 已冻结
CORE_FLOW| 已建立，作为程序职责和调用顺序依据
五阶段业务流程| 已实现，继续审查异常边界
models.py| 接口字段正式冻结
核心业务程序| 已实现，持续进行边界审查
GitHub Actions| test、formal 均有成功记录
单元测试| 第46次运行231项全部通过
最近测试模式| 第46次运行成功
最近正式运行| 第36次运行，工作流成功但业务不完整
当前正式订阅| 第36次正式运行发布10个频道

项目已经完成自动采集、整理、IPv4检测、频道筛选、M3U生成和GitHub正式发布的端到端运行。

第36次正式运行整理出146条候选，验证通过10条，另有2条因单候选验证预算耗尽而未完成。正式输出包含10个频道。工作流结论为success，但业务日志明确标记“运行是否不完整：True”，两者不能混为一谈。

第46次运行是最新测试模式运行，不是正式发布运行。正式发布记录仍以第36次运行作为最新正式运行记录。

---

二、程序进度

文件| 状态| 已完成事项及剩余检查
sources.py| 已实现| 来源整理、人工来源读取、索引解析
collector.py| 已实现| 两轮来源下载、并发和预算控制；已审查外层截止时间取消时部分字节不保留的处理方式
normalizer.py| 已实现| M3U/TXT解析、候选规范化、去重、名额分配和整理预算控制
network.py| 已实现| IPv4网络请求、安全检查、响应读取限制和HTTP错误诊断；剩余安全边界待核对
validator.py| 已实现| 检测编排、TS/HLS验证；检测阶段预算耗尽和外部取消专项测试已通过
filter.py| 已实现| 频道筛选、去重和M3U生成
publisher.py| 已实现| 文件质量检查、原子替换、Git发布和共享发布预算控制
main.py| 已实现| 统一调度完整运行流程；两轮采集、阶段异常停止、发布退出码及筛选交接专项测试已通过
config.py| 已实现| 统一配置参数和运行限制；未直接引用配置项待按规范处理
GitHub Actions| 已验证| 手动test、手动formal均有成功记录

以上“已实现”不代表每个程序的所有异常边界都已独立测试。

---

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
- job ID：130007305516
- 结果：success
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
已验证候选| 87
验证通过候选| 29
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
已验证候选| 144
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

该文件中第一条频道记录格式有效，解析器成功解析并产生1条候选。文件尾部另有一条不完整的EXTINF记录，缺少频道名，下一行内容为"undefined"。解析器对该异常记录发出警告并跳过，没有影响前面有效记录的解析。

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
已验证候选| 146
验证通过候选| 9
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
- 下游程序会跳过失败或截断结果，部分字
