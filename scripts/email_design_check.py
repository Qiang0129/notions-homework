"""Render a fictional standalone mail at desktop/mobile widths; no SMTP or production data."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from app.rendering import render

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/playwright'

def main():
    n={'subject':'数据库｜第四次作业 截止提醒','title':'别忘了，作业即将截止','course':'数据库','assignment':'第四次作业','deadline':'2026-10-21T23:59','submission_email':'homework@example.com','delta':{'ops':[{'insert':'{{name}}同学，你好：\n\n温馨提醒：{{assignment}}即将截止，请检查作业是否完成，并及时发送至下方提交邮箱。\n如果你已提交，请忽略本次提醒，无需重复提交。\n\n感谢配合，祝学习顺利！\n'}]}}
    content=render(n,{'name':'张三','class_name':'2026 级 1 班'})
    OUT.mkdir(parents=True,exist_ok=True);(OUT/'email-reference.html').write_text(content['html'],encoding='utf-8')
    errors=[];results={}
    with sync_playwright() as p:
        edge=Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')
        browser=p.chromium.launch(headless=True,**({'executable_path':str(edge)} if edge.exists() else {}))
        page=browser.new_page(viewport={'width':840,'height':900},device_scale_factor=1)
        page.on('pageerror',lambda e:errors.append(str(e)))
        for width in (840,640,480,375,320):
            page.set_viewport_size({'width':width,'height':900})
            page.set_content(content['html'],wait_until='load')
            page.wait_for_function('Array.from(document.images).every(image=>image.complete&&image.naturalWidth>0)')
            assert page.locator('h1').inner_text()==n['title']
            assert page.locator('a').filter(has_text='发送作业邮件').get_attribute('href')=='mailto:homework@example.com'
            overflow=page.evaluate('document.documentElement.scrollWidth>innerWidth')
            assert not overflow,f'Email overflow at {width}'
            results[str(width)]={'images':page.locator('img').count(),'overflow':overflow,'title_px':page.locator('h1').evaluate('el=>getComputedStyle(el).fontSize')}
            if width in (840,375):page.screenshot(path=str(OUT/f'email-reference-{width}.png'),full_page=True)
        page.add_style_tag(content='img{visibility:hidden!important}')
        assert 'homework@example.com' in page.inner_text('body') and '2026-10-21 23:59' in page.inner_text('body')
        page.screenshot(path=str(OUT/'email-images-disabled.png'),full_page=True)
        browser.close()
    assert not errors,errors
    (OUT/'email-design-report.json').write_text(json.dumps({'widths':results,'page_errors':errors,'all_submission_links':'mailto','data':'fictional only'},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False))

if __name__=='__main__':main()
