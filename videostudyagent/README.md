# VideoStudyAgent

阶段 8–14 功能已实现，当前新建课程使用统一操作队列。已有课程库须先停止 API/Worker，运行下方显式备份升级命令；本次开发没有迁移你的个人课程库，也没有运行你的待处理任务。

本地课程视频智能学习 MVP。支持 MP4、SRT/VTT 或视频配字幕，配字幕时优先使用字幕。字幕始终自动准备；用户分别选择梳理笔记和生成自测，两项都关可在没有 LLM Key 时只处理字幕。新自测每批固定 5 道简答题，支持 easy/medium/hard、答案、解析、引用、换批及历史导出，旧 1–20 题结果仍可阅读。资料语言可选中文或英文。

笔记页提供按章节聊天、课程专属偏好和版本管理。聊天默认只读；可明确点击“按此要求生成笔记草稿”，或填写修改要求生成草稿。预览后应用，支持放弃与恢复旧版本；不会自动重新生成自测。操作记录显示排队、失败、取消、手动重试、每次尝试和课程累计预留量。

导出：notes.md、quiz.md、quiz.json、transcript.json、transcript.srt。导出只读取经过校验的已有产物，不重新调用模型。

阶段 1–7 已完成离线验收；真实小视频/FFmpeg/Whisper 和实际 Worker 子进程已验证。真实 DeepSeek 验收按用户要求延后；测试模型结果不能用于评价模型生成质量。最新证据见 [阶段 14 记录](docs/STAGE_14_REPORT.md)。

## 安装

需要 Python 3.12、uv、Node.js 22.12–24、FFmpeg/FFprobe。依赖版本由 backend/uv.lock 和 frontend/package-lock.json 固定。音视频工具需在 PATH，或在 .env 中设置 VSA_FFMPEG_BINARY / VSA_FFPROBE_BINARY 完整路径；二进制不随源码分发。

Windows PowerShell，从 videostudyagent 目录执行：

```powershell
Set-Location backend
uv sync --locked --extra asr --python 3.12
Set-Location ../frontend
npm.cmd ci
Set-Location ..
Copy-Item .env.example .env
```

仅用字幕可省去 `--extra asr` 和 FFmpeg；视频配字幕仍需 FFprobe 验证媒体/时长。Linux/macOS 使用相同 uv/npm 命令，Python 路径改为 `.venv/bin/python`。当前真实进程与浏览器验收在 Windows 完成。

faster-whisper 1.2.1 与 PyAV 19 存在实测不兼容，当前锁定 av<19；不要绕过锁文件单独升级。模型运行时仅加载本地文件。显式准备默认 small 模型（此命令需要联网下载公共权重）：

```powershell
Set-Location backend
& .\.venv\Scripts\python.exe -m app.prepare_model small
```

模型保存在 data/models/small，source.json 记录实际固定 revision。可在 .env 设置 VSA_ASR_MODEL=tiny 后显式准备 tiny；或 VSA_ASR_MODEL_PATH 指向已有完整模型目录。默认 CPU/int8，无需 GPU。实际 tiny 短样本测试不代表默认 small 或长课程的速度和质量。

## 配置

.env 固定从 videostudyagent/.env 读取，环境变量优先。仅在本地填写 `VSA_LLM_API_KEY`；模型默认 deepseek-flash，服务地址默认 https://api.deepseek.com，关闭思考模式。不要把密钥放进前端、聊天、日志或 Git。源码中不存在真实密钥；没有 Key 时 API 和页面仍能启动，仅字幕模式可完成；启用笔记、自测或聊天时需要有效服务端模型配置。

| 配置 | 默认与含义 |
| --- | --- |
| VSA_DATA_DIR | 项目下 data，API 和 Worker 必须使用同一目录 |
| VSA_MAX_VIDEO_BYTES / VSA_MAX_SUBTITLE_BYTES | 500 MiB / 5 MiB |
| VSA_MAX_DURATION_MS | 7200000，即 120 分钟；不是处理速度承诺 |
| VSA_LLM_CONTEXT_TOKENS / VSA_LLM_MAX_OUTPUT_TOKENS | 32768 / 4096 |
| VSA_LLM_MAX_REQUESTS / VSA_LLM_TOTAL_TOKENS | 每次操作尝试 100 / 500000 的保守预算 |
| VSA_AGENT_MAX_TOOL_CALLS | 每次尝试最多 12 个工具调用 |
| VSA_TASK_TIMEOUT / VSA_ASR_TIMEOUT | 总任务 7200 秒 / ASR 900 秒 |

预算使用 UTF-8 字节作保守输入上界，并为供应商最多三次网络尝试预留请求和输出预算；它不是计费 token 或人民币费用上限。认证失败不自动重试；限流/临时网络故障最多三次，超过短等待范围时留给手动重试。任务重试可能再次产生模型费用，已验证的步骤/缓存可复用。实际付费验收前需另行确认费用上限。

## 已有课程库升级

先在三个终端用 Ctrl+C 停止 API、Worker 和前端。确认 API 与 Worker 均已退出后，在 backend 目录执行：

```powershell
& .\.venv\Scripts\python.exe -m app.migrate_study --api-stopped
```

Windows CMD 使用同一命令，去掉开头的 `&`。脚本先将 SQLite 完整备份到 `data/backups/before-v2-*.db`，再显式升级至 0003 并索引通过校验的旧结果；原始媒体及生成文件不改写，不调用模型。已是新版本的课程不会重复导入。Worker 运行时锁会阻止升级，`--api-stopped` 是你确认 API 已停止的必要参数。

旧结果按原题数保留。旧排队或中断任务不会自动生成，原 Task 状态保留作历史记录；需按新选项重新上传确认处理。损坏产物会被跳过或报错，不伪装成成功。不要直接对运行中的数据库执行 Alembic。

如升级后需要回滚，保持所有服务停止，先将当前 `app.db` 及同名 `-wal`/`-shm` 文件移到独立恢复目录保存，再将升级前备份复制为 `app.db`，并使用相应旧版本代码；不能将旧备份与新库的 WAL/SHM 混用。不要让新代码覆盖备份，不删除原始课程目录。

## 启动

分别启动三个终端，均绑定本机。API 和 Worker 启动前确保使用相同 .env。

终端一，backend：

```powershell
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

终端二，backend：

```powershell
& .\.venv\Scripts\python.exe -m app.worker
```

终端三，frontend：

```powershell
npm.cmd run dev
```

打开 [学习工作台](http://127.0.0.1:5173)。[API 文档](http://127.0.0.1:8000/docs) 列出实际接口。health/config 不初始化数据库、不加载模型、不联网；新空库在首次上传时建表；现有旧库会提示 MIGRATION_REQUIRED，等待显式升级。`python -m app.worker --once` 仅处理一个待执行操作。

上传后等待 Worker 整理。选择笔记、自测或字幕；点击“查看答案与解析”展开答案。视频课程可点击来源跳转，不自动播放。失败任务仅在可重试时显示按钮；损坏的已完成结果也允许显式重试。刷新页面或重启 API 后，任务和产物仍在原 data 目录。

Ctrl+C 停止各终端。Worker 持有原生进程锁，第二实例会退出；超时/中断终止本次任务的自有子进程，重启后中断任务标为可重试，不自动重新付费执行。Worker 启动时只清理超过一小时的临时文件，跳过活动任务、正式输入/产物和目录链接；不自动删除课程或模型。

## 测试

backend：

```powershell
& .\.venv\Scripts\python.exe -m pytest -q
& .\.venv\Scripts\python.exe -m ruff check .
& .\.venv\Scripts\python.exe -m ruff format --check .
uv lock --check --offline
```

默认 pytest 隔离 VSA_ 配置并阻止外网；有 ASR 可选依赖时运行解码测试，否则相关解码用例会注明跳过。测试只清理自己的 .cache/pytest，不能在该目录放个人资料。

frontend：

```powershell
npm.cmd test
npm.cmd run build
$env:PLAYWRIGHT_BROWSERS_PATH='../.cache/ms-playwright'
npx.cmd playwright install chromium
npm.cmd run test:e2e
```

浏览器首次安装需要联网，测试本身只使用本机服务。Playwright 自动启动隔离的测试 API（8001）和前端（5174）；请保持这两个端口空闲。测试模型仅在 tests/e2e_app.py 显式测试入口注入，不是生产环境降级模式。截图/追踪位于忽略的 .cache 目录。

真实媒体/本地模型冒烟（需要自行准备短 MP4 和本地模型；LLM 永远使用回环 HTTP 测试服务）：

```powershell
# backend，路径替换为自己的已授权短样本和已准备模型
& .\.venv\Scripts\python.exe scripts/smoke_local.py --video C:/samples/lesson.mp4 --model-path ../data/models/tiny
```

该命令使用实际 API、Worker、任务子进程、DeepSeek HTTP 适配器、FFmpeg/ASR、SQLite 和导出；检查 MP4/VTT/视频配 SRT/缓存/重启。独立数据写入 .cache/smoke-final-*，不使用真实云端 Key。请勿将测试模型响应当作真实笔记质量验证。

修改契约后在 backend 运行 `python scripts/export_openapi.py`，再在 frontend 运行 `npm.cmd run generate:types`；不要手改快照和生成类型。

## 架构与复用

React + TypeScript + Vite；FastAPI + Pydantic；SQLite + SQLAlchemy/Alembic；API 负责上传/查询，独立单 Worker 领取任务，一个 Agent 通过原生 Tool Calling 选择五个工具。字幕、笔记、题目使用版本化 JSON 主格式，整数毫秒引用原片段。生成结果必须通过结构和跨文档来源校验，才写入有效缓存并标记成功。

| 模块 | 职责 |
| --- | --- |
| app/api.py、main.py、core | HTTP、配置、脱敏错误、上传上限 |
| app/db、alembic | 状态、原子领取、步骤、产物索引、迁移 |
| app/services | 上传、字幕、媒体、转写、生成、缓存、导出、临时文件 |
| app/agent、task_runner.py、worker.py、operation_worker.py | 单 Agent、受控工具、统一操作队列、预算、独立进程与恢复 |
| app/routes/study.py、notes.py、services/note_chat.py、note_revisions.py | 聊天、课程偏好、草稿及版本 API |
| app/providers、adapters、vendor、prompts | Whisper/DeepSeek、上游适配和版本化提示 |
| frontend/src/components、hooks、api | 上传、学习资料、进度轮询、类型化请求 |

实际采用 B1/B2/B3/B4（BiliNote）、D1/D2/D3（DeepTutor）、T1（AI Tutor）。T2 经源码评估后替换；V1 只参考策略；N1 缺少明确许可证，未复制代码/提示/测试。固定 SHA、源/本地哈希、修改、测试见 [来源清单](docs/UPSTREAM_SOURCES.json)；版权及许可见 [通知](THIRD_PARTY_NOTICES.md)。未安装任一上游整站。

## 已知边界

- 只供本机单使用者；未实现认证、多 Agent、OCR、RAG、自动评分、PDF/Word 导出或部署。
- 引用匹配保证 quote 来自原片段，不能保证答案语义正确。真实 DeepSeek 质量、成本、长课程性能、真实课程公式抽查仍待付费验收；本轮不调用云端。
- 长字幕按预算分块并检查全片段覆盖；没有静默截断。笔记分块单独保存经校验的检查点，手动重试复用有效块；损坏块重新生成。预算不足先报错，建议分段另建课程，不自动提高预算。大型结果页面暂未虚拟滚动，浏览超长字幕可能较慢。
- Markdown/KaTeX 构建包有体积提示，当前本地 MVP 可用，后续可按需加载优化。
