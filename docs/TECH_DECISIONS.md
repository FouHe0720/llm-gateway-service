# 技术决策

1. **项目级 uv 环境**：预检发现 Ubuntu Python 3.12 缺少 `ensurepip`，但已安装 uv。
   使用 `uv venv .venv` / `uv pip install --python .venv/bin/python ...`；不使用 sudo，
   不安装系统包。`scripts/install.sh` 同时兼容标准 venv/pip。
2. **Chat Completions 文本子集**：不代理任意上游 JSON，不开放任意 URL；支持 system/user/
   assistant 与 temperature/top_p/max_tokens，模型别名仅由运维配置。
3. **Protocol + composition**：Router 选择配置别名；HTTP 和 Local 共享异步传输实现，
   Local 仅约束 localhost endpoint，不下载模型。
4. **流事件边界**：上游真正增量消费；Mock 明确标注模拟。流开始后不重试，避免重复内容及
   重复计费；普通生成默认也不自动重试 read timeout，因为上游可能已执行。
5. **运维范围**：限流、并发控制与指标只在一个进程有效；多 worker/副本需要共享存储和
   聚合指标。生产入口需要 TLS/反向代理；健康检查不访问模型。

协议参考：[OpenAI Chat Completions streaming events](https://developers.openai.com/api/reference/resources/chat/subresources/completions/streaming-events)。
usage chunk 可没有 choices，流中断时 usage 可能不可得；实现不自行估算 token。
