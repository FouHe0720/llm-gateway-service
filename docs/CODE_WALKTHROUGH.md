# 代码导读

请求从 `app/main.py` 组装的 FastAPI 应用进入 API，经 ChatService 调用 Provider。校园示例沿用同一条路径，只在调用端补充来源和资料版本。

| 文件 | 主要职责 |
| --- | --- |
| `app/core/config.py` | 模型映射、认证配置、上游地址及启动校验 |
| `app/domain/schemas.py` | 请求、响应、usage、metadata 和错误结构 |
| `app/providers/base.py` | generate/stream/list_models 协议和统一结果类型 |
| `app/providers/openai_compatible.py` | 异步传输、上游协议解析、错误分类与重试 |
| `app/services/chat_service.py` | 总截止时间、并发、缓存、回退与 SSE 事件 |
| `app/middleware/request_id.py` | 请求标识、正文上限和整个请求周期的日志/指标 |
| `examples/campus_client.py` | 资料校验、证据预算、快照与观测费用 |

## 异步传输和连接池

网关主要等待网络 I/O。Provider 共用 lifespan 中创建的 AsyncClient，await 期间事件循环可处理其他连接。连接池避免每次请求重新握手；它不会加快 GPU 推理，也不能消除同步 CPU 计算对事件循环的阻塞。

Service 只依赖 Provider 协议和统一结果类型。Mock、HTTP、本地模型及测试替身可替换使用。Local 是 Chat Completions HTTP 适配器的薄子类，额外约束 endpoint；Ollama 使用原生 NDJSON 协议，本地模型服务的启动和权重由外部管理。

## 流事件和取消

文本响应使用 HTTP SSE，浏览器通过 fetch reader 提交 POST 和消费响应。原生 EventSource 只有 GET，不能直接发送 messages 正文。

Provider 增量读取 httpx Response，Service 收到块后立即发送 delta，不先生成完整答案。start 后 HTTP 状态不能再修改，上游失败转换为 error 事件。客户端必须区分 done、error 与意外断流，不能只看 HTTP 200。

StreamingResponse 监测 ASGI 断开并取消任务。Service 透传 CancelledError，通过 finally/aclosing 关闭生成器，在取消屏蔽区域完成清理，并释放 Semaphore。关闭 HTTP 连接不保证远端 GPU 推理立即停止。

`tests/test_http_integration.py` 使用真实 TCP 和 Event 阻塞第二块，确认客户端能先收到第一块；随后断开并核对上游清理和并发名额恢复。Mock 的模拟分块用 `simulated=true` 标记，不用于验证推理速度。

## 总预算、重试与回退

连接超时限制建立连接，读取超时限制等待下一批数据，总截止时间限制排队、退避及整个请求。持续收到小块的流也受总预算约束。当前没有公平队列或等待队列长度上限。

生成请求可能收费且非幂等。读取超时不代表上游没有执行，所以不自动重试 ReadTimeout、401、400 或协议错误。连接错误、429 和部分 5xx 可在次数与时间预算内退避重试，仍可能重复执行。非流式请求可配置单跳回退；流从 start 起禁用重试和回退，避免重复 delta。

## 缓存与费用

缓存只保存显式 temperature=0 的非流式成功响应，受 TTL、条目数和字节数限制。缓存键包含完整请求和模型映射。校园调用端还把资料快照写入请求，来源修订后不会复用旧键。

缓存响应保留原始 usage，表示这份内容生成时的观测，并非本次又调用了模型。校园 `observed_cost` 接收显式 cache_hit 标记，命中时不将历史 usage 再计入推理费用。缺少 usage 或价格时也保留 null。

## 单实例状态与日志

限流 deque、缓存和指标只在当前进程中有效。多 worker 会各自拥有配额，重启会清零；多副本需要共享配额与缓存，以及外部指标聚合。

日志不记录完整 Prompt、Key、上游响应或地址。请求标识只接受受限字符，指标路由使用固定集合，未知路径合并为 other。request ID、用户 ID、任意模型名或 IP 不进入指标标签。鉴权使用 compare_digest；启用认证后 metrics 也需要 Key，health 只检查进程存活。

## 验证范围

单元测试检查契约、路由与策略；模拟 HTTP 传输检查协议和尝试次数；TCP 测试检查超时、逐块消费和取消清理。历史 Mock 与 Qwen2.5 实验使用独立负载进程，保留逐请求数据与源码指纹。校园示例只验证调用链，没有测模型问答质量。

执行命令与日期见 [VALIDATION](VALIDATION.md)，实验定义见 [BENCHMARK](BENCHMARK.md)，资料处理见 [CAMPUS_SCENARIO](CAMPUS_SCENARIO.md)。
