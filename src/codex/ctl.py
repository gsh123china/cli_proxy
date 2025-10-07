#!/usr/bin/env python3
"""
Codex服务控制器 - 使用优化后的基础类
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from ..core.base_proxy import BaseServiceController
from ..config.cached_config_manager import codex_config_manager

class CodexController(BaseServiceController):
    """
    Codex服务控制器
    """
    def __init__(self):
        super().__init__(
            service_name='codex',
            port=3211,
            config_manager=codex_config_manager,
            proxy_module_path='src.codex.proxy'
        )

# 创建全局实例
controller = CodexController()

# 兼容性函数（保持原有接口）
def get_pid():
    return controller.get_pid()

def is_running():
    return controller.is_running()

def start():
    return controller.start()

def stop():
    return controller.stop()

def restart():
    return controller.restart()

def status():
    controller.status()

# 兼容旧版本的函数
def start_daemon(port=3211):
    """启动守护进程（兼容旧接口）"""
    return start()

def stop_handler(signum, frame):
    """停止信号处理函数（兼容旧接口）"""
    stop()

config_dir = Path.home() / '.clp/run'
data_dir = Path.home() / '.clp/data'
PID_FILE = controller.pid_file
LOG_FILE = controller.log_file


def _current_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'on'}
    if isinstance(value, (int, float)):
        return bool(value)
    return bool(value)


def _load_config_file() -> Dict[str, Any]:
    path = codex_config_manager.ensure_config_file()
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _normalize_configs(configs: Dict[str, Any]) -> None:
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


def _save_config_file(configs: Dict[str, Any]) -> None:
    _normalize_configs(configs)
    path = codex_config_manager.ensure_config_file()
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(configs, f, ensure_ascii=False, indent=2)
    if hasattr(codex_config_manager, 'force_reload'):
        codex_config_manager.force_reload()


def _cleanup_lb_for_config(config_name: str) -> None:
    lb_file = data_dir / 'lb_config.json'
    if not lb_file.exists():
        return
    try:
        with open(lb_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        services = data.setdefault('services', {})
        section = services.setdefault('codex', {})
        failures = section.get('currentFailures', {}) or {}
        excluded = section.get('excludedConfigs', []) or []
        changed = False
        if config_name in failures:
            failures.pop(config_name, None)
            section['currentFailures'] = failures
            changed = True
        if config_name in excluded:
            section['excludedConfigs'] = [x for x in excluded if x != config_name]
            changed = True
        if changed:
            with open(lb_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        # 清理失败不影响主流程
        pass


def disable_config(config_name: str) -> bool:
    configs = _load_config_file()
    cfg = configs.get(config_name)
    if not isinstance(cfg, dict):
        print(f"配置 {config_name} 不存在")
        return False
    if _coerce_bool(cfg.get('deleted', False)):
        print(f"配置 {config_name} 已处于禁用状态")
        return True
    cfg['deleted'] = True
    cfg['deleted_at'] = _current_utc_iso()
    cfg['active'] = False
    configs[config_name] = cfg
    _save_config_file(configs)
    _cleanup_lb_for_config(config_name)
    print(f"已禁用配置: {config_name}")
    if codex_config_manager.active_config == config_name:
        print("提示: 当前激活配置已被禁用，请使用 `clp active codex <配置名>` 切换。")
    return True


def enable_config(config_name: str) -> bool:
    configs = _load_config_file()
    cfg = configs.get(config_name)
    if not isinstance(cfg, dict):
        print(f"配置 {config_name} 不存在")
        return False
    if not _coerce_bool(cfg.get('deleted', False)):
        print(f"配置 {config_name} 已处于启用状态")
        return True
    cfg.pop('deleted', None)
    cfg.pop('deleted_at', None)
    configs[config_name] = cfg
    _save_config_file(configs)
    # 启用时也清理负载均衡历史条目
    _cleanup_lb_for_config(config_name)
    print(f"已启用配置: {config_name}")
    print(f"提示: 如需使用该配置，请执行 `clp active codex {config_name}`。")
    return True


# 添加缺失的函数
def set_active_config(config_name):
    """设置激活配置"""
    if codex_config_manager.set_active_config(config_name):
        print(f"Codex配置已切换到: {config_name}")
        return True
    else:
        print(f"配置 {config_name} 不存在")
        return False

def list_configs(include_deleted: bool = False):
    """列出配置"""
    all_configs = codex_config_manager.get_all_configs()
    configs = all_configs if include_deleted else codex_config_manager.configs
    active = codex_config_manager.active_config

    if not configs:
        if include_deleted:
            if all_configs:
                print("Codex: 全部配置均已禁用")
            else:
                print("Codex: 没有配置记录")
        else:
            if all_configs:
                print("Codex: 没有启用的配置，使用 --include-deleted 查看已禁用配置")
            else:
                print("Codex: 没有配置记录")
        return

    header = "Codex 全部配置（含已禁用）:" if include_deleted else "Codex 可用配置:"
    print(header)
    for name in sorted(configs.keys()):
        cfg = configs[name]
        deleted = _coerce_bool(cfg.get('deleted', False))
        status_parts = []
        if deleted:
            status_parts.append("已禁用")
            deleted_at = cfg.get('deleted_at')
            if isinstance(deleted_at, str) and deleted_at:
                status_parts.append(f"禁用于 {deleted_at}")
        elif name == active:
            status_parts.append("激活")
        else:
            status_parts.append("备用")

        weight = cfg.get('weight')
        if isinstance(weight, (int, float)) and weight not in (0, None):
            status_parts.append(f"权重 {weight:g}")

        status_text = '，'.join(status_parts)
        marker = '*' if name == active and not deleted else '-'
        print(f"  {marker} {name} ({status_text})")

    if (not include_deleted) and any(_coerce_bool(cfg.get('deleted', False)) for cfg in all_configs.values()):
        print("提示: 使用 `clp list codex --include-deleted` 查看已禁用配置。")
