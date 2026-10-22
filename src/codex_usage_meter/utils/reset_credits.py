"""Labels for states present in the original distribution."""
def reset_credit_status_label(status):
    return {'available':'利用可能','active':'利用可能','unused':'利用可能','redeemed':'使用済み','used':'使用済み','expired':'失効済み'}.get((status or '').lower(),'状態不明')

def is_reset_credit_expiring_soon(credit, days, now=None):
    from datetime import datetime,timezone,timedelta
    return credit.expires_at is not None and 0<(credit.expires_at-(now or datetime.now(timezone.utc))).total_seconds()<=timedelta(days=days).total_seconds()
