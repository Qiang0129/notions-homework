from __future__ import annotations
import html
import json
import re
from urllib.parse import urlsplit
import nh3
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from markupsafe import Markup
from .config import ROOT
from .email_assets import preview_sources

EMAIL_ENV=Environment(loader=FileSystemLoader(ROOT/'templates'),autoescape=select_autoescape(['html']),undefined=StrictUndefined)

TOKENS = {'name','class_name','course','assignment','deadline','submission_email','submission_url'}
TOKEN = re.compile(r'\{\{\s*([a-z_]+)\s*\}\}')
COLORS = {'#e8693a','#c2410c','#1f2937','#64748b','#166534','#1d4ed8','#b91c1c','#000000'}


def replace(value, context):
    def sub(m):
        key=m.group(1)
        if key not in TOKENS: raise ValueError('未知变量：'+key)
        if key not in context or not str(context[key]).strip(): raise ValueError('变量缺少值：'+key)
        return str(context[key])
    result=TOKEN.sub(sub,value)
    if '{{' in result or '}}' in result: raise ValueError('变量格式错误，请使用变量按钮重新插入')
    return result


def safe_link(value):
    try:
        u=urlsplit(value)
        if u.scheme in ('http','https') and u.hostname and not u.username and not u.password: return value
        if u.scheme=='mailto' and u.path and not u.query and '\n' not in value and '\r' not in value: return value
    except ValueError: pass
    raise ValueError('正文含有不安全的链接，只允许 http、https 或 mailto')


def validate_delta(delta):
    if not isinstance(delta,dict) or set(delta)!={'ops'} or not isinstance(delta['ops'],list) or len(delta['ops'])>3000:
        raise ValueError('正文格式无效或过长')
    if len(json.dumps(delta,ensure_ascii=False))>150000: raise ValueError('正文最多支持约五万字')
    for op in delta['ops']:
        if not isinstance(op,dict) or set(op)-{'insert','attributes'} or not isinstance(op.get('insert'),str):
            raise ValueError('正文仅支持文字，不支持图片、附件或嵌入内容')
        attrs=op.get('attributes',{})
        if not isinstance(attrs,dict) or set(attrs)-{'bold','italic','underline','strike','header','list','align','color','link'}:
            raise ValueError('正文包含不支持的格式')
        for k,v in attrs.items():
            if k in {'bold','italic','underline','strike'} and type(v) is not bool: raise ValueError('文字样式无效')
            if k=='header' and (type(v) is not int or v not in (1,2)): raise ValueError('只支持两级标题')
            if k=='list' and v not in ('ordered','bullet'): raise ValueError('列表格式无效')
            if k=='align' and v not in ('left','center','right','justify'): raise ValueError('对齐格式无效')
            if k=='color' and v not in COLORS: raise ValueError('请使用工具栏提供的强调色')
            if k=='link' and not isinstance(v,str): raise ValueError('链接格式无效')
    # Validate variable boundaries per operation, avoiding tokens split by rich-text styling.
    sample={key:'https://example.com' if key=='submission_url' else 'homework@example.com' if key=='submission_email' else '示例' for key in TOKENS}
    for op in delta['ops']:
        replace(op['insert'],sample)
        if 'link' in op.get('attributes',{}): safe_link(replace(op['attributes']['link'],sample))
    if not ''.join(o['insert'] for o in delta['ops']).strip(): raise ValueError('请填写邮件正文')
    return delta


def body_html(delta,context):
    validate_delta(delta)
    result=[]; line=[]; list_kind=None
    def close_list():
        nonlocal list_kind
        if list_kind: result.append('</'+list_kind+'>'); list_kind=None
    def flush(attrs):
        nonlocal line,list_kind
        content=''.join(line); blank=not content; content=content or '<br>'; line=[]
        align=attrs.get('align','left')
        style='margin:0 0 14px;line-height:1.85;text-align:'+align
        if blank: style='margin:0;height:8px;line-height:8px'
        greeting=not result and not blank and not attrs.get('header') and not attrs.get('list') and '同学' in content and any(word in content for word in ('你好','您好'))
        if greeting: style+=';font-size:22px;font-weight:700;color:#07152f;margin-bottom:20px'
        if attrs.get('list'):
            kind='ol' if attrs['list']=='ordered' else 'ul'
            if list_kind!=kind:
                close_list(); result.append('<'+kind+' style="margin:0 0 14px;padding-left:24px">'); list_kind=kind
            result.append('<li style="'+style+'">'+content+'</li>')
        else:
            close_list(); tag='h'+str(attrs['header']+1) if attrs.get('header') else 'p'
            result.append('<'+tag+(' class="notice-greeting"' if greeting else '')+' style="'+style+'">'+content+'</'+tag+'>')
    for op in delta['ops']:
        attrs=op.get('attributes',{})
        pieces=replace(op['insert'],context).split('\n')
        for i,piece in enumerate(pieces):
            text=html.escape(piece)
            for key,tag in [('bold','strong'),('italic','em'),('underline','u'),('strike','s')]:
                if attrs.get(key): text='<'+tag+'>'+text+'</'+tag+'>'
            if attrs.get('color'): text='<span style="color:'+attrs['color']+'">'+text+'</span>'
            if attrs.get('link'):
                url=html.escape(safe_link(replace(attrs['link'],context)),quote=True)
                text='<a href="'+url+'" style="color:#c2410c;text-decoration:underline">'+text+'</a>'
            line.append(text)
            if i<len(pieces)-1: flush(attrs)
    if line: flush({})
    close_list()
    return nh3.clean(''.join(result),tags={'p','br','h2','h3','strong','em','u','s','span','a','ul','ol','li'},attributes={'*':{'style'},'p':{'class'},'a':{'href'}},url_schemes={'http','https','mailto'},link_rel='noopener noreferrer')


def render(notice,person):
    n=notice.model_dump() if hasattr(notice,'model_dump') else notice
    context={key:n[key] for key in ('course','assignment','deadline')}
    # New notices always validate submission_email at the API boundary. Old immutable job
    # snapshots retain their original web destination rather than being silently rewritten.
    if 'submission_email' in n:
        from .schemas import address
        email=address(n['submission_email'])
        target='mailto:'+email
        context.update(submission_email=email,submission_url=target)
        action='发送作业邮件 →'
        hint='也可以复制邮箱地址，通过常用邮箱发送作业：'
        destination=email
        plain_destination='提交邮箱：'+email
    elif 'submission_url' in n:
        target=safe_link(n['submission_url'])
        if urlsplit(target).scheme not in ('http','https'): raise ValueError('旧任务的提交链接无效')
        context['submission_url']=target
        action='前往提交作业 →'
        hint='按钮无法打开？复制链接到浏览器：'
        destination=target
        plain_destination='提交链接：'+target
    else:
        raise ValueError('请填写有效的提交邮箱')
    context.update(name=person.get('name','同学'),class_name=person.get('class_name','示例班级'))
    context['deadline']=context['deadline'].replace('T',' ')+'（北京时间）'
    subject=replace(n['subject'],context)
    title=replace(n['title'],context)
    if any(c in subject for c in '\r\n') or len(subject)>300: raise ValueError('邮件主题过长或包含换行')
    body=body_html(n['delta'],context)
    document=EMAIL_ENV.get_template('email_notice.html').render(
        subject=subject,title=title,course=context['course'],assignment=context['assignment'],
        deadline=context['deadline'],class_name=context['class_name'],body_html=Markup(body),
        images=preview_sources(),target=target,action=action,hint=hint,destination=destination,
    )
    text=f"{title}\n课程：{context['course']}\n作业：{context['assignment']}\n截止：{context['deadline']}\n\n"+''.join(replace(o['insert'],context) for o in n['delta']['ops'])+f"\n{plain_destination}\n\n本邮件由课程助教发送，如有疑问请直接回复。"
    return {'subject':subject,'html':document,'text':text}

BUILTINS=[
    ('作业发布','{{course}}｜{{assignment}} 作业通知','新的作业，准备好了吗？','{{name}}同学，你好：\n\n本次{{assignment}}已发布，请认真阅读课程要求，安排好完成时间。\n如遇到问题，可以直接回复这封邮件与助教沟通。\n\n祝学习顺利！\n'),
    ('截止提醒','{{course}}｜{{assignment}} 截止提醒','别忘了，作业即将截止','{{name}}同学，你好：\n\n温馨提醒：{{assignment}}即将截止，请检查作业是否完成，并及时发送至下方提交邮箱。\n如果你已提交，请忽略本次提醒，无需重复提交。\n\n感谢配合，祝学习顺利！\n'),
    ('补交通知','{{course}}｜{{assignment}} 补交通知','关于本次作业的补交说明','{{name}}同学，你好：\n\n{{assignment}}现开放补交，请在下方标注的截止时间前完成提交。\n如有特殊情况，请及时联系课程助教说明。\n\n感谢理解与配合。\n')
]
