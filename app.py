import os
import time
import json
import re
import shutil
import subprocess
import requests
import asyncio
from pathlib import Path
from typing import List, Dict, Optional
from PIL import Image
import streamlit as st
import edge_tts

# ============================================================
# CONFIGURATION ET PATHS DE BASE
# ============================================================

APP_TITLE = "🧠 Cerveau Curieux — Studio IA Ultime"
BASE_DIR = Path(__file__).resolve().parent
TEMP_DIR = BASE_DIR / "temp"
OUTPUT_DIR = BASE_DIR / "output"

TEMP_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

FFMPEG_BIN = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE_BIN = shutil.which("ffprobe") or "ffprobe"

TTS_VOICE = "fr-FR-HenriNeural"

MASCOT_FILES = {
    "default": BASE_DIR / "mascot_default.png",
    "thinking": BASE_DIR / "mascot_thinking.png",
    "confused": BASE_DIR / "mascot_confused.png",
    "laughing": BASE_DIR / "mascot_laughing.png",
    "explaining": BASE_DIR / "mascot_explaining.png",
    "surprised": BASE_DIR / "mascot_surprised.png",
}

# ============================================================
# EXECUTION COMMANDES SHELL & FFPROBE
# ============================================================

def run_command(command: List[str]) -> subprocess.CompletedProcess:
    try:
        command_str = [str(arg) for arg in command]
        result = subprocess.run(command_str, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return result
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Erreur FFmpeg/Shell: {e.stderr[-500:]}")

def get_media_duration(file_path: Path) -> float:
    cmd = [
        FFPROBE_BIN, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(file_path)
    ]
    res = run_command(cmd)
    return float(res.stdout.strip())

def qc_validate_video(video_path: Path, min_duration: float):
    """Contrôle de qualité strict via FFprobe avant validation."""
    if not video_path.exists():
        raise RuntimeError("QC Échec: Fichier vidéo inexistant.")
        
    duration = get_media_duration(video_path)
    if duration < min_duration:
        raise RuntimeError(f"QC Échec: Durée insuffisante ({duration:.1f}s produites, minimum requis {min_duration}s).")
        
    cmd_audio = [
        FFPROBE_BIN, "-v", "error",
        "-select_streams", "a",
        "-show_entries", "stream=codec_type",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path)
    ]
    res_audio = run_command(cmd_audio)
    if "audio" not in res_audio.stdout.lower():
        raise RuntimeError("QC Échec: Le fichier MP4 final ne contient AUCUNE piste audio.")

# ============================================================
# GENERATION AUDIO EDGE-TTS
# ============================================================

async def generate_tts_async(text: str, output_path: Path):
    communicate = edge_tts.Communicate(text, TTS_VOICE)
    await communicate.save(str(output_path))

def generate_tts(text: str, output_path: Path):
    asyncio.run(generate_tts_async(text, output_path))

# ============================================================
# APIS IA ET PROMPTS ENRICHIS
# ============================================================

SYSTEM_PROMPT = """Tu es un vulgarisateur scientifique captivant pour la chaîne 'Cerveau Curieux'.
Tu dois produire un script détaillé et très riche pour garantir une durée de narration suffisante.

EXIGENCES :
- Teaser (Shorts) : 120 à 150 mots minimum (6 à 8 scènes).
- Vidéo Longue : 600 à 900 mots minimum (15 à 25 scènes détaillées).

POUR CHAQUE SCÈNE, FOURNIS UN SCRIPT DENSE ET UN REQUÊTE VISUELLE CLAIRE (EN ANGLAIS).

STRUCTURE JSON STRICTE (SANS MARKDOWN REQUIS) :
{
  "title": "Titre explicatif",
  "script_long": [
    {"text": "Avez-vous déjà remarqué comment votre cerveau réagit lorsque...", "emotion": "explaining", "visual_query": "human brain memory"},
    {"text": "Ce phénomène s'explique par la libération massive de dopamine...", "emotion": "thinking", "visual_query": "neuroscience laboratory"}
  ],
  "script_teaser": [
    {"text": "Votre cerveau vous trompe tous les jours, et voici exactement comment !", "emotion": "surprised", "visual_query": "optical illusion mind"}
  ]
}
"""

def call_openrouter(topic: str) -> str:
    if not OPENROUTER_API_KEY:
        raise RuntimeError("Clé API OpenRouter manquante.")
        
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    
    models = [
        "google/gemini-2.0-flash-exp:free",
        "meta-llama/llama-3.3-70b-instruct:free",
        "google/gemini-flash-1.5-8b:free"
    ]
    
    for model in models:
        try:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Sujet détaillé : {topic}"}
                ],
                "temperature": 0.7
            }
            res = requests.post(url, json=payload, headers=headers, timeout=30)
            if res.status_code == 200:
                content = res.json()["choices"][0]["message"]["content"]
                if content and len(content.strip()) > 0:
                    return content
        except Exception:
            continue
            
    raise RuntimeError("Erreur lors de la génération du script via l'IA.")

# ============================================================
# RECHERCHE PEXELS
# ============================================================

def search_pexels_video(query: str, orientation: str) -> Optional[str]:
    if not PEXELS_API_KEY:
        return None
    url = f"https://api.pexels.com/videos/search?query={query}&orientation={orientation}&per_page=3"
    headers = {"Authorization": PEXELS_API_KEY}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            videos = r.json().get("videos", [])
            for v in videos:
                files = sorted(v.get("video_files", []), key=lambda x: x.get("width", 0), reverse=True)
                for f in files:
                    if ".mp4" in str(f.get("link", "")).lower():
                        return f.get("link")
    except Exception:
        pass
    return None

def download_file(url: str, dest: Path) -> bool:
    try:
        with requests.get(url, stream=True, timeout=20) as r:
            r.raise_for_status()
            with open(dest, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        return True
    except Exception:
        return False

# ============================================================
# SOUS-TITRES ASS
# ============================================================

def create_ass_subtitles(scenes: List[Dict], output_ass: Path, width: int, height: int):
    font_size = 48 if width == 1080 else 36
    margin_v = 180 if height == 1920 else 60
    
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{font_size},&H00FFFFFF,&H00000000,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,20,20,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    current_time = 0.0
    
    for scene in scenes:
        duration = scene["duration"]
        start_t = time.strftime('%H:%M:%S', time.gmtime(current_time)) + f".{int((current_time % 1)*100):02d}"
        end_t = time.strftime('%H:%M:%S', time.gmtime(current_time + duration)) + f".{int(((current_time + duration) % 1)*100):02d}"
        
        text = scene["text"].replace("\n", " ")
        lines.append(f"Dialogue: 0,{start_t},{end_t},Default,,0,0,0,,{text}")
        current_time += duration

    with open(output_ass, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(lines))

# ============================================================
# PIPELINE DE PRODUCTION SYNCHRONISÉ SUR L'AUDIO
# ============================================================

def generate_video_pipeline(
    script_scenes: List[Dict], 
    video_format: str, 
    min_target_duration: float,
    status_cb=None
) -> Path:

    def log(msg):
        if status_cb: status_cb(msg)

    work_dir = TEMP_DIR / f"run_{int(time.time())}_{video_format}"
    work_dir.mkdir(parents=True, exist_ok=True)
    
    width, height = (1080, 1920) if video_format == "portrait" else (1920, 1080)
    orientation = "portrait" if video_format == "portrait" else "landscape"

    # 1. Génération Audio TTS par scène et synchronisation stricte
    log("🎙️ Génération de la voix off (Edge-TTS)...")
    audio_clips = []
    
    for idx, scene in enumerate(script_scenes):
        audio_file = work_dir / f"audio_{idx:03d}.mp3"
        generate_tts(scene["text"], audio_file)
        
        duration = get_media_duration(audio_file)
        scene["audio_path"] = audio_file
        scene["duration"] = duration
        audio_clips.append(audio_file)

    # Concaténation Audio Globale
    concat_audio_list = work_dir / "concat_audio.txt"
    with open(concat_audio_list, "w") as f:
        for a in audio_clips:
            f.write(f"file '{a.resolve().as_posix()}'\n")
            
    full_audio = work_dir / "full_audio.mp3"
    run_command([FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_audio_list), "-c", "copy", str(full_audio)])

    # 2. Téléchargement et découpe des Visuels
    log("🎥 Recherche des visuels et calage exact sur la durée audio...")
    video_clips = []
    fps = 25

    for idx, scene in enumerate(script_scenes):
        visual_file = work_dir / f"src_vis_{idx:03d}.mp4"
        duration = scene["duration"]
        url = search_pexels_video(scene.get("visual_query", "science"), orientation)
        
        is_downloaded = url and download_file(url, visual_file)
        output_clip = work_dir / f"clip_{idx:03d}.mp4"
        
        if is_downloaded:
            filter_str = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
            cmd = [
                FFMPEG_BIN, "-y", "-stream_loop", "-1", "-i", str(visual_file),
                "-t", str(duration), "-filter_complex", filter_str,
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps), str(output_clip)
            ]
        else:
            fallback = work_dir / f"fallback_{idx:03d}.png"
            Image.new("RGB", (width, height), color=(20, 25, 35)).save(fallback)
            frames = int(duration * fps)
            filter_str = f"zoompan=z='min(zoom+0.0015,1.3)':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)',scale={width}:{height}"
            cmd = [
                FFMPEG_BIN, "-y", "-loop", "1", "-i", str(fallback),
                "-t", str(duration), "-filter_complex", filter_str,
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps), str(output_clip)
            ]
        run_command(cmd)
        video_clips.append(output_clip)

    # Concaténation Vidéo
    concat_video_list = work_dir / "concat_video.txt"
    with open(concat_video_list, "w") as f:
        for v in video_clips:
            f.write(f"file '{v.resolve().as_posix()}'\n")
            
    raw_video = work_dir / "raw_video.mp4"
    run_command([FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_video_list), "-c", "copy", str(raw_video)])

    # 3. Génération des sous-titres ASS
    log("📝 Génération et incrustation des sous-titres...")
    ass_file = work_dir / "subtitles.ass"
    create_ass_subtitles(script_scenes, ass_file, width, height)

    # 4. Multiplexage Final (Vidéo + Audio + Sous-titres + Mascotte discrète dans le coin)
    log("⚙️ Assemblage final et mixage audio/vidéo...")
    final_output = OUTPUT_DIR / f"export_{int(time.time())}_{video_format}.mp4"
    mascot_img = MASCOT_FILES.get("default", BASE_DIR / "mascot_default.png")
    
    # Mascotte repositionnée en bas à droite (20% de taille) pour ne pas masquer le contenu
    ass_path_escaped = str(ass_file.resolve()).replace("\\", "/").replace(":", "\\:")
    
    if mascot_img.exists():
        filter_complex = (
            f"[1:v]scale={int(width*0.20)}:-1[mascot];"
            f"[0:v][mascot]overlay=x=W-w-30:y=H-h-30[v_mascot];"
            f"[v_mascot]subtitles='{ass_path_escaped}'[outv]"
        )
        cmd_final = [
            FFMPEG_BIN, "-y",
            "-i", str(raw_video),
            "-i", str(mascot_img),
            "-i", str(full_audio),
            "-filter_complex", filter_complex,
            "-map", "[outv]", "-map", "2:a",
            "-c:v", "libx264", "-c:a", "aac", "-b:a", "192k",
            "-shortest", str(final_output)
        ]
    else:
        cmd_final = [
            FFMPEG_BIN, "-y",
            "-i", str(raw_video),
            "-i", str(full_audio),
            "-vf", f"subtitles='{ass_path_escaped}'",
            "-map", "0:v", "-map", "1:a",
            "-c:v", "libx264", "-c:a", "aac", "-b:a", "192k",
            "-shortest", str(final_output)
        ]
        
    run_command(cmd_final)

    # 5. Contrôle Qualité Final via FFprobe
    log("🔍 Contrôle qualité FFprobe...")
    qc_validate_video(final_output, min_target_duration)
    
    return final_output

# ============================================================
# STREAMLIT UI
# ============================================================

def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="🧠", layout="centered")
    st.title("🧠 Cerveau Curieux — Studio IA")

    topic = st.text_area("Sujet de la vidéo :", placeholder="Ex: Comment le cerveau fabrique-t-il les souvenirs ?")
    mode = st.selectbox(
        "Format de création :",
        ["pack_complete", "short_only", "long_only"],
        format_func=lambda x: {
            "pack_complete": "🔥 Pack Ultime : Vidéo Longue (16:9) + Teaser Vertical (9:16)",
            "short_only": "📱 Teaser / Short Seul (9:16)",
            "long_only": "💻 Vidéo Longue YouTube Seule (16:9)"
        }[x]
    )

    if st.button("🚀 Lancer la production", type="primary"):
        if not topic.strip():
            st.error("Veuillez saisir un sujet.")
            return

        status = st.empty()
        progress = st.progress(0)

        try:
            status.info("🧠 Génération du script enrichi via l'IA...")
            progress.progress(10)
            
            raw_ai = call_openrouter(topic)
            clean_ai = re.sub(r"^\x60{3}(?:json)?\s*", "", raw_ai.strip(), flags=re.IGNORECASE)
            clean_ai = re.sub(r"\s*\x60{3}$", "", clean_ai)
            
            json_match = re.search(r"\{.*\}", clean_ai, re.DOTALL)
            if json_match:
                clean_ai = json_match.group(0)
                
            ai_data = json.loads(clean_ai)

            if mode in ["pack_complete", "short_only"]:
                status.info("📱 Production du Teaser Vertical (cible min. 35s)...")
                progress.progress(40)
                short_path = generate_video_pipeline(
                    ai_data.get("script_teaser", []), 
                    "portrait", 
                    min_target_duration=30.0, 
                    status_cb=status.info
                )
                st.subheader("📱 Teaser (TikTok / Shorts 9:16)")
                st.video(str(short_path))

            if mode in ["pack_complete", "long_only"]:
                status.info("💻 Production de la Vidéo Longue (cible min. 120s)...")
                progress.progress(70)
                long_path = generate_video_pipeline(
                    ai_data.get("script_long", []), 
                    "landscape", 
                    min_target_duration=60.0, 
                    status_cb=status.info
                )
                st.subheader("💻 Vidéo Longue (YouTube 16:9)")
                st.video(str(long_path))

            progress.progress(100)
            status.success("🎉 Production et validation Qualité réussies avec succès !")

        except Exception as e:
            progress.progress(100)
            status.error(f"❌ Échec de la production : {e}")

if __name__ == "__main__":
    main()
