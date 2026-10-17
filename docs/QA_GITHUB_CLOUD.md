# Kiểm thử bản GitHub / Telegram / Drive / Releases

## Kết quả

- **153 tests passed** khi chạy `python -m pytest tests -q`.
- 37 test mới dành cho cloud/triển khai, cùng 116 test hiện có.
- Môi trường kiểm thử: Linux, Python 3.13; phiên bản workflow dùng Python 3.11 mới nhất do setup-python cung cấp.
- Đã kiểm tra cú pháp Python và phân tích YAML hai workflow.

## Phạm vi mới đã kiểm tra

- Ưu tiên Drive, chuyển Releases khi chưa liên kết, token lỗi hoặc mạng lỗi.
- Biên nhận theo SHA-256 và dùng lại upload đã hoàn tất; phân trang release assets.
- Chặn repo công khai mặc định; checkpoint luôn bắt buộc private.
- Mock OAuth refresh + khởi tạo upload Drive + streaming nội dung, chặn URL upload không thuộc Google.
- AES-256-GCM round trip trên dữ liệu nhiều block, phát hiện ciphertext bị sửa, từ chối khóa sai.
- SQLite WAL backup, loại file tạm/log, chống path traversal/symlink khi giải nén.
- Giữ bản checkpoint trước khi upload lỗi, xoay vòng sau khi upload xong.
- Khôi phục queue từ checkpoint mô phỏng, giữ input gốc, requeue công việc đang chạy.
- Không âm thầm chọn checkpoint cũ khi bản mới nhất lỗi, không ghi đè BOT_DATA đã có.
- Không tạo hai job khi replay cùng Telegram message ID; giới hạn quyền người dùng vẫn được giữ.
- Bot lưu cloud trước khi gửi Telegram, chỉ gửi link khi file lớn, không đánh dấu đã gửi nếu cloud lỗi, không upload tác vụ đã hủy.

## Chưa thể xác minh trong môi trường này

- Không có token hoặc quyền truy cập tài khoản của bạn: chưa gọi Telegram/Drive/GitHub thật cho tính năng mới.
- Không có Docker daemon, self-hosted runner hoặc tài khoản Actions để chạy workflow thật.
- Không chứng minh uptime 24/7; máy chủ riêng cần vận hành và giám sát thực tế.
- Chưa kiểm thử OAuth helper bằng consent Google thật; cần chạy trên máy cá nhân có trình duyệt.
- Chưa chạy bộ test dưới Python 3.11 tại đây. Dự án khuyến nghị 3.11 cho runtime Piper; workflow cài bản 3.11 mới nhất.

## Kiểm tra sau khi triển khai

1. `/start`, `/storage` và một TXT ngắn bằng `/dich`.
2. Bỏ bốn secret Drive để kiểm tra Releases dự phòng trong repo private.
3. Liên kết Drive rồi thử lại; kiểm tra tệp trong NovelReader_Output.
4. Dừng/khởi động lại một tác vụ nhỏ để xác nhận checkpoint và quyền repo.
5. Thử `/full` trên một chương trước khi gửi truyện dài; theo dõi dung lượng, hạn mức Actions và thời gian chạy.
