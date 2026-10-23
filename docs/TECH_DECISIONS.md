# 技术决策

1. **项目级虚拟环境和锁文件**：依赖安装在 `.venv`，由 `uv.lock` 固定解析结果。
   安装脚本优先使用 uv，也支持标准 venv/pip，不修改系统 Python。
2. **Chat Completions 文本子集**：不代理任意上游 JSON，不开放任意 URL；支持 system/user/
   assistant 与 temperature/top_p/max_tokens，模型别名仅由运维配置。
3. **Protocol + composition**：Router 选择配置别名；HTTP 和 Local 共享异步传输实现，
   Local 仅约束 localhost endpoint，不下载模型。
4. **流事件边界**：上游真正增量消费；Mock 明确标注模拟。流开始后不重试，避免重复内容及
   重复计费；普通生成默认也不自动重试 read timeout，因为上游可能已执行。
5. **运维范围**：限流、并发控制与指标只在一个进程有效；多 worker/副本需要共享存储和
   聚合指标。生产入口需要 TLS/反向代理；健康检查不访问模型。
6. **Python 3.11+**：使用原生 `asyncio.timeout` 和 `TaskGroup` 表达总截止时间与测试任务生命周期。
   当前 WSL 为 Python 3.12；CI 覆盖 3.11/3.12/3.13。

协议参考：[OpenAI Chat Completions streaming events](https://developers.openai.com/api/reference/resources/chat/subresources/completions/streaming-events)。
usage chunk 可没有 choices，流中断时 usage 可能不可得；实现不自行估算 token。
