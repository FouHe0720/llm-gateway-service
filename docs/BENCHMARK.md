# 可复现实验 A–E

所有结果来自 `benchmarks/results/<run-id>/`，报告在 `benchmarks/reports/index.html`。
实验脚本只允许 localhost；无付费 API、无训练、无 3B 必选前置。模型权重位于 Ollama 自身目录，
不进入本仓库。每个运行保存实际环境、参数、模型 digest、任务 SHA、源码快照和原始结果。

## 一键运行

```bash
make install
make benchmark-mock-quick  # CI / 流程检查，一轮、每组 50 个请求
make benchmark-mock        # 三轮、每组 100 个请求、20ms 配置延迟
make benchmark-report     # 从已有原始结果重建离线 HTML
```

Mock 通过真实 TCP 的独立客户端/Gateway/上游进程执行。报告区分 `simulated` / `real`，
没有真实模型数据时，准确率/生成 Tokens/s/GPU 显示“未测试”。不将模拟回答当作模型质量。

真实模型先在另一个终端启动已有 Ollama（已有服务运行时不要重复启动）：

```bash
bash scripts/serve_ollama.sh
# 新终端：只从官方 Ollama registry 下载；不使用第三方安装脚本。
ollama pull qwen2.5:0.5b
ollama pull qwen2.5:1.5b
make benchmark-real
```

Ollama 尚未安装时，先阅读 [官方 Linux 安装说明](https://docs.ollama.com/linux)，
官方安装脚本地址为 `https://ollama.com/install.sh`。需要系统安装/sudo 时由用户决定；本次环境已有
Ollama 0.34.4，未执行系统安装。网络失败需记录原始错误并重试官方来源，不切换未知镜像脚本。

## A：纯网关开销

同一个固定延迟 HTTP Mock，使用相同文本、temperature=0、seed=42、max_tokens=64。
并发 1/5/20/50；直连上游与经过 Gateway 两组。缓存关闭，重试关闭，Gateway 上游并发设为 64，
入站限流提升至实验专用阈值。每轮交替两组先后顺序，记录首请求冷样本，连接池预热后记录热样本。
这是闭环固定并发实验，客户端连接池容量不小于目标并发。

`comparisons.csv` 中额外开销 = 同轮/阶段/并发 Gateway P50/P95 − Direct P50/P95。
这是两个分位数的差，不能称为“逐请求额外耗时的 P95”。负数也原样保留，不删异常或只选最好一轮。

## B：故障注入与恢复

无恢复 / Retry（最多额外 2 次）/ Retry + 单跳 Fallback。
503/429：逻辑编号能被 5 整除时，首次请求故障，后续成功；读取超时：相同编号始终延迟超过读超时；
连接失败：主地址在保留但未 listen 的 localhost socket 上，拒绝所有主请求，避免伪装 HTTP 错误。
Fallback 指向显式配置的健康备用模型。所有故障脚本固定，不依赖并发完成顺序的随机数。

读取超时不会自动重试；配置 fallback 时允许调用备用服务，这仍可能造成主上游继续执行。
流发送 start 后不重试、不 fallback。最多 6 次总传输尝试，且整个过程共用总截止时间；
本实验主服务最多 3 次、健康备用服务 1 次。永久上游 4xx 不触发 fallback。

请求级 metadata 记录尝试/重试/回退，HTTP fixture 的独立 `/stats` 台账用于核对收到的请求。
连接建立失败无法在服务器计数，报告中的 attempts 表示客户端发起的尝试，台账单独保留实际接收数。
重试次数不等于尝试次数减一：fallback 的首次调用也是新 attempt，但不计 retry。

## C：缓存

请求重复率 0/50/90%，固定种子、精确唯一条数，关闭/开启缓存使用相同请求序列。
每组串行调用避免把并发合并请求收益混入缓存命中；本实现没有 single-flight。

缓存是进程内 TTL + LRU，默认关闭，默认 60s、128 条、2MiB 答案与键字节预算（Python 对象额外开销
另受条数约束）。只有显式 temperature=0 的非流式请求可缓存；完整消息、模型别名和所有生成参数进入
SHA-256 key，原始 prompt 不作为日志/指标标签。重启清空；读取和插入时检查过期；超预算逐出。
不缓存错误或 fallback 回答。命中返回新 request ID，usage/timing=null、attempts=0，避免冒充新推理。
这是单个 Gateway 凭据下的共享缓存，尚无多租户隔离与分布式一致性。

调用节省比例 = 1 − 缓存组实际上游调用数 / 同工作负载关闭缓存的调用数。
在本实验每个无缓存请求恰好调用一次且没有错误，因此也等于 1 − attempts/N；以独立台账复核。

## D：多模型路由

`benchmarks/data/tasks.json` 在模型评测前固定：18 题，各 6 道提取、算术、推理题，均为自建公开任务。
其 SHA-256 为 `23a47ad358b1cba636050817036f08bb5cf9ec67772e9e76d54c974526cf4f6e`。
不按模型回答修改题目、答案、分组或评分规则，不使用 LLM judge。

策略：全部 0.5B、全部 1.5B、任务路由（提取/算术→0.5B，推理→1.5B）。任务类型由调用方提供，
不是本项目训练了语义分类器。每轮相同种子的任务顺序用于三种策略；比较策略整体结果，另保留逐题预测。
评分只 trim 空白 + casefold 后 exact match；失败算错，不去掉模型的解释前缀或标点来提高准确率。

每次策略开始卸载本实验模型。调用前查 `/api/ps`：目标未驻留记 cold，已驻留记 warm；
4GB 下一次最多驻留一个模型，路由切换可能反复加载，是策略的实际成本，不能当作全部模型常驻。
报告整体准确率、正确完成任务的平均耗时、模型加载时间和冷热占比。冷/热子集的题型构成可能不同，
不能直接把子集准确率差当作冷启动导致质量变化。

## E：真实模型性能与资源限制

默认 Qwen2.5 0.5B/1.5B Q4_K_M；记录实际模型 digest/大小和 Ollama 版本。
使用原生 `/api/chat`，Gateway 把 NDJSON 转为 SSE，同时保留 usage 和纳秒 timing。
直接调用与 Gateway 使用同样的 prompt、seed=42、temperature=0、num_ctx=1024、num_predict=64、keep_alive=2m。
每轮交替组别顺序，每组先确认模型卸载再记录一条 cold，随后采集热请求。
默认两轮、每组 4 条热请求，客户端并发从 1 到 2；这是小批量检查，P95 在小样本下可能就是最大值。
Ollama 服务并行固定为 1，因此客户端并发 2 主要测排队，不宣称双路 GPU 并行推理。

TTFT = 客户端收到首个非空文本块 − 发出请求；SSE start 不计入。
生成速度 = Ollama eval_count / eval_duration × 1e9，缺失就 null；
它排除排队和 prompt prefill。端到端输出吞吐 = 成功请求输出 token 总数 / 实验跨度，另行保存。
时间单位以 Ollama 官方返回的纳秒为准，不用字符数估 token。

每个组开始前检查 RAM/显存，默认可用内存至少 1024MiB、整卡显存占用低于 90%。
不同时加载两个模型；服务无空闲显存或冷请求失败时停止升级并发，保留失败/跳过原因。
采样整张 GPU 的使用量/利用率，约 500ms 一次，包含 Windows/其他进程且可能漏掉瞬时峰值；
不能把采样峰值称作模型精确显存。资源不足时先仅并发 1、减少输出和热请求数，再改协议进行 512 context
的单独匹配对照；当前固定协议拒绝偷偷改变一组 context。

## 统计口径与文件

- 成功率 = 正确完成协议的请求数/N，包含失败/超时为分母；D 正确率单独计算，不能用 HTTP 200 替代。
- p50/p95 = nearest-rank，排序后 ceil(p×N) 项；输出所有请求延迟，并额外提供成功请求 P95。
- QPS = 成功完成数 / (最后完成时间 − 首个发出时间)，含组内收尾，非理论服务容量。
- 三轮 Mock / 两轮真实保留逐轮结果，`variability.json` 记录中位数、范围、标准差；不把多轮误当独立任务数。
- 冷启动不清操作系统页缓存，也不重启 Windows/GPU，不能宣称硬件完全冷机。

| 文件 | 内容 |
| --- | --- |
| manifest.json | 时间、硬件、配置、模型 digest、源码/任务指纹、跳过和状态 |
| source_snapshot.json | 运行时实际源码与配置，支持 dirty tree 时核查 |
| requests.jsonl / requests.csv | 逐请求耗时、结果、元信息、公开任务预测 |
| fixture_ledgers.json | Mock 上游收到请求的独立计数与故障事件 |
| summary.json / summary.csv | 分场景/策略/并发/轮次/冷热结果，all 是同一数据的整体视图，勿重复累加 |
| comparisons.json / comparisons.csv | Direct/Gateway 同组分位数差和 QPS 比例 |
| variability.json | 多轮波动 |
| resources.csv | Gateway CPU/RSS 与真实模型 GPU 采样 |

## 报告与截图

HTML 完全离线，图表/数据内嵌，不依赖 CDN。可直接打开，或在项目根目录运行：

```bash
.venv/bin/python -m http.server 8080 --bind 127.0.0.1
# 浏览器打开 http://127.0.0.1:8080/benchmarks/reports/index.html
```

真实浏览器截图使用可选 Playwright，不是图片生成工具绘制的示意图：

```bash
uv sync --frozen --extra dev --extra screenshots
PLAYWRIGHT_BROWSERS_PATH=.venv/playwright-browsers .venv/bin/python -m playwright install chromium --only-shell
make benchmark-screenshot
```

本机缺少 libnspr4/libnss3，实际从 Ubuntu 官方 apt 来源下载 deb 并仅解包到 `.venv/browser-libs`，
没有系统安装。缺少中文字体时同样使用项目内字体。截图脚本只打开本地报告并关闭浏览器联网。

实验结论与失败案例见 `docs/FAILURE_ANALYSIS.md` 与 README 的实测结果段落。

## 真实缓存补充实验

`make benchmark-real` 在 D/E 完成后继续运行 0.5B 原生缓存实验；也可单独 `make benchmark-cache-real`。
每个重复率 10 条请求、并发 1、两轮、输出上限 16，关闭/开启组使用相同内容和参数。
每组先卸载 0.5B，记录一条 cold；其余请求 warm。比对返回的真实 usage 与 attempt 计数，
确保成功 miss 的推理调用有 Ollama token 记录，而 hit 不产生新的 token/usage。
这是小规模调用节省验证，不以它估计生产 QPS；组间/请求间的显存保护检查会影响整体实验跨度。

## 实验台版本与旧记录

正式结果使用 method_version=2。开发期 v1 使用 Uvicorn `fd=` 接口传递已监听的 TCP socket；
本机安装版本在该分支使用 `socket.fromfd(..., AF_UNIX, ...)`。检查发现这会改变传输层的 family
元信息及 TCP_NODELAY 设置路径，开发期出现约数十毫秒的额外延迟。
已改为保留实际 AF_INET socket、显式 TCP_NODELAY、通过 `serve(sockets=[...])` 启动子进程，
补充连接池预热后重新采集。旧记录保留在本地作为诊断，未用于正式 README 结论。

并发 50 大于 httpx 默认 20 条 keep-alive 保留数，连接预热不等于全部连接永久驻留；
此项配置是本次测量的一部分。后续可针对 keep-alive 上限做独立实验，不把当前高并发结果解释为纯 CPU 开销。
