# Bot Telegram - Ebook to Audiobook

Bot nhan file ebook, day len GitHub, kich hoat workflow `audiobook.yml`, cho
GitHub Actions tao audio bang Piper (giong Ngoc Huyen) roi **tu dong dang len
Internet Archive (archive.org)** va gui lai link `archive.org/details/<id>`.

## 1. Chuan bi

### a) Tao bot Telegram
1. Chat voi **@BotFather** tren Telegram -> `/newbot` -> lay **token**.

### b) Tao GitHub token (fine-grained PAT)
1. GitHub -> Settings -> Developer settings -> Fine-grained tokens.
2. Chi chon repo `piper-tts-service`.
3. Quyen: **Contents = Read and write**, **Actions = Read and write**.

### b2) Tao khoa Internet Archive va them vao GitHub Secrets
1. Dang nhap https://archive.org -> mo https://archive.org/account/s3.php.
2. Lay **access key** va **secret key**.
3. Trong repo GitHub: **Settings > Secrets and variables > Actions**, them 2 secret:
   `IA_ACCESS_KEY` va `IA_SECRET_KEY`.

> Viec upload chay tren GitHub Actions nen bot **khong** can 2 khoa nay o `.env`.

### c) Cau hinh bien moi truong
```bash
cd bot
cp .env.example .env
# mo .env dien token va owner/repo
```

## 2. Cai va chay

```bash
pip install -r bot/requirements-bot.txt
# nap bien moi truong tu .env (vi du dung python-dotenv hoac export thu cong)
set -a; source bot/.env; set +a
python bot/telegram_bot.py
```

## 3. Cach dung

1. Gui file ebook cho bot (`.txt`, `.epub`, `.zip` chua txt, `.mobi`, `.pdf`, `.docx`...).
2. Chon **toc do doc** (0.9 - 1.3).
3. Chon **dinh dang** (MP3 / M4B / WAV).
4. Bot gui ngay **link archive.org** (link co dinh, noi dung day dan khi xu ly), roi bao lai khi hoan tat.

## 4. Luu y

- File Telegram gioi han ~50MB khi gui truc tiep; bot gui **link archive.org** nen khong bi gioi han.
- Moi audiobook la 1 item archive.org, identifier tat dinh tu tieu de + job_id.
- Bot phat hien "hoan tat" khi item co file `_COMPLETE.json`; truyen dai co the mat nhieu gio.
- Muon gioi han nguoi dung: dien `ALLOWED_USER_IDS` trong `.env`.
- Co the deploy bot len Render/VPS bang cach chay lenh `python bot/telegram_bot.py` nhu mot worker.
