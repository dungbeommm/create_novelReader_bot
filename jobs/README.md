# jobs/

Thu muc chua cac job dang cho xu ly. Bot Telegram se tao:

```
jobs/<job_id>/<ten-file-ebook>
jobs/<job_id>/job.json
```

Workflow `audiobook.yml` doc file trong day, tao audio, **dang tung batch len
Internet Archive (archive.org)** roi tu dong xoa thu muc job de tranh phinh repo.

Moi audiobook = mot *item* tren archive.org voi identifier tat dinh sinh tu
tieu de + job_id. Link chia se co dinh:

```
https://archive.org/details/<identifier>
```

Khi toan bo hoan tat, workflow ghi them file `_COMPLETE.json` len item; bot dua
vao file nay de bao "da xong".

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

> Can dat 2 GitHub Secrets `IA_ACCESS_KEY` va `IA_SECRET_KEY` (lay tai
> https://archive.org/account/s3.php) de workflow co the dang tai.
