"""Stage 9 streaming benchmark contract (simulated HTTP, never real performance)."""
from __future__ import annotations

import json

import httpx
import pytest

from src.infrastructure.scripts.benchmark_stage9_llm import (
    BenchmarkError, aggregate, build_report, collect_sample, load_prompts,
    percentile, require_loopback,
)


def test_stage9_benchmark_dataset_and_local_url_guard():
    prompts, digest = load_prompts()
    assert len(prompts) == 4 and len(digest) == 64
    assert len({entry["id"] for entry in prompts}) == 4
    assert require_loopback("http://localhost:8080/") == "http://localhost:8080"
    for value in (
        "http://192.0.2.1:8080", "https://localhost:8080",
        "http://user:pass@localhost:8080", "http://localhost:8080/v1",
        "http://localhost:8080?api_key=secret", "http://localhost",
    ):
        with pytest.raises(BenchmarkError):
            require_loopback(value)


def fake_transport(request):
    if request.url.path == "/health":
        return httpx.Response(200, json={"status": "ok"})
    if request.url.path == "/v1/models":
        return httpx.Response(200, json={"data": [{"id": "synthetic-test-model"}]})
    if request.url.path == "/v1/chat/completions":
        payload = json.loads(request.content)
        assert payload["stream"] is True and payload["temperature"] == 0
        first = {"choices": [{"delta": {"content": "پاسخ"}}]}
        second = {"choices": [{"delta": {"content": " نمونه"}}]}
        usage = {"choices": [], "usage": {"completion_tokens": 4}}
        stream = "".join("data: " + json.dumps(part, ensure_ascii=False) + "\n\n"
                         for part in (first, second, usage)) + "data: [DONE]\n\n"
        return httpx.Response(200, text=stream, headers={"content-type": "text/event-stream"})
    return httpx.Response(404)


def test_real_stream_protocol_measures_usage_when_server_supplies_it():
    prompts, digest = load_prompts()
    with httpx.Client(base_url="http://127.0.0.1:8080",
                      transport=httpx.MockTransport(fake_transport)) as client:
        report = build_report(
            client, prompts, digest, model_label="SYNTHETIC HTTP TEST",
            runtime_version="test", quantization="test", runs=1, warmup=1,
            max_tokens=32,
        )
    assert report["completed"] == 4 and report["failed"] == 0
    assert len(report["samples"]) == 4
    assert all(row["completion_tokens"] == 4 for row in report["samples"])
    assert report["aggregates"]["generated_tokens_per_second"]["sample_count"] == 4
    assert all(row["ttft_ms"] >= 0 and row["total_ms"] > 0 for row in report["samples"])


def test_opt_in_synthetic_response_capture_has_strict_size_limit():
    with httpx.Client(base_url="http://127.0.0.1:8080",
                      transport=httpx.MockTransport(fake_transport)) as client:
        captured = collect_sample(
            client, "synthetic-test-model", "Synthetic fixed prompt", 32,
            include_response_text=True,
        )
    assert captured["response_text"] == "پاسخ نمونه"
    assert captured["response_text_truncated"] is False
    with httpx.Client(base_url="http://127.0.0.1:8080",
                      transport=httpx.MockTransport(fake_transport)) as client:
        private = collect_sample(client, "synthetic-test-model", "Synthetic fixed prompt", 32)
    assert "response_text" not in private


def test_missing_server_usage_never_invents_token_throughput():
    def without_usage(request):
        result = fake_transport(request)
        if request.url.path == "/v1/chat/completions":
            response = result.text.replace(
                'data: {"choices": [], "usage": {"completion_tokens": 4}}\n\n', ""
            )
            return httpx.Response(200, text=response)
        return result

    with httpx.Client(base_url="http://127.0.0.1:8080",
                      transport=httpx.MockTransport(without_usage)) as client:
        sample = collect_sample(client, "synthetic-test-model", "test", 32)
    assert sample["generated_tokens_per_second"] is None
    assert sample["completion_tokens"] is None
    assert aggregate([sample])["generated_tokens_per_second"]["p50"] is None
    assert percentile([1, 3, 5], .95) == pytest.approx(4.8)


def test_broken_sse_is_an_error_not_a_success():
    def broken(request):
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"hello"}}]}\n\n')

    with httpx.Client(base_url="http://localhost:8080",
                      transport=httpx.MockTransport(broken)) as client:
        with pytest.raises(BenchmarkError, match="Incomplete"):
            collect_sample(client, "synthetic-test-model", "test", 32)



def test_native_llama_cpp_models_shape_with_auth_is_supported():
    prompts, digest = load_prompts()
    actual_model = r"D:\models\Qwen3-1.7B-Q4_K_M.gguf"

    def handler(request):
        assert request.headers.get("authorization") == "Bearer synthetic-runtime-key"
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={
                "models": [{"name": actual_model, "model": actual_model}]
            })
        return fake_transport(request)

    with httpx.Client(
        base_url="http://127.0.0.1:8080",
        headers={"Authorization": "Bearer synthetic-runtime-key"},
        transport=httpx.MockTransport(handler),
    ) as client:
        report = build_report(
            client, prompts, digest, model_label="SYNTHETIC HTTP TEST",
            runtime_version="test", quantization="test", runs=1, warmup=1,
            max_tokens=32,
        )
    assert report["model_id_served"] == actual_model
    assert report["completed"] == 4
    assert report["failed"] == 0


def test_native_llama_cpp_name_fallback_and_invalid_shape():
    from src.infrastructure.scripts.benchmark_stage9_llm import model_id_async_safe

    def handler(request):
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"models": [{"name": "test-model"}]})
        return httpx.Response(404)

    with httpx.Client(base_url="http://127.0.0.1:8080",
                      transport=httpx.MockTransport(handler)) as client:
        assert model_id_async_safe(client, "") == "test-model"
        with pytest.raises(BenchmarkError, match="not served"):
            model_id_async_safe(client, "other-model")

    for response in ({"models": [{"name": ""}]}, {"models": [42]}, {"models": []}):
        with httpx.Client(
            base_url="http://127.0.0.1:8080",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=(
                    {"status": "ok"} if request.url.path == "/health" else response
                ))
            ),
        ) as client:
            with pytest.raises(BenchmarkError, match="Invalid model listing"):
                model_id_async_safe(client, "")


def test_llm_listing_unauthorized_error_is_actionable_without_leaking_token():
    from src.infrastructure.scripts.benchmark_stage9_llm import model_id_async_safe

    def unauthorized(request):
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(401, json={"error": {"message": "secret response"}})

    with httpx.Client(base_url="http://127.0.0.1:8080",
                      transport=httpx.MockTransport(unauthorized)) as client:
        with pytest.raises(BenchmarkError, match="CHATBOT_LLM_API_KEY") as info:
            model_id_async_safe(client, "")
    assert "secret response" not in str(info.value)
