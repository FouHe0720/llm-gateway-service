# LLM Gateway Service

[![CI](https://github.com/FouHe0720/llm-gateway-service/actions/workflows/ci.yml/badge.svg)](https://github.com/FouHe0720/llm-gateway-service/actions/workflows/ci.yml)

一个可独立运行的异步 Python LLM 网关：统一文本对话、SSE、模型路由、鉴权、限流和可观测性。
面向多个客户端需要接入不同 OpenAI-compatible 服务的场景，把连接管理、错误边界和调用策略放在服务端。
默认 Mock 无需 API Key、GPU、模型下载或付费服务；安装依赖需要访问 PyPI，安装后 Mock 可断网运行。

**English overview:** An asynchronous FastAPI gateway for deterministic Mock and OpenAI-compatible
text models. Includes incremental SSE, cancellation, bounded retries/concurrency, Bearer authentication,
process-local rate limiting, optional TTL/LRU caching and bounded fallback. Includes reproducible
Mock and real Ollama benchmarks with raw data, cold/warm metrics and an offline dashboard.

## 能力与架构

- `BaseLLMProvider` 协议统一 Mock、OpenAI-compatible、Local 和原生 Ollama；保留真实 token/timing 元信息。
- 可选 TTL/LRU 缓存、单跳 Fallback 和按 task_type 的配置路由；默认关闭，尝试次数和总耗时均有上限。
- `httpx.AsyncClient` 生命周期连接池；区分连接/读取超时，总截止时间涵盖排队和退避。
- 真正增量读取上游 SSE；Mock 明确标注模拟分块；断开连接会取消流并关闭上游连接。
- Bearer Key 常量时间比较、单进程滑动窗口限流、安全 request ID、统一 JSON 错误。
- 固定路由标签的请求/失败/取消计数、延迟累计桶；日志不输出 prompt、Key、上游响应正文或 URL。

```mermaid
flowchart LR
    C[HTTP client] --> M[ASGI request ID / body limit / logs / metrics]
    M --> A[FastAPI validation / auth / rate limit]
    A --> S[ChatService deadline / semaphore / SSE]
    S --> CA[Optional TTL/LRU cache]
    S --> R[ProviderRouter / task routes]
    R --> F[Optional single-hop fallback]
    R --> P[BaseLLMProvider protocol]
    P --> K[MockProvider: deterministic echo]
    P --> O[OpenAICompatibleProvider: async HTTP]
    P --> L[LocalProvider: same adapter, localhost only]
    P --> N[OllamaProvider: native NDJSON / timings]
    N --> Q[Qwen2.5 0.5B / 1.5B]
    O --> U[Configured Chat Completions endpoint]
    L --> V[User-managed Ollama / vLLM]
```

## Quick Start

Python **3.11+**，推荐 3.12；Linux/WSL bash。已安装 uv 时使用锁文件；否则需要可用的标准 venv/pip。
本次 WSL 缺少 ensurepip，实际用已有 uv 创建项目 `.venv`，没有安装系统包。

```bash
git clone https://github.com/FouHe0720/llm-gateway-service.git
cd llm-gateway-service
make install
make demo
```

`make demo` 自动在 localhost 空闲端口启动仅有 Mock 的实例，逐块打印 SSE，验证所有主要接口后退出，
不会读取 `.env` 中的真实模型配置。持续启动服务：

```bash
cp -n .env.example .env
make run
# 新终端，同一项目目录：
make smoke
```

默认地址 `http://127.0.0.1:8000`；Swagger UI：`http://127.0.0.1:8000/docs`。
`.env.example` 显式设置 development + Mock + `GATEWAY_AUTH_ENABLED=false`。
直接启动而没有这个配置时，应用默认要求 Gateway Key；不会悄悄关闭鉴权。

```bash
curl -sS http://127.0.0.1:8000/health
curl -sS http://127.0.0.1:8000/v1/models
curl -sS http://127.0.0.1:8000/metrics
curl -sS http://127.0.0.1:8000/v1/chat \
  -H 'Content-Type: application/json' -H 'X-Request-ID: example-chat' \
  --data-binary @examples/chat.json
curl -N http://127.0.0.1:8000/v1/chat/stream \
  -H 'Content-Type: application/json' --data-binary @examples/chat.json
```

Chat 示例结构（request ID / latency 为每次实际执行值，下例时间仅说明字段）：

```json
{"answer":"[mock] Hello Gateway","model":"mock-echo","request_id":"example-chat","usage":null,"latency_ms":0.1}
```

Mock 不计算 token、不执行真实推理；生成参数经过校验，但 Mock 回显不模拟采样和 token 截断。
`examples/` 是本项目自建的公开虚构样例，随 MIT License 分发。

## API 契约

| 接口 | 行为 |
| --- | --- |
| `POST /v1/chat` | answer / model（公开别名）/ request_id / usage / latency_ms / metadata |
| `POST /v1/chat/stream` | SSE `start → delta* → done`，发生故障以 `error` 终止 |
| `GET /v1/models` | 启用的 model/provider 映射与 simulated_stream，不暴露上游模型名、URL、Key |
| `GET /health` | 无需鉴权、无上游调用，仅返回 `{"status":"ok"}` |
| `GET /metrics` | 结构化 JSON；启用鉴权时需要 Key；不消耗 API 限流窗口 |
| `GET /docs`, `/openapi.json` | 公开 API 文档和成功/错误示例，不包含运行时配置 |

`messages` 1–100 条，仅 system/user/assistant；每条非空且最多 16000 字符，总计最多 32000 字符；
原始 HTTP body 默认上限 128 KiB。`temperature` 0–2，`top_p` >0 且 ≤1，`max_tokens` 整数 1–8192。
另外支持可选 seed，以及 model=auto + task_type（extract/arithmetic/reasoning）；需配置任务路由。
metadata 返回实际服务的公开别名、尝试/重试/回退/缓存/排队信息；Ollama 返回原生生成与加载 timing。
未知字段会拒绝。不是 OpenAI API 的逐字段透传接口，暂不支持工具调用、多模态和 Responses API。

错误格式：`{"error":{"code":"model_not_found","message":"Requested model is not enabled","request_id":"..."}}`。
401=入站鉴权失败；429 的 `rate_limited`=Gateway、`provider_rate_limited`=上游；
404=模型未知或禁用；422=输入不合法；413=body 过大；502=上游错误/协议错误；504=超时。
SSE 开始后的 HTTP status 已为 200，此后失败用 `error` 事件表示，不发送 `done`。
客户端必须检查终止事件；只收到部分 delta 不代表请求成功。每个事件均包含 request_id（error 位于 error 对象中）。
usage 只使用 Provider 返回值，缺失为 `null`，中断流不保证有 usage。

## 接入真实服务

仅在你准备好自建或第三方 endpoint 时手动启用；本项目没有预置私人地址和密钥。
修改私有 `.env` 并重启：

```dotenv
GATEWAY_AUTH_ENABLED=true
GATEWAY_ENVIRONMENT=production
GATEWAY_API_KEY=REPLACE_WITH_A_RANDOM_SECRET_AT_LEAST_16_CHARS
GATEWAY_MODELS='[{"model":"online-chat","provider":"openai","upstream_model":"YOUR_MODEL","enabled":true}]'
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=REPLACE_PRIVATELY
```

Base URL 应以 `/v1` 等 API 前缀结尾，适配器自动追加 `/chat/completions`。
普通请求只传显式设置的生成参数；流请求发送 `stream=true` 与 `stream_options.include_usage=true`。
第三方服务必须支持这一文本 SSE 子集，否则返回协议错误；没有隐式兼容性降级。
[OpenAI 官方流协议](https://developers.openai.com/api/reference/resources/chat/subresources/completions/streaming-events)
说明 usage 可在 choices 为空的最后一块返回；实现处理了这一情况。

请求时发送 `Authorization: Bearer <你的 Gateway Key>`。Gateway Key 与上游 Key 分开管理；
不要把上游 Key 发送给本服务客户端。可以在 `/docs` 的 Authorize 中填入 Gateway Key。

Local 示例（仍需开启 Gateway 鉴权）：

```dotenv
GATEWAY_MODELS='[{"model":"local-chat","provider":"local","upstream_model":"YOUR_INSTALLED_MODEL"}]'
LOCAL_BASE_URL=http://127.0.0.1:11434/v1
# LOCAL_API_KEY=仅在本地 endpoint 要求时设置
```

Local 是共享 HTTP adapter 的薄子类，配置仅允许 localhost/127.0.0.1/::1；不会安装 Ollama、启动模型或下载权重。
容器的 localhost 是容器自身；连接宿主机/其他容器 endpoint 时使用 `openai` provider 配置可达地址与 Key，
或在 WSL 本机运行 Gateway。已在 RTX 3050 4GB 上实测原生 Ollama Qwen2.5 0.5B/1.5B；
未调用付费 API 或运行 vLLM。原生配置见 `.env.example` 的 provider=ollama，用于保留模型 timing。

## 验证与容器

```bash
make install
make lint
make test
make demo
.venv/bin/python -m scripts.privacy_check
docker compose config --quiet
docker build --check .
docker compose up --build -d --wait
make smoke
docker compose down
```

截至 **2026-10-21**：本地 **77 passed**，Ruff check/format 通过；新版 Docker 镜像、
Compose healthy、非 root 和只读容器 API smoke 已实际通过。历史与当前验证见 [VALIDATION](docs/VALIDATION.md)。
CI 覆盖 Python 3.11/3.12/3.13、Docker，以及无需 GPU 的 Mock Benchmark，并上传数据/HTML artifact。

## 可核查的 A–E 实验

```bash
make benchmark-mock-quick  # 一轮流程检查，无 GPU/Key/模型依赖
make benchmark-mock       # 三轮 Mock A/B/C + D/E 契约验证
# 有本地 Ollama 与指定模型后：
make benchmark-real       # 两轮真实 D/E，随后真实 0.5B 缓存实验
make benchmark-report
.venv/bin/python -m scripts.verify_benchmark_results
```

配置和模型准备见 [BENCHMARK](docs/BENCHMARK.md)。实际记录：Mock **8,031 条**、
完整真实模型实验 **308 条**，分别保存 CSV/JSONL、冷热统计、波动、硬件/模型 digest、源码快照。
样本量为记录的请求数，预热/模型卸载/状态查询不混入推理请求数；18 道任务重复两轮仍只有 18 道独立题目。

| 实验 | 当前实测结论 |
| --- | --- |
| A 开销 | 并发 1 的热态配对 ΔP95 中位数 **3.05ms**；并发 20/50 波动明显，保留全部轮次与负值 |
| B 恢复 | 20% 首次 503/429：成功率 80%→100%；永久连接失败仅 Retry 仍为 0%，显式 Fallback 恢复 |
| C 缓存 | 真实 0.5B、10 条/组、90% 重复：模型调用 **10→1**；含冷启动 P95 未改善 |
| D 路由 | 严格匹配率：全 0.5B **22.2%**、全 1.5B **55.6%**、任务路由 **33.3%**；路由加载代价明显增加 |
| E 模型 | 两模型真实 GPU、SSE 并发 1→2 已跑通；TTFT/E2E/生成 tokens/s/显存均来自实测 |

[完整实测表](docs/BENCHMARK_RESULTS.md) · [失败与退化分析](docs/FAILURE_ANALYSIS.md) ·
[离线 Dashboard](benchmarks/reports/index.html) · [Mock 原始数据](benchmarks/results/20261021T053001Z-mock-33f3d4/) ·
[真实原始数据](benchmarks/results/20261021T054417Z-real-bdb4f7/)

Dashboard 可直接打开，或在仓库根目录执行：

```bash
.venv/bin/python -m http.server 8080 --bind 127.0.0.1
# http://127.0.0.1:8080/benchmarks/reports/index.html
```

以下为真实浏览器对该报告的截图，非示意数据：

![Benchmark overview](docs/images/benchmark-overview.png)
![Real model SSE comparison](docs/images/benchmark-e.png)
![Measured GPU memory](docs/images/benchmark-gpu.png)

上述结果仅描述当前笔记本和固定小样本协议，不用于宣称生产 QPS 或通用模型能力。
冷启动未清 OS 页缓存；真实推理服务器并行为 1，客户端并发 2 主要体现排队。

## 设计取舍与安全边界

- 默认最多额外重试两次，仅针对连接失败/连接超时/读取连接错误、429、500/502/503/504；指数退避 + full jitter。
  **不自动重试读取超时**，普通生成重试仍可能重复计费：上游接受 POST 后掉线，网关无法证明它没有执行。
  成本敏感场景设置 `UPSTREAM_MAX_RETRIES=0`。SSE 发送 start 后一律不重试。
- 总截止时间默认 60 秒，包括并发排队和退避；连接超时 3 秒、读取无数据超时 20 秒；上游并发上限默认 8。
  等待者没有单独队列长度上限，生产入口还需控制连接数和请求量。
- 限流为**整个实例共享**的 60 请求/60 秒滑动窗口，在认证后计算，Chat/Stream/Models 共用。
  不是按用户配额；多进程、多副本需 Redis/shared store，当前指标也需外部聚合，重启后清零。
- request ID 只接受 1–64 位字母/数字/点/下划线/连字符，否则重新生成；不作为指标标签。
  `/metrics` 的 active_requests 包含当前抓取请求，请求计数和延迟在请求完成后更新。
- 无 Key 的 Mock 只用于 localhost 开发。生产应使用 TLS、反向代理、密钥管理和网络访问控制。
  HTTP endpoint 可用于本地自建，公网应使用 HTTPS；关闭重定向，不从请求接收 URL，HTTP client 不读取代理环境变量。
  客户端断开只保证网关取消与关闭连接，远端模型是否停止推理由上游决定。

后续可扩展 Redis 配额、公平队列、OpenTelemetry、熔断、独立 readiness 和 Provider 能力声明；当前均未实现。
不包含持久化会话、计费系统、通用大规模模型评测或 GPU 训练。

## 导航

- [BENCHMARK](docs/BENCHMARK.md)、[BENCHMARK_RESULTS](docs/BENCHMARK_RESULTS.md)、[FAILURE_ANALYSIS](docs/FAILURE_ANALYSIS.md)
- [ARCHITECTURE](docs/ARCHITECTURE.md)：模块交互、错误与资源生命周期
- [DEMO](docs/DEMO.md)：可复制的正常/错误/流式演示
- [INTERVIEW_GUIDE](docs/INTERVIEW_GUIDE.md)：10 个基于实现的面试问答
- [RESUME_BULLETS](docs/RESUME_BULLETS.md)：不虚构指标的简历描述
- [TECH_DECISIONS](docs/TECH_DECISIONS.md)、[IMPLEMENTATION_PLAN](docs/IMPLEMENTATION_PLAN.md)

License: [MIT](LICENSE).
