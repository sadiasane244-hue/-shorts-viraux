import os
import random
import re
import subprocess
import tempfile
import asyncio
import concurrent.futures
import time

from pathlib import Path

import requests
from PIL import Image, UnidentifiedImageError
import streamlit as st


# =========================================================
# CONFIGURATION
# =========================================================

st.set_page_config(
    page_title="Studio Vidéo IA",
    page_icon="🎬",
    layout="centered"
)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "meta-llama/llama-3.3-70b-instruct"

VOICE = "fr-FR-RemyNeural"

REQUEST_TIMEOUT = 90
PEXELS_TIMEOUT = 20

MAX_PEXELS_WORKERS = 6

# ---------------------------------------------------------
# NOUVELLES CONTRAINTES DE DURÉE
# ---------------------------------------------------------

# Vidéo longue : strictement plus de 2 minutes.
LONG_MIN_DURATION = 120.0

# Il n'y a volontairement PAS de maximum.
# Le sujet décide de la longueur naturelle de la vidéo.

# Short : suffisamment court pour rester un teaser.
SHORT_MIN_DURATION = 25.0
SHORT_MAX_DURATION = 40.0

# Cibles de mots indicatives uniquement.
# Elles ne servent PAS à bloquer la vidéo longue.
LONG_TARGET_MIN_WORDS = 650
LONG_TARGET_MAX_WORDS = 1000

SHORT_TARGET_MIN_WORDS = 75
SHORT_TARGET_MAX_WORDS = 95


# =========================================================
# OUTILS GÉNÉRAUX
# =========================================================

def run_command(cmd, timeout=None):
    """
    Exécute une commande système et retourne :
    code retour, stdout, stderr.
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )

        return (
            result.returncode,
            result.stdout or "",
            result.stderr or ""
        )

    except subprocess.TimeoutExpired as exc:
        return (
            -1,
            exc.stdout or "",
            f"Timeout après {timeout}s: {exc}"
        )

    except Exception as exc:
        return (
            -1,
            "",
            str(exc)
        )


def ffprobe_value(path, selector):
    """
    Récupère une valeur numérique avec FFprobe.
    """
    if not path or not os.path.exists(path):
        return None

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        selector,
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        path
    ]

    code, stdout, _ = run_command(
        cmd,
        timeout=30
    )

    if code != 0:
        return None

    try:
        return float(stdout.strip())

    except (TypeError, ValueError):
        return None


def get_audio_duration(audio_path):
    """
    Mesure la durée réelle de la voix off.

    IMPORTANT :
    Il n'y a volontairement plus de fallback à 300 secondes.
    """
    duration = ffprobe_value(
        audio_path,
        "format=duration"
    )

    if duration is None or duration <= 0:
        raise RuntimeError(
            "FFprobe n'a pas pu lire la durée réelle de la voix off. "
            "Le fichier audio est absent, vide ou illisible."
        )

    return duration


def file_is_valid_image(path):
    """
    Vérifie qu'un fichier est réellement une image lisible.
    """
    if not path or not os.path.exists(path):
        return False

    try:
        if os.path.getsize(path) < 1000:
            return False

        with Image.open(path) as img:
            img.verify()

        return True

    except (OSError, UnidentifiedImageError):
        return False


def clean_filename(text):
    """
    Transforme un texte en nom de fichier sûr.
    """
    text = re.sub(
        r"[^a-zA-Z0-9_-]+",
        "_",
        text
    )

    text = text.strip("_")

    return text[:80] or "video"


def format_time_ass(seconds):
    """
    Format ASS :
    H:MM:SS.cc
    """
    seconds = max(
        0.0,
        float(seconds)
    )

    hours = int(seconds // 3600)

    minutes = int(
        (seconds % 3600) // 60
    )

    secs = int(
        seconds % 60
    )

    centis = int(
        (seconds - int(seconds)) * 100
    )

    return (
        f"{hours}:"
        f"{minutes:02d}:"
        f"{secs:02d}."
        f"{centis:02d}"
    )


def retry_sleep(attempt):
    """
    Petite pause entre les tentatives.
    """
    time.sleep(
        min(
            2 ** attempt,
            8
        )
    )


# =========================================================
# OPENROUTER
# =========================================================

def call_openrouter(
    messages,
    max_tokens,
    temperature
):
    """
    Appelle OpenRouter avec 3 tentatives.
    """
    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "Clé OPENROUTER_API_KEY manquante."
        )

    headers = {
        "Authorization": (
            f"Bearer {OPENROUTER_API_KEY}"
        ),
        "Content-Type": "application/json",
        "HTTP-Referer": (
            "https://shorts-viraux-1.onrender.com"
        ),
        "X-Title": "Studio Vidéo IA"
    }

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens
    }

    last_error = None

    for attempt in range(3):

        try:
            response = requests.post(
                OPENROUTER_URL,
                headers=headers,
                json=payload,
                timeout=REQUEST_TIMEOUT
            )

            if response.status_code == 200:

                data = response.json()

                content = (
                    data
                    .get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )

                if content and content.strip():
                    return content.strip()

                last_error = (
                    "Réponse OpenRouter vide."
                )

            else:

                try:
                    detail = response.json()

                except Exception:
                    detail = response.text

                last_error = (
                    f"HTTP {response.status_code}: "
                    f"{detail}"
                )

        except requests.RequestException as exc:

            last_error = str(exc)

        if attempt < 2:
            retry_sleep(attempt)

    raise RuntimeError(
        "OpenRouter a échoué après 3 tentatives: "
        f"{last_error}"
    )


# =========================================================
# GÉNÉRATION DES SCRIPTS
# =========================================================

def generate_pack_scripts(subject):

    # -----------------------------------------------------
    # SCRIPT LONG
    # -----------------------------------------------------

    long_system_prompt = f"""
Vous êtes un scénariste documentaire YouTube francophone.

SUJET :
{subject}

OBJECTIF PRINCIPAL :

Créer une vidéo documentaire captivante, claire et factuelle.

IMPORTANT :
La vidéo longue doit durer naturellement PLUS DE 2 MINUTES.

Il n'existe PAS de minimum de 5 minutes.

Ne cherchez surtout pas à atteindre artificiellement une durée.
Ne répétez pas les mêmes informations.
Ne rajoutez pas de phrases inutiles uniquement pour augmenter
le nombre de mots.

Une vidéo de 2 minutes 30 excellente est préférable à une vidéo
de 5 minutes remplie de répétitions.

Pour une narration naturelle, visez généralement environ
650 à 1000 mots, mais cette plage est INDICATIVE et non
bloquante.

Le contenu doit être suffisamment développé pour expliquer
correctement le sujet.

EXIGENCES FACTUELLES :

- N'inventez aucune étude.
- N'inventez aucun chiffre.
- N'inventez aucune citation.
- N'inventez aucun événement.
- N'inventez aucune date.
- Ne présentez pas une hypothèse comme un fait.
- Si une information est incertaine, dites-le clairement.
- Privilégiez les faits établis.
- Évitez les affirmations sensationnalistes non vérifiées.

STRUCTURE :

TITRE: titre YouTube

HOOK:
Accroche immédiate et intrigante.

INTRO:
Présentation rapide du sujet.

PARTIE 1:
Premier élément important.

PARTIE 2:
Deuxième élément important.

PARTIE 3:
Explication ou découverte importante.

PARTIE 4:
Exemple concret, conséquence ou élément surprenant.

CONCLUSION:
Synthèse claire et mémorable.

CTA:
Abonne-toi pour en savoir plus sur le monde.

RÈGLE VISUELLE :

Ajoutez des balises :

[IMAGE: english visual keywords]

environ toutes les 1 à 2 phrases.

Produisez environ 20 à 35 balises visuelles.

Les mots-clés visuels doivent être simples et pertinents
pour une recherche Pexels.

Exemples :

[IMAGE: human brain close up]

[IMAGE: person working desk]

[IMAGE: ancient city]

[IMAGE: scientist laboratory]

Évitez les logos, marques et personnages protégés.

IMPORTANT :

Le texte doit rester naturel lorsque les balises [IMAGE: ...]
sont retirées.
"""


    # -----------------------------------------------------
    # SCRIPT SHORT
    # -----------------------------------------------------

    short_system_prompt = f"""
Vous êtes un créateur professionnel de Shorts YouTube
en français.

SUJET :
{subject}

OBJECTIF :

Créer un TEASER court qui donne envie de regarder la vidéo
longue.

Le teaser doit durer environ 25 à 40 secondes.

Visez généralement environ 75 à 95 mots.

IMPORTANT :

Le teaser NE DOIT PAS raconter toute l'histoire.

Il doit :

1. Capturer immédiatement l'attention.
2. Présenter le mystère ou le problème.
3. Donner une ou deux informations intéressantes.
4. Créer une question.
5. S'arrêter AVANT la révélation principale.
6. Donner envie de regarder la vidéo complète.

Ne révélez pas toute la conclusion dans le teaser.

N'inventez aucun fait.

FORMAT :

TITRE: titre court

HOOK:
Accroche très forte.

TEASER:
Développement très rapide.

SUSPENSE:
Question ou élément qui donne envie de connaître la suite.

CTA:
Retrouve la vidéo complète sur la chaîne.

RÈGLE VISUELLE :

Ajoutez des balises :

[IMAGE: english visual keywords]

environ toutes les 1 à 2 phrases.

Produisez environ 8 à 12 balises visuelles.

Les mots-clés doivent être simples et adaptés à Pexels.
"""


    # -----------------------------------------------------
    # GÉNÉRATION
    # -----------------------------------------------------

    long_script = call_openrouter(
        [
            {
                "role": "system",
                "content": long_system_prompt
            },
            {
                "role": "user",
                "content": (
                    "Rédige maintenant le script documentaire "
                    f"sur : {subject}"
                )
            }
        ],
        max_tokens=4500,
        temperature=0.65
    )


    teaser_script = call_openrouter(
        [
            {
                "role": "system",
                "content": short_system_prompt
            },
            {
                "role": "user",
                "content": (
                    "Rédige maintenant le teaser "
                    f"sur : {subject}"
                )
            }
        ],
        max_tokens=900,
        temperature=0.7
    )


    return (
        long_script,
        teaser_script
    )


# =========================================================
# PARSING
# =========================================================

def parse_script(script_text):

    narration_parts = []
    visual_prompts = []

    for raw_line in script_text.splitlines():

        line = raw_line.strip()

        if not line:
            continue

        # ---------------------------------------------
        # Recherche des visuels
        # ---------------------------------------------

        matches = re.findall(
            r"(?:IMAGE|MEME|VISUEL)\s*:\s*([^]+)\]",
            line,
            re.IGNORECASE
        )

        for match in matches:

            keyword = match.strip()

            if keyword:
                visual_prompts.append(keyword)

        # ---------------------------------------------
        # Suppression des lignes non narrées
        # ---------------------------------------------

        if re.match(
            r"^(TITRE|HASHTAGS?|SOURCES?)\s*:",
            line,
            re.IGNORECASE
        ):
            continue

        # ---------------------------------------------
        # Nettoyage des balises visuelles
        # ---------------------------------------------

        cleaned = re.sub(
            r"(?:IMAGE|MEME|VISUEL)\s*:[^]+\]",
            "",
            line,
            flags=re.IGNORECASE
        )

        # ---------------------------------------------
        # Suppression des labels
        # ---------------------------------------------

        cleaned = re.sub(
            r"^(HOOK|INTRO|PARTIE\s*\d+|"
            r"TEASER|SUSPENSE|REVELATION|"
            r"CONCLUSION|CTA)\s*:\s*",
            "",
            cleaned,
            flags=re.IGNORECASE
        )

        cleaned = re.sub(
            r"[*_`]+",
            "",
            cleaned
        ).strip()

        if cleaned:
            narration_parts.append(cleaned)

    narration = " ".join(
        narration_parts
    )

    narration = re.sub(
        r"\s+",
        " ",
        narration
    ).strip()

    return (
        narration,
        visual_prompts
    )


# =========================================================
# EDGE-TTS
# =========================================================

async def generate_audio_with_boundaries_async(
    text,
    output_mp3
):
    """
    Génère la voix et récupère les WordBoundary réelles.
    """

    import edge_tts

    communicate = edge_tts.Communicate(
        text,
        VOICE,
        rate="+8%"
    )

    words = []

    audio_received = False

    with open(
        output_mp3,
        "wb"
    ) as audio_file:

        async for chunk in communicate.stream():

            chunk_type = chunk.get("type")

            # -----------------------------------------
            # AUDIO
            # -----------------------------------------

            if chunk_type == "audio":

                data = chunk.get("data")

                if data:
                    audio_file.write(data)
                    audio_received = True

            # -----------------------------------------
            # WORD BOUNDARY
            # -----------------------------------------

            elif chunk_type == "WordBoundary":

                word = str(
                    chunk.get("text", "")
                ).strip()

                offset = chunk.get("offset")
                duration = chunk.get("duration")

                if (
                    word
                    and offset is not None
                    and duration is not None
                ):

                    start = (
                        float(offset)
                        / 10_000_000
                    )

                    end = (
                        float(offset)
                        + float(duration)
                    ) / 10_000_000

                    words.append(
                        {
                            "text": word,
                            "start": start,
                            "end": end
                        }
                    )

    if not audio_received:
        raise RuntimeError(
            "Edge-TTS n'a reçu aucun flux audio."
        )

    if not words:
        raise RuntimeError(
            "Edge-TTS a généré l'audio mais "
            "aucune WordBoundary n'a été reçue."
        )

    if (
        not os.path.exists(output_mp3)
        or os.path.getsize(output_mp3) < 1000
    ):
        raise RuntimeError(
            "Le fichier audio généré est absent ou vide."
        )

    return words


def generate_audio(
    text,
    output_mp3
):
    """
    Génère la voix avec deux tentatives.
    """

    if not text.strip():

        return (
            None,
            None,
            "Narration vide, impossible de générer la voix."
        )

    last_error = None

    for attempt in range(2):

        try:

            if os.path.exists(output_mp3):
                os.remove(output_mp3)

            words = asyncio.run(
                generate_audio_with_boundaries_async(
                    text,
                    output_mp3
                )
            )

            duration = get_audio_duration(
                output_mp3
            )

            return (
                output_mp3,
                words,
                None
            )

        except Exception as exc:

            last_error = str(exc)

            if attempt == 0:
                retry_sleep(attempt)

    return (
        None,
        None,
        f"Edge-TTS a échoué: {last_error}"
    )


# =========================================================
# SOUS-TITRES ASS
# =========================================================

def generate_ass_subtitles(
    word_timings,
    output_ass,
    is_short=True
):
    """
    Sous-titres synchronisés avec les vrais timings
    de la voix.
    """

    if is_short:

        res_x = 1080
        res_y = 1920

        font_size = 58
        margin_v = 260

        # Short :
        # petits groupes pour une lecture rapide
        max_words = 3

    else:

        res_x = 1920
        res_y = 1080

        font_size = 44
        margin_v = 90

        # Long :
        # groupes légèrement plus grands
        max_words = 5


    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {res_x}
PlayResY: {res_y}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{font_size},&H00FFFFFF,&H00FFFFFF,&H00101010,&H90000000,-1,0,0,0,100,100,0,0,1,4,1,2,60,60,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


    with open(
        output_ass,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(header)

        for i in range(
            0,
            len(word_timings),
            max_words
        ):

            group = word_timings[
                i:i + max_words
            ]

            if not group:
                continue

            start = group[0]["start"]

            end = (
                group[-1]["end"]
                + 0.05
            )

            text = " ".join(
                item["text"]
                for item in group
            )

            text = (
                text
                .replace("{", "(")
                .replace("}", ")")
            )

            f.write(
                "Dialogue: 0,"
                f"{format_time_ass(start)},"
                f"{format_time_ass(end)},"
                "Default,,0,0,0,,"
                f"{text}\n"
            )

    return output_ass


# =========================================================
# PEXELS
# =========================================================

def pexels_headers():

    if not PEXELS_API_KEY:
        return {}

    return {
        "Authorization": PEXELS_API_KEY
    }


def clean_visual_query(keyword):

    keyword = re.sub(
        r"[^a-zA-Z0-9\s-]",
        " ",
        keyword
    )

    keyword = re.sub(
        r"\s+",
        " ",
        keyword
    ).strip()

    return (
        keyword[:100]
        or "abstract technology"
    )


def download_binary(
    url,
    output_path
):
    """
    Télécharge un fichier binaire.
    """

    response = requests.get(
        url,
        timeout=PEXELS_TIMEOUT,
        stream=True
    )

    response.raise_for_status()

    with open(
        output_path,
        "wb"
    ) as f:

        for chunk in response.iter_content(
            chunk_size=1024 * 128
        ):

            if chunk:
                f.write(chunk)

    return output_path


def fetch_pexels_photo(
    keyword,
    idx,
    temp_dir,
    is_short
):

    if not PEXELS_API_KEY:
        raise RuntimeError(
            "PEXELS_API_KEY manquante."
        )

    orientation = (
        "portrait"
        if is_short
        else "landscape"
    )

    clean_query = clean_visual_query(
        keyword
    )

    query_variants = [
        clean_query,
        clean_query.replace(
            "human",
            "person"
        ),
        clean_query.replace(
            "scientific",
            "science"
        )
    ]

    # Évite les doublons de requêtes.
    query_variants = list(
        dict.fromkeys(
            query_variants
        )
    )

    output = os.path.join(
        temp_dir,
        f"photo_{idx:03d}.jpg"
    )

    for query in query_variants:

        try:

            url = (
                "https://api.pexels.com/v1/search"
            )

            params = {
                "query": query,
                "orientation": orientation,
                "size": "large",
                "per_page": 15
            }

            response = requests.get(
                url,
                headers=pexels_headers(),
                params=params,
                timeout=PEXELS_TIMEOUT
            )

            if response.status_code != 200:
                continue

            photos = (
                response
                .json()
                .get("photos", [])
            )

            if not photos:
                continue

            candidates = photos[:10]

            random.shuffle(
                candidates
            )

            for photo in candidates:

                src = photo.get(
                    "src",
                    {}
                )

                image_url = (
                    src.get("large2x")
                    or src.get("large")
                    or src.get("original")
                )

                if not image_url:
                    continue

                try:

                    download_binary(
                        image_url,
                        output
                    )

                    if file_is_valid_image(
                        output
                    ):

                        return {
                            "type": "image",
                            "path": output,
                            "source_id": str(
                                photo.get(
                                    "id",
                                    idx
                                )
                            )
                        }

                except Exception:
                    continue

        except Exception:
            continue

    raise RuntimeError(
        "Aucun visuel Pexels trouvé pour: "
        f"{keyword}"
    )


def fetch_pexels_video(
    keyword,
    idx,
    temp_dir,
    is_short
):

    if not PEXELS_API_KEY:
        raise RuntimeError(
            "PEXELS_API_KEY manquante."
        )

    orientation = (
        "portrait"
        if is_short
        else "landscape"
    )

    query = clean_visual_query(
        keyword
    )

    output = os.path.join(
        temp_dir,
        f"clip_{idx:03d}.mp4"
    )

    try:

        response = requests.get(
            "https://api.pexels.com/v1/videos/search",
            headers=pexels_headers(),
            params={
                "query": query,
                "orientation": orientation,
                "size": "medium",
                "per_page": 10
            },
            timeout=PEXELS_TIMEOUT
        )

        if response.status_code != 200:
            return None

        videos = (
            response
            .json()
            .get("videos", [])
        )

        if not videos:
            return None

        random.shuffle(
            videos
        )

        for video in videos[:8]:

            files = video.get(
                "video_files",
                []
            )

            compatible = [
                item
                for item in files
                if (
                    item.get("link")
                    and item.get("width", 0) >= 720
                )
            ]

            if not compatible:
                continue

            compatible.sort(
                key=lambda item: abs(
                    item.get(
                        "width",
                        720
                    ) - 1080
                )
            )

            link = compatible[0]["link"]

            try:

                download_binary(
                    link,
                    output
                )

                duration = ffprobe_value(
                    output,
                    "format=duration"
                )

                if (
                    duration
                    and duration >= 1
                ):

                    return {
                        "type": "video",
                        "path": output,
                        "source_id": str(
                            video.get(
                                "id",
                                idx
                            )
                        ),
                        "duration": duration
                    }

            except Exception:

                if os.path.exists(output):
                    os.remove(output)

    except Exception:
        return None

    return None


def make_placeholder(
    keyword,
    idx,
    temp_dir,
    is_short
):

    if is_short:
        width, height = (
            1080,
            1920
        )
    else:
        width, height = (
            1920,
            1080
        )

    path = os.path.join(
        temp_dir,
        f"placeholder_{idx:03d}.jpg"
    )

    image = Image.new(
        "RGB",
        (width, height),
        (18, 22, 30)
    )

    image.save(
        path,
        quality=92
    )

    return {
        "type": "image",
        "path": path,
        "source_id": (
            f"placeholder-{idx}"
        )
    }


def fetch_visuals(
    prompts,
    temp_dir,
    is_short,
    target_count
):

    if not prompts:

        prompts = [
            "science laboratory",
            "human brain concept",
            "person thinking",
            "technology close up",
            "night city"
        ]

    # -----------------------------------------------------
    # On utilise les prompts existants puis on les recycle
    # uniquement si le modèle n'en a pas fourni assez.
    # -----------------------------------------------------

    original_prompts = list(
        prompts
    )

    prompts = []

    cursor = 0

    while len(prompts) < target_count:

        prompts.append(
            original_prompts[
                cursor
                % len(original_prompts)
            ]
        )

        cursor += 1


    jobs = []

    for idx, prompt in enumerate(
        prompts
    ):

        jobs.append(
            (
                idx,
                prompt
            )
        )


    results = [None] * len(
        jobs
    )


    def worker(item):

        idx, prompt = item

        # Short :
        # priorité aux vidéos.
        #
        # Long :
        # environ 1 visuel sur 3
        # peut être une vidéo.

        prefer_video = (
            is_short
            or idx % 3 == 1
        )

        if prefer_video:

            video = fetch_pexels_video(
                prompt,
                idx,
                temp_dir,
                is_short
            )

            if video:
                return (
                    idx,
                    video
                )

        # -------------------------------------------------
        # PHOTO
        # -------------------------------------------------

        try:

            photo = fetch_pexels_photo(
                prompt,
                idx,
                temp_dir,
                is_short
            )

            return (
                idx,
                photo
            )

        except Exception:

            # -------------------------------------------------
            # DERNIÈRE CHANCE : VIDÉO
            # -------------------------------------------------

            video = fetch_pexels_video(
                prompt,
                idx,
                temp_dir,
                is_short
            )

            if video:

                return (
                    idx,
                    video
                )

            # -------------------------------------------------
            # PLACEHOLDER
            # -------------------------------------------------

            return (
                idx,
                make_placeholder(
                    prompt,
                    idx,
                    temp_dir,
                    is_short
                )
            )


    with concurrent.futures.ThreadPoolExecutor(
        max_workers=MAX_PEXELS_WORKERS
    ) as executor:

        futures = [
            executor.submit(
                worker,
                job
            )
            for job in jobs
        ]

        for future in concurrent.futures.as_completed(
            futures
        ):

            idx, visual = future.result()

            results[idx] = visual


    return [
        item
        for item in results
        if (
            item
            and os.path.exists(
                item["path"]
            )
        )
    ]


# =========================================================
# MONTAGE DYNAMIQUE FFMPEG
# =========================================================

def render_image_scene(
    image_path,
    duration,
    output_path,
    is_short,
    effect_index
):

    if is_short:

        width, height = (
            1080,
            1920
        )

    else:

        width, height = (
            1920,
            1080
        )

    duration = max(
        0.8,
        float(duration)
    )

    fps = 25


    effects = [
        (1.00, 1.08, "center"),
        (1.08, 1.00, "center"),
        (1.00, 1.06, "left"),
        (1.06, 1.00, "right")
    ]

    start_zoom, end_zoom, anchor = (
        effects[
            effect_index
            % len(effects)
        ]
    )


    if anchor == "left":

        x_expr = (
            "iw/2-(iw/zoom/2)"
            "-min(iw/zoom/2,80)"
        )

    elif anchor == "right":

        x_expr = (
            "iw/2-(iw/zoom/2)"
            "+min(iw/zoom/2,80)"
        )

    else:

        x_expr = (
            "iw/2-(iw/zoom/2)"
        )


    y_expr = (
        "ih/2-(ih/zoom/2)"
    )


    total_frames = max(
        1,
        int(
            duration * fps
        )
    )

    zoom_expr = (
        f"{start_zoom}+"
        f"({end_zoom}-{start_zoom})"
        f"*on/{max(1, total_frames - 1)}"
    )


    vf = (
        f"scale={width * 2}:{height * 2}:"
        "force_original_aspect_ratio=increase,"
        f"crop={width * 2}:{height * 2},"
        f"zoompan="
        f"z='{zoom_expr}':"
        f"x='{x_expr}':"
        f"y='{y_expr}':"
        f"d={total_frames}:"
        f"s={width}x{height}:"
        f"fps={fps},"
        "format=yuv420p"
    )


    cmd = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-i",
        image_path,
        "-t",
        f"{duration:.3f}",
        "-vf",
        vf,
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "21",
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(fps),
        output_path
    ]


    code, _, stderr = run_command(
        cmd,
        timeout=max(
            90,
            int(duration * 12)
        )
    )


    if (
        code != 0
        or not os.path.exists(
            output_path
        )
        or os.path.getsize(
            output_path
        ) < 5000
    ):

        raise RuntimeError(
            "FFmpeg scène image: "
            f"{stderr[-2500:]}"
        )


    return output_path


def render_video_scene(
    video_path,
    duration,
    output_path,
    is_short
):

    if is_short:

        width,
