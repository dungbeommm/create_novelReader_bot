# Configuration

All behavior is driven by `config/default.yaml` and environment variables. No
values are hard-coded in the source. Load order (later wins):

1. Built-in defaults (Pydantic models in `config/models.py`).
2. YAML file at `AUDIOBOOK_FORGE_CONFIG` (default `config/default.yaml`).
3. Environment variables (for secrets and deploy-specific overrides).

## Environment variables

| Variable | Maps to | Notes |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | (env only) | Secret; required for bot + notify. Never stored in config or code. |
| `TELEGRAM_ALLOWED_USER_IDS` | `telegram.allowed_user_ids` | Comma-separated ids; empty = allow all |
| `GITHUB_TOKEN` / `GH_TOKEN` | (env only) | Secret; read directly from the environment. Provided automatically in Actions. |
| `GITHUB_REPOSITORY` | `github.repository` | `owner/name`; set by Actions automatically |
| `GITHUB_REF` | `github.ref` | Branch used for workflow_dispatch |
| `GITHUB_WORKFLOW_FILE` | `github.workflow_file` | Defaults to `convert.yml` |
| `AUDIOBOOK_FORGE_CONFIG` | (loader) | Path to a YAML config file |
| `LOG_LEVEL` | `log_level` | `DEBUG`/`INFO`/`WARNING`/... |

## YAML keys

### `tts`

| Key | Default | Meaning |
| --- | --- | --- |
| `models_dir` | `models` | Where voices are auto-discovered |
| `default_voice` | `null` | Voice id used when none selected (null = first found) |
| `speed` | `1.0` | Default length scale (higher = slower) |
| `noise_scale` | `0.667` | Piper synthesis noise scale |
| `noise_w` | `0.8` | Piper phoneme duration noise |
| `sentence_silence` | `0.35` | Seconds of silence Piper adds between sentences |
| `allowed_speeds` | `[0.7 .. 1.5]` | Speed buttons shown in Telegram |

### `segmentation`

| Key | Default | Meaning |
| --- | --- | --- |
| `max_chars` | `320` | Absolute character cap per segment (>= 80); long sentences are split safely |
| `soft_chars` | `220` | Preferred size; flush at the next sentence end past this |
| `max_tokens` | `180` | Approximate whitespace-token cap per segment |
| `overlap_sentences` | `0` | Sentence overlap between segments (0-3) |
| `min_chars` | `20` | Drop/merge threshold for tiny trailing segments |

### `normalization`

Toggles for the rule engine: `unicode_form` (`NFC`), `strip_html`,
`strip_markdown`, `strip_bbcode`, `decode_html_entities`, `remove_emoji`,
`collapse_whitespace`, `normalize_punctuation`, `language` (`vi`),
`expand_vietnamese`, and `extra_rules` (dotted import paths of custom `Rule`
callables). Add new rules in `normalize/text_rules.py` or
`normalize/vietnamese.py`, or register them via `extra_rules`, without touching
callers.

### `audio`

| Key | Default | Meaning |
| --- | --- | --- |
| `format` | `mp3` | Default output container/codec |
| `bitrate` | `128` | Default bitrate (kbps) |
| `sample_rate` | `22050` | Default sample rate (Hz) |
| `channels` | `1` | Output channels (1-2) |
| `merge_mode` | `per_chapter` | `per_chapter` or `single` |
| `normalize_volume` | `true` | ffmpeg `loudnorm` to the targets below |
| `loudness_target_i` | `-16.0` | Integrated loudness target (LUFS) |
| `loudness_tp` | `-1.5` | True-peak ceiling (dBTP) |
| `loudness_lra` | `11.0` | Loudness range |
| `noise_reduction` | `false` | Optional afftdn denoise |
| `trim_silence` | `true` | Trim leading/trailing silence |
| `silence_threshold_db` | `-45.0` | Silence detection threshold |
| `silence_min_duration` | `0.6` | Minimum silence length to trim |
| `allowed_formats` | mp3/wav/opus/m4a/aac | Format buttons |
| `allowed_bitrates` | 64..320 | Bitrate buttons |
| `allowed_sample_rates` | 22050..48000 | Sample-rate buttons |

### `cache`

| Key | Default | Meaning |
| --- | --- | --- |
| `enabled` | `true` | Toggle the SHA256 audio cache |
| `dir` | `.cache/audio` | Cache location (also cached by Actions) |
| `hash_algorithm` | `sha256` | Hash used for cache keys |

### `queue`

| Key | Default | Meaning |
| --- | --- | --- |
| `dir` | `state/queue` | Task + checkpoint storage |
| `max_concurrent` | `1` | Reserved for multi-worker setups |
| `max_history` | `200` | Terminal tasks retained |

### `release`

| Key | Default | Meaning |
| --- | --- | --- |
| `zip_threshold` | `100` | At/above this many files, auto-zip audio |
| `include_log` / `include_cover` / `include_playlist` | `true` | Extra assets |
| `tag_prefix` | `audiobook` | Output release tag prefix |
| `draft` / `prerelease` | `false` | Release visibility |

### `compression`

| Key | Default | Meaning |
| --- | --- | --- |
| `enabled` | `false` | Force-zip regardless of file count (user toggle) |
| `format` | `zip` | Archive format |
| `level` | `6` | Deflate level (0-9) |

### `github`

| Key | Default | Meaning |
| --- | --- | --- |
| `repository` | `""` | `owner/name` (usually from `GITHUB_REPOSITORY`) |
| `workflow_file` | `convert.yml` | Workflow to dispatch |
| `ref` | `main` | Dispatch ref |
| `api_url` | `https://api.github.com` | For GitHub Enterprise, override |
| `intake_tag_prefix` | `inbox` | Transient intake release prefix |
| `runner_time_budget_seconds` | `18000` | Soft budget before checkpoint + resume |

> The GitHub token is **not** a config key. It is read from `GITHUB_TOKEN` /
> `GH_TOKEN` in the environment so it never lands in YAML or source.

### `telegram`

| Key | Default | Meaning |
| --- | --- | --- |
| `allowed_user_ids` | `[]` | Allowlist; empty = public |
| `max_upload_mb` | `45` | Reject larger uploads (Bot API limit ~50MB) |
| `media_group_wait_seconds` | `2.0` | Debounce for multi-file albums |
| `default_language` | `vi` | Default UI/normalization language |

> The bot token is **not** a config key. It is read from `TELEGRAM_BOT_TOKEN` in
> the environment.
