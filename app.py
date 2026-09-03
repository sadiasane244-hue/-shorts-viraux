import os
import sys
import json
import random
import re
import subprocess
import tempfile
import asyncio
import urllib.parse
import concurrent.futures
import requests
from PIL import Image
import streamlit as st

# ---------------------------------------------------------
# CONFIGURATION STREAMLIT & VARIABLES
# ---------------------------------------------------------
st.set_page_config(
    page_title="Générateur Vidéo IA",
    page_icon="🎬",
    layout="centered"
)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "meta-llama/llama-3.3-70b-instruct"

# ---------------------------------------------------------
# GENERATION DE SCRIPTS (SHORT TEASER & VIDÉO LONGUE)
# ---------------------------------------------------------
def generate_pack_scripts(subject=None):
    if not OPENROUTER_API_KEY:
        return None, None, "❌ Clé OpenRouter manquante."

    topics = [
        "pourquoi ton cerveau te fait procrastiner au pire moment",
        "l'astuce psychologique pour savoir si quelqu'un te ment",
        "pourquoi tu te rappelles d'un détail inutile d'il y a 5 ans mais pas de tes clés",
        "ce qui arrive dans ton cerveau quand tu scrolles sur ton téléphone",
        "le phénomène bizarre qui te fait oublier pourquoi tu es entré dans une pièce"
    ]

    if not subject:
        subject = random.choice(topics)

    # 1. Script Vidéo Longue
    long_system_prompt = """Tu es un vulgarisateur scientifique pour des vidéos longues YouTube (16:9).
Tu écris des scripts structurés, captivants, pédagogiques et amusants (durée 2 à 3 minutes).

STYLE ET TON:
- Professionnel mais accessible, engageant avec tutoiement direct.
- Explications claires, exemples concrets de la vie quotidienne.
- ZÉRO vulgarité, zéro mention de "Mère Nature" ou théorie de l'évolution.

FORMAT STRICT (Inclus pour chaque section une balise [IMAGE: description visuelle en anglais]) :
TITRE: [Titre accrocheur YouTube]
INTRO: [Introduction captivante] [IMAGE: detailed concept visual in English]
PARTIE 1: [Titre et explications premier concept] [IMAGE: detailed concept visual in English]
PARTIE 2: [Titre et explications deuxième concept] [IMAGE: detailed concept visual in English]
PARTIE 3: [Titre et explications troisième concept] [IMAGE: detailed concept visual in English]
CONCLUSION: [Résumé rapide] [IMAGE: detailed concept visual in English]
CTA: [Invitation à s'abonner] [IMAGE: YouTube subscribe visual background in English]
HASHTAGS: [5 hashtags YouTube]"""

    # 2. Script Short Teaser
    teaser_system_prompt = f"""Tu es un créateur de contenu viral TikTok / YouTube Shorts (9:16).
Ton but est de créer un SHORT TEASER hyper dynamique (20-30 secondes) pour donner ENVIE de regarder la vidéo longue complète sur : "{subject}".

STYLE ET TON:
- Très court, intrigant, mystérieux et percutant.
- Tu révèles juste assez d'informations pour susciter la curiosité, sans tout dévoiler.
- LE CTA DOIT EXPLICITEMENT DIRE DE RENTER SUR LA CHAÎNE POUR VOIR LA VIDÉO COMPLÈTE.

FORMAT STRICT (Inclus des balises [IMAGE: ...] et [MEME: ...]) :
TITRE: [Titre court du teaser]
HOOK: [Accroche mystérieuse et choc] [IMAGE: mysterious psychology brain concept visual in English]
TEASER: [Extrait captivant ou question intrigante] [MEME: shocked reaction meme visual in English]
CTA: [Découvre la suite et l'explication complète dans la vidéo longue sur la chaîne !] [IMAGE: click full video CTA visual in English]
HASHTAGS: [5 hashtags viraux]"""

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://shorts-viraux.render.com",
        "X-Title": "Video Generator"
    }

    try:
        # Requête pour la vidéo longue
        p_long = {"model": OPENROUTER_MODEL, "messages": [{"role": "system", "content": long_system_prompt}, {"role": "user", "content": f"Script long sur : {subject}"}], "temperature": 0.85, "max_tokens": 1500}
        r_long = requests.post(OPENROUTER_URL, headers=headers, json=p_long, timeout=40)
        script_long = r_long.json()['choices'][0]['message']['content'] if r_long.status_code == 200 else None

        # Requête pour le teaser
        p_teaser = {"model": OPENROUTER_MODEL, "messages": [{"role": "system", "content": teaser_system_prompt}, {"role": "user", "content": f"Teaser court sur : {subject}"}], "temperature": 0.85, "max_tokens": 600}
        r_teaser = requests.post(OPENROUTER_URL, headers=headers, json=p_teaser, timeout=40)
        script_teaser = r_teaser.json()['choices'][0]['message']['content'] if r_teaser.status_code == 200 else None

        if script_long and script_teaser:
            return script_long, script_teaser, None
        return None, None, "❌ Erreur lors de la génération des scripts."

    except Exception as e:
        return None, None, f"❌ Erreur connexion: {str(e)}"

# ---------------------------------------------------------
# NETTOYAGE DU SCRIPT ET EXTRACTION DES PROMPTS VISUELS
# ---------------------------------------------------------
def parse_script(script_text):
    clean_lines = []
    visual_prompts = []
    
    for line in script_text.splitlines():
        line = line.strip()
        if not line:
            continue
            
        visual_matches = re.findall(r'\[(?:IMAGE|MEME|MÈME|Meme|Mème)\s*:\s*(.*?)\]', line, re.IGNORECASE)
        for v in visual_matches:
            if v.strip():
                visual_prompts.append(v.strip())

        if re.match(r'^(TITRE|HASHTAGS|HASHTAG)\s*:', line, re.IGNORECASE):
            continue

        cleaned = re.sub(r'\[.*?\]', '', line)
        cleaned = re.sub(r'^(HOOK|INTRO|PARTIE\s*\d+|FAIT\s*\d+|MEME\s*\d+|TEASER|CONCLUSION|CTA)\s*:\s*', '', cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.replace('*', '').strip()

        if cleaned:
            clean_lines.append(cleaned)

    narration_text = " ".join(clean_lines)
    return narration_text, visual_prompts

# ---------------------------------------------------------
# GENERATION DES IMAGES ET MÈMES PAR IA (Pollinations.ai)
# ---------------------------------------------------------
def fetch_single_image(prompt, idx, temp_dir, is_short=True):
    width, height = (1080, 1920) if is_short else (1920, 1080)
    img_path = os.path.join(temp_dir, f"scene_{idx}.jpg")
    
    encoded_prompt = urllib.parse.quote(f"{prompt}, high quality, 8k, cinematic lighting")
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width={width}&height={height}&nologo=true"
    
    try:
        resp = requests.get(url, timeout=20)
        if resp.status_code == 200 and len(resp.content) > 1000:
            with open(img_path, "wb") as f:
                f.write(resp.content)
            return img_path
    except Exception:
        pass
        
    # Correction du tuple de couleur pour éviter le crash TypeError
    fallback_color = (20, 30, 50) if idx % 2 == 0 else (40, 20, 60)
    img = Image.new('RGB', (width, height), color=fallback_color)
    img.save(img_path)
    return img_path

def fetch_all_images(prompts, temp_dir, is_short=True):
    if not prompts:
        prompts = [
            "human brain thinking psychology cinematic",
            "funny reaction meme shocked face",
            "nervous system stress illustration",
            "brain wave memory concept cinematic"
        ]
        
    images = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [
            executor.submit(fetch_single_image, p, i, temp_dir, is_short)
            for i, p in enumerate(prompts)
        ]
        for future in futures:
            images.append(future.result())
    return images

# ---------------------------------------------------------
# GENERATION AUDIO (Edge-TTS)
# ---------------------------------------------------------
async def generate_audio_async(text, output_mp3):
    import edge_tts
    voice = "fr-FR-HenriNeural"
    communicate = edge_tts.Communicate(text, voice, rate="+5%")
    await communicate.save(output_mp3)

def generate_audio(text, output_mp3="narration.mp3"):
    try:
        asyncio.run(generate_audio_async(text, output_mp3))
        if os.path.exists(output_mp3):
            return output_mp3, None
        return None, "❌ Erreur génération fichier audio."
    except Exception as e:
        return None, f"❌ Erreur Edge-TTS: {str(e)}"

def get_audio_duration(audio_path):
    try:
        cmd = [
            'ffprobe', '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprintwrappers=1:nokey=1',
            audio_path
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        return float(res.stdout.strip())
    except Exception:
        return 30.0

# ---------------------------------------------------------
# SOUS-TITRES ASS
# ---------------------------------------------------------
def generate_ass_subtitles(text, output_ass="subtitles.ass", is_short=True):
    res_x = 1080 if is_short else 1920
    res_y = 1920 if is_short else 1080
    font_size = 65 if is_short else 48
    margin_v = 900 if is_short else 120

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {res_x}
PlayResY: {res_y}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,0,2,50,50,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    words = text.split()
    chunk_size = 3 if is_short else 6
    current_time = 0.0
    word_duration = 0.35

    with open(output_ass, "w", encoding="utf-8") as f:
        f.write(header)
        for i in range(0, len(words), chunk_size):
            chunk = " ".join(words[i:i+chunk_size])
            start_sec = current_time
            end_sec = start_sec + (len(words[i:i+chunk_size]) * word_duration)
            
            def format_time(s):
                hrs = int(s // 3600)
                mins = int((s % 3600) // 60)
                secs = int(s % 60)
                cs = int((s - int(s)) * 100)
                return f"{hrs}:{mins:02d}:{secs:02d}.{cs:02d}"

            start_str = format_time(start_sec)
            end_str = format_time(end_sec)
            f.write(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{chunk}\n")
            current_time = end_sec

    return output_ass

# ---------------------------------------------------------
# ASSEMBLAGE VIDÉO FFMPEG DIRECT
# ---------------------------------------------------------
def create_video_ffmpeg(images, audio_path, ass_subtitles_path, output_path="video_output.mp4", is_short=True):
    try:
        temp_dir = tempfile.mkdtemp()
        
        audio_duration = get_audio_duration(audio_path) if audio_path and os.path.exists(audio_path) else 30.0
        num_images = max(len(images), 1)
        segment_duration = max(1.5, audio_duration / num_images)

        concat_file = os.path.join(temp_dir, "input.txt")

        with open(concat_file, 'w', encoding='utf-8') as f:
            for img_p in images:
                clean_img = img_p.replace("\\", "/")
                f.write(f"file '{clean_img}'\n")
                f.write(f"duration {segment_duration:.2f}\n")
            clean_last_img = images[-1].replace("\\", "/")
            f.write(f"file '{clean_last_img}'\n")

        cmd = [
            'ffmpeg', '-y',
            '-f', 'concat', '-safe', '0', '-i', concat_file
        ]

        if audio_path and os.path.exists(audio_path):
            cmd.extend(['-i', audio_path])

        if is_short:
            filter_complex = (
                "[0:v]scale=1280:2275,zoompan=z='min(zoom+0.0015,1.15)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=125:s=1080x1920:fps=25,"
                "format=yuv420p[v_zoom]"
            )
        else:
            filter_complex = (
                "[0:v]scale=2048:1152,zoompan=z='min(zoom+0.0012,1.12)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=125:s=1920x1080:fps=25,"
                "format=yuv420p[v_zoom]"
            )

        if ass_subtitles_path and os.path.exists(ass_subtitles_path):
            clean_ass_path = ass_subtitles_path.replace("\\", "/").replace(":", "\\:")
            filter_complex += f";[v_zoom]subtitles='{clean_ass_path}'[v]"
            map_video_label = '[v]'
        else:
            map_video_label = '[v_zoom]'

        cmd.extend([
            '-filter_complex', filter_complex,
            '-map', map_video_label
        ])

        if audio_path and os.path.exists(audio_path):
            cmd.extend(['-map', '1:a', '-c:a', 'aac', '-shortest'])

        cmd.extend([
            '-c:v', 'libx264',
            '-preset', 'ultrafast',
            '-r', '25',
            output_path
        ])

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode == 0 and os.path.exists(output_path):
            return output_path, None
        else:
            return None, f"❌ Erreur FFmpeg: {result.stderr[-400:]}"
            
    except Exception as e:
        return None, f"❌ Erreur exécution FFmpeg: {str(e)}"

# ---------------------------------------------------------
# INTERFACE UTILISATEUR STREAMLIT
# ---------------------------------------------------------
st.title("🎬 Studio Vidéo IA - Pack Duo (Teaser + Long)")

subject_input = st.text_input("Sujet principal de la vidéo :", placeholder="Ex: Pourquoi le cerveau procrastine ?", key="subject_main")

if st.button("🚀 Générer le Pack Duo (Vidéo Longue + Short Teaser)", key="btn_pack"):
    if not subject_input:
        st.warning("Veuillez saisir un sujet de vidéo.")
    else:
        st.info("⚡ Génération du Pack Duo en cours...")
        
        # 1. Génération des deux scripts
        with st.spinner("1/5 Rédaction des scripts (Longue + Teaser)..."):
            script_long, script_teaser, err = generate_pack_scripts(subject_input)
            
        if err:
            st.error(err)
        else:
            col_a, col_b = st.columns(2)
            with col_a:
                st.subheader("🎥 Script Vidéo Longue")
                st.text_area("Long", script_long, height=200)
            with col_b:
                st.subheader("📱 Script Short Teaser")
                st.text_area("Teaser", script_teaser, height=200)

            # 2. Génération de la Vidéo Longue
            st.markdown("---")
            st.subheader("🎥 1. Production de la Vidéo Longue (16:9)")
            
            narration_long, prompts_long = parse_script(script_long)
            audio_long, err1 = generate_audio(narration_long, "long_voice.mp3")
            ass_long = generate_ass_subtitles(narration_long, "long_subs.ass", is_short=False)
            
            temp_dir_long = tempfile.mkdtemp()
            images_long = fetch_all_images(prompts_long, temp_dir_long, is_short=False)
            video_long, err2 = create_video_ffmpeg(images_long, audio_long, ass_long, "long_final.mp4", is_short=False)

            if video_long and os.path.exists(video_long):
                st.success("✅ Vidéo Longue prête !")
                st.video(video_long)
                with open(video_long, "rb") as f:
                    st.download_button("📥 Télécharger Vidéo Longue (MP4)", data=f, file_name="video_longue.mp4", mime="video/mp4")
            else:
                st.error(f"Erreur vidéo longue: {err2}")

            # 3. Génération du Short Teaser
            st.markdown("---")
            st.subheader("📱 2. Production du Short Teaser (9:16)")
            
            narration_teaser, prompts_teaser = parse_script(script_teaser)
            audio_teaser, err3 = generate_audio(narration_teaser, "teaser_voice.mp3")
            ass_teaser = generate_ass_subtitles(narration_teaser, "teaser_subs.ass", is_short=True)
            
            temp_dir_teaser = tempfile.mkdtemp()
            images_teaser = fetch_all_images(prompts_teaser, temp_dir_teaser, is_short=True)
            video_teaser, err4 = create_video_ffmpeg(images_teaser, audio_teaser, ass_teaser, "teaser_final.mp4", is_short=True)

            if video_teaser and os.path.exists(video_teaser):
                st.success("✅ Short Teaser prêt !")
                st.video(video_teaser)
                with open(video_teaser, "rb") as f:
                    st.download_button("📥 Télécharger Short Teaser (MP4)", data=f, file_name="short_teaser.mp4", mime="video/mp4")
            else:
                st.error(f"Erreur short teaser: {err4}")
