# 阶段 7 综合验收记录

日期：2026-10-13。结论：MVP 实现与离线验收完成；真实 DeepSeek 的生成质量、计费与课程语义抽查按用户要求延后。本轮云端模型调用为 0，未部署。

## 完成范围与修改文件

- app/services/cleanup.py、worker.py：原生 Worker 锁内启动清理，仅删除超过一小时且未引用的临时文件；跳过 queued/running 任务、正式输入/产物、符号链接/Windows junction，不递归删除课程或模型。
- app/providers/asr.py：将 zh-CN/en-US 等 BCP47 语种在 Whisper 边界转换为 zh/en；原任务参数和字幕语言保留。
- app/services/subtitles.py：拒绝分钟溢出、库静默忽略的空 VTT cue；继续保留毫秒时间。
- app/core/upload_limit.py、main.py、api.py：用 ASGI 累计接收限制取代 BaseHTTPMiddleware 的接收异常；带/不带 Content-Length 的超限流式上传正常返回 413，解析器能够关闭已暂存的文件。
- app/services/exports.py：成功任务缺少产物索引时显式报告损坏，GET 不更改任务状态；手动重试后可恢复。
- tests/test_final_hardening.py：上述边界、目录链接、正式文件保留、来源哈希及许可证检查。
- tests/http_model_server.py、scripts/smoke_local.py：显式测试入口，在回环 HTTP 上模拟模型协议，运行真实 API/Worker/任务子进程/FFmpeg/Whisper/存储/导出。测试数据与报告保存在忽略目录。
- schemas/common.py、tests/test_config_health.py、openapi.json、前端 schema.d.ts：健康阶段与契约同步到 7。
- README、上级 README/PLAN、AGENTS、.env.example、UPSTREAM_SOURCES.json：清除阶段 1 旧状态，补安装、三进程启动、配置、预算、测试、恢复和限制。

## 自动化测试

| 检查 | 实际结果 |
| --- | --- |
| 全量 pytest | **188 passed，21.27 s，无跳过**；本环境装有 ASR 可选依赖 |
| Ruff check / format --check | 通过；66 个项目 Python 文件已格式化，原样 vendor 排除 |
| uv lock --check --offline | 通过，53 packages |
| Vitest | **13 passed**；上传、错误、取消、轮询停止、来源毫秒、安全 Markdown、失败下载 |
| TypeScript / Vite build | 通过；含 Playwright 配置与 E2E 类型检查 |
| Playwright Chromium | **2 passed，15.3 s**；上传到结果/折叠/五种下载/刷新恢复，手机 375 px 无横向溢出 |
| 已采用来源完整性 | 8 条采用记录的本地 SHA-256 全匹配；固定 SHA、源路径/哈希、许可证、通知和差异完整 |

已有回归包含：1/5/20 题及三难度、中英文长字幕后半覆盖、证据/数字/负号/重复题、有限修复、未知/越权工具、预算、限流/认证/超时、无音轨/无语音、缓存损坏、重启/崩溃、原生锁与超时终止自有后代进程。对应测试此前阶段已有通过记录，本阶段运行全量回归。

## 真实媒体与本地 HTTP 联调

自建英语课程语音，合成为 640×360 MP4；不使用用户资料或未授权课程。环境 Windows、Python 3.12、FFmpeg/FFprobe 9.0.2、faster-whisper 1.2.1、PyAV 18.1.0。tiny 模型固定 Systran/faster-whisper-tiny revision d90ca5fe260221311c53c58e660288d3deb8d356，CPU/int8。

运行脚本使用实际生产 API、Worker CLI、task_runner、ASR 子进程和 DeepSeek HTTP 适配器；模型端为仅回环测试服务，不是云端 DeepSeek，也不是生产降级模式。

| 输入 | 结果 | 题数/难度 | 五种导出 | API 重启 | 缓存命中步骤 |
| --- | --- | --- | --- | --- | --- |
| MP4 | ASR，34000 ms，7 段 | 5 / medium | 全通过 | 结果相同 | 0 |
| VTT | subtitle，2500 ms，1 段 | 1 / easy | 全通过 | 结果相同 | 0 |
| MP4 + SRT | subtitle，未调用 ASR | 5 / medium | 全通过 | 结果相同 | 1 |
| 同 VTT 再次上传 | subtitle | 1 / easy | 全通过 | 结果相同 | 3 |

本地 HTTP 模型接收 22 次请求，其中内容生成 5 次；完整通过模型协议适配器与原生工具调用格式传递。JSON 导出逐对象比对主结果；正式结果重启后仍可读取。修复上传上限后重跑上述完整冒烟通过。摘要见 stage7_smoke.json；原始输入/结果/报告不上传。

## 复用结论

实际采用：B1/B2/B3/B4 来自 BiliNote 90940fde4d224d0f69ad99674f4af0a1ea52d3c4（MIT）；D1/D2/D3 来自 DeepTutor 6cf793bd868ba5ecbe64722936d4be8fab5a01df（Apache-2.0）；T1 来自 AI Tutor 438e3aa42af58dcba61fa993dd1519ade55aafcc（MIT）。本阶段 B2 语言映射改动已同步本地 hash 和差异说明。

T2 评估后替换为本地简答组件，V1 只参考策略，N1 因未见明确许可证不复制代码/提示/测试。没有上游整站、RAG、认证、自动评分或多 Agent 依赖；许可证和相关通知保留在 third_party/licenses 与 THIRD_PARTY_NOTICES.md。

## 遗留项

- 用户明确延后：真实 DeepSeek 工具调用兼容、生成质量、费用和真实课程公式/答案语义抽查；付费验证前需本地 Key 和确认费用上限。
- 未实测默认 small 模型、长课程资源/速度、GPU 和 Linux/macOS 原生进程行为。tiny 的短样本不代表这些性能。
- Markdown/KaTeX 单 JS 包约 669 kB（gzip 204 kB），构建有体积提示；长字幕页面未做虚拟滚动。
- 当前为无认证的 localhost MVP，未部署。后续工作由新的用户指示确定。
