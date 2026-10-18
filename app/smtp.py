from __future__ import annotations
import smtplib
import socket
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import formataddr, format_datetime
from .email_assets import prepare_message_html

class TransportFailure(Exception):
    def __init__(self,detail,ambiguous=False,fatal=False):
        super().__init__(detail); self.detail=detail; self.ambiguous=ambiguous; self.fatal=fatal


def server_error(code,phase,response=b''):
    diagnostic=response.decode('utf-8',errors='ignore').lower() if isinstance(response,bytes) else str(response).lower()
    quota=any(word in diagnostic for word in ('quota','limit','frequency','rate exceeded','too many','频率','配额','上限','过于频繁'))
    fatal=quota or code in (421,450,451,452,454,530,534,535,552,554)
    label='服务器暂时拒绝或触发配额，请检查邮箱服务商限制' if fatal else '服务器明确拒绝此邮件或地址'
    return TransportFailure(f'{phase}失败（SMTP {code}）：{label}',fatal=fatal)

class SMTPTransport:
    def __init__(self,profile,password): self.profile=profile; self.password=password; self.client=None

    def connect(self):
        p=self.profile
        try:
            context=ssl.create_default_context()
            if p['security']=='ssl': self.client=smtplib.SMTP_SSL(p['host'],p['port'],timeout=30,context=context)
            else:
                self.client=smtplib.SMTP(p['host'],p['port'],timeout=30)
                self.client.ehlo()
                self.client.starttls(context=context)
                self.client.ehlo()
            self.client.login(p['username'],self.password)
        except smtplib.SMTPAuthenticationError: raise TransportFailure('认证失败：请检查用户名、授权码或应用专用密码',fatal=True) from None
        except ssl.SSLError: raise TransportFailure('TLS 握手或证书验证失败，未降级为明文连接',fatal=True) from None
        except smtplib.SMTPNotSupportedError: raise TransportFailure('服务器不支持所选 TLS 或认证方式',fatal=True) from None
        except (OSError,smtplib.SMTPException): raise TransportFailure('无法连接 SMTP 服务器，请检查地址、端口和网络',fatal=True) from None
        finally: self.password=None

    def deliver(self,rendered,person,message_id):
        p=self.profile
        message=EmailMessage(policy=SMTP)
        message['Subject']=rendered['subject']; message['From']=formataddr((p['sender_name'],p['sender_email']))
        message['To']=formataddr((person['name'],person['email']))
        message['Date']=format_datetime(datetime.now(timezone.utc)); message['Message-ID']=message_id
        if p.get('reply_to'): message['Reply-To']=p['reply_to']
        html,related=prepare_message_html(rendered['html'])
        message.set_content(rendered['text']); message.add_alternative(html,subtype='html')
        html_part=message.get_payload()[-1]
        for cid,data in related:
            html_part.add_related(data,maintype='image',subtype='png',cid=cid,disposition='inline')
        phase='envelope'
        try:
            self.client.ehlo_or_helo_if_needed()
            code,response=self.client.mail(p['sender_email'])
            if code!=250: raise server_error(code,'发件地址',response)
            code,response=self.client.rcpt(person['email'])
            if code not in (250,251):
                try: self.client.rset()
                except smtplib.SMTPException: pass
                raise server_error(code,'收件地址',response)
            phase='data'
            code,response=self.client.data(message.as_bytes())
            if code!=250: raise server_error(code,'邮件提交',response)
        except TransportFailure: raise
        except smtplib.SMTPDataError as exc: raise server_error(exc.smtp_code,'邮件提交',exc.smtp_error) from None
        except smtplib.SMTPResponseException as exc: raise server_error(exc.smtp_code,'SMTP',exc.smtp_error) from None
        except (OSError,smtplib.SMTPException):
            if phase=='data': raise TransportFailure('提交阶段连接中断，服务器是否接收未知；请核查后人工处理',ambiguous=True,fatal=True) from None
            raise TransportFailure('邮件正文尚未提交，连接已中断',fatal=True) from None

    def close(self):
        if self.client:
            try: self.client.quit()
            except Exception:
                try: self.client.close()
                except Exception: pass
            self.client=None
