import os
import time
import json
import re
import shutil
import subprocess
import requests
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont
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

# Recherche dynamique des fichiers sonores
SFX_FILE = next((f for f in BASE_DIR.iterdir() if f.is_file() and "sfx_whoosh" in f.name), BASE_DIR / "sfx_whoosh.mp3")
CLICK_SFX_FILE = next((f for f in BASE_DIR.iterdir() if f.is_file() and "sfx_ding" in f.name), BASE_DIR / "sfx_ding.mp3")

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
# SCHÉMA JSON (PYDANTIC)
# ============================================================

class Scene(BaseModel):
    text: str = Field(description="Texte de la narration. Ton très street, urbain, mais sans aucune insulte.")
    emotion: str = Field(description="Émotion parmi: default, thinking, confused, laughing, explaining, surprised, angry, happy, shocked, sad")
    visual_query: str = Field(description="Mots-clés visuels en ANGLAIS. Action physique concrète.")

class ScriptOutput(BaseModel):
    format_choisi: str = Field(description="Choix parmi: short_single, short_twoparts, long_plus_teaser")
    title: str = Field(description="Titre captivant et très accrocheur (3 à 6 mots max)")
    hashtags: List[str] = Field(description="Liste de 4 à 6 hashtags pertinents")
    script_principal: List[Scene] = Field(description="Scènes de la vidéo (au moins 8 à 10 scènes). La dernière scène est l'appel à l'action.")
    script_teaser: List[Scene] = Field(default=[], description="Scènes du teaser si le format long_plus_teaser est choisi")

# ============================================================
# OUTILS ET EXÉCUTION
# ============================================================

def cleanup_old_temp_dirs(max_age_hours=1):
    now = time.time()
    for item in TEMP_DIR.iterdir():
        if item.is_dir():
            if (now - item.stat().st_mtime) > (max_age_hours * 3600):
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
        raise RuntimeError("QC Échec : Le fichier final n'a pas été généré.")
    cmd_audio = [
        FFPROBE_BIN, "-v", "error", "-select_streams", "a",
        "-show_entries", "stream=codec_type", "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path)
    ]
    res_audio = run_command(cmd_audio)
    if "audio" not in res_audio.stdout.lower():
        raise RuntimeError("QC Échec : La vidéo générée ne contient pas de piste audio.")

# ============================================================
# GENERATION DE MINIATURE (COVER) AUTOMATIQUE
# ============================================================

def generate_thumbnail(title: str, emotion: str, width: int, height: int, output_path: Path):
    """Génère une miniature accrocheuse avec l'identité de la chaîne."""
    img = Image.new("RGB", (width, height), color=(15, 15, 26))
    draw = ImageDraw.Draw(img)

    for y in range(0, height, 10):
        alpha = int(255 * (y / height))
        draw.line([(0, y), (width, y)], fill=(10 + alpha//10, 15 + alpha//8, 35 + alpha//5))

    mascot_path = MASCOT_FILES.get(emotion, MASCOT_FILES["default"])
    if not mascot_path.exists(): mascot_path = MASCOT_FILES["default"]
    
    if mascot_path.exists():
        mascot = Image.open(mascot_path).convert("RGBA")
        m_width = int(width * 0.55)
        m_height = int(mascot.height * (m_width / mascot.width))
        mascot = mascot.resize((m_width, m_height), Image.Resampling.LANCZOS)
        m_pos_x = (width - m_width) // 2
        m_pos_y = height - m_height - int(height * 0.08)
        img.paste(mascot, (m_pos_x, m_pos_y), mascot)

    words = title.upper().split()
    lines = []
    curr_line = []
    for w in words:
        curr_line.append(w)
        if len(" ".join(curr_line)) > 14:
            lines.append(" ".join(curr_line[:-1]))
            curr_line = [w]
    if curr_line:
        lines.append(" ".join(curr_line))

    text_y = int(height * 0.12)
    line_height = int(height * 0.07)
    
    for line in lines[:3]:
        draw.text(((width // 2) + 4, text_y + 4), line, fill=(0, 0, 0), anchor="mm", font_size=int(width * 0.075))
        draw.text((width // 2, text_y), line, fill=(255, 230, 0), anchor="mm", font_size=int(width * 0.075))
        text_y += line_height

    draw.rectangle([(int(width*0.1), height - 120), (int(width*0.9), height - 40)], fill=(220, 20, 60))
    draw.text((width // 2, height - 80), "🧠 CERVEAU CURIEUX", fill=(255, 255, 255), anchor="mm", font_size=int(width * 0.045))

    img.save(output_path)

# ============================================================
# TTS & GEMINI
# ============================================================

def generate_tts(text: str, output_path: Path):
    cmd = ["edge-tts", "--voice", TTS_VOICE, "--text", text, "--write-media", str(output_path)]
    run_command(cmd)

SYSTEM_PROMPT = """Tu es le réalisateur IA de 'Cerveau Curieux'. Ton but est de créer des scripts de vidéos ultra-dynamiques (min 45 secondes).

RÈGLES DE NARRATION (STYLE STREET/URBAIN) :
- Utilise un vocabulaire très jeune, "street" et urbain (ex : "une dinguerie", "frérot", "wesh l'équipe", "carrément", "ça rend ouf", "le cerveau il pète un câble", "bref").
- Le ton doit être ultra-familier, direct et dynamique. Tutoiement obligatoire.
- INTERDICTION STRICTE d'utiliser des insultes ou du vocabulaire vulgaire.
- Explique le sujet avec des exemples très concrets.

RÈGLES DE DÉCOUPAGE :
- DÉCOUPE LE SCRIPT : 1 seule phrase par scène. 
- Une vidéo doit contenir au minimum 8 à 10 scènes.
- Termine la dernière scène par un appel à l'action ("Abonne-toi frérot", "Lâche ton like").

RÈGLES VISUELLES (`visual_query`) :
- Actions physiques et concrètes uniquement (2 à 4 mots en ANGLAIS).
- Pour le dernier appel à l'action : utiliser "thumbs up" ou "like button".
"""

def generate_script_gemini(topic: str, status_cb) -> Dict:
    if not GEMINI_API_KEY: raise RuntimeError("Clé API GEMINI manquante.")
    client = genai.Client(api_key=GEMINI_API_KEY)
    status_cb("🧠 Analyse du sujet et rédaction du script...")

    try:
        response = client.models.generate_content(
            model='gemini-3.6-flash',
            contents=f"Sujet : {topic}",
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=ScriptOutput,
                temperature=0.8,
            ),
        )
        if hasattr(response, 'parsed') and response.parsed:
            return response.parsed.model_dump()
        return json.loads(response.text)
    except Exception as e:
        raise RuntimeError(f"Erreur Gemini Flash : {e}")

# ============================================================
# VISUELS & SOUS-TITRES
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

def create_ass_subtitles(scenes: List[Dict], output_ass: Path, width: int, height: int):
    font_size = 56 if width == 1080 else 38
    margin_v = 300 if height == 1920 else 70
    
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
                        formatted_words.append(f"{{\\c&H00FFFF&}}{w}{{\\c&HFFFFFF&}}")
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
# PIPELINE GLOBAL
# ============================================================

def generate_video_pipeline(script_scenes: List[Dict], video_format: str, status_cb) -> Path:
    if not script_scenes: raise ValueError("Le script est vide.")

    work_dir = TEMP_DIR / f"run_{int(time.time())}_{video_format}"
    work_dir.mkdir(parents=True, exist_ok=True)
    width, height = (1080, 1920) if video_format == "portrait" else (1920, 1080)
    orientation = "portrait" if video_format == "portrait" else "landscape"

    status_cb("🎙️ Génération de la voix off et mixage audio...")
    audio_clips = []
    total_scenes = len(script_scenes)

    for idx, scene in enumerate(script_scenes):
        temp_audio = work_dir / f"temp_audio_{idx:03d}.mp3"
        final_audio = work_dir / f"audio_{idx:03d}.mp3"
        
        generate_tts(scene["text"], temp_audio)
        
        is_last_scene = (idx == total_scenes - 1)
        sfx_to_use = CLICK_SFX_FILE if (is_last_scene and CLICK_SFX_FILE.exists()) else (SFX_FILE if (idx > 0 and SFX_FILE.exists()) else None)

        if sfx_to_use:
            cmd_mix = [
                FFMPEG_BIN, "-y", "-i", str(temp_audio), "-i", str(sfx_to_use),
                "-filter_complex", "[1:a]volume=0.15[sfx];[0:a][sfx]amix=inputs=2:duration=first[mix];[mix]volume=2.0[a]",
                "-map", "[a]", str(final_audio)
            ]
            run_command(cmd_mix, cwd=work_dir)
        else:
            shutil.copy(temp_audio, final_audio)

        scene["duration"] = get_media_duration(final_audio)
        audio_clips.append(final_audio)

    with open(work_dir / "concat_audio.txt", "w") as f:
        for a in audio_clips: f.write(f"file '{a.name}'\n")
    run_command([FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0", "-i", "concat_audio.txt", "-c", "copy", "full_audio.mp3"], cwd=work_dir)

    status_cb("🎥 Montage visuel et incrustation de la marque...")
    video_clips = []
    fps = 25
    mascot_scale = int(width * 0.22) if video_format == "portrait" else int(width * 0.15)
    pos_x = "(W-w)/2" if video_format == "portrait" else "40"
    pos_y = "H-h-450" if video_format == "portrait" else "H-h-40"

    for idx, scene in enumerate(script_scenes):
        duration = scene["duration"]
        emotion = scene.get("emotion", "default")
        mascot_img = MASCOT_FILES.get(emotion, MASCOT_FILES["default"])
        if not mascot_img.exists(): mascot_img = MASCOT_FILES["default"]

        url = search_pexels_video(scene.get("visual_query", "brain science"), orientation)
        visual_file = work_dir / f"src_vis_{idx:03d}.mp4"
        output_clip = work_dir / f"clip_{idx:03d}.mp4"
        
        display_duration = min(4.0, duration) 
        enable_expr = f"between(t,0,{display_duration})"
        flash_effect = ",colorchannelmixer=rr=1.8:gg=1.8:bb=1.8:enable='between(t,0,0.15)'" if idx > 0 else ""

        if url and download_file(url, visual_file):
            base_filter = f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}{flash_effect}[bg]"
            cmd = [FFMPEG_BIN, "-y", "-stream_loop", "-1", "-i", visual_file.name, "-i", str(mascot_img.resolve())]
        else:
            fallback = work_dir / f"fallback_{idx:03d}.png"
            Image.new("RGB", (width, height), color=(20, 20, 35)).save(fallback)
            frames = int(duration * fps)
            base_filter = f"[0:v]zoompan=z='min(zoom+0.0015,1.3)':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)',scale={width}:{height}{flash_effect}[bg]"
            cmd = [FFMPEG_BIN, "-y", "-loop", "1", "-i", fallback.name, "-i", str(mascot_img.resolve())]

        filter_complex = f"{base_filter};[1:v]scale={mascot_scale}:-1[mascot];[bg][mascot]overlay=x={pos_x}:y={pos_y}:enable='{enable_expr}'[v_out]"
        cmd.extend(["-t", str(duration), "-filter_complex", filter_complex, "-map", "[v_out]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps), output_clip.name])
        run_command(cmd, cwd=work_dir)
        video_clips.append(output_clip)

    with open(work_dir / "concat_video.txt", "w") as f:
        for v in video_clips: f.write(f"file '{v.name}'\n")
    run_command([FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0", "-i", "concat_video.txt", "-c", "copy", "raw_video.mp4"], cwd=work_dir)

    status_cb("⚙️ Incrustation des sous-titres, du Watermark et normalisation...")
    create_ass_subtitles(script_scenes, work_dir / "subtitles.ass", width, height)

    watermark_x = 40
    watermark_y = 60 if video_format == "portrait" else 40
    
    vf_filter = (
        f"subtitles=subtitles.ass,"
        f"drawtext=text='🧠 CERVEAU CURIEUX':x={watermark_x}:y={watermark_y}:"
        f"fontsize=26:fontcolor=white:box=1:boxcolor=black@0.5:boxborderw=8"
    )

    final_output = OUTPUT_DIR / f"export_{int(time.time())}_{video_format}.mp4"
    cmd_final = [
        FFMPEG_BIN, "-y", "-i", "raw_video.mp4", "-i", "full_audio.mp3",
        "-vf", vf_filter,
        "-af", "loudnorm=I=-14:LRA=11:TP=-1.5",
        "-map", "0:v", "-map", "1:a",
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

    cleanup_old_temp_dirs()
    
    topic = st.text_area("Sujet de la vidéo :", placeholder="Ex: Pourquoi notre cerveau invente des souvenirs ?")
    
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
            title = ai_data.get("title", "Cerveau Curieux")
            
            st.success(f"🎬 Format sélectionné : **{format_choisi.replace('_', ' ').title()}**")
            st.info(f"**Titre de la vidéo :** {title}")
            st.text("Hashtags recommandés : " + " ".join(ai_data.get('hashtags', [])))

            # Génération de la miniature
            first_scene_emotion = ai_data.get("script_principal", [{}])[0].get("emotion", "default")
            thumb_w, thumb_h = (1080, 1920) if "short" in format_choisi else (1920, 1080)
            thumb_path = OUTPUT_DIR / f"thumb_{int(time.time())}.png"
            generate_thumbnail(title, first_scene_emotion, thumb_w, thumb_h, thumb_path)

            if format_choisi == "short_single":
                progress.progress(40)
                video_path = generate_video_pipeline(ai_data.get("script_principal", []), "portrait", status.info)
                
                st.subheader("📱 Vidéo Finale (9:16)")
                st.video(str(video_path))
                
                st.subheader("🖼️ Miniature générée")
                st.image(str(thumb_path), width=300)

            elif format_choisi == "short_twoparts":
                progress.progress(40)
                full_video_path = generate_video_pipeline(ai_data.get("script_principal", []), "portrait", status.info)
                status.info("✂️ Découpage de la vidéo en 2 parties...")
                total_duration = get_media_duration(full_video_path)
                part1, part2 = split_video_in_two(full_video_path, total_duration, OUTPUT_DIR)
                
                col1, col2 = st.columns(2)
                with col1:
                    st.subheader("Partie 1")
                    st.video(str(part1))
                with col2:
                    st.subheader("Partie 2")
                    st.video(str(part2))
                
                st.subheader("🖼️ Miniature générée")
                st.image(str(thumb_path), width=300)

            elif format_choisi == "long_plus_teaser":
                progress.progress(30)
                long_path = generate_video_pipeline(ai_data.get("script_principal", []), "landscape", status.info)
                progress.progress(70)
                short_path = generate_video_pipeline(ai_data.get("script_teaser", []), "portrait", status.info)
                
                st.subheader("📺 Vidéo Longue (16:9)")
                st.video(str(long_path))
                
                st.subheader("📱 Teaser Short (9:16)")
                st.video(str(short_path))
                
                st.subheader("🖼️ Miniature générée")
                st.image(str(thumb_path), width=500)

            progress.progress(100)
            status.success("🎉 Production terminée ! Tout est prêt pour la publication.")

        except Exception as e:
            progress.progress(100)
            st.error(f"❌ ÉCHEC DE PRODUCTION : {e}")

if __name__ == "__main__":
    main()
