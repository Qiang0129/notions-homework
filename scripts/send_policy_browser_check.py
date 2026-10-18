"""Actual app + temporary SQLite + MemoryVault + fake SMTP. Never uses production data."""
from __future__ import annotations
import json
import sys
from types import SimpleNamespace
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'));sys.path.insert(0,str(ROOT/'tests'))
from roster_browser_check import isolated_app
from conftest import seed
from playwright.sync_api import sync_playwright,expect
OUT=ROOT/'output/playwright/send-policy'


def run():
    OUT.mkdir(parents=True,exist_ok=True)
    with isolated_app() as (app,factory,base),sync_playwright() as pw:
        edge=Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')
        browser=pw.chromium.launch(headless=True,**({'executable_path':str(edge)} if edge.exists() else {}))
        context=browser.new_context(viewport={'width':1440,'height':1080},locale='zh-CN')
        context.request.post(base+'/api/auth/setup',data={'password':'fictional-policy-password'})
        page=context.new_page();errors=[];injected=[];outside=[];creates=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.on('console',lambda message:errors.append(message.text) if message.type=='error' else None)
        def protect(route):
            if route.request.url.startswith(base+'/'):route.continue_()
            else:outside.append(route.request.url);route.abort()
        context.route('**/*',protect)
        page.on('request',lambda request:creates.append(request.post_data) if request.url==base+'/api/send-jobs' and request.method=='POST' else None)
        page.goto(base);page.wait_for_function('() => !!S.csrf')
        csrf=page.evaluate('S.csrf')
        class Adapter:
            def post(self,path,json=None,data=None):
                result=context.request.post(base+path,**({'data':json} if json is not None else {'form':data}),headers={'X-CSRF-Token':csrf})
                return SimpleNamespace(status_code=result.status,json=result.json,text=result.text())
            def get(self,path):
                result=context.request.get(base+path);return SimpleNamespace(status_code=result.status,json=result.json,text=result.text())
        profile,pid,cid,n=seed(Adapter(),21)
        second=context.request.post(base+'/api/smtp-profiles',data={**profile,'name':'第二个模拟邮箱','sender_email':'second@example.com','default_concurrency':5,'default_interval':6},headers={'X-CSRF-Token':csrf}).json()['id']
        page.evaluate('refreshBasics()');page.locator('[data-route=settings]').click()
        page.locator(f'[data-edit-profile="{pid}"]').click();expect(page.locator('#dialog')).to_be_visible()
        page.locator('#profile-policy input[type=radio][value="3"]').check();page.locator('#profile-interval').fill('4')
        expect(page.locator('#profile-policy')).to_contain_text('最多同时处理 3 封；每路完成后等待 4 秒')
        page.locator('#profile-policy').scroll_into_view_if_needed();page.screenshot(path=str(OUT/'mailbox-desktop.png'))
        page.locator('#dialog-confirm').click();expect(page.locator('#dialog')).not_to_be_visible()
        expect(page.locator('#profile-list')).to_contain_text('3 路并发')
        current=context.request.get(base+'/api/smtp-profiles').json();p=next(p for p in current if p['id']==pid)
        assert (p['default_concurrency'],p['default_interval'])==(3,4)
        page.locator('[data-route=compose]').click();page.evaluate('(n)=>fillNotice(n)',{k:v for k,v in n.items() if k not in ('concurrency','interval')})
        assert page.evaluate('notice().concurrency')==3 and page.evaluate('notice().interval')==4
        page.locator('#compose-profile').select_option(second);assert page.evaluate('notice().concurrency')==5 and page.evaluate('notice().interval')==6
        page.locator('#compose-profile').select_option(pid)
        page.evaluate('(n)=>fillNotice(n)',{**n,'concurrency':2,'interval':7})
        assert page.evaluate('notice().concurrency')==2 and page.evaluate('notice().interval')==7
        page.evaluate('(n)=>fillNotice(n)',{**n,'student_ids':n['student_ids'][:12],'concurrency':3,'interval':4})
        page.locator('#recipient-search').fill('student0@');expect(page.locator('#recipient-area [data-recipient]')).to_have_count(1)
        page.locator('#review-send').click();expect(page.locator('#send-confirm-drawer')).to_be_visible()
        expect(page.locator('#send-confirm-total')).to_have_text('12');expect(page.locator('#send-policy-origin')).to_have_text('沿用邮箱默认')
        page.locator('#send-confirm-ack').check();page.locator('#send-confirm-policy input[type=radio][value="2"]').check();expect(page.locator('#send-confirm-ack')).not_to_be_checked()
        expect(page.locator('#send-policy-origin')).to_have_text('仅本次修改');page.locator('#send-policy-reset').click()
        expect(page.locator('#send-confirm-policy input[type=radio][value="3"]')).to_be_checked();expect(page.locator('#send-confirm-interval')).to_have_value('4')
        page.locator('#send-confirm-policy input[type=radio][value="3"]').focus();page.keyboard.press('ArrowRight');expect(page.locator('#send-confirm-policy input[type=radio][value="4"]')).to_be_checked()
        page.locator('#send-confirm-interval').fill('0');expect(page.locator('#send-confirm-submit')).to_be_disabled()
        page.locator('#send-confirm-interval').fill('5');page.locator('#send-confirm-ack').check()
        page.locator('#send-confirm-search').fill('no-match');expect(page.locator('#send-confirm-ack')).to_be_checked();expect(page.locator('#send-confirm-total')).to_have_text('12')
        page.locator('[data-clear-confirm-search]').click();expect(page.locator('#toast-region > *')).to_have_count(0,timeout=12000);page.locator('#send-confirm-policy').scroll_into_view_if_needed();page.screenshot(path=str(OUT/'confirm-desktop.png'))
        layout={}
        for width,height,label in [(375,900,'mobile'),(320,740,'narrow'),(1024,540,'short')]:
            page.set_viewport_size({'width':width,'height':height});page.locator('#send-confirm-policy').scroll_into_view_if_needed()
            metrics=page.evaluate("""() => {const d=document.querySelector('#send-confirm-drawer'),r=document.querySelector('#send-confirm-policy');return {width:d.getBoundingClientRect().width,overflow:d.scrollWidth>d.clientWidth,body:document.querySelector('#send-confirm-body').clientHeight,font:getComputedStyle(r.querySelector('input[type=number]')).fontSize}}""")
            assert not metrics['overflow'] and metrics['font']=='16px' and metrics['body']>100,metrics
            layout[label]=metrics;page.screenshot(path=str(OUT/f'confirm-{label}.png'))
        contrast=page.evaluate('''() => {
            const canvas=document.createElement('canvas');canvas.width=canvas.height=1;const ctx=canvas.getContext('2d',{willReadFrequently:true});
            const lum=color=>{ctx.clearRect(0,0,1,1);ctx.fillStyle=color;ctx.fillRect(0,0,1,1);const c=[...ctx.getImageData(0,0,1,1).data].slice(0,3).map(x=>{x/=255;return x<=.04045?x/12.92:((x+.055)/1.055)**2.4});return c[0]*.2126+c[1]*.7152+c[2]*.0722};
            const result={};for(const selector of ['.send-policy-summary','.send-policy-warning','.send-policy-label','.send-policy-segments input:checked+span','.send-policy-origin']){const el=document.querySelector('#send-confirm-drawer '+selector),style=getComputedStyle(el);let bg=style.backgroundColor;if(bg==='rgba(0, 0, 0, 0)')bg='white';const x=lum(style.color),y=lum(bg);result[selector]=(Math.max(x,y)+.05)/(Math.min(x,y)+.05)}return result;
        }''')
        assert min(contrast.values())>=4.5,contrast
        page.emulate_media(reduced_motion='reduce')
        assert page.locator('#send-confirm-drawer').evaluate('el=>getComputedStyle(el).transitionDuration')=='0s'
        page.locator('#send-confirm-back').click();expect(page.locator('#send-confirm-drawer')).not_to_be_visible()
        expect(page.locator('#recipient-search')).to_have_value('student0@');assert page.evaluate('S.selected.size')==12
        page.locator('#review-send').click();expect(page.locator('#send-confirm-ack')).not_to_be_checked()
        page.locator('#send-confirm-policy input[type=radio][value="4"]').check();page.locator('#send-confirm-interval').fill('5')
        page.locator('#send-confirm-ack').check()
        # Let the server create the job, then lose only the browser's response.
        saved_job=[]
        def lose_response(route):
            result=route.fetch();saved_job.append(result.json()['id']);route.abort()
        page.route(base+'/api/send-jobs',lose_response)
        page.locator('#send-confirm-submit').click();expect(page.locator('#send-confirm-outcome-title')).to_have_text('创建结果待确认')
        expect(page.locator('#send-confirm-interval')).to_be_disabled();expect(page.locator('#send-confirm-policy input[type=radio][value="2"]')).to_be_disabled()
        assert len(creates)==1
        page.locator('#send-confirm-close').click();expect(page.locator('#send-confirm-drawer')).not_to_be_visible()
        page.locator('#review-send').click();expect(page.locator('#send-confirm-outcome-title')).to_have_text('创建结果待确认');expect(page.locator('#send-confirm-ack')).not_to_be_checked()
        page.unroute(base+'/api/send-jobs',lose_response)
        # Once the ID is known, a failed read must never trigger another create.
        detail_url=base+'/api/send-jobs/'+saved_job[0]
        def fail_read(route):route.fulfill(status=503,json={'detail':'Injected record read failure'})
        page.route(detail_url,fail_read);page.locator('#send-confirm-ack').check();page.locator('#send-confirm-submit').click()
        expect(page.locator('#send-confirm-outcome-title')).to_have_text('任务已创建');assert len(creates)==2 and creates[0]==creates[1]
        page.unroute(detail_url,fail_read);page.locator('#send-confirm-submit').click();expect(page.locator('#send-confirm-drawer')).not_to_be_visible()
        page.wait_for_function("() => S.page==='history'");expect(page.locator('#job-detail')).to_contain_text('4 路并发 · 每路间隔 5 秒')
        assert len(creates)==2
        jobs=context.request.get(base+'/api/send-jobs').json();assert len(jobs)==1 and jobs[0]['total']==12
        assert jobs[0]['concurrency']==4 and jobs[0]['interval']==5
        detail=context.request.get(detail_url).json();assert [d['email'] for d in detail['deliveries']]==[p['email'] for p in context.request.get(base+f'/api/classes/{cid}/students').json()[:12]]
        expect(page.locator('#job-detail .status-badge').first).to_have_text('已完成',timeout=15000)
        assert len(factory.messages)==12
        p=next(p for p in context.request.get(base+'/api/smtp-profiles').json() if p['id']==pid);assert (p['default_concurrency'],p['default_interval'])==(3,4)
        page.set_viewport_size({'width':375,'height':900});page.evaluate("location.hash='settings'");page.evaluate('(id)=>profileDialog(S.profiles.find(p=>p.id===id))',pid)
        expect(page.locator('#dialog')).to_be_visible();page.locator('#profile-policy').scroll_into_view_if_needed();page.screenshot(path=str(OUT/'mailbox-mobile.png'))
        injected=[error for error in errors if 'ERR_FAILED' in error or '503' in error];unexpected=[error for error in errors if error not in injected]
        assert not unexpected,unexpected;assert not outside,outside
        report={'checks':['Mailbox defaults persisted; compose inherits defaults and explicit draft overrides','Profile switching resets policy to chosen mailbox defaults','Temporary overrides and reset do not modify mailbox defaults','Native arrow keys, invalid interval, acknowledgement reset and display-only search','12 frozen recipients; response lost after actual mocked-SMTP job creation','Manual retry uses byte-identical JSON and same idempotency key','Record failure retries GET only; one task, 12 simulated messages','Desktop/mobile/narrow/short layouts and reduced motion; text contrast >=4.5:1'], 'layout':layout,'contrast':contrast,'simulated_messages':len(factory.messages),'create_attempts':len(creates),'created_jobs':len(jobs),'expected_injected_errors':injected,'unexpected_errors':unexpected,'external_requests':outside,'data':'temporary SQLite, fictional addresses, MemoryVault and FakeFactory'}
        (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=True));browser.close()

if __name__=='__main__':run()
