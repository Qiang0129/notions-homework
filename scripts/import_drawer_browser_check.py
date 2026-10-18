"""Two-step import drawer acceptance. Temporary data only; never sends SMTP mail."""
from __future__ import annotations
import io
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT/'scripts'))
from playwright.sync_api import sync_playwright, expect
from openpyxl import Workbook
from app.models import Classroom, Student
from roster_browser_check import isolated_app
OUT = ROOT/'output'/'playwright'/'import-drawer'


def verify(page, context, app, factory, base, classes, errors, external):
    primary = page.locator('#import-primary')
    drawer = page.locator('#import-drawer')
    checks, layouts, expected_errors = [], {}, []
    target, other = classes
    preview_url = base+f'/api/classes/{target}/import/preview'
    confirm_url = base+f'/api/classes/{target}/import/confirm'
    requests = []
    page.on('request', lambda r: requests.append((r.method, r.url)) if '/import/' in r.url else None)
    def open_drawer():
        if page.locator('#navigation').is_visible() and page.viewport_size['width']<992:
            page.keyboard.press('Escape')
        page.locator('#import-students').click()
        expect(drawer).to_have_class(__import__('re').compile(r'\bshow\b'))
        expect(page.locator('#import-text')).to_be_focused()
        expect(primary).to_be_disabled()
    def discard():
        page.locator('#import-close').click()
        if page.locator('#import-discard').is_visible(): page.locator('#import-discard-confirm').click()
        expect(drawer).not_to_be_visible()
        expect(page.locator('#import-students')).to_be_focused()
    def set_text(text):
        if len(text) > 50000:
            page.locator('#import-text').evaluate("(el,text)=>{el.value=text;el.dispatchEvent(new Event('input',{bubbles:true}))}",text)
        else: page.locator('#import-text').fill(text)
    def preview(text):
        set_text(text); primary.click()
        expect(drawer).to_have_attribute('data-state','ready')
        expect(drawer).to_have_attribute('data-step','2')
    def commit():
        primary.click(); expect(drawer).not_to_be_visible()
    def students(ident=target): return context.request.get(base+f'/api/classes/{ident}/students').json()
    def record_expected(start, code):
        captured = errors[start:]
        assert all(str(code) in e for e in captured), captured
        expected_errors.extend(captured); del errors[start:]
    def upload(name, data):
        page.locator('#import-tab-file').click()
        page.locator('#import-file').set_input_files({'name':name,'mimeType':'application/octet-stream','buffer':data})
    def page_response_fixture(text):
        csrf=page.evaluate('S.csrf')
        response=context.request.post(preview_url, multipart={'text':text},headers={'X-CSRF-Token':csrf})
        assert response.ok,response.text()
        return response.json()

    page.goto(base+'/#classes'); page.evaluate('(id)=>showClass(id)',target)
    page.wait_for_function("() => S.rosterState === 'ready'")
    # Empty state, two-step hierarchy and independent input modes.
    open_drawer()
    expect(page.locator('#import-file-panel')).not_to_be_visible()
    expect(page.locator('#import-review-step')).not_to_be_visible()
    expect(page.locator('#dialog')).not_to_be_visible()
    expect(page.locator('#import-target-class')).to_have_text('周三下午班')
    assert page.locator('#import-text').evaluate('e=>getComputedStyle(e).fontSize')=='16px'
    page.locator('#import-tab-paste').focus();page.keyboard.press('ArrowRight')
    expect(page.locator('#import-tab-file')).to_be_focused()
    expect(page.locator('#import-file-panel')).to_be_visible()
    page.keyboard.press('ArrowLeft');expect(page.locator('#import-paste-panel')).to_be_visible()
    page.locator('#import-text').fill('粘贴同学 paste-only@example.com')
    upload('ignored.csv','姓名,邮箱\n文件同学,file-only@example.com'.encode())
    expect(page.locator('#import-file-name')).to_have_text('ignored.csv')
    page.locator('#import-tab-paste').click();expect(page.locator('#import-text')).to_have_value('粘贴同学 paste-only@example.com')
    primary.click();expect(drawer).to_have_attribute('data-step','2')
    expect(page.locator('#import-results')).to_contain_text('paste-only@example.com')
    expect(page.locator('#import-results')).not_to_contain_text('file-only@example.com')
    commit(); assert any(s['email']=='paste-only@example.com' for s in students())
    assert all(s['email']!='file-only@example.com' for s in students())
    checks.append('Only active source submitted, keyboard tabs, preserved mode inputs, no shared modal')

    # CSV with unsupported first-row names triggers explicit mapping. XLSX uses real bytes.
    open_drawer();upload('columns.csv','A,B\nmapped@example.com,映射同学'.encode())
    primary.click();expect(drawer).to_have_attribute('data-step','2')
    assert page.locator('#import-mapping').evaluate('e=>e.open')
    expect(primary).to_be_disabled()
    page.locator('#import-name-column').select_option('1');page.locator('#import-email-column').select_option('0');page.locator('#import-header').check()
    expect(primary).to_have_text('重新检查');primary.click()
    expect(drawer).to_have_attribute('data-state','ready');expect(page.locator('#import-summary')).to_contain_text('有效 1')
    commit();assert any(s['email']=='mapped@example.com' and s['name']=='映射同学' for s in students())
    wb=Workbook();wb.active.append(['姓名','邮箱']);wb.active.append(['表格同学','xlsx@example.com']);buf=io.BytesIO();wb.save(buf)
    open_drawer();upload('名单.xlsx',buf.getvalue());primary.click()
    expect(page.locator('#import-results')).to_contain_text('xlsx@example.com');commit()
    assert any(s['email']=='xlsx@example.com' for s in students())
    open_drawer();upload('名单.csv','姓名,邮箱\n编码同学,encoding@example.com'.encode('gb18030'));primary.click()
    expect(page.locator('#import-results')).to_contain_text('编码同学');discard()
    checks.append('Real CSV/GB18030/XLSX inputs, manual column swap/header adjustment, recheck invalidates preview')

    # File removal, invalid format/size, corrupt workbook and text limit do not write records.
    open_drawer();upload('bad.txt',b'not a csv');expect(primary).to_be_disabled();expect(page.locator('#import-error')).to_contain_text('只支持')
    page.locator('#import-file-remove').click();expect(primary).to_be_disabled()
    upload('empty.csv',b'');expect(primary).to_be_disabled()
    upload('oversize.csv',b'a'*(5*1024*1024+1));expect(primary).to_be_disabled();expect(page.locator('#import-error')).to_contain_text('5 MB')
    upload('bad.xlsx',b'broken workbook');start=len(errors);primary.click()
    expect(page.locator('#import-error')).to_contain_text('无法读取');expect(drawer).to_have_attribute('data-step','1');record_expected(start,422)
    page.locator('#import-tab-paste').click();set_text('\n'.join(f'同学{i} user{i}@example.com' for i in range(5002)))
    expect(primary).to_be_disabled();expect(page.locator('#import-footer-hint')).to_contain_text('5000');discard()
    checks.append('Empty/unsupported/oversize files, corrupt XLSX, line limit and removal remain editable without import')

    # Preview data after row 200 is visible. Paginate all 5000 input lines, not the first 200.
    lines=[f'同学{i:04d} person{i:04d}@example.com' for i in range(5000)]
    lines[250]='错误邮箱 invalid-address';lines[350]='已在班级 existing@example.com';lines[4999]='文件内姓名冲突 person0001@example.com'
    open_drawer();preview('\n'.join(lines))
    expect(page.locator('#import-summary')).to_contain_text('共 5000 行')
    expect(page.locator('#import-results tbody tr')).to_have_count(50)
    expect(page.locator('#import-preview-page')).to_have_text('1 / 100')
    seen=[]
    for n in range(100):
        seen.extend(page.locator('#import-results tbody tr').evaluate_all('rows=>rows.map(r=>Number(r.dataset.importLine))'))
        if n<99: page.locator('#import-preview-next').click()
    assert seen==list(range(1,5001)),len(seen)
    page.locator('[data-import-filter=problem]').click()
    shown=page.locator('#import-results tr[data-import-line]').evaluate_all('rows=>rows.map(r=>Number(r.dataset.importLine))')
    assert shown==[251,5000],shown
    page.locator('[data-import-filter=duplicate]').click();expect(page.locator('#import-results tr[data-import-line]')).to_have_attribute('data-import-line','351')
    discard();checks.append('5000 rows / 100 preview pages exact-once; problems and duplicates after row 200 accessible')

    # Default blocks problems; only explicit options allow valid-only and existing-name updates.
    open_drawer();preview('新增 good@example.com\n错误 invalid\n换个姓名 existing@example.com\n文件重名 good@example.com')
    expect(primary).to_be_disabled();assert not page.locator('#valid-only').is_checked();assert not page.locator('#overwrite-conflicts').is_checked()
    page.locator('#overwrite-conflicts').check();expect(primary).to_be_disabled()
    page.locator('#valid-only').check();expect(primary).to_be_enabled()
    page.locator('#import-back').click();assert 'good@example.com' in page.locator('#import-text').input_value()
    page.locator('#import-text').fill('新增 good@example.com\n错误 invalid\n换个姓名 existing@example.com\n文件重名 good@example.com\n第二位 good2@example.com')
    primary.click();expect(drawer).to_have_attribute('data-step','2');assert not page.locator('#valid-only').is_checked();assert not page.locator('#overwrite-conflicts').is_checked()
    page.locator('#valid-only').check();commit()
    assert next(s['name'] for s in students() if s['email']=='existing@example.com')=='已在班级'
    assert next(s['name'] for s in students() if s['email']=='good@example.com')=='新增'
    open_drawer();preview('更新姓名 existing@example.com')
    expect(primary).to_be_disabled();page.locator('#overwrite-conflicts').check();expect(primary).to_be_enabled();commit()
    assert next(s['name'] for s in students() if s['email']=='existing@example.com')=='更新姓名'
    open_drawer();preview('更新姓名 existing@example.com');expect(primary).to_be_disabled();expect(page.locator('#import-footer-hint')).to_contain_text('无需导入');discard()
    checks.append('Default blocking, valid-only opt-in, overwrite opt-in, file-internal conflict remains blocked, duplicates no-op')

    # Every close affordance routes to inline discard; opening is always clean.
    for method in ('close','cancel','escape','backdrop'):
        print('Close method:',method,flush=True)
        open_drawer();page.locator('#import-text').fill('未提交 pending@example.com')
        if method=='close':page.locator('#import-close').click()
        elif method=='cancel':page.locator('#import-cancel').click()
        elif method=='escape':page.keyboard.press('Escape')
        else:page.mouse.click(300,150)
        expect(page.locator('#import-discard')).to_be_visible();expect(page.locator('#dialog')).not_to_be_visible()
        expect(page.locator('#import-keep')).to_be_focused();page.locator('#import-keep').click()
        expect(page.locator('#import-text')).to_have_value('未提交 pending@example.com')
        discard()
    open_drawer();page.keyboard.press('Escape');expect(drawer).not_to_be_visible()
    assert not any(s['email']=='pending@example.com' for s in students())
    checks.append('X/cancel/Escape/backdrop use inline discard; keep retains input; close resets memory and focus')

    # Delayed responses after edits, mode switch or a new drawer session cannot restore stale previews.
    delayed=[]
    old_preview=page_response_fixture('旧请求 stale@example.com')
    def hold_preview(route):delayed.append(route)
    page.route(preview_url,hold_preview)
    for mutation in ('text','mode','reopen'):
        open_drawer();page.locator('#import-text').fill('旧请求 stale@example.com');primary.click()
        page.wait_for_function("() => document.querySelector('#import-drawer').dataset.state==='checking'")
        assert delayed
        if mutation=='text':page.locator('#import-text').fill('新内容 fresh@example.com')
        elif mutation=='mode':page.locator('#import-tab-file').click()
        else:discard();open_drawer()
        delayed.pop(0).fulfill(status=200,json=old_preview);page.wait_for_timeout(80)
        expect(drawer).to_have_attribute('data-step','1');expect(drawer).to_have_attribute('data-state','editing')
        discard()
    page.unroute(preview_url,hold_preview)
    checks.append('Aborted/stale preview responses ignored after text edits, source change and close/reopen')

    # Preview expiration retains input and exposes only recheck.
    open_drawer();preview('过期验收 expiry@example.com')
    def expire(route):route.fulfill(status=410,json={'detail':'预览过期'})
    page.route(confirm_url,expire);start=len(errors);primary.click()
    expect(page.locator('#import-error')).to_contain_text('预览已过期');expect(primary).to_have_text('重新检查');record_expected(start,410)
    page.unroute(confirm_url,expire);primary.click();expect(primary).to_have_text('确认导入');commit()
    assert any(s['email']=='expiry@example.com' for s in students())
    checks.append('Expired preview retains input and rechecks before a successful manual confirm')

    # Freeze target class and prevent concurrent posts/closing while commit is outstanding.
    open_drawer();preview('固定班级 pinned@example.com')
    held=[]
    def hold_confirm(route):held.append(route)
    page.route(confirm_url,hold_confirm);before=len([r for r in requests if r[1]==confirm_url])
    page.evaluate("() => {document.querySelector('#import-primary').click();document.querySelector('#import-primary').click()}")
    expect(drawer).to_have_attribute('data-state','committing');assert held
    assert len([r for r in requests if r[1]==confirm_url])==before+1
    expect(page.locator('#import-close')).to_be_disabled();expect(page.locator('#import-back')).to_be_disabled()
    expect(page.locator('#valid-only')).to_be_disabled();page.keyboard.press('Escape');expect(drawer).to_be_visible()
    page.mouse.click(300,150);expect(drawer).to_be_visible();expect(page.locator('#import-discard')).not_to_be_visible()
    page.evaluate('(id)=>S.managedClass=id',other)
    held.pop().continue_();page.unroute(confirm_url,hold_confirm);expect(drawer).not_to_be_visible()
    assert any(s['email']=='pinned@example.com' for s in students(target));assert not students(other)
    checks.append('Pinned target, single confirm request, edits/close/Escape/backdrop blocked until commit finishes')

    # A confirmed import followed by refresh failure cannot be imported a second time.
    open_drawer();preview('刷新失败 refresh@example.com')
    def fail_refresh(route):route.fulfill(status=503,json={'detail':'Injected refresh failure'})
    page.route(base+'/api/classes',fail_refresh);before=len([r for r in requests if r[1]==confirm_url]);start=len(errors);primary.click()
    expect(page.locator('#import-completed-title')).to_have_text('名单已导入')
    expect(page.locator('#import-error')).to_contain_text('刷新失败');expect(primary).to_have_text('重新刷新名单')
    assert any(s['email']=='refresh@example.com' for s in students());record_expected(start,503)
    page.unroute(base+'/api/classes',fail_refresh);primary.click();expect(drawer).not_to_be_visible()
    assert len([r for r in requests if r[1]==confirm_url])==before+1
    # Simulate a committed DB transaction whose response gets lost.
    open_drawer();preview('回包丢失 uncertain@example.com')
    def lose_response(route):
        response=route.fetch();assert response.ok
        route.fulfill(status=503,json={'detail':'Injected response lost after commit'})
    page.route(confirm_url,lose_response);start=len(errors);before=len([r for r in requests if r[1]==confirm_url]);primary.click()
    expect(page.locator('#import-completed-title')).to_have_text('导入结果需要核对');record_expected(start,503)
    page.unroute(confirm_url,lose_response);primary.click();expect(drawer).not_to_be_visible()
    assert len([r for r in requests if r[1]==confirm_url])==before+1
    assert any(s['email']=='uncertain@example.com' for s in students())
    checks.append('Successful commit + failed refresh and lost response both permit GET refresh only, never duplicate POST')

    # Complete the small import before the drawer's opening transition has finished.
    page.evaluate('''() => new Promise(resolve => {
      const root=document.querySelector('#import-drawer');
      root.addEventListener('hidden.bs.offcanvas',resolve,{once:true});
      document.querySelector('#import-students').click();
      const input=document.querySelector('#import-text');input.value='快速确认 quick@example.com';input.dispatchEvent(new Event('input',{bubbles:true}));
      const observer=new MutationObserver(()=>{
        if(root.dataset.state==='ready'){observer.disconnect();document.querySelector('#import-primary').click()}
      });observer.observe(root,{attributes:true,attributeFilter:['data-state']});
      document.querySelector('#import-primary').click();
    })''')
    expect(drawer).not_to_be_visible();assert any(s['email']=='quick@example.com' for s in students())
    checks.append('Fast preview/confirm safely closes only after the offcanvas opening lifecycle completes')

    # Representative step screenshots and root overlay geometry.
    expect(page.locator('#toast-region > *')).to_have_count(0,timeout=12000)
    from sqlalchemy import select
    with app.state.Session() as db:
        names=['林知远','周书瑶','陈安宁','叶初夏','许明轩','沈沐言','苏景行','唐予彤','林书宁','陈知夏','周安然','许景明']
        for index,person in enumerate(db.scalars(select(Student).where(Student.class_id==target))):person.name=names[index%len(names)]
        db.commit()
    page.evaluate('(id)=>showClass(id)',target)
    sample='姓名 邮箱\n林知远 lin@example.com\n周书瑶 zhou@example.com\n陈安宁 chen@example.com\n叶初夏 ye@example.com'
    for width,height in [(1440,1000),(1366,768),(768,1024),(375,812),(320,740),(1366,560),(683,384)]:
        page.set_viewport_size({'width':width,'height':height});page.evaluate("scrollTo({top:0,behavior:'instant'})")
        open_drawer();page.locator('#import-text').fill(sample)
        result=page.evaluate('''() => {
          const rect=id=>{const r=document.getElementById(id).getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,bottom:r.bottom,right:r.right}};
          return {drawer:rect('import-drawer'),body:rect('import-drawer-body'),footer:document.querySelector('.import-drawer-footer').getBoundingClientRect().bottom,
            backgroundOverflow:document.documentElement.scrollWidth>innerWidth,drawerOverflow:document.getElementById('import-drawer').scrollWidth>document.getElementById('import-drawer').clientWidth,
            inputFont:getComputedStyle(document.getElementById('import-text')).fontSize,
            backdropZ:Number(getComputedStyle(document.querySelector('.offcanvas-backdrop')).zIndex),navigationZ:Number(getComputedStyle(document.getElementById('navigation')).zIndex)};
        }''')
        assert result['drawer']['width']==(720 if width>=768 else width),result
        assert abs(result['drawer']['right']-width)<1 and result['drawer']['height']==height,result
        assert result['footer']<=height+1 and result['body']['height']>50,result
        assert not result['backgroundOverflow'] and not result['drawerOverflow'],result
        assert result['inputFont']=='16px' and result['backdropZ']>result['navigationZ'],result
        page.locator('#import-drawer-title').click()
        page.screenshot(path=str(OUT/f'step1-{width}x{height}.png'))
        primary.click();expect(drawer).to_have_attribute('data-step','2')
        page.locator('#import-drawer-title').click()
        page.screenshot(path=str(OUT/f'step2-{width}x{height}.png'))
        assert not page.locator('#import-drawer').evaluate('e=>e.scrollWidth>e.clientWidth')
        primary.focus();page.keyboard.press('Tab');assert page.evaluate("()=>!!document.activeElement.closest('#import-drawer')")
        page.keyboard.press('Shift+Tab');assert page.evaluate("()=>!!document.activeElement.closest('#import-drawer')")
        discard();layouts[f'{width}x{height}']=result
    page.set_viewport_size({'width':375,'height':812})
    page.evaluate("location.hash='compose'");expect(page.locator('[data-page=compose]')).to_be_visible()
    page.locator('[aria-label="打开导航"]').click();expect(page.locator('#navigation')).to_be_visible()
    page.locator('#navigation [data-route=classes]').click();expect(page.locator('#navigation')).not_to_be_visible()
    open_drawer();assert page.locator('.offcanvas-backdrop').count()==1;discard()
    page.emulate_media(reduced_motion='reduce');open_drawer()
    assert drawer.evaluate('e=>getComputedStyle(e).transitionDuration')=='0s';discard()
    checks.append('720px/full-width right drawer, fixed header/footer, one scroll body, root layering, mobile nav, focus trap and reduced motion')
    assert not factory.messages
    assert not errors,errors
    assert not external,external
    report={'checks':checks,'layouts':layouts,'expected_injected_http_errors':expected_errors,'unexpected_errors':errors,'external_requests':external,'smtp_messages':len(factory.messages),'browser':context.browser.version,'data':'fictional temporary database only','fixture_note':'Large (over 50KB) textarea fixtures use value assignment plus a real input event; ordinary entries use browser fill.','note':'683x384 simulates the CSS viewport of 200% desktop browser zoom, not a physical phone or browser-menu test'}
    (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


def run():
    OUT.mkdir(parents=True,exist_ok=True)
    with isolated_app() as (app,factory,base),sync_playwright() as pw:
        with app.state.Session() as db:
            a=Classroom(name='周三下午班');b=Classroom(name='周五上午班');db.add_all([a,b]);db.flush()
            classes=(a.id,b.id);db.add(Student(class_id=a.id,name='已在班级',email='existing@example.com'));db.commit()
        edge=Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')
        browser=pw.chromium.launch(headless=True,**({'executable_path':str(edge)} if edge.exists() else {}))
        context=browser.new_context(viewport={'width':1366,'height':768},locale='zh-CN')
        errors,external=[],[]
        def protect(route):
            if route.request.url.startswith(base+'/'):route.continue_()
            else:external.append(route.request.url);route.abort()
        context.route('**/*',protect)
        response=context.request.post(base+'/api/auth/setup',data={'password':'fictional-drawer-test-password'})
        assert response.status==200
        page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)));page.on('console',lambda m:errors.append(m.text) if m.type=='error' else None)
        try:verify(page,context,app,factory,base,classes,errors,external)
        except Exception:
            page.screenshot(path=str(OUT/'failure.png'))
            print('Failure state:',page.evaluate("()=>({state:document.querySelector('#import-drawer').dataset.state,step:document.querySelector('#import-drawer').dataset.step,active:document.activeElement?.outerHTML.slice(0,250),error:document.querySelector('#import-error').textContent,footer:document.querySelector('#import-footer-hint').textContent})"))
            raise
        finally:browser.close()

if __name__=='__main__':run()
