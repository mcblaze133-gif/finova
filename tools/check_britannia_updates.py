"""Bounded official archive check, retaining original public response locally."""
import asyncio
import json
import re
from backend import storage
from backend.documents import Fetcher

async def main():
    fetcher=Fetcher(['britannia.co.in'])
    target=storage.PROJECT_DIR/'outputs/britannia-source-review'
    url='https://www.britannia.co.in/investors/financial-performance/financial-results?tab=financial-performance'
    try:
        data,kind,original=await fetcher.fetch(url)
        text=data.decode('utf-8','replace').replace('\\u002F','/').replace('\\/','/')
        (target/'official-investor-page.html').write_text(text,encoding='utf-8')
        links=sorted(set(re.findall(r'https://media\.britannia\.co\.in/[^"<>\s\\]+\.pdf',text)))
        selected=[u for u in links if re.search(r'2026|26_|27_|AGM|[Vv]oting',u)]
        result={'checked_at':storage.now(),'official_url':original,'linked_pdfs':len(links),'selected_links':selected,
                'coverage':'Links visible in official page response; not an exhaustive announcement search.'}
    except Exception as exc:
        result={'checked_at':storage.now(),'official_url':url,'status':'unavailable','failure_type':type(exc).__name__}
    (target/'external-update-check.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))

if __name__=='__main__':asyncio.run(main())
