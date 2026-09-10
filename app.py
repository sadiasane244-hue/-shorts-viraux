import os
import time
import json
import shutil
import subprocess
import requests
from pathlib import Path
from typing import List, Dict, Optional
from PIL import Image
import streamlit as st

# ============================================================
# CONFIGURATION ET PATHS DE BASE
# ============================================================

APP_TITLE = "🧠 Cerveau Curieux — Studio IA Ultime"
BASE_DIR = Path(__file__).resolve().parent
TEMP_DIR = BASE_DIR / "temp"
OUTPUT_DIR = BASE_DIR / "output"

TEMP_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# API Keys (depuis st.secrets ou variables d'environnement)
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

FFMPEG_BIN = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE_BIN = shutil.which("ffprobe") or "ffprobe"
AUDIO_BITRATE = "192k"

# Cartographie des mascottes (à placer à la racine avec app.py)
MASCOT_FILES = {
    "default": BASE_DIR / "mascot_default.png",
    "thinking": BASE_DIR / "mascot_thinking.png",
    "confused": BASE_DIR / "mascot_confused.png",
    "laughing": BASE_DIR / "mascot_laughing.png",
    "explaining": BASE_DIR / "mascot_explaining.png",
    "surprised": BASE_DIR / "mascot_surprised.png",
}

# Cartographie des effets sonores (Bruitages uniquement, ZÉRO musique)
SFX_FILES = {
    "pop": BASE_DIR / "sfx_pop.mp3",
    "whoosh": BASE_DIR / "sfx_whoosh.mp3",
    "ding": BASE_DIR / "sfx_ding.mp3",
}

# ============================================================
# EXECUTION COMMANDES SHELL
# ============================================================

def run_command(command: List[str]) -> subprocess.CompletedProcess:
    try:
        command_str = [str(arg) for arg in command]
        result = subprocess.run(command_str, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return result
    except subprocess.CalledProcessError as e:
        print(f"❌ Erreur FFmpeg/Shell: {e.stderr}")
        raise RuntimeError(f"Erreur lors de l'exécution : {e.stderr[-500:]}")

def ensure_ffmpeg():
    if not shutil.which(FFMPEG_BIN):
        raise RuntimeError("FFmpeg n'est pas installé ou n'est pas accessible.")

# ============================================================
# API IA & GENERATION DE SCRIPT COMPLET
# ============================================================

SYSTEM_PROMPT = """Tu es un créateur de contenu star spécialisé en psychologie, neurosciences et curiosités scientifiques.
Ton ton est dynamique, captivant, drôle et légèrement sarcastique.

TU DOIS PRODUIRE DEUX SCRIPTS DANS LE MÊME RETOUR JSON :
1. "script": Le script d'une vidéo longue et détaillée (environ 150-250 mots).
2. "teaser_script": Le script d'un teaser ultra-court (max 45 mots) conçu pour captiver en 3 secondes et renvoyer vers la vidéo longue.

DÉCOUPAGE ET ÉMOTIONS :
Associe les phrases à une émotion parmi : ["default", "thinking", "confused", "laughing", "explaining", "surprised"].

STRUCTURE JSON EXIGÉE :
{
  "title": "Titre accrocheur",
  "script_long": [
    {"text": "Phrase racontée...", "emotion": "explaining", "visual_query": "brain neuroscience"},
    {"text": "Mais pourquoi fait-on ça ?", "emotion": "thinking", "visual_query": "confused person"}
  ],
  "script_teaser": [
    {"text": "Savais-tu que ton cerveau te ment ?", "emotion": "surprised", "visual_query": "shocked face"}
  ]
}
"""

def call_openrouter(topic: str) -> str:
    if not OPENROUTER_API_KEY:
        raise RuntimeError("Clé API OpenRouter manquante.")
        
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "google/gemini-2.5-flash",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Sujet de la vidéo : {topic}"}
        ]
    }
    response = requests.post(url, json=payload, headers=headers, timeout=45)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]

# ============================================================
# PEXELS VIDEO SEARCH
# ============================================================

def search_pexels_video(query: str, orientation: str = "portrait", min_duration: int = 3) -> Optional[str]:
    if not PEXELS_API_KEY:
        return None
    
    clean_query = "".join(c for c in query if c.isalnum() or c.isspace()).strip()
    url = f"https://api.pexels.com/videos/search?query={clean_query}&orientation={orientation}&per_page=5"
    headers = {"Authorization": PEXELS_API_KEY}
    
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            videos = r.json().get("videos", [])
            for video in videos:
                if video.get("duration", 0) >= min_duration:
                    files = video.get("video_files", [])
                    files.sort(key=lambda x: x.get("width", 0), reverse=True)
                    for f in files:
                        if ".mp4" in str(f.get("link", "")).lower():
                            return f.get("link")
    except Exception as e:
        print(f"⚠️ Pexels error: {e}")
    return None

def download_file(url: str, dest_path: Path) -> bool:
    try:
        with requests.get(url, stream=True, timeout=20) as r:
            r.raise_for_status()
            with open(dest_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        return True
    except Exception:
        return False

# ============================================================
# SOUS-TITRES DYNAMIQUES (.ASS / KARAOKÉ)
# ============================================================

def generate_ass_subtitles(boundaries: List[Dict], output_ass_path: Path, width: int, height: int):
    font_size = int(height / 18)
    margin_v = int(height * 0.25)
    
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: TikTok,Arial,{font_size},&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,0,2,10,10,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for b in boundaries:
        word = str(b.get("word", "")).upper().replace("'", "\\'")
        start_t = format_ass_time(float(b.get("start", 0)))
        end_t = format_ass_time(float(b.get("end", 0)))
        
        line = f"Dialogue: 0,{start_t},{end_t},TikTok,,0,0,0,,{{\\c&H0000FFFF&\\t(0,0.1,\\c&H00FFFFFF&)}} {word}"
        events.append(line)
        
    with open(output_ass_path, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(events))

def format_ass_time(seconds: float) -> str:
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centis = int((seconds % 1) * 100)
    return f"{hrs:01d}:{mins:02d}:{secs:02d}.{centis:02d}"

# ============================================================
# PRODUCTION VIDEO & MIX AUDIO (Zéro Musique)
# ============================================================

def create_scene_clips(scenes: List[Dict], work_dir: Path, width: int, height: int) -> List[Path]:
    clips = []
    fps = 25
    
    for idx, scene in enumerate(scenes):
        input_path = scene.get("visual_path")
        duration = float(scene.get("duration", 3.0))
        output_path = work_dir / f"clip_{idx:03d}.mp4"
        frames = int(duration * fps)
        
        filter_complex = (
            f"zoompan=z='min(zoom+0.0015,1.4)':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)',"
            f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
        )
        
        cmd = [
            FFMPEG_BIN, "-y",
            "-loop", "1", "-i", str(input_path),
            "-t", str(duration),
            "-filter_complex", filter_complex,
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps),
            str(output_path)
        ]
        run_command(cmd)
        if output_path.exists():
            clips.append(output_path)
            
    return clips

def process_audio(narration_path: Path, output_audio_path: Path, duration: float) -> Path:
    """
    Traite la voix off (narration) et assure le bon format audio.
    Aucune musique de fond n'est ajoutée ici.
    """
    cmd = [
        FFMPEG_BIN, "-y", 
        "-i", str(narration_path),
        "-c:a", "aac", "-b:a", AUDIO_BITRATE,
        "-t", str(duration),
        str(output_audio_path)
    ]
    run_command(cmd)
    return output_audio_path

# ============================================================
# PIPELINE GLOBAL DE GENERATION
# ============================================================

def generate_video_pipeline(
    script_data: List[Dict], 
    video_format: str = "portrait", 
    status_callback=None
) -> Path:
    
    def log(msg):
        if status_callback: status_callback(msg)
        print(msg)

    ensure_ffmpeg()
    work_dir = TEMP_DIR / f"run_{int(time.time())}"
    work_dir.mkdir(parents=True, exist_ok=True)
    
    width, height = (1080, 1920) if video_format == "portrait" else (1920, 1080)
    orientation = "portrait" if video_format == "portrait" else "landscape"
    
    log("🎥 Recherche des visuels Pexels et téléchargement...")
    scenes = []
    for idx, item in enumerate(script_data):
        file_path = work_dir / f"scene_{idx:03d}.mp4"
        url = search_pexels_video(item.get("visual_query", "science"), orientation=orientation)
        
        if url and download_file(url, file_path):
            item["visual_path"] = file_path
        else:
            fallback = work_dir / f"fallback_{idx:03d}.jpg"
            img = Image.new("RGB", (width, height), color=(25, 25, 35))
            img.save(fallback)
            item["visual_path"] = fallback
            
        item["duration"] = 3.5 
        scenes.append(item)

    log("🎞️ Assemblage des clips et effets de caméra...")
    clips = create_scene_clips(scenes, work_dir, width, height)
    
    list_file = work_dir / "concat.txt"
    with open(list_file, "w") as f:
        for clip in clips:
            f.write(f"file '{clip.resolve().as_posix()}'\n")
            
    concat_video = work_dir / "concat.mp4"
    run_command([
        FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0",
        "-i", str(list_file), "-c", "copy", str(concat_video)
    ])
    
    final_output = OUTPUT_DIR / f"studio_{int(time.time())}_{video_format}.mp4"
    
    # Intégration de la mascotte par défaut (peut être amélioré pour changer par scène)
    mascot_img = MASCOT_FILES.get("default", BASE_DIR / "mascot_default.png")
    
    overlay_cmd = [
        FFMPEG_BIN, "-y",
        "-i", str(concat_video),
        "-i", str(mascot_img) if mascot_img.exists() else str(concat_video),
        "-filter_complex", f"[1:v]scale={int(width*0.30)}:-1[mascot];[0:v][mascot]overlay=x=(W-w)/2:y=H-h-150",
        "-c:v", "libx264", "-preset", "fast",
        str(final_output)
    ]
    run_command(overlay_cmd)
    
    return final_output

# ============================================================
# INTERFACE STREAMLIT
# ============================================================

def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="🧠", layout="centered")
    
    st.title("🧠 Cerveau Curieux — Studio IA")
    st.markdown("Générateur de Vidéos Longues (16:9), Shorts (9:16) et Teasers avec ton avatar.")
    
    topic = st.text_area("Sujet de la vidéo :", placeholder="Ex: Pourquoi avons-nous peur du noir ?")
    
    mode = st.selectbox(
        "Format de création :",
        ["pack_complete", "short_only", "long_only"],
        format_func=lambda x: {
            "pack_complete": "🔥 Pack Ultime : Vidéo Longue (16:9) + Teaser TikTok (9:16)",
            "short_only": "📱 Short / TikTok seul (9:16)",
            "long_only": "💻 Vidéo Longue YouTube seule (16:9)"
        }[x]
    )
    
    if st.button("🚀 Lancer la production", type="primary"):
        if not topic.strip():
            st.error("Veuillez saisir un sujet.")
            return
            
        status = st.empty()
        progress = st.progress(0)
        
        try:
            status.info("🧠 L'IA prépare les scripts et les émotions...")
            progress.progress(15)
            
            raw_ai = call_openrouter(topic)
            
            # Nettoyage de la réponse IA si entourée de backticks
            clean_ai = raw_ai.strip()
            if clean_ai.startswith("
http://googleusercontent.com/immersive_entry_chip/0
http://googleusercontent.com/immersive_entry_chip/1
http://googleusercontent.com/immersive_entry_chip/2
