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
from PIL import Image
import streamlit as st
from pydantic import BaseModel, Field

# SDK Google GenAI unifié
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


# ============================================================
# CLÉS API
# ============================================================

def get_secret(name: str) -> str:
    value = os.environ.get(name, "")
    if value: return value
    try: value = st.secrets.get(name, "")
    except Exception: value = ""
    return value or ""

PEXELS_API_KEY = get_secret("PEXELS_API_KEY")
GEMINI_API_KEY = get_secret("GEMINI_API_KEY")

FFMPEG_BIN = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE_BIN = shutil.which("ffprobe") or "ffprobe"


# ============================================================
# TTS & AUDIO
# ============================================================

TTS_VOICE = "fr-FR-HenriNeural"
TTS_RATE = "+5%"

NASHEED_FILE = BASE_DIR / "nasheed.mp3"
NASHEED_VOLUME = 0.055


# ============================================================
# DURÉE DES SHORTS
# ============================================================

SHORT_MIN_DURATION = 35.0
SHORT_TARGET_MIN_DURATION = 40.0
SHORT_TARGET_MAX_DURATION = 65.0
SHORT_MAX_DURATION = 90.0

SHORT_MIN_WORDS = 100
SHORT_TARGET_MIN_WORDS = 120
SHORT_TARGET_MAX_WORDS = 170
SHORT_MAX_WORDS = 200


# ============================================================
# FICHIERS VISUELS & SONORES
# ============================================================

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

# NOUVEAU : Emojis d'effets sonores (Stickers)
CUSTOM_EMOJIS = {
    "sfx_boom": BASE_DIR / "emoji_boom.png",
    "sfx_glitch": BASE_DIR / "emoji_glitch.png",
    "sfx_siren": BASE_DIR / "emoji_siren.png",
    "sfx_punch": BASE_DIR / "emoji_punch.png",
    "sfx_cricket": BASE_DIR / "emoji_cricket.png",
    "sfx_laugh": BASE_DIR / "emoji_laugh.png",
    "sfx_ding": BASE_DIR / "emoji_ding.png",
    "sfx_pop": BASE_DIR / "emoji_pop.png",
}


# ============================================================
# EXCEPTIONS SPÉCIALES
# ============================================================

class ShortTooShortError(RuntimeError): pass
class ShortTooLongError(RuntimeError): pass


# ============================================================
# SCHÉMA JSON GEMINI
# ============================================================

class Scene(BaseModel):
    text: str = Field(description="Une seule phrase courte de narration. Ton moderne, jeune, urbain et naturel.")
    emotion: str = Field(description="Émotion de la mascotte parmi: default, thinking, confused, laughing, explaining, surprised, angry, happy, shocked, sad")
    visual_query: str = Field(description="Mots-clés visuels en anglais, 2 à 4 mots, décrivant une action physique concrète facile à trouver sur Pexels.")
    sfx: str = Field(default="", description="Nom exact du bruitage. Options: sfx_boom, sfx_glitch, sfx_siren, sfx_punch, sfx_cricket, sfx_laugh, sfx_whoosh, sfx_pop, sfx_ding. Laisse vide si aucun bruitage.")

class ScriptOutput(BaseModel):
    format_choisi: str = Field(description="Choix parmi: short_single, short_twoparts, long_plus_teaser")
    title: str = Field(description="Titre YouTube/TikTok très accrocheur, basé sur la curiosité. Max 65 car.")
    hashtags: List[str] = Field(description="4 à 6 hashtags pertinents directement liés au sujet.")
    script_principal: List[Scene] = Field(description="Scènes principales. Pour un Short, viser 120 à 170 mots.")
    script_teaser: List[Scene] = Field(default_factory=list, description="Scènes du teaser si besoin.")


# ============================================================
# PROMPT GEMINI (AMÉLIORÉ)
# ============================================================

SYSTEM_PROMPT = """
Tu es le réalisateur et scénariste de la chaîne YouTube/TikTok "Cerveau Curieux".
OBJECTIF : Créer des vidéos virales, humoristiques, dynamiques et documentées sur le cerveau, la psychologie et les comportements humains.

ACCROCHE (HOOK) IMMÉDIATE :
- Ne fais AUCUNE salutation (INTERDIT : "Wesh l'équipe", "Bonjour", etc.).
- Attaque DIRECTEMENT à la première seconde avec une question choc, un constat décalé ou une situation vécue hyper identifiable. Le spectateur doit se dire "Mais grave, ça m'arrive tout le temps !".

NARRATION ET STORYTELLING (Le secret de la rétention) :
- Le Cerveau comme personnage : Traite le cerveau du spectateur comme un colocataire un peu parano, maladroit ou dramatique (ex: "Ton cerveau panique", "Il croit que tu vas mourir", "C'est son mode économie d'énergie").
- Analogies modernes : Vulgarise la science en utilisant des références actuelles (un bug de mise à jour, un lag de jeu vidéo, une alarme de voiture).
- Micro-hooks de relance : Insère des phrases au milieu de la vidéo pour relancer l'attention (ex: "Mais le plus fou, c'est que...", "Et c'est là que ça devient une dinguerie...").
- Style parlé et percutant : Phrases très courtes. Vocabulaire jeune, urbain et piquant (buguer, dinguerie, chelou, frérot).

RÈGLE DE L'ANTI-CLIMAX COMIQUE (Créer de la fausse attente) :
- Quand tu prépares une explication ou un tournant dans la vidéo ("Et c'est là que ça devient absurde..."), monte la tension comme pour un film d'action ou un truc grandiose.
- Puis casse immédiatement l'ambiance avec une réalité ridicule ou décevante, idéalement accompagnée d'un bruitage marquant.

DURÉE DES SHORTS :
- Le Short doit durer au minimum 35 secondes. Zone idéale : environ 45 à 65 secondes (soit 120 à 170 mots). NE REMPLIS PAS AVEC DU VIDE.

PEXELS, MASCOTTES ET BRUITAGES (SFX) :
- Chaque scène est accompagnée d'une vidéo Pexels, d'une mascotte et d'un bruitage optionnel.
- Laisse le champ 'sfx' vide ("") si la phrase n'a pas besoin d'accentuation. Utilise les sons comme sfx_boom, sfx_glitch, sfx_siren, sfx_punch, sfx_pop.

CTA DYNAMIQUE (Dernière scène) :
- La dernière scène DOIT être une Call To Action originale, qui lie naturellement l'explication qu'on vient d'entendre avec l'incitation à s'abonner.
- Exemple : "Alors pour éviter de te faire arnaquer par tes propres neurones, abonne-toi au Cerveau Curieux !"
"""


# ============================================================
# OUTILS GÉNÉRAUX
# ============================================================

def cleanup_old_temp_dirs(max_age_hours=2):
    now = time.time()
    try: items = list(TEMP_DIR.iterdir())
    except Exception: return
    for item in items:
        if not item.is_dir(): continue
        try:
            if now - item.stat().st_mtime > max_age_hours * 3600:
                shutil.rmtree(item, ignore_errors=True)
        except Exception: pass

def run_command(command: List[str], cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    cmd_str = [str(arg) for arg in command]
    try:
        return subprocess.run(cmd_str, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True, cwd=cwd)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Erreur Shell:\nCommande: {' '.join(cmd_str)}\nErreur: {e.stderr[-3000:]}")

def get_media_duration(file_path: Path) -> float:
    if not file_path.exists() or file_path.stat().st_size == 0: return 0.0
    cmd = [FFPROBE_BIN, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(file_path)]
    try: return float(run_command(cmd).stdout.strip())
    except ValueError: return 0.0

def count_words_in_scenes(scenes: List[Dict]) -> int:
    return sum(len(str(scene.get("text", "")).split()) for scene in scenes or [])


# ============================================================
# QC VIDÉO & NORMALISATION
# ============================================================

def qc_validate_video(video_path: Path, expected_format: Optional[str] = None):
    if not video_path.exists(): raise RuntimeError("QC Échec : le fichier final n'a pas été généré.")
    if video_path.stat().st_size < 10000: raise RuntimeError("QC Échec : la vidéo semble vide ou corrompue.")
    duration = get_media_duration(video_path)
    if duration <= 0: raise RuntimeError("QC Échec : impossible de lire la durée de la vidéo.")
    return duration

def fix_phonetics_for_tts(text: str) -> str:
    return text.replace("buguer", "beuguer").replace("Buguer", "Beuguer")

def generate_tts(text: str, output_path: Path):
    spoken_text = fix_phonetics_for_tts(text)
    run_command(["edge-tts", "--voice", TTS_VOICE, "--rate", TTS_RATE, "--text", spoken_text, "--write-media", str(output_path)])

def normalize_hashtags(hashtags: List[str]) -> List[str]:
    clean = []
    for tag in hashtags or []:
        if not isinstance(tag, str): continue
        tag = tag.strip()
        if not tag: continue
        if not tag.startswith("#"): tag = "#" + tag
        tag = re.sub(r"[^\w#]", "", tag)
        if len(tag) < 2: continue
        if tag.lower() not in [x.lower() for x in clean]: clean.append(tag)
    return clean[:6]

def clean_pexels_query(query: str) -> str:
    query = re.sub(r"[^a-zA-Z\s]", "", query or "")
    words = [w for w in query.split() if len(w) > 2]
    return " ".join(words[:4])

def normalize_scene(scene) -> Optional[Dict]:
    if hasattr(scene, "model_dump"): scene = scene.model_dump()
    if not isinstance(scene, dict): return None

    text = str(scene.get("text", "")).strip()
    emotion = str(scene.get("emotion", "default")).strip().lower()
    visual_query = str(scene.get("visual_query", "person thinking")).strip()
    sfx = str(scene.get("sfx", "")).strip().lower().replace(".mp3", "")

    if not text: return None
    if emotion not in set(MASCOT_FILES.keys()): emotion = "default"
    visual_query = clean_pexels_query(visual_query) or "person thinking"

    return {
        "text": text,
        "emotion": emotion,
        "visual_query": visual_query[:80],
        "sfx": sfx
    }

def validate_and_repair_script(data: Dict) -> Dict:
    if not isinstance(data, dict): raise RuntimeError("Réponse Gemini invalide.")
    
    scenes = data.get("script_principal") or []
    if not scenes: raise RuntimeError("Gemini n'a généré aucune scène.")

    normalized = [normalize_scene(s) for s in scenes if normalize_scene(s)]
    if not normalized: raise RuntimeError("Le script Gemini est vide.")

    # La CTA dynamique demande de la joie et un ding à la toute fin
    normalized[-1]["emotion"] = "happy"
    normalized[-1]["sfx"] = "sfx_ding"
    data["script_principal"] = normalized

    teaser = data.get("script_teaser") or []
    data["script_teaser"] = [normalize_scene(s) for s in teaser if normalize_scene(s)]

    allowed_formats = {"short_single", "short_twoparts", "long_plus_teaser"}
    if data.get("format_choisi") not in allowed_formats: data["format_choisi"] = "short_single"

    title = str(data.get("title", "Pourquoi ton cerveau fait ça")).strip()
    title = re.sub(r"\s+", " ", title).strip("\"'")
    if len(title) > 65: title = title[:65].rstrip()
    data["title"] = title or "Pourquoi ton cerveau fait ça"

    data["hashtags"] = normalize_hashtags(data.get("hashtags", []))
    if not data["hashtags"]: data["hashtags"] = ["#Cerveau", "#Psychologie", "#Science"]

    return data


# ============================================================
# APPEL GEMINI (NOUVEAU SDK)
# ============================================================

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
    parsed = response.parsed.model_dump() if (hasattr(response, "parsed") and response.parsed) else json.loads(response.text)
    return validate_and_repair_script(parsed)

def repair_script_by_words(client, topic: str, data: Dict, status_cb, too_short: bool) -> Dict:
    scenes = data.get("script_principal", [])
    word_count = count_words_in_scenes(scenes)
    current_script = "\n".join(scene.get("text", "") for scene in scenes)

    instruction = f"Le script fait {word_count} mots. Réécris-le pour viser {SHORT_TARGET_MIN_WORDS} à {SHORT_TARGET_MAX_WORDS} mots. N'ajoute pas de blabla, juste des infos et de l'humour." if too_short else f"Le script fait {word_count} mots. Réduis-le vers {SHORT_TARGET_MIN_WORDS} à {SHORT_TARGET_MAX_WORDS} mots. Supprime les longueurs."
    prompt = f"Sujet: {topic}\n\n{instruction}\n\nScript actuel :\n{current_script}\n\nConserve le format humoristique et la CTA dynamique à la fin."
    
    status_cb("🧠 Ajustement du contenu avec Gemini...")
    repaired = call_gemini_script(client, prompt)
    repaired["format_choisi"] = data.get("format_choisi", repaired.get("format_choisi", "short_single"))
    return repaired

def generate_script_gemini(topic: str, status_cb) -> Tuple[Dict, object]:
    if not GEMINI_API_KEY: raise RuntimeError("Clé API GEMINI manquante.")
    client = genai.Client(api_key=GEMINI_API_KEY)
    status_cb("🧠 Analyse du sujet et rédaction du script...")

    prompt = f"""Sujet à traiter : {topic.strip()}
    Crée le contenu complet de la vidéo avec une accroche choc immédiate et une CTA dynamique sur-mesure à la fin.
    Vise {SHORT_TARGET_MIN_WORDS} à {SHORT_TARGET_MAX_WORDS} mots."""
    
    try:
        data = call_gemini_script(client, prompt)
        format_choisi = data.get("format_choisi", "short_single")
        if format_choisi in ("short_single", "short_twoparts"):
            word_count = count_words_in_scenes(data.get("script_principal", []))
            if word_count < SHORT_MIN_WORDS: data = repair_script_by_words(client, topic, data, status_cb, True)
            elif word_count > SHORT_MAX_WORDS: data = repair_script_by_words(client, topic, data, status_cb, False)
        return (data, client)
    except Exception as e:
        raise RuntimeError(f"Erreur Gemini : {e}")

def repair_script_by_real_duration(client, topic: str, data: Dict, measured_duration: float, status_cb) -> Dict:
    scenes = data.get("script_principal", [])
    current_script = "\n".join(scene.get("text", "") for scene in scenes)

    if measured_duration < SHORT_MIN_DURATION:
        status_cb(f"⏱️ Durée réelle trop courte ({measured_duration:.1f} s). Ajout d'infos...")
        instruction = "Il faut dépasser 35 secondes. Ajoute de l'humour, de l'anti-climax et des faits."
    else:
        status_cb(f"⏱️ Durée réelle trop longue ({measured_duration:.1f} s). Resserrement...")
        instruction = "Resserre le script pour viser environ 45-65 secondes. Garde le rythme nerveux."

    prompt = f"Sujet : {topic}\n{instruction}\n\nSCRIPT ACTUEL :\n{current_script}"
    repaired = call_gemini_script(client, prompt)
    repaired["format_choisi"] = data.get("format_choisi", repaired.get("format_choisi", "short_single"))
    return repaired


# ============================================================
# CHOIX INTELLIGENT DU SFX
# ============================================================

def choose_sfx_for_scene(scene: Dict, idx: int, total_scenes: int) -> Optional[Dict]:
    sfx_name = scene.get("sfx", "")
    
    # CTA = Ding
    if idx == total_scenes - 1: sfx_name = "sfx_ding"
    if not sfx_name: return None
    
    sfx_file = BASE_DIR / f"{sfx_name}.mp3"
    
    # Fallback si le fichier son exact n'existe pas physiquement
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


# ============================================================
# AUDIO PAR SCÈNE & MIXAGE
# ============================================================

def process_scene_audio(scene: Dict, idx: int, total_scenes: int, work_dir: Path) -> Path:
    temp_audio = work_dir / f"temp_audio_{idx:03d}.mp3"
    processed_audio = work_dir / f"audio_{idx:03d}.wav"
    generate_tts(scene["text"], temp_audio)
    sfx_info = choose_sfx_for_scene(scene, idx, total_scenes)

    if not sfx_info:
        run_command([FFMPEG_BIN, "-y", "-i", str(temp_audio), "-af", "aresample=48000,aformat=channel_layouts=stereo,loudnorm=I=-16:LRA=11:TP=-1.5", "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(processed_audio)], cwd=work_dir)
    else:
        cmd_mix = [
            FFMPEG_BIN, "-y", "-i", str(temp_audio), "-i", str(sfx_info["file"]), "-filter_complex",
            (f"[0:a]aresample=48000,aformat=channel_layouts=stereo[voice];"
             f"[1:a]atrim=0:{sfx_info['max_duration']},asetpts=N/SR/TB,volume={sfx_info['volume']},adelay={sfx_info['delay']}|{sfx_info['delay']},aresample=48000,aformat=channel_layouts=stereo[sfx];"
             "[voice][sfx]amix=inputs=2:duration=first:dropout_transition=0,loudnorm=I=-16:LRA=11:TP=-1.5[a]"),
            "-map", "[a]", "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(processed_audio)
        ]
        run_command(cmd_mix, cwd=work_dir)

    scene["duration"] = get_media_duration(processed_audio)
    return processed_audio

def concatenate_audio(audio_clips: List[Path], work_dir: Path) -> Path:
    with open(work_dir / "concat_audio.txt", "w", encoding="utf-8") as f:
        for audio in audio_clips: f.write(f"file '{audio.name}'\n")
    raw_audio = work_dir / "raw_audio.wav"
    run_command([FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0", "-i", "concat_audio.txt", "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(raw_audio)], cwd=work_dir)
    return raw_audio

def add_nasheed_track(voice_audio: Path, work_dir: Path, status_cb=None) -> Path:
    output = work_dir / "full_audio.m4a"
    if not NASHEED_FILE.exists():
        if status_cb: status_cb("🎙️ Aucun nasheed détecté : voix seule.")
        run_command([FFMPEG_BIN, "-y", "-i", str(voice_audio), "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", str(output)], cwd=work_dir)
        return output
    
    if status_cb: status_cb("🎵 Nasheed détecté : mixage vocal intelligent...")
    cmd = [
        FFMPEG_BIN, "-y", "-i", str(voice_audio), "-stream_loop", "-1", "-i", str(NASHEED_FILE), "-filter_complex",
        (f"[0:a]aresample=48000,aformat=channel_layouts=stereo,volume=1.0[voice];"
         f"[1:a]aresample=48000,aformat=channel_layouts=stereo,volume={NASHEED_VOLUME},highpass=f=100,lowpass=f=9000,afade=t=in:st=0:d=1.5[nasheed_raw];"
         "[nasheed_raw][voice]sidechaincompress=threshold=0.045:ratio=7:attack=20:release=300:makeup=1:knee=3[nasheed_ducked];"
         "[voice][nasheed_ducked]amix=inputs=2:duration=first:dropout_transition=2,loudnorm=I=-16:LRA=11:TP=-1.5[mixed]"),
        "-map", "[mixed]", "-ar", "48000", "-ac", "2", "-c:a", "aac", "-b:a", "192k", str(output)
    ]
    run_command(cmd, cwd=work_dir)
    return output


# ============================================================
# VIDÉO PEXELS & EMOJIS INCORPORÉS
# ============================================================

def search_pexels_video(query: str, orientation: str) -> Optional[str]:
    if not PEXELS_API_KEY: return None
    clean_query = clean_pexels_query(query) or "human thinking"
    try:
        r = requests.get("https://api.pexels.com/videos/search", headers={"Authorization": PEXELS_API_KEY}, params={"query": clean_query, "orientation": orientation, "per_page": 12}, timeout=10)
        if r.status_code != 200: return None
        candidates = []
        for video in r.json().get("videos", []):
            files = [f for f in video.get("video_files", []) if ".mp4" in str(f.get("link", "")).lower()]
            for file_info in files:
                w, h, link = int(file_info.get("width", 0) or 0), int(file_info.get("height", 0) or 0), file_info.get("link")
                if not link: continue
                if orientation == "portrait" and h < 720: continue
                if orientation == "landscape" and w < 1280: continue
                candidates.append((w * h, link))
        if not candidates: return None
        candidates.sort(key=lambda x: x[0], reverse=True)
        return random.choice(candidates[:min(5, len(candidates))])[1]
    except Exception: return None

def download_file(url: str, dest: Path) -> bool:
    try:
        with requests.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=64 * 1024):
                    if chunk: f.write(chunk)
        return dest.exists() and dest.stat().st_size > 10000
    except Exception: return False

def create_video_clip_from_pexels(visual_file: Path, mascot_img: Path, sfx_icon_img: Optional[Path], output_clip: Path, duration: float, width: int, height: int, mascot_scale: int, pos_x: str, pos_y: str, enable_expr: str, work_dir: Path):
    fps = 30
    filter_complex = f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps={fps},setsar=1[bg];"
    filter_complex += f"[1:v]scale={mascot_scale}:-1,format=rgba[mascot];"
    
    if sfx_icon_img and sfx_icon_img.exists():
        icon_scale = int(width * 0.35)
        filter_complex += f"[2:v]scale={icon_scale}:-1,format=rgba[icon];"
        filter_complex += f"[bg][mascot]overlay=x={pos_x}:y={pos_y}:enable='{enable_expr}'[v_tmp];"
        filter_complex += f"[v_tmp][icon]overlay=x=(W-w)/2:y=(H-h)/2:enable='between(t,0.05,0.85)'[v_out]"
        cmd = [FFMPEG_BIN, "-y", "-stream_loop", "-1", "-i", str(visual_file), "-loop", "1", "-i", str(mascot_img.resolve()), "-loop", "1", "-i", str(sfx_icon_img.resolve()), "-t", str(duration), "-filter_complex", filter_complex, "-map", "[v_out]", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(fps), "-movflags", "+faststart", str(output_clip)]
    else:
        filter_complex += f"[bg][mascot]overlay=x={pos_x}:y={pos_y}:enable='{enable_expr}'[v_out]"
        cmd = [FFMPEG_BIN, "-y", "-stream_loop", "-1", "-i", str(visual_file), "-loop", "1", "-i", str(mascot_img.resolve()), "-t", str(duration), "-filter_complex", filter_complex, "-map", "[v_out]", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(fps), "-movflags", "+faststart", str(output_clip)]
    run_command(cmd, cwd=work_dir)

def create_fallback_video_clip(output_clip: Path, mascot_img: Path, sfx_icon_img: Optional[Path], duration: float, width: int, height: int, mascot_scale: int, pos_x: str, pos_y: str, enable_expr: str, work_dir: Path):
    fallback = work_dir / f"fallback_{output_clip.stem}.png"
    Image.new("RGB", (width, height), color=(20, 20, 35)).save(fallback)
    fps = 30
    filter_complex = f"[0:v]scale={width}:{height},fps={fps},setsar=1[bg];[1:v]scale={mascot_scale}:-1,format=rgba[mascot];"
    
    if sfx_icon_img and sfx_icon_img.exists():
        icon_scale = int(width * 0.35)
        filter_complex += f"[2:v]scale={icon_scale}:-1,format=rgba[icon];"
        filter_complex += f"[bg][mascot]overlay=x={pos_x}:y={pos_y}:enable='{enable_expr}'[v_tmp];"
        filter_complex += f"[v_tmp][icon]overlay=x=(W-w)/2:y=(H-h)/2:enable='between(t,0.05,0.85)'[v_out]"
        cmd = [FFMPEG_BIN, "-y", "-loop", "1", "-i", str(fallback), "-loop", "1", "-i", str(mascot_img.resolve()), "-loop", "1", "-i", str(sfx_icon_img.resolve()), "-t", str(duration), "-filter_complex", filter_complex, "-map", "[v_out]", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(fps), "-movflags", "+faststart", str(output_clip)]
    else:
        filter_complex += f"[bg][mascot]overlay=x={pos_x}:y={pos_y}:enable='{enable_expr}'[v_out]"
        cmd = [FFMPEG_BIN, "-y", "-loop", "1", "-i", str(fallback), "-loop", "1", "-i", str(mascot_img.resolve()), "-t", str(duration), "-filter_complex", filter_complex, "-map", "[v_out]", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(fps), "-movflags", "+faststart", str(output_clip)]
    run_command(cmd, cwd=work_dir)


def create_ass_subtitles(scenes: List[Dict], output_ass: Path, width: int, height: int):
    font_size, margin_v = (58, 300) if width == 1080 else (40, 75)
    header = f"[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nScaledBorderAndShadow: yes\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Arial,{font_size},&H00FFFFFF,&H00000000,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,2,30,30,{margin_v},1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    
    def ass_time(seconds: float) -> str:
        s = max(0.0, seconds)
        return f"{int(s//3600)}:{int((s%3600)//60):02d}:{int(s%60):02d}.{int((s-int(s))*100):02d}"

    lines, current_time = [], 0.0
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
# PIPELINE VIDÉO MAITRE
# ============================================================

def generate_video_pipeline(script_scenes: List[Dict], video_format: str, status_cb) -> Path:
    if not script_scenes: raise ValueError("Le script est vide.")
    work_dir = TEMP_DIR / f"run_{int(time.time())}_{video_format}_{random.randint(1000, 9999)}"
    work_dir.mkdir(parents=True, exist_ok=True)
    
    width, height = (1080, 1920) if video_format == "portrait" else (1920, 1080)
    orientation = "portrait" if video_format == "portrait" else "landscape"

    status_cb("🎙️ Génération de la voix off...")
    audio_clips = [process_scene_audio(scene, idx, len(script_scenes), work_dir) for idx, scene in enumerate(script_scenes)]
    raw_audio = concatenate_audio(audio_clips, work_dir)
    full_audio = add_nasheed_track(raw_audio, work_dir, status_cb)
    
    voice_duration = get_media_duration(full_audio)
    status_cb(f"⏱️ Durée audio réelle : {voice_duration:.1f} secondes")
    
    if video_format == "portrait":
        if voice_duration <= SHORT_MIN_DURATION: raise ShortTooShortError(f"Le script audio fait {voice_duration:.1f}s.")
        if voice_duration > SHORT_MAX_DURATION: raise ShortTooLongError(f"Le script audio fait {voice_duration:.1f}s.")
        status_cb(f"✅ Durée validée : {voice_duration:.1f} secondes")

    status_cb("🎥 Recherche Pexels et Montage des scènes...")
    video_clips = []
    mascot_scale = int(width * 0.19) if video_format == "portrait" else int(width * 0.14)
    mascot_positions = [("(W-w)/2", "H-h-470"), ("40", "H-h-470"), ("W-w-40", "H-h-470")] if video_format == "portrait" else [("40", "H-h-40"), ("W-w-40", "H-h-40"), ("40", "H-h-120")]

    for idx, scene in enumerate(script_scenes):
        duration = max(0.5, float(scene.get("duration", 1.0)))
        mascot_img = MASCOT_FILES.get(scene.get("emotion", "default"), MASCOT_FILES["default"])
        if not mascot_img.exists(): mascot_img = MASCOT_FILES["default"]

        # Récupération de l'emoji si le son est présent
        sfx_name = scene.get("sfx", "")
        if idx == len(script_scenes) - 1: sfx_name = "sfx_ding" # Force le ding à la fin
        sfx_icon_img = CUSTOM_EMOJIS.get(sfx_name)

        status_cb(f"🎬 Clip {idx + 1}/{len(script_scenes)} : {scene.get('visual_query', '')}")
        url = search_pexels_video(scene.get("visual_query", "person thinking"), orientation)
        visual_file = work_dir / f"src_vis_{idx:03d}.mp4"
        output_clip = work_dir / f"clip_{idx:03d}.mp4"
        pos_x, pos_y = mascot_positions[idx % len(mascot_positions)]
        enable_expr = f"between(t,0,{min(2.5, duration)})"

        if url and download_file(url, visual_file):
            create_video_clip_from_pexels(visual_file, mascot_img, sfx_icon_img, output_clip, duration, width, height, mascot_scale, pos_x, pos_y, enable_expr, work_dir)
        else:
            create_fallback_video_clip(output_clip, mascot_img, sfx_icon_img, duration, width, height, mascot_scale, pos_x, pos_y, enable_expr, work_dir)
        video_clips.append(output_clip)

    status_cb("⚡ Fusion finale et sous-titres...")
    raw_video = work_dir / "raw_video.mp4"
    if len(video_clips) == 1: shutil.copy(video_clips[0], raw_video)
    else:
        with open(work_dir / "concat_video.txt", "w", encoding="utf-8") as f:
            for video in video_clips: f.write(f"file '{video.name}'\n")
        run_command([FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0", "-i", "concat_video.txt", "-c", "copy", "raw_video.mp4"], cwd=work_dir)

    create_ass_subtitles(script_scenes, work_dir / "subtitles.ass", width, height)
    
    final_output = OUTPUT_DIR / f"export_{int(time.time())}_{video_format}.mp4"
    watermark_y = 55 if video_format == "portrait" else 35
    vf_filter = f"subtitles=subtitles.ass,drawtext=text='CERVEAU CURIEUX':x=35:y={watermark_y}:fontsize=25:fontcolor=white:box=1:boxcolor=black@0.45:boxborderw=7"
    
    run_command([FFMPEG_BIN, "-y", "-i", "raw_video.mp4", "-i", "full_audio.m4a", "-vf", vf_filter, "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", "-movflags", "+faststart", str(final_output.resolve())], cwd=work_dir)

    final_duration = qc_validate_video(final_output, expected_format="portrait" if video_format == "portrait" else "landscape")
    if video_format == "portrait":
        if final_duration <= SHORT_MIN_DURATION: raise ShortTooShortError(f"QC Échec : le Short final fait {final_duration:.1f} s.")
        if final_duration > SHORT_MAX_DURATION: raise ShortTooLongError(f"QC Échec : le Short final fait {final_duration:.1f} s.")

    status_cb(f"✅ Vidéo finale validée : {final_duration:.1f} secondes")
    return final_output


def split_video_in_two(input_video: Path, total_duration: float, out_dir: Path) -> Tuple[Path, Path]:
    mid_point = total_duration / 2.0
    part1 = out_dir / f"{input_video.stem}_Part1.mp4"
    part2 = out_dir / f"{input_video.stem}_Part2.mp4"
    base_cmd = [FFMPEG_BIN, "-y", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]
    run_command(base_cmd[:2] + ["-i", str(input_video), "-t", str(mid_point)] + base_cmd[2:] + [str(part1)])
    run_command(base_cmd[:2] + ["-ss", str(mid_point), "-i", str(input_video)] + base_cmd[2:] + [str(part2)])
    return part1, part2


# ============================================================
# INTERFACE STREAMLIT
# ============================================================

def initialize_session_state():
    for key, value in {"generation_done": False, "ai_data": None, "format_choisi": None, "title": None, "video_path": None, "topic_generated": ""}.items():
        if key not in st.session_state: st.session_state[key] = value

def save_generation_result(ai_data: Dict, format_choisi: str, video_path, topic: str):
    st.session_state.generation_done = True
    st.session_state.ai_data = ai_data
    st.session_state.format_choisi = format_choisi
    st.session_state.title = ai_data.get("title", "Pourquoi ton cerveau fait ça")
    st.session_state.video_path = video_path
    st.session_state.topic_generated = topic

def clear_generation_result():
    for key in ["generation_done", "ai_data", "format_choisi", "title", "video_path", "topic_generated"]:
        st.session_state[key] = False if key == "generation_done" else ("" if key == "topic_generated" else None)

def render_results():
    if not st.session_state.get("generation_done", False): return
    ai_data, format_choisi, video_path, title = st.session_state.ai_data, st.session_state.format_choisi, st.session_state.video_path, st.session_state.title
    if not ai_data or not video_path: return

    st.markdown("---")
    st.markdown("## 🍿 Ton contenu est prêt !")
    info_tab, video_tab = st.tabs(["📄 Informations", "🎥 Vidéo(s)"])

    with info_tab:
        st.info(f"**Titre suggéré :** {title}")
        st.write("**Hashtags :** " + " ".join(ai_data.get("hashtags", [])))
        st.write(f"📝 **Narration : {count_words_in_scenes(ai_data.get('script_principal', []))} mots**")
        st.markdown("---")
        if NASHEED_FILE.exists(): st.success("🎵 Nasheed : actif")
        else: st.info("🎵 Nasheed : désactivé")
        
        active_sfx = [k.replace("sfx_", "") for k, v in CUSTOM_EMOJIS.items() if (BASE_DIR / f"{k}.mp3").exists()]
        if active_sfx: st.caption("🔊 SFX actifs : " + ", ".join(active_sfx))
        
        with st.expander("📜 Voir le script complet"):
            st.code("".join(f"Scène {idx + 1} : {scene.get('text', '')}\n\n" for idx, scene in enumerate(ai_data.get("script_principal", []))), language="text")

    with video_tab:
        paths = [Path(str(x))] if format_choisi == "short_single" else [Path(str(x)) for x in video_path]
        if format_choisi == "short_twoparts":
            col1, col2 = st.columns(2)
            for col, p, name in zip([col1, col2], paths, ["Partie 1", "Partie 2"]):
                with col:
                    st.caption(name)
                    if p.exists():
                        st.video(str(p))
                        with open(p, "rb") as f: st.download_button(f"⬇️ {name}", data=f.read(), file_name=p.name, mime="video/mp4", use_container_width=True)
        else:
            for p, name in zip(paths, ["Vidéo Longue", "Teaser Short"] if format_choisi == "long_plus_teaser" else ["Short"]):
                if p.exists():
                    st.caption(name)
                    st.video(str(p))
                    with open(p, "rb") as f: st.download_button(f"⬇️ Télécharger {name}", data=f.read(), file_name=p.name, mime="video/mp4", type="primary", use_container_width=True)


def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="🧠", layout="centered", initial_sidebar_state="expanded")
    initialize_session_state()

    st.markdown("""
        <style>
        .stApp { background-color: #0E1117; }
        div.stButton > button:first-child { background: linear-gradient(90deg, #FF4B4B 0%, #FF8F8F 100%); color: white; border: none; border-radius: 12px; padding: 0.6rem 1rem; font-size: 1.2rem; font-weight: 700; width: 100%; transition: all 0.3s ease; box-shadow: 0 4px 6px rgba(255, 75, 75, 0.2); }
        div.stButton > button:first-child:hover { transform: translateY(-2px); box-shadow: 0 6px 15px rgba(255, 75, 75, 0.4); color: white; }
        .main-title { text-align: center; font-size: 3rem; font-weight: 800; margin-bottom: 0px; color: #FFFFFF; }
        .sub-title { text-align: center; font-size: 1.2rem; color: #A0AEC0; margin-top: 0px; margin-bottom: 30px; }
        .stTextArea textarea { background-color: #1A1C24; border: 1px solid #2D3748; border-radius: 10px; color: #E2E8F0; font-size: 1.1rem; }
        .stTextArea textarea:focus { border-color: #FF4B4B; box-shadow: 0 0 0 1px #FF4B4B; }
        </style>
    """, unsafe_allow_html=True)

    with st.sidebar:
        st.markdown("<h3 style='text-align:center;'>Tableau de bord</h3>", unsafe_allow_html=True)
        if MASCOT_FILES["default"].exists(): st.image(str(MASCOT_FILES["default"]), use_container_width=True)
        st.markdown("---")
        st.markdown("🎯 **Mode Autonome Actif**")
        st.write("Pipeline Gemini + Edge-TTS + Pexels Video + FFmpeg.")
        st.markdown("---")
        st.markdown("### 🎵 Audio")
        if NASHEED_FILE.exists(): st.success("Nasheed actif")
        else: st.info("Nasheed désactivé")
        sfx_count = sum([1 for k in CUSTOM_EMOJIS if (BASE_DIR / f"{k}.mp3").exists()])
        st.caption(f"🔊 {sfx_count} bruitages disponibles")
        st.caption("Voix prioritaire • SFX synchronisés avec Emojis 3D")
        st.markdown("---")
        st.caption("Accroche directe / CTA sur-mesure")
        st.caption("Short : plus de 35 secondes")

    st.markdown('<div class="main-title">🧠 Cerveau Curieux</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-title">Studio IA Autonome 🎬</div>', unsafe_allow_html=True)
    cleanup_old_temp_dirs()

    st.markdown("### 📝 Quel est ton sujet aujourd'hui ?")
    topic = st.text_area("Sujet", placeholder="Ex: Pourquoi le cerveau oublie-t-il ce qu'il est venu chercher en passant une porte ?", label_visibility="collapsed", height=120, key="topic_input")

    if st.button("🚀 LANCER LA GÉNÉRATION", key="generate_video_button"):
        if not topic.strip():
            st.warning("⚠️ Oups ! Tu as oublié d'écrire un sujet.")
            return

        clear_generation_result()
        with st.status("🎬 Allumage des caméras virtuelles...", expanded=True) as status_box:
            try:
                def update_status(msg): st.write(msg)
                
                ai_data, gemini_client = generate_script_gemini(topic, update_status)
                format_choisi = ai_data.get("format_choisi", "short_single")
                title = ai_data.get("title", "Pourquoi ton cerveau fait ça")
                word_count = count_words_in_scenes(ai_data.get("script_principal", []))
                
                st.write(f"✅ Format défini : **{format_choisi.replace('_', ' ').title()}**")
                st.write(f"📝 Narration initiale : **{word_count} mots**")

                if format_choisi == "short_single":
                    for repair_attempt in range(3):
                        try:
                            video_path = generate_video_pipeline(ai_data.get("script_principal", []), "portrait", update_status)
                            break
                        except (ShortTooShortError, ShortTooLongError) as e:
                            if repair_attempt >= 2: raise RuntimeError(str(e) + " Impossible de stabiliser la durée.")
                            m = re.search(r"([0-9]+(?:\.[0-9]+)?)", str(e))
                            ai_data = repair_script_by_real_duration(gemini_client, topic, ai_data, float(m.group(1)) if m else (44.0 if isinstance(e, ShortTooShortError) else 91.0), update_status)

                elif format_choisi == "short_twoparts":
                    for repair_attempt in range(3):
                        try:
                            full_video_path = generate_video_pipeline(ai_data.get("script_principal", []), "portrait", update_status)
                            break
                        except (ShortTooShortError, ShortTooLongError) as e:
                            if repair_attempt >= 2: raise RuntimeError(str(e) + " Impossible de stabiliser la durée.")
                            m = re.search(r"([0-9]+(?:\.[0-9]+)?)", str(e))
                            ai_data = repair_script_by_real_duration(gemini_client, topic, ai_data, float(m.group(1)) if m else (44.0 if isinstance(e, ShortTooShortError) else 91.0), update_status)
                    
                    update_status("✂️ Découpage de la vidéo en 2 parties...")
                    part1, part2 = split_video_in_two(full_video_path, get_media_duration(full_video_path), OUTPUT_DIR)
                    video_path = [part1, part2]

                elif format_choisi == "long_plus_teaser":
                    long_path = generate_video_pipeline(ai_data.get("script_principal", []), "landscape", update_status)
                    short_path = generate_video_pipeline(ai_data.get("script_teaser", []), "portrait", update_status)
                    video_path = [long_path, short_path]

                save_generation_result(ai_data=ai_data, format_choisi=format_choisi, video_path=video_path, topic=topic)
                status_box.update(label="🎉 Production terminée avec succès !", state="complete", expanded=False)
            except Exception as e:
                status_box.update(label="❌ Oups, une erreur s'est produite.", state="error", expanded=True)
                st.error(str(e))
                return
    render_results()

if __name__ == "__main__":
    main()
