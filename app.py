import os
import sys
import json
import random
import re
import subprocess
import tempfile
import asyncio
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
# GENERATION DE SCRIPT (SHORT & LONG)
# ---------------------------------------------------------
def generate_script(subject=None, mode="short"):
    if not OPENROUTER_API_KEY:
        return None, "❌ Clé OpenRouter manquante dans les variables d'environnement."

    topics = [
        "pourquoi ton cerveau te fait procrastiner au pire moment",
        "l'astuce psychologique pour savoir si quelqu'un te ment",
        "pourquoi tu te rappelles d'un détail inutile d'il y a 5 ans mais pas de tes clés",
        "ce qui arrive dans ton cerveau quand tu scrolles sur ton téléphone",
        "le phénomène bizarre qui te fait oublier pourquoi tu es entré dans une pièce"
    ]

    if not subject:
        subject = random.choice(topics)

    if mode == "short":
        system_prompt = """Tu es un créateur de contenu viral pour TikTok et YouTube Shorts.
Tu écris des scripts HYPER CAPTIVANTS (30-45s), modernes et amusants sur la psychologie et le cerveau.

STYLE ET TON:
- Dynamique, percutant, énergique avec un tutoiement direct.
- Accroches modernes ("Attends...", "Regarde ça...", "C'est complètement fou").
- Humour intelligent et situationnel.
- BOUCLE PARFAITE : La dernière phrase du CTA doit s'enchaîner avec la première du HOOK.

RÈGLES ÉTHIQUES STRICTES:
- ZÉRO vulgarité, zéro insulte.
- NE PARLE JAMAIS de "Mère Nature" ni d'évolution. Utilise : "Le cerveau humain", "Notre biologie".
- Zéro mention de musique, zéro mention de religion.

FORMAT STRICT:
TITRE: [titre court]
HOOK: [Phrase d'accroche choc] [MEME: réaction surprise]
FAIT 1: [Premier fait scientifique avec **mots-clés** en gras] [MEME: réaction drôle]
FAIT 2: [Deuxième fait scientifique avec **mots-clés** en gras] [MEME: réflexion]
FAIT 3: [Troisième fait scientifique avec **mots-clés** en gras] [MEME: choc]
CTA: [Call to action court posant une question engageante]
HASHTAGS: [5 hashtags viraux]"""
    else:
        system_prompt = """Tu es un vulgarisateur scientifique pour des vidéos longues YouTube (16:9).
Tu écris des scripts structurés, captivants, pédagogiques et amusants (durée 2 à 3 minutes).

STYLE ET TON:
- Professionnel mais accessible, engageant avec tutoiement ou adressage direct à l'audience.
- Explications claires, exemples concrets de la vie quotidienne.
- ZÉRO vulgarité, zéro mention de "Mère Nature" ou théorie de l'évolution (parle de biologie, physiologie, cerveau).

FORMAT STRICT:
TITRE: [Titre accrocheur YouTube]
INTRO: [Introduction captivante posant le problème]
PARTIE 1: [Titre et explications du premier concept]
PARTIE 2: [Titre et explications du deuxième concept]
PARTIE 3: [Titre et explications du troisième concept]
CONCLUSION: [Résumé rapide et conseils pratiques]
CTA: [Invitation à s'abonner et poser une question en commentaire]
HASHTAGS: [5 hashtags YouTube]"""

    user_prompt = f"Crée un script ({mode}) moderne, fun et instructif sur : {subject}"

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://shorts-viraux.render.com",
        "X-Title": "Video Generator"
    }

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.85,
        "max_tokens": 1500 if mode == "long" else 800
    }

    try:
        response = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=40)
        if response.status_code == 200:
            data = response.json()
            if 'choices' in data and len(data['choices']) > 0:
                return data['choices'][0]['message']['content'], None
            return None, "❌ Réponse vide d'OpenRouter."
        else:
            return None, f"❌ Erreur {response.status_code}: {response.text[:200]}"
    except Exception as e:
        return None, f"❌ Erreur connexion: {str(e)}"

def parse_script(script_text):
    clean_lines = []
    memes = []
    
    for line in script_text.splitlines():
        line = line.strip()
        if not line:
            continue
            
        meme_matches = re.findall(r'\[MEME:\s*(.*?)\]', line)
        for m in meme_matches:
            memes.append(m)
            
        cleaned = re.sub(r'\[MEME:\s*.*?\]', '', line)
        cleaned = re.sub(r'^(TITRE|HOOK|INTRO|PARTIE \d|CONCLUSION|FAIT \d|CTA|HASHTAGS):\s*', '', cleaned)
        cleaned = cleaned.replace('*', '').strip()
        
        if cleaned and not line.startswith('TITRE:') and not line.startswith('HASHTAGS:'):
            clean_lines.append(cleaned)

    narration_text = " ".join(clean_lines)
    return narration_text, memes

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

# ---------------------------------------------------------
# SOUS-TITRES ASS (Format Vertical vs Horizontal)
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

def fetch_placeholder_images(temp_dir, count=6, is_short=True):
    images = []
    width, height = (1080, 1920) if is_short else (1920, 1080)
    colors = [(25, 30, 45), (40, 20, 50), (15, 45, 60), (50, 35, 25), (30, 40, 30), (20, 30, 50)]
    for i in range(count):
        img_path = os.path.join(temp_dir, f"bg_{i}.jpg")
        img = Image.new('RGB', (width, height), color=colors[i % len(colors)])
        img.save(img_path)
        images.append(img_path)
    return images

# ---------------------------------------------------------
# ASSEMBLAGE VIDÉO FFMPEG DIRECT
# ---------------------------------------------------------
def create_video_ffmpeg(images, audio_path, ass_subtitles_path, output_path="video_output.mp4", is_short=True):
    try:
        temp_dir = tempfile.mkdtemp()
        if not images:
            images = fetch_placeholder_images(temp_dir, is_short=is_short)

        concat_file = os.path.join(temp_dir, "input.txt")
        segment_duration = 3.0 if is_short else 5.0

        with open(concat_file, 'w', encoding='utf-8') as f:
            for img_p in images:
                f.write(f"file '{img_p}'\n")
                f.write(f"duration {segment_duration}\n")
            f.write(f"file '{images[-1]}'\n")

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
            '-vf', filter_complex,
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
            return None, f"❌ Erreur FFmpeg: {result.stderr[-300:]}"
            
    except Exception as e:
        return None, f"❌ Erreur exécution FFmpeg: {str(e)}"

# ---------------------------------------------------------
# INTERFACE UTILISATEUR STREAMLIT (TABS)
# ---------------------------------------------------------
st.title("🎬 Studio de Création Vidéo IA")

tab_short, tab_long = st.tabs(["📱 Short Court (YouTube Shorts / TikTok)", "🎥 Vidéo Longue (YouTube 16:9)"])

# ----------------- ONGLET 1 : SHORT COURT -----------------
with tab_short:
    st.header("Format Vertical (9:16)")
    st.caption("Optimisé pour YouTube Shorts, TikTok et Reels avec rythme rapide et sous-titres dynamiques.")

    subject_short = st.text_input("Sujet du Short (optionnel) :", placeholder="Ex: Pourquoi le cerveau procrastine ?", key="short_subject")

    if st.button("🚀 Générer le Short Court", key="btn_short"):
        with st.spinner("Génération du Short en cours..."):
            script, err = generate_script(subject_short if subject_short else None, mode="short")
            if err:
                st.error(err)
            else:
                st.subheader("📝 Script Généré")
                st.info(script)

                narration_text, memes = parse_script(script)
                audio_file, err = generate_audio(narration_text, "short_voice.mp3")
                
                if err:
                    st.error(err)
                else:
                    ass_file = generate_ass_subtitles(narration_text, "short_subs.ass", is_short=True)
                    temp_dir = tempfile.mkdtemp()
                    images = fetch_placeholder_images(temp_dir, count=6, is_short=True)

                    final_video, err = create_video_ffmpeg(images, audio_file, ass_file, "short_final.mp4", is_short=True)

                    if final_video and os.path.exists(final_video):
                        st.success("✅ Short généré avec succès !")
                        st.video(final_video)
                        with open(final_video, "rb") as f:
                            st.download_button("📥 Télécharger le Short (MP4)", data=f, file_name="short_youtube.mp4", mime="video/mp4")
                    else:
                        st.error(f"Erreur rendu : {err}")

# ----------------- ONGLET 2 : VIDÉO LONGUE -----------------
with tab_long:
    st.header("Format Horizontal (16:9)")
    st.caption("Optimisé pour les vidéos YouTube explicatives plus complètes (2-3 minutes).")

    subject_long = st.text_input("Sujet de la vidéo longue (optionnel) :", placeholder="Ex: Comment fonctionne la mémoire humaine ?", key="long_subject")

    if st.button("🚀 Générer la Vidéo Longue", key="btn_long"):
        with st.spinner("Génération de la vidéo longue en cours..."):
            script, err = generate_script(subject_long if subject_long else None, mode="long")
            if err:
                st.error(err)
            else:
                st.subheader("📝 Script Détaillé Généré")
                st.info(script)

                narration_text, memes = parse_script(script)
                audio_file, err = generate_audio(narration_text, "long_voice.mp3")
                
                if err:
                    st.error(err)
                else:
                    ass_file = generate_ass_subtitles(narration_text, "long_subs.ass", is_short=False)
                    temp_dir = tempfile.mkdtemp()
                    images = fetch_placeholder_images(temp_dir, count=8, is_short=False)

                    final_video, err = create_video_ffmpeg(images, audio_file, ass_file, "long_final.mp4", is_short=False)

                    if final_video and os.path.exists(final_video):
                        st.success("✅ Vidéo longue générée avec succès !")
                        st.video(final_video)
                        with open(final_video, "rb") as f:
                            st.download_button("📥 Télécharger la Vidéo Longue (MP4)", data=f, file_name="video_youtube_longue.mp4", mime="video/mp4")
                    else:
                        st.error(f"Erreur rendu : {err}")
