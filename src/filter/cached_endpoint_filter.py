#!/usr/bin/env python3
"""
请求接口过滤器（带缓存）

- 配置文件：~/.clp/endpoint_filter.json
  结构：
  {
    "enabled": true,
    "rules": [
      {
        "id": "block-count-tokens",
        "services": ["claude", "codex"],      # 可选，默认两者
        "methods": ["GET", "POST"],            # 可选，默认 ["*"] 表示任意
        # 三选一：path / prefix / regex
        "path": "/api/v1/messages/count_tokens",
        "prefix": "/internal/",
        "regex": "^/api/experimental/.*$",
        # 可选：query 键值匹配（全部满足）; value 为 "*" 表示存在即可
        "query": {"beta": "true"},
        "action": {"type": "block", "status": 403, "message": "Endpoint is blocked by proxy"}
      }
    ]
  }

- 匹配逻辑：service ∧ method ∧ (path|prefix|regex) ∧ query
  命中后返回阻断结果，代理将不再向上游转发。
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class MatchResult:
    """命中结果"""
    rule_id: Optional[str]
    status: int
    message: str


class CachedEndpointFilter:
    """接口过滤器（缓存文件内容，按需热加载）"""

    def __init__(self, cache_check_interval: float = 1.0):
        self.config_file = Path.home() / '.clp' / 'endpoint_filter.json'
        self.enabled: bool = True
        self._rules: List[Dict[str, Any]] = []
        self._compiled_regex: List[Optional[re.Pattern]] = []
        self._file_mtime: float = 0.0
        self._last_check_time: float = 0.0
        self.cache_check_interval = cache_check_interval
        self._load_config(force=True)

    # --------------------- 对外 API ---------------------
    def reload(self):
        """按需重载配置（带最小检查间隔）"""
        self._load_config()

    def force_reload(self):
        """强制重载配置"""
        self._load_config(force=True)

    def match(
        self,
        service: str,
        method: str,
        path: str,
        query: Dict[str, str],
    ) -> Optional[MatchResult]:
        """尝试匹配当前请求

        Args:
            service: 服务名："claude" 或 "codex"
            method: 大写 HTTP 方法
            path: 以 '/' 开头的路径
            query: 查询参数（取首值）

        Returns:
            MatchResult or None
        """
        if not self.enabled or not self._rules:
            return None

        svc = (service or '').strip().lower()
        m = (method or 'GET').strip().upper()
        p = path if path.startswith('/') else f'/{path}'

        for idx, rule in enumerate(self._rules):
            try:
                # 服务范围
                services = rule.get('services')
                if isinstance(services, list) and services:
                    allowed = {str(s).strip().lower() for s in services}
                    if svc not in allowed:
                        continue

                # 方法
                methods = rule.get('methods')
                if isinstance(methods, list) and methods:
                    normalized = [str(x).strip().upper() for x in methods]
                    if '*' not in normalized and m not in normalized:
                        continue

                # 路径匹配（三选一）
                if not self._match_path(idx, rule, p):
                    continue

                # 查询参数
                if not self._match_query(rule.get('query'), query):
                    continue

                # 动作（当前仅支持 block）
                action = rule.get('action') or {}
                if str(action.get('type') or 'block').strip().lower() != 'block':
                    # 未识别动作则跳过
                    continue
                status = int(action.get('status') or 403)
                message = str(action.get('message') or 'Endpoint is blocked by proxy')
                return MatchResult(rule_id=rule.get('id'), status=status, message=message)
            except Exception:
                # 单条规则异常不影响整体
                continue

        return None

    # --------------------- 内部实现 ---------------------
    def _should_reload(self) -> bool:
        now = time.time()
        if now - self._last_check_time < self.cache_check_interval:
            return False
        self._last_check_time = now
        try:
            if not self.config_file.exists():
                return self._file_mtime != 0
            mtime = self.config_file.stat().st_mtime
            return mtime != self._file_mtime
        except Exception:
            return False

    def _load_config(self, force: bool = False):
        if not force and not self._should_reload():
            return

        if not self.config_file.exists():
            self._create_default_config()
            return

        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            self.enabled = bool(data.get('enabled', True))
            rules = data.get('rules', [])
            if not isinstance(rules, list):
                rules = []

            # 规范化 + 预编译 regex
            compiled: List[Optional[re.Pattern]] = []
            normalized_rules: List[Dict[str, Any]] = []
            for r in rules:
                if not isinstance(r, dict):
                    continue
                # 互斥匹配项：按 path > prefix > regex 优先取第一个合法的
                path = r.get('path')
                prefix = r.get('prefix')
                regex = r.get('regex')
                chosen = None
                if isinstance(path, str) and path.strip():
                    chosen = ('path', path.strip())
                elif isinstance(prefix, str) and prefix.strip():
                    chosen = ('prefix', prefix.strip())
                elif isinstance(regex, str) and regex.strip():
                    chosen = ('regex', regex.strip())
                else:
                    continue

                nr = dict(r)  # 浅拷贝
                # 归一化 methods / services
                if isinstance(nr.get('methods'), list):
                    nr['methods'] = [str(x).strip().upper() for x in nr['methods'] if str(x).strip()]
                if isinstance(nr.get('services'), list):
                    nr['services'] = [str(x).strip().lower() for x in nr['services'] if str(x).strip()]

                # 保存最终选择的匹配器
                nr.pop('path', None)
                nr.pop('prefix', None)
                nr.pop('regex', None)
                nr[chosen[0]] = chosen[1]

                # 预编译正则
                if chosen[0] == 'regex':
                    try:
                        compiled.append(re.compile(chosen[1]))
                    except re.error:
                        compiled.append(None)
                else:
                    compiled.append(None)

                normalized_rules.append(nr)

            self._rules = normalized_rules
            self._compiled_regex = compiled
            self._file_mtime = self.config_file.stat().st_mtime
            print(f"Endpoint 过滤配置已加载: 启用={self.enabled}, 规则数={len(self._rules)}")
        except Exception as e:
            print(f"加载 Endpoint 过滤配置失败: {e}")
            # 出错时回落到禁用
            self.enabled = False
            self._rules = []
            self._compiled_regex = []
            try:
                self._file_mtime = self.config_file.stat().st_mtime
            except Exception:
                self._file_mtime = 0

    def _create_default_config(self):
        default = {
            'enabled': True,
            'rules': []
        }
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(default, f, ensure_ascii=False, indent=2)
            self.enabled = True
            self._rules = []
            self._compiled_regex = []
            self._file_mtime = self.config_file.stat().st_mtime
            print("已创建默认 Endpoint 过滤配置")
        except Exception as e:
            print(f"创建默认 Endpoint 过滤配置失败: {e}")
            self.enabled = True
            self._rules = []
            self._compiled_regex = []
            self._file_mtime = 0

    def _match_path(self, idx: int, rule: Dict[str, Any], path: str) -> bool:
        # path 精确
        p = rule.get('path')
        if isinstance(p, str) and p:
            return path == p
        # 前缀
        pre = rule.get('prefix')
        if isinstance(pre, str) and pre:
            return path.startswith(pre)
        # 正则
        reg = rule.get('regex')
        if isinstance(reg, str) and reg and idx < len(self._compiled_regex):
            c = self._compiled_regex[idx]
            if c is None:
                return False
            return c.search(path) is not None
        return False

    def _match_query(self, rule_query: Any, actual: Dict[str, str]) -> bool:
        if not rule_query:
            return True
        if not isinstance(rule_query, dict):
            return True
        for k, v in rule_query.items():
            key = str(k)
            if key not in actual:
                return False
            if v is None:
                continue
            vs = str(v)
            if vs == '*':
                continue
            if str(actual.get(key)) != vs:
                return False
        return True


# 全局实例（与其他过滤器保持一致的使用方式）
endpoint_filter = CachedEndpointFilter()


def is_endpoint_blocked(service: str, method: str, path: str, query: Dict[str, str]) -> Optional[MatchResult]:
    """便捷函数：返回命中结果或 None"""
    endpoint_filter.reload()
    return endpoint_filter.match(service, method, path, query)

