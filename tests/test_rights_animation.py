import sys,unittest,dataclasses,math
from pathlib import Path
from datetime import datetime,timedelta,timezone
from codex_usage_meter.reset_rights import *
from codex_usage_meter.animation import *
T=datetime(2030,1,1,tzinfo=UTC)
def right(key='a',hours=4,status='available',units=1,**kw):
 return Right(key,status,T+timedelta(hours=hours) if hours is not None else None,units,**kw)
def bundle(items,count=None,revision=1,complete=True,account='A'):
 if count is None: count=sum(r.units for r in items if r.status in AVAILABLE and r.supported and not r.redeemed and r.units>0 and (r.starts is None or r.starts<=T) and (r.expires is None or r.expires>T))
 return RightsBundle(account,revision,T,tuple(items),count,complete)
def engine(items,count=None,**kw):
 e=RightsEngine('A'); e.accept(bundle(items,count,**kw)); return e

class RightsTests(unittest.TestCase):
 def test_E01_E04_usage_windows_cannot_enter_exp(self):
  e=engine([right(hours=96)])
  for unrelated_5h,unrelated_week in ((2,144),(1/6,144),(2,20)):
   self.assertEqual(e.evaluate(T).exp,'EXP 4d\n0h')
  e.accept(bundle([right(hours=3)],revision=2)); self.assertEqual(e.evaluate(T).exp,'EXP 0d\n3h')
 def test_E05_E06_missing_zero(self):
  self.assertEqual(engine([right(hours=None,expiry_valid=False)]).evaluate(T).exp,'')
  v=engine([],0).evaluate(T); self.assertEqual((v.count,v.exp),(0,''))
 def test_B01_B03_sort_status_boundary(self):
  e=engine([right('a',96),right('b',1),right('c',48)]); self.assertEqual(e.evaluate(T).exp,'EXP 0d\n1h')
  e=engine([right('used',1/6,'used'),right('valid',2)]); self.assertEqual((e.evaluate(T).count,e.evaluate(T).exp),(1,'EXP 0d\n2h'))
  e=engine([right('past',-1),right('now',0),right('valid',1)]); self.assertEqual(e.evaluate(T).count,1)
 def test_B04_B05_expiry_without_api(self):
  e=engine([right('a',1),right('b',1),right('c',2)])
  self.assertEqual(e.evaluate(T+timedelta(hours=1)).count,1)
  self.assertEqual(e.evaluate(T+timedelta(hours=1)).exp,'EXP 0d\n1h')
  self.assertEqual((e.evaluate(T+timedelta(hours=2)).count,e.evaluate(T+timedelta(hours=2)).exp),(0,''))
 def test_B06_B07_zero_and_use(self):
  e=engine([right('a',1),right('b',2)]); e.accept(bundle([right('a',1,'used'),right('b',2)],revision=2))
  self.assertEqual(e.evaluate(T).exp,'EXP 0d\n2h'); e.accept(bundle([],0,revision=3)); self.assertEqual(e.evaluate(T).count,0)
 def test_B08_groups(self):
  e=engine([right('a',1,units=3),right('b',2,units=2)]); self.assertEqual(e.evaluate(T).count,5)
  self.assertEqual(e.evaluate(T+timedelta(hours=1)).count,2)
 def test_B09_B10_ids(self):
  a=right('a',1); b=right('b',1)
  self.assertEqual(engine([a,b]).evaluate(T).count,2)
  self.assertEqual(engine([a,a],1).evaluate(T).count,1)
  self.assertEqual(engine([a,right('a',2)],1).evaluate(T).exp,'')
 def test_B11_B12_unlimited_unsupported_future(self):
  forever=right('forever',None,unlimited=True)
  self.assertEqual(engine([forever,right('finite',1)]).evaluate(T).count,2)
  self.assertEqual(engine([forever]).evaluate(T).exp,'')
  self.assertEqual(engine([right('future',4,starts=T+timedelta(hours=1)),right('no',4,supported=False),right('cancel',4,status='cancelled',supported=False)]).evaluate(T).count,0)
 def test_F01_F03_format_and_ms_boundary(self):
  cases={(86400+5*3600+59*60):'EXP 1d\n5h',96*3600:'EXP 4d\n0h',4.69*3600:'EXP 0d\n4h',24*3600:'EXP 1d\n0h',24*3600-1:'EXP 0d\n23h',3600:'EXP 0d\n1h',3599:'EXP 0d\n59m',60:'EXP 0d\n1m',59:'EXP 0d\n<1m',.001:'EXP 0d\n<1m',0:'',-1:''}
  for seconds,text in cases.items(): self.assertEqual(format_exp(seconds),text)
  e=engine([right(hours=1)])
  self.assertEqual(e.evaluate(T+timedelta(hours=1,milliseconds=-1)).count,1)
  self.assertEqual(e.evaluate(T+timedelta(hours=1)).count,0)
  self.assertEqual(e.evaluate(T+timedelta(hours=1,milliseconds=1)).count,0)
 def test_F04_F06_units_offsets_invalid(self):
  expected=datetime(2030,1,1,tzinfo=UTC)
  for value in ('2030-01-01T00:00:00Z','2030-01-01T09:00:00+09:00','2029-12-31T19:00:00-05:00'): self.assertEqual(parse_utc(value),expected)
  self.assertEqual(parse_utc(expected.timestamp(),'s'),expected); self.assertEqual(parse_utc(expected.timestamp()*1000,'ms'),expected)
  for value in (None,'','bad','2030-01-01T00:00:00',float('nan'),float('inf'),12345): self.assertIsNone(parse_utc(value))
 def test_F07_F09_bad_counts_missing_coverage(self):
  self.assertEqual(engine([right('bad',None,expiry_valid=False),right('good',1)]).evaluate(T).state,'expiry_unknown')
  for units in (-1,.5,float('nan'),float('inf')):
   e=RightsEngine('A'); e.accept(bundle([right(units=units)],1)); self.assertIsNone(e.evaluate(T).count)
  self.assertEqual(engine([right()],2).evaluate(T).exp,'')
  self.assertEqual(engine([right()],1,complete=False).evaluate(T).exp,'')
 def test_U01_U05_states_and_generation(self):
  e=RightsEngine('A'); self.assertIsNone(e.evaluate(T).count); e.fetching=True; self.assertEqual(e.evaluate(T).state,'fetching')
  e.fail('offline',1,'A'); self.assertEqual(e.evaluate(T).state,'failed')
  e.accept(bundle([right()],revision=2)); self.assertTrue(e.evaluate(T).exp)
  e.fail('offline',3,'A'); self.assertEqual(e.evaluate(T).state,'stale'); self.assertFalse(e.evaluate(T).exp)
  self.assertFalse(e.accept(bundle([],0,revision=1))); self.assertEqual(e.revision,3)
  e.accept(bundle([right()],revision=4)); self.assertEqual(e.evaluate(T).state,'ready')
 def test_U06_U07_sleep_clock_and_reconfirm(self):
  e=engine([right('a',1),right('b',2)])
  self.assertEqual(e.evaluate(T+timedelta(hours=3)).count,0)
  e.observe_clock(T+timedelta(hours=3),100)
  self.assertTrue(e.observe_clock(T,101)); self.assertEqual(e.evaluate(T).count,0); self.assertEqual(e.evaluate(T).exp,'')
  e.accept(bundle([right('a',1),right('b',2)],revision=2)); self.assertEqual(e.evaluate(T).count,2)
 def test_U09_accounts(self):
  e=engine([right()]); e.switch_account('B'); self.assertIsNone(e.evaluate(T).count)
  self.assertFalse(e.accept(bundle([right()],revision=2))); self.assertEqual(e.account,'B')
 def test_all45_colors(self):
  for count in range(100):
   simulated=[0]*5
   for step in range(min(count,45)): simulated[step%5]=step//5+1
   self.assertEqual(segment_levels(count),tuple(simulated))
   if count: self.assertEqual(engine([right(units=count)]).evaluate(T).color,PALETTE[segment_levels(count)[0]])
  for value in (None,-1,.5,float('nan'),float('inf')): self.assertIsNone(segment_levels(value))
 def test_raw_adapter(self):
  payload={'available_count':2,'credits':[{'id':'a','reset_type':'codex_rate_limits','status':'available','expires_at':'2030-01-01T01:00:00Z','granted_at':'2029-01-01T00:00:00Z','is_supported_by_plan':True},{'id':'b','reset_type':'codex_rate_limits','status':'available','expires_at':'2030-01-01T02:00:00Z'}]}
  b=normalize_payload(payload,'A',1,T); e=RightsEngine('A'); e.accept(b); self.assertEqual(e.evaluate(T).exp,'EXP 0d\n1h')
  payload['credits'][0]['expires_at']='2030-01-01T01:00:00'; e.accept(normalize_payload(payload,'A',2,T)); self.assertFalse(e.evaluate(T).exp)

 def test_raw_adapter_rejects_ambiguous_scope_and_types(self):
  base={'id':'safe-id','reset_type':'codex_rate_limits','status':'available','expires_at':'2030-01-02T00:00:00Z','granted_at':'2029-01-01T00:00:00Z','is_supported_by_plan':True}
  for key,value in [('id',None),('id',123),('reset_type','unknown'),('is_supported_by_plan','yes'),('granted_at','bad')]:
   item=dict(base); item[key]=value
   e=RightsEngine('A'); e.accept(normalize_payload({'available_count':1,'credits':[item]},'A',1,T))
   self.assertFalse(e.evaluate(T).exp,(key,value))

class AnimationTests(unittest.TestCase):
 def test_timeline_synchronization(self):
  b=BootAnimation(0); target=(23,89); outer=(65,20)
  start=b.sample(0,target,outer,3); self.assertEqual(start.count,0); self.assertEqual(start.outer,(100,100))
  middle=b.sample(.8,target,outer,3); self.assertAlmostEqual(middle.count,10); self.assertAlmostEqual(middle.values[0],50)
  top=b.sample(1.6-1e-7,target,outer,3); self.assertAlmostEqual(top.values[0],100,places=5); self.assertAlmostEqual(top.count,20,places=5)
  self.assertEqual(b.sample(1.6,target,outer,3).count,20)
  falling=b.sample(2.175,target,outer,3); self.assertAlmostEqual(falling.values[0],50); self.assertAlmostEqual(falling.count,10)
  down=b.sample(2.75-1e-7,target,outer,3); self.assertAlmostEqual(down.values[0],0,places=5); self.assertAlmostEqual(down.count,0,places=5)
  landing=b.sample(2.75,target,outer,3); self.assertEqual(landing.outer,(100,100)); self.assertEqual(landing.count,0); final=b.sample(3.6,target,outer,3)
  self.assertFalse(final.active); self.assertEqual(final.values,target); self.assertEqual(final.outer,outer)
 def test_late_data_latest_targets_and_no_restart(self):
  b=BootAnimation(0); self.assertEqual(b.sample(4,(None,None),(None,None),None).phase,'waiting')
  first=b.sample(5,(10,20),(60,70),3); before=b.sample(5.3,(10,20),(60,70),3)
  changed=b.sample(5.3,(90,40),(80,50),8); self.assertEqual(before.values,changed.values)
  final=b.sample(8,(90,40),(80,50),8); self.assertFalse(final.active)
  self.assertEqual(b.sample(9,(45,90),(1,2),0).phase,'live')

if __name__=='__main__': unittest.main(verbosity=2)
