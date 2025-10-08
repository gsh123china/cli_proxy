#!/usr/bin/env python3
"""
基础代理服务类 - 消除claude和codex的重复代码
提供统一的代理服务实现
"""
import asyncio
import base64
import json
import subprocess
import os
import sys
import threading
import time
import uuid
from collections import deque
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse

from ..utils.usage_parser import (
    extract_usage_from_response,
    normalize_usage_record,
    update_usage_from_sse_chunk,
    process_sse_buffer,
    process_ndjson_buffer,
)
from ..utils.platform_helper import create_detached_process
from .realtime_hub import RealTimeRequestHub

class BaseProxyService(ABC):
    """基础代理服务类"""
    
    def __init__(self, service_name: str, port: int, config_manager):
        """
        初始化代理服务

        Args:
            service_name: 服务名称 (claude/codex)
            port: 服务端口
            config_manager: 配置管理器实例
        """
        self.service_name = service_name
        self.port = port
        self.config_manager = config_manager

        # 初始化路径
        self.config_dir = Path.home() / '.clp/run'
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.pid_file = self.config_dir / f'{service_name}_proxy.pid'
        self.log_file = self.config_dir / f'{service_name}_proxy.log'

        # 数据目录
        self.data_dir = Path.home() / '.clp/data'
        self.data_dir.mkdir(parents=True, exist_ok=True)
        # 按服务拆分日志文件，降低跨进程写入争用
        self.traffic_log = self.data_dir / f'proxy_requests_{self.service_name}.jsonl'

        # 路由配置文件
        self.routing_config_file = self.data_dir / 'model_router_config.json'
        self.routing_config = self._load_routing_config()
        self.routing_config_signature = self._get_file_signature(self.routing_config_file)

        # 负载均衡配置文件
        self.lb_config_file = self.data_dir / 'lb_config.json'
        self.lb_config = self._load_lb_config()
        self.lb_config_signature = self._get_file_signature(self.lb_config_file)

        # 初始化异步HTTP客户端
        self.client = self._create_async_client()

        # 响应日志截断阈值（避免长流占用过多内存）
        self.max_logged_response_bytes = 1024 * 1024  # 1MB

        # 初始化实时事件中心
        self.realtime_hub = RealTimeRequestHub(service_name)

        # 并发控制锁
        self._lb_lock = threading.RLock()
        self._log_lock = threading.RLock()
        self._log_max_entries = 1000
        self._log_cache = deque(maxlen=self._log_max_entries)
        self._log_cache_loaded = False

        # 初始化FastAPI应用
        self.app = FastAPI()
        self._setup_routes()
        self.app.add_event_handler("shutdown", self._shutdown_event)

        # 集成鉴权中间件
        self._setup_auth_middleware()

        # 导入过滤器
        try:
            from ..filter.cached_request_filter import CachedRequestFilter
            self.request_filter = CachedRequestFilter()
        except ImportError:
            # 如果缓存版本不存在，使用原版本
            from ..filter.request_filter import filter_request_data
            self.filter_request_data = filter_request_data
            self.request_filter = None

        # 导入 Header 过滤器
        try:
            from ..filter.cached_header_filter import CachedHeaderFilter
            self.header_filter = CachedHeaderFilter()
        except ImportError as e:
            print(f"警告: Header 过滤器加载失败: {e}")
            self.header_filter = None

        # 导入 Endpoint 过滤器
        try:
            from ..filter.cached_endpoint_filter import CachedEndpointFilter
            self.endpoint_filter = CachedEndpointFilter()
        except ImportError as e:
            print(f"警告: Endpoint 过滤器加载失败: {e}")
            self.endpoint_filter = None
    
    def _create_async_client(self) -> httpx.AsyncClient:
        """创建并配置 httpx AsyncClient"""
        timeout = httpx.Timeout(  # 允许长时间流式响应
            timeout=None,
            connect=30.0,
            read=None,
            write=30.0,
            pool=None,
        )
        limits = httpx.Limits(
            max_connections=200,
            max_keepalive_connections=100,
        )
        return httpx.AsyncClient(timeout=timeout, limits=limits, headers={"Connection": "keep-alive"})

    async def _shutdown_event(self):
        """FastAPI 关闭事件，释放HTTP客户端资源"""
        await self.client.aclose()

    def _setup_routes(self):
        """设置API路由"""
        @self.app.api_route(
            "/{path:path}",
            methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS']
        )
        async def proxy_route(path: str, request: Request):
            return await self.proxy(path, request)

        @self.app.websocket("/ws/realtime")
        async def websocket_endpoint(websocket: WebSocket):
            """WebSocket实时事件端点"""
            await self.realtime_hub.connect(websocket)
            try:
                # 保持连接活跃，等待客户端消息或断开
                while True:
                    # 接收客户端的ping消息，保持连接
                    try:
                        await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                    except asyncio.TimeoutError:
                        # 发送ping消息保持连接
                        await websocket.send_text('{"type":"ping"}')
            except WebSocketDisconnect:
                pass
            except Exception as e:
                print(f"WebSocket连接异常: {e}")
            finally:
                self.realtime_hub.disconnect(websocket)

    def _setup_auth_middleware(self):
        """设置鉴权中间件"""
        try:
            from ..auth.auth_manager import AuthManager
            from ..auth.fastapi_middleware import AuthMiddleware

            # 初始化鉴权管理器
            auth_manager = AuthManager()

            # 添加鉴权中间件
            self.app.add_middleware(
                AuthMiddleware,
                auth_manager=auth_manager,
                service_name=self.service_name,
                whitelist_paths={'/health', '/ping', '/favicon.ico'}
            )
        except ImportError as e:
            # 如果鉴权模块不存在，跳过（向后兼容）
            print(f"警告: 鉴权模块加载失败，将不启用鉴权功能: {e}")
        except Exception as e:
            print(f"警告: 鉴权中间件初始化失败: {e}")

    async def log_request(
        self,
        method: str,
        path: str,
        status_code: int,
        duration_ms: int,
        target_headers: Optional[Dict] = None,
        filtered_body: Optional[bytes] = None,
        original_headers: Optional[Dict] = None,
        original_body: Optional[bytes] = None,
        response_content: Optional[bytes] = None,
        channel: Optional[str] = None,
        usage: Optional[Dict[str, Any]] = None,
        response_truncated: bool = False,
        total_response_bytes: Optional[int] = None,
        target_url: Optional[str] = None,
        blocked: Optional[bool] = None,
        blocked_by: Optional[str] = None,
        blocked_reason: Optional[str] = None,
    ):
        """记录请求日志到jsonl文件（异步调度）"""

        def _write_log():
            try:
                log_entry = {
                    'id': str(uuid.uuid4()),
                    'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
                    'service': self.service_name,
                    'method': method,
                    'path': target_url if target_url else path,
                    'status_code': status_code,
                    'duration_ms': duration_ms,
                    'target_headers': target_headers or {}
                }

                if channel:
                    log_entry['channel'] = channel

                if filtered_body:
                    log_entry['filtered_body'] = base64.b64encode(filtered_body).decode('utf-8')

                if original_headers:
                    log_entry['original_headers'] = original_headers

                if original_body:
                    log_entry['original_body'] = base64.b64encode(original_body).decode('utf-8')

                usage_record = usage
                if usage_record is None:
                    usage_record = extract_usage_from_response(self.service_name, response_content)
                usage_record = normalize_usage_record(self.service_name, usage_record)
                log_entry['usage'] = usage_record

                if response_content:
                    log_entry['response_content'] = base64.b64encode(response_content).decode('utf-8')

                if response_truncated:
                    log_entry['response_truncated'] = True

                if total_response_bytes is not None:
                    log_entry['response_bytes'] = total_response_bytes

                if blocked is not None:
                    log_entry['blocked'] = bool(blocked)
                if blocked_by is not None:
                    log_entry['blocked_by'] = blocked_by
                if blocked_reason is not None:
                    log_entry['blocked_reason'] = blocked_reason

                # 限制日志文件为最多1000条记录
                self._maintain_log_limit(log_entry)
            except Exception as exc:
                print(f"日志记录失败: {exc}")

        await asyncio.to_thread(_write_log)

    def _ensure_log_cache_loaded(self, max_logs: int):
        if self._log_cache_loaded and self._log_cache.maxlen == max_logs:
            return

        if self._log_cache.maxlen != max_logs:
            self._log_cache = deque(self._log_cache, maxlen=max_logs)

        try:
            self.traffic_log.parent.mkdir(parents=True, exist_ok=True)
            if not self.traffic_log.exists():
                self._log_cache.clear()
                self._log_cache_loaded = True
                return

            entries = deque(maxlen=max_logs)
            with open(self.traffic_log, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            self._log_cache = entries
            self._log_cache_loaded = True
        except Exception as exc:
            print(f"初始化日志缓存失败: {exc}")
            self._log_cache = deque(maxlen=max_logs)
            self._log_cache_loaded = True

    def _maintain_log_limit(self, new_log_entry: dict, max_logs: int = 1000):
        """维护日志文件条数限制（跨进程文件锁），只保留最近的max_logs条记录。"""
        try:
            import fcntl  # POSIX 文件锁
        except Exception:
            fcntl = None

        with self._log_lock:
            try:
                max_logs = max_logs or self._log_max_entries
                self._log_max_entries = max_logs
                self._ensure_log_cache_loaded(max_logs)

                self._log_cache.append(new_log_entry)

                # 以 w 打开文件，获取独占锁，写入缓存内容
                with open(self.traffic_log, 'w', encoding='utf-8') as f:
                    try:
                        if fcntl is not None:
                            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                    except Exception:
                        pass
                    for log_entry in self._log_cache:
                        f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except Exception:
                        pass

            except Exception as exc:
                print(f"维护日志文件限制失败: {exc}")
                # 如果维护失败，直接追加写入（尽最大努力）
                try:
                    with open(self.traffic_log, 'a', encoding='utf-8') as f:
                        f.write(json.dumps(new_log_entry, ensure_ascii=False) + '\n')
                except Exception as fallback_exc:
                    print(f"备用日志写入也失败: {fallback_exc}")

    def _get_file_signature(self, file_path: Path) -> Tuple[int, int]:
        """获取文件签名，用于检测内容变化"""
        try:
            stat_result = file_path.stat()
            return stat_result.st_mtime_ns, stat_result.st_size
        except FileNotFoundError:
            return (0, 0)
        except OSError as exc:
            print(f"读取文件签名失败({file_path}): {exc}")
            return (0, 0)

    def _ensure_routing_config_current(self):
        """检查路由配置是否有更新，如有则重新加载"""
        current_signature = self._get_file_signature(self.routing_config_file)
        if current_signature != self.routing_config_signature:
            self.routing_config = self._load_routing_config()
            self.routing_config_signature = current_signature

    def _load_routing_config(self) -> dict:
        """加载路由配置"""
        try:
            if self.routing_config_file.exists():
                with open(self.routing_config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"加载路由配置失败: {e}")
        
        # 返回默认配置
        return {
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

    def _default_lb_config(self) -> dict:
        """构建负载均衡默认配置"""
        return {
            'mode': 'active-first',
            'options': {
                # 是否在一轮候选全部失败后自动重置失败计数
                'autoResetOnAllFailed': True,
                # 冷却期，避免频繁重置导致风暴（秒）
                'resetCooldownSeconds': 30,
                # UI 通知开关（前端可读取）
                'notifyEnabled': True,
                'failureThreshold': 3,
            },
            'services': {
                'claude': {
                    'failureThreshold': 3,
                    'currentFailures': {},
                    'excludedConfigs': [],
                    # 上次自动重置时间戳（秒）
                    'lastResetAt': 0,
                },
                'codex': {
                    'failureThreshold': 3,
                    'currentFailures': {},
                    'excludedConfigs': [],
                    'lastResetAt': 0,
                }
            }
        }

    def _ensure_lb_service_section(self, config: dict, service: str):
        """确保指定服务的负载均衡配置结构完整"""
        services = config.setdefault('services', {})
        service_section = services.setdefault(service, {})
        service_section.setdefault('failureThreshold', 3)
        service_section.setdefault('currentFailures', {})
        service_section.setdefault('excludedConfigs', [])
        service_section.setdefault('lastResetAt', 0)
        # 兼容老版本缺失 options
        config.setdefault('options', {})
        options = config['options']
        options.setdefault('autoResetOnAllFailed', True)
        options.setdefault('resetCooldownSeconds', 30)
        options.setdefault('notifyEnabled', True)
        options.setdefault('failureThreshold', service_section.get('failureThreshold', 3))

    def _load_lb_config(self) -> dict:
        """加载负载均衡配置"""
        try:
            if self.lb_config_file.exists():
                with open(self.lb_config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            else:
                data = self._default_lb_config()
        except Exception as exc:
            print(f"加载负载均衡配置失败: {exc}")
            data = self._default_lb_config()

        if 'mode' not in data:
            data['mode'] = 'active-first'

        self._ensure_lb_service_section(data, 'claude')
        self._ensure_lb_service_section(data, 'codex')
        return data

    def _ensure_lb_config_current(self):
        """检查负载均衡配置是否有更新"""
        with self._lb_lock:
            self._ensure_lb_config_current_locked()

    def _persist_lb_config(self):
        """持久化负载均衡配置"""
        with self._lb_lock:
            self._persist_lb_config_locked()

    def reload_lb_config(self):
        """重新加载负载均衡配置"""
        with self._lb_lock:
            self.lb_config = self._load_lb_config()
            self.lb_config_signature = self._get_file_signature(self.lb_config_file)

    def _ensure_lb_config_current_locked(self):
        """假定已获取锁的情况下检查配置更新"""
        current_signature = self._get_file_signature(self.lb_config_file)
        if current_signature != self.lb_config_signature:
            self.lb_config = self._load_lb_config()
            self.lb_config_signature = current_signature

    def _persist_lb_config_locked(self):
        """假定已获取锁的情况下持久化配置"""
        try:
            with open(self.lb_config_file, 'w', encoding='utf-8') as f:
                json.dump(self.lb_config, f, ensure_ascii=False, indent=2)
            self.lb_config_signature = self._get_file_signature(self.lb_config_file)
        except OSError as exc:
            print(f"保存负载均衡配置失败: {exc}")

    def _apply_model_routing(self, body: bytes) -> Tuple[bytes, Optional[str]]:
        """应用模型路由规则，返回修改后的body和要使用的配置名"""
        routing_mode = self.routing_config.get('mode', 'default')
        
        if routing_mode == 'default':
            return body, None
        
        try:
            # 解析请求体
            if not body:
                return body, None
                
            body_str = body.decode('utf-8')
            body_json = json.loads(body_str)
            
            # 获取模型名称
            model = body_json.get('model')
            if not model:
                return body, None
            
            if routing_mode == 'model-mapping':
                return self._apply_model_mapping(body_json, model, body)
            elif routing_mode == 'config-mapping':
                return self._apply_config_mapping(body_json, model, body)
                
        except Exception as e:
            print(f"应用模型路由失败: {e}")
            
        return body, None

    def _apply_model_mapping(self, body_json: dict, model: str, original_body: bytes) -> Tuple[bytes, Optional[str]]:
        """应用模型→模型映射和配置→模型映射"""
        mappings = self.routing_config.get('modelMappings', {}).get(self.service_name, [])

        for mapping in mappings:
            source = mapping.get('source', '').strip()
            target = mapping.get('target', '').strip()
            source_type = mapping.get('source_type', 'model').strip()

            if not source or not target:
                continue

            if source_type == 'config':
                # 配置→模型映射
                current_config = self._get_current_active_config()
                if current_config == source:
                    body_json['model'] = target
                    modified_body = json.dumps(body_json, ensure_ascii=False).encode('utf-8')
                    print(f"配置映射: {source} -> {target}")
                    return modified_body, None
            elif source_type == 'model':
                # 模型→模型映射
                if model == source:
                    body_json['model'] = target
                    modified_body = json.dumps(body_json, ensure_ascii=False).encode('utf-8')
                    print(f"模型映射: {source} -> {target}")
                    return modified_body, None

        return original_body, None

    def _apply_config_mapping(self, body_json: dict, model: str, original_body: bytes) -> Tuple[bytes, Optional[str]]:
        """应用模型→配置映射"""
        mappings = self.routing_config.get('configMappings', {}).get(self.service_name, [])
        
        for mapping in mappings:
            mapped_model = mapping.get('model', '').strip()
            target_config = mapping.get('config', '').strip()
            
            if mapped_model and target_config and model == mapped_model:
                # 检查目标配置是否存在
                if target_config in self.config_manager.configs:
                    print(f"配置映射: {model} -> {target_config}")
                    return original_body, target_config
                else:
                    print(f"配置映射失败: 配置 {target_config} 不存在")
        
        return original_body, None

    def _get_current_active_config(self) -> Optional[str]:
        """获取当前激活的配置名（考虑负载均衡）"""
        configs = self.config_manager.configs
        return self._select_config_by_loadbalance(configs)

    def _select_config_by_loadbalance(self, configs: Dict[str, Dict[str, Any]]) -> Optional[str]:
        """根据负载均衡策略选择配置名"""
        with self._lb_lock:
            self._ensure_lb_config_current_locked()
            mode = self.lb_config.get('mode', 'active-first')
            if mode == 'weight-based':
                return self._select_weighted_config_locked(configs)
        return self.config_manager.active_config

    def _select_weighted_config_locked(self, configs: Dict[str, Dict[str, Any]]) -> Optional[str]:
        """按权重选择配置（要求已持有负载均衡锁）。

        仅返回健康候选；当无健康候选时返回 None，避免继续尝试已被暂时跳过的上游。
        """
        if not configs:
            return None

        service_section = self.lb_config.get('services', {}).get(self.service_name, {})
        threshold = service_section.get('failureThreshold', 3)
        failures = service_section.get('currentFailures', {})
        excluded = set(service_section.get('excludedConfigs', []))

        sorted_configs = sorted(
            configs.items(),
            key=lambda item: (-float(item[1].get('weight', 0) or 0), item[0])
        )

        for name, _ in sorted_configs:
            if failures.get(name, 0) >= threshold:
                continue
            if name in excluded:
                continue
            return name

        # 无健康候选时，不再回退到任意配置，返回 None
        return None

    def reload_routing_config(self):
        """重新加载路由配置"""
        self.routing_config = self._load_routing_config()
        self.routing_config_signature = self._get_file_signature(self.routing_config_file)

    def _record_lb_result(self, config_name: Optional[str], status_code: int):
        """记录请求结果以更新负载均衡状态"""
        if not config_name:
            return

        with self._lb_lock:
            self._ensure_lb_config_current_locked()
            if self.lb_config.get('mode', 'active-first') != 'weight-based':
                return

            self._ensure_lb_service_section(self.lb_config, self.service_name)
            service_section = self.lb_config['services'][self.service_name]
            threshold = service_section.get('failureThreshold', 3)
            failures = service_section.setdefault('currentFailures', {})
            excluded = service_section.setdefault('excludedConfigs', [])

            changed = False
            is_success = status_code is not None and self._is_success_status(int(status_code))

            if is_success:
                if failures.get(config_name, 0) != 0:
                    failures[config_name] = 0
                    changed = True
                if config_name in excluded:
                    excluded.remove(config_name)
                    changed = True
            else:
                # 失败计数递增，但不超过阈值，避免 UI 显示超过阈值的异常数字
                prev = int(failures.get(config_name, 0) or 0)
                new_count = min(prev + 1, int(threshold or 1))
                if failures.get(config_name) != new_count:
                    failures[config_name] = new_count
                    changed = True
                if new_count >= threshold and config_name not in excluded:
                    excluded.append(config_name)
                    changed = True

            if changed:
                self._persist_lb_config_locked()

    def _is_success_status(self, sc: int) -> bool:
        """定义成功的HTTP状态：2xx + 白名单3xx(304/307)"""
        return (200 <= sc < 300) or sc in {304, 307}

    def _get_candidate_order(self, configs: Dict[str, Dict[str, Any]]) -> list:
        """按权重返回健康候选列表；若无健康项，不再兜底回退。

        这样可确保“已暂时跳过”的上游不会被继续尝试。
        """
        if not configs:
            return []

        with self._lb_lock:
            self._ensure_lb_config_current_locked()
            service_section = self.lb_config.get('services', {}).get(self.service_name, {})
            threshold = service_section.get('failureThreshold', 3)
            failures = service_section.get('currentFailures', {})
            excluded = set(service_section.get('excludedConfigs', []))

            sorted_configs = sorted(
                configs.items(),
                key=lambda item: (-float(item[1].get('weight', 0) or 0), item[0])
            )

            healthy = [name for name, _ in sorted_configs if failures.get(name, 0) < threshold and name not in excluded]
            fallback_name = sorted_configs[0][0] if sorted_configs else None

        if healthy:
            return healthy

        # 无健康候选：返回空列表，交由上层走重置或直接失败逻辑
        return []

    def _reset_lb_service_failures(self) -> bool:
        """重置当前服务的失败计数并记录时间戳；返回是否执行了重置（受冷却期限制）"""
        with self._lb_lock:
            self._ensure_lb_config_current_locked()
            options = self.lb_config.setdefault('options', {})
            cooldown = int(options.get('resetCooldownSeconds', 30) or 30)

            service_section = self.lb_config['services'][self.service_name]
            last_reset = float(service_section.get('lastResetAt', 0) or 0)
            now = time.time()
            if last_reset and (now - last_reset) < cooldown:
                return False

            service_section['currentFailures'] = {}
            service_section['excludedConfigs'] = []
            service_section['lastResetAt'] = now
            self._persist_lb_config_locked()
            return True

    def _get_lb_options(self) -> dict:
        with self._lb_lock:
            self._ensure_lb_config_current_locked()
            return dict(self.lb_config.get('options', {}))

    def _get_lb_mode(self) -> str:
        with self._lb_lock:
            self._ensure_lb_config_current_locked()
            return self.lb_config.get('mode', 'active-first')

    def build_target_param(self, path: str, request: Request, body: bytes) -> Tuple[str, Dict, bytes, Optional[str]]:
        """
        构建请求参数

        Returns:
            (target_url, headers, body, active_config_name)
        """
        # 使用最新的路由配置
        self._ensure_routing_config_current()

        # 应用模型路由规则
        modified_body, config_override = self._apply_model_routing(body)

        # 预加载配置列表，减少重复 I/O
        configs = self.config_manager.configs
        if not configs:
            raise ValueError(
                f"{self.service_name} 当前没有启用的上游配置，请在 ~/.clp/{self.service_name}.json 中取消禁用或新增配置"
            )

        # 确定要使用的配置
        if config_override:
            active_config_name = config_override
        else:
            active_config_name = self._select_config_by_loadbalance(configs)

        config_data = configs.get(active_config_name)
        if not config_data and active_config_name:
            # 配置字典可能因缓存过期，需要重新获取
            configs = self.config_manager.configs
            config_data = configs.get(active_config_name)

        if not config_data:
            fallback_name = self.config_manager.active_config
            configs = self.config_manager.configs
            config_data = configs.get(fallback_name)
            active_config_name = fallback_name

        if not config_data:
            raise ValueError(f"未找到激活配置: {active_config_name}")
        
        # 构建目标URL
        base_url = config_data['base_url'].rstrip('/')
        normalized_path = path.lstrip('/')
        target_url = f"{base_url}/{normalized_path}" if normalized_path else base_url

        raw_query = request.url.query
        if raw_query:
            target_url = f"{target_url}?{raw_query}"

        # 处理headers
        # 1. 应用 Header Filter 过滤敏感 headers（如果启用）
        original_headers_dict = dict(request.headers)
        if self.header_filter:
            # 重新加载配置（使用缓存机制，仅在文件修改时重新加载）
            self.header_filter.reload_config()
            filtered_headers_dict = self.header_filter.filter_headers(original_headers_dict)
        else:
            filtered_headers_dict = original_headers_dict

        # 2. 排除会被重新设置的头
        excluded_headers = {'authorization', 'host', 'content-length'}
        headers = {k: v for k, v in filtered_headers_dict.items() if k.lower() not in excluded_headers}

        # 3. 添加必要的 headers
        headers['host'] = urlsplit(target_url).netloc
        headers.setdefault('connection', 'keep-alive')
        if config_data.get('api_key'):
            headers['x-api-key'] = config_data['api_key']
        if config_data.get('auth_token'):
            headers['authorization'] = f'Bearer {config_data["auth_token"]}'

        return target_url, headers, modified_body, active_config_name

    @abstractmethod
    def test_endpoint(self, model: str, base_url: str, auth_token: str = None, api_key: str = None, extra_params: dict = None) -> dict:
        """
        测试API端点连通性

        Args:
            model: 模型名称
            base_url: 目标API地址
            auth_token: 认证令牌（可选）
            api_key: API密钥（可选）
            extra_params: 扩展参数（可选）

        Returns:
            dict: 包含测试结果的字典
        """
        pass

    def apply_request_filter(self, data: bytes) -> bytes:
        """应用请求过滤器"""
        if self.request_filter:
            # 使用缓存版本的过滤器
            return self.request_filter.apply_filters(data)
        else:
            # 使用原版本的过滤器
            return self.filter_request_data(data)
    
    async def proxy(self, path: str, request: Request):
        """处理代理请求"""
        start_time = time.time()
        request_id = str(uuid.uuid4())

        original_headers = {k: v for k, v in request.headers.items()}
        original_body = await request.body()

        # —— 接口过滤：最先判定，命中则直接阻断 ——
        try:
            if self.endpoint_filter:
                self.endpoint_filter.reload()
                # 以 Request.url.path 作为匹配路径，始终带前导 '/'
                full_path = request.url.path
                # 将查询参数标准化为首值字典
                qd = {}
                try:
                    for k in request.query_params.keys():
                        qd[k] = request.query_params.get(k)
                except Exception:
                    qd = {}
                mr = self.endpoint_filter.match(self.service_name, request.method, full_path, qd)
                if mr:
                    # 广播实时事件
                    try:
                        await self.realtime_hub.request_started(
                            request_id=request_id,
                            method=request.method,
                            path=full_path,
                            channel="blocked",
                            headers=original_headers,
                            target_url=None,
                        )
                    except Exception:
                        pass

                    duration_ms = int((time.time() - start_time) * 1000)
                    try:
                        await self.realtime_hub.request_completed(
                            request_id=request_id,
                            status_code=mr.status,
                            duration_ms=duration_ms,
                            success=False,
                        )
                    except Exception:
                        pass

                    # 记录日志（原始头/体保留审计）
                    await self.log_request(
                        method=request.method,
                        path=full_path,
                        status_code=mr.status,
                        duration_ms=duration_ms,
                        target_headers=None,
                        filtered_body=None,
                        original_headers=original_headers,
                        original_body=original_body,
                        response_content=None,
                        channel="blocked",
                        target_url=None,
                        blocked=True,
                        blocked_by=mr.rule_id,
                        blocked_reason=mr.message,
                    )

                    return JSONResponse({
                        "error": "ENDPOINT_BLOCKED",
                        "message": mr.message,
                        "rule_id": mr.rule_id,
                        "service": self.service_name,
                    }, status_code=mr.status)
        except Exception as e:
            # 过滤器的异常不能影响正常转发
            print(f"Endpoint 过滤判定失败: {e}")

        active_config_name: Optional[str] = None
        target_headers: Optional[Dict[str, str]] = None
        filtered_body: Optional[bytes] = None
        target_url: Optional[str] = None

        # ---- 新的多候选重试流程（仅权重模式） ----
        # 预处理：模型/配置路由
        self._ensure_routing_config_current()
        modified_body, config_override = self._apply_model_routing(original_body)

        # 请求是否流式
        headers_lower = {k.lower(): v for k, v in original_headers.items()}
        x_stainless_helper_method = headers_lower.get('x-stainless-helper-method', '').lower()
        content_type = headers_lower.get('content-type', '').lower()
        accept = headers_lower.get('accept', '').lower()
        is_stream = (
            'text/event-stream' in accept or
            'text/event-stream' in content_type or
            'stream' in content_type or
            'application/x-ndjson' in content_type or
            "stream" in x_stainless_helper_method
        )

        # 构建候选序列
        configs = self.config_manager.configs
        lb_mode = self._get_lb_mode()
        auto_reset_enabled = bool(self._get_lb_options().get('autoResetOnAllFailed', True))

        def _build_target_param_for_config(config_name: str):
            cfg = self.config_manager.configs.get(config_name)
            if not cfg:
                raise ValueError(f"未找到配置: {config_name}")

            base_url = cfg['base_url'].rstrip('/')
            normalized_path = path.lstrip('/')
            url = f"{base_url}/{normalized_path}" if normalized_path else base_url
            raw_query = request.url.query
            if raw_query:
                url = f"{url}?{raw_query}"

            # Header 过滤
            original_headers_dict = dict(request.headers)
            if self.header_filter:
                self.header_filter.reload_config()
                filtered_headers_dict = self.header_filter.filter_headers(original_headers_dict)
            else:
                filtered_headers_dict = original_headers_dict

            excluded_headers = {'authorization', 'host', 'content-length'}
            headers = {k: v for k, v in filtered_headers_dict.items() if k.lower() not in excluded_headers}
            headers['host'] = urlsplit(url).netloc
            headers.setdefault('connection', 'keep-alive')
            if cfg.get('api_key'):
                headers['x-api-key'] = cfg['api_key']
            if cfg.get('auth_token'):
                headers['authorization'] = f'Bearer {cfg["auth_token"]}'
            return url, headers

        async def _try_once(config_name: str):
            nonlocal filtered_body
            # 为该尝试生成 target
            try:
                url, headers = _build_target_param_for_config(config_name)
            except Exception as e:
                return False, {"error": str(e)}, None, False, None, None

            # 首次发送 started 事件使用第一候选
            if not started_event_sent[0]:
                await self.realtime_hub.request_started(
                    request_id=request_id,
                    method=request.method,
                    path=path,
                    channel=config_name or "unknown",
                    headers=headers,
                    target_url=url
                )
                started_event_sent[0] = True

            # 过滤 Body（一次性缓存）
            if filtered_body is None:
                filtered_body = await asyncio.to_thread(self.apply_request_filter, modified_body)

            try:
                request_out = self.client.build_request(
                    method=request.method,
                    url=url,
                    headers=headers,
                    content=filtered_body if filtered_body else None,
                )
                response = await self.client.send(request_out, stream=is_stream)
                sc = response.status_code
                if not self._is_success_status(sc):
                    await asyncio.to_thread(self._record_lb_result, config_name, sc)
                    await response.aclose()
                    return False, {"error": f"上游返回非2xx: {sc}"}, sc, False, url, headers

                # 2xx：返回可流式的 StreamingResponse，并在 iterator 中记录日志与成功
                excluded_response_headers = {'connection', 'transfer-encoding'}
                response_headers = {k: v for k, v in response.headers.items() if k.lower() not in excluded_response_headers}

                collected = bytearray()
                total_response_bytes = 0
                response_truncated = False
                first_chunk = True
                lb_result_recorded = False
                last_usage = None
                sse_buffer = ''
                nd_buffer = ''
                resp_ct = response.headers.get('content-type', '')
                sse_mode = 'text/event-stream' in (resp_ct or '').lower()
                ndjson_mode = 'application/x-ndjson' in (resp_ct or '').lower()

                iterator_error: Optional[BaseException] = None
                iterator_error_status: Optional[int] = None

                async def iterator():
                    nonlocal response_truncated, total_response_bytes, first_chunk, lb_result_recorded, last_usage, iterator_error, iterator_error_status, sse_buffer, nd_buffer
                    try:
                        async for chunk in response.aiter_bytes():
                            if not chunk:
                                continue
                            current_duration = int((time.time() - start_time) * 1000)
                            if first_chunk:
                                await self.realtime_hub.request_streaming(request_id, current_duration)
                                first_chunk = False
                            try:
                                chunk_text = chunk.decode('utf-8', errors='ignore')
                                if chunk_text.strip():
                                    if sse_mode or ('data:' in chunk_text):
                                        last_usage, sse_buffer = process_sse_buffer(self.service_name, sse_buffer, chunk_text, last_usage)
                                    elif ndjson_mode:
                                        last_usage, nd_buffer = process_ndjson_buffer(self.service_name, nd_buffer, chunk_text, last_usage)
                                    else:
                                        last_usage = update_usage_from_sse_chunk(self.service_name, chunk_text, last_usage)
                                    await self.realtime_hub.response_chunk(request_id, chunk_text, current_duration)
                            except Exception:
                                pass
                            total_response_bytes += len(chunk)
                            if len(collected) < self.max_logged_response_bytes:
                                remaining = self.max_logged_response_bytes - len(collected)
                                collected.extend(chunk[:remaining])
                                if len(chunk) > remaining:
                                    response_truncated = True
                            else:
                                response_truncated = True
                            yield chunk
                    except Exception as exc:
                        iterator_error = exc
                        if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
                            iterator_error_status = int(exc.response.status_code)
                        elif isinstance(exc, httpx.TimeoutException):
                            iterator_error_status = 504
                        else:
                            iterator_error_status = 502
                        raise
                    finally:
                        final_duration = int((time.time() - start_time) * 1000)
                        success = iterator_error is None and self._is_success_status(sc)
                        status_for_log = sc if success else (iterator_error_status or 502)
                        await self.realtime_hub.request_completed(
                            request_id=request_id,
                            status_code=status_for_log,
                            duration_ms=final_duration,
                            success=success
                        )
                        try:
                            if sse_buffer:
                                last_usage, sse_buffer = process_sse_buffer(self.service_name, sse_buffer, "\n\n", last_usage)
                            if nd_buffer:
                                last_usage, nd_buffer = process_ndjson_buffer(self.service_name, nd_buffer + "\n", "", last_usage)
                        except Exception:
                            pass
                        await response.aclose()
                        response_content = bytes(collected) if collected else None
                        await self.log_request(
                            method=request.method,
                            path=path,
                            status_code=status_for_log,
                            duration_ms=final_duration,
                            target_headers=headers,
                            filtered_body=filtered_body,
                            original_headers=original_headers,
                            original_body=original_body,
                            usage=last_usage,
                            response_content=response_content,
                            channel=config_name,
                            response_truncated=response_truncated,
                            total_response_bytes=total_response_bytes,
                            target_url=url,
                        )
                        if not lb_result_recorded:
                            lb_status = sc if success else None
                            await asyncio.to_thread(self._record_lb_result, config_name, lb_status)
                            lb_result_recorded = True

                streaming_resp = StreamingResponse(iterator(), status_code=sc, headers=response_headers)
                return True, streaming_resp, sc, False, url, headers

            except httpx.RequestError as exc:
                # 连接/超时等错误：可切换
                await asyncio.to_thread(self._record_lb_result, config_name, None)
                err = {
                    "error": "请求失败",
                    "detail": str(exc)
                }
                return False, err, None, False, url, headers

        # 候选序列
        if config_override:
            candidates_round1 = [config_override]
            no_healthy_candidates = False
        elif lb_mode == 'weight-based':
            candidates_round1 = self._get_candidate_order(configs)
            no_healthy_candidates = (len(candidates_round1) == 0)
        else:
            # active-first: 维持原有行为
            try:
                target_url, target_headers, target_body, active_config_name = self.build_target_param(path, request, original_body)
                await self.realtime_hub.request_started(
                    request_id=request_id,
                    method=request.method,
                    path=path,
                    channel=active_config_name or "unknown",
                    headers=target_headers,
                    target_url=target_url
                )
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=500)
            # 回退到原有单次执行路径
            filtered_body = await asyncio.to_thread(self.apply_request_filter, target_body)
            try:
                request_out = self.client.build_request(
                    method=request.method,
                    url=target_url,
                    headers=target_headers,
                    content=filtered_body if filtered_body else None,
                )
                response = await self.client.send(request_out, stream=is_stream)
                status_code = response.status_code
                lb_result_recorded = False
                if not self._is_success_status(status_code):
                    await asyncio.to_thread(self._record_lb_result, active_config_name, status_code)
                    lb_result_recorded = True
                excluded_response_headers = {'connection', 'transfer-encoding'}
                response_headers = {k: v for k, v in response.headers.items() if k.lower() not in excluded_response_headers}
                collected = bytearray()
                total_response_bytes = 0
                response_truncated = False
                first_chunk = True
                last_usage = None
                sse_buffer = ''
                nd_buffer = ''
                resp_ct = response.headers.get('content-type', '')
                sse_mode = 'text/event-stream' in (resp_ct or '').lower()
                ndjson_mode = 'application/x-ndjson' in (resp_ct or '').lower()
                iterator_error: Optional[BaseException] = None
                iterator_error_status: Optional[int] = None

                async def iterator():
                    nonlocal response_truncated, total_response_bytes, first_chunk, lb_result_recorded, last_usage, sse_buffer, nd_buffer, iterator_error, iterator_error_status
                    try:
                        async for chunk in response.aiter_bytes():
                            if not chunk:
                                continue
                            current_duration = int((time.time() - start_time) * 1000)
                            if first_chunk:
                                await self.realtime_hub.request_streaming(request_id, current_duration)
                                first_chunk = False
                            try:
                                chunk_text = chunk.decode('utf-8', errors='ignore')
                                if chunk_text.strip():
                                    if sse_mode or ('data:' in chunk_text):
                                        last_usage, sse_buffer = process_sse_buffer(self.service_name, sse_buffer, chunk_text, last_usage)
                                    elif ndjson_mode:
                                        last_usage, nd_buffer = process_ndjson_buffer(self.service_name, nd_buffer, chunk_text, last_usage)
                                    else:
                                        last_usage = update_usage_from_sse_chunk(self.service_name, chunk_text, last_usage)
                                    await self.realtime_hub.response_chunk(request_id, chunk_text, current_duration)
                            except Exception:
                                pass
                            total_response_bytes += len(chunk)
                            if len(collected) < self.max_logged_response_bytes:
                                remaining = self.max_logged_response_bytes - len(collected)
                                collected.extend(chunk[:remaining])
                                if len(chunk) > remaining:
                                    response_truncated = True
                            else:
                                response_truncated = True
                            yield chunk
                    except Exception as exc:
                        iterator_error = exc
                        if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
                            iterator_error_status = int(exc.response.status_code)
                        elif isinstance(exc, httpx.TimeoutException):
                            iterator_error_status = 504
                        else:
                            iterator_error_status = 502
                        raise
                    finally:
                        final_duration = int((time.time() - start_time) * 1000)
                        success = iterator_error is None and self._is_success_status(status_code)
                        status_for_log = status_code if success else (iterator_error_status or 502)
                        await self.realtime_hub.request_completed(
                            request_id=request_id,
                            status_code=status_for_log,
                            duration_ms=final_duration,
                            success=success
                        )
                        try:
                            if sse_buffer:
                                last_usage, sse_buffer = process_sse_buffer(self.service_name, sse_buffer, "\n\n", last_usage)
                            if nd_buffer:
                                last_usage, nd_buffer = process_ndjson_buffer(self.service_name, nd_buffer + "\n", "", last_usage)
                        except Exception:
                            pass
                        await response.aclose()
                        response_content = bytes(collected) if collected else None
                        await self.log_request(
                            method=request.method,
                            path=path,
                            status_code=status_for_log,
                            duration_ms=final_duration,
                            target_headers=target_headers,
                            filtered_body=filtered_body,
                            original_headers=original_headers,
                            original_body=original_body,
                            usage=last_usage,
                            response_content=response_content,
                            channel=active_config_name,
                            response_truncated=response_truncated,
                            total_response_bytes=total_response_bytes,
                            target_url=target_url
                        )
                        if not lb_result_recorded:
                            lb_status = status_code if success else None
                            await asyncio.to_thread(self._record_lb_result, active_config_name, lb_status)
                            lb_result_recorded = True
                return StreamingResponse(iterator(), status_code=status_code, headers=response_headers)
            except httpx.RequestError as exc:
                duration_ms = int((time.time() - start_time) * 1000)
                if isinstance(exc, httpx.ConnectTimeout): error_msg = "连接超时"
                elif isinstance(exc, httpx.ReadTimeout): error_msg = "响应读取超时"
                elif isinstance(exc, httpx.ConnectError): error_msg = "连接错误"
                elif isinstance(exc, httpx.HTTPStatusError): error_msg = "上游返回错误状态"
                else: error_msg = "请求失败"
                response_data = {"error": error_msg, "detail": str(exc)}
                status_code = 500
                await self.realtime_hub.request_completed(request_id=request_id, status_code=status_code, duration_ms=duration_ms, success=False)
                await self.log_request(method=request.method, path=path, status_code=status_code, duration_ms=duration_ms, target_headers=target_headers, filtered_body=filtered_body, original_headers=original_headers, original_body=original_body, channel=active_config_name, target_url=target_url)
                await asyncio.to_thread(self._record_lb_result, active_config_name, status_code)
                return JSONResponse(response_data, status_code=status_code)

        # weight-based 多候选：两轮（第二轮可重置）
        candidates_history_error = None
        attempt_counter = 0
        previous_candidate = None
        last_status_code = None
        # 用于首次 started 事件的标记
        started_event_sent = [False]

        async def run_round(candidates: list, round_index: int):
            nonlocal previous_candidate, attempt_counter, candidates_history_error, last_status_code
            for cand in candidates:
                with self._lb_lock:
                    self._ensure_lb_config_current_locked()
                    service_section = self.lb_config['services'][self.service_name]
                    threshold = service_section.get('failureThreshold', 3)
                    failures_snapshot = dict(service_section.get('currentFailures', {}))

                attempt_counter += 1
                if previous_candidate and previous_candidate != cand:
                    failures = failures_snapshot.get(previous_candidate, 0)
                    reason = 'http_non2xx' if (last_status_code and not (200 <= int(last_status_code) < 300)) else 'request_error'
                    await self.realtime_hub.lb_switch(
                        request_id,
                        from_channel=previous_candidate,
                        to_channel=cand,
                        reason=reason,
                        failures=failures,
                        threshold=threshold,
                        attempt=attempt_counter,
                        path=path,
                    )
                ok, result, sc, bytes_sent, url, headers = await _try_once(cand)
                previous_candidate = cand
                last_status_code = sc
                if ok:
                    # 直接返回成功的 StreamingResponse
                    return True, result
                else:
                    candidates_history_error = result
                    # 未开始向客户端写入，继续下一候选
                    continue
            return False, candidates_history_error

        # 第一轮
        ok1, res1 = await run_round(candidates_round1, 1)
        if ok1:
            return res1

        # 第一轮全部失败：根据选项判断是否自动重置并进行第二轮
        reset_triggered = False
        if auto_reset_enabled and self._reset_lb_service_failures():
            reset_triggered = True
            # 广播重置事件
            with self._lb_lock:
                self._ensure_lb_config_current_locked()
                svc_section = self.lb_config['services'][self.service_name]
                threshold_value = svc_section.get('failureThreshold', 3)
            await self.realtime_hub.lb_reset(
                request_id,
                reason='last_candidate_failed',
                total_configs=len(configs),
                threshold=threshold_value
            )
            # 第二轮：重置后等价于所有候选健康，直接按权重排序
            sorted_all = sorted(configs.items(), key=lambda item: (-float(item[1].get('weight', 0) or 0), item[0]))
            candidates_round2 = [name for name, _ in sorted_all]
            ok2, res2 = await run_round(candidates_round2, 2)
            if ok2:
                return res2

        # 如无健康候选且未触发自动重置，发送耗尽事件并返回更明确的错误
        if lb_mode == 'weight-based' and no_healthy_candidates and not reset_triggered:
            with self._lb_lock:
                self._ensure_lb_config_current_locked()
                svc_section = self.lb_config['services'][self.service_name]
                options = self.lb_config.get('options', {})
                threshold_value = int(svc_section.get('failureThreshold', 3) or 3)
                cooldown = int(options.get('resetCooldownSeconds', 30) or 30)
                last_reset = float(svc_section.get('lastResetAt', 0) or 0)
            now = time.time()
            remaining = int(max(0, cooldown - (now - last_reset)))
            if not started_event_sent[0]:
                await self.realtime_hub.request_started(
                    request_id=request_id,
                    method=request.method,
                    path=path,
                    channel="unassigned",
                    headers={},
                    target_url=None
                )
                started_event_sent[0] = True
            await self.realtime_hub.lb_exhausted(
                request_id=request_id,
                reason='no_healthy_candidates',
                total_configs=len(configs),
                threshold=threshold_value,
                cooldown_seconds=cooldown,
                cooldown_remaining_seconds=remaining,
            )
            duration_ms = int((time.time() - start_time) * 1000)
            await self.realtime_hub.request_completed(
                request_id=request_id,
                status_code=503,
                duration_ms=duration_ms,
                success=False
            )
            # 记录失败（不含响应体）
            await self.log_request(
                method=request.method,
                path=path,
                status_code=503,
                duration_ms=duration_ms,
                target_headers=None,
                filtered_body=None,
                original_headers=original_headers,
                original_body=original_body,
                channel=None,
                target_url=None
            )
            return JSONResponse({
                "error": "NO_HEALTHY_UPSTREAM",
                "message": "无健康上游可用：所有候选均已达到失败阈值或被暂时跳过",
                "service": self.service_name,
                "threshold": threshold_value,
                "auto_reset": auto_reset_enabled,
                "reset_cooldown_seconds": cooldown,
                "cooldown_remaining_seconds": remaining
            }, status_code=503)

        # 未开启自动重置 或 第二轮仍失败 → 返回最后错误
        duration_ms = int((time.time() - start_time) * 1000)
        await self.realtime_hub.request_completed(
            request_id=request_id,
            status_code=500 if (last_status_code is None) else last_status_code,
            duration_ms=duration_ms,
            success=False
        )
        # 记录一次失败日志（不含响应体）
        await self.log_request(
            method=request.method,
            path=path,
            status_code=500 if (last_status_code is None) else last_status_code,
            duration_ms=duration_ms,
            target_headers=None,
            filtered_body=None,
            original_headers=original_headers,
            original_body=original_body,
            channel=previous_candidate,
            target_url=None
        )
        return JSONResponse(candidates_history_error or {"error": "所有上游均失败"}, status_code=500 if (last_status_code is None) else int(last_status_code))

    def run_app(self):
        """启动代理服务"""
        import os
        # 切换到项目根目录
        project_root = Path(__file__).parent.parent.parent

        # 在daemon环境中，需要明确指定环境和重定向
        env = os.environ.copy()

        # 通过环境变量控制代理服务监听地址
        proxy_host = os.getenv('CLP_PROXY_HOST', '127.0.0.1')

        try:
            with open(self.log_file, 'a') as log_file:
                uvicorn_cmd = [
                    sys.executable, '-m', 'uvicorn',
                    f'src.{self.service_name}.proxy:app',
                    '--host', proxy_host,
                    '--port', str(self.port),
                    '--http', 'h11',
                    '--timeout-keep-alive', '60',
                    '--limit-concurrency', '500',
                ]
                subprocess.run(
                    uvicorn_cmd,
                    cwd=str(project_root),
                    env=env,
                    stdout=log_file,
                    stderr=log_file,
                    stdin=subprocess.DEVNULL
                )
                print(f"启动{self.service_name}代理成功 在端口 {self.port}")
        except Exception as e:
            print(f"启动{self.service_name}代理失败: {e}")


class BaseServiceController(ABC):
    """基础服务控制器类"""
    
    def __init__(self, service_name: str, port: int, config_manager, proxy_module_path: str):
        """
        初始化服务控制器
        
        Args:
            service_name: 服务名称
            port: 服务端口
            config_manager: 配置管理器实例
            proxy_module_path: 代理模块路径 (如 'src.claude.proxy')
        """
        self.service_name = service_name
        self.port = port
        self.config_manager = config_manager
        self.proxy_module_path = proxy_module_path
        
        # 初始化路径
        self.config_dir = Path.home() / '.clp/run'
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.pid_file = self.config_dir / f'{service_name}_proxy.pid'
        self.log_file = self.config_dir / f'{service_name}_proxy.log'
    
    def get_pid(self) -> Optional[int]:
        """获取服务进程PID"""
        if self.pid_file.exists():
            try:
                return int(self.pid_file.read_text().strip())
            except:
                return None
        return None
    
    def is_running(self) -> bool:
        """检查服务是否在运行"""
        import psutil
        pid = self.get_pid()
        if pid:
            try:
                process = psutil.Process(pid)
                return process.is_running()
            except psutil.NoSuchProcess:
                return False
        return False
    
    def start(self) -> bool:
        """启动服务"""
        if self.is_running():
            print(f"{self.service_name}服务已经在运行")
            return False
        
        config_file_path = None
        ensure_file_fn = getattr(self.config_manager, 'ensure_config_file', None)
        if callable(ensure_file_fn):
            config_file_path = ensure_file_fn()
        elif hasattr(self.config_manager, 'config_file'):
            config_file_path = getattr(self.config_manager, 'config_file')

        # 检查配置
        configs = self.config_manager.configs
        if not configs:
            if config_file_path:
                print(f"警告: {self.service_name}配置为空，将以占位模式启动。请编辑 {config_file_path} 补充配置后重启。")
            else:
                print(f"警告: 未检测到{self.service_name}配置文件，将以占位模式启动。")
        
        import os
        project_root = Path(__file__).parent.parent.parent
        env = os.environ.copy()

        # 通过环境变量控制代理服务监听地址
        proxy_host = os.getenv('CLP_PROXY_HOST', '127.0.0.1')

        uvicorn_cmd = [
            sys.executable, '-m', 'uvicorn',
            f'{self.proxy_module_path}:app',
            '--host', proxy_host,
            '--port', str(self.port),
            '--http', 'h11',
            '--timeout-keep-alive', '60',
            '--limit-concurrency', '500',
        ]
        with open(self.log_file, 'a') as log_handle:
            # 在独立进程组中运行，避免控制台信号终止子进程
            process = create_detached_process(
                uvicorn_cmd,
                log_handle,
                cwd=str(project_root),
                env=env,
            )

        # 保存PID
        self.pid_file.write_text(str(process.pid))

        # 等待服务启动
        time.sleep(1)

        if self.is_running():
            print(f"{self.service_name}服务启动成功 (端口: {self.port})")
            return True
        else:
            print(f"{self.service_name}服务启动失败")
            return False
    
    def stop(self) -> bool:
        """停止服务"""
        import psutil
        
        if not self.is_running():
            print(f"{self.service_name}服务未运行")
            return False
        
        pid = self.get_pid()
        if pid:
            try:
                process = psutil.Process(pid)
                process.terminate()
                process.wait(timeout=5)
            except psutil.TimeoutExpired:
                process.kill()
            except psutil.NoSuchProcess:
                pass
            
            # 清理PID文件
            if self.pid_file.exists():
                self.pid_file.unlink()
            
            print(f"{self.service_name}服务已停止")
            return True
        
        return False
    
    def restart(self) -> bool:
        """重启服务"""
        self.stop()
        time.sleep(1)
        return self.start()
    
    def status(self):
        """查看服务状态"""
        if self.is_running():
            pid = self.get_pid()
            active_config = self.config_manager.active_config
            print(f"{self.service_name}服务: 运行中 (PID: {pid}, 配置: {active_config})")
        else:
            print(f"{self.service_name}服务: 未运行")
