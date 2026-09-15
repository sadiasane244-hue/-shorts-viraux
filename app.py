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

def get_secret(name: str) -> str:
    value = os.environ.get(name, "")

    if value:
        return value

    try:
        value = st.secrets.get(name, "")
    except Exception:
        value = ""

    return value or ""


PEXELS_API_KEY = get_secret("PEXELS_API_KEY")
GEMINI_API_KEY = get_secret("GEMINI_API_KEY")


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
# DURÉE DES SHORTS
# ============================================================

# IMPORTANT :
# Le Short doit faire PLUS de 45 secondes.
# Il n'y a plus de limite stricte à 60 secondes.
#
# 90 secondes = limite de sécurité.
#
# On vise volontairement une zone confortable entre
# environ 50 et 75 secondes, sans jamais remplir artificiellement.

SHORT_MIN_DURATION = 45.1
SHORT_TARGET_MIN_DURATION = 50.0
SHORT_TARGET_MAX_DURATION = 75.0
SHORT_MAX_DURATION = 90.0

SHORT_MIN_WORDS = 135
SHORT_TARGET_MIN_WORDS = 150
SHORT_TARGET_MAX_WORDS = 180
SHORT_MAX_WORDS = 200


# ============================================================
# FICHIERS AUDIO OPTIONNELS
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
# EXCEPTIONS SPÉCIALES
# ============================================================

class ShortTooShortError(RuntimeError):
    pass


class ShortTooLongError(RuntimeError):
    pass


# ============================================================
# SCHÉMA JSON GEMINI
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
            "décrivant une action physique concrète "
            "facile à trouver sous forme de vidéo Pexels."
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
            "Scènes principales. Pour un Short, viser "
            "150 à 180 mots réellement informatifs."
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

    try:
        items = list(TEMP_DIR.iterdir())
    except Exception:
        return

    for item in items:

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
            f"Erreur: {e.stderr[-3000:]}"
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


def get_script_text(
    scenes: List[Dict]
) -> str:

    return " ".join(
        str(
            scene.get(
                "text",
                ""
            )
        ).strip()
        for scene in scenes or []
        if str(
            scene.get(
                "text",
                ""
            )
        ).strip()
    )


# ============================================================
# QC VIDÉO
# ============================================================

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
# TTS
# ============================================================

def fix_phonetics_for_tts(
    text: str
) -> str:

    # IMPORTANT :
    # On ne remplace plus "buguer" par "beuguer".
    # Le CTA affiché et prononcé reste fidèle au texte demandé.

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
# PROMPT GEMINI
# ============================================================

SYSTEM_PROMPT = f"""
Tu es le réalisateur et scénariste de la chaîne
YouTube/TikTok "Cerveau Curieux".

OBJECTIF :
Créer des vidéos modernes, dynamiques, documentées
et réellement intéressantes sur le cerveau,
la psychologie, les sciences et les comportements humains.

============================================================
IDENTITÉ DE MARQUE
============================================================

La première scène DOIT commencer exactement par :

"{INTRO_SIGNATURE}"

Après cette phrase, enchaîne immédiatement avec
un hook fort lié au sujet.

Ne fais PAS de présentation longue.

Ne dis PAS :
"Bienvenue sur la chaîne."

============================================================
STYLE
============================================================

- Tutoiement.
- Ton moderne, jeune, naturel.
- Le texte doit sonner comme une vraie personne.
- Expressions naturelles possibles :
  "frérot", "ton cerveau", "ça paraît bizarre", etc.
- Pas d'insulte.
- Pas de vulgarité.
- Pas de langage artificiellement jeune.
- Aucune phrase inutile.

============================================================
RIGUEUR SCIENTIFIQUE
============================================================

- Ne jamais inventer un fait.
- Ne jamais inventer une expérience.
- Ne jamais inventer un chiffre.
- Ne jamais présenter une hypothèse comme une certitude.
- Expliquer simplement les nuances importantes.

============================================================
DURÉE DES SHORTS
============================================================

ATTENTION :

Le Short doit durer PLUS DE 45 secondes.

Il n'est PAS limité à 60 secondes.

Une durée allant jusqu'à 90 secondes est autorisée.

ZONE IDÉALE :
environ 50 à 75 secondes.

Le script doit généralement contenir
environ 150 à 180 mots.

Il peut aller jusqu'à environ 200 mots si le sujet
nécessite réellement plus d'explications.

NE JAMAIS remplir la durée artificiellement.

Chaque phrase doit apporter une vraie information :

- fait,
- mécanisme,
- exemple,
- conséquence,
- nuance,
- explication,
- comparaison utile,
- transition nécessaire.

INTERDIT :

"Et c'est incroyable."
"Mais attends, c'est fou."
"Tu vas halluciner."

si ces phrases n'apportent aucune information.

Si le sujet permet d'expliquer davantage,
utilise cette place pour apporter du contenu utile.

============================================================
STRUCTURE SHORT
============================================================

1. Signature.
2. Hook.
3. Présentation du phénomène.
4. Explication.
5. Exemple concret.
6. Détail surprenant.
7. Conséquence.
8. Nuance scientifique si nécessaire.
9. Conclusion.
10. CTA.

============================================================
SCÈNES
============================================================

Une scène = une unité naturelle de narration.

Les scènes doivent être suffisamment courtes
pour permettre un montage dynamique.

Ne découpe PAS artificiellement une phrase
simplement pour augmenter le nombre de scènes.

============================================================
CTA
============================================================

La dernière scène DOIT être exactement :

"{CTA_SIGNATURE}"

Ne modifie aucun mot.

============================================================
TITRE
============================================================

Maximum 65 caractères.

Accrocheur mais honnête.

Directement lié au sujet.

Pas de clickbait mensonger.

============================================================
HASHTAGS
============================================================

4 à 6 hashtags ciblés.

Priorité :

- sujet précis,
- science,
- psychologie,
- cerveau,
- comportement humain.

============================================================
PEXELS
============================================================

Les visuels seront de VRAIES VIDÉOS Pexels.

Chaque visual_query doit être :

- en anglais,
- 2 à 4 mots,
- concret,
- facile à rechercher en vidéo.

Exemples :

"person opening door"
"confused man thinking"
"woman checking phone"
"brain scan closeup"
"student studying desk"
"person forgetting keys"

Éviter les concepts abstraits.

============================================================
RÈGLE ABSOLUE
============================================================

Une vidéo plus longue doit être plus riche,
pas simplement plus bavarde.
"""


# ============================================================
# HASHTAGS
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
# PEXELS QUERY
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


# ============================================================
# NORMALISATION SCÈNES
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
# VALIDATION SCRIPT
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
            "Le script Gemini est vide."
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
    # TEASER
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

    data["script_teaser"] = normalized_teaser

    # --------------------------------------------------------
    # FORMAT
    # --------------------------------------------------------

    allowed_formats = {
        "short_single",
        "short_twoparts",
        "long_plus_teaser"
    }

    if data.get(
        "format_choisi"
    ) not in allowed_formats:

        data["format_choisi"] = "short_single"

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
# RÉPARATION PAR NOMBRE DE MOTS
# ============================================================

def repair_script_by_words(
    client,
    topic: str,
    data: Dict,
    status_cb,
    too_short: bool
) -> Dict:

    scenes = data.get(
        "script_principal",
        []
    )

    word_count = count_words_in_scenes(
        scenes
    )

    current_script = "\n".join(
        scene.get(
            "text",
            ""
        )
        for scene in scenes
    )

    if too_short:

        instruction = f"""
Le script est trop court.

Il contient actuellement environ {word_count} mots.

Réécris-le pour atteindre environ
{SHORT_TARGET_MIN_WORDS} à {SHORT_TARGET_MAX_WORDS} mots.

Ajoute uniquement des informations utiles :

- mécanisme scientifique,
- exemple concret,
- conséquence,
- détail intéressant,
- nuance scientifique,
- explication supplémentaire.

Aucune phrase de remplissage.
Aucune répétition.
"""

    else:

        instruction = f"""
Le script est trop long.

Il contient actuellement environ {word_count} mots.

Réduis-le vers environ
{SHORT_TARGET_MIN_WORDS} à {SHORT_TARGET_MAX_WORDS} mots.

Supprime uniquement les répétitions,
digressions et formulations inutiles.

Conserve les informations importantes.
Ne supprime pas les explications essentielles.
"""

    prompt = f"""
Le sujet est :

{topic.strip()}

Voici le script actuel :

{current_script}

{instruction}

Le résultat doit rester naturel à l'oral.

La première scène DOIT commencer exactement par :

"{INTRO_SIGNATURE}"

La dernière scène DOIT être exactement :

"{CTA_SIGNATURE}"

Conserve le format actuel :

{data.get("format_choisi", "short_single")}

Renvoie le script complet au format JSON demandé.
"""

    status_cb(
        "🧠 Ajustement du contenu avec Gemini..."
    )

    repaired = call_gemini_script(
        client,
        prompt
    )

    repaired["format_choisi"] = data.get(
        "format_choisi",
        repaired.get(
            "format_choisi",
            "short_single"
        )
    )

    return validate_and_repair_script(
        repaired
    )


# ============================================================
# GÉNÉRATION SCRIPT
# ============================================================

def generate_script_gemini(
    topic: str,
    status_cb
) -> Tuple[Dict, object]:

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

    prompt = f"""
Sujet à traiter :

{topic.strip()}

Crée le contenu complet de la vidéo.

Pour un Short :

- vise {SHORT_TARGET_MIN_WORDS} à
  {SHORT_TARGET_MAX_WORDS} mots,
- minimum conseillé : {SHORT_MIN_WORDS},
- maximum normal : {SHORT_MAX_WORDS},
- durée recherchée : plus de 45 secondes,
- durée maximale autorisée : 90 secondes.

La zone idéale est environ 50 à 75 secondes.

NE REMPLIS PAS avec du blabla.

Chaque phrase doit apporter une information réelle.

La première scène doit commencer exactement par :

"{INTRO_SIGNATURE}"

La dernière scène doit être exactement :

"{CTA_SIGNATURE}"
"""

    try:

        data = call_gemini_script(
            client,
            prompt
        )

        format_choisi = data.get(
            "format_choisi",
            "short_single"
        )

        if format_choisi in (
            "short_single",
            "short_twoparts"
        ):

            word_count = count_words_in_scenes(
                data.get(
                    "script_principal",
                    []
                )
            )

            if word_count < SHORT_MIN_WORDS:

                data = repair_script_by_words(
                    client,
                    topic,
                    data,
                    status_cb,
                    too_short=True
                )

            elif word_count > SHORT_MAX_WORDS:

                data = repair_script_by_words(
                    client,
                    topic,
                    data,
                    status_cb,
                    too_short=False
                )

        return (
            validate_and_repair_script(data),
            client
        )

    except Exception as e:

        raise RuntimeError(
            f"Erreur Gemini : {e}"
        )


# ============================================================
# RÉPARATION APRÈS MESURE AUDIO RÉELLE
# ============================================================

def repair_script_by_real_duration(
    client,
    topic: str,
    data: Dict,
    measured_duration: float,
    status_cb
) -> Dict:

    scenes = data.get(
        "script_principal",
        []
    )

    current_script = "\n".join(
        scene.get(
            "text",
            ""
        )
        for scene in scenes
    )

    if measured_duration < SHORT_MIN_DURATION:

        status_cb(
            f"⏱️ Durée réelle trop courte "
            f"({measured_duration:.1f} s). "
            "Ajout d'informations utiles..."
        )

        prompt = f"""
Sujet :

{topic.strip()}

Le script actuel produit seulement
{measured_duration:.1f} secondes avec la vraie voix off.

Il faut dépasser 45 secondes.

Réécris le script pour viser environ
55 à 70 secondes de narration réelle.

SCRIPT ACTUEL :

{current_script}

IMPORTANT :

N'ajoute aucun remplissage.

Ajoute seulement de vraies informations
directement liées au sujet :

- mécanisme,
- explication,
- exemple concret,
- conséquence,
- nuance,
- fait scientifique pertinent.

Ne répète pas ce qui est déjà dit.

La vidéo doit devenir plus intéressante,
pas simplement plus longue.

Première scène :

"{INTRO_SIGNATURE}"

Dernière scène :

"{CTA_SIGNATURE}"

Conserve le format :

{data.get("format_choisi", "short_single")}

Renvoie le script complet.
"""

    else:

        status_cb(
            f"⏱️ Durée réelle trop longue "
            f"({measured_duration:.1f} s). "
            "Resserrement du contenu..."
        )

        prompt = f"""
Sujet :

{topic.strip()}

Le script actuel produit
{measured_duration:.1f} secondes.

La limite maximale est de 90 secondes.

Resserre le script pour viser environ
55 à 75 secondes.

Supprime :

- répétitions,
- phrases secondaires,
- formulations trop longues,
- digressions.

Conserve :

- le hook,
- les faits importants,
- les explications,
- les exemples utiles,
- les nuances scientifiques.

Ne détruis pas la logique du raisonnement.

SCRIPT ACTUEL :

{current_script}

Première scène :

"{INTRO_SIGNATURE}"

Dernière scène :

"{CTA_SIGNATURE}"

Conserve le format :

{data.get("format_choisi", "short_single")}

Renvoie le script complet.
"""

    repaired = call_gemini_script(
        client,
        prompt
    )

    repaired["format_choisi"] = data.get(
        "format_choisi",
        repaired.get(
            "format_choisi",
            "short_single"
        )
    )

    return validate_and_repair_script(
        repaired
    )


# ============================================================
# PEXELS
# ============================================================

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
                        .replace(",", "")
                        .replace(".", "")
                        .replace("?", "")
                        .replace("!", "")
                        .replace(";", "")
                        .replace(":", "")
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
# AUDIO PAR SCÈNE
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

    processed_audio = (
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

    # ========================================================
    # IMPORTANT
    # ========================================================
    #
    # AVANT :
    #
    # silenceremove supprimait les silences de CHAQUE scène.
    #
    # Comme chaque phrase était un fichier séparé, ces petites
    # suppressions s'additionnaient et pouvaient faire perdre
    # beaucoup de secondes par rapport au pré-test.
    #
    # MAINTENANT :
    #
    # On conserve la durée réelle produite par Edge-TTS.
    # On normalise seulement le niveau audio.
    #
    # Cela rend la mesure de durée beaucoup plus fiable.
    # ========================================================

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
                "[1:a]"
                "volume=0.16"
                "[sfx];"
                "[0:a][sfx]"
                "amix=inputs=2:"
                "duration=first:"
                "dropout_transition=0,"
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
            str(processed_audio)
        ]

        run_command(
            cmd_mix,
            cwd=work_dir
        )

    else:

        cmd_normalize = [
            FFMPEG_BIN,
            "-y",
            "-i",
            str(temp_audio),
            "-af",
            (
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
            str(processed_audio)
        ]

        run_command(
            cmd_normalize,
            cwd=work_dir
        )

    scene["duration"] = get_media_duration(
        processed_audio
    )

    return processed_audio


# ============================================================
# CONCATÉNATION AUDIO
# ============================================================

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
            "dropout_transition=2"
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
# VIDÉO PEXELS
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


# ============================================================
# PIPELINE VIDÉO
# ============================================================

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

    # ========================================================
    # AUDIO
    # ========================================================

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

    status_cb(
        f"⏱️ Durée audio réelle : "
        f"{voice_duration:.1f} secondes"
    )

    # ========================================================
    # CONTRÔLE DURÉE SHORT
    # ========================================================

    if video_format == "portrait":

        if voice_duration <= SHORT_MIN_DURATION:

            raise ShortTooShortError(
                "Le script audio réel fait seulement "
                f"{voice_duration:.1f} secondes. "
                f"Il faut dépasser {SHORT_MIN_DURATION:.1f} secondes."
            )

        if voice_duration > SHORT_MAX_DURATION:

            raise ShortTooLongError(
                "Le script audio réel fait "
                f"{voice_duration:.1f} secondes. "
                f"La limite de sécurité est {SHORT_MAX_DURATION:.0f} secondes."
            )

        status_cb(
            f"✅ Durée validée : "
            f"{voice_duration:.1f} secondes"
        )

    # ========================================================
    # RECHERCHE PEXELS
    # ========================================================

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

    # ========================================================
    # CONCATÉNATION VIDÉO
    # ========================================================

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
                "raw_video.mp4"
            ],
            cwd=work_dir
        )

    # ========================================================
    # SOUS-TITRES
    # ========================================================

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

    # ========================================================
    # EXPORT FINAL
    # ========================================================

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

    # ========================================================
    # QC FINAL
    # ========================================================

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

    if video_format == "portrait":

        if final_duration <= SHORT_MIN_DURATION:

            raise ShortTooShortError(
                "QC Échec : le Short final fait "
                f"{final_duration:.1f} secondes."
            )

        if final_duration > SHORT_MAX_DURATION:

            raise ShortTooLongError(
                "QC Échec : le Short final fait "
                f"{final_duration:.1f} secondes."
            )

    status_cb(
        f"✅ Vidéo finale validée : "
        f"{final_duration:.1f} secondes"
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
# SESSION STATE
# ============================================================

def initialize_session_state():

    defaults = {
        "generation_done": False,
        "ai_data": None,
        "format_choisi": None,
        "title": None,
        "video_path": None,
        "topic_generated": "",
    }

    for key, value in defaults.items():

        if key not in st.session_state:

            st.session_state[key] = value


def save_generation_result(
    ai_data: Dict,
    format_choisi: str,
    video_path,
    topic: str
):

    st.session_state.generation_done = True
    st.session_state.ai_data = ai_data
    st.session_state.format_choisi = format_choisi
    st.session_state.title = ai_data.get(
        "title",
        "Pourquoi ton cerveau fait ça"
    )
    st.session_state.video_path = video_path
    st.session_state.topic_generated = topic


def clear_generation_result():

    st.session_state.generation_done = False
    st.session_state.ai_data = None
    st.session_state.format_choisi = None
    st.session_state.title = None
    st.session_state.video_path = None
    st.session_state.topic_generated = ""


# ============================================================
# AFFICHAGE DES RÉSULTATS
# ============================================================

def render_results():

    if not st.session_state.get(
        "generation_done",
        False
    ):
        return

    ai_data = st.session_state.ai_data
    format_choisi = st.session_state.format_choisi
    video_path = st.session_state.video_path
    title = st.session_state.title

    if not ai_data or not video_path:
        return

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

    # ========================================================
    # INFORMATIONS
    # ========================================================

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

        word_count = count_words_in_scenes(
            ai_data.get(
                "script_principal",
                []
            )
        )

        st.write(
            f"📝 **Narration : {word_count} mots**"
        )

        st.caption(
            "Le Short doit dépasser 45 secondes. "
            "La limite de sécurité est de 90 secondes. "
            "Aucun remplissage artificiel n'est ajouté."
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

    # ========================================================
    # VIDÉOS
    # ========================================================

    with video_tab:

        if format_choisi == "short_single":

            video_file = Path(
                str(video_path)
            )

            if not video_file.exists():

                st.error(
                    "Le fichier vidéo n'est plus "
                    "disponible sur le serveur."
                )

                return

            final_duration = get_media_duration(
                video_file
            )

            st.success(
                f"Durée finale : "
                f"**{final_duration:.1f} secondes**"
            )

            st.video(
                str(video_file)
            )

            # ------------------------------------------------
            # IMPORTANT
            # ------------------------------------------------
            # on_click="ignore" empêche Streamlit de relancer
            # l'application lorsqu'on clique sur Télécharger.
            # ------------------------------------------------

            with open(
                video_file,
                "rb"
            ) as video_file_handle:

                video_bytes = (
                    video_file_handle.read()
                )

            st.download_button(
                "⬇️ Télécharger la vidéo",
                data=video_bytes,
                file_name=video_file.name,
                mime="video/mp4",
                on_click="ignore",
                key="download_short_single",
                type="primary",
                use_container_width=True
            )

        elif format_choisi == "short_twoparts":

            paths = [
                Path(str(x))
                for x in video_path
            ]

            if len(paths) < 2:
                st.error(
                    "Les deux parties de la vidéo "
                    "ne sont plus disponibles."
                )
                return

            col1, col2 = st.columns(2)

            with col1:

                st.caption(
                    "Partie 1"
                )

                st.video(
                    str(paths[0])
                )

                if paths[0].exists():

                    with open(
                        paths[0],
                        "rb"
                    ) as f:

                        part1_bytes = f.read()

                    st.download_button(
                        "⬇️ Partie 1",
                        data=part1_bytes,
                        file_name=paths[0].name,
                        mime="video/mp4",
                        on_click="ignore",
                        key="download_part1",
                        use_container_width=True
                    )

            with col2:

                st.caption(
                    "Partie 2"
                )

                st.video(
                    str(paths[1])
                )

                if paths[1].exists():

                    with open(
                        paths[1],
                        "rb"
                    ) as f:

                        part2_bytes = f.read()

                    st.download_button(
                        "⬇️ Partie 2",
                        data=part2_bytes,
                        file_name=paths[1].name,
                        mime="video/mp4",
                        on_click="ignore",
                        key="download_part2",
                        use_container_width=True
                    )

        elif format_choisi == "long_plus_teaser":

            paths = [
                Path(str(x))
                for x in video_path
            ]

            if len(paths) < 2:

                st.error(
                    "Les fichiers vidéo ne sont plus "
                    "disponibles."
                )

                return

            # ------------------------------------------------
            # LONG
            # ------------------------------------------------

            st.subheader(
                "📺 Format Long (16:9)"
            )

            long_duration = get_media_duration(
                paths[0]
            )

            st.caption(
                f"Durée : "
                f"{long_duration:.1f} secondes"
            )

            st.video(
                str(paths[0])
            )

            if paths[0].exists():

                with open(
                    paths[0],
                    "rb"
                ) as f:

                    long_bytes = f.read()

                st.download_button(
                    "⬇️ Télécharger la vidéo longue",
                    data=long_bytes,
                    file_name=paths[0].name,
                    mime="video/mp4",
                    on_click="ignore",
                    key="download_long_video",
                    type="primary",
                    use_container_width=True
                )

            st.divider()

            # ------------------------------------------------
            # TEASER
            # ------------------------------------------------

            st.subheader(
                "📱 Teaser Short (9:16)"
            )

            teaser_duration = get_media_duration(
                paths[1]
            )

            st.caption(
                f"Durée : "
                f"{teaser_duration:.1f} secondes"
            )

            st.video(
                str(paths[1])
            )

            if paths[1].exists():

                with open(
                    paths[1],
                    "rb"
                ) as f:

                    teaser_bytes = f.read()

                st.download_button(
                    "⬇️ Télécharger le teaser",
                    data=teaser_bytes,
                    file_name=paths[1].name,
                    mime="video/mp4",
                    on_click="ignore",
                    key="download_teaser",
                    type="primary",
                    use_container_width=True
                )


# ============================================================
# INTERFACE
# ============================================================

def main():

    st.set_page_config(
        page_title=APP_TITLE,
        page_icon="🧠",
        layout="centered",
        initial_sidebar_state="expanded"
    )

    initialize_session_state()

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
            "Short : plus de 45 secondes"
        )

        st.caption(
            "Limite de sécurité : 90 secondes"
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
        height=120,
        key="topic_input"
    )

    # ========================================================
    # BOUTON GÉNÉRATION
    # ========================================================

    if st.button(
        "🚀 LANCER LA GÉNÉRATION",
        key="generate_video_button"
    ):

        if not topic.strip():

            st.warning(
                "⚠️ Oups ! Tu as oublié "
                "d'écrire un sujet."
            )

            return

        clear_generation_result()

        with st.status(
            "🎬 Allumage des caméras virtuelles...",
            expanded=True
        ) as status_box:

            try:

                def update_status(msg):
                    st.write(msg)

                # ==========================================
                # SCRIPT
                # ==========================================

                ai_data, gemini_client = (
                    generate_script_gemini(
                        topic,
                        update_status
                    )
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
                    f"📝 Narration initiale : "
                    f"**{word_count} mots**"
                )

                # ==========================================
                # SHORT SINGLE
                # ==========================================

                if format_choisi == "short_single":

                    max_repair_attempts = 2
                    repair_attempt = 0

                    while True:

                        try:

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

                            break

                        except ShortTooShortError as e:

                            repair_attempt += 1

                            if (
                                repair_attempt
                                > max_repair_attempts
                            ):

                                raise RuntimeError(
                                    str(e)
                                    + " Impossible d'obtenir "
                                    "plus de 45 secondes après "
                                    "les réparations automatiques."
                                )

                            measured = re.search(
                                r"([0-9]+(?:\.[0-9]+)?)",
                                str(e)
                            )

                            measured_duration = (
                                float(
                                    measured.group(1)
                                )
                                if measured
                                else 44.0
                            )

                            ai_data = (
                                repair_script_by_real_duration(
                                    gemini_client,
                                    topic,
                                    ai_data,
                                    measured_duration,
                                    update_status
                                )
                            )

                            new_word_count = (
                                count_words_in_scenes(
                                    ai_data.get(
                                        "script_principal",
                                        []
                                    )
                                )
                            )

                            st.write(
                                "📝 Nouveau script : "
                                f"**{new_word_count} mots**"
                            )

                        except ShortTooLongError as e:

                            repair_attempt += 1

                            if (
                                repair_attempt
                                > max_repair_attempts
                            ):

                                raise RuntimeError(
                                    str(e)
                                    + " Impossible de rester "
                                    "sous 90 secondes après "
                                    "les réparations automatiques."
                                )

                            measured = re.search(
                                r"([0-9]+(?:\.[0-9]+)?)",
                                str(e)
                            )

                            measured_duration = (
                                float(
                                    measured.group(1)
                                )
                                if measured
                                else 91.0
                            )

                            ai_data = (
                                repair_script_by_real_duration(
                                    gemini_client,
                                    topic,
                                    ai_data,
                                    measured_duration,
                                    update_status
                                )
                            )

                            new_word_count = (
                                count_words_in_scenes(
                                    ai_data.get(
                                        "script_principal",
                                        []
                                    )
                                )
                            )

                            st.write(
                                "📝 Nouveau script : "
                                f"**{new_word_count} mots**"
                            )

                # ==========================================
                # SHORT TWO PARTS
                # ==========================================

                elif format_choisi == "short_twoparts":

                    max_repair_attempts = 2
                    repair_attempt = 0

                    while True:

                        try:

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

                            break

                        except ShortTooShortError as e:

                            repair_attempt += 1

                            if (
                                repair_attempt
                                > max_repair_attempts
                            ):

                                raise RuntimeError(
                                    str(e)
                                )

                            measured = re.search(
                                r"([0-9]+(?:\.[0-9]+)?)",
                                str(e)
                            )

                            measured_duration = (
                                float(
                                    measured.group(1)
                                )
                                if measured
                                else 44.0
                            )

                            ai_data = (
                                repair_script_by_real_duration(
                                    gemini_client,
                                    topic,
                                    ai_data,
                                    measured_duration,
                                    update_status
                                )
                            )

                        except ShortTooLongError as e:

                            repair_attempt += 1

                            if (
                                repair_attempt
                                > max_repair_attempts
                            ):

                                raise RuntimeError(
                                    str(e)
                                )

                            measured = re.search(
                                r"([0-9]+(?:\.[0-9]+)?)",
                                str(e)
                            )

                            measured_duration = (
                                float(
                                    measured.group(1)
                                )
                                if measured
                                else 91.0
                            )

                            ai_data = (
                                repair_script_by_real_duration(
                                    gemini_client,
                                    topic,
                                    ai_data,
                                    measured_duration,
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

                # ==========================================
                # LONG + TEASER
                # ==========================================

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

                # ==========================================
                # SAUVEGARDE SESSION
                # ==========================================

                save_generation_result(
                    ai_data=ai_data,
                    format_choisi=format_choisi,
                    video_path=video_path,
                    topic=topic
                )

                # ==========================================
                # FIN
                # ==========================================

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

    # ========================================================
    # AFFICHAGE PERSISTANT DES RÉSULTATS
    # ========================================================

    render_results()


if __name__ == "__main__":
    main()
