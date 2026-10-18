import secrets
import threading
import time
import pytest
from fastapi.testclient import TestClient
from filelock import FileLock
from sqlalchemy import select
from app.config import Settings
from app.main import create_app
from app.models import Delivery, SendJob
from app.schemas import NoticeInput, StudentInput
from conftest import MemoryVault, FakeFactory, seed, wait_job


def test_full_restart_persists_data_without_resending(tmp_path):
    settings=Settings(tmp_path,testing=True,worker_interval=.01,send_interval_override=0)
    vault=MemoryVault(); first=FakeFactory(); app=create_app(settings,vault,first)
    with TestClient(app) as c:
        c.headers['X-CSRF-Token']=c.post('/api/auth/setup',json={'password':'restart-test-password'}).json()['csrf']
        _,pid,cid,n=seed(c,1)
        draft=c.post('/api/notices',json={'content':n}).json()['id']
        template=c.post('/api/templates',json={'name':'持久模板','subject':n['subject'],'title':n['title'],'delta':n['delta']}).json()['id']
        ident=c.post('/api/send-jobs',json={'notice':n,'idempotency_key':secrets.token_hex(16)}).json()['id']
        wait_job(c,ident);app.state.sender.shutdown()
        with app.state.Session() as db:
            j=db.get(SendJob,ident);j.status='sending'
            d=db.scalar(select(Delivery).where(Delivery.job_id==ident));d.status='sending';db.commit()
    second=FakeFactory(); restarted=create_app(settings,vault,second)
    with TestClient(restarted) as c:
        c.headers['X-CSRF-Token']=c.post('/api/auth/login',json={'password':'restart-test-password'}).json()['csrf']
        assert c.get('/api/smtp-profiles').json()[0]['id']==pid
        assert c.get('/api/classes').json()[0]['id']==cid
        assert c.get('/api/notices').json()[0]['id']==draft
        assert template in [t['id'] for t in c.get('/api/templates').json()]
        result=c.get('/api/send-jobs/'+ident).json()
        assert result['status']=='interrupted' and result['counts']=={'unknown':1}
        time.sleep(.1);assert not second.messages

def test_single_instance_lock(tmp_path):
    app=create_app(Settings(tmp_path,testing=True),MemoryVault(),FakeFactory())
    with TestClient(app):
        with pytest.raises(RuntimeError,match='已有一个实例'):
            with TestClient(create_app(Settings(tmp_path,testing=True),MemoryVault(),FakeFactory())): pass

def test_rate_limit_not_bypassed_by_other_queue_notifications(system):
    c,app,factory,_=system;_,_,_,n=seed(c,2)
    app.state.settings.send_interval_override=.3
    j=c.post('/api/send-jobs',json={'notice':n,'idempotency_key':secrets.token_hex(16)}).json()['id']
    deadline=time.monotonic()+3
    while len(factory.timestamps)<1 and time.monotonic()<deadline: time.sleep(.005)
    for _ in range(10):app.state.sender.notify();time.sleep(.01)
    wait_job(c,j)
    assert factory.timestamps[1]-factory.timestamps[0]>=.28

def test_deadline_is_normalized_to_beijing_and_names_reject_headers(system):
    c,*_=system;*_,n=seed(c,0)
    n['deadline']='2026-10-20T10:00:00+00:00'
    assert NoticeInput.model_validate(n).deadline=='2026-10-20T18:00'
    with pytest.raises(ValueError):StudentInput(name='张三\r\nBcc: another@example.com',email='zhang@example.com')
