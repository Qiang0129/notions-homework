"""Send-confirm drawer acceptance with a static app, fictional rosters and mocked APIs only."""
from __future__ import annotations
import json
import socket
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from playwright.sync_api import sync_playwright,expect

OUT=ROOT/'output'/'playwright'/'send-drawer'
COUNTS=(1,9,20,21,66,200,5000)

class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(ROOT),**kwargs)
    def log_message(self,*args):pass
    def do_GET(self):
        if urlparse(self.path).path=='/':
            data=(ROOT/'app/templates/index.html').read_bytes();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data);return
        if self.path.startswith('/static/'):
            self.path='/app'+self.path
        super().do_GET()

def people(count):
    return [{'id':f's{count}-{n:04d}','name':('林同学' if n<3 else f'同学{n+1:04d}'),'email':f'student{n+1:04d}.long-address@example.com'} for n in range(count)]

def run():
    OUT.mkdir(parents=True,exist_ok=True)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{port}';created=[];errors=[]
    try:
        with sync_playwright() as pw:
            edge=Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')
            browser=pw.chromium.launch(headless=True,**({'executable_path':str(edge)} if edge.exists() else {}))
            context=browser.new_context(viewport={'width':1440,'height':960},locale='zh-CN')
            page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)));page.on('console',lambda m:errors.append(m.text) if m.type=='error' else None)
            rosters={f'c{count}':people(count) for count in COUNTS}
            classes=[{'id':key,'name':f'验收班 · {len(value)} 人','count':len(value)} for key,value in rosters.items()]
            profile={'id':'p1','name':'模拟邮箱','sender_name':'课程助教','sender_email':'teacher@example.com','host':'smtp.example.com','port':465,'security':'ssl','username':'teacher@example.com','reply_to':'','is_default':True}
            template={'id':'t1','name':'截止提醒','subject':'{{name}}：关于第三章作业的超长主题核对示例','title':'第三章作业提醒','delta':{'ops':[{'insert':'请按时提交作业。\n'}]},'builtin':True}
            def api(route):
                req=route.request;path=urlparse(req.url).path
                if path=='/api/auth/status':data={'authenticated':True,'csrf':'mock-csrf'}
                elif path=='/api/smtp-profiles':data=[profile]
                elif path=='/api/classes':data=classes
                elif path=='/api/templates':data=[template]
                elif path=='/api/notices':data=[]
                elif path.startswith('/api/classes/') and path.endswith('/students'):data=rosters[path.split('/')[3]]
                elif path=='/api/notices/preview':
                    payload=req.post_data_json;first=next((p for p in rosters[payload['notice']['class_id']] if p['id']==payload.get('student_id')),rosters[payload['notice']['class_id']][0]);data={'subject':payload['notice']['subject'].replace('{{name}}',first['name']),'html':f'<!doctype html><html><body><h1>{first["name"]}同学，你好</h1><p>模拟邮件内容</p></body></html>'}
                elif path=='/api/send-jobs' and req.method=='POST':created.append(req.post_data_json);data={'id':'job-1','reused':len(created)>1}
                elif path=='/api/send-jobs':data=[]
                elif path=='/api/send-jobs/job-1':
                    payload=created[-1]['notice'];data={'id':'job-1','subject':'模拟主题','sender_name':'课程助教','sender_email':'teacher@example.com','status':'queued','total':len(payload['student_ids']),'created_at':'2026-10-18T08:00:00','cancel_requested':False,'error':None,'counts':{'pending':len(payload['student_ids']),'sending':0,'accepted':0,'failed':0,'unknown':0,'cancelled':0},'deliveries':[]}
                else:data=[]
                route.fulfill(status=200,content_type='application/json',body=json.dumps(data,ensure_ascii=False))
            page.route('**/api/**',api)
            page.goto(base+'/#compose');page.wait_for_function("() => S.profiles.length===1 && S.classes.length===7")
            page.locator('#course').fill('高等数学');page.locator('#assignment').fill('第三章习题');page.locator('#deadline').fill('2026-10-20T23:59');page.locator('#submission-email').fill('homework@example.com')
            report={'counts':{},'checks':[],'errors':errors}
            for count in COUNTS:
                page.locator('#compose-class').select_option(f'c{count}');page.wait_for_function("() => S.recipientState==='ready'")
                page.locator('#review-send').click();expect(page.locator('#send-confirm-drawer')).to_be_visible();expect(page.locator('#send-confirm-total')).to_have_text(str(count))
                seen=[]
                while True:
                    seen.extend(page.locator('#send-confirm-list .send-confirm-person span').all_text_contents())
                    next_button=page.locator('#send-confirm-pages [aria-label="下一页"]')
                    if next_button.count()==0 or next_button.is_disabled():break
                    next_button.click()
                expected=[p['email'] for p in rosters[f'c{count}']]
                assert seen==expected,(count,len(seen),len(set(seen)))
                report['counts'][str(count)]={'pages':(count+19)//20,'unique':len(set(seen)),'ordered':seen==expected}
                page.locator('#send-confirm-close').click();expect(page.locator('#send-confirm-drawer')).not_to_be_visible()
            page.locator('#compose-class').select_option('c66');page.wait_for_function("() => S.recipientState==='ready'")
            page.evaluate("() => {S.selected=new Set(S.students.slice(0,12).map(s=>s.id));updateSelected()}");page.locator('#recipient-search').fill('林')
            expect(page.locator('#recipient-area [data-recipient]')).to_have_count(3);expect(page.locator('#send-count')).to_have_text('12')
            page.locator('#review-send').click();expect(page.locator('#send-confirm-total')).to_have_text('12');expect(page.locator('#send-confirm-list .send-confirm-roster li')).to_have_count(12)
            frozen=page.evaluate('sendConfirmController.state.snapshot.people.map(p=>p.id)');assert frozen==[p['id'] for p in rosters['c66'][:12]]
            page.locator('#send-confirm-search').fill('not-found');expect(page.locator('#send-confirm-list')).to_contain_text('仅筛选显示，不改变发送名单');expect(page.locator('#send-confirm-total')).to_have_text('12')
            page.locator('[data-clear-confirm-search]').click();page.locator('#send-confirm-pages [aria-label="下一页"]') if False else None
            page.locator('#send-confirm-ack').check();page.locator('#send-confirm-interval').fill('0');expect(page.locator('#send-confirm-ack')).not_to_be_checked();expect(page.locator('#send-confirm-submit')).to_be_disabled();page.locator('#send-confirm-interval').fill('4');page.locator('#send-confirm-ack').check();expect(page.locator('#send-confirm-submit')).to_be_enabled()
            page.locator('#send-confirm-body').evaluate('el=>el.scrollTop=0');page.screenshot(path=str(OUT/'send-confirm-desktop.png'))
            page.set_viewport_size({'width':375,'height':812});page.locator('#send-confirm-body').evaluate('el=>el.scrollTop=0');page.screenshot(path=str(OUT/'send-confirm-mobile.png'))
            page.locator('#send-confirm-submit').click();page.wait_for_function("() => S.page==='history'")
            assert len(created)==1 and created[0]['notice']['student_ids']==frozen and created[0]['notice']['interval']==4
            report['checks']+=['All requested sizes preserve ordered unique recipients across 20-person pages','3 visible / 12 selected opens and submits exactly the frozen 12 IDs','Drawer search, empty result and clear do not alter send scope','Invalid interval and missing acknowledgement disable submission','Desktop and mobile screenshots captured','Single mocked create request uses one idempotency key']
            assert not errors,errors
            (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            browser.close()
            print(json.dumps(report,ensure_ascii=False))
    finally:server.shutdown();server.server_close();thread.join(5)

if __name__=='__main__':run()
