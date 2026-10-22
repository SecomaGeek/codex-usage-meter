"""Read-only Full Reset state. No usage-window data is accepted by this module."""
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import math

UTC = timezone.utc
PALETTE = (None, '#ef5b58', '#f4d35e', '#c4db60', '#68ca88', '#65c8b2', '#7fd3e7', '#8cbac8', '#d998d6', '#f4f6fa')
AVAILABLE = frozenset(('available','active','unused'))  # Existing packaged status map.
EXCLUDED = frozenset(('redeemed','used','expired'))

def positive_integer(value, allow_zero=False):
    return type(value) is int and value >= (0 if allow_zero else 1)

def parse_utc(value, unit='iso'):
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo is not None else None
    try:
        if unit in ('s','ms') and type(value) in (int,float) and math.isfinite(value):
            return datetime.fromtimestamp(value/(1000 if unit=='ms' else 1),UTC)
        if unit=='iso' and isinstance(value,str) and value:
            parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
            return parsed.astimezone(UTC) if parsed.tzinfo is not None else None
    except (ValueError,TypeError,OverflowError,OSError):
        pass
    return None

def segment_levels(count):
    if not positive_integer(count,True):
        return None
    capped=min(count,45)
    return tuple(max(0,min(9,(capped-i+4)//5)) for i in range(5))

def format_exp(seconds):
    """Two rows: whole days above, remaining hours (or finer units) below."""
    if not isinstance(seconds,(int,float)) or not math.isfinite(seconds) or seconds<=0:
        return ''
    whole=math.floor(seconds)
    days=whole//86400
    if seconds>=3600:
        detail=f'{whole%86400//3600}h'
    elif seconds>=60:
        detail=f'{whole//60}m'
    else:
        detail='<1m'
    return f'EXP {days}d\n{detail}'

@dataclass(frozen=True)
class Right:
    identifier: str | None
    status: str
    expires: datetime | None
    units: int = 1
    expiry_valid: bool = True
    unlimited: bool = False
    starts: datetime | None = None
    supported: bool = True
    redeemed: bool = False
    title: str = 'Full reset (Weekly + 5-hr)'

@dataclass(frozen=True)
class RightsBundle:
    account: str
    revision: int
    received: datetime
    rights: tuple[Right,...]
    reported_count: int | None
    complete: bool = True
    errors: tuple[str,...] = ()
    total_earned: int | None = None

@dataclass(frozen=True)
class RightsView:
    state: str
    count: int | None
    earliest: datetime | None = None
    exp: str = ''
    reason: str = ''
    eligible: tuple[Right,...] = ()
    color: str | None = None


def canonical_rights(rights):
    seen={}; result=[]; errors=[]
    for right in rights:
        if right.identifier:
            if right.identifier in seen:
                if seen[right.identifier]!=right: errors.append('同じ権利IDの内容が不整合です。')
                continue
            seen[right.identifier]=right
        if not positive_integer(right.units,True): errors.append('権利の残回数が不正です。')
        result.append(right)
    return tuple(result),tuple(errors)


def normalize_payload(payload, account, revision, received):
    """Actual API: credits[] is one right each; dates are offset-aware ISO strings.
    There is no observed grouped-count or unlimited field; neither is invented.
    """
    errors=[]; rights=[]
    if account=='unauthenticated': errors.append('対象アカウントを確認できません。')
    reported=payload.get('available_count')
    if not positive_integer(reported,True): errors.append('利用可能回数を確認できません。')
    raw=payload.get('credits')
    if not isinstance(raw,list):
        raw=[]; errors.append('権利一覧が欠損しています。')
    for item in raw:
        if not isinstance(item,dict): errors.append('権利一覧に不正な項目があります。'); continue
        if item.get('reset_type')!='codex_rate_limits':
            errors.append('未確認のリセット権種別です。')
        status=item.get('status')
        status=status.lower() if isinstance(status,str) else ''
        expiry=parse_utc(item.get('expires_at'))
        granted=parse_utc(item.get('granted_at'))
        supported=item.get('is_supported_by_plan',True) is True
        redeemed=item.get('redeemed_at') is not None or item.get('redeem_started_at') is not None
        identifier=item.get('id')
        if not isinstance(identifier,str) or not identifier:
            errors.append('権利IDを確認できません。')
        if type(item.get('is_supported_by_plan',True)) is not bool:
            errors.append('プラン対応状態が不正です。')
        if status in AVAILABLE and supported and not redeemed and item.get('granted_at') is not None and granted is None:
            errors.append('付与日時が不正です。')
        rights.append(Right(identifier if isinstance(identifier,str) and identifier else None,status,expiry,
                            expiry_valid=expiry is not None,starts=granted,supported=supported,redeemed=redeemed,
                            title=item.get('title') if isinstance(item.get('title'),str) else 'Full reset (Weekly + 5-hr)'))
    unique,problems=canonical_rights(rights); errors.extend(problems)
    eligible=[r for r in unique if r.status in AVAILABLE and r.supported and not r.redeemed
              and (r.starts is None or r.starts<=received) and (r.expires is None or r.expires>received) and r.units>0]
    # The endpoint has no pagination field in the observed schema. Matching the
    # unique available list with the authoritative total confirms current coverage.
    listed=sum(r.units for r in eligible)
    complete=positive_integer(reported,True) and listed==reported
    if not complete and positive_integer(reported,True): errors.append('合計回数と権利一覧が一致しないか、一覧が不足しています。')
    unknown=any(r.status not in AVAILABLE|EXCLUDED and r.supported and not r.redeemed and r.units for r in unique)
    if unknown: errors.append('未確認の権利状態が含まれています。')
    return RightsBundle(account,revision,received,unique,reported,complete,tuple(errors),payload.get('total_earned_count'))


def normalize_legacy(snapshot, account, revision, received):
    """Fallback for test/custom providers without raw IDs; do not deduplicate by date."""
    rights=tuple(Right(None,(c.status or '').lower(),parse_utc(c.expires_at),expiry_valid=parse_utc(c.expires_at) is not None,
                       starts=parse_utc(c.granted_at),redeemed=c.redeemed_at is not None,title=c.title or '') for c in snapshot.credits)
    count=snapshot.available_count
    eligible=[r for r in rights if r.status in AVAILABLE and not r.redeemed and (r.starts is None or r.starts<=received)
              and (r.expires is None or r.expires>received)]
    complete=positive_integer(count,True) and len(eligible)==count
    errors=() if complete else ('合計回数と権利一覧が一致しないか、一覧が不足しています。',)
    return RightsBundle(account,revision,received,rights,count,complete,errors,snapshot.total_earned_count)


class RightsEngine:
    def __init__(self, account=''):
        self.account=account; self.bundle=None; self.revision=-1; self.failure=''; self.fetching=False
        self.expired=set(); self.clock_untrusted=False; self.resume_recheck=False; self.last_wall=None; self.last_mono=None

    def switch_account(self, account):
        if account!=self.account:
            self.__init__(account)
            return True
        return False

    def accept(self, bundle):
        if bundle.account!=self.account or bundle.revision<self.revision:
            return False
        rights,problems=canonical_rights(bundle.rights)
        bundle=replace(bundle,rights=rights)
        initial=sum(r.units for r in rights if positive_integer(r.units) and r.status in AVAILABLE and r.supported and not r.redeemed
                    and (r.starts is None or r.starts<=bundle.received) and (r.expires is None or r.expires>bundle.received))
        if bundle.complete and (initial!=bundle.reported_count or problems):
            bundle=replace(bundle,complete=False,errors=bundle.errors+problems+('合計回数と一覧が不整合です。',))
        if self.clock_untrusted:
            # A fresh server response, not the old cache, must reconfirm availability.
            for r in rights:
                if r.identifier and r.status in AVAILABLE and r.expires and r.expires>bundle.received:
                    self.expired.discard(r.identifier)
        self.bundle=bundle; self.revision=bundle.revision; self.failure=''; self.fetching=False
        self.clock_untrusted=False; self.resume_recheck=False
        return True

    def fail(self, message, revision, account):
        if account!=self.account or revision<self.revision: return False
        self.revision=revision; self.failure=message; self.fetching=False
        return True

    def observe_clock(self, now, monotonic):
        anomaly=False
        if self.last_wall is not None:
            wall=(now-self.last_wall).total_seconds(); elapsed=monotonic-self.last_mono
            # Forward sleep gaps re-evaluate immediately, without invalidating UTC.
            if elapsed>60: self.resume_recheck=True
            anomaly=wall < 0 or (abs(wall-elapsed)>5 and elapsed<5)
            if anomaly: self.clock_untrusted=True
        self.last_wall=now; self.last_mono=monotonic
        return anomaly

    def evaluate(self, now):
        bundle=self.bundle
        if bundle is None:
            return RightsView('failed' if self.failure else ('fetching' if self.fetching else 'unknown'),None,reason=self.failure or '権利情報は取得中／未取得です。')
        rights,problems=canonical_rights(bundle.rights)
        if problems or not positive_integer(bundle.reported_count,True):
            return RightsView('invalid',None,reason='権利データが不整合です。')
        eligible=[]; expiry_unknown=False; unknown_status=False
        for index,right in enumerate(rights):
            identity=right.identifier or f'local:{bundle.revision}:{index}'
            if not right.supported or right.redeemed or right.units==0: continue
            if right.status not in AVAILABLE:
                unknown_status |= right.status not in EXCLUDED
                continue
            if right.starts is not None and right.starts>now: continue
            if right.expires is not None and right.expires<=now:
                self.expired.add(identity)
            if identity in self.expired: continue
            if not right.expiry_valid and not right.unlimited: expiry_unknown=True
            eligible.append(right)
        count=sum(r.units for r in eligible)
        if self.failure or self.clock_untrusted or self.resume_recheck:
            reason=('時刻変更を検出しました。再取得による確認が必要です。' if self.clock_untrusted else ('復帰後の再取得待ちです。前回の情報です。' if self.resume_recheck else '取得失敗。前回取得した古い情報です。'))
            known=count if bundle.complete and not bundle.errors and not unknown_status else None
            return RightsView('stale',known,reason=reason,eligible=tuple(eligible))
        if not bundle.complete or bundle.errors or unknown_status:
            return RightsView('partial',None,reason='／'.join(bundle.errors) or '権利一覧または状態が不足・不整合です。',eligible=tuple(eligible))
        if expiry_unknown:
            return RightsView('expiry_unknown',count,reason='利用可能な権利の期限が不明です。',eligible=tuple(eligible))
        if not count:
            return RightsView('ready',0,reason='利用可能0回')
        earliest=min((r.expires for r in eligible if r.expires is not None),default=None)
        exp=format_exp((earliest-now).total_seconds()) if earliest else ''
        color=PALETTE[segment_levels(count)[0]]
        return RightsView('ready',count,earliest,exp,'有効期限なし' if earliest is None else '',tuple(eligible),color)
