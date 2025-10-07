import json
from importlib import reload
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.core.base_proxy import BaseProxyService


class _DummyConfigManager:
    """最小配置管理器，满足 BaseProxyService 在阻断路径上的依赖"""

    def __init__(self):
        self.configs = {}
        self.active_config = None

    def get_all_configs(self):  # pragma: no cover - 兼容潜在访问
        return {}


class _DummyProxy(BaseProxyService):
    """最小实现，用于测试 Endpoint Filter 的短路逻辑"""

    def __init__(self):
        super().__init__('codex', port=9999, config_manager=_DummyConfigManager())

    def test_endpoint(self, model: str, base_url: str, auth_token: str = None, api_key: str = None, extra_params: dict = None) -> dict:
        return {}


@pytest.fixture()
def temp_home(monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.setattr('pathlib.Path.home', lambda: tmp_path)
    return tmp_path


def _write_endpoint_filter(home: Path, payload: dict) -> Path:
    config_dir = home / '.clp'
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / 'endpoint_filter.json'
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return path


def test_blocked_request_short_circuits_before_upstream(monkeypatch, temp_home: Path) -> None:
    # 写入规则：阻断 count_tokens 接口
    _write_endpoint_filter(temp_home, {
        'enabled': True,
        'rules': [
            {
                'id': 'block-count-tokens',
                'services': ['codex'],
                'methods': ['POST'],
                'path': '/api/v1/messages/count_tokens',
                'query': {'beta': 'true'},
                'action': {'type': 'block', 'status': 451, 'message': 'blocked in tests'},
            }
        ],
    })

    proxy = _DummyProxy()

    async def fail_send(*args, **kwargs):  # pragma: no cover - 被调用时测试应失败
        raise AssertionError('Upstream should not be invoked when endpoint filter blocks')

    monkeypatch.setattr(proxy.client, 'send', fail_send)

    with TestClient(proxy.app) as client:
        response = client.post('/api/v1/messages/count_tokens?beta=true', json={'foo': 'bar'})

    assert response.status_code == 451
    body = response.json()
    assert body['error'] == 'ENDPOINT_BLOCKED'
    assert body['rule_id'] == 'block-count-tokens'
    assert body['message'] == 'blocked in tests'


@pytest.fixture()
def ui_app(monkeypatch, tmp_path: Path):
    monkeypatch.setattr('pathlib.Path.home', lambda: tmp_path)
    from src.ui import ui_server

    # 重新加载模块以便使用新的 HOME 路径
    reload(ui_server)
    yield ui_server.app


def test_endpoint_filter_api_roundtrip(ui_app, tmp_path: Path):
    client = ui_app.test_client()

    resp = client.get('/api/endpoint-filter')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['config']['enabled'] is True
    assert data['config']['rules'] == []

    payload = {
        'enabled': True,
        'rules': [
            {
                'id': 'block-count-tokens',
                'services': ['claude', 'codex'],
                'methods': ['GET', 'POST'],
                'path': '/api/v1/messages/count_tokens',
                'query': {'beta': 'true'},
                'action': {'type': 'block', 'status': 403, 'message': 'count_tokens disabled'},
            }
        ],
    }

    save_resp = client.post('/api/endpoint-filter', json=payload)
    assert save_resp.status_code == 200
    save_data = save_resp.get_json()
    assert save_data['success'] is True

    config_path = tmp_path / '.clp' / 'endpoint_filter.json'
    assert config_path.exists()
    saved = json.loads(config_path.read_text(encoding='utf-8'))
    assert saved['enabled'] is True
    assert len(saved['rules']) == 1
    saved_rule = saved['rules'][0]
    assert saved_rule['id'] == 'block-count-tokens'
    assert saved_rule['services'] == ['claude', 'codex']
    assert saved_rule['methods'] == ['GET', 'POST']
    assert saved_rule['path'] == '/api/v1/messages/count_tokens'
    assert saved_rule['query'] == {'beta': 'true'}
    assert saved_rule['action'] == {
        'type': 'block',
        'status': 403,
        'message': 'count_tokens disabled',
    }
