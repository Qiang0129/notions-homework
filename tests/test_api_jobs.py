import secrets
import threading
import time
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.config import Settings
from app.main import COOKIE, create_app
from app.models import Delivery, LoginSession, SMTPProfile, SendJob, Setting, now
from app.credentials import CredentialError
from app.smtp import TransportFailure
from conftest import FakeFactory, MemoryVault, seed, wait_job

def send(c,n,key=None):
    result=c.post('/api/send-jobs',json={'notice':n,'idempotency_key':key or secrets.token_hex(16)})
    assert result.status_code==200,result.text
    return result.json()['id']

def test_authentication_security_and_cookie(system):
    c,app,_,_=system
    assert c.get('/').status_code==200
    assert c.get('/').headers['X-Frame-Options']=='DENY'
    token=c.headers.pop('X-CSRF-Token')
    assert c.post('/api/classes',json={'name':'a'}).status_code==403
    c.headers['X-CSRF-Token']=token
    assert c.post('/api/classes',json={'name':'a'},headers={'Origin':'https://evil.example'}).status_code==403
    assert c.get('/api/classes',headers={'host':'evil.example'}).status_code==400
    assert c.post('/api/auth/setup',json={'password':'new-password-123'}).status_code==409
    assert c.post('/api/auth/logout').status_code==200
    assert c.get('/api/classes').status_code==401
    response=c.post('/api/auth/login',json={'password':'test-password-12345'})
    assert response.status_code==200
    assert 'HttpOnly' in response.headers['set-cookie'] and 'SameSite=strict' in response.headers['set-cookie']
    for _ in range(5): assert c.post('/api/auth/login',json={'password':'incorrect-password'}).status_code==401
    assert c.post('/api/auth/login',json={'password':'test-password-12345'}).status_code==429

def test_first_setup_rejected_on_lan(tmp_path):
    app=create_app(Settings(tmp_path,testing=True),MemoryVault(),FakeFactory())
    with TestClient(app,client=('192.168.1.50',5000)) as c:
        assert c.get('/api/auth/status').json()['local'] is False
        assert c.post('/api/auth/setup',json={'password':'long-enough-password'}).status_code==403

def test_profile_secret_and_defaults(system):
    c,app,_,vault=system
    profile,pid,_,_=seed(c,0)
    out=c.get('/api/smtp-profiles').json()
    assert 'password' not in out[0] and 'credential_ref' not in out[0]
    p2={**profile,'name':'第二个','is_default':True}
    assert c.post('/api/smtp-profiles',json=p2).status_code==200
    assert sum(x['is_default'] for x in c.get('/api/smtp-profiles').json())==1
    old_values=list(vault.values.values())
    assert c.put('/api/smtp-profiles/'+pid,json={**profile,'password':None}).status_code==200
    assert sorted(old_values)==sorted(vault.values.values())
    for path in app.state.settings.data_dir.glob('app.db*'): assert b'ONLY-TEST-APP-PASSWORD' not in path.read_bytes()
    assert 'ONLY-TEST-APP-PASSWORD' not in str(out)
    assert c.delete('/api/smtp-profiles/'+pid).status_code==200
    assert len(vault.values)==1

def test_unavailable_vault_never_saves_profile(system):
    c,app,_,vault=system
    def fail(*a): raise CredentialError('系统凭据库不可用')
    vault.set=fail
    profile={'name':'x','host':'smtp.example.com','port':465,'security':'ssl','username':'x@example.com','sender_name':'x','sender_email':'x@example.com','password':'secret-demo'}
    assert c.post('/api/smtp-profiles',json=profile).status_code==503
    assert c.get('/api/smtp-profiles').json()==[]

def test_import_confirmation_revalidates_and_handles_conflicts(system):
    c,*_=system
    _,_,cid,_=seed(c,0)
    pre=c.post(f'/api/classes/{cid}/import/preview',data={'text':'张三 zhang@example.com\n错误 nope'}).json()
    assert c.post(f'/api/classes/{cid}/import/confirm',json={'preview_id':pre['preview_id']}).status_code==422
    out=c.post(f'/api/classes/{cid}/import/confirm',json={'preview_id':pre['preview_id'],'valid_only':True}).json()
    assert out=={'added':1,'updated':0,'skipped':1}
    assert c.post(f'/api/classes/{cid}/import/confirm',json={'preview_id':pre['preview_id'],'valid_only':True}).status_code==410
    pre=c.post(f'/api/classes/{cid}/import/preview',data={'text':'新姓名 zhang@example.com'}).json()
    assert pre['rows'][0]['status']=='conflict'
    assert c.post(f'/api/classes/{cid}/import/confirm',json={'preview_id':pre['preview_id'],'overwrite_conflicts':True}).json()['updated']==1

def test_partial_draft_and_templates(system):
    c,*_=system
    content={'subject':'写到一半','course':'','delta':{'ops':[{'insert':'\n'}]}}
    r=c.post('/api/notices',json={'content':content}); assert r.status_code==200,r.text
    ident=r.json()['id']; assert c.get('/api/notices').json()[0]['content']==content
    assert c.put('/api/notices/'+ident,json={'content':{**content,'title':'继续写'}}).status_code==200
    assert len(c.get('/api/templates').json())==3
    assert c.delete('/api/notices/'+ident).status_code==200

def test_preview_test_and_actual_job_same_render(system):
    c,app,factory,_=system
    _,_,_,n=seed(c,1); sid=n['student_ids'][0]
    preview=c.post('/api/notices/preview',json={'notice':n,'student_id':sid}).json()
    assert c.post('/api/notices/test',json={'notice':n,'student_id':sid,'to':'only-me@example.com'}).status_code==200
    ident=send(c,n); assert wait_job(c,ident)['status']=='completed'
    assert factory.messages[0][1]==preview==factory.messages[1][1]
    assert factory.messages[0][2]['email']=='only-me@example.com'

def test_200_recipients_and_idempotency(system):
    c,app,factory,_=system
    _,_,_,n=seed(c,200); key=secrets.token_hex(16)
    ident=send(c,n,key); assert send(c,n,key)==ident
    result=wait_job(c,ident,40)
    assert result['counts']=={'accepted':200} and len(factory.messages)==200
    assert len({m[2]['email'] for m in factory.messages})==200
    assert len({m[3] for m in factory.messages})==200

def test_failures_unknown_and_manual_retry(system):
    c,app,factory,_=system
    _,_,_,n=seed(c,3)
    factory.outcomes['student0@example.com']=TransportFailure('SMTP 550 明确拒绝')
    result=wait_job(c,send(c,n))
    assert result['status']=='partial' and result['counts']=={'failed':1,'accepted':2}
    factory.outcomes.clear()
    r=c.post('/api/send-jobs/'+result['id']+'/retry',json={'idempotency_key':secrets.token_hex(16)})
    assert wait_job(c,r.json()['id'])['counts']=={'accepted':1}
    factory.outcomes['student0@example.com']=TransportFailure('DATA 超时',ambiguous=True,fatal=True)
    result=wait_job(c,send(c,n))
    assert result['status']=='paused' and result['counts']=={'unknown':1,'pending':2}
    assert c.post('/api/send-jobs/'+result['id']+'/retry',json={'idempotency_key':secrets.token_hex(16)}).status_code==422

def test_auth_failure_pauses_and_does_not_rotate(system):
    c,_,factory,_=system; _,_,_,n=seed(c,3)
    factory.connection_failure=TransportFailure('认证失败',fatal=True)
    result=wait_job(c,send(c,n))
    assert result['status']=='paused' and result['counts']=={'failed':1,'pending':2} and not factory.messages

def test_snapshot_profile_lock_and_cancellation(system):
    c,app,factory,_=system; profile,pid,_,n=seed(c,3)
    factory.block=threading.Event()
    ident=send(c,n); assert factory.entered.wait(5)
    assert c.put('/api/smtp-profiles/'+pid,json={**profile,'password':None}).status_code==409
    assert c.delete('/api/smtp-profiles/'+pid).status_code==409
    assert c.post('/api/send-jobs/'+ident+'/cancel').status_code==200
    n['course']='被修改的课程'; factory.block.set()
    result=wait_job(c,ident)
    assert result['status']=='cancelled' and result['counts']=={'accepted':1,'cancelled':2}
    assert '高等数学' in factory.messages[0][1]['subject']

def test_invalid_recipient_and_variable_block_send(system):
    c,_,factory,_=system; _,_,_,n=seed(c,1)
    n['student_ids'].append('missing')
    assert c.post('/api/send-jobs',json={'notice':n,'idempotency_key':secrets.token_hex(16)}).status_code==422
    n['student_ids'].pop(); n['subject']='{{unknown}}'
    assert c.post('/api/send-jobs',json={'notice':n,'idempotency_key':secrets.token_hex(16)}).status_code==422
    assert not factory.messages

def test_restart_persistence_and_no_resend(system):
    c,app,factory,vault=system; _,pid,cid,n=seed(c,1)
    ident=send(c,n); wait_job(c,ident)
    with app.state.Session() as db:
        j=db.get(SendJob,ident); j.status='sending'
        d=db.scalar(select(Delivery).where(Delivery.job_id==ident)); d.status='sending'; db.commit()
    app.state.sender.recover()
    result=c.get('/api/send-jobs/'+ident).json()
    assert result['status']=='interrupted' and result['counts']=={'unknown':1}
    time.sleep(.1); assert len(factory.messages)==1
    assert c.get('/api/smtp-profiles').json()[0]['id']==pid
    assert c.get('/api/classes').json()[0]['id']==cid

def test_validation_errors_never_echo_password(system):
    c,*_=system
    secret='VERY-PRIVATE-SECRET'
    result=c.post('/api/smtp-profiles',json={'password':secret})
    assert result.status_code==422 and secret not in result.text
