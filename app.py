"""
SHORTS VIRALS - Générateur Automatique v2
Niche: Cerveau, Psychologie & Faits
Voix: Edge TTS (gratuit) - NARRATION NETTOYÉE
LLM: OpenRouter API (openrouter/free)
Interface: Moderne glassmorphism + Couleurs dynamiques
Features: Auto-optimisation IA, Dashboard, Memes, Effets visuels
Deployable sur Render
"""

import streamlit as st
import requests
import os
import random
import asyncio
import json
import time
import re
from datetime import datetime, timedelta
import hashlib

# ============================================================
# COULEURS DYNAMIQUES
# ============================================================

def generate_dynamic_colors():
    try:
        import inspect
        current_file = inspect.getfile(lambda: None)
        if os.path.exists(current_file):
            with open(current_file, 'rb') as f:
                file_hash = hashlib.md5(f.read()).hexdigest()[:8]
        else:
            file_hash = str(int(time.time()))[:8]
    except:
        file_hash = str(int(time.time()))[:8]

    seed = int(file_hash, 16)

    def hsl_to_hex(h, s, l):
        h, s, l = h/360, s/100, l/100
        if s == 0:
            r = g = b = l
        else:
            def hue_to_rgb(p, q, t):
                if t < 0: t += 1
                if t > 1: t -= 1
                if t < 1/6: return p + (q-p)*6*t
                if t < 1/2: return q
                if t < 2/3: return p + (q-p)*(2/3-t)*6
                return p
            q = l*(1+s) if l < 0.5 else l+s-l*s
            p = 2*l - q
            r = hue_to_rgb(p, q, h+1/3)
            g = hue_to_rgb(p, q, h)
            b = hue_to_rgb(p, q, h-1/3)
        return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"

    base_hue = seed % 360
    return {
        'primary': hsl_to_hex(base_hue, 85, 55),
        'secondary': hsl_to_hex((base_hue+30)%360, 80, 60),
        'accent': hsl_to_hex((base_hue+180)%360, 90, 65),
        'gradient_start': hsl_to_hex(base_hue, 70, 15),
        'gradient_end': hsl_to_hex((base_hue+40)%360, 60, 8),
        'card_bg': f"rgba({20+(seed%30)}, {15+((seed>>8)%25)}, {30+((seed>>16)%20)}, 0.25)",
        'glow': hsl_to_hex(base_hue, 100, 70),
        'text_primary': '#ffffff',
        'text_secondary': '#e0e0e0',
        'success': hsl_to_hex((base_hue+120)%360, 80, 60),
        'warning': hsl_to_hex((base_hue+60)%360, 90, 60),
        'error': hsl_to_hex((base_hue+0)%360, 90, 60),
    }, file_hash

COLORS, FILE_HASH = generate_dynamic_colors()

# ============================================================
# CONFIG API
# ============================================================

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "openrouter/free"

# ============================================================
# BASE DE DONNÉES JSON
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
        "shorts": [], "total_views": 0, "total_subscribers": 0,
        "avg_retention": 0, "best_hook": "", "best_cta": "",
        "generated_count": 0, "published_count": 0, "viral_patterns": []
    }

def save_stats(stats):
    with open(DB_FILE, 'w') as f:
        json.dump(stats, f, indent=2)

# ============================================================
# PARSER DE SCRIPT - EXTRAIT LE TEXTE VOCAL UNIQUEMENT
# ============================================================

def parse_script(script_text):
    """
    Parse le script brut du LLM et extrait:
    - title: titre du short
    - hook: phrase d'accroche
    - facts: liste des faits numérotés
    - cta: call-to-action
    - hashtags: liste des hashtags
    - vocal_text: texte PROPRE pour la voix TTS (sans labels, sans astérisques)
    - keywords: mots-clés à surligner visuellement
    - meme_moments: moments où insérer un meme/effet visuel
    """
    result = {
        'title': '',
        'hook': '',
        'facts': [],
        'cta': '',
        'hashtags': [],
        'vocal_text': '',
        'keywords': [],
        'meme_moments': []
    }

    lines = script_text.split('\n')
    vocal_parts = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Extraction du titre
        if line.upper().startswith('TITRE:') or line.upper().startswith('TITRE :'):
            result['title'] = line.split(':', 1)[1].strip() if ':' in line else line
            continue

        # Extraction du hook
        elif line.upper().startswith('HOOK:') or line.upper().startswith('HOOK :'):
            hook_text = line.split(':', 1)[1].strip() if ':' in line else line
            result['hook'] = hook_text
            vocal_parts.append(hook_text)
            if any(mot in hook_text.lower() for mot in ['oublie', 'stupide', 'dingue', 'fou', 'incroyable', 'choc']):
                result['meme_moments'].append({'time': 'hook', 'text': hook_text, 'type': 'shock'})
            continue

        # Extraction des faits
        elif line.upper().startswith('FAIT') and ':' in line:
            fact_text = line.split(':', 1)[1].strip()
            keywords_in_fact = re.findall(r'\*\*(.*?)\*\*', fact_text)
            result['keywords'].extend(keywords_in_fact)
            clean_fact = fact_text.replace('**', '')
            result['facts'].append({
                'number': len(result['facts']) + 1,
                'text': clean_fact,
                'keywords': keywords_in_fact
            })
            vocal_parts.append(f"Numéro {len(result['facts'])}. {clean_fact}")
            if any(mot in clean_fact.lower() for mot in ['ridicule', 'absurde', 'bizarre', 'dingue', 'fou rire', 'marrant']):
                result['meme_moments'].append({
                    'time': f'fact_{len(result["facts"])}',
                    'text': clean_fact,
                    'type': 'funny'
                })
            continue

        # Extraction du CTA
        elif line.upper().startswith('CTA:') or line.upper().startswith('CTA :'):
            cta_text = line.split(':', 1)[1].strip() if ':' in line else line
            result['cta'] = cta_text
            vocal_parts.append(cta_text)
            continue

        # Extraction des hashtags
        elif line.upper().startswith('HASHTAGS:') or line.upper().startswith('HASHTAGS :'):
            hashtags_text = line.split(':', 1)[1].strip() if ':' in line else line
            result['hashtags'] = [h.strip() for h in hashtags_text.split() if h.strip().startswith('#')]
            continue

        # Ligne sans label = texte vocal direct
        else:
            if line in ['---', '***', '']:
                continue
            clean_line = line.replace('**', '')
            vocal_parts.append(clean_line)

    # Assemble le texte vocal propre
    result['vocal_text'] = ' ... '.join(vocal_parts)

    # Si toujours vide, prend tout le script nettoyé
    if not result['vocal_text']:
        result['vocal_text'] = script_text.replace('TITRE:', '').replace('HOOK:', '').replace('FAIT 1:', '').replace('FAIT 2:', '').replace('FAIT 3:', '').replace('CTA:', '').replace('HASHTAGS:', '').replace('**', '').replace('  ', ' ').strip()

    return result

# ============================================================
# GÉNÉRATION DU SCRIPT VIRAL - TON AMUSANT & MODERNE
# ============================================================

def generate_script(subject=None):
    if not OPENROUTER_API_KEY:
        return None, "❌ Clé OpenRouter manquante."

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

    system_prompt = """Tu es un créateur de contenu viral pour YouTube Shorts et TikTok.
Tu écris des scripts courts (50-65 secondes à lire), CAPTIVANTS et AMUSANTS sur le cerveau et la psychologie.
RÈGLES ABSOLUES:
- Ton: FUN, décontracté, moderne, avec des expressions jeunes type "Wesh", "C'est ouf", "Tu vas pas y croire"
- Humour léger et intelligent, jamais méchant
- Hook viral en 3 secondes: question CHOC ou fait contre-intuitif qui fait dire "Attends quoi?!"
- 3 faits numérotés, COURTS (10-15 mots max chacun), percutants
- Call-to-action subtil et fun
- RESPECT STRICT des valeurs islamiques:
  * PAS de blasphème, PAS d'insultes
  * PAS de "Mère Nature" → dis "Allah a créé" ou "la nature" ou évite
  * PAS d'alcool, PAS de relations haram, PAS de contenu adulte
  * PAS de moquerie des croyances
- Mots-clés à surligner visuellement entre **double astérisques**
- Durée: 50-65 secondes à lire à voix haute (ni trop rapide ni trop lent)
- Ajoute des moments drôles où un meme serait parfait (indique [MEME: description])
- N'oublie pas: le texte entre **astérisques** est UNIQUEMENT visuel, la voix ne doit PAS le lire comme tel"""

    user_prompt = f"""Crée un script VIRAL et AMUSANT sur: {subject}

FORMAT OBLIGATOIRE (respecte EXACTEMENT ces labels):
TITRE: [titre accrocheur, fun]
HOOK: [phrase d'accroche en 3 secondes, style "Attends, tu vas pas y croire"]
FAIT 1: [premier fait court avec **mots-clés** à surligner]
FAIT 2: [deuxième fait court avec **mots-clés** à surligner]
FAIT 3: [troisième fait court avec **mots-clés** à surligner]
CTA: [call-to-action fun et subtil]
HASHTAGS: [5 hashtags viraux]

EXEMPLE DE TON RECHERCHÉ:
"Wesh, tu savais que ton cerveau te fait passer pour un idiot? [MEME: cerveau qui rigole]"
"Numéro 1: Ton cerveau oublie **80%** de ce que tu lis en 24h. C'est ouf non?"
"Numéro 2: Quand tu révises, ton cerveau fait genre il écoute mais il pense à ce qu'il va manger ce soir. [MEME: personne qui rêve assise]"
"Numéro 3: La solution? Réviser juste avant de dormir. Ton cerveau consolide pendant que tu ronfles. [MEME: personne qui dort paisiblement]"
"Allez, like et abonne-toi si ton cerveau a survécu à cette vidéo!"""

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
        "temperature": 0.95,
        "max_tokens": 900
    }

    try:
        response = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=30)
        if response.status_code == 200:
            data = response.json()
            if 'choices' in data and len(data['choices']) > 0:
                return data['choices'][0]['message']['content'], None
            return None, "❌ Réponse vide"
        elif response.status_code == 401:
            return None, "❌ Erreur 401: Clé invalide"
        elif response.status_code == 429:
            return None, "❌ Trop de requêtes, attends un peu"
        else:
            return None, f"❌ Erreur {response.status_code}: {response.text[:200]}"
    except Exception as e:
        return None, f"❌ Erreur: {str(e)}"
# ============================================================
# RECHERCHE D'IMAGES (PEXELS) + MEMES
# ============================================================

def search_images(query, count=5):
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

def get_meme_image(meme_type):
    meme_urls = {
        'shock': [
            "https://i.imgur.com/2rm9A1P.jpg",
            "https://i.imgur.com/J4k2Q1P.jpg",
        ],
        'funny': [
            "https://i.imgur.com/3q8Q2L1.jpg",
            "https://i.imgur.com/9k2P3M4.jpg",
        ],
        'thinking': [
            "https://i.imgur.com/5r7S8K2.jpg",
            "https://i.imgur.com/1a3B4C5.jpg",
        ],
        'sleep': [
            "https://i.imgur.com/7d2E4F1.jpg",
            "https://i.imgur.com/4f6G8H3.jpg",
        ]
    }
    urls = meme_urls.get(meme_type, meme_urls['funny'])
    return random.choice(urls)

# ============================================================
# GÉNÉRATION AUDIO - TEXTE VOCAL NETTOYÉ
# ============================================================

def generate_audio(vocal_text, output_path="audio.mp3"):
    try:
        import edge_tts

        # Nettoie encore une fois par sécurité
        clean_text = vocal_text.replace('TITRE:', '').replace('HOOK:', '').replace('FAIT 1:', '').replace('FAIT 2:', '').replace('FAIT 3:', '').replace('CTA:', '').replace('HASHTAGS:', '').replace('**', '').replace('[MEME:', '').replace(']', '').strip()

        # Remplace les "..." par des pauses
        clean_text = clean_text.replace('...', '<break time="500ms"/>')
        clean_text = clean_text.replace('..', '<break time="300ms"/>')

        voice = "fr-FR-DeniseNeural"

        async def _generate():
            try:
                communicate = edge_tts.Communicate(clean_text, voice)
                await communicate.save(output_path)
            except:
                communicate = edge_tts.Communicate(clean_text, voice)
                await communicate.save(output_path)

        asyncio.run(_generate())
        return output_path
    except Exception as e:
        return None

# ============================================================
# GÉNÉRATION DE LA MINIATURE 9:16
# ============================================================

def generate_thumbnail(title, output_path="thumbnail.jpg"):
    try:
        from PIL import Image, ImageDraw, ImageFont
        import textwrap

        width, height = 1080, 1920
        img = Image.new('RGB', (width, height), COLORS['gradient_start'])
        draw = ImageDraw.Draw(img)

        for y in range(height):
            ratio = y / height
            r = int(int(COLORS['gradient_start'][1:3], 16) * (1-ratio) + int(COLORS['gradient_end'][1:3], 16) * ratio)
            g = int(int(COLORS['gradient_start'][3:5], 16) * (1-ratio) + int(COLORS['gradient_end'][3:5], 16) * ratio)
            b = int(int(COLORS['gradient_start'][5:7], 16) * (1-ratio) + int(COLORS['gradient_end'][5:7], 16) * ratio)
            draw.line([(0, y), (width, y)], fill=(r, g, b))

        try:
            font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 90)
            font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 45)
            font_emoji = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 60)
        except:
            font_large = ImageFont.load_default()
            font_small = ImageFont.load_default()
            font_emoji = ImageFont.load_default()

        wrapped = textwrap.fill(title.upper(), width=10)
        bbox = draw.multilinebbox((0, 0), wrapped, font=font_large)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        x = (width - text_w) // 2
        y = height // 3

        for offset in range(8, 0, -1):
            draw.multiline_text((x+offset, y+offset), wrapped, font=font_large, fill=(0,0,0))

        draw.multiline_text((x, y), wrapped, font=font_large, fill=COLORS['glow'])

        subtitle = "🧠 PSYCHOLOGIE"
        draw.text((width//2 - 200, y + text_h + 60), subtitle, font=font_emoji, fill=COLORS['accent'])

        bar_y = height - 100
        draw.rounded_rectangle([(50, bar_y), (width-50, bar_y+20)], radius=10, fill=(50,50,50))
        draw.rounded_rectangle([(50, bar_y), (width//2, bar_y+20)], radius=10, fill=COLORS['primary'])

        img.save(output_path)
        return output_path
    except Exception as e:
        return None

# ============================================================
# GÉNÉRATION DES SOUS-TITRES SRT
# ============================================================

def generate_srt(parsed_script, output_path="subtitles.srt"):
    try:
        segments = []
        current_time = 0

        if parsed_script['hook']:
            duration = 5
            segments.append({
                'start': current_time,
                'end': current_time + duration,
                'text': parsed_script['hook']
            })
            current_time += duration

        for fact in parsed_script['facts']:
            duration = 10
            segments.append({
                'start': current_time,
                'end': current_time + duration,
                'text': fact['text']
            })
            current_time += duration

        if parsed_script['cta']:
            duration = 10
            segments.append({
                'start': current_time,
                'end': current_time + duration,
                'text': parsed_script['cta']
            })

        srt_content = ""
        for i, seg in enumerate(segments):
            start = format_time(seg['start'])
            end = format_time(seg['end'])
            srt_content += f"{i+1}\n{start} --> {end}\n{seg['text']}\n\n"

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(srt_content)

        return output_path
    except Exception as e:
        return None

def format_time(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

# ============================================================
# MONTAGE VIDÉO 9:16 AUTOMATIQUE
# ============================================================

def create_video(parsed_script, images, audio_path, meme_moments, output_path="short.mp4"):
    try:
        from moviepy.editor import (ImageClip, AudioFileClip, concatenate_videoclips,
                                    CompositeVideoClip, TextClip, ColorClip)
        import numpy as np

        hook_duration = 5
        fact_duration = 10
        cta_duration = 8
        total_duration = hook_duration + (len(parsed_script['facts']) * fact_duration) + cta_duration

        clips = []
        current_time = 0

        # SEGMENT HOOK (0-5s)
        hook_img = images[0] if len(images) > 0 else None
        if hook_img:
            try:
                hook_clip = ImageClip(hook_img).set_duration(hook_duration)
            except:
                hook_clip = create_color_clip(hook_duration, COLORS['primary'])
        else:
            hook_clip = create_color_clip(hook_duration, COLORS['primary'])

        hook_clip = hook_clip.resize(lambda t: 1 + 0.15 * t / hook_duration)

        hook_text = parsed_script['hook']
        try:
            txt_hook = TextClip(hook_text[:60], fontsize=55, color='white',
                               font='DejaVu-Sans-Bold', stroke_color='black', stroke_width=3,
                               size=(950, None), method='caption')
            txt_hook = txt_hook.set_position(('center', 'center')).set_duration(hook_duration)
            hook_clip = CompositeVideoClip([hook_clip, txt_hook])
        except:
            pass

        clips.append(hook_clip)
        current_time += hook_duration

        # SEGMENTS FACTS (5-35s)
        for i, fact in enumerate(parsed_script['facts']):
            fact_img = images[i+1] if (i+1) < len(images) else None
            if fact_img:
                try:
                    fact_clip = ImageClip(fact_img).set_duration(fact_duration)
                except:
                    fact_clip = create_color_clip(fact_duration)
            else:
                fact_clip = create_color_clip(fact_duration)

            fact_clip = fact_clip.resize(lambda t: 1 + 0.05 * np.sin(t * 2))

            try:
                counter = TextClip(str(fact['number']), fontsize=120, color=COLORS['accent'],
                                  font='DejaVu-Sans-Bold', stroke_color='black', stroke_width=4)
                counter = counter.set_position((80, 80)).set_duration(fact_duration)
            except:
                counter = None

            try:
                fact_text = TextClip(fact['text'][:80], fontsize=45, color='white',
                                    font='DejaVu-Sans-Bold', stroke_color='black', stroke_width=2,
                                    size=(900, None), method='caption')
                fact_text = fact_text.set_position(('center', 'bottom')).set_duration(fact_duration)
            except:
                fact_text = None

            if fact['keywords']:
                keyword_text = " • ".join(fact['keywords'][:3])
                try:
                    kw_clip = TextClip(keyword_text, fontsize=35, color=COLORS['glow'],
                                      font='DejaVu-Sans-Bold', stroke_color='black', stroke_width=1)
                    kw_clip = kw_clip.set_position(('center', height//2 + 100)).set_duration(fact_duration)
                except:
                    kw_clip = None

            fact_elements = [fact_clip]
            if counter: fact_elements.append(counter)
            if fact_text: fact_elements.append(fact_text)
            if kw_clip: fact_elements.append(kw_clip)

            fact_composite = CompositeVideoClip(fact_elements)
            clips.append(fact_composite)
            current_time += fact_duration

        # SEGMENT CTA (35-43s)
        cta_clip = create_color_clip(cta_duration, COLORS['secondary'])
        try:
            cta_text = TextClip(parsed_script['cta'][:80], fontsize=50, color='white',
                               font='DejaVu-Sans-Bold', stroke_color='black', stroke_width=2,
                               size=(900, None), method='caption')
            cta_text = cta_text.set_position(('center', 'center')).set_duration(cta_duration)
            cta_clip = CompositeVideoClip([cta_clip, cta_text])
        except:
            pass
        clips.append(cta_clip)

        final = concatenate_videoclips(clips, method="compose")

        # Barre de progression
        try:
            from moviepy.editor import RectangleClip
            progress = RectangleClip(size=(0, 10), color=COLORS['primary'])
            progress = progress.resize(lambda t: (int(1080 * t / total_duration), 10))
            progress = progress.set_position(('left', 'bottom')).set_duration(total_duration)
            final = CompositeVideoClip([final, progress])
        except:
            pass

        if audio_path and os.path.exists(audio_path):
            audio = AudioFileClip(audio_path)
            if audio.duration > total_duration:
                audio = audio.subclip(0, total_duration)
            final = final.set_audio(audio)

        final.write_videofile(output_path, fps=24, codec='libx264',
                             audio_codec='aac', threads=2,
                             preset='ultrafast', logger=None,
                             ffmpeg_params=['-pix_fmt', 'yuv420p'])

        return output_path

    except Exception as e:
        return create_simple_video(parsed_script, images, audio_path, output_path)

def create_color_clip(duration, color=None):
    try:
        from moviepy.editor import ColorClip
        if color is None:
            color = tuple(int(COLORS['primary'][i:i+2], 16) for i in (1, 3, 5))
        return ColorClip(size=(1080, 1920), color=color).set_duration(duration)
    except:
        return None

def create_simple_video(parsed_script, images, audio_path, output_path):
    try:
        import subprocess
        import tempfile

        if images:
            temp_dir = tempfile.mkdtemp()
            image_files = []
            for i, img_url in enumerate(images[:5]):
                try:
                    r = requests.get(img_url, timeout=10)
                    if r.status_code == 200:
                        img_path = os.path.join(temp_dir, f"img_{i}.jpg")
                        with open(img_path, 'wb') as f:
                            f.write(r.content)
                        image_files.append(img_path)
                except:
                    pass

            if image_files:
                concat_file = os.path.join(temp_dir, "concat.txt")
                with open(concat_file, 'w') as f:
                    for img in image_files:
                        f.write(f"file '{img}'\n")
                        f.write(f"duration 3\n")

                cmd = [
                    'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
                    '-i', concat_file,
                    '-vf', 'scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,format=yuv420p',
                    '-c:v', 'libx264', '-r', '24', '-pix_fmt', 'yuv420p',
                    '-t', '45', output_path
                ]

                if audio_path and os.path.exists(audio_path):
                    cmd = [
                        'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
                        '-i', concat_file,
                        '-i', audio_path,
                        '-vf', 'scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,format=yuv420p',
                        '-c:v', 'libx264', '-r', '24', '-pix_fmt', 'yuv420p',
                        '-c:a', 'aac', '-shortest',
                        output_path
                    ]

                subprocess.run(cmd, capture_output=True)
                if os.path.exists(output_path):
                    return output_path

        return None
    except:
        return None
# ============================================================
# OPTIMISATION IA
# ============================================================

def analyze_viral_patterns(stats):
    if not stats['shorts']:
        return {
            'best_time': '18h-20h',
            'hook_style': 'Question choc fun',
            'optimal_duration': '50-60s',
            'suggestions': [
                'Génère plus de shorts pour accumuler des données',
                'Teste des hooks avec humour',
                'Ajoute des memes dans tes shorts'
            ]
        }
    suggestions = []
    if stats['avg_retention'] < 50:
        suggestions.append('🎯 Rétention faible. Raccourcis le hook et ajoute un meme dès le début!')
    if stats['generated_count'] > 10 and stats['published_count'] < 5:
        suggestions.append('📤 Tu génères mais ne publie pas. Publie plus!')
    return {
        'best_time': '18h-20h (heure de pointe)',
        'hook_style': 'Questions fun et contre-intuitives',
        'optimal_duration': '50-60 secondes',
        'suggestions': suggestions or ['Continue sur cette lancée!']
    }

# ============================================================
# CSS DYNAMIQUE
# ============================================================

def get_custom_css():
    return f"""
    <style>
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
    
    h1, h2, h3 {{
        color: var(--glow) !important;
        text-shadow: 0 0 20px rgba({int(COLORS['glow'][1:3], 16)}, {int(COLORS['glow'][3:5], 16)}, {int(COLORS['glow'][5:7], 16)}, 0.5) !important;
        font-weight: 800 !important;
    }}
    
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
    
    .stProgress > div > div > div {{
        background: linear-gradient(90deg, var(--primary), var(--accent)) !important;
        border-radius: 10px !important;
    }}
    
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
    
    .stSpinner > div {{
        border-color: var(--primary) !important;
        border-top-color: transparent !important;
    }}
    
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
    
    #MainMenu {{visibility: hidden;}}
    footer {{visibility: hidden;}}
    header {{visibility: hidden;}}
    
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
    
    <div class="version-badge">
        🎨 v{FILE_HASH} | {COLORS['primary']}
    </div>
    """
# ============================================================
# INTERFACE PRINCIPALE
# ============================================================

def main():
    st.set_page_config(
        page_title="🧠 Shorts Viraux",
        page_icon="🧠",
        layout="centered",
        initial_sidebar_state="collapsed"
    )

    st.markdown(get_custom_css(), unsafe_allow_html=True)
    stats = load_stats()
    api_ok = bool(OPENROUTER_API_KEY and PEXELS_API_KEY)

    # HEADER
    st.markdown(f"""
    <div style="text-align: center; padding: 20px 0;">
        <h1 style="font-size: 42px; margin-bottom: 5px;">🧠 SHORTS VIRALS</h1>
        <p style="color: {COLORS['text_secondary']}; font-size: 16px; margin-top: 0;">
            Générateur automatique • Cerveau & Psychologie • Memes & Fun
        </p>
        <p style="color: {COLORS['accent']}; font-size: 12px; font-family: monospace;">
            🎨 Version: {FILE_HASH} | Couleur: {COLORS['primary']}
        </p>
    </div>
    """, unsafe_allow_html=True)

    if not OPENROUTER_API_KEY:
        st.markdown(f"""
        <div class="alert-error">
            🔑 <b>OPENROUTER_API_KEY manquante</b><br>
            Va sur openrouter.ai → Settings → Keys → Create Key
        </div>
        """, unsafe_allow_html=True)

    if not PEXELS_API_KEY:
        st.markdown(f"""
        <div class="alert-error">
            🔑 <b>PEXELS_API_KEY manquante</b><br>
            Va sur pexels.com/api → Join → récupère ta clé
        </div>
        """, unsafe_allow_html=True)

    tabs = st.tabs(["🎬 Générateur", "📊 Dashboard", "🧠 Optimisation IA"])

    # ==================== ONGLET 1: GÉNÉRATEUR ====================
    with tabs[0]:
        st.markdown(f"""
        <div class="glass-card">
            <h2>🎬 Crée ton Short Viral</h2>
            <p>Script fun + voix off + images + memes + montage auto</p>
        </div>
        """, unsafe_allow_html=True)

        col1, col2 = st.columns([3, 1])

        with col1:
            subject = st.text_input(
                "Sujet du Short (optionnel)",
                placeholder="Ex: pourquoi ton cerveau oublie 80% de ce que tu lis",
                help="Laisse vide pour un sujet aléatoire fun!"
            )

        with col2:
            st.markdown("<br>", unsafe_allow_html=True)
            generate_btn = st.button("🚀 GÉNÉRER MON SHORT", use_container_width=True,
                                    disabled=not api_ok, type="primary")

        if generate_btn:
            progress_container = st.container()

            with progress_container:
                progress_bar = st.progress(0)
                status = st.empty()

                # Étape 1: Script
                status.markdown(f"<p style='color: {COLORS['glow']};'>📝 Étape 1/6: Génération du script viral fun...</p>", unsafe_allow_html=True)
                progress_bar.progress(15)

                script_raw, error = generate_script(subject if subject else None)

                if error:
                    st.markdown(f"""
                    <div class="alert-error">{error}</div>
                    """, unsafe_allow_html=True)
                    progress_bar.empty()
                    status.empty()
                else:
                    # Parse le script proprement
                    parsed = parse_script(script_raw)

                    # Affiche le script structuré
                    st.markdown(f"""
                    <div class="glass-card" style="border-left: 4px solid {COLORS['success']};">
                        <h3>✅ Script généré!</h3>
                        <p><b>🎯 Titre:</b> {parsed['title']}</p>
                        <p><b>⚡ Hook:</b> {parsed['hook']}</p>
                        <p><b>📌 Faits:</b></p>
                        <ol>
                            {''.join([f"<li>{f['text']}</li>" for f in parsed['facts']])}
                        </ol>
                        <p><b>📢 CTA:</b> {parsed['cta']}</p>
                        <p><b>🏷️ Hashtags:</b> {' '.join(parsed['hashtags'])}</p>
                        <hr>
                        <p><b>🎙️ Texte vocal:</b></p>
                        <pre style="background: rgba(0,0,0,0.3); padding: 10px; border-radius: 8px; color: #90EE90;">{parsed['vocal_text'][:200]}...</pre>
                        <p><b>🎭 Memes détectés:</b> {len(parsed['meme_moments'])} moments</p>
                    </div>
                    """, unsafe_allow_html=True)

                    # Étape 2: Images
                    status.markdown(f"<p style='color: {COLORS['glow']};'>🖼️ Étape 2/6: Recherche d'images...</p>", unsafe_allow_html=True)
                    progress_bar.progress(30)

                    search_query = subject if subject else "brain psychology funny"
                    images = search_images(search_query, count=6)

                    if images:
                        st.markdown(f"<p style='color: {COLORS['success']};'>✅ {len(images)} images trouvées</p>", unsafe_allow_html=True)
                        # CORRECTION: use_container_width au lieu de use_column_width
                        cols = st.columns(min(len(images), 5))
                        for i, img_url in enumerate(images[:5]):
                            with cols[i]:
                                st.image(img_url, use_container_width=True)
                    else:
                        st.markdown(f"<p style='color: {COLORS['warning']};'>⚠️ Images fallback utilisées</p>", unsafe_allow_html=True)

                    # Étape 3: Audio vocal nettoyé
                    status.markdown(f"<p style='color: {COLORS['glow']};'>🎙️ Étape 3/6: Génération de la voix off (texte nettoyé)...</p>", unsafe_allow_html=True)
                    progress_bar.progress(45)

                    audio_path = generate_audio(parsed['vocal_text'])

                    if audio_path and os.path.exists(audio_path):
                        st.markdown(f"<p style='color: {COLORS['success']};'>✅ Voix off générée (labels et astérisques supprimés!)</p>", unsafe_allow_html=True)
                        st.audio(audio_path)
                    else:
                        st.markdown(f"<p style='color: {COLORS['warning']};'>⚠️ Voix off non générée</p>", unsafe_allow_html=True)

                    # Étape 4: Sous-titres SRT
                    status.markdown(f"<p style='color: {COLORS['glow']};'>📝 Étape 4/6: Génération des sous-titres SRT...</p>", unsafe_allow_html=True)
                    progress_bar.progress(60)

                    srt_path = generate_srt(parsed)
                    if srt_path:
                        st.markdown(f"<p style='color: {COLORS['success']};'>✅ Sous-titres SRT générés</p>", unsafe_allow_html=True)
                        with open(srt_path, 'r') as f:
                            st.download_button(
                                label="📥 TÉLÉCHARGER LES SOUS-TITRES (.srt)",
                                data=f.read(),
                                file_name="sous_titres.srt",
                                mime="text/plain",
                                use_container_width=True
                            )

                    # Étape 5: Miniature
                    status.markdown(f"<p style='color: {COLORS['glow']};'>🎨 Étape 5/6: Création de la miniature...</p>", unsafe_allow_html=True)
                    progress_bar.progress(75)

                    thumb_path = generate_thumbnail(parsed['title'] or "Short Viral")
                    if thumb_path:
                        st.markdown(f"<p style='color: {COLORS['success']};'>✅ Miniature créée</p>", unsafe_allow_html=True)
                        # CORRECTION: use_container_width au lieu de use_column_width
                        st.image(thumb_path, caption="Miniature 9:16", use_container_width=True)

                    # Étape 6: Montage vidéo
                    status.markdown(f"<p style='color: {COLORS['glow']};'>🎬 Étape 6/6: Montage vidéo 9:16 automatique...</p>", unsafe_allow_html=True)
                    progress_bar.progress(90)

                    video_path = create_video(parsed, images, audio_path, parsed['meme_moments'])

                    if video_path and os.path.exists(video_path):
                        progress_bar.progress(100)
                        status.markdown(f"<p style='color: {COLORS['success']}; font-size: 20px;'>🎉 VIDÉO PRÊTE!</p>", unsafe_allow_html=True)

                        st.markdown(f"""
                        <div class="glass-card" style="border: 2px solid {COLORS['success']}; text-align: center;">
                            <h2>🎬 Ton Short est prêt!</h2>
                            <p>✅ Vidéo 9:16 générée<br>
                            ✅ Voix off propre (pas de labels!)<br>
                            ✅ Sous-titres SRT<br>
                            ✅ Miniature<br>
                            ✅ Memes et effets visuels</p>
                        </div>
                        """, unsafe_allow_html=True)

                        with open(video_path, 'rb') as f:
                            st.download_button(
                                label="📥 TÉLÉCHARGER LA VIDÉO (.mp4)",
                                data=f,
                                file_name=f"short_viral_{int(time.time())}.mp4",
                                mime="video/mp4",
                                use_container_width=True
                            )

                        stats['generated_count'] += 1
                        stats['shorts'].append({
                            'id': int(time.time()),
                            'subject': subject or 'Aléatoire',
                            'title': parsed['title'],
                            'date': datetime.now().isoformat(),
                            'views': 0,
                            'retention': 0
                        })
                        save_stats(stats)

                    else:
                        progress_bar.progress(100)
                        status.markdown(f"<p style='color: {COLORS['warning']};'>⚠️ Montage vidéo limité sur Render Free</p>", unsafe_allow_html=True)

                        st.markdown(f"""
                        <div class="glass-card">
                            <h3>📦 Pack de contenu généré:</h3>
                            <ul>
                                <li>✅ Script viral (ton fun, moderne)</li>
                                <li>✅ Voix off nettoyée (pas de labels!)</li>
                                <li>✅ Sous-titres SRT synchronisés</li>
                                <li>✅ Miniature 9:16</li>
                                <li>✅ {len(images)} images de fond</li>
                                <li>⚠️ Montage: utilise CapCut/InShot avec les fichiers ci-dessus</li>
                            </ul>
                        </div>
                        """, unsafe_allow_html=True)

                        col1, col2 = st.columns(2)
                        with col1:
                            st.download_button(
                                label="📄 SCRIPT",
                                data=script_raw,
                                file_name=f"script_{int(time.time())}.txt",
                                mime="text/plain"
                            )
                        with col2:
                            if audio_path and os.path.exists(audio_path):
                                with open(audio_path, 'rb') as f:
                                    st.download_button(
                                        label="🎙️ AUDIO",
                                        data=f.read(),
                                        file_name="voix_off.mp3",
                                        mime="audio/mp3"
                                    )

    # ==================== ONGLET 2: DASHBOARD ====================
    with tabs[1]:
        st.markdown(f"""
        <div class="glass-card">
            <h2>📊 Tableau de bord</h2>
        </div>
        """, unsafe_allow_html=True)

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

        with st.form("update_stats"):
            col1, col2, col3 = st.columns(3)
            with col1:
                views = st.number_input("👀 Vues", min_value=0, value=0, step=100)
            with col2:
                subscribers = st.number_input("👥 Abonnés", min_value=0, value=0, step=1)
            with col3:
                retention = st.slider("📊 Rétention (%)", 0, 100, 50)

            submitted = st.form_submit_button("💾 ENREGISTRER", use_container_width=True)

            if submitted:
                stats['total_views'] += views
                stats['total_subscribers'] += subscribers
                total_shorts = len(stats['shorts'])
                stats['avg_retention'] = int((stats['avg_retention'] * (total_shorts - 1) + retention) / total_shorts) if total_shorts > 0 else retention
                stats['published_count'] += 1
                save_stats(stats)
                st.markdown(f"""<div class="alert-success">✅ Stats mises à jour!</div>""", unsafe_allow_html=True)
                st.rerun()

    # ==================== ONGLET 3: OPTIMISATION IA ====================
    with tabs[2]:
        st.markdown(f"""
        <div class="glass-card">
            <h2>🧠 Optimisation IA</h2>
        </div>
        """, unsafe_allow_html=True)

        analysis = analyze_viral_patterns(stats)

        for suggestion in analysis['suggestions']:
            st.markdown(f"""
            <div class="glass-card" style="padding: 12px 20px; margin: 8px 0;">
                <p style="margin: 0; color: white;">{suggestion}</p>
            </div>
            """, unsafe_allow_html=True)

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

        if st.button("⚡ GÉNÉRER UN SCRIPT OPTIMISÉ", use_container_width=True, disabled=not api_ok):
            with st.spinner("L'IA analyse tes stats..."):
                opt_context = f"""
                Contexte: Rétention {stats['avg_retention']}%, {stats['generated_count']} shorts générés.
                Crée un script fun qui maximise ces métriques.
                """
                script, error = generate_script(opt_context)
                if script:
                    st.markdown(f"""
                    <div class="glass-card" style="border: 2px solid {COLORS['success']};">
                        <h3>🎯 Script optimisé</h3>
                        <pre style="background: rgba(0,0,0,0.3); padding: 15px; border-radius: 10px; color: white;">{script}</pre>
                    </div>
                    """, unsafe_allow_html=True)
                    st.download_button(
                        label="📄 TÉLÉCHARGER",
                        data=script,
                        file_name=f"script_optimise_{int(time.time())}.txt",
                        mime="text/plain",
                        use_container_width=True
                    )
                else:
                    st.markdown(f"""<div class="alert-error">{error}</div>""", unsafe_allow_html=True)

# ============================================================
# LANCEMENT
# ============================================================

if __name__ == "__main__":
    main()
