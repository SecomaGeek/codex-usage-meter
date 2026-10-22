"""Isolated fixtures for screenshots and trial use. Never reads authentication."""
from datetime import datetime,timedelta,timezone
from .models import UsageSnapshot,LimitWindow,ResetCredit,ResetCreditSnapshot

def configure_demo(ui):
    now=datetime.now(timezone.utc)
    credits=tuple(ResetCredit(status='available',title='Full reset (Weekly + 5-hr)',reset_type='codex_rate_limits',granted_at=now-timedelta(days=1),expires_at=now+timedelta(days=1+i,hours=5)) for i in range(3))
    snapshot=UsageSnapshot(limits=(LimitWindow('5時間枠',24,76,300,now+timedelta(hours=3)),LimitWindow('週間枠',16,84,10080,now+timedelta(days=4,hours=8))),reset_credits=ResetCreditSnapshot(3,3,credits),updated_at=now)
    ui.current_account_key=lambda:'demo'
    ui.find_binary=lambda:'demo-no-process'
    ui.api_client.fetch_usage_snapshot=lambda **kwargs:snapshot
