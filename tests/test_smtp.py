import smtplib
import socket
import ssl
from email import policy
from email.parser import BytesParser
from unittest.mock import MagicMock, patch
import pytest
from aiosmtpd.controller import Controller
from app.smtp import SMTPTransport, TransportFailure

PROFILE={'host':'smtp.example.com','port':465,'security':'ssl','username':'ta@example.com','sender_name':'课程助教','sender_email':'ta@example.com','reply_to':'reply@example.com'}
CONTENT={'subject':'作业截止提醒','html':'<html><body><h1>你好</h1></body></html>','text':'你好，请及时提交。'}
PERSON={'name':'张三','email':'student@example.com'}

@pytest.mark.parametrize('security',['ssl','starttls'])
def test_verified_tls_configuration(security):
    p={**PROFILE,'security':security,'port':465 if security=='ssl' else 587}
    mock=MagicMock()
    with patch('app.smtp.smtplib.SMTP_SSL',return_value=mock) as implicit,patch('app.smtp.smtplib.SMTP',return_value=mock) as explicit:
        transport=SMTPTransport(p,'application-password'); transport.connect(); transport.close()
        context=implicit.call_args.kwargs['context'] if security=='ssl' else mock.starttls.call_args.kwargs['context']
        assert context.verify_mode==ssl.CERT_REQUIRED and context.check_hostname
        mock.login.assert_called_once_with('ta@example.com','application-password')
        assert transport.password is None

@pytest.mark.parametrize('error,match',[(smtplib.SMTPAuthenticationError(535,b'secret echoed'),'认证失败'),(ssl.SSLCertVerificationError('secret echoed'),'TLS'),(socket.timeout('secret echoed'),'无法连接'),(smtplib.SMTPNotSupportedError('secret echoed'),'不支持')])
def test_connect_errors_are_classified_without_raw_data(error,match):
    with patch('app.smtp.smtplib.SMTP_SSL',side_effect=error):
        with pytest.raises(TransportFailure) as e: SMTPTransport(PROFILE,'secret echoed').connect()
        assert match in e.value.detail and 'secret echoed' not in e.value.detail and e.value.fatal

@pytest.mark.parametrize('code,ambiguous',[(550,False),(452,False)])
def test_explicit_data_rejection_is_not_unknown(code,ambiguous):
    t=SMTPTransport(PROFILE,'x'); t.client=MagicMock(); t.client.mail.return_value=(250,b'OK'); t.client.rcpt.return_value=(250,b'OK'); t.client.data.side_effect=smtplib.SMTPDataError(code,b'no')
    with pytest.raises(TransportFailure) as e: t.deliver(CONTENT,PERSON,'<one@example.com>')
    assert e.value.ambiguous is ambiguous

def test_data_disconnect_is_unknown():
    t=SMTPTransport(PROFILE,'x'); t.client=MagicMock(); t.client.mail.return_value=(250,b'OK'); t.client.rcpt.return_value=(250,b'OK'); t.client.data.side_effect=smtplib.SMTPServerDisconnected()
    with pytest.raises(TransportFailure) as e: t.deliver(CONTENT,PERSON,'<one@example.com>')
    assert e.value.ambiguous and e.value.fatal

def test_real_loopback_smtp_mime_and_recipient_privacy():
    class Capture:
        def __init__(self): self.messages=[]
        async def handle_DATA(self,server,session,envelope): self.messages.append(envelope); return '250 OK'
    with socket.socket() as s: s.bind(('127.0.0.1',0)); port=s.getsockname()[1]
    capture=Capture(); controller=Controller(capture,hostname='127.0.0.1',port=port); controller.start()
    try:
        transport=SMTPTransport(PROFILE,'not-used')
        # Only tests bypass connect(): production always negotiates verified TLS and authenticates.
        transport.client=smtplib.SMTP('127.0.0.1',port,timeout=5)
        transport.deliver(CONTENT,PERSON,'<test@example.com>')
        transport.deliver(CONTENT,{'name':'李四','email':'second@example.com'},'<test2@example.com>'); transport.close()
        assert len(capture.messages)==2
        for envelope in capture.messages:
            assert len(envelope.rcpt_tos)==1
            message=BytesParser(policy=policy.default).parsebytes(envelope.content)
            assert message['Subject']=='作业截止提醒' and message['Reply-To']=='reply@example.com'
            assert message.get_body(preferencelist=('plain',)).get_content().strip()==CONTENT['text']
            assert '<h1>你好</h1>' in message.get_body(preferencelist=('html',)).get_content()
            assert message['Bcc'] is None
            assert 'student@example.com' not in str(message['To']) or envelope.rcpt_tos==['student@example.com']
    finally: controller.stop()

def test_nonstandard_550_quota_error_stops_sending():
    from app.smtp import server_error
    failure=server_error(550,'收件地址',b'daily message limit exceeded; secret provider diagnostics')
    assert failure.fatal and not failure.ambiguous
    assert 'secret provider diagnostics' not in failure.detail
