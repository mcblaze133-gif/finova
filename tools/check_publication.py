"""Check the staged Git snapshot without printing secret values. No network calls."""
import json
import re
import subprocess
from pathlib import Path
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
PRIVATE_DIRS = {'data', 'reports', 'backups', 'outputs', 'output', 'tmp',
                'company-packs', 'local-sources', '.venv', 'node_modules'}
PRIVATE_FILES = {'config/runtime.json', 'config/library.json', 'config/n8n-runtime.json'}


def main():
    paths = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    paths = [p for p in paths if p]
    if not paths:
        raise SystemExit('No staged/tracked files to check.')
    local_secrets = [str(v).encode() for k, v in dotenv_values(ROOT / '.env').items()
                     if v and len(str(v)) >= 12 and re.search(r'KEY|TOKEN|SECRET|PASSWORD', k, re.I)]
    patterns = [rb'AIza[0-9A-Za-z_-]{30,}', rb'gh[pousr]_[0-9A-Za-z]{30,}',
                rb'github_pat_[0-9A-Za-z_]{30,}', rb'sk-ant-[0-9A-Za-z_-]{30,}',
                rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----']
    failures = []
    for name in paths:
        p = Path(name)
        if (p.parts[0] in PRIVATE_DIRS or name in PRIVATE_FILES
                or (p.name.startswith('.env') and p.name != '.env.example')
                or p.suffix.lower() in {'.sqlite', '.db', '.pem', '.key'}):
            failures.append({'file': name, 'reason': 'private file in Git snapshot'})
            continue
        content = subprocess.check_output(['git', 'show', ':' + name], cwd=ROOT)
        if any(secret in content for secret in local_secrets) or any(re.search(pattern, content) for pattern in patterns):
            failures.append({'file': name, 'reason': 'potential credential; value withheld'})
        if len(content) > 50_000_000:
            failures.append({'file': name, 'reason': 'oversized publication file'})
    print(json.dumps({'files_checked': len(paths), 'passed': not failures, 'issues': failures}, indent=2))
    raise SystemExit(1 if failures else 0)


if __name__ == '__main__':
    main()
