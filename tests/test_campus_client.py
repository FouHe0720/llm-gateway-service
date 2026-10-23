import hashlib
import json
import shutil
from decimal import Decimal

import pytest

from app.domain.schemas import Usage
from examples.campus_client import (
    DATA,
    EvidenceUnavailable,
    build_campus_request,
    observed_cost,
)


def build(**overrides):
    return build_campus_request(
        "2024级新生选课时间？", ["course-selection-2024"], **{"year": 2024, **overrides}
    )


def test_historical_evidence_and_paragraphs_are_visible_to_model():
    bundle = build()
    content = bundle.request.messages[-1].content
    assert "2024年9月14日10：00—9月20日10：00" in content
    assert "[course-selection-2024:p6]" in content
    assert bundle.snapshot in content
    assert bundle.request.temperature == 0
    assert bundle.request.max_tokens == 256


@pytest.mark.parametrize(
    "overrides", [{"year": 2026}, {"campus": "青岛"}, {"evidence_limit": 20}]
)
def test_unmatched_evidence_is_rejected_before_provider(overrides):
    with pytest.raises(EvidenceUnavailable):
        build(**overrides)


@pytest.mark.parametrize("sources", [[], ["missing"], ["course-selection-2024"] * 2])
def test_missing_or_duplicate_sources_are_rejected(sources):
    with pytest.raises(EvidenceUnavailable):
        build_campus_request("选课时间", sources, year=2024)


def test_modified_source_and_inconsistent_manifest_are_rejected(tmp_path):
    data = tmp_path / "sources"
    shutil.copytree(DATA, data)
    source_path = data / "corpus/course-selection-2024.md"
    source_path.write_text(source_path.read_text() + "\nchanged\n")
    with pytest.raises(EvidenceUnavailable):
        build(data_dir=data)
    shutil.copytree(DATA, data, dirs_exist_ok=True)
    manifest_path = data / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["documents"][0]["paragraphs"][0]["text"] = "不存在的原文"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(EvidenceUnavailable):
        build(data_dir=data)


async def test_evidence_revision_invalidates_gateway_cache(client, tmp_path):
    client._transport.app.state.chat.settings.gateway_cache_enabled = True
    original = build()
    first = await client.post("/v1/chat", json=original.request.model_dump())
    second = await client.post("/v1/chat", json=original.request.model_dump())
    assert first.json()["metadata"]["cache_status"] == "miss"
    assert second.json()["metadata"]["cache_status"] == "hit"
    data = tmp_path / "sources"
    shutil.copytree(DATA, data)
    source_path = data / "corpus/course-selection-2024.md"
    source_path.write_text(source_path.read_text() + "\n版本标记：测试修订\n")
    manifest_path = data / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["documents"][0]["excerpt_sha256"] = hashlib.sha256(
        source_path.read_bytes()
    ).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    revised = build(data_dir=data)
    assert original.snapshot != revised.snapshot
    third = await client.post("/v1/chat", json=revised.request.model_dump())
    assert third.json()["metadata"]["cache_status"] == "miss"


def test_only_observed_tokens_and_explicit_prices_produce_cost():
    usage = Usage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
    assert observed_cost(None, Decimal("2"), Decimal("4")) is None
    assert observed_cost(usage) is None
    assert observed_cost(usage, Decimal("2"), Decimal("4")) == Decimal("0.004")
    with pytest.raises(ValueError):
        observed_cost(usage, Decimal("Infinity"), Decimal("1"))


def test_cached_response_usage_does_not_produce_a_second_inference_cost():
    usage = Usage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
    assert observed_cost(usage, Decimal("2"), Decimal("4"), cache_hit=True) is None
    assert observed_cost(usage, Decimal("2"), Decimal("4"), cache_hit=False) == Decimal("0.004")
