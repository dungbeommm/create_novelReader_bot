# GitHub, Telegram và Google Drive

## Chọn cách chạy

| Phương án | Cách hoạt động | Phù hợp |
|---|---|---|
| **VPS/máy riêng + self-hosted runner** | Actions triển khai Docker rồi kết thúc; container tiếp tục chạy và tự khởi động lại | **Muốn bot hoạt động 24/7**; máy phải luôn bật, có Internet và đủ ổ đĩa |
| **GitHub-hosted Actions** | Chạy một phiên hữu hạn, dừng có kiểm soát và lưu checkpoint mã hóa | Thử nghiệm/chạy theo đợt, không phải dịch vụ 24/7 |

Không có vòng lặp tự kích hoạt workflow hoặc thủ thuật vượt giới hạn GitHub. GitHub-hosted job tối đa 6 giờ; lịch có thể trễ, không chạy đúng giờ, và chịu hạn mức/phí Actions. Lịch mặc định ở phút 17 mỗi giờ, mỗi phiên bot chạy 45 phút **không tính** cài đặt và lưu checkpoint. Có khoảng offline; Telegram giữ cập nhật chưa nhận tối đa khoảng 24 giờ. Không coi đây là lưu hàng đợi dài hạn. Lịch chỉ có hiệu lực trên nhánh mặc định và bị tắt mặc định trong dự án.

**Chỉ chạy một phiên bot cho một token. Không bật cả hosted workflow và bot VPS cùng lúc.** Concurrency của workflow chỉ ngăn hai phiên hosted chồng nhau; không khóa bot đang chạy trên máy khác.

## Luồng lưu kết quả

1. Gửi TXT/EPUB vào bot: `/dich`, `/audio` hoặc `/full`.
2. Bot chạy tác vụ, giữ SQLite/checkpoint và audio theo chương như trước.
3. Với từng tệp hoàn thành, thử lưu lên Drive trước.
4. Không cấu hình Drive, thiếu quyền, hết hạn OAuth hoặc upload lỗi → chuyển sang **GitHub Releases**, một release `novel-job-<mã>` cho mỗi truyện.
5. Bot gửi liên kết nơi lưu và gửi thêm tệp trực tiếp qua Telegram khi tệp không quá 48 MiB. Tệp lớn chỉ gửi liên kết khi đã lưu cloud thành công.
6. `cloud.json` giữ SHA-256 và biên nhận; khi `/retry`, không upload lại tệp đã lưu thành công. Releases dùng tên chứa hash; Drive dùng appProperties để tìm lại upload đã hoàn tất trước lúc tiến trình dừng. Lỗi giữa lúc upload có thể để lại phiên upload Drive chưa hoàn thành; thử lại bắt đầu phiên mới.
7. Nếu cả hai đích lỗi, tác vụ báo lỗi, không giả vờ thành công; sửa cấu hình và `/retry <mã>`.

**Không tự công khai file Drive.** Quyền chia sẻ theo tài khoản/thư mục Drive. Releases kế thừa quyền repository: ai có quyền đọc repo sẽ đọc được kết quả. Đường dẫn của repo private yêu cầu đăng nhập GitHub, không phải liên kết công khai.

`/storage` chỉ hiện trạng thái đã cấu hình, không hiển thị token và không khẳng định kết nối đã hoạt động. Cấu hình Drive là **dùng chung cho toàn bộ bot**, không phải mỗi người một tài khoản Drive.

`/xoa <mã>` chỉ xóa file/checkpoint ở máy đang chạy. Nó **không** xóa bản đã gửi trên Telegram, Drive hay Releases. Với hosted mode, checkpoint cũ được giữ một bản dự phòng: dữ liệu có thể còn trong bản sao trước đó cho đến lần lưu kế tiếp. Muốn xóa triệt để, dừng bot và tự xóa cả hai checkpoint release assets cùng bản cloud/Telegram tương ứng.

## 1. Chuẩn bị repository và Telegram

- Tạo repository **private**. Không đưa `.env`, client secret JSON, `gdrive-secrets.json`, database hay nội dung truyện vào Git.
- Chép mã nguồn, bao gồm `.github/workflows/`, lên repo. Giữ giọng mặc định `models/voices/ngochuyennew.onnx` và `.onnx.json` để workflow dùng được; các model không phải dữ liệu truyện.
- `.gitignore` loại `models/` vì model là file lớn. Gói ZIP này có sẵn giọng đọc. Nếu bạn có quyền phân phối model, thêm riêng giọng mặc định bằng:

```sh
git add -f models/voices/ngochuyennew.onnx models/voices/ngochuyennew.onnx.json
```

- Không cần đưa model dịch lên Git: bot tự tải model QT khi dùng hoặc hosted workflow tải trước. Kiểm tra giấy phép/quyền sử dụng model trước khi phân phối.
- Tạo bot qua `@BotFather`, lấy token. Lấy numeric user ID Telegram của người được phép dùng. Không điền username vào `ALLOWED_USER_IDS`.
- Vào **Settings → Secrets and variables → Actions**, tạo các **Repository secrets** dưới đây. Không gửi thông tin bí mật vào chat.

| Secret | Hosted | VPS | Ý nghĩa |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Bắt buộc | Bắt buộc | Token BotFather |
| `ALLOWED_USER_IDS` | Bắt buộc | Bắt buộc | ID số, cách nhau dấu phẩy |
| `CHECKPOINT_KEY` | Bắt buộc | Không cần | Khóa mã hóa checkpoint, phải giữ nguyên giữa các phiên |
| `GH_RELEASE_TOKEN` | Không cần | Bắt buộc | Fine-grained PAT cho repo đích, quyền **Contents: read/write** |
| `GDRIVE_CLIENT_ID` | Tùy chọn | Tùy chọn | OAuth client ID |
| `GDRIVE_CLIENT_SECRET` | Tùy chọn | Tùy chọn | OAuth client secret |
| `GDRIVE_REFRESH_TOKEN` | Tùy chọn | Tùy chọn | Refresh token được người dùng cấp quyền |
| `GDRIVE_FOLDER_ID` | Tùy chọn | Tùy chọn | Thư mục app được phép ghi |

Hosted workflow dùng `GITHUB_TOKEN` do GitHub tự cấp và `contents: write`. Không dùng token tạm thời này cho bot VPS: token hết hiệu lực khi job kết thúc. Fine-grained PAT phải được cấp đúng repository; org có thể cần phê duyệt. Token hết hạn cần được thay mới.

### Tạo khóa checkpoint trên máy của bạn

```sh
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Lưu kết quả vào secret `CHECKPOINT_KEY`, đồng thời giữ bản sao trong trình quản lý mật khẩu. Đổi/mất khóa sẽ không đọc được checkpoint cũ; chương trình sẽ dừng thay vì âm thầm xóa hàng đợi. Không tạo khóa ngẫu nhiên mới trong mỗi workflow.

## 2. Liên kết Google Drive (tùy chọn)

Nếu bỏ qua bước này, bot trên GitHub/VPS vẫn tải kết quả lên Releases.

### Cách dành cho máy chủ không có trình duyệt

1. Trong Google Cloud, bật **Google Drive API**, cấu hình OAuth consent screen và tạo OAuth client loại **Desktop app**. Nếu app ở chế độ Testing, thêm tài khoản của bạn vào Test users.
2. Tải client JSON về **máy cá nhân**. Không upload lên repository.
3. Cài Python và `requests` trên máy đó rồi chạy từ thư mục dự án:

```sh
pip install requests
python scripts/link_gdrive.py --client-file /duong-dan/client_secret.json
```

4. Mở URL/đồng ý trên chính máy chạy script. Script dùng loopback callback, kiểm tra `state` và PKCE, xin quyền `drive.file`, tự tạo thư mục **NovelReader_Output** và ghi bốn giá trị vào `gdrive-secrets.json`. Không in refresh token vào terminal.
5. Tạo bốn Actions secrets `GDRIVE_*` tương ứng từ tệp đó. Xóa bản tạm hoặc cất vào trình quản lý bí mật. Trên Windows, kiểm tra quyền truy cập tệp cục bộ: chế độ `0600` chỉ được bảo đảm trên hệ Unix.
6. Thư mục do helper tạo nằm trong My Drive của tài khoản bạn chọn. `drive.file` chỉ truy cập tệp/thư mục app được phép dùng; không tùy tiện điền một folder ID khác rồi trông đợi có quyền.

Google OAuth app External ở trạng thái Testing thường cấp refresh token hết hạn sau 7 ngày cho quyền Drive; cần cấu hình consent screen phù hợp cho sử dụng lâu dài và tuân thủ yêu cầu xác minh của Google. Không có token nào được đảm bảo vĩnh viễn. Khi bị thu hồi/hết hạn, bot chuyển sang Releases; chạy helper lại để cấp quyền mới.

### Cấu hình Web có sẵn

Khi chạy bot trên máy riêng, bot cũng đọc `NOVEL_DATA/gdrive_config.json` nếu không dùng biến `GDRIVE_*`. Muốn dùng cấu hình Web, phải cho bot truy cập đúng thư mục dữ liệu Web. Docker mặc định dùng volume riêng; cấu hình Web **không tự được chia sẻ** sang bot. Trên hosted Actions, luôn dùng Secrets, không chép JSON chứa token vào repo/checkpoint.

## 3. Chạy một phiên trên GitHub-hosted Actions

1. Thiết lập secrets và giọng đọc như trên; dùng repo private.
2. Mở **Actions → Telegram bot - bounded hosted session → Run workflow**.
3. Chọn số phút 1–300 (mặc định 45). Trong phiên online, gửi `/start`, `/storage` rồi gửi truyện nhỏ bằng `/dich` để thử.
4. Kiểm tra release `novel-job-<mã>` nếu chưa cấu hình Drive; bot phải gửi link. Kiểm tra `novel-checkpoints` có asset `.enc` sau lần lưu.
5. Chạy một phiên mới để kiểm tra phục hồi tác vụ của bạn trước khi gửi truyện lớn.
6. Muốn lịch theo giờ, thêm **Repository variable** `ENABLE_HOSTED_SCHEDULE=true`. Xóa hoặc đặt `false` để ngừng tạo phiên theo lịch; phiên đang chạy không tự dừng vì đổi biến. Dừng nó trong Actions nếu cần.

Mỗi 15 phút và khi dừng bình thường, runner sao lưu online SQLite, đóng gói **BOT_DATA**, mã hóa **AES-256-GCM** và tải lên release riêng `novel-checkpoints`. Chỉ giữ bản mới + bản trước, xóa bản cũ sau khi upload thành công. Checkpoint không chứa biến môi trường hoặc token Drive cấu hình Web. File TXT/EPUB gốc, queue và audio vẫn là dữ liệu nhạy cảm nên **bắt buộc repo private** kể cả khi checkpoint có mã hóa.

- Giới hạn gói checkpoint nén: **1.8 GiB**; giới hạn giải nén: 12 GiB. Một release asset đầu ra nhỏ hơn 2 GiB.
- Tác vụ đã dừng và chưa `/xoa` vẫn chiếm dung lượng checkpoint. Dọn tác vụ đã nhận xong để tránh đầy ổ/asset quá lớn.
- Mất nguồn, force-cancel hoặc hết timeout cứng có thể khiến lần lưu cuối không chạy. Khi đó chỉ có checkpoint đã upload gần nhất; có thể mất tiến độ/tác vụ nhận sau lần lưu đó.
- Không cam kết gửi Telegram đúng một lần: crash giữa khi gửi thành công và ghi `sent.json` có thể gửi lặp. Gửi lại cùng document update không tạo thêm tác vụ nhờ khóa message ID; không bảo đảm tải file đang nhận dở được phục hồi.
- Bot có thể nhận tin ở phiên sau trong thời gian Telegram còn giữ chúng; không gửi liên tục khi bot offline dài ngày.
- Không cache token/database bằng Actions cache hoặc upload-artifact công khai.

## 4. Chạy 24/7 trên VPS/máy riêng (khuyến nghị)

Máy Linux x86_64 luôn bật, Docker Engine + Compose v2 hỗ trợ `--wait`, Git, rsync; khuyến nghị ít nhất 2 CPU, 4 GB RAM và vài chục GB trống cho truyện/audio.

1. Đăng ký **GitHub self-hosted runner** trên máy đó, thêm label `novel-bot`, và cài runner thành **system service** theo hướng dẫn GitHub.
2. Chỉ dùng runner này cho repo private đáng tin cậy, không nhận workflow PR từ người lạ. Runner user cần quyền dùng Docker (quyền này tương đương quyền quản trị máy).
3. Tạo thư mục triển khai riêng, ví dụ `/srv/novel-bot`, và cấp quyền ghi cho runner user. Không dùng thư mục checkout tạm `_work` làm nơi lưu lâu dài.
4. Thêm Repository variable `NOVEL_DEPLOY_DIR=/srv/novel-bot`.
5. Tạo GitHub Environment `bot-production`; có thể đặt approval để bảo vệ bước triển khai. Thiết lập Secrets phù hợp (Repository secrets được workflow dùng mặc định).
6. Đặt `GH_RELEASE_TOKEN` là PAT dài hạn, chỉ cho repo private này quyền Contents read/write. Workflow ghi `.env` quyền `0600`, không in giá trị ra log.
7. Chạy **Actions → Deploy persistent bot on your own server**. Workflow build hai image, khởi động Docker rồi kết thúc; **bot không phụ thuộc job Actions phải tiếp tục chạy**.
8. Bật Docker khởi động cùng hệ điều hành, ví dụ `sudo systemctl enable --now docker`. Hai service dùng `restart: unless-stopped`.

Triển khai dùng `compose.github.yaml` để model dịch nằm trong Docker named volume có quyền ghi, tránh lỗi bind mount UID 10001. Queue/checkpoint và cache cũng nằm ở named volumes; một lần deploy không xóa chúng. **Không chạy `docker compose down -v` nếu muốn giữ dữ liệu.** Không bật hosted schedule khi đang dùng bot VPS.

```sh
cd /srv/novel-bot
docker compose -f compose.yaml -f compose.github.yaml ps
docker compose -f compose.yaml -f compose.github.yaml logs --tail=100 bot
# Dừng rõ ràng (restart unless-stopped sẽ không tự bật lại service đã stop)
docker compose -f compose.yaml -f compose.github.yaml stop bot tts
# Chạy lại
docker compose -f compose.yaml -f compose.github.yaml up -d tts bot
```

Deployment workflow bảo toàn state/config hiện có, không tự sao lưu ổ VPS. Hãy sao lưu Docker volumes bằng công cụ máy chủ phù hợp. Tắt máy, mất Internet, hết dung lượng hoặc lỗi model vẫn khiến bot ngừng phục vụ; “24/7” là cách triển khai, không phải cam kết uptime.

## 5. Khắc phục nhanh

| Triệu chứng | Kiểm tra |
|---|---|
| Bot không trả lời | Phiên có đang chạy không? Token đúng? `ALLOWED_USER_IDS` có ID số của bạn? Có hai bot cùng token gây 409 Conflict? |
| Drive bị bỏ qua | Đủ cả 4 secret? Folder do đúng OAuth app tạo? Refresh token còn hiệu lực? `/storage` chỉ kiểm tra cấu hình, không kiểm tra quyền |
| Releases 403 | `contents: write`/PAT Contents read-write, repo đúng và private, org đã phê duyệt token chưa? |
| Checkpoint không đọc được | Giữ đúng `CHECKPOINT_KEY`; không xóa release để thử tùy tiện. Tải bản mã hóa về và sao lưu trước khi khôi phục thủ công |
| Checkpoint quá lớn | `/xoa` tác vụ cũ rồi lưu lại, hoặc chuyển VPS. Chưa có tự chia checkpoint nhiều asset |
| Thiếu voice khi hosted/deploy | File `.onnx` bị `.gitignore` bỏ qua; thêm giọng mặc định hoặc cung cấp model hợp lệ trước khi chạy |
| Gửi Telegram lặp | Có thể xảy ra khi khởi động lại đúng lúc gửi; `cloud.json` tránh tải lại kết quả đã lưu có cùng hash |

## Kiểm thử và giới hạn xác minh

```sh
pip install -r telegram/requirements.txt pytest httpx pyyaml
python -m pytest tests -q
```

Test giả lập GitHub/Drive/Telegram, kiểm tra fallback, chặn public repo, checkpoint mã hóa/chống sửa dữ liệu, SQLite WAL, chống path traversal, lưu biên nhận, file Telegram quá lớn và phục hồi queue. Không có credentials của bạn nên không thể xác minh kết nối thật, quyền Google, chạy workflow thật hoặc uptime 24/7 từ gói ZIP này. Hãy thử một truyện nhỏ, kiểm tra cloud và khởi động lại trước khi xử lý dữ liệu quan trọng.

Tham khảo giới hạn nhà cung cấp:
- https://docs.github.com/en/actions/reference/limits
- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
- https://docs.github.com/en/actions/concepts/runners/self-hosted-runners
- https://developers.google.com/identity/protocols/oauth2#expiration
- https://core.telegram.org/bots/api#getting-updates
