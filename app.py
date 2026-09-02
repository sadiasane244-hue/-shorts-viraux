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
    page_title="Générateur de Shorts Viraux",
    page_icon="🎬",
    layout="centered"
)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "meta-llama/llama-3.3-70b-instruct"

# ---------------------------------------------------------
# GENERATION DE SCRIPT VIRAL & ETHIQUE
# ---------------------------------------------------------
def generate_script(subject=None):
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

    system_prompt = """Tu es un créateur de contenu viral pour TikTok et Shorts.
Tu écris des scripts HYPER CAPTIVANTS, modernes et amusants sur la psychologie et le cerveau.

STYLE ET TON:
- Dynamique, percutant, énergique avec un tutoiement direct.
- Utilise des accroches modernes ("Attends...", "Regarde ça...", "C'est complètement fou", "Ton cerveau te ment").
- Humour intelligent et situationnel.
- BOUCLE PARFAITE : Fais en sorte que la dernière phrase du CTA s'enchaîne naturellement avec le premier mot du HOOK pour créer un loop infini.

RÈGLES ÉTHIQUES STRICTES:
- ZÉRO vulgarité, zéro insulte, zéro argot grossier.
- NE PARLE JAMAIS de "Mère Nature" ni d'évolution. Utilise des termes scientifiques neutres : "Le cerveau humain", "Notre biologie", "La façon dont le corps fonctionne".
- Zéro mention de musique, zéro mention de religion/Islam, zéro sujet inapproprié.
- Le script doit captiver dès les 2 premières secondes.

RÈGLE DES MEMES:
Insère la balise [MEME: description courte de l'émotion] immédiatement après le HOOK et après chaque FAIT.

FORMAT STRICT DE RÉPONSE:
TITRE: [titre court]
HOOK: [Phrase d'accroche choc] [MEME: réaction surprise]
FAIT 1: [Premier fait scientifique avec **mots-clés** en gras] [MEME: réaction drôle]
FAIT 2: [Deuxième fait scientifique avec **mots-clés** en gras] [MEME: réaction réflexion]
FAIT 3: [Troisième fait scientifique avec **mots-clés** en gras] [MEME: réaction choc]
CTA: [Call to action court posant une question engageante pour lancer des commentaires]
HASHTAGS: [5 hashtags viraux]"""

    user_prompt = f"Crée un script court, moderne et fun sur : {subject}"

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://shorts-viraux.render.com",
        "X-Title": "Shorts Viraux Generator"
    }

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.88,
        "max_tokens": 800
    }

    try:
        response = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=30)
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
        cleaned = re.sub(r'^(TITRE|HOOK|FAIT \d|CTA|HASHTAGS):\s*', '', cleaned)
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
# SOUS-TITRES & IMAGES
# ---------------------------------------------------------
def generate_ass_subtitles(text, output_ass="subtitles.ass"):
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,65,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,0,2,50,50,900,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    words = text.split()
    chunk_size = 3
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

def fetch_placeholder_images(temp_dir, count=5):
    images = []
    colors = [(25, 30, 45), (40, 20, 50), (15, 45, 60), (50, 35, 25), (30, 40, 30)]
    for i in range(count):
        img_path = os.path.join(temp_dir, f"bg_{i}.jpg")
        img = Image.new('RGB', (1080, 1920), color=colors[i % len(colors)])
        img.save(img_path)
        images.append(img_path)
    return images

# ---------------------------------------------------------
# ASSEMBLAGE VIDÉO FFMPEG DIRECT
# ---------------------------------------------------------
def create_video_ffmpeg(images, audio_path, ass_subtitles_path, output_path="short_viral.mp4"):
    try:
        temp_dir = tempfile.mkdtemp()
        if not images:
            images = fetch_placeholder_images(temp_dir)

        concat_file = os.path.join(temp_dir, "input.txt")
        segment_duration = 3.0

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

        filter_complex = (
            "[0:v]scale=1280:2275,zoompan=z='min(zoom+0.0015,1.15)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=125:s=1080x1920:fps=25,"
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
# INTERFACE UTILISATEUR STREAMLIT
# ---------------------------------------------------------
st.title("🎬 Générateur de Shorts Viraux")
st.write("Générez des scripts, voix-off et vidéos TikTok / Shorts en un clic.")

subject_input = st.text_input(
    "Sujet de la vidéo (optionnel) :", 
    placeholder="Ex: Pourquoi on procrastine ?"
)

if st.button("🚀 Générer la Vidéo"):
    with st.spinner("Génération du script et du rendu en cours..."):
        # Step 1: Script
        script, err = generate_script(subject_input if subject_input else None)
        if err:
            st.error(err)
            st.stop()
            
        st.subheader("📝 Script Généré")
        st.info(script)

        # Step 2: Parse & Audio
        narration_text, memes = parse_script(script)
        audio_file, err = generate_audio(narration_text, "voiceover.mp3")
        if err:
            st.error(err)
            st.stop()

        # Step 3: Subtitles & Video
        ass_file = generate_ass_subtitles(narration_text, "subtitles.ass")
        temp_dir = tempfile.mkdtemp()
        images = fetch_placeholder_images(temp_dir, count=6)

        final_video, err = create_video_ffmpeg(images, audio_file, ass_file, "short_viral_final.mp4")

        # Step 4: Display Result
        if final_video and os.path.exists(final_video):
            st.success("✅ Vidéo générée avec succès !")
            st.video(final_video)
            
            with open(final_video, "rb") as file:
                st.download_button(
                    label="📥 Télécharger la vidéo MP4",
                    data=file,
                    file_name="short_viral.mp4",
                    mime="video/mp4"
                )
        else:
            st.error(f"Erreur lors de la création de la vidéo : {err}")
