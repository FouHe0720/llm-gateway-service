# 验证记录

## 2026-10-23：校园调用端与回归

| 检查 | 结果 |
| --- | --- |
| `make lint test` | Ruff lint/format 通过；89 项 pytest 通过 |
| `make demo` | 临时 TCP 服务的 health、models、chat、SSE、404、422、metrics 检查通过 |
| `make campus-demo` | 首次 miss、重复 hit、更换证据 miss、模型别名 404、缺少 2026 年资料时提前拒绝 |
| 来源校验 | 文件指纹、段落一致性、资料版本、校区与证据预算检查通过 |
| 缓存与费用 | 资料修订后旧缓存不复用；缓存响应的历史 usage 不重复计入推理费用 |

校园示例通过真实 FastAPI lifespan 与 ASGI HTTP 客户端调用，Provider 固定为 Mock。Mock 回显请求，没有测试模型答案或生产费用。报告写入忽略的 `runtime/campus-demo.json`。

TCP 流测试使用 Event 阻塞第二块，确认客户端已收到第一块，再主动断开并核对上游清理和并发名额恢复。ASGI 客户端的缓冲响应不用于证明网络流的增量性。

本轮没有重跑真实模型推理、Docker 或远端 CI。缓存保留原始 usage 的通用接口语义不变，校园调用端根据 cache_hit 标记跳过历史 token 的重复费用计算。

## 2026-10-21：固定协议实验

环境：WSL2 / Ubuntu 24.04，Ryzen 7 6800H，RTX 3050 Laptop 4 GB，Ollama 0.34.4。一次驻留一个模型，模型端并行 1、context 1024。实验时本地 78 项测试与 Ruff 通过。

| 原始记录 | 请求数 | 内容 |
| --- | ---: | --- |
| `20261021T053001Z-mock-33f3d4` | 8,031 | Mock 开销、故障恢复和缓存对照 |
| `20261021T054417Z-real-bdb4f7` | 308 | Qwen2.5 0.5B/1.5B 路由、SSE 与缓存对照 |

已核对这两份已跟踪结果：JSONL 与 CSV 请求一致，数据集及源码快照指纹正确，从逐请求数据重新计算的 summary/comparisons 与保存值一致。已发布 HTML 中的 manifest、summary、comparisons、variability 与 GPU 采样也与对应原始文件一致。

README 与 [BENCHMARK_RESULTS](BENCHMARK_RESULTS.md) 的数字来自上述 10 月 21 日记录。实验规模、冷热定义、统计口径和限制见 [BENCHMARK](BENCHMARK.md)，结果解释见 [FAILURE_ANALYSIS](FAILURE_ANALYSIS.md)。新增校园调用端没有混入这组实验。

报告工作台在 1440 × 1200 桌面和 390 × 844 移动视口下无整页横向溢出或 JavaScript 异常。A–E 五个页签和真实数据筛选均可操作。

## 容器与 CI 历史记录

2026-10-20 已运行 Docker build、Compose 配置检查、容器健康检查与 smoke；容器使用 UID 10001、只读根文件系统、cap-drop ALL 和 no-new-privileges。

[首次远端 CI](https://github.com/FouHe0720/llm-gateway-service/actions/runs/39436032137) 在提交 `49bd916` 上通过 Python 3.11/3.12/3.13、Ruff、Mock Demo、隐私扫描与 Docker Compose 检查，每个 Python 版本执行 62 项测试。后续状态以实际 workflow 为准，历史成功不代表当前提交已经运行远端检查。

## 可重复命令

```bash
make install
make lint test demo campus-demo
.venv/bin/python -m scripts.privacy_check
```

容器检查需要可用 Docker daemon：

```bash
cp -n .env.example .env
docker compose config --quiet
docker build --check .
docker compose up --build -d --wait
make smoke
docker compose down
```

隐私脚本审阅索引文件与忽略规则；启发式扫描不能代替来源、暂存差异和配置的人工检查。
