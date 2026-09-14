import os
import time
import json
import re
import shutil
import subprocess
import requests
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from PIL import Image, ImageDraw
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

# Crée une mascotte de secours si le fichier par défaut n'existe pas
if not MASCOT_FILES["default"].exists():
    Image.new('RGBA', (200, 200), color=(0, 0, 0, 0)).save(MASCOT_FILES["default"])

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
    script_principal: List[Scene] = Field(description="Scènes de la vidéo (au moins 12 à 15 scènes pour rythme rapide). La dernière scène est l'appel à l'action.")
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
# TTS & GEMINI
# ============================================================

def generate_tts(text: str, output_path: Path):
    cmd = ["edge-tts", "--voice", TTS_VOICE, "--text", text, "--write-media", str(output_path)]
    run_command(cmd)

# 🚀 NOUVEAU PROMPT DE RÉTENTION
SYSTEM_PROMPT = """Tu es le réalisateur IA de 'Cerveau Curieux'. Ton but est de créer des scripts de vidéos ultra-dynamiques (min 45 secondes).

RÈGLES DE NARRATION (STYLE STREET/URBAIN) :
- Utilise un vocabulaire très jeune, "street" et urbain (ex : "une dinguerie", "frérot", "wesh l'équipe", "carrément", "ça rend ouf", "le cerveau il pète un câble", "bref").
- Le ton doit être ultra-familier, direct et dynamique. Tutoiement obligatoire.
- INTERDICTION STRICTE d'utiliser des insultes ou du vocabulaire vulgaire.
- Explique le sujet avec des exemples très concrets.

RÈGLES DE DÉCOUPAGE (TRÈS IMPORTANT) :
- DÉCOUPE LE SCRIPT : 1 seule phrase TRÈS COURTE par scène (maximum 3 secondes de lecture par scène). 
- Une vidéo doit contenir au minimum 12 à 15 scènes pour un rythme frénétique.
- Termine la dernière scène par un appel à l'action hyper positif ("Abonne-toi frérot", "Lâche ton like").

RÈGLES VISUELLES (`visual_query`) :
- Actions physiques et concrètes uniquement (2 à 4 mots en ANGLAIS).
- POUR LA DERNIÈRE SCÈNE (CTA) : Le visuel DOIT OBLIGATOIREMENT être ultra-positif (ex: "smiling person thumbs up", "happy cheering"). JAMAIS de geste négatif.
"""

def generate_script_gemini(topic: str, api_key: str, status_cb) -> Dict:
    if not api_key: raise RuntimeError("Clé API GEMINI manquante.")
    client = genai.Client(api_key=api_key)
    status_cb("🧠 Analyse du sujet et rédaction du script en cours...")

    try:
        response = client.models.generate_content(
            model='gemini-1.5-flash',
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

        # 🚀 MODIFICATION 2 : COUPURE AUDIO (SILENCEREMOVE) INTÉGRÉE ICI
        if sfx_to_use:
            cmd_mix = [
                FFMPEG_BIN, "-y", "-i", str(temp_audio), "-i", str(sfx_to_use),
                "-filter_complex", "[0:a]silenceremove=stop_periods=1:stop_duration=0:stop_threshold=-35dB[voice];[1:a]volume=0.15[sfx];[voice][sfx]amix=inputs=2:duration=first[mix];[mix]volume=2.0[a]",
                "-map", "[a]", str(final_audio)
            ]
            run_command(cmd_mix, cwd=work_dir)
        else:
            cmd_trim = [
                FFMPEG_BIN, "-y", "-i", str(temp_audio),
                "-af", "silenceremove=stop_periods=1:stop_duration=0:stop_threshold=-35dB",
                str(final_audio)
            ]
            run_command(cmd_trim, cwd=work_dir)

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
            # 🚀 MODIFICATION 3 : ZOOM ACCÉLÉRÉ (0.0025)
            base_filter = f"[0:v]zoompan=z='min(zoom+0.0025,1.3)':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)',scale={width}:{height}{flash_effect}[bg]"
            cmd = [FFMPEG_BIN, "-y", "-loop", "1", "-i", fallback.name, "-i", str(mascot_img.resolve())]

        filter_complex = f"{base_filter};[1:v]scale={mascot_scale}:-1[mascot];[bg][mascot]overlay=x={pos_x}:y={pos_y}:enable='{enable_expr}'[v_out]"
        cmd.extend(["-t", str(duration), "-filter_complex", filter_complex, "-map", "[v_out]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps), output_clip.name])
        run_command(cmd, cwd=work_dir)
        video_clips.append(output_clip)

    with open(work_dir / "concat_video.txt", "w") as f:
        for v in video_clips: f.write(f"file '{v.name}'\n")
    run_command([FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0", "-i", "concat_video.txt", "-c", "copy", "raw_video.mp4"], cwd=work_dir)

    status_cb("⚙️ Incrustation des sous-titres, du Watermark et finalisation audio...")
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
# INTERFACE STREAMLIT (EMBELLIE)
# ============================================================

def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="🧠", layout="centered", initial_sidebar_state="expanded")
    
    st.markdown("""
        <style>
        .stApp { background-color: #0E1117; }
        div.stButton > button:first-child {
            background: linear-gradient(90deg, #FF4B4B 0%, #FF8F8F 100%);
            color: white;
            border: none;
            border-radius: 12px;
            padding: 0.6rem 1rem;
            font-size: 1.2rem;
            font-weight: 700;
            width: 100%;
            transition: all 0.3s ease;
            box-shadow: 0 4px 6px rgba(255, 75, 75, 0.2);
        }
        div.stButton > button:first-child:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 15px rgba(255, 75, 75, 0.4);
            color: white;
        }
        .main-title { text-align: center; font-size: 3rem; font-weight: 800; margin-bottom: 0px; color: #FFFFFF; }
        .sub-title { text-align: center; font-size: 1.2rem; color: #A0AEC0; margin-top: 0px; margin-bottom: 30px; }
        .stTextArea textarea {
            background-color: #1A1C24;
            border: 1px solid #2D3748;
            border-radius: 10px;
            color: #E2E8F0;
            font-size: 1.1rem;
        }
        .stTextArea textarea:focus { border-color: #FF4B4B; box-shadow: 0 0 0 1px #FF4B4B; }
        </style>
    """, unsafe_allow_html=True)

    with st.sidebar:
        st.markdown("<h3 style='text-align: center;'>Tableau de bord</h3>", unsafe_allow_html=True)
        if MASCOT_FILES["default"].exists():
            st.image(str(MASCOT_FILES["default"]), use_container_width=True)
        
        st.markdown("---")
        st.markdown("🎯 **Mode Autonome Actif**")
        st.write("L'IA détecte le format idéal selon la longueur et la complexité de ton sujet.")

    st.markdown('<div class="main-title">🧠 Cerveau Curieux</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-title">Studio IA Autonome 🎬</div>', unsafe_allow_html=True)

    cleanup_old_temp_dirs()
    
    # Sécurisation de la clé d'API directement dans l'interface
    api_key = st.text_input("Clé API Google Gemini :", type="password")
    
    st.markdown("### 📝 Quel est ton sujet aujourd'hui ?")
    topic = st.text_area("Sujet", placeholder="Ex: L'effet Mandela...", label_visibility="collapsed", height=120)
    
    if st.button("🚀 LANCER LA MAGIE"):
        if not api_key:
            st.warning("⚠️ Merci d'insérer ta clé API Gemini.")
            return
        if not topic.strip():
            st.warning("⚠️ Oups ! Tu as oublié d'écrire un sujet.")
            return

        with st.status("🎬 Allumage des caméras virtuelles...", expanded=True) as status_box:
            try:
                def update_status(msg):
                    st.write(msg)
                
                ai_data = generate_script_gemini(topic, api_key, update_status)
                format_choisi = ai_data.get("format_choisi", "short_single")
                title = ai_data.get("title", "Cerveau Curieux")
                
                st.write(f"✅ Format défini : **{format_choisi.replace('_', ' ').title()}**")
                
                if format_choisi == "short_single":
                    video_path = generate_video_pipeline(ai_data.get("script_principal", []), "portrait", update_status)
                    
                elif format_choisi == "short_twoparts":
                    full_video_path = generate_video_pipeline(ai_data.get("script_principal", []), "portrait", update_status)
                    update_status("✂️ Découpage de la vidéo en 2 parties...")
                    total_duration = get_media_duration(full_video_path)
                    part1, part2 = split_video_in_two(full_video_path, total_duration, OUTPUT_DIR)
                    video_path = [part1, part2]
                    
                elif format_choisi == "long_plus_teaser":
                    long_path = generate_video_pipeline(ai_data.get("script_principal", []), "landscape", update_status)
                    short_path = generate_video_pipeline(ai_data.get("script_teaser", []), "portrait", update_status)
                    video_path = [long_path, short_path]
                
                status_box.update(label="🎉 Production terminée avec succès !", state="complete", expanded=False)

            except Exception as e:
                status_box.update(label="❌ Oups, une erreur s'est produite.", state="error", expanded=True)
                st.error(str(e))
                return

        st.markdown("---")
        st.markdown("## 🍿 Ton contenu est prêt ! ")
        
        info_tab, video_tab = st.tabs(["📄 Informations", "🎥 Vidéo(s)"])
        
        with info_tab:
            st.info(f"**Titre suggéré :** {title}")
            st.write(f"**Hashtags :** " + " ".join(ai_data.get('hashtags', [])))
            st.write("*(Copie ces éléments pour ta description TikTok/YouTube)*")
            
            st.markdown("---")
            # 🚀 MODIFICATION 4 : LE MENU DÉROULANT POUR COPIER LE SCRIPT (POUR CLAUDE)
            with st.expander("📜 Voir le script complet (pour l'audit de Claude)"):
                script_complet = ""
                for idx, scene in enumerate(ai_data.get("script_principal", [])):
                    script_complet += f"**Scène {idx + 1}** : {scene.get('text', '')}\n\n"
                st.code(script_complet, language="markdown")
            
        with video_tab:
            if format_choisi == "short_single":
                st.video(str(video_path))
            elif format_choisi == "short_twoparts":
                col1, col2 = st.columns(2)
                with col1:
                    st.caption("Partie 1")
                    st.video(str(video_path[0]))
                with col2:
                    st.caption("Partie 2")
                    st.video(str(video_path[1]))
            elif format_choisi == "long_plus_teaser":
                st.subheader("📺 Format Long (16:9)")
                st.video(str(video_path[0]))
                st.divider()
                st.subheader("📱 Teaser Short (9:16)")
                st.video(str(video_path[1]))
                
        st.balloons()

if __name__ == "__main__":
    main()
