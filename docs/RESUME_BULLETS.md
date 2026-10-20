# 简历描述（基于已实现内容）

- 基于 FastAPI、Pydantic 和 httpx 构建异步 LLM Gateway，使用 Provider Protocol 与配置路由统一
  Mock、OpenAI-compatible 和 localhost 模型服务的文本对话接口，支持标准 JSON 与 SSE 增量返回。
- 实现 Gateway Bearer 鉴权、单实例滑动窗口限流、请求 ID、结构化日志与延迟桶指标，使用总截止时间、
  有限退避重试和并发控制约束上游调用，并处理流式中断后的连接与并发名额释放。
- 编写离线单元/集成测试及真实 localhost 故障注入与 SSE 取消测试，完成 Docker 非 root 部署、
  一键 Mock Demo 和 GitHub Actions 配置；本地 Python 3.12 验证 62 项测试通过。

不写“降低延迟 X%”“高并发 QPS”“多实例生产验证”“真实模型评测通过”等未经测量的结论。
Local adapter 已实现，但本次没有运行 Ollama/vLLM 推理；Online 未调用真实付费 API。
