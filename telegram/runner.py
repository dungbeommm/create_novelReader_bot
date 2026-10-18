"""Subprocess per novel: synchronized directly with tool's Job workflow, audio_service, and merge_service."""
import contextlib
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from storage.files import parse_file, export_txt, export_epub
from storage.store import Store
from workflows.jobs import Job
from audio import audio_service, merge_service
from audio.audio_service import get_chapter_audio_path

log = logging.getLogger(__name__)

def write_json(path, data):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    tmp.replace(path)

def progress(folder, stage, **kw):
    write_json(folder / 'progress.json', {'stage': stage, **kw})

def copy_or_segment_audio(src_path: Path, output_dir: Path, base_name: str):
    """Copy audio sang thư mục output; nếu vượt quá 48 MB sẽ tự động segment chia nhỏ cho Telegram."""
    if not src_path.is_file() or src_path.stat().st_size == 0:
        return
    output_dir.mkdir(parents=True, exist_ok=True)
    limit = 48 * 1024 * 1024
    if src_path.stat().st_size <= limit:
        shutil.copy2(src_path, output_dir / base_name)
    else:
        stem = Path(base_name).stem
        ext = Path(base_name).suffix or '.mp3'
        subprocess.run([
            'ffmpeg', '-v', 'error', '-y', '-i', str(src_path),
            '-c', 'copy', '-f', 'segment', '-segment_time', '600',
            '-reset_timestamps', '1',
            str(output_dir / f"{stem}_%03d{ext}")
        ], check=True, timeout=600)

def run(folder: Path):
    request = json.loads((folder / 'request.json').read_text(encoding='utf-8'))
    output = folder / 'output'
    output.mkdir(exist_ok=True)
    store = Store(folder / 'book.sqlite3', text_dir=folder/'output_text', audio_dir=folder/'output_audio')

    if not store.book():
        chapters, enc = parse_file(request['input'], (folder / request['input']).read_bytes())
        if not chapters or len(chapters) > 10000 or sum(len(t)+len(b) for t,b in chapters) > 2000000:
            raise ValueError('Mỗi truyện tối đa 10.000 chương / 2 triệu ký tự. Hãy chia tập.')
        if any(len(t)+len(b) > 200000 for t,b in chapters):
            raise ValueError('Một chương quá 200.000 ký tự. Hãy chia nhỏ.')
        store.replace(request['input'], enc, chapters)

    req_cfg = request.get('config') or {}
    all_chapters = store.list()
    total_count = len(all_chapters)
    raw_start = req_cfg.get('start_pos')
    raw_end = req_cfg.get('end_pos')
    start_pos = int(raw_start) if (raw_start is not None and str(raw_start).strip().isdigit()) else None
    end_pos = int(raw_end) if (raw_end is not None and str(raw_end).strip().isdigit()) else None
    group_size = int(req_cfg.get('group_size', 1))

    if start_pos is not None or end_pos is not None:
        s = start_pos if start_pos is not None else 1
        e = end_pos if end_pos is not None else total_count
        s = max(1, min(s, e))
        e = min(total_count, max(s, e))
        target_chapters = [c for idx, c in enumerate(all_chapters) if s <= (c.get('position') or idx + 1) <= e]
    else:
        s = 1
        e = total_count
        target_chapters = all_chapters

    if not target_chapters:
        target_chapters = all_chapters
        s = 1
        e = total_count

    target_ids = [c['id'] for c in target_chapters]
    target_id_set = set(target_ids)
    total_target = len(target_chapters)

    voice_id = req_cfg.get('voice_id', 'ngochuyennew')
    speed = float(req_cfg.get('audio_speed', 1.0))
    noise_scale = float(req_cfg.get('noise_scale', 0.667))
    noise_w_scale = float(req_cfg.get('noise_w_scale', 0.8))

    mode = request.get('mode', 'full')

    # Chế độ 1: Chỉ tạo Audio (từ nội dung text sẵn có)
    if mode == 'audio':
        for idx, ch in enumerate(target_chapters, 1):
            if shutil.disk_usage(folder).free < 1024**3:
                raise RuntimeError('Ổ đĩa còn dưới 1 GB. Dọn dữ liệu trước khi tiếp tục.')
            pos = ch.get('position', idx)
            paras = ch.get('source', [])
            title = ch.get('title', '')
            if ch.get('translated') and any(ch.get('translated')):
                paras = ch.get('translated')
                title = ch.get('translated_title') or title

            progress(folder, f"đang tạo audio {idx-1}/{total_target}", done=idx-1, total=total_target)
            audio_service.generate_chapter_audio(
                ch['id'], pos, title, paras, store.audio_dir,
                voice_id=voice_id, speed=speed, noise_scale=noise_scale, noise_w_scale=noise_w_scale,
                fmt='mp3', bitrate='96k'
            )
            store.update(ch['id'], audio_status='done')

            if group_size > 1:
                with contextlib.suppress(Exception):
                    merge_service.group_and_merge_chapters(
                        store, group_size=group_size, fmt='mp3', chapter_ids=target_ids, bitrate='96k'
                    )

        if group_size > 1:
            with contextlib.suppress(Exception):
                merge_service.group_and_merge_chapters(
                    store, group_size=group_size, fmt='mp3', chapter_ids=target_ids, bitrate='96k'
                )
        progress(folder, f"tạo audio {total_target}/{total_target}", done=total_target, total=total_target)

    # Chế độ 2: Dịch hoặc Dịch + Audio đồng bộ trực tiếp qua workflows.jobs.Job
    else:
        job = Job(store)
        job_config = {
            'engine': req_cfg.get('engine', 'HachimiMT-60-QT'),
            'glossary': req_cfg.get('glossary', ''),
            'batch_size': int(req_cfg.get('batch_size', 8)),
            'honorific_mode': req_cfg.get('honorific_mode', 'safe'),
            'pronoun_harmonizer': bool(req_cfg.get('pronoun_harmonizer', True)),
            'beam_size': int(req_cfg.get('beam_size', 2)),
            'chunk_mode': req_cfg.get('chunk_mode', 'sentence'),
            'normalize_mode': req_cfg.get('normalize_mode', 'auto'),
            'start_pos': s if (start_pos or end_pos) else None,
            'end_pos': e if (start_pos or end_pos) else None,
            'generate_audio': (mode == 'full'),
            'auto_group_audio': bool(group_size > 1),
            'group_size': group_size if group_size > 1 else 50,
            'voice_id': voice_id,
            'audio_speed': speed,
            'noise_scale': noise_scale,
            'noise_w_scale': noise_w_scale,
            'audio_format': 'mp3',
            'audio_bitrate': '96k',
        }

        if any(c['status'] != 'done' for c in target_chapters):
            job.start(job_config)

        while job.active:
            summary = job.summary()
            trans_done = summary.get('done', 0)
            total = summary.get('total', total_target)
            if mode == 'full':
                audio_done = sum(1 for c in store.list() if c['id'] in target_id_set and get_chapter_audio_path(store.audio_dir, c['id'], c.get('position')) is not None)
                stage = f"dịch {trans_done}/{total} | audio {audio_done}/{total}"
            else:
                stage = f"đang dịch {trans_done}/{total}"
            progress(folder, stage, done=trans_done, total=total)
            time.sleep(1.5)

        if job.status == 'error':
            raise RuntimeError(job.message or 'Có chương dịch lỗi; dùng /retry để thử lại.')

        if any(c['status'] != 'done' for c in store.list() if c['id'] in target_id_set):
            raise RuntimeError('Có chương dịch chưa hoàn tất; dùng /retry để thử lại.')

        completed = [store.get(c['id']) for c in target_chapters]
        (output / 'ban_dich.txt').write_bytes(export_txt(store.book(), completed))
        (output / 'ban_dich.epub').write_bytes(export_epub(store.book(), completed))

    # Chuyển các file audio đã tạo sang thư mục output để Telegram Bot gửi cho người dùng
    if mode != 'translate':
        groups_dir = store.audio_dir / 'audio_gop'
        has_merged = False
        if group_size > 1 and groups_dir.exists():
            for merged_file in sorted(groups_dir.iterdir()):
                if merged_file.is_file() and merged_file.suffix.lower() in ('.mp3', '.m4b', '.m4a', '.opus', '.wav'):
                    copy_or_segment_audio(merged_file, output, merged_file.name)
                    has_merged = True

        # Nếu không gộp (group_size <= 1) hoặc fallback nếu chưa có file gộp
        if not has_merged:
            for c in target_chapters:
                p = get_chapter_audio_path(store.audio_dir, c['id'], c.get('position'))
                if p and p.is_file():
                    copy_or_segment_audio(p, output, f"chuong_{c.get('position', 1):04d}{p.suffix}")

    progress(folder, 'xử lý xong', done=total_target, total=total_target)

if __name__ == '__main__':
    try:
        run(Path(sys.argv[1]).resolve())
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
