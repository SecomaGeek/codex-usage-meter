"""Compact Windows meter UI; all network operations run off the UI thread."""
import ctypes
class wintypes: HWND = ctypes.c_void_p; UINT = ctypes.c_uint
from collections import Counter
from datetime import datetime, timezone, timedelta
import math
import os
from pathlib import Path
import queue
import shutil
import sys
import threading
import time
import json
import hashlib
from . import reset_rights as rights
from .animation import BootAnimation, Frame
import tkinter as tk
class TkFont:
    def __init__(self, root, family, size):
        self.tk = root.tk; self.name = self.tk.call('font', 'create', '-family', family, '-size', size)
    def __str__(self): return self.name
    def measure(self, text): return int(self.tk.call('font', 'measure', self.name, text))
    def metrics(self, field): return int(self.tk.call('font', 'metrics', self.name, '-'+field))

from codex_usage_meter import api_client
from codex_usage_meter.config import load_config
from codex_usage_meter.utils.single_instance import SingleInstance, default_lock_path
from codex_usage_meter.utils.time_format import format_local_datetime, format_remaining_time, reset_countdown_percent
from codex_usage_meter.utils.reset_credits import reset_credit_status_label, is_reset_credit_expiring_soon

KEY = '#010203'
BG = '#151c28'
INK = '#edf2f7'
MUTED = '#b9c9da'
BLUE = '#6db7ff'
GREEN = '#7bddbd'
WARN = '#f2c768'
ERROR = '#ffac9f'

RESET_SEGMENT_COLORS = rights.PALETTE
reset_credit_segment_levels = rights.segment_levels
_fetch_context = threading.local()

def utc_now():
    return datetime.now(timezone.utc)

def account_fingerprint(account_id):
    if not isinstance(account_id,str) or not account_id: return 'unauthenticated'
    return hashlib.sha256((str(auth_path())+'|'+account_id).encode()).hexdigest()

def current_account_key():
    try:
        data=json.loads(auth_path().read_text(encoding='utf8'))
        identifier=data.get('tokens',{}).get('account_id','')
        return account_fingerprint(identifier) if isinstance(identifier,str) and identifier else 'unauthenticated'
    except (OSError,ValueError,TypeError):
        return 'unauthenticated'

def format_local_datetime(value):
    return value.astimezone().strftime('%Y-%m-%d %H:%M:%S %Z (UTC%z)') if value is not None else '不明'

_original_find = api_client.find_codex_binary

def auth_path():
    home = os.environ.get('CODEX_HOME')
    return Path(home).expanduser() / 'auth.json' if home else Path.home() / '.codex' / 'auth.json'

def find_binary():
    override = os.environ.get('CODEX_USAGE_METER_CODEX_EXE')
    if override and Path(override).is_file():
        return override
    base = Path(os.environ.get('LOCALAPPDATA', '')) / 'OpenAI' / 'Codex' / 'bin'
    if base.is_dir():
        candidates = list(base.glob('*/codex.exe')) + list(base.glob('codex.exe'))
        if candidates:
            return str(max(candidates, key=lambda p: p.stat().st_mtime))
    found = shutil.which('codex.exe') or shutil.which('codex')
    return found or _original_find()

api_client.default_codex_auth_path = auth_path
api_client.find_codex_binary = find_binary

_original_reset_request = api_client._request_reset_credits

def capture_reset_request(access_token, account_id, timeout_seconds):
    payload=_original_reset_request(access_token,account_id,timeout_seconds)
    _fetch_context.bundle=rights.normalize_payload(payload,account_fingerprint(account_id),getattr(_fetch_context,'revision',0),utc_now())
    return payload

api_client._request_reset_credits=capture_reset_request

class CompactWindow:
    WIDTH = 280

    def __init__(self, root, config):
        self.root = root
        self.config = config
        self.snapshot = None
        self.error = ''
        self.refreshing = False
        self.closed = False
        self.mini_mode = False
        self.mini = None
        self.mini_background = None
        self.results = queue.Queue()
        self.opacity = .84
        self.topmost = True
        self.last_success = None
        self.content_lines = []
        self.account_key=current_account_key()
        self.rights_engine=rights.RightsEngine(self.account_key)
        self.rights_view=self.rights_engine.evaluate(utc_now())
        self.request_seq=0
        self.tick_timer=self.anim_timer=self.poll_timer=None
        self.boot=BootAnimation(time.monotonic(),getattr(config,'show_startup_animation',True))
        self.display_frame=Frame('waiting',(None,None),(None,None),None,not self.boot.finished)
        families=set(root.tk.call('font','families'))
        self.ui_font='Bahnschrift' if 'Bahnschrift' in families else 'Segoe UI'
        self.tip_font='BIZ UDPゴシック' if 'BIZ UDPゴシック' in families else 'Yu Gothic UI'
        self.font_selection={'main':self.ui_font,'tooltip':self.tip_font}
        self.body_font = TkFont(root, family='Yu Gothic UI', size=-12)
        self.small_font = TkFont(root, family='Yu Gothic UI', size=-11)
        self.line_height = max(16, self.small_font.metrics('linespace') + 1)
        root.title('Codex Usage Meter')
        for icon_path in (Path(__file__).with_name('CodexUsageMeter.ico'), Path(__file__).parent.parent/'CodexUsageMeter.ico'):
            if icon_path.is_file():
                root.iconbitmap(default=str(icon_path))
                break
        root.configure(bg=KEY)
        root.resizable(False, False)
        root.attributes('-topmost', True)
        root.attributes('-transparentcolor', KEY)
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.backdrop = tk.Toplevel(root)
        self.backdrop.overrideredirect(True)
        self.backdrop.configure(bg=BG)
        self.backdrop.attributes('-alpha', self.opacity)
        self.backdrop.attributes('-topmost', True)
        self.backdrop.bind('<ButtonPress-1>', self.drag_start)
        self.backdrop.bind('<B1-Motion>', self.drag_move)
        self.backdrop.bind('<Button-3>', self.show_menu)
        self.gauges = tk.Canvas(root,width=self.WIDTH,height=104,bg=KEY,highlightthickness=0)
        self.gauges.pack()
        self.status=tk.Label(root,text='●',fg=BLUE,bg=KEY,font=('Segoe UI',-10))
        self.status.place(x=5,y=0)
        self.refresh_button=tk.Button(root,text='↻',command=self.refresh_now,bg='#223347',fg=INK,
                                      activebackground='#343d4c',activeforeground=INK,relief='flat',bd=0,
                                      font=('Segoe UI Symbol',-15),takefocus=True,padx=0,pady=0,highlightthickness=0)
        self.refresh_button.place(x=self.WIDTH-28,y=0,width=22,height=20)
        self.tooltip = None
        self.tooltip_target = None
        self.readout_values = {}
        self.hide_timer = None
        self.expiry_label=tk.Label(root,text='',bg=KEY,fg=INK,font=(self.ui_font,-12),padx=0,pady=0,takefocus=False)
        self.expiry_label.bind('<Enter>',self.show_exp_details)
        self.expiry_label.bind('<Leave>',self.schedule_hide_details)
        self.expiry_label.bind('<FocusIn>',self.show_exp_details)
        self.expiry_label.bind('<FocusOut>',self.schedule_hide_details)
        self.expiry_label.bind('<Return>',self.show_exp_details)
        # Canvas primitives are repainted by Tk on window exposure/movement.
        self.gauges.configure(takefocus=True)
        self.gauges.bind('<Motion>', self.route_meter_hover)
        self.gauges.bind('<Enter>', self.route_meter_hover)
        self.gauges.bind('<Leave>', self.schedule_hide_details)
        self.gauges.bind('<FocusIn>', lambda e:self.show_meter_details(0))
        self.gauges.bind('<FocusOut>', self.schedule_hide_details)
        self.gauges.bind('<Left>', lambda e:self.show_meter_details(0))
        self.gauges.bind('<Right>', lambda e:self.show_meter_details(1))
        self.gauges.bind('<Up>', self.show_reset_gauge_details)
        self.backdrop.bind('<Motion>', self.route_meter_hover)
        self.backdrop.bind('<Enter>', self.route_meter_hover)
        self.backdrop.bind('<Leave>', self.schedule_hide_details)
        self.refresh_button.bind('<Enter>', self.show_refresh_details)
        self.refresh_button.bind('<Leave>', self.schedule_hide_details)
        self.refresh_button.bind('<FocusIn>', self.show_refresh_details)
        self.refresh_button.bind('<FocusOut>', self.schedule_hide_details)
        self.error_label = tk.Label(root, fg=ERROR, bg=KEY, wraplength=self.WIDTH-18, justify='left', anchor='w', font=('Yu Gothic UI', -11))
        self.menu = tk.Menu(root, tearoff=False)
        self.menu.add_command(label='利用量を更新', command=self.refresh_now)
        self.topmost_var = tk.BooleanVar(root, value=True)
        self.menu.add_checkbutton(label='最前面に表示', variable=self.topmost_var, command=self.toggle_topmost)
        opacity_menu = tk.Menu(self.menu, tearoff=False)
        for name, alpha in [('背景 60%', .60), ('背景 74%', .74), ('背景 84%（標準）', .84), ('背景 90%', .90), ('背景 不透明', 1.0)]:
            opacity_menu.add_command(label=name, command=lambda a=alpha:self.set_opacity(a))
        self.menu.add_cascade(label='背景の濃さ', menu=opacity_menu)
        self.menu.add_command(label='小型ガジェットに切り替え', command=self.minimize_to_mini)
        self.menu.add_separator()
        self.menu.add_command(label='終了', command=self.close)
        root.bind('<Button-3>', self.show_menu)
        root.bind('<Configure>', self.sync_backdrop)
        root.bind('<Map>', self.on_map)
        root.bind('<Unmap>', self.on_unmap)
        root.bind('<Control-r>', lambda e:self.refresh_now())
        root.bind('<Escape>', lambda e:(self.hide_details(), self.menu.unpost()))
        self.render()
        root.update_idletasks()
        self.resize()
        self.style_caption()
        self.sync_backdrop()
        self.refresh_now()
        self.poll_timer=root.after(100,self.poll)
        self.schedule_tick()
        self.ensure_animation()
        if config.refresh_interval_seconds>0:
            root.after(max(10,config.refresh_interval_seconds)*1000,self.scheduled_refresh)

    def style_caption(self):
        try:
            hwnd = self.hwnd(self.root)
            value = ctypes.c_int(1)
            dwm = ctypes.windll.dwmapi.DwmSetWindowAttribute
            dwm.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
            dwm.restype = ctypes.c_long
            if dwm(hwnd, 20, ctypes.byref(value), 4) != 0:
                dwm(hwnd, 19, ctypes.byref(value), 4)
        except (OSError, AttributeError):
            pass

    @staticmethod
    def hwnd(window):
        user = ctypes.windll.user32
        user.GetParent.argtypes = [wintypes.HWND]
        user.GetParent.restype = wintypes.HWND
        return user.GetParent(window.winfo_id()) or window.winfo_id()

    def sync_backdrop(self, event=None):
        if self.closed or self.mini_mode or (event is not None and event.widget is not self.root):
            return
        self.root.update_idletasks()
        self.backdrop.geometry(f'{self.root.winfo_width()}x{self.root.winfo_height()}+{self.root.winfo_rootx()}+{self.root.winfo_rooty()}')
        try:
            user = ctypes.windll.user32
            user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
            user.SetWindowPos(self.hwnd(self.backdrop), self.hwnd(self.root), 0, 0, 0, 0, 0x0013)
        except (OSError, AttributeError):
            pass

    def on_unmap(self, event):
        if event.widget is self.root:
            self.hide_details()
            self.backdrop.withdraw()
            if self.root.state() == 'iconic':
                self.root.after_idle(lambda:self.minimize_to_mini(check_minimized=True))

    def on_map(self, event):
        if event.widget is self.root and not self.closed and not self.mini_mode:
            self.backdrop.deiconify()
            self.render()
            self.sync_backdrop()

    MINI_WIDTH = 104
    MINI_HEIGHT = 43

    def create_mini(self):
        if self.mini is not None:
            return
        self.mini = tk.Toplevel(self.root)
        self.mini.title('Codex Usage Meter Mini')
        self.mini.overrideredirect(True)
        self.mini.configure(bg=KEY)
        self.mini.attributes('-transparentcolor', KEY)
        self.mini.attributes('-topmost', self.topmost)
        self.mini_background = tk.Toplevel(self.root)
        self.mini_background.overrideredirect(True)
        self.mini_background.configure(bg=BG)
        self.mini_background.attributes('-alpha', self.opacity)
        self.mini_background.attributes('-topmost', self.topmost)
        self.mini_canvas = tk.Canvas(self.mini, width=self.MINI_WIDTH, height=self.MINI_HEIGHT, bg=KEY, highlightthickness=0, takefocus=True)
        self.mini_canvas.pack()
        self.mini_menu = tk.Menu(self.mini, tearoff=False)
        self.mini_menu.add_command(label='メーターを表示', command=self.restore_from_mini)
        self.mini_menu.add_command(label='今すぐ更新', command=self.refresh_now)
        self.mini_menu.add_command(label='リセット権の詳細', command=self.show_details)
        self.mini_menu.add_separator()
        self.mini_menu.add_command(label='終了', command=self.close)
        for target in (self.mini_canvas, self.mini_background):
            target.bind('<ButtonPress-1>', self.mini_drag_start)
            target.bind('<B1-Motion>', self.mini_drag_move)
            target.bind('<Double-Button-1>', lambda e:self.restore_from_mini())
            target.bind('<Button-3>', lambda e:self.mini_menu.tk_popup(e.x_root,e.y_root))
            target.bind('<Motion>', self.route_mini_hover)
            target.bind('<Enter>', self.route_mini_hover)
            target.bind('<Leave>', self.schedule_hide_details)
        self.mini.bind('<Configure>', self.sync_mini_background)
        self.mini.bind('<Return>', lambda e:self.restore_from_mini())
        self.mini.bind('<Control-r>', lambda e:self.refresh_now())
        self.mini.bind('<Escape>', lambda e:self.hide_details())
        self.mini_canvas.bind('<FocusIn>', lambda e:self.show_meter_details(0))
        self.mini_canvas.bind('<Left>', lambda e:self.show_meter_details(0))
        self.mini_canvas.bind('<Right>', lambda e:self.show_meter_details(1))
        self.mini_canvas.bind('<Up>',self.show_reset_gauge_details)
        self.mini_canvas.bind('<FocusOut>', self.schedule_hide_details)
        class Rect(ctypes.Structure):
            _fields_ = [('left',ctypes.c_long),('top',ctypes.c_long),('right',ctypes.c_long),('bottom',ctypes.c_long)]
        area = Rect()
        ctypes.windll.user32.SystemParametersInfoW(0x30,0,ctypes.byref(area),0)
        x = max(0, (area.right or self.root.winfo_screenwidth())-self.MINI_WIDTH-12)
        y = max(0, (area.bottom or self.root.winfo_screenheight())-self.MINI_HEIGHT-12)
        self.mini.geometry(f'{self.MINI_WIDTH}x{self.MINI_HEIGHT}+{x}+{y}')

    def minimize_to_mini(self, check_minimized=False):
        if self.closed or self.mini_mode:
            return
        if check_minimized and self.root.state() != 'iconic':
            return
        self.hide_details()
        self.mini_mode = True
        self.create_mini()
        self.backdrop.withdraw()
        self.root.withdraw()
        self.mini.deiconify()
        self.mini_background.deiconify()
        self.render_mini()
        self.mini.update_idletasks()
        self.sync_mini_background()

    def restore_from_mini(self):
        if self.closed:
            return
        self.hide_details()
        self.mini_mode = False
        if self.mini is not None:
            self.mini.withdraw()
            self.mini_background.withdraw()
        self.root.deiconify()
        self.root.state('normal')
        self.render(); self.resize()
        self.backdrop.deiconify()
        self.sync_backdrop()
        self.root.lift()
        self.root.focus_force()

    def sync_mini_background(self, event=None):
        if self.closed or not self.mini_mode or self.mini is None:
            return
        if event is not None and event.widget is not self.mini:
            return
        self.mini.update_idletasks()
        self.mini_background.geometry(f'{self.MINI_WIDTH}x{self.MINI_HEIGHT}+{self.mini.winfo_rootx()}+{self.mini.winfo_rooty()}')
        user = ctypes.windll.user32
        user.SetWindowPos.argtypes = [wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.UINT]
        user.SetWindowPos(self.hwnd(self.mini_background),self.hwnd(self.mini),0,0,0,0,0x0013)

    def render_mini(self):
        if self.mini is None:
            return
        self.prepare_frame()
        c = self.mini_canvas
        c.delete('all')
        limits = self.snapshot.limits if self.snapshot else ()
        for index,label in enumerate(('5H','WEEK')):
            cx = self.MINI_WIDTH*(.25+.5*index)
            color = BLUE if index == 0 else GREEN
            c.create_text(cx,7,text=label,fill=ERROR if self.error else color,font=(self.ui_font,-10))
            percent = self.display_frame.values[index]
            value = (str(round(percent)) if self.display_frame.active else f'{percent:g}') if percent is not None else '—'
            self.draw_led_readout(index,cx,28,value,canvas=c,max_width=36,height=20)
        self.draw_reset_credit_gauge(c,self.MINI_WIDTH/2,28,width=8,bar_height=2,gap=2)
        self.update_exp_label()
        if self.tooltip is not None:
            self.tooltip_label.configure(text='\n'.join(self.tooltip_lines()))
            self.fit_tooltip()

    def mini_drag_start(self, event):
        self.mini_drag_origin = (event.x_root,event.y_root,self.mini.winfo_x(),self.mini.winfo_y())

    def mini_drag_move(self, event):
        x,y,wx,wy = self.mini_drag_origin
        self.hide_details()
        self.mini.geometry(f'+{wx+event.x_root-x}+{wy+event.y_root-y}')
        self.sync_mini_background()

    def route_mini_hover(self, event):
        if not self.mini_mode:
            return
        x = event.x_root-self.mini.winfo_rootx()
        y = event.y_root-self.mini.winfo_rooty()
        if abs(x-self.MINI_WIDTH/2) <= 7 and 17 <= y <= 39:
            self.show_reset_gauge_details()
            return
        self.show_meter_details(0 if x < self.MINI_WIDTH/2 else 1)


    def drag_start(self, event):
        self.drag_origin = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())
        self.root.lift()
        self.sync_backdrop()

    def drag_move(self, event):
        x, y, wx, wy = self.drag_origin
        self.root.geometry(f'+{wx + event.x_root-x}+{wy + event.y_root-y}')

    def show_menu(self, event):
        self.menu.tk_popup(event.x_root, event.y_root)

    def set_opacity(self, alpha):
        self.opacity = alpha
        self.backdrop.attributes('-alpha', alpha)
        if self.mini_background is not None:
            self.mini_background.attributes('-alpha', alpha)

    def toggle_topmost(self):
        self.topmost = not self.topmost
        self.topmost_var.set(self.topmost)
        for window in (self.root, self.backdrop, self.mini, self.mini_background):
            if window is None: continue
            window.attributes('-topmost', self.topmost)
        self.sync_backdrop()

    def usage_targets(self):
        limits=self.snapshot.limits if self.snapshot else ()
        values=[]; outer=[]
        for index in range(2):
            limit=limits[index] if index<len(limits) else None
            values.append(limit.remaining_percent if limit else None)
            remaining=max(0,min(100,(limit.resets_at-utc_now()).total_seconds()/(limit.window_minutes*60)*100)) if limit and limit.resets_at and limit.window_minutes else None
            outer.append(None if remaining is None else 100-remaining)
        return tuple(values),tuple(outer)

    def prepare_frame(self):
        now=utc_now()
        self.rights_engine.observe_clock(now,time.monotonic())
        self.rights_view=self.rights_engine.evaluate(now)
        values,outer=self.usage_targets()
        self.display_frame=self.boot.sample(time.monotonic(),values,outer,self.rights_view.count)

    def ensure_animation(self):
        if not self.closed and not self.boot.finished and self.anim_timer is None:
            self.anim_timer=self.root.after(16,self.animation_tick)

    def animation_tick(self):
        self.anim_timer=None
        if self.closed: return
        self.repaint()
        if self.display_frame.phase!='waiting': self.ensure_animation()

    def repaint(self):
        if self.mini_mode: self.render_mini()
        else: self.render()

    def render_center(self):
        canvas=self.mini_canvas if self.mini_mode else self.gauges
        canvas.delete('reset-credit-gauge')
        if self.mini_mode:
            self.draw_reset_credit_gauge(canvas,self.MINI_WIDTH/2,28,8,2,2)
        else:
            arc=self.outer_arc_bounds(0)
            if not arc: return
            axis=(arc[1]+arc[3])/2; height=(axis-arc[1])*.75
            self.draw_reset_credit_gauge(canvas,self.WIDTH/2,axis-(height-3)/2,12,(height-11)/5,2,True)

    def schedule_tick(self):
        if self.closed: return
        if self.tick_timer is not None:
            self.root.after_cancel(self.tick_timer)
        now=utc_now(); delay=1000
        bundle=self.rights_engine.bundle
        if bundle:
            future=[(r.expires-now).total_seconds() for r in bundle.rights if r.expires and r.expires>now]
            if future: delay=min(delay,max(1,math.ceil(min(future)*1000)))
        self.tick_timer=self.root.after(delay,self.tick)

    def refresh_now(self):
        if self.closed or self.refreshing: return
        self.check_account()
        self.request_seq+=1; revision=self.request_seq; account=self.account_key
        self.refreshing=True; self.rights_engine.fetching=True
        self.refresh_button.configure(state='disabled')
        def worker():
            _fetch_context.bundle=None; _fetch_context.revision=revision
            try:
                result=api_client.fetch_usage_snapshot(codex_binary=find_binary())
                bundle=getattr(_fetch_context,'bundle',None)
                if bundle is None and not getattr(result.reset_credits,'error',None):
                    bundle=rights.normalize_legacy(result.reset_credits,account,revision,utc_now())
                self.results.put(('success',revision,bundle.account if bundle else account,result,bundle))
            except Exception as exc:
                message=str(exc) if isinstance(exc,api_client.UsageFetchError) else type(exc).__name__
                self.results.put(('error',revision,account,message,None))
        threading.Thread(target=worker,daemon=True).start()

    def poll(self):
        if self.closed: return
        try:
            while True:
                self.apply_fetch_result(*self.results.get_nowait())
        except queue.Empty: pass
        self.poll_timer=self.root.after(100,self.poll)

    def apply_fetch_result(self,state,revision,account,data,bundle):
        self.check_account()
        if account!=self.account_key or revision!=self.request_seq:
            if revision==self.request_seq:
                self.refreshing=False; self.refresh_button.configure(state='normal')
            return False
        self.refreshing=False; self.refresh_button.configure(state='normal')
        if state=='success':
            self.snapshot=data; self.last_success=datetime.now().astimezone(); self.error=''
            if bundle is not None and not getattr(data.reset_credits,'error',None):
                self.rights_engine.accept(bundle)
            else:
                self.rights_engine.fail(getattr(data.reset_credits,'error','権利情報を取得できません。'),revision,account)
        else:
            self.error=data; self.rights_engine.fail(data,revision,account)
        self.repaint(); self.ensure_animation(); self.schedule_tick()
        return True

    def check_account(self):
        account=current_account_key()
        if account!=self.account_key:
            self.account_key=account; self.rights_engine.switch_account(account)
            self.snapshot=None; self.last_success=None; self.error=''
            self.request_seq+=1; self.refreshing=False; self.refresh_button.configure(state='normal')
            self.boot.finished=True; self.boot.target=None
            if self.anim_timer is not None:
                self.root.after_cancel(self.anim_timer); self.anim_timer=None
            self.hide_details(); self.repaint()
            return True
        return False

    def tick(self):
        self.tick_timer=None
        if self.closed: return
        self.check_account()
        previous=(self.rights_view.state,self.rights_view.count)
        now=utc_now(); self.rights_engine.observe_clock(now,time.monotonic())
        self.rights_view=self.rights_engine.evaluate(now)
        if self.boot.finished:
            self.prepare_frame()
            if previous!=(self.rights_view.state,self.rights_view.count): self.render_center()
        self.update_exp_label()
        if self.tooltip is not None:
            text='\n'.join(self.tooltip_lines())
            if self.tooltip_label.cget('text')!=text:
                self.tooltip_label.configure(text=text); self.fit_tooltip()
        self.schedule_tick()

    def scheduled_refresh(self):
        if self.closed or self.config.refresh_interval_seconds<=0: return
        self.refresh_now()
        self.root.after(max(10,self.config.refresh_interval_seconds)*1000,self.scheduled_refresh)

    def wrapped(self, text, font, max_width):
        lines = []
        current = ''
        for char in text:
            if current and font.measure(current + char) > max_width:
                lines.append(current)
                current = char
            else:
                current += char
        lines.append(current)
        return lines

    def render(self):
        self.prepare_frame()
        self.gauges.delete('all')
        limits=self.snapshot.limits if self.snapshot else ()
        for index,label in enumerate(('5H','WEEK')):
            self.draw_gauge(index,label,limits[index] if index<len(limits) else None)
        self.render_center()
        self.update_exp_label()
        self.status.configure(fg=ERROR if self.error or self.rights_view.state in ('failed','stale','invalid') else (GREEN if self.rights_view.state=='ready' else WARN))
        self.refresh_button.lift(); self.status.lift()
        if self.tooltip is not None: self.tooltip_label.configure(text='\n'.join(self.tooltip_lines()))

    def update_exp_label(self):
        visible=bool(self.rights_view.exp) and not self.display_frame.active and not self.mini_mode
        if not visible:
            self.expiry_label.place_forget(); self.expiry_label.configure(text='',takefocus=False)
            if self.tooltip_target==('expiry',): self.hide_details()
            return
        if self.expiry_label.cget('text')!=self.rights_view.exp or self.expiry_label.cget('fg')!=self.rights_view.color:
            self.expiry_label.configure(text=self.rights_view.exp,fg=self.rights_view.color)
        self.expiry_label.configure(takefocus=True)
        line_height=int(self.root.tk.call('font','metrics',self.expiry_label.cget('font'),'-linespace'))
        center_y=10+line_height*(len(self.rights_view.exp.splitlines())-1)/2
        self.expiry_label.place(x=self.WIDTH/2,y=center_y,anchor='center')
        self.expiry_label.lift()

    def show_exp_details(self,event=None):
        if self.rights_view.exp and not self.display_frame.active and not self.mini_mode:
            self.show_tooltip(('expiry',),self.WIDTH/2+self.gauges.winfo_rootx())

    def detail_lines(self):
        view=self.rights_view; bundle=self.rights_engine.bundle; now=utc_now()
        lines=['Full reset (Weekly + 5-hr)',f'利用可能: {view.count}回' if view.count is not None else '利用可能回数: 不明']
        if view.reason: lines.append(view.reason)
        if view.earliest:
            lines.append('最短失効: '+format_local_datetime(view.earliest))
            lines.append('失効まで '+format_remaining_time(view.earliest,now=now).removeprefix('あと').lstrip())
        if bundle:
            if rights.positive_integer(bundle.total_earned,True): lines.append(f'累計付与: {bundle.total_earned}回')
            lines.append('最終取得: '+format_local_datetime(bundle.received))
            for index,right in enumerate(bundle.rights,1):
                status=reset_credit_status_label(right.status)
                if right.redeemed: status='使用済み'
                elif not right.supported: status='対象外'
                elif right.starts and right.starts>now: status='利用開始前'
                elif right.expires and right.expires<=now: status='失効済み'
                lines.append(f'{index}. {status}'+(f' ×{right.units}回' if right.units!=1 else ''))
                lines.append('   '+('有効期限なし' if right.unlimited else ('期限 '+format_local_datetime(right.expires) if right.expiry_valid else '期限不明')))
        return lines

    def meter_detail_lines(self, index):
        label = ('5時間枠', '週間枠')[index]
        if not self.snapshot or index >= len(self.snapshot.limits):
            return [label, '利用量を取得中…']
        limit = self.snapshot.limits[index]
        remaining = f'{limit.remaining_percent:g}%' if limit.remaining_percent is not None else '不明'
        lines = [label, '残量 '+remaining,
                 'リセットまで '+format_remaining_time(limit.resets_at,now=utc_now()).removeprefix('あと').lstrip(),
                 '次回リセット '+format_local_datetime(limit.resets_at) if limit.resets_at else '次回リセット 不明']
        if self.last_success:
            lines.append('最終取得 '+self.last_success.strftime('%Y-%m-%d %H:%M:%S'))
        if self.error:
            lines.append('取得エラー: '+self.error)
        return lines

    def tooltip_lines(self):
        if self.tooltip_target and self.tooltip_target[0]=='meter':
            return self.meter_detail_lines(self.tooltip_target[1])
        if self.tooltip_target and self.tooltip_target[0]=='refresh':
            lines=['今すぐ更新',f'定期取得: {self.config.refresh_interval_seconds}秒ごと' if self.config.refresh_interval_seconds>0 else '手動更新']
            if self.last_success: lines.append('最終取得 '+format_local_datetime(self.last_success))
            if self.error: lines.append('取得エラー: '+self.error)
            return lines
        return self.detail_lines()

    def route_meter_hover(self, event):
        x = event.x_root-self.gauges.winfo_rootx()
        y = event.y_root-self.gauges.winfo_rooty()
        if 0 <= x < self.WIDTH and 0 <= y < self.gauges.winfo_height():
            if self.reset_gauge_hit(self.gauges,x,y):
                self.show_reset_gauge_details()
                return
            self.show_meter_details(0 if x < self.WIDTH/2 else 1)
        elif self.tooltip_target and self.tooltip_target[0] in ('meter','reset_gauge'):
            self.schedule_hide_details()

    def show_meter_details(self, index):
        canvas = self.mini_canvas if self.mini_mode else self.gauges
        width = self.MINI_WIDTH if self.mini_mode else self.WIDTH
        self.show_tooltip(('meter', index), canvas.winfo_rootx()+width*(.25+.5*index))

    def show_details(self, event=None):
        center = self.mini.winfo_rootx()+self.MINI_WIDTH/2 if self.mini_mode else self.gauges.winfo_rootx()+self.WIDTH/2
        self.show_tooltip(('credits',), center)

    def show_reset_gauge_details(self, event=None):
        canvas = self.mini_canvas if self.mini_mode else self.gauges
        width = self.MINI_WIDTH if self.mini_mode else self.WIDTH
        self.show_tooltip(('reset_gauge',),canvas.winfo_rootx()+width/2)

    def show_refresh_details(self, event=None):
        self.show_tooltip(('refresh',), self.refresh_button.winfo_rootx()+self.refresh_button.winfo_width()/2)

    def show_tooltip(self, target, center_x):
        self.cancel_hide_details()
        if self.tooltip is not None and self.tooltip_target == target:
            return
        self.tooltip_target = target
        if self.tooltip is None:
            self.tooltip = tk.Toplevel(self.root)
            self.tooltip.overrideredirect(True)
            self.tooltip.attributes('-topmost', True)
            self.tooltip.configure(bg='#34485f')
            self.tooltip_canvas=tk.Canvas(self.tooltip,bg=BG,highlightthickness=0)
            self.tooltip_canvas.pack(side='left',padx=1,pady=1)
            self.tooltip_scroll=tk.Scrollbar(self.tooltip,orient='vertical',command=self.tooltip_canvas.yview)
            self.tooltip_canvas.configure(yscrollcommand=self.tooltip_scroll.set)
            self.tooltip_label = tk.Label(self.tooltip_canvas, bg=BG, fg=INK, justify='left', anchor='nw', font=(self.tip_font, -12), wraplength=330, padx=11, pady=9)
            self.tooltip_canvas.create_window(0,0,window=self.tooltip_label,anchor='nw')
            self.tooltip_label.bind('<MouseWheel>',lambda e:self.tooltip_canvas.yview_scroll(-1 if e.delta>0 else 1,'units'))
            self.tooltip.bind('<Enter>', lambda e:self.cancel_hide_details())
            self.tooltip.bind('<Leave>', self.schedule_hide_details)
        self.tooltip_label.configure(text='\n'.join(self.tooltip_lines()))
        self.fit_tooltip()
        self.tooltip.update_idletasks()
        x = int(center_x-self.tooltip.winfo_reqwidth()/2)
        anchor = self.mini if self.mini_mode else self.root
        y = anchor.winfo_rooty()+anchor.winfo_height()+5
        if y+self.tooltip.winfo_reqheight() > self.root.winfo_screenheight()-40:
            y = max(0,anchor.winfo_rooty()-self.tooltip.winfo_reqheight()-5)
        x = max(0, min(x, self.root.winfo_screenwidth()-self.tooltip.winfo_reqwidth()))
        y = min(y, self.root.winfo_screenheight()-self.tooltip.winfo_reqheight())
        self.tooltip.geometry(f'+{x}+{y}')

    def fit_tooltip(self):
        self.tooltip_label.update_idletasks()
        width=self.tooltip_label.winfo_reqwidth(); height=self.tooltip_label.winfo_reqheight()
        limit=max(150,self.root.winfo_screenheight()-70)
        self.tooltip_canvas.configure(width=width,height=min(height,limit),scrollregion=(0,0,width,height))
        if height>limit: self.tooltip_scroll.pack(side='right',fill='y')
        else: self.tooltip_scroll.pack_forget()

    def cancel_hide_details(self):
        if self.hide_timer is not None:
            self.root.after_cancel(self.hide_timer)
            self.hide_timer = None

    def schedule_hide_details(self, event=None):
        self.cancel_hide_details()
        self.hide_timer = self.root.after(180, self.hide_details)

    def hide_details(self):
        self.cancel_hide_details()
        if self.tooltip is not None:
            self.tooltip.destroy()
            self.tooltip = None
        self.tooltip_target = None

    @staticmethod
    def reset_gauge_hit(canvas, x, y):
        segments = canvas.find_withtag('reset-credit-gauge')
        if any(item in segments for item in canvas.find_overlapping(x-1,y-1,x+1,y+1)):
            return True
        # Include the transparent interior of an unlit outlined segment.
        for item in segments:
            coords = canvas.coords(item)
            points = list(zip(coords[::2],coords[1::2]))
            inside = False
            x1,y1 = points[-1]
            for x2,y2 in points:
                if (y1>y) != (y2>y) and x < (x2-x1)*(y-y1)/(y2-y1)+x1:
                    inside = not inside
                x1,y1 = x2,y2
            if inside:
                return True
        return False

    def draw_reset_credit_gauge(self,canvas,cx,cy,width,bar_height,gap,follow_arcs=False):
        count=self.display_frame.count
        display_count=count
        if count is not None and self.display_frame.active:
            if self.display_frame.phase in ('up','down'):
                # Snap numeric noise at exact steps; retain the last bar until zero.
                display_count=max(1,math.ceil(count-1e-9)) if count>0 else 0
            else:
                display_count=round(count)
        levels=rights.segment_levels(display_count) if display_count is not None else None
        unknown=levels is None
        levels=levels or (0,0,0,0,0)
        bottom=cy+(5*bar_height+4*gap)/2
        if follow_arcs:
            a=self.outer_arc_bounds(0); b=self.outer_arc_bounds(1)
            acx,acy=(a[0]+a[2])/2,(a[1]+a[3])/2; bcx,bcy=(b[0]+b[2])/2,(b[1]+b[3])/2
            radius=(a[2]-a[0])/2+2+3
            def bounds(y):
                return acx+math.sqrt(max(0,radius**2-(y-acy)**2)),bcx-math.sqrt(max(0,radius**2-(y-bcy)**2))
        for index,level in enumerate(levels):
            y=bottom-index*(bar_height+gap)-bar_height
            if follow_arcs:
                tl,tr=bounds(y); bl,br=bounds(y+bar_height)
                top=[(tl+(tr-tl)*step/12,y-3*(1-(step/6-1)**2)) for step in range(13)]
                low=[(bl+(br-bl)*step/12,y+bar_height-3*(1-(step/6-1)**2)) for step in range(12,-1,-1)]
                points=top+low
            else:
                left,right=cx-width/2,cx+width/2; bevel=min(1,bar_height/2)
                points=[(left+bevel,y),(right-bevel,y),(right,y+bar_height/2),(right-bevel,y+bar_height),(left+bevel,y+bar_height),(left,y+bar_height/2)]
            color=RESET_SEGMENT_COLORS[level]
            abnormal=unknown or (not self.display_frame.active and self.rights_view.state in ('stale','partial','invalid','failed'))
            canvas.create_polygon(*[v for point in points for v in point],fill=color or '',outline=WARN if abnormal else (color or '#647487'),
                                  width=1,dash=(1,2) if abnormal else (),stipple='gray50' if abnormal and color else '',
                                  tags=('reset-credit-gauge',f'reset-credit-segment-{index}'))

    def draw_led_readout(self, index, cx, cy, text, canvas=None, max_width=54, height=26):
        c = self.gauges if canvas is None else canvas
        self.readout_values[index] = text
        segments = {
            'a':((3,0),(10,0),(12,1.5),(10,3),(3,3),(1,1.5)),
            'b':((10,3),(12,1.5),(13,3),(13,11),(11.5,13),(10,11)),
            'c':((10,15),(11.5,13),(13,15),(13,23),(12,24.5),(10,23)),
            'd':((3,23),(10,23),(12,24.5),(10,26),(3,26),(1,24.5)),
            'e':((0,15),(1.5,13),(3,15),(3,23),(1,24.5),(0,23)),
            'f':((0,3),(1,1.5),(3,3),(3,11),(1.5,13),(0,11)),
            'g':((3,11.5),(10,11.5),(11.5,13),(10,14.5),(3,14.5),(1.5,13)),
        }
        digits = {'0':'abcdef','1':'bc','2':'abdeg','3':'abcdg','4':'bcfg','5':'acdfg','6':'acdefg','7':'abc','8':'abcdefg','9':'abcdfg','—':'g','-':'g','e':'adefg'}
        widths = [4 if char == '.' else 13 for char in text]
        total = sum(widths)+4*(len(text)-1)
        scale = min(height/26, max_width/max(1,total))
        x = cx-total*scale/2
        top = cy-13*scale
        for char, width in zip(text, widths):
            if char == '.':
                c.create_oval(x, top+23*scale, x+3*scale, top+26*scale, fill=INK, outline='', tags=(f'value-{index}', f'lit-segment-{index}'))
            else:
                enabled = digits.get(char,'g')
                for name, polygon in segments.items():
                    coords = [coordinate for px,py in polygon for coordinate in (x+px*scale,top+py*scale)]
                    tags = (f'value-{index}', f'lit-segment-{index}') if name in enabled else (f'value-{index}',)
                    c.create_polygon(*coords, fill=INK if name in enabled else '#45586d', outline='', tags=tags)
            x += (width+4)*scale

    def outer_arc_bounds(self,index):
        cx=self.WIDTH*(.25+.5*index)
        return (cx-56,31,cx+56,143)

    @staticmethod
    def draw_arc_stroke(canvas,box,start,extent,color,width=4,tags=()):
        # A clipped native Windows ellipse can leave lower-half fragments.
        # Draw only the requested angular path; no off-canvas ellipse is painted.
        if abs(extent)<1e-9: return None
        cx,cy=(box[0]+box[2])/2,(box[1]+box[3])/2
        rx,ry=(box[2]-box[0])/2,(box[3]-box[1])/2
        steps=max(1,math.ceil(abs(extent)))
        points=[]
        for i in range(steps+1):
            theta=math.radians(start+extent*i/steps)
            points.extend((cx+rx*math.cos(theta),cy-ry*math.sin(theta)))
        return canvas.create_line(*points,fill=color,width=width,capstyle='butt',joinstyle='round',tags=tags)

    def draw_gauge(self, index, label, limit):
        c = self.gauges
        cx = self.WIDTH*(.25+.5*index)
        cy = 87
        color = BLUE if index == 0 else GREEN
        c.create_text(cx, 10, text=label, fill=INK, font=(self.ui_font, -12))
        self.draw_arc_stroke(c,self.outer_arc_bounds(index),0,180,'#000000',tags=(f'outer-arc-{index}',))
        elapsed = self.display_frame.outer[index]
        if elapsed is not None:
            self.draw_arc_stroke(c,self.outer_arc_bounds(index),0,1.8*elapsed,color,tags=(f'countdown-{index}',))
        # Four-pixel clear gap between the two four-pixel rings.
        self.draw_arc_stroke(c,(cx-48,cy-48,cx+48,cy+48),0,180,'#000000')
        percent = self.display_frame.values[index]
        if percent is not None:
            self.draw_arc_stroke(c,(cx-48,cy-48,cx+48,cy+48),180,-1.8*percent,color,tags=(f'remaining-arc-{index}',))
        units = 5 if index == 0 else 7
        for value in range(1, units+1):
            angle = math.radians(180-180*value/units)
            c.create_line(cx+36*math.cos(angle), cy-36*math.sin(angle), cx+44*math.cos(angle), cy-44*math.sin(angle), fill=MUTED, width=1, tags=(f'major-tick-{index}',))
        text = (str(round(percent)) if self.display_frame.active else f'{percent:g}') if percent is not None else '—'
        self.draw_led_readout(index, cx, 68, text)
        # Needle layers follow the LED polygons so they remain in front.
        if percent is not None:
            angle = math.radians(180-1.8*percent)
            ux, uy = math.cos(angle), -math.sin(angle)
            px, py = -uy, ux
            tail, tip = -7, 42
            rim_end = tip-(tip-tail)*.05
            border = [coordinate
                      for distance, side in ((tail, -2), (rim_end, -2), (rim_end, 2), (tail, 2))
                      for coordinate in (cx+distance*ux+side*px, cy+distance*uy+side*py)]
            c.create_polygon(*border, fill='#000000', outline='', tags=(f'needle-{index}', f'needle-border-{index}'))
            c.create_line(cx+(tail+1)*ux, cy+(tail+1)*uy, cx+tip*ux, cy+tip*uy,
                          fill=color, width=2, capstyle='butt', tags=(f'needle-{index}', f'needle-core-{index}'))
        c.create_oval(cx-3, cy-3, cx+3, cy+3, fill='#ffffff', outline='#ffffff', tags=(f'needle-{index}', f'needle-hub-{index}'))

    def resize(self):
        self.root.update_idletasks()
        height = self.root.winfo_reqheight()
        self.root.minsize(self.WIDTH, height)
        self.root.geometry(f'{self.WIDTH}x{height}')
        self.sync_backdrop()

    def close(self):
        if self.closed:
            return
        self.hide_details()
        self.closed = True
        for timer in (self.tick_timer,self.anim_timer,self.poll_timer):
            if timer is not None: self.root.after_cancel(timer)
        if self.mini is not None:
            self.mini_background.destroy()
            self.mini.destroy()
        self.backdrop.destroy()
        self.root.destroy()


def run_app():
    with SingleInstance(default_lock_path(), enabled=load_config().prevent_multiple_instances) as instance:
        if not instance.acquired:
            return
        root = tk.Tk()
        app = CompactWindow(root, load_config())
        if '--mini' in sys.argv: root.after_idle(app.minimize_to_mini)
        root.mainloop()
