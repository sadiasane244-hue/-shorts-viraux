import os
import time
import json
import re
import shutil
import subprocess
import random
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


# ============================================================
# CLÉS API
# ============================================================

PEXELS_API_KEY = (
    os.environ.get("PEXELS_API_KEY")
    or (
        st.secrets.get("PEXELS_API_KEY", "")
        if hasattr(st, "secrets")
        else ""
    )
)

GEMINI_API_KEY = (
    os.environ.get("GEMINI_API_KEY")
    or (
        st.secrets.get("GEMINI_API_KEY", "")
        if hasattr(st, "secrets")
        else ""
    )
)


# ============================================================
# BINAIRES
# ============================================================

FFMPEG_BIN = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE_BIN = shutil.which("ffprobe") or "ffprobe"


# ============================================================
# TTS
# ============================================================

TTS_VOICE = "fr-FR-HenriNeural"
TTS_RATE = "+5%"


# ============================================================
# IDENTITÉ DE MARQUE
# ============================================================

INTRO_SIGNATURE = "Wesh l'équipe"

CTA_SIGNATURE = (
    "Et maintenant que ton cerveau sait ça... "
    "abonne-toi frérot, parce qu'on n'a pas fini de le faire buguer."
)


# ============================================================
# OBJECTIFS DE DURÉE SHORT
# ============================================================

# Durée absolue autorisée
SHORT_MIN_DURATION = 45.0
SHORT_MAX_DURATION = 60.0

# Zone idéale recherchée par le pré-test TTS
SHORT_PREVIEW_MIN_DURATION = 45.5
SHORT_PREVIEW_TARGET_MIN = 47.0
SHORT_PREVIEW_TARGET_MAX = 58.0

# Le nombre de mots est volontairement plus élevé qu'avant.
#
# Ancien réglage :
# 140 mots -> environ 39 secondes dans votre capture.
#
# Nouveau réglage :
# 165 à 180 mots -> beaucoup plus de chances d'obtenir
# une vraie durée de 45 à 60 secondes avec HenriNeural +5%.
#
# La durée réelle TTS reste prioritaire sur le simple
# nombre de mots.
SHORT_MIN_WORDS = 160
SHORT_TARGET_MIN_WORDS = 165
SHORT_TARGET_MAX_WORDS = 180
SHORT_MAX_WORDS = 190


# ============================================================
# AUDIO OPTIONNEL
# ============================================================

SFX_FILE = next(
    (
        f
        for f in BASE_DIR.iterdir()
        if f.is_file()
        and "sfx_whoosh" in f.name.lower()
    ),
    BASE_DIR / "sfx_whoosh.mp3"
)

CLICK_SFX_FILE = next(
    (
        f
        for f in BASE_DIR.iterdir()
        if f.is_file()
        and "sfx_ding" in f.name.lower()
    ),
    BASE_DIR / "sfx_ding.mp3"
)

BGM_FILE = next(
    (
        f
        for f in BASE_DIR.iterdir()
        if f.is_file()
        and "bgm" in f.name.lower()
    ),
    BASE_DIR / "bgm.mp3"
)


# ============================================================
# MASCOTTES
# ============================================================

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
    ).save(
        MASCOT_FILES["default"]
    )


# ============================================================
# SCHÉMA JSON
# ============================================================

class Scene(BaseModel):
    text: str = Field(
        description=(
            "Une seule phrase courte de narration. "
            "Ton moderne, jeune, urbain et naturel."
        )
    )

    emotion: str = Field(
        description=(
            "Émotion parmi: default, thinking, confused, "
            "laughing, explaining, surprised, angry, "
            "happy, shocked, sad"
        )
    )

    visual_query: str = Field(
        description=(
            "Mots-clés visuels en anglais, 2 à 4 mots, "
            "décrivant une action physique concrète."
        )
    )


class ScriptOutput(BaseModel):
    format_choisi: str = Field(
        description=(
            "Choix parmi: short_single, short_twoparts, "
            "long_plus_teaser"
        )
    )

    title: str = Field(
        description=(
            "Titre YouTube/TikTok très accrocheur, "
            "fidèle au sujet, basé sur la curiosité, "
            "sans mensonge. Maximum 65 caractères."
        )
    )

    hashtags: List[str] = Field(
        description=(
            "4 à 6 hashtags pertinents directement liés "
            "au sujet."
        )
    )

    script_principal: List[Scene] = Field(
        description=(
            "Scènes principales de la vidéo. "
            "Pour un Short, viser environ 165 à 180 mots. "
            "La première scène commence obligatoirement "
            "par 'Wesh l'équipe'. "
            "La dernière scène est exactement le CTA demandé."
        )
    )

    script_teaser: List[Scene] = Field(
        default_factory=list,
        description=(
            "Scènes du teaser si le format "
            "long_plus_teaser est choisi."
        )
    )


# ============================================================
# OUTILS GÉNÉRAUX
# ============================================================

def cleanup_old_temp_dirs(max_age_hours=2):

    now = time.time()

    for item in TEMP_DIR.iterdir():

        if not item.is_dir():
            continue

        try:

            age = now - item.stat().st_mtime

            if age > max_age_hours * 3600:

                shutil.rmtree(
                    item,
                    ignore_errors=True
                )

        except Exception:
            pass


def run_command(
    command: List[str],
    cwd: Optional[Path] = None
) -> subprocess.CompletedProcess:

    cmd_str = [
        str(arg)
        for arg in command
    ]

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
            f"Erreur: {e.stderr[-2000:]}"
        )


def get_media_duration(
    file_path: Path
) -> float:

    if (
        not file_path.exists()
        or file_path.stat().st_size == 0
    ):
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

        return float(
            res.stdout.strip()
        )

    except ValueError:

        return 0.0


def count_words_in_scenes(
    scenes: List[Dict]
) -> int:

    total = 0

    for scene in scenes or []:

        text = str(
            scene.get(
                "text",
                ""
            )
        ).strip()

        total += len(
            text.split()
        )

    return total


def qc_validate_video(
    video_path: Path,
    expected_format: Optional[str] = None
):

    if not video_path.exists():

        raise RuntimeError(
            "QC Échec : le fichier final "
            "n'a pas été généré."
        )

    if video_path.stat().st_size < 10000:

        raise RuntimeError(
            "QC Échec : la vidéo semble vide "
            "ou corrompue."
        )

    duration = get_media_duration(
        video_path
    )

    if duration <= 0:

        raise RuntimeError(
            "QC Échec : impossible de lire "
            "la durée de la vidéo."
        )

    # --------------------------------------------------------
    # VIDÉO
    # --------------------------------------------------------

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

    res_video = run_command(
        cmd_video
    )

    try:

        data = json.loads(
            res_video.stdout
        )

        streams = data.get(
            "streams",
            []
        )

        if not streams:

            raise RuntimeError(
                "QC Échec : aucune piste "
                "vidéo détectée."
            )

        width = int(
            streams[0].get(
                "width",
                0
            )
        )

        height = int(
            streams[0].get(
                "height",
                0
            )
        )

        if width <= 0 or height <= 0:

            raise RuntimeError(
                "QC Échec : résolution vidéo invalide."
            )

        if expected_format == "portrait":

            if height <= width:

                raise RuntimeError(
                    "QC Échec : le Short final "
                    "n'est pas au format vertical."
                )

        elif expected_format == "landscape":

            if width <= height:

                raise RuntimeError(
                    "QC Échec : la vidéo longue "
                    "n'est pas au format horizontal."
                )

    except (
        ValueError,
        TypeError,
        json.JSONDecodeError
    ):

        raise RuntimeError(
            "QC Échec : impossible de vérifier "
            "la résolution."
        )

    # --------------------------------------------------------
    # AUDIO
    # --------------------------------------------------------

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

    res_audio = run_command(
        cmd_audio
    )

    if "audio" not in res_audio.stdout.lower():

        raise RuntimeError(
            "QC Échec : aucune piste audio détectée."
        )

    return duration


# ============================================================
# TEXTE / TTS
# ============================================================

def fix_phonetics_for_tts(
    text: str
) -> str:

    """
    IMPORTANT :

    Le mot 'buguer' est volontairement conservé.

    Nous ne le transformons plus en 'beuguer', car cette
    transformation modifiait la prononciation recherchée
    et pouvait rendre le CTA moins naturel.

    Le texte affiché et le texte TTS restent donc identiques.
    """

    return text


def generate_tts(
    text: str,
    output_path: Path
):

    spoken_text = fix_phonetics_for_tts(
        text
    )

    cmd = [
        "edge-tts",
        "--voice",
        TTS_VOICE,
        "--rate",
        TTS_RATE,
        "--text",
        spoken_text,
        "--write-media",
        str(output_path)
    ]

    run_command(
        cmd
    )


# ============================================================
# GEMINI
# ============================================================

SYSTEM_PROMPT = f"""
Tu es le réalisateur et scénariste de la chaîne
YouTube/TikTok 'Cerveau Curieux'.

OBJECTIF :
Créer des vidéos courtes, modernes, dynamiques,
documentées et réellement intéressantes sur le cerveau,
la psychologie, les sciences et les comportements humains.

============================================================
IDENTITÉ DE MARQUE
============================================================

La première scène DOIT commencer exactement par :

"{INTRO_SIGNATURE}"

Cette phrase est la signature sonore de Cerveau Curieux.

Après cette phrase, enchaîne immédiatement avec
un hook fort lié au sujet.

Ne fais PAS de présentation longue.

Ne dis PAS :
"Bienvenue sur la chaîne."

Ne perds PAS plusieurs secondes à expliquer ce que
va faire la vidéo.

============================================================
STYLE
============================================================

- Tutoiement.
- Ton moderne, jeune, urbain et naturel.
- Le texte doit sonner comme une vraie personne qui parle.
- Expressions possibles : "frérot", "ça rend ouf",
  "une dinguerie", "ton cerveau il..."
- Aucune insulte.
- Aucune vulgarité.
- Pas de langage artificiellement jeune.
- Pas de phrases inutiles.

============================================================
RIGUEUR SCIENTIFIQUE
============================================================

- Ne jamais inventer un fait.
- Ne jamais présenter une hypothèse comme une certitude.
- Ne jamais utiliser un faux chiffre.
- Ne jamais inventer une expérience scientifique.
- Si une nuance scientifique est importante,
  l'expliquer simplement.
- Le contenu doit rester fidèle aux connaissances
  scientifiques disponibles.

============================================================
DURÉE DES SHORTS
============================================================

Pour short_single et short_twoparts :

Le script principal doit viser environ :

165 à 180 mots.

Minimum absolu :

160 mots.

Maximum normal :

190 mots.

IMPORTANT :

Le nombre de mots n'est qu'une cible.

La durée réelle de la voix Edge-TTS est prioritaire.

La narration doit naturellement produire
environ 45 à 60 secondes.

NE JAMAIS ralentir artificiellement la voix.

NE JAMAIS ajouter de silence.

NE JAMAIS répéter une phrase.

NE JAMAIS écrire des phrases uniquement
pour atteindre un nombre de mots.

Chaque phrase doit avoir une fonction réelle :

- apporter un fait,
- expliquer un mécanisme,
- donner un exemple,
- montrer une conséquence,
- apporter une nuance,
- créer une transition utile,
- ou faire progresser le raisonnement.

INTERDIT :

"Et c'est vraiment incroyable."

"Mais attends, c'est fou."

"Tu vas halluciner."

"Et voilà pourquoi c'est dingue."

si ces phrases n'apportent aucune information.

Si le sujet permet d'expliquer davantage,
utilise cette place pour apporter de vraies informations.

============================================================
STRUCTURE D'UN SHORT
============================================================

Structure recommandée :

1. Signature :
"{INTRO_SIGNATURE}"

2. Hook immédiat.

3. Présentation rapide du phénomène.

4. Explication du mécanisme.

5. Exemple concret du quotidien.

6. Conséquence ou détail surprenant.

7. Petite nuance scientifique si nécessaire.

8. Conclusion.

9. CTA exact.

Le contenu doit rester fluide et naturel.

============================================================
SCÈNES
============================================================

Une scène contient une seule phrase.

Les scènes doivent être courtes pour permettre
un montage dynamique.

Cependant :

NE DÉCOUPE PAS artificiellement une phrase
uniquement pour créer davantage de scènes.

Chaque scène doit correspondre à une vraie
unité de narration.

Vise environ 18 à 28 scènes pour un Short.

============================================================
FIN
============================================================

La dernière scène DOIT être exactement :

"{CTA_SIGNATURE}"

Ne modifie aucun mot de cette phrase.

============================================================
TITRE
============================================================

Créer un titre très accrocheur mais honnête.

Le titre doit :

- créer une vraie curiosité,
- être directement lié au sujet,
- être compréhensible immédiatement,
- éviter le clickbait mensonger,
- ne rien promettre que la vidéo ne démontre pas,
- éviter "Vous ne croirez jamais...",
- éviter "INCROYABLE !!!",
- éviter les majuscules excessives,
- rester sous 65 caractères.

============================================================
HASHTAGS
============================================================

Donner 4 à 6 hashtags.

Priorité :

1. sujet précis,
2. science,
3. psychologie,
4. cerveau,
5. comportement humain.

Éviter les hashtags génériques inutiles.

============================================================
VISUELS PEXELS
============================================================

IMPORTANT :

Les visuels seront recherchés sur Pexels sous forme
de VRAIES VIDÉOS.

Chaque visual_query doit donc décrire une scène physique
qui peut exister sous forme de clip vidéo.

Utiliser uniquement :

- 2 à 4 mots,
- en anglais,
- action concrète,
- sujet visuel facilement trouvable sur Pexels.

Exemples :

"person opening door"
"confused man thinking"
"woman checking phone"
"brain scan closeup"
"student studying desk"
"person forgetting keys"
"man looking confused"

Éviter les concepts abstraits impossibles à rechercher.

============================================================
FORMAT
============================================================

Choisir entre :

short_single
short_twoparts
long_plus_teaser

Pour un sujet normal de Short, privilégier :

short_single

Utiliser short_twoparts uniquement si le sujet
gagne réellement à être séparé en deux parties.

Pour long_plus_teaser, le script principal doit être
nettement plus long et documenté.

============================================================
RÈGLE ABSOLUE
============================================================

NE REMPLIS JAMAIS LA DURÉE AVEC DU BLABLA.

Une vidéo plus longue doit être plus riche,
pas simplement plus bavarde.

Si une réparation est demandée parce que la durée
audio est trop courte, ajoute uniquement des
informations réellement pertinentes au sujet.
"""


# ============================================================
# NORMALISATION DES HASHTAGS
# ============================================================

def normalize_hashtags(
    hashtags: List[str]
) -> List[str]:

    clean = []

    for tag in hashtags or []:

        if not isinstance(
            tag,
            str
        ):
            continue

        tag = tag.strip()

        if not tag:
            continue

        if not tag.startswith("#"):
            tag = "#" + tag

        tag = re.sub(
            r"[^\w#]",
            "",
            tag
        )

        if len(tag) < 2:
            continue

        if tag.lower() not in [
            x.lower()
            for x in clean
        ]:

            clean.append(tag)

    return clean[:6]


# ============================================================
# NORMALISATION D'UNE SCÈNE
# ============================================================

def normalize_scene(
    scene
) -> Optional[Dict]:

    if hasattr(
        scene,
        "model_dump"
    ):

        scene = scene.model_dump()

    if not isinstance(
        scene,
        dict
    ):

        return None

    text = str(
        scene.get(
            "text",
            ""
        )
    ).strip()

    emotion = str(
        scene.get(
            "emotion",
            "default"
        )
    ).strip().lower()

    visual_query = str(
        scene.get(
            "visual_query",
            "person thinking"
        )
    ).strip()

    if not text:
        return None

    allowed_emotions = set(
        MASCOT_FILES.keys()
    )

    if emotion not in allowed_emotions:

        emotion = "default"

    visual_query = clean_pexels_query(
        visual_query
    )

    if not visual_query:

        visual_query = "person thinking"

    return {
        "text": text,
        "emotion": emotion,
        "visual_query": visual_query[:80]
    }


# ============================================================
# VALIDATION ET RÉPARATION DU SCRIPT
# ============================================================

def validate_and_repair_script(
    data: Dict
) -> Dict:

    if not isinstance(
        data,
        dict
    ):

        raise RuntimeError(
            "Réponse Gemini invalide."
        )

    scenes = data.get(
        "script_principal"
    ) or []

    if not scenes:

        raise RuntimeError(
            "Gemini n'a généré aucune scène."
        )

    normalized = []

    for scene in scenes:

        clean_scene = normalize_scene(
            scene
        )

        if clean_scene:

            normalized.append(
                clean_scene
            )

    if not normalized:

        raise RuntimeError(
            "Le script Gemini est vide "
            "après validation."
        )

    # --------------------------------------------------------
    # INTRO
    # --------------------------------------------------------

    first_text = normalized[0]["text"]

    if not first_text.lower().startswith(
        INTRO_SIGNATURE.lower()
    ):

        normalized[0]["text"] = (
            INTRO_SIGNATURE
            + ". "
            + first_text
        )

    # --------------------------------------------------------
    # CTA
    # --------------------------------------------------------

    normalized[-1]["text"] = CTA_SIGNATURE
    normalized[-1]["emotion"] = "happy"
    normalized[-1]["visual_query"] = (
        "smiling person thumbs up"
    )

    data["script_principal"] = normalized

    # --------------------------------------------------------
    # SCRIPT TEASER
    # --------------------------------------------------------

    teaser = data.get(
        "script_teaser"
    ) or []

    normalized_teaser = []

    for scene in teaser:

        clean_scene = normalize_scene(
            scene
        )

        if clean_scene:

            normalized_teaser.append(
                clean_scene
            )

    data["script_teaser"] = (
        normalized_teaser
    )

    # --------------------------------------------------------
    # TITRE
    # --------------------------------------------------------

    title = str(
        data.get(
            "title",
            "Pourquoi ton cerveau fait ça"
        )
    ).strip()

    title = re.sub(
        r"\s+",
        " ",
        title
    )

    title = title.strip(
        "\"'"
    )

    if len(title) > 65:

        title = title[:65].rstrip()

    if not title:

        title = (
            "Pourquoi ton cerveau fait ça"
        )

    data["title"] = title

    # --------------------------------------------------------
    # HASHTAGS
    # --------------------------------------------------------

    data["hashtags"] = normalize_hashtags(
        data.get(
            "hashtags",
            []
        )
    )

    if not data["hashtags"]:

        data["hashtags"] = [
            "#Cerveau",
            "#Psychologie",
            "#Science",
            "#CerveauCurieux"
        ]

    # --------------------------------------------------------
    # FORMAT
    # --------------------------------------------------------

    allowed_formats = {
        "short_single",
        "short_twoparts",
        "long_plus_teaser"
    }

    if data.get("format_choisi") not in allowed_formats:

        data["format_choisi"] = "short_single"

    return data


# ============================================================
# APPEL GEMINI
# ============================================================

def call_gemini_script(
    client,
    contents: str
) -> Dict:

    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=ScriptOutput,
            temperature=0.75,
        ),
    )

    parsed = None

    if (
        hasattr(
            response,
            "parsed"
        )
        and response.parsed
    ):

        parsed = response.parsed.model_dump()

    if parsed is None:

        parsed = json.loads(
            response.text
        )

    return validate_and_repair_script(
        parsed
    )


# ============================================================
# RÉPARATION D'UN SHORT TROP COURT EN MOTS
# ============================================================

def expand_short_script(
    client,
    topic: str,
    data: Dict,
    status_cb
) -> Dict:

    scenes = data.get(
        "script_principal",
        []
    )

    word_count = count_words_in_scenes(
        scenes
    )

    if word_count >= SHORT_MIN_WORDS:

        return data

    status_cb(
        "🧠 Script trop court : "
        "ajout d'informations utiles..."
    )

    current_script = "\n".join(
        scene.get(
            "text",
            ""
        )
        for scene in scenes
    )

    repair_prompt = f"""
Le sujet de la vidéo est :

{topic.strip()}

Format actuel :

{data.get("format_choisi", "short_single")}

Voici le script actuel :

{current_script}

Le script contient environ {word_count} mots.

Il est trop court pour une narration de 45 à 60 secondes.

Réécris le script complet pour atteindre environ
{SHORT_TARGET_MIN_WORDS} à {SHORT_TARGET_MAX_WORDS} mots.

IMPORTANT :

N'ajoute absolument aucune phrase de remplissage.

Chaque ajout doit apporter une information réelle.

Tu peux ajouter :

- une explication du mécanisme,
- un exemple concret du quotidien,
- une conséquence,
- une nuance scientifique,
- une comparaison utile,
- un fait complémentaire directement lié.

Ne répète pas les informations déjà présentes.

Conserve ce qui fonctionne déjà dans le hook.

La première scène doit commencer exactement par :

"{INTRO_SIGNATURE}"

La dernière scène doit être exactement :

"{CTA_SIGNATURE}"

Conserve impérativement le format :

{data.get("format_choisi", "short_single")}

Le résultat doit être naturel à l'oral et adapté
à une vidéo de 45 à 60 secondes.

Renvoie le script complet dans le format JSON demandé.
"""

    repaired = call_gemini_script(
        client,
        repair_prompt
    )

    repaired = validate_and_repair_script(
        repaired
    )

    # On force le format d'origine
    repaired["format_choisi"] = data.get(
        "format_choisi",
        "short_single"
    )

    final_words = count_words_in_scenes(
        repaired.get(
            "script_principal",
            []
        )
    )

    if final_words < SHORT_MIN_WORDS:

        raise RuntimeError(
            "Gemini a produit un Short encore "
            "trop court après la réparation."
        )

    return repaired


# ============================================================
# PRÉ-TEST RÉEL DE LA DURÉE TTS
# ============================================================

def preflight_tts_duration(
    scenes: List[Dict],
    status_cb=None
) -> float:

    """
    Génère temporairement les voix de chaque scène
    et mesure leur durée réelle.

    Ce pré-test permet de savoir AVANT Pexels si le script
    produira réellement un Short de 45 à 60 secondes.

    Aucun SFX ni BGM n'est ajouté ici.
    """

    if not scenes:

        return 0.0

    preflight_dir = (
        TEMP_DIR
        / f"preflight_{int(time.time())}_"
        f"{random.randint(1000, 9999)}"
    )

    preflight_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    audio_clips = []

    try:

        for idx, scene in enumerate(
            scenes
        ):

            audio_path = (
                preflight_dir
                / f"tts_{idx:03d}.mp3"
            )

            generate_tts(
                scene.get(
                    "text",
                    ""
                ),
                audio_path
            )

            audio_clips.append(
                audio_path
            )

        concat_file = (
            preflight_dir
            / "concat.txt"
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

        combined_audio = (
            preflight_dir
            / "combined.wav"
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
                "concat.txt",
                "-c:a",
                "pcm_s16le",
                "-ar",
                "48000",
                "-ac",
                "2",
                str(combined_audio)
            ],
            cwd=preflight_dir
        )

        duration = get_media_duration(
            combined_audio
        )

        return duration

    finally:

        shutil.rmtree(
            preflight_dir,
            ignore_errors=True
        )


# ============================================================
# RÉPARATION BASÉE SUR LA DURÉE RÉELLE
# ============================================================

def repair_short_script_for_duration(
    client,
    topic: str,
    data: Dict,
    measured_duration: float,
    status_cb
) -> Dict:

    current_words = count_words_in_scenes(
        data.get(
            "script_principal",
            []
        )
    )

    current_script = "\n".join(
        scene.get(
            "text",
            ""
        )
        for scene in data.get(
            "script_principal",
            []
        )
    )

    # --------------------------------------------------------
    # CAS 1 : TROP COURT
    # --------------------------------------------------------

    if measured_duration < SHORT_PREVIEW_MIN_DURATION:

        status_cb(
            f"⏱️ Voix trop courte ({measured_duration:.1f} s) : "
            "enrichissement du contenu..."
        )

        repair_instruction = f"""
La narration actuelle produit seulement
{measured_duration:.1f} secondes avec Edge-TTS.

Elle contient {current_words} mots.

Elle doit atteindre naturellement entre
45 et 60 secondes.

Réécris le script complet en visant environ
{SHORT_TARGET_MIN_WORDS} à {SHORT_TARGET_MAX_WORDS} mots.

IMPORTANT :

N'ajoute PAS de blabla.

N'ajoute PAS de répétitions.

N'ajoute PAS de phrases vagues.

N'ajoute PAS de phrases destinées uniquement
à augmenter la durée.

Ajoute uniquement des informations utiles au sujet :

- mécanisme scientifique,
- explication plus précise,
- exemple concret,
- conséquence,
- nuance,
- comparaison pertinente,
- fait intéressant directement lié.

Chaque nouvelle phrase doit apprendre quelque chose
ou faire réellement progresser l'explication.

Le sujet est :

{topic.strip()}

Script actuel :

{current_script}

Conserve le hook lorsqu'il est bon.

La première scène doit commencer exactement par :

"{INTRO_SIGNATURE}"

La dernière scène doit être exactement :

"{CTA_SIGNATURE}"

Conserve impérativement le format :

{data.get("format_choisi", "short_single")}

Renvoie le script complet dans le format JSON demandé.
"""

    # --------------------------------------------------------
    # CAS 2 : TROP LONG
    # --------------------------------------------------------

    else:

        status_cb(
            f"⏱️ Voix trop longue ({measured_duration:.1f} s) : "
            "resserrage du contenu..."
        )

        repair_instruction = f"""
La narration actuelle produit
{measured_duration:.1f} secondes avec Edge-TTS.

Elle contient {current_words} mots.

Elle dépasse la durée maximale de 60 secondes.

Réécris le script complet pour obtenir naturellement
environ 47 à 58 secondes.

Vise environ 165 à 180 mots.

IMPORTANT :

Ne supprime pas les informations essentielles.

Supprime en priorité :

- répétitions,
- formulations inutiles,
- transitions trop longues,
- phrases qui n'apportent aucune information.

Conserve :

- le hook,
- les faits importants,
- l'explication scientifique,
- l'exemple concret,
- la nuance utile,
- la conclusion.

Le sujet est :

{topic.strip()}

Script actuel :

{current_script}

La première scène doit commencer exactement par :

"{INTRO_SIGNATURE}"

La dernière scène doit être exactement :

"{CTA_SIGNATURE}"

Conserve impérativement le format :

{data.get("format_choisi", "short_single")}

Renvoie le script complet dans le format JSON demandé.
"""

    repaired = call_gemini_script(
        client,
        repair_instruction
    )

    repaired = validate_and_repair_script(
        repaired
    )

    repaired["format_choisi"] = data.get(
        "format_choisi",
        "short_single"
    )

    return repaired


# ============================================================
# CONTRÔLE COMPLET DU SHORT
# ============================================================

def ensure_short_duration(
    client,
    topic: str,
    data: Dict,
    status_cb
) -> Dict:

    """
    Contrôle en deux niveaux :

    1. nombre de mots,
    2. durée réelle Edge-TTS.

    Si la durée est mauvaise, Gemini réécrit uniquement
    ce qui est nécessaire.

    Maximum :
    2 réparations.
    """

    # --------------------------------------------------------
    # ÉTAPE 1 : CONTRÔLE DES MOTS
    # --------------------------------------------------------

    word_count = count_words_in_scenes(
        data.get(
            "script_principal",
            []
        )
    )

    if word_count < SHORT_MIN_WORDS:

        data = expand_short_script(
            client,
            topic,
            data,
            status_cb
        )

    # --------------------------------------------------------
    # ÉTAPE 2 : MESURE TTS RÉELLE
    # --------------------------------------------------------

    max_repairs = 2

    for attempt in range(
        max_repairs + 1
    ):

        status_cb(
            "🎙️ Test réel de durée de la voix off..."
        )

        duration = preflight_tts_duration(
            data.get(
                "script_principal",
                []
            ),
            status_cb
        )

        words = count_words_in_scenes(
            data.get(
                "script_principal",
                []
            )
        )

        status_cb(
            f"⏱️ Pré-test : {duration:.1f} s "
            f"pour {words} mots"
        )

        # ----------------------------------------------------
        # DURÉE CORRECTE
        # ----------------------------------------------------

        if (
            duration >= SHORT_MIN_DURATION
            and duration <= SHORT_MAX_DURATION
        ):

            status_cb(
                f"✅ Durée validée : "
                f"{duration:.1f} secondes"
            )

            return data

        # ----------------------------------------------------
        # PLUS DE RÉPARATION DISPONIBLE
        # ----------------------------------------------------

        if attempt >= max_repairs:

            if duration < SHORT_MIN_DURATION:

                raise RuntimeError(
                    "Impossible d'obtenir une narration "
                    f"de 45 secondes minimum après "
                    f"{max_repairs} réparations. "
                    f"Dernière durée mesurée : "
                    f"{duration:.1f} s."
                )

            raise RuntimeError(
                "Impossible de ramener la narration "
                "sous 60 secondes après "
                f"{max_repairs} réparations. "
                f"Dernière durée mesurée : "
                f"{duration:.1f} s."
            )

        # ----------------------------------------------------
        # RÉPARATION
        # ----------------------------------------------------

        data = repair_short_script_for_duration(
            client,
            topic,
            data,
            duration,
            status_cb
        )

    return data


# ============================================================
# GÉNÉRATION DU SCRIPT
# ============================================================

def generate_script_gemini(
    topic: str,
    status_cb
) -> Dict:

    if not GEMINI_API_KEY:

        raise RuntimeError(
            "Clé API GEMINI manquante."
        )

    client = genai.Client(
        api_key=GEMINI_API_KEY
    )

    status_cb(
        "🧠 Analyse du sujet et rédaction "
        "du script..."
    )

    try:

        prompt = f"""
Sujet à traiter :

{topic.strip()}

Crée le contenu complet de la vidéo.

IMPORTANT POUR UN SHORT :

Si tu choisis short_single ou short_twoparts,
produis environ {SHORT_TARGET_MIN_WORDS} à
{SHORT_TARGET_MAX_WORDS} mots de narration
dans script_principal.

Minimum :
{SHORT_MIN_WORDS} mots.

Maximum normal :
{SHORT_MAX_WORDS} mots.

La durée visée est de 45 à 60 secondes.

Chaque mot doit servir le contenu.

NE remplis jamais artificiellement la durée.

Si tu as suffisamment de matière pour développer
le sujet, utilise cette place pour :

- expliquer le mécanisme,
- donner un exemple,
- montrer une conséquence,
- apporter une nuance scientifique,
- donner un détail intéressant.

La première scène doit commencer exactement par :

"{INTRO_SIGNATURE}"

La dernière scène doit être exactement :

"{CTA_SIGNATURE}"
"""

        data = call_gemini_script(
            client,
            prompt
        )

        format_choisi = data.get(
            "format_choisi",
            "short_single"
        )

        # ----------------------------------------------------
        # CONTRÔLE SHORT
        # ----------------------------------------------------

        if format_choisi in (
            "short_single",
            "short_twoparts"
        ):

            data = ensure_short_duration(
                client,
                topic,
                data,
                status_cb
            )

        return validate_and_repair_script(
            data
        )

    except Exception as e:

        raise RuntimeError(
            f"Erreur Gemini : {e}"
        )


# ============================================================
# PEXELS
# ============================================================

def clean_pexels_query(
    query: str
) -> str:

    query = re.sub(
        r"[^a-zA-Z\s]",
        "",
        query or ""
    )

    words = [
        w
        for w in query.split()
        if len(w) > 2
    ]

    return " ".join(
        words[:4]
    )


def search_pexels_video(
    query: str,
    orientation: str
) -> Optional[str]:

    if not PEXELS_API_KEY:

        return None

    clean_query = clean_pexels_query(
        query
    )

    if not clean_query:

        clean_query = "human thinking"

    url = (
        "https://api.pexels.com/videos/search"
    )

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

        videos = r.json().get(
            "videos",
            []
        )

        candidates = []

        for video in videos:

            files = [
                f
                for f in video.get(
                    "video_files",
                    []
                )
                if ".mp4" in str(
                    f.get(
                        "link",
                        ""
                    )
                ).lower()
            ]

            for file_info in files:

                width = int(
                    file_info.get(
                        "width",
                        0
                    ) or 0
                )

                height = int(
                    file_info.get(
                        "height",
                        0
                    ) or 0
                )

                link = file_info.get(
                    "link"
                )

                if not link:

                    continue

                if orientation == "portrait":

                    if height < 720:

                        continue

                else:

                    if width < 1280:

                        continue

                score = width * height

                candidates.append(
                    (
                        score,
                        link
                    )
                )

        if not candidates:

            return None

        candidates.sort(
            key=lambda x: x[0],
            reverse=True
        )

        top = candidates[
            :min(
                5,
                len(candidates)
            )
        ]

        return random.choice(
            top
        )[1]

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
            timeout=30
        ) as r:

            r.raise_for_status()

            with open(
                dest,
                "wb"
            ) as f:

                for chunk in r.iter_content(
                    chunk_size=64 * 1024
                ):

                    if chunk:

                        f.write(
                            chunk
                        )

        return (
            dest.exists()
            and dest.stat().st_size > 10000
        )

    except Exception:

        return False


# ============================================================
# SOUS-TITRES ASS
# ============================================================

def ass_time(
    seconds: float
) -> str:

    seconds = max(
        0.0,
        seconds
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

    centiseconds = int(
        (
            seconds
            - int(seconds)
        ) * 100
    )

    return (
        f"{hours}:"
        f"{minutes:02d}:"
        f"{secs:02d}."
        f"{centiseconds:02d}"
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
            scene.get(
                "duration",
                0
            )
        )

        text = (
            str(
                scene.get(
                    "text",
                    ""
                )
            )
            .replace(
                "\n",
                " "
            )
            .replace(
                "{",
                ""
            )
            .replace(
                "}",
                ""
            )
            .strip()
        )

        words = text.split()

        if not words:

            current_time += scene_duration

            continue

        chunk_size = (
            4
            if width == 1080
            else 5
        )

        chunks = [
            words[i:i + chunk_size]
            for i in range(
                0,
                len(words),
                chunk_size
            )
        ]

        chunk_duration = (
            scene_duration
            / len(chunks)
        )

        for idx_chunk, chunk_words in enumerate(
            chunks
        ):

            chunk_start = (
                current_time
                + idx_chunk
                * chunk_duration
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
                    + idx_word
                    * word_duration
                )

                end_t = (
                    start_t
                    + word_duration
                )

                formatted_words = []

                for k, w in enumerate(
                    chunk_words
                ):

                    safe_word = (
                        w
                        .replace(
                            ",",
                            ""
                        )
                        .replace(
                            ".",
                            ""
                        )
                        .replace(
                            "?",
                            ""
                        )
                        .replace(
                            "!",
                            ""
                        )
                    )

                    if k == idx_word:

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
        / f"audio_{idx:03d}.wav"
    )

    generate_tts(
        scene["text"],
        temp_audio
    )

    is_last = (
        idx == total_scenes - 1
    )

    sfx_to_use = None

    if (
        is_last
        and CLICK_SFX_FILE.exists()
    ):

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
            "-c:a",
            "pcm_s16le",
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
            "-c:a",
            "pcm_s16le",
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
        work_dir
        / "concat_audio.txt"
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
        work_dir
        / "raw_audio.wav"
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
        work_dir
        / "full_audio.m4a"
    )

    if not BGM_FILE.exists():

        run_command(
            [
                FFMPEG_BIN,
                "-y",
                "-i",
                str(voice_audio),
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-ar",
                "48000",
                "-ac",
                "2",
                str(output)
            ],
            cwd=work_dir
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

def create_video_clip_from_pexels(
    visual_file: Path,
    mascot_img: Path,
    output_clip: Path,
    duration: float,
    width: int,
    height: int,
    mascot_scale: int,
    pos_x: str,
    pos_y: str,
    enable_expr: str,
    work_dir: Path
):

    fps = 30

    # --------------------------------------------------------
    # VRAI CLIP VIDÉO PEXELS
    # --------------------------------------------------------

    base_filter = (
        f"[0:v]"
        f"scale={width}:{height}:"
        "force_original_aspect_ratio=increase,"
        f"crop={width}:{height},"
        f"fps={fps},"
        "setsar=1"
        "[bg]"
    )

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
        str(mascot_img.resolve()),
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

    run_command(
        cmd,
        cwd=work_dir
    )


def create_fallback_video_clip(
    output_clip: Path,
    mascot_img: Path,
    duration: float,
    width: int,
    height: int,
    mascot_scale: int,
    pos_x: str,
    pos_y: str,
    enable_expr: str,
    work_dir: Path
):

    fallback = (
        work_dir
        / f"fallback_{output_clip.stem}.png"
    )

    Image.new(
        "RGB",
        (width, height),
        color=(20, 20, 35)
    ).save(
        fallback
    )

    fps = 30

    filter_complex = (
        f"[0:v]"
        "scale="
        f"{width}:{height},"
        f"fps={fps},"
        "setsar=1"
        "[bg];"
        f"[1:v]"
        f"scale={mascot_scale}:-1,"
        "format=rgba"
        "[mascot];"
        f"[bg][mascot]"
        f"overlay=x={pos_x}:y={pos_y}:"
        f"enable='{enable_expr}'"
        "[v_out]"
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
        str(mascot_img.resolve()),
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

    run_command(
        cmd,
        cwd=work_dir
    )


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
        / f"run_{int(time.time())}_"
        f"{video_format}_{random.randint(1000, 9999)}"
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

    total_scenes = len(
        script_scenes
    )

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

    voice_duration = get_media_duration(
        full_audio
    )

    # --------------------------------------------------------
    # CONTRÔLE DURÉE SHORT
    # --------------------------------------------------------

    if video_format == "portrait":

        if voice_duration < SHORT_MIN_DURATION:

            raise RuntimeError(
                "Le contrôle audio a détecté une durée "
                f"inférieure à 45 secondes "
                f"({voice_duration:.1f} s). "
                "Le script aurait dû être réparé "
                "avant le téléchargement des clips."
            )

        if voice_duration > SHORT_MAX_DURATION:

            raise RuntimeError(
                "Le contrôle audio a détecté une durée "
                f"supérieure à 60 secondes "
                f"({voice_duration:.1f} s). "
                "Le script aurait dû être raccourci "
                "avant le téléchargement des clips."
            )

    # --------------------------------------------------------
    # VIDÉOS PEXELS
    # --------------------------------------------------------

    status_cb(
        "🎥 Recherche des clips vidéo Pexels..."
    )

    video_clips = []

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
            scene.get(
                "duration",
                1.0
            )
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

            mascot_img = (
                MASCOT_FILES["default"]
            )

        status_cb(
            f"🎬 Clip {idx + 1}/{total_scenes} : "
            f"{scene.get('visual_query', '')}"
        )

        url = search_pexels_video(
            scene.get(
                "visual_query",
                "person thinking"
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

        pos_x, pos_y = mascot_positions[
            idx % len(
                mascot_positions
            )
        ]

        mascot_duration = min(
            2.5,
            duration
        )

        enable_expr = (
            f"between(t,0,{mascot_duration})"
        )

        if (
            url
            and download_file(
                url,
                visual_file
            )
        ):

            create_video_clip_from_pexels(
                visual_file=visual_file,
                mascot_img=mascot_img,
                output_clip=output_clip,
                duration=duration,
                width=width,
                height=height,
                mascot_scale=mascot_scale,
                pos_x=pos_x,
                pos_y=pos_y,
                enable_expr=enable_expr,
                work_dir=work_dir
            )

        else:

            # Fallback uniquement si Pexels ne fournit
            # aucun clip exploitable.
            create_fallback_video_clip(
                output_clip=output_clip,
                mascot_img=mascot_img,
                duration=duration,
                width=width,
                height=height,
                mascot_scale=mascot_scale,
                pos_x=pos_x,
                pos_y=pos_y,
                enable_expr=enable_expr,
                work_dir=work_dir
            )

        video_clips.append(
            output_clip
        )

    # --------------------------------------------------------
    # CONCATÉNATION VIDÉO
    # --------------------------------------------------------

    status_cb(
        "⚡ Fusion des scènes vidéo..."
    )

    raw_video = (
        work_dir
        / "raw_video.mp4"
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
        work_dir
        / "subtitles.ass"
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
        str(
            final_output.resolve()
        )
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

    final_duration = qc_validate_video(
        final_output,
        expected_format=(
            "portrait"
            if video_format == "portrait"
            else "landscape"
        )
    )

    # --------------------------------------------------------
    # CONTRÔLE FINAL SHORT
    # --------------------------------------------------------

    if video_format == "portrait":

        if final_duration < SHORT_MIN_DURATION:

            raise RuntimeError(
                "QC Échec : le Short final fait "
                f"{final_duration:.1f} secondes. "
                "Minimum demandé : 45 secondes."
            )

        if final_duration > SHORT_MAX_DURATION:

            raise RuntimeError(
                "QC Échec : le Short final fait "
                f"{final_duration:.1f} secondes. "
                "Maximum demandé : 60 secondes."
            )

    return final_output


# ============================================================
# DÉCOUPAGE EN DEUX PARTIES
# ============================================================

def split_video_in_two(
    input_video: Path,
    total_duration: float,
    out_dir: Path
) -> Tuple[Path, Path]:

    mid_point = (
        total_duration / 2.0
    )

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
            "-movflags",
            "+faststart",
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
            "-movflags",
            "+faststart",
            str(part2)
        ]
    )

    return (
        part1,
        part2
    )


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

    # ========================================================
    # SIDEBAR
    # ========================================================

    with st.sidebar:

        st.markdown(
            "<h3 style='text-align:center;'>"
            "Tableau de bord"
            "</h3>",
            unsafe_allow_html=True
        )

        if MASCOT_FILES[
            "default"
        ].exists():

            st.image(
                str(
                    MASCOT_FILES[
                        "default"
                    ]
                ),
                use_container_width=True
            )

        st.markdown("---")

        st.markdown(
            "🎯 **Mode Autonome Actif**"
        )

        st.write(
            "Pipeline Gemini + Edge-TTS + "
            "Pexels Video + FFmpeg."
        )

        st.markdown("---")

        st.caption(
            "Signature : Wesh l'équipe"
        )

        st.caption(
            "CTA : signature Cerveau Curieux"
        )

        st.caption(
            "Short : 45 à 60 secondes"
        )

        st.caption(
            "Cible script : 165 à 180 mots"
        )

    # ========================================================
    # HEADER
    # ========================================================

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

    # ========================================================
    # SUJET
    # ========================================================

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
                "⚠️ Oups ! Tu as oublié "
                "d'écrire un sujet."
            )

            return

        with st.status(
            "🎬 Allumage des caméras virtuelles...",
            expanded=True
        ) as status_box:

            try:

                def update_status(msg):
                    st.write(msg)

                # --------------------------------------------
                # SCRIPT
                # --------------------------------------------

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

                word_count = count_words_in_scenes(
                    ai_data.get(
                        "script_principal",
                        []
                    )
                )

                st.write(
                    "✅ Format défini : "
                    f"**{format_choisi.replace('_', ' ').title()}**"
                )

                st.write(
                    f"📝 Narration : **{word_count} mots**"
                )

                # --------------------------------------------
                # VIDÉO
                # --------------------------------------------

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
                        "✂️ Découpage de la vidéo "
                        "en 2 parties..."
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

                    teaser_scenes = ai_data.get(
                        "script_teaser",
                        []
                    )

                    if not teaser_scenes:

                        raise RuntimeError(
                            "Le teaser est vide."
                        )

                    # ----------------------------------------
                    # CONTRÔLE DU TEASER
                    # ----------------------------------------

                    teaser_words = count_words_in_scenes(
                        teaser_scenes
                    )

                    if teaser_words < SHORT_MIN_WORDS:

                        raise RuntimeError(
                            "Le teaser Short est trop court "
                            f"({teaser_words} mots)."
                        )

                    short_path = (
                        generate_video_pipeline(
                            teaser_scenes,
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
                        f"Format inconnu : "
                        f"{format_choisi}"
                    )

                status_box.update(
                    label=(
                        "🎉 Production terminée "
                        "avec succès !"
                    ),
                    state="complete",
                    expanded=False
                )

            except Exception as e:

                status_box.update(
                    label=(
                        "❌ Oups, une erreur "
                        "s'est produite."
                    ),
                    state="error",
                    expanded=True
                )

                st.error(
                    str(e)
                )

                return

        # ====================================================
        # RÉSULTATS
        # ====================================================

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

        # ====================================================
        # INFORMATIONS
        # ====================================================

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
                "Le script est contrôlé avec la durée "
                "réelle d'Edge-TTS avant la recherche "
                "des clips Pexels. Aucun remplissage "
                "artificiel n'est ajouté."
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

        # ====================================================
        # VIDÉOS
        # ====================================================

        with video_tab:

            if format_choisi == "short_single":

                final_duration = (
                    get_media_duration(
                        video_path
                    )
                )

                st.success(
                    f"Durée finale : "
                    f"**{final_duration:.1f} secondes**"
                )

                st.video(
                    str(video_path)
                )

                with open(
                    video_path,
                    "rb"
                ) as video_file:

                    video_bytes = (
                        video_file.read()
                    )

                st.download_button(
                    "⬇️ Télécharger la vidéo",
                    data=video_bytes,
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
                        str(
                            video_path[0]
                        )
                    )

                    with open(
                        video_path[0],
                        "rb"
                    ) as f:

                        part1_bytes = f.read()

                    st.download_button(
                        "⬇️ Partie 1",
                        data=part1_bytes,
                        file_name=video_path[0].name,
                        mime="video/mp4"
                    )

                with col2:

                    st.caption(
                        "Partie 2"
                    )

                    st.video(
                        str(
                            video_path[1]
                        )
                    )

                    with open(
                        video_path[1],
                        "rb"
                    ) as f:

                        part2_bytes = f.read()

                    st.download_button(
                        "⬇️ Partie 2",
                        data=part2_bytes,
                        file_name=video_path[1].name,
                        mime="video/mp4"
                    )

            elif format_choisi == "long_plus_teaser":

                st.subheader(
                    "📺 Format Long (16:9)"
                )

                long_duration = (
                    get_media_duration(
                        video_path[0]
                    )
                )

                st.caption(
                    f"Durée : "
                    f"{long_duration:.1f} secondes"
                )

                st.video(
                    str(
                        video_path[0]
                    )
                )

                with open(
                    video_path[0],
                    "rb"
                ) as f:

                    long_bytes = f.read()

                st.download_button(
                    "⬇️ Télécharger la vidéo longue",
                    data=long_bytes,
                    file_name=video_path[0].name,
                    mime="video/mp4"
                )

                st.divider()

                st.subheader(
                    "📱 Teaser Short (9:16)"
                )

                teaser_duration = (
                    get_media_duration(
                        video_path[1]
                    )
                )

                st.caption(
                    f"Durée : "
                    f"{teaser_duration:.1f} secondes"
                )

                st.video(
                    str(
                        video_path[1]
                    )
                )

                with open(
                    video_path[1],
                    "rb"
                ) as f:

                    teaser_bytes = f.read()

                st.download_button(
                    "⬇️ Télécharger le teaser",
                    data=teaser_bytes,
                    file_name=video_path[1].name,
                    mime="video/mp4"
                )

        st.balloons()


if __name__ == "__main__":
    main()
            
