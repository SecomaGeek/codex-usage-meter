"""Read local settings; credentials are never part of application settings."""
from dataclasses import dataclass, fields
from pathlib import Path
import json, os

@dataclass(frozen=True)
class AppConfig:
    refresh_interval_seconds: int = 60
    autostart_with_windows: bool = False
    autostart_with_codex: bool = True
    codex_launch_mode: str = 'cli'
    codex_command: str = 'codex'
    codex_app_path: str = ''
    prevent_multiple_instances: bool = True
    show_startup_animation: bool = True
    highlight_reset_credit_expiry_days: int = 7
    log_level: str = 'INFO'

def default_config_path():
    return Path(os.environ.get('APPDATA',str(Path.home())))/'CodexUsageMeter'/'config.json'

def load_config(path=None):
    defaults=AppConfig()
    try:
        data=json.loads((Path(path) if path else default_config_path()).read_text(encoding='utf-8-sig'))
    except (OSError,ValueError,TypeError): return defaults
    if not isinstance(data,dict): return defaults
    values={}
    for item in fields(defaults):
        value=data.get(item.name,getattr(defaults,item.name))
        if type(value) is type(getattr(defaults,item.name)): values[item.name]=value
    if 'refresh_interval_seconds' in values:
        values['refresh_interval_seconds']=max(0,values['refresh_interval_seconds'])
    return AppConfig(**values)
