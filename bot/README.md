# Bot Telegram tao audiobook

Co **2 cach chay bot**, dung cach nao cung duoc:

| | Cach A: chay tren may/VPS | Cach B: chay tren GitHub |
|---|---|---|
| File | `telegram_bot.py` | `bot_poll.py` + `.github/workflows/bot.yml` |
| May chay | Can may/VPS bat 24/7 | Khong can, GitHub lo het |
| Token GitHub (PAT) | **Can** (`GITHUB_TOKEN` ca nhan) | **Khong can** (Actions co san) |
| Toc do tra loi | Tuc thi | Cham ~5 phut/buoc (theo lich cron) |
| Gioi han file | ~20MB (Bot API) | ~20MB (Bot API) |

Ca hai deu dung chung luong hoi thoai: `/tts` -> gui file -> hoi ten truyen -> chon toc do -> chon dinh dang -> bao "Bat dau tao audio" -> khi xong gui link Release.

---

## Cach A - Chay tren may/VPS (`telegram_bot.py`)

1. Tao bot voi @BotFather, lay `TELEGRAM_BOT_TOKEN`.
2. Tao GitHub fine-grained token (`GITHUB_TOKEN`) chi cho repo nay, quyen **Contents: RW** + **Actions: RW**.
3. Cau hinh:
   ```bash
   cp .env.example .env   # dien token va GITHUB_REPO=owner/repo
   pip install -r requirements-bot.txt
   set -a; source .env; set +a
   python telegram_bot.py
   ```
Bot day file len repo, kich hoat workflow `audiobook.yml`, roi gui link khi xong.

---

## Cach B - Chay tren GitHub (`bot_poll.py`) [khuyen dung neu khong co VPS]

Khong can may rieng, khong can token ca nhan.

1. Tao bot voi @BotFather, lay token.
2. Trong repo GitHub: **Settings > Secrets and variables > Actions > New repository secret**
   - `TELEGRAM_BOT_TOKEN` = token bot.
   - (tuy chon) `ALLOWED_USER_IDS` = user id cua ban (chan nguoi la).
3. Vao tab **Actions**, bat workflow **"Telegram Bot (chay tren GitHub theo lich)"**.
   - No tu chay moi ~5 phut. Muon test ngay: bam **Run workflow**.
4. Nhan tin cho bot: `/tts` -> gui file -> ... (moi buoc cho toi vai phut vi cron 5 phut/lan).

**Cach hoat dong:** workflow `bot.yml` chay `bot_poll.py`, poll tin nhan (offset luu trong `bot/state/state.json`), tao audio ngay trong lan chay do bang `GITHUB_TOKEN` co san cua Actions, tao Release va nhan tin bao link. Trang thai hoi thoai + file upload tam luu trong `bot/state/` va duoc commit lai sau moi luot.

**Luu y:**
- Do tre: moi buoc hoi thoai cho toi ~5 phut (gioi han cron toi thieu cua GitHub). Neu can tuc thi, dung Cach A.
- File > 20MB: Bot API Telegram khong tai duoc; hay chia nho hoac dung Cach A voi local Bot API server.
- `bot/state/` la thu muc lam viec cua bot; khong sua tay khi bot dang chay.
