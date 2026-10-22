def main():
    import sys,os,pathlib,dataclasses,json,traceback
    from datetime import datetime,timedelta,timezone
    from codex_usage_meter import ui as p
    p.find_binary=lambda:'test-no-process'
    from codex_usage_meter.models import UsageSnapshot,LimitWindow,ResetCredit,ResetCreditSnapshot
    T=datetime(2030,1,1,tzinfo=timezone.utc); clock=[T]
    active_account=['A']
    p.utc_now=lambda:clock[0]; p.current_account_key=lambda:active_account[0]
    credit=ResetCredit(status='available',title='Full reset (Weekly + 5 hr)',reset_type=None,description=None,granted_at=T-timedelta(days=1),expires_at=T+timedelta(days=4),redeemed_at=None)
    limits=(LimitWindow(label='5時間枠',used_percent=20,remaining_percent=80,window_minutes=300,resets_at=T+timedelta(hours=2)),LimitWindow(label='週間枠',used_percent=10,remaining_percent=90,window_minutes=10080,resets_at=T+timedelta(days=6)))
    snapshot=UsageSnapshot(limits=limits,reset_credits=ResetCreditSnapshot(available_count=1,total_earned_count=1,credits=(credit,),error=None),updated_at=T)
    calls=[]
    def fetch(**kwargs): calls.append(kwargs); return snapshot
    p.api_client.fetch_usage_snapshot=fetch

    mono=[0.]
    p.time.monotonic=lambda:mono[0]
    root=p.tk.Tk(); app=p.CompactWindow(root,dataclasses.replace(p.load_config(),show_startup_animation=True,refresh_interval_seconds=0))
    root.update_idletasks(); app.poll()
    # Deliver the one mocked read, then step a shared clock across both views.
    root.update(); app.poll()
    assert app.rights_view.count==1
    boot=app.boot
    checks=[]
    for second,phase in [(0,'up'),(.4,'up'),(.8,'up'),(1.2,'up'),(1.59,'up'),(1.599999,'up'),(1.6,'down'),(2.175,'down'),(2.7,'down'),(2.749999,'down'),(2.75,'landing'),(3.7,'live')]:
     mono[0]=second; clock[0]=T+timedelta(seconds=second)
     app.repaint(); first=app.display_frame
     assert first.phase==phase,(second,first)
     if phase in ('up','down'):
      for index in range(2):
       value=first.values[index]
       assert abs(value+first.outer[index]-100)<1e-9
       hub=app.gauges.coords(f'needle-hub-{index}')
       cx,cy=(hub[0]+hub[2])/2,(hub[1]+hub[3])/2
       needle=app.gauges.coords(f'needle-core-{index}')[-2:]
       direction=((needle[0]-cx)/42,(needle[1]-cy)/42)
       for tag,radius,empty_at in ((f'countdown-{index}',56,100),(f'remaining-arc-{index}',48,0)):
        coords=app.gauges.coords(tag)
        if not coords:
         assert abs(value-empty_at)<1e-8,(phase,value,tag)
        else:
         endpoint=coords[-2:]
         assert abs((endpoint[0]-cx)/radius-direction[0])<1e-8,(phase,value,tag)
         assert abs((endpoint[1]-cy)/radius-direction[1])<1e-8,(phase,value,tag)

     assert app.rights_view.count==1
     if phase in ('up','down'):
      assert abs(first.count-first.values[0]*20/100)<1e-9
     if second in (.8,2.175):
      assert abs(first.count-10)<1e-9
      assert [app.gauges.itemcget(f'reset-credit-segment-{i}','fill') for i in range(5)]==[p.RESET_SEGMENT_COLORS[2]]*5
     if second==1.6:
      assert first.count==20
      assert all(app.gauges.itemcget(i,'fill')==p.RESET_SEGMENT_COLORS[4] for i in app.gauges.find_withtag('reset-credit-gauge'))
     if second==2.749999:
      assert app.gauges.itemcget('reset-credit-segment-0','fill')==p.RESET_SEGMENT_COLORS[1]
     if second in (0,2.75):
      assert first.count==0 and all(app.gauges.itemcget(i,'fill')=='' for i in app.gauges.find_withtag('reset-credit-gauge'))
     assert '利用可能: 1回' in '\n'.join(app.detail_lines())
     if phase!='live': assert not app.expiry_label.winfo_manager()
     app.minimize_to_mini(); root.update_idletasks()
     assert app.boot is boot and app.display_frame==first
     app.restore_from_mini(); root.update_idletasks()
     assert app.boot is boot and app.display_frame==first
     checks.append({'time':second,'phase':phase,'demo_count':first.count,'real_count':app.rights_view.count,'needle_values':first.values,'outer_color_percent':first.outer})
    assert boot.finished and app.expiry_label.winfo_manager()
    # Rendering ticks and wall-clock anomalies do not issue network requests or restart boot.
    clock[0]=T-timedelta(hours=1); mono[0]=4.; app.tick()
    assert boot.finished and app.rights_view.state=='stale' and not app.expiry_label.winfo_manager()
    assert len(calls)==1 and app.config.refresh_interval_seconds==0
    app.close()
    print('ANIMATION_MODE_SYNC_PASS',flush=True)

if __name__=='__main__': main()
