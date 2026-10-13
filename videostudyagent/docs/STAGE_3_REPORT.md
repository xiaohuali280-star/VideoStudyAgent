# 阶段 3：字幕、媒体与本地转写

2026-10-13。阶段 3 对应验证通过。

已完成：SRT/VTT 成熟库解析及 UTF-8/BOM、UTF-16、GB18030 解码；严格时间轴/时长和毫秒契约；FFprobe 解码/音轨/时长检查；FFmpeg 16 kHz 单声道 PCM WAV；字幕优先和视频配字幕时间范围检查；ASR 可终止子进程；带内容校验的独立缓存与原子产物保存。Windows 长路径问题已通过内部扩展路径支持修复，HTTP 不暴露路径。

修改：services/storage.py、subtitles.py、media.py、transcription.py；providers/asr.py、asr_cli.py；prepare_model.py；配置/依赖锁；字幕/媒体/ASR 测试；实际来源清单、许可证、通知、复用决策及本报告；健康阶段/OpenAPI/前端生成类型同步。

复用 B2：BiliNote 90940fde4d224d0f69ad99674f4af0a1ea52d3c4 的 whisper.py 模型配置/片段映射封装及适用配置转发断言，改为本地-only、显式依赖和语言、CPU 线程转发、严格毫秒、错误传播、子进程超时。去除自动删目录、重下载、事件与原始异常打印；未整体安装 BiliNote。MIT 原版权/许可已保留，原始 Git blob SHA 和 SHA-256、本地哈希见 UPSTREAM_SOURCES.json。B2 可用，因此未启用 V1 备选；N1 仍排除。

验证：**后端 96 passed**，包括真实 FFmpeg 提取、无音轨、合法重叠、非法时间轴、多编码、字幕优先、缓存损坏、越界路径、配置转发、空语音/异常和超时。Ruff 通过。真实 ASR 单独使用本地 tiny、CPU int8、英文自编课程，**34 秒 / 7 个片段**，识别到 learning rate；结果仅保存在被忽略的缓存。

tiny 模型明确下载自 Systran/faster-whisper-tiny，固定 revision d90ca5fe260221311c53c58e660288d3deb8d356；模型与 FFmpeg 二进制未上传。FFmpeg 9.0.2 Windows 构建来自官网列出的 Gyan 来源，并核对 SHA-256。默认 small 未下载或测量，不将 tiny 冒烟当作 small 的性能/质量证据。

实际发现并修复 faster-whisper 1.2.1 与 PyAV 19 的 metadata_errors 不兼容，锁定 PyAV 18.1.0 并增加真实解码回归；依据 [官方 issue 1589](https://github.com/SYSTRAN/faster-whisper/issues/1589)。

遗留：真实用户课程质量/硬件速度在最终验收中分别记录；用户选择 deepseek-flash，但明确延后真实 LLM 验收，不发起收费调用。下一阶段接入分块、结构化生成和来源校验；当前未运行 Agent 或伪造生成结果。
