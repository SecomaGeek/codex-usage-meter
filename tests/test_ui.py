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
    root=p.tk.Tk(); app=p.CompactWindow(root,dataclasses.replace(p.load_config(),show_startup_animation=False)); root.geometry('+650+160')
    errors=[]; checks={}
    def error(kind,value,tb): traceback.print_exception(kind,value,tb); errors.append(str(value)); app.close()
    root.report_callback_exception=error

    def deliver(items,count,limits=limits):
     app.request_seq+=1; revision=app.request_seq
     total=p.rights.RightsBundle('A',revision,clock[0],tuple(items),count)
     old=dataclasses.replace(snapshot,limits=limits,reset_credits=dataclasses.replace(snapshot.reset_credits,available_count=count,credits=()))
     app.apply_fetch_result('success',revision,'A',old,total); root.update()
     return total

    def test():
     app.poll(); root.update()
     assert app.rights_view.exp=='EXP 4d\n0h',app.rights_view
     assert app.expiry_label.cget('text')=='EXP 4d\n0h' and app.expiry_label.winfo_manager()=='place'
     assert app.expiry_label.cget('fg')==p.RESET_SEGMENT_COLORS[1]
     assert (root.winfo_width(),root.winfo_height())==(280,104)
     assert app.ui_font in ('Bahnschrift','Segoe UI') and app.tip_font in ('BIZ UDPゴシック','Yu Gothic UI')
     a=p.rights.Right('a','available',T+timedelta(days=4))
     deliver([a],1,(dataclasses.replace(limits[0],resets_at=T+timedelta(minutes=10)),limits[1]))
     assert app.expiry_label.cget('text')=='EXP 4d\n0h'
     deliver([a],1,(limits[0],dataclasses.replace(limits[1],resets_at=T+timedelta(days=1))))
     assert app.expiry_label.cget('text')=='EXP 4d\n0h'
     deliver([dataclasses.replace(a,expires=T+timedelta(hours=3))],1)
     assert app.expiry_label.cget('text')=='EXP 0d\n3h'
     deliver([dataclasses.replace(a,expires=None,expiry_valid=False)],1)
     assert app.expiry_label.cget('text')=='' and app.expiry_label.winfo_manager()==''
     deliver([],0)
     assert app.expiry_label.cget('text')=='' and app.expiry_label.winfo_manager()=='' and str(app.expiry_label.cget('takefocus'))=='0'
     assert (root.winfo_width(),root.winfo_height())==(280,104)
     checks['E01_E06_actual_Tk_binding_and_no_empty_EXP_row']='pass'
     # The tooltip shares WEEK's formatter, and day/hour rows stay inside the existing gap.
     mixed=p.rights.Right('mixed','available',T+timedelta(days=1,hours=5,minutes=59))
     deliver([mixed],1,(limits[0],dataclasses.replace(limits[1],resets_at=mixed.expires)))
     assert app.expiry_label.cget('text')=='EXP 1d\n5h'
     assert '失効まで 1日5時間' in app.detail_lines(),repr(app.detail_lines())
     assert 'リセットまで 1日5時間' in app.meter_detail_lines(1),repr(app.meter_detail_lines(1))
     label_bottom=app.expiry_label.winfo_y()+app.expiry_label.winfo_height()
     gauge_top=min(y for i in range(5) for y in app.gauges.coords(f'reset-credit-segment-{i}')[1::2])
     assert label_bottom<gauge_top and (root.winfo_width(),root.winfo_height())==(280,104)

     soon=dataclasses.replace(a,expires=T+timedelta(seconds=1))
     deliver([soon],1); app.show_exp_details(); root.update_idletasks(); assert app.tooltip is not None
     needles=app.gauges.find_withtag('needle-0')
     clock[0]=T+timedelta(seconds=1); app.tick(); root.update()
     assert app.rights_view.count==0 and not app.expiry_label.winfo_manager() and app.tooltip is None
     assert app.gauges.find_withtag('needle-0')==needles
     assert all(app.gauges.itemcget(i,'fill')=='' for i in app.gauges.find_withtag('reset-credit-gauge'))
     checks['last_right_expires_without_API_or_full_redraw']='pass'
     clock[0]=T+timedelta(seconds=2)
     deliver([p.rights.Right('b','available',T+timedelta(days=2),units=8)],8)
     assert app.expiry_label.cget('fg')==p.RESET_SEGMENT_COLORS[2]
     revision=app.request_seq+1; app.request_seq=revision
     app.apply_fetch_result('error',revision,'A','テスト用エラー',None)
     assert not app.expiry_label.winfo_manager() and app.rights_view.state=='stale'
     deliver([p.rights.Right('b','available',T+timedelta(days=2),units=8)],8)
     assert app.expiry_label.winfo_manager()=='place'
     checks['failure_recovery_and_shared_bottom_color']='pass'
     # Full normal ribbons really curve, widen upward and keep the original arcs.
     widths=[]
     for index in range(5):
      coords=app.gauges.coords(f'reset-credit-segment-{index}')
      assert len(coords)>20
      widths.append(max(coords[::2])-min(coords[::2]))
     assert all(a<b for a,b in zip(widths,widths[1:]))
     main_ys=[v for i in range(5) for v in app.gauges.coords(f'reset-credit-segment-{i}')[1::2]]
     assert abs(max(main_ys)-min(main_ys)-42)<.01
     assert app.refresh_button.winfo_y()==0 and app.refresh_button.winfo_x()==252 and app.refresh_button.winfo_height()>=20
     assert app.refresh_button.winfo_y()+app.refresh_button.winfo_height()/2==10
     assert all(app.gauges.coords(i)[1]==10 for i in app.gauges.find_all() if app.gauges.type(i)=='text')
     assert app.outer_arc_bounds(0)[1]==31
     assert app.gauges.coords('needle-hub-0')[1]==84
     assert not any(app.gauges.type(i)=='arc' for i in app.gauges.find_all())
     for index in range(2):
      for tag in (f'outer-arc-{index}',f'countdown-{index}',f'remaining-arc-{index}'):
       assert all(y<=87.000001 for y in app.gauges.coords(tag)[1::2])
     assert [app.gauges.itemcget(i,'text') for i in app.gauges.find_all() if app.gauges.type(i)=='text']==['5H','WEEK']
     app.show_reset_gauge_details(); root.update_idletasks(); assert app.tip_font in str(app.tooltip_label.cget('font')); app.hide_details()
     checks['English_fonts_curved_fan_upper_right_button_and_no_lower_arcs']='pass'
     app.minimize_to_mini(); root.update()
     assert (app.mini.winfo_width(),app.mini.winfo_height())==(104,43)
     assert not app.expiry_label.winfo_manager()
     for i in range(5): assert len(app.mini_canvas.coords(f'reset-credit-segment-{i}'))==12
     app.show_reset_gauge_details(); root.update_idletasks(); assert '利用可能: 8回' in app.tooltip_label.cget('text'); app.hide_details()
     app.restore_from_mini(); root.update(); assert app.expiry_label.winfo_manager()=='place'
     assert len(calls)==1
     checks['mini_size_straight_shape_restore_and_no_extra_requests']='pass'
     old_count=app.rights_view.count
     assert not app.apply_fetch_result('error',app.request_seq-1,'A','old error',None)
     assert app.rights_view.count==old_count
     active_account[0]='B'; app.check_account(); root.update()
     assert app.snapshot is None and app.rights_view.count is None and not app.expiry_label.winfo_manager()
     assert app.boot.finished and app.boot.target is None
     assert not app.apply_fetch_result('success',app.request_seq,'A',snapshot,None)
     checks['old_response_and_account_cache_isolation']='pass'
     assert len(calls)==1 and not errors,errors
     print('EXP_UI_TESTS_PASS',json.dumps(checks),flush=True); app.close()
    root.after(150,test); root.after(10000,app.close); root.mainloop()
    assert len(checks)==6 and not errors,checks


if __name__=='__main__': main()
