from __future__ import annotations
import threading
import time
from collections import deque
from sqlalchemy import select, update
from .models import SendJob, Delivery
from .rendering import render
from .smtp import TransportFailure
from .credentials import CredentialError

ACTIVE=('queued','sending')

class Sender:
    def __init__(self,app):
        self.app=app; self.stop=threading.Event(); self.wake=threading.Event(); self.thread=None

    def recover(self):
        with self.app.state.Session() as db:
            # No automatic continuation: an old in-flight SMTP DATA may have been accepted.
            db.execute(update(Delivery).where(Delivery.status=='sending').values(status='unknown',detail='应用曾在提交过程中退出，请核查收件箱后处理'))
            db.execute(update(SendJob).where(SendJob.status.in_(ACTIVE)).values(status='interrupted',error='应用已重启；任务未自动续发，请检查结果并按需重试明确失败项'))
            db.commit()

    def start(self):
        self.recover(); self.thread=threading.Thread(target=self.run,name='mail-sender',daemon=True); self.thread.start()

    def shutdown(self):
        self.stop.set(); self.wake.set()
        if self.thread: self.thread.join()

    def notify(self): self.wake.set()

    def run(self):
        while not self.stop.is_set():
            try:
                with self.app.state.Session() as db:
                    job=db.scalar(select(SendJob).where(SendJob.status=='queued').order_by(SendJob.created_at))
                    job_id=job.id if job else None
                if job_id: self.process(job_id); continue
            except Exception:
                # Never include exception payloads: a provider may echo credentials or body data.
                import logging
                logging.getLogger('homework').error('发送工作线程遇到内部错误，请查看任务状态；未输出敏感异常详情')
                if 'job_id' in locals() and job_id:
                    with self.app.state.Session() as db:
                        db.execute(update(Delivery).where(Delivery.job_id==job_id,Delivery.status=='sending').values(status='unknown',detail='内部异常，提交结果待确认'))
                        db.execute(update(SendJob).where(SendJob.id==job_id).values(status='interrupted',error='内部异常，已停止自动发送'))
                        db.commit()
            self.wake.wait(self.app.state.settings.worker_interval); self.wake.clear()

    def process(self,job_id):
        with self.app.state.command_lock:
            with self.app.state.Session() as db:
                job=db.get(SendJob,job_id)
                if not job or job.status!='queued': return
                if job.cancel_requested:
                    self.cancel_pending(db,job); db.commit(); return
                job.status='sending'; db.commit()
                snapshot=job.smtp_snapshot; notice=job.notice_snapshot
                ids=list(db.scalars(select(Delivery.id).where(Delivery.job_id==job_id,Delivery.status=='pending').order_by(Delivery.position)))
                interval=self.app.state.settings.send_interval_override
                if interval is None: interval=job.interval
        # Only this job runs. Each lane owns its transport; claims and DB writes are
        # serialized briefly, never across SMTP I/O or the independent cooldowns.
        concurrency=min(5,max(1,notice.get('concurrency',1)),max(1,len(ids)))
        pending=deque(ids); gate=threading.RLock(); abort=threading.Event(); connected=threading.Event()
        failure={'detail':'','internal':False}

        def fail(detail,internal=False,initial=False):
            abort.set()
            with gate:
                if not failure['detail']: failure.update(detail=detail,internal=internal)
                if initial and pending:
                    with self.app.state.Session() as db:
                        item=db.get(Delivery,pending.popleft()); item.status='failed'; item.detail=detail; db.commit()

        def claim():
            with gate, self.app.state.command_lock:
                if abort.is_set() or self.stop.is_set() or not pending: return None
                with self.app.state.Session() as db:
                    if db.get(SendJob,job_id).cancel_requested: abort.set(); return None
                    item=db.get(Delivery,pending.popleft())
                    person={'name':item.name,'email':item.email,'class_name':item.class_name}
                    item.status='sending'; db.commit()
                    return item.id,person,item.message_id

        def cooldown():
            deadline=time.monotonic()+interval
            while not abort.is_set() and not self.stop.is_set():
                with gate:
                    if not pending: return
                    with self.app.state.Session() as db:
                        if db.get(SendJob,job_id).cancel_requested: abort.set(); return
                remaining=deadline-time.monotonic()
                if remaining<=0: return
                # Bounded poll also wakes every lane on cancellation, unlike a
                # shared auto-cleared event that can be consumed by one waiter.
                abort.wait(min(.05,remaining))

        def lane(first=False):
            transport=None; active=None
            try:
                if abort.is_set() or self.stop.is_set(): return
                password=self.app.state.vault.get(snapshot['credential_ref'])
                transport=self.app.state.transport_factory(snapshot,password); password=None
                try: transport.connect()
                except (CredentialError,TransportFailure) as exc:
                    fail(str(exc),initial=first); return
                if first: connected.set()
                while (active:=claim()) is not None:
                    item_id,person,message_id=active; fatal=False
                    try:
                        transport.deliver(render(notice,person),person,message_id)
                        status,detail='accepted','SMTP 服务器已接受；不代表已送达或已读'
                    except TransportFailure as exc:
                        status='unknown' if exc.ambiguous else 'failed'; detail=exc.detail; fatal=exc.fatal
                    except Exception:
                        status,detail,fatal='unknown','内部异常，提交结果待确认',True
                    if fatal: fail(detail)
                    with gate:
                        with self.app.state.Session() as db:
                            item=db.get(Delivery,item_id); item.status=status; item.detail=detail; db.commit()
                    active=None
                    if fatal: return
                    cooldown()
            except CredentialError as exc:
                fail(str(exc),initial=first)
            except Exception:
                fail('发送工作线程遇到内部错误，已停止自动发送',internal=True)
                if active:
                    with gate:
                        with self.app.state.Session() as db:
                            item=db.get(Delivery,active[0]); item.status='unknown'; item.detail='内部异常，提交结果待确认'; db.commit()
            finally:
                if first: connected.set()
                if transport:
                    try: transport.close()
                    except Exception: fail('SMTP 连接关闭异常，已停止自动发送',internal=True)

        threads=[threading.Thread(target=lane,args=(True,),name='mail-lane-1')]
        threads[0].start()
        try:
            connected.wait()
            if not abort.is_set() and not self.stop.is_set():
                for index in range(1,concurrency):
                    thread=threading.Thread(target=lane,name=f'mail-lane-{index+1}'); thread.start(); threads.append(thread)
        except Exception:
            fail('无法启动发送工作线程，已停止自动发送',internal=True)
        finally:
            for thread in threads: thread.join()
        # No final task state is published until every in-flight outcome is durable.
        with self.app.state.command_lock, self.app.state.Session() as db:
            job=db.get(SendJob,job_id)
            if job.cancel_requested: self.cancel_pending(db,job)
            elif failure['detail']:
                job.status='interrupted' if failure['internal'] else 'paused'; job.error=failure['detail']
            elif self.stop.is_set(): job.status='interrupted'; job.error='应用已停止，剩余邮件未发送'
            else:
                statuses=list(db.scalars(select(Delivery.status).where(Delivery.job_id==job_id)))
                job.status='completed' if all(x=='accepted' for x in statuses) else 'partial'
            db.commit()

    @staticmethod
    def cancel_pending(db,job):
        db.execute(update(Delivery).where(Delivery.job_id==job.id,Delivery.status=='pending').values(status='cancelled',detail='用户取消，未发送'))
        job.status='cancelled'
