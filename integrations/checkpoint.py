"""Encrypted, rotating checkpoints for bounded GitHub-hosted Actions sessions.

Only BOT_DATA is backed up. SQLite uses the online backup API, not raw WAL copies.
No environment credentials or Web Drive settings are included.
"""
import argparse
import base64
import os
import shutil
import sqlite3
import tarfile
import tempfile
import time
import uuid
from pathlib import Path
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from integrations.github import GitHubReleases

MAGIC = b'NOVELCP1'
TAG = 'novel-checkpoints'
MAX_SIZE = 1800 * 1024**2


def key():
    try:
        result = base64.urlsafe_b64decode(os.environ['CHECKPOINT_KEY'])
        if len(result) != 32:
            raise ValueError()
        return result
    except Exception:
        raise ValueError('CHECKPOINT_KEY phải là khóa 32 byte, mã hóa URL-safe base64.') from None


def encrypt(source, target):
    nonce = os.urandom(12)
    cipher = Cipher(algorithms.AES(key()), modes.GCM(nonce)).encryptor()
    cipher.authenticate_additional_data(MAGIC)
    with Path(source).open('rb') as src, Path(target).open('wb') as dst:
        dst.write(MAGIC + nonce)
        for block in iter(lambda: src.read(1024 * 1024), b''):
            dst.write(cipher.update(block))
        dst.write(cipher.finalize())
        dst.write(cipher.tag)


def decrypt(source, target):
    size = Path(source).stat().st_size
    if size < len(MAGIC) + 28:
        raise ValueError('Checkpoint quá ngắn.')
    try:
        with Path(source).open('rb') as src:
            if src.read(len(MAGIC)) != MAGIC:
                raise ValueError('Sai định dạng checkpoint.')
            nonce = src.read(12)
            src.seek(-16, 2)
            cipher = Cipher(algorithms.AES(key()), modes.GCM(nonce, src.read(16))).decryptor()
            cipher.authenticate_additional_data(MAGIC)
            src.seek(len(MAGIC) + 12)
            remaining = size - len(MAGIC) - 28
            with Path(target).open('wb') as dst:
                while remaining:
                    block = src.read(min(1024 * 1024, remaining))
                    if not block:
                        raise ValueError('Checkpoint bị cắt ngắn.')
                    remaining -= len(block)
                    dst.write(cipher.update(block))
                dst.write(cipher.finalize())
    except BaseException:
        Path(target).unlink(missing_ok=True)
        raise


def snapshot(root, target):
    root = Path(root).resolve()
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(target, 'w:gz') as tar:
            for path in sorted(root.rglob('*')):
                if not path.is_file() or path.is_symlink():
                    continue
                if path.name.endswith(('-wal', '-shm', '.tmp', '.log')) or path.name == 'chapter.mp3':
                    continue
                relative = path.relative_to(root)
                if path.suffix == '.sqlite3':
                    copy = Path(tmp) / str(uuid.uuid4())
                    with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as src, sqlite3.connect(copy) as dst:
                        src.backup(dst)
                    tar.add(copy, arcname=str(relative), recursive=False)
                else:
                    try:
                        tar.add(path, arcname=str(relative), recursive=False)
                    except FileNotFoundError:
                        # /xoa may remove an inactive job during a periodic snapshot.
                        continue


def extract(source, target):
    target = Path(target).resolve()
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(source, 'r:gz') as tar:
        total = 0
        for member in tar.getmembers():
            dest = (target / member.name).resolve()
            if not dest.is_relative_to(target) or not member.isfile() or member.size < 0:
                raise ValueError('Đường dẫn/checkpoint không an toàn.')
            total += member.size
            if total > 12 * 1024**3:
                raise ValueError('Checkpoint giải nén quá 12 GiB.')
        tar.extractall(target, filter='data')


def save(root):
    key()  # Fail before any remote side effects.
    gh = GitHubReleases()
    gh.check_private(strict=True)
    release = gh.release(TAG)
    previous = gh.assets(release)
    with tempfile.TemporaryDirectory() as temp:
        archive, encrypted = Path(temp)/'state.tar.gz', Path(temp)/'state.enc'
        snapshot(root, archive)
        if archive.stat().st_size > MAX_SIZE:
            raise ValueError('Checkpoint quá 1.8 GiB; /xoa tác vụ cũ hoặc dùng VPS có ổ lưu bền.')
        encrypt(archive, encrypted)
        name = f'checkpoint-{time.time_ns():020d}-{uuid.uuid4().hex[:8]}.enc'
        gh.upload(release, encrypted, name)
    # Keep the newest old copy as rollback. Never delete the previous good copy
    # before the new upload has completed successfully.
    old = sorted((a for a in previous if a['name'].startswith('checkpoint-') and a['name'].endswith('.enc')),
                 key=lambda a: a['name'], reverse=True)
    for asset in old[1:]:
        gh.delete_asset(asset)


def restore(root):
    key()
    root = Path(root)
    if root.exists() and any(root.iterdir()):
        raise ValueError('Chỉ restore vào BOT_DATA trống; không ghi đè dữ liệu hiện tại.')
    gh = GitHubReleases()
    gh.check_private(strict=True)
    release = gh.release(TAG, create=False)
    if not release:
        return False
    assets = sorted((a for a in gh.assets(release) if a['name'].startswith('checkpoint-') and a['name'].endswith('.enc')),
                    key=lambda a: a['name'], reverse=True)
    if not assets:
        return False
    # Fail closed if the latest checkpoint is corrupt/wrong key. Do not silently
    # restore an older queue and replay already completed user requests.
    if assets[0]['size'] > MAX_SIZE + 1024:
        raise ValueError('Checkpoint quá lớn.')
    with tempfile.TemporaryDirectory() as temp:
        encrypted, archive = Path(temp)/'state.enc', Path(temp)/'state.tar.gz'
        gh.download(assets[0], encrypted)
        decrypt(encrypted, archive)
        staging = Path(temp)/'staging'
        extract(archive, staging)
        root.mkdir(parents=True, exist_ok=True)
        for path in staging.iterdir():
            shutil.move(str(path), str(root/path.name))
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['save', 'restore'])
    args = parser.parse_args()
    root = Path(os.environ.get('BOT_DATA', 'data/telegram'))
    if args.action == 'save':
        save(root)
    else:
        restore(root)


if __name__ == '__main__':
    main()
