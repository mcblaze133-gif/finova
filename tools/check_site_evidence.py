"""Read-only check of the live website's document integration; no AI calls."""
import httpx

if __name__ == '__main__':
    with httpx.Client(base_url='http://127.0.0.1:8000', timeout=20) as client:
        companies = client.get('/company-library').raise_for_status().json()
        ready = {c['id'] for c in companies if c['has_documents']}
        assert {'britannia','hul','itc','nestle-india','tata-consumer'}.issubset(ready)
        for company in sorted(ready):
            result = client.get('/results/'+company).raise_for_status().json()
            evidence = result['evidence']
            assert evidence['status'] == 'ready'
            assert result['valuation'] and len(result['valuation']['methods']) >= 3, company
            assert result['valuation']['weighted'] and result['valuation_readiness']['can_build'],company
            assert any(m['primary'] for m in result['valuation']['methods'])
            for key in ('index_url','text_url'):
                response = client.get(evidence[key]).raise_for_status()
                assert 'attachment' in response.headers['content-disposition']
                assert response.content
            with client.stream('GET',evidence['pdf_url']) as response:
                response.raise_for_status()
                assert next(response.iter_bytes()).startswith(b'%PDF-')
                assert response.headers['content-type'] == 'application/pdf'
            print(f'{company}: financial results, valuation status and document links verified', flush=True)
