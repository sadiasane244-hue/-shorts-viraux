"""
SHORTS VIRALS - Générateur Automatique
Niche: Cerveau, Psychologie & Faits
Voix: Edge TTS (gratuit)
LLM: OpenRouter API (inclusionai/ling-3.0-flash-fn:free)
Interface: Moderne glassmorphism + Couleurs dynamiques
Features: Auto-optimisation IA, Dashboard Analytics, Couleurs changeantes
Deployable sur Render
"""

import streamlit as st
import requests
import os
import random
import asyncio
import json
import time
from datetime import datetime, timedelta
import hashlib

# ============================================================
# CONFIGURATION - COULEURS DYNAMIQUES (CHANGE À CHAQUE MAJ)
# ============================================================

# Génère une palette de couleurs unique basée sur le hash du fichier
# Ça change à CHAQUE modification du code → tu vois immédiatement si c'est actif
def generate_dynamic_colors():
    """Génère une palette unique basée sur le contenu actuel du fichier"""
    # On utilise le timestamp de modification du fichier comme seed
    # Sur Render, chaque déploiement = nouveau fichier = nouvelles couleurs
    try:
        import inspect
        # Récupère le contenu du fichier courant
        current_file = inspect.getfile(lambda: None)
        if os.path.exists(current_file):
            with open(current_file, 'rb') as f:
                file_hash = hashlib.md5(f.read()).hexdigest()[:8]
        else:
            file_hash = str(int(time.time()))[:8]
    except:
        file_hash = str(int(time.time()))[:8]
    
    # Convertit le hash en couleurs HSL harmonieuses
    seed = int(file_hash, 16)
    
    def hsl_to_hex(h, s, l):
        h = h / 360
        s = s / 100
        l = l / 100
        if s == 0:
            r = g = b = l
        else:
            def hue_to_rgb(p, q, t):
                if t < 0: t += 1
                if t > 1: t -= 1
                if t < 1/6: return p + (q - p) * 6 * t
                if t < 1/2: return q
                if t < 2/3: return p + (q - p) * (2/3 - t) * 6
                return p
            q = l * (1 + s) if l < 0.5 else l + s - l * s
            p = 2 * l - q
            r = hue_to_rgb(p, q, h + 1/3)
            g = hue_to_rgb(p, q, h)
            b = hue_to_rgb(p, q, h - 1/3)
        return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
    
    # Génère une palette cohérente
    base_hue = (seed % 360)
    
    colors = {
        'primary': hsl_to_hex(base_hue, 85, 55),
        'secondary': hsl_to_hex((base_hue + 30) % 360, 80, 60),
        'accent': hsl_to_hex((base_hue + 180) % 360, 90, 65),
        'gradient_start': hsl_to_hex(base_hue, 70, 15),
        'gradient_end': hsl_to_hex((base_hue + 40) % 360, 60, 8),
        'card_bg': f"rgba({20 + (seed % 30)}, {15 + ((seed >> 8) % 25)}, {30 + ((seed >> 16) % 20)}, 0.25)",
        'glow': hsl_to_hex(base_hue, 100, 70),
        'text_primary': '#ffffff',
        'text_secondary': '#e0e0e0',
        'success': hsl_to_hex((base_hue + 120) % 360, 80, 60),
        'warning': hsl_to_hex((base_hue + 60) % 360, 90, 60),
        'error': hsl_to_hex((base_hue + 0) % 360, 90, 60),
    }
    
    return colors, file_hash

# Génère les couleurs dynamiques
COLORS, FILE_HASH = generate_dynamic_colors()

# ============================================================
# CONFIGURATION API
# ============================================================

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "inclusionai/ling-3.0-flash-fn:free"

# ============================================================
# BASE DE DONNÉES JSON (stats)
# ============================================================

DB_FILE = "shorts_stats.json"

def load_stats():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {
        "shorts": [],
        "total_views": 0,
        "total_subscribers": 0,
        "avg_retention": 0,
        "best_hook": "",
        "best_cta": "",
        "generated_count": 0,
        "published_count": 0,
        "viral_patterns": []
    }

def save_stats(stats):
    with open(DB_FILE, 'w') as f:
        json.dump(stats, f, indent=2)

# ============================================================
# GÉNÉRATION DU SCRIPT VIRAL (LLM)
# ============================================================

def generate_script(subject=None):
    """Génère un script viral de 45-60 secondes"""
    
    if not OPENROUTER_API_KEY:
        return None, "❌ Clé OpenRouter manquante. Ajoute OPENROUTER_API_KEY dans les variables d'environnement Render."
    
    topics = [
        "pourquoi ton cerveau oublie 80% de ce que tu lis",
        "l'effet de serreau qui te manipule sans que tu le saches",
        "pourquoi tu procrastines et comment arrêter",
        "le secret de la mémoire des champions",
        "pourquoi tu prends de mauvaises décisions quand tu es stressé",
        "l'illusion de la multitâche",
        "pourquoi tu te réveilles fatigué même après 8h de sommeil",
        "le pouvoir des habitudes atomiques",
        "pourquoi les réseaux sociaux rendent ton cerveau paresseux",
        "l'effet Dunning-Kruger expliqué simplement"
    ]
    
    if not subject:
        subject = random.choice(topics)
    
    system_prompt = """Tu es un expert en création de contenu viral pour YouTube Shorts et TikTok.
Tu crées des scripts courts (45-60 secondes), captivants, éducatifs sur le cerveau et la psychologie.
Règles STRICTES:
- Hook viral en 3 premières secondes (question choc, fait contre-intuitif)
- 3 faits numérotés, courts et percutants
- Call-to-action final subtil
- Ton: naturel, moderne, sans insulte, sans blasphème, respectueux des valeurs islamiques
- Pas de "Mère Nature" → dis "Allah a créé" ou évite totalement
- Pas de références à l'alcool, aux relations haram, etc.
- Mots-clés à surligner pour le montage (entre **asterisques**)
- Durée: 45-60 secondes à lire"""

    user_prompt = f"""Crée un script viral sur: {subject}

Format attendu:
TITRE: [titre accrocheur]
HOOK: [phrase d'accroche en 3 secondes]
FAIT 1: [premier fait avec **mots-clés**]
FAIT 2: [deuxième fait avec **mots-clés**]
FAIT 3: [troisième fait avec **mots-clés**]
CTA: [call-to-action]
HASHTAGS: [5 hashtags viraux]

Le script doit être prêt à être lu à voix haute."""

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
        "temperature": 0.9,
        "max_tokens": 800
    }
    
    try:
        response = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            if 'choices' in data and len(data['choices']) > 0:
                script = data['choices'][0]['message']['content']
                return script, None
            else:
                return None, f"❌ Réponse vide de l'API. Réponse: {data}"
        elif response.status_code == 401:
            return None, "❌ Erreur 401: Clé API invalide. Vérifie ta clé OpenRouter sur openrouter.ai/keys"
        elif response.status_code == 404:
            return None, f"❌ Erreur 404: Modèle non trouvé. Le modèle '{OPENROUTER_MODEL}' n'est peut-être plus disponible. Essaie un autre modèle gratuit."
        elif response.status_code == 429:
            return None, "❌ Erreur 429: Trop de requêtes. Attends un peu et réessaie."
        else:
            return None, f"❌ Erreur {response.status_code}: {response.text[:200]}"
            
    except requests.exceptions.Timeout:
        return None, "❌ Timeout: L'API met trop de temps à répondre. Réessaie."
    except requests.exceptions.ConnectionError:
        return None, "❌ Erreur de connexion. Vérifie ta connexion internet."
    except Exception as e:
        return None, f"❌ Erreur inattendue: {str(e)}"

# ============================================================
# RECHERCHE D'IMAGES (PEXELS)
# ============================================================

def search_images(query, count=5):
    """Recherche des images stock gratuites sur Pexels"""
    if not PEXELS_API_KEY:
        return []
    
    url = f"https://api.pexels.com/v1/search?query={query}&per_page={count}&orientation=portrait"
    headers = {"Authorization": PEXELS_API_KEY}
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            return [photo['src']['medium'] for photo in data.get('photos', [])]
    except:
        pass
    return []

# ============================================================
# GÉNÉRATION AUDIO (EDGE TTS)
# ============================================================

def generate_audio(text, output_path="audio.mp3"):
    """Génère la voix off avec Edge TTS"""
    try:
        import edge_tts
        import asyncio
        
        voice = "fr-FR-DeniseNeural"  # Voix féminine française naturelle
        
        async def _generate():
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(output_path)
        
        asyncio.run(_generate())
        return output_path
    except Exception as e:
        return None

# ============================================================
# GÉNÉRATION DE LA MINIATURE
# ============================================================

def generate_thumbnail(title, output_path="thumbnail.jpg"):
    """Génère une miniature 9:16 optimisée"""
    try:
        from PIL import Image, ImageDraw, ImageFont
        import textwrap
        
        # Dimensions 9:16 (1080x1920)
        width, height = 1080, 1920
        img = Image.new('RGB', (width, height), COLORS['gradient_start'])
        draw = ImageDraw.Draw(img)
        
        # Dégradé de fond
        for y in range(height):
            ratio = y / height
            r = int(int(COLORS['gradient_start'][1:3], 16) * (1-ratio) + int(COLORS['gradient_end'][1:3], 16) * ratio)
            g = int(int(COLORS['gradient_start'][3:5], 16) * (1-ratio) + int(COLORS['gradient_end'][3:5], 16) * ratio)
            b = int(int(COLORS['gradient_start'][5:7], 16) * (1-ratio) + int(COLORS['gradient_end'][5:7], 16) * ratio)
            draw.line([(0, y), (width, y)], fill=(r, g, b))
        
        # Titre principal
        try:
            font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 80)
            font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 40)
        except:
            font_large = ImageFont.load_default()
            font_small = ImageFont.load_default()
        
        # Glow effect behind text
        wrapped = textwrap.fill(title.upper(), width=12)
        bbox = draw.multilinebbox((0, 0), wrapped, font=font_large)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        x = (width - text_w) // 2
        y = height // 3
        
        # Ombre portée
        for offset in range(5, 0, -1):
            alpha = int(255 * (1 - offset/5) * 0.3)
            draw.multiline_text((x+offset, y+offset), wrapped, font=font_large, fill=(0,0,0))
        
        # Texte principal
        draw.multiline_text((x, y), wrapped, font=font_large, fill=COLORS['glow'])
        
        # Sous-titre
        subtitle = "🧠 PSYCHOLOGIE"
        draw.text((width//2 - 150, y + text_h + 50), subtitle, font=font_small, fill=COLORS['accent'])
        
        img.save(output_path)
        return output_path
    except Exception as e:
        return None

# ============================================================
# MONTAGE VIDÉO (MOVIEPY)
# ============================================================

def create_video(script, images, audio_path, output_path="short.mp4"):
    """Assemble le short final avec montage dynamique"""
    try:
        from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips, CompositeVideoClip, TextClip
        import numpy as np
        
        if not images:
            # Fallback: créer des clips colorés
            images = [None] * 5
        
        # Parse le script pour extraire les segments
        segments = []
        lines = script.split('\n')
        current_segment = {"text": "", "duration": 3}
        
        for line in lines:
            line = line.strip()
            if line.startswith('HOOK:'):
                current_segment = {"text": line.replace('HOOK:', '').strip(), "duration": 3, "type": "hook"}
                segments.append(current_segment)
            elif line.startswith('FAIT'):
                current_segment = {"text": line.split(':', 1)[1].strip() if ':' in line else line, "duration": 4, "type": "fact"}
                segments.append(current_segment)
            elif line.startswith('CTA:'):
                current_segment = {"text": line.replace('CTA:', '').strip(), "duration": 3, "type": "cta"}
                segments.append(current_segment)
        
        if not segments:
            segments = [{"text": "Short viral!", "duration": 10, "type": "hook"}]
        
        clips = []
        for i, seg in enumerate(segments):
            # Image de fond
            if i < len(images) and images[i]:
                try:
                    clip = ImageClip(images[i]).set_duration(seg['duration'])
                except:
                    clip = create_color_clip(seg['duration'])
            else:
                clip = create_color_clip(seg['duration'])
            
            # Zoom dynamique (Ken Burns)
            if seg['type'] == 'hook':
                clip = clip.resize(lambda t: 1 + 0.1 * t / seg['duration'])
            elif seg['type'] == 'fact':
                clip = clip.resize(lambda t: 1 + 0.05 * np.sin(t * 2))
            
            # Texte overlay
            text = seg['text'].replace('**', '')
            try:
                txt_clip = TextClip(text[:50], fontsize=50, color='white', 
                                   font='DejaVu-Sans-Bold', 
                                   stroke_color='black', stroke_width=2,
                                   size=(900, None), method='caption')
                txt_clip = txt_clip.set_position(('center', 'bottom')).set_duration(seg['duration'])
                clip = CompositeVideoClip([clip, txt_clip])
            except:
                pass
            
            clips.append(clip)
        
        # Assemble
        if clips:
            final = concatenate_videoclips(clips, method="compose")
            
            # Ajoute l'audio
            if audio_path and os.path.exists(audio_path):
                audio = AudioFileClip(audio_path)
                final = final.set_audio(audio)
            
            # Export
            final.write_videofile(output_path, fps=24, codec='libx264', 
                                 audio_codec='aac', threads=2,
                                 preset='ultrafast', logger=None)
            return output_path
            
    except Exception as e:
        return None

def create_color_clip(duration, color=None):
    """Crée un clip de couleur unie"""
    try:
        from moviepy.editor import ColorClip
        if color is None:
            color = tuple(int(COLORS['primary'][i:i+2], 16) for i in (1, 3, 5))
        return ColorClip(size=(1080, 1920), color=color).set_duration(duration)
    except:
        return None

# ============================================================
# OPTIMISATION IA (ANALYSE DES PERFORMANCES)
# ============================================================

def analyze_viral_patterns(stats):
    """Analyse les patterns viraux et suggère des améliorations"""
    if not stats['shorts']:
        return {
            'best_time': '18h-20h',
            'hook_style': 'Question choc',
            'optimal_duration': '45-55s',
            'suggestions': [
                'Génère plus de shorts pour accumuler des données',
                'Teste des hooks différents',
                'Varie les sujets dans la niche cerveau/psychologie'
            ]
        }
    
    # Analyse simple basée sur les stats
    suggestions = []
    
    if stats['avg_retention'] < 50:
        suggestions.append('🎯 Ton taux de rétention est faible. Raccourcis le hook à 2 secondes max.')
    
    if stats['generated_count'] > 10 and stats['published_count'] < 5:
        suggestions.append('📤 Tu génères beaucoup mais publie peu. Publie plus régulièrement!')
    
    return {
        'best_time': '18h-20h (heure de pointe)',
        'hook_style': 'Questions contre-intuitives',
        'optimal_duration': '45-55 secondes',
        'suggestions': suggestions or ['Continue sur cette lancée!']
    }

# ============================================================
# CSS PERSONNALISÉ DYNAMIQUE
# ============================================================

def get_custom_css():
    """Génère le CSS avec les couleurs dynamiques actuelles"""
    return f"""
    <style>
    /* ===== COULEURS DYNAMIQUES (Hash: {FILE_HASH}) ===== */
    /* Si ce hash change = ton code a bien été mis à jour! */
    
    :root {{
        --primary: {COLORS['primary']};
        --secondary: {COLORS['secondary']};
        --accent: {COLORS['accent']};
        --gradient-start: {COLORS['gradient_start']};
        --gradient-end: {COLORS['gradient_end']};
        --card-bg: {COLORS['card_bg']};
        --glow: {COLORS['glow']};
        --success: {COLORS['success']};
        --warning: {COLORS['warning']};
        --error: {COLORS['error']};
    }}
    
    /* Fond animé dégradé */
    .stApp {{
        background: linear-gradient(135deg, var(--gradient-start) 0%, var(--gradient-end) 50%, var(--gradient-start) 100%);
        background-size: 400% 400%;
        animation: gradientShift 15s ease infinite;
    }}
    
    @keyframes gradientShift {{
        0% {{ background-position: 0% 50%; }}
        50% {{ background-position: 100% 50%; }}
        100% {{ background-position: 0% 50%; }}
    }}
    
    /* Glassmorphism cards */
    .glass-card {{
        background: var(--card-bg) !important;
        backdrop-filter: blur(20px) !important;
        -webkit-backdrop-filter: blur(20px) !important;
        border: 1px solid rgba(255,255,255,0.1) !important;
        border-radius: 20px !important;
        padding: 25px !important;
        margin: 15px 0 !important;
        box-shadow: 0 8px 32px rgba(0,0,0,0.3), 
                    0 0 20px rgba({int(COLORS['primary'][1:3], 16)}, {int(COLORS['primary'][3:5], 16)}, {int(COLORS['primary'][5:7], 16)}, 0.1) !important;
        transition: all 0.3s ease !important;
    }}
    
    .glass-card:hover {{
        transform: translateY(-5px) !important;
        box-shadow: 0 12px 40px rgba(0,0,0,0.4), 
                    0 0 30px rgba({int(COLORS['primary'][1:3], 16)}, {int(COLORS['primary'][3:5], 16)}, {int(COLORS['primary'][5:7], 16)}, 0.2) !important;
    }}
    
    /* Boutons néon */
    .stButton > button {{
        background: linear-gradient(135deg, var(--primary), var(--secondary)) !important;
        color: white !important;
        border: none !important;
        border-radius: 15px !important;
        padding: 15px 30px !important;
        font-weight: bold !important;
        font-size: 16px !important;
        text-transform: uppercase !important;
        letter-spacing: 1px !important;
        box-shadow: 0 0 20px rgba({int(COLORS['primary'][1:3], 16)}, {int(COLORS['primary'][3:5], 16)}, {int(COLORS['primary'][5:7], 16)}, 0.4),
                    0 4px 15px rgba(0,0,0,0.3) !important;
        transition: all 0.3s ease !important;
        width: 100% !important;
    }}
    
    .stButton > button:hover {{
        transform: scale(1.05) !important;
        box-shadow: 0 0 40px rgba({int(COLORS['primary'][1:3], 16)}, {int(COLORS['primary'][3:5], 16)}, {int(COLORS['primary'][5:7], 16)}, 0.6),
                    0 6px 20px rgba(0,0,0,0.4) !important;
    }}
    
    /* Titres avec glow */
    h1, h2, h3 {{
        color: var(--glow) !important;
        text-shadow: 0 0 20px rgba({int(COLORS['glow'][1:3], 16)}, {int(COLORS['glow'][3:5], 16)}, {int(COLORS['glow'][5:7], 16)}, 0.5) !important;
        font-weight: 800 !important;
    }}
    
    /* Inputs stylisés */
    .stTextInput > div > div > input {{
        background: rgba(255,255,255,0.05) !important;
        border: 2px solid rgba(255,255,255,0.1) !important;
        border-radius: 12px !important;
        color: white !important;
        padding: 12px !important;
    }}
    
    .stTextInput > div > div > input:focus {{
        border-color: var(--primary) !important;
        box-shadow: 0 0 15px rgba({int(COLORS['primary'][1:3], 16)}, {int(COLORS['primary'][3:5], 16)}, {int(COLORS['primary'][5:7], 16)}, 0.3) !important;
    }}
    
    /* Progress bar custom */
    .stProgress > div > div > div {{
        background: linear-gradient(90deg, var(--primary), var(--accent)) !important;
        border-radius: 10px !important;
    }}
    
    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {{
        background: rgba(255,255,255,0.05) !important;
        border-radius: 15px !important;
        padding: 5px !important;
    }}
    
    .stTabs [data-baseweb="tab"] {{
        color: white !important;
        border-radius: 10px !important;
    }}
    
    .stTabs [aria-selected="true"] {{
        background: linear-gradient(135deg, var(--primary), var(--secondary)) !important;
        color: white !important;
    }}
    
    /* Badge de version */
    .version-badge {{
        position: fixed !important;
        top: 10px !important;
        right: 10px !important;
        background: var(--card-bg) !important;
        backdrop-filter: blur(10px) !important;
        border: 1px solid var(--primary) !important;
        border-radius: 20px !important;
        padding: 8px 16px !important;
        color: var(--glow) !important;
        font-size: 12px !important;
        font-family: monospace !important;
        z-index: 9999 !important;
        box-shadow: 0 0 15px rgba({int(COLORS['primary'][1:3], 16)}, {int(COLORS['primary'][3:5], 16)}, {int(COLORS['primary'][5:7], 16)}, 0.3) !important;
    }}
    
    /* Alertes */
    .alert-success {{
        background: rgba({int(COLORS['success'][1:3], 16)}, {int(COLORS['success'][3:5], 16)}, {int(COLORS['success'][5:7], 16)}, 0.2) !important;
        border-left: 4px solid var(--success) !important;
        padding: 15px !important;
        border-radius: 0 10px 10px 0 !important;
    }}
    
    .alert-error {{
        background: rgba({int(COLORS['error'][1:3], 16)}, {int(COLORS['error'][3:5], 16)}, {int(COLORS['error'][5:7], 16)}, 0.2) !important;
        border-left: 4px solid var(--error) !important;
        padding: 15px !important;
        border-radius: 0 10px 10px 0 !important;
    }}
    
    /* Spinner personnalisé */
    .stSpinner > div {{
        border-color: var(--primary) !important;
        border-top-color: transparent !important;
    }}
    
    /* Scrollbar */
    ::-webkit-scrollbar {{
        width: 8px !important;
    }}
    
    ::-webkit-scrollbar-track {{
        background: var(--gradient-end) !important;
    }}
    
    ::-webkit-scrollbar-thumb {{
        background: var(--primary) !important;
        border-radius: 4px !important;
    }}
    
    /* Cache le menu hamburger et footer */
    #MainMenu {{visibility: hidden;}}
    footer {{visibility: hidden;}}
    header {{visibility: hidden;}}
    
    /* Responsive mobile */
    @media (max-width: 768px) {{
        .glass-card {{
            padding: 15px !important;
            margin: 10px 0 !important;
        }}
        
        h1 {{ font-size: 24px !important; }}
        h2 {{ font-size: 20px !important; }}
        
        .stButton > button {{
            padding: 12px 20px !important;
            font-size: 14px !important;
        }}
    }}
    </style>
    
    <!-- Badge de version dynamique -->
    <div class="version-badge">
        🎨 v{FILE_HASH} | {COLORS['primary']}
    </div>
    """

# ============================================================
# INTERFACE PRINCIPALE
# ============================================================

def main():
    # Configuration de la page
    st.set_page_config(
        page_title="🧠 Shorts Viraux",
        page_icon="🧠",
        layout="centered",
        initial_sidebar_state="collapsed"
    )
    
    # Injection du CSS dynamique
    st.markdown(get_custom_css(), unsafe_allow_html=True)
    
    # Chargement des stats
    stats = load_stats()
    
    # Vérification des clés API
    api_ok = bool(OPENROUTER_API_KEY and PEXELS_API_KEY)
    
    # ===== HEADER =====
    st.markdown(f"""
    <div style="text-align: center; padding: 20px 0;">
        <h1 style="font-size: 42px; margin-bottom: 5px;">🧠 SHORTS VIRALS</h1>
        <p style="color: {COLORS['text_secondary']}; font-size: 16px; margin-top: 0;">
            Générateur automatique • Cerveau & Psychologie
        </p>
        <p style="color: {COLORS['accent']}; font-size: 12px; font-family: monospace;">
            🎨 Version: {FILE_HASH} | Couleur: {COLORS['primary']}
        </p>
    </div>
    """, unsafe_allow_html=True)
    
    # Alertes API
    if not OPENROUTER_API_KEY:
        st.markdown(f"""
        <div class="alert-error">
            🔑 <b>OPENROUTER_API_KEY manquante</b><br>
            Va sur openrouter.ai → Settings → Keys → Create Key<br>
            Ajoute-la dans Render → Environment Variables
        </div>
        """, unsafe_allow_html=True)
    
    if not PEXELS_API_KEY:
        st.markdown(f"""
        <div class="alert-error">
            🔑 <b>PEXELS_API_KEY manquante</b><br>
            Va sur pexels.com/api → Join → récupère ta clé
        </div>
        """, unsafe_allow_html=True)
    
    # ===== ONGLETS =====
    tabs = st.tabs(["🎬 Générateur", "📊 Dashboard", "🧠 Optimisation IA"])
    
    # ==================== ONGLET 1: GÉNÉRATEUR ====================
    with tabs[0]:
        st.markdown(f"""
        <div class="glass-card">
            <h2>🎬 Crée ton Short Viral</h2>
            <p>Génère un script, une voix off, des visuels et le montage — en un clic.</p>
        </div>
        """, unsafe_allow_html=True)
        
        col1, col2 = st.columns([3, 1])
        
        with col1:
            subject = st.text_input(
                "Sujet du Short (optionnel)",
                placeholder="Ex: pourquoi ton cerveau oublie 80% de ce que tu lis",
                help="Laisse vide pour un sujet aléatoire dans la niche cerveau/psychologie"
            )
        
        with col2:
            st.markdown("<br>", unsafe_allow_html=True)
            generate_btn = st.button("🚀 GÉNÉRER MON SHORT", use_container_width=True, 
                                    disabled=not api_ok, type="primary")
        
        if generate_btn:
            progress_container = st.container()
            
            with progress_container:
                # Étape 1: Script
                progress_bar = st.progress(0)
                status = st.empty()
                
                status.markdown(f"<p style='color: {COLORS['glow']};'>📝 Étape 1/5: Génération du script viral...</p>", unsafe_allow_html=True)
                progress_bar.progress(20)
                
                script, error = generate_script(subject if subject else None)
                
                if error:
                    st.markdown(f"""
                    <div class="alert-error">
                        {error}
                    </div>
                    """, unsafe_allow_html=True)
                    progress_bar.empty()
                    status.empty()
                else:
                    # Affiche le script
                    st.markdown(f"""
                    <div class="glass-card" style="border-left: 4px solid {COLORS['success']};">
                        <h3>✅ Script généré!</h3>
                        <pre style="background: rgba(0,0,0,0.3); padding: 15px; border-radius: 10px; color: white; white-space: pre-wrap;">{script}</pre>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # Étape 2: Images
                    status.markdown(f"<p style='color: {COLORS['glow']};'>🖼️ Étape 2/5: Recherche d'images...</p>", unsafe_allow_html=True)
                    progress_bar.progress(40)
                    
                    # Extrait les mots-clés pour la recherche
                    search_query = subject if subject else "brain psychology"
                    images = search_images(search_query, count=5)
                    
                    if images:
                        st.markdown(f"<p style='color: {COLORS['success']};'>✅ {len(images)} images trouvées</p>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"<p style='color: {COLORS['warning']};'>⚠️ Images fallback utilisées</p>", unsafe_allow_html=True)
                    
                    # Étape 3: Audio
                    status.markdown(f"<p style='color: {COLORS['glow']};'>🎙️ Étape 3/5: Génération de la voix off...</p>", unsafe_allow_html=True)
                    progress_bar.progress(60)
                    
                    # Nettoie le texte pour le TTS
                    tts_text = script.replace('**', '').replace('TITRE:', '').replace('HOOK:', '').replace('FAIT', '').replace('CTA:', '').replace('HASHTAGS:', '')
                    tts_text = ' '.join(tts_text.split()[:100])  # Limite la longueur
                    
                    audio_path = generate_audio(tts_text)
                    
                    if audio_path:
                        st.markdown(f"<p style='color: {COLORS['success']};'>✅ Voix off générée</p>", unsafe_allow_html=True)
                        st.audio(audio_path)
                    else:
                        st.markdown(f"<p style='color: {COLORS['warning']};'>⚠️ Voix off non générée (Edge TTS peut nécessiter une installation)</p>", unsafe_allow_html=True)
                    
                    # Étape 4: Miniature
                    status.markdown(f"<p style='color: {COLORS['glow']};'>🎨 Étape 4/5: Création de la miniature...</p>", unsafe_allow_html=True)
                    progress_bar.progress(80)
                    
                    # Extrait le titre
                    title = "Short Viral"
                    for line in script.split('\n'):
                        if line.startswith('TITRE:'):
                            title = line.replace('TITRE:', '').strip()
                            break
                    
                    thumb_path = generate_thumbnail(title)
                    
                    if thumb_path:
                        st.markdown(f"<p style='color: {COLORS['success']};'>✅ Miniature créée</p>", unsafe_allow_html=True)
                        st.image(thumb_path, caption="Miniature 9:16", use_column_width=True)
                    
                    # Étape 5: Montage
                    status.markdown(f"<p style='color: {COLORS['glow']};'>🎬 Étape 5/5: Montage vidéo...</p>", unsafe_allow_html=True)
                    progress_bar.progress(95)
                    
                    video_path = create_video(script, images, audio_path)
                    
                    if video_path and os.path.exists(video_path):
                        progress_bar.progress(100)
                        status.markdown(f"<p style='color: {COLORS['success']}; font-size: 20px;'>🎉 SHORT PRÊT!</p>", unsafe_allow_html=True)
                        
                        st.markdown(f"""
                        <div class="glass-card" style="border: 2px solid {COLORS['success']}; text-align: center;">
                            <h2>🎬 Ton Short est prêt!</h2>
                            <p>Télécharge-le et publie-le sur YouTube Shorts / TikTok</p>
                        </div>
                        """, unsafe_allow_html=True)
                        
                        with open(video_path, 'rb') as f:
                            st.download_button(
                                label="📥 TÉLÉCHARGER LE SHORT",
                                data=f,
                                file_name=f"short_viral_{int(time.time())}.mp4",
                                mime="video/mp4",
                                use_container_width=True
                            )
                        
                        # Met à jour les stats
                        stats['generated_count'] += 1
                        stats['shorts'].append({
                            'id': int(time.time()),
                            'subject': subject or 'Aléatoire',
                            'title': title,
                            'date': datetime.now().isoformat(),
                            'views': 0,
                            'retention': 0
                        })
                        save_stats(stats)
                        
                    else:
                        progress_bar.progress(100)
                        status.markdown(f"<p style='color: {COLORS['warning']};'>⚠️ Montage simplifié (MoviePy peut être limité sur Render Free)</p>", unsafe_allow_html=True)
                        
                        # Propose le téléchargement du script + audio
                        st.markdown(f"""
                        <div class="glass-card">
                            <h3>📦 Contenu généré:</h3>
                            <ul>
                                <li>✅ Script viral prêt à lire</li>
                                <li>✅ Voix off (si générée)</li>
                                <li>✅ Miniature</li>
                                <li>⚠️ Montage vidéo: utilise CapCut ou InShot avec le script et les images</li>
                            </ul>
                        </div>
                        """, unsafe_allow_html=True)
                        
                        # Téléchargement du script
                        st.download_button(
                            label="📄 TÉLÉCHARGER LE SCRIPT",
                            data=script,
                            file_name=f"script_{int(time.time())}.txt",
                            mime="text/plain",
                            use_container_width=True
                        )
    
    # ==================== ONGLET 2: DASHBOARD ====================
    with tabs[1]:
        st.markdown(f"""
        <div class="glass-card">
            <h2>📊 Tableau de bord</h2>
            <p>Suis tes performances et optimise ta stratégie.</p>
        </div>
        """, unsafe_allow_html=True)
        
        # Stats globales
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.markdown(f"""
            <div class="glass-card" style="text-align: center;">
                <h1 style="font-size: 36px; margin: 0; color: {COLORS['primary']};">{stats['generated_count']}</h1>
                <p style="margin: 5px 0; color: {COLORS['text_secondary']};">Shorts générés</p>
            </div>
            """, unsafe_allow_html=True)
        
        with col2:
            st.markdown(f"""
            <div class="glass-card" style="text-align: center;">
                <h1 style="font-size: 36px; margin: 0; color: {COLORS['success']};">{stats['published_count']}</h1>
                <p style="margin: 5px 0; color: {COLORS['text_secondary']};">Publiés</p>
            </div>
            """, unsafe_allow_html=True)
        
        with col3:
            st.markdown(f"""
            <div class="glass-card" style="text-align: center;">
                <h1 style="font-size: 36px; margin: 0; color: {COLORS['accent']};">{stats['total_views']}</h1>
                <p style="margin: 5px 0; color: {COLORS['text_secondary']};">Vues totales</p>
            </div>
            """, unsafe_allow_html=True)
        
        with col4:
            retention = stats['avg_retention']
            color = COLORS['success'] if retention > 60 else COLORS['warning'] if retention > 40 else COLORS['error']
            st.markdown(f"""
            <div class="glass-card" style="text-align: center;">
                <h1 style="font-size: 36px; margin: 0; color: {color};">{retention}%</h1>
                <p style="margin: 5px 0; color: {COLORS['text_secondary']};">Rétention moy.</p>
            </div>
            """, unsafe_allow_html=True)
        
        # Formulaire de mise à jour des stats
        st.markdown(f"""
        <div class="glass-card">
            <h3>📝 Mettre à jour les stats</h3>
            <p>Entre les performances de ton dernier short publié:</p>
        </div>
        """, unsafe_allow_html=True)
        
        with st.form("update_stats"):
            col1, col2, col3 = st.columns(3)
            
            with col1:
                views = st.number_input("👀 Vues", min_value=0, value=0, step=100)
            with col2:
                subscribers = st.number_input("👥 Nouveaux abonnés", min_value=0, value=0, step=1)
            with col3:
                retention = st.slider("📊 Taux de rétention (%)", 0, 100, 50)
            
            submitted = st.form_submit_button("💾 ENREGISTRER", use_container_width=True)
            
            if submitted:
                stats['total_views'] += views
                stats['total_subscribers'] += subscribers
                
                # Calcule la nouvelle moyenne de rétention
                total_shorts = len(stats['shorts'])
                if total_shorts > 0:
                    stats['avg_retention'] = int((stats['avg_retention'] * (total_shorts - 1) + retention) / total_shorts)
                else:
                    stats['avg_retention'] = retention
                
                stats['published_count'] += 1
                save_stats(stats)
                
                st.markdown(f"""
                <div class="alert-success">
                    ✅ Stats mises à jour! Rétention moyenne: {stats['avg_retention']}%
                </div>
                """, unsafe_allow_html=True)
                st.rerun()
        
        # Historique des shorts
        if stats['shorts']:
            st.markdown(f"""
            <div class="glass-card">
                <h3>📜 Historique des shorts</h3>
            </div>
            """, unsafe_allow_html=True)
            
            for short in reversed(stats['shorts'][-10:]):
                st.markdown(f"""
                <div class="glass-card" style="padding: 15px; margin: 8px 0;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <div>
                            <strong style="color: {COLORS['glow']};">{short.get('title', 'Sans titre')[:40]}...</strong><br>
                            <span style="color: {COLORS['text_secondary']}; font-size: 12px;">{short.get('subject', 'N/A')} • {short.get('date', '')[:10]}</span>
                        </div>
                        <div style="text-align: right;">
                            <span style="color: {COLORS['primary']}; font-size: 18px; font-weight: bold;">{short.get('views', 0)}</span><br>
                            <span style="color: {COLORS['text_secondary']}; font-size: 11px;">vues</span>
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
    
    # ==================== ONGLET 3: OPTIMISATION IA ====================
    with tabs[2]:
        st.markdown(f"""
        <div class="glass-card">
            <h2>🧠 Optimisation IA</h2>
            <p>L'IA analyse tes performances et te donne des conseils personnalisés.</p>
        </div>
        """, unsafe_allow_html=True)
        
        analysis = analyze_viral_patterns(stats)
        
        # Recommandations
        st.markdown(f"""
        <div class="glass-card" style="border-left: 4px solid {COLORS['accent']};">
            <h3>💡 Recommandations personnalisées</h3>
        </div>
        """, unsafe_allow_html=True)
        
        for suggestion in analysis['suggestions']:
            st.markdown(f"""
            <div class="glass-card" style="padding: 12px 20px; margin: 8px 0;">
                <p style="margin: 0; color: white;">{suggestion}</p>
            </div>
            """, unsafe_allow_html=True)
        
        # Stats d'optimisation
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.markdown(f"""
            <div class="glass-card" style="text-align: center;">
                <p style="color: {COLORS['text_secondary']}; margin: 0;">🕐 Meilleur horaire</p>
                <h3 style="color: {COLORS['glow']}; margin: 5px 0;">{analysis['best_time']}</h3>
            </div>
            """, unsafe_allow_html=True)
        
        with col2:
            st.markdown(f"""
            <div class="glass-card" style="text-align: center;">
                <p style="color: {COLORS['text_secondary']}; margin: 0;">🎯 Style de hook</p>
                <h3 style="color: {COLORS['glow']}; margin: 5px 0;">{analysis['hook_style']}</h3>
            </div>
            """, unsafe_allow_html=True)
        
        with col3:
            st.markdown(f"""
            <div class="glass-card" style="text-align: center;">
                <p style="color: {COLORS['text_secondary']}; margin: 0;">⏱️ Durée optimale</p>
                <h3 style="color: {COLORS['glow']}; margin: 5px 0;">{analysis['optimal_duration']}</h3>
            </div>
            """, unsafe_allow_html=True)
        
        # Auto-optimisation: génère un script amélioré
        st.markdown(f"""
        <div class="glass-card" style="margin-top: 20px;">
            <h3>✨ Générer un script optimisé</h3>
            <p>L'IA crée un script basé sur tes meilleures performances.</p>
        </div>
        """, unsafe_allow_html=True)
        
        if st.button("⚡ GÉNÉRER UN SCRIPT OPTIMISÉ", use_container_width=True, disabled=not api_ok):
            with st.spinner("L'IA analyse tes stats et crée le script parfait..."):
                # Construit un prompt d'optimisation basé sur les stats
                optimization_context = f"""
                Contexte des performances actuelles:
                - Rétention moyenne: {stats['avg_retention']}%
                - Total shorts générés: {stats['generated_count']}
                - Total shorts publiés: {stats['published_count']}
                - Meilleur horaire: {analysis['best_time']}
                - Style de hook optimal: {analysis['hook_style']}
                
                Crée un script qui maximise ces métriques.
                """
                
                script, error = generate_script(optimization_context)
                
                if script:
                    st.markdown(f"""
                    <div class="glass-card" style="border: 2px solid {COLORS['success']};">
                        <h3>🎯 Script optimisé par l'IA</h3>
                        <pre style="background: rgba(0,0,0,0.3); padding: 15px; border-radius: 10px; color: white; white-space: pre-wrap;">{script}</pre>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    st.download_button(
                        label="📄 TÉLÉCHARGER LE SCRIPT OPTIMISÉ",
                        data=script,
                        file_name=f"script_optimise_{int(time.time())}.txt",
                        mime="text/plain",
                        use_container_width=True
                    )
                else:
                    st.markdown(f"""
                    <div class="alert-error">
                        {error}
                    </div>
                    """, unsafe_allow_html=True)

# ============================================================
# LANCEMENT
# ============================================================

if __name__ == "__main__":
    main()

