"""Read-time compatibility for older drafts/templates; historical job snapshots remain immutable."""
from copy import deepcopy
import re
from .schemas import address

LEGACY_TOKEN=re.compile(r'\{\{\s*submission_url\s*\}\}')

def tokens(value):
    if isinstance(value,str): return LEGACY_TOKEN.sub('{{submission_email}}',value)
    if isinstance(value,list): return [tokens(item) for item in value]
    if isinstance(value,dict):
        result={key:tokens(item) for key,item in value.items()}
        # An old URL token used as a rich-text hyperlink needs an explicit mailto scheme.
        attrs=value.get('attributes')
        if isinstance(attrs,dict) and isinstance(attrs.get('link'),str) and LEGACY_TOKEN.fullmatch(attrs['link'].strip()):
            result['attributes']['link']='mailto:{{submission_email}}'
        return result
    return value

def template_content(content):
    result=deepcopy(content)
    for key in ('subject','title','delta'):
        if key in result: result[key]=tokens(result[key])
    return result

def draft_content(content):
    result=template_content(content)
    if 'submission_url' in result:
        old=result.pop('submission_url')
        if 'submission_email' not in result:
            value=old[7:] if isinstance(old,str) and old.lower().startswith('mailto:') else old
            try: result['submission_email']=address(value) if isinstance(value,str) and value else ''
            except ValueError: result['submission_email']=''
    return result
