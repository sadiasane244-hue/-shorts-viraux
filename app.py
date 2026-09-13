import os
import time
import json
import re
import shutil
import subprocess
import requests
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from PIL import Image
import streamlit as st
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

# ============================================================
# CONFIGURATION ET PATHS DE BASE
# ============================================================

APP_TITLE = "🧠 Cerveau Curieux — Studio IA Autonome"
BASE_DIR = Path.cwd()
TEMP_DIR = BASE_DIR / "temp"
OUTPUT_DIR = BASE_DIR / "output"

TEMP_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

FFMPEG_BIN = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE_BIN = shutil.which("ffprobe") or "ffprobe"

TTS_VOICE = "fr-FR-HenriNeural"

# Fichiers audio SFX mis à jour avec tes noms exacts
SFX_FILE = BASE_DIR / "sfx_whoosh.mp3" 
CLICK_SFX_FILE = BASE_DIR / "sfx_ding.mp3"

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

# ============================================================
# STRUCTURE D'OUTPUT JSON STRICTE (PYDANTIC)
# ============================================================

class Scene(BaseModel):
    text: str = Field(description="Texte de la narration. Ton moderne, amusant, direct.")
    emotion: str = Field(description="Émotion parmi: default, thinking, confused, laughing, explaining, surprised, angry, happy, shocked, sad")
    visual_query: str = Field(description="Mots-clés visuels en ANGLAIS. DOIT REFLÉTER UNE ACTION PHYSIQUE LITTÉRALE. AUCUN concept abstrait.")

class ScriptOutput(BaseModel):
    format_choisi: str = Field(description="Choix parmi: short_single, short_twoparts, long_plus_teaser")
    title: str = Field(description="Titre captivant, accrocheur et honnête pour la vidéo")
    hashtags: List[str] = Field(description="Liste de 4 à 6 hashtags pertinents")
    script_principal: List[Scene] = Field(description="Scènes de la vidéo (au moins 8 à 10 scènes). La dernière scène DOIT être l'appel à l'action.")
    script_teaser: List[Scene] = Field(default=[], description="Scènes du teaser si le format long_plus_teaser est choisi")

# ============================================================
# SÉCURITÉ ET OUTILS SYSTEME
# ============================================================

def cleanup_old_temp_dirs(max_age_hours=1):
    now = time.time()
    for item in TEMP_DIR.iterdir():
        if item.is_dir():
            folder_age = now - item.stat().st_mtime
            if folder_age > (max_age_hours * 3600):
                try: shutil.rmtree(item)
                except Exception: pass

def run_command(command: List[str], cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    try:
        cmd_str = [str(arg) for arg in command]
        return subprocess.run(cmd_str, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True, cwd=cwd)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Erreur Shell:\nCommande: {' '.join(cmd_str)}\nErreur: {e.stderr[-800:]}")

def get_media_duration(file_path: Path) -> float:
    if not file_path.exists() or file_path.stat().st_size == 0: return 0.0
    cmd = [FFPROBE_BIN, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(file_path)]
    res = run_command(cmd)
    try: return float(res.stdout.strip())
    except ValueError: return 0.0

def qc_validate_video(video_path: Path):
    if not video_path.exists():
        raise RuntimeError("QC Échec: Le fichier final n'a pas été généré.")
    cmd_audio = [
        FFPROBE_BIN, "-v", "error", "-select_streams", "a",
        "-show_entries", "stream=codec_type", "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path)
    ]
    res_audio = run_command(cmd_audio)
    if "audio" not in res_audio.stdout.lower():
        raise RuntimeError("QC Échec: Le MP4 final est muet.")

# ============================================================
# EDGE-TTS
# ============================================================

def generate_tts(text: str, output_path: Path):
    cmd = ["edge-tts", "--voice", TTS_VOICE, "--text", text, "--write-media", str(output_path)]
    run_command(cmd)
    if not output_path.exists() or output_path.stat().st_size < 100:
        raise RuntimeError(f"Génération TTS échouée pour le texte : {text[:30]}...")

# ============================================================
# GENERATION VIA SDK GEMINI OFFICIEL
# ============================================================

SYSTEM_PROMPT = """Tu es le réalisateur IA de 'Cerveau Curieux'. Ton but est de créer des scripts de vidéos courtes très détaillés et dynamiques (min 45 secondes).

RÈGLES DE NARRATION ET DE RYTHME (CRITIQUE) :
- Explique le sujet en profondeur, ne te contente pas de le survoler. Donne des exemples.
- DÉCOUPE LE SCRIPT : 1 seule phrase par scène. C'est obligatoire pour garantir un changement visuel très régulier. Une vidéo doit contenir au minimum 8 à 10 scènes.
- Termine TOUJOURS la dernière scène par un appel à l'action naturel ("Abonne-toi", "Like").

RÈGLES CRITIQUES POUR LES REQUÊTES VISUELLES (`visual_query`) :
- Décris LITTÉRALEMENT ce qu'on voit à l'écran. UNIQUEMENT des actions physiques et concrètes.
- 2 à 4 mots max en ANGLAIS.
- RÈGLE ABSOLUE POUR LA DERNIÈRE SCÈNE (CTA) : La `visual_query` DOIT ÊTRE "thumbs up" ou "like button" ou "person smiling pointing".
"""

def generate_script_gemini(topic: str, status_cb) -> Dict:
    if not GEMINI_API_KEY: raise RuntimeError("Clé API GEMINI manquante.")
    client = genai.Client(api_key=GEMINI_API_KEY)
    status_cb("🧠 Analyse du sujet et rédaction détaillée du script...")

    try:
        response = client.models.generate_content(
            model='gemini-3.6-flash',
            contents=f"Sujet : {topic}",
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=ScriptOutput,
                temperature=0.7,
            ),
        )
        if hasattr(response, 'parsed') and response.parsed:
            return response.parsed.model_dump()
        return json.loads(response.text)
    except Exception as e:
        raise RuntimeError(f"Erreur Gemini Flash : {e}")

# ============================================================
# PEXELS & FALLBACK
# ============================================================

def search_pexels_video(query: str, orientation: str) -> Optional[str]:
    if not PEXELS_API_KEY: return None
    words = [w for w in re.sub(r'[^a-zA-Z\s]', '', query).split() if len(w) > 2]
    clean_query = " ".join(words[:4])
    
    url = f"https://api.pexels.com/videos/search?query={clean_query}&orientation={orientation}&per_page=5"
    headers = {"Authorization": PEXELS_API_KEY}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            for v in r.json().get("videos", []):
                files = sorted(v.get("video_files", []), key=lambda x: x.get("width", 0), reverse=True)
                for f in files:
                    if ".mp4" in str(f.get("link", "")).lower():
                        return f.get("link")
    except Exception: pass
    return None

def download_file(url: str, dest: Path) -> bool:
    try:
        with requests.get(url, stream=True, timeout=15) as r:
            r.raise_for_status()
            with open(dest, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192): f.write(chunk)
        return True
    except Exception: return False

# ============================================================
# SOUS-TITRES DYNAMIQUES (EFFET KARAOKÉ)
# ============================================================

def create_ass_subtitles(scenes: List[Dict], output_ass: Path, width: int, height: int):
    font_size = 56 if width == 1080 else 38
    margin_v = 300 if height == 1920 else 70
    
    HIGHLIGHT_COLOR = "&H00FFFF&" # Jaune en ASS
    NORMAL_COLOR = "&HFFFFFF&"   # Blanc
    
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{font_size},&H00FFFFFF,&H00000000,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,2,20,20,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    current_time = 0.0
    
    for scene in scenes:
        scene_duration = scene["duration"]
        text = scene["text"].replace("\n", " ").replace('"', '')
        words = text.split()
        
        if not words:
            current_time += scene_duration
            continue
            
        chunk_size = 5
        chunks = [words[i:i + chunk_size] for i in range(0, len(words), chunk_size)]
        chunk_duration = scene_duration / len(chunks)
        
        for idx_chunk, chunk_words in enumerate(chunks):
            chunk_start = current_time + (idx_chunk * chunk_duration)
            word_duration = chunk_duration / len(chunk_words)
            
            for idx_word, word in enumerate(chunk_words):
                start_t = chunk_start + (idx_word * word_duration)
                end_t = start_t + word_duration
                
                def fmt_time(t):
                    return time.strftime('%H:%M:%S', time.gmtime(t)) + f".{int((t % 1)*100):02d}"
                
                formatted_words = []
                for k, w in enumerate(chunk_words):
                    if k == idx_word:
                        formatted_words.append(f"{{\\c{HIGHLIGHT_COLOR}}}{w}{{\\c{NORMAL_COLOR}}}")
                    else:
                        formatted_words.append(w)
                
                dialogue_text = " ".join(formatted_words)
                lines.append(f"Dialogue: 0,{fmt_time(start_t)},{fmt_time(end_t)},Default,,0,0,0,,{dialogue_text}")
                
        current_time += scene_duration

    with open(output_ass, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(lines))

def split_video_in_two(input_video: Path, total_duration: float, out_dir: Path) -> Tuple[Path, Path]:
    mid_point = total_duration / 2.0
    part1 = out_dir / f"{input_video.stem}_Part1.mp4"
    part2 = out_dir / f"{input_video.stem}_Part2.mp4"
    run_command([FFMPEG_BIN, "-y", "-i", str(input_video), "-t", str(mid_point), "-c:v", "libx264", "-preset", "fast", "-c:a", "aac", str(part1)])
    run_command([FFMPEG_BIN, "-y", "-i", str(input_video), "-ss", str(mid_point), "-c:v", "libx264", "-preset", "fast", "-c:a", "aac", str(part2)])
    return part1, part2

# ============================================================
# PIPELINE DE PRODUCTION GLOBAL
# ============================================================

def generate_video_pipeline(script_scenes: List[Dict], video_format: str, status_cb) -> Path:
    if not script_scenes: raise ValueError("Le script est vide.")

    work_dir = TEMP_DIR / f"run_{int(time.time())}_{video_format}"
    work_dir.mkdir(parents=True, exist_ok=True)
    width, height = (1080, 1920) if video_format == "portrait" else (1920, 1080)
    orientation = "portrait" if video_format == "portrait" else "landscape"

    status_cb("🎙️ Génération de la voix off et mixage SFX...")
    audio_clips = []
    total_duration = 0.0
    
    total_scenes = len(script_scenes)

    for idx, scene in enumerate(script_scenes):
        temp_audio = work_dir / f"temp_audio_{idx:03d}.mp3"
        final_audio = work_dir / f"audio_{idx:03d}.mp3"
        
        # Correction de la prononciation avant génération (n'affecte pas les sous-titres)
        text_for_tts = scene["text"].replace("hacker", "haquer").replace("Hacker", "Haquer")
        generate_tts(text_for_tts, temp_audio)
        
        is_last_scene = (idx == total_scenes - 1)
        sfx_to_use = None
        
        if is_last_scene and CLICK_SFX_FILE.exists():
            sfx_to_use = CLICK_SFX_FILE
        elif idx > 0 and SFX_FILE.exists():
            sfx_to_use = SFX_FILE

        if sfx_to_use:
            # Filtre amix simplifié pour compatibilité Streamlit Cloud
            cmd_mix = [
                FFMPEG_BIN, "-y", "-i", str(temp_audio), "-i", str(sfx_to_use),
                "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=first[a]",
                "-map", "[a]", str(final_audio)
            ]
            run_command(cmd_mix, cwd=work_dir)
        else:
            shutil.copy(temp_audio, final_audio)

        dur = get_media_duration(final_audio)
        scene["duration"] = dur
        total_duration += dur
        audio_clips.append(final_audio)

    with open(work_dir / "concat_audio.txt", "w") as f:
        for a in audio_clips: f.write(f"file '{a.name}'\n")
    run_command([FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0", "-i", "concat_audio.txt", "-c", "copy", "full_audio.mp3"], cwd=work_dir)

    status_cb("🎥 Assemblage des visuels et mascotte...")
    video_clips = []
    fps = 25
    mascot_scale = int(width * 0.22) if video_format == "portrait" else int(width * 0.15)
    pos_x = "(W-w)/2" if video_format == "portrait" else "40"
    pos_y = "H-h-450" if video_format == "portrait" else "H-h-40"

    for idx, scene in enumerate(script_scenes):
        duration = scene["duration"]
        emotion = scene.get("emotion", "default")
        mascot_img = MASCOT_FILES.get(emotion, MASCOT_FILES["default"])
        if not mascot_img.exists(): mascot_img = MASCOT_FILES.get("default")

        url = search_pexels_video(scene.get("visual_query", "person working"), orientation)
        visual_file = work_dir / f"src_vis_{idx:03d}.mp4"
        output_clip = work_dir / f"clip_{idx:03d}.mp4"
        
        display_duration = min(4.0, duration) 
        enable_expr = f"between(t,0,{display_duration})"

        if url and download_file(url, visual_file):
            base_filter = f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}[bg]"
            cmd = [FFMPEG_BIN, "-y", "-stream_loop", "-1", "-i", visual_file.name, "-i", str(mascot_img.resolve())]
        else:
            fallback = work_dir / f"fallback_{idx:03d}.png"
            Image.new("RGB", (width, height), color=(30, 30, 45)).save(fallback)
            frames = int(duration * fps)
            base_filter = f"[0:v]zoompan=z='min(zoom+0.0015,1.3)':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)',scale={width}:{height}[bg]"
            cmd = [FFMPEG_BIN, "-y", "-loop", "1", "-i", fallback.name, "-i", str(mascot_img.resolve())]

        filter_complex = f"{base_filter};[1:v]scale={mascot_scale}:-1[mascot];[bg][mascot]overlay=x={pos_x}:y={pos_y}:enable='{enable_expr}'[v_out]"
        cmd.extend(["-t", str(duration), "-filter_complex", filter_complex, "-map", "[v_out]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps), output_clip.name])
        run_command(cmd, cwd=work_dir)
        video_clips.append(output_clip)

    with open(work_dir / "concat_video.txt", "w") as f:
        for v in video_clips: f.write(f"file '{v.name}'\n")
    run_command([FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0", "-i", "concat_video.txt", "-c", "copy", "raw_video.mp4"], cwd=work_dir)

    status_cb("⚙️ Incrustation des sous-titres karaoké...")
    create_ass_subtitles(script_scenes, work_dir / "subtitles.ass", width, height)

    final_output = OUTPUT_DIR / f"export_{int(time.time())}_{video_format}.mp4"
    cmd_final = [
        FFMPEG_BIN, "-y", "-i", "raw_video.mp4", "-i", "full_audio.mp3",
        "-vf", "subtitles=subtitles.ass", "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-c:a", "aac", "-b:a", "192k", "-shortest", str(final_output.resolve())
    ]
    run_command(cmd_final, cwd=work_dir)
    
    status_cb("🔍 Contrôle Qualité Final...")
    qc_validate_video(final_output)
    
    return final_output

# ============================================================
# INTERFACE STREAMLIT
# ============================================================

def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="🧠", layout="centered")
    st.title("🧠 Cerveau Curieux — Studio IA Autonome")
    
    # --- LES 3 LIGNES SONT AJOUTÉES ICI ---
    st.info(f"📁 Dossier analysé : {BASE_DIR}")
    fichiers_sfx = [f.name for f in BASE_DIR.iterdir() if f.is_file() and "sfx" in f.name]
    st.info(f"🎵 Fichiers audio vus par le serveur : {fichiers_sfx}")
    # --------------------------------------

    # Alerte si les fichiers audio sont manquants sur le serveur Streamlit

    cleanup_old_temp_dirs()
    topic = st.text_area("Sujet de la vidéo :", placeholder="Ex: L'effet Mandela, pourquoi notre cerveau invente des souvenirs ?")

    if st.button("🚀 Lancer la production automatique", type="primary"):
        if not topic.strip():
            st.error("Veuillez saisir un sujet.")
            return

        status = st.empty()
        progress = st.progress(0)

        try:
            progress.progress(10)
            ai_data = generate_script_gemini(topic, status.info)
            format_choisi = ai_data.get("format_choisi", "short_single")
            
            st.success(f"🎬 Format : **{format_choisi.replace('_', ' ').title()}**")
            st.info(f"**Titre suggéré :** {ai_data.get('title', '')}")
            st.text("Hashtags : " + " ".join(ai_data.get('hashtags', [])))

            if format_choisi == "short_single":
                progress.progress(40)
                video_path = generate_video_pipeline(ai_data.get("script_principal", []), "portrait", status.info)
                st.subheader("📱 Short / TikTok (9:16)")
                st.video(str(video_path))
            elif format_choisi == "short_twoparts":
                progress.progress(40)
                full_video_path = generate_video_pipeline(ai_data.get("script_principal", []), "portrait", status.info)
                status.info("✂️ Découpage de la vidéo en 2...")
                total_duration = get_media_duration(full_video_path)
                part1, part2 = split_video_in_two(full_video_path, total_duration, OUTPUT_DIR)
                col1, col2 = st.columns(2)
                with col1: st.video(str(part1))
                with col2: st.video(str(part2))
            elif format_choisi == "long_plus_teaser":
                progress.progress(30)
                long_path = generate_video_pipeline(ai_data.get("script_principal", []), "landscape", status.info)
                progress.progress(70)
                short_path = generate_video_pipeline(ai_data.get("script_teaser", []), "portrait", status.info)
                st.video(str(long_path))
                st.video(str(short_path))

            progress.progress(100)
            status.success("🎉 Production terminée avec succès !")

        except Exception as e:
            progress.progress(100)
            st.error(f"❌ ÉCHEC : {e}")

if __name__ == "__main__":
    main()
