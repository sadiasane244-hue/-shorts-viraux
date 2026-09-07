import os
import re
import json
import time
import math
import shutil
import asyncio
import subprocess
import threading
import textwrap
from pathlib import Path
from typing import List, Dict, Tuple, Optional

import requests
import streamlit as st
from PIL import Image, ImageDraw, ImageFont
import edge_tts


# ============================================================
# CERVEAU CURIEUX - STUDIO VIDEO IA V3
# ============================================================

APP_TITLE = "Cerveau Curieux | Studio Vidéo IA"
CHANNEL_NAME = "Cerveau Curieux"

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "meta-llama/llama-3.3-70b-instruct"

OPENROUTER_FALLBACK_MODELS = [
    "meta-llama/llama-3.3-70b-instruct",
    "google/gemini-2.0-flash-001",
]

PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"


# ============================================================
# PARAMÈTRES
# ============================================================

VOICE_RATE = "+2%"
VOICE_VOLUME = "+0%"

SHORT_TARGET_SECONDS = 45
SHORT_MIN_SECONDS = 25
SHORT_MAX_SECONDS = 60

SHORT_MIN_WORDS = 70
SHORT_MAX_WORDS = 150

LONG_MIN_WORDS = 700
REGENERATE_BELOW = 70


# Identité Cerveau Curieux
MASCOT_WIDTH = 165

MASCOT_BLUE = (74, 61, 184)
MASCOT_PURPLE = (122, 92, 255)
MASCOT_PINK = (242, 142, 190)
MASCOT_DARK = (66, 37, 105)


# ============================================================
# RÉPERTOIRES
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

OUTPUT_DIR = BASE_DIR / "outputs"
TEMP_DIR = BASE_DIR / "temp"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# SECRETS
# ============================================================

OPENROUTER_API_KEY = ""
PEXELS_API_KEY = ""


def get_secret(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name)

        if value:
            return str(value)

    except Exception:
        pass

    return os.getenv(name, default)


def refresh_secrets() -> None:
    global OPENROUTER_API_KEY
    global PEXELS_API_KEY

    OPENROUTER_API_KEY = get_secret(
        "OPENROUTER_API_KEY"
    )

    PEXELS_API_KEY = get_secret(
        "PEXELS_API_KEY"
    )


# ============================================================
# TEXTE
# ============================================================

def normalize_text(text: str) -> str:

    text = str(text or "")

    text = text.replace(
        "\r\n",
        "\n",
    )

    text = text.replace(
        "\r",
        "\n",
    )

    text = re.sub(
        r"[ \t]+",
        " ",
        text,
    )

    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text,
    )

    return text.strip()


def clean_ai_text(text: str) -> str:

    text = str(
        text or ""
    ).strip()

    text = re.sub(
        r"^```(?:text|markdown|json)?\s*",
        "",
        text,
        flags=re.I,
    )

    text = re.sub(
        r"\s*```$",
        "",
        text,
    )

    return normalize_text(
        text
    )


def count_words(text: str) -> int:

    text = remove_visual_markers(
        normalize_text(text)
    )

    return len(
        re.findall(
            r"\b[\wÀ-ÿ'-]+\b",
            text,
        )
    )


def safe_slug(
    text: str,
    max_len: int = 45,
) -> str:

    text = re.sub(
        r"[^a-zA-Z0-9À-ÿ]+",
        "-",
        text.lower(),
    ).strip("-")

    return (
        text[:max_len]
        or "production"
    )


# ============================================================
# COMMANDES
# ============================================================

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

    if not shutil.which(
        "ffmpeg"
    ):
        raise RuntimeError(
            "FFmpeg est introuvable. "
            "Ajoutez `ffmpeg` dans packages.txt."
        )

    if not shutil.which(
        "ffprobe"
    ):
        raise RuntimeError(
            "FFprobe est introuvable. "
            "Vérifiez packages.txt."
        )


def ffmpeg_escape_path(
    path: Path,
) -> str:

    return (
        str(path)
        .replace("\\", "/")
        .replace(":", r"\:")
        .replace("'", r"\'")
    )


def create_production_directory(
    topic: str,
) -> Path:

    folder = (
        TEMP_DIR
        / (
            time.strftime(
                "%Y%m%d-%H%M%S"
            )
            + "-"
            + safe_slug(topic)
        )
    )

    folder.mkdir(
        parents=True,
        exist_ok=True,
    )

    return folder


# ============================================================
# OPENROUTER
# ============================================================

def openrouter_request(
    messages: List[Dict[str, str]],
    temperature: float = 0.65,
    max_tokens: int = 1800,
    timeout: int = 75,
    max_retries: int = 1,
) -> str:

    if not OPENROUTER_API_KEY:

        raise RuntimeError(
            "OPENROUTER_API_KEY est introuvable "
            "dans les secrets Streamlit."
        )

    headers = {
        "Authorization": (
            f"Bearer {OPENROUTER_API_KEY}"
        ),
        "Content-Type": (
            "application/json"
        ),
        "HTTP-Referer": (
            "https://share.streamlit.io/"
        ),
        "X-Title": CHANNEL_NAME,
    }

    payload = {
        "model": OPENROUTER_MODEL,
        "models": OPENROUTER_FALLBACK_MODELS,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "provider": {
            "allow_fallbacks": True,
        },
    }

    last_error = (
        "Erreur inconnue OpenRouter."
    )

    attempts = max(
        1,
        max_retries + 1,
    )

    for attempt in range(
        attempts
    ):

        try:

            response = requests.post(
                OPENROUTER_URL,
                headers=headers,
                json=payload,
                timeout=timeout,
            )

        except requests.RequestException as exc:

            last_error = (
                f"Erreur réseau OpenRouter : "
                f"{exc}"
            )

            if (
                attempt + 1
                < attempts
            ):

                time.sleep(
                    2 + attempt * 2
                )

                continue

            raise RuntimeError(
                last_error
            ) from exc

        if response.status_code == 200:

            try:

                data = response.json()

                content = (
                    data["choices"][0]
                    ["message"]["content"]
                )

            except Exception as exc:

                raise RuntimeError(
                    "Réponse OpenRouter invalide."
                ) from exc

            content = clean_ai_text(
                content
            )

            if not content:

                raise RuntimeError(
                    "OpenRouter a répondu "
                    "sans contenu exploitable."
                )

            return content

        try:

            data = response.json()

            error = (
                data.get("error", {})
                if isinstance(
                    data,
                    dict,
                )
                else {}
            )

            message = (
                error.get("message")
                if isinstance(
                    error,
                    dict,
                )
                else None
            )

            if (
                not message
                and isinstance(
                    data,
                    dict,
                )
            ):

                message = data.get(
                    "message"
                )

        except Exception:

            message = response.text[
                :500
            ]

        last_error = (
            f"OpenRouter HTTP "
            f"{response.status_code}: "
            f"{message or 'erreur inconnue'}"
        )

        if (
            response.status_code == 429
            and attempt + 1 < attempts
        ):

            retry_after = (
                response.headers.get(
                    "Retry-After"
                )
            )

            try:

                wait = min(
                    max(
                        float(
                            retry_after
                        ),
                        1,
                    ),
                    8,
                ) if retry_after else 4

            except ValueError:

                wait = 4

            time.sleep(
                wait
            )

            continue

        if (
            400
            <= response.status_code
            < 500
        ):

            raise RuntimeError(
                last_error
            )

        if (
            attempt + 1
            < attempts
        ):

            time.sleep(
                3
            )

            continue

        raise RuntimeError(
            last_error
        )

    raise RuntimeError(
        last_error
    )


# ============================================================
# MARQUEURS VISUELS
# ============================================================

IMAGE_MARKER_RE = re.compile(
    r"\[(?:IMAGE|VISUAL)\s*:\s*(.*?)\]",
    re.I | re.S,
)


def extract_visual_markers(
    text: str,
) -> List[str]:

    return [
        normalize_text(item)
        for item in IMAGE_MARKER_RE.findall(
            text or ""
        )
        if normalize_text(item)
    ]


def remove_visual_markers(
    text: str,
) -> str:

    text = IMAGE_MARKER_RE.sub(
        " ",
        text or "",
    )

    return normalize_text(
        text
    )


# ============================================================
# GÉNÉRATION DU SCRIPT
# ============================================================

def generate_main_script(
    topic: str,
) -> str:

    topic = normalize_text(
        topic
    )

    if not topic:

        raise ValueError(
            "Le sujet est vide."
        )

    prompt = f"""
Vous écrivez pour la chaîne française
Cerveau Curieux.

THÈME :
{topic}

Cerveau Curieux explique la psychologie,
les neurosciences et le comportement humain
de façon surprenante, amusante et accessible.

Le contenu doit donner envie de rester jusqu'à
la dernière seconde.

RÈGLES SCIENTIFIQUES ABSOLUES :

- utilisez uniquement des informations vraies
- n'inventez aucune étude
- n'inventez aucune statistique
- n'inventez aucun chercheur
- n'inventez aucune expérience
- ne transformez pas une hypothèse en certitude
- soyez prudent lorsqu'une affirmation dépend du contexte

STYLE :

- hook très fort dans les 1 à 3 premières secondes
- ton naturel et énergique
- parfois humoristique
- jamais scolaire
- phrases courtes
- une idée intéressante régulièrement
- éviter les longues introductions
- éviter "Bonjour et bienvenue"
- expliquer simplement
- créer une progression narrative
- terminer par une idée mémorable
- terminer par un CTA naturel vers Cerveau Curieux

VISUELS :

Ajoutez des marqueurs :

[VISUAL: description précise]

Les descriptions doivent représenter
le sens réel de la phrase.

Ne choisissez jamais une image uniquement
parce qu'un mot apparaît dans la phrase.

Exemple mauvais :
"cerveau"

Exemple correct :
"personne devant une tâche non terminée,
regard hésitant, environnement de travail moderne"

Les visuels doivent varier.

Retournez uniquement le script.
"""

    return openrouter_request(
        [
            {
                "role": "system",
                "content": (
                    "Vous êtes un scénariste "
                    "scientifique précis, "
                    "créatif et factuellement prudent."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        temperature=0.72,
        max_tokens=2200,
        timeout=75,
        max_retries=1,
    )


def regenerate_short_main_script(
    topic: str,
) -> str:

    prompt = f"""
Créez un Short Cerveau Curieux
de 90 à 130 mots sur :

{topic}

Contraintes :

- accroche immédiatement
- psychologie, neurosciences ou comportement
- ton fun et intelligent
- jamais scolaire
- faits vrais uniquement
- aucune étude inventée
- aucune statistique inventée
- une progression claire
- une révélation ou idée surprenante
- conclusion mémorable
- CTA naturel vers Cerveau Curieux
- 4 à 6 marqueurs [VISUAL: ...]
- chaque visuel doit correspondre au sens réel
- ne retournez que le script
"""

    return openrouter_request(
        [
            {
                "role": "system",
                "content": (
                    "Vous écrivez des Shorts "
                    "scientifiques fiables "
                    "et divertissants."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        temperature=0.72,
        max_tokens=850,
        timeout=60,
        max_retries=1,
    )


def generate_two_shorts(
    script: str,
    topic: str,
) -> Tuple[str, str]:

    prompt = f"""
Transformez ce contenu en deux Shorts
autonomes pour Cerveau Curieux.

SUJET :
{topic}

SCRIPT :
{script}

Chaque partie doit avoir :

- son propre hook
- une progression compréhensible
- un ton fun et surprenant
- une base scientifique fiable
- aucun fait inventé
- des visuels [VISUAL: ...]
- une conclusion naturelle

Retournez exactement :

[PARTIE 1]
...

[PARTIE 2]
...
"""

    result = openrouter_request(
        [
            {
                "role": "system",
                "content": (
                    "Vous êtes un monteur éditorial "
                    "spécialisé dans les Shorts "
                    "scientifiques."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        temperature=0.6,
        max_tokens=1800,
        timeout=75,
        max_retries=1,
    )

    match1 = re.search(
        r"\[PARTIE\s*1\]"
        r"(.*?)(?=\[PARTIE\s*2\]|$)",
        result,
        re.I | re.S,
    )

    match2 = re.search(
        r"\[PARTIE\s*2\]"
        r"(.*)$",
        result,
        re.I | re.S,
    )

    if match1 and match2:

        return (
            clean_ai_text(
                match1.group(1)
            ),
            clean_ai_text(
                match2.group(1)
            ),
        )

    words = (
        remove_visual_markers(
            script
        ).split()
    )

    middle = max(
        1,
        len(words) // 2,
    )

    return (
        " ".join(
            words[:middle]
        ),
        " ".join(
            words[middle:]
        ),
    )


def fit_short_script(
    script: str,
    topic: str = "",
) -> str:

    script = clean_ai_text(
        script
    )

    word_count = count_words(
        script
    )

    if (
        SHORT_MIN_WORDS
        <= word_count
        <= SHORT_MAX_WORDS
    ):

        return script

    if (
        word_count < SHORT_MIN_WORDS
        and topic
    ):

        return regenerate_short_main_script(
            topic
        )

    if (
        word_count
        <= SHORT_MAX_WORDS
    ):

        return script

    prompt = f"""
Réduisez ce script pour un Short
Cerveau Curieux de 70 à 150 mots.

Conservez :

- le hook
- les faits essentiels
- l'idée surprenante
- le CTA
- les visuels pertinents

N'inventez rien.

SCRIPT :

{script}

Retournez uniquement le texte.
"""

    try:

        result = openrouter_request(
            [
                {
                    "role": "system",
                    "content": (
                        "Vous réduisez des scripts "
                        "scientifiques sans inventer."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=0.45,
            max_tokens=850,
            timeout=60,
            max_retries=0,
        )

        return clean_ai_text(
            result
        )

    except Exception:

        return script


def generate_teaser(
    script: str,
    topic: str,
) -> str:

    prompt = f"""
Créez un teaser vertical
de 60 à 100 mots pour Cerveau Curieux.

Sujet :
{topic}

Source :
{script}

Le teaser doit :

- créer une curiosité réelle
- ne pas tout révéler
- être scientifiquement correct
- ne rien inventer
- être naturel à l'oral
- donner envie de découvrir la suite

Retournez uniquement le texte.
"""

    try:

        return clean_ai_text(
            openrouter_request(
                [
                    {
                        "role": "system",
                        "content": (
                            "Vous créez des teasers "
                            "scientifiques courts "
                            "et captivants."
                        ),
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                temperature=0.7,
                max_tokens=650,
                timeout=60,
                max_retries=0,
            )
        )

    except Exception:

        return " ".join(
            remove_visual_markers(
                script
            ).split()[:90]
        )


def choose_content_mode(
    word_count: int,
) -> str:

    if (
        word_count
        < REGENERATE_BELOW
    ):

        return "regenerate"

    if word_count < 350:

        return "one_short"

    if word_count < LONG_MIN_WORDS:

        return "two_shorts"

    return "long"


# ============================================================
# PEXELS
# ============================================================

STOPWORDS = {
    "dans",
    "avec",
    "pour",
    "cette",
    "cela",
    "comme",
    "votre",
    "vous",
    "nous",
    "notre",
    "leurs",
    "leur",
    "mais",
    "donc",
    "alors",
    "quand",
    "plus",
    "moins",
    "être",
    "avoir",
    "faire",
    "très",
    "aussi",
    "parce",
    "ces",
    "des",
    "une",
    "les",
    "sur",
    "sous",
    "entre",
    "vers",
    "chez",
    "sans",
    "qui",
    "que",
    "est",
    "sont",
    "son",
    "ses",
    "aux",
    "du",
    "de",
    "la",
    "le",
    "un",
    "et",
    "ou",
    "en",
    "à",
    "au",
}


def pexels_search(
    query: str,
    per_page: int = 10,
    orientation: str = "portrait",
) -> List[dict]:

    if (
        not PEXELS_API_KEY
        or not query
    ):

        return []

    try:

        response = requests.get(
            PEXELS_SEARCH_URL,
            headers={
                "Authorization":
                    PEXELS_API_KEY
            },
            params={
                "query": query,
                "per_page": per_page,
                "orientation":
                    orientation,
            },
            timeout=20,
        )

        if response.status_code != 200:

            return []

        data = response.json()

        photos = data.get(
            "photos",
            [],
        )

        if not isinstance(
            photos,
            list,
        ):

            return []

        return photos

    except Exception:

        return []


def download_file(
    url: str,
    destination: Path,
) -> bool:

    try:

        response = requests.get(
            url,
            timeout=30,
            stream=True,
        )

        if response.status_code != 200:

            return False

        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with open(
            destination,
            "wb",
        ) as file:

            for chunk in response.iter_content(
                128 * 1024
            ):

                if chunk:
                    file.write(
                        chunk
                    )

        return (
            destination.exists()
            and destination.stat().st_size
            > 0
        )

    except Exception:

        return False


def normalize_image(
    source: Path,
    destination: Path,
    width: int,
    height: int,
) -> bool:

    try:

        with Image.open(
            source
        ) as image:

            image = image.convert(
                "RGB"
            )

            ratio = max(
                width / image.width,
                height / image.height,
            )

            new_width = max(
                width,
                int(
                    image.width
                    * ratio
                ),
            )

            new_height = max(
                height,
                int(
                    image.height
                    * ratio
                ),
            )

            image = image.resize(
                (
                    new_width,
                    new_height,
                ),
                Image.Resampling.LANCZOS,
            )

            left = (
                new_width
                - width
            ) // 2

            top = (
                new_height
                - height
            ) // 2

            image = image.crop(
                (
                    left,
                    top,
                    left + width,
                    top + height,
                )
            )

            destination.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            image.save(
                destination,
                "JPEG",
                quality=92,
                optimize=True,
            )

        return True

    except Exception:

        return False


def create_placeholder(
    destination: Path,
    text: str,
    width: int,
    height: int,
) -> Path:

    image = Image.new(
        "RGB",
        (
            width,
            height,
        ),
        (18, 16, 34),
    )

    draw = ImageDraw.Draw(
        image
    )

    font = ImageFont.load_default()

    wrapped = textwrap.fill(
        normalize_text(
            text
        )[:160],
        width=35
        if height > width
        else 55,
    )

    bbox = (
        draw.multiline_textbbox(
            (0, 0),
            wrapped,
            font=font,
            spacing=8,
            align="center",
        )
    )

    text_width = (
        bbox[2]
        - bbox[0]
    )

    text_height = (
        bbox[3]
        - bbox[1]
    )

    x = (
        width
        - text_width
    ) // 2

    y = (
        height
        - text_height
    ) // 2

    draw.multiline_text(
        (
            x,
            y,
        ),
        wrapped,
        font=font,
        fill="white",
        spacing=8,
        align="center",
    )

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    image.save(
        destination,
        "JPEG",
        quality=90,
    )

    return destination


# ============================================================
# VISUELS
# ============================================================

def _visual_query_keywords(
    text: str,
) -> List[str]:

    words = re.findall(
        r"[A-Za-zÀ-ÿ]{4,}",
        text.lower(),
    )

    result = []

    for word in words:

        if (
            word in STOPWORDS
            or word in result
        ):
            continue

        result.append(
            word
        )

    return result[:7]


def _visual_query_variants(
    description: str,
) -> List[str]:

    description = normalize_text(
        description
    )

    keywords = _visual_query_keywords(
        description
    )

    queries = [
        description
    ]

    if keywords:

        queries.append(
            " ".join(
                keywords[:5]
            )
        )

        queries.append(
            " ".join(
                keywords[:3]
            )
            + " realistic photo"
        )

    return list(
        dict.fromkeys(
            queries
        )
    )


def _select_best_visual_photo(
    photos: List[dict],
    query: str,
    used_ids: set,
) -> Optional[dict]:

    query_words = set(
        _visual_query_keywords(
            query
        )
    )

    ranked = []

    for photo in photos:

        photo_id = photo.get(
            "id"
        )

        if photo_id in used_ids:

            continue

        alt = str(
            photo.get(
                "alt",
                "",
            )
        ).lower()

        score = sum(
            1
            for word in query_words
            if word in alt
        )

        if (
            photo.get(
                "width",
                0,
            )
            and
            photo.get(
                "height",
                0,
            )
        ):

            score += 0.2

        ranked.append(
            (
                score,
                photo,
            )
        )

    if not ranked:

        return None

    ranked.sort(
        key=lambda item:
            item[0],
        reverse=True,
    )

    return ranked[0][1]


# ============================================================
# TIMING DE LA NARRATION
# ============================================================

def get_word_boundaries(
    text: str,
    voice: str,
    duration: float,
) -> List[
    Tuple[
        str,
        float,
        float,
    ]
]:

    text = remove_visual_markers(
        text
    )

    if not text:

        return []

    boundaries = []

    async def collect():

        communicate = (
            edge_tts.Communicate(
                text=text,
                voice=voice,
                rate=VOICE_RATE,
                volume=VOICE_VOLUME,
            )
        )

        async for event in (
            communicate.stream()
        ):

            if (
                event.get(
                    "type"
                )
                != "WordBoundary"
            ):

                continue

            word = str(
                event.get(
                    "text",
                    "",
                )
            ).strip()

            if not word:

                continue

            start = (
                float(
                    event.get(
                        "offset",
                        0,
                    )
                )
                / 10_000_000
            )

            word_duration = max(
                0.03,
                float(
                    event.get(
                        "duration",
                        0,
                    )
                )
                / 10_000_000,
            )

            boundaries.append(
                (
                    word,
                    start,
                    word_duration,
                )
            )

    try:

        asyncio.run(
            collect()
        )

    except RuntimeError:

        errors = []

        def runner():

            loop = (
                asyncio.new_event_loop()
            )

            asyncio.set_event_loop(
                loop
            )

            try:

                loop.run_until_complete(
                    collect()
                )

            except Exception as exc:

                errors.append(
                    exc
                )

            finally:

                loop.close()

        thread = threading.Thread(
            target=runner
        )

        thread.start()
        thread.join()

        if errors:

            boundaries = []

    except Exception:

        boundaries = []

    if not boundaries:

        words = text.split()

        step = (
            duration
            / max(
                len(words),
                1,
            )
        )

        return [
            (
                word,
                index * step,
                step,
            )
            for index, word
            in enumerate(words)
        ]

    cleaned = []

    for index, item in enumerate(
        boundaries
    ):

        word, start, word_duration = (
            item
        )

        start = max(
            0.0,
            min(
                start,
                duration,
            ),
        )

        if (
            index + 1
            < len(boundaries)
        ):

            end = min(
                duration,
                max(
                    start + 0.03,
                    boundaries[
                        index + 1
                    ][1],
                ),
            )

        else:

            end = min(
                duration,
                max(
                    start + 0.03,
                    start
                    + word_duration,
                ),
            )

        cleaned.append(
            (
                word,
                start,
                max(
                    0.03,
                    end - start,
                ),
            )
        )

    return cleaned


def build_visual_requests(
    script: str,
    count: int,
) -> List[str]:

    markers = extract_visual_markers(
        script
    )

    text = remove_visual_markers(
        script
    )

    sentences = [
        normalize_text(item)
        for item in re.split(
            r"(?<=[.!?])\s+",
            text,
        )
        if normalize_text(item)
    ]

    requests = []

    for marker in markers:

        if (
            len(requests)
            >= count
        ):

            break

        requests.append(
            marker
        )

    for sentence in sentences:

        if (
            len(requests)
            >= count
        ):

            break

        if count_words(
            sentence
        ) >= 5:

            requests.append(
                sentence
            )

    if not requests:

        requests = [
            text[:180]
            or "human brain psychology"
        ]

    while (
        len(requests)
        < count
    ):

        requests.append(
            requests[-1]
        )

    return requests[
        :count
    ]


def build_visual_timing(
    boundaries: List[
        Tuple[
            str,
            float,
            float,
        ]
    ],
    count: int,
    total_duration: float,
) -> List[
    Tuple[
        float,
        float,
    ]
]:

    if count <= 1:

        return [
            (
                0.0,
                total_duration,
            )
        ]

    if not boundaries:

        step = (
            total_duration
            / count
        )

        return [
            (
                index * step,
                (index + 1)
                * step,
            )
            for index in range(
                count
            )
        ]

    word_count = len(
        boundaries
    )

    spans = []

    for index in range(
        count
    ):

        start_index = round(
            index
            * word_count
            / count
        )

        end_index = round(
            (index + 1)
            * word_count
            / count
        )

        start = (
            boundaries[
                min(
                    start_index,
                    word_count - 1,
                )
            ][1]
        )

        if (
            end_index
            < word_count
        ):

            end = (
                boundaries[
                    end_index
                ][1]
            )

        else:

            end = total_duration

        spans.append(
            (
                max(
                    0.0,
                    start,
                ),
                max(
                    start + 0.8,
                    min(
                        total_duration,
                        end,
                    ),
                ),
            )
        )

    spans[0] = (
        0.0,
        spans[0][1],
    )

    spans[-1] = (
        spans[-1][0],
        total_duration,
    )

    return spans


def create_visual_plan(
    script: str,
    boundaries: List[
        Tuple[
            str,
            float,
            float,
        ]
    ],
    duration: float,
    vertical: bool,
    work_dir: Path,
) -> List[
    Tuple[
        Path,
        float,
        float,
    ]
]:

    if vertical:

        count = max(
            5,
            min(
                12,
                int(
                    math.ceil(
                        duration
                        / 3.4
                    )
                ),
            ),
        )

    else:

        count = max(
            8,
            min(
                24,
                int(
                    math.ceil(
                        duration
                        / 5.0
                    )
                ),
            ),
        )

    requests_ = build_visual_requests(
        script,
        count,
    )

    timings = build_visual_timing(
        boundaries,
        count,
        duration,
    )

    if vertical:

        width, height = (
            1080,
            1920,
        )

        orientation = (
            "portrait"
        )

    else:

        width, height = (
            1920,
            1080,
        )

        orientation = (
            "landscape"
        )

    used_ids = set()
    plan = []

    for index, (
        query,
        timing,
    ) in enumerate(
        zip(
            requests_,
            timings,
        )
    ):

        start, end = timing

        image_path = (
            work_dir
            / f"visual_{index:02d}.jpg"
        )

        raw_path = (
            work_dir
            / f"raw_{index:02d}.jpg"
        )

        photo = None

        if PEXELS_API_KEY:

            for variant in (
                _visual_query_variants(
                    query
                )
            ):

                photos = pexels_search(
                    variant,
                    per_page=10,
                    orientation=orientation,
                )

                photo = (
                    _select_best_visual_photo(
                        photos,
                        query,
                        used_ids,
                    )
                )

                if photo:

                    break

        if photo:

            photo_id = photo.get(
                "id"
            )

            if photo_id:

                used_ids.add(
                    photo_id
                )

            source_url = (
                photo
                .get("src", {})
                .get("large2x")
                or
                photo
                .get("src", {})
                .get("large")
                or
                photo
                .get("src", {})
                .get("original")
            )

            if (
                source_url
                and download_file(
                    source_url,
                    raw_path,
                )
                and normalize_image(
                    raw_path,
                    image_path,
                    width,
                    height,
                )
            ):

                pass

            else:

                create_placeholder(
                    image_path,
                    query,
                    width,
                    height,
                )

        else:

            create_placeholder(
                image_path,
                query,
                width,
                height,
            )

        plan.append(
            (
                image_path,
                start,
                end,
            )
        )

    return plan# ============================================================
# EDGE TTS
# ============================================================

def select_french_voice() -> str:

    preferred = [
        "fr-FR-DeniseNeural",
        "fr-FR-HenriNeural",
        "fr-FR-VivienneMultilingualNeural",
        "fr-FR-RemyMultilingualNeural",
    ]

    try:

        async def get_voices():

            return await edge_tts.list_voices()

        voices = asyncio.run(
            get_voices()
        )

        available = {
            str(
                voice.get(
                    "ShortName"
                )
            )
            for voice in voices
            if isinstance(
                voice,
                dict,
            )
        }

        for voice in preferred:

            if voice in available:

                return voice

    except Exception:

        pass

    return preferred[0]


def synthesize_with_voice(
    text: str,
    output_path: Path,
    voice: str,
) -> Path:

    text = remove_visual_markers(
        text
    )

    if not text:

        raise RuntimeError(
            "Le texte de narration est vide."
        )

    async def generate():

        communicate = (
            edge_tts.Communicate(
                text=text,
                voice=voice,
                rate=VOICE_RATE,
                volume=VOICE_VOLUME,
            )
        )

        await communicate.save(
            str(output_path)
        )

    try:

        asyncio.run(
            generate()
        )

    except RuntimeError:

        errors = []

        def runner():

            loop = (
                asyncio.new_event_loop()
            )

            asyncio.set_event_loop(
                loop
            )

            try:

                loop.run_until_complete(
                    generate()
                )

            except Exception as exc:

                errors.append(
                    exc
                )

            finally:

                loop.close()

        thread = threading.Thread(
            target=runner
        )

        thread.start()
        thread.join()

        if errors:

            raise RuntimeError(
                f"Erreur Edge-TTS : "
                f"{errors[0]}"
            )

    if (
        not output_path.exists()
        or output_path.stat().st_size
        == 0
    ):

        raise RuntimeError(
            "Edge-TTS n'a pas créé "
            "la narration."
        )

    return output_path


def get_duration(
    path: Path,
) -> float:

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
            str(path),
        ],
        30,
    )

    if result.returncode != 0:

        raise RuntimeError(
            result.stderr[-600:]
        )

    try:

        return max(
            0.01,
            float(
                result.stdout.strip()
            ),
        )

    except ValueError as exc:

        raise RuntimeError(
            "Durée média invalide."
        ) from exc


# ============================================================
# SOUS-TITRES
# ============================================================

def ass_time(
    seconds: float,
) -> str:

    seconds = max(
        0.0,
        float(seconds),
    )

    hours = int(
        seconds // 3600
    )

    minutes = int(
        (
            seconds
            % 3600
        )
        // 60
    )

    whole_seconds = int(
        seconds % 60
    )

    centiseconds = int(
        round(
            (
                seconds
                - int(seconds)
            )
            * 100
        )
    )

    if centiseconds >= 100:

        whole_seconds += 1
        centiseconds = 0

    return (
        f"{hours}:"
        f"{minutes:02d}:"
        f"{whole_seconds:02d}."
        f"{centiseconds:02d}"
    )


def ass_escape(
    text: str,
) -> str:

    return (
        text
        .replace(
            "\\",
            "\\\\",
        )
        .replace(
            "{",
            "\\{",
        )
        .replace(
            "}",
            "\\}",
        )
        .replace(
            "\n",
            " ",
        )
    )


def wrap_phrase(
    words: List[str],
    max_chars: int,
) -> List[str]:

    lines = []
    current = ""

    for word in words:

        candidate = (
            f"{current} {word}"
        ).strip()

        if (
            current
            and len(candidate)
            > max_chars
        ):

            lines.append(
                current
            )

            current = word

        else:

            current = candidate

    if current:

        lines.append(
            current
        )

    return lines[:2]


def group_subtitles(
    boundaries: List[
        Tuple[
            str,
            float,
            float,
        ]
    ],
    max_words: int = 7,
) -> List[
    Tuple[
        int,
        int,
    ]
]:

    groups = []

    start = 0

    for index in range(
        1,
        len(boundaries) + 1,
    ):

        if (
            index
            == len(boundaries)
            or index - start
            >= max_words
        ):

            groups.append(
                (
                    start,
                    index,
                )
            )

            start = index

    return groups


def create_ass_subtitles(
    boundaries: List[
        Tuple[
            str,
            float,
            float,
        ]
    ],
    output_path: Path,
    vertical: bool,
) -> Path:

    if vertical:

        width, height = (
            1080,
            1920,
        )

        font_size = 58
        margin_v = 275
        max_chars = 31

    else:

        width, height = (
            1920,
            1080,
        )

        font_size = 46
        margin_v = 90
        max_chars = 52

    header = f"""
[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: CC,DejaVu Sans,{font_size},&H00FFFFFF,&H00FFFFFF,&H00131313,&H90000000,-1,0,0,0,100,100,0,0,1,4,1,2,80,80,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = [
        header
    ]

    groups = group_subtitles(
        boundaries,
        max_words=7,
    )

    active_color = (
        r"\c&H0050E6FF&"
    )

    normal_color = (
        r"\c&H00FFFFFF&"
    )

    for group_start, group_end in groups:

        group = boundaries[
            group_start:group_end
        ]

        words = [
            item[0]
            for item in group
        ]

        wrapped = wrap_phrase(
            words,
            max_chars,
        )

        first_line_words = (
            len(
                wrapped[0].split()
            )
            if len(wrapped) > 1
            else len(words)
        )

        for active_index in range(
            group_start,
            group_end,
        ):

            local_active = (
                active_index
                - group_start
            )

            start = group[
                local_active
            ][1]

            if (
                active_index + 1
                < group_end
            ):

                end = boundaries[
                    active_index + 1
                ][1]

            else:

                last_word = boundaries[
                    group_end - 1
                ]

                end = (
                    last_word[1]
                    + last_word[2]
                )

            end = max(
                start + 0.05,
                end,
            )

            tokens = []

            for local_index, word in enumerate(
                words
            ):

                color = (
                    active_color
                    if local_index
                    == local_active
                    else normal_color
                )

                tokens.append(
                    color
                    + ass_escape(word)
                )

            phrase = " ".join(
                tokens
            )

            if len(wrapped) > 1:

                split_at = first_line_words

                phrase_tokens = (
                    phrase.split(" ")
                )

                phrase = (
                    " ".join(
                        phrase_tokens[
                            :split_at
                        ]
                    )
                    + r"\N"
                    + " ".join(
                        phrase_tokens[
                            split_at:
                        ]
                    )
                )

            dialogue = (
                "Dialogue: 0,"
                f"{ass_time(start)},"
                f"{ass_time(end)},"
                "CC,,0,0,0,,"
                "{\\an2}"
                f"{phrase}\n"
            )

            lines.append(
                dialogue
            )

    output_path.write_text(
        "".join(lines),
        encoding="utf-8",
    )

    return output_path


# ============================================================
# MASCOTTE CERVEAU
# ============================================================

def font_bold(
    size: int,
):

    possible_fonts = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ]

    for path in possible_fonts:

        if Path(path).exists():

            return ImageFont.truetype(
                path,
                size,
            )

    return ImageFont.load_default()


def draw_brain_shape(
    draw: ImageDraw.ImageDraw,
    box: Tuple[
        int,
        int,
        int,
        int,
    ],
    fill,
    outline,
    width: int = 12,
    expression: str = "normal",
):

    x0, y0, x1, y1 = box

    # Hémisphère gauche
    left = [
        (x0 + 70, y0 + 155),
        (x0 + 55, y0 + 105),
        (x0 + 85, y0 + 55),
        (x0 + 140, y0 + 25),
        (x0 + 205, y0 + 35),
        (x0 + 245, y0 + 75),
        (x0 + 250, y0 + 145),
        (x0 + 225, y0 + 205),
        (x0 + 175, y0 + 250),
        (x0 + 105, y0 + 235),
    ]

    # Hémisphère droit
    right = [
        (x0 + 245, y0 + 75),
        (x0 + 285, y0 + 35),
        (x0 + 350, y0 + 42),
        (x0 + 395, y0 + 85),
        (x0 + 410, y0 + 145),
        (x0 + 395, y0 + 200),
        (x0 + 350, y0 + 238),
        (x0 + 285, y0 + 252),
        (x0 + 245, y0 + 205),
    ]

    draw.polygon(
        left,
        fill=fill,
        outline=outline,
    )

    draw.polygon(
        right,
        fill=fill,
        outline=outline,
    )

    # Circonvolutions.
    folds = [
        [
            (x0 + 90, y0 + 100),
            (x0 + 125, y0 + 78),
            (x0 + 155, y0 + 100),
            (x0 + 135, y0 + 130),
            (x0 + 100, y0 + 145),
        ],
        [
            (x0 + 170, y0 + 55),
            (x0 + 185, y0 + 95),
            (x0 + 165, y0 + 125),
            (x0 + 185, y0 + 155),
            (x0 + 160, y0 + 190),
        ],
        [
            (x0 + 85, y0 + 175),
            (x0 + 120, y0 + 165),
            (x0 + 145, y0 + 190),
            (x0 + 125, y0 + 215),
        ],
        [
            (x0 + 295, y0 + 65),
            (x0 + 325, y0 + 92),
            (x0 + 305, y0 + 125),
            (x0 + 340, y0 + 145),
            (x0 + 365, y0 + 120),
        ],
        [
            (x0 + 275, y0 + 160),
            (x0 + 310, y0 + 180),
            (x0 + 295, y0 + 215),
            (x0 + 345, y0 + 220),
        ],
        [
            (x0 + 370, y0 + 80),
            (x0 + 350, y0 + 105),
            (x0 + 375, y0 + 145),
            (x0 + 355, y0 + 175),
        ],
    ]

    for points in folds:

        draw.line(
            points,
            fill=outline,
            width=max(
                3,
                width // 3,
            ),
            joint="curve",
        )

    # Séparation des deux hémisphères.
    draw.line(
        (
            x0 + 250,
            y0 + 65,
            x0 + 250,
            y0 + 220,
        ),
        fill=outline,
        width=7,
    )

    # Yeux.
    eye_y = y0 + 145

    draw.ellipse(
        (
            x0 + 130,
            eye_y - 20,
            x0 + 185,
            eye_y + 35,
        ),
        fill="white",
        outline=outline,
        width=5,
    )

    draw.ellipse(
        (
            x0 + 300,
            eye_y - 20,
            x0 + 355,
            eye_y + 35,
        ),
        fill="white",
        outline=outline,
        width=5,
    )

    pupil_y = (
        eye_y - 3
        if expression == "surprised"
        else eye_y + 5
    )

    pupil_shift = (
        7
        if expression == "amused"
        else 0
    )

    draw.ellipse(
        (
            x0 + 153 + pupil_shift,
            pupil_y - 3,
            x0 + 170 + pupil_shift,
            pupil_y + 20,
        ),
        fill=outline,
    )

    draw.ellipse(
        (
            x0 + 323 + pupil_shift,
            pupil_y - 3,
            x0 + 340 + pupil_shift,
            pupil_y + 20,
        ),
        fill=outline,
    )

    # Sourcils.
    if expression == "surprised":

        draw.arc(
            (
                x0 + 125,
                y0 + 105,
                x0 + 185,
                y0 + 140,
            ),
            200,
            340,
            fill=outline,
            width=6,
        )

        draw.arc(
            (
                x0 + 295,
                y0 + 105,
                x0 + 355,
                y0 + 140,
            ),
            200,
            340,
            fill=outline,
            width=6,
        )

    elif expression == "thinking":

        draw.line(
            (
                x0 + 125,
                y0 + 120,
                x0 + 180,
                y0 + 108,
            ),
            fill=outline,
            width=7,
        )

        draw.line(
            (
                x0 + 300,
                y0 + 108,
                x0 + 355,
                y0 + 120,
            ),
            fill=outline,
            width=7,
        )

    else:

        draw.line(
            (
                x0 + 128,
                y0 + 115,
                x0 + 180,
                y0 + 118,
            ),
            fill=outline,
            width=7,
        )

        draw.line(
            (
                x0 + 305,
                y0 + 118,
                x0 + 357,
                y0 + 115,
            ),
            fill=outline,
            width=7,
        )

    # Bouche.
    mouth = (
        x0 + 205,
        y0 + 170,
        x0 + 295,
        y0 + 225,
    )

    if expression in {
        "talking",
        "surprised",
    }:

        draw.ellipse(
            mouth,
            fill=outline,
        )

        if expression == "talking":

            draw.ellipse(
                (
                    x0 + 225,
                    y0 + 193,
                    x0 + 275,
                    y0 + 214,
                ),
                fill=(244, 105, 125),
            )

    elif expression == "amused":

        draw.arc(
            mouth,
            10,
            170,
            fill=outline,
            width=8,
        )

    else:

        draw.arc(
            mouth,
            15,
            165,
            fill=outline,
            width=8,
        )


def create_brain_mascot(
    output_path: Path,
    expression: str = "normal",
) -> Path:

    image = Image.new(
        "RGBA",
        (
            480,
            480,
        ),
        (
            0,
            0,
            0,
            0,
        ),
    )

    draw = ImageDraw.Draw(
        image
    )

    # Badge Cerveau Curieux.
    draw.ellipse(
        (
            12,
            12,
            468,
            468,
        ),
        fill=MASCOT_BLUE
        + (235,),
        outline=MASCOT_PURPLE
        + (255,),
        width=8,
    )

    draw_brain_shape(
        draw,
        (
            40,
            70,
            440,
            330,
        ),
        MASCOT_PINK,
        MASCOT_DARK,
        12,
        expression,
    )

    # Petit corps.
    draw.line(
        (
            210,
            325,
            180,
            405,
        ),
        fill=MASCOT_DARK,
        width=13,
    )

    draw.line(
        (
            270,
            325,
            300,
            405,
        ),
        fill=MASCOT_DARK,
        width=13,
    )

    draw.line(
        (
            180,
            405,
            150,
            420,
        ),
        fill=MASCOT_DARK,
        width=13,
    )

    draw.line(
        (
            300,
            405,
            330,
            420,
        ),
        fill=MASCOT_DARK,
        width=13,
    )

    # Bulle de curiosité.
    if expression in {
        "thinking",
        "surprised",
    }:

        draw.ellipse(
            (
                355,
                25,
                455,
                120,
            ),
            fill="white",
            outline=MASCOT_DARK,
            width=6,
        )

        font = font_bold(
            52
        )

        symbol = (
            "?"
            if expression
            == "thinking"
            else "!"
        )

        bbox = draw.textbbox(
            (0, 0),
            symbol,
            font=font,
        )

        draw.text(
            (
                405
                - (
                    bbox[2]
                    - bbox[0]
                ) / 2,
                72
                - (
                    bbox[3]
                    - bbox[1]
                ) / 2,
            ),
            symbol,
            fill=MASCOT_DARK,
            font=font,
        )

    image.save(
        output_path
    )

    return output_path# ============================================================
# SCÈNES VIDÉO
# ============================================================

def create_image_scene(
    image_path: Path,
    output_path: Path,
    duration: float,
    width: int,
    height: int,
    index: int,
) -> Path:

    ensure_ffmpeg()

    duration = max(
        0.8,
        duration,
    )

    pattern = index % 4

    if pattern == 0:

        x = (
            "(iw-ow)/2"
            "+18*sin(t*0.55)"
        )

        y = (
            "(ih-oh)/2"
            "+12*cos(t*0.45)"
        )

    elif pattern == 1:

        x = (
            "(iw-ow)*0.20"
            "+35*sin(t*0.42)"
        )

        y = (
            "(ih-oh)/2"
            "+10*cos(t*0.38)"
        )

    elif pattern == 2:

        x = (
            "(iw-ow)*0.65"
            "+28*cos(t*0.40)"
        )

        y = (
            "(ih-oh)*0.35"
            "+18*sin(t*0.32)"
        )

    else:

        x = (
            "(iw-ow)/2"
            "+24*cos(t*0.34)"
        )

        y = (
            "(ih-oh)*0.60"
            "+15*sin(t*0.40)"
        )

    video_filter = (
        f"scale={int(width * 1.10)}:"
        f"{int(height * 1.10)}:"
        "force_original_aspect_ratio=increase,"
        f"crop={width}:{height}:"
        f"x='{x}':"
        f"y='{y}',"
        "eq=contrast=1.03:"
        "saturation=1.05:"
        "brightness=0.01,"
        "format=yuv420p"
    )

    result = run_command(
        [
            "ffmpeg",
            "-y",
            "-loop",
            "1",
            "-i",
            str(image_path),
            "-vf",
            video_filter,
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
        ],
        timeout=120,
    )

    if (
        result.returncode != 0
    ):

        fallback_filter = (
            f"scale={width}:{height}:"
            "force_original_aspect_ratio=increase,"
            f"crop={width}:{height},"
            "format=yuv420p"
        )

        result = run_command(
            [
                "ffmpeg",
                "-y",
                "-loop",
                "1",
                "-i",
                str(image_path),
                "-vf",
                fallback_filter,
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
            ],
            timeout=120,
        )

    if (
        result.returncode != 0
        or not output_path.exists()
    ):

        raise RuntimeError(
            "Impossible de créer "
            "une scène vidéo : "
            + result.stderr[-900:]
        )

    return output_path


def concat_scenes(
    scenes: List[Path],
    output: Path,
) -> Path:

    ensure_ffmpeg()

    if not scenes:

        raise RuntimeError(
            "Aucune scène à assembler."
        )

    concat_file = (
        output.parent
        / "concat.txt"
    )

    lines = []

    for scene in scenes:

        path = (
            scene.resolve()
            .as_posix()
        )

        path = path.replace(
            "'",
            r"'\''",
        )

        lines.append(
            f"file '{path}'"
        )

    concat_file.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

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
            str(output),
        ],
        timeout=300,
    )

    if (
        result.returncode != 0
    ):

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
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-pix_fmt",
                "yuv420p",
                str(output),
            ],
            timeout=300,
        )

    if (
        result.returncode != 0
    ):

        raise RuntimeError(
            "Impossible d'assembler "
            "les scènes : "
            + result.stderr[-1000:]
        )

    return output


# ============================================================
# EFFETS SONORES
# ============================================================

def create_sfx(
    path: Path,
    kind: str,
) -> Path:

    ensure_ffmpeg()

    if kind == "whoosh":

        source = (
            "anoisesrc="
            "color=white:"
            "amplitude=0.16:"
            "d=0.35"
        )

        audio_filter = (
            "highpass=f=500,"
            "lowpass=f=6500,"
            "afade=t=in:st=0:d=0.04,"
            "afade=t=out:st=0.24:d=0.11"
        )

        duration = "0.35"

    elif kind == "impact":

        source = (
            "sine="
            "frequency=115:"
            "sample_rate=44100:"
            "duration=0.22"
        )

        audio_filter = (
            "volume=0.22,"
            "afade=t=out:st=0.05:d=0.17"
        )

        duration = "0.22"

    else:

        source = (
            "sine="
            "frequency=720:"
            "sample_rate=44100:"
            "duration=0.16"
        )

        audio_filter = (
            "volume=0.16,"
            "afade=t=out:st=0.03:d=0.13"
        )

        duration = "0.16"

    result = run_command(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            source,
            "-af",
            audio_filter,
            "-t",
            duration,
            "-ar",
            "44100",
            "-ac",
            "2",
            str(path),
        ],
        timeout=30,
    )

    if result.returncode != 0:

        raise RuntimeError(
            "Impossible de créer "
            "un effet sonore : "
            + result.stderr[-500:]
        )

    return path


def choose_sfx_events(
    script: str,
    boundaries: List[
        Tuple[
            str,
            float,
            float,
        ]
    ],
    duration: float,
) -> List[
    Tuple[
        float,
        str,
        float,
    ]
]:

    text = remove_visual_markers(
        script
    )

    sentences = [
        item.strip()
        for item in re.split(
            r"(?<=[.!?])\s+",
            text,
        )
        if item.strip()
    ]

    events = []

    cursor = 0

    trigger_words = {
        "mais",
        "pourtant",
        "surprise",
        "étonnant",
        "pourquoi",
        "cerveau",
        "jamais",
        "vraiment",
        "incroyable",
        "exactement",
    }

    for sentence in sentences:

        words = re.findall(
            r"\b[\wÀ-ÿ'-]+\b",
            sentence.lower(),
        )

        hits = [
            word
            for word in words
            if word in trigger_words
        ]

        if (
            hits
            and cursor
            < len(boundaries)
        ):

            index = min(
                len(boundaries) - 1,
                cursor
                + max(
                    0,
                    len(words) // 2,
                ),
            )

            start = boundaries[
                index
            ][1]

            if any(
                word in hits
                for word in [
                    "surprise",
                    "étonnant",
                    "incroyable",
                ]
            ):

                kind = "impact"

            else:

                kind = "whoosh"

            events.append(
                (
                    min(
                        max(
                            0.05,
                            start,
                        ),
                        max(
                            0.05,
                            duration
                            - 0.05,
                        ),
                    ),
                    kind,
                    (
                        0.18
                        if kind
                        == "impact"
                        else 0.16
                    ),
                )
            )

        cursor += max(
            1,
            len(words),
        )

    if (
        boundaries
        and not events
    ):

        first_sentence_words = (
            len(
                re.findall(
                    r"\b[\wÀ-ÿ'-]+\b",
                    sentences[0],
                )
            )
            if sentences
            else 0
        )

        if (
            first_sentence_words
            <= 14
        ):

            events.append(
                (
                    max(
                        0.05,
                        boundaries[0][1],
                    ),
                    "impact",
                    0.18,
                )
            )

    deduped = []

    for event in events:

        if (
            not deduped
            or abs(
                event[0]
                - deduped[-1][0]
            )
            > 1.8
        ):

            deduped.append(
                event
            )

    return deduped[:7]


def mix_audio_with_sfx(
    narration: Path,
    sfx_events: List[
        Tuple[
            float,
            str,
            float,
        ]
    ],
    work_dir: Path,
    output: Path,
) -> Path:

    if not sfx_events:

        shutil.copy2(
            narration,
            output,
        )

        return output

    inputs = [
        str(narration)
    ]

    filters = []

    labels = [
        "[0:a]"
    ]

    for index, (
        time_sec,
        kind,
        volume,
    ) in enumerate(
        sfx_events,
        start=1,
    ):

        sfx_path = (
            work_dir
            / (
                f"sfx_{index:02d}_"
                f"{kind}.wav"
            )
        )

        create_sfx(
            sfx_path,
            kind,
        )

        inputs.append(
            str(sfx_path)
        )

        delay = int(
            time_sec * 1000
        )

        filters.append(
            f"[{index}:a]"
            f"volume={volume},"
            f"adelay={delay}|{delay}"
            f"[s{index}]"
        )

        labels.append(
            f"[s{index}]"
        )

    filters.append(
        (
            "".join(labels)
            + "amix="
            f"inputs={len(labels)}:"
            "duration=first:"
            "dropout_transition=0,"
            "alimiter=limit=0.88"
            "[out]"
        )
    )

    command = [
        "ffmpeg",
        "-y",
    ]

    for item in inputs:

        command += [
            "-i",
            item,
        ]

    command += [
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[out]",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(output),
    ]

    result = run_command(
        command,
        timeout=120,
    )

    if (
        result.returncode != 0
    ):

        shutil.copy2(
            narration,
            output,
        )

    return output


# ============================================================
# AUDIO FINAL
# ============================================================

def attach_audio(
    video: Path,
    audio: Path,
    output: Path,
) -> Path:

    result = run_command(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video),
            "-i",
            str(audio),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            str(output),
        ],
        timeout=300,
    )

    if result.returncode != 0:

        raise RuntimeError(
            "Impossible d'ajouter "
            "l'audio : "
            + result.stderr[-1000:]
        )

    return output


# ============================================================
# MASCOTTE ANIMÉE
# ============================================================

def create_mascot_sequence(
    work_dir: Path,
) -> Path:

    expressions = [
        "normal",
        "talking",
        "thinking",
        "surprised",
        "amused",
        "talking",
    ]

    for index, expression in enumerate(
        expressions
    ):

        create_brain_mascot(
            work_dir
            / f"mascot_{index:02d}.png",
            expression,
        )

    # Le fichier texte contrôle les durées.
    concat_file = (
        work_dir
        / "mascot_concat.txt"
    )

    lines = []

    for index in range(
        len(expressions)
    ):

        image_path = (
            work_dir
            / f"mascot_{index:02d}.png"
        )

        lines.append(
            f"file '{image_path.resolve().as_posix()}'"
        )

        lines.append(
            "duration 1.25"
        )

    image_path = (
        work_dir
        / "mascot_05.png"
    )

    lines.append(
        f"file '{image_path.resolve().as_posix()}'"
    )

    concat_file.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    output = (
        work_dir
        / "mascot_animation.mov"
    )

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
            "-vf",
            "format=rgba,"
            "scale=165:-1,"
            "fps=12",
            "-an",
            "-c:v",
            "qtrle",
            str(output),
        ],
        timeout=120,
    )

    if result.returncode != 0:

        # Fallback : image animée simple.
        output = (
            work_dir
            / "mascot_fallback.png"
        )

        create_brain_mascot(
            output,
            "talking",
        )

    return output# ============================================================
# SOUS-TITRES + MASCOTTE
# ============================================================

def burn_subtitles_and_mascot(
    video: Path,
    ass: Path,
    mascot_video: Path,
    output: Path,
    vertical: bool,
) -> Path:

    ensure_ffmpeg()

    subtitle_path = (
        ffmpeg_escape_path(
            ass
        )
    )

    if vertical:

        width = 1080
        height = 1920

        mascot_width = 165

        # Les sous-titres sont à environ 275 px
        # du bas. La mascotte reste au-dessus.
        mascot_x = 32
        mascot_y = 1425

    else:

        width = 1920
        height = 1080

        mascot_width = 130
        mascot_x = 35
        mascot_y = 820

    # Mouvement vertical extrêmement léger.
    overlay_filter = (
        "[0:v]"
        f"ass='{subtitle_path}'"
        "[sub];"
        "[1:v]"
        f"scale={mascot_width}:-1,"
        "format=rgba,"
        "setpts=PTS-STARTPTS"
        "[mas];"
        "[sub][mas]"
        f"overlay="
        f"x={mascot_x}:"
        f"y='{mascot_y}+3*sin(t*2.2)':"
        "eof_action=repeat"
        "[v]"
    )

    result = run_command(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video),
            "-stream_loop",
            "-1",
            "-i",
            str(mascot_video),
            "-filter_complex",
            overlay_filter,
            "-map",
            "[v]",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            "-shortest",
            str(output),
        ],
        timeout=400,
    )

    if result.returncode != 0:

        # Fallback critique :
        # la vidéo doit quand même sortir avec
        # ses sous-titres même si la mascotte
        # animée pose problème sur une version FFmpeg.
        fallback = run_command(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(video),
                "-vf",
                (
                    f"ass='{subtitle_path}'"
                ),
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "copy",
                str(output),
            ],
            timeout=400,
        )

        if fallback.returncode != 0:

            raise RuntimeError(
                "Impossible d'incruster "
                "les sous-titres : "
                + fallback.stderr[-1200:]
            )

    return output


# ============================================================
# CONSTRUCTION COMPLÈTE
# ============================================================

def build_video(
    script: str,
    output_dir: Path,
    filename: str,
    vertical: bool = True,
) -> Path:

    ensure_ffmpeg()

    script = clean_ai_text(
        script
    )

    narration_text = (
        remove_visual_markers(
            script
        )
    )

    if not narration_text:

        raise RuntimeError(
            "Le script ne contient "
            "aucun texte narrable."
        )

    if vertical:

        width = 1080
        height = 1920

    else:

        width = 1920
        height = 1080

    voice = select_french_voice()

    narration = (
        output_dir
        / (
            f"{Path(filename).stem}"
            "_voice.mp3"
        )
    )

    synthesize_with_voice(
        narration_text,
        narration,
        voice,
    )

    duration = get_duration(
        narration
    )

    st.write(
        f"🎙️ Narration : "
        f"{duration:.1f}s"
    )

    boundaries = get_word_boundaries(
        narration_text,
        voice,
        duration,
    )

    st.write(
        f"📝 Sous-titres : "
        f"{len(boundaries)} mots synchronisés"
    )

    visual_plan = create_visual_plan(
        script,
        boundaries,
        duration,
        vertical,
        output_dir,
    )

    st.write(
        f"🖼️ Visuels : "
        f"{len(visual_plan)} plans"
    )

    scenes = []

    for index, (
        image_path,
        start,
        end,
    ) in enumerate(
        visual_plan
    ):

        scene_duration = max(
            0.7,
            end - start,
        )

        scene_path = (
            output_dir
            / f"scene_{index:02d}.mp4"
        )

        create_image_scene(
            image_path,
            scene_path,
            scene_duration,
            width,
            height,
            index,
        )

        scenes.append(
            scene_path
        )

    visual_video = (
        output_dir
        / (
            f"{Path(filename).stem}"
            "_visual.mp4"
        )
    )

    concat_scenes(
        scenes,
        visual_video,
    )

    # --------------------------------------------------------
    # PAS DE MUSIQUE
    # --------------------------------------------------------
    # Seulement des effets contextuels.
    # La voix reste toujours prioritaire.

    sfx_events = choose_sfx_events(
        script,
        boundaries,
        duration,
    )

    st.write(
        f"🔊 Effets sonores contextuels : "
        f"{len(sfx_events)}"
    )

    mixed_audio = (
        output_dir
        / (
            f"{Path(filename).stem}"
            "_audio.m4a"
        )
    )

    mix_audio_with_sfx(
        narration,
        sfx_events,
        output_dir,
        mixed_audio,
    )

    with_audio = (
        output_dir
        / (
            f"{Path(filename).stem}"
            "_audio_video.mp4"
        )
    )

    attach_audio(
        visual_video,
        mixed_audio,
        with_audio,
    )

    # --------------------------------------------------------
    # SOUS-TITRES
    # --------------------------------------------------------

    ass_path = (
        output_dir
        / (
            f"{Path(filename).stem}"
            ".ass"
        )
    )

    create_ass_subtitles(
        boundaries,
        ass_path,
        vertical,
    )

    # --------------------------------------------------------
    # MASCOTTE
    # --------------------------------------------------------

    mascot_video = (
        create_mascot_sequence(
            output_dir
        )
    )

    st.write(
        "🧠 Mascotte cerveau : "
        "animation activée"
    )

    final_path = (
        output_dir
        / filename
    )

    burn_subtitles_and_mascot(
        with_audio,
        ass_path,
        mascot_video,
        final_path,
        vertical,
    )

    if (
        not final_path.exists()
        or final_path.stat().st_size
        < 10_000
    ):

        raise RuntimeError(
            "La vidéo finale n'a pas "
            "été créée correctement."
        )

    return final_path


# ============================================================
# PROCESSUS
# ============================================================

def process_short(
    script: str,
    production_dir: Path,
    filename: str,
    label: str,
) -> Path:

    st.write(
        f"🎬 {label} : "
        f"{count_words(script)} mots"
    )

    return build_video(
        script,
        production_dir,
        filename,
        vertical=True,
    )


def process_long_video(
    script: str,
    production_dir: Path,
) -> Path:

    st.write(
        f"🎬 Vidéo longue : "
        f"{count_words(script)} mots"
    )

    return build_video(
        script,
        production_dir,
        "video_longue.mp4",
        vertical=False,
    )


def process_teaser(
    script: str,
    topic: str,
    production_dir: Path,
) -> Optional[Path]:

    try:

        teaser = generate_teaser(
            script,
            topic,
        )

        if not teaser:

            return None

        return build_video(
            teaser,
            production_dir,
            "teaser.mp4",
            vertical=True,
        )

    except Exception as exc:

        st.warning(
            f"Teaser non généré : "
            f"{exc}"
        )

        return None


# ============================================================
# WORKFLOW
# ============================================================

def run_generation(
    topic: str,
) -> Dict[
    str,
    List[Path],
]:

    topic = normalize_text(
        topic
    )

    if not topic:

        raise ValueError(
            "Veuillez saisir un sujet."
        )

    production_dir = (
        create_production_directory(
            topic
        )
    )

    st.info(
        "🧠 Création du script "
        "Cerveau Curieux..."
    )

    script = clean_ai_text(
        generate_main_script(
            topic
        )
    )

    word_count = count_words(
        script
    )

    st.success(
        f"Script généré : "
        f"{word_count} mots"
    )

    mode = choose_content_mode(
        word_count
    )

    # --------------------------------------------------------
    # SCRIPT TROP COURT
    # --------------------------------------------------------

    if mode == "regenerate":

        st.info(
            "Le script est très court. "
            "Adaptation intelligente en Short..."
        )

        try:

            script = clean_ai_text(
                regenerate_short_main_script(
                    topic
                )
            )

            word_count = count_words(
                script
            )

        except Exception as exc:

            st.warning(
                "L'adaptation IA "
                "a échoué. "
                f"Détail : {exc}"
            )

        mode = "one_short"

    results = {
        "shorts": [],
        "long": [],
        "teaser": [],
    }

    # --------------------------------------------------------
    # UN SHORT
    # --------------------------------------------------------

    if mode == "one_short":

        short_script = fit_short_script(
            script,
            topic,
        )

        short_path = process_short(
            short_script,
            production_dir,
            "short_1.mp4",
            "Short",
        )

        results[
            "shorts"
        ].append(
            short_path
        )

        return results

    # --------------------------------------------------------
    # DEUX SHORTS
    # --------------------------------------------------------

    if mode == "two_shorts":

        st.info(
            "✂️ Adaptation en deux Shorts..."
        )

        part1, part2 = (
            generate_two_shorts(
                script,
                topic,
            )
        )

        part1 = fit_short_script(
            part1,
            topic,
        )

        part2 = fit_short_script(
            part2,
            topic,
        )

        if not part1:

            part1 = script

        if not part2:

            part2 = part1

        short1 = process_short(
            part1,
            production_dir,
            "short_1.mp4",
            "Short 1",
        )

        results[
            "shorts"
        ].append(
            short1
        )

        short2 = process_short(
            part2,
            production_dir,
            "short_2.mp4",
            "Short 2",
        )

        results[
            "shorts"
        ].append(
            short2
        )

        return results

    # --------------------------------------------------------
    # VIDÉO LONGUE
    # --------------------------------------------------------

    long_video = process_long_video(
        script,
        production_dir,
    )

    results[
        "long"
    ].append(
        long_video
    )

    teaser = process_teaser(
        script,
        topic,
        production_dir,
    )

    if teaser:

        results[
            "teaser"
        ].append(
            teaser
        )

    return results


# ============================================================
# INTERFACE STREAMLIT
# ============================================================

st.set_page_config(
    page_title=APP_TITLE,
    page_icon="🧠",
    layout="centered",
)

refresh_secrets()

st.title(
    "🧠 Cerveau Curieux"
)

st.caption(
    "Psychologie, cerveau et comportement humain, "
    "expliqués de façon surprenante."
)

with st.expander(
    "⚙️ Configuration",
    expanded=False,
):

    st.write(
        "OpenRouter :",
        (
            "connecté"
            if OPENROUTER_API_KEY
            else "non connecté"
        ),
    )

    st.write(
        "Pexels :",
        (
            "connecté"
            if PEXELS_API_KEY
            else "non connecté"
        ),
    )

    st.write(
        "FFmpeg :",
        (
            "présent"
            if shutil.which(
                "ffmpeg"
            )
            else "absent"
        ),
    )

    st.write(
        "Musique de fond : "
        "désactivée"
    )

    st.write(
        "Effets sonores : "
        "contextuels uniquement"
    )

    st.write(
        "Sous-titres : "
        "phrase complète + mot actif"
    )

    st.write(
        "Mascotte : "
        "cerveau cartoon animé"
    )


st.subheader(
    "Sujet de la vidéo"
)

topic = st.text_area(
    "",
    placeholder=(
        "Exemple : Pourquoi notre cerveau "
        "remet-il certaines tâches à plus tard ?"
    ),
    height=110,
    label_visibility="collapsed",
)


if st.button(
    "🚀 Générer la vidéo",
    type="primary",
    use_container_width=True,
):

    try:

        with st.status(
            "🎬 Production en cours...",
            expanded=True,
        ) as status:

            results = run_generation(
                topic
            )

            status.update(
                label="✅ Vidéo terminée",
                state="complete",
                expanded=False,
            )

        st.success(
            "La production est terminée."
        )

        all_outputs = (
            results["shorts"]
            + results["long"]
            + results["teaser"]
        )

        for path in all_outputs:

            st.video(
                str(path)
            )

            with open(
                path,
                "rb",
            ) as file:

                st.download_button(
                    f"⬇️ Télécharger {path.name}",
                    data=file.read(),
                    file_name=path.name,
                    mime="video/mp4",
                    key=(
                        f"download_"
                        f"{path.name}_"
                        f"{path.stat().st_mtime_ns}"
                    ),
                    use_container_width=True,
                )

    except Exception as exc:

        st.error(
            "❌ La génération a échoué."
        )

        st.exception(
            exc
    )
