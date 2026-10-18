from copy import deepcopy
import pytest
from app.compat import draft_content, template_content
from app.models import Notice, MailTemplate
from app.rendering import render
from app.schemas import NoticeInput
from conftest import seed

@pytest.mark.parametrize('email', ['homework@example.com','TA+math@EXAMPLE.COM'])
def test_new_notice_accepts_submission_email(system,email):
    c,*_=system;*_,n=seed(c,0);n['submission_email']=email
    parsed=NoticeInput.model_validate(n)
    assert parsed.submission_email==email.lower()

@pytest.mark.parametrize('email',['https://example.com/submit','mailto:ta@example.com','invalid-email','ta@example.com\r\nBcc:x@example.com','ta@example.com,other@example.com'])
def test_submission_destination_requires_one_plain_email(system,email):
    c,_,factory,_=system;*_,n=seed(c,1);n['submission_email']=email
    result=c.post('/api/notices/preview',json={'notice':n})
    assert result.status_code==422 and not factory.messages

def test_new_mail_contains_mailto_and_copyable_address(system):
    c,*_=system;*_,n=seed(c,0)
    n['delta']={'ops':[{'insert':'请发送到 {{submission_email}}。\n'},{'insert':'邮件提交','attributes':{'link':'mailto:{{submission_email}}'}},{'insert':'\n'}]}
    result=render(n,{'name':'张三','class_name':'一班'})
    assert 'href="mailto:homework@example.com"' in result['html']
    assert '发送作业邮件 →' in result['html'] and '复制邮箱地址' in result['html']
    assert '提交邮箱：homework@example.com' in result['text']
    assert '复制链接到浏览器' not in result['html'] and '提交链接：' not in result['text']

def test_old_frozen_job_keeps_its_original_destination(system):
    c,*_=system;*_,n=seed(c,0)
    n.pop('submission_email');n['submission_url']='https://example.com/original-homework'
    before=deepcopy(n);result=render(n,{'name':'张三','class_name':'一班'})
    assert n==before
    assert 'href="https://example.com/original-homework"' in result['html']
    assert '前往提交作业' in result['html']
    assert '提交链接：https://example.com/original-homework' in result['text']

def test_old_draft_is_read_adapted_without_changing_storage(system):
    c,app,factory,_=system
    old={'subject':'旧草稿','submission_url':'https://example.com/old','delta':{'ops':[{'insert':'提交：{{submission_url}}\n'}]}}
    with app.state.Session() as db:
        item=Notice(name='旧草稿',content=old);db.add(item);db.commit();ident=item.id
    visible=c.get('/api/notices').json()[0]
    assert visible['needs_submission_email'] is True
    assert visible['content']['submission_email']=='' and 'submission_url' not in visible['content']
    assert visible['content']['delta']['ops'][0]['insert']=='提交：{{submission_email}}\n'
    with app.state.Session() as db:assert db.get(Notice,ident).content==old
    assert not factory.messages

def test_legacy_template_link_token_becomes_mailto_without_modification():
    old={'name':'旧模板','subject':'提交到{{submission_url}}','delta':{'ops':[{'insert':'作业提交','attributes':{'link':'{{ submission_url }}'}}]}}
    before=deepcopy(old);new=template_content(old)
    assert old==before
    assert new['subject']=='提交到{{submission_email}}'
    assert new['delta']['ops'][0]['attributes']['link']=='mailto:{{submission_email}}'

@pytest.mark.parametrize('old',['teacher@example.com','mailto:teacher@example.com'])
def test_draft_may_recover_a_previously_entered_email(old):
    assert draft_content({'submission_url':old})=={'submission_email':'teacher@example.com'}

def test_explicit_new_email_takes_priority_over_legacy_value():
    assert draft_content({'submission_url':'https://example.com','submission_email':'new@example.com'})=={'submission_email':'new@example.com'}

def test_partial_draft_saves_new_email_field(system):
    c,*_=system
    result=c.post('/api/notices',json={'content':{'subject':'未完成','submission_email':'','delta':{'ops':[{'insert':'\n'}]}}})
    assert result.status_code==200
    assert c.get('/api/notices').json()[0]['content']['submission_email']==''
