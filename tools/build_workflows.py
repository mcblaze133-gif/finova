"""Generate credential-free n8n 2.x workflows with small, explicit tool boundaries."""
import json
from pathlib import Path
from uuid import uuid5, NAMESPACE_URL

ROOT = Path(__file__).resolve().parents[1]


def workflow(name, slug, method, endpoint, body=None, queries=None):
    webhook_id = str(uuid5(NAMESPACE_URL, 'signalai/' + slug))
    parameters = {'httpMethod': 'POST', 'path': 'signalai-' + slug, 'responseMode': 'lastNode', 'options': {}}
    request = {'method': method, 'url': endpoint, 'options': {'timeout': 110000}}
    if body:
        request.update({'sendBody': True, 'specifyBody': 'json', 'jsonBody': body})
    if queries:
        request.update({'sendQuery': True, 'queryParameters': {'parameters': queries}})
    return {'id': uuid5(NAMESPACE_URL, name.replace('Finova', 'SignalAI', 1)).hex[:16], 'name': name,
            'active': False, 'nodes': [
                {'id': 'input', 'name': 'Local input', 'type': 'n8n-nodes-base.webhook', 'typeVersion': 2,
                 'position': [0, 0], 'webhookId': webhook_id, 'parameters': parameters},
                {'id': 'backend', 'name': 'Finova bounded operation', 'type': 'n8n-nodes-base.httpRequest',
                 'typeVersion': 4.2, 'position': [300, 0], 'parameters': request}],
            'connections': {'Local input': {'main': [[{'node': 'Finova bounded operation', 'type': 'main', 'index': 0}]]}},
            'settings': {'executionOrder': 'v1', 'saveDataErrorExecution': 'none', 'saveDataSuccessExecution': 'none',
                         'saveExecutionProgress': False, 'executionTimeout': 120},
            'pinData': {}, 'tags': []}


exports = [
    workflow('Finova 01 Document ingestion', 'ingest', 'POST', 'http://127.0.0.1:8000/documents',
             '={{ JSON.stringify({company: $json.body.company, url: $json.body.url, title: $json.body.title || "Public disclosure", publication_date: $json.body.publication_date || null}) }}'),
    workflow('Finova 02 Company research', 'research', 'POST', 'http://127.0.0.1:8000/runs',
             '={{ JSON.stringify({company: $json.body.company, refresh: $json.body.refresh !== false}) }}'),
    workflow('Finova 03 Counterevidence search', 'counterevidence', 'GET', 'http://127.0.0.1:8000/search',
             queries=[{'name': 'company', 'value': '={{ $json.body.company }}'},
                      {'name': 'query', 'value': '={{ $json.body.query || "acquisition demerger discontinued restated seasonality exceptional lease inventory" }}'}]),
    workflow('Finova 04 Report retrieval', 'report', 'GET',
             '=http://127.0.0.1:8000/runs/{{ $json.body.run_id }}/report'),
    workflow('Finova 05 Evaluation status', 'evaluation', 'GET', 'http://127.0.0.1:8000/evaluation'),
]

if __name__ == '__main__':
    evaluation = exports[-1]
    evaluation['nodes'].append({'id': 'manual', 'name': 'Manual evaluation',
                                'type': 'n8n-nodes-base.manualTrigger', 'typeVersion': 1,
                                'position': [0, 180], 'parameters': {}})
    evaluation['connections']['Manual evaluation'] = {'main': [[{'node': 'Finova bounded operation', 'type': 'main', 'index': 0}]]}
    exports.extend([
        workflow('Finova 06 Excel generation', 'excel', 'POST', 'http://127.0.0.1:8000/excel/exports',
                 '={{ JSON.stringify({company: $json.body.company}) }}'),
        workflow('Finova 07 Source library status', 'library', 'GET', 'http://127.0.0.1:8000/library'),
    ])
    folder = ROOT / 'workflows'
    folder.mkdir(exist_ok=True)
    for index, item in enumerate(exports, 1):
        (folder / f'{index:02d}-{item["name"].split(" ", 2)[2].lower().replace(" ", "-")}.json').write_text(json.dumps(item, indent=2), encoding='utf-8')
    print('Seven inactive, credential-free workflow exports created.')
