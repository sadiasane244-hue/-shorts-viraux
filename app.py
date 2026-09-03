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
# CONFIGURATION STREAMLIT & VARIABLES D'ENVIRONNEMENT
# ---------------------------------------------------------
st.set_page_config(
    page_title="Studio Vidéo Pexels HD (Grand Format)",
    page_icon="🎬",
    layout="centered"
)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "meta-llama/llama-3.3-70b-instruct"

# ---------------------------------------------------------
# GENERATION DE SCRIPTS (> 5 MINUTES POUR LA VIDÉO LONGUE)
# ---------------------------------------------------------
def generate_pack_scripts(subject=None):
    if not OPENROUTER_API_KEY:
        return None, None, "❌ Clé OpenRouter manquante."

    topics = [
        "pourquoi ton cerveau te fait procrastiner au pire moment",
        "le phénomène bizarre qui te fait oublier pourquoi tu es entré dans une pièce",
        "ce qui se passe dans ton cerveau quand tu scrolles sur ton téléphone la nuit"
    ]

    if not subject:
        subject = random.choice(topics)

    # 1. Script Vidéo Longue (1200 - 1600 mots pour 5 à 8+ minutes)
    long_system_prompt = f"""Tu es un vulgarisateur scientifique passionnant pour des vidéos YouTube longues (16:9).
INSTRUCTION STRICTE DE DURÉE: La vidéo DOIT faire PLUS DE 5 MINUTES. Ton script DOIT contenir entre 1200 et 1600 mots.
Prends tout ton temps : pose le contexte, explique en détail la science, donne plusieurs anecdotes réelles, des études de cas et des conseils pratiques.

FORMAT ET BALISES VISUELLES PEXELS:
Toutes les 1 ou 2 phrases, insère une balise [IMAGE: mots clés simples en anglais].
Les mots-clés doivent décrire des visuels réels pour une recherche de banques d'images (ex: [IMAGE: scientist looking at microscope], [IMAGE: person stressed at night desk], [IMAGE: human brain neural connections]).
Insère AU MOINS 50 à 70 balises [IMAGE: ...] réparties tout au long du script.

STRUCTURE COMPLÈTE EN 5 PARTIES:
TITRE: [Titre captivant YouTube]
INTRO: [Mise en situation complète et problème] [IMAGE: ...] ...
PARTIE 1: [Les fondements et explications anatomiques/psychologiques] [IMAGE: ...] ...
PARTIE 2: [Pourquoi cela arrive au quotidien - Études et exemples] [IMAGE: ...] ...
PARTIE 3: [Les idées reçues et pièges à éviter] [IMAGE: ...] ...
PARTIE 4: [Les conséquences à long terme] [IMAGE: ...] ...
PARTIE 5: [Solutions concrètes et étapes pratiques] [IMAGE: ...] ...
CONCLUSION: [Synthèse inspirante] [IMAGE: ...]
CTA: [Appel à l'abonnement et question d'engagement] [IMAGE: youtube subscribe red button]
HASHTAGS: [5 hashtags]"""

    # 2. Script Short Teaser (130 - 160 mots pour 45s à 60s)
    teaser_system_prompt = f"""Tu es un créateur de contenu viral pour TikTok/Shorts (9:16).
INSTRUCTION DE DURÉE: Ton script DOIT contenir entre 130 et 160 mots (durée exacte: 45 à 60 secondes).
C'est un TEASER captivant pour donner envie d'aller regarder la vidéo complète de +5 minutes sur le sujet : "{subject}".

FORMAT ET BALISES VISUELLES PEXELS:
À CHAQUE PHRASE, insère une balise [IMAGE: mots clés simples en anglais].
Insère au moins 15 balises [IMAGE: ...].

STRUCTURE:
TITRE: [Titre court du teaser]
HOOK: [Accroche percutante] [IMAGE: ...]
TEASER: [Accroche mystérieuse sans tout dévoiler] [IMAGE: ...]
CTA: [La vidéo complète de 5 minutes est sur la chaîne, va tout comprendre maintenant !] [IMAGE: click link bio CTA]
HASHTAGS: [5 hashtags viraux]"""

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://shorts-viraux.render.com",
        "X-Title": "Video Generator Pexels"
    }

    try:
        # Script Long (+5000 tokens pour éviter toute troncature)
        p_long = {
            "model": OPENROUTER_MODEL,
            "messages": [
                {"role": "system", "content": long_system_prompt},
                {"role": "user", "content": f"Rédige le grand script LONG (minimum 1200-1600 mots) sur : {subject}"}
            ],
            "temperature": 0.8,
            "max_tokens": 5000
        }
        r_long = requests.post(OPENROUTER_URL, headers=headers, json=p_long, timeout=90)
        script_long = r_long.json()['choices'][0]['message']['content'] if r_long.status_code == 200 else None

        # Script Teaser
        p_teaser = {
            "model": OPENROUTER_MODEL,
            "messages": [
                {"role": "system", "content": teaser_system_prompt},
                {"role": "user", "content": f"Rédige le SHORT TEASER (45-60s) sur : {subject}"}
            ],
            "temperature": 0.85,
            "max_tokens": 1000
        }
        r_teaser = requests.post(OPENROUTER_URL, headers=headers, json=p_teaser, timeout=40)
        script_teaser = r_teaser.json()['choices'][0]['message']['content'] if r_teaser.status_code == 200 else None

        if script_long and script_teaser:
            return script_long, script_teaser, None
        return None, None, "❌ Erreur de génération auprès de l'IA."

    except Exception as e:
        return None, None, f"❌ Erreur connexion OpenRouter: {str(e)}"

# ---------------------------------------------------------
# EXTRACTION DE LA NARRATION ET DES BALISES
# ---------------------------------------------------------
def parse_script(script_text):
    clean_lines = []
    visual_prompts = []
    
    for line in script_text.splitlines():
        line = line.strip()
        if not line:
            continue
            
        # Extraction des termes visuels Pexels
        visual_matches = re.findall(r'\[(?:IMAGE|MEME|VISUEL)[^\]]*:\s*([^\]]+)\]', line, re.IGNORECASE)
        for v in visual_matches:
            kw = v.strip()
            if kw:
                visual_prompts.append(kw)

        if re.match(r'^(TITRE|HASHTAGS|HASHTAG)\s*:', line, re.IGNORECASE):
            continue

        cleaned = re.sub(r'\[.*?\]', '', line)
        cleaned = re.sub(r'^(HOOK|INTRO|PARTIE\s*\d+|TEASER|CONCLUSION|CTA)\s*:\s*', '', cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.replace('*', '').strip()

        if cleaned:
            clean_lines.append(cleaned)

    narration_text = " ".join(clean_lines)
    return narration_text, visual_prompts

# ---------------------------------------------------------
# TELECHARGEMENT IMAGES PEXELS HD
# ---------------------------------------------------------
def fetch_pexels_image(keyword, idx, temp_dir, is_short=True):
    orientation = "portrait" if is_short else "landscape"
    width, height = (1080, 1920) if is_short else (1920, 1080)
    img_path = os.path.join(temp_dir, f"pex_{idx:03d}.jpg")

    clean_kw = re.sub(r'[^a-zA-Z0-9\s]', '', keyword).strip()
    if not clean_kw:
        clean_kw = "scientific concept background"

    headers = {}
    if PEXELS_API_KEY:
        headers["Authorization"] = PEXELS_API_KEY

    url = f"https://api.pexels.com/v1/search?query={urllib.parse.quote(clean_kw)}&orientation={orientation}&per_page=15"
    
    try:
        res = requests.get(url, headers=headers, timeout=12)
        if res.status_code == 200:
            data = res.json()
            photos = data.get("photos", [])
            if photos:
                photo = random.choice(photos)
                img_url = photo["src"].get("large2x") or photo["src"].get("original")
                
                img_res = requests.get(img_url, timeout=15)
                if img_res.status_code == 200:
                    with open(img_path, "wb") as f:
                        f.write(img_res.content)
                    return img_path
    except Exception:
        pass

    # Fallback Unsplash HD
    try:
        fallback_url = f"https://images.unsplash.com/photo-1507413245164-6160d8298b31?w={width}&h={height}&fit=crop"
        img_res = requests.get(fallback_url, timeout=10)
        if img_res.status_code == 200:
            with open(img_path, "wb") as f:
                f.write(img_res.content)
            return img_path
    except Exception:
        pass

    # Fallback fond neutre
    img = Image.new('RGB', (width, height), color=(25, 35, 50) if idx % 2 == 0 else (40, 25, 45))
    img.save(img_path)
    return img_path

def fetch_all_images(prompts, temp_dir, is_short=True, required_count=20):
    if len(prompts) < required_count:
        fallback_keywords = prompts if prompts else ["technology research", "brain network", "human psychology", "focus idea"]
        while len(prompts) < required_count:
            prompts.extend(fallback_keywords)

    prompts = prompts[:required_count]

    images = []
    # Accélération du téléchargement parallèle (max_workers=10)
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(fetch_pexels_image, p, i, temp_dir, is_short) for i, p in enumerate(prompts)]
        for future in futures:
            images.append(future.result())
    return images

# ---------------------------------------------------------
# GENERATION AUDIO EDGE-TTS
# ---------------------------------------------------------
async def generate_audio_async(text, output_mp3, is_short=True):
    import edge_tts
    voice = "fr-FR-RemyNeural" 
    rate = "+10%" if is_short else "+2%"
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(output_mp3)

def generate_audio(text, output_mp3="narration.mp3", is_short=True):
    try:
        asyncio.run(generate_audio_async(text, output_mp3, is_short))
        if os.path.exists(output_mp3):
            return output_mp3, None
        return None, "❌ Erreur génération fichier audio."
    except Exception as e:
        return None, f"❌ Erreur Edge-TTS: {str(e)}"

def get_audio_duration(audio_path):
    try:
        cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprintwrappers=1:nokey=1', audio_path]
        res = subprocess.run(cmd, capture_output=True, text=True)
        return float(res.stdout.strip())
    except Exception:
        return 300.0

# ---------------------------------------------------------
# GENERATION SOUS-TITRES ASS
# ---------------------------------------------------------
def generate_ass_subtitles(text, output_ass="subtitles.ass", is_short=True):
    res_x = 1080 if is_short else 1920
    res_y = 1920 if is_short else 1080
    font_size = 62 if is_short else 46
    margin_v = 880 if is_short else 120

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {res_x}
PlayResY: {res_y}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,2,50,50,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    words = text.split()
    chunk_size = 3 if is_short else 5
    current_time = 0.0
    word_duration = 0.32 if is_short else 0.35

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

            f.write(f"Dialogue: 0,{format_time(start_sec)},{format_time(end_sec)},Default,,0,0,0,,{chunk}\n")
            current_time = end_sec

    return output_ass

# ---------------------------------------------------------
# MONTAGE FFMPEG DIRECT
# ---------------------------------------------------------
def create_video_ffmpeg(images, audio_path, ass_subtitles_path, output_path="video_output.mp4", is_short=True):
    try:
        temp_dir = tempfile.mkdtemp()
        audio_dur = get_audio_duration(audio_path) if audio_path and os.path.exists(audio_path) else 300.0
        
        num_images = len(images)
        segment_duration = audio_dur / num_images if num_images > 0 else 3.0

        concat_file = os.path.join(temp_dir, "input.txt")
        with open(concat_file, 'w', encoding='utf-8') as f:
            for img_p in images:
                clean_img = img_p.replace("\\", "/")
                f.write(f"file '{clean_img}'\n")
                f.write(f"duration {segment_duration:.3f}\n")
            f.write(f"file '{images[-1].replace('\\', '/')}'\n")

        cmd = [
            'ffmpeg', '-y',
            '-f', 'concat', '-safe', '0', '-i', concat_file
        ]

        if audio_path and os.path.exists(audio_path):
            cmd.extend(['-i', audio_path])

        if is_short:
            filter_complex = "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,format=yuv420p[v_base]"
        else:
            filter_complex = "[0:v]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,format=yuv420p[v_base]"

        if ass_subtitles_path and os.path.exists(ass_subtitles_path):
            clean_ass_path = ass_subtitles_path.replace("\\", "/").replace(":", "\\:")
            filter_complex += f";[v_base]subtitles='{clean_ass_path}'[v]"
            map_video_label = '[v]'
        else:
            map_video_label = '[v_base]'

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
# INTERFACE STREAMLIT
# ---------------------------------------------------------
st.title("🎬 Studio Vidéo IA - Grand Format (+5 Min)")

subject_input = st.text_input("Sujet principal de la vidéo :", placeholder="Ex: Pourquoi le cerveau procrastine le soir ?", key="subject_main")

if st.button("🚀 Générer le Pack Duo (+5 Min & Short Teaser)", key="btn_pack"):
    if not subject_input:
        st.warning("Veuillez saisir un sujet de vidéo.")
    else:
        st.info("⚡ Génération du Pack Duo en cours... Cela peut prendre 3 à 5 minutes pour rédiger et monter la vidéo de +5 min.")
        
        # 1. Scripts
        with st.spinner("1/5 Rédaction des scripts en profondeur par l'IA..."):
            script_long, script_teaser, err = generate_pack_scripts(subject_input)
            
        if err:
            st.error(err)
        else:
            col_a, col_b = st.columns(2)
            with col_a:
                st.subheader("🎥 Script Vidéo Longue (+5 Min)")
                st.text_area("Long", script_long, height=250)
            with col_b:
                st.subheader("📱 Script Short Teaser")
                st.text_area("Teaser", script_teaser, height=250)

            # --- VIDEO LONGUE ---
            st.markdown("---")
            st.subheader("🎥 1. Production de la Vidéo Longue (16:9)")
            
            narration_long, prompts_long = parse_script(script_long)
            audio_long, err1 = generate_audio(narration_long, "long_voice.mp3", is_short=False)
            ass_long = generate_ass_subtitles(narration_long, "long_subs.ass", is_short=False)
            
            audio_dur_long = get_audio_duration(audio_long)
            # Image toutes les 3 secondes : pour 5 min (300s), cela fait ~100 images
            req_images_long = max(30, int(audio_dur_long / 3.0))
            
            temp_dir_long = tempfile.mkdtemp()
            with st.spinner(f"Téléchargement de {req_images_long} images Pexels HD..."):
                images_long = fetch_all_images(prompts_long, temp_dir_long, is_short=False, required_count=req_images_long)
                
            with st.spinner("Montage FFmpeg & Synchronisation..."):
                video_long, err2 = create_video_ffmpeg(images_long, audio_long, ass_long, "long_final.mp4", is_short=False)

            if video_long and os.path.exists(video_long):
                minutes = int(audio_dur_long // 60)
                secondes = int(audio_dur_long % 60)
                st.success(f"✅ Vidéo Longue prête ! (Durée: {minutes}m {secondes}s - {len(images_long)} images)")
                st.video(video_long)
                with open(video_long, "rb") as f:
                    st.download_button("📥 Télécharger Vidéo Longue (MP4)", data=f, file_name="video_longue.mp4", mime="video/mp4")
            else:
                st.error(f"Erreur vidéo longue: {err2}")

            # --- SHORT TEASER ---
            st.markdown("---")
            st.subheader("📱 2. Production du Short Teaser (9:16)")
            
            narration_teaser, prompts_teaser = parse_script(script_teaser)
            audio_teaser, err3 = generate_audio(narration_teaser, "teaser_voice.mp3", is_short=True)
            ass_teaser = generate_ass_subtitles(narration_teaser, "teaser_subs.ass", is_short=True)
            
            audio_dur_teaser = get_audio_duration(audio_teaser)
            req_images_teaser = max(10, int(audio_dur_teaser / 2.5))
            
            temp_dir_teaser = tempfile.mkdtemp()
            with st.spinner(f"Téléchargement de {req_images_teaser} images Pexels HD pour le teaser..."):
                images_teaser = fetch_all_images(prompts_teaser, temp_dir_teaser, is_short=True, required_count=req_images_teaser)
                
            with st.spinner("Montage FFmpeg & Synchronisation..."):
                video_teaser, err4 = create_video_ffmpeg(images_teaser, audio_teaser, ass_teaser, "teaser_final.mp4", is_short=True)

            if video_teaser and os.path.exists(video_teaser):
                st.success(f"✅ Short Teaser prêt ! (Durée: {audio_dur_teaser:.1f} sec)")
                st.video(video_teaser)
                with open(video_teaser, "rb") as f:
                    st.download_button("📥 Télécharger Short Teaser (MP4)", data=f, file_name="short_teaser.mp4", mime="video/mp4")
            else:
                st.error(f"Erreur short teaser: {err4}")

