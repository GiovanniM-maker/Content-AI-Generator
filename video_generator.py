"""
Video UGC generator — produces lip-sync talking-head videos.
Pipeline: Script → LLM audio prep → MiniMax TTS (audio) → SadTalker (lip-sync video)
All via fal.ai API + OpenRouter for script preparation.
"""

import os
import hashlib
import time
import logging
import requests as http_requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

import fal_client

LOG_DIR = Path(__file__).parent / "data"
LOG_DIR.mkdir(parents=True, exist_ok=True)

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)

# File handler — always log to data/video.log
_fh = logging.FileHandler(LOG_DIR / "video.log")
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-5s | %(message)s", datefmt="%H:%M:%S"))
log.addHandler(_fh)

FAL_KEY = os.getenv("FAL_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE = "https://openrouter.ai/api/v1"

OUTPUT_DIR = Path(__file__).parent / "static" / "video_output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

AVATAR_DIR = Path(__file__).parent / "static" / "avatars"
AVATAR_DIR.mkdir(parents=True, exist_ok=True)

# Timeouts (seconds)
UPLOAD_TIMEOUT = 60
TTS_TIMEOUT = 180  # MiniMax can be slower on longer texts
VIDEO_TIMEOUT = 600  # SadTalker can be slow on long audio
LLM_TIMEOUT = 60


# ---------------------------------------------------------------------------
# MiniMax voice configuration
# ---------------------------------------------------------------------------

# Default voice for Italian male speaker (Juan's persona)
DEFAULT_VOICE_ID = "Italian_DiligentLeader"
DEFAULT_EMOTION = "neutral"

# Common English tech terms used in AI/retail content
# Format: {"word": "pronunciation"} — helps MiniMax pronounce them correctly
PRONUNCIATION_DICT = {
    "AI": "Ei-Ai",
    "eCommerce": "i-commerce",
    "workflow": "uork-flo",
    "tool": "tuul",
    "startup": "start-ap",
    "machine learning": "mashin lerning",
    "deep learning": "diip lerning",
    "framework": "freim-uork",
    "ROI": "ar-ou-ai",
    "KPI": "kei-pi-ai",
    "API": "ei-pi-ai",
    "SaaS": "sas",
    "CRM": "si-ar-em",
    "ERP": "i-ar-pi",
    "B2B": "bi-tu-bi",
    "B2C": "bi-tu-si",
    "CEO": "si-i-ou",
    "CTO": "si-ti-ou",
    "ChatGPT": "ciat-gi-pi-ti",
    "GPT": "gi-pi-ti",
    "OpenAI": "open-ei-ai",
    "LLM": "el-el-em",
    "NLP": "en-el-pi",
    "RAG": "rag",
    "fine-tuning": "fain-tiuning",
    "prompt": "prompt",
    "retail": "riiteil",
    "cloud": "claud",
    "dashboard": "desh-bord",
    "chatbot": "ciat-bot",
    "e-commerce": "i-commerce",
    "software": "soft-uer",
    "hardware": "hard-uer",
    "online": "on-lain",
    "marketing": "marketing",
    "business": "bisnes",
    "benchmark": "bench-mark",
}

# LLM prompt for preparing TTS-optimized audio script
AUDIO_PREP_SYSTEM_PROMPT = """Sei un esperto di preparazione testi per text-to-speech italiano.
Il tuo compito è trasformare un post LinkedIn scritto in un testo ottimizzato per la lettura ad alta voce con un sintetizzatore vocale avanzato.

REGOLE:
1. PAUSE: Inserisci marcatori di pausa nel formato <#X.X#> dove X.X sono i secondi (0.01-99.99):
   - <#0.3#> dopo ogni punto fermo (pausa breve)
   - <#0.2#> dopo ogni virgola
   - <#0.5#> tra un paragrafo e l'altro (pausa media)
   - <#0.8#> prima di un concetto importante o una domanda retorica (pausa drammatica)
   - <#1.0#> prima della conclusione/CTA finale

2. RESPIRI E INTERJECTIONS: Inserisci tag tra parentesi per rendere la lettura naturale:
   - (breath) ogni 2-3 frasi, per simulare una pausa respiratoria naturale
   - (exhale) dopo una frase emotiva o di impatto
   - (emm) occasionalmente quando il personaggio "pensa" prima di un insight importante
   NON usare (laughs), (sighs) o altri tag emotivi a meno che il contesto non lo richieda davvero.

3. TERMINI INGLESI: NON tradurre i termini tecnici inglesi. Lasciali in inglese.
   Il sistema ha un dizionario di pronuncia che li gestisce automaticamente.

4. STRUTTURA:
   - Rimuovi emoji, hashtag, link e qualsiasi elemento visivo
   - Rimuovi "CTA" finali tipo "link in bio" o "seguimi" — non servono nel video
   - Mantieni il tono conversazionale e diretto
   - IMPORTANTE: Il video DEVE durare massimo 45-60 secondi (circa 120-180 parole, NON di più)
   - TAGLIA senza pietà: mantieni solo hook + 1 insight chiave + chiusura breve
   - Se il testo originale è lungo, sintetizza drasticamente — meglio corto e potente che lungo e noioso

5. APERTURA: Inizia con una frase d'impatto, senza presentazioni ("Ciao sono Juan" NO)

RESTITUISCI SOLO il testo preparato, senza commenti o spiegazioni."""


def _run_with_timeout(fn, timeout, label="operation"):
    """Run a callable with a timeout. Returns result or raises TimeoutError."""
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(fn)
        try:
            return future.result(timeout=timeout)
        except FuturesTimeoutError:
            raise TimeoutError(f"{label} ha superato il timeout di {timeout}s")


def _friendly_error(error_str: str) -> str:
    """Convert fal.ai error messages to Italian user-friendly messages."""
    e = str(error_str).lower()
    if "exhausted balance" in e or "locked" in e:
        return "Credito fal.ai esaurito. Ricarica il saldo su fal.ai/dashboard/billing"
    if "timeout" in e:
        return "Timeout nella generazione. Il servizio potrebbe essere sovraccarico, riprova tra poco."
    if "not found" in e:
        return "Modello non trovato su fal.ai. Verifica la configurazione."
    if "unauthorized" in e or "invalid key" in e or "authentication" in e:
        return "Chiave API fal.ai non valida. Controlla FAL_KEY nel file .env"
    return str(error_str)


def _get_avatar_path() -> Path | None:
    """Find the current avatar image."""
    for ext in ("jpg", "jpeg", "png", "webp"):
        candidates = list(AVATAR_DIR.glob(f"avatar.{ext}"))
        if candidates:
            return candidates[0]
    # Fallback: any image in avatars dir
    for ext in ("jpg", "jpeg", "png", "webp"):
        candidates = list(AVATAR_DIR.glob(f"*.{ext}"))
        if candidates:
            return candidates[0]
    return None


def _upload_file_to_fal(filepath: Path) -> str:
    """Upload a local file to fal.ai storage and return the URL."""
    log.info(f"Uploading {filepath.name} ({filepath.stat().st_size / 1024:.0f} KB) to fal.ai...")
    url = _run_with_timeout(
        lambda: fal_client.upload_file(filepath),
        timeout=UPLOAD_TIMEOUT,
        label="Upload avatar"
    )
    log.info(f"Upload OK: {url}")
    return url


# ---------------------------------------------------------------------------
# Audio script preparation (LLM rewrite for TTS)
# ---------------------------------------------------------------------------

def _prepare_audio_script(text: str) -> dict:
    """
    Use Claude via OpenRouter to rewrite a LinkedIn post into a TTS-optimized
    audio script with pause markers, breathing tags, and proper structure.
    Returns: { 'script': '...', 'original_length': int, 'prepared_length': int }
    """
    if not OPENROUTER_API_KEY:
        log.warning("OPENROUTER_API_KEY not set — skipping audio script preparation")
        return {"script": text, "original_length": len(text), "prepared_length": len(text)}

    try:
        log.info(f"Preparing audio script ({len(text)} chars) via LLM...")

        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:5001",
            "X-Title": "Content Dashboard - TTS Prep",
        }
        payload = {
            "model": "google/gemini-2.0-flash-001",  # fast + cheap for this task
            "messages": [
                {"role": "system", "content": AUDIO_PREP_SYSTEM_PROMPT},
                {"role": "user", "content": f"Prepara questo testo per il TTS:\n\n{text}"},
            ],
            "temperature": 0.3,
        }

        resp = http_requests.post(
            f"{OPENROUTER_BASE}/chat/completions",
            headers=headers,
            json=payload,
            timeout=LLM_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        if "error" in data:
            err_msg = data["error"].get("message", str(data["error"]))
            log.warning(f"LLM audio prep error: {err_msg}")
            return {"script": text, "original_length": len(text), "prepared_length": len(text), "error": err_msg}

        prepared = data["choices"][0]["message"]["content"].strip()

        log.info(f"Audio script prepared: {len(text)} → {len(prepared)} chars")
        return {
            "script": prepared,
            "original_length": len(text),
            "prepared_length": len(prepared),
        }

    except Exception as e:
        log.warning(f"Audio script preparation failed, using original text: {e}")
        return {"script": text, "original_length": len(text), "prepared_length": len(text), "error": str(e)}


# ---------------------------------------------------------------------------
# TTS generation (MiniMax Speech 2.8 HD)
# ---------------------------------------------------------------------------

def generate_tts(text: str, voice_id: str = DEFAULT_VOICE_ID,
                 speed: float = 1.0, emotion: str = DEFAULT_EMOTION) -> dict:
    """
    Generate Italian TTS audio using MiniMax Speech 2.8 HD on fal.ai.
    Supports pause markers <#0.5#>, interjection tags (breath), (exhale), etc.
    Returns: { 'audio_url': '...', 'duration_ms': int, 'duration_estimate': float }
    """
    if not FAL_KEY:
        return {"error": "FAL_KEY not set"}

    os.environ["FAL_KEY"] = FAL_KEY

    try:
        log.info(f"Generating TTS audio via MiniMax 2.8 HD ({len(text)} chars, voice={voice_id}, emotion={emotion})...")

        arguments = {
            "prompt": text,
            "voice_setting": {
                "voice_id": voice_id,
                "speed": speed,
                "vol": 1,
                "emotion": emotion,
                "english_normalization": True,
            },
            "language_boost": "Italian",
            "pronunciation_dict": PRONUNCIATION_DICT,
            "output_format": "url",  # CRITICAL: default is "hex", we need "url"
            "audio_setting": {
                "sample_rate": 32000,
                "bitrate": 128000,
                "format": "mp3",
                "channel": 1,
            },
        }

        result = _run_with_timeout(
            lambda: fal_client.subscribe(
                "fal-ai/minimax/speech-2.8-hd",
                arguments=arguments,
            ),
            timeout=TTS_TIMEOUT,
            label="Generazione TTS MiniMax"
        )

        audio_url = result.get("audio", {}).get("url", "")
        if not audio_url:
            return {"error": "Nessun audio generato dal servizio TTS MiniMax", "raw": result}

        # Use actual duration from MiniMax if available, otherwise estimate
        duration_ms = result.get("duration_ms", 0)
        if duration_ms:
            duration_estimate = duration_ms / 1000.0
        else:
            # Fallback estimate: ~150 words per minute in Italian, ~5 chars/word
            chars = len(text)
            words = chars / 5
            duration_estimate = (words / 150) * 60

        log.info(f"TTS OK: {audio_url} ({duration_estimate:.1f}s)")
        return {
            "audio_url": audio_url,
            "duration_ms": duration_ms,
            "duration_estimate": round(duration_estimate, 1),
        }

    except TimeoutError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": _friendly_error(str(e))}


def generate_video(image_url: str, audio_url: str) -> dict:
    """
    Generate lip-sync video using SadTalker on fal.ai.
    ~$0.03 per video vs ~$10+ with Fabric 1.0.
    Returns: { 'video_url': '...', 'local_path': '...' }
    """
    if not FAL_KEY:
        return {"error": "FAL_KEY not set"}

    os.environ["FAL_KEY"] = FAL_KEY

    try:
        log.info("Generating lip-sync video with SadTalker...")
        result = _run_with_timeout(
            lambda: fal_client.subscribe(
                "fal-ai/sadtalker",
                arguments={
                    "source_image_url": image_url,
                    "driven_audio_url": audio_url,
                    "face_model_resolution": "512",
                    "expression_scale": 1.0,
                    "face_enhancer": "gfpgan",
                    "preprocess": "full",
                    "still_mode": False,
                },
            ),
            timeout=VIDEO_TIMEOUT,
            label="Generazione video lip-sync"
        )

        video_url = result.get("video", {}).get("url", "")
        if not video_url:
            return {"error": "Nessun video generato dal servizio lip-sync", "raw": result}

        # Download video locally
        content_hash = hashlib.md5(f"{image_url}{audio_url}".encode()).hexdigest()[:10]
        filename = f"ugc_{content_hash}_{int(time.time())}.mp4"
        local_path = OUTPUT_DIR / filename

        log.info(f"Downloading video to {local_path}...")
        resp = http_requests.get(video_url, timeout=120)
        resp.raise_for_status()
        local_path.write_bytes(resp.content)

        log.info(f"Video saved: {filename} ({len(resp.content) / 1024:.0f} KB)")
        return {
            "video_url": video_url,
            "local_path": f"/static/video_output/{filename}",
            "file_size": len(resp.content),
        }

    except TimeoutError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": _friendly_error(str(e))}


def generate_ugc_video(script: str, voice_id: str = DEFAULT_VOICE_ID,
                       speed: float = 1.0, emotion: str = DEFAULT_EMOTION) -> dict:
    """
    Full pipeline: script → LLM audio prep → MiniMax TTS → SadTalker lip-sync video.
    Returns: { 'video_url': '...', 'local_path': '...', 'audio_url': '...', 'steps': [...] }
    """
    steps = []

    # Step 1: Find avatar
    avatar_path = _get_avatar_path()
    if not avatar_path:
        return {"error": "No avatar image found. Upload one in static/avatars/"}

    steps.append({"step": "avatar", "status": "ok", "path": str(avatar_path)})

    # Step 2: Upload avatar to fal.ai
    try:
        image_url = _upload_file_to_fal(avatar_path)
        steps.append({"step": "upload_avatar", "status": "ok", "url": image_url})
    except TimeoutError as e:
        return {"error": str(e), "steps": steps}
    except Exception as e:
        return {"error": _friendly_error(f"Upload avatar fallito: {e}"), "steps": steps}

    # Step 3: Prepare audio script via LLM (add pauses, breathing, clean up)
    prep_result = _prepare_audio_script(script)
    prepared_script = prep_result["script"]

    # Hard-cap: max ~900 chars of actual text (excluding pause markers)
    # SadTalker chokes on audio longer than ~60s
    clean_len = len(prepared_script.replace("<#", "").replace("#>", ""))
    if clean_len > 900:
        log.warning(f"Script too long after prep ({clean_len} clean chars), truncating to ~900")
        # Truncate at last sentence boundary before 900 chars
        cut = prepared_script[:950]
        last_dot = cut.rfind(".")
        if last_dot > 400:
            prepared_script = cut[:last_dot + 1]
        else:
            prepared_script = cut

    steps.append({
        "step": "audio_prep",
        "status": "ok",
        "original_chars": prep_result["original_length"],
        "prepared_chars": len(prepared_script),
    })
    if "error" in prep_result:
        steps[-1]["warning"] = f"LLM prep fallback: {prep_result['error']}"

    # Step 4: Generate TTS audio with MiniMax Speech 2.8 HD
    tts_result = generate_tts(prepared_script, voice_id=voice_id, speed=speed, emotion=emotion)
    if "error" in tts_result:
        return {"error": tts_result["error"], "steps": steps}
    steps.append({"step": "tts", "status": "ok", "audio_url": tts_result["audio_url"],
                   "duration_estimate": tts_result.get("duration_estimate", 0)})

    # Step 5: Generate lip-sync video
    video_result = generate_video(image_url, tts_result["audio_url"])
    if "error" in video_result:
        return {"error": video_result["error"], "steps": steps}
    steps.append({"step": "video", "status": "ok", "video_url": video_result["video_url"],
                   "local_path": video_result["local_path"]})

    return {
        "video_url": video_result["video_url"],
        "local_path": video_result["local_path"],
        "audio_url": tts_result["audio_url"],
        "duration_estimate": tts_result.get("duration_estimate", 0),
        "prepared_script": prepared_script,  # include for debugging
        "steps": steps,
    }
