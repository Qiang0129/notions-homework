"""Rebuild code-authored SVG decorations as PNGs for email-client compatibility.
Only a development tool; runtime uses the shipped PNG files and needs no browser.
"""
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'app/static/email'
SVG={
'course':'''<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64"><defs><linearGradient id="b" x2="1" y2="1"><stop stop-color="#426196"/><stop offset="1" stop-color="#233e6c"/></linearGradient></defs><path d="M10 16h44v33c0 13-44 13-44 0z" fill="url(#b)"/><ellipse cx="32" cy="16" rx="22" ry="10" fill="#3e5d94" stroke="white" stroke-width="2"/><path d="M10 31c0 13 44 13 44 0M10 46c0 13 44 13 44 0" fill="none" stroke="white" stroke-width="2.5"/></svg>''',
'assignment':'''<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64"><circle cx="32" cy="32" r="31" fill="#ffeadf"/><rect x="22" y="17" width="22" height="31" rx="3" fill="none" stroke="#e96337" stroke-width="3"/><path d="M27 25h12M27 32h12M27 39h7" stroke="#e96337" stroke-width="3" stroke-linecap="round"/></svg>''',
'clock':'''<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64"><circle cx="32" cy="32" r="31" fill="#ffeadf"/><circle cx="32" cy="32" r="17" fill="none" stroke="#e96337" stroke-width="3.5"/><path d="M32 21v12l8 5" fill="none" stroke="#e96337" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/></svg>''',
'contact':'''<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64"><circle cx="32" cy="32" r="31" fill="#f0f3f8"/><rect x="16" y="21" width="32" height="23" rx="4" fill="none" stroke="#74859f" stroke-width="3"/><path d="m17 23 15 12 15-12M18 42l11-10M46 42 35 32" fill="none" stroke="#74859f" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/></svg>''',
'hero':'''<svg xmlns="http://www.w3.org/2000/svg" width="360" height="280" viewBox="0 0 360 280"><defs><linearGradient id="paper" x1="0" x2="1" y2="1"><stop stop-color="#f0f4fc"/><stop offset="1" stop-color="#dfe8f7"/></linearGradient><linearGradient id="book" y2="1"><stop stop-color="#5a9cd4"/><stop offset="1" stop-color="#337db9"/></linearGradient><linearGradient id="orange" x2="1" y2="1"><stop stop-color="#ffc5ad"/><stop offset="1" stop-color="#ff9c75"/></linearGradient></defs><circle cx="178" cy="148" r="123" fill="#f4f7fc"/><circle cx="305" cy="216" r="80" fill="#f0f5fb"/><circle cx="93" cy="244" r="61" fill="#f8faff"/><g transform="translate(94 49) rotate(9 80 90)"><rect x="5" y="6" width="150" height="189" rx="13" fill="#d8e3f5" opacity=".65"/><rect width="150" height="189" rx="13" fill="url(#paper)"/><path d="M27 40h92M27 68h77M27 96h53M27 124h72" stroke="#c5d4ed" stroke-width="9" stroke-linecap="round"/></g><g transform="translate(175 186)"><ellipse cx="69" cy="76" rx="93" ry="8" fill="#d8e2f0" opacity=".35"/><path d="m-8 41 105-11 49 9-107 14z" fill="#8093b3"/><path d="m-8 41 8 6v23l39 8 107-16V39L39 53z" fill="#cfdaea"/><path d="m2 45 37 7 99-12v19L39 72 2 66z" fill="#fffaf5"/><path d="M7 49v13l31 6 99-12" fill="none" stroke="#e8dfdc" stroke-width="2"/><path d="m-2 8 105-13 39 6-103 15z" fill="#4d8ec6"/><path d="M-2 8q-10 1-10 15v11q0 8 10 9l41 5L142 35V1L39 16z" fill="url(#book)"/><path d="M-1 15q-5 0-5 7v12q0 5 5 5l40 5 96-13V8L39 21z" fill="#fffdf9"/><path d="m0 22 39 5L134 14M0 29l39 5 95-13" fill="none" stroke="#e8e7e9" stroke-width="2"/><path d="m11 39 27 3v5l-27-3z" fill="#f77543"/></g><path d="m265 31 4-22q2-9 11-6 7 2 2 11l-9 20q-5 6-8-3zm19 9 14-17q6-7 12-1 6 6-2 11l-17 12q-7 4-7-5z" fill="url(#orange)"/></svg>'''
}

def main():
    DEST.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as p:
        edge=Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')
        browser=p.chromium.launch(headless=True,**({'executable_path':str(edge)} if edge.exists() else {}))
        page=browser.new_page(viewport={'width':500,'height':400},device_scale_factor=2)
        for name,svg in SVG.items():
            (DEST/f'{name}.svg').write_text(svg,encoding='utf-8')
            page.set_content('<html><body style="margin:0;background:transparent">'+svg+'</body></html>')
            page.locator('svg').screenshot(path=str(DEST/f'{name}.png'),omit_background=True)
            print(name,(DEST/f'{name}.png').stat().st_size,'bytes')
        browser.close()

if __name__=='__main__':main()
