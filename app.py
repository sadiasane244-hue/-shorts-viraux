# ============================================================
# CERVEAU CURIEUX — STUDIO IA AUTONOME (v6.1 — Full Video Edition)
# Pexels + Pixabay uniquement (100 % gratuit) - Zéro image fixe
# ============================================================

import os
import time
import json
import re
import shutil
import subprocess
import random
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import requests
import streamlit as st
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

# ============================================================
# CONFIGURATION
# ============================================================

APP_TITLE = "🧠 Cerveau Curieux — Studio IA Autonome"

BASE_DIR = Path.cwd()
TEMP_DIR = BASE_DIR / "temp"
OUTPUT_DIR = BASE_DIR / "output"

TEMP_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def get_secret(name: str) -> str:
    value = os.environ.get(name, "")
    if value:
        return value
    try:
        value = st.secrets.get(name, "")
    except Exception:
        value = ""
    return value or ""

PEXELS_API_KEY = get_secret("PEXELS_API_KEY")
PIXABAY_API_KEY = get_secret("PIXABAY_API_KEY")
GEMINI_API_KEY = get_secret("GEMINI_API_KEY")

FFMPEG_BIN = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE_BIN = shutil.which("ffprobe") or "ffprobe"

# ============================================================
# TTS & IDENTITÉ
# ============================================================

TTS_VOICE = "fr-FR-HenriNeural"

TTS_RATE_BY_EMOTION = {
    "default":    "+10%", "thinking":   "+4%", "confused":   "+7%",
    "laughing":   "+16%", "explaining": "+6%", "surprised":  "+18%",
    "angry":      "+13%", "happy":      "+11%", "shocked":    "+18%",
    "sad":        "-2%",
}
TTS_RATE_CTA = "+20%"

INTRO_SIGNATURE = "Wesh l'équipe"
CTA_SIGNATURE = (
    "Et maintenant que ton cerveau sait ça... "
    "abonne-toi frérot, parce qu'on n'a pas fini de le faire buguer."
)

# ============================================================
# DURÉE & AUDIO
# ============================================================

SHORT_MIN_DURATION = 45.1
SHORT_TARGET_MIN_DURATION = 50.0
SHORT_TARGET_MAX_DURATION = 75.0
SHORT_MAX_DURATION = 90.0

SHORT_MIN_WORDS = 135
SHORT_TARGET_MIN_WORDS = 150
SHORT_TARGET_MAX_WORDS = 180
SHORT_MAX_WORDS = 200

NASHEED_FILE = BASE_DIR / "nasheed.mp3"
NASHEED_VOLUME = 0.055

WHOOSH_SFX_FILE = BASE_DIR / "sfx_whoosh.mp3"
POP_SFX_FILE = BASE_DIR / "sfx_pop.mp3"
DING_SFX_FILE = BASE_DIR / "sfx_ding.mp3"

SFX_VOLUME_WHOOSH = 0.13
SFX_VOLUME_POP = 0.10
SFX_VOLUME_DING = 0.15

SFX_MAX_DURATION_WHOOSH = 0.80
SFX_MAX_DURATION_POP = 0.45
SFX_MAX_DURATION_DING = 0.85

SFX_DELAY_WHOOSH = 90
SFX_DELAY_POP = 70
SFX_DELAY_DING = 110

# ============================================================
# MASCOTTES
# ============================================================

MASCOT_FILES = {
    "default":    BASE_DIR / "mascot_default.png",
    "thinking":   BASE_DIR / "mascot_thinking.png",
    "confused":   BASE_DIR / "mascot_confused.png",
    "laughing":   BASE_DIR / "mascot_laughing.png",
    "explaining": BASE_DIR / "mascot_explaining.png",
    "surprised":  BASE_DIR / "mascot_surprised.png",
    "angry":      BASE_DIR / "mascot_angry.png",
    "happy":      BASE_DIR / "mascot_happy.png",
    "shocked":    BASE_DIR / "mascot_shocked.png",
    "sad":        BASE_DIR / "mascot_sad.png",
}

def has_any_mascot() -> bool:
    return any(p.exists() for p in MASCOT_FILES.values())

class ShortTooShortError(RuntimeError): pass
class ShortTooLongError(RuntimeError): pass

# ============================================================
# SCHÉMA GEMINI
# ============================================================

class Scene(BaseModel):
    text: str = Field(description="UNE SEULE phrase. Fin : . ! ou ?")
    emotion: str = Field(description="default, thinking, confused, laughing, explaining, surprised, angry, happy, shocked, sad")
    intensity: int = Field(description="Intensité 1 à 5. Jamais 3 de suite identiques.")
    visual_query: str = Field(
        description=(
            "Action FILMABLE en anglais, 2-4 mots, SUJET PHYSIQUE + VERBE D'ACTION FORT. "
            "Ex: 'man walking street', 'woman typing laptop', 'person running park'. JAMAIS statique."
        )
    )

class ScriptOutput(BaseModel):
    format_choisi: str = Field(description="short_single, short_twoparts, ou long_plus_teaser")
    title: str = Field(description="Titre honnête, max 65 caractères.")
    hashtags: List[str] = Field(description="4 à 6 hashtags.")
    script_principal: List[Scene] = Field(description="150-180 mots.")
    script_teaser: List[Scene] = Field(default_factory=list)

# ============================================================
# OUTILS & QC
# ============================================================

def cleanup_old_temp_dirs(max_age_hours=2):
    now = time.time()
    try:
        items = list(TEMP_DIR.iterdir())
    except Exception:
        return
    for item in items:
        if not item.is_dir(): continue
        try:
            if now - item.stat().st_mtime > max_age_hours * 3600:
                shutil.rmtree(item, ignore_errors=True)
        except Exception:
            pass

def run_command(command, cwd=None):
    cmd_str = [str(arg) for arg in command]
    try:
        return subprocess.run(cmd_str, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True, cwd=cwd)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Erreur Shell:\nCommande: {' '.join(cmd_str)}\nErreur: {e.stderr[-3000:]}")

def get_media_duration(file_path: Path) -> float:
    if not file_path.exists() or file_path.stat().st_size == 0: return 0.0
    cmd = [FFPROBE_BIN, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(file_path)]
    try:
        return float(run_command(cmd).stdout.strip())
    except ValueError:
        return 0.0

def count_words_in_scenes(scenes) -> int:
    return sum(len(str(s.get("text", "")).strip().split()) for s in scenes or [])

def qc_validate_video(video_path, expected_format=None):
    if not video_path.exists(): raise RuntimeError("QC Échec : fichier final absent.")
    duration = get_media_duration(video_path)
    if duration <= 0: raise RuntimeError("QC Échec : durée illisible.")
    return duration

# ============================================================
# TTS & PROMPT
# ============================================================

def fix_phonetics_for_tts(text: str) -> str:
    return text.replace("le faire buguer", "le faire beuguer")

def generate_tts(text: str, output_path: Path, emotion: str = "default", is_cta: bool = False):
    spoken_text = fix_phonetics_for_tts(text)
    rate = TTS_RATE_CTA if is_cta else TTS_RATE_BY_EMOTION.get(emotion, "+10%")
    run_command(["edge-tts", "--voice", TTS_VOICE, "--rate", rate, "--text", spoken_text, "--write-media", str(output_path)])

SYSTEM_PROMPT = f"""
Tu es le réalisateur et scénariste de la chaîne YouTube/TikTok "Cerveau Curieux".
OBJECTIF : Créer des Shorts modernes, dynamiques, drôles et documentés.

RÈGLE 1 : UNE SCÈNE = UNE SEULE PHRASE. Fin : . ! ou ?
RÈGLE 2 : RELANCES OBLIGATOIRES toutes les 2-3 scènes (ex: "Attends.", "Sauf que..."). Punchlines percutantes.
RÈGLE 3 : RYTHME VARIABLE d'intensité (1 à 5). JAMAIS 3 intensités identiques de suite.

VISUAL_QUERY — RÈGLE ABSOLUE POUR LES VIDÉOS :
Format : 2 à 4 mots en anglais. SUJET PHYSIQUE + VERBE DE MOUVEMENT.
Ex: "man walking street", "woman typing laptop", "couple laughing dinner".
INTERDIT les verbes statiques (sitting, standing, thinking) ou les concepts abstraits.

Identité :
Scène 1 DOIT commencer par : "{INTRO_SIGNATURE}"
Dernière scène (CTA) EXACTEMENT : "{CTA_SIGNATURE}"
"""

def normalize_hashtags(hashtags):
    clean = []
    for tag in hashtags or []:
        tag = tag.strip()
        if not tag: continue
        if not tag.startswith("#"): tag = "#" + tag
        tag = re.sub(r"[^\w#]", "", tag)
        if len(tag) > 1 and tag.lower() not in [x.lower() for x in clean]:
            clean.append(tag)
    return clean[:6]

def clean_pexels_query(query: str) -> str:
    words = [w for w in re.sub(r"[^a-zA-Z\s]", "", query or "").split() if len(w) > 2]
    return " ".join(words[:4])

def normalize_scene(scene) -> Optional[Dict]:
    if hasattr(scene, "model_dump"): scene = scene.model_dump()
    if not isinstance(scene, dict): return None
    text = str(scene.get("text", "")).strip()
    if not text: return None
    return {
        "text": text,
        "emotion": str(scene.get("emotion", "default")).strip().lower(),
        "intensity": max(1, min(5, int(scene.get("intensity", 3)))),
        "visual_query": (clean_pexels_query(str(scene.get("visual_query", ""))) or "person walking")[:80],
    }

SENTENCE_SPLIT_RE = re.compile(r"(?<=[\.!\?])\s+(?=[A-ZÀ-Ý])")

def split_multi_sentence_scenes(scenes: List[Dict]) -> List[Dict]:
    result = []
    for scene in scenes:
        parts = [p.strip() for p in SENTENCE_SPLIT_RE.split(scene["text"].strip()) if p.strip()]
        if len(parts) <= 1:
            result.append(scene)
        else:
            for part in parts:
                new_scene = dict(scene)
                new_scene["text"] = part
                result.append(new_scene)
    return result

def enforce_rhythm_diversity(scenes: List[Dict]) -> List[Dict]:
    for i in range(2, len(scenes)):
        if scenes[i - 2].get("intensity", 3) == scenes[i - 1].get("intensity", 3) == scenes[i].get("intensity", 3):
            scenes[i]["intensity"] = 5 if scenes[i]["intensity"] < 4 else 1
    return scenes

def dedupe_visual_queries(scenes: List[Dict]) -> List[Dict]:
    variants = ["man walking street", "woman typing laptop", "person running park", "student writing notebook"]
    for i in range(1, len(scenes)):
        if scenes[i].get("visual_query") == scenes[i - 1].get("visual_query"):
            scenes[i]["visual_query"] = random.choice(variants)
    return scenes

def validate_and_repair_script(data: Dict) -> Dict:
    scenes = [s for s in [normalize_scene(s) for s in data.get("script_principal") or []] if s]
    if not scenes: raise RuntimeError("Script Gemini vide.")
    
    scenes = dedupe_visual_queries(enforce_rhythm_diversity(split_multi_sentence_scenes(scenes)))
    if not scenes[0]["text"].lower().startswith(INTRO_SIGNATURE.lower()):
        scenes[0]["text"] = f"{INTRO_SIGNATURE}, {scenes[0]['text']}"
        
    scenes[-1]["text"] = CTA_SIGNATURE
    scenes[-1]["emotion"], scenes[-1]["intensity"], scenes[-1]["visual_query"] = "happy", 5, "smiling person thumbs up"
    data["script_principal"] = scenes

    teaser = [s for s in [normalize_scene(s) for s in data.get("script_teaser") or []] if s]
    data["script_teaser"] = dedupe_visual_queries(enforce_rhythm_diversity(split_multi_sentence_scenes(teaser)))
    data["format_choisi"] = data.get("format_choisi") if data.get("format_choisi") in {"short_single", "short_twoparts", "long_plus_teaser"} else "short_single"
    title = re.sub(r"\s+", " ", str(data.get("title", "Pourquoi ton cerveau fait ça"))).strip("\"'")[:65].rstrip()
    data["title"] = title or "Pourquoi ton cerveau fait ça"
    data["hashtags"] = normalize_hashtags(data.get("hashtags", [])) or ["#Cerveau", "#Psychologie", "#Science"]
    return data

# ============================================================
# GEMINI CALLS
# ============================================================

def call_gemini_script(client, contents: str) -> Dict:
    res = client.models.generate_content(
        model="gemini-3.6-flash", contents=contents,
        config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT, response_mime_type="application/json", response_schema=ScriptOutput, temperature=0.75)
    )
    parsed = res.parsed.model_dump() if hasattr(res, "parsed") and res.parsed else json.loads(res.text)
    return validate_and_repair_script(parsed)

def generate_script_gemini(topic: str, status_cb) -> Tuple[Dict, object]:
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = f"Sujet : {topic.strip()}\nShort : {SHORT_TARGET_MIN_WORDS}-{SHORT_TARGET_MAX_WORDS} mots.\nDurée : > 45s. Scène 1: '{INTRO_SIGNATURE}'. Fin: '{CTA_SIGNATURE}'."
    status_cb("🧠 Analyse du sujet...")
    return call_gemini_script(client, prompt), client

def repair_script_by_real_duration(client, topic, data, measured_duration, status_cb):
    current_script = "\n".join(s.get("text", "") for s in data.get("script_principal", []))
    prompt = f"Sujet : {topic.strip()}\nDurée : {measured_duration:.1f}s.\nVise 55-75s.\nScript actuel:\n{current_script}\nAdapte la longueur. Format: {data.get('format_choisi')}."
    repaired = call_gemini_script(client, prompt)
    repaired["format_choisi"] = data.get("format_choisi")
    return validate_and_repair_script(repaired)

# ============================================================
# APIs VIDÉO RECHERCHE & TÉLÉCHARGEMENT
# ============================================================

def search_pexels_video(query: str, orientation: str, used_urls: Optional[set] = None) -> Optional[str]:
    if not PEXELS_API_KEY: return None
    used_urls = used_urls or set()
    clean_query = clean_pexels_query(query) or "person walking"
    
    attempts = [clean_query, " ".join(clean_query.split()[:2]), "person walking street"]
    for attempt in attempts:
        try:
            r = requests.get("https://api.pexels.com/videos/search", headers={"Authorization": PEXELS_API_KEY},
                             params={"query": attempt, "orientation": orientation, "per_page": 40}, timeout=12)
            if r.status_code != 200: continue
            
            candidates = []
            for video in r.json().get("videos", []):
                dur = float(video.get("duration", 0) or 0)
                if dur < 3: continue
                for fi in video.get("video_files", []):
                    link, w, h = fi.get("link"), int(fi.get("width", 0) or 0), int(fi.get("height", 0) or 0)
                    if not link or ".mp4" not in str(link).lower() or w <= 0 or h <= 0: continue
                    if (orientation == "portrait" and h < 720) or (orientation == "landscape" and w < 1280): continue
                    candidates.append((dur * 1_000_000 + w * h, link))
                    
            if candidates:
                fresh = [c for c in candidates if c[1] not in used_urls]
                pool = fresh if fresh else candidates
                return random.choice(sorted(pool, reverse=True)[:5])[1]
        except Exception: continue
    return None

def search_pixabay_video(query: str, orientation: str, used_urls: Optional[set] = None) -> Optional[str]:
    if not PIXABAY_API_KEY: return None
    used_urls = used_urls or set()
    try:
        r = requests.get("https://pixabay.com/api/videos/", params={
            "key": PIXABAY_API_KEY, "q": clean_pexels_query(query) or "person walking",
            "video_type": "film", "orientation": "vertical" if orientation == "portrait" else "horizontal",
            "per_page": 30, "safesearch": "true", "min_duration": 3
        }, timeout=12)
        if r.status_code != 200: return None
        
        candidates = []
        for hit in r.json().get("hits", []):
            dur = float(hit.get("duration", 0) or 0)
            if dur < 3: continue
            for quality in ["large", "medium", "small"]:
                v = hit.get("videos", {}).get(quality)
                if v and v.get("url") and int(v.get("width", 0) or 0) > 0:
                    candidates.append((dur * 1_000_000 + v["width"] * v["height"], v["url"]))
                    break
                    
        if candidates:
            fresh = [c for c in candidates if c[1] not in used_urls]
            pool = fresh if fresh else candidates
            return random.choice(sorted(pool, reverse=True)[:5])[1]
    except Exception: pass
    return None

def download_file(url: str, dest: Path) -> bool:
    try:
        with requests.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=64 * 1024):
                    if chunk: f.write(chunk)
        return dest.exists() and dest.stat().st_size > 10000
    except Exception: return False

# ============================================================
# COMPOSITION VIDÉO ET SOUS-TITRES
# ============================================================

def create_ass_subtitles(scenes: List[Dict], output_ass: Path, width: int, height: int):
    sub_fontsize, sub_margin_v = (72, int(height * 0.24)) if height > width else (48, 120)
    lines = []
    current_time = 0.0

    for scene in scenes:
        dur = float(scene.get("duration", 0))
        words = str(scene.get("text", "")).replace("\n", " ").replace("{", "").replace("}", "").strip().split()
        if not words:
            current_time += dur
            continue

        chunk_size = 4 if height > width else 5
        chunks = [words[i:i + chunk_size] for i in range(0, len(words), chunk_size)]
        chunk_duration = dur / len(chunks)

        for idx_c, chunk_words in enumerate(chunks):
            c_start = current_time + idx_c * chunk_duration
            w_dur = chunk_duration / len(chunk_words)
            for idx_w, w in enumerate(chunk_words):
                s_t = c_start + idx_w * w_dur
                e_t = s_t + w_dur
                fmt_words = ["{\\c&H00FFFF&}" + re.sub(r"[,.?!;:]", "", ww) + "{\\c&HFFFFFF&}" if k == idx_w else re.sub(r"[,.?!;:]", "", ww) for k, ww in enumerate(chunk_words)]
                lines.append(f"Dialogue: 0,{ass_time(s_t)},{ass_time(e_t)},Default,,0,0,0,,{' '.join(fmt_words)}")
        current_time += dur

    header = f"[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nScaledBorderAndShadow: yes\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,DejaVu Sans,{sub_fontsize},&H00FFFFFF,&H00000000,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,3,2,40,40,{sub_margin_v},1\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    with open(output_ass, "w", encoding="utf-8") as f: f.write(header + "\n".join(lines))

def ass_time(seconds: float) -> str:
    h, m, s = int(seconds // 3600), int((seconds % 3600) // 60), int(seconds % 60)
    return f"{h}:{m:02d}:{s:02d}.{int((seconds - int(seconds)) * 100):02d}"

def process_scene_audio(scene, idx, total_scenes, work_dir):
    temp_audio, processed_audio = work_dir / f"temp_{idx:03d}.mp3", work_dir / f"audio_{idx:03d}.wav"
    generate_tts(scene["text"], temp_audio, scene.get("emotion", "default"), is_cta=(idx == total_scenes - 1))
    
    cmd = [FFMPEG_BIN, "-y", "-i", str(temp_audio), "-af", "aresample=48000,aformat=channel_layouts=stereo,loudnorm=I=-16:LRA=11:TP=-1.5", "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(processed_audio)]
    run_command(cmd, cwd=work_dir)
    scene["duration"] = get_media_duration(processed_audio)
    return processed_audio

def concatenate_audio(audio_clips, work_dir):
    raw_audio = work_dir / "raw_audio.wav"
    with open(work_dir / "concat_audio.txt", "w", encoding="utf-8") as f:
        for a in audio_clips: f.write(f"file '{a.name}'\n")
    run_command([FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0", "-i", "concat_audio.txt", "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(raw_audio)], cwd=work_dir)
    return raw_audio

def add_nasheed_track(voice_audio, work_dir):
    output = work_dir / "full_audio.m4a"
    run_command([FFMPEG_BIN, "-y", "-i", str(voice_audio), "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", str(output)], cwd=work_dir)
    return output

def create_video_clip_from_pexels(visual_file, mascot_img, output_clip, duration, width, height, mascot_scale, pos_x, pos_y, enable_expr, work_dir, intensity=3):
    total_frames = max(1, int(duration * 30))
    zoom_end = 1.03 + (min(intensity, 5) - 1) * 0.0075
    
    if mascot_img and Path(mascot_img).exists():
        fc = (f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps=30,setsar=1,"
              f"zoompan=z='min(zoom+0.0006,{zoom_end})':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}[bg];"
              f"[1:v]scale={mascot_scale}:-1,format=rgba,fade=t=in:st=0:d=0.2,fade=t=out:st={max(0.1, min(2.5, duration)-0.35)}:d=0.3[mascot];"
              f"[bg][mascot]overlay=x={pos_x}:y={pos_y}:enable='{enable_expr}'[v_out]")
        cmd = [FFMPEG_BIN, "-y", "-stream_loop", "-1", "-i", str(visual_file), "-loop", "1", "-i", str(mascot_img.resolve()), "-t", str(duration),
               "-filter_complex", fc, "-map", "[v_out]", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30", str(output_clip)]
    else:
        fc = f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps=30,setsar=1,zoompan=z='min(zoom+0.0006,{zoom_end})':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}[v_out]"
        cmd = [FFMPEG_BIN, "-y", "-stream_loop", "-1", "-i", str(visual_file), "-t", str(duration),
               "-filter_complex", fc, "-map", "[v_out]", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30", str(output_clip)]
    run_command(cmd, cwd=work_dir)

def create_blank_video_fallback(output_clip, duration, width, height, work_dir):
    # Ultimate fail-safe vidéo généré par FFmpeg (fond sombre abstrait) au lieu d'une simple image
    fc = f"color=c=#1a1a2e:s={width}x{height}:d={duration}[bg]; [bg]noise=alls=10:allf=t+u[v_out]"
    cmd = [FFMPEG_BIN, "-y", "-f", "lavfi", "-i", fc, "-map", "[v_out]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30", str(output_clip)]
    run_command(cmd, cwd=work_dir)

# ============================================================
# PIPELINE PRINCIPAL
# ============================================================

def generate_video_pipeline(script_scenes, video_format, status_cb):
    work_dir = TEMP_DIR / f"run_{int(time.time())}_{video_format}_{random.randint(1000,9999)}"
    work_dir.mkdir(parents=True, exist_ok=True)
    width, height, orientation = (1080, 1920, "portrait") if video_format == "portrait" else (1920, 1080, "landscape")

    mascot_available = has_any_mascot()
    status_cb("🎙️ Génération de la voix off...")
    raw_audio = concatenate_audio([process_scene_audio(s, i, len(script_scenes), work_dir) for i, s in enumerate(script_scenes)], work_dir)
    full_audio = add_nasheed_track(raw_audio, work_dir)
    voice_duration = get_media_duration(full_audio)
    
    if video_format == "portrait" and not (SHORT_MIN_DURATION <= voice_duration <= SHORT_MAX_DURATION):
        raise ShortTooShortError(f"Durée {voice_duration:.1f}s hors limites.")

    status_cb("🎥 Recherche stricte de clips vidéo...")
    video_clips, used_urls = [], set()
    mascot_scale = int(width * (0.19 if video_format == "portrait" else 0.14))
    mascot_positions = [("(W-w)/2", "H-h-470"), ("40", "H-h-470"), ("W-w-40", "H-h-470")] if video_format == "portrait" else [("40", "H-h-40"), ("W-w-40", "H-h-40"), ("40", "H-h-120")]

    for idx, scene in enumerate(script_scenes):
        dur = max(0.5, float(scene.get("duration", 1.0)))
        mascot_img = MASCOT_FILES.get(scene.get("emotion", "default"), MASCOT_FILES["default"]) if mascot_available else None
        visual_file, output_clip = work_dir / f"src_{idx:03d}.mp4", work_dir / f"clip_{idx:03d}.mp4"
        pos_x, pos_y = mascot_positions[idx % len(mascot_positions)]
        
        got_clip = False
        queries_to_try = [scene.get("visual_query", "person walking"), "city timelapse", "abstract motion", "nature driving"]
        
        for q in queries_to_try:
            if got_clip: break
            url = search_pexels_video(q, orientation, used_urls)
            if url and download_file(url, visual_file):
                used_urls.add(url); got_clip = True
            elif PIXABAY_API_KEY and not got_clip:
                url = search_pixabay_video(q, orientation, used_urls)
                if url and download_file(url, visual_file):
                    used_urls.add(url); got_clip = True

        if got_clip:
            create_video_clip_from_pexels(visual_file, mascot_img, output_clip, dur, width, height, mascot_scale, pos_x, pos_y, f"between(t,0,{min(2.5, dur)})", work_dir, int(scene.get("intensity", 3)))
        else:
            status_cb(f"⚠️ API saturée, génération d'un fond vidéo dynamique natif pour la scène {idx+1}")
            create_blank_video_fallback(output_clip, dur, width, height, work_dir)
        video_clips.append(output_clip)

    status_cb("⚡ Fusion et sous-titres...")
    with open(work_dir / "concat_video.txt", "w", encoding="utf-8") as f:
        for v in video_clips: f.write(f"file '{v.name}'\n")
    run_command([FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0", "-i", "concat_video.txt", "-c", "copy", "raw_video.mp4"], cwd=work_dir)

    create_ass_subtitles(script_scenes, work_dir / "subtitles.ass", width, height)
    final_output = OUTPUT_DIR / f"export_{int(time.time())}_{video_format}.mp4"
    
    cmd_final = [FFMPEG_BIN, "-y", "-i", "raw_video.mp4", "-i", "full_audio.m4a", "-vf", f"subtitles=subtitles.ass,drawtext=text='CERVEAU CURIEUX':x=35:y={55 if video_format == 'portrait' else 35}:fontsize=25:fontcolor=white:box=1:boxcolor=black@0.45:boxborderw=7", "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", "-movflags", "+faststart", str(final_output.resolve())]
    run_command(cmd_final, cwd=work_dir)
    return final_output

def split_video_in_two(input_video, total_duration, out_dir):
    mid = total_duration / 2.0
    p1, p2 = out_dir / f"{input_video.stem}_P1.mp4", out_dir / f"{input_video.stem}_P2.mp4"
    run_command([FFMPEG_BIN, "-y", "-i", str(input_video), "-t", str(mid), "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", str(p1)])
    run_command([FFMPEG_BIN, "-y", "-ss", str(mid), "-i", str(input_video), "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", str(p2)])
    return p1, p2

# ============================================================
# APP STREAMLIT MAIN
# ============================================================

def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="🧠", layout="centered")
    if "generation_done" not in st.session_state: st.session_state.update({"generation_done": False, "ai_data": None})

    st.markdown("<style>.stApp { background-color: #0E1117; }</style>", unsafe_allow_html=True)
    st.title("🧠 Cerveau Curieux - Auto Studio")

    topic = st.text_area("Sujet du short", placeholder="Ex: Pourquoi on oublie nos rêves ?")
    
    if st.button("🚀 LANCER LA PRODUCTION", type="primary"):
        with st.status("🎬 Production en cours...", expanded=True) as status:
            try:
                ai_data, client = generate_script_gemini(topic, st.write)
                v_path = generate_video_pipeline(ai_data["script_principal"], "portrait", st.write)
                st.session_state.update({"generation_done": True, "ai_data": ai_data, "v_path": v_path})
                status.update(label="🎉 Terminé !", state="complete", expanded=False)
            except Exception as e:
                status.update(label="❌ Erreur", state="error")
                st.error(str(e))

    if st.session_state.generation_done:
        st.video(str(st.session_state.v_path))
        with open(st.session_state.v_path, "rb") as f:
            st.download_button("⬇️ Télécharger", f.read(), file_name=st.session_state.v_path.name, mime="video/mp4")

if __name__ == "__main__":
    main()
