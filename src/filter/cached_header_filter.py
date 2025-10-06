#!/usr/bin/env python3
"""
缓存请求头过滤器 - 优化配置加载性能
通过监控文件修改时间来决定是否重新加载
"""
import json
import time
from pathlib import Path
from typing import Dict, Set


class CachedHeaderFilter:
    """带缓存的请求头过滤器"""

    def __init__(self, cache_check_interval: float = 1.0):
        """
        初始化缓存过滤器

        Args:
            cache_check_interval: 检查文件修改的最小间隔（秒）
        """
        self.config_file = Path.home() / '.clp' / 'header_filter.json'
        self.blocked_headers: Set[str] = set()
        self.enabled = True
        self._file_mtime = 0
        self._last_check_time = 0
        self.cache_check_interval = cache_check_interval

        # 初始加载配置
        self._load_config(force=True)

    def _should_reload(self) -> bool:
        """
        检查是否需要重新加载配置
        通过文件修改时间判断
        """
        # 限制检查频率，避免过于频繁的stat调用
        current_time = time.time()
        if current_time - self._last_check_time < self.cache_check_interval:
            return False

        self._last_check_time = current_time

        try:
            if not self.config_file.exists():
                # 文件不存在，如果之前有配置则需要重置为默认
                if self.blocked_headers or self._file_mtime != 0:
                    return True
                return False

            current_mtime = self.config_file.stat().st_mtime
            if current_mtime != self._file_mtime:
                return True

            return False
        except (OSError, FileNotFoundError):
            return False

    def _load_config(self, force: bool = False):
        """
        加载过滤配置（使用缓存）

        Args:
            force: 是否强制重新加载
        """
        if not force and not self._should_reload():
            return  # 使用缓存的配置

        try:
            if not self.config_file.exists():
                self._create_default_config()
                return

            with open(self.config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            self.enabled = data.get('enabled', True)
            blocked_list = data.get('blocked_headers', [])

            if isinstance(blocked_list, list):
                self.blocked_headers = {h.lower().strip() for h in blocked_list if h}
            else:
                self.blocked_headers = set()

            # 更新文件修改时间
            self._file_mtime = self.config_file.stat().st_mtime

            print(f"Header 过滤配置已加载: 启用={self.enabled}, 黑名单数量={len(self.blocked_headers)}")

        except (json.JSONDecodeError, IOError) as e:
            print(f"加载 Header 过滤配置失败: {e}")
            self._create_default_config()

    def _create_default_config(self):
        """创建默认配置文件"""
        default_config = {
            'enabled': True,
            'blocked_headers': [
                'x-forwarded-for',
                'x-forwarded-proto',
                'x-forwarded-scheme',
                'x-real-ip',
                'x-forwarded-host',
                'x-forwarded-port',
                'x-forwarded-server'
            ]
        }

        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, ensure_ascii=False, indent=2)

            self.enabled = default_config['enabled']
            self.blocked_headers = {h.lower() for h in default_config['blocked_headers']}
            self._file_mtime = self.config_file.stat().st_mtime

            print("已创建默认 Header 过滤配置")
        except Exception as e:
            print(f"创建默认 Header 过滤配置失败: {e}")
            self.enabled = True
            self.blocked_headers = set()
            self._file_mtime = 0

    def filter_headers(self, headers: Dict[str, str]) -> Dict[str, str]:
        """
        过滤 HTTP Headers，移除黑名单中的 headers

        Args:
            headers: 原始 headers 字典

        Returns:
            过滤后的 headers 字典
        """
        if not self.enabled or not self.blocked_headers:
            return headers

        return {
            k: v for k, v in headers.items()
            if k.lower() not in self.blocked_headers
        }

    def reload_config(self):
        """重新加载配置文件（使用缓存机制）"""
        self._load_config()

    def force_reload(self):
        """强制重新加载配置"""
        self._load_config(force=True)


# 创建全局实例
cached_header_filter = CachedHeaderFilter()


def filter_request_headers(headers: Dict[str, str]) -> Dict[str, str]:
    """
    兼容性函数 - 过滤请求头

    Args:
        headers: 原始 headers 字典

    Returns:
        过滤后的 headers 字典
    """
    cached_header_filter.reload_config()
    return cached_header_filter.filter_headers(headers)


def reload_header_filter():
    """重新加载 Header 过滤规则的便捷函数"""
    cached_header_filter.reload_config()
