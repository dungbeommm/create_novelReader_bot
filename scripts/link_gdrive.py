"""Run on your own computer to authorize Drive (loopback OAuth + state + PKCE).

Writes a private JSON file for copying into GitHub Actions Secrets. Never prints
refresh tokens/client secrets and never accepts them through Telegram.
"""
import argparse
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import time
from urllib.parse import parse_qs, urlencode, urlparse
import webbrowser
import requests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client-file', type=Path, required=True,
                        help='Google OAuth Desktop app JSON (downloaded locally)')
    parser.add_argument('--output', type=Path, default=Path('gdrive-secrets.json'))
    args = parser.parse_args()
    raw = json.loads(args.client_file.read_text(encoding='utf-8'))
    client = raw.get('installed')
    if not client:
        parser.error('Dùng OAuth client loại Desktop app, không dùng Web client.')
    if args.output.exists():
        parser.error('Tệp output đã tồn tại; chọn tên khác để không ghi đè thông tin cũ.')
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    result = {}

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Authorization codes must not appear in logs.

        def do_GET(self):
            query = parse_qs(urlparse(self.path).query)
            if urlparse(self.path).path != '/callback' or query.get('state') != [state]:
                self.send_response(400);self.end_headers();self.wfile.write(b'Invalid OAuth state.');return
            result.update({k: v[0] for k, v in query.items()})
            self.send_response(200);self.end_headers()
            self.wfile.write(b'Authorization received. Return to your terminal. You may close this tab.')

    with HTTPServer(('127.0.0.1', 0), Callback) as server:
        server.timeout = 1
        redirect = f'http://127.0.0.1:{server.server_port}/callback'
        url = 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode({
            'client_id': client['client_id'], 'redirect_uri': redirect,
            'response_type': 'code', 'scope': 'https://www.googleapis.com/auth/drive.file',
            'access_type': 'offline', 'prompt': 'consent', 'state': state,
            'code_challenge': challenge, 'code_challenge_method': 'S256'})
        print('Mở URL sau trên CHÍNH máy đang chạy script (hết hạn sau 5 phút):\n' + url)
        webbrowser.open(url)
        deadline = time.monotonic() + 300
        while not result and time.monotonic() < deadline:
            server.handle_request()
    if not result.get('code'):
        raise SystemExit('Không nhận được mã xác thực hoặc bạn đã từ chối. Chạy lại khi sẵn sàng.')
    r = requests.post('https://oauth2.googleapis.com/token', data={
        'client_id': client['client_id'], 'client_secret': client['client_secret'],
        'code': result['code'], 'redirect_uri': redirect, 'grant_type': 'authorization_code',
        'code_verifier': verifier}, timeout=30)
    if not r.ok:
        raise SystemExit(f'Không đổi được token (HTTP {r.status_code}); không in phản hồi chứa thông tin riêng tư.')
    tokens = r.json()
    if not tokens.get('refresh_token'):
        raise SystemExit('Google không trả refresh token. Kiểm tra quyền OAuth rồi thử lại.')
    r = requests.post('https://www.googleapis.com/drive/v3/files',
        headers={'Authorization': 'Bearer ' + tokens['access_token']},
        json={'name': 'NovelReader_Output', 'mimeType': 'application/vnd.google-apps.folder'}, timeout=30)
    if not r.ok:
        raise SystemExit(f'Không tạo được thư mục Drive (HTTP {r.status_code}).')
    values = {'GDRIVE_CLIENT_ID': client['client_id'], 'GDRIVE_CLIENT_SECRET': client['client_secret'],
              'GDRIVE_REFRESH_TOKEN': tokens['refresh_token'], 'GDRIVE_FOLDER_ID': r.json()['id']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as output:
        json.dump(values, output, indent=2)
    print('Đã tạo thư mục NovelReader_Output và lưu cấu hình vào:', args.output)
    print('Đưa 4 giá trị vào Actions Secrets. Không commit tệp này; xóa bản tạm khi hoàn tất.')


if __name__ == '__main__':
    main()
