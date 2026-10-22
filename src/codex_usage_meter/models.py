"""Immutable snapshots shared by the read-only client and UI."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import math

@dataclass(frozen=True)
class LimitWindow:
    label: str
    used_percent: float | None = None
    remaining_percent: float | None = None
    window_minutes: int | None = None
    resets_at: datetime | None = None

@dataclass(frozen=True)
class ResetCredit:
    status: str
    title: str = ''
    reset_type: str = ''
    description: str = ''
    granted_at: datetime | None = None
    expires_at: datetime | None = None
    redeemed_at: datetime | None = None

@dataclass(frozen=True)
class ResetCreditSnapshot:
    available_count: int | None = None
    total_earned_count: int | None = None
    credits: tuple[ResetCredit, ...] = ()
    error: str = ''

@dataclass(frozen=True)
class UsageSnapshot:
    limits: tuple[LimitWindow, ...] = ()
    reset_credits: ResetCreditSnapshot = field(default_factory=ResetCreditSnapshot)
    updated_at: datetime | None = None
    error: str = ''

def clamp_percent(value):
    if type(value) not in (int,float) or not math.isfinite(value): return None
    return max(0.,min(100.,float(value)))

def datetime_from_unix(value):
    # The rate-limit contract specifies seconds. Never infer milliseconds.
    if type(value) not in (int,float) or not math.isfinite(value): return None
    try: return datetime.fromtimestamp(value,timezone.utc)
    except (ValueError,OverflowError,OSError): return None

def parse_iso_datetime(value):
    if not isinstance(value,str): return None
    try:
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except (ValueError,TypeError,OverflowError): return None
