# 实施计划

顺序：V0 → V1 → V2 → V3。每阶段验证通过后独立提交；仅在项目目录初始化 Git。

| 阶段 | 交付 | 完成条件 |
| --- | --- | --- |
| V0 | pyproject、分层 FastAPI、Mock chat、models、health、基本测试 | 项目 venv 安装成功、Mock API 测试和 Ruff 通过 |
| V1 | Provider 协议、HTTP/Local adapter、Router、真实 SSE、超时与重试 | 本地故障注入覆盖 HTTP/429/timeout/stream/cancel，无外部 Key |
| V2 | 鉴权、单进程限流、request ID、安全日志、指标、Docker/CI | 正反向接口和真实 TCP 取消测试、格式与静态检查通过 |
| V3 | 中文文档、示例、一键 Demo、隐私检查、公开发布 | Quick Start 实跑、验证记录、分阶段提交、确认账户后普通推送 |

文件结构：`app/{api/routes,core,domain,providers,services,middleware,infra}`；
`tests/`、`scripts/`、`examples/`、`docs/`、`.github/workflows/`。

技术边界：仅 Chat Completions 文本子集；单进程内存限流/指标；Mock usage 不估算；
真实 API 和 GPU 模型不作为验收前提。流输出后禁止重放。未验证的能力如实记录。
