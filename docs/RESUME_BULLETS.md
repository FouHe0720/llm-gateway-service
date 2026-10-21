# 项目经历

**LLM Gateway｜Python / FastAPI / httpx / Ollama**

- 实现异步模型网关，统一 Mock、OpenAI-compatible 与原生 Ollama 的文本对话和 SSE 接口；处理总截止时间、并发控制、客户端取消和上游连接释放。
- 为非流式请求加入有限重试、单跳回退与 TTL/LRU 缓存，通过故障注入验证恢复行为；在 20% 首次 503/429 的 Mock 场景中，重试将成功率由 80% 提高到 100%。
- 在 RTX 3050 Laptop 4 GB 上完成 Qwen2.5 0.5B/1.5B 对照实验，保存 308 条真实模型请求与 8,031 条 Mock 记录，生成可离线查看的性能报告。90% 重复率下，每组 10 条真实请求的模型调用从 10 次降到 1 次；含冷启动的 P95 未改善。
- 编写 78 项 pytest 测试，配置 Python 3.11–3.13 CI、Docker 验证与无 GPU Mock Benchmark；通过真实 TCP 测试检查 SSE 增量到达和断开后的资源清理。

实验条件与结果见 [BENCHMARK_RESULTS](BENCHMARK_RESULTS.md)。任务路由受单模型驻留限制，频繁切换带来加载开销；当前结果适用于该单机实验规模。
