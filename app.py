import os
import time
import json
import re
import shutil
import subprocess
import random
import html
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import requests
from PIL import Image
import streamlit as st
from pydantic import BaseModel, Field
from google import genai
from google.genai import types


# ============================================================
# CONFIGURATION
# ============================================================

APP_TITLE = "🧠 Cerveau Curieux — Studio IA Autonome"

BASE_DIR = Path.cwd()
TEMP_DIR = BASE_DIR / "temp"
OUTPUT_DIR = BASE_DIR / "output"

TEMP_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PEXELS_API_KEY = (
    os.environ.get("PEXELS_API_KEY")
    or (st.secrets.get("PEXELS_API_KEY", "") if hasattr(st, "secrets") else "")
)

GEMINI_API_KEY = (
    os.environ.get("GEMINI_API_KEY")
    or (st.secrets.get("GEMINI_API_KEY", "") if hasattr(st, "secrets") else "")
)

FFMPEG_BIN = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE_BIN = shutil.which("ffprobe") or "ffprobe"

TTS_VOICE = "fr-FR-HenriNeural"

# Signature de marque
INTRO_SIGNATURE = "Wesh l'équipe"

CTA_SIGNATURE = (
    "Et maintenant que ton cerveau sait ça... "
    "abonne-toi frérot, parce qu'on n'a pas fini de le faire buguer."
)

# Fichiers audio optionnels
SFX_FILE = next(
    (
        f for f in BASE_DIR.iterdir()
        if f.is_file() and "sfx_whoosh" in f.name.lower()
    ),
    BASE_DIR / "sfx_whoosh.mp3"
)

CLICK_SFX_FILE = next(
    (
        f for f in BASE_DIR.iterdir()
        if f.is_file() and "sfx_ding" in f.name.lower()
    ),
    BASE_DIR / "sfx_ding.mp3"
)

BGM_FILE = next(
    (
        f for f in BASE_DIR.iterdir()
        if f.is_file() and "bgm" in f.name.lower()
    ),
    BASE_DIR / "bgm.mp3"
)

# Mascottes
MASCOT_FILES = {
    "default": BASE_DIR / "mascot_default.png",
    "thinking": BASE_DIR / "mascot_thinking.png",
    "confused": BASE_DIR / "mascot_confused.png",
    "laughing": BASE_DIR / "mascot_laughing.png",
    "explaining": BASE_DIR / "mascot_explaining.png",
    "surprised": BASE_DIR / "mascot_surprised.png",
    "angry": BASE_DIR / "mascot_angry.png",
    "happy": BASE_DIR / "mascot_happy.png",
    "shocked": BASE_DIR / "mascot_shocked.png",
    "sad": BASE_DIR / "mascot_sad.png",
}

if not MASCOT_FILES["default"].exists():
    Image.new(
        "RGBA",
        (200, 200),
        color=(0, 0, 0, 0)
    ).save(MASCOT_FILES["default"])


# ============================================================
# SCHÉMA JSON
# ============================================================

class Scene(BaseModel):
    text: str = Field(
        description=(
            "Une seule phrase courte de narration. "
            "Ton moderne, jeune, urbain et naturel, sans insultes."
        )
    )

    emotion: str = Field(
        description=(
            "Émotion parmi: default, thinking, confused, laughing, "
            "explaining, surprised, angry, happy, shocked, sad"
        )
    )

    visual_query: str = Field(
        description=(
            "Mots-clés visuels en ANGLAIS, 2 à 4 mots, "
            "décrivant une action physique concrète."
        )
    )


class ScriptOutput(BaseModel):
    format_choisi: str = Field(
        description=(
            "Choix parmi: short_single, short_twoparts, long_plus_teaser"
        )
    )

    title: str = Field(
        description=(
            "Titre YouTube/TikTok très accrocheur, fidèle au sujet, "
            "basé sur la curiosité, sans mensonge ni promesse exagérée. "
            "Maximum 65 caractères."
        )
    )

    hashtags: List[str] = Field(
        description=(
            "4 à 6 hashtags très pertinents directement liés au sujet. "
            "Éviter les hashtags génériques sans rapport."
        )
    )

    script_principal: List[Scene] = Field(
        description=(
            "Scènes principales de la vidéo. "
            "La première scène commence obligatoirement par "
            "'Wesh l'équipe'."
        )
    )

    script_teaser: List[Scene] = Field(
        default=[],
        description=(
            "Scènes du teaser si le format long_plus_teaser est choisi."
        )
    )


# ============================================================
# OUTILS
# ============================================================

def cleanup_old_temp_dirs(max_age_hours=2):
    now = time.time()

    for item in TEMP_DIR.iterdir():
        if not item.is_dir():
            continue

        try:
            age = now - item.stat().st_mtime

            if age > max_age_hours * 3600:
                shutil.rmtree(item, ignore_errors=True)

        except Exception:
            pass


def run_command(
    command: List[str],
    cwd: Optional[Path] = None
) -> subprocess.CompletedProcess:

    cmd_str = [str(arg) for arg in command]

    try:
        return subprocess.run(
            cmd_str,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
            cwd=cwd
        )

    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            "Erreur Shell:\n"
            f"Commande: {' '.join(cmd_str)}\n"
            f"Erreur: {e.stderr[-1500:]}"
        )


def get_media_duration(file_path: Path) -> float:

    if not file_path.exists() or file_path.stat().st_size == 0:
        return 0.0

    cmd = [
        FFPROBE_BIN,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(file_path)
    ]

    res = run_command(cmd)

    try:
        return float(res.stdout.strip())
    except ValueError:
        return 0.0


def qc_validate_video(video_path: Path):

    if not video_path.exists():
        raise RuntimeError(
            "QC Échec : le fichier final n'a pas été généré."
        )

    if video_path.stat().st_size < 10000:
        raise RuntimeError(
            "QC Échec : le fichier vidéo semble vide ou corrompu."
        )

    duration = get_media_duration(video_path)

    if duration <= 0:
        raise RuntimeError(
            "QC Échec : impossible de lire la durée de la vidéo."
        )

    # Vérification vidéo
    cmd_video = [
        FFPROBE_BIN,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_type,width,height",
        "-of",
        "json",
        str(video_path)
    ]

    res_video = run_command(cmd_video)

    try:
        data = json.loads(res_video.stdout)
        streams = data.get("streams", [])

        if not streams:
            raise RuntimeError(
                "QC Échec : aucune piste vidéo détectée."
            )

        width = int(streams[0].get("width", 0))
        height = int(streams[0].get("height", 0))

        if width <= 0 or height <= 0:
            raise RuntimeError(
                "QC Échec : résolution vidéo invalide."
            )

    except (ValueError, TypeError, json.JSONDecodeError):
        raise RuntimeError(
            "QC Échec : impossible de vérifier la résolution."
        )

    # Vérification audio
    cmd_audio = [
        FFPROBE_BIN,
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=codec_type",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(video_path)
    ]

    res_audio = run_command(cmd_audio)

    if "audio" not in res_audio.stdout.lower():
        raise RuntimeError(
            "QC Échec : la vidéo générée ne contient pas de piste audio."
        )


# ============================================================
# TEXTE / TTS
# ============================================================

def fix_phonetics_for_tts(text: str) -> str:

    replacements = {
        r"\bbugges\b": "beugues",
        r"\bbugge\b": "beugue",
        r"\bbug\b": "beugue",
        r"\bbugger\b": "beuguer",
        r"\bbuggué\b": "beugué",
    }

    cleaned = text

    for pattern, repl in replacements.items():
        cleaned = re.sub(
            pattern,
            repl,
            cleaned,
            flags=re.IGNORECASE
        )

    return cleaned


def generate_tts(text: str, output_path: Path):

    spoken_text = fix_phonetics_for_tts(text)

    cmd = [
        "edge-tts",
        "--voice",
        TTS_VOICE,
        "--rate",
        "+5%",
        "--text",
        spoken_text,
        "--write-media",
        str(output_path)
    ]

    run_command(cmd)


# ============================================================
# GEMINI
# ============================================================

SYSTEM_PROMPT = f"""
Tu es le réalisateur et scénariste de la chaîne YouTube/TikTok
'Cerveau Curieux'.

OBJECTIF :
Créer des vidéos courtes, modernes, dynamiques et documentées
sur le cerveau, la psychologie, les sciences et les comportements humains.

IDENTITÉ DE MARQUE :

La première scène DOIT commencer exactement par :
"{INTRO_SIGNATURE}"

Cette phrase est la signature sonore de Cerveau Curieux.
Elle doit rester reconnaissable dans toutes les vidéos.

IMPORTANT :
Après "{INTRO_SIGNATURE}", enchaîne immédiatement avec un hook
lié au sujet.

NE PAS mettre de présentation longue.
NE PAS dire "bienvenue sur la chaîne".
NE PAS commencer par une question générique sans intérêt.

STRUCTURE DU DÉBUT :

"{INTRO_SIGNATURE}" + hook très rapide + information intrigante.

STYLE :

- Tutoiement.
- Ton moderne, jeune, urbain et naturel.
- Expressions possibles : "frérot", "ça rend ouf",
  "une dinguerie", "le cerveau il...", "ton cerveau vient de..."
- Aucune insulte.
- Aucune vulgarité.
- Pas de langage artificiellement jeune.
- Le texte doit sonner comme quelqu'un qui parle réellement.

RIGUEUR :

- Ne jamais inventer un fait.
- Ne jamais présenter une hypothèse comme une certitude.
- Ne jamais promettre un résultat que la science ne garantit pas.
- Si une explication scientifique comporte une nuance importante,
  l'exprimer simplement.
- Pas de fake facts pour obtenir des vues.

SCÈNES :

- Une seule phrase courte par scène.
- Environ 1 à 3 secondes par scène.
- Adapter la longueur à la voix naturelle.
- Les scènes doivent s'enchaîner rapidement.
- Chaque scène doit apporter une information ou faire progresser
  l'histoire.
- Éviter les répétitions.

FIN :

La dernière scène DOIT utiliser exactement cette signature :

"{CTA_SIGNATURE}"

Ne pas remplacer cette phrase par un CTA générique.

TITRE :

Créer un titre qui donne immédiatement envie de regarder.

Le titre doit :
- créer une vraie curiosité,
- rester directement lié au sujet,
- être compréhensible en une seconde,
- éviter le clickbait mensonger,
- ne pas inventer d'information,
- éviter "Vous ne croirez jamais...",
- éviter "INCROYABLE !!!",
- éviter les majuscules excessives,
- faire idéalement moins de 65 caractères.

Privilégier des structures comme :
- "Pourquoi ton cerveau fait ça sans que tu le remarques"
- "Ton cerveau fait ça pour une raison surprenante"
- "Pourquoi tu oublies ça dès que tu changes de pièce"
- "Le détail qui piège ton cerveau"
- "Pourquoi ton cerveau réagit comme ça"

Adapter évidemment le titre au sujet réel.

HASHTAGS :

Donner 4 à 6 hashtags.

Priorité :
1. sujet précis,
2. science / psychologie si pertinent,
3. cerveau si pertinent,
4. comportement humain si pertinent.

Éviter les hashtags génériques inutiles.

VISUELS :

Chaque visual_query doit être en anglais,
2 à 4 mots maximum,
et décrire une action physique concrète.

Exemples :
"person opening door"
"confused man thinking"
"woman checking phone"
"brain scan closeup"

FORMAT :

Choisir entre :
short_single
short_twoparts
long_plus_teaser

Pour les Shorts, privilégier short_single sauf si le sujet
nécessite réellement deux parties.

PREMIÈRE SCÈNE :
Elle commence obligatoirement par "{INTRO_SIGNATURE}".

DERNIÈRE SCÈNE :
Elle doit contenir la signature CTA exacte.
"""


def normalize_hashtags(hashtags: List[str]) -> List[str]:

    clean = []

    for tag in hashtags or []:
        if not isinstance(tag, str):
            continue

        tag = tag.strip()

        if not tag:
            continue

        if not tag.startswith("#"):
            tag = "#" + tag

        tag = re.sub(r"[^\w#]", "", tag)

        if len(tag) < 2:
            continue

        if tag.lower() not in [x.lower() for x in clean]:
            clean.append(tag)

    return clean[:6]


def validate_and_repair_script(data: Dict) -> Dict:

    if not isinstance(data, dict):
        raise RuntimeError("Réponse Gemini invalide.")

    scenes = data.get("script_principal") or []

    if not scenes:
        raise RuntimeError("Gemini n'a généré aucune scène.")

    # Conversion en dictionnaires simples
    normalized = []

    for scene in scenes:

        if hasattr(scene, "model_dump"):
            scene = scene.model_dump()

        if not isinstance(scene, dict):
            continue

        text = str(scene.get("text", "")).strip()
        emotion = str(scene.get("emotion", "default")).strip().lower()
        visual_query = str(
            scene.get("visual_query", "brain science")
        ).strip()

        if not text:
            continue

        allowed_emotions = set(MASCOT_FILES.keys())

        if emotion not in allowed_emotions:
            emotion = "default"

        normalized.append({
            "text": text,
            "emotion": emotion,
            "visual_query": visual_query[:80]
        })

    if not normalized:
        raise RuntimeError("Le script Gemini est vide après validation.")

    # Verrouillage de l'identité de début
    first_text = normalized[0]["text"]

    if not first_text.lower().startswith(
        INTRO_SIGNATURE.lower()
    ):
        normalized[0]["text"] = (
            INTRO_SIGNATURE + ". " + first_text
        )

    # Verrouillage du CTA final
    normalized[-1]["text"] = CTA_SIGNATURE
    normalized[-1]["emotion"] = "happy"
    normalized[-1]["visual_query"] = "smiling person thumbs up"

    data["script_principal"] = normalized

    # Nettoyage du titre
    title = str(
        data.get("title", "Pourquoi ton cerveau fait ça")
    ).strip()

    title = re.sub(r"\s+", " ", title)
    title = title.strip("\"'")

    if len(title) > 65:
        title = title[:65].rstrip()

    if not title:
        title = "Pourquoi ton cerveau fait ça"

    data["title"] = title

    data["hashtags"] = normalize_hashtags(
        data.get("hashtags", [])
    )

    if not data["hashtags"]:
        data["hashtags"] = [
            "#Cerveau",
            "#Psychologie",
            "#Science",
            "#CerveauCurieux"
        ]

    return data


def generate_script_gemini(
    topic: str,
    status_cb
) -> Dict:

    if not GEMINI_API_KEY:
        raise RuntimeError(
            "Clé API GEMINI manquante."
        )

    client = genai.Client(api_key=GEMINI_API_KEY)

    status_cb(
        "🧠 Analyse du sujet et rédaction du script..."
    )

    try:

        response = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=(
                "Sujet à traiter :\n"
                f"{topic.strip()}\n\n"
                "Crée le contenu complet en respectant strictement "
                "l'identité Cerveau Curieux."
            ),
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=ScriptOutput,
                temperature=0.75,
            ),
        )

        parsed = None

        if hasattr(response, "parsed") and response.parsed:
            parsed = response.parsed.model_dump()

        if parsed is None:
            parsed = json.loads(response.text)

        return validate_and_repair_script(parsed)

    except Exception as e:
        raise RuntimeError(
            f"Erreur Gemini : {e}"
        )


# ============================================================
# PEXELS
# ============================================================

def clean_pexels_query(query: str) -> str:

    query = re.sub(
        r"[^a-zA-Z\s]",
        "",
        query or ""
    )

    words = [
        w for w in query.split()
        if len(w) > 2
    ]

    return " ".join(words[:4])


def search_pexels_video(
    query: str,
    orientation: str
) -> Optional[str]:

    if not PEXELS_API_KEY:
        return None

    clean_query = clean_pexels_query(query)

    if not clean_query:
        clean_query = "human thinking"

    url = "https://api.pexels.com/videos/search"

    params = {
        "query": clean_query,
        "orientation": orientation,
        "per_page": 12
    }

    headers = {
        "Authorization": PEXELS_API_KEY
    }

    try:

        r = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=10
        )

        if r.status_code != 200:
            return None

        videos = r.json().get("videos", [])

        candidates = []

        for video in videos:

            files = [
                f for f in video.get("video_files", [])
                if ".mp4" in str(
                    f.get("link", "")
                ).lower()
            ]

            for file_info in files:

                width = int(
                    file_info.get("width", 0) or 0
                )

                height = int(
                    file_info.get("height", 0) or 0
                )

                link = file_info.get("link")

                if not link:
                    continue

                # Éviter les vidéos trop petites
                if orientation == "portrait":
                    if height < 720:
                        continue
                else:
                    if width < 1280:
                        continue

                score = width * height

                candidates.append(
                    (score, link)
                )

        if not candidates:
            return None

        candidates.sort(
            key=lambda x: x[0],
            reverse=True
        )

        # Prendre parmi les meilleurs pour éviter
        # d'avoir toujours exactement le même type de fichier.
        top = candidates[:min(5, len(candidates))]

        return random.choice(top)[1]

    except Exception:
        return None


def download_file(
    url: str,
    dest: Path
) -> bool:

    try:

        with requests.get(
            url,
            stream=True,
            timeout=20
        ) as r:

            r.raise_for_status()

            with open(dest, "wb") as f:

                for chunk in r.iter_content(
                    chunk_size=64 * 1024
                ):

                    if chunk:
                        f.write(chunk)

        return (
            dest.exists()
            and dest.stat().st_size > 10000
        )

    except Exception:
        return False


# ============================================================
# SOUS-TITRES ASS
# ============================================================

def ass_time(seconds: float) -> str:

    seconds = max(0.0, seconds)

    hours = int(seconds // 3600)
    minutes = int(
        (seconds % 3600) // 60
    )

    secs = int(seconds % 60)
    centiseconds = int(
        (seconds - int(seconds)) * 100
    )

    return (
        f"{hours}:{minutes:02d}:"
        f"{secs:02d}.{centiseconds:02d}"
    )


def create_ass_subtitles(
    scenes: List[Dict],
    output_ass: Path,
    width: int,
    height: int
):

    if width == 1080:
        font_size = 58
        margin_v = 300
    else:
        font_size = 40
        margin_v = 75

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{font_size},&H00FFFFFF,&H00000000,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,2,30,30,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = []
    current_time = 0.0

    for scene in scenes:

        scene_duration = float(
            scene.get("duration", 0)
        )

        text = (
            str(scene.get("text", ""))
            .replace("\n", " ")
            .replace("{", "")
            .replace("}", "")
            .strip()
        )

        words = text.split()

        if not words:
            current_time += scene_duration
            continue

        # Pour les Shorts, petits groupes.
        # Cela conserve l'effet karaoké sans afficher
        # des blocs énormes.
        chunk_size = 4 if width == 1080 else 5

        chunks = [
            words[i:i + chunk_size]
            for i in range(
                0,
                len(words),
                chunk_size
            )
        ]

        chunk_duration = (
            scene_duration / len(chunks)
        )

        for idx_chunk, chunk_words in enumerate(chunks):

            chunk_start = (
                current_time
                + idx_chunk * chunk_duration
            )

            word_duration = (
                chunk_duration
                / len(chunk_words)
            )

            for idx_word, word in enumerate(
                chunk_words
            ):

                start_t = (
                    chunk_start
                    + idx_word * word_duration
                )

                end_t = start_t + word_duration

                formatted_words = []

                for k, w in enumerate(chunk_words):

                    safe_word = w.replace(
                        ",", ""
                    )

                    if k == idx_word:
                        # Jaune vif pour le mot actif
                        formatted_words.append(
                            "{\\c&H00FFFF&}"
                            + safe_word
                            + "{\\c&HFFFFFF&}"
                        )
                    else:
                        formatted_words.append(
                            safe_word
                        )

                dialogue_text = " ".join(
                    formatted_words
                )

                lines.append(
                    "Dialogue: 0,"
                    f"{ass_time(start_t)},"
                    f"{ass_time(end_t)},"
                    "Default,,0,0,0,,"
                    f"{dialogue_text}"
                )

        current_time += scene_duration

    with open(
        output_ass,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(
            header
            + "\n".join(lines)
        )


# ============================================================
# AUDIO
# ============================================================

def process_scene_audio(
    scene: Dict,
    idx: int,
    total_scenes: int,
    work_dir: Path
) -> Path:

    temp_audio = (
        work_dir
        / f"temp_audio_{idx:03d}.mp3"
    )

    trimmed_audio = (
        work_dir
        / f"audio_{idx:03d}.mp3"
    )

    generate_tts(
        scene["text"],
        temp_audio
    )

    # On garde les effets sonores ponctuels.
    # Pas de whoosh sur absolument chaque phrase.
    is_first = idx == 0
    is_last = idx == total_scenes - 1

    sfx_to_use = None

    if is_last and CLICK_SFX_FILE.exists():
        sfx_to_use = CLICK_SFX_FILE

    elif (
        idx > 0
        and idx % 3 == 0
        and SFX_FILE.exists()
    ):
        sfx_to_use = SFX_FILE

    if sfx_to_use:

        cmd_mix = [
            FFMPEG_BIN,
            "-y",
            "-i",
            str(temp_audio),
            "-i",
            str(sfx_to_use),
            "-filter_complex",
            (
                "[0:a]"
                "areverse,"
                "silenceremove="
                "start_periods=1:"
                "start_duration=0:"
                "start_threshold=-40dB,"
                "areverse"
                "[voice];"
                "[1:a]"
                "volume=0.16"
                "[sfx];"
                "[voice][sfx]"
                "amix=inputs=2:"
                "duration=first:"
                "dropout_transition=0"
                "[mix];"
                "[mix]"
                "loudnorm="
                "I=-16:"
                "LRA=11:"
                "TP=-1.5"
                "[a]"
            ),
            "-map",
            "[a]",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(trimmed_audio)
        ]

        run_command(
            cmd_mix,
            cwd=work_dir
        )

    else:

        cmd_trim = [
            FFMPEG_BIN,
            "-y",
            "-i",
            str(temp_audio),
            "-af",
            (
                "areverse,"
                "silenceremove="
                "start_periods=1:"
                "start_duration=0:"
                "start_threshold=-40dB,"
                "areverse,"
                "loudnorm="
                "I=-16:"
                "LRA=11:"
                "TP=-1.5"
            ),
            "-ar",
            "48000",
            "-ac",
            "2",
            str(trimmed_audio)
        ]

        run_command(
            cmd_trim,
            cwd=work_dir
        )

    scene["duration"] = get_media_duration(
        trimmed_audio
    )

    return trimmed_audio


def concatenate_audio(
    audio_clips: List[Path],
    work_dir: Path
) -> Path:

    concat_file = (
        work_dir / "concat_audio.txt"
    )

    with open(
        concat_file,
        "w",
        encoding="utf-8"
    ) as f:

        for audio in audio_clips:
            f.write(
                f"file '{audio.name}'\n"
            )

    raw_audio = (
        work_dir / "raw_audio.wav"
    )

    # WAV intermédiaire plus robuste
    run_command(
        [
            FFMPEG_BIN,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            "concat_audio.txt",
            "-c:a",
            "pcm_s16le",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(raw_audio)
        ],
        cwd=work_dir
    )

    return raw_audio


def add_background_music(
    voice_audio: Path,
    work_dir: Path
) -> Path:

    output = (
        work_dir / "full_audio.m4a"
    )

    if not BGM_FILE.exists():
        shutil.copy(
            voice_audio,
            output
        )
        return output

    cmd = [
        FFMPEG_BIN,
        "-y",
        "-i",
        str(voice_audio),
        "-stream_loop",
        "-1",
        "-i",
        str(BGM_FILE),
        "-filter_complex",
        (
            "[1:a]"
            "volume=0.045,"
            "highpass=f=80,"
            "lowpass=f=10000"
            "[bgm];"
            "[0:a][bgm]"
            "amix=inputs=2:"
            "duration=first:"
            "dropout_transition=2,"
            "loudnorm="
            "I=-14:"
            "LRA=11:"
            "TP=-1.5"
            "[a]"
        ),
        "-map",
        "[a]",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(output)
    ]

    run_command(
        cmd,
        cwd=work_dir
    )

    return output


# ============================================================
# VIDÉO
# ============================================================

def split_video_in_two(
    input_video: Path,
    total_duration: float,
    out_dir: Path
) -> Tuple[Path, Path]:

    mid_point = total_duration / 2.0

    part1 = (
        out_dir
        / f"{input_video.stem}_Part1.mp4"
    )

    part2 = (
        out_dir
        / f"{input_video.stem}_Part2.mp4"
    )

    run_command(
        [
            FFMPEG_BIN,
            "-y",
            "-i",
            str(input_video),
            "-t",
            str(mid_point),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(part1)
        ]
    )

    run_command(
        [
            FFMPEG_BIN,
            "-y",
            "-ss",
            str(mid_point),
            "-i",
            str(input_video),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(part2)
        ]
    )

    return part1, part2


def generate_video_pipeline(
    script_scenes: List[Dict],
    video_format: str,
    status_cb
) -> Path:

    if not script_scenes:
        raise ValueError(
            "Le script est vide."
        )

    work_dir = (
        TEMP_DIR
        / f"run_{int(time.time())}_{video_format}"
    )

    work_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    width, height = (
        (1080, 1920)
        if video_format == "portrait"
        else (1920, 1080)
    )

    orientation = (
        "portrait"
        if video_format == "portrait"
        else "landscape"
    )

    # --------------------------------------------------------
    # AUDIO
    # --------------------------------------------------------

    status_cb(
        "🎙️ Génération de la voix off..."
    )

    audio_clips = []
    total_scenes = len(script_scenes)

    for idx, scene in enumerate(
        script_scenes
    ):

        audio_path = process_scene_audio(
            scene,
            idx,
            total_scenes,
            work_dir
        )

        audio_clips.append(
            audio_path
        )

    raw_audio = concatenate_audio(
        audio_clips,
        work_dir
    )

    full_audio = add_background_music(
        raw_audio,
        work_dir
    )

    # --------------------------------------------------------
    # VIDÉOS
    # --------------------------------------------------------

    status_cb(
        "🎥 Recherche et montage des visuels..."
    )

    video_clips = []

    fps = 30

    if video_format == "portrait":
        mascot_scale = int(
            width * 0.19
        )

        mascot_positions = [
            ("(W-w)/2", "H-h-470"),
            ("40", "H-h-470"),
            ("W-w-40", "H-h-470"),
        ]

    else:

        mascot_scale = int(
            width * 0.14
        )

        mascot_positions = [
            ("40", "H-h-40"),
            ("W-w-40", "H-h-40"),
            ("40", "H-h-120"),
        ]

    for idx, scene in enumerate(
        script_scenes
    ):

        duration = float(
            scene.get("duration", 1.0)
        )

        duration = max(
            0.5,
            duration
        )

        emotion = scene.get(
            "emotion",
            "default"
        )

        mascot_img = MASCOT_FILES.get(
            emotion,
            MASCOT_FILES["default"]
        )

        if not mascot_img.exists():
            mascot_img = MASCOT_FILES["default"]

        # Recherche Pexels
        url = search_pexels_video(
            scene.get(
                "visual_query",
                "brain science"
            ),
            orientation
        )

        visual_file = (
            work_dir
            / f"src_vis_{idx:03d}.mp4"
        )

        output_clip = (
            work_dir
            / f"clip_{idx:03d}.mp4"
        )

        # Position variable mais contrôlée
        pos_x, pos_y = mascot_positions[
            idx % len(mascot_positions)
        ]

        # La mascotte ne doit pas être présente
        # sur une durée énorme.
        mascot_duration = min(
            2.5,
            duration
        )

        enable_expr = (
            f"between(t,0,{mascot_duration})"
        )

        if url and download_file(
            url,
            visual_file
        ):

            # Zoom progressif très léger.
            # L'objectif est d'éviter l'effet diaporama.
            base_filter = (
                f"[0:v]"
                f"scale={width}:{height}:"
                "force_original_aspect_ratio=increase,"
                f"crop={width}:{height},"
                "zoompan="
                "z='min(zoom+0.0008,1.08)':"
                f"d={max(1, int(duration * fps))}:"
                "x='iw/2-(iw/zoom/2)':"
                "y='ih/2-(ih/zoom/2)':"
                f"s={width}x{height}:"
                f"fps={fps}"
                "[bg]"
            )

            cmd = [
                FFMPEG_BIN,
                "-y",
                "-stream_loop",
                "-1",
                "-i",
                str(visual_file),
                "-loop",
                "1",
                "-i",
                str(mascot_img.resolve())
            ]

        else:

            fallback = (
                work_dir
                / f"fallback_{idx:03d}.png"
            )

            # Fond neutre uniquement en dernier recours.
            Image.new(
                "RGB",
                (width, height),
                color=(20, 20, 35)
            ).save(fallback)

            frames = max(
                1,
                int(duration * fps)
            )

            base_filter = (
                f"[0:v]"
                "zoompan="
                "z='min(zoom+0.0025,1.12)':"
                f"d={frames}:"
                "x='iw/2-(iw/zoom/2)':"
                "y='ih/2-(ih/zoom/2)':"
                f"s={width}x{height}:"
                f"fps={fps}"
                "[bg]"
            )

            cmd = [
                FFMPEG_BIN,
                "-y",
                "-loop",
                "1",
                "-i",
                str(fallback),
                "-loop",
                "1",
                "-i",
                str(mascot_img.resolve())
            ]

        filter_complex = (
            f"{base_filter};"
            f"[1:v]"
            f"scale={mascot_scale}:-1,"
            "format=rgba"
            "[mascot];"
            f"[bg][mascot]"
            f"overlay=x={pos_x}:y={pos_y}:"
            f"enable='{enable_expr}'"
            "[v_out]"
        )

        cmd.extend(
            [
                "-t",
                str(duration),
                "-filter_complex",
                filter_complex,
                "-map",
                "[v_out]",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-r",
                str(fps),
                "-movflags",
                "+faststart",
                str(output_clip)
            ]
        )

        run_command(
            cmd,
            cwd=work_dir
        )

        video_clips.append(
            output_clip
        )

    # --------------------------------------------------------
    # CONCATÉNATION VIDÉO
    # --------------------------------------------------------

    status_cb(
        "⚡ Fusion des scènes..."
    )

    raw_video = (
        work_dir / "raw_video.mp4"
    )

    if len(video_clips) == 1:

        shutil.copy(
            video_clips[0],
            raw_video
        )

    else:

        concat_file = (
            work_dir
            / "concat_video.txt"
        )

        with open(
            concat_file,
            "w",
            encoding="utf-8"
        ) as f:

            for video in video_clips:
                f.write(
                    f"file '{video.name}'\n"
                )

        run_command(
            [
                FFMPEG_BIN,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                "concat_video.txt",
                "-c",
                "copy",
                str(raw_video.name)
            ],
            cwd=work_dir
        )

    # --------------------------------------------------------
    # SOUS-TITRES
    # --------------------------------------------------------

    status_cb(
        "💬 Création des sous-titres karaoké..."
    )

    subtitles_file = (
        work_dir / "subtitles.ass"
    )

    create_ass_subtitles(
        script_scenes,
        subtitles_file,
        width,
        height
    )

    # --------------------------------------------------------
    # EXPORT FINAL
    # --------------------------------------------------------

    status_cb(
        "🎬 Rendu final..."
    )

    watermark_x = 35
    watermark_y = (
        55
        if video_format == "portrait"
        else 35
    )

    # Pas d'emoji dans drawtext, car certains serveurs
    # FFmpeg n'ont pas la police adéquate.
    vf_filter = (
        "subtitles=subtitles.ass,"
        "drawtext="
        "text='CERVEAU CURIEUX':"
        f"x={watermark_x}:"
        f"y={watermark_y}:"
        "fontsize=25:"
        "fontcolor=white:"
        "box=1:"
        "boxcolor=black@0.45:"
        "boxborderw=7"
    )

    final_output = (
        OUTPUT_DIR
        / f"export_{int(time.time())}_"
        f"{video_format}.mp4"
    )

    cmd_final = [
        FFMPEG_BIN,
        "-y",
        "-i",
        "raw_video.mp4",
        "-i",
        "full_audio.m4a",
        "-vf",
        vf_filter,
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-shortest",
        "-movflags",
        "+faststart",
        str(final_output.resolve())
    ]

    run_command(
        cmd_final,
        cwd=work_dir
    )

    # --------------------------------------------------------
    # QC
    # --------------------------------------------------------

    status_cb(
        "🔍 Contrôle qualité final..."
    )

    qc_validate_video(
        final_output
    )

    return final_output


# ============================================================
# INTERFACE STREAMLIT
# ============================================================

def main():

    st.set_page_config(
        page_title=APP_TITLE,
        page_icon="🧠",
        layout="centered",
        initial_sidebar_state="expanded"
    )

    st.markdown(
        """
        <style>

        .stApp {
            background-color: #0E1117;
        }

        div.stButton > button:first-child {
            background: linear-gradient(
                90deg,
                #FF4B4B 0%,
                #FF8F8F 100%
            );
            color: white;
            border: none;
            border-radius: 12px;
            padding: 0.6rem 1rem;
            font-size: 1.2rem;
            font-weight: 700;
            width: 100%;
            transition: all 0.3s ease;
            box-shadow:
                0 4px 6px rgba(255, 75, 75, 0.2);
        }

        div.stButton > button:first-child:hover {
            transform: translateY(-2px);
            box-shadow:
                0 6px 15px rgba(255, 75, 75, 0.4);
            color: white;
        }

        .main-title {
            text-align: center;
            font-size: 3rem;
            font-weight: 800;
            margin-bottom: 0px;
            color: #FFFFFF;
        }

        .sub-title {
            text-align: center;
            font-size: 1.2rem;
            color: #A0AEC0;
            margin-top: 0px;
            margin-bottom: 30px;
        }

        .stTextArea textarea {
            background-color: #1A1C24;
            border: 1px solid #2D3748;
            border-radius: 10px;
            color: #E2E8F0;
            font-size: 1.1rem;
        }

        .stTextArea textarea:focus {
            border-color: #FF4B4B;
            box-shadow:
                0 0 0 1px #FF4B4B;
        }

        </style>
        """,
        unsafe_allow_html=True
    )

    # --------------------------------------------------------
    # SIDEBAR
    # --------------------------------------------------------

    with st.sidebar:

        st.markdown(
            "<h3 style='text-align:center;'>"
            "Tableau de bord"
            "</h3>",
            unsafe_allow_html=True
        )

        if MASCOT_FILES["default"].exists():

            st.image(
                str(MASCOT_FILES["default"]),
                use_container_width=True
            )

        st.markdown("---")

        st.markdown(
            "🎯 **Mode Autonome Actif**"
        )

        st.write(
            "Pipeline Gemini + Edge-TTS + Pexels + FFmpeg."
        )

        st.markdown("---")

        st.caption(
            "Signature : Wesh l'équipe"
        )

        st.caption(
            "CTA : signature Cerveau Curieux"
        )

    # --------------------------------------------------------
    # HEADER
    # --------------------------------------------------------

    st.markdown(
        '<div class="main-title">'
        '🧠 Cerveau Curieux'
        '</div>',
        unsafe_allow_html=True
    )

    st.markdown(
        '<div class="sub-title">'
        'Studio IA Autonome 🎬'
        '</div>',
        unsafe_allow_html=True
    )

    cleanup_old_temp_dirs()

    # --------------------------------------------------------
    # SUJET
    # --------------------------------------------------------

    st.markdown(
        "### 📝 Quel est ton sujet aujourd'hui ?"
    )

    topic = st.text_area(
        "Sujet",
        placeholder=(
            "Ex: Pourquoi le cerveau oublie-t-il "
            "ce qu'il est venu chercher en passant "
            "une porte ?"
        ),
        label_visibility="collapsed",
        height=120
    )

    if st.button(
        "🚀 LANCER LA GÉNÉRATION"
    ):

        if not topic.strip():

            st.warning(
                "⚠️ Oups ! Tu as oublié d'écrire un sujet."
            )

            return

        with st.status(
            "🎬 Allumage des caméras virtuelles...",
            expanded=True
        ) as status_box:

            try:

                def update_status(msg):
                    st.write(msg)

                # -------------------------------
                # SCRIPT
                # -------------------------------

                ai_data = generate_script_gemini(
                    topic,
                    update_status
                )

                format_choisi = ai_data.get(
                    "format_choisi",
                    "short_single"
                )

                title = ai_data.get(
                    "title",
                    "Pourquoi ton cerveau fait ça"
                )

                st.write(
                    "✅ Format défini : "
                    f"**{format_choisi.replace('_', ' ').title()}**"
                )

                # -------------------------------
                # VIDÉO
                # -------------------------------

                if format_choisi == "short_single":

                    video_path = (
                        generate_video_pipeline(
                            ai_data.get(
                                "script_principal",
                                []
                            ),
                            "portrait",
                            update_status
                        )
                    )

                elif format_choisi == "short_twoparts":

                    full_video_path = (
                        generate_video_pipeline(
                            ai_data.get(
                                "script_principal",
                                []
                            ),
                            "portrait",
                            update_status
                        )
                    )

                    update_status(
                        "✂️ Découpage de la vidéo en 2 parties..."
                    )

                    total_duration = (
                        get_media_duration(
                            full_video_path
                        )
                    )

                    part1, part2 = (
                        split_video_in_two(
                            full_video_path,
                            total_duration,
                            OUTPUT_DIR
                        )
                    )

                    video_path = [
                        part1,
                        part2
                    ]

                elif format_choisi == "long_plus_teaser":

                    long_path = (
                        generate_video_pipeline(
                            ai_data.get(
                                "script_principal",
                                []
                            ),
                            "landscape",
                            update_status
                        )
                    )

                    short_path = (
                        generate_video_pipeline(
                            ai_data.get(
                                "script_teaser",
                                []
                            ),
                            "portrait",
                            update_status
                        )
                    )

                    video_path = [
                        long_path,
                        short_path
                    ]

                else:

                    raise RuntimeError(
                        f"Format inconnu : {format_choisi}"
                    )

                status_box.update(
                    label=(
                        "🎉 Production terminée avec succès !"
                    ),
                    state="complete",
                    expanded=False
                )

            except Exception as e:

                status_box.update(
                    label=(
                        "❌ Oups, une erreur s'est produite."
                    ),
                    state="error",
                    expanded=True
                )

                st.error(
                    str(e)
                )

                return

        # ----------------------------------------------------
        # RÉSULTATS
        # ----------------------------------------------------

        st.markdown("---")

        st.markdown(
            "## 🍿 Ton contenu est prêt !"
        )

        info_tab, video_tab = st.tabs(
            [
                "📄 Informations",
                "🎥 Vidéo(s)"
            ]
        )

        # ----------------------------------------------------
        # INFORMATIONS
        # ----------------------------------------------------

        with info_tab:

            st.info(
                f"**Titre suggéré :** {title}"
            )

            st.write(
                "**Hashtags :** "
                + " ".join(
                    ai_data.get(
                        "hashtags",
                        []
                    )
                )
            )

            st.caption(
                "Titre optimisé pour créer de la curiosité "
                "sans inventer de promesse."
            )

            st.markdown("---")

            with st.expander(
                "📜 Voir le script complet"
            ):

                script_complet = ""

                for idx, scene in enumerate(
                    ai_data.get(
                        "script_principal",
                        []
                    )
                ):

                    script_complet += (
                        f"Scène {idx + 1} : "
                        f"{scene.get('text', '')}\n\n"
                    )

                st.code(
                    script_complet,
                    language="text"
                )

        # ----------------------------------------------------
        # VIDÉOS
        # ----------------------------------------------------

        with video_tab:

            if format_choisi == "short_single":

                st.video(
                    str(video_path)
                )

                st.download_button(
                    "⬇️ Télécharger la vidéo",
                    data=open(
                        video_path,
                        "rb"
                    ).read(),
                    file_name=video_path.name,
                    mime="video/mp4"
                )

            elif format_choisi == "short_twoparts":

                col1, col2 = st.columns(2)

                with col1:

                    st.caption(
                        "Partie 1"
                    )

                    st.video(
                        str(video_path[0])
                    )

                with col2:

                    st.caption(
                        "Partie 2"
                    )

                    st.video(
                        str(video_path[1])
                    )

            elif format_choisi == "long_plus_teaser":

                st.subheader(
                    "📺 Format Long (16:9)"
                )

                st.video(
                    str(video_path[0])
                )

                st.divider()

                st.subheader(
                    "📱 Teaser Short (9:16)"
                )

                st.video(
                    str(video_path[1])
                )

        st.balloons()


if __name__ == "__main__":
    main()
