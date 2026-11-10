# IPTV 自动订阅系统

轻量、自动化运行的 IPTV 订阅生成与发布系统。

系统自动完成：

来源管理 → 订阅采集 → 数据整理 → IPv4 网络检测 → TS/HLS 直播流验证 → 筛选去重 → 生成 M3U → 发布更新。

正式订阅文件：

```text
output/iptv.m3u
```

测试订阅文件：

```text
output/test/iptv-test.m3u
```

> 本项目以 `MASTER_PLAN.md` 为唯一完整技术规范和验收依据。  
> 本文档只负责项目简介、运行方式和订阅地址；与 `MASTER_PLAN.md` 冲突时，以 `MASTER_PLAN.md` 为准。  
> 开发进度和实际测试结果见 `PROGRESS.md`；总体架构和调用流程见 `CORE_FLOW.md`。

---

## 一、项目特点

- 五阶段流程：采集、整理、检测、筛选、发布。
- 六个核心程序职责分离。
- 两轮采集：先索引，再订阅。
- 仅允许公网 IPv4，禁止代理和 IPv6。
- 有限流式读取，避免无限下载。
- TS/HLS 实际直播流验证。
- 候选去重先于名额分配，结果不受并发完成顺序影响。
- 正式发布使用临时文件和原子替换。
- 测试模式与正式模式隔离。
- 正式发布支持 Git 推送和远端 SHA 核验。
- 不使用评分系统，不建立复杂数据库。

---

## 二、目录结构

```text
.
├── MASTER_PLAN.md          # 唯一完整技术规范和验收依据
├── CORE_FLOW.md            # 总体架构与调用流程
├── PROGRESS.md             # 真实开发进度、测试结果和待办
├── README.md               # 项目简介、运行方式和订阅地址
├── main.py                 # 统一调度
├── models.py               # 数据结构与接口
├── config.py               # 参数、预算、人工来源配置
├── network.py              # 统一 IPv4 网络请求
├── sources.py              # 来源管理和索引解析
├── collector.py            # 实际下载
├── normalizer.py           # 解析、规范化、候选去重和名额分配
├── validator.py            # 检测编排和 TS/HLS 验证
├── filter.py               # 筛选、去重、生成 M3U
├── publisher.py            # 文件检查和发布
└── output/
    ├── iptv.m3u            # 正式订阅
    └── test/
        └── iptv-test.m3u   # 测试订阅
```

---

## 三、人工来源配置

人工来源统一配置在 `config.py`：

```python
MANUAL_SUBSCRIPTION_SOURCES: list[str] = [
    # 每项一个 HTTP/HTTPS 订阅来源 URL
]

MANUAL_STREAM_URLS: list[str] = [
    # 每项一个 HTTP/HTTPS 单条直播地址 URL
]
```

规则：

- 人工订阅来源参与来源下载名额分配。
- 人工单条直播地址不占来源下载名额，但计入全局候选上限。
- 人工输入优先于自动发现来源。
- 不合法 URL 会被跳过并记录原因。

详细规则见 `MASTER_PLAN.md`。

---

## 四、运行方式

系统支持三种运行方式：

1. 每日自动正式运行。
2. 手动正式运行。
3. 手动测试运行。

### 1. 每日自动运行

每日北京时间 06:00 自动运行，对应 GitHub Actions UTC 前一日 22:00。

自动运行执行正式发布流程。

### 2. 手动正式运行

通过 GitHub Actions 手动触发，选择正式模式。

正式模式会：

- 生成正式文件 `output/iptv.m3u`；
- 执行文件质量保护；
- 通过检查后原子替换；
- 按规则提交并推送 Git；
- 核对远端分支 SHA。

### 3. 手动测试运行

通过 GitHub Actions 手动触发，选择测试模式。

测试模式：

- 只写入 `output/test/iptv-test.m3u`；
- 不覆盖正式文件；
- 不推送 Git；
- 不检查正式旧文件是否损坏；
- 只检查测试文件自身。

### 4. 并发保护

自动运行、手动正式运行、手动测试运行使用同一个 concurrency group。

设置：

```yaml
cancel-in-progress: false
```

三种运行互斥，不允许同时发布或互相干扰。

具体工作流输入名称和命令参数，以实际 GitHub Actions 工作流和 `main.py` 实现为准；不得与 `MASTER_PLAN.md` 冲突。

---

## 五、输出文件

| 文件 | 用途 |
|---|---|
| `output/iptv.m3u` | 正式订阅文件 |
| `output/test/iptv-test.m3u` | 测试订阅文件 |

正式文件采用标准 M3U 格式：

```m3u
#EXTM3U
#EXTINF:-1 tvg-id="ID" tvg-name="NAME" group-title="GROUP",频道名称
https://example.com/live.m3u8
```

正式发布要求：

- UTF-8 无 BOM；
- LF 换行；
- 首行 `#EXTM3U`；
- 至少一个有效频道；
- 旧文件损坏时停止正式发布；
- 测试模式不覆盖正式文件。

---

## 六、订阅地址

正式订阅地址使用仓库中的正式文件。

将下面占位符替换为实际仓库信息：

```text
https://raw.githubusercontent.com/<OWNER>/<REPO>/<BRANCH>/output/iptv.m3u
```

或使用 GitHub Pages 地址：

```text
https://<OWNER>.github.io/<REPO>/iptv.m3u
```

说明：

- `<OWNER>`：GitHub 用户名或组织名。
- `<REPO>`：仓库名。
- `<BRANCH>`：正式发布分支，例如 `main`。
- 实际订阅地址以仓库正式发布配置为准。
- 测试文件地址不得作为正式订阅地址对外发布。

---

## 七、发布保护与退出码

正式发布具备以下保护：

- 先写临时文件，再检查，检查通过后原子替换。
- 旧文件损坏时停止正式发布，保留旧文件。
- 有效频道为 0 时不得覆盖旧文件。
- 测试模式与正式模式隔离。
- Git 推送失败或远端状态无法确认时，不误报成功。
- 禁止强制推送。

退出码：

| 退出码 | 含义 |
|---|---|
| 0 | 运行成功 |
| 1 | 配置或输入错误 |
| 2 | 阶段发生不可恢复错误 |
| 3 | 正式发布失败 |
| 4 | 发布状态无法确认 |

---

## 八、开发与测试

开发顺序和测试要求以 `MASTER_PLAN.md` 为准。

当前开发进度、实际测试结果和待办见 `PROGRESS.md`。

总体架构和程序调用流程见 `CORE_FLOW.md`。

任何未实际执行的测试不得标记为通过；任何未完成的功能不得报告为已完成。

---

## 九、文档优先级

1. `MASTER_PLAN.md`：唯一完整技术规范和验收依据。
2. `CORE_FLOW.md`：总体架构和调用流程说明。
3. `PROGRESS.md`：真实开发进度、测试结果和待办。
4. `README.md`：项目简介、运行方式和订阅地址。

其他文件与 `MASTER_PLAN.md` 冲突时，以 `MASTER_PLAN.md` 为准。
