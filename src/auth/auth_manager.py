#!/usr/bin/env python3
"""
鉴权管理器
负责加载、验证和管理 auth.json 配置文件
"""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


class AuthManager:
    """鉴权配置管理器"""

    def __init__(self, config_dir: Optional[Path] = None):
        """
        初始化鉴权管理器

        Args:
            config_dir: 配置目录路径，默认为 ~/.clp
        """
        self.config_dir = config_dir or Path.home() / '.clp'
        self.auth_file = self.config_dir / 'auth.json'

        # 文件签名缓存（用于检测配置变更）
        self._file_signature: Tuple[int, int] = (0, 0)
        self._cached_config: Optional[Dict[str, Any]] = None

    def _ensure_config_dir(self):
        """确保配置目录存在"""
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def _get_file_signature(self) -> Tuple[int, int]:
        """获取文件签名（mtime_ns, size）"""
        try:
            stat = self.auth_file.stat()
            return (stat.st_mtime_ns, stat.st_size)
        except FileNotFoundError:
            return (0, 0)
        except OSError:
            return (0, 0)

    def _load_config(self, force: bool = False) -> Dict[str, Any]:
        """
        从文件加载配置，使用文件签名缓存

        Args:
            force: 是否强制重新加载

        Returns:
            配置字典
        """
        current_signature = self._get_file_signature()

        # 如果文件未变化且有缓存，直接返回缓存
        if not force and self._cached_config is not None and current_signature == self._file_signature:
            return self._cached_config

        # 文件不存在或变化了，重新加载
        if not self.auth_file.exists():
            config = self._default_config()
        else:
            try:
                with open(self.auth_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    # 确保配置结构完整
                    config = self._normalize_config(config)
            except (json.JSONDecodeError, OSError) as e:
                print(f"加载鉴权配置失败: {e}")
                config = self._default_config()

        # 更新缓存
        self._cached_config = config
        self._file_signature = current_signature

        return config

    def _default_config(self) -> Dict[str, Any]:
        """返回默认配置"""
        return {
            "enabled": False,  # 默认关闭，向后兼容
            "tokens": [],
            "services": {
                "ui": True,
                "claude": True,
                "codex": True
            }
        }

    def _normalize_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """规范化配置结构"""
        normalized = self._default_config()

        # 合并配置
        if 'enabled' in config:
            normalized['enabled'] = bool(config['enabled'])

        if 'tokens' in config and isinstance(config['tokens'], list):
            normalized['tokens'] = config['tokens']

        if 'services' in config and isinstance(config['services'], dict):
            normalized['services'].update(config['services'])

        return normalized

    def _save_config(self, config: Dict[str, Any]):
        """保存配置到文件"""
        self._ensure_config_dir()

        try:
            with open(self.auth_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)

            # 更新缓存和签名
            self._cached_config = config
            self._file_signature = self._get_file_signature()
        except OSError as e:
            print(f"保存鉴权配置失败: {e}")
            raise

    def is_enabled(self, service: Optional[str] = None) -> bool:
        """
        检查鉴权是否启用

        Args:
            service: 服务名称（ui/claude/codex），None 表示检查全局开关

        Returns:
            True 如果启用，否则 False
        """
        config = self._load_config()

        # 全局开关关闭
        if not config.get('enabled', False):
            return False

        # 检查特定服务
        if service:
            services = config.get('services', {})
            return services.get(service, True)

        return True

    def verify_token(self, token: str) -> bool:
        """
        验证 token 是否有效

        Args:
            token: 要验证的 token

        Returns:
            True 如果有效，否则 False
        """
        if not token or not isinstance(token, str):
            return False

        config = self._load_config()
        tokens = config.get('tokens', [])

        for token_entry in tokens:
            if not isinstance(token_entry, dict):
                continue

            # 检查 token 值
            if token_entry.get('token') != token:
                continue

            # 检查是否激活
            if not token_entry.get('active', True):
                continue

            # 检查是否过期
            expires_at = token_entry.get('expires_at')
            if expires_at:
                try:
                    expire_time = datetime.fromisoformat(expires_at)
                    if datetime.now() > expire_time:
                        continue
                except (ValueError, TypeError):
                    pass

            return True

        return False

    def add_token(self, token: str, name: str, description: str = "", expires_at: Optional[str] = None) -> bool:
        """
        添加新 token

        Args:
            token: token 字符串
            name: token 名称（唯一标识）
            description: 描述信息
            expires_at: 过期时间（ISO格式字符串），None 表示永不过期

        Returns:
            True 如果添加成功，否则 False
        """
        config = self._load_config()
        tokens = config.get('tokens', [])

        # 检查名称是否已存在
        for existing in tokens:
            if isinstance(existing, dict) and existing.get('name') == name:
                print(f"Token 名称 '{name}' 已存在")
                return False

        # 添加新 token
        new_token = {
            "token": token,
            "name": name,
            "description": description,
            "created_at": datetime.now().isoformat(),
            "expires_at": expires_at,
            "active": True
        }

        tokens.append(new_token)
        config['tokens'] = tokens

        self._save_config(config)
        return True

    def remove_token(self, name: str) -> bool:
        """
        删除 token

        Args:
            name: token 名称

        Returns:
            True 如果删除成功，否则 False
        """
        config = self._load_config()
        tokens = config.get('tokens', [])

        # 过滤掉要删除的 token
        new_tokens = [t for t in tokens if not (isinstance(t, dict) and t.get('name') == name)]

        if len(new_tokens) == len(tokens):
            print(f"Token '{name}' 不存在")
            return False

        config['tokens'] = new_tokens
        self._save_config(config)
        return True

    def set_token_active(self, name: str, active: bool) -> bool:
        """
        启用或禁用 token

        Args:
            name: token 名称
            active: True 启用，False 禁用

        Returns:
            True 如果操作成功，否则 False
        """
        config = self._load_config()
        tokens = config.get('tokens', [])

        found = False
        for token_entry in tokens:
            if isinstance(token_entry, dict) and token_entry.get('name') == name:
                token_entry['active'] = active
                found = True
                break

        if not found:
            print(f"Token '{name}' 不存在")
            return False

        config['tokens'] = tokens
        self._save_config(config)
        return True

    def set_enabled(self, enabled: bool):
        """
        设置全局启用状态

        Args:
            enabled: True 启用鉴权，False 关闭鉴权
        """
        config = self._load_config()
        config['enabled'] = enabled
        self._save_config(config)

    def list_tokens(self) -> List[Dict[str, Any]]:
        """
        列出所有 token

        Returns:
            token 列表
        """
        config = self._load_config()
        return config.get('tokens', [])

    def ensure_config_file(self) -> Path:
        """
        确保配置文件存在，如果不存在则创建默认配置

        Returns:
            配置文件路径
        """
        if not self.auth_file.exists():
            self._save_config(self._default_config())
        return self.auth_file