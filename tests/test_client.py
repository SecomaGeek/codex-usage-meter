import io,json,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
from codex_usage_meter import api_client as api
from codex_usage_meter.config import AppConfig,load_config
from codex_usage_meter.models import clamp_percent,datetime_from_unix,parse_iso_datetime
from codex_usage_meter.utils.single_instance import SingleInstance

class Recorder(io.StringIO):
    def close(self): self.saved=self.getvalue();super().close()

class FakeProcess:
    def __init__(self,response):
        self.stdin=Recorder();self.stdout=io.StringIO(response);self.returncode=None
    def poll(self): return self.returncode
    def terminate(self): self.returncode=0
    def wait(self,timeout=None): return self.returncode
    def kill(self): self.returncode=-1

class ClientTests(unittest.TestCase):
    def test_stdio_only_initialization_and_read(self):
        result={'rateLimits':{'primary':{'usedPercent':25,'windowDurationMins':300,'resetsAt':1893459600}}}
        process=FakeProcess(json.dumps({'id':1,'result':{}})+'\n'+json.dumps({'id':2,'result':result})+'\n')
        with patch.object(api.subprocess,'Popen',return_value=process) as spawn:
            self.assertEqual(api._request_rate_limits('fake-codex',1),result)
        requests=[json.loads(line) for line in process.stdin.saved.splitlines()]
        self.assertEqual([item['method'] for item in requests],['initialize','initialized','account/rateLimits/read'])
        self.assertEqual(spawn.call_args.args[0],['fake-codex','app-server','--stdio'])
        self.assertEqual(process.returncode,0)
    def test_stdio_failure_is_generic(self):
        process=FakeProcess(json.dumps({'id':2,'error':{'message':'PRIVATE_FIXTURE_MUST_NOT_APPEAR'}})+'\n')
        with patch.object(api.subprocess,'Popen',return_value=process):
            with self.assertRaises(api.UsageFetchError) as error: api._request_rate_limits('fake',1)
        self.assertNotIn('PRIVATE_FIXTURE',str(error.exception))
    def test_http_is_get_only_and_does_not_follow_redirects(self):
        response=io.BytesIO(b'{"available_count":0,"credits":[]}')
        class Opener:
            def open(self,request,timeout):
                self.request=request;self.timeout=timeout;return response
        opener=Opener()
        with patch.object(api.urllib.request,'build_opener',return_value=opener):
            value=api._request_reset_credits('fixture-not-a-token','fixture-account',1)
        self.assertEqual(opener.request.get_method(),'GET')
        self.assertEqual(opener.request.full_url,api._RESET_CREDITS_URL)
        self.assertEqual(value['available_count'],0)
        self.assertIsNone(api._NoRedirect().redirect_request(None,None,None,None,None,None))
    def test_auth_failure_never_leaks_exception_text(self):
        with patch.object(api,'_load_auth_json',side_effect=ValueError('PRIVATE_FIXTURE_MUST_NOT_APPEAR')):
            snapshot=api.fetch_reset_credit_snapshot(auth_path=Path('unused'))
        self.assertTrue(snapshot.error);self.assertNotIn('PRIVATE_FIXTURE',snapshot.error)
    def test_usage_survives_reset_credit_failure(self):
        limits={'primary':{'usedPercent':20,'windowDurationMins':300,'resetsAt':1893459600},'secondary':{'usedPercent':10,'windowDurationMins':10080,'resetsAt':1893974400}}
        with patch.object(api,'_request_rate_limits',return_value={'rateLimits':limits}),patch.object(api,'fetch_reset_credit_snapshot',return_value=api.ResetCreditSnapshot(error='offline')):
            snapshot=api.fetch_usage_snapshot(codex_binary='fake')
        self.assertEqual([item.remaining_percent for item in snapshot.limits],[80,90]);self.assertEqual(snapshot.reset_credits.error,'offline')
    def test_missing_primary_keeps_weekly_on_right(self):
        snapshot=api.snapshot_from_rate_limits({'secondary':{'usedPercent':10,'windowDurationMins':10080}})
        self.assertIsNone(snapshot.limits[0].remaining_percent)
        self.assertEqual(snapshot.limits[1].label,'週間枠')
        self.assertEqual(snapshot.limits[1].remaining_percent,90)
    def test_weekly_primary_does_not_invent_five_hour_limit(self):
        snapshot=api.snapshot_from_rate_limits({'primary':{'usedPercent':10,'windowDurationMins':10080}})
        self.assertIsNone(snapshot.limits[0].remaining_percent)
        self.assertEqual(snapshot.limits[1].remaining_percent,90)
    def test_model_validation(self):
        for value in (True,'bad',float('nan'),float('inf')): self.assertIsNone(clamp_percent(value))
        self.assertEqual(clamp_percent(120),100);self.assertIsNone(datetime_from_unix(True));self.assertIsNone(parse_iso_datetime('2030-01-01T00:00:00'))
    def test_config_types_and_manual_update(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json';path.write_text(json.dumps({'refresh_interval_seconds':0,'show_startup_animation':False,'prevent_multiple_instances':'wrong'}),encoding='utf8')
            config=load_config(path)
            self.assertEqual(config.refresh_interval_seconds,0);self.assertFalse(config.show_startup_animation);self.assertTrue(config.prevent_multiple_instances)
    def test_os_lock_releases_after_exit(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'instance.lock'
            with SingleInstance(path) as first:
                self.assertTrue(first.acquired)
                with SingleInstance(path) as second: self.assertFalse(second.acquired)
            with SingleInstance(path) as third: self.assertTrue(third.acquired)

if __name__=='__main__': unittest.main()
