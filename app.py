"""
SHORTS VIRAUX - Generateur Automatique v2.0
Niche: Cerveau, Psychologie & Faits Fascinants
Voix: Edge TTS (gratuit)
LLM: OpenRouter API (Llama 3.3 70B gratuit)
Interface: Moderne glassmorphism + Dashboard Analytics
Features: Auto-optimisation IA, suivi viralite, pas de musique
Deployable sur Render
"""

import streamlit as st
import requests
import os
import random
import asyncio
import json
import textwrap
from datetime import datetime, timedelta

import edge_tts
from moviepy.editor import (
    ImageClip, TextClip, ColorClip, CompositeVideoClip,
    AudioFileClip, concatenate_videoclips
)
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

# ============================================
# CONFIGURATION
# ============================================

PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

# Fallback secrets.json
try:
    with open("secrets.json", "r") as f2:
        secrets = json.load(f2)
        PEXELS_API_KEY = secrets.get("PEXELS_API_KEY", PEXELS_API_KEY)
        OPENROUTER_API_KEY = secrets.get("OPENROUTER_API_KEY", OPENROUTER_API_KEY)
except:
    pass

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "meta-llama/llama-3.3-70b-instruct:free"

W, H = 1080, 1920
FPS = 30
TEMP_DIR = "/tmp/shorts_viraux"
os.makedirs(TEMP_DIR, exist_ok=True)

# Fichier de base de donnees pour les stats
DB_FILE = "shorts_database.json"

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
# BASE DE DONNEES - ANALYTICS
# ============================================

def load_database():
    """Charge la base de donnees des shorts"""
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            return json.load(f)
    return {"shorts": [], "viral_patterns": {}, "best_hooks": [], "best_ctas": []}

def save_database(db):
    """Sauvegarde la base de donnees"""
    with open(DB_FILE, "w") as f:
        json.dump(db, f, indent=2)

def add_short_to_db(title, topic, script, views=0, likes=0, retention_rate=0, subscribers_gained=0, platform=""):
    """Ajoute un short a la base de donnees"""
    db = load_database()
    short = {
        "id": len(db["shorts"]) + 1,
        "title": title,
        "topic": topic,
        "script": script,
        "created_at": datetime.now().isoformat(),
        "views": views,
        "likes": likes,
        "retention_rate": retention_rate,
        "subscribers_gained": subscribers_gained,
        "platform": platform,
        "viral_score": 0
    }
    db["shorts"].append(short)
    save_database(db)
    return short["id"]

def update_short_stats(short_id, views=None, likes=None, retention_rate=None, subscribers_gained=None):
    """Met a jour les stats d'un short"""
    db = load_database()
    for short in db["shorts"]:
        if short["id"] == short_id:
            if views is not None:
                short["views"] = views
            if likes is not None:
                short["likes"] = likes
            if retention_rate is not None:
                short["retention_rate"] = retention_rate
            if subscribers_gained is not None:
                short["subscribers_gained"] = subscribers_gained
            # Calcul du score viral
            short["viral_score"] = calculate_viral_score(short)
            save_database(db)
            return True
    return False

def calculate_viral_score(short):
    """Calcule un score viral base sur les performances"""
    score = 0
    if short["views"] > 1000:
        score += 20
    if short["views"] > 10000:
        score += 30
    if short["retention_rate"] > 50:
        score += 25
    if short["retention_rate"] > 70:
        score += 25
    if short["likes"] > short["views"] * 0.05:
        score += 15
    if short["subscribers_gained"] > 10:
        score += 15
    return min(score, 100)

def get_best_performing_shorts(limit=5):
    """Recupere les meilleurs shorts par score viral"""
    db = load_database()
    sorted_shorts = sorted(db["shorts"], key=lambda x: x.get("viral_score", 0), reverse=True)
    return sorted_shorts[:limit]

def get_analytics_summary():
    """Resume des analytics globales"""
    db = load_database()
    shorts = db["shorts"]
    if not shorts:
        return {
            "total_shorts": 0,
            "total_views": 0,
            "total_likes": 0,
            "avg_retention": 0,
            "total_subscribers": 0,
            "best_score": 0
        }
    
    total_views = sum(s["views"] for s in shorts)
    total_likes = sum(s["likes"] for s in shorts)
    avg_retention = sum(s["retention_rate"] for s in shorts) / len(shorts)
    total_subscribers = sum(s["subscribers_gained"] for s in shorts)
    best_score = max(s.get("viral_score", 0) for s in shorts)
    
    return {
        "total_shorts": len(shorts),
        "total_views": total_views,
        "total_likes": total_likes,
        "avg_retention": round(avg_retention, 1),
        "total_subscribers": total_subscribers,
        "best_score": best_score
    }

# ============================================
# IA AUTO-OPTIMISATION
# ============================================

def analyze_viral_patterns():
    """Analyse les patterns des videos virales"""
    db = load_database()
    shorts = db["shorts"]
    
    if len(shorts) < 3:
        return None
    
    # Analyser les hooks des meilleures videos
    best_shorts = [s for s in shorts if s.get("viral_score", 0) > 50]
    if not best_shorts:
        return None
    
    patterns = {
        "successful_hooks": [],
        "successful_ctas": [],
        "best_topics": [],
        "avg_duration": 0,
        "retention_threshold": 0
    }
    
    for short in best_shorts:
        script = short.get("script", {})
        segments = script.get("segments", [])
        for seg in segments:
            if seg.get("type") == "hook":
                patterns["successful_hooks"].append(seg.get("text", ""))
            if seg.get("type") == "cta":
                patterns["successful_ctas"].append(seg.get("text", ""))
        patterns["best_topics"].append(short.get("topic", ""))
    
    patterns["retention_threshold"] = sum(s["retention_rate"] for s in best_shorts) / len(best_shorts)
    
    return patterns

def generate_optimized_script(topic, viral_patterns=None):
    """Genere un script optimise base sur les patterns viraux"""
    
    # Construire le prompt d'optimisation
    optimization_context = ""
    if viral_patterns:
        optimization_context = f"""
PATTERNS VIRALS IDENTIFIES (utilise-les pour optimiser ce script) :
- Hooks qui ont fonctionne : {viral_patterns.get('successful_hooks', [])[:3]}
- CTAs qui ont fonctionne : {viral_patterns.get('successful_ctas', [])[:3]}
- Sujets populaires : {viral_patterns.get('best_topics', [])[:3]}
- Taux de retention moyen des videos virales : {viral_patterns.get('retention_threshold', 0)}%

REGLES D'OPTIMISATION :
1. Le hook doit etre SIMILAIRE en style aux hooks qui ont fonctionne
2. Le CTA doit reprendre les formules gagnantes
3. Les faits doivent etre encore plus percutants
4. Cible un taux de retention de 70%+
"""
    
    return optimization_context

# ============================================
# CSS MODERNE - INTERFACE GLASSMORPHISM
# ============================================

CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;900&display=swap');

.stApp {
    background: linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%);
    font-family: 'Inter', sans-serif;
}

.glass-card {
    background: rgba(255, 255, 255, 0.05);
    backdrop-filter: blur(20px);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 24px;
    padding: 24px;
    margin: 16px 0;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
}

.glass-card-success {
    background: rgba(34, 197, 94, 0.1);
    border: 1px solid rgba(34, 197, 94, 0.3);
}

.glass-card-warning {
    background: rgba(234, 179, 8, 0.1);
    border: 1px solid rgba(234, 179, 8, 0.3);
}

.neon-title {
    font-size: 3rem;
    font-weight: 900;
    text-align: center;
    color: #fff;
    text-shadow: 0 0 20px rgba(147, 51, 234, 0.5),
                 0 0 40px rgba(147, 51, 234, 0.3),
                 0 0 60px rgba(147, 51, 234, 0.1);
    margin-bottom: 8px;
    letter-spacing: -2px;
}

.neon-subtitle {
    text-align: center;
    color: rgba(255, 255, 255, 0.6);
    font-size: 1rem;
    font-weight: 400;
    margin-bottom: 32px;
}

.stat-card {
    background: rgba(255, 255, 255, 0.08);
    border-radius: 16px;
    padding: 20px;
    text-align: center;
    border: 1px solid rgba(255, 255, 255, 0.1);
}

.stat-number {
    font-size: 2.5rem;
    font-weight: 900;
    color: #a78bfa;
    text-shadow: 0 0 20px rgba(167, 139, 250, 0.5);
}

.stat-label {
    font-size: 0.85rem;
    color: rgba(255, 255, 255, 0.6);
    margin-top: 4px;
}

.stButton > button {
    width: 100%;
    height: 56px;
    font-size: 1.1rem;
    font-weight: 700;
    border-radius: 16px;
    border: none;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    box-shadow: 0 4px 20px rgba(102, 126, 234, 0.4);
    transition: all 0.3s ease;
    text-transform: uppercase;
    letter-spacing: 1px;
}

.stButton > button:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 30px rgba(102, 126, 234, 0.6);
}

.stButton > button:active {
    transform: translateY(0);
}

.secondary-btn > button {
    background: rgba(255, 255, 255, 0.1);
    border: 1px solid rgba(255, 255, 255, 0.2);
    box-shadow: none;
}

.secondary-btn > button:hover {
    background: rgba(255, 255, 255, 0.15);
    box-shadow: 0 4px 20px rgba(255, 255, 255, 0.1);
}

.stTextInput > div > div > input {
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 16px;
    color: white;
    padding: 16px 20px;
    font-size: 1rem;
}

.stTextInput > div > div > input::placeholder {
    color: rgba(255, 255, 255, 0.4);
}

.stProgress > div > div {
    background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
    border-radius: 10px;
    height: 8px;
}

.stAlert {
    border-radius: 16px;
    border: 1px solid rgba(255, 255, 255, 0.1);
    background: rgba(255, 255, 255, 0.05) !important;
}

.streamlit-expanderHeader {
    background: rgba(255, 255, 255, 0.05);
    border-radius: 16px;
    border: 1px solid rgba(255, 255, 255, 0.1);
    color: white;
}

video, img {
    border-radius: 20px;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
}

hr {
    border: none;
    height: 1px;
    background: linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.2) 50%, transparent 100%);
    margin: 32px 0;
}

.stDownloadButton > button {
    background: rgba(255, 255, 255, 0.1);
    border: 1px solid rgba(255, 255, 255, 0.2);
    border-radius: 12px;
    color: white;
    font-weight: 600;
}

.stDownloadButton > button:hover {
    background: rgba(255, 255, 255, 0.2);
}

.metric-positive {
    color: #22c55e;
    font-weight: 700;
}

.metric-negative {
    color: #ef4444;
    font-weight: 700;
}

#MainMenu, footer, header {visibility: hidden;}
</style>
"""

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
# 1. GENERATION DU SCRIPT (OpenRouter API)
# ============================================

def generate_script(topic, use_optimization=False):
    if not OPENROUTER_API_KEY:
        return None, "Cle API OpenRouter manquante."

    # Analyser les patterns viraux si optimisation activee
    viral_patterns = None
    optimization_context = ""
    if use_optimization:
        viral_patterns = analyze_viral_patterns()
        optimization_context = generate_optimized_script(topic, viral_patterns)

    system_prompt = f"""Tu es un createur de contenu viral sur TikTok/YouTube Shorts, specialise dans la niche "cerveau, psychologie et faits fascinants".

TON :
- Francais jeune et moderne (style TikTok 2024/2025)
- Naturel, comme si tu parlais a un pote
- ENTHOUSIASTE et DYNAMIQUE
- JAMAIS vulgaire, JAMAIS dinsultes
- Respectueux des valeurs islamiques :
  * Ne mentionne jamais "Mere Nature" ou "la nature a cree"
  * Ne dis jamais que quelque chose a ete cree par hasard
  * Si tu parles de creation, dis "Allah a cree" ou evite le sujet
  * Pas de blaspheme, pas de contenu haram
  * Pas de references religieuses forcees, sois naturel
- Utilise des expressions modernes : "c est fou ca", "incroyable", "tu vas pas y croire", "la science confirme"
- Style narratif AMUSANT, comme si tu racontais a ton frere au cafe

{optimization_context}

Genere un script de SHORT (50-55 secondes, environ 130 mots) au format JSON strict :

{{
  "title": "Titre accrocheur (3-5 mots max)",
  "segments": [
    {{"type": "hook", "text": "Phrase choc (8-12 mots)", "emoji": "🧠", "color": "#FFD700", "effect": "zoom"}},
    {{"type": "fact", "text": "Fait 1 (15-20 mots)", "emoji": "1️⃣", "color": "#FFFFFF", "effect": "shake"}},
    {{"type": "fact", "text": "Fait 2 (15-20 mots)", "emoji": "2️⃣", "color": "#FFFFFF", "effect": "flash"}},
    {{"type": "fact", "text": "Fait 3 (15-20 mots)", "emoji": "3️⃣", "color": "#FFFFFF", "effect": "zoom"}},
    {{"type": "cta", "text": "CTA engageant (8-10 mots)", "emoji": "🔥", "color": "#00FFFF", "effect": "none"}}
  ]
}}

REGLES STRICTES :
- Hook : question choc OU fait contre-intuitif
- Faits : courts, percutants, avec chiffres
- CTA : incite a sabonner
- PAS de markdown dans le JSON
- Reponds UNIQUEMENT avec le JSON"""

    user_prompt = f"Sujet du Short : {topic}"

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://shorts-viraux.onrender.com",
        "X-Title": "Shorts Viraux"
    }

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.9,
        "max_tokens": 800
    }

    try:
        response = requests.post(OPENROUTER_API_URL, headers=headers, json=payload, timeout=30)
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
        return None, f"Erreur OpenRouter: {str(e)}"

# ============================================
# 2. GENERATION AUDIO (Edge TTS - GRATUIT)
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
        return None, "Cle API Pexels manquante."

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

def create_ken_burns_clip(image_path, duration, zoom_direction="in"):
    clip = ImageClip(image_path).set_duration(duration)
    if zoom_direction == "in":
        def zoom_func(t):
            return 1.0 + 0.22 * (t / duration)
    elif zoom_direction == "out":
        def zoom_func(t):
            return 1.22 - 0.22 * (t / duration)
    else:
        def zoom_func(t):
            return 1.1
    clip = clip.resize(zoom_func)
    clip = clip.set_position("center")
    return clip

def apply_shake(clip, intensity=3):
    def shake_func(t):
        import random
        random.seed(int(t * 100))
        dx = random.randint(-intensity, intensity)
        dy = random.randint(-intensity, intensity)
        return (dx, dy)
    return clip.set_position(shake_func)

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
    zoom_directions = ["in", "out", "in", "out", "pan"]

    for i, (seg, seg_dur) in enumerate(zip(segments, seg_durations)):
        img_path = image_paths[i % len(image_paths)]
        direction = zoom_directions[i % len(zoom_directions)]
        bg = create_ken_burns_clip(img_path, seg_dur, direction)

        if i > 0:
            effect = seg.get("effect", "none")
            if effect == "flash":
                flash = ColorClip(size=(W, H), color=(255, 255, 255)).set_duration(0.08)
                flash = flash.set_opacity(0.3)
                clips.append(flash)
                current_time += 0.08
            elif effect == "shake":
                shake_trans = ColorClip(size=(W, H), color=(20, 20, 30)).set_duration(0.15)
                clips.append(shake_trans)
                current_time += 0.15
            else:
                zoom_trans = ColorClip(size=(W, H), color=(0, 0, 0)).set_duration(0.05)
                clips.append(zoom_trans)
                current_time += 0.05

        emoji_clip = TextClip(
            seg["emoji"],
            fontsize=100,
            color="white",
            font="DejaVu-Sans-Bold" if FONT_PATH else "Arial-Bold",
            stroke_color="black",
            stroke_width=3
        ).set_duration(seg_dur).set_position(("center", 100))

        if seg["type"] == "hook":
            bg_color = (255, 50, 50)
            bg_opacity = 0.35
        elif seg["type"] == "cta":
            bg_color = (0, 150, 255)
            bg_opacity = 0.35
        else:
            bg_color = (0, 0, 0)
            bg_opacity = 0.55

        txt_bg = ColorClip(size=(1000, 380), color=bg_color)
        txt_bg = txt_bg.set_opacity(bg_opacity).set_duration(seg_dur)
        txt_bg = txt_bg.set_position("center")

        color = seg.get("color", "#FFFFFF")
        wrapped_text = "\n".join(textwrap.wrap(seg["text"], width=17))

        text_len = len(seg["text"])
        if text_len < 30:
            font_size = 72
        elif text_len < 60:
            font_size = 64
        else:
            font_size = 56

        txt_clip = TextClip(
            wrapped_text,
            fontsize=font_size,
            color=color,
            stroke_color="black",
            stroke_width=4,
            font="DejaVu-Sans-Bold" if FONT_PATH else "Arial-Bold",
            size=(950, None),
            method="caption",
            align="center"
        ).set_duration(seg_dur).set_position("center")

        effect = seg.get("effect", "none")
        if effect == "shake":
            txt_clip = apply_shake(txt_clip, intensity=4)

        extra_clips = [bg, txt_bg, txt_clip, emoji_clip]

        if seg["type"] == "fact":
            fact_num = sum(1 for s in segments[:i+1] if s["type"] == "fact")
            counter = TextClip(
                str(fact_num),
                fontsize=320,
                color=(255, 255, 255),
                font="DejaVu-Sans-Bold" if FONT_PATH else "Arial-Bold",
                stroke_color="black",
                stroke_width=5
            ).set_duration(seg_dur).set_position((50, 150))
            counter = counter.set_opacity(0.12)
            extra_clips.append(counter)

        progress_width = int(W * ((current_time + seg_dur) / total_duration))
        progress_bar = ColorClip(size=(progress_width, 22), color=(255, 80, 80))
        progress_bar = progress_bar.set_duration(seg_dur).set_position(("left", H - 22))
        extra_clips.append(progress_bar)

        time_left = int(total_duration - current_time - seg_dur)
        time_text = TextClip(
            f"{time_left}s",
            fontsize=35,
            color=(255, 255, 255),
            font="DejaVu-Sans-Bold" if FONT_PATH else "Arial-Bold",
            stroke_color="black",
            stroke_width=2
        ).set_duration(seg_dur).set_position((W - 120, 50))
        extra_clips.append(time_text)

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
    thumb = Image.new("RGB", (W, H), (15, 15, 25))
    draw = ImageDraw.Draw(thumb)

    if image_paths:
        bg_img = Image.open(image_paths[0]).convert("RGB")
        bg_img = bg_img.resize((W, H), Image.LANCZOS)
        bg_img = bg_img.filter(ImageFilter.GaussianBlur(radius=18))
        enhancer = ImageEnhance.Brightness(bg_img)
        bg_img = enhancer.enhance(0.35)
        thumb.paste(bg_img)

    for y in range(H):
        alpha = int(200 * (y / H))
        draw.line([(0, y), (W, y)], fill=(0, 0, 0, alpha))

    try:
        font_title = ImageFont.truetype(FONT_PATH, 120) if FONT_PATH else ImageFont.load_default()
        font_sub = ImageFont.truetype(FONT_PATH, 55) if FONT_PATH else ImageFont.load_default()
        font_emoji = ImageFont.truetype(FONT_PATH, 220) if FONT_PATH else ImageFont.load_default()
    except:
        font_title = ImageFont.load_default()
        font_sub = ImageFont.load_default()
        font_emoji = ImageFont.load_default()

    draw.text((W//2, 220), "🧠", fill=(255, 215, 0), font=font_emoji, anchor="mm")

    title_upper = title.upper()
    words = title_upper.split()
    lines = []
    current_line = []
    for word in words:
        test_line = " ".join(current_line + [word])
        bbox = draw.textbbox((0, 0), test_line, font=font_title)
        if bbox[2] - bbox[0] < 950:
            current_line.append(word)
        else:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]
    if current_line:
        lines.append(" ".join(current_line))

    y_pos = 480
    for line in lines:
        for dx in [-5, -4, -3, -2, -1, 0, 1, 2, 3, 4, 5]:
            for dy in [-5, -4, -3, -2, -1, 0, 1, 2, 3, 4, 5]:
                if abs(dx) + abs(dy) <= 5:
                    draw.text((W//2 + dx, y_pos + dy), line, fill=(0, 0, 0), font=font_title, anchor="mm")
        draw.text((W//2, y_pos), line, fill=(255, 255, 255), font=font_title, anchor="mm")
        y_pos += 150

    draw.text((W//2, y_pos + 50), "FAIT SCIENTIFIQUE", fill=(255, 215, 0), font=font_sub, anchor="mm")
    draw.rectangle([250, y_pos + 120, 830, y_pos + 132], fill=(255, 60, 60))
    draw.text((W//2, H - 180), "⚡", fill=(255, 215, 0), font=font_emoji, anchor="mm")

    thumb.save(output_path, quality=95)
    return output_path

# ============================================
# 6. INTERFACE STREAMLIT - DASHBOARD COMPLET
# ============================================

def show_dashboard():
    """Affiche le tableau de bord analytics"""
    st.markdown("<div class='neon-title'>📊 DASHBOARD</div>", unsafe_allow_html=True)
    st.markdown("<div class='neon-subtitle'>Suivi de tes performances virales</div>", unsafe_allow_html=True)
    
    analytics = get_analytics_summary()
    db = load_database()
    
    # Cartes de stats
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-number">{analytics['total_shorts']}</div>
            <div class="stat-label">Shorts crees</div>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-number">{analytics['total_views']:,}</div>
            <div class="stat-label">Vues totales</div>
        </div>
        """, unsafe_allow_html=True)
    with col3:
        retention_color = "metric-positive" if analytics['avg_retention'] > 50 else "metric-negative"
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-number {retention_color}">{analytics['avg_retention']}%</div>
            <div class="stat-label">Retention moyenne</div>
        </div>
        """, unsafe_allow_html=True)
    with col4:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-number">{analytics['total_subscribers']}</div>
            <div class="stat-label">Abonnes gagnes</div>
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("<hr>", unsafe_allow_html=True)
    
    # Meilleurs shorts
    st.subheader("🏆 Tes meilleurs shorts")
    best_shorts = get_best_performing_shorts(5)
    
    if best_shorts:
        for i, short in enumerate(best_shorts, 1):
            with st.container():
                st.markdown("<div class='glass-card'>", unsafe_allow_html=True)
                col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
                with col1:
                    st.write(f"**#{i} {short['title']}**")
                    st.caption(f"Sujet: {short['topic']}")
                with col2:
                    st.write(f"👁️ {short['views']:,}")
                with col3:
                    retention = short.get('retention_rate', 0)
                    color = "metric-positive" if retention > 50 else "metric-negative"
                    st.write(f"<span class='{color}'>📊 {retention}%</span>", unsafe_allow_html=True)
                with col4:
                    score = short.get('viral_score', 0)
                    st.write(f"🔥 {score}/100")
                st.markdown("</div>", unsafe_allow_html=True)
    else:
        st.info("Aucun short enregistre encore. Genere ton premier short !")
    
    # Formulaire pour mettre a jour les stats
    st.markdown("<hr>", unsafe_allow_html=True)
    st.subheader("📝 Mettre a jour les stats d'un short")
    
    if db["shorts"]:
        short_options = {f"#{s['id']} - {s['title']}": s['id'] for s in db["shorts"]}
        selected = st.selectbox("Choisir un short", list(short_options.keys()))
        short_id = short_options[selected]
        
        col1, col2, col3 = st.columns(3)
        with col1:
            new_views = st.number_input("Vues", min_value=0, value=0)
        with col2:
            new_retention = st.number_input("Retention %", min_value=0, max_value=100, value=0)
        with col3:
            new_subs = st.number_input("Abonnes gagnes", min_value=0, value=0)
        
        if st.button("Mettre a jour les stats", use_container_width=True):
            update_short_stats(short_id, views=new_views, retention_rate=new_retention, subscribers_gained=new_subs)
            st.success("Stats mises a jour !")
            st.rerun()
    else:
        st.info("Genere d'abord un short pour pouvoir suivre ses stats.")

def show_generator():
    """Affiche le generateur de shorts"""
    st.markdown("<div class='neon-title'>🧠 SHORTS VIRAUX</div>", unsafe_allow_html=True)
    st.markdown("<div class='neon-subtitle'>Cerveau & Psychologie · Genere des Shorts viraux en un clic</div>", unsafe_allow_html=True)
    
    # Option d'optimisation IA
    db = load_database()
    has_data = len(db["shorts"]) >= 3
    
    use_optimization = False
    if has_data:
        with st.container():
            st.markdown("<div class='glass-card glass-card-success'>", unsafe_allow_html=True)
            patterns = analyze_viral_patterns()
            if patterns:
                st.write("🧠 **IA d'optimisation active**")
                st.caption(f"Analyse de {len([s for s in db['shorts'] if s.get('viral_score', 0) > 50])} videos virales")
                use_optimization = st.toggle("Utiliser l'optimisation IA", value=True)
            st.markdown("</div>", unsafe_allow_html=True)
    
    missing = []
    if not OPENROUTER_API_KEY:
        missing.append("OPENROUTER_API_KEY")
    if not PEXELS_API_KEY:
        missing.append("PEXELS_API_KEY")

    if missing:
        with st.container():
            st.markdown("<div class='glass-card'>", unsafe_allow_html=True)
            st.warning("Configuration requise")
            with st.expander("Comment configurer les cles API"):
                st.markdown(f"""
                **Cles manquantes :** {', '.join(missing)}

                **1. OpenRouter API** (gratuit) :
                - Va sur openrouter.ai
                - Cree un compte → Settings → Keys → Create Key
                - Copie la cle (commence par sk-or-...)

                **2. Pexels API** (gratuit) :
                - Va sur pexels.com/api
                - Join → API Key

                **3. Dans Render :**
                - Settings → Environment Variables
                - Ajoute chaque cle
                """)
            st.markdown("</div>", unsafe_allow_html=True)
        st.stop()

    with st.container():
        st.markdown("<div class='glass-card'>", unsafe_allow_html=True)
        col1, col2 = st.columns([3, 1])
        with col1:
            topic = st.text_input(
                "Sujet du Short",
                placeholder="Ex: pourquoi tu procrastines",
                label_visibility="collapsed"
            )
        with col2:
            st.markdown("<div class='secondary-btn'>", unsafe_allow_html=True)
            random_topic = st.button("🎲 Aleatoire", use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)

        if random_topic or not topic:
            topic = random.choice(NICHE_TOPICS)
            st.info(f"Sujet choisi : **{topic}**")

        st.markdown("</div>", unsafe_allow_html=True)

    with st.container():
        st.markdown("<div class='glass-card' style='padding: 8px;'>", unsafe_allow_html=True)
        generate_btn = st.button(
            "🎬 GENERER MON SHORT",
            type="primary",
            use_container_width=True
        )
        st.markdown("</div>", unsafe_allow_html=True)

    if generate_btn and topic:
        with st.container():
            st.markdown("<div class='glass-card'>", unsafe_allow_html=True)
            progress_bar = st.progress(0)
            status = st.empty()

            try:
                status.info("📝 Generation du script viral...")
                progress_bar.progress(10)
                script, error = generate_script(topic, use_optimization=use_optimization)
                if error:
                    st.error(error)
                    st.stop()

                st.success(f"✅ Script genere : **{script['title']}**")
                
                # Sauvegarder dans la base de donnees
                short_id = add_short_to_db(
                    title=script['title'],
                    topic=topic,
                    script=script
                )
                st.caption(f"Short #{short_id} enregistre dans le dashboard")

                status.info("🔊 Generation de la voix off...")
                progress_bar.progress(30)
                full_text = " ".join([seg["text"] for seg in script["segments"]])
                audio_path = os.path.join(TEMP_DIR, "voice.mp3")
                generate_audio(full_text, audio_path)

                status.info("🖼 Recherche d'images...")
                progress_bar.progress(50)
                image_paths, error = fetch_images(topic, count=5)
                if error:
                    st.error(error)
                    st.stop()

                status.info("🎞 Montage video dynamique...")
                progress_bar.progress(65)
                video_path = os.path.join(TEMP_DIR, "short.mp4")
                create_video(script, audio_path, image_paths, video_path)

                status.info("🖼 Creation de la miniature...")
                progress_bar.progress(85)
                thumb_path = os.path.join(TEMP_DIR, "thumbnail.jpg")
                create_thumbnail(script["title"], image_paths, thumb_path)

                progress_bar.progress(100)
                status.success("🎉 Short genere avec succes !")
                st.markdown("</div>", unsafe_allow_html=True)

                st.markdown("<hr>", unsafe_allow_html=True)

                with st.container():
                    st.markdown("<div class='glass-card'>", unsafe_allow_html=True)
                    st.subheader("📺 Previsualisation")
                    st.video(video_path)
                    st.markdown("</div>", unsafe_allow_html=True)

                with st.container():
                    st.markdown("<div class='glass-card'>", unsafe_allow_html=True)
                    st.subheader("🖼 Miniature")
                    st.image(thumb_path, use_column_width=True)
                    st.markdown("</div>", unsafe_allow_html=True)

                with st.container():
                    st.markdown("<div class='glass-card'>", unsafe_allow_html=True)
                    col_dl1, col_dl2 = st.columns(2)
                    with col_dl1:
                        with open(video_path, "rb") as file:
                            st.download_button(
                                label="📥 Video",
                                data=file,
                                file_name=f"short_{script['title'].replace(' ', '_')}.mp4",
                                mime="video/mp4",
                                use_container_width=True
                            )
                    with col_dl2:
                        with open(thumb_path, "rb") as file:
                            st.download_button(
                                label="📥 Miniature",
                                data=file,
                                file_name=f"thumb_{script['title'].replace(' ', '_')}.jpg",
                                mime="image/jpeg",
                                use_container_width=True
                            )
                    st.markdown("</div>", unsafe_allow_html=True)

                with st.container():
                    st.markdown("<div class='glass-card glass-card-warning'>", unsafe_allow_html=True)
                    st.subheader("📊 Suis tes stats")
                    st.write("Apres avoir publie ton short, retourne dans le **Dashboard** pour enregistrer :")
                    st.write("- Nombre de vues")
                    st.write("- Taux de retention")
                    st.write("- Abonnes gagnes")
                    st.write("L'IA utilisera ces donnees pour optimiser tes futurs shorts !")
                    st.markdown("</div>", unsafe_allow_html=True)

                st.info("💡 Telecharge les fichiers et upload-les sur YouTube Shorts ou TikTok.")

            except Exception as e:
                st.error(f"❌ Erreur : {str(e)}")
                st.exception(e)
                st.markdown("</div>", unsafe_allow_html=True)

def main():
    st.set_page_config(
        page_title="Shorts Viraux Pro",
        page_icon="🧠",
        layout="centered",
        initial_sidebar_state="collapsed"
    )

    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    
    # Navigation
    page = st.sidebar.radio("Navigation", ["🎬 Generateur", "📊 Dashboard", "🧠 Optimisation IA"])
    
    if page == "🎬 Generateur":
        show_generator()
    elif page == "📊 Dashboard":
        show_dashboard()
    elif page == "🧠 Optimisation IA":
        show_optimization()

def show_optimization():
    """Affiche les conseils d'optimisation IA"""
    st.markdown("<div class='neon-title'>🧠 OPTIMISATION IA</div>", unsafe_allow_html=True)
    st.markdown("<div class='neon-subtitle'>Analyse et recommandations pour plus de viralite</div>", unsafe_allow_html=True)
    
    patterns = analyze_viral_patterns()
    db = load_database()
    
    if not patterns:
        st.info("Genere au moins 3 shorts et enregistre leurs stats pour activer l'optimisation IA.")
        return
    
    with st.container():
        st.markdown("<div class='glass-card glass-card-success'>", unsafe_allow_html=True)
        st.subheader("✅ Ce qui fonctionne chez toi")
        
        if patterns.get('successful_hooks'):
            st.write("**🎯 Hooks gagnants :**")
            for hook in patterns['successful_hooks'][:3]:
                st.write(f"- {hook}")
        
        if patterns.get('successful_ctas'):
            st.write("**📢 CTAs gagnants :**")
            for cta in patterns['successful_ctas'][:3]:
                st.write(f"- {cta}")
        
        if patterns.get('best_topics'):
            st.write("**🔥 Sujets qui performent :**")
            for topic in patterns['best_topics'][:3]:
                st.write(f"- {topic}")
        
        st.write(f"**📊 Retention moyenne des videos virales :** {patterns.get('retention_threshold', 0):.1f}%")
        st.markdown("</div>", unsafe_allow_html=True)
    
    with st.container():
        st.markdown("<div class='glass-card'>", unsafe_allow_html=True)
        st.subheader("💡 Recommandations de l'IA")
        
        recommendations = []
        
        if patterns.get('retention_threshold', 0) < 50:
            recommendations.append("🎯 **Raccourcis le hook** - Les 3 premieres secondes doivent choquer")
            recommendations.append("⚡ **Plus de dynamisme** - Change de visuel toutes les 2 secondes max")
        
        if not any("?" in h for h in patterns.get('successful_hooks', [])):
            recommendations.append("❓ **Utilise des questions** dans tes hooks pour creer du suspense")
        
        recommendations.append("🔢 **Mets des chiffres precis** - '80%' marche mieux que 'beaucoup'")
        recommendations.append("😱 **Emotions fortes** - Peur, surprise, curiosite = retention")
        recommendations.append("⏱️ **Max 55 secondes** - Au-dela, la retention chute")
        
        for rec in recommendations:
            st.write(rec)
        
        st.markdown("</div>", unsafe_allow_html=True)
    
    # Conseils generaux de viralite
    with st.container():
        st.markdown("<div class='glass-card'>", unsafe_allow_html=True)
        st.subheader("📚 Methodes de viralite analysees")
        
        st.write("""
        **Sans musique (respectueux islamique) :**
        
        1. **Hook visuel 0-1s** - Flash blanc + zoom rapide d'entree
        2. **Voix off enthouiaste** - Variation de ton, pas monotone
        3. **Texte mot-a-mot** - Synchronise avec la voix
        4. **Emojis qui pop** - 🧠 ⚡ 💡 sur les mots cles
        5. **Changement visuel toutes les 1-3s** - Zero temps mort
        6. **Compteur de temps** - Cree de l'urgence
        7. **CTA direct** - 'Abonne-toi' pas 'n'oublie pas de...'
        8. **Pause avant revelation** - 0.5s de silence = suspense
        """)
        st.markdown("</div>", unsafe_allow_html=True)

if __name__ == "__main__":
    main()
