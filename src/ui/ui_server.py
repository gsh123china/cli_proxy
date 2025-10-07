import json
import hashlib
import webbrowser
import time
from pathlib import Path
from typing import Any, Dict, Optional, Set
from flask import Flask, jsonify, send_file, request
import os
from datetime import datetime, timezone

from src.utils.usage_parser import (
    METRIC_KEYS,
    empty_metrics,
    format_usage_value,
    merge_usage_metrics,
    normalize_usage_record,
)

# 数据目录 - 使用绝对路径
DATA_DIR = Path.home() / '.clp/data'
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR = Path(__file__).resolve().parent / 'static'

LOG_FILE = DATA_DIR / 'proxy_requests.jsonl'
OLD_LOG_FILE = DATA_DIR / 'traffic_statistics.jsonl'
HISTORY_FILE = DATA_DIR / 'history_usage.json'
HISTORY_TOKENS_FILE = DATA_DIR / 'history_usage_by_token.json'

if OLD_LOG_FILE.exists() and not LOG_FILE.exists():
    try:
        OLD_LOG_FILE.rename(LOG_FILE)
    except OSError:
        pass

app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path='/static')


# 初始化鉴权中间件
def _setup_auth_middleware():
    """设置鉴权中间件"""
    try:
        from src.auth.auth_manager import AuthManager
        from src.auth.flask_middleware import FlaskAuthMiddleware

        # 初始化鉴权管理器
        auth_manager = AuthManager()

        # 注册鉴权中间件
        FlaskAuthMiddleware(
            app=app,
            auth_manager=auth_manager,
            service_name='ui',
            whitelist_paths={'/', '/health', '/ping', '/favicon.ico'},
            whitelist_prefixes={'/static/'}
        )
    except ImportError as e:
        print(f"警告: 鉴权模块加载失败，将不启用鉴权功能: {e}")
    except Exception as e:
        print(f"警告: 鉴权中间件初始化失败: {e}")


# 初始化鉴权
_setup_auth_middleware()


def _safe_json_load(line: str) -> Dict[str, Any]:
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return {}


def _config_signature(config_entry: Dict[str, Any]) -> tuple:
    """Create a comparable signature for a config entry to help detect renames."""
    if not isinstance(config_entry, dict):
        return tuple()
    return (
        config_entry.get('base_url'),
        config_entry.get('auth_token'),
        config_entry.get('api_key'),
    )


def _detect_config_renames(old_configs: Dict[str, Any], new_configs: Dict[str, Any]) -> Dict[str, str]:
    """Return mapping of {old_name: new_name} for configs that only changed key names."""
    rename_map: Dict[str, str] = {}
    if not isinstance(old_configs, dict) or not isinstance(new_configs, dict):
        return rename_map

    old_signatures: Dict[tuple, list[str]] = {}
    for name, cfg in old_configs.items():
        sig = _config_signature(cfg)
        old_signatures.setdefault(sig, []).append(name)

    new_signatures: Dict[tuple, list[str]] = {}
    for name, cfg in new_configs.items():
        sig = _config_signature(cfg)
        new_signatures.setdefault(sig, []).append(name)

    for signature, old_names in old_signatures.items():
        new_names = new_signatures.get(signature)
        if not new_names:
            continue
        if set(old_names) == set(new_names):
            continue
        if len(old_names) == len(new_names) == 1:
            old_name = old_names[0]
            new_name = new_names[0]
            if old_name != new_name:
                rename_map[old_name] = new_name

    return rename_map


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'on'}
    if isinstance(value, (int, float)):
        return bool(value)
    return bool(value)


def _current_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _normalize_deleted_flags(configs: Dict[str, Any]) -> None:
    if not isinstance(configs, dict):
        return
    for cfg in configs.values():
        if not isinstance(cfg, dict):
            continue
        deleted = _coerce_bool(cfg.get('deleted', False))
        if deleted:
            cfg['deleted'] = True
            cfg['active'] = False
            deleted_at = cfg.get('deleted_at')
            if not isinstance(deleted_at, str) or not deleted_at.strip():
                cfg['deleted_at'] = _current_utc_iso()
        else:
            cfg.pop('deleted', None)
            cfg.pop('deleted_at', None)


def _rename_history_channels(service: str, rename_map: Dict[str, str]) -> None:
    if not rename_map:
        return
    history_usage = load_history_usage()
    service_bucket = history_usage.get(service)
    if not service_bucket:
        return

    changed = False
    for old_name, new_name in rename_map.items():
        if old_name == new_name:
            continue
        if old_name not in service_bucket:
            continue

        existing_metrics = service_bucket.pop(old_name)
        target_metrics = service_bucket.get(new_name)
        if target_metrics:
            merge_usage_metrics(target_metrics, existing_metrics)
        else:
            service_bucket[new_name] = existing_metrics
        changed = True

    if changed:
        save_history_usage(history_usage)


def _rename_log_channels(service: str, rename_map: Dict[str, str]) -> None:
    if not rename_map or not LOG_FILE.exists():
        return

    temp_path = LOG_FILE.with_suffix('.tmp')
    try:
        with open(LOG_FILE, 'r', encoding='utf-8') as src, open(temp_path, 'w', encoding='utf-8') as dst:
            for raw_line in src:
                if not raw_line.strip():
                    dst.write(raw_line)
                    continue
                try:
                    record = json.loads(raw_line)
                except json.JSONDecodeError:
                    dst.write(raw_line)
                    continue

                if record.get('service') == service:
                    channel_name = record.get('channel')
                    if channel_name in rename_map:
                        record['channel'] = rename_map[channel_name]
                        raw_line = json.dumps(record, ensure_ascii=False) + '\n'
                dst.write(raw_line)
    except Exception:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise

    temp_path.replace(LOG_FILE)


def _sync_router_config_names(service: str, rename_map: Dict[str, str]) -> None:
    """同步模型路由配置中的配置名称"""
    if not rename_map:
        return

    router_config_file = DATA_DIR / 'model_router_config.json'
    if not router_config_file.exists():
        return

    try:
        with open(router_config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)

        changed = False

        # 更新 modelMappings 中的配置名称
        if 'modelMappings' in config and service in config['modelMappings']:
            for mapping in config['modelMappings'][service]:
                if mapping.get('source_type') == 'config' and mapping.get('source') in rename_map:
                    old_name = mapping['source']
                    new_name = rename_map[old_name]
                    mapping['source'] = new_name
                    changed = True

        # 更新 configMappings 中的配置名称
        if 'configMappings' in config and service in config['configMappings']:
            for mapping in config['configMappings'][service]:
                if mapping.get('config') in rename_map:
                    old_name = mapping['config']
                    new_name = rename_map[old_name]
                    mapping['config'] = new_name
                    changed = True

        if changed:
            with open(router_config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)

    except Exception as e:
        print(f"同步路由配置名称失败: {e}")


def _sync_loadbalance_config_names(service: str, rename_map: Dict[str, str]) -> None:
    """同步负载均衡配置中的配置名称"""
    if not rename_map:
        return

    lb_config_file = DATA_DIR / 'lb_config.json'
    if not lb_config_file.exists():
        return

    try:
        with open(lb_config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)

        changed = False
        service_config = config.get('services', {}).get(service, {})

        # 更新 currentFailures 中的配置名称
        current_failures = service_config.get('currentFailures', {})
        new_failures = {}
        for config_name, count in current_failures.items():
            if config_name in rename_map:
                new_failures[rename_map[config_name]] = count
                changed = True
            else:
                new_failures[config_name] = count

        if changed:
            service_config['currentFailures'] = new_failures

        # 更新 excludedConfigs 中的配置名称
        excluded_configs = service_config.get('excludedConfigs', [])
        new_excluded = []
        for config_name in excluded_configs:
            if config_name in rename_map:
                new_excluded.append(rename_map[config_name])
                changed = True
            else:
                new_excluded.append(config_name)

        if changed:
            service_config['excludedConfigs'] = new_excluded
            config.setdefault('services', {})[service] = service_config

            with open(lb_config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)

    except Exception as e:
        print(f"同步负载均衡配置名称失败: {e}")


def _cleanup_deleted_configs(service: str, old_configs: Dict[str, Any], new_configs: Dict[str, Any]) -> None:
    """清理被删除的配置在路由配置和负载均衡配置中的引用"""
    if not isinstance(old_configs, dict) or not isinstance(new_configs, dict):
        return

    # 找出被删除的配置
    deleted_configs = set(old_configs.keys()) - set(new_configs.keys())
    if not deleted_configs:
        return

    # 清理路由配置中的引用
    _cleanup_router_config_references(service, deleted_configs)
    # 清理负载均衡配置中的引用
    _cleanup_loadbalance_config_references(service, deleted_configs)


def _cleanup_router_config_references(service: str, deleted_configs: set) -> None:
    """清理路由配置中对已删除配置的引用"""
    router_config_file = DATA_DIR / 'model_router_config.json'
    if not router_config_file.exists():
        return

    try:
        with open(router_config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)

        changed = False

        # 清理 modelMappings 中的配置引用
        if 'modelMappings' in config and service in config['modelMappings']:
            original_mappings = config['modelMappings'][service][:]
            config['modelMappings'][service] = [
                mapping for mapping in original_mappings
                if not (mapping.get('source_type') == 'config' and mapping.get('source') in deleted_configs)
            ]
            if len(config['modelMappings'][service]) != len(original_mappings):
                changed = True

        # 清理 configMappings 中的配置引用
        if 'configMappings' in config and service in config['configMappings']:
            original_mappings = config['configMappings'][service][:]
            config['configMappings'][service] = [
                mapping for mapping in original_mappings
                if mapping.get('config') not in deleted_configs
            ]
            if len(config['configMappings'][service]) != len(original_mappings):
                changed = True

        if changed:
            with open(router_config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)

    except Exception as e:
        print(f"清理路由配置引用失败: {e}")


def _cleanup_loadbalance_config_references(service: str, deleted_configs: set) -> None:
    """清理负载均衡配置中对已删除配置的引用"""
    lb_config_file = DATA_DIR / 'lb_config.json'
    if not lb_config_file.exists():
        return

    try:
        with open(lb_config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)

        changed = False
        service_config = config.get('services', {}).get(service, {})

        # 清理 currentFailures 中的配置引用
        current_failures = service_config.get('currentFailures', {})
        new_failures = {
            config_name: count for config_name, count in current_failures.items()
            if config_name not in deleted_configs
        }
        if len(new_failures) != len(current_failures):
            service_config['currentFailures'] = new_failures
            changed = True

        # 清理 excludedConfigs 中的配置引用
        excluded_configs = service_config.get('excludedConfigs', [])
        new_excluded = [
            config_name for config_name in excluded_configs
            if config_name not in deleted_configs
        ]
        if len(new_excluded) != len(excluded_configs):
            service_config['excludedConfigs'] = new_excluded
            changed = True

        if changed:
            config.setdefault('services', {})[service] = service_config
            with open(lb_config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)

    except Exception as e:
        print(f"清理负载均衡配置引用失败: {e}")


def _cleanup_loadbalance_for_deleted(service: str, configs: Dict[str, Any]) -> None:
    """清理负载均衡中对逻辑删除配置的引用（currentFailures/excludedConfigs）"""
    lb_config_file = DATA_DIR / 'lb_config.json'
    if not lb_config_file.exists():
        return

    try:
        deleted_names = {
            name for name, cfg in (configs or {}).items()
            if isinstance(cfg, dict) and bool(cfg.get('deleted'))
        }
        if not deleted_names:
            return

        _cleanup_loadbalance_for_names(service, deleted_names)
    except Exception as e:
        print(f"清理负载均衡逻辑删除引用失败: {e}")


def _cleanup_loadbalance_for_names(service: str, names: set[str]) -> None:
    lb_config_file = DATA_DIR / 'lb_config.json'
    if not lb_config_file.exists() or not names:
        return
    try:
        with open(lb_config_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        services = data.get('services', {})
        service_config = services.get(service, {})
        if not service_config:
            return
        changed = False
        current_failures = service_config.get('currentFailures', {}) or {}
        for name in list(current_failures.keys()):
            if name in names:
                current_failures.pop(name, None)
                changed = True
        if changed:
            service_config['currentFailures'] = current_failures
        excluded_configs = service_config.get('excludedConfigs', []) or []
        filtered_excluded = [n for n in excluded_configs if n not in names]
        if len(filtered_excluded) != len(excluded_configs):
            service_config['excludedConfigs'] = filtered_excluded
            changed = True
        if changed:
            data.setdefault('services', {})[service] = service_config
            with open(lb_config_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _apply_channel_renames(service: str, rename_map: Dict[str, str]) -> None:
    if not rename_map:
        return
    _rename_history_channels(service, rename_map)
    _rename_log_channels(service, rename_map)
    _sync_router_config_names(service, rename_map)
    _sync_loadbalance_config_names(service, rename_map)


def _compute_log_id(entry: Dict[str, Any], raw_line: str, index: int) -> str:
    """Ensure a log entry has a stable identifier for UI lookups."""
    existing = entry.get('id')
    if isinstance(existing, str) and existing:
        return existing

    digest = hashlib.md5(raw_line.encode('utf-8')).hexdigest()
    return f'legacy-{digest}-{index}'


def load_logs() -> list[Dict[str, Any]]:
    logs: list[Dict[str, Any]] = []
    log_path = LOG_FILE if LOG_FILE.exists() else (
        OLD_LOG_FILE if OLD_LOG_FILE.exists() else None
    )
    if log_path is None:
        return logs

    with open(log_path, 'r', encoding='utf-8') as f:
        for index, raw_line in enumerate(f):
            line = raw_line.strip()
            if not line:
                continue
            entry = _safe_json_load(line)
            if not entry:
                continue
            service = entry.get('service') or entry.get('usage', {}).get('service') or 'unknown'
            entry['usage'] = normalize_usage_record(service, entry.get('usage'))
            entry['id'] = _compute_log_id(entry, raw_line, index)
            logs.append(entry)
    return logs


def _load_auth_tokens_map() -> Dict[str, Dict[str, Any]]:
    """载入 auth.json 中的 token 映射，键为 token 字符串。"""
    try:
        from src.auth.auth_manager import AuthManager  # 延迟导入避免循环依赖
    except ImportError:
        return {}

    try:
        manager = AuthManager()
        tokens = manager.list_tokens()
    except Exception:
        return {}

    mapping: Dict[str, Dict[str, Any]] = {}
    for entry in tokens or []:
        if not isinstance(entry, dict):
            continue
        token_value = entry.get('token')
        if not isinstance(token_value, str) or not token_value:
            continue
        name = entry.get('name')
        if not isinstance(name, str) or not name:
            # 回退到截断 token 值但隐藏主体
            suffix = token_value[-6:] if len(token_value) >= 6 else token_value
            name = f'令牌({suffix})'
        services_field = entry.get('services')
        normalized_services: Set[str] = set()
        if isinstance(services_field, list):
            for svc in services_field:
                if isinstance(svc, str):
                    normalized_services.add(svc.strip().lower())
        elif isinstance(services_field, str):
            normalized_services.add(services_field.strip().lower())
        if not normalized_services:
            normalized_services = {'ui', 'claude', 'codex'}
        mapping[token_value] = {
            'name': name,
            'services': normalized_services,
            'active': bool(entry.get('active', True)),
        }
    return mapping


def _extract_client_token(entry: Dict[str, Any]) -> str:
    """从日志条目中提取调用方 token 字符串。"""
    headers = entry.get('original_headers') or {}
    if isinstance(headers, dict):
        lowered = {}
        for key, value in headers.items():
            if isinstance(key, str):
                lowered[key.lower()] = value

        auth_header = lowered.get('authorization')
        if isinstance(auth_header, str) and auth_header.lower().startswith('bearer '):
            candidate = auth_header[7:].strip()
            if candidate.startswith('clp_'):
                return candidate

        api_key_header = lowered.get('x-api-key')
        if isinstance(api_key_header, str) and api_key_header.startswith('clp_'):
            return api_key_header
    return ''


def _clone_usage_by_token_map(data: Dict[str, Dict[str, Dict[str, Dict[str, int]]]]) -> Dict[str, Dict[str, Dict[str, Dict[str, int]]]]:
    """深拷贝 token usage 结构，避免原地修改。"""
    return {
        token: {
            service: {
                channel: dict(metrics)
                for channel, metrics in channels.items()
            }
            for service, channels in services.items()
        }
        for token, services in data.items()
    }


def aggregate_usage_by_token_from_logs(
    logs: list[Dict[str, Any]],
    token_map: Dict[str, Dict[str, Any]]
) -> Dict[str, Dict[str, Dict[str, Dict[str, int]]]]:
    """
    将日志根据调用方 token 分组，结构：token_name -> service -> channel -> metrics
    """
    aggregated: Dict[str, Dict[str, Dict[str, Dict[str, int]]]] = {}

    for entry in logs:
        usage = entry.get('usage', {})
        metrics = usage.get('metrics', {})
        if not metrics:
            continue

        service = (usage.get('service') or entry.get('service') or 'unknown').strip().lower()
        if service not in {'claude', 'codex'}:
            continue
        channel = entry.get('channel') or 'unknown'

        token_value = _extract_client_token(entry)
        if token_value:
            token_info = token_map.get(token_value)
            if token_info:
                display_name = token_info.get('name') or token_value[-6:]
                allowed_services = token_info.get('services') or {'claude', 'codex'}
                if service and allowed_services and service not in allowed_services:
                    continue
            else:
                suffix = token_value[-6:] if len(token_value) >= 6 else token_value
                display_name = f'未登记({suffix})'
        else:
            display_name = '匿名访问'
            token_info = None

        token_bucket = aggregated.setdefault(display_name, {})
        service_bucket = token_bucket.setdefault(service, {})
        channel_bucket = service_bucket.setdefault(channel, empty_metrics())
        merge_usage_metrics(channel_bucket, metrics)

    return aggregated


def build_log_summary(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Return a lightweight projection of a log entry for list views."""
    return {
        'id': entry.get('id'),
        'timestamp': entry.get('timestamp'),
        'service': entry.get('service'),
        'channel': entry.get('channel'),
        'method': entry.get('method'),
        'path': entry.get('path'),
        'status_code': entry.get('status_code'),
        'duration_ms': entry.get('duration_ms'),
        'usage': entry.get('usage'),
        'response_truncated': entry.get('response_truncated', False),
    }


def load_history_usage() -> Dict[str, Dict[str, Dict[str, int]]]:
    if not HISTORY_FILE.exists():
        return {}
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}

    history: Dict[str, Dict[str, Dict[str, int]]] = {}
    for service, channels in (data or {}).items():
        if not isinstance(channels, dict):
            continue
        service_bucket: Dict[str, Dict[str, int]] = {}
        for channel, metrics in channels.items():
            normalized = empty_metrics()
            if isinstance(metrics, dict):
                merge_usage_metrics(normalized, metrics)
            service_bucket[channel] = normalized
        history[service] = service_bucket
    return history


def save_history_usage(data: Dict[str, Dict[str, Dict[str, int]]]) -> None:
    serializable = {
        service: {
            channel: {key: int(value) for key, value in metrics.items()}
            for channel, metrics in channels.items()
        }
        for service, channels in data.items()
    }
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)


def load_history_usage_by_token() -> Dict[str, Dict[str, Dict[str, Dict[str, int]]]]:
    if not HISTORY_TOKENS_FILE.exists():
        return {}
    try:
        with open(HISTORY_TOKENS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}

    history: Dict[str, Dict[str, Dict[str, Dict[str, int]]]] = {}
    for token, services in (data or {}).items():
        if not isinstance(services, dict):
            continue
        token_bucket: Dict[str, Dict[str, Dict[str, int]]] = {}
        for service, channels in services.items():
            if not isinstance(channels, dict):
                continue
            service_bucket: Dict[str, Dict[str, int]] = {}
            for channel, metrics in channels.items():
                normalized = empty_metrics()
                if isinstance(metrics, dict):
                    merge_usage_metrics(normalized, metrics)
                service_bucket[channel] = normalized
            token_bucket[service] = service_bucket
        history[token] = token_bucket
    return history


def save_history_usage_by_token(data: Dict[str, Dict[str, Dict[str, Dict[str, int]]]]) -> None:
    serializable = {
        token: {
            service: {
                channel: {key: int(value) for key, value in metrics.items()}
                for channel, metrics in channels.items()
            }
            for service, channels in services.items()
        }
        for token, services in data.items()
    }
    with open(HISTORY_TOKENS_FILE, 'w', encoding='utf-8') as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)


def aggregate_usage_from_logs(logs: list[Dict[str, Any]]) -> Dict[str, Dict[str, Dict[str, int]]]:
    aggregated: Dict[str, Dict[str, Dict[str, int]]] = {}
    for entry in logs:
        usage = entry.get('usage', {})
        metrics = usage.get('metrics', {})
        if not metrics:
            continue
        service = usage.get('service') or entry.get('service') or 'unknown'
        channel = entry.get('channel') or 'unknown'
        service_bucket = aggregated.setdefault(service, {})
        channel_bucket = service_bucket.setdefault(channel, empty_metrics())
        merge_usage_metrics(channel_bucket, metrics)
    return aggregated


def merge_history_usage(base: Dict[str, Dict[str, Dict[str, int]]],
                        addition: Dict[str, Dict[str, Dict[str, int]]]) -> Dict[str, Dict[str, Dict[str, int]]]:
    for service, channels in addition.items():
        service_bucket = base.setdefault(service, {})
        for channel, metrics in channels.items():
            channel_bucket = service_bucket.setdefault(channel, empty_metrics())
            merge_usage_metrics(channel_bucket, metrics)
    return base


def merge_history_usage_by_token(
    base: Dict[str, Dict[str, Dict[str, Dict[str, int]]]],
    addition: Dict[str, Dict[str, Dict[str, Dict[str, int]]]]
) -> Dict[str, Dict[str, Dict[str, Dict[str, int]]]]:
    for token, services in addition.items():
        token_bucket = base.setdefault(token, {})
        for service, channels in services.items():
            service_bucket = token_bucket.setdefault(service, {})
            for channel, metrics in channels.items():
                channel_bucket = service_bucket.setdefault(channel, empty_metrics())
                merge_usage_metrics(channel_bucket, metrics)
    return base


def combine_usage_maps(current: Dict[str, Dict[str, Dict[str, int]]],
                       history: Dict[str, Dict[str, Dict[str, int]]]) -> Dict[str, Dict[str, Dict[str, int]]]:
    combined: Dict[str, Dict[str, Dict[str, int]]] = {}
    services = set(current.keys()) | set(history.keys())
    for service in services:
        combined_channels: Dict[str, Dict[str, int]] = {}
        current_channels = current.get(service, {})
        history_channels = history.get(service, {})
        all_channels = set(current_channels.keys()) | set(history_channels.keys())
        for channel in all_channels:
            metrics = empty_metrics()
            if channel in current_channels:
                merge_usage_metrics(metrics, current_channels[channel])
            if channel in history_channels:
                merge_usage_metrics(metrics, history_channels[channel])
            combined_channels[channel] = metrics
        combined[service] = combined_channels
    return combined


def compute_total_metrics(channels_map: Dict[str, Dict[str, int]]) -> Dict[str, int]:
    totals = empty_metrics()
    for metrics in channels_map.values():
        merge_usage_metrics(totals, metrics)
    return totals


def format_metrics(metrics: Dict[str, int]) -> Dict[str, str]:
    return {key: format_usage_value(metrics.get(key, 0)) for key in METRIC_KEYS}


def build_usage_snapshot() -> Dict[str, Any]:
    logs = load_logs()
    current_usage = aggregate_usage_from_logs(logs)
    history_usage = load_history_usage()
    combined_usage = combine_usage_maps(current_usage, history_usage)
    return {
        'logs': logs,
        'current_usage': current_usage,
        'history_usage': history_usage,
        'combined_usage': combined_usage
    }

@app.route('/')
def index():
    """返回主页"""
    index_file = STATIC_DIR / 'index.html'
    return send_file(index_file)

@app.route('/static/<path:filename>')
def static_files(filename):
    """返回静态文件"""
    return send_file(STATIC_DIR / filename)

@app.route('/api/status')
def get_status():
    """获取服务状态"""
    try:
        # 直接获取实时服务状态，不依赖status.json文件
        from src.claude import ctl as claude
        from src.codex import ctl as codex
        from src.config.cached_config_manager import claude_config_manager, codex_config_manager
        
        claude_running = claude.is_running()
        claude_pid = claude.get_pid() if claude_running else None
        claude_config = claude_config_manager.active_config
        
        codex_running = codex.is_running()
        codex_pid = codex.get_pid() if codex_running else None
        codex_config = codex_config_manager.active_config
        
        # 计算配置数量
        claude_configs = len(claude_config_manager.configs)
        codex_configs = len(codex_config_manager.configs)
        total_configs = claude_configs + codex_configs
        
        usage_snapshot = build_usage_snapshot()
        logs = usage_snapshot['logs']
        request_count = len(logs)
        combined_usage = usage_snapshot['combined_usage']

        service_usage_totals: Dict[str, Dict[str, int]] = {}
        for service_name, channels in combined_usage.items():
            service_usage_totals[service_name] = compute_total_metrics(channels)

        for expected_service in ('claude', 'codex'):
            service_usage_totals.setdefault(expected_service, empty_metrics())

        overall_totals = empty_metrics()
        for totals in service_usage_totals.values():
            merge_usage_metrics(overall_totals, totals)

        usage_summary = {
            'totals': overall_totals,
            'formatted_totals': format_metrics(overall_totals),
            'per_service': {
                service: {
                    'metrics': totals,
                    'formatted': format_metrics(totals)
                }
                for service, totals in service_usage_totals.items()
            }
        }
        
        # 计算过滤规则数量
        filter_file = Path.home() / '.clp' / 'filter.json'
        filter_count = 0
        if filter_file.exists():
            try:
                with open(filter_file, 'r', encoding='utf-8') as f:
                    filter_data = json.load(f)
                    if isinstance(filter_data, list):
                        filter_count = len(filter_data)
                    elif isinstance(filter_data, dict):
                        filter_count = 1
            except (json.JSONDecodeError, IOError):
                filter_count = 0

        # 计算 Header Filter 配置数量
        header_filter_file = Path.home() / '.clp' / 'header_filter.json'
        header_filter_count = 0
        if header_filter_file.exists():
            try:
                with open(header_filter_file, 'r', encoding='utf-8') as f:
                    header_filter_data = json.load(f)
                    if header_filter_data.get('enabled') and isinstance(header_filter_data.get('blocked_headers'), list):
                        header_filter_count = len(header_filter_data['blocked_headers'])
            except (json.JSONDecodeError, IOError):
                header_filter_count = 0

        data = {
            'services': {
                'claude': {
                    'running': claude_running,
                    'pid': claude_pid,
                    'config': claude_config
                },
                'codex': {
                    'running': codex_running,
                    'pid': codex_pid,
                    'config': codex_config
                }
            },
            'request_count': request_count,
            'config_count': total_configs,
            'filter_count': filter_count,
            'header_filter_count': header_filter_count,
            'last_updated': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'usage_summary': usage_summary
        }
        
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/<service>', methods=['GET'])
def get_config(service):
    """获取配置文件内容"""
    try:
        if service not in ['claude', 'codex']:
            return jsonify({'error': 'Invalid service name'}), 400
        
        config_file = Path.home() / '.clp' / f'{service}.json'
        config_file.parent.mkdir(parents=True, exist_ok=True)

        if not config_file.exists():
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False, indent=2)

        content = config_file.read_text(encoding='utf-8')
        if not content.strip():
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False, indent=2)
            content = config_file.read_text(encoding='utf-8')

        return jsonify({'content': content})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/config/<service>', methods=['POST'])
def save_config(service):
    """保存配置文件内容"""
    try:
        if service not in ['claude', 'codex']:
            return jsonify({'error': 'Invalid service name'}), 400
        
        data = request.get_json()
        content = data.get('content', '')

        if not content:
            return jsonify({'error': 'Content cannot be empty'}), 400

        # 验证JSON格式
        try:
            new_configs = json.loads(content)
        except json.JSONDecodeError as e:
            return jsonify({'error': f'Invalid JSON format: {str(e)}'}), 400

        if not isinstance(new_configs, dict):
            return jsonify({'error': '配置文件必须是对象类型'}), 400

        _normalize_deleted_flags(new_configs)
        normalized_content = json.dumps(new_configs, ensure_ascii=False, indent=2)

        config_file = Path.home() / '.clp' / f'{service}.json'
        old_content = None
        old_configs: Dict[str, Any] = {}

        if config_file.exists():
            with open(config_file, 'r', encoding='utf-8') as f:
                old_content = f.read()
            try:
                old_configs = json.loads(old_content)
            except json.JSONDecodeError:
                old_configs = {}

        rename_map = _detect_config_renames(old_configs, new_configs)

        try:
            # 直接写入新内容
            with open(config_file, 'w', encoding='utf-8') as f:
                f.write(normalized_content)

            _apply_channel_renames(service, rename_map)
            _cleanup_deleted_configs(service, old_configs, new_configs)

            # 逻辑删除清理负载均衡引用
            _cleanup_loadbalance_for_deleted(service, new_configs)

            # 复原启用（从 deleted=true -> false）的配置也清理负载均衡历史
            reenabled = set()
            for name, old_cfg in (old_configs or {}).items():
                new_cfg = (new_configs or {}).get(name, {})
                if isinstance(old_cfg, dict) and isinstance(new_cfg, dict):
                    old_del = _coerce_bool(old_cfg.get('deleted', False))
                    new_del = _coerce_bool(new_cfg.get('deleted', False))
                    if old_del and not new_del:
                        reenabled.add(name)
            if reenabled:
                _cleanup_loadbalance_for_names(service, reenabled)
        except Exception as exc:
            # 恢复旧配置，避免部分成功
            if old_content is not None:
                with open(config_file, 'w', encoding='utf-8') as f:
                    f.write(old_content)
            else:
                config_file.unlink(missing_ok=True)
            return jsonify({'error': f'配置保存失败: {exc}'}), 500

        return jsonify({'success': True, 'message': f'{service}配置保存成功'})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/filter', methods=['GET'])
def get_filter():
    """获取过滤规则文件内容"""
    try:
        filter_file = Path.home() / '.clp' / 'filter.json'
        
        if not filter_file.exists():
            # 创建默认的过滤规则文件
            default_content = '[\n  {\n    "source": "example_text",\n    "target": "replacement_text",\n    "op": "replace"\n  }\n]'
            return jsonify({'content': default_content})
        
        with open(filter_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return jsonify({'content': content})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/filter', methods=['POST'])
def save_filter():
    """保存过滤规则文件内容"""
    try:
        data = request.get_json()
        content = data.get('content', '')
        
        if not content:
            return jsonify({'error': 'Content cannot be empty'}), 400
        
        # 验证JSON格式
        try:
            filter_data = json.loads(content)
            # 验证过滤规则格式
            if isinstance(filter_data, list):
                for rule in filter_data:
                    if not isinstance(rule, dict):
                        return jsonify({'error': 'Each filter rule must be an object'}), 400
                    if 'source' not in rule or 'op' not in rule:
                        return jsonify({'error': 'Each rule must have "source" and "op" fields'}), 400
                    if rule['op'] not in ['replace', 'remove']:
                        return jsonify({'error': 'op must be "replace" or "remove"'}), 400
                    if rule['op'] == 'replace' and 'target' not in rule:
                        return jsonify({'error': 'replace operation requires "target" field'}), 400
            elif isinstance(filter_data, dict):
                if 'source' not in filter_data or 'op' not in filter_data:
                    return jsonify({'error': 'Rule must have "source" and "op" fields'}), 400
                if filter_data['op'] not in ['replace', 'remove']:
                    return jsonify({'error': 'op must be "replace" or "remove"'}), 400
                if filter_data['op'] == 'replace' and 'target' not in filter_data:
                    return jsonify({'error': 'replace operation requires "target" field'}), 400
            else:
                return jsonify({'error': 'Filter data must be an object or array of objects'}), 400
                
        except json.JSONDecodeError as e:
            return jsonify({'error': f'Invalid JSON format: {str(e)}'}), 400
        
        filter_file = Path.home() / '.clp' / 'filter.json'
        
        # 直接写入新内容，不进行备份
        with open(filter_file, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return jsonify({'success': True, 'message': '过滤规则保存成功'})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/header-filter', methods=['GET'])
def get_header_filter():
    """获取 Header 过滤配置"""
    try:
        filter_file = Path.home() / '.clp' / 'header_filter.json'

        if not filter_file.exists():
            default_config = {
                'enabled': True,
                'blocked_headers': [
                    'x-forwarded-for',
                    'x-forwarded-proto',
                    'x-forwarded-scheme',
                    'x-real-ip',
                    'x-forwarded-host',
                    'x-forwarded-port'
                ]
            }
            return jsonify({'config': default_config})

        with open(filter_file, 'r', encoding='utf-8') as f:
            config = json.load(f)

        return jsonify({'config': config})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/header-filter', methods=['POST'])
def save_header_filter():
    """保存 Header 过滤配置"""
    try:
        data = request.get_json()

        if not data:
            return jsonify({'error': 'No configuration data provided'}), 400

        if 'enabled' not in data or 'blocked_headers' not in data:
            return jsonify({'error': 'Missing required fields'}), 400

        if not isinstance(data['blocked_headers'], list):
            return jsonify({'error': 'blocked_headers must be an array'}), 400

        normalized_headers = [h.lower().strip() for h in data['blocked_headers'] if h and h.strip()]

        config = {
            'enabled': bool(data['enabled']),
            'blocked_headers': normalized_headers
        }

        filter_file = Path.home() / '.clp' / 'header_filter.json'

        with open(filter_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

        return jsonify({'success': True, 'message': 'Header 过滤配置保存成功'})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/logs')
def get_logs():
    """获取请求日志"""
    try:
        logs = load_logs()
        return jsonify(logs[-10:][::-1])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/logs/all')
def get_all_logs():
    """获取所有请求日志"""
    try:
        logs = load_logs()
        summaries = [build_log_summary(entry) for entry in logs]
        summaries.reverse()
        return jsonify(summaries[:100])
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/logs/<log_id>')
def get_log_detail(log_id: str):
    """按ID获取单条请求日志详情"""
    try:
        logs = load_logs()
        for entry in reversed(logs):
            if entry.get('id') == log_id:
                return jsonify(entry)
        return jsonify({'error': 'Log not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/logs', methods=['DELETE'])
def clear_logs():
    """清空所有日志"""
    try:
        logs = load_logs()
        if logs:
            aggregated = aggregate_usage_from_logs(logs)
            if aggregated:
                history_usage = load_history_usage()
                merged = merge_history_usage(history_usage, aggregated)
                save_history_usage(merged)

            # 同步合并到 token 维度的历史，避免“清空日志”后丢失令牌累计
            token_map = _load_auth_tokens_map()
            token_aggregated = aggregate_usage_by_token_from_logs(logs, token_map)
            if token_aggregated:
                history_usage_tokens = load_history_usage_by_token()
                merged_tokens = merge_history_usage_by_token(history_usage_tokens, token_aggregated)
                save_history_usage_by_token(merged_tokens)

        log_path = LOG_FILE if LOG_FILE.exists() else (
            OLD_LOG_FILE if OLD_LOG_FILE.exists() else LOG_FILE
        )
        log_path.write_text('', encoding='utf-8')
        if log_path != LOG_FILE:
            LOG_FILE.touch(exist_ok=True)
        
        return jsonify({'success': True, 'message': '日志已清空'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/usage/details')
def get_usage_details():
    """返回合并后的usage明细"""
    try:
        snapshot = build_usage_snapshot()
        combined_usage = snapshot['combined_usage']
        logs = snapshot['logs']

        services_payload: Dict[str, Any] = {}
        for service, channels in combined_usage.items():
            overall_metrics = compute_total_metrics(channels)
            services_payload[service] = {
                'overall': {
                    'metrics': overall_metrics,
                    'formatted': format_metrics(overall_metrics)
                },
                'channels': {
                    channel: {
                        'metrics': metrics,
                        'formatted': format_metrics(metrics)
                    }
                    for channel, metrics in channels.items()
                }
            }

        totals_metrics = empty_metrics()
        for service_data in services_payload.values():
            merge_usage_metrics(totals_metrics, service_data['overall']['metrics'])

        token_map = _load_auth_tokens_map()
        current_usage_by_token = aggregate_usage_by_token_from_logs(logs, token_map)
        history_usage_by_token = load_history_usage_by_token()
        combined_usage_by_token = merge_history_usage_by_token(
            _clone_usage_by_token_map(history_usage_by_token),
            current_usage_by_token
        )

        tokens_payload: Dict[str, Any] = {}
        for token_name, services_map in combined_usage_by_token.items():
            service_blocks: Dict[str, Any] = {}
            token_totals = empty_metrics()
            for service_name, channels_map in services_map.items():
                overall_metrics = compute_total_metrics(channels_map)
                service_blocks[service_name] = {
                    'overall': {
                        'metrics': overall_metrics,
                        'formatted': format_metrics(overall_metrics)
                    },
                    'channels': {
                        channel: {
                            'metrics': metrics,
                            'formatted': format_metrics(metrics)
                        }
                        for channel, metrics in channels_map.items()
                    }
                }
                merge_usage_metrics(token_totals, overall_metrics)

            if not any(token_totals.values()):
                continue

            tokens_payload[token_name] = {
                'totals': {
                    'metrics': token_totals,
                    'formatted': format_metrics(token_totals)
                },
                'services': service_blocks
            }

        response = {
            'totals': {
                'metrics': totals_metrics,
                'formatted': format_metrics(totals_metrics)
            },
            'services': services_payload,
            'tokens': tokens_payload
        }
        return jsonify(response)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/usage/clear', methods=['DELETE'])
def clear_usage():
    """清空Token使用记录"""
    try:
        # 1. 先清空日志（复用现有功能）
        logs = load_logs()
        token_map = _load_auth_tokens_map()
        if logs:
            aggregated = aggregate_usage_from_logs(logs)
            if aggregated:
                history_usage = load_history_usage()
                merged = merge_history_usage(history_usage, aggregated)
                save_history_usage(merged)
            token_aggregated = aggregate_usage_by_token_from_logs(logs, token_map)
            if token_aggregated:
                history_usage_tokens = load_history_usage_by_token()
                merged_tokens = merge_history_usage_by_token(history_usage_tokens, token_aggregated)
                save_history_usage_by_token(merged_tokens)

        log_path = LOG_FILE if LOG_FILE.exists() else (
            OLD_LOG_FILE if OLD_LOG_FILE.exists() else LOG_FILE
        )
        log_path.write_text('', encoding='utf-8')
        if log_path != LOG_FILE:
            LOG_FILE.touch(exist_ok=True)

        # 2. 清空 history_usage.json 中的所有数值
        history_usage = load_history_usage()
        for service in history_usage:
            for channel in history_usage[service]:
                for key in history_usage[service][channel]:
                    history_usage[service][channel][key] = 0
        save_history_usage(history_usage)

        history_usage_tokens = load_history_usage_by_token()
        for token in history_usage_tokens:
            for service in history_usage_tokens[token]:
                for channel in history_usage_tokens[token][service]:
                    for key in history_usage_tokens[token][service][channel]:
                        history_usage_tokens[token][service][channel][key] = 0
        save_history_usage_by_token(history_usage_tokens)

        return jsonify({'success': True, 'message': 'Token使用记录已清空'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/switch-config', methods=['POST'])
def switch_config():
    """切换激活配置"""
    try:
        data = request.get_json()
        service = data.get('service')
        config = data.get('config')

        if not service or not config:
            return jsonify({'error': 'Missing service or config parameter'}), 400

        if service not in ['claude', 'codex']:
            return jsonify({'error': 'Invalid service name'}), 400

        # 导入对应的配置管理器
        if service == 'claude':
            from src.config.cached_config_manager import claude_config_manager as config_manager
        else:
            from src.config.cached_config_manager import codex_config_manager as config_manager

        # 切换配置
        if config_manager.set_active_config(config):
            # 验证配置确实已切换
            actual_config = config_manager.active_config
            if actual_config == config:
                return jsonify({
                    'success': True,
                    'message': f'{service}配置已切换到: {config}',
                    'active_config': actual_config
                })
            else:
                return jsonify({
                    'success': False,
                    'message': f'配置切换验证失败，当前配置: {actual_config}'
                })
        else:
            return jsonify({'success': False, 'message': f'配置{config}不存在'})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/routing/config', methods=['GET'])
def get_routing_config():
    """获取模型路由配置"""
    try:
        routing_config_file = DATA_DIR / 'model_router_config.json'
        
        # 如果配置文件不存在，返回默认配置
        if not routing_config_file.exists():
            default_config = {
                'mode': 'default',
                'modelMappings': {
                    'claude': [],
                    'codex': []
                },
                'configMappings': {
                    'claude': [],
                    'codex': []
                }
            }
            return jsonify({'config': default_config})
        
        with open(routing_config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        return jsonify({'config': config})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/routing/config', methods=['POST'])
def save_routing_config():
    """保存模型路由配置"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No configuration data provided'}), 400
        
        # 验证配置格式
        required_fields = ['mode', 'modelMappings', 'configMappings']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        # 验证模式
        if data['mode'] not in ['default', 'model-mapping', 'config-mapping']:
            return jsonify({'error': 'Invalid routing mode'}), 400
        
        # 验证映射格式
        for service in ['claude', 'codex']:
            if service not in data['modelMappings']:
                data['modelMappings'][service] = []
            if service not in data['configMappings']:
                data['configMappings'][service] = []
        
        routing_config_file = DATA_DIR / 'model_router_config.json'
        
        # 保存配置
        with open(routing_config_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        return jsonify({'success': True, 'message': '路由配置保存成功'})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/test-connection', methods=['POST'])
def test_connection():
    """测试API端点连通性"""
    try:
        data = request.get_json()
        service = data.get('service')
        model = data.get('model')
        base_url = data.get('base_url')
        auth_token = data.get('auth_token')
        api_key = data.get('api_key')
        extra_params = data.get('extra_params', {})

        # 参数验证
        if not service:
            return jsonify({'error': 'Missing service parameter'}), 400
        if not model:
            return jsonify({'error': 'Missing model parameter'}), 400
        if not base_url:
            return jsonify({'error': 'Missing base_url parameter'}), 400

        if service not in ['claude', 'codex']:
            return jsonify({'error': 'Invalid service name'}), 400

        # 验证至少有一种认证方式
        if not auth_token and not api_key:
            return jsonify({'error': 'Missing authentication (auth_token or api_key)'}), 400

        # 获取对应的proxy实例
        if service == 'claude':
            from src.claude.proxy import proxy_service
        else:
            from src.codex.proxy import proxy_service

        # 调用测试方法
        result = proxy_service.test_endpoint(
            model=model,
            base_url=base_url,
            auth_token=auth_token,
            api_key=api_key,
            extra_params=extra_params
        )

        return jsonify(result)

    except Exception as e:
        return jsonify({
            'success': False,
            'status_code': None,
            'response_text': str(e),
            'target_url': None,
            'error_message': str(e)
        }), 500

@app.route('/api/loadbalance/config', methods=['GET'])
def get_loadbalance_config():
    """获取负载均衡配置"""
    try:
        lb_config_file = DATA_DIR / 'lb_config.json'

        def default_section():
            return {
                'failureThreshold': 3,
                'currentFailures': {},
                'excludedConfigs': []
            }

        default_config = {
            'mode': 'active-first',
            'options': {
                'autoResetOnAllFailed': True,
                'resetCooldownSeconds': 30,
                'notifyEnabled': True,
                'failureThreshold': 3,
            },
            'services': {
                'claude': default_section(),
                'codex': default_section()
            }
        }

        if not lb_config_file.exists():
            return jsonify({'config': default_config})

        with open(lb_config_file, 'r', encoding='utf-8') as f:
            raw_config = json.load(f)

        config = {
            'mode': raw_config.get('mode', 'active-first'),
            'options': {
                'autoResetOnAllFailed': bool(raw_config.get('options', {}).get('autoResetOnAllFailed', True)),
                'notifyEnabled': bool(raw_config.get('options', {}).get('notifyEnabled', True)),
                'resetCooldownSeconds': int(raw_config.get('options', {}).get('resetCooldownSeconds', 30) or 30),
                'failureThreshold': int(raw_config.get('options', {}).get('failureThreshold', 3) or 3),
            },
            'services': {
                'claude': default_section(),
                'codex': default_section()
            }
        }

        for service in ['claude', 'codex']:
            section = raw_config.get('services', {}).get(service, {})
            threshold = section.get('failureThreshold', section.get('failover_count', 3))
            try:
                threshold = int(threshold)
                if threshold <= 0:
                    threshold = 3
            except (TypeError, ValueError):
                threshold = 3

            failures = section.get('currentFailures', section.get('current_failures', {}))
            if not isinstance(failures, dict):
                failures = {}
            normalized_failures = {}
            for name, count in failures.items():
                try:
                    numeric = int(count)
                except (TypeError, ValueError):
                    numeric = 0
                normalized_failures[str(name)] = max(numeric, 0)

            excluded = section.get('excludedConfigs', section.get('excluded_configs', []))
            if not isinstance(excluded, list):
                excluded = []
            normalized_excluded = [str(item) for item in excluded if isinstance(item, str)]

            config['services'][service] = {
                'failureThreshold': threshold,
                'currentFailures': normalized_failures,
                'excludedConfigs': normalized_excluded,
            }

        # 若存在全局阈值，应用到各服务，保持前端展示一致
        options_threshold = config['options']['failureThreshold']
        for service in ['claude', 'codex']:
            config['services'][service]['failureThreshold'] = options_threshold

        return jsonify({'config': config})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/loadbalance/config', methods=['POST'])
def save_loadbalance_config():
    """保存负载均衡配置"""
    try:
        data = request.get_json()

        if not data:
            return jsonify({'error': 'No configuration data provided'}), 400

        mode = data.get('mode')
        if mode not in ['active-first', 'weight-based']:
            return jsonify({'error': 'Invalid loadbalance mode'}), 400

        services = data.get('services', {})
        normalized = {
            'mode': mode,
            'options': {
                'autoResetOnAllFailed': bool(data.get('options', {}).get('autoResetOnAllFailed', True)),
                'notifyEnabled': bool(data.get('options', {}).get('notifyEnabled', True)),
            },
            'services': {}
        }

        # 限制冷却秒数为正整数
        try:
            cooldown = int(data.get('options', {}).get('resetCooldownSeconds', 30) or 30)
            if cooldown <= 0:
                cooldown = 30
        except Exception:
            cooldown = 30
        normalized['options']['resetCooldownSeconds'] = cooldown
        try:
            failure_threshold = int(data.get('options', {}).get('failureThreshold', 3) or 3)
            if failure_threshold <= 0:
                failure_threshold = 1
        except Exception:
            failure_threshold = 3
        normalized['options']['failureThreshold'] = failure_threshold

        for service in ['claude', 'codex']:
            section = services.get(service, {})
            threshold = section.get('failureThreshold', 3)
            try:
                threshold = int(threshold)
                if threshold <= 0:
                    threshold = 3
            except (TypeError, ValueError):
                return jsonify({'error': f'Invalid failureThreshold for service {service}'}), 400

            failures = section.get('currentFailures', {})
            if not isinstance(failures, dict):
                return jsonify({'error': f'currentFailures for service {service} must be an object'}), 400
            normalized_failures = {}
            for name, count in failures.items():
                try:
                    numeric = int(count)
                except (TypeError, ValueError):
                    return jsonify({'error': f'Failure count for {service}:{name} must be integer'}), 400
                normalized_failures[str(name)] = max(numeric, 0)

            excluded = section.get('excludedConfigs', [])
            if excluded is None:
                excluded = []
            if not isinstance(excluded, list):
                return jsonify({'error': f'excludedConfigs for service {service} must be an array'}), 400
            normalized_excluded = [str(item) for item in excluded if isinstance(item, str)]

            normalized['services'][service] = {
                'failureThreshold': threshold,
                'currentFailures': normalized_failures,
                'excludedConfigs': normalized_excluded
            }

        lb_config_file = DATA_DIR / 'lb_config.json'

        # 合并写入，保留内部使用的 lastResetAt 等字段
        to_write = {}
        if lb_config_file.exists():
            try:
                with open(lb_config_file, 'r', encoding='utf-8') as f:
                    to_write = json.load(f)
            except Exception:
                to_write = {}
        # 覆盖 mode/options
        to_write['mode'] = normalized['mode']
        to_write['options'] = normalized['options']
        # 覆盖/规范 services 公开字段
        services_out = to_write.setdefault('services', {})
        for svc in ['claude', 'codex']:
            sec_out = services_out.setdefault(svc, {})
            sec_in = normalized['services'][svc]
            sec_out['failureThreshold'] = normalized['options']['failureThreshold']
            sec_out['currentFailures'] = sec_in['currentFailures']
            sec_out['excludedConfigs'] = sec_in['excludedConfigs']
            # 保留 lastResetAt（如果有）
            if 'lastResetAt' not in sec_out:
                sec_out['lastResetAt'] = 0

        with open(lb_config_file, 'w', encoding='utf-8') as f:
            json.dump(to_write, f, ensure_ascii=False, indent=2)

        return jsonify({'success': True, 'message': '负载均衡配置保存成功'})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/loadbalance/reset-failures', methods=['POST'])
def reset_loadbalance_failures():
    """重置负载均衡失败计数"""
    try:
        data = request.get_json()
        service = data.get('service')
        config_name = data.get('config_name')  # 可选，如果不提供则重置所有

        if not service or service not in ['claude', 'codex']:
            return jsonify({'error': 'Invalid service parameter'}), 400

        lb_config_file = DATA_DIR / 'lb_config.json'

        # 如果配置文件不存在，直接返回成功
        if not lb_config_file.exists():
            return jsonify({'success': True, 'message': '无需重置'})

        with open(lb_config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)

        services = config.setdefault('services', {})
        service_config = services.setdefault(service, {
            'failureThreshold': 3,
            'currentFailures': {},
            'excludedConfigs': []
        })

        current_failures = service_config.setdefault('currentFailures', {})
        excluded_configs = service_config.setdefault('excludedConfigs', [])
        # 记录 lastResetAt 以与自动重置的冷却逻辑保持一致
        import time as _time

        if config_name:
            key = str(config_name)
            if key in current_failures:
                current_failures[key] = 0
            if key in excluded_configs:
                excluded_configs.remove(key)
            # 单个配置重置也刷新整体 lastResetAt，避免立刻触发自动重置
            service_config['lastResetAt'] = _time.time()
            message = f'已重置 {service} 服务的 {key} 配置失败计数'
        else:
            service_config['currentFailures'] = {}
            service_config['excludedConfigs'] = []
            service_config['lastResetAt'] = _time.time()
            message = f'已重置 {service} 服务的所有失败计数'

        with open(lb_config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

        return jsonify({'success': True, 'message': message})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

def start_ui_server(port=3300):
    """启动UI服务器并打开浏览器"""
    host = os.getenv('CLP_UI_HOST', '127.0.0.1')
    print(f"启动Web UI服务器在 {host}:{port}")

    # 启动Flask应用
    app.run(host=host, port=port, debug=False)

if __name__ == '__main__':
    start_ui_server()
