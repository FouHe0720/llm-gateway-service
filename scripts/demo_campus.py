"""Exercise campus RAG requests through the real FastAPI app, offline Mock only."""

import asyncio
import json
from pathlib import Path

import httpx

from app.core.config import ModelMapping, Settings
from app.domain.schemas import Usage
from app.main import create_app
from examples.campus_client import EvidenceUnavailable, build_campus_request, observed_cost


async def main() -> None:
    app = create_app(
        Settings(
            _env_file=None,
            gateway_environment="development",
            gateway_auth_enabled=False,
            gateway_models=[ModelMapping(model="campus-mock", provider="mock")],
            gateway_task_routes={},
            gateway_cache_enabled=True,
            gateway_cache_ttl_seconds=60,
            gateway_rate_limit_requests=100,
            mock_chunk_delay_seconds=0,
        )
    )
    rows = []
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://campus-demo"
        ) as client:
            scenarios = [
                ("首次选课咨询", "2024级新生选课时间是什么？", ["course-selection-2024"]),
                ("相同问题与证据", "2024级新生选课时间是什么？", ["course-selection-2024"]),
                (
                    "同一问题换证据",
                    "2024级新生选课时间是什么？",
                    ["course-selection-2024", "english-placement-2024"],
                ),
                (
                    "翻译学院例外",
                    "2024级英语分级测试是否包含翻译学院？",
                    ["english-placement-2024"],
                ),
            ]
            for label, question, sources in scenarios:
                bundle = build_campus_request(question, sources, year=2024, model="campus-mock")
                response = await client.post("/v1/chat", json=bundle.request.model_dump())
                response.raise_for_status()
                body = response.json()
                metadata = body["metadata"]
                usage = Usage.model_validate(body["usage"]) if body["usage"] else None
                rows.append(
                    {
                        "scenario": label,
                        "status": response.status_code,
                        "cache": metadata["cache_status"],
                        "attempts": metadata["attempts"],
                        "sources": list(bundle.source_ids),
                        "snapshot": bundle.snapshot,
                        "evidence_characters": bundle.evidence_characters,
                        "usage": body["usage"],
                        "observed_cost": observed_cost(
                            usage, cache_hit=metadata["cache_status"] == "hit"
                        ),
                        "answer_kind": "mock_echo_not_a_policy_answer",
                    }
                )
            invalid = bundle.request.model_copy(update={"model": "missing-model"})
            response = await client.post("/v1/chat", json=invalid.model_dump())
            rows.append(
                {
                    "scenario": "错误模型别名",
                    "status": response.status_code,
                    "error": response.json()["error"]["code"],
                }
            )
    try:
        build_campus_request("2026级新生选课时间？", ["course-selection-2024"], year=2026)
    except EvidenceUnavailable:
        rows.append(
            {"scenario": "2026资料缺失", "status": "refused_before_provider", "attempts": 0}
        )
    assert [row["cache"] for row in rows[:4]] == ["miss", "hit", "miss", "miss"]
    assert rows[4]["status"] == 404
    assert rows[5]["attempts"] == 0
    report = {"provider": "offline Mock", "model_quality_tested": False, "cases": rows}
    output = Path("runtime/campus-demo.json")
    output.parent.mkdir(exist_ok=True)
    await asyncio.to_thread(
        output.write_text, json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print("校园咨询调用链（Mock 只回显，未验证模型答案）")
    for row in rows:
        print(
            f"  {row['scenario']}: {row['status']} / {row.get('cache', row.get('error', ''))}"
        )
    print(f"报告：{output}")


if __name__ == "__main__":
    asyncio.run(main())
