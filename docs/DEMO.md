# 逐条演示

以下命令在仓库根目录的 WSL/Linux bash 执行。默认演示不需要真实 API。

## 自动演示

```bash
make install
make demo
make lint test
```

Demo 启动临时端口，校验 health/models/chat/SSE/404/422/metrics 后退出。
成功末行：`Mock smoke passed: health, models, chat, SSE, 404, 422, metrics`。

## 持续服务与 curl

```bash
cp -n .env.example .env
make run
```

另开终端，在同一项目目录逐条执行：

```bash
curl -sS http://127.0.0.1:8000/health
curl -sS http://127.0.0.1:8000/v1/models
curl -sS -D - http://127.0.0.1:8000/v1/chat \
  -H 'Content-Type: application/json' -H 'X-Request-ID: interview-demo' \
  --data-binary @examples/chat.json
curl -N http://127.0.0.1:8000/v1/chat/stream \
  -H 'Content-Type: application/json' --data-binary @examples/chat.json
curl -sS -i http://127.0.0.1:8000/v1/chat \
  -H 'Content-Type: application/json' --data-binary @examples/unknown_model.json
curl -sS -i http://127.0.0.1:8000/v1/chat \
  -H 'Content-Type: application/json' --data-binary @examples/invalid_messages.json
curl -sS http://127.0.0.1:8000/metrics
make smoke
```

应观察到：普通响应 `[mock] Hello Gateway`，header 和 body 的 request ID 一致；
流按 start/delta/done 到达，start.simulated=true，done.usage=null；错误分别为 404/422。
latency 和自动生成的 request ID 以当前运行值为准，不作为性能基准。

## 浏览器逐块消费

先打开本机 `http://127.0.0.1:8000/docs`，在浏览器控制台粘贴 [stream_fetch.js](../examples/stream_fetch.js)。
脚本使用 fetch 的 ReadableStream，因为原生 EventSource 不支持 POST body；无需配置 CORS。
它只适用于上述无鉴权 Mock 演示，生产客户端需要按自己的方式安全传入 Gateway Bearer Key。

## 鉴权与限流

停止之前的 make run，在私有 `.env` 中设置开启鉴权，或下面只使用公开 fixture Key 做本机演示：

```bash
GATEWAY_AUTH_ENABLED=true \
GATEWAY_API_KEY=fixture-key-for-local-demo \
GATEWAY_RATE_LIMIT_REQUESTS=2 \
make run
```

新终端：

```bash
curl -sS -i http://127.0.0.1:8000/v1/models -H 'Authorization: Bearer wrong'
for i in 1 2 3; do
  curl -sS -i http://127.0.0.1:8000/v1/models \
    -H 'Authorization: Bearer fixture-key-for-local-demo'
done
```

分别得到 401，以及 200/200/429；429 包含 Retry-After。
这是公开演示 fixture，不能用作真实部署 Key。

## 故障、取消和并发验证

```bash
.venv/bin/python -m pytest -q tests/test_retry.py tests/test_http_integration.py tests/test_service.py
```

测试启动 localhost 故障 HTTP Server，注入 503/429/401、读取超时；计数确认最多 3 次尝试、
401/读取超时不重放。真实 TCP SSE 测试阻塞第二块，验证第一块已被客户端消费，然后断开，
检查上游 finally 执行、Semaphore 可再次获取、cancelled 指标。无需实际模型和外部 Key。

## Docker

```bash
docker compose config --quiet
docker build --check .
docker compose up --build -d --wait
docker compose ps
make smoke
docker compose exec gateway id
docker compose down
```

先停止占用 8000 的 make run；也可 `PORT=8001 docker compose up --build -d --wait`，
再 `bash scripts/smoke_test.sh --base-url http://127.0.0.1:8001`。
`id` 应显示 uid=10001；健康状态 healthy。`.env` 仅供容器运行时载入，不进入构建上下文。
