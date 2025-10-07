#!/usr/bin/env python3
import json
import os
from pathlib import Path
from typing import Dict, Any, Optional

def _as_bool(value: Any) -> bool:
    """宽松解析布尔值"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'on'}
    if isinstance(value, (int, float)):
        return bool(value)
    return bool(value)

class ConfigManager:
    """统一配置管理器"""
    
    def __init__(self, service_name: str):
        self.service_name = service_name
        self.config_dir = Path.home() / '.clp'
        self.config_file = self.config_dir / f'{service_name}.json'
        self._last_all_configs: Dict[str, Dict[str, Any]] = {}

    def _ensure_config_dir(self):
        """确保配置目录存在"""
        self.config_dir.mkdir(exist_ok=True)

    def _ensure_config_file(self) -> bool:
        """确保配置文件存在，返回是否新创建"""
        self._ensure_config_dir()
        if not self.config_file.exists():
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False, indent=2)
            return True
        return False

    def ensure_config_file(self) -> Path:
        """对外暴露的确保配置文件存在的方法"""
        self._ensure_config_file()
        return self.config_file

    def _load_configs(self, include_deleted: bool = False) -> tuple[Dict[str, Dict[str, Any]], Optional[str]]:
        """从文件加载配置，每次都重新读取"""
        created_new = self._ensure_config_file()
        if created_new:
            self._last_all_configs = {}
            return {}, None
            
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            configs = {}
            all_configs: Dict[str, Dict[str, Any]] = {}
            active_config = None
            
            # 解析配置格式
            for config_name, config_data in data.items():
                if 'base_url' in config_data and 'auth_token' in config_data:
                    weight_value = config_data.get('weight', 0)
                    try:
                        weight_value = float(weight_value)
                    except (TypeError, ValueError):
                        weight_value = 0

                    deleted_flag = _as_bool(config_data.get('deleted', False))
                    deleted_at = config_data.get('deleted_at')
                    if deleted_flag and not isinstance(deleted_at, str):
                        deleted_at = None

                    parsed_config: Dict[str, Any] = {
                        'base_url': config_data['base_url'],
                        'auth_token': config_data['auth_token'],
                        'weight': weight_value,
                        'deleted': deleted_flag,
                        'deleted_at': deleted_at,
                        'active': _as_bool(config_data.get('active', False)) and not deleted_flag
                    }

                    # 如果存在 api_key，也保留它
                    if 'api_key' in config_data:
                        parsed_config['api_key'] = config_data['api_key']

                    all_configs[config_name] = parsed_config
                    if deleted_flag and not include_deleted:
                        continue

                    configs[config_name] = parsed_config
                    
                    # 检查是否为激活配置（忽略已逻辑删除的配置）
                    if not deleted_flag and config_data.get('active', False):
                        active_config = config_name
                        
        except (json.JSONDecodeError, OSError) as e:
            print(f"配置文件加载失败: {e}")
            # 创建空文件避免后续请求再次失败
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False, indent=2)
            self._last_all_configs = {}
            return {}, None

        self._last_all_configs = all_configs
            
        # 如果没有激活配置，使用第一个
        if not active_config and configs:
            active_config = list(configs.keys())[0]
            
        return configs, active_config

    @property
    def configs(self) -> Dict[str, Dict[str, Any]]:
        """获取所有配置"""
        configs, _ = self._load_configs()
        return {name: cfg.copy() for name, cfg in configs.items()}

    @property
    def active_config(self) -> Optional[str]:
        """获取当前激活的配置名"""
        _, active_config = self._load_configs()
        return active_config

    def get_all_configs(self) -> Dict[str, Dict[str, Any]]:
        """返回包含逻辑删除项在内的配置副本"""
        self._load_configs(include_deleted=True)
        return {name: cfg.copy() for name, cfg in self._last_all_configs.items()}

    def set_active_config(self, config_name: str) -> bool:
        """设置激活配置"""
        configs, _ = self._load_configs(include_deleted=True)
        target_cfg = configs.get(config_name)
        if not target_cfg or target_cfg.get('deleted'):
            return False
        
        try:
            for name, cfg in configs.items():
                cfg['active'] = (name == config_name) and not cfg.get('deleted', False)
            self._save_configs(configs, config_name)
            return True
        except Exception as e:
            print(f"保存配置失败: {e}")
            return False

    def _save_configs(self, configs: Dict[str, Dict[str, Any]], active_config: str):
        """保存配置到文件"""
        self._ensure_config_dir()
        
        # 构建要保存的数据
        data = {}
        for name, config in configs.items():
            data[name] = {
                'base_url': config['base_url'],
                'auth_token': config.get('auth_token', ''),
                'active': (name == active_config) and not config.get('deleted', False)
            }
            # 如果存在 api_key，也保存它
            if 'api_key' in config:
                data[name]['api_key'] = config['api_key']

            # 如果存在权重，也保存
            if 'weight' in config:
                data[name]['weight'] = config['weight']

            if config.get('deleted', False):
                data[name]['deleted'] = True
                if config.get('deleted_at'):
                    data[name]['deleted_at'] = config['deleted_at']
            else:
                # 确保清理无效的 deleted_at
                if 'deleted_at' in data[name]:
                    data[name].pop('deleted_at', None)
        
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except OSError as e:
            print(f"保存配置文件失败: {e}")
            raise

    def get_active_config_data(self) -> Optional[Dict[str, Any]]:
        """获取当前激活配置的数据"""
        configs, active_config = self._load_configs()
        if not active_config:
            return None
        return configs.get(active_config)

# 全局实例
claude_config_manager = ConfigManager('claude')
codex_config_manager = ConfigManager('codex')
