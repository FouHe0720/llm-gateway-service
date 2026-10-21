# API 与 Provider 配置

网关使用自定义文本对话协议。运行后可通过 `/docs` 查看完整 OpenAPI 示例。

## 请求和返回值

```json
{
  "model": "mock-echo",
  "messages": [{"role": "user", "content": "Hello Gateway"}],
  "temperature": 0.2,
  "max_tokens": 64
}
```

`POST /v1/chat` 返回 `answer`、`model`（公开别名）、`request_id`、`usage`、`latency_ms` 和 `metadata`。
usage 来自 Provider，缺失时为 `null`，不会自行估算。Mock 回显输入，不执行采样或 token 截断。
metadata 包含实际服务的模型别名、尝试/重试/回退/缓存/排队信息；原生 Ollama 还返回加载和生成 timing。

| 字段 | 限制 |
| --- | --- |
| `messages` | 1–100 条，角色为 system/user/assistant |
| `content` | 非空，每条最多 16000 字符，总计最多 32000 字符 |
| `temperature` | 0–2 |
| `top_p` | 大于 0、小于等于 1 |
| `max_tokens` | 整数，1–8192 |
| `seed` | 可选随机种子 |
| `task_type` | model 为 auto 时，按配置映射 extract/arithmetic/reasoning |

未知字段会被拒绝；原始 HTTP body 默认上限为 128 KiB。
`X-Request-ID` 可使用 1–64 位字母、数字、点、下划线和连字符，不合法时重新生成。
返回的模型名为公开别名，`/v1/models` 不暴露上游地址和凭据。

## SSE

`POST /v1/chat/stream` 接收相同请求体，正常事件为 `start → delta* → done`。
每个事件包含 request ID；错误事件的 ID 在 error 对象中。Mock 的 start 标记 `simulated=true`。

SSE 启动后 HTTP 状态已经是 200，此后失败以 `error` 结束，不再发送 `done`。
客户端应检查终止事件；只收到部分 delta 不能算成功。中断时可能没有 usage。
流启动后禁用重试和回退，断开连接会关闭网关持有的上游流；远端是否停止推理由上游决定。

## 错误码

错误体形如：

```json
{"error":{"code":"model_not_found","message":"Requested model is not enabled","request_id":"..."}}
```

| HTTP 状态 | 含义 |
| --- | --- |
| 401 | Gateway 鉴权失败 |
| 404 | 模型未知或禁用 |
| 413 / 422 | Body 过大 / 输入不合法 |
| 429 | rate_limited 为 Gateway 限流，provider_rate_limited 为上游限流 |
| 502 | 上游错误或协议错误 |
| 504 | 超时 |

默认最多额外重试两次，范围为连接类错误、429 和 500/502/503/504，使用指数退避与 full jitter。
读取超时不自动重试；其他 POST 重试仍可能重复执行，成本敏感时设置 `UPSTREAM_MAX_RETRIES=0`。
总截止时间默认 60 秒，包含并发排队和退避；连接超时 3 秒、读取无数据超时 20 秒。

## Provider 配置

复制 `.env.example` 为 `.env`，修改后重启。所有真实模型都要求 Gateway 鉴权：

```dotenv
GATEWAY_AUTH_ENABLED=true
GATEWAY_API_KEY=REPLACE_WITH_A_RANDOM_SECRET_AT_LEAST_16_CHARS
```

请求时使用 `Authorization: Bearer <Gateway Key>`。它与上游 Key 分开管理。
`/metrics` 启用鉴权时也需要 Key，但不消耗 API 限流窗口；`/health` 与 `/docs` 公开。

### 原生 Ollama

```dotenv
GATEWAY_MODELS='[{"model":"qwen-0.5b","provider":"ollama","upstream_model":"qwen2.5:0.5b"},{"model":"qwen-1.5b","provider":"ollama","upstream_model":"qwen2.5:1.5b"}]'
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_CONTEXT_LENGTH=1024
GATEWAY_TASK_ROUTES='{"extract":"qwen-0.5b","arithmetic":"qwen-0.5b","reasoning":"qwen-1.5b"}'
```

原生适配器使用 Ollama NDJSON，保留 token 数与加载/生成耗时。
请求指定 `model: "auto"` 与 `task_type` 后使用固定路由表；服务不会自动判断任务难度。
安装 Ollama 和下载模型的步骤见 [BENCHMARK](BENCHMARK.md)。

### OpenAI-compatible

```dotenv
GATEWAY_ENVIRONMENT=production
GATEWAY_MODELS='[{"model":"online-chat","provider":"openai","upstream_model":"YOUR_MODEL"}]'
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=REPLACE_PRIVATELY
```

适配器在 Base URL 后追加 `/chat/completions`，普通请求只传显式设置的生成参数。
流请求发送 `stream=true` 和 `stream_options.include_usage=true`，上游需支持文本 SSE 子集。
支持最后一块 choices 为空的 usage；缺少终止标记会视为截断错误。

### Local HTTP

```dotenv
GATEWAY_MODELS='[{"model":"local-chat","provider":"local","upstream_model":"YOUR_INSTALLED_MODEL"}]'
LOCAL_BASE_URL=http://127.0.0.1:11434/v1
```

Local 复用 OpenAI-compatible adapter，仅允许 localhost / 127.0.0.1 / ::1。
它不会安装模型或启动推理进程。容器的 localhost 指向容器自身；连接其他容器或宿主机时，可改用 openai provider 与可达地址。

## 部署说明

限流为整个实例共享的滑动窗口，默认 60 请求 / 60 秒，Chat / Stream / Models 共用。
指标、缓存和限流状态在重启后清零；多 worker 或多副本需要共享存储与外部聚合。
`/metrics` 的 active_requests 包含当前抓取请求，请求计数和延迟在请求完成后更新。

生产入口应使用 TLS、反向代理、密钥管理和访问控制。HTTP client 关闭重定向，不读取代理环境变量；客户端不能传入任意上游 URL。
