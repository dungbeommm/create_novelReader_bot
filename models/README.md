# Voice models

Audiobook Forge auto-discovers Piper voices in this directory. **Nothing is
hard-coded** — add or remove voices freely and they appear/disappear from the
Telegram menu automatically.

## How to add a voice

Each Piper voice is two files with the same base name:

```
models/
  <voice_name>/
    <voice_name>.onnx        # the model weights
    <voice_name>.onnx.json   # the model config (sample rate, phonemes, ...)
```

A flat layout is also supported:

```
models/
  <voice_name>.onnx
  <voice_name>.onnx.json
```

The voice `id` is the base file name (e.g. `ngoc_huyen`). The friendly name
shown in Telegram comes from `config/voices.example.yaml` if present, otherwise
it is derived from the file name.

## Bundled voice

This repository ships with the **Ngọc Huyền** Vietnamese voice under
`models/ngoc_huyen/`. Add as many additional voices as you like.

## Where to get voices

Download community Piper voices from the official Piper voices release page and
drop the `.onnx` + `.onnx.json` pair here.
