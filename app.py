"""
SHORTS VIRAUX - Generateur Automatique
Niche: Cerveau, Psychologie & Faits Fascinants
Deployable sur Render, Streamlit Cloud, ou Replit
"""

import streamlit as st
import requests
import os
import random
import asyncio
import json
import textwrap
from io import BytesIO
from datetime import datetime

import edge_tts
from moviepy.editor import (
    ImageClip, TextClip, ColorClip, CompositeVideoClip,
    AudioFileClip, concatenate_videoclips
)
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import numpy as np

# ============================================
# CONFIGURATION
# ============================================

# Clés API depuis les variables d'environnement (Render/Streamlit Cloud)
# OU depuis un fichier config local (Replit)
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

# Fallback: essayer de lire depuis un fichier secrets.json (pour Replit)
try:
    with open("secrets.json", "r") as f:
        secrets = json.load(f)
        PEXELS_API_KEY = secrets.get("PEXELS_API_KEY", PEXELS_API_KEY)
        GROQ_API_KEY = secrets.get("GROQ_API_KEY", GROQ_API_KEY)
except:
    pass

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

W, H = 1080, 1920
FPS = 30
TEMP_DIR = "/tmp/shorts_viraux"
os.makedirs(TEMP_DIR, exist_ok=True)

NICHE_TOPICS = [
    "pourquoi ton cerveau oublie 80 pourcent de ce que tu lis",
    "la dopamine et les reseaux sociaux addiction",
    "mensonges que ton cerveau te raconte chaque jour",
    "pourquoi tu procrastines et comment arreter",
    "le syndrome de l imposteur explique scientifiquement",
    "pourquoi les souvenirs changent a chaque fois",
    "le pouvoir des habitudes cerveau",
    "anxiete comment ton cerveau te trompe",
    "pourquoi tu prends de mauvaises decisions fatigue",
    "la meditation change reellement ton cerveau",
    "pourquoi tu aimes les personnes toxiques",
    "le biais de confirmation explique simplement",
    "pourquoi le temps passe plus vite en vieillissant",
    "le cerveau des gens creatifs est different",
    "pourquoi tu ne peux pas te concentrer plus de 20 minutes",
]

# ============================================
# FONCTIONS UTILITAIRES
# ============================================

def run_async(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)

def get_font_path():
    possible_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "C:/Windows/Fonts/arialbd.ttf",
    ]
    for path in possible_paths:
        if os.path.exists(path):
            return path
    return None

FONT_PATH = get_font_path()

# ============================================
# 1. GENERATION DU SCRIPT (Groq API)
# ============================================

def generate_script(topic):
    if not GROQ_API_KEY:
        return None, "Cle API Groq manquante. Ajoute-la dans les variables d'environnement ou dans secrets.json"

    system_prompt = """Tu es un expert de contenu viral sur les reseaux sociaux, specialise dans la niche "cerveau, psychologie et faits fascinants sur l esprit humain".

Genere un script de SHORT (50-55 secondes, environ 130 mots) au format JSON strict avec cette structure exacte :

{
  "title": "Titre accrocheur pour la miniature (3-5 mots max)",
  "segments": [
    {"type": "hook", "text": "Phrase choc percutante (8-12 mots)", "emoji": "🧠", "color": "#FFD700"},
    {"type": "fact", "text": "Fait numero 1 (15-20 mots)", "emoji": "1️⃣", "color": "#FFFFFF"},
    {"type": "fact", "text": "Fait numero 2 (15-20 mots)", "emoji": "2️⃣", "color": "#FFFFFF"},
    {"type": "fact", "text": "Fait numero 3 (15-20 mots)", "emoji": "3️⃣", "color": "#FFFFFF"},
    {"type": "cta", "text": "Call-to-action engageant (8-10 mots)", "emoji": "🔥", "color": "#00FFFF"}
  ]
}

REGLES STRICTES :
- Hook : question rhetorique choc OU fait contre-intuitif avec chiffre precis
- Faits : courts, percutants, avec des chiffres ou exemples concrets
- CTA : incite subtilement a s abonner ou a reagir
- Le texte doit etre en francais, style conversationnel et energique
- PAS de markdown dans le JSON, PAS de sauts de ligne dans les textes
- Reponds UNIQUEMENT avec le JSON, rien d autre avant ou apres"""

    user_prompt = f"Sujet du Short : {topic}"

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.85,
        "max_tokens": 800
    }

    try:
        response = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]

        content = content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        script = json.loads(content)
        return script, None

    except Exception as e:
        return None, f"Erreur Groq: {str(e)}"

# ============================================
# 2. GENERATION AUDIO (Edge TTS)
# ============================================

async def generate_audio_async(text, output_path, voice="fr-FR-DeniseNeural"):
    communicate = edge_tts.Communicate(text, voice=voice)
    await communicate.save(output_path)

def generate_audio(text, output_path):
    run_async(generate_audio_async(text, output_path))

# ============================================
# 3. RECUPERATION IMAGES (Pexels)
# ============================================

def fetch_images(topic, count=5):
    if not PEXELS_API_KEY:
        return None, "Cle API Pexels manquante. Ajoute-la dans les variables d'environnement ou dans secrets.json"

    search_query = topic.replace("pourquoi", "").replace("comment", "").strip()
    if len(search_query) < 3:
        search_query = "brain psychology"

    url = "https://api.pexels.com/v1/search"
    headers = {"Authorization": PEXELS_API_KEY}
    params = {"query": search_query, "per_page": count + 3, "orientation": "portrait"}

    try:
        response = requests.get(url, headers=headers, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        photos = data.get("photos", [])

        if not photos:
            params["query"] = "brain psychology mind"
            response = requests.get(url, headers=headers, params=params, timeout=15)
            data = response.json()
            photos = data.get("photos", [])

        image_paths = []
        for i, photo in enumerate(photos[:count]):
            img_url = photo["src"]["portrait"]
            img_response = requests.get(img_url, timeout=15)
            img_response.raise_for_status()
            img_path = os.path.join(TEMP_DIR, f"img_{i}.jpg")
            with open(img_path, "wb") as file:
                file.write(img_response.content)
            image_paths.append(img_path)

        return image_paths, None

    except Exception as e:
        return None, f"Erreur Pexels: {str(e)}"

# ============================================
# 4. CREATION VIDEO (MoviePy)
# ============================================

def create_ken_burns_clip(image_path, duration):
    clip = ImageClip(image_path).set_duration(duration)
    def zoom_func(t):
        return 1.0 + 0.18 * (t / duration)
    clip = clip.resize(zoom_func)
    clip = clip.set_position("center")
    return clip

def create_video(script, audio_path, image_paths, output_path):
    segments = script["segments"]
    audio = AudioFileClip(audio_path)
    total_duration = audio.duration

    total_words = sum(len(seg["text"].split()) for seg in segments)
    seg_durations = []
    for seg in segments:
        ratio = len(seg["text"].split()) / total_words
        seg_durations.append(total_duration * ratio)

    diff = total_duration - sum(seg_durations)
    seg_durations[0] += diff

    clips = []
    current_time = 0

    for i, (seg, seg_dur) in enumerate(zip(segments, seg_durations)):
        img_path = image_paths[i % len(image_paths)]
        bg = create_ken_burns_clip(img_path, seg_dur)

        if i > 0:
            flash = ColorClip(size=(W, H), color=(255, 255, 255)).set_duration(0.06)
            flash = flash.set_opacity(0.25)
            clips.append(flash)
            current_time += 0.06

        emoji_clip = TextClip(
            seg["emoji"],
            fontsize=90,
            color="white",
            font="DejaVu-Sans-Bold" if FONT_PATH else "Arial-Bold",
            stroke_color="black",
            stroke_width=2
        ).set_duration(seg_dur).set_position(("center", 120))

        txt_bg = ColorClip(size=(980, 350), color=(0, 0, 0))
        txt_bg = txt_bg.set_opacity(0.55).set_duration(seg_dur)
        txt_bg = txt_bg.set_position("center")

        color = seg.get("color", "#FFFFFF")
        wrapped_text = "\n".join(textwrap.wrap(seg["text"], width=18))

        txt_clip = TextClip(
            wrapped_text,
            fontsize=62,
            color=color,
            stroke_color="black",
            stroke_width=3,
            font="DejaVu-Sans-Bold" if FONT_PATH else "Arial-Bold",
            size=(900, None),
            method="caption",
            align="center"
        ).set_duration(seg_dur).set_position("center")

        extra_clips = [bg, txt_bg, txt_clip, emoji_clip]

        if seg["type"] == "fact":
            fact_num = sum(1 for s in segments[:i+1] if s["type"] == "fact")
            counter = TextClip(
                str(fact_num),
                fontsize=280,
                color=(255, 255, 255),
                font="DejaVu-Sans-Bold" if FONT_PATH else "Arial-Bold",
                stroke_color="black",
                stroke_width=4
            ).set_duration(seg_dur).set_position((750, 200))
            counter = counter.set_opacity(0.15)
            extra_clips.append(counter)

        progress_width = int(W * ((current_time + seg_dur) / total_duration))
        progress_bar = ColorClip(size=(progress_width, 18), color=(255, 50, 50))
        progress_bar = progress_bar.set_duration(seg_dur).set_position(("left", H - 18))
        extra_clips.append(progress_bar)

        segment = CompositeVideoClip(extra_clips, size=(W, H))
        segment = segment.set_duration(seg_dur)
        clips.append(segment)
        current_time += seg_dur

    if len(clips) == 1:
        final = clips[0]
    else:
        final = concatenate_videoclips(clips, method="compose")

    final = final.set_audio(audio)

    final.write_videofile(
        output_path,
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        temp_audiofile=os.path.join(TEMP_DIR, "temp_audio.m4a"),
        remove_temp=True,
        threads=4,
        preset="ultrafast",
        logger=None
    )

    audio.close()
    final.close()
    return output_path

# ============================================
# 5. GENERATION MINIATURE (Pillow)
# ============================================

def create_thumbnail(title, image_paths, output_path):
    thumb = Image.new("RGB", (W, H), (20, 20, 30))
    draw = ImageDraw.Draw(thumb)

    if image_paths:
        bg_img = Image.open(image_paths[0]).convert("RGB")
        bg_img = bg_img.resize((W, H), Image.LANCZOS)
        bg_img = bg_img.filter(ImageFilter.GaussianBlur(radius=15))
        enhancer = ImageEnhance.Brightness(bg_img)
        bg_img = enhancer.enhance(0.4)
        thumb.paste(bg_img)

    for y in range(H):
        alpha = int(180 * (y / H))
        draw.line([(0, y), (W, y)], fill=(0, 0, 0, alpha))

    try:
        font_title = ImageFont.truetype(FONT_PATH, 110) if FONT_PATH else ImageFont.load_default()
        font_sub = ImageFont.truetype(FONT_PATH, 50) if FONT_PATH else ImageFont.load_default()
        font_emoji = ImageFont.truetype(FONT_PATH, 200) if FONT_PATH else ImageFont.load_default()
    except:
        font_title = ImageFont.load_default()
        font_sub = ImageFont.load_default()
        font_emoji = ImageFont.load_default()

    draw.text((W//2, 250), "🧠", fill=(255, 215, 0), font=font_emoji, anchor="mm")

    title_upper = title.upper()
    words = title_upper.split()
    lines = []
    current_line = []
    for word in words:
        test_line = " ".join(current_line + [word])
        bbox = draw.textbbox((0, 0), test_line, font=font_title)
        if bbox[2] - bbox[0] < 900:
            current_line.append(word)
        else:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]
    if current_line:
        lines.append(" ".join(current_line))

    y_pos = 500
    for line in lines:
        for dx in [-4, -3, -2, -1, 0, 1, 2, 3, 4]:
            for dy in [-4, -3, -2, -1, 0, 1, 2, 3, 4]:
                if abs(dx) + abs(dy) <= 4:
                    draw.text((W//2 + dx, y_pos + dy), line, fill=(0, 0, 0), font=font_title, anchor="mm")
        draw.text((W//2, y_pos), line, fill=(255, 255, 255), font=font_title, anchor="mm")
        y_pos += 140

    draw.text((W//2, y_pos + 40), "FAIT SCIENTIFIQUE", fill=(255, 215, 0), font=font_sub, anchor="mm")
    draw.rectangle([290, y_pos + 100, 790, y_pos + 108], fill=(255, 50, 50))
    draw.text((W//2, H - 200), "⚡", fill=(255, 215, 0), font=font_emoji, anchor="mm")

    thumb.save(output_path, quality=95)
    return output_path

# ============================================
# 6. INTERFACE STREAMLIT
# ============================================

def main():
    st.set_page_config(
        page_title="Shorts Viraux",
        page_icon="🧠",
        layout="centered",
        initial_sidebar_state="collapsed"
    )

    st.markdown("<h1 style='text-align:center; font-size:2.2rem; font-weight:900;'>🧠 SHORTS VIRAUX</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align:center; color:gray; margin-bottom:2rem;'>Cerveau & Psychologie · 100% Automatique</p>", unsafe_allow_html=True)

    if not GROQ_API_KEY or not PEXELS_API_KEY:
        st.warning("Configuration requise")
        with st.expander("Comment configurer les cles API"):
            st.markdown("""
            **1. Groq API** (gratuit) :
            - Va sur groq.com
            - Cree un compte → API Keys → Create API Key
            - Copie la cle

            **2. Pexels API** (gratuit) :
            - Va sur pexels.com/api
            - Join → API Key → copie la cle

            **3. Dans Render :**
            - Va dans Settings → Environment Variables
            - Ajoute : GROQ_API_KEY et PEXELS_API_KEY

            **3b. Dans Replit :**
            - Cree un fichier secrets.json avec :
            {"GROQ_API_KEY": "ta_cle", "PEXELS_API_KEY": "ta_cle"}
            """)
        st.stop()

    col1, col2 = st.columns([3, 1])
    with col1:
        topic = st.text_input(
            "Sujet du Short (optionnel)",
            placeholder="Ex: pourquoi tu procrastines",
            label_visibility="collapsed"
        )
    with col2:
        random_topic = st.button("🎲 Aleatoire", use_container_width=True)

    if random_topic or not topic:
        topic = random.choice(NICHE_TOPICS)
        st.info(f"Sujet choisi : **{topic}**")

    generate_btn = st.button(
        "🎬 GENERER MON SHORT",
        type="primary",
        use_container_width=True
    )

    if generate_btn and topic:
        progress_bar = st.progress(0)
        status = st.empty()

        try:
            status.info("Etape 1/5 : Generation du script viral...")
            progress_bar.progress(10)
            script, error = generate_script(topic)
            if error:
                st.error(error)
                st.stop()

            st.success(f"Script genere : **{script['title']}**")

            status.info("Etape 2/5 : Generation de la voix off...")
            progress_bar.progress(30)
            full_text = " ".join([seg["text"] for seg in script["segments"]])
            audio_path = os.path.join(TEMP_DIR, "voice.mp3")
            generate_audio(full_text, audio_path)

            status.info("Etape 3/5 : Recherche d'images...")
            progress_bar.progress(50)
            image_paths, error = fetch_images(topic, count=5)
            if error:
                st.error(error)
                st.stop()

            status.info("Etape 4/5 : Montage video dynamique...")
            progress_bar.progress(65)
            video_path = os.path.join(TEMP_DIR, "short.mp4")
            create_video(script, audio_path, image_paths, video_path)

            status.info("Etape 5/5 : Creation de la miniature...")
            progress_bar.progress(85)
            thumb_path = os.path.join(TEMP_DIR, "thumbnail.jpg")
            create_thumbnail(script["title"], image_paths, thumb_path)

            progress_bar.progress(100)
            status.success("Short genere avec succes !")

            st.divider()
            st.subheader("Previsualisation")

            st.video(video_path)

            st.subheader("Miniature")
            st.image(thumb_path, use_column_width=True)

            col_dl1, col_dl2 = st.columns(2)
            with col_dl1:
                with open(video_path, "rb") as file:
                    st.download_button(
                        label="Telecharger la video",
                        data=file,
                        file_name=f"short_{script['title'].replace(' ', '_')}.mp4",
                        mime="video/mp4",
                        use_container_width=True
                    )
            with col_dl2:
                with open(thumb_path, "rb") as file:
                    st.download_button(
                        label="Telecharger la miniature",
                        data=file,
                        file_name=f"thumb_{script['title'].replace(' ', '_')}.jpg",
                        mime="image/jpeg",
                        use_container_width=True
                    )

            st.info("Telecharge la video et la miniature, puis upload-les manuellement sur YouTube Shorts ou TikTok depuis ton telephone.")

        except Exception as e:
            st.error(f"Une erreur est survenue : {str(e)}")
            st.exception(e)

if __name__ == "__main__":
    main()

