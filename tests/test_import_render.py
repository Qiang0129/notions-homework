import io
from openpyxl import Workbook
import pytest
from app.importing import pasted, read_file, preview
from app.rendering import render, validate_delta

@pytest.mark.parametrize('text', ['张三 zhang@example.com','张三\tzhang@example.com','张三,zhang@example.com','张三，zhang@example.com','张三 <zhang@example.com>'])
def test_name_email_formats(text):
    r=preview(pasted(text),{})['rows'][0]
    assert r['name']=='张三' and r['email']=='zhang@example.com' and r['status']=='valid'

@pytest.mark.parametrize('encoding',['utf-8-sig','gb18030'])
def test_csv_headers(encoding):
    rows=read_file('姓名,邮箱\n张三,zhang@example.com\n'.encode(encoding),'class.csv')
    p=preview(rows,{})
    assert p['has_header'] and p['rows'][0]['name']=='张三'

def test_xlsx_and_manual_mapping():
    wb=Workbook(); ws=wb.active; ws.append(['number','contact','student']); ws.append([1,'li@example.com','李四'])
    buf=io.BytesIO(); wb.save(buf)
    p=preview(read_file(buf.getvalue(),'students.xlsx'),{},2,1,True)
    assert p['rows'][0]['name']=='李四'

def test_duplicates_conflicts_and_invalid():
    p=preview(pasted('张三 a@example.com\n张三 a@example.com\n另一个 a@example.com\n李四 nope\n王五 existing@example.com'),{'existing@example.com':'原姓名'})
    assert [r['status'] for r in p['rows']]==['valid','duplicate','conflict','invalid','conflict']

@pytest.mark.parametrize('delta',[{'ops':[{'insert':{'image':'https://example.com/x'}}]},{'ops':[{'insert':'text','attributes':{'link':'javascript:alert(1)'}}]},{'ops':[{'insert':'text','attributes':{'color':'red;display:none'}}]},{'ops':[{'insert':'{{unknown}}\n'}]},{'ops':[{'insert':'{{na'},{'insert':'me}}'}]}])
def test_dangerous_delta(delta):
    with pytest.raises(ValueError): validate_delta(delta)

def test_renderer_escapes_and_preserves_lists(system):
    from conftest import seed
    c,app,factory,vault=system
    *_,n=seed(c,1)
    n['delta']={'ops':[{'insert':'{{name}} <script>alert(1)</script>\n'},{'insert':'一'},{'insert':'\n','attributes':{'list':'ordered'}},{'insert':'二'},{'insert':'\n','attributes':{'list':'ordered'}},{'insert':'作业','attributes':{'bold':True,'link':'mailto:{{submission_email}}'}},{'insert':'\n'}]}
    out=render(n,{'name':'<img src=x onerror=alert(1)>','class_name':'一班'})
    assert '<script>' not in out['html'] and '<img src=x' not in out['html']
    assert '&lt;script&gt;' in out['html'] and '&lt;img' in out['html']
    assert out['html'].count('<ol ')==1 and '<strong>' in out['html']
    assert '提交邮箱：homework@example.com' in out['text'] and '北京时间' in out['html']
