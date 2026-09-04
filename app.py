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


def run_command(
    command: List[str],
    timeout: int = 300,
) -> subprocess.CompletedProcess:

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
        raise RuntimeError(
            "OpenRouter a retourné un texte vide."
        )

    return content


# ============================================================
# GENERATION DU SCRIPT PRINCIPAL
# ============================================================

def generate_main_script(
    topic: str,
    attempt: int = 1,
) -> str:

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

def generate_one_short(
    source_script: str,
    topic: str,
) -> str:

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


def generate_two_shorts(
    source_script: str,
    topic: str,
) -> Tuple[str, str]:

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

def generate_teaser(
    long_script: str,
    topic: str,
) -> str:

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

def parse_script(
    script: str,
) -> Tuple[str, List[str]]:

    image_keywords = re.findall(
        r"IMAGE:\s*(.*?)",
        script,
        flags=re.IGNORECASE,
    )

    narration = re.sub(
        r"IMAGE:\s*.*?",
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


def download_file(
    url: str,
    destination: Path,
) -> bool:

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
            for chunk in response.iter_content(
                chunk_size=1024 * 256
            ):
                if chunk:
                    f.write(chunk)

        return (
            destination.exists()
            and destination.stat().st_size > 5000
        )

    except Exception:
        return False


def search_pexels_photo(
    query: str,
    index: int,
) -> Optional[Path]:

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

            destination = TEMP_DIR / (
                f"visual_{index}_{random.randint(1000,9999)}.jpg"
            )

            if download_file(
                url,
                destination,
            ):
                return destination

    except Exception:
        return None

    return None


def create_placeholder(
    path: Path,
    text: str = "VISUEL",
) -> Path:

    width, height = 1920, 1080

    image = Image.new(
        "RGB",
        (width, height),
        (18, 18, 18),
    )

    # Image très simple de secours.
    image.save(
        path,
        quality=90,
    )

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

        visual = search_pexels_photo(
            keyword,
            i,
        )

        if visual:
            visuals.append(visual)

    # Si Pexels ne fournit pas suffisamment d'images,
    # on réutilise les images déjà téléchargées.
    if visuals:

        while len(visuals) < target_count:
            visuals.append(
                visuals[len(visuals) % len(visuals)]
            )

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
    text: str
