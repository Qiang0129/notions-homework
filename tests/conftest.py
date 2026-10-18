from __future__ import annotations
import copy
import threading
import time
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.config import Settings
from app.smtp import TransportFailure

class MemoryVault:
    """Explicit test injection; never selected by production configuration."""
    def __init__(self): self.values={}
    def get(self,ref):
        from app.credentials import CredentialError
        if ref not in self.values: raise CredentialError('测试凭据不存在')
        return self.values[ref]
    def set(self,ref,password): self.values[ref]=password
    def delete(self,ref): self.values.pop(ref,None)

class FakeFactory:
    def __init__(self): self.messages=[]; self.outcomes={}; self.connection_failure=None; self.block=None; self.entered=threading.Event(); self.timestamps=[]
    def __call__(self,profile,password):
        factory=self
        class Fake:
            def connect(self):
                if factory.connection_failure: raise factory.connection_failure
            def deliver(self,content,person,message_id):
                factory.entered.set()
                if factory.block: factory.block.wait(10)
                if person['email'] in factory.outcomes: raise factory.outcomes[person['email']]
                factory.messages.append((copy.deepcopy(profile),copy.deepcopy(content),copy.deepcopy(person),message_id))
                factory.timestamps.append(time.monotonic())
            def close(self): pass
        return Fake()

@pytest.fixture
def system(tmp_path):
    vault=MemoryVault(); factory=FakeFactory(); app=create_app(Settings(tmp_path,testing=True,worker_interval=.01,send_interval_override=0),vault,factory)
    with TestClient(app) as client:
        response=client.post('/api/auth/setup',json={'password':'test-password-12345'})
        assert response.status_code==200,response.text
        client.headers['X-CSRF-Token']=response.json()['csrf']
        yield client,app,factory,vault


def seed(client,count=2):
    profile={'name':'课程邮箱','host':'smtp.example.com','port':465,'security':'ssl','username':'teacher@example.com','sender_name':'课程助教','sender_email':'teacher@example.com','reply_to':'ta@example.com','password':'ONLY-TEST-APP-PASSWORD','is_default':True}
    response=client.post('/api/smtp-profiles',json=profile); assert response.status_code==200,response.text
    pid=response.json()['id']
    cid=client.post('/api/classes',json={'name':'高数一班'}).json()['id']
    if count>10:
        text='\n'.join(f'同学{i} student{i}@example.com' for i in range(count))
        pre=client.post(f'/api/classes/{cid}/import/preview',data={'text':text}).json()
        result=client.post(f'/api/classes/{cid}/import/confirm',json={'preview_id':pre['preview_id']}); assert result.status_code==200,result.text
    else:
        for i in range(count): client.post(f'/api/classes/{cid}/students',json={'name':f'同学{i}','email':f'student{i}@example.com'})
    students=client.get(f'/api/classes/{cid}/students').json()
    n={'subject':'{{course}} | {{assignment}} 提醒','title':'记得提交作业','course':'高等数学','assignment':'第三章习题','deadline':'2026-10-20T23:59','submission_email':'homework@example.com','delta':{'ops':[{'insert':'{{name}}同学，你好：\n请及时提交{{assignment}}。\n'}]},'profile_id':pid,'class_id':cid,'student_ids':[s['id'] for s in students],'interval':3}
    return profile,pid,cid,n


def wait_job(client,ident,timeout=30):
    stop=time.monotonic()+timeout
    while time.monotonic()<stop:
        j=client.get('/api/send-jobs/'+ident).json()
        if j['status'] not in ('queued','sending'): return j
        time.sleep(.02)
    raise AssertionError('Task timeout: '+str(j))
