import os
import re
import json
import time
import math
import shutil
import asyncio
import tempfile
import unicodedata
import subprocess
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from datetime import datetime

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

FFMPEG_BIN = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE_BIN = shutil.which("ffprobe") or "ffprobe"


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
# ============================================================# ============================================================
# VOIX
# ============================================================

FRENCH_VOICES = [
    "fr-FR-HenriNeural",
    "fr-FR-DeniseNeural",
]


def select_french_voice() -> str:
    """
    Sélectionne la voix française utilisée pour la narration.
    """

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

    text = normalize_text(
        text
    )

    if not text:
        raise ValueError(
            "Impossible de créer une narration "
            "à partir d'un texte vide."
        )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:

        asyncio.run(
            _edge_tts_save(
                text=text,
                output_path=output_path,
                voice=voice,
                rate=rate,
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
                    text=text,
                    output_path=output_path,
                    voice=voice,
                    rate=rate,
                )
            )

        finally:

            loop.close()

            asyncio.set_event_loop(
                None
            )

    except Exception as exc:

        raise RuntimeError(
            f"Erreur Edge-TTS : {exc}"
        ) from exc

    if not output_path.exists():

        raise RuntimeError(
            "La narration audio n'a pas été créée."
        )

    if output_path.stat().st_size <= 0:

        raise RuntimeError(
            "Le fichier audio créé est vide."
        )

    return output_path


def create_narration(
    text: str,
    output_path: Path,
    voice: Optional[str] = None,
    rate: str = "+2%",
) -> Path:
    """
    Wrapper unique utilisé par le pipeline.
    """

    if voice is None:
        voice = select_french_voice()

    return synthesize_with_voice(
        text=text,
        output_path=output_path,
        voice=voice,
        rate=rate,
    )


# ============================================================
# DURÉE AUDIO
# ============================================================

def get_audio_duration(
    audio_path: Path,
) -> float:

    ensure_ffmpeg()

    if not audio_path.exists():

        raise RuntimeError(
            f"Fichier audio introuvable : {audio_path}"
        )

    result = run_command(
        [
            FFPROBE_BIN,
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
            "Impossible de déterminer la durée audio : "
            + result.stderr[-800:]
        )

    try:

        duration = float(
            result.stdout.strip()
        )

    except (
        ValueError,
        TypeError,
    ) as exc:

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
    audio_path: Optional[Path] = None,
    voice: Optional[str] = None,
    rate: str = "+2%",
) -> List[Dict[str, object]]:
    """
    Récupère les timings mot par mot fournis par Edge-TTS.

    Retour :
        [
            {
                "word": "...",
                "start": 0.0,
                "end": 0.35
            },
            ...
        ]

    Si Edge-TTS ne fournit pas les événements attendus,
    un fallback proportionnel à la longueur des mots est utilisé.
    """

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

    # --------------------------------------------------------
    # Si aucun audio n'est fourni, nous créons une narration
    # temporaire afin de connaître la durée réelle.
    # --------------------------------------------------------

    temporary_audio = None

    if audio_path is None:

        temporary_audio = (
            TEMP_DIR
            / f"timing_{int(time.time() * 1000)}.mp3"
        )

        create_narration(
            text=text,
            output_path=temporary_audio,
            voice=voice,
            rate=rate,
        )

        audio_path = temporary_audio

    audio_path = Path(
        audio_path
    )

    words = re.findall(
        r"\S+",
        text,
    )

    if not words:
        return []

    boundaries = []

    async def collect_boundaries():

        communicate = edge_tts.Communicate(
            text=text,
            voice=voice,
            rate=rate,
        )

        async for event in communicate.stream():

            if event.get("type") != "WordBoundary":
                continue

            offset = event.get(
                "offset",
                0,
            )

            duration = event.get(
                "duration",
                0,
            )

            try:

                start = (
                    float(offset)
                    / 10_000_000.0
                )

                event_duration = (
                    float(duration)
                    / 10_000_000.0
                )

            except (
                ValueError,
                TypeError,
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

            boundaries.append(
                {
                    "word": word,
                    "start": start,
                    "duration": max(
                        0.03,
                        event_duration,
                    ),
                }
            )

    try:

        asyncio.run(
            collect_boundaries()
        )

    except RuntimeError:

        loop = asyncio.new_event_loop()

        try:

            asyncio.set_event_loop(
                loop
            )

            loop.run_until_complete(
                collect_boundaries()
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

    duration = get_audio_duration(
        audio_path
    )

    # --------------------------------------------------------
    # Nettoyage des timings Edge-TTS
    # --------------------------------------------------------

    if boundaries:

        cleaned = []

        for index, item in enumerate(
            boundaries
        ):

            word = str(
                item.get(
                    "word",
                    "",
                )
            ).strip()

            if not word:
                continue

            start = float(
                item.get(
                    "start",
                    0.0,
                )
            )

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

                next_start = float(
                    boundaries[
                        index + 1
                    ].get(
                        "start",
                        start,
                    )
                )

                end = min(
                    duration,
                    max(
                        start + 0.03,
                        next_start,
                    ),
                )

            else:

                event_duration = float(
                    item.get(
                        "duration",
                        0.08,
                    )
                )

                end = min(
                    duration,
                    max(
                        start + event_duration,
                        start + 0.08,
                    ),
                )

            if end <= start:
                continue

            cleaned.append(
                {
                    "word": word,
                    "start": start,
                    "end": end,
                }
            )

        if cleaned:

            # Le dernier mot doit aller jusqu'à la
            # fin réelle de la narration.
            cleaned[-1]["end"] = duration

            return cleaned

    # ========================================================
    # FALLBACK
    # ========================================================

    clean_words = re.findall(
        r"\S+",
        text,
    )

    if not clean_words:
        return []

    weights = []

    for word in clean_words:

        clean_word = re.sub(
            r"[^\wÀ-ÿ'-]",
            "",
            word,
        )

        weights.append(
            max(
                1.0,
                len(clean_word) ** 0.72,
            )
        )

    total_weight = sum(
        weights
    )

    if total_weight <= 0:
        total_weight = float(
            len(clean_words)
        )

    fallback = []

    current_time = 0.0

    for word, weight in zip(
        clean_words,
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
            start + word_duration,
        )

        if end > start:

            fallback.append(
                {
                    "word": word,
                    "start": start,
                    "end": end,
                }
            )

        current_time = end

    if fallback:

        fallback[-1]["end"] = duration

    # Nettoyage du fichier temporaire.
    if temporary_audio is not None:

        try:
            temporary_audio.unlink(
                missing_ok=True
            )
        except Exception:
            pass

    return fallback


# ============================================================
# UTILITAIRES VIDÉO
# ============================================================

def ffmpeg_escape_path(
    path: Path,
) -> str:

    value = str(
        path
    )

    return (
        value
        .replace(
            "\\",
            "\\\\",
        )
        .replace(
            ":",
            "\\:",
        )
        .replace(
            "'",
            "\\'",
        )
    )


def get_media_duration(
    media_path: Path,
) -> float:

    suffix = media_path.suffix.lower()

    if suffix in (
        ".mp3",
        ".wav",
        ".m4a",
        ".aac",
        ".ogg",
        ".flac",
    ):

        return get_audio_duration(
            media_path
        )

    return get_video_duration(
        media_path
    )


def get_video_duration(
    video_path: Path,
) -> float:

    ensure_ffmpeg()

    if not video_path.exists():

        raise RuntimeError(
            f"Vidéo introuvable : {video_path}"
        )

    result = run_command(
        [
            FFPROBE_BIN,
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
            + result.stderr[-800:]
        )

    try:

        duration = float(
            result.stdout.strip()
        )

    except (
        ValueError,
        TypeError,
    ) as exc:

        raise RuntimeError(
            "Durée vidéo invalide."
        ) from exc

    if duration <= 0:

        raise RuntimeError(
            "La durée de la vidéo est nulle."
        )

    return duration


def get_video_dimensions(
    video_path: Path,
) -> Tuple[int, int]:

    stream = probe_video_stream(
        video_path
    )

    try:

        width = int(
            stream.get(
                "width",
                0,
            )
        )

        height = int(
            stream.get(
                "height",
                0,
            )
        )

    except (
        ValueError,
        TypeError,
    ):

        width = 0
        height = 0

    if width <= 0 or height <= 0:

        raise RuntimeError(
            "Impossible de déterminer "
            "les dimensions de la vidéo."
        )

    return width, height


def probe_video_stream(
    video_path: Path,
) -> Dict[str, object]:

    ensure_ffmpeg()

    if not video_path.exists():
        return {}

    result = run_command(
        [
            FFPROBE_BIN,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,r_frame_rate,"
            "codec_name,pix_fmt",
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
            "",
        )
    ).strip()


def select_unique_photos(
    photos: List[dict],
    used_urls: set,
    limit: int = 5,
) -> List[dict]:

    selected = []

    for photo in photos:

        fingerprint = visual_fingerprint(
            photo
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
        description
    ]

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

    if (
        simplified
        and simplified != description
    ):

        queries.append(
            simplified
        )

    return list(
        dict.fromkeys(
            queries
        )
    )


def build_semantic_visual_query(
    description: str,
) -> str:

    description = normalize_text(
        description
    )

    if not description:
        return "human behavior psychology"

    lower = description.lower()

    # --------------------------------------------------------
    # Les recherches sont volontairement concrètes.
    # Pexels fonctionne mieux avec des concepts visuels
    # qu'avec des phrases purement abstraites.
    # --------------------------------------------------------

    if any(
        term in lower
        for term in (
            "cerveau",
            "neuroscience",
            "neurone",
            "mémoire",
            "pensée",
            "penser",
        )
    ):

        return (
            f"human brain neuroscience "
            f"person thinking {description}"
        )

    if any(
        term in lower
        for term in (
            "peur",
            "stress",
            "émotion",
            "joie",
            "triste",
            "surprise",
        )
    ):

        return (
            f"human emotional reaction "
            f"{description}"
        )

    if any(
        term in lower
        for term in (
            "décision",
            "choix",
            "décider",
        )
    ):

        return (
            f"person making decision "
            f"{description}"
        )

    if any(
        term in lower
        for term in (
            "sommeil",
            "dormir",
            "rêve",
        )
    ):

        return (
            f"person sleeping sleep "
            f"{description}"
        )

    return description


def build_alternative_visual_query(
    description: str,
) -> str:

    description = normalize_text(
        description
    )

    if not description:

        return "human behavior"

    lower = description.lower()

    if "cerveau" in lower:

        return "brain science human thinking"

    if "mémoire" in lower:

        return "person remembering memory"

    if "émotion" in lower:

        return "human emotional reaction"

    if "décision" in lower:

        return "person choosing decision"

    if "stress" in lower:

        return "stressed person psychology"

    return (
        "human behavior "
        + description[:100]
    )


def find_visual_for_scene(
    description: str,
    used_urls: set,
    portrait: bool = True,
) -> Optional[dict]:

    description = normalize_text(
        description
    )

    if not description:
        return None

    orientation = (
        "portrait"
        if portrait
        else "landscape"
    )

    queries = [
        build_semantic_visual_query(
            description
        ),
        build_alternative_visual_query(
            description
        ),
    ]

    queries.extend(
        build_visual_queries(
            description
        )
    )

    queries = list(
        dict.fromkeys(
            query
            for query in queries
            if query
        )
    )

    for query in queries:

        photos = pexels_search(
            query=query,
            per_page=12,
            orientation=orientation,
        )

        selected = select_unique_photos(
            photos=photos,
            used_urls=used_urls,
            limit=1,
        )

        if selected:
            return selected[0]

    return None


def get_best_photo_url(
    photo: dict,
    portrait: bool = True,
) -> Optional[str]:

    if not isinstance(
        photo,
        dict,
    ):
        return None

    src = photo.get(
        "src",
        {},
    )

    if not isinstance(
        src,
        dict,
    ):
        return None

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

    # --------------------------------------------------------
    # Si l'IA n'a pas généré de marqueurs,
    # nous découpons automatiquement par phrases.
    # --------------------------------------------------------

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
            if normalize_text(
                sentence
            )
        ]

        return [
            {
                "text": sentence,
                "visual": sentence,
            }
            for sentence in sentences
        ]

    blocks = []

    prefix = normalize_text(
        script[
            :matches[0].start()
        ]
    )

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
            script[
                start:end
            ]
        )

        if narration:

            blocks.append(
                {
                    "text": narration,
                    "visual": (
                        visual
                        or narration
                    ),
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

        if len(current) >= max_words:

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
                "",
            )
        )

        visual = normalize_text(
            block.get(
                "visual",
                "",
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
                    "visual": (
                        visual
                        or part
                    ),
                }
            )

    return prepared


# ============================================================
# SYNCHRONISATION DES SCÈNES
# ============================================================

def _boundary_values(
    boundary,
) -> Tuple[str, float, float]:

    if isinstance(
        boundary,
        dict,
    ):

        word = str(
            boundary.get(
                "word",
                "",
            )
        )

        start = float(
            boundary.get(
                "start",
                0.0,
            )
        )

        end = float(
            boundary.get(
                "end",
                start + 0.05,
            )
        )

        return (
            word,
            start,
            end,
        )

    if isinstance(
        boundary,
        (list, tuple),
    ) and len(boundary) >= 3:

        return (
            str(
                boundary[0]
            ),
            float(
                boundary[1]
            ),
            float(
                boundary[2]
            ),
        )

    return (
        "",
        0.0,
        0.05,
    )


def estimate_scene_boundaries(
    blocks: List[Dict[str, str]],
    word_boundaries: List,
    total_duration: float,
) -> List[Dict[str, object]]:

    if not blocks:
        return []

    total_duration = max(
        0.1,
        float(total_duration),
    )

    normalized_boundaries = [
        _boundary_values(
            item
        )
        for item in (
            word_boundaries
            or []
        )
    ]

    if not normalized_boundaries:

        weights = [
            max(
                1,
                count_words(
                    block.get(
                        "text",
                        "",
                    )
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

            scene_duration = (
                total_duration
                * weight
                / total_weight
            )

            end = min(
                total_duration,
                current + scene_duration,
            )

            result.append(
                {
                    "text": block.get(
                        "text",
                        "",
                    ),
                    "visual": block.get(
                        "visual",
                        "",
                    ),
                    "start": current,
                    "end": end,
                }
            )

            current = end

        if result:
            result[-1]["end"] = total_duration

        return result

    all_words = [
        re.sub(
            r"[^\wÀ-ÿ'-]",
            "",
            word.lower(),
        )
        for word, _, _ in normalized_boundaries
    ]

    result = []

    cursor = 0

    for block in blocks:

        target_words = re.findall(
            r"\b[\wÀ-ÿ'-]+\b",
            block.get(
                "text",
                "",
            ).lower(),
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
        matched = 0

        while (
            cursor < len(all_words)
            and matched < len(
                target_words
            )
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

        if (
            start_index
            >= len(
                normalized_boundaries
            )
        ):
            break

        end_index = max(
            start_index,
            cursor - 1,
        )

        start = normalized_boundaries[
            start_index
        ][1]

        end = normalized_boundaries[
            min(
                end_index,
                len(
                    normalized_boundaries
                ) - 1,
            )
        ][2]

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
                "text": block.get(
                    "text",
                    "",
                ),
                "visual": block.get(
                    "visual",
                    "",
                ),
                "start": start,
                "end": end,
            }
        )

    # --------------------------------------------------------
    # Si le matching a laissé des trous, on s'assure
    # que la dernière scène termine exactement avec la voix.
    # --------------------------------------------------------

    if result:

        result[-1]["end"] = total_duration

    return result


def build_narration_scene_boundaries(
    script: str,
    word_boundaries: List,
    total_duration: float,
) -> List[Dict[str, object]]:

    blocks = prepare_scene_blocks(
        script
    )

    return estimate_scene_boundaries(
        blocks=blocks,
        word_boundaries=word_boundaries,
        total_duration=total_duration,
    )


# ============================================================
# TÉLÉCHARGEMENT DES VISUELS
# ============================================================

def download_visual(
    photo: dict,
    output_path: Path,
    portrait: bool = True,
) -> Optional[Path]:

    url = get_best_photo_url(
        photo,
        portrait=portrait,
    )

    if not url:
        return None

    if download_file(
        url=url,
        destination=output_path,
        timeout=30,
    ):

        return output_path

    return None


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

        description = normalize_text(
            str(
                scene.get(
                    "visual",
                    scene.get(
                        "text",
                        "",
                    ),
                )
            )
        )

        photo = find_visual_for_scene(
            description=description,
            used_urls=used_urls,
            portrait=portrait,
        )

        if photo is None:
            continue

        destination = (
            work_dir
            / f"visual_{index:03d}.jpg"
        )

        visual_path = download_visual(
            photo=photo,
            output_path=destination,
            portrait=portrait,
        )

        if visual_path is None:
            continue

        scene_copy = dict(
            scene
        )

        scene_copy[
            "visual_path"
        ] = visual_path

        scene_copy[
            "photo_url"
        ] = visual_fingerprint(
            photo
        )

        result.append(
            scene_copy
        )

    return result


# ============================================================
# FALLBACK VISUEL
# ============================================================

def create_fallback_visual(
    output_path: Path,
    width: int = SHORT_WIDTH,
    height: int = SHORT_HEIGHT,
) -> Path:

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

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
            max(
                32,
                int(width * 0.065),
            ),
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
    """
    Transforme une image en plan vidéo.
    
    Version robuste :
    - aucun zoompan
    - aucun pad
    - conservation du ratio
    - l'image est toujours suffisamment grande pour le crop
    - léger mouvement horizontal ou vertical
    - compatible avec les images portrait et paysage
    """

    ensure_ffmpeg()

    duration = max(
        0.15,
        float(duration),
    )

    if not image_path.exists():
        raise RuntimeError(
            f"Image introuvable : {image_path}"
        )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # Mouvement léger.
    #
    # On agrandit légèrement l'image par rapport à la taille
    # finale afin d'avoir une marge pour le déplacement.
    # --------------------------------------------------------

    motion_scale = 1.06

    scaled_width = int(
        math.ceil(width * motion_scale)
    )

    scaled_height = int(
        math.ceil(height * motion_scale)
    )

    cycle = max(
        duration,
        1.0,
    )

    amplitude = 0.035

    phase = (
        int(motion_index)
        % 4
    )

    # --------------------------------------------------------
    # Positions du crop.
    #
    # L'image a été mise à l'échelle avec
    # force_original_aspect_ratio=increase.
    #
    # Elle sera donc toujours au moins aussi grande que
    # la résolution finale.
    # --------------------------------------------------------

    if phase == 0:

        crop_x = (
            f"(iw-{width})/2"
            f"+(iw-{width})*{amplitude}"
            f"*sin(2*PI*t/{cycle:.4f})"
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
            f"*sin(2*PI*t/{cycle:.4f})"
        )

    elif phase == 2:

        crop_x = (
            f"(iw-{width})/2"
            f"+(iw-{width})*{amplitude}"
            f"*cos(2*PI*t/{cycle:.4f})"
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
            f"*cos(2*PI*t/{cycle:.4f})"
        )

    # --------------------------------------------------------
    # FILTRE FFmpeg ROBUSTE
    #
    # IMPORTANT :
    # On utilise "increase" et non "decrease".
    #
    # Cela garantit que l'image sera suffisamment grande
    # pour le crop final.
    #
    # Aucun "pad" n'est nécessaire.
    # --------------------------------------------------------

    vf = (
        f"scale={scaled_width}:"
        f"{scaled_height}:"
        "force_original_aspect_ratio=increase,"
        f"crop={width}:{height}:"
        f"{crop_x}:{crop_y},"
        "setsar=1,"
        "format=yuv420p"
    )

    command = [
        FFMPEG_BIN,
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
            + result.stderr[-1800:]
        )

    if not output_path.exists():

        raise RuntimeError(
            "Le plan vidéo n'a pas été créé."
        )

    if output_path.stat().st_size <= 0:

        raise RuntimeError(
            "Le plan vidéo créé est vide."
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

    work_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

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

        start = float(
            scene.get(
                "start",
                0.0,
            )
        )

        end = float(
            scene.get(
                "end",
                0.0,
            )
        )

        duration = end - start

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

    valid_clips = [
        Path(clip)
        for clip in clips
        if Path(clip).exists()
    ]

    if not valid_clips:

        raise RuntimeError(
            "Aucun plan vidéo valide."
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

        for clip in valid_clips:

            escaped = str(
                clip.resolve()
            ).replace(
                "'",
                "'\\''",
            )

            handle.write(
                f"file '{escaped}'\n"
            )

    # --------------------------------------------------------
    # Les clips ont tous les mêmes paramètres vidéo.
    # Le concat demuxer est donc rapide et fiable.
    # --------------------------------------------------------

    command = [
        FFMPEG_BIN,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
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
        timeout=180,
    )

    if result.returncode != 0:

        raise RuntimeError(
            "Erreur FFmpeg pendant "
            "la concaténation :\n"
            + result.stderr[-2000:]
        )

    if not output_path.exists():

        raise RuntimeError(
            "La vidéo concaténée n'a pas été créée."
        )

    return output_path


def concat_videos(
    clips: List[Path],
    output_path: Path,
) -> Path:

    return concat_video_clips(
        clips=clips,
        output_path=output_path,
    )


# ============================================================
# FIN DE LA PARTIE 2/6
# ============================================================# ============================================================
# NARRATION ET MUXAGE AUDIO
# ============================================================

def mux_narration(
    video_path: Path,
    audio_path: Path,
    output_path: Path,
) -> Path:

    ensure_ffmpeg()

    if not video_path.exists():
        raise RuntimeError(
            f"Vidéo introuvable : {video_path}"
        )

    if not audio_path.exists():
        raise RuntimeError(
            f"Audio introuvable : {audio_path}"
        )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    command = [
        FFMPEG_BIN,
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
            "Erreur FFmpeg pendant "
            "l'ajout de la narration :\n"
            + result.stderr[-2000:]
        )

    if not output_path.exists():

        raise RuntimeError(
            "La vidéo avec narration "
            "n'a pas été créée."
        )

    return output_path


# ============================================================
# NORMALISATION AUDIO
# ============================================================

def normalize_audio(
    input_video: Path,
    output_video: Path,
) -> Path:

    ensure_ffmpeg()

    if not input_video.exists():

        raise RuntimeError(
            f"Vidéo introuvable : {input_video}"
        )

    output_video.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    command = [
        FFMPEG_BIN,
        "-y",
        "-i",
        str(input_video),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        str(VIDEO_CRF),
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        AUDIO_BITRATE,
        "-af",
        (
            "loudnorm="
            "I=-16:"
            "TP=-1.5:"
            "LRA=11"
        ),
        "-movflags",
        "+faststart",
        str(output_video),
    ]

    result = run_command(
        command,
        timeout=180,
    )

    if result.returncode != 0:

        raise RuntimeError(
            "Erreur pendant la normalisation audio :\n"
            + result.stderr[-2000:]
        )

    if not output_video.exists():

        raise RuntimeError(
            "La vidéo normalisée n'a pas été créée."
        )

    return output_video


def normalize_audio_video(
    input_video: Path,
    output_path: Path,
) -> Path:

    return normalize_audio(
        input_video=input_video,
        output_video=output_path,
    )


# ============================================================
# VALIDATION DE LA VIDÉO
# ============================================================

def validate_video_output(
    video_path: Path,
    expected_duration: Optional[float] = None,
) -> bool:

    if not video_path.exists():

        raise RuntimeError(
            "Le fichier vidéo final est introuvable."
        )

    if video_path.stat().st_size < 10_000:

        raise RuntimeError(
            "Le fichier vidéo final semble vide "
            "ou beaucoup trop petit."
        )

    ensure_ffmpeg()

    result = run_command(
        [
            FFPROBE_BIN,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,codec_name,width,height",
            "-show_entries",
            "format=duration,size",
            "-of",
            "json",
            str(video_path),
        ],
        timeout=30,
    )

    if result.returncode != 0:

        raise RuntimeError(
            "FFprobe n'arrive pas à lire "
            "la vidéo finale :\n"
            + result.stderr[-1500:]
        )

    try:

        data = json.loads(
            result.stdout
        )

    except Exception as exc:

        raise RuntimeError(
            "FFprobe a renvoyé une réponse invalide."
        ) from exc

    streams = data.get(
        "streams",
        [],
    )

    video_stream = next(
        (
            stream
            for stream in streams
            if stream.get(
                "codec_type"
            ) == "video"
        ),
        None,
    )

    if video_stream is None:

        raise RuntimeError(
            "La vidéo finale ne contient "
            "aucune piste vidéo."
        )

    width = int(
        video_stream.get(
            "width",
            0,
        )
        or 0
    )

    height = int(
        video_stream.get(
            "height",
            0,
        )
        or 0
    )

    if width <= 0 or height <= 0:

        raise RuntimeError(
            "Les dimensions de la vidéo finale "
            "sont invalides."
        )

    duration = float(
        data.get(
            "format",
            {},
        ).get(
            "duration",
            0,
        )
        or 0
    )

    if duration <= 0:

        raise RuntimeError(
            "La durée de la vidéo finale est invalide."
        )

    if expected_duration is not None:

        expected_duration = float(
            expected_duration
        )

        # Une petite différence est normale à cause
        # de l'encodage et de l'arrondi des timestamps.
        tolerance = max(
            1.0,
            expected_duration * 0.05,
        )

        if abs(
            duration - expected_duration
        ) > tolerance:

            raise RuntimeError(
                "La durée finale est incohérente : "
                f"{duration:.2f}s au lieu d'environ "
                f"{expected_duration:.2f}s."
            )

    return True


# ============================================================
# PRÉPARATION DU SCRIPT POUR LE MONTAGE
# ============================================================

def clean_script_for_video(
    script: str,
) -> str:

    script = remove_visual_markers(
        script
    )

    script = normalize_text(
        script
    )

    # Supprime certains marqueurs que l'IA peut
    # occasionnellement produire malgré les consignes.
    script = re.sub(
        r"\[(?:HOOK|INTRO|OUTRO|CTA)\s*:\s*",
        "",
        script,
        flags=re.I,
    )

    script = script.replace(
        "]",
        "",
    )

    return normalize_text(
        script
    )


def ensure_cta(
    script: str,
) -> str:

    script = normalize_text(
        script
    )

    if not script:
        return script

    cta_patterns = [
        "abonne-toi",
        "abonne toi",
        "abonnez-vous",
        "abonnez vous",
    ]

    lower = script.lower()

    if any(
        pattern in lower
        for pattern in cta_patterns
    ):

        return script

    return (
        script.rstrip()
        + "\n\n"
        + "Abonne-toi pour en savoir plus "
        + "sur ton cerveau."
    )


# ============================================================
# SÉCURISATION DU TEXTE
# ============================================================

def normalize_for_matching(
    text: str,
) -> str:

    text = str(
        text or ""
    )

    text = unicodedata.normalize(
        "NFKD",
        text,
    )

    text = "".join(
        char
        for char in text
        if not unicodedata.combining(
            char
        )
    )

    text = text.lower()

    text = re.sub(
        r"[^\w\s'-]",
        " ",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def remove_internal_markers(
    text: str,
) -> str:

    if not text:
        return ""

    patterns = [
        r"\[VISUAL\s*:\s*.*?\]",
        r"\[IMAGE\s*:\s*.*?\]",
        r"\[HOOK\s*:\s*.*?\]",
        r"\[CTA\s*:\s*.*?\]",
    ]

    for pattern in patterns:

        text = re.sub(
            pattern,
            " ",
            text,
            flags=re.I | re.S,
        )

    return normalize_text(
        text
    )


# ============================================================
# DÉTECTION DU FORMAT
# ============================================================

def determine_video_format(
    script: str,
    duration: float,
) -> str:

    words = count_words(
        script
    )

    duration = float(
        duration
    )

    # --------------------------------------------------------
    # Un script court reste un Short.
    # Un script suffisamment long peut devenir une vidéo
    # horizontale.
    # --------------------------------------------------------

    if (
        words >= 500
        or duration > 90
    ):

        return "landscape"

    return "portrait"


def get_video_dimensions_for_format(
    video_format: str,
) -> Tuple[int, int]:

    if video_format == "landscape":

        return (
            LONG_WIDTH,
            LONG_HEIGHT,
        )

    return (
        SHORT_WIDTH,
        SHORT_HEIGHT,
    )


# ============================================================
# ADAPTATION DU NOMBRE DE SCÈNES
# ============================================================

def rebalance_scene_durations(
    scenes: List[Dict[str, object]],
    total_duration: float,
) -> List[Dict[str, object]]:

    if not scenes:
        return []

    total_duration = max(
        0.1,
        float(total_duration),
    )

    weights = []

    for scene in scenes:

        text = str(
            scene.get(
                "text",
                "",
            )
        )

        words = count_words(
            text
        )

        weights.append(
            max(
                1,
                words,
            )
        )

    total_weight = sum(
        weights
    )

    if total_weight <= 0:
        total_weight = len(
            scenes
        )

    current = 0.0

    result = []

    for scene, weight in zip(
        scenes,
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

        item = dict(
            scene
        )

        item[
            "start"
        ] = current

        item[
            "end"
        ] = end

        result.append(
            item
        )

        current = end

    if result:

        result[-1][
            "end"
        ] = total_duration

    return result


# ============================================================
# COMPATIBILITÉ AVEC LES ANCIENNES FONCTIONS
# ============================================================

def create_scene_blocks(
    script: str,
) -> List[Dict[str, str]]:

    return prepare_scene_blocks(
        script
    )


def split_long_scenes(
    scenes: List[Dict[str, object]],
    max_words: int = 28,
) -> List[Dict[str, object]]:

    result = []

    for scene in scenes:

        text = normalize_text(
            str(
                scene.get(
                    "text",
                    "",
                )
            )
        )

        visual = normalize_text(
            str(
                scene.get(
                    "visual",
                    "",
                )
            )
        )

        parts = split_long_scene(
            text,
            max_words=max_words,
        )

        if not parts:
            continue

        for part in parts:

            item = dict(
                scene
            )

            item[
                "text"
            ] = part

            item[
                "visual"
            ] = (
                visual
                or part
            )

            result.append(
                item
            )

    return result


# ============================================================
# SÉLECTION DU MEILLEUR VISUEL
# ============================================================

def select_best_visual(
    photos: List[dict],
    used_urls: Optional[set] = None,
) -> Optional[dict]:

    if not photos:
        return None

    if used_urls is None:
        used_urls = set()

    # --------------------------------------------------------
    # Premier choix :
    # photo non utilisée avec une URL exploitable.
    # --------------------------------------------------------

    for photo in photos:

        url = visual_fingerprint(
            photo
        )

        if not url:
            continue

        if url in used_urls:
            continue

        used_urls.add(
            url
        )

        return photo

    # --------------------------------------------------------
    # Si toutes les photos ont déjà été utilisées,
    # on autorise exceptionnellement une répétition.
    # --------------------------------------------------------

    for photo in photos:

        if get_best_photo_url(
            photo
        ):

            return photo

    return None


# ============================================================
# RECHERCHE D'UN VISUEL DE SECOURS
# ============================================================

def search_fallback_visual(
    description: str,
    used_urls: Optional[set] = None,
    portrait: bool = True,
) -> Optional[dict]:

    if used_urls is None:
        used_urls = set()

    query = build_alternative_visual_query(
        description
    )

    orientation = (
        "portrait"
        if portrait
        else "landscape"
    )

    photos = pexels_search(
        query=query,
        per_page=15,
        orientation=orientation,
    )

    return select_best_visual(
        photos=photos,
        used_urls=used_urls,
    )


# ============================================================
# CONSTRUCTION DES PLANS AVEC FALLBACK
# ============================================================

def ensure_scene_visuals(
    scenes: List[Dict[str, object]],
    work_dir: Path,
    width: int,
    height: int,
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

        item = dict(
            scene
        )

        visual_path = item.get(
            "visual_path"
        )

        if visual_path:

            visual_path = Path(
                visual_path
            )

            if visual_path.exists():

                result.append(
                    item
                )

                url = str(
                    item.get(
                        "photo_url",
                        "",
                    )
                )

                if url:
                    used_urls.add(
                        url
                    )

                continue

        description = normalize_text(
            str(
                item.get(
                    "visual",
                    item.get(
                        "text",
                        "",
                    ),
                )
            )
        )

        photo = search_fallback_visual(
            description=description,
            used_urls=used_urls,
            portrait=portrait,
        )

        destination = (
            work_dir
            / f"visual_fallback_{index:03d}.jpg"
        )

        downloaded = None

        if photo:

            downloaded = download_visual(
                photo=photo,
                output_path=destination,
                portrait=portrait,
            )

        if downloaded is None:

            downloaded = create_fallback_visual(
                output_path=destination,
                width=width,
                height=height,
            )

        item[
            "visual_path"
        ] = downloaded

        if photo:

            item[
                "photo_url"
            ] = visual_fingerprint(
                photo
            )

        result.append(
            item
        )

    return result


# ============================================================
# FIN DE LA PARTIE 3/6
# ============================================================# ============================================================
# SOUS-TITRES MOT PAR MOT
# ============================================================

def clean_subtitle_word(
    word: str,
) -> str:

    if word is None:
        return ""

    word = str(
        word
    )

    # Supprimer les marqueurs éventuels
    word = re.sub(
        r"\[.*?\]",
        "",
        word,
    )

    # Supprimer les caractères qui pourraient
    # être interprétés comme des options FFmpeg.
    word = word.replace(
        "\\",
        "",
    )

    word = word.replace(
        "\n",
        " ",
    )

    word = word.replace(
        "\r",
        " ",
    )

    return normalize_text(
        word
    )


def subtitle_safe_word(
    word: str,
) -> str:

    word = clean_subtitle_word(
        word
    )

    if not word:
        return ""

    # drawtext utilise ":" comme séparateur
    # de paramètres.
    word = word.replace(
        ":",
        "\\:",
    )

    # Protection des apostrophes.
    word = word.replace(
        "'",
        "\\'",
    )

    # Protection des caractères spéciaux
    # pouvant avoir une signification dans
    # les expressions FFmpeg.
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


def build_word_subtitle_filter(
    boundaries: List[Dict[str, object]],
) -> str:
    """
    Construit le filtre FFmpeg des sous-titres mot par mot.

    Important :
    - un seul mot affiché à la fois
    - aucun ASS
    - aucun code couleur
    - aucune phrase empilée
    - les virgules de between() sont échappées pour FFmpeg
    """

    filters = []

    for boundary in boundaries:

        word = clean_subtitle_word(
            str(
                boundary.get(
                    "word",
                    "",
                )
            )
        )

        if not word:
            continue

        try:
            start = float(
                boundary.get(
                    "start",
                    0.0,
                )
            )

            end = float(
                boundary.get(
                    "end",
                    start + 0.05,
                )
            )

        except (
            ValueError,
            TypeError,
        ):
            continue

        if end <= start:
            continue

        safe_word = subtitle_safe_word(
            word
        )

        if not safe_word:
            continue

        # ----------------------------------------------------
        # IMPORTANT :
        # Les virgules dans l'expression FFmpeg doivent être
        # échappées.
        #
        # Sans cela :
        #
        # between(t,0.000,14.098)
        #
        # peut être interprété comme plusieurs filtres.
        # ----------------------------------------------------

        enable_expression = (
            f"between(t\\,{start:.3f}\\,{end:.3f})"
        )

        drawtext_filter = (
            "drawtext="
            f"text='{safe_word}':"
            "fontfile=/usr/share/fonts/"
            "truetype/dejavu/"
            "DejaVuSans-Bold.ttf:"
            "fontcolor=white:"
            "fontsize=72:"
            "borderw=5:"
            "bordercolor=black:"
            "shadowx=2:"
            "shadowy=2:"
            "x=(w-text_w)/2:"
            "y=h-text_h-170:"
            f"enable='{enable_expression}'"
        )

        filters.append(
            drawtext_filter
        )

    return ",".join(filters)
    )

def burn_word_by_word_subtitles(
    input_video: Path,
    output_video: Path,
    boundaries: List[Dict[str, object]],
    video_duration: float,
) -> Path:

    ensure_ffmpeg()

    if not input_video.exists():

        raise RuntimeError(
            f"Vidéo introuvable : {input_video}"
        )

    if not boundaries:

        # Aucun timing disponible.
        # On conserve la vidéo sans tenter
        # de construire un filtre vide.
        shutil.copy2(
            input_video,
            output_video,
        )

        return output_video

    subtitle_filter = (
        build_word_subtitle_filter(
            boundaries
        )
    )

    if not subtitle_filter:

        shutil.copy2(
            input_video,
            output_video,
        )

        return output_video

    output_video.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    command = [
        FFMPEG_BIN,
        "-y",
        "-i",
        str(input_video),
        "-vf",
        subtitle_filter,
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        str(VIDEO_CRF),
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        str(output_video),
    ]

    result = run_command(
        command,
        timeout=180,
    )

    if result.returncode != 0:

        raise RuntimeError(
            "Erreur FFmpeg pendant "
            "l'incrustation des sous-titres :\n"
            + result.stderr[-2500:]
        )

    if not output_video.exists():

        raise RuntimeError(
            "La vidéo avec sous-titres "
            "n'a pas été créée."
        )

    return output_video


# ============================================================
# MASCOTTE CERVEAU
# ============================================================

MASCOT_WIDTH = 210

MASCOT_BOTTOM_MARGIN = 55


def get_mascot_font(
    size: int,
):

    font_paths = [
        "/usr/share/fonts/truetype/dejavu/"
        "DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/"
        "LiberationSans-Bold.ttf",
    ]

    for font_path in font_paths:

        if Path(
            font_path
        ).exists():

            try:

                return ImageFont.truetype(
                    font_path,
                    size,
                )

            except Exception:
                pass

    return ImageFont.load_default()


def create_brain_mascot(
    output_path: Path,
    state: str = "normal",
    size: int = MASCOT_WIDTH,
) -> Path:

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    size = max(
        100,
        int(size),
    )

    image = Image.new(
        "RGBA",
        (
            size,
            size,
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

    # --------------------------------------------------------
    # Le cerveau est volontairement clairement identifiable.
    # --------------------------------------------------------

    margin = int(
        size * 0.08
    )

    brain_box = (
        margin,
        margin,
        size - margin,
        int(
            size * 0.78
        ),
    )

    # Silhouette principale.
    draw.ellipse(
        brain_box,
        fill=(
            126,
            91,
            180,
            255,
        ),
        outline=(
            55,
            35,
            90,
            255,
        ),
        width=max(
            3,
            int(size * 0.025),
        ),
    )

    # --------------------------------------------------------
    # Séparation centrale du cerveau.
    # --------------------------------------------------------

    center_x = size // 2

    draw.line(
        (
            center_x,
            int(size * 0.18),
            center_x,
            int(size * 0.70),
        ),
        fill=(
            70,
            45,
            110,
            255,
        ),
        width=max(
            2,
            int(size * 0.018),
        ),
    )

    # --------------------------------------------------------
    # Circonvolutions.
    # --------------------------------------------------------

    line_width = max(
        3,
        int(size * 0.018),
    )

    ridge_color = (
        210,
        177,
        235,
        255,
    )

    paths = [
        [
            (
                int(size * 0.18),
                int(size * 0.30),
            ),
            (
                int(size * 0.31),
                int(size * 0.22),
            ),
            (
                int(size * 0.38),
                int(size * 0.34),
            ),
        ],
        [
            (
                int(size * 0.15),
                int(size * 0.48),
            ),
            (
                int(size * 0.29),
                int(size * 0.42),
            ),
            (
                int(size * 0.38),
                int(size * 0.53),
            ),
        ],
        [
            (
                int(size * 0.62),
                int(size * 0.31),
            ),
            (
                int(size * 0.72),
                int(size * 0.22),
            ),
            (
                int(size * 0.83),
                int(size * 0.35),
            ),
        ],
        [
            (
                int(size * 0.62),
                int(size * 0.51),
            ),
            (
                int(size * 0.73),
                int(size * 0.43),
            ),
            (
                int(size * 0.84),
                int(size * 0.53),
            ),
        ],
    ]

    for points in paths:

        draw.line(
            points,
            fill=ridge_color,
            width=line_width,
            joint="curve",
        )

    # --------------------------------------------------------
    # Yeux.
    # --------------------------------------------------------

    eye_y = int(
        size * 0.57
    )

    left_x = int(
        size * 0.35
    )

    right_x = int(
        size * 0.65
    )

    eye_radius = max(
        5,
        int(size * 0.045),
    )

    # Expression selon l'état.
    if state == "surprised":

        eye_radius = max(
            7,
            int(size * 0.065),
        )

    elif state == "thinking":

        eye_y -= int(
            size * 0.025
        )

    elif state == "amused":

        eye_y += int(
            size * 0.01
        )

    for x in (
        left_x,
        right_x,
    ):

        draw.ellipse(
            (
                x - eye_radius,
                eye_y - eye_radius,
                x + eye_radius,
                eye_y + eye_radius,
            ),
            fill=(
                255,
                255,
                255,
                255,
            ),
        )

        pupil_radius = max(
            2,
            int(
                eye_radius * 0.45
            ),
        )

        pupil_offset = 0

        if state == "thinking":
            pupil_offset = -2

        if state == "amused":
            pupil_offset = 2

        draw.ellipse(
            (
                x
                - pupil_radius
                + pupil_offset,
                eye_y
                - pupil_radius,
                x
                + pupil_radius
                + pupil_offset,
                eye_y
                + pupil_radius,
            ),
            fill=(
                30,
                25,
                45,
                255,
            ),
        )

    # --------------------------------------------------------
    # Sourcils.
    # --------------------------------------------------------

    eyebrow_y = int(
        size * 0.47
    )

    eyebrow_width = max(
        3,
        int(size * 0.018),
    )

    if state == "surprised":

        draw.line(
            (
                int(size * 0.27),
                eyebrow_y - 8,
                int(size * 0.42),
                eyebrow_y - 13,
            ),
            fill=(
                45,
                30,
                65,
                255,
            ),
            width=eyebrow_width,
        )

        draw.line(
            (
                int(size * 0.58),
                eyebrow_y - 13,
                int(size * 0.73),
                eyebrow_y - 8,
            ),
            fill=(
                45,
                30,
                65,
                255,
            ),
            width=eyebrow_width,
        )

    elif state == "thinking":

        draw.line(
            (
                int(size * 0.27),
                eyebrow_y,
                int(size * 0.41),
                eyebrow_y - 5,
            ),
            fill=(
                45,
                30,
                65,
                255,
            ),
            width=eyebrow_width,
        )

        draw.line(
            (
                int(size * 0.59),
                eyebrow_y - 8,
                int(size * 0.73),
                eyebrow_y - 3,
            ),
            fill=(
                45,
                30,
                65,
                255,
            ),
            width=eyebrow_width,
        )

    # --------------------------------------------------------
    # Bouche.
    # --------------------------------------------------------

    mouth_y = int(
        size * 0.69
    )

    mouth_width = int(
        size * 0.18
    )

    if state == "talking":

        draw.ellipse(
            (
                center_x - mouth_width // 2,
                mouth_y - int(size * 0.035),
                center_x + mouth_width // 2,
                mouth_y + int(size * 0.055),
            ),
            fill=(
                50,
                25,
                55,
                255,
            ),
        )

    elif state == "surprised":

        draw.ellipse(
            (
                center_x - int(size * 0.045),
                mouth_y - int(size * 0.045),
                center_x + int(size * 0.045),
                mouth_y + int(size * 0.055),
            ),
            fill=(
                50,
                25,
                55,
                255,
            ),
        )

    elif state == "amused":

        draw.arc(
            (
                center_x - mouth_width,
                mouth_y - int(size * 0.03),
                center_x + mouth_width,
                mouth_y + int(size * 0.08),
            ),
            10,
            170,
            fill=(
                50,
                25,
                55,
                255,
            ),
            width=max(
                3,
                int(size * 0.02),
            ),
        )

    elif state == "conclusion":

        draw.arc(
            (
                center_x - mouth_width,
                mouth_y - int(size * 0.04),
                center_x + mouth_width,
                mouth_y + int(size * 0.09),
            ),
            10,
            170,
            fill=(
                50,
                25,
                55,
                255,
            ),
            width=max(
                3,
                int(size * 0.02),
            ),
        )

    else:

        draw.arc(
            (
                center_x - mouth_width,
                mouth_y - int(size * 0.02),
                center_x + mouth_width,
                mouth_y + int(size * 0.07),
            ),
            15,
            165,
            fill=(
                50,
                25,
                55,
                255,
            ),
            width=max(
                3,
                int(size * 0.018),
            ),
        )

    # --------------------------------------------------------
    # Petit badge sous le cerveau.
    # --------------------------------------------------------

    badge_font = get_mascot_font(
        max(
            12,
            int(size * 0.075),
        )
    )

    label = "CC"

    bbox = draw.textbbox(
        (
            0,
            0,
        ),
        label,
        font=badge_font,
    )

    label_width = (
        bbox[2] - bbox[0]
    )

    label_height = (
        bbox[3] - bbox[1]
    )

    badge_x = (
        size - label_width
    ) // 2

    badge_y = int(
        size * 0.80
    )

    draw.rounded_rectangle(
        (
            badge_x - 10,
            badge_y - 5,
            badge_x + label_width + 10,
            badge_y + label_height + 8,
        ),
        radius=8,
        fill=(
            44,
            38,
            75,
            245,
        ),
    )

    draw.text(
        (
            badge_x,
            badge_y,
        ),
        label,
        font=badge_font,
        fill=(
            255,
            255,
            255,
            255,
        ),
    )

    image.save(
        output_path,
        "PNG",
    )

    return output_path


def choose_mascot_state(
    index: int,
    total: int,
) -> str:

    if total <= 1:
        return "normal"

    progress = (
        index
        / max(
            1,
            total - 1,
        )
    )

    if progress < 0.15:
        return "surprised"

    if progress < 0.35:
        return "talking"

    if progress < 0.55:
        return "thinking"

    if progress < 0.75:
        return "amused"

    if progress < 0.90:
        return "talking"

    return "conclusion"


# ============================================================
# MASCOTTE ANIMÉE
# ============================================================

def create_mascot_overlay(
    input_video: Path,
    output_video: Path,
    boundaries: List[Dict[str, object]],
    video_duration: float,
) -> Path:

    ensure_ffmpeg()

    if not input_video.exists():

        raise RuntimeError(
            f"Vidéo introuvable : {input_video}"
        )

    output_video.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # On change d'expression plusieurs fois pendant la vidéo.
    #
    # La mascot est placée tout en bas, mais suffisamment
    # au-dessus des sous-titres pour éviter leur chevauchement.
    # --------------------------------------------------------

    duration = max(
        0.1,
        float(video_duration),
    )

    segment_count = max(
        1,
        min(
            8,
            int(
                math.ceil(
                    duration / 5.0
                )
            ),
        ),
    )

    segment_duration = (
        duration
        / segment_count
    )

    mascot_paths = []

    for index in range(
        segment_count
    ):

        state = choose_mascot_state(
            index,
            segment_count,
        )

        mascot_path = (
            TEMP_DIR
            / f"mascot_{int(time.time()*1000)}_"
            f"{index}_{state}.png"
        )

        create_brain_mascot(
            output_path=mascot_path,
            state=state,
            size=MASCOT_WIDTH,
        )

        mascot_paths.append(
            mascot_path
        )

    # --------------------------------------------------------
    # Filtergraph :
    #
    # Chaque mascot commence à son propre timestamp.
    # Elle ne reste donc PAS affichée pendant toute la vidéo.
    #
    # Le setpts + start/TB est essentiel.
    # --------------------------------------------------------

    inputs = [
        str(input_video)
    ]

    for mascot_path in mascot_paths:
        inputs.extend(
            [
                "-loop",
                "1",
                "-i",
                str(mascot_path),
            ]
        )

    filter_parts = [
        "[0:v]setpts=PTS-STARTPTS[base]"
    ]

    current_label = "base"

    for index in range(
        segment_count
    ):

        input_index = index + 1

        start = (
            index
            * segment_duration
        )

        seg_duration = min(
            segment_duration,
            duration - start,
        )

        if seg_duration <= 0:
            continue

        mascot_label = (
            f"mascot{index}"
        )

        output_label = (
            f"v{index}"
        )

        # ----------------------------------------------------
        # Animation légère de la mascot.
        #
        # Pas de zoompan lourd.
        # La rotation et le déplacement sont calculés
        # directement par FFmpeg.
        # ----------------------------------------------------

        filter_parts.append(
            f"[{input_index}:v]"
            f"trim=duration={seg_duration:.3f},"
            "setpts=PTS-STARTPTS,"
            "format=rgba,"
            f"rotate='0.025*sin(2*PI*t/1.8)':"
            "fillcolor=none,"
            f"setpts=PTS-STARTPTS+{start:.3f}/TB"
            f"[{mascot_label}]"
        )

        # ----------------------------------------------------
        # IMPORTANT :
        # La mascot est positionnée sous la zone principale
        # de la vidéo, mais au-dessus de la marge inférieure.
        #
        # Elle ne doit pas toucher la zone des sous-titres.
        # ----------------------------------------------------

        overlay_y = (
            "H-h-330"
        )

        filter_parts.append(
            f"[{current_label}]"
            f"[{mascot_label}]"
            "overlay="
            f"x=(W-w)/2:"
            f"y={overlay_y}:"
            "eof_action=pass:"
            "repeatlast=0:"
            f"shortest=0"
            f"[{output_label}]"
        )

        current_label = output_label

    filter_complex = ";".join(
        filter_parts
    )

    command = [
        FFMPEG_BIN,
        "-y",
    ]

    command.extend(
        [
            "-i",
            str(input_video),
        ]
    )

    for mascot_path in mascot_paths:

        command.extend(
            [
                "-loop",
                "1",
                "-i",
                str(mascot_path),
            ]
        )

    command.extend(
        [
            "-filter_complex",
            filter_complex,
            "-map",
            f"[{current_label}]",
            "-map",
            "0:a:0?",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            str(VIDEO_CRF),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            "-shortest",
            "-movflags",
            "+faststart",
            str(output_video),
        ]
    )

    result = run_command(
        command,
        timeout=180,
    )

    if result.returncode != 0:

        raise RuntimeError(
            "Erreur FFmpeg pendant "
            "l'ajout de la mascot :\n"
            + result.stderr[-3000:]
        )

    if not output_video.exists():

        raise RuntimeError(
            "La vidéo avec mascot "
            "n'a pas été créée."
        )

    # Nettoyage des mascots temporaires.
    for mascot_path in mascot_paths:

        try:

            mascot_path.unlink(
                missing_ok=True
            )

        except Exception:
            pass

    return output_video


# ============================================================
# EFFETS SONORES CONTEXTUELS
# ============================================================

SFX_SAMPLE_RATE = 44100


def create_sfx_tone(
    output_path: Path,
    kind: str,
    duration: float = 0.18,
) -> Path:

    ensure_ffmpeg()

    duration = max(
        0.04,
        min(
            0.8,
            float(duration),
        ),
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # Sons synthétiques très légers.
    #
    # Pas de musique de fond.
    # --------------------------------------------------------

    if kind == "impact":

        frequency = 110
        volume = 0.16

    elif kind == "question":

        frequency = 520
        volume = 0.10

    else:

        frequency = 760
        volume = 0.09

    filter_audio = (
        f"sine=frequency={frequency}:"
        f"sample_rate={SFX_SAMPLE_RATE}:"
        f"duration={duration},"
        "afade=t=in:st=0:d=0.02,"
        f"afade=t=out:st={max(0.01, duration-0.06):.3f}:d=0.06,"
        f"volume={volume}"
    )

    command = [
        FFMPEG_BIN,
        "-y",
        "-f",
        "lavfi",
        "-i",
        filter_audio,
        "-ar",
        str(SFX_SAMPLE_RATE),
        "-ac",
        "2",
        "-c:a",
        "pcm_s16le",
        str(output_path),
    ]

    result = run_command(
        command,
        timeout=30,
    )

    if result.returncode != 0:

        raise RuntimeError(
            "Impossible de créer le son :\n"
            + result.stderr[-1200:]
        )

    return output_path


def choose_sfx_events(
    script: str,
    boundaries: List[Dict[str, object]],
    max_events: int = 5,
) -> List[Dict[str, object]]:

    if not boundaries:
        return []

    script_lower = (
        script.lower()
    )

    events = []

    # --------------------------------------------------------
    # Hook.
    # --------------------------------------------------------

    if boundaries:

        first = boundaries[0]

        events.append(
            {
                "time": float(
                    first.get(
                        "start",
                        0.0,
                    )
                ),
                "kind": "reveal",
            }
        )

    # --------------------------------------------------------
    # Détection de formulations pouvant bénéficier
    # d'un petit accent sonore.
    # --------------------------------------------------------

    keywords_impact = (
        "jamais",
        "incroyable",
        "surprenant",
        "surprise",
        "attention",
        "important",
        "vraiment",
    )

    keywords_question = (
        "?",
        "pourquoi",
        "comment",
        "saviez-vous",
        "tu savais",
    )

    for boundary in boundaries:

        word = str(
            boundary.get(
                "word",
                "",
            )
        )

        lower = word.lower()

        if any(
            keyword in lower
            for keyword in keywords_impact
        ):

            events.append(
                {
                    "time": float(
                        boundary.get(
                            "start",
                            0.0,
                        )
                    ),
                    "kind": "impact",
                }
            )

        if any(
            keyword in lower
            for keyword in keywords_question
        ):

            events.append(
                {
                    "time": float(
                        boundary.get(
                            "start",
                            0.0,
                        )
                    ),
                    "kind": "question",
                }
            )

    # --------------------------------------------------------
    # Les questions dans le texte.
    # --------------------------------------------------------

    if "?" in script_lower:

        question_boundary = None

        for boundary in boundaries:

            word = str(
                boundary.get(
                    "word",
                    "",
                )
            )

            if "?" in word:

                question_boundary = boundary
                break

        if question_boundary:

            events.append(
                {
                    "time": float(
                        question_boundary.get(
                            "start",
                            0.0,
                        )
                    ),
                    "kind": "question",
                }
            )

    # --------------------------------------------------------
    # Tri + déduplication temporelle.
    # --------------------------------------------------------

    events.sort(
        key=lambda event: float(
            event.get(
                "time",
                0.0,
            )
        )
    )

    selected = []

    last_time = -999.0

    for event in events:

        event_time = float(
            event.get(
                "time",
                0.0,
            )
        )

        if (
            event_time
            - last_time
            < 2.5
        ):
            continue

        selected.append(
            event
        )

        last_time = event_time

        if len(selected) >= max_events:
            break

    return selected


def add_contextual_sfx(
    input_video: Path,
    output_video: Path,
    script: str,
    boundaries: List[Dict[str, object]],
    workdir: Path,
) -> Path:

    ensure_ffmpeg()

    if not input_video.exists():

        raise RuntimeError(
            f"Vidéo introuvable : {input_video}"
        )

    events = choose_sfx_events(
        script=script,
        boundaries=boundaries,
        max_events=5,
    )

    if not events:

        shutil.copy2(
            input_video,
            output_video,
        )

        return output_video

    workdir.mkdir(
        parents=True,
        exist_ok=True,
    )

    duration = get_video_duration(
        input_video
    )

    sfx_files = []

    valid_events = []

    for index, event in enumerate(
        events
    ):

        event_time = float(
            event.get(
                "time",
                0.0,
            )
        )

        if event_time < 0:
            continue

        if event_time >= duration:
            continue

        kind = str(
            event.get(
                "kind",
                "reveal",
            )
        )

        sfx_path = (
            workdir
            / f"sfx_{index}_{kind}.wav"
        )

        create_sfx_tone(
            output_path=sfx_path,
            kind=kind,
        )

        sfx_files.append(
            sfx_path
        )

        valid_events.append(
            (
                sfx_path,
                event_time,
            )
        )

    if not valid_events:

        shutil.copy2(
            input_video,
            output_video,
        )

        return output_video

    # --------------------------------------------------------
    # Entrée audio originale.
    # --------------------------------------------------------

    inputs = [
        "-i",
        str(input_video),
    ]

    for sfx_path, _ in valid_events:

        inputs.extend(
            [
                "-i",
                str(sfx_path),
            ]
        )

    filter_parts = [
        "[0:a]aresample=44100,"
        "aformat=sample_fmts=fltp:"
        "sample_rates=44100:"
        "channel_layouts=stereo[main]"
    ]

    mix_inputs = [
        "[main]"
    ]

    for index, (
        sfx_path,
        event_time,
    ) in enumerate(
        valid_events
    ):

        delay_ms = max(
            0,
            int(
                event_time
                * 1000
            ),
        )

        label = (
            f"sfx{index}"
        )

        filter_parts.append(
            f"[{index + 1}:a]"
            f"adelay={delay_ms}|{delay_ms},"
            "aresample=44100,"
            "aformat="
            "sample_fmts=fltp:"
            "sample_rates=44100:"
            "channel_layouts=stereo"
            f"[{label}]"
        )

        mix_inputs.append(
            f"[{label}]"
        )

    filter_parts.append(
        "".join(
            mix_inputs
        )
        + f"amix=inputs={len(mix_inputs)}:"
        "duration=first:"
        "dropout_transition=0:"
        "normalize=0,"
        "alimiter=limit=0.95"
        "[mixed]"
    )

    filter_complex = ";".join(
        filter_parts
    )

    command = [
        FFMPEG_BIN,
        "-y",
    ]

    command.extend(
        inputs
    )

    command.extend(
        [
            "-filter_complex",
            filter_complex,
            "-map",
            "0:v:0",
            "-map",
            "[mixed]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            AUDIO_BITRATE,
            "-movflags",
            "+faststart",
            str(output_video),
        ]
    )

    result = run_command(
        command,
        timeout=120,
    )

    if result.returncode != 0:

        raise RuntimeError(
            "Erreur FFmpeg pendant "
            "l'ajout des effets sonores :\n"
            + result.stderr[-2500:]
        )

    if not output_video.exists():

        raise RuntimeError(
            "La vidéo avec effets sonores "
            "n'a pas été créée."
        )

    # Nettoyage.
    for sfx_path in sfx_files:

        try:

            sfx_path.unlink(
                missing_ok=True
            )

        except Exception:
            pass

    return output_video


# ============================================================
# FIN DE LA PARTIE 4/6
# ============================================================# ============================================================
# PARTIE 5/6 — PIPELINE DE PRODUCTION VIDÉO
# ============================================================


# ============================================================
# CRÉATION DU DOSSIER DE TRAVAIL
# ============================================================

def create_job_directory(
    prefix: str = "video_job",
) -> Path:

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S_%f"
    )

    job_dir = (
        TEMP_DIR
        / f"{prefix}_{timestamp}"
    )

    job_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    return job_dir


# ============================================================
# NETTOYAGE D'UN DOSSIER DE TRAVAIL
# ============================================================

def cleanup_job_directory(
    job_dir: Optional[Path],
) -> None:

    if not job_dir:
        return

    try:

        job_dir = Path(
            job_dir
        )

        if job_dir.exists():

            shutil.rmtree(
                job_dir,
                ignore_errors=True,
            )

    except Exception:
        pass


# ============================================================
# NETTOYAGE DES ANCIENS FICHIERS TEMPORAIRES
# ============================================================

def cleanup_old_temp_files(
    max_age_hours: int = 24,
) -> None:

    try:

        if not TEMP_DIR.exists():
            return

        now = time.time()

        max_age_seconds = (
            max_age_hours * 3600
        )

        for path in TEMP_DIR.iterdir():

            try:

                age = (
                    now
                    - path.stat().st_mtime
                )

                if age <= max_age_seconds:
                    continue

                if path.is_dir():

                    shutil.rmtree(
                        path,
                        ignore_errors=True,
                    )

                elif path.is_file():

                    path.unlink(
                        missing_ok=True
                    )

            except Exception:
                continue

    except Exception:
        pass


# ============================================================
# PRÉPARATION DU SCRIPT FINAL
# ============================================================

def prepare_final_script(
    script: str,
) -> str:

    script = clean_script_for_video(
        script
    )

    script = remove_internal_markers(
        script
    )

    script = normalize_text(
        script
    )

    if not script:

        raise RuntimeError(
            "Le script final est vide."
        )

    script = ensure_cta(
        script
    )

    script = remove_internal_markers(
        script
    )

    script = normalize_text(
        script
    )

    return script


# ============================================================
# GÉNÉRATION DE LA NARRATION
# ============================================================

def create_video_narration(
    script: str,
    job_dir: Path,
    voice: Optional[str] = None,
) -> Tuple[Path, float]:

    script = normalize_text(
        script
    )

    if not script:

        raise RuntimeError(
            "Impossible de générer une narration "
            "avec un script vide."
        )

    audio_path = (
        job_dir
        / "narration.mp3"
    )

    narration_path = create_narration(
        text=script,
        output_path=audio_path,
        voice=voice,
        rate="+2%",
    )

    duration = get_audio_duration(
        narration_path
    )

    return (
        narration_path,
        duration,
    )


# ============================================================
# LIMITATION DE LA DURÉE D'UN SHORT
# ============================================================

def adapt_script_to_short_duration(
    script: str,
    max_seconds: float = SHORT_MAX_SECONDS,
) -> str:

    script = normalize_text(
        script
    )

    if not script:
        return ""

    # --------------------------------------------------------
    # On ne coupe jamais arbitrairement un texte déjà correct.
    #
    # Cette fonction sert uniquement de garde-fou si le texte
    # produit une narration trop longue pour un Short.
    # --------------------------------------------------------

    estimated_seconds = (
        count_words(script)
        / 2.35
    )

    if estimated_seconds <= max_seconds:

        return script

    sentences = re.split(
        r"(?<=[.!?])\s+",
        script,
    )

    sentences = [
        normalize_text(
            sentence
        )
        for sentence in sentences
        if normalize_text(
            sentence
        )
    ]

    if not sentences:

        return script

    selected = []

    current_words = 0

    # Environ 2,35 mots/seconde.
    max_words = max(
        SHORT_MIN_WORDS,
        int(
            max_seconds
            * 2.35
        ),
    )

    for sentence in sentences:

        sentence_words = count_words(
            sentence
        )

        if not selected:

            selected.append(
                sentence
            )

            current_words += (
                sentence_words
            )

            continue

        if (
            current_words
            + sentence_words
            > max_words
        ):

            break

        selected.append(
            sentence
        )

        current_words += (
            sentence_words
        )

    result = normalize_text(
        " ".join(
            selected
        )
    )

    if not result:
        return script

    return result


# ============================================================
# ADAPTATION GÉNÉRALE DU SCRIPT
# ============================================================

def adapt_script_for_format(
    script: str,
    requested_format: str = "auto",
) -> Tuple[str, str]:

    script = prepare_final_script(
        script
    )

    requested_format = (
        str(
            requested_format
            or "auto"
        )
        .strip()
        .lower()
    )

    # --------------------------------------------------------
    # Le script reste la source principale.
    # On ne rejette pas un script simplement parce qu'il est
    # plus court ou plus long que prévu.
    # --------------------------------------------------------

    if requested_format in (
        "short",
        "portrait",
        "vertical",
    ):

        script = adapt_script_to_short_duration(
            script
        )

        return (
            script,
            "portrait",
        )

    if requested_format in (
        "long",
        "landscape",
        "horizontal",
    ):

        return (
            script,
            "landscape",
        )

    # --------------------------------------------------------
    # AUTO
    # --------------------------------------------------------

    words = count_words(
        script
    )

    # Un script suffisamment long devient horizontal.
    # Sinon, il est traité comme Short.
    if words >= LONG_MIN:

        return (
            script,
            "landscape",
        )

    return (
        script,
        "portrait",
    )


# ============================================================
# VÉRIFICATION DES TIMINGS MOT PAR MOT
# ============================================================

def sanitize_word_boundaries(
    boundaries: List[Dict[str, object]],
    duration: float,
) -> List[Dict[str, object]]:

    if not boundaries:
        return []

    duration = max(
        0.1,
        float(duration),
    )

    result = []

    for boundary in boundaries:

        if not isinstance(
            boundary,
            dict,
        ):
            continue

        word = clean_subtitle_word(
            str(
                boundary.get(
                    "word",
                    "",
                )
            )
        )

        if not word:
            continue

        try:

            start = float(
                boundary.get(
                    "start",
                    0.0,
                )
            )

            end = float(
                boundary.get(
                    "end",
                    start + 0.05,
                )
            )

        except (
            ValueError,
            TypeError,
        ):

            continue

        start = max(
            0.0,
            min(
                start,
                duration,
            ),
        )

        end = max(
            start + 0.03,
            end,
        )

        end = min(
            duration,
            end,
        )

        if end <= start:
            continue

        result.append(
            {
                "word": word,
                "start": start,
                "end": end,
            }
        )

    if result:

        result[-1]["end"] = duration

    return result


# ============================================================
# CONSTRUCTION DES VISUELS
# ============================================================

def prepare_video_scenes(
    script: str,
    word_boundaries: List[Dict[str, object]],
    duration: float,
    job_dir: Path,
    video_format: str,
) -> List[Dict[str, object]]:

    scenes = build_narration_scene_boundaries(
        script=script,
        word_boundaries=word_boundaries,
        total_duration=duration,
    )

    if not scenes:

        # Fallback de sécurité.
        scenes = [
            {
                "text": script,
                "visual": script,
                "start": 0.0,
                "end": duration,
            }
        ]

    scenes = rebalance_scene_durations(
        scenes=scenes,
        total_duration=duration,
    )

    width, height = (
        get_video_dimensions_for_format(
            video_format
        )
    )

    portrait = (
        video_format == "portrait"
    )

    visual_dir = (
        job_dir
        / "visuals"
    )

    scenes = ensure_scene_visuals(
        scenes=scenes,
        work_dir=visual_dir,
        width=width,
        height=height,
        portrait=portrait,
    )

    if not scenes:

        fallback_path = (
            visual_dir
            / "fallback.jpg"
        )

        create_fallback_visual(
            output_path=fallback_path,
            width=width,
            height=height,
        )

        scenes = [
            {
                "text": script,
                "visual": script,
                "start": 0.0,
                "end": duration,
                "visual_path": fallback_path,
            }
        ]

    return scenes


# ============================================================
# CONSTRUCTION DE LA VIDÉO DE BASE
# ============================================================

def build_base_video(
    scenes: List[Dict[str, object]],
    job_dir: Path,
    video_format: str,
) -> Path:

    width, height = (
        get_video_dimensions_for_format(
            video_format
        )
    )

    clips_dir = (
        job_dir
        / "clips"
    )

    clips = create_scene_clips(
        scenes=scenes,
        work_dir=clips_dir,
        width=width,
        height=height,
    )

    if not clips:

        raise RuntimeError(
            "Aucun plan vidéo n'a pu être créé."
        )

    silent_video = (
        job_dir
        / "video_silent.mp4"
    )

    concat_videos(
        clips=clips,
        output_path=silent_video,
    )

    return silent_video


# ============================================================
# AJOUT DE LA NARRATION
# ============================================================

def add_video_narration(
    silent_video: Path,
    narration_path: Path,
    job_dir: Path,
) -> Path:

    narrated_video = (
        job_dir
        / "video_narrated.mp4"
    )

    mux_narration(
        video_path=silent_video,
        audio_path=narration_path,
        output_path=narrated_video,
    )

    return narrated_video


# ============================================================
# PIPELINE PRINCIPAL
# ============================================================

def build_video(
    script: str,
    job_dir: Path,
    requested_format: str = "auto",
    progress_callback=None,
) -> Dict[str, object]:

    ensure_ffmpeg()

    job_dir = Path(
        job_dir
    )

    job_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    def progress(
        message: str,
    ) -> None:

        if progress_callback:

            try:

                progress_callback(
                    message
                )

            except Exception:
                pass

    progress(
        "Préparation du script..."
    )

    script, video_format = (
        adapt_script_for_format(
            script=script,
            requested_format=requested_format,
        )
    )

    if not script:

        raise RuntimeError(
            "Le script final est vide."
        )

    progress(
        "Génération de la narration..."
    )

    narration_path, duration = (
        create_video_narration(
            script=script,
            job_dir=job_dir,
        )
    )

    # --------------------------------------------------------
    # Sécurité Short.
    # --------------------------------------------------------

    if video_format == "portrait":

        if duration < SHORT_MIN_SECONDS:

            progress(
                "Le Short est très court, "
                "adaptation conservée."
            )

        elif duration > SHORT_MAX_SECONDS:

            progress(
                "Le Short dépasse légèrement "
                "la durée cible, adaptation..."
            )

            adapted_script = (
                adapt_script_to_short_duration(
                    script,
                    SHORT_MAX_SECONDS,
                )
            )

            if (
                adapted_script
                and adapted_script != script
            ):

                script = adapted_script

                narration_path, duration = (
                    create_video_narration(
                        script=script,
                        job_dir=job_dir,
                    )
                )

    progress(
        "Calcul des timings mot par mot..."
    )

    boundaries = get_word_boundaries(
        text=script,
        audio_path=narration_path,
        voice=select_french_voice(),
        rate="+2%",
    )

    boundaries = sanitize_word_boundaries(
        boundaries=boundaries,
        duration=duration,
    )

    if not boundaries:

        raise RuntimeError(
            "Impossible d'obtenir les timings "
            "mot par mot de la narration."
        )

    progress(
        "Préparation des scènes et des visuels..."
    )

    scenes = prepare_video_scenes(
        script=script,
        word_boundaries=boundaries,
        duration=duration,
        job_dir=job_dir,
        video_format=video_format,
    )

    progress(
        f"{len(scenes)} scène(s) préparée(s)."
    )

    progress(
        "Assemblage des plans vidéo..."
    )

    silent_video = build_base_video(
        scenes=scenes,
        job_dir=job_dir,
        video_format=video_format,
    )

    progress(
        "Ajout de la narration..."
    )

    narrated_video = add_video_narration(
        silent_video=silent_video,
        narration_path=narration_path,
        job_dir=job_dir,
    )

    # --------------------------------------------------------
    # Normalisation audio.
    # --------------------------------------------------------

    progress(
        "Normalisation audio..."
    )

    normalized_video = (
        job_dir
        / "video_normalized.mp4"
    )

    normalize_audio_video(
        input_video=narrated_video,
        output_path=normalized_video,
    )

    # --------------------------------------------------------
    # Sous-titres mot par mot.
    # --------------------------------------------------------

    progress(
        "Incrustation des sous-titres mot par mot..."
    )

    subtitle_video = (
        job_dir
        / "video_subtitles.mp4"
    )

    burn_word_by_word_subtitles(
        input_video=normalized_video,
        output_video=subtitle_video,
        boundaries=boundaries,
        video_duration=duration,
    )

    # --------------------------------------------------------
    # Mascotte.
    # --------------------------------------------------------

    progress(
        "Animation de la mascotte cerveau..."
    )

    mascot_video = (
        job_dir
        / "video_mascot.mp4"
    )

    create_mascot_overlay(
        input_video=subtitle_video,
        output_video=mascot_video,
        boundaries=boundaries,
        video_duration=duration,
    )

    # --------------------------------------------------------
    # Effets sonores contextuels.
    # --------------------------------------------------------

    progress(
        "Ajout des effets sonores contextuels..."
    )

    sfx_video = (
        job_dir
        / "video_sfx.mp4"
    )

    add_contextual_sfx(
        input_video=mascot_video,
        output_video=sfx_video,
        script=script,
        boundaries=boundaries,
        workdir=job_dir / "sfx",
    )

    # --------------------------------------------------------
    # Validation finale.
    # --------------------------------------------------------

    progress(
        "Validation de la vidéo finale..."
    )

    validate_video_output(
        video_path=sfx_video,
        expected_duration=duration,
    )

    final_width, final_height = (
        get_video_dimensions(
            sfx_video
        )
    )

    expected_width, expected_height = (
        get_video_dimensions_for_format(
            video_format
        )
    )

    if (
        final_width != expected_width
        or final_height != expected_height
    ):

        raise RuntimeError(
            "Les dimensions finales sont incorrectes : "
            f"{final_width}x{final_height} "
            f"au lieu de "
            f"{expected_width}x{expected_height}."
        )

    progress(
        "Production terminée."
    )

    return {
        "video_path": sfx_video,
        "script": script,
        "duration": duration,
        "format": video_format,
        "width": final_width,
        "height": final_height,
        "scenes": scenes,
        "boundaries": boundaries,
    }


# ============================================================
# CRÉATION D'UN SHORT
# ============================================================

def create_short_video(
    script: str,
    job_dir: Path,
    progress_callback=None,
) -> Dict[str, object]:

    return build_video(
        script=script,
        job_dir=job_dir,
        requested_format="short",
        progress_callback=progress_callback,
    )


# ============================================================
# CRÉATION D'UNE VIDÉO LONGUE
# ============================================================

def create_long_video(
    script: str,
    job_dir: Path,
    progress_callback=None,
) -> Dict[str, object]:

    return build_video(
        script=script,
        job_dir=job_dir,
        requested_format="long",
        progress_callback=progress_callback,
    )


# ============================================================
# NOM DU FICHIER FINAL
# ============================================================

def generate_video_filename(
    topic: str,
    video_format: str,
) -> str:

    topic = normalize_text(
        topic
    )

    topic = unicodedata.normalize(
        "NFKD",
        topic,
    )

    topic = "".join(
        char
        for char in topic
        if not unicodedata.combining(
            char
        )
    )

    topic = re.sub(
        r"[^a-zA-Z0-9]+",
        "_",
        topic,
    ).strip(
        "_"
    )

    if not topic:
        topic = "cerveau_curieux"

    topic = topic[:60]

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    suffix = (
        "short"
        if video_format == "portrait"
        else "long"
    )

    return (
        f"{topic}_{suffix}_{timestamp}.mp4"
    )


# ============================================================
# COPIE VERS OUTPUTS
# ============================================================

def save_final_video(
    video_path: Path,
    topic: str,
    video_format: str,
) -> Path:

    video_path = Path(
        video_path
    )

    if not video_path.exists():

        raise RuntimeError(
            "La vidéo finale à sauvegarder "
            "est introuvable."
        )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    filename = generate_video_filename(
        topic=topic,
        video_format=video_format,
    )

    output_path = (
        OUTPUT_DIR
        / filename
    )

    shutil.copy2(
        video_path,
        output_path,
    )

    if not output_path.exists():

        raise RuntimeError(
            "Impossible de sauvegarder "
            "la vidéo finale."
        )

    if output_path.stat().st_size <= 10_000:

        raise RuntimeError(
            "La vidéo sauvegardée semble invalide."
        )

    return output_path


# ============================================================
# GÉNÉRATION COMPLÈTE À PARTIR D'UN SUJET
# ============================================================

def generate_video_from_topic(
    topic: str,
    requested_format: str = "auto",
    progress_callback=None,
) -> Dict[str, object]:

    topic = normalize_text(
        topic
    )

    if not topic:

        raise ValueError(
            "Le sujet est vide."
        )

    cleanup_old_temp_files()

    job_dir = create_job_directory()

    try:

        if progress_callback:

            progress_callback(
                "Génération du script..."
            )

        script = generate_main_script(
            topic
        )

        if not script:

            raise RuntimeError(
                "L'IA n'a généré aucun script."
            )

        result = build_video(
            script=script,
            job_dir=job_dir,
            requested_format=requested_format,
            progress_callback=progress_callback,
        )

        final_path = save_final_video(
            video_path=Path(
                result["video_path"]
            ),
            topic=topic,
            video_format=str(
                result["format"]
            ),
        )

        result[
            "video_path"
        ] = final_path

        result[
            "job_dir"
        ] = job_dir

        return result

    except Exception:

        cleanup_job_directory(
            job_dir
        )

        raise


# ============================================================
# FIN DE LA PARTIE 5/6
# ============================================================# ============================================================
# PARTIE 6/6 — INTERFACE STREAMLIT
# ============================================================


# ============================================================
# ÉTAT DE SESSION
# ============================================================

def init_session_state() -> None:

    defaults = {
        "generated_video": None,
        "generated_script": "",
        "generated_duration": 0.0,
        "generated_format": "",
        "generation_running": False,
        "generation_error": None,
        "last_topic": "",
        "status_messages": [],
    }

    for key, value in defaults.items():

        if key not in st.session_state:

            st.session_state[key] = value


# ============================================================
# RÉINITIALISATION DU RÉSULTAT
# ============================================================

def reset_generation_result() -> None:

    st.session_state.generated_video = None
    st.session_state.generated_script = ""
    st.session_state.generated_duration = 0.0
    st.session_state.generated_format = ""
    st.session_state.generation_error = None
    st.session_state.status_messages = []


# ============================================================
# CALLBACK DE PROGRESSION
# ============================================================

def create_progress_callback(
    status_container,
):

    def callback(
        message: str,
    ) -> None:

        message = normalize_text(
            message
        )

        if not message:
            return

        st.session_state.status_messages.append(
            message
        )

        try:

            status_container.write(
                f"• {message}"
            )

        except Exception:
            pass

    return callback


# ============================================================
# STYLE DE L'APPLICATION
# ============================================================

def render_custom_css() -> None:

    st.markdown(
        """
        <style>

        .main-title {
            text-align: center;
            font-size: 3rem;
            font-weight: 800;
            margin-bottom: 0.2rem;
        }

        .main-subtitle {
            text-align: center;
            font-size: 1.1rem;
            opacity: 0.75;
            margin-bottom: 2rem;
        }

        .feature-card {
            padding: 1rem;
            border-radius: 16px;
            border: 1px solid rgba(128,128,128,0.22);
            margin-bottom: 1rem;
        }

        .success-card {
            padding: 1rem;
            border-radius: 16px;
            border: 1px solid rgba(80,180,100,0.35);
            margin-top: 1rem;
        }

        .small-muted {
            opacity: 0.7;
            font-size: 0.9rem;
        }

        </style>
        """,
        unsafe_allow_html=True,
    )


# ============================================================
# EN-TÊTE
# ============================================================

def render_header() -> None:

    st.markdown(
        '<div class="main-title">🧠 Cerveau Curieux</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="main-subtitle">'
        "Psychologie • Neurosciences • Comportement humain"
        "</div>",
        unsafe_allow_html=True,
    )


# ============================================================
# BARRE LATÉRALE
# ============================================================

def render_sidebar() -> str:

    with st.sidebar:

        st.header(
            "⚙️ Configuration"
        )

        openrouter_ok = bool(
            OPENROUTER_API_KEY
        )

        pexels_ok = bool(
            PEXELS_API_KEY
        )

        ffmpeg_ok = bool(
            shutil.which("ffmpeg")
        )

        ffprobe_ok = bool(
            shutil.which("ffprobe")
        )

        st.write(
            "OpenRouter : "
            + (
                "✅ connecté"
                if openrouter_ok
                else "❌ absent"
            )
        )

        st.write(
            "Pexels : "
            + (
                "✅ connecté"
                if pexels_ok
                else "⚠️ absent"
            )
        )

        st.write(
            "FFmpeg : "
            + (
                "✅ disponible"
                if ffmpeg_ok
                else "❌ absent"
            )
        )

        st.write(
            "FFprobe : "
            + (
                "✅ disponible"
                if ffprobe_ok
                else "❌ absent"
            )
        )

        st.divider()

        st.subheader(
            "Format"
        )

        format_choice = st.radio(
            "Choisissez le format",
            options=[
                "Automatique",
                "Short vertical",
                "Vidéo longue",
            ],
            index=0,
        )

        if format_choice == "Short vertical":

            return "short"

        if format_choice == "Vidéo longue":

            return "long"

        return "auto"


# ============================================================
# VÉRIFICATION DE LA CONFIGURATION
# ============================================================

def validate_configuration() -> None:

    if not OPENROUTER_API_KEY:

        raise RuntimeError(
            "OPENROUTER_API_KEY est absente. "
            "Ajoutez-la dans les secrets Streamlit."
        )

    ensure_ffmpeg()


# ============================================================
# AFFICHAGE DU RÉSULTAT
# ============================================================

def render_generation_result() -> None:

    video_path = (
        st.session_state.get(
            "generated_video"
        )
    )

    if not video_path:
        return

    video_path = Path(
        video_path
    )

    if not video_path.exists():

        st.warning(
            "La vidéo générée n'est plus disponible."
        )

        return

    st.divider()

    st.subheader(
        "🎬 Vidéo générée"
    )

    duration = float(
        st.session_state.get(
            "generated_duration",
            0.0,
        )
        or 0.0
    )

    video_format = (
        st.session_state.get(
            "generated_format",
            "",
        )
    )

    script = (
        st.session_state.get(
            "generated_script",
            "",
        )
    )

    col1, col2, col3 = st.columns(3)

    with col1:

        st.metric(
            "Durée",
            f"{duration:.1f} s",
        )

    with col2:

        if video_format == "portrait":

            label = "Short 9:16"

        else:

            label = "Vidéo 16:9"

        st.metric(
            "Format",
            label,
        )

    with col3:

        st.metric(
            "Taille",
            f"{video_path.stat().st_size / 1024 / 1024:.1f} MB",
        )

    st.video(
        str(video_path)
    )

    st.download_button(
        label="⬇️ Télécharger la vidéo",
        data=video_path.read_bytes(),
        file_name=video_path.name,
        mime="video/mp4",
        use_container_width=True,
    )

    if script:

        with st.expander(
            "📜 Voir le script utilisé"
        ):

            st.write(
                script
            )


# ============================================================
# AFFICHAGE D'UNE ERREUR
# ============================================================

def render_generation_error() -> None:

    error = (
        st.session_state.get(
            "generation_error"
        )
    )

    if not error:
        return

    st.error(
        "❌ La génération a échoué."
    )

    with st.expander(
        "Détails de l'erreur"
    ):

        st.code(
            str(error)
        )


# ============================================================
# LANCEMENT DE LA GÉNÉRATION
# ============================================================

def run_generation(
    topic: str,
    requested_format: str,
) -> None:

    if st.session_state.get(
        "generation_running",
        False,
    ):

        return

    topic = normalize_text(
        topic
    )

    if not topic:

        st.warning(
            "Veuillez entrer un sujet."
        )

        return

    st.session_state.generation_running = True
    st.session_state.generation_error = None
    st.session_state.generated_video = None
    st.session_state.status_messages = []
    st.session_state.last_topic = topic

    status_container = st.empty()

    progress_bar = st.progress(
        0
    )

    progress_steps = [
        "Génération du script...",
        "Préparation du script...",
        "Génération de la narration...",
        "Calcul des timings mot par mot...",
        "Préparation des scènes et des visuels...",
        "Assemblage des plans vidéo...",
        "Ajout de la narration...",
        "Normalisation audio...",
        "Incrustation des sous-titres mot par mot...",
        "Animation de la mascotte cerveau...",
        "Ajout des effets sonores contextuels...",
        "Validation de la vidéo finale...",
        "Production terminée.",
    ]

    current_progress = 0

    def progress_callback(
        message: str,
    ) -> None:

        nonlocal current_progress

        message = normalize_text(
            message
        )

        if not message:
            return

        st.session_state.status_messages.append(
            message
        )

        status_container.info(
            f"⚙️ {message}"
        )

        matching_index = None

        for index, step in enumerate(
            progress_steps
        ):

            if step.lower() in message.lower():

                matching_index = index
                break

        if matching_index is not None:

            current_progress = max(
                current_progress,
                matching_index + 1,
            )

            progress_bar.progress(
                min(
                    1.0,
                    current_progress
                    / len(progress_steps),
                )
            )

    job_dir = None

    try:

        validate_configuration()

        # ----------------------------------------------------
        # Le dossier de travail est créé ici uniquement pour
        # permettre au finally de toujours le nettoyer.
        # ----------------------------------------------------

        job_dir = create_job_directory(
            prefix="studio_video"
        )

        progress_callback(
            "Génération du script..."
        )

        script = generate_main_script(
            topic
        )

        if not script:

            raise RuntimeError(
                "L'IA n'a généré aucun script exploitable."
            )

        script = prepare_final_script(
            script
        )

        if not script:

            raise RuntimeError(
                "Le script final est vide."
            )

        progress_callback(
            "Script généré. Préparation de la vidéo..."
        )

        result = build_video(
            script=script,
            job_dir=job_dir,
            requested_format=requested_format,
            progress_callback=progress_callback,
        )

        video_path = Path(
            result[
                "video_path"
            ]
        )

        if not video_path.exists():

            raise RuntimeError(
                "La vidéo finale n'existe pas après "
                "la production."
            )

        progress_callback(
            "Sauvegarde de la vidéo..."
        )

        final_path = save_final_video(
            video_path=video_path,
            topic=topic,
            video_format=str(
                result.get(
                    "format",
                    "portrait",
                )
            ),
        )

        validate_video_output(
            final_path,
            expected_duration=float(
                result.get(
                    "duration",
                    0.0,
                )
            ),
        )

        st.session_state.generated_video = str(
            final_path
        )

        st.session_state.generated_script = str(
            result.get(
                "script",
                script,
            )
        )

        st.session_state.generated_duration = float(
            result.get(
                "duration",
                0.0,
            )
        )

        st.session_state.generated_format = str(
            result.get(
                "format",
                "portrait",
            )
        )

        st.session_state.generation_error = None

        progress_bar.progress(
            1.0
        )

        status_container.success(
            "✅ Production terminée."
        )

    except Exception as exc:

        st.session_state.generation_error = (
            str(exc)
        )

        status_container.error(
            "❌ La génération a échoué."
        )

    finally:

        # ----------------------------------------------------
        # Nettoyage garanti.
        #
        # Même si FFmpeg, Edge-TTS, Pexels ou OpenRouter
        # provoque une exception, le dossier de travail
        # temporaire est supprimé.
        # ----------------------------------------------------

        cleanup_job_directory(
            job_dir
        )

        st.session_state.generation_running = False


# ============================================================
# INTERFACE PRINCIPALE
# ============================================================

def render_main_interface(
    requested_format: str,
) -> None:

    st.markdown(
        "### 🎯 Créez votre prochaine vidéo"
    )

    st.write(
        "Entrez un sujet de psychologie, "
        "de neurosciences ou de comportement humain."
    )

    topic = st.text_area(
        "Sujet de la vidéo",
        placeholder=(
            "Exemple : "
            "Pourquoi notre cerveau se souvient-il "
            "mieux des choses surprenantes ?"
        ),
        height=100,
        key="topic_input",
    )

    st.caption(
        "Le script sera adapté automatiquement "
        "au format choisi."
    )

    generation_disabled = (
        st.session_state.get(
            "generation_running",
            False,
        )
        or not bool(
            OPENROUTER_API_KEY
        )
    )

    button = st.button(
        "🚀 Générer la vidéo",
        type="primary",
        use_container_width=True,
        disabled=generation_disabled,
    )

    if button:

        reset_generation_result()

        run_generation(
            topic=topic,
            requested_format=requested_format,
        )

    render_generation_error()

    render_generation_result()


# ============================================================
# APPLICATION PRINCIPALE
# ============================================================

def main() -> None:

    st.set_page_config(
        page_title=APP_TITLE,
        page_icon="🧠",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    init_session_state()

    render_custom_css()

    render_header()

    requested_format = render_sidebar()

    st.divider()

    render_main_interface(
        requested_format=requested_format
    )


# ============================================================
# POINT D'ENTRÉE
# ============================================================

if __name__ == "__main__":

    main()


# ============================================================
# FIN DE LA PARTIE 6/6
# ============================================================
