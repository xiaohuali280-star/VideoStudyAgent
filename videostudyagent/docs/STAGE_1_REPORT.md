# 阶段 1 验收记录

日期：2026-10-13（Asia/Shanghai）。范围：复用基线、工程骨架与数据契约。结论：本阶段检查通过；阶段 2 尚未开始。

## 交付结果

1. FastAPI 可在无密钥、无模型、无数据库时启动，提供真实健康接口；配置读取、CORS 和错误响应有验证。
2. Pydantic 契约覆盖学习参数、时间戳字幕、来源映射分块、笔记、简答题、任务/步骤/产物/缓存和模型工具调用；OpenAPI 与前端类型同步。
3. SQLite/SQLAlchemy 连接与 Alembic 空基线建立，迁移只写版本表；业务表留到阶段 2。
4. React 工作台展示真实后端连接状态，明确提示业务功能后续开放；未加入上传或伪造生成结果。
5. FakeLLM/FakeASR 可供后续离线测试使用；项目内环境、依赖锁、忽略规则、运行指南齐备。
6. 五个调研项目的 11 个条目登记为候选/参考/排除，完整 SHA、许可证、路径、采用阶段接受模型校验。

## 实际验证

| 检查 | 实际结果 |
| --- | --- |
| 后端 `python -m pytest -q` | **63 passed**，1.98 秒，无 warning |
| Ruff check / format check | 通过，23 个 Python 文件格式已符合要求 |
| uv `lock --check --offline` | 通过，锁文件包含 32 个已解析包 |
| 前端 `npm test` | **2 files / 7 tests passed** |
| 前端 `npm run build` | TypeScript 检查及 Vite 生产构建通过 |
| `npm run generate:types` | 通过；重新生成前后 SHA-256 一致 |
| OpenAPI | 快照一致，组件引用可解析，已公开路径仅 `/api/health` |
| SQLite 临时库 | upgrade 两次、重开后版本保留、WAL/外键/busy timeout、downgrade 通过 |
| 本地浏览器冒烟 | 页面可打开，显示“本地服务已连接”；默认窄面板中的三张流程卡片排列正常 |

测试包含题数上下界与类型、难度枚举、空答案/解析、非法时间戳、片段排序/重复、合法重叠、来源集合、危险存储键、带时区时间、配置优先级、测试密钥脱敏、404/422/500 错误响应和上游登记约束。密钥用例只在测试临时目录生成无效随机测试串，没有真实 API Key。

环境：Windows；Python 3.12.14（项目虚拟环境）、uv 0.13.0、Node.js 24.21.0、npm 11.19.0。主要实际锁定版本：FastAPI 0.143.0、Pydantic 2.14.1、SQLAlchemy 2.0.54、Alembic 1.20.0、React 19.3.0、Vite 8.3.4、TypeScript 5.9.3、Vitest 4.1.11。完整版本以两份锁文件为准。

执行期间修复了 Windows asyncio 本机 socketpair 被离线守卫阻断的问题，以及过时 TestClient/Alembic 配置警告。离线守卫禁止外部连接、允许必要本机回环；API 测试改为 HTTPX ASGITransport。受工具沙箱的临时目录和 socket 限制，pytest/Vitest 的成功执行使用了获批的本地权限，测试本身没有调用外部服务。

## 修改文件

以下路径相对项目镜像根目录。除原有规划/约束文档外，其余为本阶段新增文件；生成的契约快照也纳入清单。

```text
PLAN.md
videostudyagent/
  AGENTS.md
  README.md
  .env.example
  .gitignore
  docs/
    REUSE_RESEARCH.md
    REUSE_DECISIONS.md
    upstream_candidates.json
    STAGE_1_REPORT.md
  backend/
    .python-version
    pyproject.toml
    uv.lock
    openapi.json
    alembic.ini
    alembic/env.py
    alembic/script.py.mako
    alembic/versions/0001_baseline.py
    app/__init__.py
    app/main.py
    app/core/__init__.py
    app/core/config.py
    app/db/__init__.py
    app/db/session.py
    app/schemas/__init__.py
    app/schemas/common.py
    app/schemas/study.py
    app/schemas/tasks.py
    app/schemas/providers.py
    app/schemas/upstream.py
    app/providers/__init__.py
    app/providers/interfaces.py
    app/providers/fakes.py
    scripts/export_openapi.py
    tests/conftest.py
    tests/test_config_health.py
    tests/test_contracts.py
    tests/test_migrations.py
    tests/test_providers_baseline.py
  frontend/
    .npmrc
    package.json
    package-lock.json
    tsconfig.json
    vite.config.ts
    index.html
    src/main.tsx
    src/App.tsx
    src/styles.css
    src/api/client.ts
    src/api/schema.d.ts
    src/tests/setup.ts
    src/tests/App.test.tsx
    src/tests/client.test.ts
```

另外安装的 `.tools/`、`.cache/`、`backend/.venv/`、`frontend/node_modules/` 及构建出的 `frontend/dist/` 都属于被忽略的本地工具/产物。根目录同步 AGENTS.md 与 sources/ 保持原样；未创建真实 `.env` 或默认 `data/app.db`。

## 复用状态与选择

- 上游业务模块实际采用数量：**0**。阶段 1 只建基线，未下载/执行上游应用或假称通过其测试。
- B2/V1 计划阶段 3；B1/B3/D1/D2/T1 阶段 4；D3 阶段 5；B4/T2 阶段 6。全部固定提交、源路径在候选清单中，尚未评估完成适配。
- N1 无明确许可证，继续排除代码、提示和测试；没有引入替代来源。
- 本阶段自行实现的是既定工程胶水、DTO 和替身，没有提前重写候选业务模块。正式采用时才生成实际来源/哈希/许可证/通知清单。
- Python 3.12 用于降低后续音视频生态兼容风险；uv/npm 锁定实际环境。前端类型从 OpenAPI 生成，避免手写两套契约漂移。
- 单 Worker 系统锁选用 filelock 原生 Windows/Unix 锁，依据及阶段 5 测试要求见 README；尚无该依赖或 Worker 实现。

## 遗留与下一阶段

阶段 1 无已知阻塞。跨文档来源存在性、原文 quote、状态转换和结果语义校验随业务阶段补齐，当前 DTO 检查不代表这些功能已经完成。

尚未运行真实 FFmpeg/ASR/LLM、上传/学习端到端、Worker 互斥或候选上游模块兼容测试，因为均超出本阶段范围；没有下载模型、调用付费服务或部署。LLM 供应商/模型/预算在阶段 4 真实接入前确定。

下一阶段仅在用户授权后实现上传、文件边界验证、业务数据库表/迁移、任务列表/详情及原子领取/重试仓储。当前停止阶段 1；未执行 Git 提交、推送或部署。
