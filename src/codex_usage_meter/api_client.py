"""Read-only transport recovered from the original distribution's observed contract.

No prompt/thread/run or reset-execution endpoint exists in this module.
Authentication is read locally, held in memory, and never printed or written.
"""
from datetime import datetime,timezone
from pathlib import Path
import json,os,queue,shutil,subprocess,threading,time
import urllib.request,urllib.error
from .models import LimitWindow,ResetCredit,ResetCreditSnapshot,UsageSnapshot,clamp_percent,datetime_from_unix,parse_iso_datetime

_RESET_CREDITS_URL='https://chatgpt.com/backend-api/wham/rate-limit-reset-credits'
_RESET_CREDITS_ERROR='リセット権情報を取得できません。Codexのログイン状態またはAPI変更を確認してください。'

class UsageFetchError(RuntimeError): pass

def default_codex_auth_path():
    return Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex'))).expanduser()/'auth.json'

def find_codex_binary():
    override=os.environ.get('CODEX_USAGE_METER_CODEX_EXE')
    if override and Path(override).is_file(): return override
    base=Path(os.environ.get('LOCALAPPDATA',''))/'OpenAI'/'Codex'/'bin'
    candidates=list(base.glob('*/codex.exe'))+list(base.glob('codex.exe')) if base.is_dir() else []
    if candidates: return str(max(candidates,key=lambda p:p.stat().st_mtime))
    found=shutil.which('codex.exe') or shutil.which('codex')
    if found: return found
    raise UsageFetchError('Codexの実行ファイルが見つかりません。CODEX_USAGE_METER_CODEX_EXEを設定してください。')

def _subprocess_creationflags():
    return getattr(subprocess,'CREATE_NO_WINDOW',0) if os.name=='nt' else 0

def _request_rate_limits(binary,timeout_seconds):
    messages=[{'id':1,'method':'initialize','params':{'clientInfo':{'name':'codex_usage_meter','title':'Codex Usage Meter','version':'0.3.0'},'capabilities':{'experimentalApi':True,'requestAttestation':False,'optOutNotificationMethods':[]}}},
              {'method':'initialized','params':{}},
              {'id':2,'method':'account/rateLimits/read','params':None}]
    try:
        process=subprocess.Popen([binary,'app-server','--stdio'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf8',errors='replace',creationflags=_subprocess_creationflags())
    except OSError as exc:
        raise UsageFetchError('Codex app-serverを起動できませんでした: '+type(exc).__name__) from None
    lines=queue.Queue()
    def read_stdout():
        try:
            while True:
                line=process.stdout.readline(1048577)
                if not line: break
                if len(line)>1048576: break
                lines.put(line)
        finally: lines.put(None)
    reader=threading.Thread(target=read_stdout,daemon=True);reader.start()
    try:
        for message in messages:
            process.stdin.write(json.dumps(message,separators=(',',':'))+'\n');process.stdin.flush()
        deadline=time.monotonic()+timeout_seconds
        while time.monotonic()<deadline:
            try: line=lines.get(timeout=min(.25,max(.001,deadline-time.monotonic())))
            except queue.Empty: continue
            if line is None: break
            try: response=json.loads(line)
            except (ValueError,TypeError): continue
            if not isinstance(response,dict) or response.get('id')!=2: continue
            if 'error' in response: raise UsageFetchError('Codex利用量APIがエラーを返しました。')
            result=response.get('result')
            if not isinstance(result,dict): raise UsageFetchError('Codex利用量APIの応答形式が不正です。')
            return result
        raise UsageFetchError('Codex利用量APIの応答がタイムアウトまたは終了しました。')
    except (OSError,ValueError) as exc:
        raise UsageFetchError('Codex利用量APIとの通信に失敗しました。') from None
    finally:
        if process.poll() is None:
            process.terminate()
            try: process.wait(timeout=3)
            except subprocess.TimeoutExpired: process.kill();process.wait(timeout=3)
        reader.join(timeout=1)
        if process.stdin: process.stdin.close()
        if process.stdout: process.stdout.close()

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None

def _request_reset_credits(access_token,account_id,timeout_seconds):
    headers={'Authorization':'Bearer '+access_token,'OpenAI-Beta':'codex-1','originator':'Codex Desktop','User-Agent':'CodexUsageMeter/0.3.0'}
    if account_id: headers['ChatGPT-Account-ID']=account_id
    request=urllib.request.Request(_RESET_CREDITS_URL,headers=headers,method='GET')
    try:
        # Never forward Authorization to a redirect target.
        with urllib.request.build_opener(_NoRedirect()).open(request,timeout=timeout_seconds) as response:
            payload=response.read(1048577)
        if len(payload)>1048576: raise UsageFetchError('リセット権APIの応答サイズが上限を超えました。')
        data=json.loads(payload.decode('utf8'))
    except urllib.error.HTTPError as exc:
        raise UsageFetchError(f'リセット権APIがHTTP {exc.code}を返しました。') from None
    except (urllib.error.URLError,TimeoutError,OSError,UnicodeError,ValueError):
        raise UsageFetchError('リセット権APIに接続できないか、応答形式が不正です。') from None
    if not isinstance(data,dict): raise UsageFetchError('リセット権APIの応答形式が不正です。')
    return data

def _load_auth_json(path):
    data=json.loads(Path(path).read_text(encoding='utf8'))
    if not isinstance(data,dict): raise UsageFetchError(_RESET_CREDITS_ERROR)
    return data

def _nested_str(data,*keys):
    value=data
    for key in keys:
        if not isinstance(value,dict): return ''
        value=value.get(key)
    return value if isinstance(value,str) else ''

def _optional_int(value): return value if type(value) is int and value>=0 else None

def reset_credit_snapshot_from_payload(payload):
    items=payload.get('credits',[]);credits=[]
    if isinstance(items,list):
        for item in items:
            if not isinstance(item,dict): continue
            strings={name:item.get(name) if isinstance(item.get(name),str) else '' for name in ('status','title','reset_type','description')}
            dates={name:parse_iso_datetime(item.get(name)) for name in ('granted_at','expires_at','redeemed_at')}
            credits.append(ResetCredit(**strings,**dates))
    return ResetCreditSnapshot(available_count=_optional_int(payload.get('available_count')),total_earned_count=_optional_int(payload.get('total_earned_count')),credits=tuple(credits))

def fetch_reset_credit_snapshot(timeout_seconds=8.,auth_path=None):
    try:
        auth=_load_auth_json(auth_path or default_codex_auth_path())
        token=_nested_str(auth,'tokens','access_token');account=_nested_str(auth,'tokens','account_id')
        if not token: return ResetCreditSnapshot(error=_RESET_CREDITS_ERROR)
        return reset_credit_snapshot_from_payload(_request_reset_credits(token,account,timeout_seconds))
    except Exception:
        return ResetCreditSnapshot(error=_RESET_CREDITS_ERROR)

def _window_from_payload(label,payload):
    if not isinstance(payload,dict): return None
    used=clamp_percent(payload.get('usedPercent'))
    return LimitWindow(label=label,used_percent=used,remaining_percent=None if used is None else 100-used,window_minutes=_optional_int(payload.get('windowDurationMins')),resets_at=datetime_from_unix(payload.get('resetsAt')))

def snapshot_from_rate_limits(rate_limits,reset_credits=None):
    payloads=[item for key in ('primary','secondary') if isinstance((item:=rate_limits.get(key)),dict)]
    if not payloads: raise UsageFetchError('利用量情報に利用枠がありません。')
    windows=tuple(next((_window_from_payload(label,item) for item in payloads if _optional_int(item.get('windowDurationMins'))==duration),LimitWindow(label)) for label,duration in (('5時間枠',300),('週間枠',10080)))
    return UsageSnapshot(limits=windows,reset_credits=reset_credits or ResetCreditSnapshot(),updated_at=datetime.now(timezone.utc))

def fetch_usage_snapshot(timeout_seconds=15.,codex_binary=None,include_reset_credits=True):
    result=_request_rate_limits(codex_binary or find_codex_binary(),timeout_seconds)
    rate_limits=result.get('rateLimits') if isinstance(result,dict) else None
    if not isinstance(rate_limits,dict): raise UsageFetchError('利用量情報の形式が変わった可能性があります。')
    credits=fetch_reset_credit_snapshot() if include_reset_credits else ResetCreditSnapshot(error='リセット権情報は未取得です。')
    return snapshot_from_rate_limits(rate_limits,credits)
