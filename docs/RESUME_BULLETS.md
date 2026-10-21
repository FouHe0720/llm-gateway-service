# 简历描述（基于已实现内容）

- 基于 FastAPI、Pydantic 和 httpx 构建异步 LLM Gateway，使用 Provider Protocol 与配置路由统一
  Mock、OpenAI-compatible 和 localhost 模型服务的文本对话接口，支持标准 JSON 与 SSE 增量返回。
- 实现 Gateway Bearer 鉴权、单实例滑动窗口限流、请求 ID、结构化日志与延迟桶指标，使用总截止时间、
  有限退避重试和并发控制约束上游调用，并处理流式中断后的连接与并发名额释放。
- 编写离线单元/集成测试及真实 localhost 故障注入与 SSE 取消测试，完成 Docker 非 root 部署、
  一键 Mock/真实 Benchmark 和 GitHub Actions 配置，保存逐请求数据、模型指纹和冷热结果；本地 Python 3.12 验证 77 项测试通过。

多模型路由在当前 4GB 单模型驻留策略下出现准确率和加载开销退化，保留原始结果。

不写“降低延迟 X%”“高并发 QPS”“多实例生产验证”“真实模型评测通过”等未经测量的结论。
已实际运行 Ollama Qwen2.5 0.5B/1.5B；未调用付费 API，未运行 vLLM 或 3B。
