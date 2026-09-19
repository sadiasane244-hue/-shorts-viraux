import streamlit as st
import os
import sys
import json
import time
import random
import shutil
import re
import subprocess
import requests
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from pydantic import BaseModel, Field

# NOUVEAU SDK GOOGLE GENAI
from google import genai
from google.genai import types

from PIL import Image

# ============================================================
# 📁 CONFIGURATION DES DOSSIERS & CONSTANTES
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
TEMP_DIR = BASE_DIR / "temp"
OUTPUT_DIR = BASE_DIR / "output"

TEMP_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

FFMPEG_BIN = "ffmpeg"
FFPROBE_BIN = "ffprobe"

APP_TITLE = "Cerveau Curieux IA"
INTRO_SIGNATURE = "Wesh l'équipe"
CTA_SIGNATURE = "Et maintenant que ton cerveau sait ça... abonne-toi frérot, parce qu'on n'a pas fini de le faire buguer."

# Bruitages & Musique
NASHEED_FILE = BASE_DIR / "nasheed.mp3"
NASHEED_VOLUME = 0.055

WHOOSH_SFX_FILE = BASE_DIR / "sfx_whoosh.mp3"
POP_SFX_FILE = BASE_DIR / "sfx_pop.mp3"
DING_SFX_FILE = BASE_DIR / "sfx_ding.mp3"

# Mascottes
MASCOT_FILES = {
    "default": BASE_DIR / "mascot_default.png",
    "thinking": BASE_DIR / "mascot_thinking.png",
    "confused": BASE_DIR / "mascot_confused.png",
    "laughing": BASE_DIR / "mascot_laughing.png",
    "explaining": BASE_DIR / "mascot_explaining.png",
    "surprised": BASE_DIR / "mascot_surprised.png",
    "angry": BASE_DIR / "mascot_angry.png",
    "happy": BASE_DIR / "mascot_happy.png",
    "shocked": BASE_DIR / "mascot_shocked.png",
    "sad": BASE_DIR / "mascot_sad.png",
}

if not MASCOT_FILES["default"].exists():
    Image.new("RGBA", (200, 200), color=(0, 0, 0, 0)).save(MASCOT_FILES["default"])

# ============================================================
# ⏱️ DURÉE DES SHORTS
# ============================================================

SHORT_MIN_DURATION = 35.0
SHORT_TARGET_MIN_DURATION = 40.0
SHORT_TARGET_MAX_DURATION = 65.0
SHORT_MAX_DURATION = 90.0

SHORT_MIN_WORDS = 100
SHORT_TARGET_MIN_WORDS = 120
SHORT_TARGET_MAX_WORDS = 170
SHORT_MAX_WORDS = 200

class ShortTooShortError(Exception): pass
class ShortTooLongError(Exception): pass

# ============================================================
# 🧠 SCHÉMA JSON GEMINI
# ============================================================

class Scene(BaseModel):
    text: str = Field(description="Une seule phrase courte de narration. Ton moderne, jeune, urbain, humoristique et naturel.")
    emotion: str = Field(description="Émotion de la mascotte parmi: default, thinking, confused, laughing, explaining, surprised, angry, happy, shocked, sad")
    visual_query: str = Field(description="Mots-clés visuels en anglais, 2 à 4 mots, très expressifs et exagérés (ex: funny brain glitch) pour Pexels.")
    sfx: str = Field(default="", description="Nom exact de l'effet sonore sans l'extension. Options: sfx_boom, sfx_glitch, sfx_siren, sfx_punch, sfx_cricket, sfx_cash, sfx_laugh, sfx_suspense, sfx_whoosh, sfx_pop, sfx_ding. Laisse vide s'il n'y a pas besoin de bruitage.")

class ScriptOutput(BaseModel):
    format_choisi: str = Field(description="Choix parmi: short_single, short_twoparts, long_plus_teaser")
    title: str = Field(description="Titre YouTube/TikTok très accrocheur. Maximum 65 caractères.")
    hashtags: List[str] = Field(description="4 à 6 hashtags pertinents.")
    script_principal: List[Scene] = Field(description="Scènes principales. Pour un Short, viser 120 à 170 mots.")
    script_teaser: List[Scene] = Field(default_factory=list, description="Scènes du teaser si besoin.")

SYSTEM_PROMPT = f"""
Tu es le réalisateur et scénariste de la chaîne YouTube/TikTok "Cerveau Curieux".
OBJECTIF : Créer des vidéos virales, humoristiques, dynamiques et documentées sur le cerveau, la psychologie et les comportements humains.

IDENTITÉ DE MARQUE & STYLE:
La première scène DOIT commencer exactement par : "{INTRO_SIGNATURE}"
- Tutoiement. Ton humoristique, percutant, décalé (utilise des mots comme buguer, dinguerie, parano).
- Des phrases courtes pour un montage frénétique.
- Le texte doit sonner comme une vraie personne sur TikTok.

DURÉE DES SHORTS:
Le Short doit durer au minimum 35 secondes. Zone idéale : environ 45 à 65 secondes (soit 120 à 170 mots).

PEXELS, MASCOTTES ET BRUITAGES (SFX):
Chaque scène est accompagnée d'une vidéo Pexels, d'une mascotte et d'un bruitage optionnel.
Laisse le champ 'sfx' vide ("") si la phrase n'a pas besoin d'accentuation. Utilise les sons comme sfx_boom, sfx_glitch, sfx_siren, etc.

CTA:
La dernière scène DOIT être exactement : "{CTA_SIGNATURE}"
"""

# ============================================================
# 🛠️ FONCTIONS UTILITAIRES
# ============================================================

def run_command(cmd: List[str], cwd: Path = BASE_DIR):
    res = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Erreur Shell:\nCommande: {' '.join(cmd)}\nErreur: {res.stderr[-3000:]}")
    return res

def get_media_duration(file_path: Path) -> float:
    if not file_path.exists() or file_path.stat().st_size == 0: return 0.0
    cmd = [FFPROBE_BIN, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(file_path)]
    res = run_command(cmd)
    try:
        return float(res.stdout.strip())
    except ValueError:
        return 0.0

def fix_phonetics_for_tts(text: str) -> str:
    return text.replace("le faire buguer", "le faire beuguer")

def generate_tts(text: str, output_path: Path):
    spoken_text = fix_phonetics_for_tts(text)
    cmd = ["edge-tts", "--voice", "fr-FR-HenriNeural", "--rate", "+5%", "--text", spoken_text, "--write-media", str(output_path)]
    run_command(cmd)

def search_pexels_video(query: str, orientation: str) -> Optional[str]:
    api_key = os.getenv("PEXELS_API_KEY") or st.secrets.get("PEXELS_API_KEY", "")
    if not api_key: return None
    
    clean_query = clean_pexels_query(query)
    if not clean_query: clean_query = "funny thinking"
    
    url = "https://api.pexels.com/videos/search"
    headers = {"Authorization": api_key}
    params = {"query": clean_query, "orientation": orientation, "per_page": 12}
    
    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        if r.status_code != 200: return None
        videos = r.json().get("videos", [])
        candidates = []
        for video in videos:
            files = [f for f in video.get("video_files", []) if ".mp4" in str(f.get("link", "")).lower()]
            for file_info in files:
                w = int(file_info.get("width", 0) or 0)
                h = int(file_info.get("height", 0) or 0)
                link = file_info.get("link")
                if not link: continue
                if orientation == "portrait" and h < 720: continue
                if orientation == "landscape" and w < 1280: continue
                candidates.append((w * h, link))
        if not candidates: return None
        candidates.sort(key=lambda x: x[0], reverse=True)
        top = candidates[:min(5, len(candidates))]
        return random.choice(top)[1]
    except Exception:
        return None

def download_file(url: str, dest: Path) -> bool:
    try:
        with requests.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=64 * 1024):
                    if chunk: f.write(chunk)
        return dest.exists() and dest.stat().st_size > 10000
    except Exception:
        return False

def clean_pexels_query(query: str) -> str:
    query = re.sub(r"[^a-zA-Z\s]", "", query or "")
    words = [w for w in query.split() if len(w) > 2]
    return " ".join(words[:4])

def count_words_in_scenes(scenes: List[Dict]) -> int:
    return sum(len(str(scene.get("text", "")).split()) for scene in scenes or [])

def cleanup_old_temp_dirs(max_age_hours=2):
    now = time.time()
    for item in TEMP_DIR.iterdir():
        if item.is_dir():
            try:
                if now - item.stat().st_mtime > max_age_hours * 3600:
                    shutil.rmtree(item, ignore_errors=True)
            except Exception: pass

# ============================================================
# 🤖 GEMINI (NOUVEAU SDK) & NORMALISATION
# ============================================================

def normalize_scene(scene) -> Optional[Dict]:
    if hasattr(scene, "model_dump"): scene = scene.model_dump()
    if not isinstance(scene, dict): return None

    text = str(scene.get("text", "")).strip()
    emotion = str(scene.get("emotion", "default")).strip().lower()
    visual_query = str(scene.get("visual_query", "funny person")).strip()
    sfx = str(scene.get("sfx", "")).strip().lower()

    if not text: return None

    if emotion not in set(MASCOT_FILES.keys()):
        emotion = "default"

    visual_query = clean_pexels_query(visual_query) or "funny person"
    sfx = sfx.replace(".mp3", "")

    return {
        "text": text,
        "emotion": emotion,
        "visual_query": visual_query[:80],
        "sfx": sfx
    }

def call_gemini_script(client, contents: str) -> Dict:
    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=ScriptOutput,
            temperature=0.75,
        ),
    )
    
    parsed = None
    if hasattr(response, "parsed") and response.parsed:
        parsed = response.parsed.model_dump()
    if parsed is None:
        parsed = json.loads(response.text)
        
    # Normalisation propre
    if "script_principal" in parsed:
        parsed["script_principal"] = [normalize_scene(s) for s in parsed["script_principal"] if normalize_scene(s)]
        
        # Sécurité Intro & CTA
        if parsed["script_principal"]:
            first_text = parsed["script_principal"][0]["text"]
            if not first_text.lower().startswith(INTRO_SIGNATURE.lower()):
                parsed["script_principal"][0]["text"] = INTRO_SIGNATURE + ". " + first_text
                
            parsed["script_principal"][-1]["text"] = CTA_SIGNATURE
            parsed["script_principal"][-1]["emotion"] = "happy"
            parsed["script_principal"][-1]["sfx"] = "sfx_ding"
            
    return parsed

def generate_script_gemini(topic: str, status_cb) -> Tuple[Dict, any]:
    api_key = os.getenv("GEMINI_API_KEY") or st.secrets.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("Clé API GEMINI manquante.")
        
    client = genai.Client(api_key=api_key)
    status_cb("🧠 Analyse du sujet et rédaction du script avec google-genai...")
    
    prompt = f"""
    Sujet à traiter : {topic.strip()}
    
    Crée le contenu complet de la vidéo humoristique.
    Vise {SHORT_TARGET_MIN_WORDS} à {SHORT_TARGET_MAX_WORDS} mots.
    Durée recherchée : {SHORT_TARGET_MIN_DURATION} à {SHORT_TARGET_MAX_DURATION} secondes.
    """
    
    data = call_gemini_script(client, prompt)
    return data, client

def repair_script_by_real_duration(client, topic: str, data: Dict, measured_duration: float, status_cb) -> Dict:
    scenes = data.get("script_principal", [])
    current_script = "\n".join(scene.get("text", "") for scene in scenes)
    
    if measured_duration < SHORT_MIN_DURATION:
        status_cb(f"⏱️ Durée réelle trop courte ({measured_duration:.1f} s). Ajout d'humour et faits...")
        instruction = "Il faut dépasser 35 secondes. Ajoute de vraies informations et des vannes, sans blabla."
    else:
        status_cb(f"⏱️ Durée réelle trop longue ({measured_duration:.1f} s). Resserrement...")
        instruction = "Resserre le script pour viser environ 45-65 secondes. Supprime les longueurs."

    prompt = f"Sujet : {topic}\n{instruction}\n\nSCRIPT ACTUEL :\n{current_script}\n\nConserve le format humoristique."
    
    repaired = call_gemini_script(client, prompt)
    repaired["format_choisi"] = data.get("format_choisi", repaired.get("format_choisi", "short_single"))
    return repaired

# ============================================================
# 🎧 AUDIO (SFX, TTS, MIXAGE)
# ============================================================

def choose_sfx_for_scene(scene: Dict, idx: int, total_scenes: int) -> Optional[Dict]:
    sfx_name = scene.get("sfx", "")
    if idx == total_scenes - 1: sfx_name = "sfx_ding"

    if not sfx_name: return None
    sfx_file = BASE_DIR / f"{sfx_name}.mp3"

    if not sfx_file.exists():
        if "boom" in sfx_name or "punch" in sfx_name: sfx_file = BASE_DIR / "sfx_pop.mp3"
        elif "glitch" in sfx_name or "siren" in sfx_name: sfx_file = BASE_DIR / "sfx_whoosh.mp3"
        else: return None

    if not sfx_file.exists(): return None

    volume_map = {
        "sfx_boom": 0.20, "sfx_siren": 0.12, "sfx_glitch": 0.15,
        "sfx_punch": 0.18, "sfx_cricket": 0.25, "sfx_laugh": 0.18,
        "sfx_suspense": 0.15, "sfx_ding": 0.15, "sfx_pop": 0.10,
        "sfx_whoosh": 0.13, "sfx_cash": 0.15
    }
    
    return {
        "file": sfx_file,
        "volume": volume_map.get(sfx_name, 0.15),
        "delay": 50,
        "max_duration": 2.0,
        "name": sfx_name
    }

def process_scene_audio(scene: Dict, idx: int, total_scenes: int, work_dir: Path) -> Path:
    temp_audio = work_dir / f"temp_audio_{idx:03d}.mp3"
    processed_audio = work_dir / f"audio_{idx:03d}.wav"
    generate_tts(scene["text"], temp_audio)
    sfx_info = choose_sfx_for_scene(scene, idx, total_scenes)

    if not sfx_info:
        cmd = [FFMPEG_BIN, "-y", "-i", str(temp_audio), "-af", "aresample=48000,aformat=channel_layouts=stereo,loudnorm=I=-16:LRA=11:TP=-1.5", "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(processed_audio)]
        run_command(cmd, cwd=work_dir)
    else:
        cmd = [
            FFMPEG_BIN, "-y", "-i", str(temp_audio), "-i", str(sfx_info["file"]),
            "-filter_complex",
            (f"[0:a]aresample=48000,aformat=channel_layouts=stereo[voice];"
             f"[1:a]atrim=0:{sfx_info['max_duration']},asetpts=N/SR/TB,volume={sfx_info['volume']},adelay={sfx_info['delay']}|{sfx_info['delay']},aresample=48000,aformat=channel_layouts=stereo[sfx];"
             "[voice][sfx]amix=inputs=2:duration=first:dropout_transition=0,loudnorm=I=-16:LRA=11:TP=-1.5[a]"),
            "-map", "[a]", "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(processed_audio)
        ]
        run_command(cmd, cwd=work_dir)

    scene["duration"] = get_media_duration(processed_audio)
    return processed_audio

def add_nasheed_track(voice_audio: Path, work_dir: Path, status_cb) -> Path:
    output = work_dir / "full_audio.m4a"
    if not NASHEED_FILE.exists():
        status_cb("🎙️ Aucun nasheed détecté : voix seule.")
        run_command([FFMPEG_BIN, "-y", "-i", str(voice_audio), "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", str(output)], cwd=work_dir)
        return output

    status_cb("🎵 Nasheed détecté : mixage vocal intelligent (ducking)...")
    cmd = [
        FFMPEG_BIN, "-y", "-i", str(voice_audio), "-stream_loop", "-1", "-i", str(NASHEED_FILE),
        "-filter_complex",
        (f"[0:a]aresample=48000,aformat=channel_layouts=stereo,volume=1.0[voice];"
         f"[1:a]aresample=48000,aformat=channel_layouts=stereo,volume={NASHEED_VOLUME},highpass=f=100,lowpass=f=9000,afade=t=in:st=0:d=1.5[nasheed_raw];"
         "[nasheed_raw][voice]sidechaincompress=threshold=0.045:ratio=7:attack=20:release=300:makeup=1:knee=3[nasheed_ducked];"
         "[voice][nasheed_ducked]amix=inputs=2:duration=first:dropout_transition=2,loudnorm=I=-16:LRA=11:TP=-1.5[mixed]"),
        "-map", "[mixed]", "-ar", "48000", "-ac", "2", "-c:a", "aac", "-b:a", "192k", str(output)
    ]
    run_command(cmd, cwd=work_dir)
    return output

def create_ass_subtitles(scenes: List[Dict], output_ass: Path, width: int, height: int):
    font_size = 58 if width == 1080 else 40
    margin_v = 300 if width == 1080 else 75
    header = f"[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nScaledBorderAndShadow: yes\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Arial,{font_size},&H00FFFFFF,&H00000000,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,2,30,30,{margin_v},1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    
    def ass_time(seconds: float) -> str:
        s = max(0.0, seconds)
        return f"{int(s//3600)}:{int((s%3600)//60):02d}:{int(s%60):02d}.{int((s-int(s))*100):02d}"

    lines = []
    current_time = 0.0
    for scene in scenes:
        scene_duration = float(scene.get("duration", 0))
        text = str(scene.get("text", "")).replace("\n", " ").replace("{", "").replace("}", "").strip()
        words = text.split()
        if not words: 
            current_time += scene_duration
            continue
            
        chunk_size = 4 if width == 1080 else 5
        chunks = [words[i:i + chunk_size] for i in range(0, len(words), chunk_size)]
        chunk_duration = scene_duration / len(chunks)

        for idx_chunk, chunk_words in enumerate(chunks):
            chunk_start = current_time + idx_chunk * chunk_duration
            word_duration = chunk_duration / len(chunk_words)
            for idx_word, word in enumerate(chunk_words):
                start_t = chunk_start + idx_word * word_duration
                end_t = start_t + word_duration
                formatted_words = []
                for k, w in enumerate(chunk_words):
                    safe_word = re.sub(r'[,\.\?!;:]', '', w)
                    if k == idx_word: formatted_words.append("{\\c&H00FFFF&}" + safe_word + "{\\c&HFFFFFF&}")
                    else: formatted_words.append(safe_word)
                lines.append(f"Dialogue: 0,{ass_time(start_t)},{ass_time(end_t)},Default,,0,0,0,,{' '.join(formatted_words)}")
        current_time += scene_duration

    with open(output_ass, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(lines))

# ============================================================
# 🎥 PIPELINE VIDÉO
# ============================================================

def create_video_clip_from_pexels(visual_file: Path, mascot_img: Path, output_clip: Path, duration: float, width: int, height: int, mascot_scale: int, pos_x: str, pos_y: str, enable_expr: str, work_dir: Path):
    fps = 30
    base_filter = f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps={fps},setsar=1[bg]"
    filter_complex = f"{base_filter};[1:v]scale={mascot_scale}:-1,format=rgba[mascot];[bg][mascot]overlay=x={pos_x}:y={pos_y}:enable='{enable_expr}'[v_out]"
    cmd = [FFMPEG_BIN, "-y", "-stream_loop", "-1", "-i", str(visual_file), "-loop", "1", "-i", str(mascot_img), "-t", str(duration), "-filter_complex", filter_complex, "-map", "[v_out]", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(fps), "-movflags", "+faststart", str(output_clip)]
    run_command(cmd, cwd=work_dir)

def create_fallback_video_clip(output_clip: Path, mascot_img: Path, duration: float, width: int, height: int, mascot_scale: int, pos_x: str, pos_y: str, enable_expr: str, work_dir: Path):
    fallback = work_dir / f"fallback_{output_clip.stem}.png"
    Image.new("RGB", (width, height), color=(20, 20, 35)).save(fallback)
    fps = 30
    filter_complex = f"[0:v]scale={width}:{height},fps={fps},setsar=1[bg];[1:v]scale={mascot_scale}:-1,format=rgba[mascot];[bg][mascot]overlay=x={pos_x}:y={pos_y}:enable='{enable_expr}'[v_out]"
    cmd = [FFMPEG_BIN, "-y", "-loop", "1", "-i", str(fallback), "-loop", "1", "-i", str(mascot_img), "-t", str(duration), "-filter_complex", filter_complex, "-map", "[v_out]", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(fps), "-movflags", "+faststart", str(output_clip)]
    run_command(cmd, cwd=work_dir)

def generate_video_pipeline(script_scenes: List[Dict], video_format: str, status_cb) -> Path:
    if not script_scenes: raise ValueError("Le script est vide.")
    work_dir = TEMP_DIR / f"run_{int(time.time())}_{video_format}_{random.randint(1000, 9999)}"
    work_dir.mkdir(parents=True, exist_ok=True)
    width, height = (1080, 1920) if video_format == "portrait" else (1920, 1080)
    orientation = "portrait" if video_format == "portrait" else "landscape"

    status_cb("🎙️ Génération de la voix off et des SFX...")
    audio_clips = [process_scene_audio(scene, idx, len(script_scenes), work_dir) for idx, scene in enumerate(script_scenes)]
    
    with open(work_dir / "concat_audio.txt", "w", encoding="utf-8") as f:
        for audio in audio_clips: f.write(f"file '{audio.name}'\n")
    raw_audio = work_dir / "raw_audio.wav"
    run_command([FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0", "-i", "concat_audio.txt", "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(raw_audio)], cwd=work_dir)

    full_audio = add_nasheed_track(raw_audio, work_dir, status_cb)
    voice_duration = get_media_duration(full_audio)
    status_cb(f"⏱️ Durée audio réelle : {voice_duration:.1f} s")

    if video_format == "portrait":
        if voice_duration <= SHORT_MIN_DURATION: raise ShortTooShortError(f"Le script audio fait {voice_duration:.1f}s.")
        if voice_duration > SHORT_MAX_DURATION: raise ShortTooLongError(f"Le script audio fait {voice_duration:.1f}s.")

    status_cb("🎥 Recherche des clips vidéo Pexels...")
    video_clips = []
    mascot_scale = int(width * 0.19) if video_format == "portrait" else int(width * 0.14)
    mascot_positions = [("(W-w)/2", "H-h-470"), ("40", "H-h-470"), ("W-w-40", "H-h-470")] if video_format == "portrait" else [("40", "H-h-40"), ("W-w-40", "H-h-40"), ("40", "H-h-120")]

    for idx, scene in enumerate(script_scenes):
        duration = max(0.5, float(scene.get("duration", 1.0)))
        mascot_img = MASCOT_FILES.get(scene.get("emotion", "default"), MASCOT_FILES["default"])
        if not mascot_img.exists(): mascot_img = MASCOT_FILES["default"]

        url = search_pexels_video(scene.get("visual_query", "funny thinking"), orientation)
        visual_file = work_dir / f"src_vis_{idx:03d}.mp4"
        output_clip = work_dir / f"clip_{idx:03d}.mp4"
        pos_x, pos_y = mascot_positions[idx % len(mascot_positions)]
        enable_expr = f"between(t,0,{min(2.5, duration)})"

        if url and download_file(url, visual_file):
            create_video_clip_from_pexels(visual_file, mascot_img, output_clip, duration, width, height, mascot_scale, pos_x, pos_y, enable_expr, work_dir)
        else:
            create_fallback_video_clip(output_clip, mascot_img, duration, width, height, mascot_scale, pos_x, pos_y, enable_expr, work_dir)
        video_clips.append(output_clip)

    status_cb("⚡ Fusion des scènes vidéo...")
    raw_video = work_dir / "raw_video.mp4"
    if len(video_clips) == 1:
        shutil.copy(video_clips[0], raw_video)
    else:
        with open(work_dir / "concat_video.txt", "w", encoding="utf-8") as f:
            for video in video_clips: f.write(f"file '{video.name}'\n")
        run_command([FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0", "-i", "concat_video.txt", "-c", "copy", "raw_video.mp4"], cwd=work_dir)

    status_cb("💬 Création des sous-titres karaoké...")
    create_ass_subtitles(script_scenes, work_dir / "subtitles.ass", width, height)

    status_cb("🎬 Rendu final...")
    final_output = OUTPUT_DIR / f"export_{int(time.time())}_{video_format}.mp4"
    watermark_y = 55 if video_format == "portrait" else 35
    vf_filter = f"subtitles=subtitles.ass,drawtext=text='CERVEAU CURIEUX':x=35:y={watermark_y}:fontsize=25:fontcolor=white:box=1:boxcolor=black@0.45:boxborderw=7"
    
    cmd_final = [FFMPEG_BIN, "-y", "-i", "raw_video.mp4", "-i", "full_audio.m4a", "-vf", vf_filter, "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", "-movflags", "+faststart", str(final_output)]
    run_command(cmd_final, cwd=work_dir)

    status_cb(f"✅ Vidéo validée : {get_media_duration(final_output):.1f} s")
    return final_output

def split_video_in_two(input_video: Path, out_dir: Path) -> Tuple[Path, Path]:
    mid_point = get_media_duration(input_video) / 2.0
    part1, part2 = out_dir / f"{input_video.stem}_Part1.mp4", out_dir / f"{input_video.stem}_Part2.mp4"
    base = [FFMPEG_BIN, "-y", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]
    run_command(base[:2] + ["-i", str(input_video), "-t", str(mid_point)] + base[2:] + [str(part1)])
    run_command(base[:2] + ["-ss", str(mid_point), "-i", str(input_video)] + base[2:] + [str(part2)])
    return part1, part2

# ============================================================
# 🌐 STREAMLIT - SESSION & UI
# ============================================================

def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="🧠", layout="centered", initial_sidebar_state="expanded")
    
    for key in ["generation_done", "ai_data", "format_choisi", "title", "video_path"]:
        if key not in st.session_state: st.session_state[key] = None if key != "generation_done" else False

    st.markdown("""
        <style>
        .stApp { background-color: #0E1117; }
        div.stButton > button:first-child {
            background: linear-gradient(90deg, #FF4B4B 0%, #FF8F8F 100%);
            color: white; border: none; border-radius: 12px; padding: 0.6rem 1rem;
            font-size: 1.2rem; font-weight: 700; width: 100%; transition: all 0.3s ease; box-shadow: 0 4px 6px rgba(255, 75, 75, 0.2);
        }
        div.stButton > button:first-child:hover { transform: translateY(-2px); box-shadow: 0 6px 15px rgba(255, 75, 75, 0.4); color: white; }
        .main-title { text-align: center; font-size: 3rem; font-weight: 800; color: #FFFFFF; }
        .sub-title { text-align: center; font-size: 1.2rem; color: #A0AEC0; margin-bottom: 30px; }
        .stTextArea textarea { background-color: #1A1C24; border: 1px solid #2D3748; border-radius: 10px; color: #E2E8F0; font-size: 1.1rem; }
        .stTextArea textarea:focus { border-color: #FF4B4B; box-shadow: 0 0 0 1px #FF4B4B; }
        </style>
    """, unsafe_allow_html=True)

    with st.sidebar:
        st.markdown("<h3 style='text-align:center;'>Tableau de bord</h3>", unsafe_allow_html=True)
        if MASCOT_FILES["default"].exists(): st.image(str(MASCOT_FILES["default"]), use_container_width=True)
        st.markdown("---")
        st.markdown("🎯 **Mode Autonome Actif**")
        st.write("Pipeline google-genai + Edge-TTS + Pexels + FFmpeg.")
        st.markdown("---")
        st.markdown("### 🎵 Audio")
        if NASHEED_FILE.exists(): st.success("Nasheed actif")
        else: st.info("Nasheed désactivé")
        sfx_count = sum([WHOOSH_SFX_FILE.exists(), POP_SFX_FILE.exists(), DING_SFX_FILE.exists()])
        st.caption(f"🔊 {sfx_count}/3 bruitages disponibles")

    st.markdown('<div class="main-title">🧠 Cerveau Curieux</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-title">Studio IA Autonome 🎬</div>', unsafe_allow_html=True)
    cleanup_old_temp_dirs()

    st.markdown("### 📝 Quel est ton sujet aujourd'hui ?")
    topic = st.text_area("Sujet", placeholder="Ex: Pourquoi le cerveau oublie-t-il ce qu'il est venu chercher en passant une porte ?", label_visibility="collapsed", height=120)

    if st.button("🚀 LANCER LA GÉNÉRATION"):
        if not topic.strip():
            st.warning("⚠️ Oups ! Tu as oublié d'écrire un sujet.")
            return

        st.session_state.generation_done = False
        with st.status("🎬 Allumage des caméras virtuelles...", expanded=True) as status_box:
            try:
                def update_status(msg): st.write(msg)
                
                ai_data, client = generate_script_gemini(topic, update_status)
                format_choisi = ai_data.get("format_choisi", "short_single")
                st.write(f"✅ Format défini : **{format_choisi.replace('_', ' ').title()}**")

                if format_choisi in ["short_single", "short_twoparts"]:
                    max_repair = 2
                    for attempt in range(max_repair + 1):
                        try:
                            video_path = generate_video_pipeline(ai_data.get("script_principal", []), "portrait", update_status)
                            if format_choisi == "short_twoparts":
                                update_status("✂️ Découpage de la vidéo en 2 parties...")
                                video_path = split_video_in_two(video_path, OUTPUT_DIR)
                            break
                        except (ShortTooShortError, ShortTooLongError) as e:
                            if attempt >= max_repair: raise RuntimeError(str(e) + " Impossible de stabiliser la durée.")
                            m = re.search(r"([0-9]+(?:\.[0-9]+)?)", str(e))
                            measured = float(m.group(1)) if m else (44.0 if isinstance(e, ShortTooShortError) else 91.0)
                            ai_data = repair_script_by_real_duration(client, topic, ai_data, measured, update_status)

                elif format_choisi == "long_plus_teaser":
                    long_path = generate_video_pipeline(ai_data.get("script_principal", []), "landscape", update_status)
                    short_path = generate_video_pipeline(ai_data.get("script_teaser", []), "portrait", update_status)
                    video_path = [long_path, short_path]

                st.session_state.update({"generation_done": True, "ai_data": ai_data, "format_choisi": format_choisi, "title": ai_data.get("title", "Titre généré"), "video_path": video_path})
                status_box.update(label="🎉 Production terminée avec succès !", state="complete", expanded=False)

            except Exception as e:
                status_box.update(label="❌ Oups, une erreur s'est produite.", state="error", expanded=True)
                st.error(str(e))
                return

    # AFFICHAGE
    if st.session_state.generation_done:
        ai_data, format_choisi, video_path = st.session_state.ai_data, st.session_state.format_choisi, st.session_state.video_path
        st.markdown("---")
        st.markdown("## 🍿 Ton contenu est prêt !")
        info_tab, video_tab = st.tabs(["📄 Informations", "🎥 Vidéo(s)"])

        with info_tab:
            st.info(f"**Titre suggéré :** {st.session_state.title}")
            st.write(f"📝 **Narration : {count_words_in_scenes(ai_data.get('script_principal', []))} mots**")
            with st.expander("📜 Voir le script complet"):
                st.code("".join([f"Scène {idx + 1} : {s.get('text', '')}\n\n" for idx, s in enumerate(ai_data.get("script_principal", []))]), language="text")

        with video_tab:
            paths = video_path if isinstance(video_path, list) else [video_path]
            for i, p in enumerate(paths):
                if Path(p).exists():
                    st.video(str(p))
                    with open(p, "rb") as f:
                        st.download_button(f"⬇️ Télécharger {Path(p).name}", data=f.read(), file_name=Path(p).name, mime="video/mp4", key=f"dl_{i}", use_container_width=True)

if __name__ == "__main__":
    main()
