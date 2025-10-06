import json
from pathlib import Path
from typing import Dict, Set


class HeaderFilter:
    """请求头过滤器 - 用于过滤和处理 HTTP Headers"""

    def __init__(self):
        self.config_file = Path.home() / '.clp' / 'header_filter.json'
        self.blocked_headers: Set[str] = set()
        self.enabled = True
        self._load_config()

    def _load_config(self):
        """从配置文件加载过滤规则"""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                self.enabled = data.get('enabled', True)
                blocked_list = data.get('blocked_headers', [])

                if isinstance(blocked_list, list):
                    self.blocked_headers = {h.lower().strip() for h in blocked_list if h}
                else:
                    self.blocked_headers = set()
            else:
                self._create_default_config()

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
        except Exception as e:
            print(f"创建默认 Header 过滤配置失败: {e}")
            self.enabled = True
            self.blocked_headers = set()

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
        """重新加载配置文件"""
        self._load_config()


header_filter = HeaderFilter()


def filter_request_headers(headers: Dict[str, str]) -> Dict[str, str]:
    """
    过滤请求头的便捷函数

    Args:
        headers: 原始 headers 字典

    Returns:
        过滤后的 headers 字典
    """
    header_filter.reload_config()
    return header_filter.filter_headers(headers)


def reload_header_filter():
    """重新加载 Header 过滤规则的便捷函数"""
    header_filter.reload_config()
