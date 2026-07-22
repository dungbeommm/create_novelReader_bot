# HƯỚNG DẪN SỬ DỤNG

Biến file ebook (.txt, .epub, .pdf, .docx, .zip, .mobi...) thành audiobook giọng **Ngọc Huyền**, điều khiển hoàn toàn qua **bot Telegram**.

Có 2 cách chạy bot. Chọn 1 trong 2:

- **Cách 1 — Chạy trên GitHub:** không cần máy/VPS, không cần token cá nhân. Nhược điểm: mỗi bước chờ tới ~5 phút.
- **Cách 2 — Chạy trên máy/VPS:** phản hồi tức thì, nhưng máy phải bật liên tục và cần token GitHub.

---

## CÁCH 1 — CHẠY TRÊN GITHUB (khuyên dùng)

### A. Cài đặt (làm 1 lần)

1. **Đưa code lên GitHub**
   - Tạo repo mới trên GitHub (ví dụ `my-audiobook`).
   - Trong thư mục `project`, chạy:
     ```bash
     cd project
     git init
     git add .
     git commit -m "Audiobook bot"
     git branch -M main
     git remote add origin https://github.com/<TEN-BAN>/my-audiobook.git
     git push -u origin main
     ```

2. **Tạo bot Telegram**
   - Chat với **@BotFather** → `/newbot` → đặt tên → nhận **token**.

3. **(Tùy chọn) Lấy user id của bạn** để chặn người lạ
   - Chat với **@userinfobot** → nó trả về **Id** (dãy số).

4. **Khai báo secret trong repo**
   - Vào repo → **Settings → Secrets and variables → Actions → New repository secret**:
     - `TELEGRAM_BOT_TOKEN` = token ở bước 2
     - `ALLOWED_USER_IDS` = user id ở bước 3 *(bỏ qua nếu muốn ai cũng dùng được)*

5. **Bật workflow**
   - Vào tab **Actions** → bật workflow nếu được hỏi.
   - Chọn **"Telegram Bot (chạy trên GitHub theo lịch)"** → bấm **Run workflow** để chạy ngay.

### B. Dùng hằng ngày (trên Telegram)

1. Gõ **`/tts`**
2. **Gửi file ebook** (đính kèm, dưới 20MB)
3. Nhập **tên truyện** (hoặc `/skip` để dùng tên file)
4. Chọn **tốc độ** (0.9 / 1.0 / 1.1 / 1.3)
5. Chọn **định dạng** (MP3 / M4B / WAV)
6. Bot báo *"Bắt đầu tạo audio..."*
7. Khi xong, bot gửi: *"Truyện: [tên] đã hoàn thành! Link như sau: ..."* kèm link tải.

> ⏳ Bot chạy 5 phút/lần nên mỗi bước có thể chờ tới ~5 phút. Cứ kiên nhẫn, không cần gửi lại.

---

## CÁCH 2 — CHẠY TRÊN MÁY / VPS (phản hồi tức thì)

1. Tạo bot Telegram (như trên), lấy `TELEGRAM_BOT_TOKEN`.
2. Tạo **GitHub fine-grained token** cho đúng repo này, quyền **Contents: Read+Write** và **Actions: Read+Write**.
3. Đưa code lên GitHub (như Cách 1, bước 1).
4. Cấu hình và chạy:
   ```bash
   cd project/bot
   cp .env.example .env      # điền TELEGRAM_BOT_TOKEN, GITHUB_TOKEN, GITHUB_REPO=<TEN-BAN>/my-audiobook
   pip install -r requirements-bot.txt
   set -a; source .env; set +a
   python telegram_bot.py
   ```
5. Dùng trên Telegram y hệt phần B ở trên (`/tts` → gửi file → ...).

---

## LỆNH BOT

| Lệnh | Tác dụng |
|------|----------|
| `/tts`  | Bắt đầu tạo audiobook |
| `/skip` | Bỏ qua đặt tên (dùng tên file) |
| `/start`| Giới thiệu |
| `/help` | Hướng dẫn nhanh |

## ĐỊNH DẠNG FILE HỖ TRỢ

`.txt` `.epub` `.zip` (chứa .txt) `.pdf` `.docx` `.html` `.htm` `.rtf` `.fb2` `.mobi` `.azw3` `.azw`

## LƯU Ý

- **Giới hạn 20MB:** Bot Telegram không tải được file lớn hơn 20MB. Hãy chia nhỏ, hoặc dùng Cách 2.
- **Giọng đọc:** dùng model `voice/ngochuyennew.onnx` có sẵn trong dự án.
- **Xem log/lỗi:** tab **Actions** trên GitHub → mở lần chạy gần nhất.
- **Chạy thử pipeline không cần bot:** xem mục Cách A/B trong `README.md`.
