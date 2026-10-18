"""Real worker concurrency, isolated SQLite and injected transports; no real SMTP."""
import copy
import secrets
import threading
import time
import pytest
from sqlalchemy import select
from app.models import Delivery, SendJob, Setting
from app.smtp import TransportFailure
from conftest import seed, wait_job


class Probe:
    def __init__(self):
        self.lock=threading.Condition(); self.release=threading.Event(); self.fail_release=threading.Event()
        self.started=[]; self.finished=[]; self.active=0; self.peak=0; self.connections=[]; self.failure=None; self.fail_email=''

    def __call__(self,profile,password):
        probe=self
        class Connection:
            owner=None
            def connect(self):
                self.owner=threading.get_ident()
                with probe.lock: probe.connections.append(self)
            def deliver(self,content,person,message_id):
                assert self.owner==threading.get_ident(), 'SMTP connection crossed threads'
                with probe.lock:
                    probe.active+=1; probe.peak=max(probe.peak,probe.active)
                    probe.started.append((self.owner,copy.deepcopy(person),message_id,time.monotonic(),content['subject']))
                    probe.lock.notify_all()
                try:
                    if person['email']==probe.fail_email:
                        assert probe.fail_release.wait(10); raise probe.failure
                    assert probe.release.wait(10)
                finally:
                    with probe.lock:
                        probe.active-=1; probe.finished.append((self.owner,time.monotonic())); probe.lock.notify_all()
            def close(self): assert self.owner in (None,threading.get_ident())
        return Connection()

    def wait_started(self,count):
        with self.lock: assert self.lock.wait_for(lambda:len(self.started)>=count,10),len(self.started)


def create(c,n,key=None):
    result=c.post('/api/send-jobs',json={'notice':n,'idempotency_key':key or secrets.token_hex(16)})
    assert result.status_code==200,result.text
    return result.json()['id']


@pytest.mark.parametrize('lanes',[1,2,3,5])
def test_bounded_overlap_connection_isolation_and_order(system,lanes):
    c,app,*_=system; _,_,_,n=seed(c,21); n['concurrency']=lanes
    probe=Probe();app.state.transport_factory=probe
    try:
        ident=create(c,n);probe.wait_started(lanes)
        assert len(probe.started)==lanes and probe.peak==lanes
        live=c.get('/api/send-jobs/'+ident).json();assert live['status']=='sending'
        assert live['concurrency']==lanes and live['interval']==3
        with app.state.Session() as db:
            rows=list(db.scalars(select(Delivery).where(Delivery.job_id==ident).order_by(Delivery.position)))
            assert [d.student_id for d in rows]==n['student_ids']
            assert [d.status for d in rows[:lanes]]==['sending']*lanes
            assert all(d.status=='pending' for d in rows[lanes:])
        probe.release.set();result=wait_job(c,ident)
        assert result['counts']=={'accepted':21} and len(probe.started)==21
        assert len({entry[2] for entry in probe.started})==21
        assert len({entry[1]['email'] for entry in probe.started})==21
        assert probe.peak<=lanes and len(probe.connections)==lanes
    finally:probe.release.set();probe.fail_release.set()


def test_fifo_jobs_do_not_overlap_and_idempotency(system):
    c,app,*_=system; _,_,_,n=seed(c,9);n['concurrency']=3
    probe=Probe();app.state.transport_factory=probe
    try:
        key=secrets.token_hex(16);first=create(c,n,key);probe.wait_started(3)
        assert create(c,n,key)==first
        second=create(c,{**n,'subject':'SECOND'})
        assert c.get('/api/send-jobs/'+second).json()['status']=='queued'
        assert len(probe.started)==3
        probe.release.set();assert wait_job(c,first)['status']=='completed';assert wait_job(c,second)['status']=='completed'
        assert len(probe.started)==18 and probe.peak<=3
        assert all(item[4]!='SECOND' for item in probe.started[:9])
        assert all(item[4]=='SECOND' for item in probe.started[9:])
    finally:probe.release.set()


def test_per_lane_cooldown(system):
    c,app,*_=system;_,_,_,n=seed(c,9);n.update(concurrency=3,interval=1)
    app.state.settings.send_interval_override=.045
    probe=Probe();probe.release.set();app.state.transport_factory=probe
    ident=create(c,n);assert wait_job(c,ident)['status']=='completed'
    for owner in {row[0] for row in probe.started}:
        starts=[row[3] for row in probe.started if row[0]==owner]
        ends=[row[1] for row in probe.finished if row[0]==owner]
        assert all(start-end>=.04 for start,end in zip(starts[1:],ends))


def test_cancel_drains_inflight_then_marks_pending(system):
    c,app,*_=system;_,_,_,n=seed(c,9);n['concurrency']=3
    probe=Probe();app.state.transport_factory=probe
    try:
        ident=create(c,n);probe.wait_started(3)
        assert c.post('/api/send-jobs/'+ident+'/cancel').status_code==200
        assert c.get('/api/send-jobs/'+ident).json()['status']=='sending'
        probe.release.set();result=wait_job(c,ident)
        assert result['status']=='cancelled' and result['counts']=={'accepted':3,'cancelled':6}
        assert len(probe.started)==3
    finally:probe.release.set()


@pytest.mark.parametrize('ambiguous',[False,True])
def test_fatal_failure_drains_other_lanes_without_overwriting_pause(system,ambiguous):
    c,app,*_=system;_,_,_,n=seed(c,9);n['concurrency']=3
    probe=Probe();probe.fail_email='student0@example.com';probe.failure=TransportFailure('DATA unknown' if ambiguous else 'SMTP rate limit',ambiguous=ambiguous,fatal=True)
    app.state.transport_factory=probe
    try:
        ident=create(c,n);probe.wait_started(3);probe.fail_release.set()
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            live=c.get('/api/send-jobs/'+ident).json()
            if live['counts'].get('unknown' if ambiguous else 'failed')==1:break
            time.sleep(.01)
        assert live['status']=='sending' and live['counts']['sending']==2
        assert len(probe.started)==3
        probe.release.set();result=wait_job(c,ident)
        assert result['status']=='paused'
        assert result['counts']=={'unknown' if ambiguous else 'failed':1,'accepted':2,'pending':6}
        if ambiguous:assert c.post('/api/send-jobs/'+ident+'/retry',json={'idempotency_key':secrets.token_hex(16)}).status_code==422
        else:
            probe.fail_email='';retry=c.post('/api/send-jobs/'+ident+'/retry',json={'idempotency_key':secrets.token_hex(16)})
            result=wait_job(c,retry.json()['id']);assert result['concurrency']==3 and result['counts']=={'accepted':1}
    finally:probe.release.set();probe.fail_release.set()


def test_defaults_roundtrip_legacy_updates_and_cleanup(system):
    c,app,*_=system;profile,pid,_,n=seed(c,1)
    old=c.get('/api/smtp-profiles').json()[0];assert (old['default_concurrency'],old['default_interval'])==(1,3)
    policy={**profile,'password':None,'default_concurrency':4,'default_interval':8}
    updated=c.put('/api/smtp-profiles/'+pid,json=policy).json();assert updated['default_concurrency']==4 and updated['default_interval']==8
    c.put('/api/smtp-profiles/'+pid,json={**profile,'password':None})
    assert c.get('/api/smtp-profiles').json()[0]['default_concurrency']==4
    n.update(concurrency=2,interval=6);result=wait_job(c,create(c,n));assert (result['concurrency'],result['interval'])==(2,6)
    assert c.get('/api/smtp-profiles').json()[0]['default_interval']==8
    assert c.post('/api/notices',json={'content':n}).status_code==200
    assert c.get('/api/notices').json()[0]['content']['concurrency']==2
    with app.state.Session() as db:
        j=db.get(SendJob,result['id']);j.notice_snapshot={k:v for k,v in j.notice_snapshot.items() if k!='concurrency'};db.commit()
    assert c.get('/api/send-jobs/'+result['id']).json()['concurrency']==1
    assert c.delete('/api/smtp-profiles/'+pid).status_code==200
    with app.state.Session() as db:assert db.get(Setting,'send_policy:'+pid) is None


@pytest.mark.parametrize('value',[0,6,1.5,'3',True,None])
def test_invalid_concurrency_rejected_everywhere(system,value):
    c,_,factory,_=system;profile,pid,_,n=seed(c,1)
    assert c.put('/api/smtp-profiles/'+pid,json={**profile,'default_concurrency':value}).status_code==422
    n['concurrency']=value
    assert c.post('/api/send-jobs',json={'notice':n,'idempotency_key':secrets.token_hex(16)}).status_code==422
    assert c.post('/api/notices',json={'content':n}).status_code==422
    assert not factory.messages


def test_shutdown_drains_lanes_and_restart_never_auto_resends(system):
    c,app,*_=system;_,_,_,n=seed(c,9);n['concurrency']=3
    probe=Probe();app.state.transport_factory=probe
    try:
        ident=create(c,n);probe.wait_started(3);app.state.sender.stop.set();probe.release.set()
        result=wait_job(c,ident);assert result['status']=='interrupted' and result['counts']=={'accepted':3,'pending':6}
        app.state.sender.thread.join(5);assert not app.state.sender.thread.is_alive()
        with app.state.Session() as db:
            j=db.get(SendJob,ident);j.status='sending'
            rows=list(db.scalars(select(Delivery).where(Delivery.job_id==ident).order_by(Delivery.position)))
            for row in rows[3:6]:row.status='sending'
            db.commit()
        app.state.sender.recover();result=c.get('/api/send-jobs/'+ident).json()
        assert result['status']=='interrupted' and result['counts']=={'accepted':3,'unknown':3,'pending':3}
        assert len(probe.started)==3
    finally:probe.release.set()


def test_auth_failure_before_fanout_preserves_existing_status_rule(system):
    c,app,factory,_=system;_,_,_,n=seed(c,9);n['concurrency']=5
    factory.connection_failure=TransportFailure('认证失败',fatal=True)
    result=wait_job(c,create(c,n))
    assert result['status']=='paused' and result['counts']=={'failed':1,'pending':8}
    assert not factory.messages


def test_retry_uses_original_policy_after_mailbox_defaults_changed(system):
    c,app,factory,_=system;profile,pid,_,n=seed(c,3);n.update(concurrency=2,interval=7)
    factory.outcomes['student0@example.com']=TransportFailure('SMTP 550')
    original=wait_job(c,create(c,n));assert original['status']=='partial'
    assert c.put('/api/smtp-profiles/'+pid,json={**profile,'password':None,'default_concurrency':5,'default_interval':1}).status_code==200
    factory.outcomes.clear()
    response=c.post('/api/send-jobs/'+original['id']+'/retry',json={'idempotency_key':secrets.token_hex(16)})
    result=wait_job(c,response.json()['id']);assert (result['concurrency'],result['interval'])==(2,7)
    assert result['total']==1 and result['counts']=={'accepted':1}
