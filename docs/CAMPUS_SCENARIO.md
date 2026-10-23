# 校园咨询调用端

这是一个 RAG 完成检索之后的网关调用示例。领域处理在 `examples/campus_client.py`，不放入 ChatService；通用 API、Ollama 接入、SSE 和已有实验保持共用。

## 使用的资料

`examples/campus/manifest.json` 和 `corpus/` 是用户现有 RAG 知识库中 8 份文档的历史摘录，涵盖 2024 年选课、英语分级、三个实验班招生，以及计算机/人工智能 2024 版和物理学 2023 级培养方案。

manifest 记录原文相对路径、原 DOCX SHA-256、摘录 SHA-256、年份和原始段落号。段落号来自所有 `w:p` 的一基位置，含空段及表格段，不是页码。2024 版计算机/人工智能培养方案未写明适用年级，cohort 为 null。

构建请求先校验 Markdown 的 SHA-256，再核对 manifest 中的段落与摘录一致。代码将来源内容与元数据计算为快照指纹，并写入 Prompt；因此相同问题换资料、原文修订或来源变化都会改变请求缓存键。指纹用于版本追踪和完整性检查，不构成原文真实性认证；原始文件的指纹由本地资料整理时记录。

只发布必要摘录，没有整库 DOCX、个人电话、邮箱、名单或账号。原文权利归原作者，MIT 代码许可不覆盖学校资料。历史资料不代表现行政策；这个项目不声称由学校运营。

## 调用流程

```python
from examples.campus_client import build_campus_request

bundle = build_campus_request(
    "2024级新生选课时间是什么？",
    ["course-selection-2024"],
    year=2024,
    model="mock-echo",
)
# 向网关 POST /v1/chat 提交 bundle.request.model_dump()
```

source_ids 来自上游检索结果，不是这个示例自动检索出来的。year 表示请求明确使用的资料版本，不能依赖模型自行判定年份；调用端仍需正确提取用户意图。缺来源、重复来源、校区/版本不符、摘录被改或证据超预算都在模型调用前拒绝。

Prompt 保留资料来源、年份和段号，并要求证据不足时说明无法确认。它要求保留原文的例外和歧义，例如翻译学院不在统一英语分级测试范围，智能导航报名时间原文“中午14点”不擅自改成 12 点。这是调用约束，没有运行真实模型证明其遵从程度。

默认证据上限 6,000 个字符、max_tokens=256。字符数是调用端上下文预算，不是 tokenizer 统计，也不用于估算 token 或账单。网关本身另有 body/总消息字符上限。

`observed_cost` 只在 usage 完整且调用方明确提供输入/输出每百万 token 价格时计算，单位由价格币种决定。没有根据模型名自动猜价格。网关的缓存响应仅保留答案，本次 usage 与 timing 为 null；调用 `observed_cost` 时仍应透传 `cache_hit=metadata.cache_status == "hit"`，明确区分缓存命中和新推理。该函数对缓存命中返回 null，避免把同一份历史 token 重复算成新的推理费用；Mock 或未报 usage 时也保持 null。即使某次响应为零次上游尝试，null 也不能直接改写为零费用。

## 离线演示与测试

```bash
make campus-demo
.venv/bin/python -m pytest tests/test_campus_client.py -q
```

演示使用真实 FastAPI lifespan 和 ASGI HTTP 客户端，Provider 强制为 Mock，不读取实际 `.env` 配置。输出六种请求的缓存、错误与来源快照到 `runtime/campus-demo.json`；其中更换证据演示使用同一问题添加另一个来源，仅为验证缓存键，不能当作检索质量实验。

测试另外构造一次摘录修订，更新校验信息后再次请求，验证旧缓存不会复用。错误文件和不一致的段落清单会被拒绝。现有 TCP 测试继续验证真正的 SSE 增量与断连取消；校园演示的 ASGI 客户端不用于证明流式性能。

本次未调用真实 LLM，没有校园问答准确率、延迟收益或实际费用结论。现有 benchmark 数字使用另一组固定通用任务，两者不能混合解释。
