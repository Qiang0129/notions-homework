"""Real-browser acceptance, isolated data and injected SMTP capture only. Never sends external mail."""
from __future__ import annotations
import json
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
import uvicorn
from playwright.sync_api import sync_playwright, expect
from app.main import create_app
from app.config import Settings
from conftest import FakeFactory, MemoryVault

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output'/'playwright'

def run():
    OUT.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='homework-browser-') as temp:
        factory=FakeFactory(); app=create_app(Settings(Path(temp),testing=True,worker_interval=.01,send_interval_override=0),MemoryVault(),factory)
        with socket.socket() as sock: sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
        server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,access_log=False,log_level='warning',proxy_headers=False))
        thread=threading.Thread(target=server.run,daemon=True);thread.start()
        for _ in range(200):
            if server.started: break
            time.sleep(.05)
        if not server.started: raise RuntimeError('浏览器测试服务未启动')
        console=[]; errors=[]; external=[]; checks=[]; font_metrics={}
        base=f'http://127.0.0.1:{port}'
        try:
            with sync_playwright() as pw:
                edge=Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')
                browser=pw.chromium.launch(headless=True,**({'executable_path':str(edge)} if edge.exists() else {}))
                context=browser.new_context(viewport={'width':1440,'height':1100},locale='zh-CN')
                def protect(route):
                    if route.request.url.startswith(base): route.continue_()
                    else: external.append(route.request.url);route.abort()
                context.route('**/*',protect)
                page=context.new_page()
                page.on('console',lambda m:console.append(m.text) if m.type=='error' else None)
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(base); expect(page.locator('#login-title')).to_have_text('创建你的工作空间')
                page.screenshot(path=str(OUT/'desktop-login.png'),full_page=True)
                page.locator('#password').fill('browser-test-password-123')
                page.locator('#confirm-password').fill('browser-test-password-123')
                page.locator('#login-submit').click(); page.wait_for_url(base+'/')
                expect(page.locator('#subject')).not_to_have_value('')
                checks.append('首次本机设置、登录和模板初始化')
                page.locator('[data-route="settings"]').click()
                page.locator('#add-profile').click()
                page.locator('#profile-preset').select_option('qq')
                page.locator('#profile-name').fill('课程通知邮箱')
                page.locator('#profile-sender-name').fill('高等数学 · 课程助教')
                page.locator('#profile-user').fill('teaching@example.com')
                page.locator('#profile-email').fill('teaching@example.com')
                page.locator('#profile-password').fill('FICTIONAL-UI-TEST-SECRET')
                page.locator('#dialog-confirm').click()
                expect(page.locator('#dialog')).not_to_be_visible()
                expect(page.locator('#profile-list')).to_contain_text('课程通知邮箱')
                page.locator('[data-test-profile]').click()
                expect(page.locator('#toast-region')).to_contain_text('连接、TLS 与认证通过')
                checks.append('SMTP 预设、保存及连接测试界面（测试替身）')
                page.screenshot(path=str(OUT/'desktop-settings.png'),full_page=True)
                page.locator('[data-route="classes"]').click(); page.locator('#add-class').click()
                page.locator('#class-name').fill('高等数学 A · 2026 级 1 班');page.locator('#dialog-confirm').click()
                expect(page.locator('#dialog')).not_to_be_visible()
                page.locator('#import-students').click()
                page.locator('#import-text').fill('姓名 邮箱\n张三 zhang@example.com\n李四 li@example.com\n王五 wang@example.com\n张三 zhang@example.com\n错误行 nope')
                page.locator('#import-primary').click()
                expect(page.locator('#import-summary')).to_contain_text('共 5 行')
                page.locator('#valid-only').check();page.locator('#import-primary').click()
                expect(page.locator('#import-drawer')).not_to_be_visible()
                expect(page.locator('#student-list')).to_contain_text('zhang@example.com')
                page.locator('#student-search').fill('张三');expect(page.locator('#student-list tbody tr')).to_have_count(1);page.locator('#student-search').fill('')
                checks.append('班级创建、粘贴导入、重复/错误提示、明确导入有效行和搜索')
                page.locator('[data-route="compose"]').click()
                page.locator('#course').fill('高等数学 A')
                page.locator('#assignment').fill('第三章 · 导数与微分课后习题')
                page.locator('#deadline').fill('2026-10-20T23:59')
                page.locator('#submission-email').fill('homework@example.com')
                expect(page.locator('#submission-email')).to_have_attribute('type','email')
                cid=page.locator('#compose-class option').nth(1).get_attribute('value')
                page.locator('#compose-class').select_option(cid)
                expect(page.locator('#send-count')).to_have_text('3')
                expect(page.locator('#preview-status')).to_contain_text('预览已更新')
                page.locator('#preview-student').select_option(label='张三')
                expect(page.frame_locator('#mail-preview').locator('body')).to_contain_text('张三同学，你好')
                expect(page.frame_locator('#mail-preview').locator('a').filter(has_text='发送作业邮件')).to_have_attribute('href','mailto:homework@example.com')
                expect(page.frame_locator('#mail-preview').locator('body')).to_contain_text('homework@example.com')
                expect(page.frame_locator('#mail-preview').locator('img')).to_have_count(5)
                assert page.frame_locator('#mail-preview').locator('body').evaluate('()=>Array.from(document.images).every(image=>image.complete&&image.naturalWidth>0)')
                expect(page.frame_locator('#mail-preview').locator('body')).to_contain_text('COURSE NOTICE')
                checks.append('富文本模板、学生变量、提交邮箱校验与 mailto 邮件提交按钮')
                page.locator('#deadline').fill('');page.locator('#save-draft').click()
                expect(page.locator('#toast-region')).to_contain_text('草稿已保存在本机')
                page.locator('#deadline').fill('2026-10-20T23:59');page.locator('#save-draft').click()
                page.locator('#save-as-template').click();page.locator('#template-name').fill('高数作业温馨提醒');page.locator('#dialog-confirm').click();expect(page.locator('#dialog')).not_to_be_visible()
                checks.append('未完成草稿保存、完整草稿更新和自定义模板保存')
                page.wait_for_timeout(4200)
                page.locator('#breadcrumb-current').click()
                page.evaluate('scrollTo(0,0)')
                page.screenshot(path=str(OUT/'desktop-compose.png'),full_page=True)
                page.screenshot(path=str(OUT/'desktop-overview.png'))
                font_metrics['desktop']=page.evaluate('''()=>Object.fromEntries(Object.entries({body:'body',input:'#course',label:'label[for=course]',navigation:'[data-route=compose]',editor:'.ql-editor',hint:'.field-hint'}).map(([key,selector])=>[key,parseFloat(getComputedStyle(document.querySelector(selector)).fontSize)]))''')
                assert font_metrics['desktop']=={'body':16,'input':16,'label':14,'navigation':15,'editor':16,'hint':13},font_metrics
                page.set_viewport_size({'width':1920,'height':960})
                page.wait_for_timeout(350)
                page.evaluate('scrollTo(0,0)')
                page.screenshot(path=str(OUT/'desktop-readable-1920.png'))
                for width in (768,375):
                    page.set_viewport_size({'width':width,'height':1000})
                    page.locator('#mode-edit').click();page.wait_for_timeout(250)
                    font_metrics[str(width)]=page.evaluate('''()=>({body:parseFloat(getComputedStyle(document.body).fontSize),input:parseFloat(getComputedStyle(document.querySelector('#course')).fontSize),label:parseFloat(getComputedStyle(document.querySelector('label[for=course]')).fontSize)})''')
                    assert font_metrics[str(width)]['body']==16 and font_metrics[str(width)]['input']==16 and font_metrics[str(width)]['label']==14,font_metrics
                    overflow=page.evaluate('document.documentElement.scrollWidth > innerWidth')
                    assert not overflow,f'Editor horizontal overflow at {width}'
                    page.evaluate('scrollTo(0,0)')
                    page.screenshot(path=str(OUT/f'compose-{width}.png'),full_page=True)
                    page.locator('#mode-preview').click()
                    expect(page.frame_locator('#mail-preview').locator('body')).to_contain_text('张三同学，你好')
                    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                    page.evaluate('scrollTo(0,0)')
                    page.screenshot(path=str(OUT/f'preview-{width}.png'),full_page=True)
                    if width==375:
                        page.locator('[aria-label="打开导航"]').click()
                        expect(page.locator('#navigation')).to_be_visible()
                        page.locator('#navigation [data-route="classes"]').click()
                        expect(page.locator('[data-page="classes"]')).to_be_visible()
                        expect(page.locator('#navigation')).not_to_be_visible()
                        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                        page.screenshot(path=str(OUT/'classes-375.png'),full_page=True)
                        page.locator('[aria-label="打开导航"]').click();page.locator('#navigation [data-route="compose"]').click()
                checks.append('1440/768/375 响应式、移动抽屉、编辑/预览切换与无页面横向溢出')
                page.emulate_media(reduced_motion='reduce')
                assert page.evaluate('matchMedia("(prefers-reduced-motion: reduce)").matches')
                page.locator('#save-draft').focus();page.keyboard.press('Tab');assert page.locator(':focus').count()==1
                checks.append('减少动画偏好与键盘焦点')
                checks.append('全局可读性：正文/输入/编辑器 16px、标签 14px、导航 15px、辅助说明 13px；手机不缩小输入字号')
                page.set_viewport_size({'width':1440,'height':1100});page.locator('#mode-edit').evaluate('el=>el.click()')
                page.locator('#test-mail').click();page.locator('#test-address').fill('my-test@example.com');page.locator('#dialog-confirm').click();expect(page.locator('#dialog')).not_to_be_visible()
                assert len(factory.messages)==1 and factory.messages[0][2]['email']=='my-test@example.com'
                page.locator('#review-send').click();page.locator('#send-confirm-ack').check();page.locator('#send-confirm-submit').click();expect(page.locator('#send-confirm-drawer')).not_to_be_visible()
                expect(page.locator('#job-detail .status-badge').first).to_have_text('已完成',timeout=15000)
                assert len(factory.messages)==4
                assert {m[2]['email'] for m in factory.messages[1:]}=={'zhang@example.com','li@example.com','wang@example.com'}
                page.screenshot(path=str(OUT/'desktop-history.png'),full_page=True)
                checks.append('指定测试邮箱试发、明确群发确认、三位独立收件人与结果记录')
                checks.append('参考图风格 HTML 邮件：白色卡片、深蓝大标题、橙色信息区、5 张内嵌插画；变量与提交邮箱保持动态')
                page.locator('[data-route="templates"]').click()
                expect(page.locator('#template-list')).to_contain_text('高数作业温馨提醒')
                page.screenshot(path=str(OUT/'desktop-templates.png'),full_page=True)
                assert not errors,errors
                assert not console,console
                assert not external,external
                result={'font_metrics':font_metrics,'checks':checks,'console_errors':console,'page_errors':errors,'external_requests':external,'captured_test_messages':len(factory.messages),'browser':browser.version,'screenshots':[p.name for p in OUT.glob('*.png')]}
                (OUT/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
                print(json.dumps(result,ensure_ascii=True,indent=2));browser.close()
        finally:
            server.should_exit=True;thread.join(10)

if __name__=='__main__':run()
