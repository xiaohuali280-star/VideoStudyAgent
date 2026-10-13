# 阶段 6 验收记录

日期：2026-10-13。范围：学习页面、结果读取、五种导出；真实 LLM 验证按用户要求延后。

## 交付

- 上传 MP4/SRT/VTT，配置 1–20 题、三档难度和语种；课程列表分页、刷新及 URL 恢复当前课程。
- 任务轮询、进度、失败重试；笔记、折叠答案/解析/原文依据、字幕与来源时间。视频播放支持 Range，来源跳转保留毫秒。
- GET result/config/video、固定格式导出 notes.md / quiz.md / quiz.json / transcript.json / transcript.srt；只读取并校验已有结果，不调用模型。损坏结果可显式重试，健康成功任务不可重复提交。
- OpenAPI 输出类型包含实际序列化的默认字段；前端类型同步生成。错误不显示代理 HTML 或供应商原始信息。

## 修改文件

后端：app/api.py、app/main.py、schemas/common.py、schemas/tasks.py、db/repository.py、services/exports.py、openapi.json；tests/test_exports.py、test_config_health.py、e2e_app.py。

前端：src/App.tsx、styles.css、api/client.ts、api/schema.d.ts、hooks/useTask.ts、components 下 UploadForm/TaskView/SafeMarkdown/NotesViewer/QuizViewer/Sources；src/tests、e2e/study.spec.ts、playwright.config.ts、vite.config.ts、tsconfig.json、package.json/package-lock.json。来源清单、通知、规划和阶段约束同步更新。

## 复用

B4：BiliNote 90940fde4d224d0f69ad99674f4af0a1ea52d3c4 的 MarkdownViewer.tsx，仅适配 ReactMarkdown + GFM + math + KaTeX 管线，删除 store/chat/图片等页面依赖，禁止 HTML、危险协议和外部图片加载；完整源路径/哈希/许可证见 UPSTREAM_SOURCES.json。

T2：AI Tutor 438e3aa42af58dcba61fa993dd1519ade55aafcc 的 QuizPanel.tsx 已评估。其 sessionId、选择题选项、评分与重新生成不适用于简答题，未复制；本地 QuizViewer 用 details 展示答案和解析。原因已登记 REUSE_DECISIONS.md。

## 实测

- pytest：177 passed（29.39 s）。包含五种导出与结果一致、重复下载不生成、部分结果、非法格式、损坏结果重试、视频 Range 和任务归属。
- Vitest：13 passed；含上传失败、网络错误、请求取消、运行任务轮询到终态停止、来源毫秒跳转、失败下载、安全 Markdown。
- Playwright Chromium：2 passed（20.2 s）。实际本地 API/SQLite/文件/Agent 工具 + 测试模型；上传三道 hard 简答题、刷新恢复、答案折叠及五种下载比对；375 px 手机无横向溢出。桌面/手机截图已本地查看，存于忽略目录 .cache/qa。
- Ruff、TypeScript 和 Vite build 通过。Vite 提示单个含 Markdown/KaTeX 的 JS 包约 669 kB（gzip 204 kB），本地 MVP 可用，后续可按需加载。

## 遗留与下一阶段

没有调用真实 DeepSeek，测试模型只用于隔离的测试入口，不作为生产降级模式。尚未验证真实模型生成质量、费用或完整长课程性能。阶段 7 继续综合回归、真实短视频/ASR 与本地 HTTP 模型协议联调、临时文件和来源清单核验、运行文档。
