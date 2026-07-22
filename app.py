import io
import os
import threading
import time
import wave

from flask import Flask, request, send_file, jsonify, Response
from piper import PiperVoice

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, "voice", "ngochuyennew.onnx")
CONFIG_PATH = os.path.join(BASE_DIR, "voice", "ngochuyennew.onnx.json")

app = Flask(__name__)
TTS_API_KEY = os.environ.get("TTS_API_KEY", "").strip()
MAX_REQUESTS_PER_MINUTE = int(os.environ.get("TTS_RATE_LIMIT", "10"))
_tts_lock = threading.BoundedSemaphore(int(os.environ.get("TTS_CONCURRENCY", "1")))
_rate_lock = threading.Lock()
_request_times = {}

# Load the voice model once at startup (kept in memory for all requests).
print("Loading Piper voice model...", flush=True)
voice = PiperVoice.load(MODEL_PATH, config_path=CONFIG_PATH)
print("Voice model loaded.", flush=True)


def synthesize_wav_bytes(text, length_scale=None, noise_scale=None, noise_w=None):
    """Return WAV bytes for the given text. Works with piper-tts 1.2.x."""
    buf = io.BytesIO()
    kwargs = {}
    if length_scale is not None:
        kwargs["length_scale"] = length_scale
    if noise_scale is not None:
        kwargs["noise_scale"] = noise_scale
    if noise_w is not None:
        kwargs["noise_w"] = noise_w

    # Prefer the 1.2 API because it supports the inference overrides exposed by
    # this service. Falling back to synthesize_wav is only safe without them.
    with wave.open(buf, "wb") as wav_file:
        if hasattr(voice, "synthesize"):
            voice.synthesize(text, wav_file, **kwargs)
        elif kwargs:
            raise RuntimeError("This Piper version does not support inference overrides")
        else:
            voice.synthesize_wav(text, wav_file)
    return buf.getvalue()


def _authorized():
    if not TTS_API_KEY:
        # Safe default: local development works, public deployments must set a
        # key or explicitly opt into insecure mode.
        if os.environ.get("ALLOW_INSECURE_TTS", "").lower() == "true":
            return True
        return (request.remote_addr or "") in {"127.0.0.1", "::1"}
    supplied = request.headers.get("X-API-Key", "")
    import hmac
    return hmac.compare_digest(supplied, TTS_API_KEY)


def _within_rate_limit():
    now = time.monotonic()
    key = request.remote_addr or "unknown"
    with _rate_lock:
        recent = [t for t in _request_times.get(key, []) if now - t < 60]
        if len(recent) >= MAX_REQUESTS_PER_MINUTE:
            _request_times[key] = recent
            return False
        recent.append(now)
        _request_times[key] = recent
        return True


def _float_arg(name):
    val = request.values.get(name)
    if val is None or val == "":
        return None
    try:
        return float(val)
    except ValueError:
        return None


INDEX_HTML = """<!doctype html>
<html lang=\"vi\">
<head>
<meta charset=\"utf-8\">
<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>Chuyen van ban thanh giong noi - Ngoc Huyen (Tieng Viet)</title>
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 0; padding: 24px;
         background: #0f172a; color: #e2e8f0; display: flex; justify-content: center; }
  .card { width: 100%; max-width: 680px; background: #1e293b; border-radius: 16px; padding: 28px;
          box-shadow: 0 10px 40px rgba(0,0,0,.4); }
  h1 { font-size: 20px; margin: 0 0 4px; }
  p.sub { margin: 0 0 20px; color: #94a3b8; font-size: 14px; }
  label { font-size: 13px; color: #cbd5e1; display: block; margin: 14px 0 6px; }
  textarea { width: 100%; min-height: 130px; padding: 12px; border-radius: 10px; border: 1px solid #334155;
             background: #0f172a; color: #e2e8f0; font-size: 15px; resize: vertical; }
  .row { display: flex; gap: 12px; flex-wrap: wrap; }
  .row > div { flex: 1; min-width: 120px; }
  input[type=number] { width: 100%; padding: 8px; border-radius: 8px; border: 1px solid #334155;
                       background: #0f172a; color: #e2e8f0; }
  button { margin-top: 18px; width: 100%; padding: 13px; border: none; border-radius: 10px;
           background: #6366f1; color: white; font-size: 15px; font-weight: 600; cursor: pointer; }
  button:disabled { opacity: .6; cursor: default; }
  audio { width: 100%; margin-top: 20px; }
  .status { margin-top: 12px; font-size: 13px; color: #94a3b8; min-height: 18px; }
  a.dl { display: none; margin-top: 12px; color: #a5b4fc; font-size: 14px; }
  code { background:#0f172a; padding:2px 6px; border-radius:6px; font-size:12px; }
</style>
</head>
<body>
  <div class=\"card\">
    <h1>Chuyen van ban thanh giong noi</h1>
    <p class=\"sub\">Giong Ngoc Huyen &middot; Tieng Viet &middot; Piper TTS</p>
    <label for=\"text\">Nhap van ban</label>
    <textarea id=\"text\" placeholder=\"Nhap doan van ban tieng Viet o day...\">Xin chao, day la giong noi tieng Viet duoc tao tu Piper.</textarea>
    <label for=\"apiKey\">API key (neu server yeu cau)</label>
    <input type=\"password\" id=\"apiKey\" autocomplete=\"off\" style=\"width:100%;padding:8px;border-radius:8px;border:1px solid #334155;background:#0f172a;color:#e2e8f0\">
    <div class=\"row\">
      <div>
        <label for=\"length\">Toc do (length_scale)</label>
        <input type=\"number\" id=\"length\" step=\"0.1\" value=\"1.0\" min=\"0.3\" max=\"3\">
      </div>
      <div>
        <label for=\"noise\">noise_scale</label>
        <input type=\"number\" id=\"noise\" step=\"0.01\" value=\"0.667\">
      </div>
      <div>
        <label for=\"noisew\">noise_w</label>
        <input type=\"number\" id=\"noisew\" step=\"0.01\" value=\"0.8\">
      </div>
    </div>
    <button id=\"go\">Tao giong noi</button>
    <div class=\"status\" id=\"status\"></div>
    <audio id=\"player\" controls></audio>
    <a class=\"dl\" id=\"dl\" download=\"output.wav\">Tai file .wav</a>
    <p class=\"sub\" style=\"margin-top:20px\">API: <code>GET /tts?text=xin+chao</code> tra ve file WAV.</p>
  </div>
<script>
const btn = document.getElementById('go');
const statusEl = document.getElementById('status');
const player = document.getElementById('player');
const dl = document.getElementById('dl');
let lastUrl = null;
btn.addEventListener('click', async () => {
  const text = document.getElementById('text').value.trim();
  if (!text) { statusEl.textContent = 'Vui long nhap van ban.'; return; }
  const params = new URLSearchParams({
    text,
    length_scale: document.getElementById('length').value,
    noise_scale: document.getElementById('noise').value,
    noise_w: document.getElementById('noisew').value,
  });
  btn.disabled = true; statusEl.textContent = 'Dang tao giong noi...';
  try {
    const apiKey = document.getElementById('apiKey').value;
    const res = await fetch('/tts?' + params.toString(), {
      headers: apiKey ? {'X-API-Key': apiKey} : {}
    });
    if (!res.ok) { throw new Error('Loi ' + res.status); }
    const blob = await res.blob();
    if (lastUrl) URL.revokeObjectURL(lastUrl);
    lastUrl = URL.createObjectURL(blob);
    player.src = lastUrl; player.play();
    dl.href = lastUrl; dl.style.display = 'inline-block';
    statusEl.textContent = 'Hoan tat!';
  } catch (e) {
    statusEl.textContent = 'That bai: ' + e.message;
  } finally {
    btn.disabled = false;
  }
});
</script>
</body>
</html>"""


@app.route("/")
def index():
    return Response(INDEX_HTML, mimetype="text/html")


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/tts", methods=["GET", "POST"])
def tts():
    if not _authorized():
        return jsonify({"error": "Unauthorized"}), 401
    if not _within_rate_limit():
        return jsonify({"error": "Rate limit exceeded"}), 429
    text = (request.values.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Missing 'text' parameter"}), 400
    if len(text) > 5000:
        return jsonify({"error": "Text too long (max 5000 chars)"}), 400

    if not _tts_lock.acquire(blocking=False):
        return jsonify({"error": "TTS engine is busy"}), 503
    try:
        audio = synthesize_wav_bytes(
            text,
            length_scale=_float_arg("length_scale"),
            noise_scale=_float_arg("noise_scale"),
            noise_w=_float_arg("noise_w"),
        )
    finally:
        _tts_lock.release()
    return send_file(
        io.BytesIO(audio),
        mimetype="audio/wav",
        as_attachment=True,
        download_name="output.wav",
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
