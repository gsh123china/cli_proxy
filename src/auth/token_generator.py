#!/usr/bin/env python3
"""
Token 生成器
生成安全的随机 token，用于代理层鉴权
"""

import secrets
import string


def generate_token(length: int = 32, prefix: str = "clp_") -> str:
    """
    生成安全的随机 token

    Args:
        length: token 长度（不包含前缀），默认 32 字符
        prefix: token 前缀，默认 "clp_"

    Returns:
        完整的 token 字符串，格式为 prefix + 随机字符串

    Example:
        >>> token = generate_token()
        >>> token.startswith("clp_")
        True
        >>> len(token) == 36  # "clp_" (4) + 32 字符
        True
    """
    # 使用 Base62 字符集（数字 + 大小写字母）
    alphabet = string.ascii_letters + string.digits

    # 使用 secrets 模块生成密码学安全的随机字符串
    random_part = ''.join(secrets.choice(alphabet) for _ in range(length))

    return f"{prefix}{random_part}"


def validate_token_format(token: str, prefix: str = "clp_", min_length: int = 32) -> bool:
    """
    验证 token 格式是否正确

    Args:
        token: 要验证的 token
        prefix: 期望的前缀
        min_length: 最小长度（不包含前缀）

    Returns:
        True 如果格式有效，否则 False
    """
    if not token or not isinstance(token, str):
        return False

    if not token.startswith(prefix):
        return False

    token_body = token[len(prefix):]
    if len(token_body) < min_length:
        return False

    # 验证字符只包含 Base62 字符集
    allowed_chars = set(string.ascii_letters + string.digits)
    return all(c in allowed_chars for c in token_body)