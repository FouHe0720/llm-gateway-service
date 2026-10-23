# LLM Gateway 使用与实现手册

本手册从安装、接口调用讲到配置、运行边界和源码结构。命令在仓库根目录执行，使用 Bash。
网关处理文本模型调用；默认 Mock 回显，不安装模型、不执行检索，也不提供工具调用协议。

## 1. 服务位置与功能

多个项目同时运行时，建议使用以下端口；这些是运行约定，不会自动改变各项目配置。

| 项目 | 建议地址或传输 |
| --- | --- |
| LLM Gateway | `http://127.0.0.1:8101` |
| Structured 输出服务 | `http://127.0.0.1:8102` |
| 校园 RAG | `http://127.0.0.1:8103` |
| AgentOps 评测 | `http://127.0.0.1:8105` |
| Research Agent | `http://127.0.0.1:8106` |
| Workspace Agent | stdio，无 HTTP 监听端口 |

网关自身默认端口仍为 8000。下文显式使用 8101，其他项目不会因此自动连到网关。

| 能力 | 实际行为 |
| --- | --- |
| 普通文本生成 | `/v1/chat`，统一响应和错误结构 |
| 流式生成 | `/v1/chat/stream`，start/delta/done/error SSE |
| 模型映射 | 公开别名映射到 Mock、OpenAI-compatible、Local 或 Ollama |
| 调用策略 | 总超时、并发控制、有限重试、单跳回退、可选 TTL/LRU 缓存 |
| 入口控制 | Bearer 鉴权、正文上限、共享滑动窗口限流 |
| 观测 | 请求标识、结构化日志、进程内 JSON 指标、调用 metadata |
| 校园示例 | 检索后的资料校验、来源快照、证据预算和费用计算 |
| 实验 | Mock 与本地 Ollama 对照、逐请求数据和离线 HTML |

## 2. 安装、启动与退出

需要 Python 3.11+；推荐 3.12。安装依赖需要访问软件源，默认运行不需要 API Key 或 GPU。

```bash
git clone https://github.com/FouHe0720/llm-gateway-service.git
cd llm-gateway-service
make install
cp -n .env.example .env
make run PORT=8101
```

安装脚本优先用 `uv sync --frozen --extra dev --python python3`，禁止自动下载 Python。
没有 uv 时，脚本尝试系统 Python 的 venv/pip，安装 requirements-dev.lock 和本项目。
如果系统缺少 ensurepip，可使用已安装的 uv；不要混用系统 site-packages 与项目环境。

`.env.example` 显式关闭 Mock 开发鉴权。Settings 的代码默认值却是开启鉴权，直接跳过 `.env` 可能因缺少 Key 启动失败。
修改模型、路由或缓存配置后需要重启。前台进程用 Ctrl+C 退出，lifespan 会关闭 HTTP 连接池。

另一个终端检查：

```bash
curl -sS http://127.0.0.1:8101/health
curl -sS http://127.0.0.1:8101/v1/models
```

预期 health 为 `{"status":"ok"}`；模型列表默认包含 mock-echo。
浏览器接口文档是 `http://127.0.0.1:8101/docs`，机器可读契约是 `/openapi.json`。

不想保留服务时，可直接执行两个独立演示：

```bash
make demo
make campus-demo
```

`make demo` 自动使用空闲 TCP 端口，演示后退出；不是固定监听 8101。
`make campus-demo` 在进程内通过 ASGI HTTP 调用应用，写入 `runtime/campus-demo.json`。
两者固定使用 Mock；后者只回显校园请求，不生成政策答案。

## 3. 普通请求和字段

```bash
curl -sS http://127.0.0.1:8101/v1/chat \
  -H 'Content-Type: application/json' \
  -H 'X-Request-ID: guide-chat' \
  --data-binary '{"model":"mock-echo","messages":[{"role":"system","content":"用简洁中文回答。"},{"role":"user","content":"说明网关的作用。"}],"temperature":0,"top_p":1,"max_tokens":128,"seed":42}'
```

Mock 返回 `[mock] ` 加最后一条消息正文；不会按 max_tokens 截断，也不模拟模型采样质量。

| ChatRequest 字段 | 默认 | 约束与用途 |
| --- | --- | --- |
| `model` | 必填 | 1–128 字符；公开别名，或配置路由时的 auto |
| `messages` | 必填 | 1–100 条，顺序原样传给 Provider |
| `messages[].role` | 必填 | system / user / assistant |
| `messages[].content` | 必填 | 非空且非全空白，单条最多 16,000 字符，总计最多 32,000 |
| `temperature` | null | 有限数，0–2；缓存要求显式为 0 |
| `top_p` | null | 有限数，大于 0、不超过 1 |
| `max_tokens` | null | 严格整数，1–8192；各上游实际支持范围另行确定 |
| `seed` | null | 严格整数，0–2³¹−1；由上游决定确定性程度 |
| `task_type` | null | extract / arithmetic / reasoning；auto 按此查路由表 |

未知字段会被拒绝。字符上限和 HTTP 正文字节上限分别检查，中文字符不能按一个字节计算。
X-Request-ID 接受 1–64 位字母、数字、点、下划线和连字符；不合法时生成新的 UUID。
响应头 X-Request-ID 与正文 request_id 用于关联当前请求，不作为指标标签。

| ChatResponse 字段 | 含义 |
| --- | --- |
| `answer` | 模型文本；Mock 为回显 |
| `model` | 调用方请求的别名，包括可能的 auto |
| `request_id` | 当前请求标识 |
| `usage` | prompt_tokens、completion_tokens、total_tokens；未知为 null |
| `latency_ms` | 从模型路由后到完成，含并发排队与退避，不含全部入站解析 |
| `metadata.served_model` | 实际服务的公开别名，回退时可能改变 |
| `metadata.attempts/retries/fallback_count` | 上游尝试、重试与回退计数 |
| `metadata.cache_status` | disabled / bypass / miss / hit |
| `metadata.queue_ms` | 等待并发名额的时间 |
| `metadata.timing` | 原生 Ollama 的 load/eval/prompt_eval 纳秒耗时与 eval_count，其他情况可为空 |

缓存命中只返回缓存答案，本次 usage/timing 为 null，attempts 为 0；不复用上次 request ID。
没有 usage 不能用字符数补成 token，也不能据此生成账单。

## 4. SSE：消费、终止与取消

```bash
curl -N -sS http://127.0.0.1:8101/v1/chat/stream \
  -H 'Content-Type: application/json' \
  --data-binary '{"model":"mock-echo","messages":[{"role":"user","content":"逐块返回这段内容。"}],"max_tokens":64}'
```

响应为 text/event-stream，事件之间空一行；网络 chunk 与 SSE 事件并非一一对应。

```text
event: start
data: {"model":"mock-echo","request_id":"...","simulated":true}

event: delta
data: {"model":"mock-echo","request_id":"...","delta":"[moc"}

event: done
data: {"model":"mock-echo","request_id":"...","usage":null,"latency_ms":0.0,"metadata":{...}}
```

上面是结构示意，latency 和分块由实际运行决定。正常顺序为 start → 零到多条 delta → done。
start 后的失败发送 error，不再发送 done；直接断流也不能视为成功。

```text
event: error
data: {"error":{"code":"provider_timeout","message":"Upstream provider timed out","request_id":"..."}}
```

校验、鉴权、未知模型和限流可在启动前返回 JSON 4xx。启动后 HTTP 已是 200，应检查终止事件。
浏览器使用 POST fetch，原生 EventSource 不能提交 messages。以下代码可在本地 `/docs` 页控制台运行：

```javascript
const controller = new AbortController();
const response = await fetch('/v1/chat/stream', {
  method: 'POST', signal: controller.signal,
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({model: 'mock-echo', messages: [{role: 'user', content: '你好'}]})
});
if (!response.ok) throw new Error(`HTTP ${response.status}`);
const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
let buffer = '', terminal = false;
try {
  while (!terminal) {
    const {value, done} = await reader.read();
    if (done) break;
    buffer += value;
    let boundary;
    while ((boundary = buffer.indexOf('\n\n')) >= 0) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const lines = frame.split('\n');
      const event = lines.find(x => x.startsWith('event:'))?.slice(6).trim();
      const data = JSON.parse(lines.filter(x => x.startsWith('data:')).map(x => x.slice(5).trimStart()).join('\n'));
      if (event === 'delta') console.log(data.delta);
      if (event === 'error') throw new Error(data.error.code);
      if (event === 'done') terminal = true;
    }
  }
  if (!terminal) throw new Error('流在终止事件前中断');
} finally {
  await reader.cancel(); reader.releaseLock();
}
```

网关固定输出 LF 分帧；上游适配器另支持 CRLF。启用鉴权时还要添加 Authorization 请求头。
取消请求可调用 controller.abort() 或停止 curl。网关关闭上游流、释放 Semaphore；远端是否立即停止推理由上游决定。
流开始后不重试、不回退、不读写缓存，避免已输出内容被重放。

## 5. 鉴权、限流与错误

真实 Provider 和 production 环境必须启用网关鉴权；只有 development 且全部启用模型为 Mock 才能关闭。
Gateway Key 至少 16 字符，它与 OpenAI/Local 上游 Key 分开。

```bash
# 先在自己的 shell 或私有 .env 中设置 GATEWAY_API_KEY。
curl -sS http://127.0.0.1:8101/v1/models \
  -H "Authorization: Bearer ${GATEWAY_API_KEY}"
```

`.env` 由应用读取，不会自动 export 到调用 curl 的另一个 shell。
Chat、Stream、Models 共用认证后的实例限流窗口，默认 60 次/60 秒；命中缓存仍消耗一次入口配额。
metrics 需要认证但不消耗该窗口，health、docs、redoc 和 openapi.json 公开。
429 的 Retry-After 表示当前窗口释放名额前的秒数，认证失败不消费 API 配额。

| HTTP | error.code | 处理方向 |
| --- | --- | --- |
| 401 | unauthorized | 核对 Gateway Bearer Key |
| 404 | model_not_found | 核对 enabled 别名或 auto 路由 |
| 413 | request_too_large | 减少 HTTP 正文 |
| 422 | validation_error | 核对字段、类型、消息长度与未知字段 |
| 429 | rate_limited | 按 Retry-After 等待或调整入口配额 |
| 429 | provider_rate_limited | 上游限流，结合重试和总预算处理 |
| 502 | provider_error | 上游 HTTP、连接或响应协议失败 |
| 504 | provider_timeout | 区分连接/读取/总预算超时 |
| 500 | internal_error | 核对日志中的请求标识，正文不回显内部异常 |
| 其他 HTTP 错误 | http_error | 路径或方法等 HTTP 请求问题 |

```bash
curl -sS -i http://127.0.0.1:8101/v1/chat \
  -H 'Content-Type: application/json' \
  --data-binary '{"model":"missing","messages":[{"role":"user","content":"test"}]}'
```

## 6. 缓存、模型路由、回退与重试

缓存默认关闭。启用后仅缓存 temperature=0 的非流式成功、非回退响应。
键是规范化完整请求与模型映射的 SHA-256；消息顺序、参数、资料快照都会影响键。
TTL 使用单调时钟；命中更新 LRU 顺序，超过条目或答案字节预算时逐项淘汰。
预算包含 UTF-8 答案和键的大小，不是完整 Python 对象占用；并发相同 miss 没有 single-flight 合并。

在私有 `.env` 中启用后重启：

```dotenv
GATEWAY_CACHE_ENABLED=true
GATEWAY_CACHE_TTL_SECONDS=60
GATEWAY_MODELS='[{"model":"small","provider":"mock","fallback_model":"backup"},{"model":"backup","provider":"mock"}]'
GATEWAY_TASK_ROUTES='{"extract":"small","arithmetic":"small","reasoning":"backup"}'
```

```bash
curl -sS http://127.0.0.1:8101/v1/chat \
  -H 'Content-Type: application/json' \
  --data-binary '{"model":"auto","task_type":"extract","temperature":0,"messages":[{"role":"user","content":"相同请求连续发送两次。"}]}'
```

第二次可观察 cache_status=hit。Mock 不注入上游故障；配置了 fallback 不代表此请求发生回退。
auto 只查调用方给出的 task_type，不分类问题难度。没有对应配置时返回 404。
回退只能指向启用、不同且没有后继回退的别名；启动时拒绝循环。上游 400/401 等不可恢复 4xx 不回退；429 按可恢复错误处理。

连接错误、ConnectTimeout、ReadError，以及 HTTP 429/500/502/503/504 可有限重试。
ReadTimeout 不自动重试；POST 在远端可能已执行，重试不是 exactly-once 保证。
每个 Provider 最多 1 + UPSTREAM_MAX_RETRIES 次，full jitter 上界为 base × 2^attempt。
主模型和备用模型另共用 GATEWAY_MAX_PROVIDER_ATTEMPTS、Semaphore 与总截止时间。
总预算包含排队和退避；读取超时是等待下一批字节的限制，不等于完整生成时长。

## 7. 四种 Provider

| provider | 上游协议 | 配置要求 |
| --- | --- | --- |
| mock | 进程内回显，模拟分块 | 无模型、无上游 Key |
| openai | Base URL + `/chat/completions`，JSON / SSE | OPENAI_BASE_URL、非空 OPENAI_API_KEY |
| local | 与 openai 同协议 | LOCAL_BASE_URL 只允许 localhost、127.0.0.1、::1；Key 可选 |
| ollama | Base URL + `/api/chat`，JSON / NDJSON | 仅 localhost 地址，保留原生 usage/timing |

接真实模型前，先自行准备可用服务和模型。以下只是配置示例，不会自动下载或启动模型：

```dotenv
GATEWAY_ENVIRONMENT=development
GATEWAY_AUTH_ENABLED=true
GATEWAY_API_KEY=REPLACE_WITH_YOUR_PRIVATE_GATEWAY_KEY
GATEWAY_MODELS='[{"model":"qwen-small","provider":"ollama","upstream_model":"qwen2.5:0.5b"}]'
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_CONTEXT_LENGTH=1024
```

OpenAI-compatible 改为 provider=openai，设置自己的 base URL、upstream_model 和私有上游 Key。
Local 示例使用 `http://127.0.0.1:11434/v1`，provider=local。
URL 不能含账号密码、query 或 fragment；HTTP 客户端不跟随重定向，不读取代理环境变量。
兼容服务应支持文本 choices/message.content，以及流式 `[DONE]`；缺终止帧视为截断。
原生 Ollama 将 max_tokens 映射为 num_predict，未设置时用默认 128；显式值仍受请求 8192 上限约束。
流帧最大 64 KiB；非流响应另受 UPSTREAM_MAX_RESPONSE_BYTES 限制。

## 8. 校园 RAG 调用端

来源位于 `examples/campus/`：8 份历史文档、manifest 和 Markdown 摘录，不包含原始 DOCX。
资料年份与年级分开；2024 版培养方案不自动解释为 2024 级。原文版权不由代码 MIT 许可授予。
`build_campus_request` 接受上游检索选出的 source_ids，不自行搜索知识库。

```bash
mkdir -p runtime/guide
.venv/bin/python - <<'PY' > runtime/guide/campus-request.json
from examples.campus_client import build_campus_request
bundle = build_campus_request(
    "2024级新生选课时间是什么？", ["course-selection-2024"], year=2024,
)
print(bundle.request.model_dump_json())
PY
curl -sS http://127.0.0.1:8101/v1/chat \
  -H 'Content-Type: application/json' \
  --data-binary @runtime/guide/campus-request.json
```

调用端验证文件 SHA-256 和段落一致性、校区和资料版本；默认最多 6,000 个证据字符、max_tokens=256。
空/重复/未知来源、范围不符、文件被修改或预算不足抛出 EvidenceUnavailable，调用方处理为资料不足提示。
资料快照写入 Prompt，改变来源会改变缓存键。Prompt 约束本身不证明真实模型能正确引用。
`observed_cost(usage, input_per_million, output_per_million, cache_hit=...)` 用 Decimal 和显式价格计算。
缺 token、价格或缓存命中时返回 None；价格必须有限且非负，币种由调用方定义。
当前网关已清空命中响应的 usage，cache_hit 仍是调用端明确区分命中的防护。
2026 级政策、未收录业务和其他校区不能直接套用这些历史资料。

## 9. 完整环境配置表

应用读取项目根 `.env`，环境变量覆盖它；显式 Settings 构造参数优先。未知 .env 字段被忽略。
布尔值使用 true/false，模型与路由填写 JSON。表中是代码默认值，示例 .env 的差异另行标明。
字典型配置会按键合并不同配置源；单独设置环境变量 `GATEWAY_TASK_ROUTES='{}'` 不能抹除 `.env` 中已有路由。
更换模型时同步修改或移除旧路由，并检查调用进程的环境。需要隔离演示配置时，应显式禁用 env_file 并使用独立 env_prefix，而不是靠空字典覆盖。

| 变量 | 默认值 | 范围或说明 |
| --- | --- | --- |
| GATEWAY_ENVIRONMENT | development | development / production |
| GATEWAY_AUTH_ENABLED | true | 示例 .env 为 false；关闭仅限全 Mock 开发 |
| GATEWAY_API_KEY | 无 | 开启鉴权时至少 16 字符 |
| GATEWAY_MODELS | 一个 mock-echo 映射 | 非空启用集合、别名唯一；结构见下表 |
| MOCK_CHUNK_DELAY_SECONDS | 0.02 | 0–5 秒，模拟分块间隔 |
| OPENAI_BASE_URL | 无 | 启用 openai 时必填 |
| OPENAI_API_KEY | 无 | 启用 openai 时非空 |
| LOCAL_BASE_URL | http://127.0.0.1:11434/v1 | localhost HTTP(S) |
| LOCAL_API_KEY | 无 | 可选上游认证 |
| OLLAMA_BASE_URL | http://127.0.0.1:11434 | localhost HTTP(S) |
| OLLAMA_CONTEXT_LENGTH | 1024 | 256–4096 |
| OLLAMA_DEFAULT_MAX_TOKENS | 128 | 默认值可配置为 1–512；显式请求不被此值截断 |
| OLLAMA_KEEP_ALIVE | 2m | 传给 Ollama 的 keep_alive 字符串 |
| GATEWAY_MAX_PROVIDER_ATTEMPTS | 6 | 1–12，整个请求尝试预算 |
| GATEWAY_CACHE_ENABLED | false | 只影响符合条件的非流请求 |
| GATEWAY_CACHE_TTL_SECONDS | 60 | 大于 0、不超过 3600 |
| GATEWAY_CACHE_MAX_ENTRIES | 128 | 1–4096 |
| GATEWAY_CACHE_MAX_BYTES | 2097152 | 1024–16777216 |
| GATEWAY_TASK_ROUTES | {} | task_type 到启用别名的映射 |
| UPSTREAM_CONNECT_TIMEOUT_SECONDS | 3 | 大于 0、不超过 60 |
| UPSTREAM_READ_TIMEOUT_SECONDS | 20 | 大于 0、不超过 300 |
| GATEWAY_REQUEST_TIMEOUT_SECONDS | 60 | 大于 0、不超过 600 |
| UPSTREAM_MAX_RETRIES | 2 | 0–5，首次调用之外的次数 |
| UPSTREAM_RETRY_BASE_SECONDS | 0.2 | 0–10，指数退避基数 |
| UPSTREAM_CONCURRENCY | 8 | 1–100，进程共享 Semaphore |
| UPSTREAM_MAX_RESPONSE_BYTES | 1048576 | 1024–10485760 |
| GATEWAY_RATE_LIMIT_REQUESTS | 60 | 1–100000 |
| GATEWAY_RATE_LIMIT_WINDOW_SECONDS | 60 | 大于 0、不超过 3600 |
| GATEWAY_MAX_BODY_BYTES | 131072 | 1024–1048576，HTTP 正文上限 |
| PORT | 8000 | Makefile/Compose 使用，应用 Settings 不读取 |
| GATEWAY_BIND_HOST | 127.0.0.1 | 仅 Compose 的宿主绑定；make run 固定 loopback |

| GATEWAY_MODELS 元素字段 | 默认与约束 |
| --- | --- |
| model | 必填；1–128，字母数字及 `_ . : / -` |
| provider | 必填；mock / openai / local / ollama |
| upstream_model | mock-echo；1–128 字符 |
| enabled | true |
| fallback_model | null；启用、不同、无后继的终点别名 |

## 10. 运维指标与日志

```bash
curl -sS http://127.0.0.1:8101/metrics
```

返回 JSON，不是 Prometheus 文本。scope=single_process；请求完成后记录计数与延迟。
requests_total、failures_total、cancelled_total 按固定路由聚合，未知路径为 other。
失败包括 HTTP 4xx/5xx 和已返回 200 的 SSE error，取消另计。
active_requests 包含正在抓取 metrics 的请求；因此它可能为 1，而当前抓取尚未计入请求总数。
延迟桶为 10/50/100/250/500/1000/5000/20000/60000 ms 和 +Inf，值为累计计数。
指标耗时覆盖 HTTP/stream 整个生命周期；与 ChatResponse.latency_ms 的起点不同。
日志包含请求标识、固定路由、状态、耗时、流错误和取消，不记录 Prompt、Key 或上游正文。
所有状态重启清零；没有 Redis、外部指标后端或跨副本聚合。

## 11. Benchmark 与离线报告

| 实验 | 检查内容 |
| --- | --- |
| A | 固定延迟 Mock 的直连/网关开销 |
| B | 503、429、读取超时、连接失败及恢复策略 |
| C | 重复率 0/50/90% 的缓存关闭/开启对照 |
| D | 固定任务的模型路由；Mock 只测协议，不给模型准确率 |
| E | 真实 SSE 首块/端到端耗时、原生生成速度；Mock 只测流协议 |

```bash
make benchmark-mock-quick
make benchmark-mock
# 已有 Ollama 与对应模型时才执行以下真实推理命令：
make benchmark-real
make benchmark-cache-real
```

`python -m benchmarks.run` 支持 --mode mock|real、--config JSON路径、--ollama-url。
`python -m benchmarks.real_cache` 只支持 --ollama-url，专门运行真实缓存对照。
配置 JSON 是运行协议，Mock 与真实配置分别读取以下项；没有通用配置热更新：

| 配置项 | mock.json / quick.json | real.json |
| --- | --- | --- |
| seed | 42 / 42 | 42 |
| repeats | 3 / 1 | 2 |
| requests | 100 / 50 | 4，真实 SSE 每组热态请求数 |
| concurrency | [1,5,20,50] | [1,2]，只允许 [1] 或 [1,2] |
| delay_ms | 20 / 5 | 不使用 |
| cache_repeat_rates | [0,0.5,0.9] | 真实缓存协议固定该三组 |
| models | 不使用 | 必须恰为 qwen2.5:0.5b 与 qwen2.5:1.5b |
| context_length | 不使用 | 必须 1024 |
| max_tokens | 不读取此键 | 文件记录为 64；实际 payload() 固定 64，单改此键不会改变输出上限 |
| gpu_stop_ratio | 不使用 | 0.9，整卡显存达到阈值时停止继续发起请求 |
| min_available_memory_mib | 不使用 | 1024，低于阈值时停止 |

真实缓存子实验另固定每组 10 条、并发 1、max_tokens=16、context=1024。资源守卫是阈值检查，不是系统资源隔离。
原始文件写到新的 `benchmarks/results/<run_id>/`，默认被忽略；包含 manifest、源码快照、请求 CSV/JSONL、summary、variability、comparisons 和资源采样。
冷启动指进程或模型未驻留，不是清空 OS 页缓存；并发不等于模型实际并行。

```bash
# 重建会扫描本地所有完整 run，并重写现有 HTML，先确认要纳入哪些数据。
make benchmark-report
.venv/bin/python -m http.server 8080 --bind 127.0.0.1
# http://127.0.0.1:8080/benchmarks/reports/index.html
```

报告按 mode/experiment 选择最新观测，包含被 Git 忽略的本地完整 run，不自动等同于公开原始数据。
`python -m scripts.verify_benchmark_results` 重算并检查已完成 method_version=2 的原始记录，不改写它们。
`python -m scripts.update_benchmark_docs` 挑选最新完整 Mock/真实 run，更新结果文档并给 .gitignore 增加对应结果目录的例外；它不会代替原始数据的发布审阅。
截图是可选步骤，会更新 docs/images，不属于默认安装或 CI 的必要前置：

```bash
uv sync --frozen --extra dev --extra screenshots
PLAYWRIGHT_BROWSERS_PATH="$PWD/.venv/playwright-browsers" .venv/bin/python -m playwright install chromium
make benchmark-screenshot
```

浏览器还需要运行系统的共享库和中文字体；项目不会自动安装系统包。截图脚本支持在 `.venv/browser-libs/` 下准备用户态库和字体。

## 12. Docker、检查与排错

```bash
cp -n .env.example .env
PORT=8101 docker compose up --build -d --wait
curl -sS http://127.0.0.1:8101/health
.venv/bin/python -m scripts.smoke_test --base-url http://127.0.0.1:8101
PORT=8101 docker compose down
```

容器内部端口固定 8000，PORT 只改变宿主映射。镜像只复制 app 与运行依赖，不包含校园 examples 或 benchmark 脚本；这些演示在源码目录运行。
容器使用 UID 10001、只读根文件系统、临时 /tmp、去 capabilities 和 no-new-privileges。
容器 localhost 指自身，不能直接用 localhost 访问宿主模型；Local/Ollama 的地址校验也不会因此放宽。
跨容器可达的 Chat Completions 服务需使用合适的 openai 配置及认证；Docker 不会代替安装模型。

```bash
make lint test
make docker-check
.venv/bin/python -m scripts.privacy_check
```

| 现象 | 检查步骤 |
| --- | --- |
| 启动提示 Task routes must target enabled model aliases | 更换模型后同步清理旧路由；环境与 .env 的字典项可能合并，核对每个目标别名 |
| 启动缺少 Gateway Key | 是否复制 .env.example；是否启用真实 Provider；Key 长度是否足够 |
| 401 | curl 的 shell 是否有 Key；与上游 Key 是否混用 |
| 404 模型不存在 | 查看 /v1/models；auto 必须有 task_type 和对应路由 |
| 缓存总是 bypass | 是否流请求；temperature 是否显式等于 0 |
| 缓存总是 miss | 消息/参数/模型映射是否变化；TTL 或容量是否已淘汰 |
| 429 | 区分 rate_limited 和 provider_rate_limited |
| SSE HTTP 200 但不完整 | 检查 error/done；代理是否缓冲；请求是否超时或取消 |
| 上游返回 502 | 协议、content-type、choices 或终止帧是否符合要求 |
| Ollama 很慢 | 检查模型驻留、上下文、加载 timing 与排队；不只看生成 tokens/s |
| demo_campus 直接脚本导入失败 | 使用 `python -m scripts.demo_campus` 或 make campus-demo |
| 地址已占用 | `make run PORT=其他端口`，同时修改客户端地址 |

## 13. 目录、链路与技术取舍

```text
app/
├── main.py                  App factory、lifespan、共享客户端与依赖组装
├── api/routes/              chat、models、health、metrics 路由
├── api/errors.py            JSON 错误和安全校验错误
├── core/config.py           配置及启动约束
├── core/security.py         Bearer 认证与限流 guard
├── core/trace.py            ContextVar 中的尝试预算、请求标识
├── core/logging.py          结构化日志
├── domain/                  Pydantic 契约和错误类型
├── providers/               协议、Mock、HTTP、Local、Ollama、Router
├── services/chat_service.py 截止时间、并发、缓存、回退与流事件
├── middleware/              请求标识、正文上限、滑动窗口
└── infra/                   TTL/LRU 缓存、进程指标
examples/                    普通请求、浏览器流示例和校园调用端
scripts/                     安装、smoke、演示、报告与隐私检查
benchmarks/
├── run.py / real.py         实验调度与真实模型路径
├── client.py / server.py    独立负载客户端和受控服务
├── metrics.py / verify.py   统计和行为核对
├── configs/ / data/         固定实验配置与任务
├── results/                 原始运行记录
└── report.py / reports/     HTML 生成器与离线产物
tests/                       单元、协议与真实 TCP 测试
docs/                        架构、协议、实验和操作说明
```

一次普通请求依次经过：ASGI 正文/ID 边界 → 认证与限流 → Pydantic → 别名路由 → 缓存检查 → 总预算内排队 → Provider → 可选回退 → 响应与指标。
流请求在校验别名后发送 start，再取得名额并逐块消费；资源清理由 aclosing、finally 和取消屏蔽共同完成。
Provider 协议隔离上游格式，Service 隔离调用策略，校园例子保留在调用端，避免把检索或政策处理塞进模型网关。
单进程内存结构让离线部署简单；代价是重启丢状态、无全局配额、无队列容量保证和无跨机审计存储。
项目没有透明兼容全部 OpenAI API，没有多模态、工具循环、统一计费平台或自动连接其他仓库的功能。
