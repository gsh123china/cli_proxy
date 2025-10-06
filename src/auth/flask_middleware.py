#!/usr/bin/env python3
"""
Flask 鉴权中间件
使用 before_request 钩子进行 token 验证
"""

from flask import Flask, request, jsonify
from typing import Optional, Set

from .auth_manager import AuthManager


class FlaskAuthMiddleware:
    """Flask 鉴权中间件"""

    def __init__(
        self,
        app: Flask,
        auth_manager: AuthManager,
        service_name: str = "ui",
        whitelist_paths: Set[str] = None,
        whitelist_prefixes: Set[str] = None
    ):
        """
        初始化中间件并注册到 Flask 应用

        Args:
            app: Flask 应用实例
            auth_manager: AuthManager 实例
            service_name: 服务名称
            whitelist_paths: 白名单路径集合
            whitelist_prefixes: 白名单路径前缀集合
        """
        self.auth_manager = auth_manager
        self.service_name = service_name

        # 默认白名单
        self.whitelist_paths = whitelist_paths or {
            '/',
            '/health',
            '/ping',
            '/favicon.ico'
        }

        self.whitelist_prefixes = whitelist_prefixes or {
            '/static/',
        }

        # 注册 before_request 钩子
        app.before_request(self._check_auth)

    def _check_auth(self) -> Optional:
        """
        请求前检查鉴权

        Returns:
            None 如果验证通过，否则返回错误响应
        """
        # 检查是否启用鉴权
        if not self.auth_manager.is_enabled(self.service_name):
            return None

        # 白名单路径直接放行
        if request.path in self.whitelist_paths:
            return None

        # 白名单前缀匹配
        for prefix in self.whitelist_prefixes:
            if request.path.startswith(prefix):
                return None

        # 提取 token
        token = self._extract_token()

        # 验证 token
        if not token or not self.auth_manager.verify_token(token, self.service_name):
            return jsonify({
                "error": "Unauthorized",
                "message": "无效的认证令牌或令牌已过期"
            }), 401

        # 验证通过，继续处理请求
        return None

    def _extract_token(self) -> str:
        """
        从请求中提取 token

        优先级：
        1. Authorization: Bearer clp_xxx
        2. X-API-Key: clp_xxx
        3. Query参数: ?token=clp_xxx

        Returns:
            token 字符串，如果未找到则返回空字符串
        """
        # 1. 尝试从 Authorization Bearer 获取
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:].strip()
            if token.startswith('clp_'):
                return token

        # 2. 尝试从 X-API-Key 获取
        api_key = request.headers.get('X-API-Key', '')
        if api_key and api_key.startswith('clp_'):
            return api_key

        # 3. 尝试从 query 参数获取
        token_param = request.args.get('token', '')
        if token_param and token_param.startswith('clp_'):
            return token_param

        return ''
