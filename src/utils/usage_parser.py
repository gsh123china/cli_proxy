"""Utilities for extracting and normalizing usage information from model responses."""
from __future__ import annotations

import json
import math
from typing import Any, Dict, Optional

METRIC_KEYS = [
    "input",
    "cached_create",
    "cached_read",
    "output",
    "reasoning",
    "total",
]


def empty_metrics() -> Dict[str, int]:
    """Return a fresh metrics dictionary with all counters set to 0."""
    return {key: 0 for key in METRIC_KEYS}


def _to_int(value: Any) -> int:
    """Best-effort conversion of numeric values to int."""
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int,)):
        return int(value)
    if isinstance(value, (float,)):
        return int(value)
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def normalize_usage(service: str, raw_usage: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Normalise raw usage payloads from different services into a common structure."""
    metrics = empty_metrics()
    raw = raw_usage or {}

    if service == "claude":
        metrics["input"] = _to_int(raw.get("input_tokens"))
        metrics["cached_create"] = _to_int(raw.get("cache_creation_input_tokens"))
        metrics["cached_read"] = _to_int(raw.get("cache_read_input_tokens"))
        metrics["output"] = _to_int(raw.get("output_tokens"))
        # Claude responses currently do not expose reasoning tokens explicitly.
        metrics["reasoning"] = _to_int(raw.get("reasoning_tokens"))
        total = raw.get("total_tokens")
        metrics["total"] = _to_int(total) if total is not None else metrics["input"] + metrics["output"]
    else:  # codex or other services following the Codex schema
        metrics["input"] = _to_int(raw.get("input_tokens"))
        cached_tokens = 0
        details = raw.get("input_tokens_details")
        if isinstance(details, dict):
            cached_tokens = _to_int(details.get("cached_tokens"))
        metrics["cached_read"] = cached_tokens
        metrics["cached_create"] = _to_int(raw.get("cache_creation_input_tokens"))
        metrics["output"] = _to_int(raw.get("output_tokens"))
        reasoning = 0
        output_details = raw.get("output_tokens_details")
        if isinstance(output_details, dict):
            reasoning = _to_int(output_details.get("reasoning_tokens"))
        metrics["reasoning"] = reasoning
        total = raw.get("total_tokens")
        metrics["total"] = _to_int(total) if total is not None else metrics["input"] + metrics["output"]

    return {
        "service": service,
        "metrics": metrics,
        "raw": raw,
    }


def normalize_usage_record(service: str, usage_obj: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Ensure a usage object follows the unified structure."""
    if not usage_obj:
        return normalize_usage(service, None)

    metrics_block = usage_obj.get("metrics") if isinstance(usage_obj, dict) else None
    raw_block = usage_obj.get("raw") if isinstance(usage_obj, dict) else None

    if isinstance(metrics_block, dict):
        metrics = empty_metrics()
        for key in METRIC_KEYS:
            metrics[key] = _to_int(metrics_block.get(key))
        raw = raw_block if isinstance(raw_block, dict) else {}
        service_name = usage_obj.get("service") if isinstance(usage_obj, dict) else service
        service_name = service_name or service
        return {
            "service": service_name,
            "metrics": metrics,
            "raw": raw,
        }

    if isinstance(usage_obj, dict):
        return normalize_usage(service, usage_obj)

    return normalize_usage(service, None)


def merge_usage_metrics(target: Dict[str, int], source: Dict[str, Any]) -> None:
    """In-place addition of usage metrics into an accumulator."""
    for key in METRIC_KEYS:
        target[key] = target.get(key, 0) + _to_int(source.get(key))


def _safe_json_loads(payload: str) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(payload)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        return None
    return None


def _extract_usage_from_payload(service: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if service == "claude":
        if "usage" in payload and isinstance(payload["usage"], dict):
            return payload["usage"]
        message = payload.get("message")
        if isinstance(message, dict) and isinstance(message.get("usage"), dict):
            return message["usage"]
    else:
        if "usage" in payload and isinstance(payload["usage"], dict):
            return payload["usage"]
        response = payload.get("response")
        if isinstance(response, dict) and isinstance(response.get("usage"), dict):
            return response["usage"]
    return None


def _extract_from_sse(service: str, text: str) -> Optional[Dict[str, Any]]:
    last_usage = None
    for chunk in text.split("\n\n"):
        lines = [line.strip() for line in chunk.splitlines() if line.strip()]
        data_lines = [line[5:].strip() for line in lines if line.startswith("data:")]
        for data_line in data_lines:
            payload = _safe_json_loads(data_line)
            if not payload:
                continue
            usage = _extract_usage_from_payload(service, payload)
            if usage:
                last_usage = usage
    return last_usage


def update_usage_from_sse_chunk(service: str,
                                chunk_text: str,
                                previous_usage: Optional[Dict[str, Any]] = None
                                ) -> Optional[Dict[str, Any]]:
    """
    增量解析 SSE/JSON 片段中的 usage 信息，返回最近一次解析到的 usage。

    Args:
        service: 服务名称（claude/codex）
        chunk_text: 当前收到的文本片段
        previous_usage: 上一次解析得到的 usage（可为空）

    Returns:
        最新解析到的 usage，如果没有新的 usage，则返回 previous_usage
    """
    if not chunk_text:
        return previous_usage

    latest_usage = previous_usage
    stripped = chunk_text.strip()

    # 优先处理典型的 SSE 片段（包含 data: 行）
    if "data:" in chunk_text:
        for raw_chunk in chunk_text.split("\n\n"):
            lines = [line.strip() for line in raw_chunk.splitlines() if line.strip()]
            data_lines = [line[5:].strip() for line in lines if line.startswith("data:")]
            for data_line in data_lines:
                payload = _safe_json_loads(data_line)
                if not payload:
                    continue
                usage = _extract_usage_from_payload(service, payload)
                if usage:
                    latest_usage = usage
        return latest_usage

    # 非 SSE：尝试将整个文本解析为 JSON
    payload = _safe_json_loads(stripped)
    if payload:
        usage = _extract_usage_from_payload(service, payload)
        if usage:
            latest_usage = usage

    return latest_usage


def process_sse_buffer(
    service: str,
    buffer: str,
    chunk_text: str,
    previous_usage: Optional[Dict[str, Any]] = None
) -> tuple[Optional[Dict[str, Any]], str]:
    """按 SSE 事件边界解析 usage。

    维护并返回残余 buffer，避免事件在 chunk 边界被截断造成丢失。
    """
    if not isinstance(buffer, str):
        buffer = ""
    if not chunk_text:
        return previous_usage, buffer

    text = buffer + chunk_text
    parts = text.split("\n\n")
    # 如果文本未以空行结尾，最后一个是未完成事件，放回 buffer
    remainder = parts.pop() if text and not text.endswith("\n\n") else ""

    latest_usage = previous_usage
    for part in parts:
        lines = [line.strip() for line in part.splitlines() if line.strip()]
        data_lines = [line[5:].strip() for line in lines if line.startswith("data:")]
        for data_line in data_lines:
            payload = _safe_json_loads(data_line)
            if not payload:
                continue
            usage = _extract_usage_from_payload(service, payload)
            if usage:
                latest_usage = usage

    return latest_usage, remainder


def process_ndjson_buffer(
    service: str,
    buffer: str,
    chunk_text: str,
    previous_usage: Optional[Dict[str, Any]] = None
) -> tuple[Optional[Dict[str, Any]], str]:
    """按 NDJSON 行边界解析 usage，返回最新 usage 与剩余未完成行。"""
    if not isinstance(buffer, str):
        buffer = ""
    if not chunk_text:
        return previous_usage, buffer

    text = buffer + chunk_text
    # 保留换行以判断最后一行是否完整
    lines = text.split("\n")
    has_trailing_newline = text.endswith("\n")
    if has_trailing_newline:
        complete_lines = lines[:-1]  # 最后一个是空串
        remainder = ""
    else:
        complete_lines = lines[:-1]
        remainder = lines[-1]

    latest_usage = previous_usage
    for line in complete_lines:
        line = line.strip()
        if not line:
            continue
        payload = _safe_json_loads(line)
        if not payload:
            continue
        usage = _extract_usage_from_payload(service, payload)
        if usage:
            latest_usage = usage

    return latest_usage, remainder


def extract_usage_from_response(service: str, response_bytes: Optional[bytes]) -> Dict[str, Any]:
    """Extract usage information from raw response bytes."""
    if not response_bytes:
        return normalize_usage(service, None)

    try:
        text = response_bytes.decode("utf-8", errors="ignore").strip()
    except (AttributeError, UnicodeDecodeError):
        return normalize_usage(service, None)

    if not text:
        return normalize_usage(service, None)

    raw_usage = None
    if text.startswith("event:") or "\ndata:" in text:
        raw_usage = _extract_from_sse(service, text)
    else:
        payload = _safe_json_loads(text)
        if payload:
            raw_usage = _extract_usage_from_payload(service, payload)

    return normalize_usage(service, raw_usage)


def format_usage_value(value: int) -> str:
    """Format usage numbers with optional shorthand in parentheses."""
    value = _to_int(value)
    short = None
    if value >= 1_000_000:
        shortened = math.floor(value / 100_000) / 10
        short = f"{shortened:.1f}m"
    elif value >= 1_000:
        shortened = math.floor(value / 100) / 10
        short = f"{shortened:.1f}k"

    if short:
        return f"{value} ({short})"
    return str(value)
