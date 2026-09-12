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
BASE_DIR = Path(__file__).resolve().parent
TEMP_DIR = BASE_DIR / "temp"
OUTPUT_DIR = BASE_DIR / "output"

TEMP_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

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
# STRUCTURE D'OUTPUT JSON STRICTE (PYDANTIC)
# ============================================================

class Scene(BaseModel):
    text: str = Field(description="Texte de la narration pour la scène")
    emotion: str = Field(description="Émotion parmi: default, thinking, confused, laughing, explaining, surprised")
    visual_query: str = Field(description="Mots-clés visuels en ANGLAIS, ultra-concrets et physiques pour Pexels (ex: person walking through doorway, confused man indoor)")

class ScriptOutput(BaseModel):
    format_choisi: str = Field(description="Choix parmi: short_single, short_twoparts, long_plus_teaser")
    title: str = Field(description="Titre captivant, accrocheur et honnête pour la vidéo")
    hashtags: List[str] = Field(description="Liste de 4 à 6 hashtags pertinents pour les réseaux sociaux (ex: #psychologie #cerveau)")
    script_principal: List[Scene] = Field(description="Scènes de la vidéo principale")
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
        raise RuntimeError("QC Échec: Le fichier MP4 final est muet (aucune piste audio trouvée).")

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

SYSTEM_PROMPT = """Tu es le réalisateur IA de 'Cerveau Curieux'. 
Analyse le sujet demandé par l'utilisateur et CHOISIS LE FORMAT IDÉAL en fonction de sa complexité.

CHOIX DE FORMATS POSSIBLES (Choisis-en UN SEUL) :
1. "short_single" : Sujet simple. Script de 120 à 150 mots (pour 45s à 60s).
2. "short_twoparts" : Sujet dense. Script d'environ 250 mots (pour ~1m40s). Le système le coupera ensuite en 2.
3. "long_plus_teaser" : Sujet complexe. Script principal TRES LONG (>450 mots pour >2m50s) ET un script teaser de ~70 mots.

RÈGLES CRITIQUES POUR LES REQUÊTES VISUELLES (`visual_query`) :
- Le `visual_query` DOIT être en ANGLAIS, ultra-concret et littéral pour une recherche Pexels (banque de vidéos).
- INTERDIT d'utiliser des termes abstraits ou psychologiques (ex: "event boundary", "memory purge", "brain processing").
- Utilise des actions visuelles réelles et des décors physiques (ex: au lieu de "event boundary", écris "person walking through doorway indoor"; au lieu de "memory working", écris "person looking around confused").
- 2 à 4 mots max par requête.

Génère également un titre accrocheur, honnête (sans mensonge ni exagération trompeuse) et une liste de 4 à 6 hashtags pertinents.
"""

def generate_script_gemini(topic: str, status_cb) -> Dict:
    if not GEMINI_API_KEY:
        raise RuntimeError("Clé API GEMINI_API_KEY manquante. Veuillez la configurer.")

    client = genai.Client(api_key=GEMINI_API_KEY)
    status_cb("🧠 Analyse du sujet et rédaction du script via Gemini 3.6 Flash...")

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
        raise RuntimeError(f"Erreur lors de la génération avec Gemini Flash : {e}")

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
# SOUS-TITRES DYNAMIQUES (CHUNKS TIKTOK STYLE)
# ============================================================

def create_ass_subtitles(scenes: List[Dict], output_ass: Path, width: int, height: int):
    font_size = 52 if width == 1080 else 38
    margin_v = 200 if height == 1920 else 70
    
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{font_size},&H0000FFFF,&H00000000,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,20,20,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    current_time = 0.0
    for scene in scenes:
        scene_duration = scene["duration"]
        text = scene["text"].replace("\n", " ").replace('"', '')
        
        # Découpage intelligent par petits morceaux (4 à 6 mots) pour un affichage dynamique type TikTok
        words = text.split()
        if not words:
            current_time += scene_duration
            continue
            
        chunks = []
        chunk_size = 5
        for i in range(0, len(words), chunk_size):
            chunks.append(" ".join(words[i:i+chunk_size]))
            
        chunk_duration = scene_duration / len(chunks)
        
        for idx, chunk in enumerate(chunks):
            start_t = current_time + (idx * chunk_duration)
            end_t = start_t + chunk_duration
            
            start_str = time.strftime('%H:%M:%S', time.gmtime(start_t)) + f".{int((start_t % 1)*100):02d}"
            end_str = time.strftime('%H:%M:%S', time.gmtime(end_t)) + f".{int((end_t % 1)*100):02d}"
            
            lines.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{chunk}")
            
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
    if not script_scenes:
        raise ValueError(f"Le script pour le format '{video_format}' est vide.")

    work_dir = TEMP_DIR / f"run_{int(time.time())}_{video_format}"
    work_dir.mkdir(parents=True, exist_ok=True)
    
    width, height = (1080, 1920) if video_format == "portrait" else (1920, 1080)
    orientation = "portrait" if video_format == "portrait" else "landscape"

    # 1. AUDIO TTS
    status_cb("🎙️ Génération de la voix off (Edge-TTS)...")
    audio_clips = []
    total_duration = 0.0
    for idx, scene in enumerate(script_scenes):
        audio_file = work_dir / f"audio_{idx:03d}.mp3"
        generate_tts(scene["text"], audio_file)
        dur = get_media_duration(audio_file)
        scene["duration"] = dur
        total_duration += dur
        audio_clips.append(audio_file)

    with open(work_dir / "concat_audio.txt", "w") as f:
        for a in audio_clips: f.write(f"file '{a.name}'\n")
    run_command([FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0", "-i", "concat_audio.txt", "-c", "copy", "full_audio.mp3"], cwd=work_dir)

    # 2. VISUELS & MASCOTTE SCÈNE PAR SCÈNE
    status_cb("🎥 Assemblage des visuels et intégration dynamique de la mascotte...")
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

        url = search_pexels_video(scene.get("visual_query", "person walking"), orientation)
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

    # 3. SOUS-TITRES & MIXAGE FINAL
    status_cb("⚙️ Incrustation des sous-titres dynamiques et mixage final...")
    create_ass_subtitles(script_scenes, work_dir / "subtitles.ass", width, height)

    final_output = OUTPUT_DIR / f"export_{int(time.time())}_{video_format}.mp4"
    cmd_final = [
        FFMPEG_BIN, "-y", "-i", "raw_video.mp4", "-i", "full_audio.mp3",
        "-vf", "subtitles=subtitles.ass", "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-c:a", "aac", "-b:a", "192k", "-shortest", str(final_output.resolve())
    ]
    run_command(cmd_final, cwd=work_dir)
    
    # 4. QUALITÉ
    status_cb("🔍 Contrôle Qualité Final...")
    qc_validate_video(final_output)
    
    return final_output

# ============================================================
# INTERFACE STREAMLIT
# ============================================================

def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="🧠", layout="centered")
    st.title("🧠 Cerveau Curieux — Studio IA Autonome")
    st.markdown("Propulsé par **Google Gemini Flash** (SDK Officiel - 100% Gratuit, Structuré & Ultra Stable)")

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
            
            # 1. Génération Intelligente via Gemini
            ai_data = generate_script_gemini(topic, status.info)
            format_choisi = ai_data.get("format_choisi", "short_single")
            
            st.success(f"🎬 Format automatiquement sélectionné : **{format_choisi.replace('_', ' ').title()}**")

            # Affichage du titre et des hashtags générés
            st.markdown("### 📌 Métadonnées pour Publication")
            st.info(f"**Titre suggéré :** {ai_data.get('title', '')}")
            st.text("Hashtags : " + " ".join(ai_data.get('hashtags', [])))

            # 2. Routage vers le bon pipeline selon le format
            if format_choisi == "short_single":
                progress.progress(40)
                video_path = generate_video_pipeline(ai_data.get("script_principal", []), "portrait", status.info)
                st.subheader("📱 Short / TikTok (9:16)")
                st.video(str(video_path))

            elif format_choisi == "short_twoparts":
                progress.progress(40)
                full_video_path = generate_video_pipeline(ai_data.get("script_principal", []), "portrait", status.info)
                
                status.info("✂️ Découpage de la vidéo en 2 parties égales...")
                total_duration = get_media_duration(full_video_path)
                part1, part2 = split_video_in_two(full_video_path, total_duration, OUTPUT_DIR)
                
                col1, col2 = st.columns(2)
                with col1:
                    st.subheader("Partie 1")
                    st.video(str(part1))
                with col2:
                    st.subheader("Partie 2")
                    st.video(str(part2))

            elif format_choisi == "long_plus_teaser":
                progress.progress(30)
                long_path = generate_video_pipeline(ai_data.get("script_principal", []), "landscape", status.info)
                
                progress.progress(70)
                short_path = generate_video_pipeline(ai_data.get("script_teaser", []), "portrait", status.info)
                
                st.subheader("💻 Vidéo Longue (YouTube 16:9)")
                st.video(str(long_path))
                st.subheader("📱 Teaser (TikTok / Shorts 9:16)")
                st.video(str(short_path))
            else:
                raise ValueError(f"Format non reconnu : {format_choisi}")

            progress.progress(100)
            status.success("🎉 Production terminée avec succès !")

        except Exception as e:
            progress.progress(100)
            st.error(f"❌ ÉCHEC : {e}")

if __name__ == "__main__":
    main()
