import asyncio
import sys
from urllib.parse import urljoin
from backend.companies import resolve
from backend.documents import Fetcher, extract, rank_link, allowed_url


async def main(company):
    profile = resolve(company)
    fetcher = Fetcher(profile.domains)
    for seed in profile.seeds:
        try:
            data, kind, original = await fetcher.fetch(seed)
            _, links = extract(data, kind)
            print({'seed': seed, 'bytes': len(data), 'links': len(links)}, flush=True)
            for href, label in sorted(links, key=rank_link, reverse=True)[:30]:
                url = urljoin(original, href)
                try:
                    allowed_url(url, profile.domains)
                    allowed = True
                except ValueError:
                    allowed = False
                print({'url': url, 'label': label[:100], 'allowed': allowed}, flush=True)
        except Exception as exc:
            print({'source': seed, 'failure_type': type(exc).__name__, 'reason': str(exc)[:150]}, flush=True)


if __name__ == '__main__':
    asyncio.run(main(sys.argv[1]))
