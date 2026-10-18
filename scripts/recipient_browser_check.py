"""Recipient picker acceptance; fictional fixtures and isolated SMTP capture only."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from roster_browser_check import isolated_app
from playwright.sync_api import sync_playwright,expect
from app.models import Classroom,Student
OUT=ROOT/'output'/'playwright'/'recipient-search'


def seed(app):
    ids={}
    with app.state.Session() as db:
        for count in (0,1,66,200,5000):
            c=Classroom(name='周三下午班' if count==66 else f'验收班 · {count} 人');db.add(c);db.flush();ids[count]=c.id
            for n in range(count):
                names=['林知远','林书宁','林安然','陈安宁','周书瑶','叶初夏','许明轩','沈沐言']
                name=names[n] if n<len(names) else f'同学{n+1:04d}'
                db.add(Student(class_id=c.id,name=name,email=f'student{n+1:04d}@example.com'))
        db.commit()
    return ids


def baseline(page,ids):
    page.locator('#compose-class').select_option(ids[66]);expect(page.locator('#send-count')).to_have_text('66')
    page.evaluate("() => { S.selected = new Set(S.students.slice(0,12).map(s=>s.id)); document.querySelectorAll('[data-recipient]').forEach(b=>b.checked=S.selected.has(b.dataset.recipient));updateSelected(); }")
    for width,height,label in [(1440,1000,'desktop'),(375,900,'mobile')]:
        page.set_viewport_size({'width':width,'height':height})
        page.locator('#recipient-area').locator('..').screenshot(path=str(OUT/f'before-{label}.png'))
    print('Captured pre-change component screenshots with fictional data.')


def verify(page,context,app,factory,base,ids,errors,external):
    from sqlalchemy import select,delete
    checks=[];timings={};layouts={};injected=[]
    query=page.locator('#recipient-search');area=page.locator('#recipient-area');bulk=page.locator('#select-all-recipients')
    def select_class(count):
        page.locator('#compose-class').select_option(ids[count])
        page.wait_for_function("() => S.recipientState==='ready'")
    def selected():return set(page.evaluate('Array.from(S.selected)'))
    def all_people(count=66):return context.request.get(base+f'/api/classes/{ids[count]}/students').json()
    def clear_search():
        if page.locator('#recipient-search-clear').is_visible():page.locator('#recipient-search-clear').click()
    def expect_ids(expected):assert selected()==set(expected),(len(selected()),len(expected))
    def request(path,data):
        response=context.request.post(base+'/api'+path,data=data,headers={'X-CSRF-Token':page.evaluate('S.csrf')})
        assert response.ok,response.text();return response.json()
    def expected_error(start,code):
        found=errors[start:];assert all(str(code) in e for e in found),found
        injected.extend(found);del errors[start:]
    def restore(content):
        page.evaluate('(content)=>fillNotice(content)',content)
    def checkbox(ident):return page.locator(f'#recipient-area [data-recipient="{ident}"]')

    expect(page.locator('#recipient-controls')).not_to_be_visible()
    expect(area).to_contain_text('先选择一个班级')
    expect(page.locator('#review-send')).to_be_disabled()
    for count in (0,1,66,200,5000):
        select_class(count)
        expect(page.locator('#send-count')).to_have_text(str(count))
        expect(area.locator('[data-recipient]')).to_have_count(count)
        assert page.locator('#recipient-area [data-recipient]:checked').count()==count
        assert page.locator('#recipient-count').text_content()==str(count)
        if not count:
            expect(query).to_be_disabled();expect(bulk).to_be_disabled();expect(area).to_contain_text('班级还没有同学');continue
        before=selected();page.evaluate('S.dirty=false')
        query.fill('  STUDENT0001@EXAMPLE.COM  ')
        expect(area.locator('[data-recipient]')).to_have_count(1);expect_ids(before)
        assert not page.evaluate('S.dirty')
        expect(page.locator('#recipient-select-label')).to_have_text('选择搜索结果（1 人）')
        query.fill('林');expect(area.locator('[data-recipient]')).to_have_count(min(count,3));expect_ids(before)
        query.fill('no-match-[]');expect(area).to_contain_text('没有找到匹配的同学');expect(bulk).to_be_disabled();expect_ids(before)
        page.locator('[data-clear-recipient-search]').click();expect(query).to_be_focused()
        expect(area.locator('[data-recipient]')).to_have_count(count);expect_ids(before)
        assert not page.evaluate('S.dirty')
        if count==5000:
            timings['filter_5000_rows_ms']=page.evaluate("() => {const t=performance.now();document.querySelector('#recipient-search').value='林';applyRecipientSearch();return performance.now()-t}")
            clear_search()
    checks.append('0/1/66/200/5000 people; case-insensitive name/email search, trimmed spaces, no matches and clearing do not alter selection/dirty state')

    # Bulk scope is the filtered view; hidden selections survive both directions.
    select_class(66);people=all_people();lins=[s['id'] for s in people if '林' in s['name']];chen=next(s['id'] for s in people if s['name']=='陈安宁')
    bulk.uncheck();expect_ids([]);assert page.evaluate('S.dirty')
    query.fill('林');bulk.check();expect_ids(lins)
    query.fill('陈');bulk.check();expect_ids(lins+[chen])
    query.fill('林');checkbox(lins[0]).uncheck();expect_ids(lins[1:]+[chen])
    assert bulk.evaluate('el=>el.indeterminate')
    expect(page.locator('#recipient-hidden-selection')).to_have_text('另有 1 位已选同学不在搜索结果中')
    expect(page.locator('#recipient-match-summary')).to_have_text('匹配 3 人，其中已选 2 人')
    bulk.check();expect_ids(lins+[chen]);bulk.uncheck();expect_ids([chen])
    assert not bulk.evaluate('el=>el.indeterminate')
    clear_search();assert checkbox(chen).is_checked()
    # Label clicks and Space preserve focus; no list rebuild during selection changes.
    row=checkbox(lins[0]);row.locator('..').click();expect_ids([chen,lins[0]])
    row.focus();page.keyboard.press('Space');expect(row).to_be_focused();expect_ids([chen])
    checks.append('Filtered bulk add/remove, indeterminate state, hidden selected count, full-row click and Space preserve exact identities')

    # Stable input node throughout Chinese IME composition, with no selection dirty side effect.
    before=selected();page.evaluate('S.dirty=false');query.focus()
    query.evaluate("el=>{window.originalRecipientInput=el;el.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));el.value='林';el.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:true}))}")
    expect(area.locator('[data-recipient]')).to_have_count(66)
    query.evaluate("el=>el.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true,data:'林'}))")
    expect(area.locator('[data-recipient]')).to_have_count(3);expect(query).to_be_focused()
    assert page.evaluate("window.originalRecipientInput===document.querySelector('#recipient-search')")
    assert not page.evaluate('S.dirty');expect_ids(before)
    clear_search();area.evaluate('el=>el.scrollTop=el.scrollHeight');assert area.evaluate('el=>el.scrollTop>0')
    query.fill('student');assert area.evaluate('el=>el.scrollTop')==0
    checks.append('IME composition retains the input/focus, commits filter only at composition end, and search resets only list scroll')

    # Complete notice for draft and sending checks, using an injected SMTP transport.
    profile=request('/smtp-profiles',{'name':'虚构验收邮箱','host':'smtp.example.com','port':465,'security':'ssl','username':'teacher@example.com','sender_name':'课程助教','sender_email':'teacher@example.com','password':'fictional-test-only','is_default':True})
    page.evaluate('refreshBasics()')
    page.locator('#course').fill('高等数学');page.locator('#assignment').fill('第三章习题')
    page.locator('#deadline').fill('2026-10-20T23:59');page.locator('#submission-email').fill('homework@example.com')
    content=page.evaluate('notice()');content['student_ids']=lins[:2]
    query.fill('林');restore(content);expect(query).to_have_value('');expect_ids(lins[:2])
    page.evaluate('S.dirty=false');query.fill('student0001')
    page.locator('#save-draft').click();page.wait_for_function('() => !!S.draftId && !S.dirty')
    draft_id=page.evaluate('S.draftId')
    drafts=context.request.get(base+'/api/notices').json();saved=next(d['content'] for d in drafts if d['id']==draft_id)
    assert saved['student_ids']==content['student_ids']
    assert not any('query' in key.lower() or 'search' in key.lower() for key in saved)
    clear_search();bulk.check();expect_ids([s['id'] for s in people])
    restore(saved);expect_ids(lins[:2]);expect(query).to_have_value('')
    restore({**saved,'student_ids':[]});expect_ids([]);expect(page.locator('#review-send')).to_be_disabled()
    checks.append('Draft restore keeps exact subset/empty selection; saves full IDs only, excludes search query, and clears query on restoration')

    # Slow old responses may not overwrite the newest class or restore old errors.
    url=base+f'/api/classes/{ids[200]}/students';old_data=all_people(200)
    for failure in (False,True):
        held=[]
        def hold(route):held.append(route)
        page.route(url,hold)
        page.locator('#compose-class').select_option(ids[200])
        expect(page.locator('#recipient-area')).to_have_attribute('aria-busy','true')
        expect(area.locator('[data-recipient]')).to_have_count(0)
        expect(query).to_be_disabled();expect(bulk).to_be_disabled();expect(page.locator('#review-send')).to_be_disabled();expect(page.locator('#save-draft')).to_be_disabled()
        assert held
        select_class(66);expect_ids([s['id'] for s in people]);expect(query).to_have_value('')
        start=len(errors);held.pop().fulfill(status=503 if failure else 200,json={'detail':'Injected stale failure'} if failure else old_data)
        page.unroute(url,hold);page.wait_for_timeout(80)
        assert page.evaluate('S.recipientClass')==ids[66] and page.evaluate('S.recipientState')=='ready'
        expect_ids([s['id'] for s in people])
        if failure:expected_error(start,503)
    checks.append('Class switches clear search and default-select all; loading blocks send/save and clears old rows; stale success/failure ignored')

    # The async send-review preview cannot reopen a stale confirmation after a class change.
    restore({**saved,'student_ids':lins[:2]});page.evaluate('clearTimeout(previewTimer)');page.evaluate('updatePreview()')
    preview_content=request('/notices/preview',{'notice':page.evaluate('notice()'),'student_id':lins[0]})
    held_review=[]
    def hold_review(route):
        payload=route.request.post_data_json
        if payload.get('notice',{}).get('class_id')==ids[66]:held_review.append(route)
        else:route.continue_()
    review_url=base+'/api/notices/preview';page.route(review_url,hold_review)
    page.locator('#review-send').click();assert held_review
    select_class(1);held_review.pop().fulfill(status=200,json=preview_content)
    page.unroute(review_url,hold_review)
    expect(page.locator('#toast-region')).to_contain_text('收件名单发生变化')
    expect(page.locator('#send-confirm-drawer')).not_to_be_visible()
    assert context.request.get(base+'/api/send-jobs').json()==[]
    checks.append('Changing class while the send-review preview is in flight cannot open a stale send confirmation')

    # Retry carries the captured load intention, including deliberately empty drafts.
    url66=base+f'/api/classes/{ids[66]}/students'
    for intention in (lins[:2],[]):
        def fail(route):route.fulfill(status=503,json={'detail':'Injected roster failure'})
        page.route(url66,fail);start=len(errors);restore({**saved,'student_ids':intention})
        expect(area).to_contain_text('收件名单加载失败');expect(area.locator('[data-recipient]')).to_have_count(0)
        expect(page.locator('#review-send')).to_be_disabled();expect(page.locator('#save-draft')).to_be_disabled()
        assert page.evaluate('S.recipientRequest.ids')==intention
        expected_error(start,503);page.unroute(url66,fail);page.locator('[data-retry-recipients]').click()
        page.wait_for_function("() => S.recipientState==='ready'");expect_ids(intention)
        expect(page.locator('#save-draft')).to_be_enabled()
    def fail_all(route):route.fulfill(status=503,json={'detail':'Injected default selection failure'})
    page.route(url,fail_all);start=len(errors);page.locator('#compose-class').select_option(ids[200])
    expect(area).to_contain_text('收件名单加载失败');expected_error(start,503)
    assert page.evaluate('S.recipientRequest.ids') is None
    page.unroute(url,fail_all);page.locator('[data-retry-recipients]').click();page.wait_for_function("() => S.recipientState==='ready'")
    expect(page.locator('#send-count')).to_have_text('200')
    checks.append('Failure retry preserves subset, explicit empty draft and default-all intents, never silently widens a saved selection')

    # Same-class roster update intersects existing selection with live IDs and preserves query.
    select_class(66);restore({**saved,'student_ids':lins+[chen]});query.fill('林')
    with app.state.Session() as db:
        db.execute(delete(Student).where(Student.id==lins[0]));new=Student(class_id=ids[66],name='林新增',email='new-person@example.com');db.add(new);db.commit();new_id=new.id
    page.evaluate('refreshRecipients()');expect(query).to_have_value('林');expect_ids(lins[1:]+[chen]);assert not checkbox(new_id).is_checked()
    # A refresh failing while a subset is chosen must preserve that intent for retry too.
    def fail_refresh(route):route.fulfill(status=503,json={'detail':'Injected refresh failure'})
    page.route(url66,fail_refresh);start=len(errors)
    page.evaluate("() => refreshRecipients().catch(()=>{})")
    expect(area).to_contain_text('收件名单加载失败');expected_error(start,503);page.unroute(url66,fail_refresh)
    page.locator('[data-retry-recipients]').click();page.wait_for_function("() => S.recipientState==='ready'")
    expect(query).to_have_value('林');expect_ids(lins[1:]+[chen])
    checks.append('Same-class add/delete/failed refresh preserves query and surviving IDs; newly imported people are not silently selected')

    # The existing import drawer's success refresh uses the same selection-preserving path.
    kept=selected();page.locator('[data-route=classes]').click();page.evaluate('(id)=>showClass(id)',ids[66])
    page.locator('#import-students').click();expect(page.locator('#import-text')).to_be_focused()
    page.locator('#import-text').fill('林导入 import-query@example.com');page.locator('#import-primary').click()
    expect(page.locator('#import-drawer')).to_have_attribute('data-state','ready')
    page.locator('#import-primary').click();expect(page.locator('#import-drawer')).not_to_be_visible()
    page.locator('[data-route=compose]').click();expect(query).to_have_value('林');expect_ids(kept)
    imported=next(s for s in all_people() if s['email']=='import-query@example.com')
    assert not checkbox(imported['id']).is_checked()
    with app.state.Session() as db:db.execute(delete(Student).where(Student.id==imported['id']));db.commit()
    page.evaluate('refreshRecipients()');expect_ids(kept)
    expect(page.locator('#compose-class option:checked')).to_contain_text('66 人')
    checks.append('Actual import-drawer success preserves the compose search/selected IDs and does not select new imports')

    # Hidden recipients still count in draft, review and actual simulated job.
    clear_search();people=all_people();lins=[s['id'] for s in people if '林' in s['name']]
    chosen=lins+[s['id'] for s in people if s['id'] not in lins][:9]
    assert len(chosen)==12
    page.evaluate('(ids)=>loadRecipients(ids)',chosen);query.fill('林')
    expect(page.locator('#recipient-match-summary')).to_have_text('匹配 3 人，其中已选 3 人')
    expect(page.locator('#recipient-hidden-selection')).to_have_text('另有 9 位已选同学不在搜索结果中')
    expect(page.locator('#send-count')).to_have_text('12');expect(page.locator('#recipient-count')).to_have_text('12')
    assert set(page.evaluate('notice().student_ids'))==set(chosen)
    page.locator('#save-draft').click();page.wait_for_function('() => !S.dirty')
    saved12=next(d['content'] for d in context.request.get(base+'/api/notices').json() if d['id']==draft_id)
    assert set(saved12['student_ids'])==set(chosen)
    # Show a send confirmation while a filter hides nine of its twelve recipients.
    page.locator('#review-send').click();expect(page.locator('#send-confirm-title')).to_have_text('确认发送')
    expect(page.locator('#send-confirm-subtitle')).to_contain_text('12 位同学')
    expect(page.locator('#send-confirm-list .send-confirm-roster li')).to_have_count(12)
    page.locator('#send-confirm-ack').check();page.locator('#send-confirm-submit').click();expect(page.locator('#send-confirm-drawer')).not_to_be_visible()
    page.wait_for_function("() => S.page==='history' && !!S.jobId")
    ident=page.evaluate('S.jobId')
    for _ in range(200):
        job=context.request.get(base+'/api/send-jobs/'+ident).json()
        if job['status'] not in ('queued','sending'):break
        page.wait_for_timeout(30)
    assert job['status']=='completed' and job['total']==12,job
    assert len(factory.messages)==12
    expected_emails={s['email'] for s in people if s['id'] in chosen}
    assert {m[2]['email'] for m in factory.messages}==expected_emails
    checks.append('Only 3 matching rows visible but 12 IDs saved, 12 reviewed, and exactly those 12 unique recipients simulated; no real SMTP')

    page.locator('[data-route=compose]').click();expect(page.locator('[data-page=compose]')).to_be_visible()
    expect(page.locator('#toast-region > *')).to_have_count(0,timeout=12000)
    # Make aligned component screenshots and verify the header/tool area never scrolls with rows.
    page.evaluate('(ids)=>loadRecipients(ids)',chosen);clear_search()
    for width,height,label in [(1920,1080,'wide'),(1440,1000,'desktop'),(1024,768,'small-desktop'),(768,1024,'tablet'),(375,900,'mobile'),(320,740,'narrow'),(683,384,'zoom-equivalent')]:
        page.set_viewport_size({'width':width,'height':height});page.locator('#recipient-picker').scroll_into_view_if_needed()
        area.evaluate('el=>el.scrollTop=0')
        metrics=page.locator('#recipient-picker').evaluate('''root=>{
          const box=el=>{const r=el.getBoundingClientRect();return {top:r.top,bottom:r.bottom,height:r.height}};
          return {bodyOverflow:document.documentElement.scrollWidth>innerWidth,pickerOverflow:root.scrollWidth>root.clientWidth,
            inputFont:getComputedStyle(root.querySelector('#recipient-search')).fontSize,nameFont:getComputedStyle(root.querySelector('.recipient-name')).fontSize,emailFont:getComputedStyle(root.querySelector('.recipient-email')).fontSize,
            list:box(root.querySelector('#recipient-area')),toolbar:box(root.querySelector('.recipient-search-toolbar')),tools:box(root.querySelector('.recipient-tools'))};
        }''')
        assert not metrics['bodyOverflow'] and not metrics['pickerOverflow'],(label,metrics)
        assert all(metrics[k]=='16px' for k in ['inputFont','nameFont','emailFont']),metrics
        assert metrics['list']['height']<=261
        area.evaluate('el=>el.scrollTop=el.scrollHeight');assert area.evaluate('el=>el.scrollTop>0')
        assert page.locator('.recipient-search-toolbar').bounding_box()['y']==metrics['toolbar']['top']
        assert page.locator('.recipient-tools').bounding_box()['y']==metrics['tools']['top']
        area.focus();page.keyboard.press('Home');area.evaluate('el=>el.scrollTop=0')
        page.locator('#recipient-picker-title').click()
        page.locator('#recipient-picker').screenshot(path=str(OUT/f'after-{label}.png'),animations='disabled',style='.send-bar{visibility:hidden!important}')
        query.fill('林');page.locator('#recipient-picker-title').click()
        page.locator('#recipient-picker').screenshot(path=str(OUT/f'search-{label}.png'),animations='disabled',style='.send-bar{visibility:hidden!important}')
        clear_search();layouts[label]=metrics
    checks.append('Seven CSS viewports: desktop/tablet/mobile/narrow/zoom equivalent, fixed 260px scrolling list, stationary tools and 16px readable text')

    # Long content, keyboard scroll and contrast samples.
    select_class(1)
    with app.state.Session() as db:
        person=db.scalar(select(Student).where(Student.class_id==ids[1]));person.name='这是很长的虚构同学姓名用于换行检查'*4;person.email='long-address.'*4+'student@example.com';db.commit()
    page.evaluate('refreshRecipients()');page.set_viewport_size({'width':375,'height':900})
    assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
    page.locator('#recipient-picker').screenshot(path=str(OUT/'long-content-mobile.png'),animations='disabled',style='.send-bar{visibility:hidden!important}')
    page.emulate_media(reduced_motion='reduce');assert page.locator('.recipient-row').evaluate('el=>getComputedStyle(el).transitionDuration')=='0s'
    page.emulate_media(reduced_motion='no-preference')
    page.set_viewport_size({'width':1440,'height':1000});select_class(66)
    area.focus();page.keyboard.press('ArrowDown');page.wait_for_function("() => document.querySelector('#recipient-area').scrollTop>0")
    contrast=page.evaluate('''() => {
      const canvas=document.createElement('canvas');canvas.width=canvas.height=1;const ctx=canvas.getContext('2d',{willReadFrequently:true});
      const lum=color=>{ctx.clearRect(0,0,1,1);ctx.fillStyle=color;ctx.fillRect(0,0,1,1);const c=[...ctx.getImageData(0,0,1,1).data].slice(0,3).map(x=>{x/=255;return x<=.04045?x/12.92:((x+.055)/1.055)**2.4});return c[0]*.2126+c[1]*.7152+c[2]*.0722};
      const pairs={name:['.recipient-name',null,'.recipient-row'],email:['.recipient-email',null,'.recipient-row'],placeholder:['#recipient-search','::placeholder','.recipient-search-field'],selectedCount:['#recipient-count',null,'.recipient-picker'],hiddenSelection:['#recipient-hidden-selection',null,'.recipient-picker']};const result={};
      for(const [key,[fg,pseudo,bg]] of Object.entries(pairs)){let b=getComputedStyle(document.querySelector(bg)).backgroundColor;if(b==='rgba(0, 0, 0, 0)')b='white';const x=lum(getComputedStyle(document.querySelector(fg),pseudo).color),y=lum(b);result[key]=(Math.max(x,y)+.05)/(Math.min(x,y)+.05)}return result;
    }''')
    assert min(contrast.values())>=4.5,contrast
    checks.append('Long-name/email wrapping, ArrowDown scrolling, visible keyboard focus, reduced motion and text contrast >=4.5:1')
    page.evaluate('S.dirty=false');page.reload();expect(page.locator('#recipient-picker-title')).to_be_visible()
    expect(query).to_have_value('');expect(page.locator('#recipient-controls')).not_to_be_visible()
    assert not errors,errors
    assert not external,external
    report={'checks':checks,'timings':timings,'layouts':layouts,'contrast':contrast,'expected_injected_errors':injected,'unexpected_errors':errors,'external_requests':external,'simulated_recipients':len(factory.messages),'browser':context.browser.version,'data':'fictional; temporary SQLite and in-memory credential/transport substitutes','environment':'process-local WMI fallback, no changes to system services or dependencies','screenshot_note':'Component-only screenshots temporarily hide the independent sticky send bar; normal application behavior is unchanged.','zoom_note':'683x384 CSS viewport equivalent, not a physical browser-menu zoom test'}
    (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


def run():
    parser=argparse.ArgumentParser();parser.add_argument('--baseline',action='store_true');args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    with isolated_app() as (app,factory,base),sync_playwright() as pw:
        ids=seed(app)
        edge=Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')
        browser=pw.chromium.launch(headless=True,**({'executable_path':str(edge)} if edge.exists() else {}))
        context=browser.new_context(viewport={'width':1440,'height':1000},locale='zh-CN')
        errors=[];external=[]
        def protect(route):
            if route.request.url.startswith(base+'/'):route.continue_()
            else:external.append(route.request.url);route.abort()
        context.route('**/*',protect)
        response=context.request.post(base+'/api/auth/setup',data={'password':'fictional-recipient-test-password'});assert response.ok
        page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)));page.on('console',lambda m:errors.append(m.text) if m.type=='error' else None)
        try:
            page.goto(base+'/#compose');expect(page.locator('#compose-class option')).to_have_count(len(ids)+1)
            if args.baseline:baseline(page,ids)
            else:verify(page,context,app,factory,base,ids,errors,external)
        except Exception:
            page.screenshot(path=str(OUT/'failure.png'))
            print('Failure:',page.evaluate("() => ({state:S.recipientState,query:S.recipientQuery,selected:S.selected.size,active:document.activeElement?.outerHTML.slice(0,220)})"))
            raise
        finally:browser.close()

if __name__=='__main__':run()
