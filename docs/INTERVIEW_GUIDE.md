# 面试阅读与追问

先按顺序读这五个源文件，再阅读对应测试：

1. `app/core/config.py`：从哪些配置能启用真实上游？哪些状态必须拒绝启动？
2. `app/providers/base.py`：Generation/StreamChunk/Protocol，usage 和关闭语义。
3. `app/providers/openai_compatible.py`：非阻塞传输、协议边界、错误分类和重试。
4. `app/services/chat_service.py`：总截止时间、并发控制、SSE 状态机和清理。
5. `app/middleware/request_id.py`：ASGI 语义、输入上限、日志/指标如何包围整个请求。

## 1. 为什么 Async，不用同步 requests？

网关主要等待网络 I/O。AsyncClient 的 await 让事件循环能处理其他连接，生命周期共享连接池避免每次握手。
它不让 GPU 推理变快，也不会消除 CPU 密集代码阻塞；这类任务应移至线程/进程或上游服务。
本项目没有拿功能测试推断 QPS，吞吐需要另行压测。

## 2. 为什么用 Provider Protocol？为什么 Local 没有独立推理实现？

Service 只依赖 generate/stream/list_models 和统一结果类型，可以用 Mock、HTTP 或测试替身替换。
Local 和 Online 使用相同 Chat Completions 协议，Local 是共享 adapter 的薄子类，区别在 endpoint 约束；
没有为了类数量复制 HTTP 逻辑。真正的本地模型服务由用户管理。

## 3. SSE 与 WebSocket 如何选择？为什么不能直接 new EventSource？

文本生成主要单向传输，HTTP SSE 的数据块和代理部署成本较低。
本项目请求是 POST，需要 messages body；原生 EventSource 只支持 GET，所以浏览器用 fetch reader。
SSE start 后不能再修改 HTTP status，只能发 error；客户端必须检查 done/error，不能只看 HTTP 200。

## 4. 怎样证明是真 streaming？

adapter 增量迭代 httpx Response，不先调用 generate；Service 收到每块立即 yield delta，不拼接完整答案。
真实 TCP 测试用 asyncio.Event 阻塞第二块，在未释放 Event 时客户端必须读取第一块。
Mock 的模拟分块单独用 start.simulated=true 标识，不拿它证明模型真实推理速度。

## 5. 为什么不能对所有异常重试？POST 是否幂等？

服务端生成可能产生费用且非幂等，读取超时不代表上游没有执行。因此不重试 ReadTimeout、401、400 或协议错误。
连接错误/429/部分 5xx 允许有限指数退避与 full jitter，但仍有重复计费风险，成本敏感时设 retries=0。
流从 start 起完全禁用重试，避免重复 delta。Exactly once 需要上游明确支持幂等键/请求查询，当前未实现。

## 6. 客户端断开时如何释放长连接？

StreamingResponse 监测 ASGI 断开并取消任务；Service 透传 CancelledError，通过 finally/aclosing 关闭生成器，
并在取消屏蔽区域完成关闭；adapter 退出 HTTP response context。Semaphore 自动释放。
测试验证上游 finally 和并发名额恢复。上游远端是否立即停止 GPU 推理，不由关闭 HTTP 的网关保证。

## 7. 为什么分连接超时、读取超时和总截止时间？

连接超时限制建立连接；读取超时限制等待下一批数据，连续小块可能让长流持续很久；
asyncio.timeout 的总截止时间额外限制排队、退避和整个请求。默认 3/20/60 秒，均可配置。
排队也在总预算中，避免等待 Semaphore 的请求永远挂起；当前没有公平队列或队列长度硬上限。

## 8. 现在的限流能直接部署多个实例吗？

不能当作全局一致限流。当前一个实例一个 deque，认证后的 /v1 请求共享滑动窗口；检查过程没有 await。
每个进程的状态独立，多 worker 会增加可通过总量，重启也会清零。
应在 Redis 使用原子脚本/shared store，定义按租户/Key 配额、时钟与故障策略；指标同样需要聚合。

## 9. 如何避免日志和 metrics 泄露信息或内存爆炸？

不记录完整 prompt/Key/上游响应/URL，不把 Pydantic error 的 input 直接回传。
request ID 只接受安全字符；日志路由用固定集合，未知 path 合并 other。
metrics 不用 request ID、用户 ID、任意模型名或 IP 作标签，单窗口 deque 长度受配置限制。
认证使用 compare_digest，/metrics 在鉴权开启后也需要 Key；/health 是公开轻量探针。

## 10. 测试覆盖了什么，不能证明什么？

单元测试验证 schema/router/retry；httpx transport fixture 验证精确协议与尝试次数；真实 localhost 服务
验证网络超时、逐块消费和断开资源释放；Docker smoke 验证封装与健康检查。
这不等同第三方服务全部兼容、不证明模型回答质量，也没有测量真实延迟/QPS或运行 GPU 模型。
下一步应在用户提供的 endpoint 上执行独立契约测试，进行带成本预算的压测，再决定分布式存储和追踪方案。
