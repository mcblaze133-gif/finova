"""Create and verify a consistent local backup without touching source data."""
import argparse
import hashlib
import json
import sqlite3
import shutil
import os
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from backend import storage

BACKUP_FOLDERS = ('data/raw', 'data/processed', 'workflows', 'prompts', 'reports',
                  'config', 'company-packs', 'outputs', 'schemas', 'excel')


def backup_files():
    for folder in BACKUP_FOLDERS:
        for directory, dirs, files in os.walk(storage.PROJECT_DIR/folder):
            dirs[:] = sorted(d for d in dirs if d.casefold()!='node_modules')
            for name in sorted(files):
                if name.casefold()!='.env':
                    yield Path(directory)/name


def backup(destination):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    db_path = destination / 'signalai.sqlite'
    source, target = storage.connect(), sqlite3.connect(db_path)
    try:
        source.backup(target)
        if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Backup database integrity check failed.')
        if target.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('Backup database contains foreign-key violations.')
    finally:
        source.close()
        target.close()
    manifest = {}
    with ZipFile(destination / 'documents-and-workflows.zip', 'x', ZIP_DEFLATED) as archive:
        for path in backup_files():
            if not path.resolve().is_relative_to(storage.PROJECT_DIR.resolve()):
                raise ValueError('Backup input points outside the project.')
            name = path.relative_to(storage.PROJECT_DIR).as_posix()
            data = path.read_bytes()
            archive.writestr(name, data)
            manifest[name] = hashlib.sha256(data).hexdigest()
    with ZipFile(destination / 'documents-and-workflows.zip') as archive:
        if archive.testzip() is not None:
            raise ValueError('Backup archive CRC verification failed.')
        for name, digest in manifest.items():
            if hashlib.sha256(archive.read(name)).hexdigest() != digest:
                raise ValueError('Backup file hash mismatch.')
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    (destination / 'backup-metadata.json').write_text(json.dumps({
        'version':2, 'project_root':str(storage.PROJECT_DIR.resolve()),
        'database_sha256':hashlib.sha256(db_path.read_bytes()).hexdigest(),
        'folders':list(BACKUP_FOLDERS), 'external_source_folder_included':False,
    }, indent=2), encoding='utf-8')
    return {'database_integrity': 'ok', 'archive_verified': True, 'files': len(manifest),
            'credentials_included': False, 'restore_rehearsal': 'not yet performed'}


def verify_restore(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    metadata_path = source / 'backup-metadata.json'
    metadata = json.loads(metadata_path.read_text(encoding='utf-8')) if metadata_path.is_file() else {}
    if metadata and hashlib.sha256((source/'signalai.sqlite').read_bytes()).hexdigest() != metadata['database_sha256']:
        raise ValueError('Backup database hash check failed.')
    shutil.copy2(source / 'signalai.sqlite', destination / 'signalai.sqlite')
    manifest = json.loads((source / 'manifest.json').read_text(encoding='utf-8'))
    with ZipFile(source / 'documents-and-workflows.zip') as archive:
        for name, digest in manifest.items():
            target = (destination / name).resolve()
            if not target.is_relative_to(destination):
                raise ValueError('Unsafe backup path.')
            data = archive.read(name)
            if hashlib.sha256(data).hexdigest() != digest:
                raise ValueError('Restore hash check failed.')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    db = sqlite3.connect(destination / 'signalai.sqlite')
    try:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Restored database integrity failed.')
        if db.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('Restored database contains foreign-key violations.')
        for path, digest in db.execute('SELECT local_path,sha256 FROM documents'):
            restored = (destination / path).resolve()
            if not restored.is_relative_to(destination) or not restored.is_file() or hashlib.sha256(restored.read_bytes()).hexdigest() != digest:
                raise ValueError('Restored original document missing or changed.')
        restored_exports = 0
        if metadata.get('version',0) >= 2:
            original_root = Path(metadata['project_root'])
            for (workbook_path,) in db.execute("SELECT workbook_path FROM excel_exports WHERE status='exported'"):
                original = Path(workbook_path).resolve()
                if not original.is_relative_to((original_root/'outputs').resolve()):
                    raise ValueError('Saved workbook path is outside the original output folder.')
                relative = original.relative_to(original_root).as_posix()
                if relative not in manifest or not (destination/relative).is_file():
                    raise ValueError('Restored saved workbook is missing.')
                db.execute('UPDATE excel_exports SET workbook_path=? WHERE workbook_path=?',
                           (str(destination/relative), workbook_path))
                restored_exports += 1
            db.commit()
    finally:
        db.close()
    return {'restore_verified': True, 'file_hashes_checked': len(manifest), 'database_integrity': 'ok',
            'saved_workbooks_restored':restored_exports,
            'external_source_folder_restored':False,
            'scope':'Application data only; code, installed runtimes, credentials and external source folders need separate recovery.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('destination', help='New local backup directory; existing paths are never overwritten.')
    parser.add_argument('--restore-from', help='Verify a prior backup by restoring into a new directory.')
    args = parser.parse_args()
    print(json.dumps(verify_restore(args.restore_from, args.destination) if args.restore_from else backup(args.destination), indent=2))
