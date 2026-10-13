# VideoStudyAgent

本地课程视频学习系统。阶段 1–5 已完成对应离线验证：上传与持久化、字幕/媒体/ASR、结构化生成工具、单 Agent 和独立 Worker；真实 LLM 验收按用户指示延后。

阶段 2 已提供上传、任务列表/详情及重试 API，首次业务访问会迁移 SQLite。页面仍是基础工作台，字幕解析、转写、生成、Worker 与导出在后续阶段开放。阶段进度见 [PLAN.md](../PLAN.md)，验收见 [阶段 1](docs/STAGE_1_REPORT.md)和[阶段 2](docs/STAGE_2_REPORT.md)。

## 环境与安装

- Python 3.12；项目锁定该次版本，避免本机 Python 3.14 与音视频依赖后续兼容性不确定。
- Node.js 22.12+ 或 24，npm；已在 Python 3.12.14、Node.js 24.21.0、npm 11.19.0 验证。
- uv 0.13.0；Python 依赖使用 `backend/uv.lock`，前端使用 `frontend/package-lock.json`。
- 阶段 1 无需 FFmpeg、ASR 模型、LLM 服务或 API Key。首次安装依赖需要网络，测试和日常启动不需要外部服务。

下述命令使用 Windows PowerShell，从 `videostudyagent/` 开始。本工作区已经安装 `.tools/bin/uv.exe`、`backend/.venv/` 和 `frontend/node_modules/`，可以直接跳到启动部分。

新环境可通过已有 Python 安装项目内 uv（不改全局包），然后创建 Python 3.12 环境：

```powershell
python -m pip install --target .tools --index-url https://pypi.org/simple uv==0.13.0
Set-Location backend
& ..\.tools\bin\uv.exe sync --locked --python 3.12 --cache-dir ..\.cache\uv --default-index https://pypi.org/simple
Set-Location ..\frontend
npm.cmd ci
Set-Location ..
```

如果没有 Python 3.12，uv 可能下载该运行时；也可先自行安装，再将 `--python` 指向其完整可执行文件路径。此次实际复用了 Codex 提供的 Python 3.12，没有替换系统 Python。

配置示例在 `.env.example`。阶段 1 无需复制；如需调整限制，可在项目根目录复制为被忽略的 `.env`。配置从该固定目录读取，环境变量优先。密钥字段保持为空；不使用 `VITE_` 环境变量保存密钥。`.env`、上传内容、模型、数据、依赖目录、缓存和构建结果都已列入忽略规则。

## 本地启动

终端一，在 `videostudyagent/backend/`：

```powershell
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

终端二，在 `videostudyagent/frontend/`：

```powershell
npm.cmd run dev
```

打开 [学习工作台](http://127.0.0.1:5173/)。显示“本地服务已连接”表示前端已通过 Vite 的 `/api` 代理连接后端。后端未启动时显示连接失败说明。服务仅绑定本机，按 Ctrl+C 停止。

可查看 [健康接口](http://127.0.0.1:8000/api/health) 与 [接口文档](http://127.0.0.1:8000/docs)。健康检查不初始化数据库、不加载模型、不联网。OpenAPI 的 components 包含未来业务 DTO；paths 只包含已实现的健康接口。

`npm.cmd run build` 生成 `frontend/dist/` 并校验类型；该产物不自带 FastAPI 服务或开发代理。本阶段未配置生产托管。

## 测试与契约同步

后端，在 `backend/`：

```powershell
& .\.venv\Scripts\python.exe -m pytest -q
& .\.venv\Scripts\python.exe -m ruff check .
& .\.venv\Scripts\python.exe -m ruff format --check .
& ..\.tools\bin\uv.exe lock --check --offline --cache-dir ..\.cache\uv
```

前端，在 `frontend/`：

```powershell
npm.cmd test
npm.cmd run build
```

后端测试隔离 `VSA_` 环境变量，禁止外部网络连接；仅允许 Windows asyncio 运行所需的本机 loopback。前端测试替换 fetch，验证成功、失败和请求取消。FakeLLM 只返回预先注入的响应，FakeASR 只返回注入的 Transcript，不调用模型或读取音频。

迁移测试使用 `.cache/pytest/` 内的临时 SQLite，验证 upgrade、重复 upgrade、重开连接、WAL/外键/超时和 downgrade。阶段 2 建立 tasks/assets/task_steps/artifacts/cache_entries；首次业务访问迁移数据库，health 不迁移。pytest 会清理自己的 basetemp，该目录只能放测试临时文件，不可存用户资料。

修改 Schema 后，先在 `backend/` 导出，再在 `frontend/` 生成类型：

```powershell
# backend/
& .\.venv\Scripts\python.exe scripts/export_openapi.py
# frontend/
npm.cmd run generate:types
```

提交变更前运行对应测试和构建；OpenAPI 快照测试会检测未同步的契约。不手改 `openapi.json` 和 `src/api/schema.d.ts`。

## 模块边界

| 位置 | 当前职责 |
| --- | --- |
| `backend/app/core/` | 服务端配置、限制、密钥字段保护 |
| `backend/app/schemas/` | 版本化请求/产物/任务/工具调用/上游登记契约 |
| `backend/app/providers/` | ASR/LLM 协议和离线替身 |
| `backend/app/db/`、`backend/alembic/` | 显式数据库连接和空基线迁移 |
| `backend/app/main.py` | 健康接口、CORS、统一错误响应、OpenAPI |
| `frontend/src/api/` | 自动生成类型和健康请求客户端 |
| `frontend/src/App.tsx` | 基础学习工作台、真实服务连接状态 |
| `docs/upstream_candidates.json` | 五个项目、11 个条目的机器可验证候选基线 |

契约使用整数毫秒、UUID 和带时区审计时间；题数严格为 1–20，难度为 easy/medium/hard，简答题必须包含答案、解析和证据。当前验证结构与文档内引用集合；跨文档来源存在性、quote 原文匹配、状态迁移及结果语义检查在对应业务阶段实现，不能用通过 Schema 代替这些检查。

## 开源复用与后续阶段

阶段 3 已实现字幕与本地转写工具，来源及实测见 [阶段 3 验收](docs/STAGE_3_REPORT.md)。安装 ASR 使用 `uv sync --locked --extra asr --python 3.12`（项目内 uv 也可）；FFmpeg/FFprobe 需在 PATH 或通过 VSA_FFMPEG_BINARY / VSA_FFPROBE_BINARY 指定。显式准备默认模型：在 backend 运行 `python -m app.prepare_model small`；短音频测试可选 tiny，并设置 VSA_ASR_MODEL=tiny。运行时不隐式下载或删除模型。生成与 Worker 仍待后续阶段接入。

复用来源和限制见 [REUSE_RESEARCH.md](docs/REUSE_RESEARCH.md)，决策状态见 [REUSE_DECISIONS.md](docs/REUSE_DECISIONS.md)。BiliNote、DeepTutor 等目前是固定版本的候选，没有上游业务源码纳入。正式采用时再补文件哈希、许可证、通知、适配差异和测试，不安装整个上游系统。

Worker 锁在阶段 5 使用 filelock 的原生平台锁：Windows 采用 WindowsFileLock，Unix 采用 UnixFileLock，非阻塞获取、全程持有，不静默退回 SoftFileLock。依据 [filelock 官方说明](https://py-filelock.readthedocs.io/en/latest/)，原生系统锁在进程退出时释放，适合单 Worker 限制。阶段 1 仅完成选型；尚未安装该依赖或验证实际 Worker 互斥，阶段 5 必须补双进程/崩溃恢复测试。

在 backend 用第三个终端运行 `python -m app.worker`；只有 Worker 处理队列任务，API 不执行模型或媒体长任务。Worker 读取本地 `.env` 中的 DeepSeek 配置，默认 deepseek-flash、关闭思考模式；没有 Key 时明确失败，可补配置后手动重试。`python -m app.worker --once` 仅处理一个待执行任务。第二 Worker 明确退出；Ctrl+C 停止服务，已中断任务可重试。

阶段 6–7 已获用户授权，按阶段测试、报告、提交上传；不执行部署，不编辑上级 `sources/` 或同步规则。Web 上传/结果/导出将在阶段 6 接入。
