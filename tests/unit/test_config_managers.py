import json
from pathlib import Path

import pytest

from src.config.config_manager import ConfigManager
from src.config.cached_config_manager import CachedConfigManager


def _write_config(home: Path, service: str, payload: dict) -> Path:
    config_dir = home / '.clp'
    config_dir.mkdir(exist_ok=True)
    config_path = config_dir / f'{service}.json'
    config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return config_path


@pytest.fixture()
def temp_home(monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.setattr('pathlib.Path.home', lambda: tmp_path)
    return tmp_path


def test_config_manager_filters_deleted_entries(temp_home: Path) -> None:
    config_data = {
        'prod': {
            'base_url': 'https://example.com',
            'auth_token': 'token-prod',
            'active': True,
            'weight': 100,
        },
        'backup': {
            'base_url': 'https://backup.example.com',
            'auth_token': 'token-backup',
            'deleted': True,
            'deleted_at': '2025-10-07T03:25:00Z',
            'weight': 50,
        },
    }
    _write_config(temp_home, 'claude', config_data)

    manager = ConfigManager('claude')

    assert set(manager.configs.keys()) == {'prod'}
    assert manager.active_config == 'prod'

    all_configs = manager.get_all_configs()
    assert set(all_configs.keys()) == {'prod', 'backup'}
    assert all_configs['backup']['deleted'] is True


def test_cached_config_manager_filters_deleted_entries(temp_home: Path) -> None:
    config_data = {
        'primary': {
            'base_url': 'https://api.service.local',
            'auth_token': 'key-primary',
            'active': True,
        },
        'deprecated': {
            'base_url': 'https://old.service.local',
            'auth_token': 'key-old',
            'deleted': True,
        },
    }
    _write_config(temp_home, 'codex', config_data)

    manager = CachedConfigManager('codex', cache_ttl=0.01)

    visible = manager.configs
    assert set(visible.keys()) == {'primary'}
    all_configs = manager.get_all_configs()
    assert set(all_configs.keys()) == {'primary', 'deprecated'}


def test_set_active_config_rejects_deleted_entry(temp_home: Path) -> None:
    config_data = {
        'primary': {
            'base_url': 'https://api.valid.local',
            'auth_token': 'key-primary',
            'active': True,
        },
        'disabled': {
            'base_url': 'https://api.disabled.local',
            'auth_token': 'key-disabled',
            'deleted': True,
        },
    }
    _write_config(temp_home, 'claude', config_data)

    manager = ConfigManager('claude')
    assert manager.set_active_config('disabled') is False
    assert manager.active_config == 'primary'
