import os
import json
import random
import re
import subprocess
import tempfile
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

# Voix préférées.
# Le système essaiera automatiquement la suivante si la précédente échoue.
PREFERRED_VOICES = [
    "fr-FR-HenriNeural",
    "fr-FR-DeniseNeural",
    "fr-FR-EloiseNeural",
    "fr-FR-RemyMultilingualNeural",
    "fr-FR-VivienneMultilingualNeural",
]

REQUEST_TIMEOUT = 90
PEXELS_TIMEOUT = 20
MAX_PEXELS_WORKERS = 6

# Objectifs de durée.
MIN_LONG_DURATION = 120.0
MAX_LONG_DURATION = 900.0

MIN_SHORT_DURATION = 30.0
MAX_SHORT_DURATION = 45.0


# =========================================================
# OUTILS GENERAUX
# =========================================================

def run_command(cmd, timeout=None):
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
    if not audio_path:
        raise RuntimeError(
            "Chemin audio manquant."
        )

    if not os.path.exists(audio_path):
        raise RuntimeError(
            "Le fichier audio n'existe pas."
        )

    if os.path.getsize(audio_path) < 1000:
        raise RuntimeError(
            "Le fichier audio est vide ou trop petit."
        )

    duration = ffprobe_value(
        audio_path,
        "format=duration"
    )

    if duration is None or duration <= 0:
        raise RuntimeError(
            "FFprobe ne peut pas lire la durée de la voix off."
        )

    return duration


def file_is_valid_image(path):
    if not path or not os.path.exists(path):
        return False

    try:
        if os.path.getsize(path) < 1000:
            return False

        with Image.open(path) as img:
            img.verify()

        return True

    except (
        OSError,
        UnidentifiedImageError
    ):
        return False


def clean_filename(text):
    text = re.sub(
        r"[^a-zA-Z0-9_-]+",
        "_",
        text
    )

    text = text.strip("_")

    return text[:80] or "video"


def format_time_ass(seconds):
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
# GENERATION DES SCRIPTS
# =========================================================

def generate_pack_scripts(subject):

    long_system_prompt = f"""
Vous êtes un scénariste expert pour une vidéo YouTube
documentaire en français.

SUJET:
{subject}

OBJECTIF:

Créer une vidéo principale de plus de 2 minutes.

Le script doit contenir environ 800 à 1050 mots.

La narration doit être riche, structurée, naturelle,
captivante et suffisamment développée.

IMPORTANT:

Ne jamais inventer de faits.

Ne jamais inventer de chiffres.

Ne jamais inventer de citations.

Ne jamais inventer d'études.

Ne jamais inventer d'événements.

Si une information est incertaine, indiquez clairement
qu'elle est incertaine.

STRUCTURE:

TITRE:
titre YouTube

HOOK:
accroche forte

INTRO:
présentation du sujet

PARTIE 1:
première explication

PARTIE 2:
développement

PARTIE 3:
élément surprenant

PARTIE 4:
explication approfondie

CONCLUSION:
résumé et ouverture

CTA:
Abonne-toi pour en savoir plus sur le monde.

VISUELS:

Ajoutez une balise [IMAGE: english keywords]
environ toutes les 1 à 2 phrases.

Utilisez environ 25 à 40 balises visuelles.

Les mots-clés doivent être simples et exploitables
par une recherche Pexels.

Exemples:

[IMAGE: human brain]
[IMAGE: person thinking]
[IMAGE: neuroscience laboratory]
[IMAGE: sleeping person]

N'utilisez pas de descriptions extrêmement longues
pour les visuels.

Le texte doit rester naturel lorsque les balises
[IMAGE: ...] sont retirées.
"""

    short_system_prompt = f"""
Vous êtes créateur de Shorts YouTube.

SUJET:
{subject}

OBJECTIF:

Créer un teaser de 90 à 115 mots.

La durée cible est d'environ 30 à 40 secondes.

Le teaser doit être beaucoup plus court que la vidéo
principale.

Il doit donner envie de regarder la vidéo complète.

Il doit révéler suffisamment d'informations pour être
intéressant, sans raconter toute la vidéo.

N'inventez aucun fait.

FORMAT:

TITRE:
titre court

HOOK:
accroche très forte

TEASER:
développement rapide

REVELATION:
élément surprenant

CTA:
Retrouve la vidéo complète sur la chaîne.

VISUELS:

Ajoutez environ 8 à 12 balises:

[IMAGE: english visual keywords]

Les mots-clés doivent être simples et adaptés à Pexels.
"""

    long_script = call_openrouter(
        [
            {
                "role": "system",
                "content": long_system_prompt
            },
            {
                "role": "user",
                "content": (
                    "Rédige maintenant le script long "
                    f"sur le sujet suivant: {subject}"
                )
            }
        ],
        max_tokens=5000,
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
                    f"sur le sujet suivant: {subject}"
                )
            }
        ],
        max_tokens=1600,
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

        matches = re.findall(
            r"\[(?:IMAGE|MEME|VISUEL)\s*:\s*([^\]]+)\]",
            line,
            re.IGNORECASE
        )

        for match in matches:

            keyword = match.strip()

            if keyword:
                visual_prompts.append(keyword)

        if re.match(
            r"^(TITRE|HASHTAGS?|SOURCES?)\s*:",
            line,
            re.IGNORECASE
        ):
            continue

        cleaned = re.sub(
            r"\[(?:IMAGE|MEME|VISUEL)\s*:[^\]]+\]",
            "",
            line,
            flags=re.IGNORECASE
        )

        cleaned = re.sub(
            r"^(HOOK|INTRO|PARTIE\s*\d+|TEASER|REVELATION|CONCLUSION|CTA)\s*:\s*",
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

def get_available_french_voices():

    try:

        import edge_tts

        voices = asyncio_run_list_voices(
            edge_tts
        )

        available = []

        for voice in voices:

            short_name = voice.get(
                "ShortName",
                ""
            )

            locale = voice.get(
                "Locale",
                ""
            )

            if (
                short_name
                and locale.lower().startswith("fr")
            ):
                available.append(
                    short_name
                )

        return available

    except Exception:
        return []


def asyncio_run_list_voices(edge_tts_module):

    import asyncio

    return asyncio.run(
        edge_tts_module.list_voices()
    )


def build_voice_candidates():

    available = get_available_french_voices()

    candidates = []

    for voice in PREFERRED_VOICES:

        if voice in available:
            candidates.append(voice)

    for voice in available:

        if voice not in candidates:
            candidates.append(voice)

    if not candidates:
        candidates = list(
            PREFERRED_VOICES
        )

    return candidates


def clean_tts_text(text):

    text = text.replace(
        "\u000b",
        " "
    )

    text = text.replace(
        "\x00",
        " "
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def split_text_for_tts(
    text,
    max_chars=2400
):

    text = clean_tts_text(text)

    if len(text) <= max_chars:
        return [text]

    sentences = re.split(
        r"(?<=[.!?])\s+",
        text
    )

    chunks = []
    current = ""

    for sentence in sentences:

        sentence = sentence.strip()

        if not sentence:
            continue

        candidate = (
            f"{current} {sentence}"
        ).strip()

        if (
            current
            and len(candidate) > max_chars
        ):

            chunks.append(
                current.strip()
            )

            current = sentence

        else:

            current = candidate

    if current:
        chunks.append(
            current.strip()
        )

    return chunks


def generate_tts_chunk(
    text,
    voice
):

    import edge_tts

    communicate = edge_tts.Communicate(
        text,
        voice,
        rate="+5%",
        boundary="WordBoundary"
    )

    audio_chunks = []
    word_timings = []

    for chunk in communicate.stream_sync():

        chunk_type = chunk.get(
            "type"
        )

        if chunk_type == "audio":

            data = chunk.get(
                "data"
            )

            if data:
                audio_chunks.append(
                    data
                )

        elif chunk_type == "WordBoundary":

            word = str(
                chunk.get(
                    "text",
                    ""
                )
            ).strip()

            offset = chunk.get(
                "offset"
            )

            duration = chunk.get(
                "duration"
            )

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

                word_timings.append(
                    {
                        "text": word,
                        "start": start,
                        "end": end
                    }
                )

    if not audio_chunks:

        raise RuntimeError(
            "No audio was received."
        )

    return (
        b"".join(audio_chunks),
        word_timings
    )


def write_mp3_from_chunks(
    audio_chunks,
    output_path
):

    with open(
        output_path,
        "wb"
    ) as f:

        for chunk in audio_chunks:

            f.write(chunk)


def generate_audio(
    text,
    output_mp3
):

    if not text or not text.strip():

        return (
            None,
            None,
            "Narration vide."
        )

    text = clean_tts_text(
        text
    )

    chunks = split_text_for_tts(
        text
    )

    voices = build_voice_candidates()

    errors = []

    for voice in voices:

        all_audio_chunks = []
        all_word_timings = []

        global_offset = 0.0

        voice_failed = False

        for chunk_index, chunk_text in enumerate(chunks):

            success = False
            last_error = None

            for attempt in range(3):

                try:

                    audio_data, words = generate_tts_chunk(
                        chunk_text,
                        voice
                    )

                    if not audio_data:
                        raise RuntimeError(
                            "Flux audio vide."
                        )

                    all_audio_chunks.append(
                        audio_data
                    )

                    for item in words:

                        all_word_timings.append(
                            {
                                "text": item["text"],
                                "start": (
                                    item["start"]
                                    + global_offset
                                ),
                                "end": (
                                    item["end"]
                                    + global_offset
                                )
                            }
                        )

                    # Durée estimée par les WordBoundary.
                    if words:

                        chunk_duration = max(
                            item["end"]
                            for item in words
                        )

                        global_offset += (
                            chunk_duration
                            + 0.05
                        )

                    success = True
                    break

                except Exception as exc:

                    last_error = str(exc)

                    if attempt < 2:
                        retry_sleep(
                            attempt
                        )

            if not success:

                voice_failed = True

                errors.append(
                    f"{voice} - morceau "
                    f"{chunk_index + 1}: "
                    f"{last_error}"
                )

                break

        if voice_failed:
            continue

        if not all_audio_chunks:
            continue

        try:

            write_mp3_from_chunks(
                all_audio_chunks,
                output_mp3
            )

            duration = get_audio_duration(
                output_mp3
            )

            if duration <= 0:
                raise RuntimeError(
                    "Durée audio invalide."
                )

            if not all_word_timings:
                raise RuntimeError(
                    "Aucune WordBoundary reçue."
                )

            return (
                output_mp3,
                all_word_timings,
                None
            )

        except Exception as exc:

            errors.append(
                f"{voice} - validation: "
                f"{exc}"
            )

            if os.path.exists(
                output_mp3
            ):

                try:
                    os.remove(
                        output_mp3
                    )
                except Exception:
                    pass

    error_text = "\n".join(
        errors[-12:]
    )

    return (
        None,
        None,
        "Edge-TTS n'a réussi avec aucune voix française.\n\n"
        "Voix essayées:\n"
        + "\n".join(voices)
        + "\n\nDétails:\n"
        + error_text
    )


# =========================================================
# SOUS-TITRES ASS
# =========================================================

def generate_ass_subtitles(
    word_timings,
    output_ass,
    is_short=True
):

    res_x = (
        1080
        if is_short
        else 1920
    )

    res_y = (
        1920
        if is_short
        else 1080
    )

    font_size = (
        58
        if is_short
        else 44
    )

    margin_v = (
        260
        if is_short
        else 90
    )

    max_words = (
        3
        if is_short
        else 5
    )

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

        f.write(
            header
        )

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
                + 0.08
            )

            text = " ".join(
                item["text"]
                for item in group
            )

            text = (
                text
                .replace(
                    "{",
                    "("
                )
                .replace(
                    "}",
                    ")"
                )
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
        ),
    ]

    output = os.path.join(
        temp_dir,
        f"photo_{idx:03d}.jpg"
    )

    for query in query_variants:

        try:

            response = requests.get(
                "https://api.pexels.com/v1/search",
                headers=pexels_headers(),
                params={
                    "query": query,
                    "orientation": orientation,
                    "size": "large",
                    "per_page": 15
                },
                timeout=PEXELS_TIMEOUT
            )

            if response.status_code != 200:
                continue

            photos = (
                response
                .json()
                .get(
                    "photos",
                    []
                )
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
        f"Aucun visuel Pexels pour: "
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
            .get(
                "videos",
                []
            )
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
                    and item.get(
                        "width",
                        0
                    ) >= 720
                )
            ]

            if not compatible:
                continue

            compatible.sort(
                key=lambda item:
                abs(
                    item.get(
                        "width",
                        720
                    ) - 1080
                )
            )

            link = compatible[0][
                "link"
            ]

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

                if os.path.exists(
                    output
                ):

                    try:
                        os.remove(
                            output
                        )
                    except Exception:
                        pass

    except Exception:
        return None

    return None


def make_placeholder(
    keyword,
    idx,
    temp_dir,
    is_short
):

    width, height = (
        (1080, 1920)
        if is_short
        else (1920, 1080)
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

    unique_prompts = []

    for prompt in prompts:

        prompt = clean_visual_query(
            prompt
        )

        if (
            prompt
            and prompt not in unique_prompts
        ):

            unique_prompts.append(
                prompt
            )

    if not unique_prompts:

        unique_prompts = [
            "human brain",
            "person thinking",
            "science laboratory"
        ]

    expanded = []

    index = 0

    while len(expanded) < target_count:

        expanded.append(
            unique_prompts[
                index
                % len(unique_prompts)
            ]
        )

        index += 1

    expanded = expanded[
        :target_count
    ]

    jobs = [
        (idx, prompt)
        for idx, prompt
        in enumerate(expanded)
    ]

    results = [
        None
    ] * len(jobs)

    def worker(item):

        idx, prompt = item

        # Les Shorts utilisent davantage de vidéos.
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
                return idx, video

        try:

            photo = fetch_pexels_photo(
                prompt,
                idx,
                temp_dir,
                is_short
            )

            return idx, photo

        except Exception:

            video = fetch_pexels_video(
                prompt,
                idx,
                temp_dir,
                is_short
            )

            if video:
                return idx, video

            return idx, make_placeholder(
                prompt,
                idx,
                temp_dir,
                is_short
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
# MONTAGE IMAGE
# =========================================================

def render_image_scene(
    image_path,
    duration,
    output_path,
    is_short,
    effect_index
):

    width, height = (
        (1080, 1920)
        if is_short
        else (1920, 1080)
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
        (1.06, 1.00, "right"),
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
            "FFmpeg scène image:\n"
            + stderr[-2500:]
        )

    return output_path


# =========================================================
# MONTAGE VIDEO
# =========================================================

def render_video_scene(
    video_path,
    duration,
    output_path,
    is_short
):

    width, height = (
        (1080, 1920)
        if is_short
        else (1920, 1080)
    )

    duration = max(
        0.8,
        float(duration)
    )

    vf = (
        f"scale={width}:{height}:"
        "force_original_aspect_ratio=increase,"
        f"crop={width}:{height},"
        "format=yuv420p"
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-stream_loop",
        "-1",
        "-i",
        video_path,
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
        "25",
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
            "FFmpeg scène vidéo:\n"
            + stderr[-2500:]
        )

    return output_path


# =========================================================
# CONCATENATION
# =========================================================

def concat_scene_files(
    scene_files,
    output_path
):

    concat_file = os.path.join(
        os.path.dirname(
            output_path
        ),
        "scenes.txt"
    )

    with open(
        concat_file,
        "w",
        encoding="utf-8"
    ) as f:

        for path in scene_files:

            safe = (
                os.path.abspath(path)
                .replace(
                    "\\",
                    "/"
                )
                .replace(
                    "'",
                    "'\\''"
                )
            )

            f.write(
                f"file '{safe}'\n"
            )

    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        concat_file,
        "-c",
        "copy",
        output_path
    ]

    code, _, stderr = run_command(
        cmd,
        timeout=300
    )

    if (
        code != 0
        or not os.path.exists(
            output_path
        )
    ):

        raise RuntimeError(
            "FFmpeg concat:\n"
            + stderr[-3000:]
        )

    return output_path


# =========================================================
# CALCUL DES DUREES DES SCENES
# =========================================================

def calculate_scene_durations(
    audio_duration,
    scene_count
):

    if scene_count <= 0:
        return []

    minimum_scene = 1.25

    if audio_duration < (
        minimum_scene
        * scene_count
    ):

        scene_count = max(
            1,
            int(
                audio_duration
                / minimum_scene
            )
        )

    if scene_count == 1:
        return [
            audio_duration
        ]

    weights = []

    for idx in range(
        scene_count
    ):

        variation = (
            0.85
            + (
                (
                    idx * 17
                ) % 30
            ) / 100
        )

        weights.append(
            variation
        )

    total_weight = sum(
        weights
    )

    durations = [
        audio_duration
        * weight
        / total_weight
        for weight in weights
    ]

    # Garantit une durée minimum.
    durations = [
        max(
            minimum_scene,
            value
        )
        for value in durations
    ]

    total = sum(
        durations
    )

    # On renormalise pour correspondre exactement
    # à la durée de l'audio.
    scale = (
        audio_duration
        / total
    )

    durations = [
        value * scale
        for value in durations
    ]

    # Correction finale des arrondis.
    difference = (
        audio_duration
        - sum(durations)
    )

    durations[-1] += difference

    return durations


# =========================================================
# CREATION VIDEO
# =========================================================

def create_video_ffmpeg(
    visuals,
    audio_path,
    ass_subtitles_path,
    output_path,
    is_short
):

    if not visuals:
        return (
            None,
            "Aucun visuel disponible."
        )

    if (
        not audio_path
        or not os.path.exists(
            audio_path
        )
    ):

        return (
            None,
            "Voix off absente."
        )

    if (
        not ass_subtitles_path
        or not os.path.exists(
            ass_subtitles_path
        )
    ):

        return (
            None,
            "Sous-titres absents."
        )

    try:

        audio_duration = get_audio_duration(
            audio_path
        )

        if audio_duration <= 0:
            raise RuntimeError(
                "Durée audio invalide."
            )

        # On évite un nombre excessif de scènes.
        if is_short:

            scene_count = min(
                len(visuals),
                12
            )

        else:

            scene_count = min(
                len(visuals),
                max(
                    20,
                    min(
                        35,
                        int(
                            audio_duration
                            / 4.0
                        )
                    )
                )
            )

        visuals = visuals[
            :scene_count
        ]

        scene_count = len(
            visuals
        )

        durations = calculate_scene_durations(
            audio_duration,
            scene_count
        )

        temp_dir = tempfile.mkdtemp(
            prefix="studio_scenes_"
        )

        scene_files = []

        for idx, visual in enumerate(
            visuals
        ):

            duration = durations[
                idx
            ]

            scene_path = os.path.join(
                temp_dir,
                f"scene_{idx:03d}.mp4"
            )

            if visual["type"] == "video":

                render_video_scene(
                    visual["path"],
                    duration,
                    scene_path,
                    is_short
                )

            else:

                render_image_scene(
                    visual["path"],
                    duration,
                    scene_path,
                    is_short,
                    idx
                )

            scene_files.append(
                scene_path
            )

        silent_video = os.path.join(
            temp_dir,
            "silent.mp4"
        )

        concat_scene_files(
            scene_files,
            silent_video
        )

        width, height = (
            (1080, 1920)
            if is_short
            else (1920, 1080)
        )

        clean_ass = os.path.abspath(
            ass_subtitles_path
        ).replace(
            "\\",
            "/"
        )

        if os.name == "nt":
            clean_ass = clean_ass.replace(
                ":",
                "\\:"
            )

        cmd = [
            "ffmpeg",
            "-y",

            "-i",
            silent_video,

            "-i",
            audio_path,

            "-filter_complex",
            f"[0:v]subtitles='{clean_ass}'[v]",

            "-map",
            "[v]",

            "-map",
            "1:a:0",

            "-c:v",
            "libx264",

            "-preset",
            "veryfast",

            "-crf",
            "21",

            "-pix_fmt",
            "yuv420p",

            "-c:a",
            "aac",

            "-b:a",
            "192k",

            "-ar",
            "48000",

            "-r",
            "25",

            "-shortest",

            "-movflags",
            "+faststart",

            output_path
        ]

        code, stdout, stderr = run_command(
            cmd,
            timeout=900
        )

        if (
            code != 0
            or not os.path.exists(
                output_path
            )
            or os.path.getsize(
                output_path
            ) < 10000
        ):

            log_path = (
                output_path
                + ".ffmpeg.log.txt"
            )

            with open(
                log_path,
                "w",
                encoding="utf-8"
            ) as log:

                log.write(
                    "STDOUT\n"
                )

                log.write(
                    stdout or ""
                )

                log.write(
                    "\n\nSTDERR\n"
                )

                log.write(
                    stderr or ""
                )

            return (
                None,
                "FFmpeg a échoué.\n\n"
                f"Log complet: {log_path}\n\n"
                + stderr[-4000:]
            )

        duration = ffprobe_value(
            output_path,
            "format=duration"
        )

        if (
            duration is None
            or duration <= 0
        ):

            return (
                None,
                "Le MP4 final est illisible."
            )

        # Vérification audio.
        probe_cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            output_path
        ]

        code, stdout, _ = run_command(
            probe_cmd,
            timeout=30
        )

        if (
            code != 0
            or not stdout.strip()
        ):

            return (
                None,
                "Contrôle qualité échoué: "
                "aucune piste audio."
            )

        return (
            output_path,
            None
        )

    except Exception as exc:

        return (
            None,
            f"Erreur montage: {exc}"
        )


# =========================================================
# VALIDATION DES DUREES
# =========================================================

def validate_duration(
    duration,
    is_short
):

    if duration is None:

        return (
            False,
            "Durée impossible à déterminer."
        )

    if is_short:

        if (
            duration
            < MIN_SHORT_DURATION
            or duration
            > MAX_SHORT_DURATION
        ):

            return (
                False,
                (
                    f"Le Short dure "
                    f"{duration:.1f}s. "
                    f"Il doit être entre "
                    f"{MIN_SHORT_DURATION:.0f} "
                    f"et "
                    f"{MAX_SHORT_DURATION:.0f} "
                    "secondes."
                )
            )

        return (
            True,
            None
        )

    if (
        duration
        <= MIN_LONG_DURATION
    ):

        return (
            False,
            (
                f"La vidéo longue dure "
                f"{duration:.1f}s. "
                "Elle doit dépasser "
                "2 minutes."
            )
        )

    if (
        duration
        > MAX_LONG_DURATION
    ):

        return (
            False,
            (
                f"La vidéo longue dure "
                f"{duration:.1f}s. "
                "Elle dépasse la limite "
                "raisonnable de génération."
            )
        )

    return (
        True,
        None
    )


# =========================================================
# INTERFACE
# =========================================================

st.title(
    "🎬 Studio Vidéo IA"
)

st.write(
    "Création automatique d'une vidéo longue "
    "et d'un Short avec voix off, "
    "sous-titres synchronisés et montage dynamique."
)


with st.expander(
    "⚙️ État de la configuration",
    expanded=False
):

    if OPENROUTER_API_KEY:
        st.success(
            "OpenRouter configuré"
        )
    else:
        st.error(
            "OPENROUTER_API_KEY manquante"
        )

    if PEXELS_API_KEY:
        st.success(
            "Pexels configuré"
        )
    else:
        st.error(
            "PEXELS_API_KEY manquante"
        )

    st.info(
        "Voix principale: "
        "fr-FR-HenriNeural\n\n"
        "Voix de secours: "
        "Denise, Eloise et autres voix françaises disponibles."
    )


subject_input = st.text_input(
    "Sujet principal de la vidéo",
    placeholder=(
        "Exemple: Pourquoi le cerveau procrastine ?"
    ),
    key="subject_main"
)


if st.button(
    "🚀 Générer le Pack Duo",
    key="btn_pack",
    type="primary"
):

    if not subject_input.strip():

        st.warning(
            "Veuillez saisir un sujet."
        )

        st.stop()

    if not OPENROUTER_API_KEY:

        st.error(
            "OPENROUTER_API_KEY manquante."
        )

        st.stop()

    if not PEXELS_API_KEY:

        st.error(
            "PEXELS_API_KEY manquante."
        )

        st.stop()

    run_id = (
        clean_filename(
            subject_input
        )
        + "_"
        + str(
            int(
                time.time()
            )
        )
    )

    work_dir = os.path.join(
        tempfile.gettempdir(),
        "studio_video",
        run_id
    )

    os.makedirs(
        work_dir,
        exist_ok=True
    )

    progress = st.progress(
        0
    )

    status = st.empty()

    try:

        # =================================================
        # 1. SCRIPTS
        # =================================================

        status.info(
            "1/7 Génération des deux scripts..."
        )

        progress.progress(
            5
        )

        script_long, script_teaser = (
            generate_pack_scripts(
                subject_input.strip()
            )
        )

        narration_long, prompts_long = (
            parse_script(
                script_long
            )
        )

        narration_teaser, prompts_teaser = (
            parse_script(
                script_teaser
            )
        )

        long_word_count = len(
            narration_long.split()
        )

        short_word_count = len(
            narration_teaser.split()
        )

        if long_word_count < 700:

            raise RuntimeError(
                (
                    f"Le script long contient "
                    f"{long_word_count} mots. "
                    "Il est trop court. "
                    "Il faut au moins environ "
                    "700 mots pour viser plus "
                    "de 2 minutes."
                )
            )

        if (
            short_word_count < 80
            or short_word_count > 130
        ):

            raise RuntimeError(
                (
                    f"Le teaser contient "
                    f"{short_word_count} mots. "
                    "Il doit contenir environ "
                    "90 à 115 mots."
                )
            )

        with st.expander(
            "📜 Voir les scripts",
            expanded=False
        ):

            st.write(
                f"Script long: "
                f"{long_word_count} mots"
            )

            st.text_area(
                "Script long",
                script_long,
                height=350
            )

            st.write(
                f"Script Short: "
                f"{short_word_count} mots"
            )

            st.text_area(
                "Script Short",
                script_teaser,
                height=250
            )

        # =================================================
        # 2. VOIX LONGUE
        # =================================================

        status.info(
            "2/7 Génération de la voix off longue..."
        )

        progress.progress(
            15
        )

        long_audio = os.path.join(
            work_dir,
            "long_voice.mp3"
        )

        long_ass = os.path.join(
            work_dir,
            "long_subs.ass"
        )

        audio_long, words_long, err = (
            generate_audio(
                narration_long,
                long_audio
            )
        )

        if err:
            raise RuntimeError(
                "Voix longue:\n\n"
                + err
            )

        duration_long = get_audio_duration(
            audio_long
        )

        valid, duration_error = (
            validate_duration(
                duration_long,
                False
            )
        )

        if not valid:

            raise RuntimeError(
                duration_error
            )

        generate_ass_subtitles(
            words_long,
            long_ass,
            is_short=False
        )

        st.success(
            (
                f"Voix longue générée: "
                f"{duration_long:.1f}s"
            )
        )

        # =================================================
        # 3. VOIX SHORT
        # =================================================

        status.info(
            "3/7 Génération de la voix off du Short..."
        )

        progress.progress(
            30
        )

        teaser_audio = os.path.join(
            work_dir,
            "teaser_voice.mp3"
        )

        teaser_ass = os.path.join(
            work_dir,
            "teaser_subs.ass"
        )

        audio_teaser, words_teaser, err = (
            generate_audio(
                narration_teaser,
                teaser_audio
            )
        )

        if err:

            raise RuntimeError(
                "Voix Short:\n\n"
                + err
            )

        duration_teaser = get_audio_duration(
            audio_teaser
        )

        valid, duration_error = (
            validate_duration(
                duration_teaser,
                True
            )
        )

        if not valid:

            raise RuntimeError(
                duration_error
            )

        generate_ass_subtitles(
            words_teaser,
            teaser_ass,
            is_short=True
        )

        st.success(
            (
                f"Voix Short générée: "
                f"{duration_teaser:.1f}s"
            )
        )

        # =================================================
        # 4. VISUELS LONGS
        # =================================================

        count_long = max(
            20,
            min(
                35,
                int(
                    duration_long
                    / 4.0
                )
            )
        )

        status.info(
            (
                "4/7 Téléchargement des "
                f"visuels longs "
                f"({count_long})..."
            )
        )

        progress.progress(
            45
        )

        long_visual_dir = os.path.join(
            work_dir,
            "visuals_long"
        )

        os.makedirs(
            long_visual_dir,
            exist_ok=True
        )

        visuals_long = fetch_visuals(
            prompts_long,
            long_visual_dir,
            is_short=False,
            target_count=count_long
        )

        if len(
            visuals_long
        ) < 10:

            raise RuntimeError(
                "Trop peu de visuels valides "
                "pour le montage long."
            )

        # =================================================
        # 5. VISUELS SHORT
        # =================================================

        count_teaser = max(
            8,
            min(
                12,
                int(
                    duration_teaser
                    / 3.0
                )
            )
        )

        status.info(
            (
                "5/7 Téléchargement des "
                f"visuels du Short "
                f"({count_teaser})..."
            )
        )

        progress.progress(
            58
        )

        teaser_visual_dir = os.path.join(
            work_dir,
            "visuals_teaser"
        )

        os.makedirs(
            teaser_visual_dir,
            exist_ok=True
        )

        visuals_teaser = fetch_visuals(
            prompts_teaser,
            teaser_visual_dir,
            is_short=True,
            target_count=count_teaser
        )

        if len(
            visuals_teaser
        ) < 6:

            raise RuntimeError(
                "Trop peu de visuels valides "
                "pour le Short."
            )

        # =================================================
        # 6. MONTAGE LONG
        # =================================================

        status.info(
            "6/7 Montage dynamique de la vidéo longue..."
        )

        progress.progress(
            70
        )

        long_output = os.path.join(
            work_dir,
            "long_final.mp4"
        )

        video_long, err = (
            create_video_ffmpeg(
                visuals_long,
                audio_long,
                long_ass,
                long_output,
                is_short=False
            )
        )

        if not video_long:

            raise RuntimeError(
                err
            )

        # =================================================
        # 6. MONTAGE SHORT
        # =================================================

        status.info(
            "6/7 Montage dynamique du Short..."
        )

        progress.progress(
            84
        )

        teaser_output = os.path.join(
            work_dir,
            "teaser_final.mp4"
        )

        video_teaser, err = (
            create_video_ffmpeg(
                visuals_teaser,
                audio_teaser,
                teaser_ass,
                teaser_output,
                is_short=True
            )
        )

        if not video_teaser:

            raise RuntimeError(
                err
            )

        # =================================================
        # 7. CONTROLE QUALITE
        # =================================================

        status.info(
            "7/7 Contrôle qualité final..."
        )

        progress.progress(
            95
        )

        final_long_duration = (
            ffprobe_value(
                long_output,
                "format=duration"
            )
        )

        final_teaser_duration = (
            ffprobe_value(
                teaser_output,
                "format=duration"
            )
        )

        valid_long, err_long = (
            validate_duration(
                final_long_duration,
                False
            )
        )

        valid_teaser, err_teaser = (
            validate_duration(
                final_teaser_duration,
                True
            )
        )

        if not valid_long:

            raise RuntimeError(
                (
                    "Contrôle vidéo longue: "
                    + err_long
                )
            )

        if not valid_teaser:

            raise RuntimeError(
                (
                    "Contrôle Short: "
                    + err_teaser
                )
            )

        progress.progress(
            100
        )

        status.success(
            "🎉 Génération terminée. "
            "Les deux vidéos ont passé les contrôles."
        )

        # =================================================
        # RESULTATS
        # =================================================

        col1, col2 = st.columns(
            2
        )

        with col1:

            st.subheader(
                "🎥 Vidéo longue"
            )

            st.caption(
                (
                    f"Durée: "
                    f"{final_long_duration:.1f}s "
                    f"| "
                    f"{len(visuals_long)} visuels"
                )
            )

            st.video(
                long_output
            )

            with open(
                long_output,
                "rb"
            ) as f:

                st.download_button(
                    "📥 Télécharger la vidéo longue",
                    data=f.read(),
                    file_name=(
                        "video_longue.mp4"
                    ),
                    mime="video/mp4",
                    key="download_long"
                )

        with col2:

            st.subheader(
                "📱 Short teaser"
            )

            st.caption(
                (
                    f"Durée: "
                    f"{final_teaser_duration:.1f}s "
                    f"| "
                    f"{len(visuals_teaser)} visuels"
                )
            )

            st.video(
                teaser_output
            )

            with open(
                teaser_output,
                "rb"
            ) as f:

                st.download_button(
                    "📥 Télécharger le Short",
                    data=f.read(),
                    file_name=(
                        "short_teaser.mp4"
                    ),
                    mime="video/mp4",
                    key="download_teaser"
                )

    except Exception as exc:

        progress.empty()

        status.error(
            "❌ La génération a été arrêtée."
        )

        st.error(
            str(exc)
        )

        st.caption(
            "Dossier de travail:"
        )

        st.code(
            work_dir
)
