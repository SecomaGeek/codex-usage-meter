"""Existing Japanese countdown conventions, evaluated from absolute UTC time."""
from datetime import datetime, timezone

def format_remaining_time(reset_at, now=None):
    if reset_at is None: return '不明'
    current=now or datetime.now(timezone.utc)
    seconds=max(0,int((reset_at-current).total_seconds()))
    days=seconds//86400; hours=seconds%86400//3600; minutes=seconds%3600//60
    if days: return f'あと{days}日{hours}時間'
    if hours: return f'あと{hours}時間{minutes}分'
    if minutes: return f'あと{minutes}分'
    return 'まもなく'

def format_local_datetime(value):
    return value.astimezone().strftime('%Y-%m-%d %H:%M:%S %Z (UTC%z)') if value else '不明'

def reset_countdown_percent(reset_at, window, now=None):
    if reset_at is None or window is None or window.total_seconds()<=0: return None
    return max(0.,min(100.,(reset_at-(now or datetime.now(timezone.utc))).total_seconds()/window.total_seconds()*100))
