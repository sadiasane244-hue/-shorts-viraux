import os
import re
import json
import time
import math
import shutil
import asyncio
import subprocess
from pathlib import Path
from typing import List, Dict, Tuple, Optional

import requests
import streamlit as st
from PIL import Image, ImageDraw, ImageFont
import edge_tts


# ============================================================
# CONFIGURATION
# ============================================================

APP_TITLE = "Studio Vidéo IA"

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

OPENROUTER_MODEL = "meta-llama/llama-3.3-70b-instruct"

OPENROUTER_FALLBACK_MODELS = [
    "meta-llama/llama-3.3-70b-instruct",
    "google/gemini-2.0-flash-001",
]

PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"


# ============================================================
# SEUILS DE CONTENU
# ============================================================

REGENERATE_BELOW = 70

ONE_SHORT_MIN = 70
ONE_SHORT_MAX = 349

TWO_SHORTS_MIN = 350
TWO_SHORTS_MAX = 699

LONG_MIN = 700


# ============================================================
# PARAMÈTRES VIDÉO
# ============================================================

SHORT_TARGET_SECONDS = 45
SHORT_MIN_SECONDS = 25
SHORT_MAX_SECONDS = 60

SHORT_MIN_WORDS = 70
SHORT_MAX_WORDS = 150

LONG_MIN_SECONDS = 180

SHORT_WIDTH = 1080
SHORT_HEIGHT = 1920

LONG_WIDTH = 1920
LONG_HEIGHT = 1080

VIDEO_FPS = 30

VIDEO_CRF = 18
VIDEO_BITRATE = "8M"

AUDIO_BITRATE = "192k"


# ============================================================
# RÉPERTOIRES
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

OUTPUT_DIR = BASE_DIR / "outputs"
TEMP_DIR = BASE_DIR / "temp"

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

TEMP_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


# ============================================================
# SECRETS
# ============================================================

def get_secret(
    name: str,
    default: str = "",
) -> str:

    try:
        value = st.secrets.get(name)

        if value:
            return str(value)

    except Exception:
        pass

    return os.getenv(
        name,
        default,
    )


OPENROUTER_API_KEY = get_secret(
    "OPENROUTER_API_KEY"
)

PEXELS_API_KEY = get_secret(
    "PEXELS_API_KEY"
)


# ============================================================
# TEXTE
# ============================================================

def normalize_text(
    text: str,
) -> str:

    if not text:
        return ""

    text = str(text)

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


def count_words(
    text: str,
) -> int:

    text = normalize_text(
        text
    )

    if not text:
        return 0

    return len(
        re.findall(
            r"\b[\wÀ-ÿ'-]+\b",
            text,
        )
    )


def clean_ai_text(
    text: str,
) -> str:

    if not text:
        return ""

    text = str(text).strip()

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


def extract_json_object(
    text: str,
) -> Optional[dict]:

    if not text:
        return None

    text = text.strip()

    try:
        return json.loads(
            text
        )

    except Exception:
        pass

    match = re.search(
        r"\{.*\}",
        text,
        flags=re.S,
    )

    if match:

        try:
            return json.loads(
                match.group(0)
            )

        except Exception:
            return None

    return None


# ============================================================
# COMMANDES SYSTÈME
# ============================================================

def run_command(
    command: List[str],
    timeout: int = 300,
    cwd: Optional[str] = None,
) -> subprocess.CompletedProcess:

    return subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        cwd=cwd,
        check=False,
    )


def ensure_ffmpeg() -> None:

    if not shutil.which("ffmpeg"):

        raise RuntimeError(
            "FFmpeg est introuvable. "
            "Vérifiez que ffmpeg est présent "
            "dans packages.txt."
        )

    if not shutil.which("ffprobe"):

        raise RuntimeError(
            "FFprobe est introuvable. "
            "Vérifiez l'installation de FFmpeg."
        )


# ============================================================
# OPENROUTER
# ============================================================

def _extract_openrouter_error(
    response: requests.Response,
) -> str:

    try:

        data = response.json()

        if isinstance(
            data,
            dict,
        ):

            error = data.get(
                "error"
            )

            if isinstance(
                error,
                dict,
            ):

                message = error.get(
                    "message"
                )

                if message:
                    return str(
                        message
                    )

            message = data.get(
                "message"
            )

            if message:
                return str(
                    message
                )

    except Exception:
        pass

    text = response.text.strip()

    if text:
        return text[:500]

    return "Erreur inconnue."


def _get_retry_after(
    response: requests.Response,
) -> Optional[float]:

    value = response.headers.get(
        "Retry-After"
    )

    if not value:
        return None

    try:
        return float(value)

    except (
        ValueError,
        TypeError,
    ):
        return None


def openrouter_request(
    messages: List[Dict[str, str]],
    temperature: float = 0.7,
    max_tokens: int = 1800,
    timeout: int = 75,
    max_retries: int = 1,
) -> str:

    if not OPENROUTER_API_KEY:

        raise RuntimeError(
            "OPENROUTER_API_KEY est introuvable. "
            "Ajoutez-la dans les secrets Streamlit."
        )

    headers = {
        "Authorization": (
            f"Bearer {OPENROUTER_API_KEY}"
        ),
        "Content-Type": "application/json",
        "HTTP-Referer": (
            "https://github.com/"
            "sadiasane244-hue/-shorts-viraux"
        ),
        "X-Title": APP_TITLE,
    }

    models = list(
        dict.fromkeys(
            OPENROUTER_FALLBACK_MODELS
        )
    )

    payload = {
        "model": OPENROUTER_MODEL,
        "models": models,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "provider": {
            "allow_fallbacks": True,
        },
    }

    last_error = None

    total_attempts = max(
        1,
        int(max_retries) + 1,
    )

    for attempt in range(
        total_attempts
    ):

        if attempt > 0:

            wait_time = min(
                2 + attempt * 2,
                6,
            )

            time.sleep(
                wait_time
            )

        try:

            response = requests.post(
                OPENROUTER_URL,
                headers=headers,
                json=payload,
                timeout=timeout,
            )

        except requests.Timeout as exc:

            last_error = (
                "OpenRouter n'a pas répondu "
                f"dans le délai de {timeout} secondes."
            )

            if attempt + 1 >= total_attempts:

                raise RuntimeError(
                    last_error
                ) from exc

            continue

        except requests.RequestException as exc:

            last_error = (
                f"Erreur réseau OpenRouter : {exc}"
            )

            if attempt + 1 >= total_attempts:

                raise RuntimeError(
                    last_error
                ) from exc

            continue

        if response.status_code == 200:

            try:

                data = response.json()

            except Exception as exc:

                raise RuntimeError(
                    "OpenRouter a renvoyé "
                    "un JSON invalide."
                ) from exc

            try:

                content = (
                    data["choices"][0]
                    ["message"]["content"]
                )

            except (
                KeyError,
                IndexError,
                TypeError,
            ) as exc:

                raise RuntimeError(
                    "Réponse OpenRouter invalide : "
                    "contenu introuvable."
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

        if response.status_code == 429:

            error_message = (
                _extract_openrouter_error(
                    response
                )
            )

            retry_after = (
                _get_retry_after(
                    response
                )
            )

            if retry_after is not None:

                wait_time = min(
                    max(
                        retry_after,
                        1,
                    ),
                    8,
                )

            else:

                wait_time = min(
                    2 + attempt * 2,
                    6,
                )

            last_error = (
                "OpenRouter HTTP 429 : "
                f"{error_message}"
            )

            if attempt + 1 < total_attempts:

                time.sleep(
                    wait_time
                )

                continue

            raise RuntimeError(
                last_error
            )

        error_message = (
            _extract_openrouter_error(
                response
            )
        )

        last_error = (
            f"Erreur OpenRouter HTTP "
            f"{response.status_code} : "
            f"{error_message}"
        )

        if 400 <= response.status_code < 500:

            raise RuntimeError(
                last_error
            )

        if attempt + 1 < total_attempts:

            time.sleep(
                2
            )

            continue

        raise RuntimeError(
            last_error
        )

    raise RuntimeError(
        last_error
        or "Erreur inconnue OpenRouter."
    )


# ============================================================
# SCRIPT PRINCIPAL
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
Vous êtes le scénariste principal de la chaîne
YouTube « Cerveau Curieux ».

SUJET :
{topic}

La chaîne parle de psychologie, neurosciences
et comportement humain.

OBJECTIF :
Créer une vidéo qui donne envie de regarder
jusqu'à la dernière seconde.

STYLE :
- amusant
- surprenant
- intelligent
- accessible
- naturel
- dynamique
- parfois légèrement humoristique
- jamais scolaire ou académique
- jamais sensationnaliste

RÈGLES SCIENTIFIQUES ABSOLUES :
- ne rien inventer
- aucune étude inventée
- aucune statistique inventée
- aucun chercheur inventé
- aucune citation inventée
- ne pas transformer une hypothèse en certitude
- rester prudent lorsqu'un phénomène dépend du contexte

STRUCTURE :
1. HOOK très fort dès la première phrase.
2. Développement rapide.
3. Explication simple du phénomène.
4. Une ou plusieurs informations surprenantes.
5. Conclusion claire et mémorable.
6. Fin naturelle avec un appel à l'action.

Le début doit fonctionner dans les 3 premières secondes.

ÉVITER :
- « Bonjour et bienvenue »
- longues introductions
- remplissage
- répétitions
- phrases trop longues
- ton de professeur

VISUELS :

Ajoutez des indications visuelles précises sous la forme :

[VISUAL: description]

Chaque indication doit correspondre exactement
à l'idée racontée à ce moment précis.

Les descriptions doivent être concrètes et facilement
illustrables par une photo, une illustration ou une scène.

IMPORTANT :
Les visuels ne doivent pas simplement représenter
un mot isolé.

Ils doivent représenter l'idée racontée.

FIN :

La vidéo doit réellement se terminer.

Ne coupez jamais la narration en plein milieu
d'une phrase.

Préparez une conclusion courte permettant
d'ajouter naturellement le CTA :

« Abonne-toi pour en savoir plus sur ton cerveau. »

Retournez uniquement le script.
"""

    messages = [
        {
            "role": "system",
            "content": (
                "Vous êtes un scénariste scientifique "
                "spécialisé dans les contenus courts "
                "de psychologie et neurosciences. "
                "Vous n'inventez jamais de faits."
            ),
        },
        {
            "role": "user",
            "content": prompt,
        },
    ]

    return openrouter_request(
        messages=messages,
        temperature=0.68,
        max_tokens=2200,
        timeout=75,
        max_retries=1,
    )


# ============================================================
# MARQUEURS VISUELS
# ============================================================

IMAGE_MARKER_RE = re.compile(
    r"\[(?:IMAGE|VISUAL)\s*:\s*(.*?)\]",
    flags=re.I | re.S,
)


def extract_visual_markers(
    text: str,
) -> List[str]:

    if not text:
        return []

    markers = IMAGE_MARKER_RE.findall(
        text
    )

    cleaned = []

    for marker in markers:

        marker = normalize_text(
            marker
        )

        if marker:
            cleaned.append(
                marker
            )

    return cleaned


def remove_visual_markers(
    text: str,
) -> str:

    if not text:
        return ""

    text = IMAGE_MARKER_RE.sub(
        " ",
        text,
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


# ============================================================
# PEXELS
# ============================================================

def pexels_search(
    query: str,
    per_page: int = 10,
    orientation: str = "portrait",
) -> List[dict]:

    if not PEXELS_API_KEY:
        return []

    query = normalize_text(
        query
    )

    if not query:
        return []

    headers = {
        "Authorization": PEXELS_API_KEY,
    }

    params = {
        "query": query,
        "per_page": per_page,
        "orientation": orientation,
    }

    try:

        response = requests.get(
            PEXELS_SEARCH_URL,
            headers=headers,
            params=params,
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
    timeout: int = 30,
) -> bool:

    try:

        response = requests.get(
            url,
            timeout=timeout,
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
        ) as handle:

            for chunk in response.iter_content(
                chunk_size=1024 * 64
            ):

                if chunk:
                    handle.write(
                        chunk
                    )

        return destination.exists()

    except Exception:
        return False


# ============================================================
# VOIX
# ============================================================

FRENCH_VOICES = [
    "fr-FR-HenriNeural",
    "fr-FR-DeniseNeural",
]


def select_french_voice() -> str:

    return FRENCH_VOICES[0]


async def _edge_tts_save(
    text: str,
    output_path: Path,
    voice: str,
    rate: str,
) -> None:

    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=rate,
    )

    await communicate.save(
        str(output_path)
    )


def synthesize_with_voice(
    text: str,
    output_path: Path,
    voice: str,
    rate: str = "+2%",
) -> Path:

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:

        asyncio.run(
            _edge_tts_save(
                text,
                output_path,
                voice,
                rate,
            )
        )

    except RuntimeError:

        loop = asyncio.new_event_loop()

        try:

            asyncio.set_event_loop(
                loop
            )

            loop.run_until_complete(
                _edge_tts_save(
                    text,
                    output_path,
                    voice,
                    rate,
                )
            )

        finally:

            loop.close()

            asyncio.set_event_loop(
                None
            )

    if not output_path.exists():

        raise RuntimeError(
            "La narration audio "
            "n'a pas été créée."
        )

    return output_path


def get_audio_duration(
    audio_path: Path,
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
            str(audio_path),
        ],
        timeout=30,
    )

    if result.returncode != 0:

        raise RuntimeError(
            "Impossible de déterminer "
            "la durée audio : "
            + result.stderr[-500:]
        )

    try:

        duration = float(
            result.stdout.strip()
        )

    except ValueError as exc:

        raise RuntimeError(
            "Durée audio invalide."
        ) from exc

    if duration <= 0:

        raise RuntimeError(
            "La durée audio est nulle."
        )

    return duration


# ============================================================
# TIMINGS MOT PAR MOT
# ============================================================

def get_word_boundaries(
    text: str,
    audio_path: Path,
    voice: Optional[str] = None,
    rate: str = "+2%",
) -> List[Tuple[str, float, float]]:

    text = remove_visual_markers(
        text
    )

    text = normalize_text(
        text
    )

    if not text:
        return []

    if voice is None:
        voice = select_french_voice()

    words = re.findall(
        r"\S+",
        text,
    )

    if not words:
        return []

    boundaries = []

    async def _collect():

        communicate = edge_tts.Communicate(
            text=text,
            voice=voice,
            rate=rate,
        )

        async for event in communicate.stream():

            if event["type"] != "WordBoundary":
                continue

            offset = event.get(
                "offset",
                0,
            )

            duration = event.get(
                "duration",
                0,
            )

            start = (
                float(offset)
                / 10_000_000
            )

            event_duration = (
                float(duration)
                / 10_000_000
            )

            word = str(
                event.get(
                    "text",
                    "",
                )
            ).strip()

            if word:

                boundaries.append(
                    (
                        word,
                        start,
                        max(
                            0.03,
                            event_duration,
                        ),
                    )
                )

    try:

        asyncio.run(
            _collect()
        )

    except RuntimeError:

        loop = asyncio.new_event_loop()

        try:

            asyncio.set_event_loop(
                loop
            )

            loop.run_until_complete(
                _collect()
            )

        except Exception:

            boundaries = []

        finally:

            loop.close()

            asyncio.set_event_loop(
                None
            )

    except Exception:

        boundaries = []

    if boundaries:

        duration = get_audio_duration(
            audio_path
        )

        cleaned = []

        for index, item in enumerate(
            boundaries
        ):

            word, start, word_duration = item

            start = max(
                0.0,
                min(
                    start,
                    duration,
                ),
            )

            if index + 1 < len(
                boundaries
            ):

                next_start = boundaries[
                    index + 1
                ][1]

                end = min(
                    duration,
                    max(
                        start + 0.03,
                        next_start,
                    ),
                )

            else:

                end = min(
                    duration,
                    max(
                        start + word_duration,
                        start + 0.08,
                    ),
                )

            if end > start:

                cleaned.append(
                    (
                        word,
                        start,
                        end,
                    )
                )

        if cleaned:
            return cleaned

    # --------------------------------------------------------
    # FALLBACK
    # --------------------------------------------------------

    duration = get_audio_duration(
        audio_path
    )

    weights = []

    for word in words:

        clean_word = re.sub(
            r"[^\wÀ-ÿ'-]",
            "",
            word,
        )

        weights.append(
            max(
                1.0,
                len(clean_word) ** 0.7,
            )
        )

    total_weight = sum(
        weights
    )

    if total_weight <= 0:
        total_weight = float(
            len(words)
        )

    result = []

    current_time = 0.0

    for word, weight in zip(
        words,
        weights,
    ):

        word_duration = (
            duration
            * weight
            / total_weight
        )

        start = current_time

        end = min(
            duration,
            current_time
            + word_duration,
        )

        result.append(
            (
                word,
                start,
                end,
            )
        )

        current_time = end

    return result


# ============================================================
# FIN DE LA PARTIE 1
# ============================================================# ============================================================
# PARTIE 2/4
# VISUELS + MONTAGE + ANIMATION
# ============================================================


# ============================================================
# UTILITAIRES VIDÉO
# ============================================================

def ffmpeg_escape_path(
    path: Path,
) -> str:

    value = str(path)

    return (
        value
        .replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
    )


def get_video_duration(
    video_path: Path,
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
            str(video_path),
        ],
        timeout=30,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Impossible de lire la durée de la vidéo : "
            + result.stderr[-500:]
        )

    try:
        duration = float(
            result.stdout.strip()
        )
    except ValueError as exc:
        raise RuntimeError(
            "Durée vidéo invalide."
        ) from exc

    if duration <= 0:
        raise RuntimeError(
            "La durée de la vidéo est nulle."
        )

    return duration


def probe_video_stream(
    video_path: Path,
) -> Dict[str, object]:

    ensure_ffmpeg()

    result = run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,r_frame_rate",
            "-of",
            "json",
            str(video_path),
        ],
        timeout=30,
    )

    if result.returncode != 0:
        return {}

    try:
        data = json.loads(
            result.stdout
        )
    except Exception:
        return {}

    streams = data.get(
        "streams",
        [],
    )

    if not streams:
        return {}

    return streams[0]


# ============================================================
# DÉDUPLICATION DES VISUELS
# ============================================================

def visual_fingerprint(
    photo: dict,
) -> str:

    if not isinstance(
        photo,
        dict,
    ):
        return ""

    src = photo.get(
        "src",
        {},
    )

    if not isinstance(
        src,
        dict,
    ):
        return ""

    return str(
        src.get(
            "original",
            ""
        )
    ).strip()


def select_unique_photos(
    photos: List[dict],
    used_urls: set,
    limit: int = 5,
) -> List[dict]:

    selected = []

    for photo in photos:

        fingerprint = (
            visual_fingerprint(
                photo
            )
        )

        if not fingerprint:
            continue

        if fingerprint in used_urls:
            continue

        used_urls.add(
            fingerprint
        )

        selected.append(
            photo
        )

        if len(selected) >= limit:
            break

    return selected


# ============================================================
# RECHERCHE VISUELLE CONTEXTUELLE
# ============================================================

def build_visual_queries(
    description: str,
) -> List[str]:

    description = normalize_text(
        description
    )

    if not description:
        return []

    queries = [
        description,
    ]

    # Recherche plus concrète si la première
    # requête est trop abstraite.
    simplified = re.sub(
        r"[^\wÀ-ÿ\s'-]",
        " ",
        description,
    )

    simplified = re.sub(
        r"\s+",
        " ",
        simplified,
    ).strip()

    if simplified and simplified != description:
        queries.append(
            simplified
        )

    return list(
        dict.fromkeys(
            queries
        )
    )


def find_visual_for_scene(
    description: str,
    used_urls: set,
    portrait: bool = True,
) -> Optional[dict]:

    orientation = (
        "portrait"
        if portrait
        else "landscape"
    )

    queries = build_visual_queries(
        description
    )

    # Quelques mots génériques qui peuvent
    # améliorer les résultats Pexels lorsque
    # la description est trop abstraite.
    fallback_queries = []

    lower = description.lower()

    if any(
        word in lower
        for word in (
            "cerveau",
            "mémoire",
            "pensée",
            "penser",
            "neuroscience",
        )
    ):
        fallback_queries.extend(
            [
                "human brain neuroscience",
                "person thinking brain",
            ]
        )

    if any(
        word in lower
        for word in (
            "émotion",
            "peur",
            "joie",
            "stress",
            "anxiété",
        )
    ):
        fallback_queries.extend(
            [
                "human emotions",
                "person emotional reaction",
            ]
        )

    if any(
        word in lower
        for word in (
            "décision",
            "choix",
            "décider",
        )
    ):
        fallback_queries.extend(
            [
                "person making decision",
                "choices decision concept",
            ]
        )

    queries.extend(
        fallback_queries
    )

    queries = list(
        dict.fromkeys(
            queries
        )
    )

    for query in queries:

        photos = pexels_search(
            query=query,
            per_page=12,
            orientation=orientation,
        )

        selected = select_unique_photos(
            photos,
            used_urls,
            limit=1,
        )

        if selected:
            return selected[0]

    return None


def get_best_photo_url(
    photo: dict,
    portrait: bool = True,
) -> Optional[str]:

    src = photo.get(
        "src",
        {},
    )

    if not isinstance(
        src,
        dict,
    ):
        return None

    if portrait:

        candidates = [
            src.get("large2x"),
            src.get("large"),
            src.get("medium"),
            src.get("original"),
        ]

    else:

        candidates = [
            src.get("large2x"),
            src.get("large"),
            src.get("medium"),
            src.get("original"),
        ]

    for url in candidates:

        if url:
            return str(
                url
            )

    return None


# ============================================================
# EXTRACTION DES SCÈNES
# ============================================================

def split_script_into_scene_blocks(
    script: str,
) -> List[Dict[str, str]]:

    script = normalize_text(
        script
    )

    if not script:
        return []

    pattern = re.compile(
        r"\[VISUAL\s*:\s*(.*?)\]",
        flags=re.I | re.S,
    )

    matches = list(
        pattern.finditer(
            script
        )
    )

    if not matches:

        sentences = re.split(
            r"(?<=[.!?])\s+",
            script,
        )

        sentences = [
            normalize_text(
                sentence
            )
            for sentence in sentences
            if normalize_text(sentence)
        ]

        return [
            {
                "text": sentence,
                "visual": sentence,
            }
            for sentence in sentences
        ]

    blocks = []

    prefix = script[
        :matches[0].start()
    ].strip()

    if prefix:

        blocks.append(
            {
                "text": prefix,
                "visual": prefix,
            }
        )

    for index, match in enumerate(
        matches
    ):

        visual = normalize_text(
            match.group(1)
        )

        start = match.end()

        if index + 1 < len(matches):
            end = matches[
                index + 1
            ].start()
        else:
            end = len(script)

        narration = normalize_text(
            script[start:end]
        )

        if narration:

            blocks.append(
                {
                    "text": narration,
                    "visual": visual or narration,
                }
            )

    return blocks


def split_long_scene(
    text: str,
    max_words: int = 28,
) -> List[str]:

    text = normalize_text(
        text
    )

    if not text:
        return []

    words = text.split()

    if len(words) <= max_words:
        return [text]

    parts = []

    current = []

    for word in words:

        current.append(
            word
        )

        if (
            len(current)
            >= max_words
        ):

            parts.append(
                " ".join(current)
            )

            current = []

    if current:
        parts.append(
            " ".join(current)
        )

    return parts


def prepare_scene_blocks(
    script: str,
) -> List[Dict[str, str]]:

    blocks = split_script_into_scene_blocks(
        script
    )

    prepared = []

    for block in blocks:

        text = normalize_text(
            block.get(
                "text",
                ""
            )
        )

        visual = normalize_text(
            block.get(
                "visual",
                ""
            )
        )

        if not text:
            continue

        parts = split_long_scene(
            text,
            max_words=28,
        )

        for part in parts:

            prepared.append(
                {
                    "text": part,
                    "visual": visual or part,
                }
            )

    return prepared


# ============================================================
# SYNCHRONISATION SCÈNES / NARRATION
# ============================================================

def estimate_scene_boundaries(
    blocks: List[Dict[str, str]],
    word_boundaries: List[
        Tuple[str, float, float]
    ],
    total_duration: float,
) -> List[Dict[str, object]]:

    if not blocks:
        return []

    if not word_boundaries:

        weights = [
            max(
                1,
                count_words(
                    block["text"]
                ),
            )
            for block in blocks
        ]

        total_weight = sum(
            weights
        )

        if total_weight <= 0:
            total_weight = len(
                blocks
            )

        result = []

        current = 0.0

        for block, weight in zip(
            blocks,
            weights,
        ):

            duration = (
                total_duration
                * weight
                / total_weight
            )

            end = min(
                total_duration,
                current + duration,
            )

            result.append(
                {
                    "text": block["text"],
                    "visual": block["visual"],
                    "start": current,
                    "end": end,
                }
            )

            current = end

        if result:
            result[-1]["end"] = total_duration

        return result

    # --------------------------------------------------------
    # Nous associons chaque bloc à des mots de la narration.
    # --------------------------------------------------------

    all_words = [
        re.sub(
            r"[^\wÀ-ÿ'-]",
            "",
            word.lower(),
        )
        for word, _, _ in word_boundaries
    ]

    result = []

    cursor = 0

    for block in blocks:

        target_words = re.findall(
            r"\b[\wÀ-ÿ'-]+\b",
            block["text"].lower(),
        )

        target_words = [
            re.sub(
                r"[^\wÀ-ÿ'-]",
                "",
                word,
            )
            for word in target_words
        ]

        target_words = [
            word
            for word in target_words
            if word
        ]

        if not target_words:
            continue

        start_index = cursor

        # Cherche les mots du bloc dans les
        # frontières TTS, avec tolérance.
        matched = 0

        while (
            cursor < len(all_words)
            and matched
            < len(target_words)
        ):

            current_word = all_words[
                cursor
            ]

            expected_word = target_words[
                matched
            ]

            if (
                current_word
                == expected_word
                or expected_word
                in current_word
                or current_word
                in expected_word
            ):

                matched += 1

            cursor += 1

        end_index = max(
            start_index,
            cursor - 1,
        )

        if (
            start_index
            < len(word_boundaries)
        ):

            start = word_boundaries[
                start_index
            ][1]

        else:

            start = (
                result[-1]["end"]
                if result
                else 0.0
            )

        if (
            end_index
            < len(word_boundaries)
        ):

            end = word_boundaries[
                end_index
            ][2]

        else:

            end = total_duration

        if result:

            start = max(
                start,
                float(
                    result[-1]["end"]
                ),
            )

        end = max(
            start + 0.05,
            end,
        )

        end = min(
            end,
            total_duration,
        )

        result.append(
            {
                "text": block["text"],
                "visual": block["visual"],
                "start": start,
                "end": end,
            }
        )

    # --------------------------------------------------------
    # Si le matching est imparfait, nous évitons
    # de perdre la fin de la narration.
    # --------------------------------------------------------

    if result:

        result[-1]["end"] = total_duration

    return result


# ============================================================
# TÉLÉCHARGEMENT DES VISUELS
# ============================================================

def download_scene_visuals(
    scenes: List[Dict[str, object]],
    work_dir: Path,
    portrait: bool = True,
) -> List[Dict[str, object]]:

    work_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    used_urls = set()

    result = []

    for index, scene in enumerate(
        scenes
    ):

        description = str(
            scene.get(
                "visual",
                scene.get(
                    "text",
                    ""
                ),
            )
        )

        photo = find_visual_for_scene(
            description=description,
            used_urls=used_urls,
            portrait=portrait,
        )

        if photo is None:

            # On conserve la scène même sans
            # visuel Pexels afin que le pipeline
            # puisse décider d'un fallback.
            continue

        url = get_best_photo_url(
            photo,
            portrait=portrait,
        )

        if not url:
            continue

        extension = ".jpg"

        destination = (
            work_dir
            / f"visual_{index:03d}{extension}"
        )

        if not download_file(
            url,
            destination,
            timeout=30,
        ):
            continue

        if not destination.exists():
            continue

        scene_copy = dict(
            scene
        )

        scene_copy[
            "visual_path"
        ] = destination

        scene_copy[
            "photo_url"
        ] = url

        result.append(
            scene_copy
        )

    return result


# ============================================================
# FALLBACK VISUEL
# ============================================================

def create_fallback_visual(
    output_path: Path,
    width: int = 1080,
    height: int = 1920,
) -> Path:

    image = Image.new(
        "RGB",
        (
            width,
            height,
        ),
        (
            22,
            24,
            35,
        ),
    )

    draw = ImageDraw.Draw(
        image
    )

    # Forme simple et neutre.
    # Elle sert uniquement de fallback
    # lorsqu'aucun visuel externe n'est disponible.

    margin = int(
        width * 0.10
    )

    box = (
        margin,
        int(height * 0.25),
        width - margin,
        int(height * 0.75),
    )

    draw.rounded_rectangle(
        box,
        radius=40,
        outline=(
            90,
            96,
            120,
        ),
        width=6,
    )

    try:

        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/"
            "DejaVuSans-Bold.ttf",
            70,
        )

    except Exception:

        font = ImageFont.load_default()

    text = "Cerveau Curieux"

    bbox = draw.textbbox(
        (0, 0),
        text,
        font=font,
    )

    text_width = (
        bbox[2] - bbox[0]
    )

    text_height = (
        bbox[3] - bbox[1]
    )

    draw.text(
        (
            (width - text_width) / 2,
            (height - text_height) / 2,
        ),
        text,
        font=font,
        fill=(
            245,
            245,
            250,
        ),
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    image.save(
        output_path,
        quality=95,
    )

    return output_path


# ============================================================
# ANIMATION LÉGÈRE DES IMAGES
# ============================================================

def create_image_scene(
    image_path: Path,
    output_path: Path,
    duration: float,
    width: int = SHORT_WIDTH,
    height: int = SHORT_HEIGHT,
    motion_index: int = 0,
) -> Path:

    ensure_ffmpeg()

    duration = max(
        0.15,
        float(duration),
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # Pas de zoompan.
    #
    # On utilise une image surdimensionnée puis
    # un recadrage animé léger. Cela évite le coût
    # extrêmement élevé rencontré précédemment.
    # --------------------------------------------------------

    source_width = width
    source_height = height

    scale_filter = (
        f"scale={source_width}:"
        f"{source_height}:"
        "force_original_aspect_ratio=increase,"
        f"crop={source_width}:"
        f"{source_height}"
    )

    # Amplitude très faible pour que le mouvement
    # reste naturel et ne détourne pas l'attention.
    amplitude = 0.018

    phase = motion_index % 4

    if phase == 0:

        crop_x = (
            f"(iw-{width})/2"
            f"+(iw-{width})*{amplitude}"
            f"*sin(2*PI*t/{max(duration, 1.0):.4f})"
        )

        crop_y = (
            f"(ih-{height})/2"
        )

    elif phase == 1:

        crop_x = (
            f"(iw-{width})/2"
        )

        crop_y = (
            f"(ih-{height})/2"
            f"+(ih-{height})*{amplitude}"
            f"*sin(2*PI*t/{max(duration, 1.0):.4f})"
        )

    elif phase == 2:

        crop_x = (
            f"(iw-{width})/2"
            f"+(iw-{width})*{amplitude}"
            f"*cos(2*PI*t/{max(duration, 1.0):.4f})"
        )

        crop_y = (
            f"(ih-{height})/2"
        )

    else:

        crop_x = (
            f"(iw-{width})/2"
        )

        crop_y = (
            f"(ih-{height})/2"
            f"+(ih-{height})*{amplitude}"
            f"*cos(2*PI*t/{max(duration, 1.0):.4f})"
        )

    # --------------------------------------------------------
    # Pour réellement obtenir une zone de déplacement,
    # l'image source est légèrement agrandie.
    # --------------------------------------------------------

    motion_scale = 1.035

    vf = (
        f"scale="
        f"{int(width * motion_scale)}:"
        f"{int(height * motion_scale)}:"
        "force_original_aspect_ratio=decrease,"
        f"pad={int(width * motion_scale)}:"
        f"{int(height * motion_scale)}:"
        f"(ow-iw)/2:"
        f"(oh-ih)/2,"
        f"crop={width}:{height}:"
        f"{crop_x}:{crop_y},"
        "setsar=1"
    )

    command = [
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
        str(VIDEO_FPS),
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        str(VIDEO_CRF),
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    result = run_command(
        command,
        timeout=120,
    )

    if result.returncode != 0:

        raise RuntimeError(
            "Erreur FFmpeg pendant "
            "la création d'un plan :\n"
            + result.stderr[-1500:]
        )

    if not output_path.exists():

        raise RuntimeError(
            "Le plan vidéo n'a pas été créé."
        )

    return output_path


# ============================================================
# CRÉATION DES PLANS
# ============================================================

def create_scene_clips(
    scenes: List[Dict[str, object]],
    work_dir: Path,
    width: int = SHORT_WIDTH,
    height: int = SHORT_HEIGHT,
) -> List[Path]:

    clips = []

    for index, scene in enumerate(
        scenes
    ):

        visual_path = scene.get(
            "visual_path"
        )

        if not visual_path:
            continue

        visual_path = Path(
            visual_path
        )

        duration = float(
            scene.get(
                "end",
                0,
            )
        ) - float(
            scene.get(
                "start",
                0,
            )
        )

        if duration <= 0:
            continue

        clip_path = (
            work_dir
            / f"scene_{index:03d}.mp4"
        )

        create_image_scene(
            image_path=visual_path,
            output_path=clip_path,
            duration=duration,
            width=width,
            height=height,
            motion_index=index,
        )

        clips.append(
            clip_path
        )

    return clips


# ============================================================
# CONCATÉNATION
# ============================================================

def concat_video_clips(
    clips: List[Path],
    output_path: Path,
) -> Path:

    ensure_ffmpeg()

    if not clips:

        raise RuntimeError(
            "Aucun plan vidéo disponible."
        )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    list_file = (
        output_path.parent
        / "concat_list.txt"
    )

    with open(
        list_file,
        "w",
        encoding="utf-8",
    ) as handle:

        for clip in clips:

            path = str(
                clip.resolve()
            )

            path = path.replace(
                "'",
                "'\\''",
            )

            handle.write(
                f"file '{path}'\n"
            )

    command = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    result = run_command(
        command,
        timeout=120,
    )

    if result.returncode != 0:

        raise RuntimeError(
            "Erreur lors de la concaténation :\n"
            + result.stderr[-1500:]
        )

    if not output_path.exists():

        raise RuntimeError(
            "La vidéo concaténée n'a pas été créée."
        )

    return output_path


# ============================================================
# AUDIO SUR LA VIDÉO
# ============================================================

def mux_narration(
    video_path: Path,
    audio_path: Path,
    output_path: Path,
) -> Path:

    ensure_ffmpeg()

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(audio_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        AUDIO_BITRATE,
        "-shortest",
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    result = run_command(
        command,
        timeout=120,
    )

    if result.returncode != 0:

        raise RuntimeError(
            "Erreur lors de l'ajout de la narration :\n"
            + result.stderr[-1500:]
        )

    if not output_path.exists():

        raise RuntimeError(
            "La vidéo avec narration "
            "n'a pas été créée."
        )

    return output_path


# ============================================================
# AUDIO NORMALISATION
# ============================================================

def normalize_audio(
    audio_path: Path,
    output_path: Path,
) -> Path:

    ensure_ffmpeg()

    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(audio_path),
        "-af",
        (
            "loudnorm="
            "I=-16:"
            "TP=-1.5:"
            "LRA=11"
        ),
        "-c:a",
        "aac",
        "-b:a",
        AUDIO_BITRATE,
        str(output_path),
    ]

    result = run_command(
        command,
        timeout=120,
    )

    if result.returncode != 0:

        # Si la normalisation échoue, on conserve
        # l'audio original plutôt que de bloquer
        # toute la génération.
        shutil.copy2(
            audio_path,
            output_path,
        )

    return output_path


# ============================================================
# FIN DE LA PARTIE 2
# ============================================================# ============================================================
# PARTIE 3/4 — SOUS-TITRES + MASCOTTE + SFX
# ============================================================


# ============================================================
# SOUS-TITRES MOT PAR MOT
# ============================================================

def clean_subtitle_word(word: str) -> str:
    """
    Nettoie un mot avant de l'envoyer à FFmpeg drawtext.
    Aucun code ASS ou balise de couleur ne doit pouvoir apparaître.
    """

    if not word:
        return ""

    word = str(word)

    # Suppression des éventuelles balises ASS
    word = re.sub(
        r"\\(?:c|1c|2c|3c|4c|alpha|k|K|kf|ko|t)\b[^}]*",
        "",
        word,
        flags=re.IGNORECASE,
    )

    word = re.sub(
        r"\{[^}]*\}",
        "",
        word,
    )

    # Suppression des codes hexadécimaux accidentels
    word = re.sub(
        r"&H[0-9A-Fa-f]+&?",
        "",
        word,
    )

    word = word.replace(
        "\\c",
        "",
    )

    word = word.replace(
        "\\N",
        " ",
    )

    word = word.replace(
        "\\n",
        " ",
    )

    word = word.strip()

    return word


def subtitle_safe_word(word: str) -> str:
    """
    Échappement FFmpeg drawtext.
    """

    word = clean_subtitle_word(word)

    if not word:
        return ""

    # drawtext utilise ':' comme séparateur
    word = word.replace(
        "\\",
        "\\\\",
    )

    word = word.replace(
        ":",
        "\\:",
    )

    word = word.replace(
        "'",
        "\\'",
    )

    word = word.replace(
        "%",
        "\\%",
    )

    word = word.replace(
        "[",
        "\\[",
    )

    word = word.replace(
        "]",
        "\\]",
    )

    return word


def find_subtitle_font():
    """
    Recherche une police lisible disponible sur Streamlit Cloud.
    """

    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]

    for font in candidates:
        if os.path.exists(font):
            return font

    return None


def build_word_subtitle_filter(
    boundaries,
    video_width=1080,
    video_height=1920,
):
    """
    Crée un filtre FFmpeg drawtext avec UN SEUL MOT À LA FOIS.

    Important :
    - aucun ASS
    - aucune balise de couleur
    - aucun karaoke
    - aucun texte empilé
    - le mot disparaît lorsqu'il n'est plus prononcé
    """

    font_path = find_subtitle_font()

    filters = []

    # Taille adaptée au format vertical
    font_size = max(
        42,
        min(
            72,
            int(video_width * 0.055),
        ),
    )

    # Position basse mais suffisamment haute pour
    # ne pas être collée au bord.
    y_position = int(
        video_height * 0.82
    )

    for item in boundaries:

        if not isinstance(item, dict):
            continue

        word = item.get(
            "word",
            "",
        )

        start = float(
            item.get(
                "start",
                0,
            )
        )

        end = float(
            item.get(
                "end",
                start + 0.1,
            )
        )

        if end <= start:
            continue

        safe_word = subtitle_safe_word(
            word
        )

        if not safe_word:
            continue

        # Chaque événement possède sa propre fenêtre temporelle.
        # Un seul mot peut donc être visible simultanément.
        enable = (
            f"between(t,{start:.3f},{end:.3f})"
        )

        if font_path:

            escaped_font = (
                font_path
                .replace(
                    "\\",
                    "\\\\",
                )
                .replace(
                    ":",
                    "\\:",
                )
            )

            drawtext = (
                "drawtext="
                f"fontfile='{escaped_font}':"
                f"text='{safe_word}':"
                f"fontsize={font_size}:"
                "fontcolor=white:"
                "borderw=5:"
                "bordercolor=black:"
                "shadowx=2:"
                "shadowy=2:"
                f"x=(w-text_w)/2:"
                f"y={y_position}:"
                f"enable='{enable}'"
            )

        else:

            drawtext = (
                "drawtext="
                f"text='{safe_word}':"
                f"fontsize={font_size}:"
                "fontcolor=white:"
                "borderw=5:"
                "bordercolor=black:"
                "shadowx=2:"
                "shadowy=2:"
                f"x=(w-text_w)/2:"
                f"y={y_position}:"
                f"enable='{enable}'"
            )

        filters.append(
            drawtext
        )

    return ",".join(
        filters
    )


def burn_word_by_word_subtitles(
    input_video,
    output_video,
    boundaries,
    video_duration,
):
    """
    Incruste définitivement les sous-titres mot par mot.

    Cette fonction remplace complètement l'ancien système ASS.
    """

    if not boundaries:
        shutil.copy2(
            input_video,
            output_video,
        )
        return output_video

    width, height = get_video_dimensions(
        input_video
    )

    subtitle_filter = build_word_subtitle_filter(
        boundaries,
        video_width=width,
        video_height=height,
    )

    if not subtitle_filter:
        shutil.copy2(
            input_video,
            output_video,
        )
        return output_video

    command = [
        FFMPEG_BIN,
        "-y",
        "-i",
        input_video,
        "-vf",
        subtitle_filter,
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
        "-movflags",
        "+faststart",
        output_video,
    ]

    run_command(
        command,
        timeout=180,
    )

    if not os.path.exists(output_video):
        raise RuntimeError(
            "La vidéo avec sous-titres n'a pas été créée."
        )

    return output_video


# ============================================================
# MASCOTTE CERVEAU
# ============================================================

def create_brain_mascot(
    output_path,
    state="normal",
    size=420,
):
    """
    Génère une mascotte cerveau avec Pillow.

    États :
    - normal
    - talking
    - thinking
    - surprised
    - amused
    - conclusion

    La mascotte est volontairement simple et reconnaissable.
    """

    image = Image.new(
        "RGBA",
        (size, size),
        (0, 0, 0, 0),
    )

    draw = ImageDraw.Draw(
        image
    )

    # --------------------------------------------------------
    # Corps principal du cerveau
    # --------------------------------------------------------

    margin = int(
        size * 0.12
    )

    brain_box = (
        margin,
        margin,
        size - margin,
        int(size * 0.73),
    )

    # Ombre
    shadow_offset = int(
        size * 0.025
    )

    shadow_box = (
        brain_box[0] + shadow_offset,
        brain_box[1] + shadow_offset,
        brain_box[2] + shadow_offset,
        brain_box[3] + shadow_offset,
    )

    draw.rounded_rectangle(
        shadow_box,
        radius=int(size * 0.18),
        fill=(25, 20, 55, 120),
    )

    # Cerveau
    draw.rounded_rectangle(
        brain_box,
        radius=int(size * 0.18),
        fill=(116, 88, 220, 255),
        outline=(55, 38, 120, 255),
        width=max(
            4,
            int(size * 0.018),
        ),
    )

    # --------------------------------------------------------
    # Sillons du cerveau
    # --------------------------------------------------------

    line_width = max(
        3,
        int(size * 0.014),
    )

    brain_left = brain_box[0]
    brain_top = brain_box[1]
    brain_right = brain_box[2]
    brain_bottom = brain_box[3]

    # Partie gauche
    left_x = int(
        size * 0.36
    )

    draw.arc(
        (
            brain_left + 20,
            brain_top + 45,
            left_x + 35,
            brain_bottom - 25,
        ),
        70,
        285,
        fill=(75, 55, 160, 255),
        width=line_width,
    )

    draw.arc(
        (
            brain_left + 40,
            brain_top + 20,
            left_x + 55,
            brain_bottom - 60,
        ),
        90,
        280,
        fill=(75, 55, 160, 255),
        width=line_width,
    )

    # Partie droite
    right_x = int(
        size * 0.64
    )

    draw.arc(
        (
            right_x - 50,
            brain_top + 35,
            brain_right - 20,
            brain_bottom - 20,
        ),
        255,
        110,
        fill=(75, 55, 160, 255),
        width=line_width,
    )

    draw.arc(
        (
            right_x - 65,
            brain_top + 70,
            brain_right - 35,
            brain_bottom - 55,
        ),
        250,
        105,
        fill=(75, 55, 160, 255),
        width=line_width,
    )

    # Ligne centrale
    draw.line(
        (
            size // 2,
            int(size * 0.18),
            size // 2,
            int(size * 0.65),
        ),
        fill=(75, 55, 160, 255),
        width=line_width,
    )

    # --------------------------------------------------------
    # Visage
    # --------------------------------------------------------

    eye_y = int(
        size * 0.45
    )

    eye_x1 = int(
        size * 0.39
    )

    eye_x2 = int(
        size * 0.61
    )

    eye_radius = int(
        size * 0.035
    )

    # Yeux
    draw.ellipse(
        (
            eye_x1 - eye_radius,
            eye_y - eye_radius,
            eye_x1 + eye_radius,
            eye_y + eye_radius,
        ),
        fill="white",
    )

    draw.ellipse(
        (
            eye_x2 - eye_radius,
            eye_y - eye_radius,
            eye_x2 + eye_radius,
            eye_y + eye_radius,
        ),
        fill="white",
    )

    # --------------------------------------------------------
    # Expressions
    # --------------------------------------------------------

    mouth_y = int(
        size * 0.59
    )

    mouth_width = int(
        size * 0.18
    )

    # Normal
    if state == "normal":

        draw.arc(
            (
                size // 2 - mouth_width,
                mouth_y - 5,
                size // 2 + mouth_width,
                mouth_y + 35,
            ),
            10,
            170,
            fill="white",
            width=line_width,
        )

    # Talking
    elif state == "talking":

        draw.ellipse(
            (
                size // 2 - int(size * 0.06),
                mouth_y - int(size * 0.01),
                size // 2 + int(size * 0.06),
                mouth_y + int(size * 0.07),
            ),
            fill=(35, 25, 80, 255),
        )

    # Thinking
    elif state == "thinking":

        draw.arc(
            (
                size // 2 - mouth_width,
                mouth_y,
                size // 2 + mouth_width,
                mouth_y + 25,
            ),
            180,
            350,
            fill="white",
            width=line_width,
        )

        # Petite bulle de réflexion
        bubble_x = int(
            size * 0.79
        )

        bubble_y = int(
            size * 0.23
        )

        r1 = int(
            size * 0.035
        )

        r2 = int(
            size * 0.06
        )

        draw.ellipse(
            (
                bubble_x,
                bubble_y,
                bubble_x + r1 * 2,
                bubble_y + r1 * 2,
            ),
            fill="white",
        )

        draw.ellipse(
            (
                bubble_x + 25,
                bubble_y - 35,
                bubble_x + 25 + r2 * 2,
                bubble_y - 35 + r2 * 2,
            ),
            fill="white",
        )

    # Surpris
    elif state == "surprised":

        # Sourcils
        draw.arc(
            (
                eye_x1 - 35,
                eye_y - 45,
                eye_x1 + 25,
                eye_y - 10,
            ),
            180,
            345,
            fill="white",
            width=line_width,
        )

        draw.arc(
            (
                eye_x2 - 25,
                eye_y - 45,
                eye_x2 + 35,
                eye_y - 10,
            ),
            195,
            0,
            fill="white",
            width=line_width,
        )

        # Bouche ouverte
        draw.ellipse(
            (
                size // 2 - int(size * 0.055),
                mouth_y - 5,
                size // 2 + int(size * 0.055),
                mouth_y + int(size * 0.09),
            ),
            fill=(35, 25, 80, 255),
        )

    # Amusé
    elif state == "amused":

        draw.arc(
            (
                size // 2 - mouth_width,
                mouth_y - 5,
                size // 2 + mouth_width,
                mouth_y + 40,
            ),
            0,
            180,
            fill="white",
            width=line_width,
        )

    # Conclusion
    elif state == "conclusion":

        draw.arc(
            (
                size // 2 - mouth_width,
                mouth_y - 8,
                size // 2 + mouth_width,
                mouth_y + 40,
            ),
            0,
            180,
            fill="white",
            width=line_width,
        )

    # --------------------------------------------------------
    # Petits bras
    # --------------------------------------------------------

    arm_y = int(
        size * 0.68
    )

    arm_width = max(
        5,
        int(size * 0.025),
    )

    draw.line(
        (
            int(size * 0.12),
            arm_y,
            int(size * 0.03),
            arm_y - int(size * 0.07),
        ),
        fill=(116, 88, 220, 255),
        width=arm_width,
    )

    draw.line(
        (
            int(size * 0.88),
            arm_y,
            int(size * 0.97),
            arm_y - int(size * 0.07),
        ),
        fill=(116, 88, 220, 255),
        width=arm_width,
    )

    # --------------------------------------------------------
    # Pieds
    # --------------------------------------------------------

    foot_y = int(
        size * 0.78
    )

    draw.line(
        (
            int(size * 0.37),
            foot_y,
            int(size * 0.32),
            int(size * 0.90),
        ),
        fill=(116, 88, 220, 255),
        width=arm_width,
    )

    draw.line(
        (
            int(size * 0.63),
            foot_y,
            int(size * 0.68),
            int(size * 0.90),
        ),
        fill=(116, 88, 220, 255),
        width=arm_width,
    )

    # --------------------------------------------------------
    # Export
    # --------------------------------------------------------

    image.save(
        output_path,
        "PNG",
    )

    return output_path


def choose_mascot_state(
    index,
    total,
    scene_text="",
):
    """
    Choisit une expression en fonction du contexte.

    L'objectif est d'éviter une mascotte totalement statique.
    """

    text = scene_text.lower()

    if index == 0:
        return "normal"

    if any(
        keyword in text
        for keyword in [
            "surpr",
            "incroyable",
            "impossible",
            "vraiment",
            "pourquoi",
            "mais",
        ]
    ):
        return "surprised"

    if any(
        keyword in text
        for keyword in [
            "penser",
            "réfléch",
            "cerveau",
            "question",
            "imagine",
        ]
    ):
        return "thinking"

    if any(
        keyword in text
        for keyword in [
            "drôle",
            "amus",
            "fun",
            "marrant",
            "rire",
        ]
    ):
        return "amused"

    if index >= total - 1:
        return "conclusion"

    # Alterner légèrement pour éviter une mascotte
    # identique sur toute la vidéo.
    states = [
        "talking",
        "normal",
        "thinking",
        "talking",
    ]

    return states[
        index % len(states)
    ]


def create_mascot_overlay(
    input_video,
    output_video,
    boundaries,
    video_duration,
):
    """
    Ajoute la mascotte cerveau en bas de l'image.

    CORRECTION IMPORTANTE :
    Le flux [base] est maintenant explicitement créé avant
    le premier overlay.

    La mascotte reste au-dessus de la vidéo mais suffisamment
    haute pour ne pas masquer les sous-titres.
    """

    width, height = get_video_dimensions(
        input_video
    )

    workdir = tempfile.mkdtemp(
        prefix="mascot_"
    )

    mascot_files = []

    try:

        # ----------------------------------------------------
        # Découpage approximatif des scènes à partir
        # des changements de contenu.
        # ----------------------------------------------------

        scene_ranges = []

        if boundaries:

            # On crée plusieurs segments d'expression.
            # Maximum 8 changements pour éviter un filtre
            # FFmpeg excessivement lourd.
            max_states = min(
                8,
                max(
                    1,
                    len(boundaries) // 8,
                ),
            )

            step = (
                video_duration
                / max_states
            )

            current = 0.0

            for i in range(max_states):

                start = current
                end = min(
                    video_duration,
                    current + step,
                )

                scene_ranges.append(
                    (
                        start,
                        end,
                    )
                )

                current = end

        if not scene_ranges:

            scene_ranges = [
                (
                    0.0,
                    video_duration,
                )
            ]

        # ----------------------------------------------------
        # Création des mascottes
        # ----------------------------------------------------

        total = len(
            scene_ranges
        )

        for index, (start, end) in enumerate(
            scene_ranges
        ):

            state = choose_mascot_state(
                index,
                total,
                "",
            )

            mascot_path = os.path.join(
                workdir,
                f"mascot_{index:02d}.png",
            )

            create_brain_mascot(
                mascot_path,
                state=state,
                size=420,
            )

            mascot_files.append(
                (
                    mascot_path,
                    start,
                    end,
                )
            )

        # ----------------------------------------------------
        # Construction du filtre
        # ----------------------------------------------------

        filter_parts = []

        # Flux principal explicite.
        #
        # C'est la correction essentielle :
        #
        # [0:v] ... [base]
        #
        # Le précédent code essayait d'utiliser [base]
        # sans l'avoir créé.
        filter_parts.append(
            "[0:v]"
            "setpts=PTS-STARTPTS"
            "[base]"
        )

        current_label = "base"

        # Taille de la mascotte.
        mascot_width = max(
            170,
            min(
                260,
                int(width * 0.22),
            ),
        )

        # Position :
        # suffisamment basse pour être discrète,
        # mais au-dessus de la zone principale des sous-titres.
        mascot_y = int(
            height * 0.67
        )

        for index, (
            mascot_path,
            start,
            end,
        ) in enumerate(
            mascot_files
        ):

            input_index = index + 1

            filter_parts.append(
                f"[{input_index}:v]"
                f"scale={mascot_width}:-1:"
                "force_original_aspect_ratio=decrease,"
                "format=rgba,"
                f"setpts=PTS-STARTPTS+{start:.3f}/TB"
                f"[mascot{index}]"
            )

            next_label = (
                f"comp{index}"
            )

            # Chaque expression n'est visible que
            # pendant son segment.
            filter_parts.append(
                f"[{current_label}]"
                f"[mascot{index}]"
                "overlay="
                f"x=(W-w)/2:"
                f"y={mascot_y}:"
                f"enable='between(t,{start:.3f},{end:.3f})'"
                f"[{next_label}]"
            )

            current_label = next_label

        filter_complex = ";".join(
            filter_parts
        )

        # ----------------------------------------------------
        # Commande FFmpeg
        # ----------------------------------------------------

        command = [
            FFMPEG_BIN,
            "-y",
            "-i",
            input_video,
        ]

        for mascot_path, _, _ in mascot_files:

            command.extend(
                [
                    "-loop",
                    "1",
                    "-i",
                    mascot_path,
                ]
            )

        command.extend(
            [
                "-filter_complex",
                filter_complex,
                "-map",
                f"[{current_label}]",
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
                "-movflags",
                "+faststart",
                output_video,
            ]
        )

        run_command(
            command,
            timeout=180,
        )

        if not os.path.exists(
            output_video
        ):
            raise RuntimeError(
                "La vidéo avec mascotte n'a pas été créée."
            )

        return output_video

    finally:

        shutil.rmtree(
            workdir,
            ignore_errors=True,
        )


# ============================================================
# EFFETS SONORES CONTEXTUELS
# ============================================================

def generate_sfx(
    output_path,
    kind="reveal",
    duration=0.25,
):
    """
    Génère un petit effet sonore procédural.

    Aucun fichier audio externe nécessaire.
    """

    duration = max(
        0.05,
        min(
            1.0,
            float(duration),
        ),
    )

    if kind == "impact":

        frequency = 110

    elif kind == "question":

        frequency = 520

    else:

        frequency = 660

    command = [
        FFMPEG_BIN,
        "-y",
        "-f",
        "lavfi",
        "-i",
        (
            f"sine=frequency={frequency}:"
            f"duration={duration:.3f}"
        ),
        "-af",
        (
            "afade=t=in:st=0:d=0.02,"
            f"afade=t=out:st={max(0, duration - 0.08):.3f}:d=0.08,"
            "volume=0.12"
        ),
        "-ar",
        "44100",
        "-ac",
        "2",
        output_path,
    ]

    run_command(
        command,
        timeout=20,
    )

    return output_path


def choose_sfx_events(
    script,
    boundaries,
    max_events=5,
):
    """
    Détermine quelques moments pertinents pour les SFX.

    Aucun SFX n'est ajouté à chaque changement de scène.
    """

    events = []

    if not boundaries:
        return events

    text = script.lower()

    keywords = [
        (
            [
                "incroyable",
                "surprenant",
                "surprise",
                "impossible",
                "jamais",
            ],
            "impact",
        ),
        (
            [
                "pourquoi",
                "comment",
                "mais pourquoi",
            ],
            "question",
        ),
        (
            [
                "découvre",
                "voici",
                "en réalité",
                "en fait",
            ],
            "reveal",
        ),
    ]

    for item in boundaries:

        word = str(
            item.get(
                "word",
                "",
            )
        ).lower()

        start = float(
            item.get(
                "start",
                0,
            )
        )

        for words, kind in keywords:

            if any(
                key in word
                for key in words
            ):

                events.append(
                    {
                        "time": start,
                        "kind": kind,
                    }
                )

                break

        if len(events) >= max_events:
            break

    return events


def add_contextual_sfx(
    input_video,
    output_video,
    script,
    boundaries,
    workdir,
):
    """
    Ajoute quelques SFX discrets à des moments pertinents.

    Pas de musique de fond.
    La narration reste dominante.
    """

    events = choose_sfx_events(
        script,
        boundaries,
        max_events=5,
    )

    if not events:

        shutil.copy2(
            input_video,
            output_video,
        )

        return output_video

    sfx_files = []

    for index, event in enumerate(
        events
    ):

        sfx_path = os.path.join(
            workdir,
            f"sfx_{index:02d}.wav",
        )

        generate_sfx(
            sfx_path,
            kind=event["kind"],
            duration=0.22,
        )

        sfx_files.append(
            (
                sfx_path,
                event["time"],
            )
        )

    # --------------------------------------------------------
    # Construire la chaîne audio
    # --------------------------------------------------------

    command = [
        FFMPEG_BIN,
        "-y",
        "-i",
        input_video,
    ]

    for sfx_path, _ in sfx_files:

        command.extend(
            [
                "-i",
                sfx_path,
            ]
        )

    filter_parts = []

    # Audio original
    filter_parts.append(
        "[0:a]"
        "aresample=44100,"
        "aformat=sample_fmts=fltp:"
        "sample_rates=44100:"
        "channel_layouts=stereo"
        "[mainaudio]"
    )

    mix_inputs = [
        "[mainaudio]"
    ]

    for index, (
        _sfx_path,
        timestamp,
    ) in enumerate(
        sfx_files
    ):

        input_index = index + 1

        delay_ms = max(
            0,
            int(
                timestamp * 1000
            ),
        )

        label = (
            f"sfxaudio{index}"
        )

        filter_parts.append(
            f"[{input_index}:a]"
            "aresample=44100,"
            f"adelay={delay_ms}|{delay_ms},"
            "volume=0.35"
            f"[{label}]"
        )

        mix_inputs.append(
            f"[{label}]"
        )

    filter_parts.append(
        "".join(mix_inputs)
        + f"amix=inputs={len(mix_inputs)}:"
          "duration=first:"
          "dropout_transition=0,"
          "loudnorm=I=-16:TP=-1.5:LRA=11"
        "[mixed]"
    )

    filter_complex = ";".join(
        filter_parts
    )

    command.extend(
        [
            "-filter_complex",
            filter_complex,
            "-map",
            "0:v",
            "-map",
            "[mixed]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            output_video,
        ]
    )

    run_command(
        command,
        timeout=120,
    )

    if not os.path.exists(
        output_video
    ):
        raise RuntimeError(
            "Impossible d'ajouter les effets sonores."
        )

    return output_video# ============================================================
# PARTIE 4/4 — PIPELINE + INTERFACE STREAMLIT
# ============================================================

def build_video(
    script: str,
    output_path: str,
    progress_callback=None,
):
    """
    Pipeline principal :

    1. Nettoyage du script
    2. Génération de la narration
    3. Calcul des timings mot-à-mot
    4. Découpage du script en scènes
    5. Recherche de visuels Pexels adaptés
    6. Création des scènes vidéo
    7. Assemblage
    8. Ajout de la narration
    9. Sous-titres mot-à-mot
    10. Mascotte cerveau animée
    11. Effets sonores contextuels
    """

    workdir = tempfile.mkdtemp(prefix="studio_video_")

    try:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        def progress(value, text):
            if progress_callback:
                progress_callback(value, text)

        # ----------------------------------------------------
        # 1. Nettoyage
        # ----------------------------------------------------

        progress(0.03, "Nettoyage du script...")

        script = clean_ai_text(script)
        script = remove_internal_markers(script)

        if not script:
            raise RuntimeError("Le script est vide après nettoyage.")

        word_count = count_words(script)

        print(f"[INFO] Script : {word_count} mots")

        # ----------------------------------------------------
        # 2. Génération narration
        # ----------------------------------------------------

        progress(0.08, "Génération de la narration...")

        narration_path = os.path.join(workdir, "narration.mp3")

        create_narration(
            script,
            narration_path,
        )

        if not os.path.exists(narration_path):
            raise RuntimeError("La narration n'a pas été générée.")

        duration = get_media_duration(narration_path)

        if duration <= 0:
            raise RuntimeError("Durée de narration invalide.")

        print(f"[INFO] Durée narration : {duration:.2f}s")

        # ----------------------------------------------------
        # 3. Timings mot-à-mot
        # ----------------------------------------------------

        progress(0.15, "Synchronisation des mots...")

        boundaries = get_word_boundaries(script)

        if not boundaries:
            raise RuntimeError(
                "Impossible de calculer les timings mot-à-mot."
            )

        # ----------------------------------------------------
        # 4. Scènes
        # ----------------------------------------------------

        progress(0.20, "Analyse du script et découpage des scènes...")

        scene_blocks = create_scene_blocks(script)

        if not scene_blocks:
            scene_blocks = [
                {
                    "text": script,
                    "start": 0.0,
                    "end": duration,
                }
            ]

        scene_blocks = split_long_scenes(
            scene_blocks,
            max_duration=7.0,
        )

        scene_blocks = build_narration_scene_boundaries(
            scene_blocks,
            boundaries,
            duration,
        )

        print(f"[INFO] Nombre de scènes : {len(scene_blocks)}")

        # ----------------------------------------------------
        # 5. Recherche des visuels
        # ----------------------------------------------------

        progress(0.27, "Recherche de visuels adaptés...")

        visual_files = []
        used_queries = []

        total_scenes = len(scene_blocks)

        for index, scene in enumerate(scene_blocks):

            scene_text = scene["text"]

            query = build_semantic_visual_query(
                scene_text
            )

            if query in used_queries:
                query = build_alternative_visual_query(
                    scene_text,
                    used_queries,
                )

            used_queries.append(query)

            orientation = (
                "portrait"
                if duration < 90
                else "landscape"
            )

            try:
                results = pexels_search(
                    query=query,
                    orientation=orientation,
                    per_page=5,
                )
            except Exception as exc:
                print(
                    f"[WARN] Pexels erreur scène {index + 1}: {exc}"
                )
                results = []

            selected = select_best_visual(
                results,
                used_visual_urls,
            )

            if selected:
                try:
                    visual_path = download_visual(
                        selected,
                        workdir,
                        index,
                    )

                    visual_files.append(visual_path)
                    used_visual_urls.add(
                        selected.get("src", {}).get("original", "")
                    )

                except Exception as exc:
                    print(
                        f"[WARN] Téléchargement visuel échoué : {exc}"
                    )
                    visual_files.append(
                        create_fallback_visual(
                            workdir,
                            index,
                            scene_text,
                        )
                    )
            else:
                visual_files.append(
                    create_fallback_visual(
                        workdir,
                        index,
                        scene_text,
                    )
                )

            progress(
                0.27 + 0.18 * (
                    (index + 1) / max(total_scenes, 1)
                ),
                f"Visuel {index + 1}/{total_scenes}",
            )

        # ----------------------------------------------------
        # 6. Création des clips
        # ----------------------------------------------------

        progress(0.47, "Création des scènes vidéo...")

        scene_paths = []

        for index, scene in enumerate(scene_blocks):

            start = float(scene["start"])
            end = float(scene["end"])

            scene_duration = max(
                0.5,
                end - start,
            )

            visual_path = visual_files[
                min(index, len(visual_files) - 1)
            ]

            scene_output = os.path.join(
                workdir,
                f"scene_{index:03d}.mp4",
            )

            create_image_scene(
                image_path=visual_path,
                output_path=scene_output,
                duration=scene_duration,
                width=1080 if duration < 90 else 1920,
                height=1920 if duration < 90 else 1080,
            )

            scene_paths.append(scene_output)

            progress(
                0.47 + 0.20 * (
                    (index + 1) / max(len(scene_blocks), 1)
                ),
                f"Montage scène {index + 1}/{len(scene_blocks)}",
            )

        if not scene_paths:
            raise RuntimeError(
                "Aucune scène vidéo n'a été créée."
            )

        # ----------------------------------------------------
        # 7. Assemblage vidéo
        # ----------------------------------------------------

        progress(0.69, "Assemblage des scènes...")

        silent_video = os.path.join(
            workdir,
            "silent_video.mp4",
        )

        concat_videos(
            scene_paths,
            silent_video,
        )

        # ----------------------------------------------------
        # 8. Ajout narration
        # ----------------------------------------------------

        progress(0.73, "Synchronisation de la narration...")

        narrated_video = os.path.join(
            workdir,
            "narrated_video.mp4",
        )

        mux_narration(
            silent_video,
            narration_path,
            narrated_video,
        )

        # ----------------------------------------------------
        # 9. Sous-titres MOT PAR MOT
        # ----------------------------------------------------

        progress(0.78, "Création des sous-titres mot-à-mot...")

        subtitle_video = os.path.join(
            workdir,
            "subtitle_video.mp4",
        )

        burn_word_by_word_subtitles(
            input_video=narrated_video,
            output_video=subtitle_video,
            boundaries=boundaries,
            video_duration=duration,
        )

        # ----------------------------------------------------
        # 10. Mascotte cerveau
        # ----------------------------------------------------

        progress(0.84, "Ajout de la mascotte cerveau...")

        mascot_video = os.path.join(
            workdir,
            "mascot_video.mp4",
        )

        create_mascot_overlay(
            input_video=subtitle_video,
            output_video=mascot_video,
            boundaries=boundaries,
            video_duration=duration,
        )

        # ----------------------------------------------------
        # 11. Effets sonores contextuels
        # ----------------------------------------------------

        progress(0.90, "Ajout des effets sonores contextuels...")

        sfx_video = os.path.join(
            workdir,
            "sfx_video.mp4",
        )

        add_contextual_sfx(
            input_video=mascot_video,
            output_video=sfx_video,
            script=script,
            boundaries=boundaries,
            workdir=workdir,
        )

        # ----------------------------------------------------
        # 12. Normalisation finale
        # ----------------------------------------------------

        progress(0.95, "Optimisation finale de la vidéo...")

        normalize_audio_video(
            sfx_video,
            output_path,
        )

        if not os.path.exists(output_path):
            raise RuntimeError(
                "Le fichier vidéo final n'existe pas."
            )

        final_duration = get_media_duration(
            output_path
        )

        if final_duration <= 0:
            raise RuntimeError(
                "La vidéo finale possède une durée invalide."
            )

        # ----------------------------------------------------
        # 13. Validation
        # ----------------------------------------------------

        progress(0.98, "Vérification de la vidéo finale...")

        validate_video_output(
            output_path,
            expected_duration=duration,
        )

        progress(
            1.0,
            "Vidéo terminée avec succès."
        )

        print(
            f"[OK] Vidéo créée : {output_path}"
        )

        return {
            "path": output_path,
            "duration": final_duration,
            "word_count": word_count,
            "scene_count": len(scene_blocks),
        }

    finally:
        # On garde le fichier final mais on supprime
        # les fichiers temporaires.
        try:
            shutil.rmtree(
                workdir,
                ignore_errors=True,
            )
        except Exception:
            pass


# ============================================================
# GÉNÉRATION DU SCRIPT PRINCIPAL
# ============================================================

def generate_video_from_topic(topic: str):
    """
    Génère le script principal à partir d'un sujet.
    """

    topic = clean_ai_text(topic)

    if not topic:
        raise ValueError(
            "Veuillez entrer un sujet."
        )

    print(
        f"[INFO] Génération du script pour : {topic}"
    )

    script = generate_main_script(topic)

    if not script:
        raise RuntimeError(
            "L'IA n'a produit aucun script."
        )

    return script


# ============================================================
# EXPORT / MÉTADONNÉES
# ============================================================

def generate_video_filename(topic: str):
    """
    Génère un nom de fichier propre.
    """

    normalized = unicodedata.normalize(
        "NFKD",
        topic,
    )

    normalized = normalized.encode(
        "ascii",
        "ignore",
    ).decode("ascii")

    normalized = re.sub(
        r"[^a-zA-Z0-9]+",
        "_",
        normalized,
    ).strip("_")

    if not normalized:
        normalized = "video"

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    return (
        f"{normalized}_{timestamp}.mp4"
    )


# ============================================================
# SESSION STATE
# ============================================================

def init_session_state():

    defaults = {
        "generated_script": "",
        "video_path": None,
        "generation_running": False,
        "last_error": None,
        "last_result": None,
    }

    for key, value in defaults.items():

        if key not in st.session_state:
            st.session_state[key] = value


# ============================================================
# INTERFACE STREAMLIT
# ============================================================

def render_header():

    st.markdown(
        """
        <div style="
            text-align:center;
            padding:10px 0 20px 0;
        ">
            <h1 style="
                margin-bottom:4px;
            ">
                🧠 Cerveau Curieux
            </h1>

            <p style="
                opacity:0.75;
                font-size:16px;
            ">
                Studio de création vidéo IA
            </p>

            <p style="
                opacity:0.60;
                font-size:13px;
            ">
                Psychologie • Neurosciences • Comportement humain
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar():

    with st.sidebar:

        st.markdown(
            "## ⚙️ Configuration"
        )

        openrouter_key = get_secret(
            "OPENROUTER_API_KEY"
        )

        pexels_key = get_secret(
            "PEXELS_API_KEY"
        )

        if openrouter_key:
            st.success(
                "OpenRouter : connecté"
            )
        else:
            st.error(
                "OpenRouter : non configuré"
            )

        if pexels_key:
            st.success(
                "Pexels : connecté"
            )
        else:
            st.warning(
                "Pexels : non configuré"
            )

        st.divider()

        st.markdown(
            "### 🎬 Format"
        )

        st.caption(
            "La longueur du script détermine automatiquement "
            "la meilleure adaptation vidéo."
        )

        st.markdown(
            """
            **Objectifs du studio**

            • Hook fort dès le début  
            • Ton amusant et surprenant  
            • Informations scientifiques vérifiables  
            • Visuels liés à la narration  
            • Sous-titres mot par mot  
            • Mascotte cerveau  
            • Effets sonores contextuels  
            • Montage dynamique  
            """
        )


def render_generation_section():

    st.markdown(
        "## 🎯 Nouveau sujet"
    )

    topic = st.text_area(
        "Sujet de la vidéo",
        placeholder=(
            "Exemple : "
            "Pourquoi notre cerveau adore les notifications ?"
        ),
        height=100,
        key="topic_input",
    )

    col1, col2 = st.columns(
        [1, 1]
    )

    with col1:

        generate_script_button = st.button(
            "🧠 Générer le script",
            use_container_width=True,
        )

    with col2:

        generate_video_button = st.button(
            "🎬 Générer la vidéo",
            use_container_width=True,
        )

    return (
        topic,
        generate_script_button,
        generate_video_button,
    )


def render_script():

    script = st.session_state.get(
        "generated_script",
        "",
    )

    if not script:
        return

    st.markdown(
        "## 📝 Script généré"
    )

    st.text_area(
        "Vous pouvez vérifier le script avant la production.",
        value=script,
        height=320,
        key="script_preview",
    )


def render_result():

    result = st.session_state.get(
        "last_result"
    )

    video_path = st.session_state.get(
        "video_path"
    )

    if not result or not video_path:
        return

    st.markdown(
        "## 🎉 Vidéo terminée"

    )

    if os.path.exists(video_path):

        st.video(
            video_path
        )

        col1, col2, col3 = st.columns(
            3
        )

        with col1:

            st.metric(
                "Durée",
                f"{result['duration']:.1f}s",
            )

        with col2:

            st.metric(
                "Mots",
                result["word_count"],
            )

        with col3:

            st.metric(
                "Scènes",
                result["scene_count"],
            )

        with open(
            video_path,
            "rb",
        ) as video_file:

            st.download_button(
                label="⬇️ Télécharger la vidéo",
                data=video_file,
                file_name=os.path.basename(
                    video_path
                ),
                mime="video/mp4",
                use_container_width=True,
            )


# ============================================================
# LANCEMENT DE LA GÉNÉRATION
# ============================================================

def run_generation(topic: str):

    if st.session_state.get(
        "generation_running",
        False,
    ):
        return

    st.session_state.generation_running = True
    st.session_state.last_error = None
    st.session_state.last_result = None
    st.session_state.video_path = None

    try:

        # ----------------------------------------------------
        # Génération script
        # ----------------------------------------------------

        script = generate_video_from_topic(
            topic
        )

        st.session_state.generated_script = script

        # ----------------------------------------------------
        # Fichier de sortie
        # ----------------------------------------------------

        output_dir = os.path.join(
            tempfile.gettempdir(),
            "studio_video_outputs",
        )

        os.makedirs(
            output_dir,
            exist_ok=True,
        )

        output_filename = (
            generate_video_filename(topic)
        )

        output_path = os.path.join(
            output_dir,
            output_filename,
        )

        # ----------------------------------------------------
        # Zone de progression
        # ----------------------------------------------------

        progress_bar = st.progress(
            0
        )

        status_text = st.empty()

        def update_progress(
            value,
            text,
        ):

            progress_bar.progress(
                min(
                    1.0,
                    max(
                        0.0,
                        value,
                    ),
                )
            )

            status_text.info(
                text
            )

        # ----------------------------------------------------
        # Production
        # ----------------------------------------------------

        result = build_video(
            script=script,
            output_path=output_path,
            progress_callback=update_progress,
        )

        st.session_state.last_result = result
        st.session_state.video_path = result[
            "path"
        ]

        status_text.success(
            "🎉 Vidéo créée avec succès !"
        )

        progress_bar.progress(
            1.0
        )

    except Exception as exc:

        error_text = (
            f"{type(exc).__name__}: {exc}"
        )

        st.session_state.last_error = (
            error_text
        )

        print(
            "[ERROR]",
            error_text,
        )

        st.error(
            "❌ La génération a échoué."
        )

        with st.expander(
            "Afficher les détails techniques"
        ):

            st.code(
                error_text
            )

            st.exception(
                exc
            )

    finally:

        st.session_state.generation_running = (
            False
        )


# ============================================================
# APPLICATION PRINCIPALE
# ============================================================

def main():

    st.set_page_config(
        page_title="Cerveau Curieux",
        page_icon="🧠",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    init_session_state()

    render_header()

    render_sidebar()

    topic, script_button, video_button = (
        render_generation_section()
    )

    # --------------------------------------------------------
    # Génération du script uniquement
    # --------------------------------------------------------

    if script_button:

        if not topic.strip():

            st.warning(
                "Veuillez entrer un sujet."
            )

        else:

            try:

                with st.spinner(
                    "🧠 Recherche d'une idée et génération du script..."
                ):

                    script = (
                        generate_video_from_topic(
                            topic
                        )
                    )

                st.session_state.generated_script = (
                    script
                )

                st.session_state.last_error = None

                st.success(
                    "Script généré."
                )

            except Exception as exc:

                st.session_state.last_error = (
                    f"{type(exc).__name__}: {exc}"
                )

                st.error(
                    "❌ Impossible de générer le script."
                )

                with st.expander(
                    "Détails"
                ):

                    st.exception(
                        exc
                    )

    # --------------------------------------------------------
    # Génération complète
    # --------------------------------------------------------

    if video_button:

        if not topic.strip():

            st.warning(
                "Veuillez entrer un sujet."
            )

        elif st.session_state.get(
            "generation_running",
            False,
        ):

            st.warning(
                "Une génération est déjà en cours."
            )

        else:

            st.markdown(
                "## 🎬 Production en cours..."
            )

            run_generation(
                topic
            )

    # --------------------------------------------------------
    # Affichage script
    # --------------------------------------------------------

    render_script()

    # --------------------------------------------------------
    # Affichage résultat
    # --------------------------------------------------------

    render_result()

    # --------------------------------------------------------
    # Erreur précédente
    # --------------------------------------------------------

    if (
        st.session_state.get("last_error")
        and not st.session_state.get("video_path")
    ):

        with st.expander(
            "Dernière erreur"
        ):

            st.code(
                st.session_state.last_error
            )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
