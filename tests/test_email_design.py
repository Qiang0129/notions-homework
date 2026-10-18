from copy import deepcopy
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
from unittest.mock import MagicMock
from app.email_assets import images,preview_sources,prepare_message_html
from app.rendering import render
from app.smtp import SMTPTransport
from conftest import seed

class Images(HTMLParser):
    def __init__(self):super().__init__();self.tags=[]
    def handle_starttag(self,tag,attrs):
        if tag=='img':self.tags.append(dict(attrs))

def test_reference_card_keeps_dynamic_content_and_email_destination(system):
    c,*_=system;*_,n=seed(c,1)
    n['course']='数据库 <script>alert(1)</script>';n['assignment']='第四次作业'
    out=render(n,{'name':'王明','class_name':'一班'})
    assert '王明同学' in out['html'] and '第四次作业' in out['html']
    assert 'COURSE NOTICE' in out['html'] and 'notice-title' in out['html']
    assert '2026-10-20 23:59' in out['html'] and '北京时间' in out['html']
    assert 'mailto:homework@example.com' in out['html'] and 'homework@example.com' in out['text']
    assert '<script>' not in out['html'] and '&lt;script&gt;' in out['html']
    assert '127.0.0.1' not in out['html'] and '<svg' not in out['html']
    parsed=Images();parsed.feed(out['html'])
    assert len(parsed.tags)==5
    assert all(t['src'].startswith('data:image/png;base64,') and t.get('alt')=='' for t in parsed.tags)
    assert all(set(t).issubset({'src','alt','style','width','height'}) for t in parsed.tags)

def test_known_preview_images_become_self_contained_cids(system):
    c,*_=system;*_,n=seed(c,0)
    rendered=render(n,{'name':'王明','class_name':'一班'});before=deepcopy(rendered)
    html,related=prepare_message_html(rendered['html'])
    assert rendered==before and len(related)==5
    assert 'data:image' not in html and 'cid:' in html
    assert len({cid for cid,data in related})==5
    for cid,data in related:
        assert cid.startswith('<') and cid.endswith('>')
        assert 'cid:'+cid[1:-1] in html and data.startswith(b'\x89PNG\r\n\x1a\n')

def test_smtp_mime_contains_related_images_and_plain_text(system):
    c,*_=system;*_,n=seed(c,0)
    rendered=render(n,{'name':'王明','class_name':'一班'})
    profile={'sender_name':'助教','sender_email':'ta@example.com','reply_to':''}
    transport=SMTPTransport(profile,'not-used');transport.client=MagicMock()
    transport.client.mail.return_value=(250,b'OK');transport.client.rcpt.return_value=(250,b'OK');transport.client.data.return_value=(250,b'OK')
    transport.deliver(rendered,{'name':'王明','email':'wang@example.com'},'<example@classnote.local>')
    message=BytesParser(policy=policy.default).parsebytes(transport.client.data.call_args.args[0])
    assert message.get_content_type()=='multipart/alternative'
    assert message.get_body(preferencelist=('plain',)).get_content().replace('\r\n','\n').strip()==rendered['text'].strip()
    html=message.get_body(preferencelist=('html',)).get_content()
    pictures=[part for part in message.walk() if part.get_content_type()=='image/png']
    assert len(pictures)==5 and 'data:image' not in html
    for part in pictures:
        assert part['Content-Disposition']=='inline'
        assert part.get_filename() is None
        assert 'cid:'+str(part['Content-ID'])[1:-1] in html
        assert part.get_payload(decode=True).startswith(b'\x89PNG')

def test_preview_image_conversion_ignores_unrelated_strings():
    html='<p>普通邮件，不带模板插画</p>'
    assert prepare_message_html(html)==(html,[])

def test_shipped_assets_are_png_and_preview_sources_are_cached():
    assert set(images())=={'course','assignment','clock','contact','hero'}
    assert all(data.startswith(b'\x89PNG') for data in images().values())
    assert preview_sources() is preview_sources()

def test_reference_card_images_survive_real_local_smtp(system):
    import smtplib,socket
    from aiosmtpd.controller import Controller
    c,*_=system;*_,n=seed(c,0)
    rendered=render(n,{'name':'王明','class_name':'一班'})
    class Capture:
        def __init__(self):self.message=None
        async def handle_DATA(self,server,session,envelope):self.message=envelope.content;return '250 OK'
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    capture=Capture();controller=Controller(capture,hostname='127.0.0.1',port=port);controller.start()
    try:
        transport=SMTPTransport({'sender_name':'课程助教','sender_email':'ta@example.com','reply_to':''},'not-used')
        transport.client=smtplib.SMTP('127.0.0.1',port,timeout=5)
        transport.deliver(rendered,{'name':'王明','email':'wang@example.com'},'<local-card@classnote.local>');transport.close()
        message=BytesParser(policy=policy.default).parsebytes(capture.message)
        html=message.get_body(preferencelist=('html',)).get_content()
        pictures=[part for part in message.walk() if part.get_content_type()=='image/png']
        assert len(pictures)==5 and 'mailto:homework@example.com' in html and 'data:image' not in html
        for part in pictures:assert 'cid:'+str(part['Content-ID'])[1:-1] in html
    finally:controller.stop()
