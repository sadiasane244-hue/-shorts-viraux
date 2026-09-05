import os
import re
import json
import time
import math
import shutil
import random
import asyncio
import subprocess
from pathlib import Path
from typing import List, Dict, Tuple, Optional

import requests
import streamlit as st
from PIL import Image, ImageDraw, ImageFont
import edge_tts


# ============================================================
# CONFIGURATION GÉNÉRALE
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
# SEUILS DE LONGUEUR
# ============================================================

REGENERATE_BELOW = 200

ONE_SHORT_MIN = 200
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

def get_secret(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name)

        if value:
            return str(value)

    except Exception:
        pass

    return os.getenv(name, default)


OPENROUTER_API_KEY = get_secret("OPENROUTER_API_KEY")
PEXELS_API_KEY = get_secret("PEXELS_API_KEY")


# ============================================================
# OUTILS TEXTE
# ============================================================

def normalize_text(text: str) -> str:
    if not text:
        return ""

    text = str(text)

    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def count_words(text: str) -> int:
    text = normalize_text(text)

    if not text:
        return 0

    return len(
        re.findall(
            r"\b[\wÀ-ÿ'-]+\b",
            text,
        )
    )


def clean_ai_text(text: str) -> str:
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

    return normalize_text(text)


def extract_json_object(text: str) -> Optional[dict]:
    if not text:
        return None

    text = text.strip()

    try:
        return json.loads(text)

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
            "Vérifiez que ffmpeg est présent dans apt.txt."
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

        if isinstance(data, dict):

            error = data.get("error")

            if isinstance(error, dict):

                message = error.get("message")

                if message:
                    return str(message)

            message = data.get("message")

            if message:
                return str(message)

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

    except (ValueError, TypeError):
        return None


def openrouter_request(
    messages: List[Dict[str, str]],
    temperature: float = 0.7,
    max_tokens: int = 1800,
    timeout: int = 75,
    max_retries: int = 1,
) -> str:
    """
    Appel OpenRouter avec protection contre les erreurs
    temporaires et les 429.

    OpenRouter gère déjà le fallback entre fournisseurs
    et peut utiliser plusieurs modèles grâce à `models`.
    """

    if not OPENROUTER_API_KEY:

        raise RuntimeError(
            "OPENROUTER_API_KEY est introuvable. "
            "Ajoutez-la dans les secrets Render."
        )

    headers = {
        "Authorization": (
            f"Bearer {OPENROUTER_API_KEY}"
        ),
        "Content-Type": "application/json",
        "HTTP-Referer": (
            "https://shorts-viraux-1.onrender.com"
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

    for attempt in range(total_attempts):

        if attempt > 0:

            wait_time = min(
                2 + attempt * 2,
                6,
            )

            st.info(
                "Nouvelle tentative OpenRouter "
                f"dans {wait_time} seconde(s)..."
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
                f"OpenRouter n'a pas répondu dans "
                f"le délai de {timeout} secondes."
            )

            if attempt + 1 >= total_attempts:
                raise RuntimeError(
                    last_error
                ) from exc

            st.warning(
                "OpenRouter met trop de temps "
                "à répondre. Nouvelle tentative."
            )

            continue

        except requests.RequestException as exc:

            last_error = (
                f"Erreur réseau OpenRouter : {exc}"
            )

            if attempt + 1 >= total_attempts:
                raise RuntimeError(
                    last_error
                ) from exc

            st.warning(
                "La connexion à OpenRouter a été "
                "interrompue. Nouvelle tentative."
            )

            continue

        # ----------------------------------------------------
        # SUCCÈS
        # ----------------------------------------------------

        if response.status_code == 200:

            try:
                data = response.json()

            except Exception as exc:

                raise RuntimeError(
                    "OpenRouter a renvoyé un JSON invalide."
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
                    "OpenRouter a répondu sans "
                    "contenu exploitable."
                )

            used_model = data.get(
                "model"
            )

            if used_model:

                st.caption(
                    f"Modèle IA utilisé : {used_model}"
                )

            return content

        # ----------------------------------------------------
        # 429
        # ----------------------------------------------------

        if response.status_code == 429:

            error_message = (
                _extract_openrouter_error(
                    response
                )
            )

            retry_after = _get_retry_after(
                response
            )

            if retry_after is not None:

                wait_time = min(
                    max(retry_after, 1),
                    8,
                )

            else:

                wait_time = min(
                    2 + attempt * 2,
                    6,
                )

            last_error = (
                "OpenRouter a retourné HTTP 429 "
                "(Too Many Requests). "
                f"{error_message}"
            )

            if attempt + 1 < total_attempts:

                st.warning(
                    "OpenRouter limite temporairement "
                    "la requête (429). "
                    f"Nouvelle tentative dans "
                    f"{wait_time:.0f} seconde(s)."
                )

                time.sleep(
                    wait_time
                )

                continue

            raise RuntimeError(
                last_error
                + " La génération est arrêtée "
                  "plutôt que de rester bloquée."
            )

        # ----------------------------------------------------
        # AUTRES ERREURS HTTP
        # ----------------------------------------------------

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

            st.warning(
                f"OpenRouter a rencontré une "
                f"erreur serveur "
                f"({response.status_code}). "
                "Nouvelle tentative."
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
# GÉNÉRATION DU SCRIPT PRINCIPAL
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
Vous êtes un scénariste spécialisé en psychologie,
neurosciences accessibles et comportement humain.

SUJET :
{topic}

Écrivez un script captivant destiné à une vidéo YouTube.

RÈGLES ABSOLUES :

1. Utilisez uniquement des informations
   scientifiquement plausibles.

2. N'inventez aucune étude, expérience,
   citation, statistique, nom de chercheur
   ou résultat scientifique.

3. Si une affirmation est incertaine,
   controversée ou dépend du contexte,
   formulez-la prudemment.

4. Le début doit créer immédiatement
   de la curiosité.

5. Expliquez les mécanismes avec des mots simples.

6. Évitez le jargon inutile.

7. Le ton doit être naturel, dynamique
   et humain.

8. Le texte doit fonctionner avec
   une narration vocale.

9. Utilisez des paragraphes courts.

10. Ajoutez des marqueurs visuels utiles :

[IMAGE: description précise]

ou :

[VISUAL: description précise]

11. Les marqueurs doivent correspondre
    à de vrais éléments illustrables.

12. N'écrivez pas "Bonjour et bienvenue".

13. Évitez les conclusions artificiellement longues.

14. Terminez avec une idée mémorable.

Le script doit être suffisamment développé
pour pouvoir être adapté intelligemment en
vidéo longue ou en Short selon sa longueur.

Retournez uniquement le script.
"""

    messages = [
        {
            "role": "system",
            "content": (
                "Vous êtes un scénariste scientifique "
                "précis. Vous ne devez jamais inventer "
                "de faits."
            ),
        },
        {
            "role": "user",
            "content": prompt,
        },
    ]

    return openrouter_request(
        messages=messages,
        temperature=0.65,
        max_tokens=2200,
        timeout=75,
        max_retries=1,
    )


# ============================================================
# CHOIX DU FORMAT
# ============================================================

def choose_content_mode(
    word_count: int,
) -> str:

    if word_count < REGENERATE_BELOW:
        return "regenerate"

    if (
        ONE_SHORT_MIN
        <= word_count
        <= ONE_SHORT_MAX
    ):
        return "one_short"

    if (
        TWO_SHORTS_MIN
        <= word_count
        <= TWO_SHORTS_MAX
    ):
        return "two_shorts"

    if word_count >= LONG_MIN:
        return "long"

    return "one_short"


# ============================================================
# RÉGÉNÉRATION D'UN SCRIPT COURT
# ============================================================

def regenerate_short_main_script(
    topic: str,
) -> str:

    prompt = f"""
Transformez le sujet suivant en un script
de Short YouTube sur la psychologie,
les neurosciences ou le comportement humain.

SUJET :
{topic}

Contraintes :

- accroche forte dès la première phrase
- narration naturelle
- explication scientifique accessible
- aucune invention
- aucune fausse statistique
- aucune étude inventée
- environ 90 à 130 mots
- conclusion mémorable
- texte directement utilisable en voix off

Retournez uniquement le script.
"""

    messages = [
        {
            "role": "system",
            "content": (
                "Vous écrivez des Shorts scientifiques "
                "accessibles et factuellement prudents."
            ),
        },
        {
            "role": "user",
            "content": prompt,
        },
    ]

    return openrouter_request(
        messages=messages,
        temperature=0.7,
        max_tokens=700,
        timeout=60,
        max_retries=1,
    )


# ============================================================
# GÉNÉRATION D'UN SHORT
# ============================================================

def generate_one_short(
    script: str,
    topic: str = "",
) -> str:

    script = clean_ai_text(
        script
    )

    word_count = count_words(
        script
    )

    if word_count == 0:

        raise RuntimeError(
            "Impossible de créer un Short "
            "à partir d'un script vide."
        )

    if (
        SHORT_MIN_WORDS
        <= word_count
        <= SHORT_MAX_WORDS
    ):

        return script

    if word_count < SHORT_MIN_WORDS:

        if topic:
            return regenerate_short_main_script(
                topic
            )

        return script

    return fit_short_script(
        script,
        part_label="Short",
        target_min=SHORT_MIN_WORDS,
        target_max=SHORT_MAX_WORDS,
    )


# ============================================================
# GÉNÉRATION DE DEUX SHORTS
# ============================================================

def generate_two_shorts(
    script: str,
    topic: str,
) -> Tuple[str, str]:

    script = clean_ai_text(
        script
    )

    if count_words(script) < 2:
        return script, ""

    prompt = f"""
Transformez ce script en DEUX Shorts YouTube
sur la psychologie, le cerveau ou le comportement humain.

SUJET :
{topic}

SCRIPT ORIGINAL :
{script}

OBJECTIF :

Créer deux parties autonomes et cohérentes.

PARTIE 1 :
- accroche forte
- introduction du phénomène
- première idée importante
- envie de connaître la suite

PARTIE 2 :
- reprise naturelle du sujet
- suite de l'explication
- conclusion satisfaisante

RÈGLES :

- ne jamais inventer de faits
- ne jamais inventer d'études
- ne pas ajouter de statistiques absentes
- conserver les informations essentielles
- phrases naturelles pour une narration vocale
- pas d'introduction inutile
- pas de remplissage
- chaque partie doit pouvoir fonctionner seule
- conserver ou déplacer les marqueurs visuels

Retournez exactement :

[PARTIE 1]
texte

[PARTIE 2]
texte
"""

    messages = [
        {
            "role": "system",
            "content": (
                "Vous êtes un monteur éditorial "
                "spécialisé dans les vidéos "
                "scientifiques courtes."
            ),
        },
        {
            "role": "user",
            "content": prompt,
        },
    ]

    result = openrouter_request(
        messages=messages,
        temperature=0.55,
        max_tokens=1800,
        timeout=75,
        max_retries=1,
    )

    match1 = re.search(
        r"\[PARTIE\s*1\](.*?)(?=\[PARTIE\s*2\]|$)",
        result,
        flags=re.I | re.S,
    )

    match2 = re.search(
        r"\[PARTIE\s*2\](.*)$",
        result,
        flags=re.I | re.S,
    )

    part1 = (
        clean_ai_text(match1.group(1))
        if match1
        else ""
    )

    part2 = (
        clean_ai_text(match2.group(1))
        if match2
        else ""
    )

    if not part1 or not part2:

        words = script.split()

        middle = max(
            1,
            len(words) // 2,
        )

        part1 = " ".join(
            words[:middle]
        ).strip()

        part2 = " ".join(
            words[middle:]
        ).strip()

    return part1, part2# ============================================================
# ADAPTATION INTELLIGENTE D'UN SHORT
# ============================================================

def fit_short_script(
    script: str,
    part_label: str = "Short",
    target_min: int = SHORT_MIN_WORDS,
    target_max: int = SHORT_MAX_WORDS,
) -> str:

    script = clean_ai_text(
        script
    )

    if not script:
        return ""

    word_count = count_words(
        script
    )

    if (
        target_min
        <= word_count
        <= target_max
    ):
        return script

    # Un texte court reste utilisable.
    # On ne demande pas à l'IA d'inventer
    # artificiellement des informations.
    if word_count < target_min:
        return script

    prompt = f"""
Adaptez le texte suivant pour un {part_label} YouTube.

Objectif :
obtenir un texte court, naturel et captivant,
idéalement entre {target_min} et {target_max} mots.

TEXTE ORIGINAL :
{script}

RÈGLES :

- conserver les informations essentielles
- ne rien inventer
- aucune nouvelle statistique
- aucune nouvelle étude
- aucun nouveau fait
- conserver le sens scientifique
- accroche forte
- phrases courtes
- narration fluide
- terminer avec une idée mémorable
- conserver les marqueurs [IMAGE:] ou [VISUAL:]
  lorsqu'ils restent pertinents

Si atteindre exactement la plage demandée
oblige à supprimer une information importante,
privilégiez la qualité.

Retournez uniquement le texte final.
"""

    messages = [
        {
            "role": "system",
            "content": (
                "Vous êtes un éditeur de scripts "
                "scientifiques. Vous réduisez les textes "
                "sans inventer d'informations."
            ),
        },
        {
            "role": "user",
            "content": prompt,
        },
    ]

    try:

        result = openrouter_request(
            messages=messages,
            temperature=0.45,
            max_tokens=900,
            timeout=60,
            max_retries=0,
        )

        result = clean_ai_text(
            result
        )

        if result:
            return result

    except Exception:

        st.warning(
            f"{part_label} : adaptation IA "
            "indisponible. Le texte original "
            "sera utilisé."
        )

    return script


# ============================================================
# TEASER
# ============================================================

def generate_teaser(
    script: str,
    topic: str = "",
) -> str:

    script = clean_ai_text(
        script
    )

    if not script:
        return ""

    word_count = count_words(
        script
    )

    if (
        SHORT_MIN_WORDS
        <= word_count
        <= SHORT_MAX_WORDS
    ):
        return script

    prompt = f"""
Créez un teaser captivant pour une vidéo YouTube.

SUJET :
{topic}

SCRIPT SOURCE :
{script}

Le teaser doit :

- attirer immédiatement l'attention
- poser une question ou créer une curiosité forte
- présenter le phénomène sans tout révéler
- rester scientifiquement correct
- ne rien inventer
- ne pas utiliser de fausse statistique
- ne pas exagérer les résultats scientifiques
- être naturel à l'oral
- faire environ 60 à 100 mots
- finir sur une phrase donnant envie de regarder la suite

Retournez uniquement le texte.
"""

    messages = [
        {
            "role": "system",
            "content": (
                "Vous créez des teasers courts, "
                "scientifiques et captivants."
            ),
        },
        {
            "role": "user",
            "content": prompt,
        },
    ]

    try:

        return openrouter_request(
            messages=messages,
            temperature=0.7,
            max_tokens=600,
            timeout=60,
            max_retries=0,
        )

    except Exception:

        words = script.split()

        fallback = " ".join(
            words[:90]
        ).strip()

        return fallback


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
    per_page: int = 8,
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
        "orientation": "landscape",
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
        ) as file:

            for chunk in response.iter_content(
                chunk_size=1024 * 128
            ):

                if chunk:
                    file.write(chunk)

        return (
            destination.exists()
            and destination.stat().st_size > 0
        )

    except Exception:
        return False


def normalize_image(
    source: Path,
    destination: Path,
    width: int = 1920,
    height: int = 1080,
) -> bool:

    try:

        with Image.open(source) as image:

            image = image.convert(
                "RGB"
            )

            src_ratio = (
                image.width
                / image.height
            )

            dst_ratio = (
                width
                / height
            )

            if src_ratio > dst_ratio:

                new_height = height

                new_width = int(
                    height * src_ratio
                )

            else:

                new_width = width

                new_height = int(
                    width / src_ratio
                )

            image = image.resize(
                (
                    new_width,
                    new_height,
                ),
                Image.Resampling.LANCZOS,
            )

            left = max(
                0,
                (new_width - width) // 2,
            )

            top = max(
                0,
                (new_height - height) // 2,
            )

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
                quality=94,
                optimize=True,
            )

        return True

    except Exception:
        return False


# ============================================================
# PLACEHOLDER
# ============================================================

def create_placeholder(
    destination: Path,
    text: str,
    width: int = 1920,
    height: int = 1080,
) -> Path:

    image = Image.new(
        "RGB",
        (width, height),
        "black",
    )

    draw = ImageDraw.Draw(
        image
    )

    font = None

    possible_fonts = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ]

    for font_path in possible_fonts:

        if Path(font_path).exists():

            try:

                font = ImageFont.truetype(
                    font_path,
                    64,
                )

                break

            except Exception:
                pass

    if font is None:
        font = ImageFont.load_default()

    text = normalize_text(
        text
    )

    if len(text) > 120:
        text = text[:117] + "..."

    bbox = draw.multiline_textbbox(
        (0, 0),
        text,
        font=font,
        spacing=12,
        align="center",
    )

    text_width = (
        bbox[2] - bbox[0]
    )

    text_height = (
        bbox[3] - bbox[1]
    )

    x = (
        width - text_width
    ) // 2

    y = (
        height - text_height
    ) // 2

    draw.multiline_text(
        (x, y),
        text,
        font=font,
        spacing=12,
        align="center",
        fill="white",
    )

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    image.save(
        destination,
        "JPEG",
        quality=94,
    )

    return destination


# ============================================================
# VISUELS
# ============================================================

def get_visuals(
    script: str,
    output_dir: Path,
    target_count: Optional[int] = None,
) -> List[Path]:

    markers = extract_visual_markers(
        script
    )

    if not markers:

        markers = [
            "psychology brain human behavior",
            "human brain neuroscience",
            "person thinking",
        ]

    if target_count is not None:

        target_count = max(
            1,
            int(target_count),
        )

        markers = markers[:target_count]

    visual_dir = (
        output_dir
        / "visuals"
    )

    visual_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    visuals = []

    used_queries = set()

    for index, query in enumerate(
        markers
    ):

        query = normalize_text(
            query
        )

        if not query:
            continue

        query_key = query.lower()

        if query_key in used_queries:
            continue

        used_queries.add(
            query_key
        )

        photos = pexels_search(
            query=query,
            per_page=5,
        )

        selected_photo = None

        if photos:

            selected_photo = random.choice(
                photos[
                    :min(
                        len(photos),
                        5,
                    )
                ]
            )

        raw_path = (
            visual_dir
            / f"raw_{index:03d}.jpg"
        )

        final_path = (
            visual_dir
            / f"visual_{index:03d}.jpg"
        )

        if selected_photo:

            src = (
                selected_photo.get(
                    "src",
                    {},
                )
                if isinstance(
                    selected_photo,
                    dict,
                )
                else {}
            )

            image_url = (
                src.get("large2x")
                or src.get("large")
                or src.get("original")
            )

            if image_url:

                if download_file(
                    image_url,
                    raw_path,
                ):

                    if normalize_image(
                        raw_path,
                        final_path,
                    ):

                        visuals.append(
                            final_path
                        )

                        continue

        placeholder = create_placeholder(
            final_path,
            query,
        )

        visuals.append(
            placeholder
        )

    if not visuals:

        fallback_path = (
            visual_dir
            / "visual_fallback.jpg"
        )

        create_placeholder(
            fallback_path,
            "Psychologie • Cerveau • Comportement",
        )

        visuals.append(
            fallback_path
        )

    return visuals


# ============================================================
# NOMBRE DE VISUELS
# ============================================================

def estimate_visual_count(
    duration_seconds: float,
) -> int:

    duration_seconds = max(
        1.0,
        float(duration_seconds),
    )

    count = math.ceil(
        duration_seconds / 4.5
    )

    return max(
        5,
        min(count, 24),
    )


# ============================================================
# EDGE-TTS : VOIX
# ============================================================

def list_tts_voices() -> List[dict]:

    async def _get_voices():

        return await edge_tts.list_voices()

    try:

        return asyncio.run(
            _get_voices()
        )

    except RuntimeError:

        result = []

        def runner():

            loop = (
                asyncio.new_event_loop()
            )

            try:

                asyncio.set_event_loop(
                    loop
                )

                result.extend(
                    loop.run_until_complete(
                        _get_voices()
                    )
                )

            except Exception:
                pass

            finally:

                loop.close()

                asyncio.set_event_loop(
                    None
                )

        import threading

        thread = threading.Thread(
            target=runner
        )

        thread.start()
        thread.join()

        return result

    except Exception:
        return []


def select_french_voice() -> str:

    preferred = [
        "fr-FR-DeniseNeural",
        "fr-FR-HenriNeural",
        "fr-FR-VivienneMultilingualNeural",
        "fr-FR-RemyMultilingualNeural",
    ]

    try:

        voices = list_tts_voices()

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

        for voice in voices:

            if not isinstance(
                voice,
                dict,
            ):
                continue

            short_name = str(
                voice.get(
                    "ShortName",
                    "",
                )
            )

            locale = str(
                voice.get(
                    "Locale",
                    "",
                )
            )

            if locale.lower().startswith(
                "fr-"
            ):
                return short_name

    except Exception:
        pass

    return "fr-FR-DeniseNeural"


# ============================================================
# EDGE-TTS : SYNTHÈSE
# ============================================================

def synthesize_with_voice(
    text: str,
    output_path: Path,
    voice: Optional[str] = None,
    rate: str = "+0%",
    volume: str = "+0%",
) -> Path:

    text = remove_visual_markers(
        text
    )

    text = normalize_text(
        text
    )

    if not text:

        raise RuntimeError(
            "Impossible de générer l'audio : "
            "le texte est vide."
        )

    if voice is None:
        voice = select_french_voice()

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    async def _generate():

        communicate = edge_tts.Communicate(
            text=text,
            voice=voice,
            rate=rate,
            volume=volume,
        )

        await communicate.save(
            str(output_path)
        )

    try:

        asyncio.run(
            _generate()
        )

    except RuntimeError:

        error_holder = []

        def runner():

            loop = (
                asyncio.new_event_loop()
            )

            try:

                asyncio.set_event_loop(
                    loop
                )

                loop.run_until_complete(
                    _generate()
                )

            except Exception as exc:

                error_holder.append(
                    exc
                )

            finally:

                loop.close()

                asyncio.set_event_loop(
                    None
                )

        import threading

        thread = threading.Thread(
            target=runner
        )

        thread.start()
        thread.join()

        if error_holder:

            raise RuntimeError(
                f"Erreur Edge-TTS : "
                f"{error_holder[0]}"
            )

    except Exception as exc:

        raise RuntimeError(
            f"Impossible de générer la narration : "
            f"{exc}"
        ) from exc

    if not output_path.exists():

        raise RuntimeError(
            "Edge-TTS n'a pas créé le fichier audio."
        )

    if output_path.stat().st_size == 0:

        raise RuntimeError(
            "Le fichier audio généré est vide."
        )

    return output_path# ============================================================
# DURÉE AUDIO
# ============================================================

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
            "Impossible de déterminer la durée "
            "de l'audio : "
            + result.stderr[:500]
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
# SOUS-TITRES MOT PAR MOT
# ============================================================

def get_word_boundaries(
    text: str,
    audio_path: Path,
    voice: Optional[str] = None,
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

        def runner():

            loop = (
                asyncio.new_event_loop()
            )

            try:

                asyncio.set_event_loop(
                    loop
                )

                loop.run_until_complete(
                    _collect()
                )

            except Exception:
                pass

            finally:

                loop.close()

                asyncio.set_event_loop(
                    None
                )

        import threading

        thread = threading.Thread(
            target=runner
        )

        thread.start()
        thread.join()

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

    word_count = len(
        words
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
            word_count
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
# ASS
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
        (seconds % 3600)
        // 60
    )

    remaining = (
        seconds
        % 60
    )

    whole_seconds = int(
        remaining
    )

    centiseconds = int(
        round(
            (
                remaining
                - whole_seconds
            )
            * 100
        )
    )

    if centiseconds >= 100:

        whole_seconds += 1
        centiseconds -= 100

    if whole_seconds >= 60:

        minutes += 1
        whole_seconds -= 60

    if minutes >= 60:

        hours += 1
        minutes -= 60

    return (
        f"{hours:01d}:"
        f"{minutes:02d}:"
        f"{whole_seconds:02d}."
        f"{centiseconds:02d}"
    )


def escape_ass(
    text: str,
) -> str:

    text = str(
        text
    )

    text = text.replace(
        "\\",
        r"\\",
    )

    text = text.replace(
        "{",
        r"\{",
    )

    text = text.replace(
        "}",
        r"\}",
    )

    text = text.replace(
        "\n",
        " ",
    )

    return text


def create_ass_subtitles(
    boundaries: List[Tuple[str, float, float]],
    output_path: Path,
    width: int = 1080,
    height: int = 1920,
) -> Path:

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if height > width:

        font_size = 64
        margin_vertical = 145

    else:

        font_size = 52
        margin_vertical = 80

    content = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "",
        "[V4+ Styles]",
        (
            "Format: Name, Fontname, Fontsize, "
            "PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, "
            "Italic, Underline, StrikeOut, ScaleX, "
            "ScaleY, Spacing, Angle, BorderStyle, "
            "Outline, Shadow, Alignment, MarginL, "
            "MarginR, MarginV, Encoding"
        ),
        (
            "Style: Default,Arial,"
            f"{font_size},"
            "&H00FFFFFF,"
            "&H000000FF,"
            "&H00000000,"
            "&H99000000,"
            "1,0,0,0,100,100,0,0,1,3,1,2,"
            "45,45,"
            f"{margin_vertical},1"
        ),
        "",
        "[Events]",
        (
            "Format: Layer, Start, End, Style, Name, "
            "MarginL, MarginR, MarginV, Effect, Text"
        ),
    ]

    for word, start, end in boundaries:

        word = escape_ass(
            word
        )

        content.append(
            "Dialogue: 0,"
            f"{ass_time(start)},"
            f"{ass_time(end)},"
            "Default,,0,0,0,,"
            f"{word}"
        )

    output_path.write_text(
        "\n".join(content),
        encoding="utf-8",
    )

    return output_path


# ============================================================
# DURÉE DES SCÈNES
# ============================================================

def distribute_scene_durations(
    total_duration: float,
    visual_count: int,
) -> List[float]:

    total_duration = max(
        1.0,
        float(total_duration),
    )

    visual_count = max(
        1,
        int(visual_count),
    )

    base = (
        total_duration
        / visual_count
    )

    durations = [
        base
        for _ in range(visual_count)
    ]

    for index in range(
        visual_count
    ):

        variation = (
            0.94
            + random.random()
            * 0.12
        )

        durations[index] *= (
            variation
        )

    current_total = sum(
        durations
    )

    if current_total <= 0:

        return [
            base
            for _ in range(
                visual_count
            )
        ]

    factor = (
        total_duration
        / current_total
    )

    return [
        value * factor
        for value in durations
    ]


# ============================================================
# IMAGE → VIDÉO
# ============================================================

def create_image_scene(
    image_path: Path,
    output_path: Path,
    duration: float,
    width: int,
    height: int,
    scene_index: int = 0,
) -> Path:

    ensure_ffmpeg()

    duration = max(
        0.5,
        float(duration),
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # V1 : priorité à la fiabilité et à la vitesse.
    # L'ancien zoompan calculait plusieurs centaines de frames
    # avec une image agrandie en 2x, ce qui pouvait dépasser
    # le timeout Render sur une seule scène.
    fps = 30

    # On adapte simplement l'image au format demandé.
    # Le crop conserve le remplissage de l'image sans zoompan.
    filter_complex = (
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
            filter_complex,
            "-t",
            f"{duration:.3f}",
            "-r",
            str(fps),
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

    if result.returncode != 0:

        raise RuntimeError(
            "Impossible de créer une scène vidéo : "
            + result.stderr[-1500:]
        )

    if not output_path.exists() or output_path.stat().st_size == 0:

        raise RuntimeError(
            "FFmpeg n'a pas créé correctement la scène vidéo."
        )

    return output_path


# ============================================================
# CONCATÉNATION
# ============================================================

def concat_scenes(
    scene_paths: List[Path],
    output_path: Path,
) -> Path:

    ensure_ffmpeg()

    if not scene_paths:

        raise RuntimeError(
            "Aucune scène à assembler."
        )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    concat_file = (
        output_path.parent
        / "concat.txt"
    )

    lines = []

    for scene in scene_paths:

        absolute_path = (
            scene.resolve()
            .as_posix()
        )

        absolute_path = (
            absolute_path.replace(
                "'",
                r"'\''",
            )
        )

        lines.append(
            f"file '{absolute_path}'"
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
            str(output_path),
        ],
        timeout=300,
    )

    if result.returncode != 0:

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
                "20",
                "-pix_fmt",
                "yuv420p",
                str(output_path),
            ],
            timeout=300,
        )

    if result.returncode != 0:

        raise RuntimeError(
            "Impossible d'assembler les scènes : "
            + result.stderr[-1200:]
        )

    return output_path


# ============================================================
# AUDIO
# ============================================================

def attach_audio(
    video_path: Path,
    audio_path: Path,
    output_path: Path,
) -> Path:

    ensure_ffmpeg()

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    result = run_command(
        [
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
            "192k",
            "-shortest",
            str(output_path),
        ],
        timeout=300,
    )

    if result.returncode != 0:

        raise RuntimeError(
            "Impossible d'ajouter l'audio : "
            + result.stderr[-1200:]
        )

    return output_path


# ============================================================
# SOUS-TITRES
# ============================================================

def burn_subtitles(
    video_path: Path,
    ass_path: Path,
    output_path: Path,
) -> Path:

    ensure_ffmpeg()

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    ass_filter_path = (
        str(ass_path)
        .replace(
            "\\",
            "/",
        )
        .replace(
            ":",
            r"\:",
        )
        .replace(
            "'",
            r"\'",
        )
    )

    subtitle_filter = (
        f"ass='{ass_filter_path}'"
    )

    result = run_command(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vf",
            subtitle_filter,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "19",
            "-c:a",
            "copy",
            str(output_path),
        ],
        timeout=400,
    )

    if result.returncode != 0:

        raise RuntimeError(
            "Impossible d'incruster les sous-titres : "
            + result.stderr[-1500:]
        )

    return output_path# ============================================================
# CONSTRUCTION COMPLÈTE D'UNE VIDÉO
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

    if not script:

        raise RuntimeError(
            "Impossible de construire la vidéo : "
            "script vide."
        )

    if vertical:

        width = 1080
        height = 1920

    else:

        width = 1920
        height = 1080

    video_dir = (
        output_dir
        / "video"
    )

    audio_dir = (
        output_dir
        / "audio"
    )

    subtitle_dir = (
        output_dir
        / "subtitles"
    )

    video_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    audio_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    subtitle_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # AUDIO
    # --------------------------------------------------------

    st.write(
        "🎙️ Génération de la narration..."
    )

    audio_path = (
        audio_dir
        / f"{Path(filename).stem}.mp3"
    )

    voice = select_french_voice()

    synthesize_with_voice(
        text=script,
        output_path=audio_path,
        voice=voice,
        rate="+2%",
    )

    audio_duration = get_audio_duration(
        audio_path
    )

    st.write(
        f"⏱️ Durée de narration : "
        f"{audio_duration:.1f} secondes"
    )

    # --------------------------------------------------------
    # VISUELS
    # --------------------------------------------------------

    st.write(
        "🖼️ Recherche des visuels..."
    )

    visual_count = estimate_visual_count(
        audio_duration
    )

    visuals = get_visuals(
        script=script,
        output_dir=output_dir,
        target_count=visual_count,
    )

    st.write(
        f"🖼️ {len(visuals)} visuels disponibles"
    )

    # --------------------------------------------------------
    # DURÉES
    # --------------------------------------------------------

    scene_durations = (
        distribute_scene_durations(
            total_duration=audio_duration,
            visual_count=len(visuals),
        )
    )

    # --------------------------------------------------------
    # SCÈNES
    # --------------------------------------------------------

    scene_dir = (
        video_dir
        / "scenes"
    )

    scene_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    scene_paths = []

    progress = st.progress(
        0,
        text="🎬 Création des scènes...",
    )

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
            scene_dir
            / f"scene_{index:03d}.mp4"
        )

        create_image_scene(
            image_path=image_path,
            output_path=scene_path,
            duration=scene_duration,
            width=width,
            height=height,
            scene_index=index,
        )

        scene_paths.append(
            scene_path
        )

        progress.progress(
            int(
                (
                    (index + 1)
                    / len(visuals)
                )
                * 100
            ),
            text=(
                f"🎬 Scène "
                f"{index + 1}/"
                f"{len(visuals)}"
            ),
        )

    progress.empty()

    # --------------------------------------------------------
    # ASSEMBLAGE
    # --------------------------------------------------------

    st.write(
        "🔗 Assemblage des scènes..."
    )

    silent_video = (
        video_dir
        / f"{Path(filename).stem}_silent.mp4"
    )

    concat_scenes(
        scene_paths=scene_paths,
        output_path=silent_video,
    )

    # --------------------------------------------------------
    # AUDIO
    # --------------------------------------------------------

    st.write(
        "🎙️ Ajout de la narration..."
    )

    narrated_video = (
        video_dir
        / f"{Path(filename).stem}_narrated.mp4"
    )

    attach_audio(
        video_path=silent_video,
        audio_path=audio_path,
        output_path=narrated_video,
    )

    # --------------------------------------------------------
    # TIMING MOT PAR MOT
    # --------------------------------------------------------

    st.write(
        "📝 Calcul des sous-titres mot par mot..."
    )

    boundaries = get_word_boundaries(
        text=script,
        audio_path=audio_path,
        voice=voice,
    )

    if not boundaries:

        raise RuntimeError(
            "Impossible de générer les timings "
            "des sous-titres."
        )

    ass_path = (
        subtitle_dir
        / f"{Path(filename).stem}.ass"
    )

    create_ass_subtitles(
        boundaries=boundaries,
        output_path=ass_path,
        width=width,
        height=height,
    )

    # --------------------------------------------------------
    # INCRUSTATION
    # --------------------------------------------------------

    st.write(
        "✨ Incrustation des sous-titres..."
    )

    final_path = (
        output_dir
        / filename
    )

    burn_subtitles(
        video_path=narrated_video,
        ass_path=ass_path,
        output_path=final_path,
    )

    if not final_path.exists():

        raise RuntimeError(
            "La vidéo finale n'a pas été créée."
        )

    return final_path


# ============================================================
# RÉPERTOIRE DE PRODUCTION
# ============================================================

def create_production_directory(
    topic: str,
) -> Path:

    safe_topic = re.sub(
        r"[^a-zA-Z0-9À-ÿ_-]+",
        "_",
        topic,
    )

    safe_topic = safe_topic.strip(
        "_"
    )

    if not safe_topic:
        safe_topic = "video"

    timestamp = time.strftime(
        "%Y%m%d_%H%M%S"
    )

    production_dir = (
        OUTPUT_DIR
        / f"{safe_topic}_{timestamp}"
    )

    production_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    return production_dir


# ============================================================
# SHORT
# ============================================================

def process_short(
    script: str,
    production_dir: Path,
    filename: str,
    label: str = "Short",
) -> Path:

    st.subheader(
        f"📱 {label}"
    )

    script = clean_ai_text(
        script
    )

    if not script:

        raise RuntimeError(
            f"{label} : script vide."
        )

    word_count = count_words(
        remove_visual_markers(
            script
        )
    )

    st.write(
        f"📝 {word_count} mots"
    )

    return build_video(
        script=script,
        output_dir=production_dir,
        filename=filename,
        vertical=True,
    )


# ============================================================
# VIDÉO LONGUE
# ============================================================

def process_long_video(
    script: str,
    production_dir: Path,
) -> Path:

    st.subheader(
        "🎬 Vidéo YouTube longue"
    )

    script = clean_ai_text(
        script
    )

    word_count = count_words(
        remove_visual_markers(
            script
        )
    )

    st.write(
        f"📝 {word_count} mots"
    )

    return build_video(
        script=script,
        output_dir=production_dir,
        filename="video_longue.mp4",
        vertical=False,
    )


# ============================================================
# TEASER
# ============================================================

def process_teaser(
    script: str,
    topic: str,
    production_dir: Path,
) -> Optional[Path]:

    st.subheader(
        "🎯 Teaser"
    )

    try:

        teaser = generate_teaser(
            script=script,
            topic=topic,
        )

        if not teaser:
            return None

        return build_video(
            script=teaser,
            output_dir=production_dir,
            filename="teaser.mp4",
            vertical=True,
        )

    except Exception as exc:

        st.warning(
            f"Teaser non généré : {exc}"
        )

        return None


# ============================================================
# COPIE SORTIE
# ============================================================

def copy_final_output(
    source: Path,
    filename: str,
) -> Path:

    destination = (
        OUTPUT_DIR
        / filename
    )

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    shutil.copy2(
        source,
        destination,
    )

    return destination


# ============================================================
# WORKFLOW PRINCIPAL
# ============================================================

def run_generation(
    topic: str,
) -> Dict[str, List[Path]]:

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
        "🧠 Génération du script..."
    )

    script = generate_main_script(
        topic
    )

    script = clean_ai_text(
        script
    )

    clean_script = remove_visual_markers(
        script
    )

    word_count = count_words(
        clean_script
    )

    visual_marker_count = len(
        extract_visual_markers(
            script
        )
    )

    st.success(
        f"Script généré : "
        f"{word_count} mots"
    )

    st.write(
        f"Marqueurs visuels : "
        f"{visual_marker_count}"
    )

    mode = choose_content_mode(
        word_count
    )

    # --------------------------------------------------------
    # SCRIPT TROP COURT
    # --------------------------------------------------------

    if mode == "regenerate":

        st.info(
            "🧠 Le script initial est très court. "
            "Création d'une version mieux adaptée..."
        )

        try:

            regenerated = (
                regenerate_short_main_script(
                    topic
                )
            )

            regenerated = clean_ai_text(
                regenerated
            )

            regenerated_count = count_words(
                remove_visual_markers(
                    regenerated
                )
            )

            if regenerated_count > 0:

                script = regenerated
                word_count = regenerated_count

            st.write(
                f"Nouvelle version : "
                f"{word_count} mots"
            )

        except Exception as exc:

            st.warning(
                "La régénération du script court "
                "a échoué. Le script initial sera "
                f"utilisé. Détail : {exc}"
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

        st.info(
            "📱 Format sélectionné : 1 Short."
        )

        short_script = generate_one_short(
            script=script,
            topic=topic,
        )

        short_path = process_short(
            script=short_script,
            production_dir=production_dir,
            filename="short_1.mp4",
            label="Short",
        )

        results["shorts"].append(
            short_path
        )

        return results

    # --------------------------------------------------------
    # DEUX SHORTS
    # --------------------------------------------------------

    if mode == "two_shorts":

        st.info(
            "✂️ Restructuration en deux Shorts "
            "cohérents..."
        )

        part1, part2 = generate_two_shorts(
            script=script,
            topic=topic,
        )

        part1 = fit_short_script(
            part1,
            part_label="Partie 1",
        )

        part2 = fit_short_script(
            part2,
            part_label="Partie 2",
        )

        if not part1:
            part1 = script

        if not part2:
            part2 = part1

        st.success(
            "Structure des deux Shorts terminée."
        )

        st.write(
            "Partie 1 : "
            f"{count_words(remove_visual_markers(part1))} mots"
        )

        st.write(
            "Partie 2 : "
            f"{count_words(remove_visual_markers(part2))} mots"
        )

        short1 = process_short(
            script=part1,
            production_dir=production_dir,
            filename="short_1.mp4",
            label="Short 1",
        )

        results["shorts"].append(
            short1
        )

        short2 = process_short(
            script=part2,
            production_dir=production_dir,
            filename="short_2.mp4",
            label="Short 2",
        )

        results["shorts"].append(
            short2
        )

        return results

    # --------------------------------------------------------
    # VIDÉO LONGUE
    # --------------------------------------------------------

    if mode == "long":

        st.info(
            "🎬 Format sélectionné : "
            "vidéo longue 16:9."
        )

        long_video = process_long_video(
            script=script,
            production_dir=production_dir,
        )

        results["long"].append(
            long_video
        )

        teaser = process_teaser(
            script=script,
            topic=topic,
            production_dir=production_dir,
        )

        if teaser:

            results["teaser"].append(
                teaser
            )

        return results

    # --------------------------------------------------------
    # SÉCURITÉ
    # --------------------------------------------------------

    st.warning(
        "Format inattendu. "
        "Adaptation automatique vers un Short."
    )

    short_script = generate_one_short(
        script=script,
        topic=topic,
    )

    short_path = process_short(
        script=short_script,
        production_dir=production_dir,
        filename="short_1.mp4",
        label="Short",
    )

    results["shorts"].append(
        short_path
    )

    return results


# ============================================================
# AFFICHAGE VIDÉO
# ============================================================

def show_video_result(
    path: Path,
    title: str,
) -> None:

    if not path.exists():
        return

    st.subheader(
        title
    )

    try:

        with open(
            path,
            "rb",
        ) as video_file:

            video_bytes = (
                video_file.read()
            )

        st.video(
            video_bytes
        )

    except Exception as exc:

        st.warning(
            f"Impossible d'afficher "
            f"{title} : {exc}"
        )


# ============================================================
# INTERFACE
# ============================================================

def main() -> None:

    st.set_page_config(
        page_title=APP_TITLE,
        page_icon="🎬",
        layout="wide",
    )

    st.title(
        "🎬 Studio Vidéo IA"
    )

    st.caption(
        "Création automatisée de vidéos "
        "sur la psychologie, le cerveau et "
        "le comportement humain."
    )

    st.divider()

    # --------------------------------------------------------
    # SIDEBAR
    # --------------------------------------------------------

    with st.sidebar:

        st.header(
            "⚙️ Configuration"
        )

        if OPENROUTER_API_KEY:

            st.success(
                "OpenRouter : connecté"
            )

        else:

            st.error(
                "OpenRouter : clé absente"
            )

        if PEXELS_API_KEY:

            st.success(
                "Pexels : connecté"
            )

        else:

            st.warning(
                "Pexels : clé absente"
            )

        st.caption(
            "Sans clé Pexels, des visuels de secours "
            "seront utilisés."
        )

        st.divider()

        st.write(
            "Formats automatiques :"
        )

        st.write(
            "• 1 Short pour un script moyen"
        )

        st.write(
            "• 2 Shorts pour un script plus long"
        )

        st.write(
            "• Vidéo 16:9 pour un script long"
        )

        st.write(
            "• Adaptation automatique si nécessaire"
        )

    # --------------------------------------------------------
    # SAISIE
    # --------------------------------------------------------

    st.header(
        "🧠 Nouveau sujet"
    )

    topic = st.text_input(
        "Sujet de la vidéo",
        placeholder=(
            "Exemple : Pourquoi ton cerveau procrastine"
        ),
    )

    st.caption(
        "Conseil : choisissez un phénomène précis "
        "de psychologie, de neurosciences ou de "
        "comportement humain."
    )

    generate_button = st.button(
        "🚀 Générer la vidéo",
        type="primary",
        use_container_width=True,
    )

    # --------------------------------------------------------
    # GÉNÉRATION
    # --------------------------------------------------------

    if generate_button:

        if not topic.strip():

            st.error(
                "Veuillez saisir un sujet."
            )

            return

        st.session_state.pop(
            "generation_results",
            None,
        )

        try:

            with st.status(
                "🎬 Production en cours...",
                expanded=True,
            ):

                results = run_generation(
                    topic=topic
                )

                st.session_state[
                    "generation_results"
                ] = results

                st.success(
                    "✅ Production terminée."
                )

        except Exception as exc:

            st.error(
                "❌ La génération a échoué."
            )

            st.exception(
                exc
            )

            return

    # --------------------------------------------------------
    # RÉSULTATS
    # --------------------------------------------------------

    results = st.session_state.get(
        "generation_results"
    )

    if not results:
        return

    st.divider()

    st.header(
        "🎉 Résultats"
    )

    shorts = results.get(
        "shorts",
        [],
    )

    long_videos = results.get(
        "long",
        [],
    )

    teasers = results.get(
        "teaser",
        [],
    )

    for index, path in enumerate(
        shorts,
        start=1,
    ):

        show_video_result(
            path,
            f"📱 Short {index}",
        )

    for path in long_videos:

        show_video_result(
            path,
            "🎬 Vidéo longue",
        )

    for path in teasers:

        show_video_result(
            path,
            "🎯 Teaser",
        )

    st.divider()

    st.info(
        "Les vidéos sont enregistrées dans "
        "le dossier `outputs` du serveur."
    )


# ============================================================
# LANCEMENT
# ============================================================

if __name__ == "__main__":
    main()
