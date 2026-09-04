import os
import re
import time
import shutil
import random
import asyncio
import threading
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import requests
import streamlit as st
import edge_tts
from PIL import Image


# ============================================================
# CONFIGURATION GÉNÉRALE
# ============================================================

APP_TITLE = "Studio Vidéo IA"

TEMP_ROOT = Path("temp_video")
TEMP_ROOT.mkdir(parents=True, exist_ok=True)

OUTPUT_ROOT = Path("outputs")
OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

ASSETS_ROOT = Path("assets")
ASSETS_ROOT.mkdir(parents=True, exist_ok=True)

PEXELS_API_URL = "https://api.pexels.com/v1/search"
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

OPENROUTER_MODEL = "meta-llama/llama-3.3-70b-instruct"

# ------------------------------------------------------------
# Routage du contenu
# ------------------------------------------------------------

MIN_REGENERATE_WORDS = 200

SHORT_MIN_WORDS = 60
SHORT_MAX_WORDS = 100

TWO_SHORTS_MIN_SCRIPT_WORDS = 350
TWO_SHORTS_MAX_SCRIPT_WORDS = 699

LONG_VIDEO_MIN_WORDS = 700
LONG_VIDEO_MAX_WORDS = 1000

# ------------------------------------------------------------
# Durées visées
# ------------------------------------------------------------

SHORT_MIN_SECONDS = 25
SHORT_MAX_SECONDS = 45

# Pas de durée minimale artificielle pour les vidéos longues.
# Une vidéo longue est acceptée dès lors que son script est
# suffisamment développé pour ce mode.
LONG_MAX_SECONDS = 900

# ------------------------------------------------------------
# Voix françaises préférées
# ------------------------------------------------------------

PREFERRED_VOICES = [
    "fr-FR-DeniseNeural",
    "fr-FR-HenriNeural",
    "fr-FR-EloiseNeural",
    "fr-FR-VivienneMultilingualNeural",
]

# ------------------------------------------------------------
# Extensions autorisées
# ------------------------------------------------------------

IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
}

VIDEO_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".mkv",
    ".webm",
}


# ============================================================
# OUTILS DE CONFIGURATION
# ============================================================

def get_secret(name: str, default: str = "") -> str:
    """
    Récupère une variable depuis st.secrets ou os.environ.
    """
    try:
        value = st.secrets.get(name)
        if value:
            return str(value).strip()
    except Exception:
        pass

    return os.getenv(name, default).strip()


OPENROUTER_API_KEY = get_secret("OPENROUTER_API_KEY")
PEXELS_API_KEY = get_secret("PEXELS_API_KEY")


# ============================================================
# OUTILS TEXTE
# ============================================================

def clean_text(text: str) -> str:
    """
    Nettoie le texte sans supprimer les marqueurs [IMAGE: ...].
    """
    if not text:
        return ""

    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

    # Supprime les espaces inutiles.
    text = re.sub(r"[ \t]+", " ", text)

    # Évite les lignes vides multiples.
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def count_words(text: str) -> int:
    """
    Compte les mots de narration.
    Les marqueurs [IMAGE: ...] sont exclus du comptage.
    """
    if not text:
        return 0

    text_without_images = re.sub(
        r"\[IMAGE:.*?\]",
        " ",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    words = re.findall(
        r"\b[\wÀ-ÿŒœÆæ'-]+\b",
        text_without_images,
        flags=re.UNICODE,
    )

    return len(words)


def format_seconds(seconds: float) -> str:
    """
    Transforme une durée en MM:SS.
    """
    seconds = max(0, float(seconds))

    minutes = int(seconds // 60)
    remaining = int(seconds % 60)

    return f"{minutes:02d}:{remaining:02d}"


# ============================================================
# EXÉCUTION DES COMMANDES SYSTÈME
# ============================================================

def run_command(
    command: List[str],
    timeout: int = 300,
) -> subprocess.CompletedProcess:
    """
    Exécute une commande système et retourne son résultat.
    """
    return subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False,
    )


def ensure_ffmpeg() -> None:
    """
    Vérifie que ffmpeg et ffprobe sont disponibles.
    """
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")

    if not ffmpeg:
        raise RuntimeError(
            "FFmpeg est introuvable sur le serveur. "
            "Vérifiez que le fichier apt.txt contient bien : ffmpeg"
        )

    if not ffprobe:
        raise RuntimeError(
            "FFprobe est introuvable sur le serveur. "
            "Vérifiez l'installation de FFmpeg."
        )


# ============================================================
# OPENROUTER
# ============================================================

def openrouter_request(
    messages: List[Dict[str, str]],
    temperature: float = 0.8,
    max_tokens: int = 2500,
    timeout: int = 120,
) -> str:
    """
    Envoie une requête au modèle via OpenRouter.
    """
    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY est absente. "
            "Ajoutez-la dans les variables d'environnement de Render."
        )

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://shorts-viraux-1.onrender.com",
        "X-Title": APP_TITLE,
    }

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    response = requests.post(
        OPENROUTER_API_URL,
        headers=headers,
        json=payload,
        timeout=timeout,
    )

    if response.status_code != 200:
        try:
            details = response.json()
        except Exception:
            details = response.text

        raise RuntimeError(
            f"OpenRouter a retourné HTTP {response.status_code}: {details}"
        )

    data = response.json()

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(
            "Réponse OpenRouter invalide ou incomplète."
        ) from exc

    if not content or not content.strip():
        raise RuntimeError(
            "OpenRouter a retourné une réponse vide."
        )

    return clean_text(content)


# ============================================================
# GÉNÉRATION DU SCRIPT PRINCIPAL
# ============================================================

def generate_main_script(topic: str) -> str:
    """
    Génère le script principal sur la psychologie, le cerveau
    et le comportement humain.
    """

    system_prompt = """
Vous êtes un vulgarisateur scientifique spécialisé dans :

- psychologie cognitive
- neurosciences
- fonctionnement du cerveau
- comportement humain
- mémoire
- attention
- prise de décision
- habitudes
- apprentissage
- sommeil
- stress
- motivation
- perception
- émotions
- cognition

Votre mission est de produire des scripts captivants mais scientifiquement sérieux.

RÈGLES ABSOLUES DE FIABILITÉ :

1. Ne présentez jamais une invention comme un fait scientifique.
2. N'inventez jamais une étude, un chercheur, une date, un pourcentage
   ou une expérience.
3. N'utilisez pas de pseudo-science.
4. Évitez les affirmations absolues du type :
   "les scientifiques ont prouvé que tous les humains..."
   lorsque les données ne permettent pas une telle généralisation.
5. Ne diagnostiquez jamais le spectateur.
6. Ne transformez pas une tendance psychologique générale en règle
   valable pour chaque personne.
7. Lorsque les connaissances scientifiques sont nuancées,
   utilisez une formulation prudente.
8. Privilégiez les mécanismes largement documentés plutôt que
   les anecdotes sensationnalistes.
9. N'utilisez pas de termes scientifiques simplement pour donner
   une apparence scientifique au texte.
10. Si vous n'êtes pas certain d'un chiffre précis, ne donnez pas
    de chiffre précis.

STYLE :

- français naturel
- vocabulaire accessible
- phrases relativement courtes
- narration dynamique
- ton intrigant mais crédible
- aucune introduction lente
- aucune répétition inutile
- aucune conclusion générique

STRUCTURE :

Le début doit immédiatement créer une question ou un paradoxe.

Exemples de mécaniques d'accroche :

- "Pourquoi est-ce que..."
- "Votre cerveau fait quelque chose d'étrange..."
- "Vous pensez que..., mais..."
- "Le plus surprenant, c'est que..."
- "Il existe une raison pour laquelle..."

NE DONNEZ PAS immédiatement toute la réponse.

Construisez progressivement l'explication afin de maintenir
la curiosité jusqu'à la fin.

Le script doit apporter une véritable explication,
pas simplement accumuler des faits étonnants.

À la fin, donnez une conclusion courte et mémorable.

FORMAT DES VISUELS :

Ajoutez des marqueurs [IMAGE: description] régulièrement
dans le script.

Chaque description doit correspondre à une scène visuelle
facilement recherchable :

- cerveau
- personne
- comportement
- environnement
- objet
- situation quotidienne
- concept visuel

Ne mettez jamais de texte important à afficher dans les images.

IMPORTANT :

Les marqueurs [IMAGE: ...] ne doivent jamais être considérés
comme des phrases de narration.
"""

    user_prompt = f"""
Créez un script de vulgarisation scientifique sur ce sujet :

{topic}

Le script principal doit contenir idéalement entre 550 et 900 mots
de narration.

Il doit être conçu pour pouvoir ensuite être transformé
automatiquement en vidéo longue ou en plusieurs Shorts.

Le spectateur doit avoir une raison de continuer après
les premières secondes.

Ne commencez pas par :
"Bonjour à tous",
"Bienvenue sur ma chaîne",
ou une présentation de la chaîne.

Commencez directement par l'idée intrigante.

Ajoutez suffisamment de marqueurs [IMAGE: ...] pour permettre
un montage dynamique.

Ne faites aucune affirmation que vous ne pouvez pas raisonnablement
défendre scientifiquement.
"""

    return openrouter_request(
        [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
        temperature=0.75,
        max_tokens=3000,
    )


# ============================================================
# CHOIX AUTOMATIQUE DU FORMAT
# ============================================================

def choose_content_mode(word_count: int) -> str:
    """
    Détermine le format en fonction du nombre de mots.
    """

    if word_count < MIN_REGENERATE_WORDS:
        return "regenerate"

    if 200 <= word_count <= 349:
        return "one_short"

    if TWO_SHORTS_MIN_SCRIPT_WORDS <= word_count <= TWO_SHORTS_MAX_SCRIPT_WORDS:
        return "two_shorts"

    if word_count >= LONG_VIDEO_MIN_WORDS:
        return "long"

    # Sécurité.
    return "one_short"


# ============================================================
# ENRICHISSEMENT AUTOMATIQUE D'UN SCRIPT TROP COURT
# ============================================================

def regenerate_short_main_script(
    topic: str,
    previous_script: str,
) -> str:
    """
    Demande au modèle d'enrichir un script trop court.
    """

    system_prompt = """
Vous êtes un vulgarisateur scientifique spécialisé en psychologie
cognitive, neurosciences et comportement humain.

Vous devez améliorer un script trop court.

Conservez uniquement les informations scientifiquement défendables.

N'inventez aucune étude, aucun chiffre et aucun fait.

Le nouveau script doit être plus riche, plus captivant et mieux structuré.

Il doit comporter :
- une accroche forte
- une explication progressive
- un mécanisme scientifique compréhensible
- un exemple concret du quotidien
- une conclusion mémorable

Ajoutez des marqueurs [IMAGE: description].

Ne commencez pas par une formule de bienvenue.
"""

    user_prompt = f"""
Sujet :
{topic}

Script actuel :
{previous_script}

Ce script est trop court.

Réécrivez-le complètement pour obtenir environ 550 à 850 mots
de narration.

Ne gonflez pas artificiellement le texte avec des répétitions.
Ajoutez de vraies explications utiles.

Répondez uniquement avec le nouveau script.
"""

    return openrouter_request(
        [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
        temperature=0.7,
        max_tokens=3000,
    )


# ============================================================
# GÉNÉRATION D'UN SHORT
# ============================================================

def generate_one_short(
    topic: str,
    source_script: str,
    retry_number: int = 0,
) -> str:
    """
    Transforme le sujet et le script source en un Short
    très condensé et captivant.
    """

    system_prompt = """
Vous êtes un scénariste spécialisé dans les Shorts de vulgarisation
scientifique sur la psychologie, le cerveau et le comportement humain.

Votre objectif est de maximiser la rétention sans sacrifier
l'exactitude scientifique.

Le Short doit :

1. commencer immédiatement par une accroche intrigante ;
2. créer une question dans l'esprit du spectateur ;
3. développer progressivement l'explication ;
4. donner une information réellement utile ou surprenante ;
5. terminer par une conclusion mémorable ;
6. rester scientifiquement prudent.

IMPORTANT :

Le texte de narration doit contenir entre 60 et 100 mots.

Ne comptez pas les marqueurs [IMAGE: ...] comme des mots.

Ne donnez pas toute la réponse dans la première phrase.

N'utilisez pas de fausses statistiques.

N'inventez pas d'études.

N'utilisez pas de pseudo-science.

Ne faites pas de diagnostic psychologique.

Ajoutez entre 7 et 12 marqueurs [IMAGE: description].

Chaque marqueur doit correspondre à un changement visuel pertinent.

Le script doit être naturel à l'oral.
"""

    retry_instruction = ""

    if retry_number > 0:
        retry_instruction = """
ATTENTION :
La tentative précédente ne respectait pas correctement
la longueur demandée.

Cette fois, respectez STRICTEMENT 60 à 100 mots de narration.
"""

    user_prompt = f"""
Sujet :
{topic}

Script source :
{source_script}

{retry_instruction}

Créez un Short autonome de 25 à 40 secondes environ.

Répondez uniquement avec le script.
"""

    return openrouter_request(
        [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
        temperature=0.8,
        max_tokens=1000,
    )


# ============================================================
# GÉNÉRATION DE DEUX SHORTS
# ============================================================

def generate_two_shorts(
    topic: str,
    source_script: str,
    retry_number: int = 0,
) -> Tuple[str, str]:
    """
    Transforme un script intermédiaire en deux Shorts cohérents.

    IMPORTANT :
    On ne coupe PAS simplement le texte en deux.
    Le modèle restructure les informations pour que chaque partie
    soit adaptée à un Short.
    """

    system_prompt = """
Vous êtes un scénariste spécialisé dans les Shorts de vulgarisation
scientifique sur la psychologie, les neurosciences et le comportement humain.

Transformez le contenu source en DEUX Shorts distincts :

PARTIE 1 :
- accroche très forte
- contexte
- première explication
- élément surprenant
- fin qui donne envie de voir la Partie 2

PARTIE 2 :
- reprise naturelle de la Partie 1
- suite de l'explication
- mécanisme scientifique
- conséquence ou exemple concret
- conclusion mémorable

RÈGLES :

Chaque partie doit contenir entre 60 et 100 mots
de narration, hors marqueurs [IMAGE: ...].

Chaque partie doit viser environ 25 à 40 secondes.

Ne coupez surtout pas le script source en deux moitiés.

Sélectionnez et reformulez les informations les plus importantes.

Ne répétez pas inutilement les mêmes phrases.

Ne révélez pas toute l'information dans la Partie 1.

N'inventez aucune étude, aucun chiffre, aucun chercheur
et aucun résultat scientifique.

Évitez les mythes populaires sur le cerveau.

Ne faites aucun diagnostic.

Chaque partie doit contenir entre 7 et 12 marqueurs [IMAGE: description].

FORMAT OBLIGATOIRE :

=== PARTIE 1 ===
[script]

=== PARTIE 2 ===
[script]
"""

    retry_instruction = ""

    if retry_number > 0:
        retry_instruction = """
IMPORTANT :
La tentative précédente ne respectait pas correctement la longueur
ou la structure.

Recommencez entièrement.

Les deux parties doivent chacune faire STRICTEMENT entre 60 et 100
mots de narration, hors marqueurs [IMAGE: ...].
"""

    user_prompt = f"""
Sujet :
{topic}

Contenu source :
{source_script}

{retry_instruction}

Répondez uniquement avec :

=== PARTIE 1 ===
...

=== PARTIE 2 ===
...
"""

    result = openrouter_request(
        [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
        temperature=0.8,
        max_tokens=1800,
    )

    match = re.search(
        r"===\s*PARTIE\s*1\s*===\s*(.*?)"
        r"===\s*PARTIE\s*2\s*===\s*(.*)",
        result,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if not match:
        raise RuntimeError(
            "Le modèle n'a pas retourné les deux parties "
            "dans le format attendu."
        )

    part1 = clean_text(match.group(1))
    part2 = clean_text(match.group(2))

    if not part1 or not part2:
        raise RuntimeError(
            "Une des deux parties du Short est vide."
        )

    return part1, part2


# ============================================================
# AJUSTEMENT AUTOMATIQUE DE LA LONGUEUR D'UN SHORT
# ============================================================

def fit_short_script(
    topic: str,
    script: str,
    part_label: str = "",
) -> str:
    """
    Vérifie la longueur d'un Short et demande une correction
    si nécessaire.

    Maximum de deux tentatives supplémentaires.
    """

    current = clean_text(script)

    for attempt in range(3):
        words = count_words(current)

        if SHORT_MIN_WORDS <= words <= SHORT_MAX_WORDS:
            return current

        direction = "plus court" if words > SHORT_MAX_WORDS else "plus long"

        current = openrouter_request(
            [
                {
                    "role": "system",
                    "content": """
Vous êtes un éditeur expert en Shorts scientifiques.

Réécrivez le script fourni sans changer son sens scientifique.

Objectif :
entre 60 et 100 mots de narration.

Le résultat doit être naturel à l'oral, captivant dès la première
phrase et adapté à une vidéo de 25 à 40 secondes.

Ne supprimez pas les informations essentielles.

N'inventez aucun fait.

Conservez ou recréez entre 7 et 12 marqueurs [IMAGE: description].

Répondez uniquement avec le script final.
""",
                },
                {
                    "role": "user",
                    "content": f"""
Sujet : {topic}

Partie : {part_label}

Script actuel :
{current}

Il contient actuellement {words} mots.

Réécrivez-le pour qu'il soit {direction} et respecte STRICTEMENT
la cible de 60 à 100 mots.
""",
                },
            ],
            temperature=0.65,
            max_tokens=900,
        )

    final_words = count_words(current)

    if final_words < SHORT_MIN_WORDS or final_words > SHORT_MAX_WORDS:
        raise RuntimeError(
            f"Impossible d'obtenir une longueur correcte pour "
            f"{part_label or 'le Short'} après plusieurs tentatives "
            f"(dernier résultat : {final_words} mots)."
        )

    return current


# ============================================================
# GÉNÉRATION DU TEASER
# ============================================================

def generate_teaser(
    topic: str,
    source_script: str,
) -> str:
    """
    Génère un teaser vertical à partir d'une vidéo longue.
    """

    system_prompt = """
Vous êtes un spécialiste des teasers YouTube Shorts
pour la vulgarisation scientifique.

Le sujet concerne la psychologie, le cerveau ou le comportement humain.

Créez un teaser de 60 à 100 mots maximum.

Le teaser doit :

- commencer par une accroche extrêmement intrigante ;
- présenter un paradoxe ou une question ;
- donner juste assez d'information pour intriguer ;
- ne pas révéler toute l'explication ;
- donner envie de regarder la vidéo complète ;
- rester scientifiquement exact.

Ne dites pas :
"Regardez la vidéo complète pour connaître la réponse"
de manière répétitive ou artificielle.

Ne faites aucune affirmation scientifique inventée.

Ajoutez 7 à 12 marqueurs [IMAGE: description].

Répondez uniquement avec le script.
"""

    user_prompt = f"""
Sujet :
{topic}

Script de la vidéo longue :
{source_script}

Créez un teaser vertical de 25 à 40 secondes environ.
"""

    teaser = openrouter_request(
        [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
        temperature=0.85,
        max_tokens=1000,
    )

    return fit_short_script(
        topic=topic,
        script=teaser,
        part_label="teaser",
    )# ============================================================
# MARQUEURS D'IMAGES
# ============================================================

IMAGE_MARKER_PATTERN = re.compile(
    r"\[IMAGE:\s*(.*?)\]",
    flags=re.IGNORECASE | re.DOTALL,
)


def extract_image_markers(text: str) -> List[str]:
    """
    Extrait toutes les descriptions présentes dans :
    [IMAGE: description]
    """
    if not text:
        return []

    markers = IMAGE_MARKER_PATTERN.findall(text)

    result = []

    for marker in markers:
        description = clean_text(marker)

        if description and description not in result:
            result.append(description)

    return result


def remove_image_markers(text: str) -> str:
    """
    Supprime les marqueurs [IMAGE: ...] de la narration.
    """
    if not text:
        return ""

    text = IMAGE_MARKER_PATTERN.sub(" ", text)

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def validate_script_images(
    script: str,
    minimum: int = 1,
    maximum: int = 50,
) -> List[str]:
    """
    Vérifie les marqueurs visuels et retourne leurs descriptions.
    """

    images = extract_image_markers(script)

    if len(images) < minimum:
        raise RuntimeError(
            f"Le script contient seulement {len(images)} marqueur(s) "
            f"[IMAGE:]. Il en faut au moins {minimum}."
        )

    if len(images) > maximum:
        images = images[:maximum]

    return images


# ============================================================
# PEXELS
# ============================================================

def pexels_headers() -> Dict[str, str]:
    """
    Prépare les headers de l'API Pexels.
    """

    if not PEXELS_API_KEY:
        raise RuntimeError(
            "PEXELS_API_KEY est absente. "
            "Ajoutez-la dans les variables d'environnement de Render."
        )

    return {
        "Authorization": PEXELS_API_KEY,
    }


def download_file(
    url: str,
    output_path: Path,
    timeout: int = 60,
) -> bool:
    """
    Télécharge un fichier distant.
    """

    try:
        response = requests.get(
            url,
            timeout=timeout,
            stream=True,
        )

        response.raise_for_status()

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with open(output_path, "wb") as file:
            for chunk in response.iter_content(
                chunk_size=1024 * 64
            ):
                if chunk:
                    file.write(chunk)

        return output_path.exists() and output_path.stat().st_size > 0

    except Exception:
        try:
            if output_path.exists():
                output_path.unlink()
        except Exception:
            pass

        return False


def search_pexels_photo(
    query: str,
    page: int = 1,
) -> Optional[Dict]:
    """
    Recherche une image sur Pexels.
    """

    if not PEXELS_API_KEY:
        return None

    try:
        response = requests.get(
            PEXELS_API_URL,
            headers=pexels_headers(),
            params={
                "query": query,
                "orientation": "landscape",
                "size": "large",
                "page": page,
                "per_page": 15,
            },
            timeout=30,
        )

        response.raise_for_status()

        data = response.json()

        photos = data.get("photos", [])

        if not photos:
            return None

        # Mélange léger pour éviter de toujours prendre
        # exactement la même image lorsque plusieurs résultats
        # sont disponibles.
        random.shuffle(photos)

        for photo in photos:
            src = photo.get("src", {})

            image_url = (
                src.get("large2x")
                or src.get("large")
                or src.get("original")
            )

            if image_url:
                return {
                    "url": image_url,
                    "id": photo.get("id"),
                    "alt": photo.get("alt", query),
                }

    except Exception:
        return None

    return None


# ============================================================
# PLACEHOLDER VISUEL
# ============================================================

def create_placeholder(
    output_path: Path,
    width: int = 1280,
    height: int = 720,
) -> Path:
    """
    Crée une image de secours si aucune image distante
    n'est disponible.
    """

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    image = Image.new(
        "RGB",
        (width, height),
        (25, 25, 25),
    )

    image.save(
        output_path,
        format="JPEG",
        quality=90,
    )

    return output_path


# ============================================================
# NORMALISATION D'UNE IMAGE
# ============================================================

def normalize_image(
    source_path: Path,
    output_path: Path,
    width: int,
    height: int,
) -> Path:
    """
    Adapte une image à une résolution donnée en conservant
    son ratio et en remplissant le cadre par recadrage central.
    """

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:
        image = Image.open(source_path).convert("RGB")

        source_ratio = image.width / image.height
        target_ratio = width / height

        if source_ratio > target_ratio:
            # Image trop large.
            new_height = height
            new_width = int(height * source_ratio)
        else:
            # Image trop haute.
            new_width = width
            new_height = int(width / source_ratio)

        image = image.resize(
            (new_width, new_height),
            Image.Resampling.LANCZOS,
        )

        left = max(0, (new_width - width) // 2)
        top = max(0, (new_height - height) // 2)

        image = image.crop(
            (
                left,
                top,
                left + width,
                top + height,
            )
        )

        image.save(
            output_path,
            format="JPEG",
            quality=92,
            optimize=True,
        )

        return output_path

    except Exception:
        return create_placeholder(
            output_path,
            width,
            height,
        )


# ============================================================
# RÉCUPÉRATION DES VISUELS
# ============================================================

def get_visuals(
    image_descriptions: List[str],
    output_dir: Path,
    orientation: str = "landscape",
) -> List[Path]:
    """
    Recherche et télécharge les visuels nécessaires.

    Si une recherche échoue, un placeholder est utilisé afin
    que toute la production ne tombe pas pour une seule image.
    """

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    if orientation == "portrait":
        target_width = 1080
        target_height = 1920
    else:
        target_width = 1280
        target_height = 720

    visuals = []

    for index, description in enumerate(image_descriptions):
        raw_path = output_dir / f"raw_{index:03d}.jpg"
        final_path = output_dir / f"visual_{index:03d}.jpg"

        photo = search_pexels_photo(
            description,
            page=1 + (index % 3),
        )

        downloaded = False

        if photo:
            downloaded = download_file(
                photo["url"],
                raw_path,
            )

        if downloaded:
            normalized = normalize_image(
                raw_path,
                final_path,
                target_width,
                target_height,
            )

            visuals.append(normalized)

            try:
                if raw_path.exists():
                    raw_path.unlink()
            except Exception:
                pass

        else:
            placeholder = create_placeholder(
                final_path,
                target_width,
                target_height,
            )

            visuals.append(placeholder)

        # Petite pause pour éviter d'envoyer trop rapidement
        # des requêtes successives à l'API.
        time.sleep(0.15)

    if not visuals:
        fallback = create_placeholder(
            output_dir / "visual_fallback.jpg",
            target_width,
            target_height,
        )

        visuals.append(fallback)

    return visuals


# ============================================================
# NOMBRE DE VISUELS SELON LA DURÉE
# ============================================================

def visual_count_for_duration(
    duration_seconds: float,
    vertical: bool = False,
) -> int:
    """
    Détermine un nombre raisonnable de visuels selon la durée.

    Shorts :
        environ 1 visuel toutes les 3 secondes.

    Vidéos longues :
        environ 1 visuel toutes les 6 secondes.
    """

    duration_seconds = max(
        1.0,
        float(duration_seconds),
    )

    if vertical:
        minimum = 7
        maximum = 14
        interval = 3.0
    else:
        minimum = 12
        maximum = 36
        interval = 6.0

    count = round(duration_seconds / interval)

    return max(
        minimum,
        min(maximum, count),
    )


# ============================================================
# EDGE-TTS : RÉCUPÉRATION SYNCHRONE DES VOIX
# ============================================================

def _edge_tts_list_voices_in_new_loop() -> List[Dict]:
    """
    Exécute edge_tts.list_voices() dans une nouvelle boucle asyncio.

    Cette fonction est utilisée lorsqu'une boucle asyncio existe
    déjà dans le thread courant.
    """

    result = []
    error = []

    def runner():
        try:
            voices = asyncio.run(
                edge_tts.list_voices()
            )

            if voices:
                result.extend(voices)

        except Exception as exc:
            error.append(exc)

    thread = threading.Thread(
        target=runner,
        daemon=True,
    )

    thread.start()
    thread.join()

    if error:
        raise error[0]

    return result


def fetch_edge_tts_voices_sync() -> List[Dict]:
    """
    Transforme l'appel asynchrone edge_tts.list_voices()
    en appel utilisable depuis le code synchrone de Streamlit.
    """

    try:
        # Vérifie si une boucle est déjà active.
        asyncio.get_running_loop()

    except RuntimeError:
        # Aucune boucle active :
        # asyncio.run() est sûr ici.
        return asyncio.run(
            edge_tts.list_voices()
        )

    # Une boucle existe déjà.
    # On utilise donc un thread indépendant.
    return _edge_tts_list_voices_in_new_loop()


def get_available_french_voices() -> List[str]:
    """
    Retourne les voix françaises Edge-TTS disponibles.

    Si l'API de récupération des voix échoue, les voix préférées
    sont utilisées comme fallback afin de ne pas bloquer toute
    la génération vidéo.
    """

    try:
        voices = fetch_edge_tts_voices_sync()

    except Exception:
        return PREFERRED_VOICES.copy()

    available = []

    for voice in voices:
        if not isinstance(voice, dict):
            continue

        short_name = voice.get(
            "ShortName",
            "",
        )

        if (
            isinstance(short_name, str)
            and short_name.startswith("fr-FR-")
        ):
            available.append(short_name)

    ordered = []

    for preferred in PREFERRED_VOICES:
        if preferred in available:
            ordered.append(preferred)

    for voice in available:
        if voice not in ordered:
            ordered.append(voice)

    return ordered or PREFERRED_VOICES.copy()


# ============================================================
# SYNTHÈSE TTS
# ============================================================

def synthesize_with_voice(
    text: str,
    voice: str,
    output_path: Path,
) -> List[Dict]:
    """
    Synthétise la narration avec Edge-TTS.

    Les événements WordBoundary sont récupérés pour générer
    les sous-titres mot par mot.
    """

    text = remove_image_markers(text)

    if not text.strip():
        raise RuntimeError(
            "Impossible de générer l'audio : "
            "la narration est vide."
        )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

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

    with open(
        output_path,
        "wb",
    ) as audio_file:

        for chunk in communicate.stream_sync():

            chunk_type = chunk.get("type")

            if chunk_type == "audio":

                data = chunk.get(
                    "data",
                    b"",
                )

                if data:
                    audio_received = True
                    audio_file.write(data)

            elif chunk_type == "WordBoundary":

                offset = chunk.get("offset")
                duration = chunk.get("duration")
                word = chunk.get(
                    "text",
                    "",
                )

                if (
                    offset is not None
                    and word
                ):
                    timings.append(
                        {
                            "word": str(word),
                            "start": (
                                float(offset)
                                / 10_000_000
                            ),
                            "duration": (
                                float(duration)
                                / 10_000_000
                                if duration is not None
                                else 0.1
                            ),
                        }
                    )

    if not audio_received:
        raise RuntimeError(
            "Edge-TTS n'a produit aucun fichier audio."
        )

    if not output_path.exists():
        raise RuntimeError(
            "Le fichier audio n'a pas été créé."
        )

    if output_path.stat().st_size == 0:
        raise RuntimeError(
            "Le fichier audio généré est vide."
        )

    return timings


# ============================================================
# DURÉE AUDIO
# ============================================================

def get_audio_duration(
    audio_path: Path,
) -> float:
    """
    Récupère la durée exacte d'un fichier audio avec ffprobe.
    """

    ensure_ffmpeg()

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
            "Impossible de déterminer la durée audio : "
            + result.stderr[-1000:]
        )

    try:
        duration = float(
            result.stdout.strip()
        )
    except ValueError as exc:
        raise RuntimeError(
            "FFprobe a retourné une durée audio invalide."
        ) from exc

    if duration <= 0:
        raise RuntimeError(
            "La durée audio calculée est nulle."
        )

    return duration


# ============================================================
# GÉNÉRATION AUDIO AVEC SÉLECTION DE VOIX
# ============================================================

def generate_audio(
    text: str,
    output_path: Path,
) -> Tuple[List[Dict], float, str]:
    """
    Génère la narration audio.

    Essaie plusieurs voix françaises si nécessaire.
    """

    voices = get_available_french_voices()

    if not voices:
        voices = PREFERRED_VOICES.copy()

    last_error = None

    for voice in voices:

        try:
            timings = synthesize_with_voice(
                text=text,
                voice=voice,
                output_path=output_path,
            )

            duration = get_audio_duration(
                output_path
            )

            return (
                timings,
                duration,
                voice,
            )

        except Exception as exc:
            last_error = exc

            try:
                if output_path.exists():
                    output_path.unlink()
            except Exception:
                pass

    raise RuntimeError(
        "Impossible de générer la narration avec les voix "
        f"françaises disponibles. Dernière erreur : {last_error}"
                )# ============================================================
# SOUS-TITRES ASS
# ============================================================

def ass_time(seconds: float) -> str:
    """
    Convertit des secondes en format temporel ASS :
    H:MM:SS.cc
    """

    seconds = max(0.0, float(seconds))

    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    remaining = seconds % 60

    centiseconds = int(round((remaining - int(remaining)) * 100))

    whole_seconds = int(remaining)

    # Gestion du passage éventuel à 60.00 secondes.
    if centiseconds >= 100:
        whole_seconds += 1
        centiseconds = 0

    if whole_seconds >= 60:
        whole_seconds -= 60
        minutes += 1

    if minutes >= 60:
        minutes -= 60
        hours += 1

    return (
        f"{hours}:{minutes:02d}:"
        f"{whole_seconds:02d}.{centiseconds:02d}"
    )


def escape_ass_text(text: str) -> str:
    """
    Échappe les caractères problématiques pour ASS.
    """

    if not text:
        return ""

    text = str(text)

    text = text.replace("\\", r"\\")
    text = text.replace("{", r"\{")
    text = text.replace("}", r"\}")

    # ASS utilise \N pour les retours à la ligne.
    text = text.replace("\n", r"\N")

    return text


def build_ass_subtitles(
    timings: List[Dict],
    output_path: Path,
    vertical: bool = False,
) -> Path:
    """
    Crée un fichier ASS avec un mot affiché à la fois.

    Les timings viennent directement des événements WordBoundary
    d'Edge-TTS.
    """

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if vertical:
        play_res_x = 1080
        play_res_y = 1920

        # Position basse, mais suffisamment haute pour éviter
        # la zone des contrôles/éléments visuels.
        alignment = 2
        margin_v = 260
        font_size = 64
    else:
        play_res_x = 1280
        play_res_y = 720

        alignment = 2
        margin_v = 55
        font_size = 48

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_res_x}
PlayResY: {play_res_y}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{font_size},&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,1,0,0,0,100,100,0,0,1,3,1,{alignment},50,50,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = [header]

    for index, timing in enumerate(timings):

        word = str(
            timing.get("word", "")
        ).strip()

        if not word:
            continue

        start = float(
            timing.get("start", 0)
        )

        duration = float(
            timing.get("duration", 0.1)
        )

        end = start + max(
            duration,
            0.08,
        )

        # Évite un sous-titre négatif ou incohérent.
        if end <= start:
            end = start + 0.1

        # Petite limite de sécurité.
        if end - start > 3.0:
            end = start + 3.0

        escaped_word = escape_ass_text(
            word
        )

        lines.append(
            "Dialogue: 0,"
            f"{ass_time(start)},"
            f"{ass_time(end)},"
            f"Default,,0,0,0,,"
            f"{escaped_word}\n"
        )

    with open(
        output_path,
        "w",
        encoding="utf-8",
    ) as subtitle_file:
        subtitle_file.write(
            "".join(lines)
        )

    return output_path


# ============================================================
# DURÉES DES SCÈNES
# ============================================================

def calculate_scene_durations(
    total_duration: float,
    scene_count: int,
) -> List[float]:
    """
    Répartit la durée audio entre les scènes.

    La somme finale est exactement égale à la durée audio.
    """

    total_duration = max(
        0.1,
        float(total_duration),
    )

    scene_count = max(
        1,
        int(scene_count),
    )

    if scene_count == 1:
        return [total_duration]

    # Durées pondérées légèrement différentes afin d'éviter
    # un montage trop mécanique.
    weights = []

    for index in range(scene_count):
        if index % 3 == 0:
            weights.append(1.05)
        elif index % 3 == 1:
            weights.append(0.95)
        else:
            weights.append(1.00)

    weight_sum = sum(weights)

    durations = [
        total_duration * weight / weight_sum
        for weight in weights
    ]

    # Correction numérique :
    # la dernière scène absorbe toute différence d'arrondi.
    difference = (
        total_duration
        - sum(durations)
    )

    durations[-1] += difference

    # Évite une dernière scène trop petite.
    if durations[-1] < 0.25 and len(durations) > 1:
        transfer = 0.25 - durations[-1]

        previous = durations[-2]

        if previous > transfer:
            durations[-2] -= transfer
            durations[-1] += transfer

    return durations


# ============================================================
# CRÉATION D'UNE SCÈNE IMAGE
# ============================================================

def create_image_scene(
    image_path: Path,
    output_path: Path,
    duration: float,
    width: int,
    height: int,
) -> Path:
    """
    Transforme une image en clip vidéo avec un léger mouvement
    de caméra afin d'éviter un rendu complètement statique.
    """

    ensure_ffmpeg()

    duration = max(
        0.1,
        float(duration),
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # Mouvement très léger :
    # zoom progressif + déplacement lent.
    #
    # Le but est de rendre les images vivantes sans provoquer
    # un mouvement agressif qui détournerait l'attention.
    zoom_expression = (
        "zoompan="
        "z='min(zoom+0.0007,1.08)':"
        "x='iw/2-(iw/zoom/2)':"
        "y='ih/2-(ih/zoom/2)':"
        f"d=1:s={width}x{height}:fps=30"
    )

    command = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-i",
        str(image_path),
        "-vf",
        zoom_expression,
        "-t",
        f"{duration:.3f}",
        "-r",
        "30",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        str(output_path),
    ]

    result = run_command(
        command,
        timeout=180,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Erreur lors de la création d'une scène visuelle : "
            + result.stderr[-2000:]
        )

    if not output_path.exists():
        raise RuntimeError(
            "FFmpeg n'a pas créé la scène visuelle."
        )

    return output_path


# ============================================================
# CONCATÉNATION DES SCÈNES
# ============================================================

def concatenate_scenes(
    scene_paths: List[Path],
    output_path: Path,
) -> Path:
    """
    Assemble toutes les scènes vidéo.
    """

    ensure_ffmpeg()

    if not scene_paths:
        raise RuntimeError(
            "Aucune scène à concaténer."
        )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    concat_file = output_path.parent / "concat.txt"

    with open(
        concat_file,
        "w",
        encoding="utf-8",
    ) as file:

        for scene in scene_paths:
            # Chemins absolus correctement échappés
            # pour le concat demuxer FFmpeg.
            path_string = str(
                scene.resolve()
            ).replace(
                "'",
                r"'\''",
            )

            file.write(
                f"file '{path_string}'\n"
            )

    command = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_file),
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "22",
        "-pix_fmt",
        "yuv420p",
        str(output_path),
    ]

    result = run_command(
        command,
        timeout=300,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Erreur pendant la concaténation des scènes : "
            + result.stderr[-2500:]
        )

    if not output_path.exists():
        raise RuntimeError(
            "La vidéo des scènes n'a pas été créée."
        )

    return output_path


# ============================================================
# AJOUT AUDIO + SOUS-TITRES
# ============================================================

def add_audio_and_subtitles(
    video_path: Path,
    audio_path: Path,
    subtitle_path: Path,
    output_path: Path,
    duration: float,
) -> Path:
    """
    Ajoute la narration et les sous-titres à la vidéo.
    """

    ensure_ffmpeg()

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # FFmpeg nécessite un chemin compatible avec le filtre subtitles.
    subtitle_filter_path = str(
        subtitle_path.resolve()
    )

    # Sous Linux, les apostrophes dans le chemin peuvent être
    # problématiques dans l'expression du filtre.
    subtitle_filter_path = (
        subtitle_filter_path
        .replace("\\", "/")
        .replace("'", r"\'")
        .replace(":", r"\:")
    )

    video_filter = (
        f"subtitles='{subtitle_filter_path}'"
    )

    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(audio_path),
        "-vf",
        video_filter,
        "-t",
        f"{duration:.3f}",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "22",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-shortest",
        str(output_path),
    ]

    result = run_command(
        command,
        timeout=300,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Erreur lors de l'ajout de l'audio ou des sous-titres : "
            + result.stderr[-3000:]
        )

    if not output_path.exists():
        raise RuntimeError(
            "La vidéo finale n'a pas été créée."
        )

    return output_path


# ============================================================
# VÉRIFICATION VIDÉO
# ============================================================

def get_video_duration(
    video_path: Path,
) -> float:
    """
    Récupère la durée d'une vidéo.
    """

    ensure_ffmpeg()

    result = run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
        timeout=60,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Impossible de lire la durée de la vidéo : "
            + result.stderr[-1000:]
        )

    try:
        duration = float(
            result.stdout.strip()
        )
    except ValueError as exc:
        raise RuntimeError(
            "Durée vidéo invalide retournée par FFprobe."
        ) from exc

    return max(
        0.0,
        duration,
    )


def validate_video_file(
    video_path: Path,
    expected_audio_duration: Optional[float] = None,
) -> None:
    """
    Effectue des contrôles de base sur la vidéo finale.
    """

    if not video_path.exists():
        raise RuntimeError(
            "Le fichier vidéo final n'existe pas."
        )

    if video_path.stat().st_size < 10_000:
        raise RuntimeError(
            "Le fichier vidéo final semble être vide ou corrompu."
        )

    duration = get_video_duration(
        video_path
    )

    if duration <= 0:
        raise RuntimeError(
            "La vidéo finale possède une durée nulle."
        )

    if expected_audio_duration is not None:
        difference = abs(
            duration
            - float(expected_audio_duration)
        )

        # Une petite différence est normale à cause de l'encodage.
        if difference > 2.0:
            raise RuntimeError(
                "La durée de la vidéo finale ne correspond pas "
                "suffisamment à celle de la narration "
                f"(vidéo={duration:.2f}s, "
                f"audio={expected_audio_duration:.2f}s)."
            )


# ============================================================
# CONSTRUCTION D'UNE VIDÉO À PARTIR DES VISUELS
# ============================================================

def build_video(
    visuals: List[Path],
    audio_path: Path,
    timings: List[Dict],
    output_path: Path,
    vertical: bool = False,
) -> Path:
    """
    Construit une vidéo complète :

    1. scènes visuelles
    2. concaténation
    3. narration
    4. sous-titres mot par mot
    5. contrôle final
    """

    ensure_ffmpeg()

    if not visuals:
        raise RuntimeError(
            "Aucun visuel disponible pour le montage."
        )

    if not audio_path.exists():
        raise RuntimeError(
            "Le fichier audio est introuvable."
        )

    duration = get_audio_duration(
        audio_path
    )

    if vertical:
        width = 1080
        height = 1920
    else:
        width = 1280
        height = 720

    work_dir = output_path.parent / "build"

    if work_dir.exists():
        shutil.rmtree(
            work_dir,
            ignore_errors=True,
        )

    work_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # Durée et nombre de scènes
    # --------------------------------------------------------

    scene_count = min(
        len(visuals),
        max(
            1,
            visual_count_for_duration(
                duration,
                vertical=vertical,
            ),
        ),
    )

    # Si nous avons plus de visuels que nécessaire,
    # sélection équilibrée des visuels.
    if len(visuals) > scene_count:

        selected_visuals = []

        if scene_count == 1:
            selected_visuals = [visuals[0]]

        else:
            for index in range(scene_count):
                position = round(
                    index
                    * (len(visuals) - 1)
                    / (scene_count - 1)
                )

                selected_visuals.append(
                    visuals[position]
                )

        visuals = selected_visuals

    scene_durations = calculate_scene_durations(
        total_duration=duration,
        scene_count=len(visuals),
    )

    # --------------------------------------------------------
    # Création des scènes
    # --------------------------------------------------------

    scene_paths = []

    for index, (
        image_path,
        scene_duration,
    ) in enumerate(
        zip(
            visuals,
            scene_durations,
        )
    ):

        scene_path = (
            work_dir
            / f"scene_{index:03d}.mp4"
        )

        create_image_scene(
            image_path=image_path,
            output_path=scene_path,
            duration=scene_duration,
            width=width,
            height=height,
        )

        scene_paths.append(
            scene_path
        )

    # --------------------------------------------------------
    # Concaténation
    # --------------------------------------------------------

    visual_video = (
        work_dir
        / "visual_video.mp4"
    )

    concatenate_scenes(
        scene_paths=scene_paths,
        output_path=visual_video,
    )

    # --------------------------------------------------------
    # Sous-titres
    # --------------------------------------------------------

    subtitle_path = (
        work_dir
        / "subtitles.ass"
    )

    build_ass_subtitles(
        timings=timings,
        output_path=subtitle_path,
        vertical=vertical,
    )

    # --------------------------------------------------------
    # Finalisation
    # --------------------------------------------------------

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    add_audio_and_subtitles(
        video_path=visual_video,
        audio_path=audio_path,
        subtitle_path=subtitle_path,
        output_path=output_path,
        duration=duration,
    )

    # --------------------------------------------------------
    # Contrôle final
    # --------------------------------------------------------

    validate_video_file(
        video_path=output_path,
        expected_audio_duration=duration,
    )

    return output_path# ============================================================
# PRODUCTION D'UN SHORT
# ============================================================

def create_short_video(
    script: str,
    output_path: Path,
    job_dir: Path,
    part_name: str = "short",
) -> Tuple[Path, float, str, int, int]:
    """
    Produit un Short vertical complet.

    Retourne :
        vidéo finale
        durée
        voix utilisée
        nombre de mots
        nombre de visuels
    """

    script = clean_text(script)

    word_count = count_words(script)

    if not (
        SHORT_MIN_WORDS
        <= word_count
        <= SHORT_MAX_WORDS
    ):
        raise RuntimeError(
            f"{part_name} contient {word_count} mots. "
            f"La cible est {SHORT_MIN_WORDS} à "
            f"{SHORT_MAX_WORDS} mots."
        )

    image_descriptions = validate_script_images(
        script,
        minimum=7,
        maximum=12,
    )

    job_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    audio_path = (
        job_dir
        / f"{part_name}_audio.mp3"
    )

    visuals_dir = (
        job_dir
        / f"{part_name}_visuals"
    )

    final_path = Path(output_path)

    final_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # Audio
    # --------------------------------------------------------

    timings, audio_duration, voice = generate_audio(
        text=script,
        output_path=audio_path,
    )

    # --------------------------------------------------------
    # Contrôle durée
    # --------------------------------------------------------

    if audio_duration < SHORT_MIN_SECONDS:
        st.warning(
            f"{part_name} est légèrement court : "
            f"{format_seconds(audio_duration)}."
        )

    if audio_duration > SHORT_MAX_SECONDS:
        st.warning(
            f"{part_name} dépasse la durée idéale : "
            f"{format_seconds(audio_duration)}."
        )

    # --------------------------------------------------------
    # Visuels
    # --------------------------------------------------------

    visual_target = visual_count_for_duration(
        audio_duration,
        vertical=True,
    )

    # Les marqueurs peuvent être plus nombreux que nécessaire.
    # On sélectionne un nombre adapté à la durée.
    selected_descriptions = image_descriptions[
        :max(
            visual_target,
            1,
        )
    ]

    visuals = get_visuals(
        image_descriptions=selected_descriptions,
        output_dir=visuals_dir,
        orientation="portrait",
    )

    if not visuals:
        raise RuntimeError(
            f"Aucun visuel disponible pour {part_name}."
        )

    # --------------------------------------------------------
    # Montage
    # --------------------------------------------------------

    final_path = build_video(
        visuals=visuals,
        audio_path=audio_path,
        timings=timings,
        output_path=final_path,
        vertical=True,
    )

    # --------------------------------------------------------
    # Vérification
    # --------------------------------------------------------

    validate_video_file(
        video_path=final_path,
        expected_audio_duration=audio_duration,
    )

    return (
        final_path,
        audio_duration,
        voice,
        word_count,
        len(visuals),
    )


# ============================================================
# PRODUCTION D'UNE VIDÉO LONGUE
# ============================================================

def create_long_video(
    script: str,
    output_path: Path,
    job_dir: Path,
) -> Tuple[Path, float, str, int, int]:
    """
    Produit une vidéo longue en 16:9.
    """

    script = clean_text(script)

    word_count = count_words(script)

    if word_count < LONG_VIDEO_MIN_WORDS:
        raise RuntimeError(
            f"Le script de la vidéo longue contient seulement "
            f"{word_count} mots."
        )

    image_descriptions = validate_script_images(
        script,
        minimum=8,
        maximum=40,
    )

    job_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    audio_path = (
        job_dir
        / "long_audio.mp3"
    )

    visuals_dir = (
        job_dir
        / "long_visuals"
    )

    final_path = Path(output_path)

    final_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # Audio
    # --------------------------------------------------------

    timings, audio_duration, voice = generate_audio(
        text=script,
        output_path=audio_path,
    )

    if audio_duration > LONG_MAX_SECONDS:
        st.warning(
            "La vidéo longue est particulièrement longue : "
            f"{format_seconds(audio_duration)}."
        )

    # --------------------------------------------------------
    # Visuels
    # --------------------------------------------------------

    visual_target = visual_count_for_duration(
        audio_duration,
        vertical=False,
    )

    selected_descriptions = image_descriptions[
        :max(
            visual_target,
            1,
        )
    ]

    visuals = get_visuals(
        image_descriptions=selected_descriptions,
        output_dir=visuals_dir,
        orientation="landscape",
    )

    if not visuals:
        raise RuntimeError(
            "Aucun visuel disponible pour la vidéo longue."
        )

    # --------------------------------------------------------
    # Montage
    # --------------------------------------------------------

    final_path = build_video(
        visuals=visuals,
        audio_path=audio_path,
        timings=timings,
        output_path=final_path,
        vertical=False,
    )

    # --------------------------------------------------------
    # Vérification
    # --------------------------------------------------------

    validate_video_file(
        video_path=final_path,
        expected_audio_duration=audio_duration,
    )

    return (
        final_path,
        audio_duration,
        voice,
        word_count,
        len(visuals),
    )


# ============================================================
# NETTOYAGE
# ============================================================

def cleanup_temp_files(
    job_dir: Optional[Path],
) -> None:
    """
    Supprime les fichiers temporaires d'un job.
    """

    if not job_dir:
        return

    try:
        if job_dir.exists():
            shutil.rmtree(
                job_dir,
                ignore_errors=True,
            )
    except Exception:
        pass


# ============================================================
# AFFICHAGE D'UNE VIDÉO
# ============================================================

def display_video_result(
    title: str,
    video_path: Path,
    duration: float,
    word_count: int,
    visual_count: int,
    voice: str,
) -> None:
    """
    Affiche une vidéo générée avec ses informations.
    """

    st.subheader(title)

    if not video_path.exists():
        st.error(
            "Le fichier vidéo n'existe plus."
        )
        return

    st.video(
        str(video_path)
    )

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            "Durée",
            format_seconds(duration),
        )

    with col2:
        st.metric(
            "Mots",
            word_count,
        )

    with col3:
        st.metric(
            "Visuels",
            visual_count,
        )

    with col4:
        st.metric(
            "Voix",
            voice.replace(
                "fr-FR-",
                "",
            ).replace(
                "Neural",
                "",
            ),
        )

    with open(
        video_path,
        "rb",
    ) as video_file:

        st.download_button(
            label="Télécharger la vidéo",
            data=video_file.read(),
            file_name=video_path.name,
            mime="video/mp4",
            key=f"download_{video_path.stem}",
        )


# ============================================================
# INTERFACE STREAMLIT
# ============================================================

st.set_page_config(
    page_title=APP_TITLE,
    page_icon="🎬",
    layout="wide",
)


st.title("🎬 Studio Vidéo IA")

st.caption(
    "Génération automatique de contenus captivants "
    "sur la psychologie, le cerveau et le comportement humain."
)


st.info(
    """
Le studio adapte automatiquement le format au contenu généré :

• moins de 200 mots → régénération automatique
• 200 à 349 mots → 1 Short
• 350 à 699 mots → 2 Shorts
• 700 mots ou plus → vidéo longue + teaser

Les Shorts sont générés en 9:16 avec narration,
visuels et sous-titres mot par mot.
"""
)


# ============================================================
# SAISIE DU SUJET
# ============================================================

st.header("Sujet de la vidéo")

topic = st.text_input(
    "Quel sujet voulez-vous traiter ?",
    placeholder=(
        "Exemple : Pourquoi ton cerveau procrastine"
    ),
)


generate_button = st.button(
    "🚀 Générer la vidéo",
    type="primary",
    use_container_width=True,
)


# ============================================================
# FONCTION DE PROGRESSION
# ============================================================

def show_progress(
    progress_bar,
    status_placeholder,
    value: float,
    message: str,
) -> None:
    """
    Met à jour proprement la progression.
    """

    value = max(
        0.0,
        min(1.0, value),
    )

    progress_bar.progress(
        value
    )

    status_placeholder.info(
        message
    )


# ============================================================
# DÉMARRAGE DU WORKFLOW
# ============================================================

if generate_button:

    if not topic.strip():
        st.error(
            "Veuillez entrer un sujet avant de lancer la génération."
        )

        st.stop()

    try:
        ensure_ffmpeg()

    except Exception as exc:
        st.error(
            f"Configuration FFmpeg incorrecte : {exc}"
        )

        st.stop()

    # --------------------------------------------------------
    # Création du job
    # --------------------------------------------------------

    timestamp = int(
        time.time()
    )

    safe_topic = re.sub(
        r"[^a-zA-Z0-9_-]+",
        "_",
        topic.strip(),
    )[:50]

    job_dir = (
        TEMP_ROOT
        / f"job_{timestamp}_{safe_topic}"
    )

    job_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_dir = (
        OUTPUT_ROOT
        / f"job_{timestamp}_{safe_topic}"
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    progress_bar = st.progress(0)

    status_placeholder = st.empty()

    try:

        # ====================================================
        # 1. GÉNÉRATION DU SCRIPT
        # ====================================================

        show_progress(
            progress_bar,
            status_placeholder,
            0.05,
            "🧠 Génération du script scientifique...",
        )

        main_script = generate_main_script(
            topic.strip()
        )

        main_script = clean_text(
            main_script
        )

        main_word_count = count_words(
            main_script
        )

        st.header(
            "1. Génération du script"
        )

        st.success(
            f"Script généré : {main_word_count} mots"
        )

        with st.expander(
            "Voir le script principal",
            expanded=False,
        ):
            st.write(
                remove_image_markers(
                    main_script
                )
            )

        script_col1, script_col2 = st.columns(2)

        with script_col1:
            st.metric(
                "Nombre de mots",
                main_word_count,
            )

        with script_col2:
            st.metric(
                "Marqueurs image",
                len(
                    extract_image_markers(
                        main_script
                    )
                ),
            )

        # ====================================================
        # 2. ROUTAGE
        # ====================================================

        mode = choose_content_mode(
            main_word_count
        )

        # ----------------------------------------------------
        # Script trop court
        # ----------------------------------------------------

        if mode == "regenerate":

            show_progress(
                progress_bar,
                status_placeholder,
                0.12,
                "✍️ Script trop court : enrichissement automatique...",
            )

            main_script = regenerate_short_main_script(
                topic.strip(),
                main_script,
            )

            main_script = clean_text(
                main_script
            )

            main_word_count = count_words(
                main_script
            )

            mode = choose_content_mode(
                main_word_count
            )

            st.info(
                "Le script a été enrichi automatiquement."
            )

            st.metric(
                "Nouveau nombre de mots",
                main_word_count,
            )

            if mode == "regenerate":
                raise RuntimeError(
                    "Le script reste trop court après "
                    "la régénération automatique "
                    f"({main_word_count} mots)."
                )

        # ====================================================
        # 3. PRODUCTION
        # ====================================================

        st.header(
            "2. Production vidéo"
        )

        # ====================================================
        # MODE : 1 SHORT
        # ====================================================

        if mode == "one_short":

            st.info(
                "Format sélectionné : "
                "1 Short vertical."
            )

            show_progress(
                progress_bar,
                status_placeholder,
                0.20,
                "🎯 Adaptation du script au format Short...",
            )

            short_script = generate_one_short(
                topic=topic.strip(),
                source_script=main_script,
            )

            short_script = fit_short_script(
                topic=topic.strip(),
                script=short_script,
                part_label="Short",
            )

            st.write(
                f"Short : {count_words(short_script)} mots"
            )

            short_path = (
                output_dir
                / "short.mp4"
            )

            show_progress(
                progress_bar,
                status_placeholder,
                0.35,
                "🎙️ Génération de la narration...",
            )

            (
                final_path,
                duration,
                voice,
                words,
                visuals,
            ) = create_short_video(
                script=short_script,
                output_path=short_path,
                job_dir=job_dir,
                part_name="short",
            )

            show_progress(
                progress_bar,
                status_placeholder,
                0.95,
                "🎬 Finalisation du Short...",
            )

            display_video_result(
                title="Short",
                video_path=final_path,
                duration=duration,
                word_count=words,
                visual_count=visuals,
                voice=voice,
            )

        # ====================================================
        # MODE : 2 SHORTS
        # ====================================================

        elif mode == "two_shorts":

            st.info(
                "Format sélectionné : "
                "2 Shorts verticaux, Partie 1 + Partie 2."
            )

            show_progress(
                progress_bar,
                status_placeholder,
                0.20,
                "✂️ Restructuration en deux Shorts cohérents...",
            )

            part1, part2 = generate_two_shorts(
                topic=topic.strip(),
                source_script=main_script,
            )

            # ------------------------------------------------
            # Ajustement individuel des deux parties.
            # ------------------------------------------------

            part1 = fit_short_script(
                topic=topic.strip(),
                script=part1,
                part_label="Partie 1",
            )

            part2 = fit_short_script(
                topic=topic.strip(),
                script=part2,
                part_label="Partie 2",
            )

            st.write(
                f"Partie 1 : {count_words(part1)} mots"
            )

            st.write(
                f"Partie 2 : {count_words(part2)} mots"
            )

            # =================================================
            # PARTIE 1
            # =================================================

            st.subheader(
                "Short - Partie 1"
            )

            part1_path = (
                output_dir
                / "short_part1.mp4"
            )

            show_progress(
                progress_bar,
                status_placeholder,
                0.35,
                "🎙️ Production de la Partie 1...",
            )

            (
                final_part1,
                duration1,
                voice1,
                words1,
                visuals1,
            ) = create_short_video(
                script=part1,
                output_path=part1_path,
                job_dir=job_dir,
                part_name="short_part1",
            )

            display_video_result(
                title="Partie 1",
                video_path=final_part1,
                duration=duration1,
                word_count=words1,
                visual_count=visuals1,
                voice=voice1,
            )

            # =================================================
            # PARTIE 2
            # =================================================

            st.subheader(
                "Short - Partie 2"
            )

            part2_path = (
                output_dir
                / "short_part2.mp4"
            )

            show_progress(
                progress_bar,
                status_placeholder,
                0.65,
                "🎙️ Production de la Partie 2...",
            )

            (
                final_part2,
                duration2,
                voice2,
                words2,
                visuals2,
            ) = create_short_video(
                script=part2,
                output_path=part2_path,
                job_dir=job_dir,
                part_name="short_part2",
            )

            show_progress(
                progress_bar,
                status_placeholder,
                0.95,
                "🎬 Finalisation des deux Shorts...",
            )

            display_video_result(
                title="Partie 2",
                video_path=final_part2,
                duration=duration2,
                word_count=words2,
                visual_count=visuals2,
                voice=voice2,
            )

        # ====================================================
        # MODE : VIDÉO LONGUE
        # ====================================================

        elif mode == "long":

            st.info(
                "Format sélectionné : "
                "vidéo longue 16:9 + teaser Short."
            )

            # =================================================
            # VIDÉO LONGUE
            # =================================================

            long_path = (
                output_dir
                / "video_longue.mp4"
            )

            show_progress(
                progress_bar,
                status_placeholder,
                0.25,
                "🎙️ Production de la vidéo longue...",
            )

            (
                final_long,
                long_duration,
                long_voice,
                long_words,
                long_visuals,
            ) = create_long_video(
                script=main_script,
                output_path=long_path,
                job_dir=job_dir,
            )

            display_video_result(
                title="Vidéo longue",
                video_path=final_long,
                duration=long_duration,
                word_count=long_words,
                visual_count=long_visuals,
                voice=long_voice,
            )

            # =================================================
            # TEASER
            # =================================================

            show_progress(
                progress_bar,
                status_placeholder,
                0.70,
                "🎯 Création du teaser Short...",
            )

            teaser_script = generate_teaser(
                topic=topic.strip(),
                source_script=main_script,
            )

            teaser_path = (
                output_dir
                / "teaser.mp4"
            )

            (
                final_teaser,
                teaser_duration,
                teaser_voice,
                teaser_words,
                teaser_visuals,
            ) = create_short_video(
                script=teaser_script,
                output_path=teaser_path,
                job_dir=job_dir,
                part_name="teaser",
            )

            show_progress(
                progress_bar,
                status_placeholder,
                0.95,
                "🎬 Finalisation de la vidéo longue et du teaser...",
            )

            display_video_result(
                title="Teaser Short",
                video_path=final_teaser,
                duration=teaser_duration,
                word_count=teaser_words,
                visual_count=teaser_visuals,
                voice=teaser_voice,
            )

        else:
            raise RuntimeError(
                f"Mode de production inconnu : {mode}"
            )

        # ====================================================
        # FIN
        # ====================================================

        show_progress(
            progress_bar,
            status_placeholder,
            1.0,
            "✅ Génération terminée avec succès.",
        )

        st.success(
            "La production est terminée."
        )

    except Exception as exc:

        st.error(
            f"❌ Une erreur est survenue : {exc}"
        )

        with st.expander(
            "Détails techniques",
            expanded=False,
        ):
            st.exception(exc)

    finally:

        # On ne supprime PAS output_dir :
        # les vidéos finales doivent rester disponibles
        # pendant la session Streamlit.

        cleanup_temp_files(
            job_dir
        )


# ============================================================
# INFORMATIONS
# ============================================================

with st.expander(
    "ℹ️ Informations sur le studio",
    expanded=False,
):

    st.markdown(
        """
### Formats automatiques

Le studio adapte le contenu à sa longueur.

**Moins de 200 mots**

Le script est automatiquement enrichi avant la production.

**200 à 349 mots**

Le contenu est transformé en un Short vertical.

**350 à 699 mots**

Le contenu est restructuré en deux Shorts :
Partie 1 et Partie 2.

**700 mots ou plus**

Le contenu devient une vidéo longue 16:9,
accompagnée d'un teaser vertical.

### Principes de génération

Les scripts sont orientés vers :

- psychologie cognitive
- neurosciences
- cerveau
- mémoire
- attention
- habitudes
- comportement humain
- prise de décision
- apprentissage
- émotions
- sommeil
- stress
- motivation

Le système évite volontairement les affirmations
pseudo-scientifiques et les statistiques non vérifiées.

Les sous-titres sont générés à partir des événements
mot par mot fournis par la synthèse vocale.
"""
)
