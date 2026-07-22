# jobs/

Thu muc chua cac job dang cho xu ly. Bot Telegram se tao:

```
jobs/<job_id>/<ten-file-ebook>
jobs/<job_id>/job.json
```

Workflow `audiobook.yml` doc file trong day, tao audio, dang len GitHub Release
roi tu dong xoa thu muc job de tranh phinh repo.

Vi du `job.json`:
```json
{
  "title": "Ten Truyen",
  "format": "mp3",
  "length_scale": "1.0",
  "package": "auto",
  "max_chars": "0",
  "install_calibre": "false"
}
```
