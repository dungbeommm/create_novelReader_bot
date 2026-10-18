"""Private Telegram frontend with interactive inline buttons, chapter range, and audio grouping."""
import asyncio
import contextlib
import json
import logging
import os
import shutil
import sys
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from state import State

ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = Path(__file__).resolve().parent

# Tự động nạp cấu hình từ .env nếu có
for env_file in (ROOT / '.env', BOT_DIR / '.env'):
    if env_file.is_file():
        for line in env_file.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"\''))

os.environ.setdefault('TTS_URL', 'http://127.0.0.1:8010')

DATA = Path(os.getenv('BOT_DATA', str(ROOT / 'data/telegram'))).resolve()
state = State(DATA)
ALLOWED = {int(x.strip()) for x in os.getenv('ALLOWED_USER_IDS', '').split(',') if x.strip()}
LIMIT = 19 * 1024**2
process = None
log = logging.getLogger(__name__)

PENDING_DIR = DATA / 'pending'
PENDING_DIR.mkdir(parents=True, exist_ok=True)

AWAITING_INPUT = {}

DEFAULT_SETTINGS = {
    'mode': 'full',               # 'full', 'translate', 'audio'
    'engine': 'HachimiMT-60-QT',  # Model AI dịch
    'beam_size': 2,               # 1, 2, 4
    'honorific_mode': 'safe',     # 'safe', 'xianxia_strict', 'off'
    'pronoun_harmonizer': True,   # True, False
    'chunk_mode': 'sentence',     # 'sentence', 'paragraph'
    'audio_speed': 1.0,           # 0.9, 1.0, 1.1, 1.25
    'start_pos': None,            # int | None
    'end_pos': None,              # int | None
    'group_size': 1,              # 1 = không gộp, >1 = gộp N chương thành 1 file
}

ENGINE_NAMES = {
    'HachimiMT-60-QT': 'Hachimi 60-QT (Tiên hiệp/Cổ trang)',
    'HachimiMT-60': 'Hachimi 60 (Hiện đại/Đô thị)',
    'HachimiMT-40-QT': 'Hachimi 40-QT (Nhanh & nhẹ)',
    'HachimiMT-30': 'Hachimi 30 (Siêu nhẹ)',
    'MoxhiMT-60': 'Moxhi 60 (Kiếm hiệp)',
    'MoxhiMT-30-QT': 'Moxhi 30-QT (Cổ trang nhẹ)',
    'HirashibaMT-Medium': 'Hirashiba Medium (Chất lượng cao)',
}

MODE_NAMES = {
    'full': '🌐 Dịch + 🔊 Audio',
    'translate': '📝 Chỉ dịch (TXT + EPUB)',
    'audio': '🔊 Chỉ audio tiếng Việt',
}

BEAM_NAMES = {
    1: '⚡ 1 (Nhanh)',
    2: '⚖️ 2 (Chuẩn - Khuyên dùng)',
    4: '🎯 4 (Kỹ - Cao cấp)',
}

HONORIFIC_NAMES = {
    'safe': '🛡️ An toàn (Safe)',
    'xianxia_strict': '⚔️ Tiên hiệp nghiêm ngặt',
    'off': '⭕ Tắt',
}

CHUNK_NAMES = {
    'sentence': '✂️ Theo câu (Sentence)',
    'paragraph': '📄 Theo đoạn (Paragraph)',
}

HELP = '''📚 Dịch truyện Trung → Việt và audio Ngọc Huyền

✨ Hướng dẫn sử dụng:
1. Gửi file TXT hoặc EPUB (tối đa 19 MB).
2. Bot gửi bảng nút bấm để tùy chỉnh:
   • Model AI dịch (Tiên hiệp, đô thị, kiếm hiệp...)
   • Dải chương cần dịch (Toàn bộ, hoặc từ chương X đến Y)
   • Số chương sẽ gộp vào 1 file audio (Không gộp, gộp 5, 10, 20...)
   • Mức độ dịch (Beam size), xưng hô, đại từ V9, tốc độ đọc...
3. Bấm [▶️ Bắt đầu xử lý] để chạy.

Các lệnh điều khiển:
/cauhinh hoặc /settings — Xem và tùy chỉnh cấu hình mặc định bằng nút bấm
/full — Chọn chế độ dịch + audio
/dich — Chọn chế độ chỉ dịch văn bản
/audio — Chọn chế độ chỉ tạo audio
/status — Xem tiến độ và mã tác vụ
/cancel <mã> — Hủy tác vụ
/retry <mã> — Tiếp tục tác vụ lỗi/đã hủy
/xoa <mã> — Xóa dữ liệu tác vụ đã dừng
'''

async def permitted(u):
    user = u.effective_user
    chat = u.effective_chat
    if not user or not chat or chat.type != 'private':
        return False
    if user.id not in ALLOWED:
        if u.effective_message:
            await u.effective_message.reply_text('Bot riêng tư. Tài khoản chưa được cấp quyền.')
        return False
    return True

def get_user_cfg(uid):
    saved = state.get_settings(uid)
    cfg = dict(DEFAULT_SETTINGS)
    cfg.update(saved)
    return cfg

def save_user_cfg(uid, cfg):
    return state.update_settings(uid, cfg)

def get_pending(uid):
    p = PENDING_DIR / str(uid)
    meta_file = p / 'meta.json'
    bin_file = p / 'file.bin'
    if meta_file.exists() and bin_file.exists():
        try:
            return json.loads(meta_file.read_text(encoding='utf-8'))
        except Exception:
            pass
    return None

def save_pending(uid, meta):
    p = PENDING_DIR / str(uid)
    p.mkdir(parents=True, exist_ok=True)
    (p / 'meta.json').write_text(json.dumps(meta, ensure_ascii=False), encoding='utf-8')

def clear_pending(uid):
    p = PENDING_DIR / str(uid)
    shutil.rmtree(p, ignore_errors=True)

def format_scope(start_pos, end_pos):
    if not start_pos and not end_pos:
        return 'Toàn bộ'
    if start_pos and end_pos:
        return f"Chương {start_pos} - {end_pos}"
    if start_pos:
        return f"Từ chương {start_pos} đến hết"
    return f"{end_pos} chương đầu"

def format_group(group_size):
    if not group_size or int(group_size) <= 1:
        return 'Không gộp (Từng chương)'
    return f"Gộp {group_size} chương / file"

def build_main_menu(uid, meta=None):
    cfg = meta['config'] if meta else get_user_cfg(uid)
    mode = cfg.get('mode', 'full')
    engine = cfg.get('engine', 'HachimiMT-60-QT')
    beam = int(cfg.get('beam_size', 2))
    honor = cfg.get('honorific_mode', 'safe')
    pronoun = bool(cfg.get('pronoun_harmonizer', True))
    chunk = cfg.get('chunk_mode', 'sentence')
    speed = float(cfg.get('audio_speed', 1.0))
    start_pos = cfg.get('start_pos')
    end_pos = cfg.get('end_pos')
    group_size = int(cfg.get('group_size', 1))

    scope_str = format_scope(start_pos, end_pos)
    group_str = format_group(group_size)

    if meta:
        title = f"📚 Truyện chờ xử lý: *{meta['filename']}* ({meta.get('file_size_mb', 0)} MB)"
        footer = "👉 *Bấm các nút dưới đây để tùy chỉnh tính năng, sau đó bấm [▶️ Bắt đầu xử lý]:*"
    else:
        title = "⚙️ *BẢNG CẤU HÌNH TÍNH NĂNG MẶC ĐỊNH*"
        footer = "👉 *Bấm để thay đổi cấu hình mặc định (tự áp dụng cho các file gửi sau này):*"

    if mode == 'audio':
        scope_line = f"• Dải chương làm audio: 📖 *{scope_str}*"
        scope_btn = f"📖 Dải chương audio: {scope_str}"
    elif mode == 'full':
        scope_line = f"• Dải chương (dịch + audio): 📖 *{scope_str}*"
        scope_btn = f"📖 Dải chương: {scope_str}"
    else:
        scope_line = f"• Dải chương dịch: 📖 *{scope_str}*"
        scope_btn = f"📖 Dải chương dịch: {scope_str}"

    text = (
        f"{title}\n\n"
        f"📌 *Cấu hình hiện tại:*\n"
        f"• Chế độ: {MODE_NAMES.get(mode, mode)}\n"
        f"{scope_line}\n"
        f"• Gộp audio: 📦 *{group_str}*\n"
        f"• Model AI: {ENGINE_NAMES.get(engine, engine)}\n"
        f"• Mức độ dịch (Beam): {BEAM_NAMES.get(beam, beam)}\n"
        f"• Chuẩn hóa xưng hô: {HONORIFIC_NAMES.get(honor, honor)}\n"
        f"• Đại từ V9: {'✅ Bật' if pronoun else '❌ Tắt'}\n"
        f"• Phân đoạn: {CHUNK_NAMES.get(chunk, chunk)}\n"
        f"• Tốc độ audio: ⏱️ {speed}x\n\n"
        f"{footer}"
    )

    kb = [
        [InlineKeyboardButton(f"🔄 Chế độ: {MODE_NAMES.get(mode, mode).split()[1]}", callback_data="menu:mode")],
        [
            InlineKeyboardButton(scope_btn, callback_data="menu:scope"),
        ],
        [
            InlineKeyboardButton(f"📦 Gộp audio: {group_str}", callback_data="menu:group"),
        ],
        [
            InlineKeyboardButton(f"🤖 Model: {engine.replace('HachimiMT-','H-').replace('MoxhiMT-','M-')}", callback_data="menu:engine"),
            InlineKeyboardButton(f"⚡ Mức độ: Beam {beam}", callback_data="menu:beam"),
        ],
        [
            InlineKeyboardButton(f"🎭 Xưng hô: {honor}", callback_data="menu:honorific"),
            InlineKeyboardButton(f"👥 Đại từ V9: {'Bật' if pronoun else 'Tắt'}", callback_data="toggle:pronoun"),
        ],
        [
            InlineKeyboardButton(f"✂️ Đoạn: {'Câu' if chunk=='sentence' else 'Đoạn'}", callback_data="toggle:chunk"),
            InlineKeyboardButton(f"⏱️ Tốc độ: {speed}x", callback_data="menu:speed"),
        ],
    ]

    if meta:
        kb.append([
            InlineKeyboardButton("▶️ BẮT ĐẦU XỬ LÝ", callback_data="action:start"),
            InlineKeyboardButton("❌ HỦY BỎ", callback_data="action:cancel_pending"),
        ])
    else:
        kb.append([
            InlineKeyboardButton("💾 LƯU MẶC ĐỊNH", callback_data="action:save_settings"),
            InlineKeyboardButton("❌ ĐÓNG", callback_data="action:close"),
        ])

    return text, InlineKeyboardMarkup(kb)

def build_scope_menu(cfg):
    start_pos = cfg.get('start_pos')
    end_pos = cfg.get('end_pos')
    cur = format_scope(start_pos, end_pos)
    text = (
        f"📖 *CHỌN SỐ CHƯƠNG SẼ DỊCH:*\n\n"
        f"Hiện tại: *{cur}*\n\n"
        f"Chọn nhanh các mức phổ biến bên dưới hoặc bấm nút *Tự nhập dải chương*:"
    )
    kb = [
        [
            InlineKeyboardButton("Toàn bộ truyện", callback_data="set:scope:all"),
            InlineKeyboardButton("5 chương đầu", callback_data="set:scope:1-5"),
        ],
        [
            InlineKeyboardButton("10 chương đầu", callback_data="set:scope:1-10"),
            InlineKeyboardButton("20 chương đầu", callback_data="set:scope:1-20"),
        ],
        [
            InlineKeyboardButton("50 chương đầu", callback_data="set:scope:1-50"),
            InlineKeyboardButton("100 chương đầu", callback_data="set:scope:1-100"),
        ],
        [
            InlineKeyboardButton("✏️ Tự nhập dải chương (VD: 1-50 hoặc 10)", callback_data="ask:scope"),
        ],
        [InlineKeyboardButton("🔙 Quay lại", callback_data="menu:main")],
    ]
    return text, InlineKeyboardMarkup(kb)

def build_group_menu(cfg):
    cur_size = int(cfg.get('group_size', 1))
    cur = format_group(cur_size)
    text = (
        f"📦 *CHỌN SỐ CHƯƠNG GỘP AUDIO:*\n\n"
        f"Hiện tại: *{cur}*\n\n"
        f"Gộp nhiều chương vào một file MP3 giúp bạn nghe liền mạch và tránh ngập tin nhắn trên Telegram:"
    )
    kb = [
        [
            InlineKeyboardButton(f"{'✅ ' if cur_size<=1 else ''}Không gộp (Từng chương)", callback_data="set:group:1"),
            InlineKeyboardButton(f"{'✅ ' if cur_size==5 else ''}Gộp 5 chương / file", callback_data="set:group:5"),
        ],
        [
            InlineKeyboardButton(f"{'✅ ' if cur_size==10 else ''}Gộp 10 chương / file", callback_data="set:group:10"),
            InlineKeyboardButton(f"{'✅ ' if cur_size==20 else ''}Gộp 20 chương / file", callback_data="set:group:20"),
        ],
        [
            InlineKeyboardButton(f"{'✅ ' if cur_size==50 else ''}Gộp 50 chương / file", callback_data="set:group:50"),
        ],
        [
            InlineKeyboardButton("✏️ Tự nhập số chương gộp", callback_data="ask:group"),
        ],
        [InlineKeyboardButton("🔙 Quay lại", callback_data="menu:main")],
    ]
    return text, InlineKeyboardMarkup(kb)

def build_mode_menu(cfg):
    cur = cfg.get('mode', 'full')
    text = "🔄 *CHỌN CHẾ ĐỘ XỬ LÝ:*\n\nChọn một trong các chế độ bên dưới:"
    kb = [
        [InlineKeyboardButton(f"{'✅ ' if cur=='full' else ''}🌐 Dịch + Audio Ngọc Huyền", callback_data="set:mode:full")],
        [InlineKeyboardButton(f"{'✅ ' if cur=='translate' else ''}📝 Chỉ dịch văn bản (TXT + EPUB)", callback_data="set:mode:translate")],
        [InlineKeyboardButton(f"{'✅ ' if cur=='audio' else ''}🔊 Chỉ tạo audio truyện tiếng Việt", callback_data="set:mode:audio")],
        [InlineKeyboardButton("🔙 Quay lại", callback_data="menu:main")],
    ]
    return text, InlineKeyboardMarkup(kb)

def build_engine_menu(cfg):
    cur = cfg.get('engine', 'HachimiMT-60-QT')
    text = "🤖 *CHỌN MODEL AI DỊCH THUẬT:*\n\nChọn model phù hợp với thể loại truyện của bạn:"
    models = [
        ('HachimiMT-60-QT', 'Hachimi 60-QT (Tiên hiệp/Cổ trang) ⭐'),
        ('HachimiMT-60', 'Hachimi 60 (Hiện đại/Đô thị)'),
        ('HachimiMT-40-QT', 'Hachimi 40-QT (Nhanh & nhẹ)'),
        ('HachimiMT-30', 'Hachimi 30 (Siêu nhẹ)'),
        ('MoxhiMT-60', 'Moxhi 60 (Kiếm hiệp cổ điển)'),
        ('MoxhiMT-30-QT', 'Moxhi 30-QT (Cổ trang nhẹ)'),
        ('HirashibaMT-Medium', 'Hirashiba Medium (Chất lượng cao)'),
    ]
    kb = []
    for mid, name in models:
        prefix = '✅ ' if cur == mid else ''
        kb.append([InlineKeyboardButton(f"{prefix}{name}", callback_data=f"set:engine:{mid}")])
    kb.append([InlineKeyboardButton("🔙 Quay lại", callback_data="menu:main")])
    return text, InlineKeyboardMarkup(kb)

def build_beam_menu(cfg):
    cur = int(cfg.get('beam_size', 2))
    text = (
        "⚡ *CHỌN MỨC ĐỘ DỊCH (BEAM SIZE):*\n\n"
        "• *Beam 1*: Tốc độ nhanh nhất, tiêu tốn ít RAM nhất.\n"
        "• *Beam 2*: Chuẩn (Khuyên dùng), cân bằng hoàn hảo giữa tốc độ và độ mượt câu chữ.\n"
        "• *Beam 4*: Dịch sâu, trau chuốt tối đa, thời gian dịch lâu hơn."
    )
    kb = [
        [InlineKeyboardButton(f"{'✅ ' if cur==1 else ''}⚡ Beam 1 (Nhanh)", callback_data="set:beam_size:1")],
        [InlineKeyboardButton(f"{'✅ ' if cur==2 else ''}⚖️ Beam 2 (Chuẩn - Khuyên dùng)", callback_data="set:beam_size:2")],
        [InlineKeyboardButton(f"{'✅ ' if cur==4 else ''}🎯 Beam 4 (Kỹ - Cao cấp)", callback_data="set:beam_size:4")],
        [InlineKeyboardButton("🔙 Quay lại", callback_data="menu:main")],
    ]
    return text, InlineKeyboardMarkup(kb)

def build_honorific_menu(cfg):
    cur = cfg.get('honorific_mode', 'safe')
    text = (
        "🎭 *CHẾ ĐỘ CHUẨN HÓA XƯNG HÔ:*\n\n"
        "• *Safe (An toàn)*: Tự động sửa cách xưng hô gia đình, họ hàng, tôn ti cơ bản.\n"
        "• *Tiên hiệp nghiêm ngặt*: Xử lý chuyên sâu ngữ cảnh cổ trang, tiên kiếm hiệp.\n"
        "• *Tắt*: Giữ nguyên bản dịch thô từ model."
    )
    kb = [
        [InlineKeyboardButton(f"{'✅ ' if cur=='safe' else ''}🛡️ An toàn (Safe)", callback_data="set:honorific_mode:safe")],
        [InlineKeyboardButton(f"{'✅ ' if cur=='xianxia_strict' else ''}⚔️ Tiên hiệp nghiêm ngặt", callback_data="set:honorific_mode:xianxia_strict")],
        [InlineKeyboardButton(f"{'✅ ' if cur=='off' else ''}⭕ Tắt", callback_data="set:honorific_mode:off")],
        [InlineKeyboardButton("🔙 Quay lại", callback_data="menu:main")],
    ]
    return text, InlineKeyboardMarkup(kb)

def build_speed_menu(cfg):
    cur = float(cfg.get('audio_speed', 1.0))
    text = "⏱️ *CHỌN TỐC ĐỘ ĐỌC AUDIO (TTS NGỌC HUYỀN):*\n\nĐiều chỉnh tốc độ đọc phù hợp với sở thích nghe của bạn:"
    speeds = [
        (0.9, '0.9x (Chậm rãi, truyền cảm)'),
        (1.0, '1.0x (Chuẩn bình thường) ⭐'),
        (1.1, '1.1x (Hơi nhanh)'),
        (1.25, '1.25x (Nhanh)'),
    ]
    kb = []
    for spd, label in speeds:
        prefix = '✅ ' if abs(cur - spd) < 0.01 else ''
        kb.append([InlineKeyboardButton(f"{prefix}{label}", callback_data=f"set:audio_speed:{spd}")])
    kb.append([InlineKeyboardButton("🔙 Quay lại", callback_data="menu:main")])
    return text, InlineKeyboardMarkup(kb)

async def start(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not await permitted(u): return
    text = (
        "📚 **HỆ THỐNG DỊCH TRUYỆN TRUNG → VIỆT & AUDIO NGỌC HUYỀN**\n\n"
        "✨ **Cách sử dụng:**\n"
        "1. Gửi file truyện **.TXT** hoặc **.EPUB** (tối đa 19 MB).\n"
        "2. Bot sẽ gửi bảng nút chọn trực tiếp để bạn tùy chỉnh:\n"
        "   • Số chương sẽ dịch (Toàn bộ hoặc khoảng chương mong muốn)\n"
        "   • Số chương gộp vào mỗi file audio\n"
        "   • Model AI, mức độ dịch, xưng hô, tốc độ đọc...\n"
        "3. Tùy chỉnh theo ý muốn rồi bấm **[▶️ Bắt đầu xử lý]**.\n\n"
        "⚙️ Bạn có thể bấm các nút dưới đây để thiết lập sẵn cấu hình mặc định hoặc xem tiến độ:"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Cài đặt tính năng dịch & audio", callback_data="menu:main")],
        [
            InlineKeyboardButton("📊 Tiến độ tác vụ (/status)", callback_data="action:status"),
            InlineKeyboardButton("📖 Hướng dẫn chi tiết", callback_data="action:help"),
        ]
    ])
    await u.message.reply_text(text, reply_markup=kb, parse_mode='Markdown')

async def settings_cmd(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not await permitted(u): return
    uid = u.effective_user.id
    meta = get_pending(uid)
    text, markup = build_main_menu(uid, meta)
    await u.message.reply_text(text, reply_markup=markup, parse_mode='Markdown')

async def mode_cmd(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not await permitted(u): return
    cmd = u.message.text.split()[0].split('@')[0]
    val = {'/full': 'full', '/dich': 'translate', '/audio': 'audio'}[cmd]
    uid = u.effective_user.id
    cfg = get_user_cfg(uid)
    cfg['mode'] = val
    save_user_cfg(uid, cfg)
    meta = get_pending(uid)
    if meta:
        meta['mode'] = val
        meta['config']['mode'] = val
        save_pending(uid, meta)
    await u.message.reply_text(f'Đã chọn chế độ: {MODE_NAMES.get(val, val)}.')

async def document(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not await permitted(u): return
    doc = u.message.document
    suffix = Path(doc.file_name or '').suffix.lower()
    if suffix not in ('.txt', '.epub'):
        await u.message.reply_text('Bản này chỉ nhận TXT hoặc EPUB.')
        return
    if doc.file_size is None or doc.file_size > LIMIT:
        await u.message.reply_text('File phải nhỏ hơn 19 MB. Hãy chia tập.')
        return
    if shutil.disk_usage(DATA).free < 3 * 1024**3:
        await u.message.reply_text('Máy chủ còn dưới 3 GB trống; cần dọn dữ liệu.')
        return
    try:
        file = await doc.get_file(read_timeout=120)
        data = bytes(await file.download_as_bytearray(read_timeout=120))
        if len(data) > LIMIT:
            raise ValueError('File quá lớn.')
        uid = u.effective_user.id
        p = PENDING_DIR / str(uid)
        p.mkdir(parents=True, exist_ok=True)
        (p / 'file.bin').write_bytes(data)

        cfg = get_user_cfg(uid)
        size_mb = round(len(data) / (1024 * 1024), 2)
        meta = {
            'filename': doc.file_name or f"input{suffix}",
            'suffix': suffix,
            'file_size_mb': size_mb,
            'chat_id': u.effective_chat.id,
            'mode': cfg.get('mode', 'full'),
            'config': cfg,
        }
        save_pending(uid, meta)
        text, markup = build_main_menu(uid, meta)
        await u.message.reply_text(text, reply_markup=markup, parse_mode='Markdown')
    except Exception:
        log.exception('Receive failed')
        await u.message.reply_text('Chưa nhận được truyện: có thể Telegram lỗi hoặc bộ nhớ đầy. Thử lại sau.')

async def on_text_message(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not await permitted(u): return
    uid = u.effective_user.id
    if uid not in AWAITING_INPUT:
        return

    mode = AWAITING_INPUT.pop(uid)
    raw = (u.message.text or '').strip()
    meta = get_pending(uid)
    cfg = meta['config'] if meta else get_user_cfg(uid)

    if mode == 'scope':
        low = raw.lower()
        if low in ('0', 'all', 'tat ca', 'toan bo', '*'):
            cfg['start_pos'] = None
            cfg['end_pos'] = None
            desc = "Toàn bộ truyện"
        elif '-' in low:
            parts = low.split('-', 1)
            s_val = int(parts[0].strip()) if parts[0].strip().isdigit() else None
            e_val = int(parts[1].strip()) if parts[1].strip().isdigit() else None
            cfg['start_pos'] = s_val
            cfg['end_pos'] = e_val
            desc = format_scope(s_val, e_val)
        elif low.isdigit():
            val = int(low)
            cfg['start_pos'] = 1
            cfg['end_pos'] = val
            desc = f"Chương 1 - {val}"
        else:
            AWAITING_INPUT[uid] = 'scope'
            await u.message.reply_text(
                "⚠️ Định dạng không đúng.\n"
                "Hãy nhập ví dụ:\n"
                "• `1-50` (Chương 1 đến 50)\n"
                "• `20` (20 chương đầu)\n"
                "• `5-` (Từ chương 5 đến hết)\n"
                "• `all` (Toàn bộ truyện)",
                parse_mode='Markdown'
            )
            return

        if meta:
            save_pending(uid, meta)
        else:
            save_user_cfg(uid, cfg)

        await u.message.reply_text(f"✅ Đã chọn dải chương dịch: *{desc}*", parse_mode='Markdown')
        text, markup = build_main_menu(uid, meta)
        await u.message.reply_text(text, reply_markup=markup, parse_mode='Markdown')

    elif mode == 'group':
        if not raw.isdigit():
            AWAITING_INPUT[uid] = 'group'
            await u.message.reply_text(
                "⚠️ Vui lòng nhập một số nguyên dương.\n"
                "Ví dụ: `10` để gộp 10 chương thành 1 file MP3, hoặc `1` để không gộp.",
                parse_mode='Markdown'
            )
            return

        val = max(1, int(raw))
        cfg['group_size'] = val
        if meta:
            save_pending(uid, meta)
        else:
            save_user_cfg(uid, cfg)

        desc = format_group(val)
        await u.message.reply_text(f"✅ Đã đặt gộp audio: *{desc}*", parse_mode='Markdown')
        text, markup = build_main_menu(uid, meta)
        await u.message.reply_text(text, reply_markup=markup, parse_mode='Markdown')

async def on_callback(u: Update, c: ContextTypes.DEFAULT_TYPE):
    q = u.callback_query
    await q.answer()
    if not await permitted(u): return

    uid = u.effective_user.id
    data = q.data or ''
    AWAITING_INPUT.pop(uid, None)
    meta = get_pending(uid)
    cfg = meta['config'] if meta else get_user_cfg(uid)

    if data == 'menu:main':
        text, markup = build_main_menu(uid, meta)
        await q.edit_message_text(text, reply_markup=markup, parse_mode='Markdown')

    elif data == 'menu:scope':
        text, markup = build_scope_menu(cfg)
        await q.edit_message_text(text, reply_markup=markup, parse_mode='Markdown')

    elif data == 'menu:group':
        text, markup = build_group_menu(cfg)
        await q.edit_message_text(text, reply_markup=markup, parse_mode='Markdown')

    elif data == 'menu:mode':
        text, markup = build_mode_menu(cfg)
        await q.edit_message_text(text, reply_markup=markup, parse_mode='Markdown')

    elif data == 'menu:engine':
        text, markup = build_engine_menu(cfg)
        await q.edit_message_text(text, reply_markup=markup, parse_mode='Markdown')

    elif data == 'menu:beam':
        text, markup = build_beam_menu(cfg)
        await q.edit_message_text(text, reply_markup=markup, parse_mode='Markdown')

    elif data == 'menu:honorific':
        text, markup = build_honorific_menu(cfg)
        await q.edit_message_text(text, reply_markup=markup, parse_mode='Markdown')

    elif data == 'menu:speed':
        text, markup = build_speed_menu(cfg)
        await q.edit_message_text(text, reply_markup=markup, parse_mode='Markdown')

    elif data == 'ask:scope':
        AWAITING_INPUT[uid] = 'scope'
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Hủy và quay lại", callback_data="menu:scope")]])
        await q.edit_message_text(
            "✍️ *HÃY NHẬP DẢI CHƯƠNG BẠN MUỐN DỊCH:*\n\n"
            "Gửi tin nhắn phản hồi theo các ví dụ sau:\n"
            "• `1-50` : Dịch từ chương 1 đến chương 50\n"
            "• `20` : Dịch 20 chương đầu (1 đến 20)\n"
            "• `5-` : Dịch từ chương 5 đến hết\n"
            "• `all` : Dịch toàn bộ truyện\n\n"
            "👉 *Hãy gõ tin nhắn dải chương của bạn ngay bên dưới:*",
            reply_markup=kb,
            parse_mode='Markdown'
        )

    elif data == 'ask:group':
        AWAITING_INPUT[uid] = 'group'
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Hủy và quay lại", callback_data="menu:group")]])
        await q.edit_message_text(
            "✍️ *HÃY NHẬP SỐ CHƯƠNG MUỐN GỘP:*\n\n"
            "Nhập số nguyên (ví dụ: `15` để gộp mỗi 15 chương thành 1 file MP3).\n"
            "Nhập `1` nếu muốn để từng chương riêng lẻ.\n\n"
            "👉 *Hãy gõ tin nhắn số chương gộp ngay bên dưới:*",
            reply_markup=kb,
            parse_mode='Markdown'
        )

    elif data == 'toggle:pronoun':
        cfg['pronoun_harmonizer'] = not cfg.get('pronoun_harmonizer', True)
        if meta:
            save_pending(uid, meta)
        else:
            save_user_cfg(uid, cfg)
        text, markup = build_main_menu(uid, meta)
        await q.edit_message_text(text, reply_markup=markup, parse_mode='Markdown')

    elif data == 'toggle:chunk':
        cur = cfg.get('chunk_mode', 'sentence')
        cfg['chunk_mode'] = 'paragraph' if cur == 'sentence' else 'sentence'
        if meta:
            save_pending(uid, meta)
        else:
            save_user_cfg(uid, cfg)
        text, markup = build_main_menu(uid, meta)
        await q.edit_message_text(text, reply_markup=markup, parse_mode='Markdown')

    elif data.startswith('set:scope:'):
        val = data.split(':', 2)[2]
        if val == 'all':
            cfg['start_pos'] = None
            cfg['end_pos'] = None
        else:
            s_val, e_val = val.split('-')
            cfg['start_pos'] = int(s_val)
            cfg['end_pos'] = int(e_val)
        if meta:
            save_pending(uid, meta)
        else:
            save_user_cfg(uid, cfg)
        text, markup = build_main_menu(uid, meta)
        await q.edit_message_text(text, reply_markup=markup, parse_mode='Markdown')

    elif data.startswith('set:group:'):
        val = int(data.split(':', 2)[2])
        cfg['group_size'] = val
        if meta:
            save_pending(uid, meta)
        else:
            save_user_cfg(uid, cfg)
        text, markup = build_main_menu(uid, meta)
        await q.edit_message_text(text, reply_markup=markup, parse_mode='Markdown')

    elif data.startswith('set:'):
        parts = data.split(':', 2)
        field, val = parts[1], parts[2]
        if field == 'beam_size':
            val = int(val)
        elif field == 'audio_speed':
            val = float(val)
        cfg[field] = val
        if field == 'mode' and meta:
            meta['mode'] = val
        if meta:
            save_pending(uid, meta)
        else:
            save_user_cfg(uid, cfg)
        text, markup = build_main_menu(uid, meta)
        await q.edit_message_text(text, reply_markup=markup, parse_mode='Markdown')

    elif data == 'action:start':
        if not meta:
            await q.edit_message_text('Không tìm thấy file đang chờ xử lý. Hãy gửi lại file TXT/EPUB.')
            return
        p = PENDING_DIR / str(uid) / 'file.bin'
        if not p.is_file():
            await q.edit_message_text('File tạm không tồn tại. Hãy gửi lại file TXT/EPUB.')
            clear_pending(uid)
            return
        file_bytes = p.read_bytes()
        try:
            jid = state.create(uid, meta['chat_id'], meta['mode'], meta['suffix'], file_bytes, config=meta['config'])
            clear_pending(uid)
            c_cfg = meta['config']
            cfg_desc = (
                f"• Chế độ: {MODE_NAMES.get(meta['mode'], meta['mode'])}\n"
                f"• Dải chương: {format_scope(c_cfg.get('start_pos'), c_cfg.get('end_pos'))}\n"
                f"• Gộp audio: {format_group(c_cfg.get('group_size'))}\n"
                f"• Model AI: {c_cfg.get('engine')}\n"
                f"• Mức độ (Beam): {c_cfg.get('beam_size')}\n"
                f"• Tốc độ: {c_cfg.get('audio_speed')}x"
            )
            await q.edit_message_text(
                f"🚀 *ĐÃ BẮT ĐẦU TÁC VỤ: `{jid}`*\n\n"
                f"📄 File: `{meta['filename']}`\n"
                f"{cfg_desc}\n\n"
                f"👉 Xem tiến độ bằng: `/status`\n"
                f"👉 Hủy tác vụ bằng: `/cancel {jid}`",
                parse_mode='Markdown'
            )
        except Exception as exc:
            log.exception('Queue job failed')
            await q.edit_message_text(f"Chưa xếp hàng được tác vụ: {str(exc)}")

    elif data == 'action:cancel_pending':
        clear_pending(uid)
        await q.edit_message_text('❌ Đã hủy tải truyện. Bạn có thể gửi file mới bất kỳ lúc nào.')

    elif data == 'action:save_settings':
        save_user_cfg(uid, cfg)
        await q.edit_message_text('💾 *Đã lưu cấu hình mặc định thành công!*\nCác file gửi sau này sẽ tự động áp dụng cấu hình này.', parse_mode='Markdown')

    elif data == 'action:close':
        await q.edit_message_text('Đã đóng bảng cài đặt.')

    elif data == 'action:status':
        lines = []
        for row in state.list(uid):
            detail = ''
            path = DATA / row['id'] / 'progress.json'
            if path.exists():
                with contextlib.suppress(Exception):
                    p = json.loads(path.read_text())
                    detail = f" | {p.get('stage','')} {p.get('done',0)}/{p.get('total',0)}"
            lines.append(f"`{row['id']}`: *{row['status']}*{detail}")
        msg = '\n'.join(lines) if lines else 'Hiện chưa có tác vụ nào.'
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Quay lại", callback_data="menu:main")]])
        await q.edit_message_text(f"📊 *TIẾN ĐỘ CÁC TÁC VỤ:*\n\n{msg}", reply_markup=kb, parse_mode='Markdown')

    elif data == 'action:help':
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Quay lại", callback_data="menu:main")]])
        await q.edit_message_text(HELP, reply_markup=kb)

async def status(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not await permitted(u): return
    lines = []
    for row in state.list(u.effective_user.id):
        detail = ''
        path = DATA / row['id'] / 'progress.json'
        if path.exists():
            with contextlib.suppress(Exception):
                p = json.loads(path.read_text())
                detail = f" | {p.get('stage','')} {p.get('done',0)}/{p.get('total',0)}"
        lines.append(f"{row['id']}: {row['status']}{detail}")
    await u.message.reply_text('\n'.join(lines) or 'Chưa có tác vụ.')

async def action(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not await permitted(u): return
    row = state.get(c.args[0], u.effective_user.id) if len(c.args) == 1 else None
    if not row:
        await u.message.reply_text('Cần mã tác vụ của bạn. Xem /status.')
        return
    jid = row['id']
    cmd = u.message.text.split()[0].split('@')[0]
    if cmd == '/cancel':
        if row['status'] not in ('queued', 'running', 'delivering'):
            await u.message.reply_text('Tác vụ đã dừng.')
            return
        state.set(jid, 'cancelled')
        await u.message.reply_text('Đã yêu cầu hủy tác vụ. Checkpoint được giữ.')
    elif cmd == '/retry':
        if c.application.bot_data.get('active') == jid:
            await u.message.reply_text('Tác vụ đang dừng; đợi vài giây rồi /retry lại.')
            return
        if row['status'] not in ('failed', 'cancelled'):
            await u.message.reply_text('Chỉ tiếp tục tác vụ lỗi/đã hủy.')
            return
        try:
            state.requeue(jid, u.effective_user.id)
        except ValueError as exc:
            await u.message.reply_text(str(exc))
            return
        await u.message.reply_text('Đã xếp hàng tiếp tục từ checkpoint.')
    else:
        if row['status'] in ('queued', 'running', 'delivering') or c.application.bot_data.get('active') == jid:
            await u.message.reply_text('Hãy /cancel rồi đợi tác vụ dừng trước khi xóa.')
            return
        shutil.rmtree(DATA / jid, ignore_errors=True)
        state.set(jid, 'deleted')
        await u.message.reply_text('Đã xóa dữ liệu và checkpoint trên máy chủ.')

async def deliver(app, row):
    folder = DATA / row['id']
    marker = folder / 'sent.json'
    sent = set(json.loads(marker.read_text())) if marker.exists() else set()
    for path in sorted((folder / 'output').iterdir()):
        if state.get(row['id'])['status'] == 'cancelled':
            return
        if path.name in sent or not path.is_file():
            continue
        if path.stat().st_size > 48 * 1024**2:
            raise ValueError('File xuất quá 48 MB; lấy trên máy chủ hoặc chia tập.')
        with path.open('rb') as f:
            if path.suffix == '.mp3':
                await app.bot.send_audio(row['chat'], audio=f, filename=path.name, title=path.stem, read_timeout=120, write_timeout=120)
            else:
                await app.bot.send_document(row['chat'], document=f, filename=path.name, read_timeout=120, write_timeout=120)
        sent.add(path.name)
        temp = marker.with_suffix('.tmp')
        temp.write_text(json.dumps(sorted(sent)))
        temp.replace(marker)
        await asyncio.sleep(1.1)
    if state.get(row['id'])['status'] != 'cancelled':
        state.set(row['id'], 'done')
        with contextlib.suppress(Exception):
            await app.bot.send_message(row['chat'], f"Hoàn tất {row['id']}. Dọn dữ liệu bằng /xoa {row['id']}.")

async def worker(app):
    global process
    state.recover()
    while True:
        row = state.next()
        if not row:
            await asyncio.sleep(2)
            continue
        jid = row['id']
        folder = DATA / jid
        app.bot_data['active'] = jid
        try:
            with contextlib.suppress(Exception):
                await app.bot.send_message(row['chat'], f'Bắt đầu {jid}. Xem tiến độ bằng /status.')
            with (folder / 'runner.log').open('ab') as logfile:
                process = await asyncio.create_subprocess_exec(
                    sys.executable, str(BOT_DIR / 'runner.py'), str(folder),
                    stdout=logfile, stderr=logfile
                )
                began = asyncio.get_running_loop().time()
                while process.returncode is None:
                    current = state.get(jid)['status']
                    if current not in ('running',) or asyncio.get_running_loop().time() - began > 86400:
                        if current == 'running':
                            state.set(jid, 'failed', 'Timeout 24 giờ; có thể /retry.')
                        process.terminate()
                        try:
                            await asyncio.wait_for(process.wait(), 10)
                        except asyncio.TimeoutError:
                            process.kill()
                            await process.wait()
                        break
                    try:
                        await asyncio.wait_for(process.wait(), 2)
                    except asyncio.TimeoutError:
                        pass
                if state.get(jid)['status'] != 'running':
                    continue
                if process.returncode:
                    raise RuntimeError('Xử lý lỗi; xem runner.log trên máy chủ.')
            state.set(jid, 'delivering')
            await deliver(app, row)
        except asyncio.CancelledError:
            if process and process.returncode is None:
                process.terminate()
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(process.wait(), 10)
                if process.returncode is None:
                    process.kill()
                    await process.wait()
            raise
        except Exception:
            log.exception('Job %s failed', jid)
            if state.get(jid)['status'] not in ('cancelled', 'queued'):
                state.set(jid, 'failed', 'Xử lý/gửi kết quả lỗi; xem runner.log.')
                with contextlib.suppress(Exception):
                    await app.bot.send_message(
                        row['chat'],
                        f'Tác vụ {jid} lỗi. Dùng /retry {jid} để thử lại. Chi tiết nằm trong runner.log.'
                    )
        finally:
            process = None
            app.bot_data['active'] = None

async def init(app):
    app.bot_data['worker'] = asyncio.create_task(worker(app))

async def shutdown(app):
    task = app.bot_data.get('worker')
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

def main():
    if not ALLOWED:
        raise SystemExit('Phải đặt ALLOWED_USER_IDS; bot từ chối chạy công khai.')
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    if not token or token.startswith('YOUR_'):
        raise SystemExit('Thiếu TELEGRAM_BOT_TOKEN.')
    logging.basicConfig(level=logging.INFO)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)

    req = HTTPXRequest(
        connection_pool_size=16,
        read_timeout=120.0,
        write_timeout=120.0,
        connect_timeout=30.0,
        pool_timeout=60.0,
    )
    app = Application.builder().token(token).request(req).post_init(init).post_stop(shutdown).build()
    app.add_handler(CommandHandler(['start', 'help'], start))
    app.add_handler(CommandHandler(['cauhinh', 'settings'], settings_cmd))
    app.add_handler(CommandHandler(['full', 'dich', 'audio'], mode_cmd))
    app.add_handler(CommandHandler('status', status))
    app.add_handler(CommandHandler(['cancel', 'retry', 'xoa'], action))
    app.add_handler(MessageHandler(filters.Document.ALL, document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text_message))
    app.add_handler(CallbackQueryHandler(on_callback))

    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)

if __name__ == '__main__':
    main()
