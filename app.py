import os
import sys
import json
import random
import re
import subprocess
import tempfile
import asyncio
import urllib.parse
import concurrent.futures
import time
from pathlib import Path

import requests
from PIL import Image, UnidentifiedImageError
import streamlit as st

# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------
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
# OUTILS GENERAUX
# ---------------------------------------------------------
def run_command(cmd, timeout=None):
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired as exc:
        return -1, exc.stdout or "", f"Timeout après {timeout}s: {exc}"
    except Exception as exc:
        return -1, "", str(exc)


def ffprobe_value(path, selector):
    if not path or not os.path.exists(path):
        return None
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", selector,
        "-of", "default=noprint_wrappers=1:nokey=1",
        path
    ]
    code, stdout, _ = run_command(cmd, timeout=30)
    if code != 0:
        return None
    try:
        return float(stdout.strip())
    except (TypeError, ValueError):
        return None


def get_audio_duration(audio_path):
    duration = ffprobe_value(audio_path, "format=duration")
    if duration is None or duration <= 0:
        raise RuntimeError(
            "FFprobe n'a pas pu lire la durée réelle de la voix off. "
            "Le fichier audio est absent, vide ou illisible."
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
    except (OSError, UnidentifiedImageError):
        return False


def clean_filename(text):
    text = re.sub(r"[^a-zA-Z0-9_-]+", "_", text)
    return text.strip("_")[:80] or "video"


def format_time_ass(seconds):
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centis = int((seconds - int(seconds)) * 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def format_time_srt(seconds):
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis >= 1000:
        secs += 1
        millis -= 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def retry_sleep(attempt):
    time.sleep(min(2 ** attempt, 8))

# ---------------------------------------------------------
# GENERATION DES SCRIPTS
# ---------------------------------------------------------
def call_openrouter(messages, max_tokens, temperature):
    if not OPENROUTER_API_KEY:
        raise RuntimeError("Clé OPENROUTER_API_KEY manquante.")

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
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                if content.strip():
                    return content.strip()
                last_error = "Réponse OpenRouter vide."
            else:
                try:
                    detail = response.json()
                except Exception:
                    detail = response.text
                last_error = f"HTTP {response.status_code}: {detail}"
        except requests.RequestException as exc:
            last_error = str(exc)
        if attempt < 2:
            retry_sleep(attempt)
    raise RuntimeError(f"OpenRouter a échoué après 3 tentatives: {last_error}")


def generate_pack_scripts(subject):
    long_system_prompt = f"""
Vous êtes scénariste scientifique pour une vidéo YouTube longue en français.
Sujet: {subject}

OBJECTIF:
Produire un script documentaire captivant et factuel de 1250 à 1550 mots.
La narration doit naturellement dépasser 5 minutes.
N'inventez aucune étude, aucun chiffre, aucune citation et aucun événement.
Si un point est incertain, présentez-le comme incertain au lieu de l'affirmer.

IMPORTANT:
Chaque bloc visuel doit correspondre à ce qui est réellement raconté.
Utilisez des mots-clés visuels simples en anglais pour Pexels.
Évitez les logos, marques et personnages protégés.

FORMAT:
TITRE: titre YouTube
HOOK: texte narré [IMAGE: english visual keywords]
INTRO: texte narré [IMAGE: english visual keywords]
PARTIE 1: texte narré [IMAGE: english visual keywords]
PARTIE 2: texte narré [IMAGE: english visual keywords]
PARTIE 3: texte narré [IMAGE: english visual keywords]
PARTIE 4: texte narré [IMAGE: english visual keywords]
PARTIE 5: texte narré [IMAGE: english visual keywords]
CONCLUSION: texte narré [IMAGE: english visual keywords]
CTA: "Abonne-toi pour en savoir plus sur le monde." [IMAGE: youtube subscribe]

Règle visuelle:
Insérez une balise [IMAGE: ...] environ toutes les 1 à 2 phrases.
Produisez environ 35 à 55 balises visuelles, pas 100.
Le texte de narration doit rester naturel lorsqu'on retire toutes les balises.
"""

    short_system_prompt = f"""
Vous êtes créateur de Shorts YouTube en français.
Sujet: {subject}

Produisez un teaser de 135 à 155 mots.
La durée visée est de 48 à 56 secondes avec une voix naturelle.
Le teaser doit être captivant mais factuel et ne doit pas inventer de faits.
Il doit donner envie de regarder la vidéo longue.

FORMAT:
TITRE: titre court
HOOK: texte [IMAGE: english visual keywords]
TEASER: texte [IMAGE: english visual keywords]
REVELATION: texte [IMAGE: english visual keywords]
CTA: "Retrouve la vidéo complète sur la chaîne." [IMAGE: youtube subscribe]

Insérez une balise [IMAGE: ...] environ toutes les 1 à 2 phrases.
Produisez 12 à 18 balises visuelles.
"""

    long_script = call_openrouter(
        [
            {"role": "system", "content": long_system_prompt},
            {"role": "user", "content": f"Rédige maintenant le script long sur: {subject}"}
        ],
        max_tokens=5000,
        temperature=0.65
    )

    teaser_script = call_openrouter(
        [
            {"role": "system", "content": short_system_prompt},
            {"role": "user", "content": f"Rédige maintenant le teaser sur: {subject}"}
        ],
        max_tokens=1200,
        temperature=0.7
    )

    return long_script, teaser_script

# ---------------------------------------------------------
# PARSING DES SCRIPTS
# ---------------------------------------------------------
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

        if re.match(r"^(TITRE|HASHTAGS?|SOURCES?)\s*:", line, re.IGNORECASE):
            continue

        cleaned = re.sub(r"\[(?:IMAGE|MEME|VISUEL)\s*:[^\]]+\]", "", line, flags=re.IGNORECASE)
        cleaned = re.sub(
            r"^(HOOK|INTRO|PARTIE\s*\d+|TEASER|REVELATION|CONCLUSION|CTA)\s*:\s*",
            "",
            cleaned,
            flags=re.IGNORECASE
        )
        cleaned = re.sub(r"[*_`]+", "", cleaned).strip()
        if cleaned:
            narration_parts.append(cleaned)

    narration = " ".join(narration_parts)
    narration = re.sub(r"\s+", " ", narration).strip()
    return narration, visual_prompts

# ---------------------------------------------------------
# EDGE-TTS + VRAIES WORD BOUNDARIES
# ---------------------------------------------------------
async def generate_audio_with_boundaries_async(text, output_mp3):
    import edge_tts

    communicate = edge_tts.Communicate(
        text,
        VOICE,
        rate="+8%"
    )

    words = []
    audio_received = False

    with open(output_mp3, "wb") as audio_file:
        async for chunk in communicate.stream():
            chunk_type = chunk.get("type")
            if chunk_type == "audio":
                data = chunk.get("data")
                if data:
                    audio_file.write(data)
                    audio_received = True
            elif chunk_type == "WordBoundary":
                word = str(chunk.get("text", "")).strip()
                offset = chunk.get("offset")
                duration = chunk.get("duration")
                if word and offset is not None and duration is not None:
                    words.append({
                        "text": word,
                        "start": float(offset) / 10_000_000,
                        "end": (float(offset) + float(duration)) / 10_000_000
                    })

    if not audio_received:
        raise RuntimeError("Edge-TTS n'a reçu aucun flux audio.")
    if not words:
        raise RuntimeError("Edge-TTS a généré l'audio mais aucune WordBoundary. Sous-titres impossibles à synchroniser.")
    if not os.path.exists(output_mp3) or os.path.getsize(output_mp3) < 1000:
        raise RuntimeError("Le fichier audio généré est absent ou vide.")

    return words


def generate_audio(text, output_mp3):
    if not text.strip():
        return None, None, "Narration vide, impossible de générer la voix."

    last_error = None
    for attempt in range(2):
        try:
            if os.path.exists(output_mp3):
                os.remove(output_mp3)
            words = asyncio.run(generate_audio_with_boundaries_async(text, output_mp3))
            duration = get_audio_duration(output_mp3)
            return output_mp3, words, None
        except Exception as exc:
            last_error = str(exc)
            if attempt == 0:
                retry_sleep(attempt)

    return None, None, f"Edge-TTS a échoué: {last_error}"

# ---------------------------------------------------------
# SOUS-TITRES MOT PAR MOT / GROUPES SYNCHRONISES
# ---------------------------------------------------------
def generate_ass_subtitles(word_timings, output_ass, is_short=True):
    res_x = 1080 if is_short else 1920
    res_y = 1920 if is_short else 1080
    font_size = 58 if is_short else 44
    margin_v = 260 if is_short else 90
    max_words = 3 if is_short else 5

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

    with open(output_ass, "w", encoding="utf-8") as f:
        f.write(header)

        for i in range(0, len(word_timings), max_words):
            group = word_timings[i:i + max_words]
            if not group:
                continue
            start = group[0]["start"]
            end = group[-1]["end"] + 0.05
            text = " ".join(item["text"] for item in group)
            text = text.replace("{", "(").replace("}", ")")
            f.write(
                f"Dialogue: 0,{format_time_ass(start)},{format_time_ass(end)},Default,,0,0,0,,{text}\n"
            )

    return output_ass

# ---------------------------------------------------------
# PEXELS IMAGES ET VIDEOS
# ---------------------------------------------------------
def pexels_headers():
    if not PEXELS_API_KEY:
        return {}
    return {"Authorization": PEXELS_API_KEY}


def clean_visual_query(keyword):
    keyword = re.sub(r"[^a-zA-Z0-9\s-]", " ", keyword)
    keyword = re.sub(r"\s+", " ", keyword).strip()
    return keyword[:100] or "abstract technology"


def download_binary(url, output_path):
    response = requests.get(url, timeout=PEXELS_TIMEOUT, stream=True)
    response.raise_for_status()
    with open(output_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=1024 * 128):
            if chunk:
                f.write(chunk)
    return output_path


def fetch_pexels_photo(keyword, idx, temp_dir, is_short):
    if not PEXELS_API_KEY:
        raise RuntimeError("PEXELS_API_KEY manquante.")

    orientation = "portrait" if is_short else "landscape"
    query_variants = [
        clean_visual_query(keyword),
        clean_visual_query(keyword).replace("human", "person"),
        clean_visual_query(keyword).replace("scientific", "science")
    ]

    output = os.path.join(temp_dir, f"photo_{idx:03d}.jpg")

    for query in query_variants:
        try:
            url = "https://api.pexels.com/v1/search"
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
            photos = response.json().get("photos", [])
            if not photos:
                continue

            candidates = photos[:10]
            random.shuffle(candidates)
            for photo in candidates:
                src = photo.get("src", {})
                image_url = src.get("large2x") or src.get("large") or src.get("original")
                if not image_url:
                    continue
                try:
                    download_binary(image_url, output)
                    if file_is_valid_image(output):
                        return {
                            "type": "image",
                            "path": output,
                            "source_id": str(photo.get("id", idx))
                        }
                except Exception:
                    continue
        except Exception:
            continue

    raise RuntimeError(f"Aucun visuel Pexels trouvé pour: {keyword}")


def fetch_pexels_video(keyword, idx, temp_dir, is_short):
    if not PEXELS_API_KEY:
        raise RuntimeError("PEXELS_API_KEY manquante.")

    orientation = "portrait" if is_short else "landscape"
    query = clean_visual_query(keyword)
    output = os.path.join(temp_dir, f"clip_{idx:03d}.mp4")

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

        videos = response.json().get("videos", [])
        if not videos:
            return None

        random.shuffle(videos)
        for video in videos[:8]:
            files = video.get("video_files", [])
            compatible = [
                item for item in files
                if item.get("link") and item.get("width", 0) >= 720
            ]
            if not compatible:
                continue
            compatible.sort(key=lambda item: abs(item.get("width", 720) - 1080))
            link = compatible[0]["link"]
            try:
                download_binary(link, output)
                duration = ffprobe_value(output, "format=duration")
                if duration and duration >= 1:
                    return {
                        "type": "video",
                        "path": output,
                        "source_id": str(video.get("id", idx)),
                        "duration": duration
                    }
            except Exception:
                if os.path.exists(output):
                    os.remove(output)
    except Exception:
        return None

    return None


def make_placeholder(keyword, idx, temp_dir, is_short):
    width, height = (1080, 1920) if is_short else (1920, 1080)
    path = os.path.join(temp_dir, f"placeholder_{idx:03d}.jpg")
    image = Image.new("RGB", (width, height), (18, 22, 30))
    image.save(path, quality=92)
    return {
        "type": "image",
        "path": path,
        "source_id": f"placeholder-{idx}"
    }


def fetch_visuals(prompts, temp_dir, is_short, target_count):
    if not prompts:
        prompts = [
            "science laboratory",
            "human brain concept",
            "person thinking",
            "technology close up",
            "night city"
        ]

    prompts = list(prompts)
    while len(prompts) < target_count:
        prompts.extend(prompts[:max(1, target_count - len(prompts))])
    prompts = prompts[:target_count]

    jobs = []
    for idx, prompt in enumerate(prompts):
        jobs.append((idx, prompt))

    results = [None] * len(jobs)

    def worker(item):
        idx, prompt = item
        # Pour un Short, on privilégie les vidéos. Pour le long, on mélange.
        prefer_video = is_short or idx % 3 == 1
        if prefer_video:
            video = fetch_pexels_video(prompt, idx, temp_dir, is_short)
            if video:
                return idx, video
        try:
            photo = fetch_pexels_photo(prompt, idx, temp_dir, is_short)
            return idx, photo
        except Exception:
            video = fetch_pexels_video(prompt, idx, temp_dir, is_short)
            if video:
                return idx, video
            return idx, make_placeholder(prompt, idx, temp_dir, is_short)

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_PEXELS_WORKERS) as executor:
        futures = [executor.submit(worker, job) for job in jobs]
        for future in concurrent.futures.as_completed(futures):
            idx, visual = future.result()
            results[idx] = visual

    return [item for item in results if item and os.path.exists(item["path"])]

# ---------------------------------------------------------
# MONTAGE DYNAMIQUE FFMPEG
# ---------------------------------------------------------
def render_image_scene(image_path, duration, output_path, is_short, effect_index):
    width, height = (1080, 1920) if is_short else (1920, 1080)
    duration = max(0.8, float(duration))
    fps = 25

    effects = [
        (1.00, 1.08, "center"),
        (1.08, 1.00, "center"),
        (1.00, 1.06, "left"),
        (1.06, 1.00, "right")
    ]
    start_zoom, end_zoom, anchor = effects[effect_index % len(effects)]

    if anchor == "left":
        x_expr = "iw/2-(iw/zoom/2)-min(iw/zoom/2,80)"
    elif anchor == "right":
        x_expr = "iw/2-(iw/zoom/2)+min(iw/zoom/2,80)"
    else:
        x_expr = "iw/2-(iw/zoom/2)"

    y_expr = "ih/2-(ih/zoom/2)"
    zoom_expr = f"{start_zoom}+({end_zoom}-{start_zoom})*on/{max(1, int(duration * fps) - 1)}"

    vf = (
        f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,"
        f"crop={width * 2}:{height * 2},"
        f"zoompan=z='{zoom_expr}':x='{x_expr}':y='{y_expr}':"
        f"d={max(1, int(duration * fps))}:s={width}x{height}:fps={fps},"
        "format=yuv420p"
    )

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", image_path,
        "-t", f"{duration:.3f}",
        "-vf", vf,
        "-an",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "21",
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
        output_path
    ]
    code, _, stderr = run_command(cmd, timeout=max(90, int(duration * 12)))
    if code != 0 or not os.path.exists(output_path) or os.path.getsize(output_path) < 5000:
        raise RuntimeError(f"FFmpeg scène image: {stderr[-2500:]}")
    return output_path


def render_video_scene(video_path, duration, output_path, is_short):
    width, height = (1080, 1920) if is_short else (1920, 1080)
    duration = max(0.8, float(duration))

    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},format=yuv420p"
    )

    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1",
        "-i", video_path,
        "-t", f"{duration:.3f}",
        "-vf", vf,
        "-an",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "21",
        "-pix_fmt", "yuv420p",
        "-r", "25",
        output_path
    ]
    code, _, stderr = run_command(cmd, timeout=max(90, int(duration * 12)))
    if code != 0 or not os.path.exists(output_path) or os.path.getsize(output_path) < 5000:
        raise RuntimeError(f"FFmpeg scène vidéo: {stderr[-2500:]}")
    return output_path


def concat_scene_files(scene_files, output_path):
    concat_file = os.path.join(os.path.dirname(output_path), "scenes.txt")
    with open(concat_file, "w", encoding="utf-8") as f:
        for path in scene_files:
            safe = os.path.abspath(path).replace("\\", "/").replace("'", "'\\''")
            f.write(f"file '{safe}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_file,
        "-c", "copy",
        output_path
    ]
    code, _, stderr = run_command(cmd, timeout=300)
    if code != 0 or not os.path.exists(output_path):
        raise RuntimeError(f"FFmpeg concat: {stderr[-3000:]}")
    return output_path


def create_video_ffmpeg(visuals, audio_path, ass_subtitles_path, output_path, is_short):
    if not visuals:
        return None, "Aucun visuel disponible."
    if not audio_path or not os.path.exists(audio_path):
        return None, "Voix off absente. Montage annulé pour éviter une vidéo silencieuse."
    if not ass_subtitles_path or not os.path.exists(ass_subtitles_path):
        return None, "Sous-titres absents. Montage annulé."

    try:
        audio_duration = get_audio_duration(audio_path)
        scene_count = len(visuals)
        base_duration = audio_duration / scene_count
        temp_dir = tempfile.mkdtemp(prefix="studio_scenes_")
        scene_files = []

        for idx, visual in enumerate(visuals):
            scene_path = os.path.join(temp_dir, f"scene_{idx:03d}.mp4")
            # Légère variation de rythme pour éviter l'effet diaporama mécanique.
            multiplier = 0.82 + ((idx * 17) % 37) / 100
            duration = max(1.25, min(base_duration * multiplier, base_duration * 1.35))
            if idx == scene_count - 1:
                duration = max(1.0, audio_duration - sum(
                    max(1.25, min(base_duration * (0.82 + ((j * 17) % 37) / 100), base_duration * 1.35))
                    for j in range(scene_count - 1)
                ))

            if visual["type"] == "video":
                render_video_scene(visual["path"], duration, scene_path, is_short)
            else:
                render_image_scene(visual["path"], duration, scene_path, is_short, idx)
            scene_files.append(scene_path)

        silent_video = os.path.join(temp_dir, "silent.mp4")
        concat_scene_files(scene_files, silent_video)

        width, height = (1080, 1920) if is_short else (1920, 1080)
        clean_ass = os.path.abspath(ass_subtitles_path).replace("\\", "/")
        if os.name == "nt":
            clean_ass = clean_ass.replace(":", "\\:")

        # Ajout voix + sous-titres. -shortest évite toute vidéo qui dépasse l'audio.
        cmd = [
            "ffmpeg", "-y",
            "-i", silent_video,
            "-i", audio_path,
            "-filter_complex", f"[0:v]subtitles='{clean_ass}'[v]",
            "-map", "[v]",
            "-map", "1:a:0",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "21",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "48000",
            "-r", "25",
            "-shortest",
            "-movflags", "+faststart",
            output_path
        ]
        code, stdout, stderr = run_command(cmd, timeout=600)
        if code != 0 or not os.path.exists(output_path) or os.path.getsize(output_path) < 10000:
            log_path = output_path + ".ffmpeg.log.txt"
            with open(log_path, "w", encoding="utf-8") as log:
                log.write("STDOUT\n")
                log.write(stdout or "")
                log.write("\n\nSTDERR\n")
                log.write(stderr or "")
            return None, f"FFmpeg a échoué. Log complet: {log_path}\n{stderr[-4000:]}"

        # Contrôle obligatoire de la piste audio et des caractéristiques.
        duration = ffprobe_value(output_path, "format=duration")
        audio_stream = ffprobe_value(output_path, "stream=duration")
        if duration is None or duration <= 0:
            return None, "Le MP4 final est illisible selon FFprobe."

        probe_cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=codec_name",
            "-of", "default=noprint_wrappers=1:nokey=1",
            output_path
        ]
        code, stdout, _ = run_command(probe_cmd, timeout=30)
        if code != 0 or not stdout.strip():
            return None, "Contrôle qualité échoué: aucune piste audio dans le MP4 final."

        return output_path, None

    except Exception as exc:
        return None, f"Erreur montage: {exc}"

# ---------------------------------------------------------
# CONTROLES DE DUREE
# ---------------------------------------------------------
def validate_duration(duration, is_short):
    if is_short:
        if duration < 45 or duration > 60:
            return False, f"Le Short dure {duration:.1f}s. Il doit être entre 45 et 60 secondes."
        return True, None
    if duration <= 300:
        return False, f"La vidéo longue dure {duration:.1f}s. Elle doit dépasser 5 minutes."
    return True, None

# ---------------------------------------------------------
# INTERFACE
# ---------------------------------------------------------
st.title("🎬 Studio Vidéo IA")
st.write("Génération d'un Pack Duo avec voix off, sous-titres synchronisés et montage dynamique.")

subject_input = st.text_input(
    "Sujet principal de la vidéo",
    placeholder="Exemple: Pourquoi le cerveau procrastine le soir ?",
    key="subject_main"
)

if not OPENROUTER_API_KEY:
    st.warning("OPENROUTER_API_KEY n'est pas configurée dans Render.")
if not PEXELS_API_KEY:
    st.warning("PEXELS_API_KEY n'est pas configurée dans Render.")

if st.button("🚀 Générer le Pack Duo", key="btn_pack", type="primary"):
    if not subject_input.strip():
        st.warning("Veuillez saisir un sujet.")
        st.stop()

    run_id = clean_filename(subject_input) + "_" + str(int(time.time()))
    work_dir = os.path.join(tempfile.gettempdir(), "studio_video", run_id)
    os.makedirs(work_dir, exist_ok=True)

    progress = st.progress(0)
    status = st.empty()

    try:
        status.info("1/7 Génération des deux scripts...")
        progress.progress(5)
        script_long, script_teaser = generate_pack_scripts(subject_input.strip())

        narration_long, prompts_long = parse_script(script_long)
        narration_teaser, prompts_teaser = parse_script(script_teaser)

        if len(narration_long.split()) < 1100:
            raise RuntimeError(
                f"Le script long est trop court ({len(narration_long.split())} mots). "
                "Génération arrêtée pour éviter une vidéo de moins de 5 minutes."
            )
        if not 120 <= len(narration_teaser.split()) <= 180:
            raise RuntimeError(
                f"Le script Short contient {len(narration_teaser.split())} mots. "
                "Une nouvelle génération est nécessaire pour viser 45 à 60 secondes."
            )

        with st.expander("Voir les scripts", expanded=False):
            st.text_area("Script long", script_long, height=300)
            st.text_area("Script Short", script_teaser, height=220)

        status.info("2/7 Génération de la voix off longue avec synchronisation mot par mot...")
        progress.progress(15)
        long_audio = os.path.join(work_dir, "long_voice.mp3")
        long_ass = os.path.join(work_dir, "long_subs.ass")
        audio_long, words_long, err = generate_audio(narration_long, long_audio)
        if err:
            raise RuntimeError(err)
        duration_long = get_audio_duration(audio_long)
        valid, duration_error = validate_duration(duration_long, False)
        if not valid:
            raise RuntimeError(duration_error)
        generate_ass_subtitles(words_long, long_ass, is_short=False)

        status.info("3/7 Génération de la voix off du Short avec synchronisation réelle...")
        progress.progress(27)
        teaser_audio = os.path.join(work_dir, "teaser_voice.mp3")
        teaser_ass = os.path.join(work_dir, "teaser_subs.ass")
        audio_teaser, words_teaser, err = generate_audio(narration_teaser, teaser_audio)
        if err:
            raise RuntimeError(err)
        duration_teaser = get_audio_duration(audio_teaser)
        valid, duration_error = validate_duration(duration_teaser, True)
        if not valid:
            raise RuntimeError(duration_error)
        generate_ass_subtitles(words_teaser, teaser_ass, is_short=True)

        # Nombre de visuels calculé à partir de la durée réelle.
        count_long = max(28, min(55, int(duration_long / 5.0)))
        count_teaser = max(10, min(18, int(duration_teaser / 3.0)))

        status.info(f"4/7 Téléchargement des visuels longs ({count_long})...")
        progress.progress(40)
        long_visual_dir = os.path.join(work_dir, "visuals_long")
        os.makedirs(long_visual_dir, exist_ok=True)
        visuals_long = fetch_visuals(
            prompts_long,
            long_visual_dir,
            is_short=False,
            target_count=count_long
        )
        if len(visuals_long) < 10:
            raise RuntimeError("Trop peu de visuels valides pour le montage long.")

        status.info(f"5/7 Téléchargement des visuels du Short ({count_teaser})...")
        progress.progress(55)
        teaser_visual_dir = os.path.join(work_dir, "visuals_teaser")
        os.makedirs(teaser_visual_dir, exist_ok=True)
        visuals_teaser = fetch_visuals(
            prompts_teaser,
            teaser_visual_dir,
            is_short=True,
            target_count=count_teaser
        )
        if len(visuals_teaser) < 6:
            raise RuntimeError("Trop peu de visuels valides pour le Short.")

        status.info("6/7 Montage dynamique de la vidéo longue...")
        progress.progress(68)
        long_output = os.path.join(work_dir, "long_final.mp4")
        video_long, err = create_video_ffmpeg(
            visuals_long,
            audio_long,
            long_ass,
            long_output,
            is_short=False
        )
        if not video_long:
            raise RuntimeError(err)

        status.info("6/7 Montage dynamique du Short...")
        progress.progress(82)
        teaser_output = os.path.join(work_dir, "teaser_final.mp4")
        video_teaser, err = create_video_ffmpeg(
            visuals_teaser,
            audio_teaser,
            teaser_ass,
            teaser_output,
            is_short=True
        )
        if not video_teaser:
            raise RuntimeError(err)

        status.info("7/7 Contrôle qualité final...")
        progress.progress(94)
        final_long_duration = ffprobe_value(long_output, "format=duration")
        final_teaser_duration = ffprobe_value(teaser_output, "format=duration")

        valid_long, err_long = validate_duration(final_long_duration or 0, False)
        valid_teaser, err_teaser = validate_duration(final_teaser_duration or 0, True)
        if not valid_long:
            raise RuntimeError(f"Contrôle vidéo longue: {err_long}")
        if not valid_teaser:
            raise RuntimeError(f"Contrôle Short: {err_teaser}")

        progress.progress(100)
        status.success("Génération terminée. Les deux fichiers ont passé les contrôles de base.")

        col1, col2 = st.columns(2)
        with col1:
            st.subheader("🎥 Vidéo longue")
            st.caption(f"Durée: {final_long_duration:.1f}s | {len(visuals_long)} visuels")
            st.video(long_output)
            with open(long_output, "rb") as f:
                st.download_button(
                    "📥 Télécharger la vidéo longue",
                    data=f.read(),
                    file_name="video_longue.mp4",
                    mime="video/mp4",
                    key="download_long"
                )

        with col2:
            st.subheader("📱 Short teaser")
            st.caption(f"Durée: {final_teaser_duration:.1f}s | {len(visuals_teaser)} visuels")
            st.video(teaser_output)
            with open(teaser_output, "rb") as f:
                st.download_button(
                    "📥 Télécharger le Short",
                    data=f.read(),
                    file_name="short_teaser.mp4",
                    mime="video/mp4",
                    key="download_teaser"
                )

    except Exception as exc:
        progress.empty()
        status.error("La génération a été arrêtée pour éviter de produire un fichier défectueux.")
        st.error(str(exc))
        st.caption(f"Dossier de travail: {work_dir}")
