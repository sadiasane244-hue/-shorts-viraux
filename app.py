import os
import random
import re
import subprocess
import tempfile
import asyncio
import concurrent.futures
import time
import traceback

import streamlit as st


# =========================================================
# CONFIGURATION STREAMLIT
# =========================================================

st.set_page_config(
    page_title="Studio Vidéo IA",
    page_icon="🎬",
    layout="centered",
    initial_sidebar_state="collapsed"
)


# =========================================================
# IMPORTS SÉCURISÉS
# =========================================================

try:
    import requests
except Exception as exc:
    st.error("❌ Impossible de charger le module requests.")
    st.code(str(exc))
    st.stop()

try:
    from PIL import Image, UnidentifiedImageError
except Exception as exc:
    st.error("❌ Impossible de charger Pillow.")
    st.code(str(exc))
    st.stop()


# =========================================================
# VARIABLES D'ENVIRONNEMENT
# =========================================================

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "").strip()

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "meta-llama/llama-3.3-70b-instruct"

VOICE = "fr-FR-RemyNeural"

REQUEST_TIMEOUT = 90
PEXELS_TIMEOUT = 20
MAX_PEXELS_WORKERS = 5


# =========================================================
# STYLE INTERFACE
# =========================================================

st.markdown(
    """
    <style>

    .main-title {
        font-size: 42px;
        font-weight: 800;
        margin-bottom: 8px;
    }

    .subtitle {
        font-size: 18px;
        opacity: 0.85;
        margin-bottom: 28px;
    }

    .status-box {
        padding: 14px 18px;
        border-radius: 12px;
        margin: 12px 0;
    }

    </style>
    """,
    unsafe_allow_html=True
)


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
            f"Timeout après {timeout}s : {exc}"
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

    code, stdout, _ = run_command(cmd, timeout=30)

    if code != 0:
        return None

    try:
        return float(stdout.strip())
    except Exception:
        return None


def get_audio_duration(audio_path):
    if not audio_path or not os.path.exists(audio_path):
        raise RuntimeError(
            "Le fichier audio n'existe pas."
        )

    duration = ffprobe_value(
        audio_path,
        "format=duration"
    )

    if duration is None or duration <= 0:
        raise RuntimeError(
            "FFprobe n'a pas réussi à lire la durée de la voix off."
        )

    return duration


def clean_filename(text):
    text = re.sub(
        r"[^a-zA-Z0-9_-]+",
        "_",
        text
    )

    text = text.strip("_")

    return text[:80] or "video"


def retry_sleep(attempt):
    time.sleep(
        min(2 ** attempt, 8)
    )


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

    except (OSError, UnidentifiedImageError):
        return False


# =========================================================
# OPENROUTER
# =========================================================

def call_openrouter(messages, max_tokens, temperature):

    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY est absente des variables Render."
        )

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://shorts-viraux-1.onrender.com",
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

                last_error = "Réponse OpenRouter vide."

            else:

                try:
                    detail = response.json()
                except Exception:
                    detail = response.text

                last_error = (
                    f"HTTP {response.status_code}: {detail}"
                )

        except requests.RequestException as exc:

            last_error = str(exc)

        if attempt < 2:
            retry_sleep(attempt)

    raise RuntimeError(
        f"OpenRouter a échoué après 3 tentatives : {last_error}"
    )


# =========================================================
# GÉNÉRATION DES SCRIPTS
# =========================================================

def generate_pack_scripts(subject):

    long_prompt = f"""
Vous êtes un excellent scénariste documentaire YouTube francophone.

SUJET :
{subject}

OBJECTIF :

Créer une vidéo documentaire captivante et factuelle.

La vidéo longue doit avoir suffisamment de narration pour produire
une vidéo de PLUS DE 2 MINUTES avec une voix naturelle.

Cible :
850 à 1100 mots.

IMPORTANT :

- Ne jamais inventer de faits.
- Ne jamais inventer de statistiques.
- Ne jamais inventer d'études.
- Ne jamais inventer de citations.
- Ne jamais inventer d'événements.
- Si une information est incertaine, le dire clairement.
- Le texte doit être naturel à l'oral.
- L'introduction doit avoir un hook très fort.
- La progression doit maintenir la curiosité.
- La conclusion doit apporter une vraie réponse.

FORMAT :

TITRE: titre de la vidéo

HOOK: narration [IMAGE: english visual keywords]

INTRO: narration [IMAGE: english visual keywords]

PARTIE 1: narration [IMAGE: english visual keywords]

PARTIE 2: narration [IMAGE: english visual keywords]

PARTIE 3: narration [IMAGE: english visual keywords]

PARTIE 4: narration [IMAGE: english visual keywords]

CONCLUSION: narration [IMAGE: english visual keywords]

CTA: Abonne-toi pour en savoir plus sur le monde.
[IMAGE: youtube subscribe]

RÈGLE VISUELLE :

Utiliser environ une balise IMAGE toutes les 1 à 2 phrases.

Produire environ 20 à 30 balises visuelles.

Les mots-clés visuels doivent être simples et en anglais.
"""


    short_prompt = f"""
Vous êtes un créateur professionnel de Shorts YouTube.

SUJET :
{subject}

Créer un teaser très captivant de 30 à 40 secondes.

Cible :
80 à 105 mots.

Le teaser doit :

- commencer par un hook très fort
- présenter une information surprenante
- créer une curiosité
- donner envie de regarder la vidéo longue
- rester totalement factuel
- ne rien inventer

FORMAT :

TITRE: titre du Short

HOOK: narration [IMAGE: english visual keywords]

TEASER: narration [IMAGE: english visual keywords]

REVELATION: narration [IMAGE: english visual keywords]

CTA: Retrouve la vidéo complète sur la chaîne.
[IMAGE: youtube subscribe]

Produire environ 8 à 12 balises visuelles.
"""


    long_script = call_openrouter(
        [
            {
                "role": "system",
                "content": long_prompt
            },
            {
                "role": "user",
                "content": (
                    f"Rédige maintenant le script long "
                    f"sur le sujet : {subject}"
                )
            }
        ],
        max_tokens=4000,
        temperature=0.6
    )


    short_script = call_openrouter(
        [
            {
                "role": "system",
                "content": short_prompt
            },
            {
                "role": "user",
                "content": (
                    f"Rédige maintenant le teaser "
                    f"sur le sujet : {subject}"
                )
            }
        ],
        max_tokens=1000,
        temperature=0.7
    )


    return long_script, short_script


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


    narration = " ".join(narration_parts)

    narration = re.sub(
        r"\s+",
        " ",
        narration
    ).strip()

    return narration, visual_prompts


# =========================================================
# EDGE TTS
# =========================================================

async def generate_audio_async(text, output_mp3):

    try:
        import edge_tts
    except Exception as exc:
        raise RuntimeError(
            "Le module edge-tts n'est pas installé. "
            "Ajoutez edge-tts dans requirements.txt."
        ) from exc


    communicate = edge_tts.Communicate(
        text,
        VOICE,
        rate="+5%"
    )


    words = []
    audio_received = False


    with open(
        output_mp3,
        "wb"
    ) as audio_file:

        async for chunk in communicate.stream():

            chunk_type = chunk.get("type")

            if chunk_type == "audio":

                data = chunk.get("data")

                if data:

                    audio_file.write(data)

                    audio_received = True


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
            "Edge-TTS n'a fourni aucune WordBoundary."
        )


    if (
        not os.path.exists(output_mp3)
        or os.path.getsize(output_mp3) < 1000
    ):
        raise RuntimeError(
            "Le fichier audio est absent ou vide."
        )


    return words


def generate_audio(text, output_mp3):

    if not text.strip():

        return (
            None,
            None,
            "Narration vide."
        )


    last_error = None


    for attempt in range(2):

        try:

            if os.path.exists(output_mp3):
                os.remove(output_mp3)


            words = asyncio.run(
                generate_audio_async(
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
        f"Edge-TTS a échoué : {last_error}"
    )


# =========================================================
# SOUS-TITRES ASS
# =========================================================

def format_time_ass(seconds):

    seconds = max(
        0.0,
        float(seconds)
    )

    hours = int(
        seconds // 3600
    )

    minutes = int(
        (seconds % 3600) // 60
    )

    secs = int(
        seconds % 60
    )

    centis = int(
        (seconds - int(seconds))
        * 100
    )

    return (
        f"{hours}:"
        f"{minutes:02d}:"
        f"{secs:02d}."
        f"{centis:02d}"
    )


def generate_ass_subtitles(
    word_timings,
    output_ass,
    is_short
):

    width = 1080 if is_short else 1920
    height = 1920 if is_short else 1080

    font_size = 58 if is_short else 46

    margin_v = 250 if is_short else 80

    words_per_line = 3 if is_short else 5


    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{font_size},&H00FFFFFF,&H00FFFFFF,&H00101010,&H90000000,-1,0,0,0,100,100,0,0,1,4,1,2,50,50,{margin_v},1

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
            words_per_line
        ):

            group = word_timings[
                i:i + words_per_line
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
            "PEXELS_API_KEY absente."
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
        f"photo_{idx:03d}.jpg"
    )


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
            return None


        photos = (
            response
            .json()
            .get("photos", [])
        )


        if not photos:
            return None


        random.shuffle(photos)


        for photo in photos[:10]:

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

                if os.path.exists(output):
                    os.remove(output)


    except Exception:
        return None


    return None


def fetch_pexels_video(
    keyword,
    idx,
    temp_dir,
    is_short
):

    if not PEXELS_API_KEY:
        return None


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


        random.shuffle(videos)


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
                key=lambda item:
                abs(
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


                if duration and duration >= 1:

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

    width, height = (
        (1080, 1920)
        if is_short
        else
        (1920, 1080)
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
        quality=90
    )


    return {
        "type": "image",
        "path": path,
        "source_id": f"placeholder-{idx}"
    }


# =========================================================
# TÉLÉCHARGEMENT DES VISUELS
# =========================================================

def fetch_visuals(
    prompts,
    temp_dir,
    is_short,
    target_count
):

    if not prompts:

        prompts = [
            "human thinking",
            "brain science",
            "person working",
            "technology",
            "science laboratory"
        ]


    # Évite de répéter immédiatement le même visuel.
    prompts = list(dict.fromkeys(prompts))


    original_prompts = list(prompts)


    while len(prompts) < target_count:

        prompts.extend(
            original_prompts
        )


    prompts = prompts[
        :target_count
    ]


    results = [None] * len(prompts)


    def worker(item):

        idx, prompt = item


        # Short :
        # beaucoup plus de vidéos.
        if is_short or idx % 3 == 1:

            video = fetch_pexels_video(
                prompt,
                idx,
                temp_dir,
                is_short
            )

            if video:
                return idx, video


        photo = fetch_pexels_photo(
            prompt,
            idx,
            temp_dir,
            is_short
        )


        if photo:
            return idx, photo


        video = fetch_pexels_video(
            prompt,
            idx,
            temp_dir,
            is_short
        )


        if video:
            return idx, video


        # Dernier recours uniquement.
        return idx, make_placeholder(
            prompt,
            idx,
            temp_dir,
            is_short
        )


    jobs = list(
        enumerate(prompts)
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
        if item
        and os.path.exists(
            item["path"]
        )
    ]


# =========================================================
# FFMPEG : SCÈNE IMAGE
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
        else
        (1920, 1080)
    )


    duration = max(
        0.8,
        float(duration)
    )


    fps = 25


    effects = [
        (1.00, 1.07),
        (1.07, 1.00),
        (1.00, 1.05),
        (1.05, 1.00)
    ]


    start_zoom, end_zoom = effects[
        effect_index % len(effects)
    ]


    frames = max(
        1,
        int(duration * fps)
    )


    zoom_expr = (
        f"{start_zoom}+"
        f"({end_zoom}-{start_zoom})"
        f"*on/{max(1, frames - 1)}"
    )


    vf = (
        f"scale={width * 2}:{height * 2}:"
        "force_original_aspect_ratio=increase,"
        f"crop={width * 2}:{height * 2},"
        f"zoompan=z='{zoom_expr}':"
        f"x='iw/2-(iw/zoom/2)':"
        f"y='ih/2-(ih/zoom/2)':"
        f"d={frames}:"
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
        "22",
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
        or not os.path.exists(output_path)
        or os.path.getsize(output_path) < 5000
    ):

        raise RuntimeError(
            "FFmpeg scène image :\n"
            + stderr[-3000:]
        )


    return output_path


# =========================================================
# FFMPEG : SCÈNE VIDÉO
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
        else
        (1920, 1080)
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
        "22",
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
        or not os.path.exists(output_path)
        or os.path.getsize(output_path) < 5000
    ):

        raise RuntimeError(
            "FFmpeg scène vidéo :\n"
            + stderr[-3000:]
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
        os.path.dirname(output_path),
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
                .replace("'", "'\\''")
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
        or not os.path.exists(output_path)
    ):

        raise RuntimeError(
            "FFmpeg concat :\n"
            + stderr[-3000:]
        )


    return output_path


# =========================================================
# MONTAGE COMPLET
# =========================================================

def create_video(
    visuals,
    audio_path,
    ass_path,
    output_path,
    is_short
):

    if not visuals:
        return None, "Aucun visuel disponible."


    if (
        not audio_path
        or not os.path.exists(audio_path)
    ):

        return (
            None,
            "Voix off absente."
        )


    if (
        not ass_path
        or not os.path.exists(ass_path)
    ):

        return (
            None,
            "Sous-titres absents."
        )


    try:

        audio_duration = get_audio_duration(
            audio_path
        )


        scene_count = len(visuals)


        if scene_count < 1:
            return None, "Aucune scène."


        # Durée moyenne par scène.
        base_duration = (
            audio_duration
            / scene_count
        )


        # Pour éviter les scènes trop courtes.
        min_scene_duration = 1.2


        # Si trop de visuels par rapport
        # à la durée audio, on en garde moins.
        max_possible_scenes = max(
            1,
            int(
                audio_duration
                / min_scene_duration
            )
        )


        if scene_count > max_possible_scenes:

            visuals = visuals[
                :max_possible_scenes
            ]

            scene_count = len(
                visuals
            )


            base_duration = (
                audio_duration
                / scene_count
            )


        temp_dir = tempfile.mkdtemp(
            prefix="studio_scenes_"
        )


        scene_files = []


        # -------------------------------------------------
        # CALCUL DES DURÉES
        # -------------------------------------------------

        weights = []


        for idx in range(scene_count):

            variation = (
                0.85
                + ((idx * 17) % 30) / 100
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


        # -------------------------------------------------
        # CRÉATION DES SCÈNES
        # -------------------------------------------------

        for idx, visual in enumerate(
            visuals
        ):

            duration = max(
                min_scene_duration,
                durations[idx]
            )


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


        # -------------------------------------------------
        # CONCATÉNATION
        # -------------------------------------------------

        silent_video = os.path.join(
            temp_dir,
            "silent.mp4"
        )


        concat_scene_files(
            scene_files,
            silent_video
        )


        # -------------------------------------------------
        # AUDIO + SOUS-TITRES
        # -------------------------------------------------

        clean_ass = os.path.abspath(
            ass_path
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
            "22",
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
            or not os.path.exists(output_path)
            or os.path.getsize(output_path) < 10000
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
                + stderr[-4000:]
            )


        # -------------------------------------------------
        # CONTRÔLE AUDIO
        # -------------------------------------------------

        final_duration = ffprobe_value(
            output_path,
            "format=duration"
        )


        audio_probe_cmd = [
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
            audio_probe_cmd,
            timeout=30
        )


        if (
            code != 0
            or not stdout.strip()
        ):

            return (
                None,
                "Le MP4 final ne contient aucune piste audio."
            )


        if not final_duration:
            return (
                None,
                "Durée finale impossible à lire."
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
# VALIDATION DURÉE
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

        if duration < 30:

            return (
                False,
                f"Le Short dure {duration:.1f}s. "
                "Il doit durer au moins 30 secondes."
            )


        if duration > 45:

            return (
                False,
                f"Le Short dure {duration:.1f}s. "
                "Il doit rester sous 45 secondes."
            )


        return True, None


    # -----------------------------------------------------
    # VIDÉO LONGUE
    # -----------------------------------------------------

    if duration <= 120:

        return (
            False,
            f"La vidéo longue dure {duration:.1f}s. "
            "Elle doit dépasser 2 minutes."
        )


    return True, None


# =========================================================
# INTERFACE
# =========================================================

st.markdown(
    '<div class="main-title">🎬 Studio Vidéo IA</div>',
    unsafe_allow_html=True
)

st.markdown(
    '<div class="subtitle">'
    "Création automatique d'une vidéo longue et d'un Short "
    "avec voix off, sous-titres synchronisés et montage dynamique."
    "</div>",
    unsafe_allow_html=True
)


# =========================================================
# ÉTAT DES CLÉS
# =========================================================

with st.expander(
    "⚙️ État de la configuration",
    expanded=False
):

    if OPENROUTER_API_KEY:
        st.success(
            "✅ OPENROUTER_API_KEY détectée"
        )
    else:
        st.error(
            "❌ OPENROUTER_API_KEY absente"
        )


    if PEXELS_API_KEY:
        st.success(
            "✅ PEXELS_API_KEY détectée"
        )
    else:
        st.error(
            "❌ PEXELS_API_KEY absente"
        )


# =========================================================
# CHAMP SUJET
# =========================================================

subject_input = st.text_input(
    "Sujet principal de la vidéo",
    placeholder=(
        "Exemple : "
        "Pourquoi le cerveau procrastine ?"
    ),
    key="subject_main"
)


# =========================================================
# BOUTON
# =========================================================

generate_button = st.button(
    "🚀 Générer le Pack Duo",
    key="btn_pack",
    type="primary",
    use_container_width=True
)


# =========================================================
# GÉNÉRATION
# =========================================================

if generate_button:

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
            "1/7 Génération des scripts..."
        )

        progress.progress(5)


        script_long, script_short = (
            generate_pack_scripts(
                subject_input.strip()
            )
        )


        narration_long, prompts_long = (
            parse_script(
                script_long
            )
        )


        narration_short, prompts_short = (
            parse_script(
                script_short
            )
        )


        long_words = len(
            narration_long.split()
        )


        short_words = len(
            narration_short.split()
        )


        # Nouvelle règle :
        # environ 850-1100 mots pour dépasser 2 min.
        if long_words < 750:

            raise RuntimeError(
                f"Le script long est trop court "
                f"({long_words} mots). "
                "La génération est arrêtée. "
                "Il faut au moins environ 750 mots "
                "pour produire une vidéo de plus de 2 minutes."
            )


        if not (
            70
            <= short_words
            <= 120
        ):

            raise RuntimeError(
                f"Le Short contient "
                f"{short_words} mots. "
                "Il faut environ 70 à 120 mots "
                "pour viser 30 à 45 secondes."
            )


        with st.expander(
            "📜 Voir les scripts",
            expanded=False
        ):

            st.text_area(
                "Script vidéo longue",
                script_long,
                height=350
            )


            st.text_area(
                "Script Short",
                script_short,
                height=250
            )


        # =================================================
        # 2. AUDIO LONG
        # =================================================

        status.info(
            "2/7 Génération de la voix off longue..."
        )

        progress.progress(15)


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
            raise RuntimeError(err)


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


        # =================================================
        # 3. AUDIO SHORT
        # =================================================

        status.info(
            "3/7 Génération de la voix off du Short..."
        )

        progress.progress(27)


        short_audio = os.path.join(
            work_dir,
            "short_voice.mp3"
        )


        short_ass = os.path.join(
            work_dir,
            "short_subs.ass"
        )


        audio_short, words_short, err = (
            generate_audio(
                narration_short,
                short_audio
            )
        )


        if err:
            raise RuntimeError(err)


        duration_short = get_audio_duration(
            audio_short
        )


        valid, duration_error = (
            validate_duration(
                duration_short,
                True
            )
        )


        if not valid:
            raise RuntimeError(
                duration_error
            )


        generate_ass_subtitles(
            words_short,
            short_ass,
            is_short=True
        )


        # =================================================
        # 4. VISUELS LONG
        # =================================================

        count_long = max(
            18,
            min(
                30,
                int(
                    duration_long
                    / 5
                )
            )
        )


        status.info(
            f"4/7 Téléchargement des visuels "
            f"de la vidéo longue ({count_long})..."
        )

        progress.progress(40)


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
            False,
            count_long
        )


        if len(visuals_long) < 8:

            raise RuntimeError(
                "Pas assez de visuels valides "
                "pour la vidéo longue."
            )


        # =================================================
        # 5. VISUELS SHORT
        # =================================================

        count_short = max(
            8,
            min(
                14,
                int(
                    duration_short
                    / 3
                )
            )
        )


        status.info(
            f"5/7 Téléchargement des visuels "
            f"du Short ({count_short})..."
        )

        progress.progress(55)


        short_visual_dir = os.path.join(
            work_dir,
            "visuals_short"
        )


        os.makedirs(
            short_visual_dir,
            exist_ok=True
        )


        visuals_short = fetch_visuals(
            prompts_short,
            short_visual_dir,
            True,
            count_short
        )


        if len(visuals_short) < 5:

            raise RuntimeError(
                "Pas assez de visuels valides "
                "pour le Short."
            )


        # =================================================
        # 6. MONTAGE LONG
        # =================================================

        status.info(
            "6/7 Montage dynamique de la vidéo longue..."
        )

        progress.progress(68)


        long_output = os.path.join(
            work_dir,
            "video_longue.mp4"
        )


        video_long, err = create_video(
            visuals_long,
            audio_long,
            long_ass,
            long_output,
            False
        )


        if not video_long:
            raise RuntimeError(err)


        # =================================================
        # MONTAGE SHORT
        # =================================================

        status.info(
            "6/7 Montage dynamique du Short..."
        )

        progress.progress(82)


        short_output = os.path.join(
            work_dir,
            "short_teaser.mp4"
        )


        video_short, err = create_video(
            visuals_short,
            audio_short,
            short_ass,
            short_output,
            True
        )


        if not video_short:
            raise RuntimeError(err)


        # =================================================
        # 7. CONTRÔLE FINAL
        # =================================================

        status.info(
            "7/7 Contrôle qualité final..."
        )

        progress.progress(94)


        final_long_duration = (
            ffprobe_value(
                long_output,
                "format=duration"
            )
        )


        final_short_duration = (
            ffprobe_value(
                short_output,
                "format=duration"
            )
        )


        valid_long, err_long = (
            validate_duration(
                final_long_duration,
                False
            )
        )


        valid_short, err_short = (
            validate_duration(
                final_short_duration,
                True
            )
        )


        if not valid_long:

            raise RuntimeError(
                "Contrôle vidéo longue : "
                + err_long
            )


        if not valid_short:

            raise RuntimeError(
                "Contrôle Short : "
                + err_short
            )


        progress.progress(100)


        status.success(
            "✅ Génération terminée avec succès."
        )


        # =================================================
        # RÉSULTATS
        # =================================================

        st.success(
            f"Pack Duo terminé : "
            f"{final_long_duration:.1f}s pour la vidéo longue "
            f"et {final_short_duration:.1f}s pour le Short."
        )


        col1, col2 = st.columns(2)


        with col1:

            st.subheader(
                "🎥 Vidéo longue"
            )


            st.caption(
                f"Durée : "
                f"{final_long_duration:.1f}s"
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


        with col2:

            st.subheader(
                "📱 Short teaser"
            )


            st.caption(
                f"Durée : "
                f"{final_short_duration:.1f}s"
            )


            st.video(
                short_output
            )


            with open(
                short_output,
                "rb"
            ) as f:

                st.download_button(
                    "📥 Télécharger le Short",
                    data=f.read(),
                    file_name="short_teaser.mp4",
                    mime="video/mp4",
                    key="download_short"
                )


        # =================================================
        # INFORMATIONS
        # =================================================

        with st.expander(
            "🔧 Informations techniques"
        ):

            st.write(
                f"**Dossier de travail :** `{work_dir}`"
            )

            st.write(
                f"**Voix longue :** {duration_long:.1f}s"
            )

            st.write(
                f"**Voix Short :** {duration_short:.1f}s"
            )

            st.write(
                f"**Visuels longs :** {len(visuals_long)}"
            )

            st.write(
                f"**Visuels Short :** {len(visuals_short)}"
            )


    except Exception as exc:

        progress.empty()


        status.error(
            "❌ La génération a été arrêtée."
        )


        st.error(
            str(exc)
        )


        with st.expander(
            "🔍 Détails techniques de l'erreur"
        ):

            st.code(
                traceback.format_exc()
            )


        st.caption(
            f"Dossier de travail : {work_dir}"
    )
