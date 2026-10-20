"""Create machine-local settings without credentials or overwriting existing files."""
import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def write_missing(path, value):
    if path.exists():
        print(f'Preserved {path.relative_to(ROOT)}')
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    print(f'Created {path.relative_to(ROOT)}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-folder', type=Path, default=ROOT / 'local-sources')
    parser.add_argument('--node', default=shutil.which('node') or 'node')
    parser.add_argument('--pdf-python', default=sys.executable)
    args = parser.parse_args()
    write_missing(ROOT / 'config/runtime.json', {'node': args.node, 'pdf_python': args.pdf_python})
    write_missing(ROOT / 'config/library.json', {
        'source_folder': str(args.source_folder.resolve()), 'history_years': 5,
        'forecast_years': 5, 'dashboard': 'excel', 'scenarios': ['bear', 'base', 'bull'],
        'assumption_policy': 'Explicitly labelled analyst estimates; preserve overrides',
        'amount_basis': 'plain INR and actual shares',
    })
    for name in ('data', 'reports', 'outputs', 'company-packs'):
        (ROOT / name).mkdir(exist_ok=True)
    if not (ROOT / '.env').exists():
        shutil.copyfile(ROOT / '.env.example', ROOT / '.env')
        print('Created .env with blank credentials; live model calls remain disabled.')
    sys.path.insert(0, str(ROOT))
    from backend import storage
    storage.initialize()
    print('Initialized local database schema (no company source data imported).')
    print('Local settings ready. Existing company data and credentials were not modified.')


if __name__ == '__main__':
    main()
