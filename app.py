import os
import time
import json
import re
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
1. "script_long": Le script d'une vidéo longue et détaillée (environ 150-250 mots).
2. "script_teaser": Le script d'un teaser ultra-court (max 45 mots) conçu pour captiver en 3 secondes et renvoyer vers la vidéo longue.

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
        "model": "openrouter/free",  # Utilisation du modèle 100% gratuit
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
# PRODUCTION VIDEO
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
            
            # Nettoyage ultra-robuste avec regex ASCII (évite les erreurs de syntaxe)
            clean_ai = raw_ai.strip()
            clean_ai = re.sub(r"^\x60{3}(?:json)?\s*", "", clean_ai, flags=re.IGNORECASE)
            clean_ai = re.sub(r"\s*\x60{3}$", "", clean_ai)
            clean_ai = clean_ai.strip()
            
            ai_data = json.loads(clean_ai)
            
            if mode in ["pack_complete", "long_only"]:
                status.info("💻 Production de la vidéo longue YouTube (16:9)...")
                progress.progress(40)
                long_path = generate_video_pipeline(ai_data.get("script_long", []), "paysage", status.info)
                st.subheader("💻 Vidéo Longue (YouTube 16:9)")
                st.video(str(long_path))
                
            if mode in ["pack_complete", "short_only"]:
                status.info("📱 Production du Teaser Vertical (9:16)...")
                progress.progress(75)
                short_path = generate_video_pipeline(ai_data.get("script_teaser", []), "portrait", status.info)
                st.subheader("📱 Teaser (TikTok / Shorts 9:16)")
                st.video(str(short_path))
                
            progress.progress(100)
            status.success("🎉 Production terminée avec succès !")
            
        except Exception as e:
            progress.progress(100)
            status.error(f"Erreur durant la génération : {e}")

if __name__ == "__main__":
    main()
