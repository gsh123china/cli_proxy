import json
from importlib import reload
from pathlib import Path

def _write_jsonl(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as fh:
        for entry in entries:
            fh.write(json.dumps(entry, ensure_ascii=False) + '\n')


def test_usage_details_tokens_split_by_service(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr('pathlib.Path.home', lambda: tmp_path)
    from src.ui import ui_server

    reload(ui_server)

    base_dir = tmp_path / '.clp'
    data_dir = base_dir / 'data'

    assert Path.home() == tmp_path

    logs_path = data_dir / 'proxy_requests.jsonl'
    _write_jsonl(logs_path, [
        {
            'service': 'claude',
            'channel': 'site-a',
            'usage': {
                'service': 'claude',
                'metrics': {
                    'input': 120,
                    'cached_create': 5,
                    'cached_read': 0,
                    'output': 60,
                    'reasoning': 0,
                    'total': 185,
                },
            },
            'original_headers': {
                'x-api-key': 'clp_test_mixed',
            },
        },
        {
            'service': 'codex',
            'channel': 'site-b',
            'usage': {
                'service': 'codex',
                'metrics': {
                    'input': 300,
                    'cached_create': 0,
                    'cached_read': 120,
                    'output': 210,
                    'reasoning': 30,
                    'total': 660,
                },
            },
            'original_headers': {
                'x-api-key': 'clp_test_mixed',
            },
        },
        {
            'service': 'claude',
            'channel': 'site-c',
            'usage': {
                'service': 'claude',
                'metrics': {
                    'input': 42,
                    'cached_create': 0,
                    'cached_read': 0,
                    'output': 21,
                    'reasoning': 0,
                    'total': 63,
                },
            },
            'original_headers': {
                'authorization': 'Bearer clp_test_claude',
            },
        },
    ])

    auth_config = {
        'enabled': False,
        'tokens': [
            {
                'token': 'clp_test_mixed',
                'name': 'mixed-client',
                'services': ['claude', 'codex'],
            },
            {
                'token': 'clp_test_claude',
                'name': 'claude-only',
                'services': ['claude', 'codex'],
            },
        ],
        'services': {
            'ui': True,
            'claude': True,
            'codex': True,
        },
    }
    auth_path = base_dir / 'auth.json'
    auth_path.parent.mkdir(parents=True, exist_ok=True)
    auth_path.write_text(json.dumps(auth_config, ensure_ascii=False, indent=2), encoding='utf-8')

    reload(ui_server)
    client = ui_server.app.test_client()
    response = client.get('/api/usage/details')

    assert response.status_code == 200
    raw_json = response.get_data(as_text=True)
    assert '"codex"' in raw_json
    payload = response.get_json()

    tokens = payload['tokens']
    assert 'mixed-client' in tokens
    assert 'claude-only' in tokens

    mixed = tokens['mixed-client']
    assert set(mixed['services'].keys()) == {'claude', 'codex'}
    claude_metrics = mixed['services']['claude']['overall']['metrics']
    codex_metrics = mixed['services']['codex']['overall']['metrics']

    assert claude_metrics['input'] == 120
    assert claude_metrics['output'] == 60
    assert codex_metrics['input'] == 300
    assert codex_metrics['cached_read'] == 120
    assert mixed['services']['codex']['channels']['site-b']['metrics']['output'] == 210
    assert mixed['totals']['metrics']['total'] == 185 + 660

    claude_only = tokens['claude-only']
    assert 'claude' in claude_only['services']
    assert claude_only['totals']['metrics']['total'] == 63
