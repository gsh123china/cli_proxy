#!/usr/bin/env python3
"""
缓存配置管理器 - 优化配置读取性能
通过缓存机制减少文件I/O操作
"""
import json
import time
import threading
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

def _as_bool(value: Any) -> bool:
    """宽松解析布尔值"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'on'}
    if isinstance(value, (int, float)):
        return bool(value)
    return bool(value)

class CachedConfigManager:
    """带缓存的配置管理器"""
    
    def __init__(self, service_name: str, cache_ttl: float = 5.0):
        """
        初始化缓存配置管理器
        
        Args:
            service_name: 服务名称 (claude/codex)
            cache_ttl: 缓存过期时间（秒），默认5秒
        """
        self.service_name = service_name
        self.cache_ttl = cache_ttl
        self.config_dir = Path.home() / '.clp'
        self.config_file = self.config_dir / f'{service_name}.json'
        
        # 缓存相关
        self._configs_cache: Dict[str, Dict[str, Any]] = {}
        self._all_configs_cache: Dict[str, Dict[str, Any]] = {}
        self._active_config_cache = None
        self._cache_time = 0
        self._file_mtime = 0
        self._lock = threading.RLock()

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
        
    def _should_reload(self) -> bool:
        """
        检查是否需要重新加载配置
        基于文件修改时间和缓存TTL判断
        """
        try:
            # 检查文件修改时间
            current_mtime = self.config_file.stat().st_mtime
            if current_mtime != self._file_mtime:
                return True
                
            # 检查缓存是否过期
            if time.time() - self._cache_time > self.cache_ttl:
                return True
                
            return False
        except (OSError, FileNotFoundError):
            # 文件不存在或无法访问，需要重新加载
            return True
    
    def _load_configs_from_file(self) -> Tuple[Dict[str, Dict[str, Any]], Optional[str], Dict[str, Dict[str, Any]]]:
        """从文件加载配置（内部方法）"""
        created_new = self._ensure_config_file()
        if created_new:
            return {}, None, {}
            
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
                    if deleted_flag:
                        continue

                    configs[config_name] = parsed_config
                    
                    # 检查是否为激活配置
                    if not deleted_flag and config_data.get('active', False):
                        active_config = config_name
                        
        except (json.JSONDecodeError, OSError) as e:
            print(f"配置文件加载失败: {e}")
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False, indent=2)
            return {}, None, {}
            
        # 如果没有激活配置，使用第一个
        if not active_config and configs:
            active_config = list(configs.keys())[0]
            
        return configs, active_config, all_configs
    
    def _refresh_cache(self):
        """刷新缓存（内部方法）"""
        configs, active_config, all_configs = self._load_configs_from_file()
        self._configs_cache = configs
        self._all_configs_cache = all_configs
        self._active_config_cache = active_config
        self._cache_time = time.time()
        
        # 更新文件修改时间
        try:
            self._file_mtime = self.config_file.stat().st_mtime
        except (OSError, FileNotFoundError):
            self._file_mtime = 0
    
    def _get_cached_data(self, include_deleted: bool = False) -> Tuple[Dict[str, Dict[str, Any]], Optional[str]]:
        """获取缓存的配置数据"""
        with self._lock:
            if self._should_reload():
                self._refresh_cache()
            cache = self._all_configs_cache if include_deleted else self._configs_cache
            return {name: cfg.copy() for name, cfg in cache.items()}, self._active_config_cache
    
    @property
    def configs(self) -> Dict[str, Dict[str, Any]]:
        """获取所有配置（使用缓存）"""
        configs, _ = self._get_cached_data()
        return configs

    def get_all_configs(self) -> Dict[str, Dict[str, Any]]:
        """返回包含逻辑删除项在内的配置副本"""
        configs, _ = self._get_cached_data(include_deleted=True)
        return configs
    
    @property
    def active_config(self) -> Optional[str]:
        """获取当前激活的配置名（使用缓存）"""
        _, active_config = self._get_cached_data()
        return active_config
    
    def set_active_config(self, config_name: str) -> bool:
        """
        设置激活配置
        注意：这会立即写入文件并刷新缓存
        """
        with self._lock:
            # 先刷新缓存确保数据最新
            self._refresh_cache()
            
            if config_name not in self._configs_cache:
                return False
            
            try:
                for name, cfg in self._all_configs_cache.items():
                    cfg['active'] = (name == config_name) and not cfg.get('deleted', False)
                self._save_configs(self._all_configs_cache, config_name)
                # 保存成功后立即刷新缓存
                self._refresh_cache()
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

            if 'weight' in config:
                data[name]['weight'] = config['weight']

            if config.get('deleted', False):
                data[name]['deleted'] = True
                if config.get('deleted_at'):
                    data[name]['deleted_at'] = config['deleted_at']
            else:
                data[name].pop('deleted_at', None)
        
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except OSError as e:
            print(f"保存配置文件失败: {e}")
            raise
    
    def get_active_config_data(self) -> Optional[Dict[str, Any]]:
        """获取当前激活配置的数据（使用缓存）"""
        configs, active_config = self._get_cached_data()
        if not active_config:
            return None
        return configs.get(active_config)
    
    def force_reload(self):
        """强制重新加载配置（跳过缓存）"""
        with self._lock:
            self._refresh_cache()

# 创建全局实例（使用缓存版本）
claude_config_manager = CachedConfigManager('claude')
codex_config_manager = CachedConfigManager('codex')
