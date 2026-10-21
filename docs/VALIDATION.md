# 实际验证记录

日期：2026-10-20（Asia/Shanghai）。所有开发在 Linux 项目目录内进行；未使用 Windows 路径或 PowerShell。

## 环境预检

按用户要求实际执行 `pwd`、`realpath .`、`uname -s`、`python3 --version`、`git --version`、
`gh --version`、`gh auth status`、`docker --version`，另检查 Node 和 Docker daemon。
父工作目录为空且不在其他 Git 仓库内，随后仅在 `./llm-gateway-service` 创建项目和初始化 Git。
机器绝对路径与认证配置不提交到公开仓库。

| 检查 | 实际结果 |
| --- | --- |
| OS | Linux |
| Python | 3.12.3 |
| Git | 2.43.0 |
| GitHub CLI | 2.45.0，认证账户 FouHe0720，另由 gh api user 确认 |
| Docker client/daemon | 29.8.2，daemon 可用 |
| Node | 24.21.0；本项目无需 Node 依赖 |
| 标准 venv | 缺少 ensurepip，未执行 sudo；改用环境已有 uv 0.12.24 |
| 项目依赖 | 项目 .venv，uv.lock 固定版本；runtime/dev requirements 导出供 pip/Docker 使用 |

## 阶段验收

| 阶段 | 实际测试 | 结果 |
| --- | --- | --- |
| V0 | pytest + Ruff | 7 passed；Mock Chat/health/models、参数与未知模型 |
| V1 | pytest + Ruff | 30 passed；HTTP adapter、重试、SSE/usage/断流、生成器关闭 |
| V2 | pytest + Ruff | 61 passed；鉴权/限流/日志/指标、真实 TCP 故障/取消、并发与截止时间 |
| V2 容器 | docker build、build --check、compose config、容器 smoke | 成功；health/models/chat/SSE/404/422/metrics；健康状态 healthy |
| V3 | install、Quick Start/curl、OpenAPI、pytest/Ruff | 62 passed；新增启动校验隐藏凭据的回归测试；命令实跑通过 |
| V2 运行边界 | inspect + 只读运行 | User=10001:10001、read-only、cap-drop ALL、no-new-privileges |

`make demo` 已实际启动临时 localhost 服务并逐块读取 SSE，验证完成后退出。
真实 TCP 流测试没有用完整字符串切片证明流式：上游第二块被 Event 阻塞时客户端已收到第一块；
随后断开并检查上游清理、并发名额和取消指标。

## 解释结果

- Mock 是确定性回显，usage=null；本地故障 Server 是测试 fixture，不是真实模型推理。
- 没有提供真实 Provider Key，没有调用 OpenAI/第三方付费 API，没有下载权重，没有运行 Ollama/vLLM。
- 没有做性能基准、模型质量评测或多副本验证。响应中的 latency 是单次测量值，不代表性能承诺。
- Docker 实际构建运行过；[首轮远端 CI](https://github.com/FouHe0720/llm-gateway-service/actions/runs/39436032137)
  在提交 `49bd916` 上全部成功：Python 3.11/3.12/3.13 各 62 passed，Ruff/Mock Demo/隐私扫描通过，
  Docker Compose 构建、健康检查和 Chat 请求通过。未将跨版本测试数相加当作不同用例数。
- 根据首轮 Actions 的 Node 20 弃用提示，更新至 checkout v7.0.1/setup-python v7.0.0 并固定 SHA；
  官方 release/API 已核对。Runner 固定为 Ubuntu 24.04，避免 ubuntu-latest 镜像迁移影响复现。
- 隐私检查会审阅 Git index、忽略规则和公开连接配置，启发式扫描不能代替人工审阅。

## 可重复命令

```bash
make install
make lint test demo
.venv/bin/python -m scripts.privacy_check
docker compose config --quiet
docker build --check .
docker compose up --build -d --wait
make smoke
docker compose down
```

README/DEMO 的持续服务命令需要先复制 `.env.example` 为 `.env`。

## 2026-10-21 Serving / Benchmark 扩展

环境再次审计：Ubuntu 24.04.5 WSL2，Ryzen 7 6800H（16 逻辑 CPU），WSL 可见约 7.4GiB RAM，
RTX 3050 Laptop 4096MiB VRAM。初始 Ollama 已安装但未启动，指定 Qwen2.5 模型缺失；
通过现有官方 CLI 下载 0.5B/1.5B，实际启动本地服务，限制一次驻留一个模型、并行 1、context 1024。
没有运行 3B、训练、付费 API 或安装系统包。

新增缓存/Fallback/任务路由、原生 Ollama、统计与数据集测试后，本地 **78 passed**，Ruff 通过。
Mock/真实运行的全部数字与限制见 [BENCHMARK.md](BENCHMARK.md) 和 [FAILURE_ANALYSIS.md](FAILURE_ANALYSIS.md)。
通过 `scripts/verify_benchmark_results.py` 从逐请求记录重新计算统计，并校验源码快照和数据集 SHA。
