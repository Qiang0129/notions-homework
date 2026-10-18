from __future__ import annotations
import hashlib
import io
import ipaddress
import json
import secrets
import threading
import time
from collections import Counter, defaultdict, deque
from contextlib import asynccontextmanager
from datetime import timedelta
from email.utils import make_msgid
from urllib.parse import urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from filelock import FileLock, Timeout
from sqlalchemy import delete, select, update

from .config import ROOT, Settings
from .compat import draft_content, template_content
from .credentials import CredentialError, WindowsVault
from .importing import pasted, preview as import_preview, read_file
from .models import Classroom, Delivery, LoginSession, MailTemplate, Notice, SMTPProfile, SendJob, Setting, Student, database, now, uid
from .rendering import BUILTINS, render, validate_delta
from .schemas import DraftInput, ImportConfirm, NameInput, NoticeInput, PasswordInput, PreviewInput, ProfileInput, RetryInput, SendInput, StudentInput, TemplateInput, TestInput
from .smtp import SMTPTransport, TransportFailure
from .worker import ACTIVE, Sender

COOKIE='hm_session'
PASSWORD=PasswordHasher()


def digest(value): return hashlib.sha256(value.encode()).hexdigest()

def loopback(request):
    try: return ipaddress.ip_address(request.client.host).is_loopback
    except (ValueError,AttributeError): return request.app.state.settings.testing and request.client and request.client.host=='testclient'


def read_session(request):
    token=request.cookies.get(COOKIE,'')
    if not 20<=len(token)<=100: return None
    with request.app.state.Session() as db:
        session=db.get(LoginSession,digest(token))
        return session if session and session.expires>now() else None


def current(request:Request):
    session=read_session(request)
    if not session: raise HTTPException(401,'请先登录')
    if request.method not in ('GET','HEAD','OPTIONS'):
        if not secrets.compare_digest(request.headers.get('X-CSRF-Token',''),session.csrf): raise HTTPException(403,'安全校验失败，请刷新页面后重试')
    return session


def get_db(request:Request):
    with request.app.state.Session() as db: yield db


def required(db,model,ident):
    obj=db.get(model,ident)
    if not obj: raise HTTPException(404,'记录不存在或已删除')
    return obj


def profile_data(p,db=None):
    data={key:getattr(p,key) for key in ('id','name','host','port','security','username','sender_name','sender_email','reply_to','is_default')}
    defaults={'default_concurrency':1,'default_interval':3}
    stored=db.get(Setting,'send_policy:'+p.id) if db is not None else None
    if stored:
        try:
            saved=json.loads(stored.value)
            for key,limit in (('default_concurrency',5),('default_interval',60)):
                value=saved.get(key)
                if type(value) is int and 1<=value<=limit: defaults[key]=value
        except (ValueError,TypeError,AttributeError): pass
    return {**data,**defaults}


def snapshot(p):
    data=profile_data(p); data['credential_ref']=p.credential_ref
    return data


def ensure_unlocked(db,pid):
    if db.scalar(select(SendJob.id).where(SendJob.profile_id==pid,SendJob.status.in_(ACTIVE))): raise HTTPException(409,'此邮箱正在发送任务中，暂时不能修改或删除')


def person_for(db,notice,student_id=None):
    if student_id:
        person=required(db,Student,student_id)
        if notice.class_id and person.class_id!=notice.class_id: raise HTTPException(422,'预览学生不属于当前班级')
        classroom=required(db,Classroom,person.class_id)
        return {'name':person.name,'email':person.email,'class_name':classroom.name}
    classroom=db.get(Classroom,notice.class_id) if notice.class_id else None
    return {'name':'李同学','email':'preview@example.com','class_name':classroom.name if classroom else '示例班级'}


def job_data(db,j,detail=False):
    deliveries=list(db.scalars(select(Delivery).where(Delivery.job_id==j.id).order_by(Delivery.position)))
    counts=Counter(d.status for d in deliveries)
    data={'id':j.id,'subject':j.subject,'status':j.status,'error':j.error,'sender_email':j.smtp_snapshot['sender_email'],'sender_name':j.smtp_snapshot['sender_name'],'total':len(deliveries),'counts':dict(counts),'created_at':j.created_at.isoformat()+'Z','cancel_requested':j.cancel_requested}
    data.update(concurrency=j.notice_snapshot.get('concurrency',1),interval=j.interval)
    if detail:
        data['deliveries']=[{key:getattr(d,key) for key in ('id','name','email','class_name','status','detail')} for d in deliveries]
    return data


def create_app(settings=None,vault=None,transport_factory=None):
    settings=settings or Settings.from_env()
    @asynccontextmanager
    async def lifespan(app):
        settings.data_dir.mkdir(parents=True,exist_ok=True)
        lock=FileLock(str(settings.data_dir/'application.lock'))
        try: lock.acquire(timeout=0)
        except Timeout: raise RuntimeError('同一数据目录已有一个实例运行，请勿多进程或重复启动') from None
        try:
            app.state.engine,app.state.Session=database(settings.data_dir/'app.db')
            with app.state.Session() as db:
                version=db.get(Setting,'schema_version')
                if version and version.value!='1': raise RuntimeError('数据版本不兼容，请先备份并使用匹配版本')
                if not version: db.add(Setting(key='schema_version',value='1'))
                if not db.scalar(select(MailTemplate.id)):
                    for name,subject,title,body in BUILTINS:
                        db.add(MailTemplate(name=name,subject=subject,title=title,delta={'ops':[{'insert':body}]},builtin=True))
                db.commit()
            app.state.sender=Sender(app); app.state.sender.start()
            yield
        finally:
            if hasattr(app.state,'sender'): app.state.sender.shutdown()
            if hasattr(app.state,'engine'): app.state.engine.dispose()
            lock.release()

    app=FastAPI(title='课信 · 作业邮件提醒助手',version='1.0.0',lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    app.state.settings=settings; app.state.vault=vault or WindowsVault(); app.state.transport_factory=transport_factory or SMTPTransport
    app.state.command_lock=threading.RLock(); app.state.auth_lock=threading.Lock(); app.state.attempts=defaultdict(deque); app.state.imports={}
    templates=Jinja2Templates(directory=str(ROOT/'templates'))
    app.mount('/static',StaticFiles(directory=str(ROOT/'static')),name='static')

    @app.exception_handler(RequestValidationError)
    async def validation_error(request,exc):
        # Pydantic's default response includes rejected inputs, potentially including a password.
        return JSONResponse({'detail':'；'.join('.'.join(str(i) for i in e['loc'][1:])+': '+e['msg'] for e in exc.errors())},status_code=422)

    @app.exception_handler(ValueError)
    async def bad_value(request,exc): return JSONResponse({'detail':str(exc)},status_code=422)

    @app.exception_handler(CredentialError)
    async def vault_error(request,exc): return JSONResponse({'detail':str(exc)},status_code=503)

    @app.exception_handler(TransportFailure)
    async def smtp_error(request,exc): return JSONResponse({'detail':exc.detail,'ambiguous':exc.ambiguous},status_code=502)

    @app.middleware('http')
    async def security(request,call_next):
        host=request.url.hostname or ''
        try: safe_host=ipaddress.ip_address(host).is_private
        except ValueError: safe_host=host=='localhost' or (settings.testing and host=='testserver')
        if not safe_host: return JSONResponse({'detail':'只接受本机或私有网络 IP 访问'},status_code=400)
        if request.method not in ('GET','HEAD','OPTIONS'):
            origin=request.headers.get('origin')
            if origin and origin.rstrip('/')!=str(request.base_url).rstrip('/'):
                return JSONResponse({'detail':'拒绝跨站请求'},status_code=403)
            if request.headers.get('sec-fetch-site')=='cross-site': return JSONResponse({'detail':'拒绝跨站请求'},status_code=403)
            chunks=[]; size=0
            async for chunk in request.stream():
                size+=len(chunk)
                if size>6*1024*1024: return JSONResponse({'detail':'请求体不能超过 6 MB'},status_code=413)
                chunks.append(chunk)
            request._body=b''.join(chunks)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['X-Frame-Options']='DENY'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-src 'self' about:; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
        response.headers['Permissions-Policy']='camera=(), microphone=(), geolocation=()'
        if not request.url.path.startswith('/static/'): response.headers['Cache-Control']='no-store'
        return response

    @app.get('/',response_class=HTMLResponse)
    def home(request:Request):
        if not read_session(request): return RedirectResponse('/login',status_code=303)
        return templates.TemplateResponse(request=request,name='index.html',context={})

    @app.get('/login',response_class=HTMLResponse)
    def login_page(request:Request):
        if read_session(request): return RedirectResponse('/',status_code=303)
        return templates.TemplateResponse(request=request,name='login.html',context={})

    @app.get('/favicon.ico',include_in_schema=False)
    def favicon(): return RedirectResponse('/static/favicon.svg')

    @app.get('/api/auth/status')
    def auth_status(request:Request,db=Depends(get_db)):
        session=read_session(request)
        return {'configured':bool(db.get(Setting,'admin_hash')),'local':loopback(request),'authenticated':bool(session),'csrf':session.csrf if session else None}

    def new_session(db,response):
        raw=secrets.token_urlsafe(32); csrf=secrets.token_urlsafe(32)
        db.execute(delete(LoginSession).where(LoginSession.expires<=now()))
        db.add(LoginSession(token_hash=digest(raw),csrf=csrf,expires=now()+timedelta(hours=8))); db.commit()
        response.set_cookie(COOKIE,raw,max_age=28800,httponly=True,samesite='strict',secure=False,path='/')
        return {'csrf':csrf}

    @app.post('/api/auth/setup')
    def setup(body:PasswordInput,request:Request,response:Response,db=Depends(get_db)):
        if not loopback(request): raise HTTPException(403,'请先在电脑本机打开网页，设置管理员密码')
        with app.state.auth_lock:
            if db.get(Setting,'admin_hash'): raise HTTPException(409,'管理员密码已设置，请登录')
            db.add(Setting(key='admin_hash',value=PASSWORD.hash(body.password)))
            return new_session(db,response)

    @app.post('/api/auth/login')
    def login(body:PasswordInput,request:Request,response:Response,db=Depends(get_db)):
        ip=request.client.host
        with app.state.auth_lock:
            if len(app.state.attempts)>1024: app.state.attempts.clear()
            attempts=app.state.attempts[ip]; stamp=time.monotonic()
            while attempts and attempts[0]<stamp-600: attempts.popleft()
            if len(attempts)>=5: raise HTTPException(429,'登录失败次数过多，请十分钟后重试')
            attempts.append(stamp)
        stored=db.get(Setting,'admin_hash')
        try:
            if not stored: raise VerifyMismatchError()
            PASSWORD.verify(stored.value,body.password)
        except VerificationError: raise HTTPException(401,'密码不正确，或尚未在本机完成初始化') from None
        with app.state.auth_lock: app.state.attempts.pop(ip,None)
        return new_session(db,response)

    @app.post('/api/auth/logout')
    def logout(response:Response,session=Depends(current),db=Depends(get_db)):
        db.delete(db.get(LoginSession,session.token_hash)); db.commit(); response.delete_cookie(COOKIE)
        return {'ok':True}

    api=APIRouter(prefix='/api',dependencies=[Depends(current)])

    @api.get('/smtp-profiles')
    def profiles(db=Depends(get_db)):
        return [profile_data(p,db) for p in db.scalars(select(SMTPProfile).order_by(SMTPProfile.is_default.desc(),SMTPProfile.name))]

    def save_profile(body,db,p=None):
        if p: ensure_unlocked(db,p.id)
        if p is None and not body.password: raise HTTPException(422,'新邮箱必须填写授权码或应用专用密码')
        data=body.model_dump(exclude={'password','default_concurrency','default_interval'})
        if p is None:
            p=SMTPProfile(id=uid(),credential_ref=uid(),**data); db.add(p)
        else:
            for k,v in data.items(): setattr(p,k,v)
        previous_ref=p.credential_ref; new_ref=None
        if body.password:
            new_ref=uid(); app.state.vault.set(new_ref,body.password); p.credential_ref=new_ref
        try:
            db.flush()
            defaults=profile_data(p,db)
            # Older clients editing SMTP fields must not reset a stored policy.
            for key in ('default_concurrency','default_interval'):
                if key in body.model_fields_set: defaults[key]=getattr(body,key)
            policy=json.dumps({key:defaults[key] for key in ('default_concurrency','default_interval')})
            db.merge(Setting(key='send_policy:'+p.id,value=policy))
            if p.is_default: db.execute(update(SMTPProfile).where(SMTPProfile.id!=p.id).values(is_default=False))
            elif not db.scalar(select(SMTPProfile.id).where(SMTPProfile.is_default==True)): p.is_default=True
            db.commit()
        except Exception:
            db.rollback()
            if new_ref:
                try: app.state.vault.delete(new_ref)
                except CredentialError: pass
            raise
        if new_ref and previous_ref!=new_ref:
            try: app.state.vault.delete(previous_ref)
            except CredentialError: pass  # Old unreachable credential; never compromise saved configuration.
        return profile_data(p,db)

    @api.post('/smtp-profiles')
    def add_profile(body:ProfileInput,db=Depends(get_db)):
        with app.state.command_lock: return save_profile(body,db)

    @api.put('/smtp-profiles/{ident}')
    def edit_profile(ident:str,body:ProfileInput,db=Depends(get_db)):
        with app.state.command_lock: return save_profile(body,db,required(db,SMTPProfile,ident))

    @api.delete('/smtp-profiles/{ident}')
    def remove_profile(ident:str,db=Depends(get_db)):
        with app.state.command_lock:
            p=required(db,SMTPProfile,ident); ensure_unlocked(db,p.id); app.state.vault.delete(p.credential_ref); db.delete(p); db.flush()
            stored=db.get(Setting,'send_policy:'+ident)
            if stored: db.delete(stored)
            if not db.scalar(select(SMTPProfile.id).where(SMTPProfile.is_default==True)):
                other=db.scalar(select(SMTPProfile))
                if other: other.is_default=True
            db.commit()
        return {'ok':True}

    @api.post('/smtp-profiles/{ident}/test')
    def test_profile(ident:str,db=Depends(get_db)):
        with app.state.command_lock:
            p=required(db,SMTPProfile,ident); snap=snapshot(p); password=app.state.vault.get(p.credential_ref)
        transport=app.state.transport_factory(snap,password)
        try: transport.connect()
        finally: transport.close()
        return {'ok':True,'detail':'连接、TLS 与认证通过；尚未发送邮件'}

    @api.get('/classes')
    def classes(db=Depends(get_db)):
        return [{'id':c.id,'name':c.name,'count':len(list(db.scalars(select(Student.id).where(Student.class_id==c.id))))} for c in db.scalars(select(Classroom).order_by(Classroom.name))]

    @api.post('/classes')
    def add_class(body:NameInput,db=Depends(get_db)):
        c=Classroom(name=body.name); db.add(c); db.commit(); return {'id':c.id,'name':c.name,'count':0}

    @api.put('/classes/{ident}')
    def edit_class(ident:str,body:NameInput,db=Depends(get_db)):
        c=required(db,Classroom,ident); c.name=body.name; db.commit(); return {'id':c.id,'name':c.name}

    @api.delete('/classes/{ident}')
    def remove_class(ident:str,db=Depends(get_db)):
        db.delete(required(db,Classroom,ident)); db.commit(); return {'ok':True}

    @api.get('/classes/{ident}/students')
    def students(ident:str,db=Depends(get_db)):
        required(db,Classroom,ident)
        return [{'id':s.id,'name':s.name,'email':s.email} for s in db.scalars(select(Student).where(Student.class_id==ident).order_by(Student.name))]

    @api.post('/classes/{ident}/students')
    def add_student(ident:str,body:StudentInput,db=Depends(get_db)):
        required(db,Classroom,ident)
        if db.scalar(select(Student.id).where(Student.class_id==ident,Student.email==body.email)): raise HTTPException(409,'该邮箱已在当前班级中')
        s=Student(class_id=ident,**body.model_dump()); db.add(s); db.commit(); return {'id':s.id,'name':s.name,'email':s.email}

    @api.put('/classes/{class_id}/students/{ident}')
    def edit_student(class_id:str,ident:str,body:StudentInput,db=Depends(get_db)):
        s=required(db,Student,ident)
        if s.class_id!=class_id: raise HTTPException(404,'学生不属于此班级')
        if db.scalar(select(Student.id).where(Student.class_id==class_id,Student.email==body.email,Student.id!=ident)): raise HTTPException(409,'该邮箱已在当前班级中')
        s.name,s.email=body.name,body.email; db.commit(); return {'id':s.id,'name':s.name,'email':s.email}

    @api.delete('/classes/{class_id}/students/{ident}')
    def remove_student(class_id:str,ident:str,db=Depends(get_db)):
        s=required(db,Student,ident)
        if s.class_id!=class_id: raise HTTPException(404,'学生不属于此班级')
        db.delete(s); db.commit(); return {'ok':True}

    @api.post('/classes/{ident}/import/preview')
    async def preview_import(ident:str,request:Request,text:str=Form(''),file:UploadFile|None=File(None),name_column:int|None=Form(None),email_column:int|None=Form(None),has_header:bool|None=Form(None),db=Depends(get_db),session=Depends(current)):
        required(db,Classroom,ident)
        rows=read_file(await file.read(5*1024*1024+1),file.filename or '') if file and file.filename else pasted(text)
        existing={s.email:s.name for s in db.scalars(select(Student).where(Student.class_id==ident))}
        result=import_preview(rows,existing,name_column,email_column,has_header)
        token=uid(); stamp=time.monotonic()
        with app.state.command_lock:
            app.state.imports={k:v for k,v in app.state.imports.items() if stamp-v['time']<900}
            if len(app.state.imports)>=20: app.state.imports.pop(next(iter(app.state.imports)))
            app.state.imports[token]={'class_id':ident,'rows':rows,'name_column':result['name_column'],'email_column':result['email_column'],'has_header':result['has_header'],'time':stamp,'owner':session.token_hash}
        result['preview_id']=token; return result

    @api.post('/classes/{ident}/import/confirm')
    def confirm_import(ident:str,body:ImportConfirm,session=Depends(current),db=Depends(get_db)):
        with app.state.command_lock:
            cached=app.state.imports.get(body.preview_id)
            if not cached or cached['class_id']!=ident or cached['owner']!=session.token_hash or time.monotonic()-cached['time']>900: raise HTTPException(410,'导入预览已过期，请重新预览')
            required(db,Classroom,ident)
            existing={s.email:s for s in db.scalars(select(Student).where(Student.class_id==ident))}
            result=import_preview(cached['rows'],{k:v.name for k,v in existing.items()},cached['name_column'],cached['email_column'],cached['has_header'])
            problems=[r for r in result['rows'] if r['status']=='invalid' or (r['status']=='conflict' and (not body.overwrite_conflicts or r['message'].startswith('文件内')))]
            if problems and not body.valid_only: raise HTTPException(422,'存在错误行或姓名冲突，请修正，或明确选择仅导入有效行')
            added=updated=skipped=0
            for row in result['rows']:
                if row['status']=='valid':
                    s=Student(class_id=ident,name=row['name'],email=row['email']); db.add(s); existing[row['email']]=s; added+=1
                elif row['status']=='conflict' and body.overwrite_conflicts and not row['message'].startswith('文件内') and row['email'] in existing:
                    existing[row['email']].name=row['name']; updated+=1
                else: skipped+=1
            db.commit(); app.state.imports.pop(body.preview_id,None)
            return {'added':added,'updated':updated,'skipped':skipped}

    @api.get('/examples/students.csv')
    def sample_csv(): return Response('\ufeff姓名,邮箱\n张同学,zhang@example.com\n李同学,li@example.com\n',media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename=students-example.csv'})

    @api.get('/templates')
    def all_templates(db=Depends(get_db)):
        return [template_content({k:getattr(t,k) for k in ('id','name','subject','title','delta','builtin')}) for t in db.scalars(select(MailTemplate).order_by(MailTemplate.builtin.desc(),MailTemplate.name))]

    @api.post('/templates')
    def add_template(body:TemplateInput,db=Depends(get_db)):
        validate_delta(body.delta)
        t=MailTemplate(**body.model_dump()); db.add(t); db.commit(); return {'id':t.id}

    @api.put('/templates/{ident}')
    def edit_template(ident:str,body:TemplateInput,db=Depends(get_db)):
        t=required(db,MailTemplate,ident); validate_delta(body.delta)
        for k,v in body.model_dump().items(): setattr(t,k,v)
        db.commit(); return {'id':t.id}

    @api.delete('/templates/{ident}')
    def delete_template(ident:str,db=Depends(get_db)):
        db.delete(required(db,MailTemplate,ident)); db.commit(); return {'ok':True}

    @api.get('/notices')
    def notices(db=Depends(get_db)):
        return [{'id':n.id,'name':n.name,'content':draft_content(n.content),'needs_submission_email':'submission_url' in n.content and not draft_content(n.content).get('submission_email'),'updated_at':n.updated_at.isoformat()+'Z'} for n in db.scalars(select(Notice).order_by(Notice.updated_at.desc()))]

    @api.post('/notices')
    def save_notice(body:DraftInput,db=Depends(get_db)):
        n=Notice(name=body.content.get('subject','')[:200] or '未命名草稿',content=body.content); db.add(n); db.commit(); return {'id':n.id}

    @api.put('/notices/{ident}')
    def update_notice(ident:str,body:DraftInput,db=Depends(get_db)):
        n=required(db,Notice,ident); n.name=body.content.get('subject','')[:200] or '未命名草稿'; n.content=body.content; n.updated_at=now(); db.commit(); return {'id':n.id}

    @api.delete('/notices/{ident}')
    def delete_notice(ident:str,db=Depends(get_db)):
        db.delete(required(db,Notice,ident)); db.commit(); return {'ok':True}

    @api.post('/notices/preview')
    def preview_notice(body:PreviewInput,db=Depends(get_db)): return render(body.notice,person_for(db,body.notice,body.student_id))

    @api.post('/notices/test')
    def test_notice(body:TestInput,db=Depends(get_db)):
        with app.state.command_lock:
            p=required(db,SMTPProfile,body.notice.profile_id); ensure_unlocked(db,p.id)
            snap=snapshot(p); password=app.state.vault.get(p.credential_ref)
        content=render(body.notice,person_for(db,body.notice,body.student_id))
        transport=app.state.transport_factory(snap,password)
        try:
            transport.connect(); transport.deliver(content,{'name':'测试收件人','email':body.to},make_msgid(domain='homework-reminder.local'))
        finally: transport.close()
        return {'ok':True,'detail':'测试邮件已提交 SMTP，请到指定测试邮箱确认实际显示'}

    def add_job(db,key,profile_id,snap,notice,people,interval):
        existing=db.scalar(select(SendJob).where(SendJob.idempotency_key==key))
        if existing: return existing
        j=SendJob(id=uid(),idempotency_key=key,profile_id=profile_id,smtp_snapshot=snap,notice_snapshot=notice,subject=render(notice,people[0])['subject'],interval=interval)
        db.add(j); db.flush()
        for position,person in enumerate(people):
            db.add(Delivery(job_id=j.id,position=position,student_id=person['id'],name=person['name'],email=person['email'],class_name=person['class_name'],message_id=make_msgid(domain='homework-reminder.local')))
        db.commit(); app.state.sender.notify(); return j

    @api.post('/send-jobs')
    def send(body:SendInput,db=Depends(get_db)):
        with app.state.command_lock:
            existing=db.scalar(select(SendJob).where(SendJob.idempotency_key==body.idempotency_key))
            if existing: return {'id':existing.id,'reused':True}
            n=body.notice; p=required(db,SMTPProfile,n.profile_id); c=required(db,Classroom,n.class_id)
            if not n.student_ids: raise HTTPException(422,'请至少选择一位收件人')
            selected=list(dict.fromkeys(n.student_ids))
            people=list(db.scalars(select(Student).where(Student.id.in_(selected),Student.class_id==c.id)))
            if len(people)!=len(selected): raise HTTPException(422,'部分学生已删除或不属于当前班级，请刷新名单')
            recipients=[]; emails=set()
            by_id={s.id:s for s in people}
            for selected_id in selected:
                s=by_id[selected_id]
                if s.email in emails: continue
                person={'id':s.id,'name':s.name,'email':s.email,'class_name':c.name}; render(n,person); recipients.append(person); emails.add(s.email)
            app.state.vault.get(p.credential_ref)
            j=add_job(db,body.idempotency_key,p.id,snapshot(p),n.model_dump(),recipients,n.interval)
            return {'id':j.id,'reused':False}

    @api.get('/send-jobs')
    def jobs(db=Depends(get_db)): return [job_data(db,j) for j in db.scalars(select(SendJob).order_by(SendJob.created_at.desc()).limit(100))]

    @api.get('/send-jobs/{ident}')
    def job(ident:str,db=Depends(get_db)): return job_data(db,required(db,SendJob,ident),True)

    @api.post('/send-jobs/{ident}/cancel')
    def cancel(ident:str,db=Depends(get_db)):
        with app.state.command_lock:
            j=required(db,SendJob,ident)
            if j.status in ACTIVE:
                j.cancel_requested=True; db.commit()
            elif j.status in ('paused','interrupted'):
                Sender.cancel_pending(db,j); db.commit()
            else: raise HTTPException(409,'任务已经结束')
        app.state.sender.notify(); return {'ok':True}

    @api.post('/send-jobs/{ident}/retry')
    def retry(ident:str,body:RetryInput,db=Depends(get_db)):
        with app.state.command_lock:
            existing=db.scalar(select(SendJob).where(SendJob.idempotency_key==body.idempotency_key))
            if existing: return {'id':existing.id,'reused':True}
            original=required(db,SendJob,ident)
            if original.status in ACTIVE: raise HTTPException(409,'任务尚未停止，不能重试')
            p=required(db,SMTPProfile,original.profile_id)
            failed=list(db.scalars(select(Delivery).where(Delivery.job_id==ident,Delivery.status=='failed').order_by(Delivery.position)))
            if not failed: raise HTTPException(422,'没有明确失败的邮件；待确认、未发送和已提交项目不会自动重发')
            people=[{'id':d.student_id,'name':d.name,'email':d.email,'class_name':d.class_name} for d in failed]
            app.state.vault.get(p.credential_ref)
            j=add_job(db,body.idempotency_key,p.id,snapshot(p),original.notice_snapshot,people,original.interval)
            return {'id':j.id,'reused':False}

    app.include_router(api)
    return app

app=create_app()
