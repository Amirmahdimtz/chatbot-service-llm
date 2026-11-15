"""Opt-in, real llama.cpp CPU streaming benchmark for fixed synthetic Persian prompts.

Measures API-visible TTFT and latency. Token/s is reported ONLY when server
sends measured completion token usage; no character-based token fabrication.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import statistics
import sys
import time
from urllib.parse import urlsplit

import httpx

PROMPTS = Path(__file__).resolve().parents[3] / "benchmarks" / "stage9_llm_prompts_fa.json"


class BenchmarkError(RuntimeError):
    pass


def require_loopback(url: str) -> str:
    parts = urlsplit(url)
    if (parts.scheme != "http" or parts.hostname not in {"localhost", "127.0.0.1"}
            or not parts.port or parts.path not in {"", "/"} or parts.username
            or parts.password or parts.query or parts.fragment):
        raise BenchmarkError("A loopback HTTP URL with explicit port is required")
    return url.rstrip("/")


def load_prompts(path: Path = PROMPTS) -> tuple[list[dict], str]:
    raw = path.read_bytes()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise BenchmarkError("Invalid UTF-8 JSON prompts") from exc
    if (not isinstance(data, dict) or set(data) != {"schema_version", "dataset_id", "prompts"}
            or data["schema_version"] != 1 or data["dataset_id"] != "stage9-local-persian-llm-v1"
            or not isinstance(data["prompts"], list) or len(data["prompts"]) != 4):
        raise BenchmarkError("Unsupported prompt dataset")
    seen = set()
    for row in data["prompts"]:
        if (not isinstance(row, dict) or set(row) != {"id", "prompt", "review_criteria"}
                or not isinstance(row["id"], str)
                or not re.fullmatch(r"[a-z_]{4,40}", row["id"])
                or row["id"] in seen or not isinstance(row["prompt"], str)
                or not 20 <= len(row["prompt"]) <= 500
                or not isinstance(row["review_criteria"], list)
                or not row["review_criteria"]
                or not all(isinstance(x, str) and x.strip()
                           for x in row["review_criteria"])):
            raise BenchmarkError("Invalid or duplicate benchmark prompt")
        seen.add(row["id"])
    return data["prompts"], sha256(raw).hexdigest()


def model_id_async_safe(client: httpx.Client, requested: str) -> str:
    health = client.get("/health")
    if health.status_code != 200:
        raise BenchmarkError("llama.cpp /health is unavailable")
    models = client.get("/v1/models")
    if models.status_code in (401, 403):
        raise BenchmarkError("llama.cpp /v1/models requires a valid CHATBOT_LLM_API_KEY")
    if models.status_code != 200:
        raise BenchmarkError("llama.cpp /v1/models is unavailable")
    try:
        payload = models.json()
        if not isinstance(payload, dict):
            raise ValueError("Invalid models payload")
        # Older/native llama.cpp responses expose "models" with "model"/"name",
        # while OpenAI-compatible listings expose "data" with "id".
        if "data" in payload:
            entries = payload["data"]
            key = "id"
        elif "models" in payload:
            entries = payload["models"]
            key = "model"
        else:
            raise ValueError("Missing models")
        if not isinstance(entries, list):
            raise ValueError("Invalid model entries")
        ids = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("Invalid model entry")
            model_id = entry.get(key)
            if key == "model" and not model_id:
                model_id = entry.get("name")
            if not isinstance(model_id, str) or not model_id:
                raise ValueError("Invalid model ID")
            ids.append(model_id)
        if not ids or len(set(ids)) != len(ids):
            raise ValueError("Empty or duplicate model IDs")
    except (ValueError, KeyError, TypeError) as exc:
        raise BenchmarkError("Invalid model listing") from exc
    if requested:
        if requested not in ids:
            raise BenchmarkError("Requested model ID is not served")
        return requested
    if len(ids) != 1:
        raise BenchmarkError("Specify --model-id when multiple models are served")
    return ids[0]


def collect_sample(client: httpx.Client, model_id: str, prompt: str, max_tokens: int,
                   include_usage: bool = True, include_response_text: bool = False) -> dict:
    body = {
        "model": model_id, "stream": True, "temperature": 0,
        "max_tokens": max_tokens,
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [
            {"role": "system", "content": "Answer in Persian. Be accurate. Do not invent evidence."},
            {"role": "user", "content": prompt},
        ],
    }
    if include_usage:
        body["stream_options"] = {"include_usage": True}
    start = time.perf_counter()
    first = None
    chars = 0
    response_parts: list[str] = []
    saved_characters = 0
    completion_tokens = None
    finish_reason = None
    done = False
    try:
        with client.stream("POST", "/v1/chat/completions", json=body,
                           headers={"Accept": "text/event-stream"}) as response:
            if response.status_code != 200:
                raise BenchmarkError("Model stream returned HTTP " + str(response.status_code))
            for line in response.iter_lines():
                if not line or line.startswith(":"):
                    continue
                if not line.startswith("data:"):
                    continue
                text = line[5:].strip()
                if text == "[DONE]":
                    done = True
                    break
                if len(text) > 65536:
                    raise BenchmarkError("Oversized stream event")
                try:
                    event = json.loads(text)
                    if not isinstance(event, dict):
                        raise ValueError("Invalid event")
                    usage = event.get("usage")
                    if isinstance(usage, dict):
                        count = usage.get("completion_tokens")
                        if type(count) is int and count >= 0:
                            completion_tokens = count
                    choices = event.get("choices", [])
                    if not isinstance(choices, list):
                        raise ValueError("Invalid choices")
                    if choices:
                        choice = choices[0]
                        if not isinstance(choice, dict):
                            raise ValueError("Invalid choice")
                        reason = choice.get("finish_reason")
                        if reason is not None:
                            if not isinstance(reason, str) or not reason:
                                raise ValueError("Invalid finish reason")
                            finish_reason = reason
                        delta = choice["delta"].get("content")
                        if delta is not None and not isinstance(delta, str):
                            raise ValueError("Non-string delta")
                        if delta:
                            if first is None:
                                first = time.perf_counter()
                            chars += len(delta)
                            if include_response_text and saved_characters < 8192:
                                fragment = delta[:8192 - saved_characters]
                                response_parts.append(fragment)
                                saved_characters += len(fragment)
                except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
                    raise BenchmarkError("Malformed model SSE event") from exc
    except httpx.TimeoutException as exc:
        raise BenchmarkError("MODEL_TIMEOUT") from exc
    except httpx.RequestError as exc:
        raise BenchmarkError("MODEL_NETWORK_ERROR") from exc
    end = time.perf_counter()
    if not done or first is None or chars == 0:
        raise BenchmarkError("Incomplete or empty model stream")
    duration = max(end - start, 1e-9)
    generation_seconds = max(end - first, 1e-9)
    return {
        "ttft_ms": round((first - start) * 1000, 2),
        "total_ms": round(duration * 1000, 2),
        "output_characters": chars,
        "characters_per_second_proxy": round(chars / generation_seconds, 2),
        "completion_tokens": completion_tokens,
        "finish_reason": finish_reason,
        **({"response_text": "".join(response_parts),
            "response_text_truncated": saved_characters < chars}
           if include_response_text else {}),
        "generated_tokens_per_second": (
            round(completion_tokens / generation_seconds, 2)
            if completion_tokens is not None else None
        ),
    }


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    sorted_values = sorted(values)
    index = (len(sorted_values) - 1) * fraction
    lower, upper = math.floor(index), math.ceil(index)
    return round(sorted_values[lower] + (sorted_values[upper] - sorted_values[lower])
                 * (index - lower), 2)


def aggregate(samples: list[dict]) -> dict:
    result = {}
    for key in ("ttft_ms", "total_ms", "characters_per_second_proxy",
                "generated_tokens_per_second"):
        values = [float(s[key]) for s in samples if s.get(key) is not None]
        result[key] = {
            "sample_count": len(values),
            "p50": percentile(values, 0.50),
            "p95": percentile(values, 0.95),
        }
    return result


def build_report(client: httpx.Client, prompts: list[dict], digest: str, *,
                 model_label: str, runtime_version: str, quantization: str,
                 runs: int, warmup: int, max_tokens: int,
                 include_usage: bool = True, model_id: str = "",
                 include_response_text: bool = False) -> dict:
    served_model = model_id_async_safe(client, model_id)
    for _ in range(warmup):
        collect_sample(client, served_model, prompts[0]["prompt"], max_tokens, include_usage)
    results = []
    failures = []
    for row in prompts:
        for index in range(runs):
            try:
                measurement = collect_sample(client, served_model, row["prompt"],
                                             max_tokens, include_usage, include_response_text)
                results.append({"prompt_id": row["id"], "run": index + 1, **measurement})
            except BenchmarkError as exc:
                # Return error categories only, never model output or server messages.
                failures.append({"prompt_id": row["id"], "run": index + 1,
                                 "error": str(exc)})
    stop_reasons = {}
    for sample in results:
        reason = sample.get("finish_reason") or "unknown"
        stop_reasons[reason] = stop_reasons.get(reason, 0) + 1
    return {
        "report_version": 1,
        "measurement_type": "real_llama_cpp_streaming_not_mock",
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_sha256": digest,
        "dataset_id": "stage9-local-persian-llm-v1",
        "model_label_declared": model_label,
        "model_id_served": served_model,
        "runtime_version_declared": runtime_version or None,
        "quantization_declared": quantization or None,
        "launch_config_declared_not_verified": {
            "threads": 4, "ctx_size": 2048, "parallel": 1, "n_gpu_layers": 0,
        },
        "warmup_calls": warmup,
        "repetitions_per_prompt": runs,
        "concurrency": 1,
        "max_tokens": max_tokens,
        "token_usage_requested": include_usage,
        "response_text_recording_opt_in": include_response_text,
        "completed": len(results),
        "failed": len(failures),
        "samples": results,
        "errors": failures,
        "aggregates": aggregate(results),
        "aggregates_by_run_position": {
            "first_run_per_prompt": aggregate([s for s in results if s["run"] == 1]),
            "repeat_runs_per_prompt": aggregate([s for s in results if s["run"] > 1]),
        },
        "finish_reason_counts": stop_reasons,
        "limitations": [
            "TTFT includes local HTTP round-trip and server scheduling.",
            "The global warmup primes only the first prompt; first-run and repeat-run "
            "latencies must not be interpreted as controlled cold/warm cache benchmarks.",
            "finish_reason is null if the server omits it; a token cap can prevent "
            "a meaningful quality review even when requests finish successfully.",
            "Token throughput is null when server does not stream completion_tokens usage.",
            "Character throughput is a proxy, NOT generated tokens/sec.",
            ("Persian answer quality and citation correctness require human review; "
             + ("text recorded by explicit opt-in and may require redaction before sharing."
                if include_response_text else "text not saved.")),
            "Peak RAM, CPU usage, retrieval/rerank and agent latency are not measured by this script.",
            "Runtime flags and model quantization labels are user-declared, not programmatically verified.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--model-id", default="")
    parser.add_argument("--model-label", required=True)
    parser.add_argument("--runtime-version", default="")
    parser.add_argument("--quantization", default="Q4_K_M")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--max-tokens", type=int, default=128)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--no-stream-usage", action="store_true")
    parser.add_argument("--include-responses", action="store_true",
                        help="Store bounded synthetic-prompt model answers for human quality review")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.runs <= 20 or not 1 <= args.warmup <= 3:
        parser.error("runs must be 1..20, warmup 1..3")
    if not 16 <= args.max_tokens <= 512 or not 5 <= args.timeout <= 600:
        parser.error("max-tokens and timeout out of range")
    url = require_loopback(args.base_url)
    if args.output.exists():
        parser.error("Output exists; choose a new filename to avoid overwriting previous measurements")
    prompts, digest = load_prompts()
    secret = os.getenv("CHATBOT_LLM_API_KEY", "")
    with httpx.Client(
        base_url=url, timeout=httpx.Timeout(args.timeout, connect=5.0),
        trust_env=False, headers={"Authorization": "Bearer " + secret} if secret else {},
    ) as client:
        report = build_report(
            client, prompts, digest, model_label=args.model_label,
            runtime_version=args.runtime_version, quantization=args.quantization,
            runs=args.runs, warmup=args.warmup, max_tokens=args.max_tokens,
            include_usage=not args.no_stream_usage, model_id=args.model_id,
            include_response_text=args.include_responses,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents accidental overwrite even with concurrent runs.
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(json.dumps({
        "output": str(args.output), "completed": report["completed"],
        "failed": report["failed"], "aggregates": report["aggregates"],
    }, ensure_ascii=False))
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BenchmarkError as exc:
        print("Benchmark failed: " + str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
