"""Publish Telegram outputs to Drive first, then GitHub Releases on failure."""
import hashlib
import json
import logging
import mimetypes
import os
import re
from pathlib import Path
import requests
from integrations.github import GitHubReleases

log = logging.getLogger(__name__)


def atomic_json(path, data):
    path = Path(path)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def fingerprint(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def drive_config():
    from gdrive.gdrive_service import get_gdrive_config
    cfg = get_gdrive_config()
    # Environment credentials never get written to the Web settings file.
    env = {key: os.getenv(var, '') for key, var in {
        'client_id': 'GDRIVE_CLIENT_ID', 'client_secret': 'GDRIVE_CLIENT_SECRET',
        'refresh_token': 'GDRIVE_REFRESH_TOKEN', 'folder_id': 'GDRIVE_FOLDER_ID'}.items()}
    if any(env.values()):
        if not all(env.values()):
            raise ValueError('Thiếu một trong bốn biến GDRIVE_*; chuyển sang Releases.')
        return dict(env, enabled=True, mode='api')
    return cfg


def upload_drive(path, jid, digest):
    cfg = drive_config()
    if not cfg.get('enabled'):
        raise ValueError('Chưa liên kết Drive.')
    if cfg.get('mode') == 'local_folder':
        # Desktop folder uploads stay local; no fake cloud URL is returned.
        from gdrive.gdrive_service import upload_audio_file
        ok, _ = upload_audio_file(path, subfolder_name=jid)
        if not ok:
            raise RuntimeError('Không sao chép được vào thư mục Drive.')
        return {'provider': 'drive-local', 'url': '', 'name': path.name}
    token = cfg.get('access_token', '')
    if cfg.get('refresh_token'):
        r = requests.post('https://oauth2.googleapis.com/token', data={
            'client_id': cfg.get('client_id', ''), 'client_secret': cfg.get('client_secret', ''),
            'refresh_token': cfg['refresh_token'], 'grant_type': 'refresh_token'}, timeout=30)
        r.raise_for_status()
        token = r.json()['access_token']
    if not token:
        raise ValueError('Drive không có token hợp lệ.')
    folder = cfg.get('folder_id', '')
    if not re.fullmatch(r'[A-Za-z0-9_-]+', folder):
        raise ValueError('Cần GDRIVE_FOLDER_ID hợp lệ.')
    headers = {'Authorization': f'Bearer {token}'}
    # Recover an upload completed before a crash, without creating duplicate files.
    q = (f"'{folder}' in parents and trashed = false and "
         f"appProperties has {{ key='novel_job' and value='{jid}' }} and "
         f"appProperties has {{ key='sha256' and value='{digest}' }}")
    r = requests.get('https://www.googleapis.com/drive/v3/files', headers=headers,
        params={'q': q, 'fields': 'files(id,name)', 'supportsAllDrives': 'true',
                'includeItemsFromAllDrives': 'true'}, timeout=30)
    r.raise_for_status()
    existing = r.json().get('files', [])
    if existing:
        return {'provider': 'drive', 'url': f"https://drive.google.com/file/d/{existing[0]['id']}/view", 'name': path.name}
    mime = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
    r = requests.post('https://www.googleapis.com/upload/drive/v3/files',
        params={'uploadType': 'resumable', 'supportsAllDrives': 'true', 'fields': 'id'},
        headers={**headers, 'X-Upload-Content-Type': mime,
                 'X-Upload-Content-Length': str(path.stat().st_size)},
        json={'name': f'{jid}_{path.name}', 'parents': [folder],
              'appProperties': {'novel_job': jid, 'sha256': digest}}, timeout=30)
    r.raise_for_status()
    location = r.headers['Location']
    from urllib.parse import urlparse
    parsed = urlparse(location)
    if parsed.scheme != 'https' or parsed.hostname != 'www.googleapis.com':
        raise ValueError('Drive trả về địa chỉ upload không hợp lệ.')
    with path.open('rb') as source:
        # Streaming the file keeps RAM usage bounded. On failure retry the job;
        # completed uploads are discovered above using appProperties.
        r = requests.put(location, headers={**headers, 'Content-Type': mime,
            'Content-Length': str(path.stat().st_size)}, data=source, timeout=(30, 1800))
    r.raise_for_status()
    return {'provider': 'drive', 'url': f"https://drive.google.com/file/d/{r.json()['id']}/view", 'name': path.name}


def upload_release(path, jid, digest):
    github = GitHubReleases()
    release = github.release('novel-job-' + jid)
    name = digest[:16] + '_' + path.name
    for asset in github.assets(release):
        if asset['name'] == name and asset['size'] == path.stat().st_size:
            return {'provider': 'github', 'url': asset['browser_download_url'], 'name': path.name}
    asset = github.upload(release, path, name)
    return {'provider': 'github', 'url': asset['browser_download_url'], 'name': path.name}


def storage_status():
    try:
        drive = bool(drive_config().get('enabled'))
    except ValueError:
        drive = False
    github = bool(os.getenv('GITHUB_REPOSITORY') and (os.getenv('GH_RELEASE_TOKEN') or os.getenv('GITHUB_TOKEN')))
    return {'drive_configured': drive, 'github_configured': github,
            'disabled': os.getenv('CLOUD_UPLOAD', 'auto').lower() == 'off'}


def publish(path, jid, folder):
    """Return a saved receipt, or None in explicitly local/unconfigured mode."""
    if not re.fullmatch(r'[a-f0-9]{16}', jid):
        raise ValueError('Mã tác vụ không hợp lệ.')
    settings = storage_status()
    if settings['disabled']:
        return None
    # Preserve local-only use of the original project; GitHub Actions always has
    # GITHUB_REPOSITORY+GITHUB_TOKEN and therefore always publishes or fails.
    if not settings['drive_configured'] and not settings['github_configured'] and not any(v for k, v in os.environ.items() if k.startswith('GDRIVE_')):
        return None
    path = Path(path)
    marker = Path(folder) / 'cloud.json'
    receipts = json.loads(marker.read_text(encoding='utf-8')) if marker.exists() else {}
    digest = fingerprint(path)
    key = path.name
    if key in receipts and receipts[key].get('sha256') == digest:
        return receipts[key]
    try:
        result = upload_drive(path, jid, digest)
    except Exception as exc:
        # Never log OAuth responses, headers, signed URLs, or credential values.
        log.warning('Drive unavailable (%s, HTTP %s); falling back to GitHub Releases.',
                    type(exc).__name__, getattr(getattr(exc, 'response', None), 'status_code', 'n/a'))
        result = upload_release(path, jid, digest)
    result['sha256'] = digest
    receipts[key] = result
    atomic_json(marker, receipts)
    return result
