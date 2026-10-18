"""Roster UI acceptance with fictional records, a temporary DB and no external SMTP.
Run --baseline before changing the UI to preserve comparable screenshots.
"""
from __future__ import annotations
import argparse
import json
import socket
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import uvicorn
from playwright.sync_api import sync_playwright, expect
from app.config import Settings
from app.main import create_app
from app.models import Classroom, Student
from conftest import FakeFactory, MemoryVault

OUT = ROOT / 'output' / 'playwright' / 'roster'

@contextmanager
def isolated_app():
    with tempfile.TemporaryDirectory(prefix='classnote-roster-') as temp:
        factory = FakeFactory()
        app = create_app(Settings(Path(temp), testing=True, worker_interval=.01, send_interval_override=0), MemoryVault(), factory)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, access_log=False, log_level='warning'))
        thread = threading.Thread(target=server.run, daemon=True); thread.start()
        try:
            for _ in range(200):
                if server.started: break
                time.sleep(.025)
            assert server.started, 'Isolated server did not start'
            yield app, factory, f'http://127.0.0.1:{port}'
        finally:
            server.should_exit = True; thread.join(10)
            assert not thread.is_alive(), 'Isolated server did not stop'


def seed_rosters(app):
    ids = {}
    with app.state.Session() as db:
        for count in (0, 1, 20, 21, 66, 200, 5000):
            name = '周三下午班' if count == 66 else '周五上午班' if count == 200 else f'验收班 · {count} 人'
            classroom = Classroom(name=name); db.add(classroom); db.flush(); ids[count] = classroom.id
            for n in range(count):
                surname = '陈林周许沈苏唐叶'[n % 8]; given = '知远安宁初夏书瑶明轩予彤景行沐言'[(n//8)%8*2:((n//8)%8+1)*2]
                name = surname + given if count == 66 and n < 64 else f'同学{n+1:04d}'
                db.add(Student(class_id=classroom.id, name=name, email=f'student{n+1:04d}@example.com'))
        db.commit()
    return ids


def select_class(page, ident):
    page.evaluate('(id) => showClass(id)', ident)
    page.wait_for_function("() => (typeof S.rosterState === 'undefined' || S.rosterState !== 'loading')")


def baseline(page, ids):
    for width, height, label in [(1366, 768, 'desktop'), (375, 812, 'mobile')]:
        page.set_viewport_size({'width': width, 'height': height})
        page.evaluate("scrollTo({top:0,behavior:'instant'})")
        page.screenshot(path=str(OUT / f'before-{label}.png'))
    print('Baseline screenshots captured using 66 fictional students.')


def verify(page, context, app, factory, base, ids, errors, external):
    checks, metrics, pagination = [], {}, {}
    def ui_class(count):
        page.locator(f'[data-manage-class="{ids[count]}"]').click()
        page.wait_for_function("() => (S.rosterState === 'ready')")
    def last_page():
        page.locator('#roster-pages [data-roster-page]').last.click()
    def assert_page(number):
        assert page.evaluate('S.rosterPage') == number
    def save_dialog():
        page.locator('#dialog-confirm').click()
        expect(page.locator('#dialog')).not_to_be_visible()
    def request(path, data, method='post'):
        csrf = page.evaluate('S.csrf')
        response = getattr(context.request, method)(base + '/api' + path, data=data, headers={'X-CSRF-Token': csrf})
        assert response.ok, response.text()
        return response.json()

    # Exercise the actual renderer on every page, including the maximum 5000-row roster.
    for count in (0, 1, 20, 21, 66, 200, 5000):
        ui_class(count)
        expected = context.request.get(base + f'/api/classes/{ids[count]}/students').json()
        for size in (20, 50, 100):
            page.locator('#roster-page-size').select_option(str(size))
            assert_page(1)
            result = page.evaluate('''() => {
              const total = Math.max(1, Math.ceil(S.managedStudents.length / S.rosterPageSize));
              const ids = []; let maxRows = 0;
              for (let p = 1; p <= total; p++) {
                S.rosterPage = p; renderStudents();
                const rows = [...document.querySelectorAll('#student-list tr[data-student-id]')];
                maxRows = Math.max(maxRows, rows.length);
                ids.push(...rows.map(row => row.dataset.studentId));
              }
              return {ids, maxRows, pages: total};
            }''')
            assert result['ids'] == [r['id'] for r in expected], (count, size)
            assert len(set(result['ids'])) == count and result['maxRows'] <= size
            pagination[f'{count}/{size}'] = {'pages': result['pages'], 'max_dom_rows': result['maxRows']}
        if count == 0:
            expect(page.locator('#student-list')).to_contain_text('把你的同学加入名单')
            assert page.locator('#roster-pages button:not(:disabled)').count() == 0
    page.locator('#roster-page-size').select_option('20')
    checks.append('All records exactly once across every page, 0/1/20/21/66/200/5000 rows and 20/50/100 page sizes')

    ui_class(66)
    page.locator('#roster-pages [data-roster-step=next]').click(); assert_page(2)
    expect(page.locator('#roster-range')).to_have_text('第 21–40 位，共 66 位')
    assert page.locator('#roster-pages [data-roster-step=next]').evaluate('el => el === document.activeElement')
    page.locator('#student-search').fill('student0066@example.com')
    assert_page(1); expect(page.locator('#student-list tbody tr')).to_have_count(1)
    expect(page.locator('#student-search-status')).to_have_text('找到 1 / 66 人')
    page.locator('#student-search').fill('no-such-person')
    expect(page.locator('#student-list')).to_contain_text('没有找到匹配的同学')
    page.locator('#clear-student-search').click()
    expect(page.locator('#student-search')).to_be_focused()
    last_page(); assert_page(4)
    page.locator('#roster-page-size').select_option('50'); assert_page(1)
    ui_class(200); assert_page(1)
    assert page.locator('#roster-page-size').input_value() == '50'
    page.locator('#roster-page-size').select_option('20')
    checks.append('Real pagination controls, full-roster search, clear, focus restore and reset rules')

    # Keep page/search after edits, clamp after deleting the only row on the last page.
    ui_class(66)
    page.locator('#student-search').fill('@example.com')
    page.locator('#roster-pages [data-roster-page="3"]').click(); assert_page(3)
    edited_id=page.locator('#student-list [data-edit-student]').first.get_attribute('data-edit-student')
    page.locator('#student-list [data-edit-student]').first.click()
    page.locator('#student-email').fill('updated-roster@example.com'); save_dialog()
    assert_page(3); expect(page.locator('#student-search')).to_have_value('@example.com')
    expect(page.locator(f'[data-edit-student="{edited_id}"]')).to_be_focused()
    ui_class(21); last_page(); assert_page(2)
    expect(page.locator('#student-list tbody tr')).to_have_count(1)
    # Confirm in the same turn as opening: the save can complete before Bootstrap's transition.
    page.evaluate("() => {window.fastModalClosed=false;document.querySelector('#dialog').addEventListener('hidden.bs.modal',()=>{window.fastModalClosed=true},{once:true});document.querySelector('#student-list [data-delete-student]').click();document.querySelector('#dialog-confirm').click()}")
    page.wait_for_function("() => window.fastModalClosed === true")
    expect(page.locator('#dialog')).not_to_be_visible()
    assert_page(1); expect(page.locator('#class-member-count')).to_have_text('20 人')
    ui_class(66); page.locator('#student-search').fill('student0066')
    page.locator('#add-student').click()
    page.locator('#student-name').fill('新增同学'); page.locator('#student-email').fill('new-person@example.com'); save_dialog()
    assert_page(1); expect(page.locator('#student-search')).to_have_value('')
    expect(page.locator('#class-member-count')).to_have_text('67 人')
    page.locator('#student-search').fill('new-person')
    page.locator('#import-students').click()
    page.locator('#import-text').fill('导入同学 imported-person@example.com')
    page.locator('#import-primary').click(); expect(page.locator('#import-summary')).to_contain_text('有效 1')
    page.locator('#import-primary').click(); expect(page.locator('#import-drawer')).not_to_be_visible(); assert_page(1)
    expect(page.locator('#student-search')).to_have_value('')
    expect(page.locator('#class-member-count')).to_have_text('68 人')
    checks.append('Edit preserves query/page; delete-last-row clamps; add/import reset and update counts; immediate confirmation closes the opening modal')

    # Hold a slow class request, switch again, then release stale results and stale errors.
    for stale_failure in (False, True):
        held = []
        url = base + f'/api/classes/{ids[1]}/students'
        old = context.request.get(url).json()
        def hold(route): held.append(route)
        page.route(url, hold)
        page.locator(f'[data-manage-class="{ids[1]}"]').click()
        page.wait_for_function("() => (S.rosterState === 'loading')")
        assert page.locator('#student-list tbody tr').count() == 0
        ui_class(200)
        before_errors = len(errors)
        assert held
        held[0].fulfill(status=503 if stale_failure else 200, json={'detail': 'Injected stale failure'} if stale_failure else old)
        page.unroute(url, hold); page.wait_for_timeout(100)
        assert page.evaluate('S.managedClass') == ids[200]
        expect(page.locator('#class-member-count')).to_have_text('200 人')
        assert page.evaluate('S.rosterState') == 'ready'
        if stale_failure:
            injected = errors[before_errors:]
            assert all('503' in e for e in injected), injected
            del errors[before_errors:]
    # Current request failure is recoverable and never renders an old class roster.
    url = base + f'/api/classes/{ids[1]}/students'
    def fail(route): route.fulfill(status=503, json={'detail': '验收注入：暂时不可用'})
    page.route(url, fail); before_errors = len(errors)
    page.locator(f'[data-manage-class="{ids[1]}"]').click()
    expect(page.locator('#student-list')).to_contain_text('名单加载失败')
    assert page.locator('#student-list tbody tr').count() == 0
    assert all('503' in e for e in errors[before_errors:]); del errors[before_errors:]
    page.unroute(url, fail)
    page.locator('[data-roster-retry]').click()
    expect(page.locator('#student-list tbody tr')).to_have_count(1)
    checks.append('Stale success/error ignored; no stale rows during loading/failure; retry succeeds (2 deliberate HTTP 503 responses)')

    # Restore the 66-row fixture for before/after screenshots and responsive metrics.
    from sqlalchemy import delete, select
    with app.state.Session() as db:
        db.execute(delete(Student).where(Student.class_id == ids[66], Student.email.in_(['new-person@example.com', 'imported-person@example.com'])))
        for n in range(22): db.add(Classroom(name=f'附加班级 {n+1:02d}'))
        db.commit()
    page.evaluate('refreshBasics()'); ui_class(66)
    expect(page.locator('#toast-region > *')).to_have_count(0,timeout=10000)
    for width, height in [(1920,1080),(1366,768),(1024,640),(768,1024),(375,812),(1366,560),(320,740)]:
        page.set_viewport_size({'width':width,'height':height}); page.evaluate("scrollTo({top:0,behavior:'instant'})")
        page.wait_for_timeout(80)
        result=page.evaluate('''() => {
          const box = el => {const r=el.getBoundingClientRect();return {top:r.top,bottom:r.bottom,height:r.height}};
          const list=document.querySelector('#student-list');
          return {bodyOverflow:document.documentElement.scrollWidth>innerWidth,
            documentHeight:document.documentElement.scrollHeight,viewportHeight:innerHeight,
            list:box(list),toolbar:box(document.querySelector('.roster-toolbar')),footer:box(document.querySelector('.roster-pagination')),
            inputFont:getComputedStyle(document.querySelector('#student-search')).fontSize,
            listOverflow:getComputedStyle(list).overflowY,sidebarScroll:document.querySelector('#class-list').scrollHeight>document.querySelector('#class-list').clientHeight};
        }''')
        assert not result['bodyOverflow'], (width,height,result)
        assert result['inputFont']=='16px', result
        bounded=width>=992 and height>=640
        if bounded:
            assert result['documentHeight']<=height+1 and result['list']['height']>=100, result
            assert result['footer']['bottom']<=height and result['toolbar']['top']>=0, result
            assert result['sidebarScroll'], 'Many classes must scroll independently'
            page.locator('#student-list').evaluate('el=>el.scrollTop=el.scrollHeight')
            assert page.locator('#student-list').evaluate('el=>el.scrollTop>0')
            assert page.locator('.roster-toolbar').bounding_box()['y']==result['toolbar']['top']
            assert abs(page.locator('#student-list th').first.bounding_box()['y']-result['list']['top'])<2
            page.locator('#student-list').evaluate('el=>el.scrollTop=0')
            page.locator('#student-list').focus(); page.keyboard.press('ArrowDown')
            page.wait_for_function("() => document.querySelector('#student-list').scrollTop > 0")
            page.locator('#student-list').evaluate('el=>el.scrollTop=0')
        else:
            assert result['listOverflow']=='visible',result
            expect(page.locator('#managed-class-select')).to_be_visible()
            expect(page.locator('#roster-top-pages')).to_be_visible()
            page.locator('#managed-class-select').select_option(ids[20]); page.wait_for_function("() => (S.rosterState === 'ready')")
            page.locator('#managed-class-select').select_option(ids[66]); page.wait_for_function("() => (S.rosterState === 'ready')")
            page.locator('#roster-top-pages [data-roster-step=next]').click(); assert_page(2)
            page.locator('#roster-pages [data-roster-step=prev]').click(); assert_page(1)
            assert page.locator('#roster-toolbar').bounding_box()['y']>=-1
            assert page.evaluate("() => !!document.activeElement.closest('#roster-top-pages')")
        page.evaluate("scrollTo({top:0,behavior:'instant'})")
        metrics[f'{width}x{height}']=result
        label='desktop' if (width,height)==(1366,768) else 'mobile' if width==375 else f'{width}x{height}'
        if width < 576:
            assert page.locator('.roster-email-mobile').first.evaluate('el => getComputedStyle(el).fontSize') == '16px'
        page.locator('#roster-page-title').click()
        page.screenshot(path=str(OUT/f'after-{label}.png'))
    checks.append('Desktop/short/tablet/mobile layouts, independent class and student scrolling, sticky headers and always-reachable pagination')

    page.set_viewport_size({'width':1366,'height':768})
    contrast=page.evaluate('''() => {
      const canvas=document.createElement('canvas');canvas.width=canvas.height=1;
      const ctx=canvas.getContext('2d',{willReadFrequently:true});
      const luminance=color=>{ctx.clearRect(0,0,1,1);ctx.fillStyle=color;ctx.fillRect(0,0,1,1);const rgb=[...ctx.getImageData(0,0,1,1).data].slice(0,3).map(c=>{c/=255;return c<=.04045?c/12.92:((c+.055)/1.055)**2.4});return rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722};
      const samples={title:['#roster-page-title',null,'.roster-page'],placeholder:['#student-search','::placeholder','.search-field'],email:['.roster-email-desktop.email-cell',null,'.roster-card'],muted:['#student-search-status',null,'.roster-card'],selectedClass:['.class-item.active',null,'.class-item.active'],currentPage:['#roster-pages [aria-current=page]',null,'#roster-pages [aria-current=page]'],primaryButton:['#add-class',null,'#add-class']};
      const result={};
      for(const [key,[selector,pseudo,bgSelector]] of Object.entries(samples)){
        const fg=getComputedStyle(document.querySelector(selector),pseudo).color;
        let bg=getComputedStyle(document.querySelector(bgSelector)).backgroundColor;
        if(bg==='rgba(0, 0, 0, 0)')bg='white';
        const a=luminance(fg),b=luminance(bg);result[key]=(Math.max(a,b)+.05)/(Math.min(a,b)+.05);
      }
      return result;
    }''')
    assert min(contrast.values())>=4.5,contrast
    checks.append('Roster text, placeholders, active states and primary button contrast at least 4.5:1')

    # Match the original seven-class fixture in the main before/after screenshots.
    with app.state.Session() as db:
        db.execute(delete(Classroom).where(Classroom.name.like('附加班级 %')));db.commit()
    page.evaluate('refreshBasics()');select_class(page,ids[66])
    for width,height,label in [(1366,768,'desktop'),(375,812,'mobile')]:
        page.set_viewport_size({'width':width,'height':height})
        page.evaluate("scrollTo({top:0,behavior:'instant'})")
        page.locator('#roster-page-title').click()
        page.screenshot(path=str(OUT/f'after-{label}.png'))

    # Long content and a 200%-zoom-equivalent CSS viewport; no CSS zoom hacks in the app.
    page.set_viewport_size({'width':375,'height':812}); select_class(page,ids[1])
    with app.state.Session() as db:
        person=db.scalar(select(Student).where(Student.class_id==ids[1]))
        person.name='很长的虚构同学姓名用于验证换行'*6
        person.email='long.address.'*4+'student@example.com';db.commit()
    select_class(page,ids[1])
    assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
    page.screenshot(path=str(OUT/'long-content-mobile.png'),full_page=True)
    page.locator('#student-list [data-edit-student]').click()
    expect(page.locator('#student-email')).to_be_visible()
    page.locator('#dialog [data-bs-dismiss=modal]').last.click(); expect(page.locator('#dialog')).not_to_be_visible()
    page.set_viewport_size({'width':1366,'height':768}); select_class(page,ids[66])
    page.emulate_media(reduced_motion='reduce')
    assert page.locator('.class-item').first.evaluate("el=>getComputedStyle(el).transitionDuration")=='0s'
    page.set_viewport_size({'width':683,'height':384})
    assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
    page.screenshot(path=str(OUT/'zoom-200-percent.png'))
    page.set_viewport_size({'width':1366,'height':768})
    page.emulate_media(reduced_motion='no-preference')
    checks.append('Long names/emails, modal accessibility, reduced motion and 200% browser-zoom-equivalent CSS viewport (683x384)')

    # Full recipient regression with one entire simulated 66-recipient job.
    profile=request('/smtp-profiles',{'name':'虚构验收邮箱','host':'smtp.example.com','port':465,'security':'ssl','username':'teacher@example.com','sender_name':'课程助教','sender_email':'teacher@example.com','password':'fictional-test-only','is_default':True})
    page.evaluate('refreshBasics()')
    page.locator('[data-route=compose]').click()
    assert not page.evaluate("document.body.classList.contains('roster-active')")
    assert page.locator('.app-footer').is_visible()
    page.locator('#compose-class').select_option(ids[66]); expect(page.locator('#send-count')).to_have_text('66')
    assert page.locator('#recipient-area [data-recipient]:checked').count()==66
    page.locator('#course').fill('名单分页验收');page.locator('#assignment').fill('虚构作业')
    page.locator('#deadline').fill('2026-10-20T23:59');page.locator('#submission-email').fill('homework@example.com')
    notice=page.evaluate('notice()')
    assert len(notice['student_ids'])==66
    preview=request('/notices/preview',{'notice':notice})
    assert 'mailto:homework@example.com' in preview['html']
    job=request('/send-jobs',{'notice':notice,'idempotency_key':'roster-browser-verification-job'})
    for _ in range(400):
        detail=context.request.get(base+'/api/send-jobs/'+job['id']).json()
        if detail['status'] not in ('queued','sending'):break
        page.wait_for_timeout(30)
    assert detail['status']=='completed' and detail['counts']['accepted']==66,detail
    assert len(factory.messages)==66
    assert len({m[2]['email'] for m in factory.messages})==66
    checks.append('Compose selects all 66 recipients after roster pagination; preview and isolated 66-person simulated delivery pass')

    # Empty application state and class CRUD; all operations target only the temp DB.
    page.locator('[data-route=classes]').click()
    with app.state.Session() as db: db.execute(delete(Classroom));db.commit()
    page.evaluate('refreshBasics()');page.evaluate("showClass('')")
    expect(page.locator('#student-list')).to_contain_text('先建立一个班级')
    assert page.locator('#add-student').is_disabled()
    page.locator('#add-class').click();page.locator('#class-name').fill('新建验收班');save_dialog()
    expect(page.locator('.class-item.active')).to_contain_text('新建验收班')
    expect(page.locator('#student-list')).to_contain_text('把你的同学加入名单')
    page.locator('#rename-class').click();page.locator('#class-name').fill('已重命名验收班');save_dialog()
    expect(page.locator('#class-title')).to_have_text('已重命名验收班')
    page.locator('#delete-class').click();save_dialog()
    expect(page.locator('#student-list')).to_contain_text('先建立一个班级')
    checks.append('No classes/empty class, class creation/rename/delete, disabled actions and valid selection')
    page.reload()
    expect(page.locator('#roster-page-title')).to_be_visible()
    expect(page.locator('script[src*="app.js"]')).to_have_attribute('src','/static/app.js?v=send-policy-20261018-1')
    expect(page.locator('link[href*="app.css"]')).to_have_attribute('href','/static/app.css?v=send-policy-20261018-1')
    assert page.evaluate("() => document.body.classList.contains('roster-active')")
    checks.append('Reload serves versioned roster markup and assets in the same isolated server process')
    assert not errors,errors
    assert not external,external
    report={'checks':checks,'pagination':pagination,'contrast':contrast,'viewports':metrics,'unexpected_console_or_page_errors':errors,'external_requests':external,'simulated_deliveries':len(factory.messages),'data':'fictional only; temporary SQLite and in-memory credentials','browser':context.browser.version}
    (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


def run():
    parser = argparse.ArgumentParser(); parser.add_argument('--baseline', action='store_true'); args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    with isolated_app() as (app, factory, base), sync_playwright() as pw:
        ids = seed_rosters(app)
        edge = Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')
        browser = pw.chromium.launch(headless=True, **({'executable_path': str(edge)} if edge.exists() else {}))
        context = browser.new_context(viewport={'width': 1366, 'height': 768}, locale='zh-CN')
        errors, external = [], []
        def protect(route):
            if route.request.url.startswith(base + '/'): route.continue_()
            else: external.append(route.request.url); route.abort()
        context.route('**/*', protect)
        response = context.request.post(base + '/api/auth/setup', data={'password': 'fictional-browser-test-password'})
        assert response.status == 200
        page = context.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
        try:
            page.goto(base + '/#classes')
            expect(page.locator('#class-list [data-manage-class]')).to_have_count(len(ids))
            select_class(page, ids[66])
            if args.baseline: baseline(page, ids)
            else: verify(page, context, app, factory, base, ids, errors, external)
        except Exception:
            page.screenshot(path=str(OUT/'failure.png'))
            print('Failure UI state:',page.evaluate("() => ({active:document.activeElement?.outerHTML.slice(0,500),state:S.rosterState,page:S.rosterPage,errors:S.rosterError})"))
            raise
        finally: browser.close()

if __name__ == '__main__': run()
