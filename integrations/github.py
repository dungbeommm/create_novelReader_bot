"""Small GitHub Releases client. Private repositories are required by default."""
import os
import re
from pathlib import Path
from urllib.parse import quote
import requests


class GitHubReleases:
    def __init__(self):
        self.repo = os.getenv('GITHUB_REPOSITORY', '')
        self.token = os.getenv('GH_RELEASE_TOKEN') or os.getenv('GITHUB_TOKEN', '')
        if not re.fullmatch(r'[\w.-]+/[\w.-]+', self.repo) or not self.token:
            raise ValueError('Cần GITHUB_REPOSITORY và GH_RELEASE_TOKEN/GITHUB_TOKEN.')
        self.base = f'https://api.github.com/repos/{self.repo}'
        self.session = requests.Session()
        self.session.headers.update({'Authorization': f'Bearer {self.token}',
            'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'})
        self.checked = False

    def check_private(self, strict=False):
        r = self.session.get(self.base, timeout=30)
        r.raise_for_status()
        if not r.json()['private'] and (strict or os.getenv('ALLOW_PUBLIC_RELEASES') != 'true'):
            raise ValueError('Repository công khai: chặn upload. Dùng repo private; chỉ bật ALLOW_PUBLIC_RELEASES=true nếu chấp nhận công khai kết quả.')
        self.checked = True

    def release(self, tag, create=True):
        if not self.checked:
            self.check_private()
        r = self.session.get(self.base + '/releases/tags/' + quote(tag, safe=''), timeout=30)
        if r.status_code == 404:
            if not create:
                return None
            r = self.session.post(self.base + '/releases', json={'tag_name': tag,
                'name': tag, 'body': 'NovelReader generated files. Do not upload credentials.',
                'make_latest': 'false'}, timeout=30)
        r.raise_for_status()
        return r.json()

    def assets(self, release):
        result = []
        page = 1
        while True:
            r = self.session.get(self.base + f"/releases/{release['id']}/assets",
                                 params={'per_page': 100, 'page': page}, timeout=30)
            r.raise_for_status()
            rows = r.json()
            result.extend(rows)
            if len(rows) < 100:
                return result
            page += 1

    def upload(self, release, path, name=None):
        path = Path(path)
        if path.stat().st_size >= 2 * 1024**3:
            raise ValueError('Một release asset phải nhỏ hơn 2 GiB.')
        # Use a fixed GitHub host, never forward credentials to a server-provided URL.
        url = f"https://uploads.github.com/repos/{self.repo}/releases/{release['id']}/assets"
        with path.open('rb') as source:
            r = self.session.post(url, params={'name': name or path.name}, data=source,
                headers={'Content-Type': 'application/octet-stream'}, timeout=(30, 1800))
        r.raise_for_status()
        return r.json()

    def delete_asset(self, asset):
        r = self.session.delete(self.base + f"/releases/assets/{asset['id']}", timeout=30)
        r.raise_for_status()

    def download(self, asset, target):
        # requests strips Authorization on cross-host redirects to asset storage.
        with self.session.get(self.base + f"/releases/assets/{asset['id']}",
                headers={'Accept': 'application/octet-stream'}, stream=True, timeout=(30, 300)) as r:
            r.raise_for_status()
            with Path(target).open('wb') as dest:
                for block in r.iter_content(1024 * 1024):
                    dest.write(block)
