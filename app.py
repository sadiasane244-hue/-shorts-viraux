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
# SÉCURITÉ : NETTOYAGE DU DISQUE & COMMANDES SHELL
# ============================================================

def cleanup_old_temp_dirs(max_age_hours=1):
    now = time.time()
    for item in TEMP_DIR.iterdir():
        if item.is_dir():
            folder_age = now - item.stat().st_mtime
            if folder_age > (max_age_hours * 3600):
                try:
                    shutil.rmtree(item)
                except Exception as e:
                    print(f"⚠️ Impossible de supprimer {item}: {e}")

def run_command(command: List[str], cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    try:
        command_str = [str(arg) for arg in command]
        result = subprocess.run(
            command_str, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            text=True, 
            check=True,
            cwd=cwd
        )
        return result
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Erreur Shell:\nCommande: {' '.join(command_str)}\nErreur: {e.stderr[-800:]}")

# ============================================================
# CONTRÔLE QUALITÉ (QC)
# ============================================================

def get_media_duration(file_path: Path) -> float:
    if not file_path.exists() or file_path.stat().st_size == 0:
        raise RuntimeError(f"Fichier invalide ou vide : {file_path.name}")
    cmd = [
        FFPROBE_BIN, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(file_path)
    ]
    res = run_command(cmd)
    try:
        return float(res.stdout.strip())
    except ValueError:
        raise RuntimeError(f"Impossible de lire la durée du fichier {file_path.name}")

def qc_validate_video(video_path: Path, min_duration: float):
    if not video_path.exists():
        raise RuntimeError("QC Échec: Le fichier final n'a pas été généré.")
        
    duration = get_media_duration(video_path)
    if duration < min_duration:
        raise RuntimeError(f"QC Échec: Vidéo trop courte ({duration:.1f}s au lieu de {min_duration}s). L'IA n'a pas écrit un script assez long.")
        
    cmd_audio = [
        FFPROBE_BIN, "-v", "error", "-select_streams", "a",
        "-show_entries", "stream=codec_type", "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path)
    ]
    res_audio = run_command(cmd_audio)
    if "audio" not in res_audio.stdout.lower():
        raise RuntimeError("QC Échec: Le fichier MP4 final est muet (aucune piste audio trouvée).")

# ============================================================
# TTS STABLE (VIA LIGNE DE COMMANDE)
# ============================================================

def generate_tts(text: str, output_path: Path):
    cmd = ["edge-tts", "--voice", TTS_VOICE, "--text", text, "--write-media", str(output_path)]
    run_command(cmd)
    if not output_path.exists() or output_path.stat().st_size < 100:
        raise RuntimeError("Génération TTS échouée (fichier vide ou non créé).")

# ============================================================
# API IA - ROBUSTE
# ============================================================

SYSTEM_PROMPT = """Tu es un vulgarisateur scientifique captivant pour la chaîne 'Cerveau Curieux'.
Tu dois produire un script détaillé et très riche pour garantir une durée de narration suffisante.

EXIGENCES VITALES :
- Teaser (Shorts) : 150 mots minimum (6 à 8 scènes).
- Vidéo Longue : 700 mots minimum (15 à 25 scènes détaillées).

POUR CHAQUE SCÈNE, FOURNIS UN TEXTE, UNE ÉMOTION PARMI ["default", "thinking", "confused", "laughing", "explaining", "surprised"], ET UNE REQUÊTE VISUELLE CLAIRE (EN ANGLAIS).

STRUCTURE JSON STRICTE (SANS MARKDOWN REQUIS) :
{
  "title": "Titre explicatif",
  "script_long": [
    {"text": "Avez-vous déjà remarqué comment...", "emotion": "explaining", "visual_query": "human brain memory"}
  ],
  "script_teaser": [
    {"text": "Votre cerveau vous trompe...", "emotion": "surprised", "visual_query": "optical illusion mind"}
  ]
}
"""

def call_openrouter(topic: str) -> str:
    if not OPENROUTER_API_KEY:
        raise RuntimeError("Clé API OpenRouter manquante (OPENROUTER_API_KEY).")
        
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://streamlit.io",
        "X-Title": "Cerveau Curieux Studio"
    }
    
    models = [
        "google/gemini-2.0-flash-exp:free",
        "google/gemini-2.0-flash-lite-001:free",
        "meta-llama/llama-3.3-70b-instruct:free",
        "openrouter/auto"
    ]
    
    errors = []
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
            res = requests.post(url, json=payload, headers=headers, timeout=40)
            if res.status_code == 200:
                content = res.json().get("choices", [])[0].get("message", {}).get("content", "")
                if content.strip():
                    return content
            else:
                errors.append(f"HTTP {res.status_code}")
        except Exception as e:
            errors.append(str(e)[:50])
            continue
            
    raise RuntimeError(f"Toutes les IA ont échoué. Raisons : {', '.join(errors)}")

# ============================================================
# PEXELS & FALLBACK
# ============================================================

def search_pexels_video(query: str, orientation: str) -> Optional[str]:
    if not PEXELS_API_KEY:
        return None
    url = f"https://api.pexels.com/videos/search?query={query}&orientation={orientation}&per_page=3"
    headers = {"Authorization": PEXELS_API_KEY}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            for v in r.json().get("videos", []):
                files = sorted(v.get("video_files", []), key=lambda x: x.get("width", 0), reverse=True)
                for f in files:
                    if ".mp4" in str(f.get("link", "")).lower():
                        return f.get("link")
    except Exception:
        pass
    return None

def download_file(url: str, dest: Path) -> bool:
    try:
        with requests.get(url, stream=True, timeout=15) as r:
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
        
        text = scene["text"].replace("\n", " ").replace('"', '')
        lines.append(f"Dialogue: 0,{start_t},{end_t},Default,,0,0,0,,{text}")
        current_time += duration

    with open(output_ass, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(lines))

# ============================================================
# PIPELINE DE PRODUCTION SYNCHRONISÉ SUR L'AUDIO & MASCOTTE DYNAMIQUE
# ============================================================

def generate_video_pipeline(script_scenes: List[Dict], video_format: str, min_target_duration: float, status_cb) -> Path:
    work_dir = TEMP_DIR / f"run_{int(time.time())}_{video_format}"
    work_dir.mkdir(parents=True, exist_ok=True)
    
    width, height = (1080, 1920) if video_format == "portrait" else (1920, 1080)
    orientation = "portrait" if video_format == "portrait" else "landscape"

    # 1. AUDIO TTS
    status_cb("🎙️ Génération de la voix off (Edge-TTS)...")
    audio_clips = []
    for idx, scene in enumerate(script_scenes):
        audio_file = work_dir / f"audio_{idx:03d}.mp3"
        generate_tts(scene["text"], audio_file)
        scene["duration"] = get_media_duration(audio_file)
        audio_clips.append(audio_file)

    concat_audio_list = work_dir / "concat_audio.txt"
    with open(concat_audio_list, "w") as f:
        for a in audio_clips:
            f.write(f"file '{a.name}'\n")
            
    full_audio = work_dir / "full_audio.mp3"
    run_command([FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0", "-i", "concat_audio.txt", "-c", "copy", "full_audio.mp3"], cwd=work_dir)

    # 2. VISUELS & MASCOTTE DYNAMIQUE SCÈNE PAR SCÈNE
    status_cb("🎥 Téléchargement des visuels et intégration dynamique de la mascotte...")
    video_clips = []
    fps = 25
    
    if video_format == "portrait":
        mascot_scale = int(width * 0.22)
        pos_x = "(W-w)/2"
        pos_y = "H-h-450"
    else:
        mascot_scale = int(width * 0.15)
        pos_x = "40"
        pos_y = "H-h-40"

    for idx, scene in enumerate(script_scenes):
        duration = scene["duration"]
        emotion = scene.get("emotion", "default")
        
        mascot_img = MASCOT_FILES.get(emotion, MASCOT_FILES["default"])
        if not mascot_img.exists():
            mascot_img = MASCOT_FILES.get("default")

        url = search_pexels_video(scene.get("visual_query", "science"), orientation)
        visual_file = work_dir / f"src_vis_{idx:03d}.mp4"
        output_clip = work_dir / f"clip_{idx:03d}.mp4"
        
        display_duration = min(4.0, duration) 
        enable_expr = f"between(t,0,{display_duration})"

        if url and download_file(url, visual_file):
            base_filter = f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}[bg]"
            input_file = visual_file.name
            cmd = [FFMPEG_BIN, "-y", "-stream_loop", "-1", "-i", input_file, "-i", str(mascot_img.resolve())]
        else:
            fallback = work_dir / f"fallback_{idx:03d}.png"
            Image.new("RGB", (width, height), color=(30, 30, 45)).save(fallback)
            frames = int(duration * fps)
            base_filter = f"[0:v]zoompan=z='min(zoom+0.0015,1.3)':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)',scale={width}:{height}[bg]"
            input_file = fallback.name
            cmd = [FFMPEG_BIN, "-y", "-loop", "1", "-i", input_file, "-i", str(mascot_img.resolve())]

        filter_complex = (
            f"{base_filter};"
            f"[1:v]scale={mascot_scale}:-1[mascot];"
            f"[bg][mascot]overlay=x={pos_x}:y={pos_y}:enable='{enable_expr}'[v_out]"
        )

        cmd.extend([
            "-t", str(duration), 
            "-filter_complex", filter_complex, 
            "-map", "[v_out]", 
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps), 
            output_clip.name
        ])
        
        run_command(cmd, cwd=work_dir)
        video_clips.append(output_clip)

    concat_video_list = work_dir / "concat_video.txt"
    with open(concat_video_list, "w") as f:
        for v in video_clips:
            f.write(f"file '{v.name}'\n")
            
    raw_video = work_dir / "raw_video.mp4"
    run_command([FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0", "-i", "concat_video.txt", "-c", "copy", "raw_video.mp4"], cwd=work_dir)

    # 3. SOUS-TITRES & MIXAGE FINAL
    status_cb("⚙️ Incrustation ASS et mixage final...")
    ass_file = work_dir / "subtitles.ass"
    create_ass_subtitles(script_scenes, ass_file, width, height)

    final_output = OUTPUT_DIR / f"export_{int(time.time())}_{video_format}.mp4"
    
    cmd_final = [
        FFMPEG_BIN, "-y", "-i", "raw_video.mp4", "-i", "full_audio.mp3",
        "-vf", "subtitles=subtitles.ass", "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-c:a", "aac", "-b:a", "192k", "-shortest", str(final_output.resolve())
    ]
        
    run_command(cmd_final, cwd=work_dir)

    # 4. QUALITÉ
    status_cb("🔍 Contrôle Qualité FFprobe...")
    qc_validate_video(final_output, min_target_duration)
    
    return final_output

# ============================================================
# INTERFACE
# ============================================================

def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="🧠", layout="centered")
    st.title("🧠 Cerveau Curieux — Studio IA")

    cleanup_old_temp_dirs()

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
            
            try:
                clean_ai = re.sub(r"^\x60{3}(?:json)?\s*", "", raw_ai.strip(), flags=re.IGNORECASE)
                clean_ai = re.sub(r"\s*\x60{3}$", "", clean_ai)
                json_match = re.search(r"\{.*\}", clean_ai, re.DOTALL)
                if json_match:
                    clean_ai = json_match.group(0)
                ai_data = json.loads(clean_ai)
            except json.JSONDecodeError as e:
                raise RuntimeError(f"Le format de réponse de l'IA est invalide. Relancez la génération. Détail : {e}")

            if mode in ["pack_complete", "short_only"]:
                status.info("📱 Préparation du Teaser Vertical (cible min. 25s)...")
                progress.progress(40)
                short_path = generate_video_pipeline(ai_data.get("script_teaser", []), "portrait", 25.0, status.info)
                st.subheader("📱 Teaser (TikTok / Shorts 9:16)")
                st.video(str(short_path))

            if mode in ["pack_complete", "long_only"]:
                status.info("💻 Préparation de la Vidéo Longue (cible min. 50s)...")
                progress.progress(70)
                long_path = generate_video_pipeline(ai_data.get("script_long", []), "landscape", 50.0, status.info)
                st.subheader("💻 Vidéo Longue (YouTube 16:9)")
                st.video(str(long_path))

            progress.progress(100)
            status.success("🎉 Production terminée et certifiée sans erreur !")

        except Exception as e:
            progress.progress(100)
            st.error(f"❌ ÉCHEC : {e}")

if __name__ == "__main__":
    main()
