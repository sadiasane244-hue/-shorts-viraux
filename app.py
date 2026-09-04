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


# =========================================================
# OUTILS GÉNÉRAUX
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
    if not path:
        return None

    if not os.path.exists(path):
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
    if not path:
        return False

    if not os.path.exists(path):
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
# GÉNÉRATION DES SCRIPTS
# =========================================================

def build_long_prompt(subject):
    return f"""
Vous êtes un scénariste expert pour une chaîne YouTube
francophone.

SUJET :
{subject}

OBJECTIF :

Créer une vidéo longue informative, captivante et naturelle.

La vidéo ne doit PAS être artificiellement rallongée.

La durée cible est d'environ 3 à 4 minutes, mais la priorité
absolue est que le contenu soit intéressant, cohérent et utile.

Le script doit contenir environ 500 à 700 mots.

IMPORTANT :

Le contenu doit être factuel.

N'inventez aucune étude.

N'inventez aucun chiffre.

N'inventez aucune citation.

N'inventez aucun événement.

N'affirmez pas comme certain un élément incertain.

Si une information est controversée ou incertaine,
présentez-la clairement comme telle.

Le script doit avoir une progression narrative.

Commencez avec un HOOK très fort.

Le spectateur doit comprendre rapidement pourquoi
le sujet est intéressant.

Ensuite :

1. HOOK
2. INTRODUCTION
3. PREMIÈRE EXPLICATION
4. DEUXIÈME EXPLICATION
5. EXEMPLE OU CAS CONCRET
6. RÉVÉLATION OU INFORMATION SURPRENANTE
7. CONCLUSION
8. CTA

Ne répétez pas inutilement les mêmes informations.

La narration doit être naturelle lorsqu'elle est lue par
une voix off.

FORMAT :

TITRE: titre de la vidéo

HOOK: narration [IMAGE: english visual keywords]

INTRO: narration [IMAGE: english visual keywords]

PARTIE 1: narration [IMAGE: english visual keywords]

PARTIE 2: narration [IMAGE: english visual keywords]

PARTIE 3: narration [IMAGE: english visual keywords]

PARTIE 4: narration [IMAGE: english visual keywords]

REVELATION: narration [IMAGE: english visual keywords]

CONCLUSION: narration [IMAGE: english visual keywords]

CTA: Abonne-toi pour en savoir plus sur le monde.
[IMAGE: youtube subscribe]

RÈGLE VISUELLE :

Ajoutez une balise [IMAGE: ...] environ toutes les
1 à 2 phrases.

Utilisez des mots-clés simples en anglais.

Les mots-clés doivent décrire précisément ce qui est
raconté à ce moment-là.

Produisez environ 25 à 40 balises visuelles.

Ne produisez pas 100 images.

Ne mettez pas de texte explicatif autour du script.
"""


def build_short_prompt(subject):
    return f"""
Vous êtes un créateur expert de YouTube Shorts.

SUJET :
{subject}

OBJECTIF :

Créer un teaser très captivant qui donne envie de regarder
la vidéo longue.

Le Short doit être nettement plus court que la vidéo longue.

Durée cible :
30 à 45 secondes.

Le script doit contenir environ 85 à 110 mots.

Le contenu doit rester factuel.

N'inventez aucune étude.

N'inventez aucun chiffre.

N'inventez aucun événement.

N'inventez aucune citation.

Le teaser doit donner une information intéressante sans
révéler absolument toute la vidéo longue.

STRUCTURE :

1. HOOK très fort
2. Mise en contexte rapide
3. Information surprenante
4. Question ou révélation
5. Invitation à regarder la vidéo complète

FORMAT :

TITRE: titre court

HOOK: narration [IMAGE: english visual keywords]

TEASER: narration [IMAGE: english visual keywords]

REVELATION: narration [IMAGE: english visual keywords]

CTA: Retrouve la vidéo complète sur la chaîne.
[IMAGE: youtube subscribe]

Ajoutez une balise [IMAGE: ...] environ toutes les
1 à 2 phrases.

Produisez environ 8 à 14 balises visuelles.

Ne produisez pas 50 images.

Ne mettez pas d'explications supplémentaires.
"""


def generate_long_script(subject):
    prompt = build_long_prompt(subject)

    last_script = None
    last_count = 0

    for attempt in range(3):

        extra_instruction = ""

        if attempt > 0:
            extra_instruction = f"""
IMPORTANT :
Votre précédente réponse était trop courte.

Elle contenait environ {last_count} mots.

Cette fois, produisez impérativement un script
d'environ 500 à 700 mots.

Ne remplissez pas artificiellement le texte.

Ajoutez de vraies explications, exemples et informations
pertinentes sur le sujet.
"""

        script = call_openrouter(
            [
                {
                    "role": "system",
                    "content": prompt
                },
                {
                    "role": "user",
                    "content": (
                        f"Rédige maintenant le script long "
                        f"sur : {subject}\n\n"
                        f"{extra_instruction}"
                    )
                }
            ],
            max_tokens=3500,
            temperature=0.65
        )

        narration, _ = parse_script(script)

        count = len(
            narration.split()
        )

        last_script = script
        last_count = count

        if count >= 400:
            return script

        if attempt < 2:
            retry_sleep(attempt)

    raise RuntimeError(
        f"Le modèle génère un script long trop court "
        f"après 3 tentatives ({last_count} mots). "
        f"Minimum accepté : 400 mots."
    )


def generate_short_script(subject):
    prompt = build_short_prompt(subject)

    last_script = None
    last_count = 0

    for attempt in range(3):

        extra_instruction = ""

        if attempt > 0:
            extra_instruction = f"""
IMPORTANT :
Votre précédente réponse contenait environ
{last_count} mots.

Le Short doit contenir entre 85 et 110 mots.

Réécrivez complètement le teaser.
"""

        script = call_openrouter(
            [
                {
                    "role": "system",
                    "content": prompt
                },
                {
                    "role": "user",
                    "content": (
                        f"Rédige maintenant le Short "
                        f"sur : {subject}\n\n"
                        f"{extra_instruction}"
                    )
                }
            ],
            max_tokens=1000,
            temperature=0.7
        )

        narration, _ = parse_script(script)

        count = len(
            narration.split()
        )

        last_script = script
        last_count = count

        if 70 <= count <= 130:
            return script

        if attempt < 2:
            retry_sleep(attempt)

    raise RuntimeError(
        f"Le Short généré contient {last_count} mots "
        f"après 3 tentatives. "
        f"Une nouvelle génération est nécessaire."
    )


def generate_pack_scripts(subject):
    long_script = generate_long_script(
        subject
    )

    teaser_script = generate_short_script(
        subject
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
                visual_prompts.append(
                    keyword
                )

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
            narration_parts.append(
                cleaned
            )

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
# EDGE TTS
# =========================================================

async def generate_audio_with_boundaries_async(
    text,
    output_mp3
):
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

            chunk_type = chunk.get(
                "type"
            )

            if chunk_type == "audio":

                data = chunk.get(
                    "data"
                )

                if data:
                    audio_file.write(
                        data
                    )

                    audio_received = True

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
                    words.append(
                        {
                            "text": word,
                            "start": (
                                float(offset)
                                / 10_000_000
                            ),
                            "end": (
                                float(offset)
                                + float(duration)
                            ) / 10_000_000
                        }
                    )

    if not audio_received:
        raise RuntimeError(
            "Edge-TTS n'a reçu aucun flux audio."
        )

    if not words:
        raise RuntimeError(
            "Edge-TTS a généré l'audio mais aucune "
            "WordBoundary n'a été reçue."
        )

    if (
        not os.path.exists(output_mp3)
        or os.path.getsize(output_mp3) < 1000
    ):
        raise RuntimeError(
            "Le fichier audio généré est absent "
            "ou vide."
        )

    return words


def generate_audio(
    text,
    output_mp3
):
    if not text.strip():
        return (
            None,
            None,
            "Narration vide."
        )

    last_error = None

    for attempt in range(2):

        try:

            if os.path.exists(
                output_mp3
            ):
                os.remove(
                    output_mp3
                )

            words = asyncio.run(
                generate_audio_with_boundaries_async(
                    text,
                    output_mp3
                )
            )

            duration = get_audio_duration(
                output_mp3
            )

            if duration <= 0:
                raise RuntimeError(
                    "Durée audio invalide."
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
        f"Edge-TTS a échoué : {last_error}"
    )


# =========================================================
# SOUS-TITRES ASS
# =========================================================

def generate_ass_subtitles(
    word_timings,
    output_ass,
    is_short=True
):
    if is_short:

        res_x = 1080
        res_y = 1920

        font_size = 58

        margin_v = 260

        max_words = 3

    else:

        res_x = 1920
        res_y = 1080

        font_size = 44

        margin_v = 90

        max_words = 5

    header = f"""
[Script Info]
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
        or "science technology"
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
                f.write(
                    chunk
                )

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

    query = clean_visual_query(
        keyword
    )

    query_variants = [
        query,
        query.replace(
            "human",
            "person"
        ),
        query.replace(
            "scientific",
            "science"
        )
    ]

    output = os.path.join(
        temp_dir,
        f"photo_{idx:03d}.jpg"
    )

    for current_query in query_variants:

        try:

            response = requests.get(
                "https://api.pexels.com/v1/search",
                headers=pexels_headers(),
                params={
                    "query": current_query,
                    "orientation": orientation,
                    "size": "large",
                    "per_page": 15
                },
                timeout=PEXELS_TIMEOUT
            )

            if response.status_code != 200:
                continue

            photos = (
                response.json()
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
        f"Aucun visuel Pexels trouvé pour : "
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
            response.json()
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
                    os.remove(
                        output
                    )

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

    prompts = list(
        prompts
    )

    original_prompts = list(
        prompts
    )

    while len(prompts) < target_count:

        prompts.extend(
            original_prompts
        )

    prompts = prompts[
        :target_count
    ]

    jobs = [
        (idx, prompt)
        for idx, prompt
        in enumerate(prompts)
    ]

    results = [
        None
        for _ in jobs
    ]

    def worker(item):

        idx, prompt = item

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

    frame_count = max(
        1,
        int(
            duration * fps
        )
    )

    zoom_expr = (
        f"{start_zoom}"
        f"+({end_zoom}-{start_zoom})"
        f"*on/{max(1, frame_count - 1)}"
    )

    vf = (
        f"scale={width * 2}:{height * 2}:"
        "force_original_aspect_ratio=increase,"
        f"crop={width * 2}:{height * 2},"
        f"zoompan="
        f"z='{zoom_expr}':"
        f"x='{x_expr}':"
        f"y='{y_expr}':"
        f"d={frame_count}:"
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
            "FFmpeg scène image : "
            f"{stderr[-2500:]}"
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
            "FFmpeg scène vidéo : "
            f"{stderr[-2500:]}"
        )

    return output_path


# =========================================================
# CONCATÉNATION
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
                .replace("\\", "/")
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
            "FFmpeg concat : "
            f"{stderr[-3000:]}"
        )

    return output_path


# =========================================================
# DURÉES DES SCÈNES
# =========================================================

def calculate_scene_durations(
    audio_duration,
    scene_count
):
    if scene_count <= 0:
        return []

    minimum_scene_duration = 1.25

    if (
        audio_duration
        < minimum_scene_duration
        * scene_count
    ):

        scene_count = max(
            1,
            int(
                audio_duration
                / minimum_scene_duration
            )
        )

    if scene_count <= 0:
        return []

    weights = []

    for index in range(
        scene_count
    ):

        variation = (
            0.85
            + (
                (index * 17) % 35
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

    # On garantit une durée minimale.
    durations = [
        max(
            minimum_scene_duration,
            duration
        )
        for duration in durations
    ]

    total = sum(
        durations
    )

    # On réajuste pour obtenir exactement la durée audio.
    if total > 0:

        factor = (
            audio_duration
            / total
        )

        durations = [
            duration * factor
            for duration in durations
        ]

    return durations


# =========================================================
# MONTAGE COMPLET
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
            "Voix off absente. "
            "Montage annulé."
        )

    if (
        not ass_subtitles_path
        or not os.path.exists(
            ass_subtitles_path
        )
    ):

        return (
            None,
            "Sous-titres absents. "
            "Montage annulé."
        )

    try:

        audio_duration = get_audio_duration(
            audio_path
        )

        # On réduit le nombre de scènes si nécessaire.
        max_scene_count = (
            18
            if is_short
            else 45
        )

        visuals = visuals[
            :max_scene_count
        ]

        durations = calculate_scene_durations(
            audio_duration,
            len(visuals)
        )

        if not durations:
            return (
                None,
                "Impossible de calculer les durées."
            )

        scene_count = min(
            len(visuals),
            len(durations)
        )

        visuals = visuals[
            :scene_count
        ]

        temp_dir = tempfile.mkdtemp(
            prefix="studio_scenes_"
        )

        scene_files = []

        for idx, visual in enumerate(
            visuals
        ):

            duration = durations[idx]

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
            (
                f"[0:v]subtitles="
                f"'{clean_ass}'[v]"
            ),
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
            timeout=600
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
                f"Log complet : {log_path}\n\n"
                f"{stderr[-4000:]}"
            )

        final_duration = ffprobe_value(
            output_path,
            "format=duration"
        )

        if (
            final_duration is None
            or final_duration <= 0
        ):

            return (
                None,
                "Le MP4 final est illisible "
                "selon FFprobe."
            )

        # Vérification obligatoire de la piste audio.
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
                "Contrôle qualité échoué : "
                "aucune piste audio dans le MP4 final."
            )

        return (
            output_path,
            None
        )

    except Exception as exc:

        return (
            None,
            f"Erreur montage : {exc}"
        )


# =========================================================
# VALIDATION DES DURÉES
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

        # Le Short est volontairement plus court.
        if duration < 28:
            return (
                False,
                f"Le Short dure {duration:.1f}s. "
                "Il doit durer environ 30 à 45 secondes."
            )

        if duration > 45:
            return (
                False,
                f"Le Short dure {duration:.1f}s. "
                "Il doit rester sous environ 45 secondes."
            )

        return (
            True,
            None
        )

    # NOUVELLE RÈGLE :
    # plus de 2 minutes, pas 5 minutes.
    if duration <= 120:

        return (
            False,
            f"La vidéo longue dure {duration:.1f}s. "
            "Elle doit dépasser 2 minutes."
        )

    return (
        True,
        None
    )


# =========================================================
# INTERFACE STREAMLIT
# =========================================================

st.title(
    "🎬 Studio Vidéo IA"
)

st.write(
    "Création automatique d'une vidéo longue "
    "et d'un Short avec voix off, "
    "sous-titres synchronisés et montage dynamique."
)


# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------

with st.expander(
    "⚙️ État de la configuration",
    expanded=False
):

    if OPENROUTER_API_KEY:

        st.success(
            "OpenRouter : configuré"
        )

    else:

        st.error(
            "OpenRouter : clé manquante"
        )

    if PEXELS_API_KEY:

        st.success(
            "Pexels : configuré"
        )

    else:

        st.error(
            "Pexels : clé manquante"
        )

    st.write(
        f"Modèle IA : {OPENROUTER_MODEL}"
    )

    st.write(
        f"Voix : {VOICE}"
    )

    st.write(
        "Durée vidéo longue : plus de 2 minutes"
    )

    st.write(
        "Durée Short : environ 30 à 45 secondes"
    )


# ---------------------------------------------------------
# SUJET
# ---------------------------------------------------------

subject_input = st.text_input(
    "Sujet principal de la vidéo",
    placeholder=(
        "Exemple : Pourquoi le cerveau procrastine ?"
    ),
    key="subject_main"
)


if (
    not OPENROUTER_API_KEY
    or not PEXELS_API_KEY
):

    st.warning(
        "Vérifiez vos clés API dans les variables "
        "d'environnement de Render avant de lancer "
        "la génération."
    )


# =========================================================
# BOUTON DE GÉNÉRATION
# =========================================================

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
        # ÉTAPE 1
        # =================================================

        status.info(
            "1/7 Génération du script long..."
        )

        progress.progress(
            5
        )

        script_long = generate_long_script(
            subject_input.strip()
        )

        narration_long, prompts_long = (
            parse_script(
                script_long
            )
        )

        long_word_count = len(
            narration_long.split()
        )

        if long_word_count < 400:

            raise RuntimeError(
                f"Le script long contient "
                f"{long_word_count} mots. "
                "Il doit contenir au moins "
                "400 mots."
            )

        # =================================================
        # ÉTAPE 1 BIS
        # =================================================

        status.info(
            "1/7 Génération du Short..."
        )

        progress.progress(
            10
        )

        script_teaser = generate_short_script(
            subject_input.strip()
        )

        narration_teaser, prompts_teaser = (
            parse_script(
                script_teaser
            )
        )

        teaser_word_count = len(
            narration_teaser.split()
        )

        if not (
            70
            <= teaser_word_count
            <= 130
        ):

            raise RuntimeError(
                f"Le Short contient "
                f"{teaser_word_count} mots. "
                "La cible est d'environ "
                "85 à 110 mots."
            )

        # =================================================
        # AFFICHAGE DES SCRIPTS
        # =================================================

        with st.expander(
            "📜 Voir les scripts",
            expanded=False
        ):

            st.write(
                f"Script long : "
                f"{long_word_count} mots"
            )

            st.text_area(
                "Script long",
                script_long,
                height=350
            )

            st.write(
                f"Script Short : "
                f"{teaser_word_count} mots"
            )

            st.text_area(
                "Script Short",
                script_teaser,
                height=250
            )

        # =================================================
        # ÉTAPE 2
        # =================================================

        status.info(
            "2/7 Génération de la voix off longue..."
        )

        progress.progress(
            18
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
                err
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
            f"Voix off longue générée : "
            f"{duration_long:.1f} secondes"
        )

        # =================================================
        # ÉTAPE 3
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
                err
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
            f"Short audio : "
            f"{duration_teaser:.1f} secondes"
        )

        # =================================================
        # CALCUL DES VISUELS
        # =================================================

        count_long = max(
            18,
            min(
                40,
                int(
                    duration_long
                    / 5.0
                )
            )
        )

        count_teaser = max(
            8,
            min(
                14,
                int(
                    duration_teaser
                    / 3.0
                )
            )
        )

        # =================================================
        # ÉTAPE 4
        # =================================================

        status.info(
            f"4/7 Téléchargement des visuels "
            f"de la vidéo longue "
            f"({count_long})..."
        )

        progress.progress(
            42
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
        # ÉTAPE 5
        # =================================================

        status.info(
            f"5/7 Téléchargement des visuels "
            f"du Short ({count_teaser})..."
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
        # ÉTAPE 6
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
        # SHORT
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
        # ÉTAPE 7
        # =================================================

        status.info(
            "7/7 Contrôle qualité final..."
        )

        progress.progress(
            94
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
                f"Contrôle vidéo longue : "
                f"{err_long}"
            )

        if not valid_teaser:

            raise RuntimeError(
                f"Contrôle Short : "
                f"{err_teaser}"
            )

        # =================================================
        # TERMINÉ
        # =================================================

        progress.progress(
            100
        )

        status.success(
            "Génération terminée. "
            "Les deux vidéos ont passé "
            "les contrôles de base."
        )

        st.success(
            "🎉 Pack Duo prêt !"
        )

        # =================================================
        # VIDÉO LONGUE
        # =================================================

        st.subheader(
            "🎥 Vidéo longue"
        )

        st.caption(
            f"Durée : "
            f"{final_long_duration:.1f}s "
            f"({final_long_duration / 60:.1f} min) "
            f"| {len(visuals_long)} visuels"
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
                file_name="video_longue.mp4",
                mime="video/mp4",
                key="download_long"
            )

        # =================================================
        # SHORT
        # =================================================

        st.subheader(
            "📱 Short teaser"
        )

        st.caption(
            f"Durée : "
            f"{final_teaser_duration:.1f}s "
            f"| {len(visuals_teaser)} visuels"
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
                file_name="short_teaser.mp4",
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
            f"Dossier de travail : "
            f"{work_dir}"
        )
