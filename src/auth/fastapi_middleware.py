#!/usr/bin/env python3
"""
FastAPI 鉴权中间件
拦截所有请求进行 token 验证
"""

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Callable, Set

from .auth_manager import AuthManager


class AuthMiddleware(BaseHTTPMiddleware):
    """FastAPI 鉴权中间件"""

    def __init__(
        self,
        app,
        auth_manager: AuthManager,
        service_name: str = "proxy",
        whitelist_paths: Set[str] = None
    ):
        """
        初始化中间件

        Args:
            app: FastAPI 应用实例
            auth_manager: AuthManager 实例
            service_name: 服务名称（用于检查是否启用鉴权）
            whitelist_paths: 白名单路径集合（这些路径不需要鉴权）
        """
        super().__init__(app)
        self.auth_manager = auth_manager
        self.service_name = service_name

        # 默认白名单
        self.whitelist_paths = whitelist_paths or {
            '/health',
            '/ping',
            '/favicon.ico'
        }

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        请求拦截处理

        Args:
            request: 请求对象
            call_next: 下一个处理器

        Returns:
            响应对象
        """
        # 检查是否启用鉴权
        if not self.auth_manager.is_enabled(self.service_name):
            return await call_next(request)

        # 白名单路径直接放行
        if request.url.path in self.whitelist_paths:
            return await call_next(request)

        # 提取 token
        token = self._extract_token(request)

        # 验证 token
        if not token or not self.auth_manager.verify_token(token, self.service_name):
            return JSONResponse(
                status_code=401,
                content={
                    "error": "Unauthorized",
                    "message": "无效的认证令牌或令牌已过期"
                }
            )

        # token 验证通过，继续处理请求
        return await call_next(request)

    def _extract_token(self, request: Request) -> str:
        """
        从请求中提取 token

        优先级：
        1. Authorization: Bearer clp_xxx
        2. X-API-Key: clp_xxx
        3. Query参数: ?token=clp_xxx (WebSocket)

        Args:
            request: 请求对象

        Returns:
            token 字符串，如果未找到则返回空字符串
        """
        # 1. 尝试从 Authorization Bearer 获取
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:].strip()
            # 只接受 clp_ 前缀的 token（区分代理层和上游层认证）
            if token.startswith('clp_'):
                return token

        # 2. 尝试从 X-API-Key 获取
        api_key = request.headers.get('X-API-Key', '')
        if api_key and api_key.startswith('clp_'):
            return api_key

        # 3. 尝试从 query 参数获取（主要用于 WebSocket）
        token_param = request.query_params.get('token', '')
        if token_param and token_param.startswith('clp_'):
            return token_param

        return ''
