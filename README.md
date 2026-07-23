# Piper TTS - Giong Ngoc Huyen (Tieng Viet)

Chuyen **van ban tieng Viet** thanh **file audio (.wav)** bang model Piper TTS `ngochuyennew.onnx`.

Project ho tro **3 cach chay**:
1. **GitHub Actions** (khuyen nghi theo yeu cau) - bam chay, nhap text, tai file audio ve.
2. Docker (deploy len Render de co web link real-time).
3. Chay local.

---

## 1. Chay bang GitHub Actions  ⭐

> GitHub Actions **khong phai web server**, nen no khong tao link gui text real-time.
> Cach hoat dong: ban **kich hoat workflow -> nhap van ban -> nhan file audio** (dang artifact hoac Release co link tai co dinh).

### Buoc chuan bi (day code len GitHub)
```bash
cd piper-tts-service
git add .
git commit -m "Them GitHub Actions TTS workflow"
git push
```
File workflow nam o `.github/workflows/tts.yml`.

### Cach chay (giao dien web GitHub)
1. Vao repo tren GitHub -> tab **Actions**.
2. Chon workflow **"Text to Speech (Piper - Ngoc Huyen)"** o cot ben trai.
3. Bam **Run workflow**, dien:
   - **text**: van ban tieng Viet can doc.
   - **filename**: ten file (khong can `.wav`).
   - **length_scale**: toc do (mac dinh 1.0, lon hon = cham hon).
   - **upload_ia**: `true` de tu dong dang len archive.org (link tai co dinh, chia se duoc).
4. Bam **Run workflow** va cho ~2-4 phut.

### Lay file audio
- **Cach A - Artifact:** mo lan chay vua xong -> keo xuong muc **Artifacts** -> tai file `.wav` (can dang nhap GitHub).
- **Cach B - archive.org (co link cong khai):** neu `upload_ia = true`, file duoc dang len https://archive.org/details/<identifier> voi **link tai/nghe truc tiep, chia se duoc** (khong can dang nhap). Link hien o phan Summary cua lan chay.

> Can dat truoc 2 GitHub Secrets `IA_ACCESS_KEY` va `IA_SECRET_KEY` (lay tai
> https://archive.org/account/s3.php). Xem muc **Cai dat archive.org** ben duoi.

### Chay bang dong lenh (tuy chon)
```bash
gh workflow run tts.yml -f text="Xin chao cac ban" -f filename=hello -f upload_ia=true
```

---

## 2. Deploy len Render bang Docker (neu can web link real-time)

Tao service moi tren https://dashboard.render.com -> **New + > Web Service** -> chon repo. Render tu nhan `Dockerfile` (Runtime = Docker), Plan Free -> **Create**.
Sau khi build xong co URL cong khai; mo `/` de nhap text hoac goi API `GET /tts?text=xin+chao`.

> Dung Docker vi `piper-phonemize` chi cai duoc tren **Python <= 3.10** (Render mac dinh Python 3.14 se build loi). Dockerfile da co dinh Python 3.10.

---

## 3. Chay local

### Tao file audio bang script (can Python 3.10)
```bash
pip install -r requirements.txt
python synth.py --text "Xin chao" --out output.wav
```

### Chay web server local
```bash
pip install -r requirements.txt
python app.py    # http://localhost:8000
```

---

## Cau truc project
```
piper-tts-service/
├── .github/workflows/tts.yml   # ⭐ Workflow GitHub Actions: text -> audio
├── synth.py                    # CLI tao file WAV tu text
├── app.py                      # Web server Flask + API /tts (cho Docker/Render/local)
├── Dockerfile                  # Co dinh Python 3.10 (cho Render)
├── render.yaml                 # Cau hinh Render runtime: docker
├── requirements.txt            # piper-tts==1.2.0, flask, gunicorn
├── .dockerignore / .gitignore
└── voice/
    ├── ngochuyennew.onnx        # Model giong noi
    └── ngochuyennew.onnx.json   # Cau hinh model
```


---

# 4. Ebook -> Audiobook tu dong (Telegram + GitHub Actions)

Ngoai cach nhap text ngan o tren, project da them **pipeline chuyen ca cuon ebook
thanh audiobook theo tung chuong**, dieu khien qua bot Telegram. **Toan bo audio
duoc tu dong dang len Internet Archive (archive.org)** thay vi GitHub Release.

## Luong hoat dong
```
Nguoi dung --(gui file + chon option)--> Bot Telegram
   -> Bot day file + job.json len GitHub (jobs/<job_id>/)
   -> Workflow audiobook.yml: tach chuong -> Piper TTS -> convert -> dong goi
   -> Dang tung batch len archive.org (1 audiobook = 1 item)
   -> Khi xong ghi _COMPLETE.json len item
   -> Bot gui lai link https://archive.org/details/<identifier>
```

Moi audiobook la mot **item archive.org** voi identifier **tat dinh** (sinh tu
tieu de + job_id), nen bot biet truoc link va gui ngay khi bat dau; link se day
noi dung dan khi tung batch hoan tat.

## Cau truc bo sung
```
pipeline/
  parse_ebook.py              # Tach ebook (txt/epub/zip/mobi/pdf/docx...) -> chuong
  batch_tts.py                # TTS tung chuong + convert (mp3/wav/m4b) + zip
  requirements-pipeline.txt   # ebooklib, bs4, python-docx, pdfplumber...
pipeline/
  ia_upload.py                # Dang tai len archive.org (IAS3) + sinh identifier
.github/workflows/
  audiobook.yml               # Workflow nhan file ebook -> archive.org
bot/
  telegram_bot.py             # Bot Telegram
  requirements-bot.txt
  .env.example
  README.md                   # Huong dan cai bot
jobs/                         # Noi bot dat file cho xu ly (tu xoa sau khi xong)
```

## Cai dat archive.org (bat buoc)
1. Dang nhap https://archive.org roi mo https://archive.org/account/s3.php de lay
   **access key** va **secret key** (IAS3).
2. Vao repo GitHub -> **Settings > Secrets and variables > Actions > New repository secret**,
   them 2 secret:
   - `IA_ACCESS_KEY`
   - `IA_SECRET_KEY`
3. Xong. Workflow `audiobook.yml` / `tts.yml` se tu dung 2 secret nay de dang tai.

> Mac dinh item duoc dang vao collection cong khai `opensource_audio`, mediatype
> `audio`, ngon ngu `vie`. Co the doi qua bien moi truong `IA_DEFAULT_COLLECTION`
> hoac tham so CLI cua `pipeline/ia_upload.py`.

## Dang tai thu cong bang ia_upload.py (tuy chon)
```bash
export IA_ACCESS_KEY=... IA_SECRET_KEY=...
# Upload 1 file va tao item moi:
python pipeline/ia_upload.py upload --identifier my-audiobook --file batch.zip \
    --make-bucket --title "Ten Truyen" --language vie
# Xem trang thai item:
python pipeline/ia_upload.py status --identifier my-audiobook
```

## Chay thu pipeline (local, khong can bot)
```bash
pip install -r requirements.txt -r pipeline/requirements-pipeline.txt
# 1. Tach chuong
python pipeline/parse_ebook.py --input truyen.epub --out-dir chapters
# 2. Tao audio
python pipeline/batch_tts.py --chapters-dir chapters --out-dir release \
    --title "Ten Truyen" --format mp3 --length-scale 1.0 --package auto
```

## Dinh dang ebook ho tro
`.txt`, `.epub`, `.zip` (chua nhieu txt), `.docx`, `.pdf`, va (khi bat calibre)
`.mobi`, `.azw3`, `.fb2`, `.html`, `.rtf`.

## Tuy chon
- **length_scale**: toc do doc (0.9 nhanh ... 1.3 rat cham).
- **format**: `mp3` (mac dinh), `wav`, `m4b` (audiobook co chapter marks), `ogg`, `opus`.
- **package**: `auto` (tu zip khi nhieu file), `zip`, `single`, `files`.
- **max_chars**: chia nho chuong dai (0 = khong chia).

Xem `bot/README.md` de cai va chay bot Telegram.
