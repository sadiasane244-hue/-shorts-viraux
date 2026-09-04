import os
import re
import json
import time
import math
import shutil
import asyncio
import random
import tempfile
import subprocess
from pathlib import Path
from typing import List, Dict, Tuple, Optional

import requests
import streamlit as st
import edge_tts
from PIL import Image


# ============================================================
# CONFIGURATION
# ============================================================

APP_TITLE = "Studio Vidéo IA"

OPENROUTER_MODEL = "meta-llama/llama-3.3-70b-instruct"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"

OUTPUT_DIR = Path("outputs")
TEMP_DIR = Path("temp")

OUTPUT_DIR.mkdir(exist_ok=True)
TEMP_DIR.mkdir(exist_ok=True)

CTA = "Abonne-toi pour en savoir plus sur le monde."

PREFERRED_VOICES = [
    "fr-FR-HenriNeural",
    "fr-FR-DeniseNeural",
    "fr-FR-EloiseNeural",
    "fr-FR-RemyMultilingualNeural",
    "fr-FR-VivienneMultilingualNeural",
]

# Routage du contenu
MIN_WORDS = 200
ONE_SHORT_MAX = 349
TWO_SHORT_MAX = 699
LONG_MAX_RECOMMENDED = 1000

# Objectifs de durée
SHORT_MIN_SECONDS = 20
SHORT_TARGET_MIN_SECONDS = 25
SHORT_TARGET_MAX_SECONDS = 40
SHORT_MAX_SECONDS = 45


# ============================================================
# OUTILS GENERAUX
# ============================================================

def get_secret(name: str) -> Optional[str]:
    """
    Cherche une variable dans st.secrets puis dans l'environnement.
    """
    try:
        value = st.secrets.get(name)
        if value:
            return str(value)
    except Exception:
        pass

    return os.getenv(name)


def clean_text(text: str) -> str:
    if not text:
        return ""

    text = text.replace("\r", "\n")

    # Supprime les éventuels blocs Markdown
    text = re.sub(r"```(?:text|markdown)?", "", text, flags=re.IGNORECASE)
    text = text.replace("```", "")

    # Supprime certains titres techniques
    text = re.sub(
        r"^\s*(SCRIPT|NARRATION|TEXTE|CONTENU)\s*:?\s*$",
        "",
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    )

    # Normalise les espaces
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def count_words(text: str) -> int:
    text = clean_text(text)
    return len(re.findall(r"\b[\wÀ-ÿ'’-]+\b", text))


def format_seconds(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    minutes = seconds // 60
    secs = seconds % 60
    return f"{minutes:02d}:{secs:02d}"


def run_command(command: List[str], timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False,
    )


def ensure_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "FFmpeg n'est pas disponible sur le serveur. "
            "Installez FFmpeg dans l'environnement Render."
        )

    if shutil.which("ffprobe") is None:
        raise RuntimeError(
            "FFprobe n'est pas disponible sur le serveur. "
            "Installez FFmpeg correctement."
        )


# ============================================================
# OPENROUTER
# ============================================================

def openrouter_request(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.7,
    max_tokens: int = 5000,
) -> str:

    api_key = get_secret("OPENROUTER_API_KEY")

    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY est absente. "
            "Ajoutez-la dans les variables d'environnement de Render."
        )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://shorts-viraux-1.onrender.com",
        "X-Title": APP_TITLE,
    }

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    response = requests.post(
        OPENROUTER_URL,
        headers=headers,
        json=payload,
        timeout=180,
    )

    if response.status_code != 200:
        try:
            detail = response.json()
        except Exception:
            detail = response.text

        raise RuntimeError(
            f"OpenRouter a renvoyé HTTP {response.status_code}: {detail}"
        )

    data = response.json()

    try:
        content = data["choices"][0]["message"]["content"]
    except Exception:
        raise RuntimeError(
            "Réponse OpenRouter invalide ou vide."
        )

    content = clean_text(content)

    if not content:
        raise RuntimeError("OpenRouter a retourné un texte vide.")

    return content


# ============================================================
# GENERATION DU SCRIPT PRINCIPAL
# ============================================================

def generate_main_script(topic: str, attempt: int = 1) -> str:

    system_prompt = """
Vous êtes un scénariste spécialisé dans les histoires historiques vraies
pour YouTube.

Votre priorité absolue est l'exactitude historique.

RÈGLES ABSOLUES :
- Ne jamais inventer de faits.
- Ne jamais inventer de citation.
- Ne jamais inventer de date.
- Ne jamais présenter une légende comme un fait établi.
- Si un détail est incertain, ne pas l'utiliser.
- Raconter une histoire réellement documentée.
- Le texte doit être naturel à l'oral.
- Éviter les répétitions.
- Chaque phrase doit apporter une information ou faire progresser le récit.
- Le début doit avoir un hook fort.
- Le récit doit suivre une progression chronologique claire.
- Utiliser des phrases relativement courtes pour la narration.
- Ne pas ajouter de bibliographie dans le script.
- Ne pas utiliser de Markdown.
- Les indications d'images doivent être en anglais et exactement sous la forme :
  [IMAGE: english visual keywords]

Le nombre de mots sert uniquement à déterminer le format final.
Il ne faut JAMAIS remplir artificiellement le texte pour atteindre un seuil.
"""

    if attempt == 1:
        target = """
Écrivez une histoire complète d'environ 550 à 900 mots.

Un script entre 200 et 699 mots sera automatiquement transformé en Short
ou en deux Shorts par le programme.

Un script entre 700 et 1000 mots sera utilisé pour une vidéo longue.

Ne raccourcissez pas artificiellement une histoire intéressante.
Ne rallongez pas artificiellement une histoire trop courte.
"""
    else:
        target = """
Votre précédente proposition était trop courte.

Développez l'histoire avec de véritables informations historiques
supplémentaires et vérifiables.

Ne répétez pas les mêmes informations.
Ne créez aucun fait.

Essayez d'obtenir au moins 200 mots.
"""

    user_prompt = f"""
Sujet historique :
{topic}

{target}

Structure souhaitée :

1. Hook immédiat.
2. Contexte historique.
3. Déroulement des événements.
4. Moment central ou tournant.
5. Conséquences.
6. Conclusion mémorable.

Ajoutez régulièrement des indications [IMAGE: english visual keywords]
adaptées à ce qui est raconté.

Le texte doit rester fluide lorsqu'il est lu par une voix IA.

Retournez uniquement le script.
"""

    return openrouter_request(
        system_prompt,
        user_prompt,
        temperature=0.65,
        max_tokens=5000,
    )


# ============================================================
# DECISION DU FORMAT
# ============================================================

def choose_content_mode(word_count: int) -> str:

    if word_count < MIN_WORDS:
        return "REGENERATE"

    if word_count <= ONE_SHORT_MAX:
        return "ONE_SHORT"

    if word_count <= TWO_SHORT_MAX:
        return "TWO_SHORTS"

    return "LONG_PLUS_TEASER"


# ============================================================
# CREATION DES SHORTS A PARTIR DU SCRIPT
# ============================================================

def generate_one_short(source_script: str, topic: str) -> str:

    system_prompt = """
Vous êtes un monteur éditorial spécialisé dans les YouTube Shorts historiques.

Vous devez transformer une histoire historique vraie en un Short très
dynamique.

RÈGLES :
- Ne rien inventer.
- Conserver uniquement les informations réellement présentes dans le script.
- Ne pas ajouter de faits non présents dans la source.
- 25 à 40 secondes environ.
- Environ 60 à 100 mots.
- Hook dès le début.
- Fin claire.
- Texte naturel à l'oral.
- Ajouter 7 à 12 indications d'images.
- Les indications doivent être en anglais :
  [IMAGE: english visual keywords]
- Ne mettre aucune indication technique en dehors de [IMAGE: ...].
- Retourner uniquement le script.
"""

    prompt = f"""
Sujet :
{topic}

Script source :
{source_script}

Créez un seul Short à partir de cette histoire.
Ne perdez pas le fait historique principal.
"""

    return openrouter_request(
        system_prompt,
        prompt,
        temperature=0.55,
        max_tokens=1800,
    )


def generate_two_shorts(source_script: str, topic: str) -> Tuple[str, str]:

    system_prompt = """
Vous êtes un scénariste spécialisé dans les YouTube Shorts historiques.

Vous devez transformer une histoire historique vraie en DEUX Shorts
complémentaires.

IMPORTANT :
Il ne faut PAS simplement couper le texte en deux.

Vous devez restructurer et condenser l'histoire pour obtenir deux épisodes
courts, cohérents et intéressants.

OBJECTIF :
- Partie 1 : environ 25 à 40 secondes.
- Partie 2 : environ 25 à 40 secondes.
- Environ 60 à 100 mots par partie.
- Les deux parties doivent raconter ensemble la même histoire.
- Partie 1 présente le contexte et le début.
- Partie 1 doit terminer avec une transition qui donne envie de voir la suite.
- Partie 2 reprend immédiatement l'histoire.
- Partie 2 contient le moment important, les conséquences et la conclusion.
- Ne jamais inventer.
- Ne jamais ajouter de faits absents du script source.
- Ne pas répéter inutilement le contenu de la Partie 1 dans la Partie 2.
- Chaque partie doit avoir un hook.
- Chaque partie doit contenir 7 à 12 indications d'images.
- Les indications d'images doivent être en anglais :
  [IMAGE: english visual keywords]

FORMAT OBLIGATOIRE :

=== PARTIE 1 ===
[TEXTE]

=== PARTIE 2 ===
[TEXTE]

Retournez uniquement ce format.
"""

    prompt = f"""
Sujet :
{topic}

Script historique source :
{source_script}

Transformez cette histoire en deux Shorts complémentaires.
"""

    result = openrouter_request(
        system_prompt,
        prompt,
        temperature=0.6,
        max_tokens=3500,
    )

    part1_match = re.search(
        r"===\s*PARTIE\s*1\s*===\s*(.*?)(?====\s*PARTIE\s*2\s*===)",
        result,
        flags=re.IGNORECASE | re.DOTALL,
    )

    part2_match = re.search(
        r"===\s*PARTIE\s*2\s*===\s*(.*)$",
        result,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if not part1_match or not part2_match:
        raise RuntimeError(
            "OpenRouter n'a pas respecté le format demandé pour les deux Shorts."
        )

    part1 = clean_text(part1_match.group(1))
    part2 = clean_text(part2_match.group(1))

    if count_words(part1) < 35 or count_words(part2) < 35:
        raise RuntimeError(
            "L'un des deux Shorts générés est trop court."
        )

    return part1, part2


# ============================================================
# TEASER
# ============================================================

def generate_teaser(long_script: str, topic: str) -> str:

    system_prompt = """
Vous êtes spécialiste des teasers YouTube Shorts.

Créez un teaser de 25 à 40 secondes pour une vidéo historique.

RÈGLES :
- Ne rien inventer.
- Utiliser uniquement les informations du script source.
- Hook extrêmement rapide.
- Créer de la curiosité.
- Ne pas raconter toute l'histoire.
- Donner envie de regarder la vidéo complète.
- Environ 70 à 100 mots.
- Ajouter 7 à 12 indications d'images en anglais :
  [IMAGE: english visual keywords]
- Terminer par un appel à l'action naturel.
- Retourner uniquement le script.
"""

    prompt = f"""
Sujet :
{topic}

Script de la vidéo longue :
{long_script}

Créez un teaser Short.
"""

    return openrouter_request(
        system_prompt,
        prompt,
        temperature=0.65,
        max_tokens=1800,
    )


# ============================================================
# PARSING DES IMAGES
# ============================================================

def parse_script(script: str) -> Tuple[str, List[str]]:

    image_keywords = re.findall(
        r"\[IMAGE:\s*(.*?)\]",
        script,
        flags=re.IGNORECASE,
    )

    narration = re.sub(
        r"\[IMAGE:\s*.*?\]",
        "",
        script,
        flags=re.IGNORECASE,
    )

    narration = clean_text(narration)

    # Retire les éventuels titres
    narration = re.sub(
        r"^\s*(PARTIE\s*[12]|SHORT|SCRIPT)\s*:?\s*",
        "",
        narration,
        flags=re.IGNORECASE,
    )

    return narration.strip(), image_keywords


# ============================================================
# PEXELS
# ============================================================

def pexels_headers() -> Dict[str, str]:
    key = get_secret("PEXELS_API_KEY")

    if not key:
        raise RuntimeError(
            "PEXELS_API_KEY est absente."
        )

    return {
        "Authorization": key,
    }


def download_file(url: str, destination: Path) -> bool:

    try:
        response = requests.get(
            url,
            timeout=45,
            stream=True,
            headers={
                "User-Agent": "StudioVideoIA/1.0"
            },
        )

        if response.status_code != 200:
            return False

        with open(destination, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 256):
                if chunk:
                    f.write(chunk)

        return destination.exists() and destination.stat().st_size > 5000

    except Exception:
        return False


def search_pexels_photo(query: str, index: int) -> Optional[Path]:

    try:
        response = requests.get(
            PEXELS_SEARCH_URL,
            headers=pexels_headers(),
            params={
                "query": query,
                "per_page": 15,
                "orientation": "landscape",
            },
            timeout=30,
        )

        if response.status_code != 200:
            return None

        data = response.json()
        photos = data.get("photos", [])

        if not photos:
            return None

        # Mélange léger pour éviter de récupérer toujours les mêmes résultats
        random.shuffle(photos)

        for photo in photos[:8]:
            src = photo.get("src", {})
            url = (
                src.get("large2x")
                or src.get("large")
                or src.get("original")
            )

            if not url:
                continue

            destination = TEMP_DIR / f"visual_{index}_{random.randint(1000,9999)}.jpg"

            if download_file(url, destination):
                return destination

    except Exception:
        return None

    return None


def create_placeholder(path: Path, text: str = "VISUEL") -> Path:

    width, height = 1920, 1080

    image = Image.new(
        "RGB",
        (width, height),
        (18, 18, 18),
    )

    # Image très simple de secours.
    image.save(path, quality=90)

    return path


def get_visuals(
    image_keywords: List[str],
    target_count: int,
) -> List[Path]:

    if not image_keywords:
        image_keywords = [
            "ancient history",
            "historical city",
            "old historical photograph",
            "ancient battlefield",
            "historic building",
        ]

    keywords = image_keywords[:target_count]

    visuals = []

    for i, keyword in enumerate(keywords):
        visual = search_pexels_photo(keyword, i)

        if visual:
            visuals.append(visual)

    # Si Pexels ne fournit pas suffisamment d'images,
    # on réutilise les images déjà téléchargées.
    if visuals:
        while len(visuals) < target_count:
            visuals.append(visuals[len(visuals) % len(visuals)])

    else:
        placeholder = TEMP_DIR / "placeholder.jpg"
        if not placeholder.exists():
            create_placeholder(placeholder)

        visuals = [placeholder] * target_count

    return visuals[:target_count]


# ============================================================
# EDGE TTS
# ============================================================

def get_available_french_voices() -> List[str]:

    try:
        voices = edge_tts.list_voices()

        available = [
            voice["ShortName"]
            for voice in voices
            if voice.get("Locale") == "fr-FR"
            and voice.get("ShortName")
        ]

        ordered = []

        for voice in PREFERRED_VOICES:
            if voice in available:
                ordered.append(voice)

        for voice in available:
            if voice not in ordered:
                ordered.append(voice)

        if ordered:
            return ordered

    except Exception:
        pass

    return PREFERRED_VOICES.copy()


def synthesize_with_voice(
    text: str,
    voice: str,
    output_path: Path,
) -> List[Dict]:

    communicate = edge_tts.Communicate(
        text,
        voice,
        rate="+5%",
        volume="+0%",
        pitch="+0Hz",
        boundary="WordBoundary",
    )

    timings = []
    audio_received = False

    with open(output_path, "wb") as audio_file:

        for chunk in communicate.stream_sync():

            chunk_type = chunk.get("type")

            if chunk_type == "audio":
                data = chunk.get("data", b"")

                if data:
                    audio_received = True
                    audio_file.write(data)

            elif chunk_type == "WordBoundary":
                offset = chunk.get("offset")
                duration = chunk.get("duration")
                word = chunk.get("text", "")

                if offset is not None:
                    timings.append(
                        {
                            "word": word,
                            "start": float(offset) / 10_000_000,
                            "duration": (
                                float(duration) / 10_000_000
                                if duration is not None
                                else 0.1
                            ),
                        }
                    )

    if not audio_received:
        raise RuntimeError(
            f"Edge-TTS n'a reçu aucun audio avec la voix {voice}."
        )

    if not output_path.exists() or output_path.stat().st_size < 1000:
        raise RuntimeError(
            f"Le fichier audio produit par Edge-TTS est vide avec {voice}."
        )

    return timings


def get_audio_duration(audio_path: Path) -> float:

    result = run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ],
        timeout=60,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"FFprobe n'a pas pu lire la durée audio : {result.stderr}"
        )

    try:
        duration = float(result.stdout.strip())
    except Exception:
        raise RuntimeError(
            "FFprobe a retourné une durée audio invalide."
        )

    if duration <= 0:
        raise RuntimeError(
            "La durée audio est invalide."
        )

    return duration


def generate_audio(
    text: str,
    output_path: Path,
) -> Tuple[Path, List[Dict], float, str]:

    voices = get_available_french_voices()

    last_error = None

    for attempt, voice in enumerate(voices[:5], start=1):

        try:
            if output_path.exists():
                output_path.unlink()

            timings = synthesize_with_voice(
                text,
                voice,
                output_path,
            )

            duration = get_audio_duration(output_path)

            return output_path, timings, duration, voice

        except Exception as e:
            last_error = e

            # Petite pause pour éviter d'enchaîner immédiatement
            # plusieurs requêtes au service Edge.
            time.sleep(1.5)

    raise RuntimeError(
        "Edge-TTS a échoué avec toutes les voix françaises disponibles. "
        f"Dernière erreur : {last_error}"
    )


# ============================================================
# SOUS-TITRES ASS
# ============================================================

def ass_time(seconds: float) -> str:

    seconds = max(0, seconds)

    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centiseconds = int((seconds - int(seconds)) * 100)

    return (
        f"{hours}:{minutes:02d}:"
        f"{secs:02d}.{centiseconds:02d}"
    )


def escape_ass(text: str) -> str:

    text = text.replace("\\", r"\\")
    text = text.replace("{", r"\{")
    text = text.replace("}", r"\}")

    return text


def create_ass_subtitles(
    timings: List[Dict],
    output_path: Path,
    vertical: bool = False,
) -> None:

    if vertical:
        play_res_x = 1080
        play_res_y = 1920
        font_size = 58
        margin_v = 180
    else:
        play_res_x = 1920
        play_res_y = 1080
        font_size = 52
        margin_v = 90

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_res_x}
PlayResY: {play_res_y}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{font_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H99000000,1,0,0,0,100,100,0,0,1,3,1,2,60,60,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events = []

    # Affiche les mots individuellement.
    for i, timing in enumerate(timings):

        word = escape_ass(str(timing.get("word", "")).strip())

        if not word:
            continue

        start = float(timing.get("start", 0))

        if i + 1 < len(timings):
            end = float(timings[i + 1].get("start", start + 0.5))
        else:
            end = start + float(timing.get("duration", 0.5))

        if end <= start:
            end = start + 0.15

        events.append(
            f"Dialogue: 0,{ass_time(start)},"
            f"{ass_time(end)},Default,,0,0,0,,{word}"
        )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(header)
        f.write("\n".join(events))


# ============================================================
# MONTAGE
# ============================================================

def calculate_scene_durations(
    audio_duration: float,
    visual_count: int,
) -> List[float]:

    visual_count = max(1, visual_count)

    # Evite des scènes trop rapides.
    max_reasonable_count = max(
        1,
        int(audio_duration / 1.25),
    )

    scene_count = min(
        visual_count,
        max_reasonable_count,
    )

    weights = []

    for i in range(scene_count):
        weights.append(
            0.85 + ((i * 17) % 31) / 100.0
        )

    total_weight = sum(weights)

    durations = [
        audio_duration * weight / total_weight
        for weight in weights
    ]

    # Correction de précision.
    difference = audio_duration - sum(durations)

    durations[-1] += difference

    return durations


def create_image_scene(
    image_path: Path,
    duration: float,
    output_path: Path,
    vertical: bool,
) -> None:

    width = 1080 if vertical else 1920
    height = 1920 if vertical else 1080

    fps = 30

    frames = max(1, int(duration * fps))

    # Zoom progressif.
    zoom_end = 1.08 + random.random() * 0.10

    vf = (
        f"scale={width * 2}:{height * 2}:"
        f"force_original_aspect_ratio=increase,"
        f"crop={width * 2}:{height * 2},"
        f"zoompan="
        f"z='min(zoom+({zoom_end - 1.0})/{frames},{zoom_end})':"
        f"x='iw/2-(iw/zoom/2)':"
        f"y='ih/2-(ih/zoom/2)':"
        f"d={frames}:"
        f"s={width}x{height}:"
        f"fps={fps},"
        f"format=yuv420p"
    )

    result = run_command(
        [
            "ffmpeg",
            "-y",
            "-loop",
            "1",
            "-i",
            str(image_path),
            "-t",
            f"{duration:.3f}",
            "-vf",
            vf,
            "-r",
            str(fps),
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            str(output_path),
        ],
        timeout=180,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"FFmpeg a échoué pendant la création d'une scène :\n"
            f"{result.stderr[-3000:]}"
        )


def concat_scenes(
    scene_paths: List[Path],
    output_path: Path,
) -> None:

    concat_file = TEMP_DIR / f"concat_{random.randint(10000,99999)}.txt"

    with open(concat_file, "w", encoding="utf-8") as f:
        for path in scene_paths:
            safe_path = str(path.resolve()).replace("'", "'\\''")
            f.write(f"file '{safe_path}'\n")

    result = run_command(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c",
            "copy",
            str(output_path),
        ],
        timeout=300,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"FFmpeg n'a pas pu concaténer les scènes :\n"
            f"{result.stderr[-3000:]}"
        )


def add_audio_and_subtitles(
    video_path: Path,
    audio_path: Path,
    ass_path: Path,
    output_path: Path,
) -> None:

    # Le filtre ASS utilise le chemin absolu.
    ass_for_ffmpeg = str(ass_path.resolve()).replace("\\", "/")
    ass_for_ffmpeg = ass_for_ffmpeg.replace(":", r"\:")

    vf = f"subtitles='{ass_for_ffmpeg}'"

    result = run_command(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-i",
            str(audio_path),
            "-vf",
            vf,
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "19",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            "-movflags",
            "+faststart",
            str(output_path),
        ],
        timeout=600,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"FFmpeg n'a pas pu assembler audio + vidéo + sous-titres :\n"
            f"{result.stderr[-4000:]}"
        )


def build_video(
    narration: str,
    visuals: List[Path],
    audio_path: Path,
    timings: List[Dict],
    output_path: Path,
    vertical: bool,
) -> Tuple[Path, float]:

    ensure_ffmpeg()

    audio_duration = get_audio_duration(audio_path)

    scene_durations = calculate_scene_durations(
        audio_duration,
        len(visuals),
    )

    # Les visuels doivent correspondre exactement au nombre de scènes.
    visuals = visuals[:len(scene_durations)]

    if not visuals:
        raise RuntimeError(
            "Aucun visuel disponible pour le montage."
        )

    scene_paths = []

    progress_bar = st.progress(
        0,
        text="Création des scènes vidéo...",
    )

    for index, (visual, duration) in enumerate(
        zip(visuals, scene_durations)
    ):

        scene_path = TEMP_DIR / (
            f"scene_{random.randint(100000,999999)}_{index}.mp4"
        )

        create_image_scene(
            visual,
            duration,
            scene_path,
            vertical,
        )

        scene_paths.append(scene_path)

        progress_bar.progress(
            int(((index + 1) / len(visuals)) * 100),
            text=f"Création des scènes vidéo... {index + 1}/{len(visuals)}",
        )

    progress_bar.empty()

    raw_video = TEMP_DIR / (
        f"raw_{random.randint(100000,999999)}.mp4"
    )

    concat_scenes(
        scene_paths,
        raw_video,
    )

    ass_path = TEMP_DIR / (
        f"subtitles_{random.randint(100000,999999)}.ass"
    )

    create_ass_subtitles(
        timings,
        ass_path,
        vertical=vertical,
    )

    add_audio_and_subtitles(
        raw_video,
        audio_path,
        ass_path,
        output_path,
    )

    if not output_path.exists() or output_path.stat().st_size < 10000:
        raise RuntimeError(
            "La vidéo finale n'a pas été créée correctement."
        )

    return output_path, get_audio_duration(audio_path)


# ============================================================
# PREPARATION DU NOMBRE DE VISUELS
# ============================================================

def visual_count_for_duration(
    duration: float,
    vertical: bool,
) -> int:

    if vertical:
        # Environ un visuel toutes les 3 secondes.
        return max(
            7,
            min(
                14,
                int(round(duration / 3.0)),
            ),
        )

    # Vidéo longue : visuel toutes les ~6 secondes.
    return max(
        12,
        min(
            36,
            int(round(duration / 6.0)),
        ),
    )


# ============================================================
# GENERATION D'UN SHORT
# ============================================================

def create_short_video(
    script: str,
    filename: str,
    label: str,
) -> Path:

    narration, image_keywords = parse_script(script)

    if not narration:
        raise RuntimeError(
            f"{label} : narration vide."
        )

    word_count = count_words(narration)

    st.info(
        f"{label} : {word_count} mots."
    )

    audio_path = TEMP_DIR / (
        f"audio_{random.randint(100000,999999)}.mp3"
    )

    with st.spinner(f"Génération de la voix pour {label}..."):
        (
            audio_path,
            timings,
            duration,
            voice,
        ) = generate_audio(
            narration,
            audio_path,
        )

    st.write(
        f"Voix utilisée : {voice} | Durée : {format_seconds(duration)}"
    )

    if duration > SHORT_MAX_SECONDS:
        st.warning(
            f"{label} dépasse légèrement la durée cible "
            f"({format_seconds(duration)}). "
            "La vidéo sera quand même générée."
        )

    target_visuals = visual_count_for_duration(
        duration,
        vertical=True,
    )

    visuals = get_visuals(
        image_keywords,
        target_visuals,
    )

    output_path = OUTPUT_DIR / filename

    with st.spinner(f"Montage de {label}..."):
        build_video(
            narration,
            visuals,
            audio_path,
            output_path,
            vertical=True,
        )

    return output_path


# ============================================================
# GENERATION VIDEO LONGUE
# ============================================================

def create_long_video(
    script: str,
    filename: str,
) -> Tuple[Path, float]:

    narration, image_keywords = parse_script(script)

    if not narration:
        raise RuntimeError(
            "La narration de la vidéo longue est vide."
        )

    word_count = count_words(narration)

    st.info(
        f"Script vidéo longue : {word_count} mots."
    )

    audio_path = TEMP_DIR / (
        f"audio_long_{random.randint(100000,999999)}.mp3"
    )

    with st.spinner("Génération de la narration..."):
        (
            audio_path,
            timings,
            duration,
            voice,
        ) = generate_audio(
            narration,
            audio_path,
        )

    st.write(
        f"Voix utilisée : {voice} | Durée audio : {format_seconds(duration)}"
    )

    # AUCUNE durée minimale.
    # Une vidéo longue est acceptée dès lors que le routage
    # l'a classée dans LONG_PLUS_TEASER.

    target_visuals = visual_count_for_duration(
        duration,
        vertical=False,
    )

    visuals = get_visuals(
        image_keywords,
        target_visuals,
    )

    output_path = OUTPUT_DIR / filename

    with st.spinner("Montage de la vidéo longue..."):
        build_video(
            narration,
            visuals,
            audio_path,
            output_path,
            vertical=False,
        )

    return output_path, duration


# ============================================================
# NETTOYAGE
# ============================================================

def cleanup_temp_files() -> None:

    for path in TEMP_DIR.glob("*"):
        try:
            if path.is_file():
                path.unlink()
        except Exception:
            pass


# ============================================================
# INTERFACE STREAMLIT
# ============================================================

st.set_page_config(
    page_title=APP_TITLE,
    page_icon="🎬",
    layout="wide",
)

st.title("🎬 Studio Vidéo IA")

st.write(
    "Créez automatiquement une vidéo historique et le format adapté "
    "à partir du nombre de mots du script."
)

st.markdown(
    """
### Routage automatique

- **Moins de 200 mots** → régénération automatique
- **200 à 349 mots** → 1 Short
- **350 à 699 mots** → 2 Shorts : Partie 1 + Partie 2
- **700 à 1000 mots** → vidéo longue + teaser
- **Plus de 1000 mots** → vidéo longue + teaser
"""
)

topic = st.text_input(
    "Sujet de la vidéo",
    placeholder="Exemple : La chute de Constantinople",
)

generate_button = st.button(
    "🚀 Générer le Pack",
    type="primary",
    use_container_width=True,
)


# ============================================================
# WORKFLOW PRINCIPAL
# ============================================================

if generate_button:

    if not topic.strip():
        st.error(
            "Veuillez entrer un sujet historique."
        )
        st.stop()

    cleanup_temp_files()

    try:

        # ----------------------------------------------------
        # 1. GENERATION DU SCRIPT
        # ----------------------------------------------------

        st.subheader("1. Génération du script")

        with st.spinner("Recherche et rédaction de l'histoire..."):

            script = generate_main_script(
                topic.strip(),
                attempt=1,
            )

        word_count = count_words(script)
        mode = choose_content_mode(word_count)

        # ----------------------------------------------------
        # 2. REGENERATION SI < 200 MOTS
        # ----------------------------------------------------

        if mode == "REGENERATE":

            st.warning(
                f"Le premier script contient seulement {word_count} mots. "
                "Le contenu est trop court. Nouvelle génération automatique..."
            )

            with st.spinner("Enrichissement automatique du script..."):

                script = generate_main_script(
                    topic.strip(),
                    attempt=2,
                )

            word_count = count_words(script)
            mode = choose_content_mode(word_count)

        # ----------------------------------------------------
        # Si toujours < 200
        # ----------------------------------------------------

        if mode == "REGENERATE":

            st.error(
                f"Le script reste trop court après deux tentatives "
                f"({word_count} mots). "
                "Impossible de produire un contenu suffisamment développé."
            )

            st.stop()

        # ----------------------------------------------------
        # 3. AFFICHAGE DU MODE
        # ----------------------------------------------------

        st.success(
            f"Script généré : {word_count} mots."
        )

        if mode == "ONE_SHORT":

            st.info(
                f"Format sélectionné automatiquement : 1 Short "
                f"({word_count} mots)"
            )

        elif mode == "TWO_SHORTS":

            st.info(
                f"Format sélectionné automatiquement : "
                f"2 Shorts Partie 1 + Partie 2 ({word_count} mots)"
            )

        else:

            st.info(
                f"Format sélectionné automatiquement : "
                f"vidéo longue + teaser ({word_count} mots)"
            )

        # ----------------------------------------------------
        # 4. MODE 1 SHORT
        # ----------------------------------------------------

        if mode == "ONE_SHORT":

            st.subheader("2. Création du Short")

            with st.spinner(
                "Transformation du script en Short..."
            ):

                short_script = generate_one_short(
                    script,
                    topic,
                )

            short_path = create_short_video(
                short_script,
                "short.mp4",
                "Short",
            )

            st.success(
                "Short terminé."
            )

            st.video(str(short_path))

            st.download_button(
                "Télécharger le Short",
                data=short_path.read_bytes(),
                file_name="short.mp4",
                mime="video/mp4",
                use_container_width=True,
            )

        # ----------------------------------------------------
        # 5. MODE 2 SHORTS
        # ----------------------------------------------------

        elif mode == "TWO_SHORTS":

            st.subheader(
                "2. Création automatique des deux Shorts"
            )

            st.write(
                "Le script n'est pas simplement coupé en deux. "
                "L'IA restructure l'histoire pour créer deux épisodes "
                "courts et cohérents."
            )

            with st.spinner(
                "Découpage éditorial en Partie 1 et Partie 2..."
            ):

                short1_script, short2_script = generate_two_shorts(
                    script,
                    topic,
                )

            st.markdown("### Partie 1")

            short1_path = create_short_video(
                short1_script,
                "short_partie_1.mp4",
                "Short Partie 1",
            )

            st.success(
                "Short Partie 1 terminé."
            )

            st.video(str(short1_path))

            st.download_button(
                "Télécharger Partie 1",
                data=short1_path.read_bytes(),
                file_name="short_partie_1.mp4",
                mime="video/mp4",
                use_container_width=True,
            )

            st.markdown("### Partie 2")

            short2_path = create_short_video(
                short2_script,
                "short_partie_2.mp4",
                "Short Partie 2",
            )

            st.success(
                "Short Partie 2 terminé."
            )

            st.video(str(short2_path))

            st.download_button(
                "Télécharger Partie 2",
                data=short2_path.read_bytes(),
                file_name="short_partie_2.mp4",
                mime="video/mp4",
                use_container_width=True,
            )

            st.success(
                "Pack de 2 Shorts terminé : Partie 1 + Partie 2."
            )

        # ----------------------------------------------------
        # 6. MODE VIDEO LONGUE + TEASER
        # ----------------------------------------------------

        else:

            st.subheader(
                "2. Création de la vidéo longue"
            )

            long_path, long_duration = create_long_video(
                script,
                "video_longue.mp4",
            )

            st.success(
                f"Vidéo longue terminée : "
                f"{format_seconds(long_duration)}"
            )

            st.video(str(long_path))

            st.download_button(
                "Télécharger la vidéo longue",
                data=long_path.read_bytes(),
                file_name="video_longue.mp4",
                mime="video/mp4",
                use_container_width=True,
            )

            # ------------------------------------------------
            # TEASER
            # ------------------------------------------------

            st.subheader(
                "3. Création du teaser Short"
            )

            with st.spinner(
                "Création du teaser..."
            ):

                teaser_script = generate_teaser(
                    script,
                    topic,
                )

            teaser_path = create_short_video(
                teaser_script,
                "teaser_short.mp4",
                "Teaser",
            )

            st.success(
                "Teaser terminé."
            )

            st.video(str(teaser_path))

            st.download_button(
                "Télécharger le teaser",
                data=teaser_path.read_bytes(),
                file_name="teaser_short.mp4",
                mime="video/mp4",
                use_container_width=True,
            )

            st.success(
                "Pack Duo terminé : vidéo longue + teaser."
            )

        # ----------------------------------------------------
        # FIN
        # ----------------------------------------------------

        st.balloons()

    except Exception as e:

        st.error(
            "La génération a rencontré un problème."
        )

        st.exception(e)

        st.info(
            "Le programme n'utilise plus le seuil de 700 mots comme "
            "une erreur. Ce seuil sert uniquement à choisir le format."
        )

finally:
    pass
