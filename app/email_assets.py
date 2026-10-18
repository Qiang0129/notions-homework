"""Local decorations use data URIs in previews and MIME CID images in outbound email.
Only these code-shipped PNGs are attached; no remote URLs or user-controlled file paths.
"""
from base64 import b64encode
from email.utils import make_msgid
from functools import lru_cache
from pathlib import Path

DIRECTORY=Path(__file__).parent/'static'/'email'
NAMES=('course','assignment','clock','contact','hero')

@lru_cache(maxsize=1)
def images():
    return {name:(DIRECTORY/f'{name}.png').read_bytes() for name in NAMES}

@lru_cache(maxsize=1)
def preview_sources():
    return {name:'data:image/png;base64,'+b64encode(data).decode('ascii') for name,data in images().items()}

def prepare_message_html(html):
    """Return SMTP HTML and (Content-ID, PNG bytes) without changing preview data."""
    related=[]
    for name,source in preview_sources().items():
        if source not in html: continue
        cid=make_msgid(domain='classnote.local')
        html=html.replace(source,'cid:'+cid[1:-1])
        related.append((cid,images()[name]))
    return html,related
