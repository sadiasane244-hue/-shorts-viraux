# ============================================================
# CERVEAU CURIEUX — STUDIO IA AUTONOME (v6 — Action Video Edition)
# Pexels + Pixabay uniquement (100 % gratuit)
# ============================================================

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
PIXABAY_API_KEY = get_secret("PIXABAY_API_KEY")
GEMINI_API_KEY = get_secret("GEMINI_API_KEY")

FFMPEG_BIN = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE_BIN = shutil.which("ffprobe") or "ffprobe"


# ============================================================
# TTS
# ============================================================

TTS_VOICE = "fr-FR-HenriNeural"

TTS_RATE_BY_EMOTION = {
    "default":    "+10%",
    "thinking":   "+4%",
    "confused":   "+7%",
    "laughing":   "+16%",
    "explaining": "+6%",
    "surprised":  "+18%",
    "angry":      "+13%",
    "happy":      "+11%",
    "shocked":    "+18%",
    "sad":        "-2%",
}

TTS_RATE_CTA = "+20%"


# ============================================================
# IDENTITÉ
# ============================================================

INTRO_SIGNATURE = "Wesh l'équipe"

CTA_SIGNATURE = (
    "Et maintenant que ton cerveau sait ça... "
    "abonne-toi frérot, parce qu'on n'a pas fini de le faire buguer."
)


# ============================================================
# DURÉE
# ============================================================

SHORT_MIN_DURATION = 45.1
SHORT_TARGET_MIN_DURATION = 50.0
SHORT_TARGET_MAX_DURATION = 75.0
SHORT_MAX_DURATION = 90.0

SHORT_MIN_WORDS = 135
SHORT_TARGET_MIN_WORDS = 150
SHORT_TARGET_MAX_WORDS = 180
SHORT_MAX_WORDS = 200


# ============================================================
# AUDIO
# ============================================================

NASHEED_FILE = BASE_DIR / "nasheed.mp3"
NASHEED_VOLUME = 0.055

WHOOSH_SFX_FILE = BASE_DIR / "sfx_whoosh.mp3"
POP_SFX_FILE = BASE_DIR / "sfx_pop.mp3"
DING_SFX_FILE = BASE_DIR / "sfx_ding.mp3"

SFX_VOLUME_WHOOSH = 0.13
SFX_VOLUME_POP = 0.10
SFX_VOLUME_DING = 0.15

SFX_MAX_DURATION_WHOOSH = 0.80
SFX_MAX_DURATION_POP = 0.45
SFX_MAX_DURATION_DING = 0.85

SFX_DELAY_WHOOSH = 90
SFX_DELAY_POP = 70
SFX_DELAY_DING = 110


# ============================================================
# MASCOTTES
# ============================================================

MASCOT_FILES = {
    "default":    BASE_DIR / "mascot_default.png",
    "thinking":   BASE_DIR / "mascot_thinking.png",
    "confused":   BASE_DIR / "mascot_confused.png",
    "laughing":   BASE_DIR / "mascot_laughing.png",
    "explaining": BASE_DIR / "mascot_explaining.png",
    "surprised":  BASE_DIR / "mascot_surprised.png",
    "angry":      BASE_DIR / "mascot_angry.png",
    "happy":      BASE_DIR / "mascot_happy.png",
    "shocked":    BASE_DIR / "mascot_shocked.png",
    "sad":        BASE_DIR / "mascot_sad.png",
}


def has_any_mascot() -> bool:
    return any(p.exists() for p in MASCOT_FILES.values())


# ============================================================
# EXCEPTIONS
# ============================================================

class ShortTooShortError(RuntimeError):
    pass


class ShortTooLongError(RuntimeError):
    pass


# ============================================================
# SCHÉMA GEMINI
# ============================================================

class Scene(BaseModel):
    text: str = Field(description="UNE SEULE phrase. Fin : . ! ou ?")
    emotion: str = Field(description="default, thinking, confused, laughing, explaining, surprised, angry, happy, shocked, sad")
    intensity: int = Field(description="Intensité 1 à 5. Jamais 3 de suite identiques.")
    visual_query: str = Field(
        description=(
            "Action FILMABLE en anglais, 2-4 mots, SUJET PHYSIQUE + VERBE D'ACTION FORT. "
            "Ex: 'man walking street', 'woman typing laptop', 'person running park', "
            "'kid jumping rope', 'man opening fridge'. JAMAIS statique comme 'person sitting'."
        )
    )


class ScriptOutput(BaseModel):
    format_choisi: str = Field(description="short_single, short_twoparts, ou long_plus_teaser")
    title: str = Field(description="Titre honnête, max 65 caractères.")
    hashtags: List[str] = Field(description="4 à 6 hashtags.")
    script_principal: List[Scene] = Field(description="150-180 mots.")
    script_teaser: List[Scene] = Field(default_factory=list)


# ============================================================
# OUTILS
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
                shutil.rmtree(item, ignore_errors=True)
        except Exception:
            pass


def run_command(command, cwd=None):
    cmd_str = [str(arg) for arg in command]
    try:
        return subprocess.run(cmd_str, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, check=True, cwd=cwd)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Erreur Shell:\nCommande: {' '.join(cmd_str)}\nErreur: {e.stderr[-3000:]}")


def get_media_duration(file_path: Path) -> float:
    if not file_path.exists() or file_path.stat().st_size == 0:
        return 0.0
    cmd = [FFPROBE_BIN, "-v", "error", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", str(file_path)]
    res = run_command(cmd)
    try:
        return float(res.stdout.strip())
    except ValueError:
        return 0.0


def count_words_in_scenes(scenes) -> int:
    return sum(len(str(s.get("text", "")).strip().split()) for s in scenes or [])


# ============================================================
# QC
# ============================================================

def qc_validate_video(video_path, expected_format=None):
    if not video_path.exists():
        raise RuntimeError("QC Échec : fichier final absent.")
    if video_path.stat().st_size < 10000:
        raise RuntimeError("QC Échec : vidéo vide.")
    duration = get_media_duration(video_path)
    if duration <= 0:
        raise RuntimeError("QC Échec : durée illisible.")

    cmd_video = [FFPROBE_BIN, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=codec_type,width,height",
                 "-of", "json", str(video_path)]
    res_video = run_command(cmd_video)
    try:
        data = json.loads(res_video.stdout)
        streams = data.get("streams", [])
        if not streams:
            raise RuntimeError("QC Échec : aucune piste vidéo.")
        width = int(streams[0].get("width", 0))
        height = int(streams[0].get("height", 0))
        if expected_format == "portrait" and height <= width:
            raise RuntimeError("QC Échec : pas vertical.")
        elif expected_format == "landscape" and width <= height:
            raise RuntimeError("QC Échec : pas horizontal.")
    except (ValueError, TypeError, json.JSONDecodeError):
        raise RuntimeError("QC Échec : résolution illisible.")

    cmd_audio = [FFPROBE_BIN, "-v", "error", "-select_streams", "a:0",
                 "-show_entries", "stream=codec_type",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)]
    res_audio = run_command(cmd_audio)
    if "audio" not in res_audio.stdout.lower():
        raise RuntimeError("QC Échec : aucune piste audio.")
    return duration


# ============================================================
# TTS
# ============================================================

def fix_phonetics_for_tts(text: str) -> str:
    return text.replace("le faire buguer", "le faire beuguer")


def generate_tts(text: str, output_path: Path, emotion: str = "default", is_cta: bool = False):
    spoken_text = fix_phonetics_for_tts(text)
    rate = TTS_RATE_CTA if is_cta else TTS_RATE_BY_EMOTION.get(emotion, "+10%")
    cmd = ["edge-tts", "--voice", TTS_VOICE, "--rate", rate,
           "--text", spoken_text, "--write-media", str(output_path)]
    run_command(cmd)


# ============================================================
# PROMPT GEMINI (v6 — Verbes d'action renforcés)
# ============================================================

SYSTEM_PROMPT = f"""
Tu es le réalisateur et scénariste de la chaîne YouTube/TikTok "Cerveau Curieux".

OBJECTIF : Créer des Shorts modernes, dynamiques, drôles et documentés.

============================================================
RÈGLE D'OR N°1 — UNE SCÈNE = UNE SEULE PHRASE
============================================================
Une scène = une phrase. Fin : . ! ou ?
JAMAIS deux phrases dans la même scène.

============================================================
RÈGLE D'OR N°2 — HUMOUR, RELANCE, PUNCHLINE
============================================================
A. RELANCES (obligatoires) : toutes les 2-3 scènes, une scène
ULTRA-COURTE (3-6 mots) : "Attends.", "Et le pire ?", "Sauf que...",
"Accroche-toi.", "Regarde bien."
Interdit : 3 scènes sans relance. 4 explications d'affilée.

B. PUNCHLINES (au moins 3) : phrases courtes et percutantes.
Ex: "Ton cerveau te ment. En boucle. Gratuitement."

============================================================
RÈGLE D'OR N°3 — RYTHME VARIABLE
============================================================
Alterner : scènes courtes (3-7 mots) / moyennes (10-15) / longues (16-22).
JAMAIS 3 scènes consécutives avec la même intensity.

============================================================
IDENTITÉ
============================================================
Scène 1 DOIT commencer exactement par : "{INTRO_SIGNATURE}"
Puis, dans la MÊME phrase, un HOOK fort.
Ex: "Wesh l'équipe, ton cerveau te fait oublier des trucs exprès."

Ton : tutoiement, street, moderne, "frérot", "ton cerveau bugue".
Pas d'insulte, pas de vulgarité lourde.

============================================================
STRUCTURE
============================================================
1. Signature + Hook (open loop)
2. RELANCE courte
3. Énoncé du phénomène
4-9. Alternance explication / exemple / relance / punchline
-2. PAYOFF = réponse à la promesse
-1. CTA EXACT : "{CTA_SIGNATURE}"

============================================================
RIGUEUR SCIENTIFIQUE
============================================================
Ne jamais inventer un fait, chiffre ou expérience.

============================================================
DURÉE
============================================================
Short > 45 s, idéal 50-75 s. 150 à 180 mots. Max 200.

============================================================
VISUAL_QUERY — RÈGLE ABSOLUE (CRITIQUE POUR LA VIDÉO)
============================================================

Le visual_query cherche une VRAIE VIDÉO sur Pexels/Pixabay.
Pexels a BEAUCOUP de vidéos statiques (objets, plans fixes).
Pour avoir du MOUVEMENT, ta query DOIT contenir un VERBE D'ACTION.

RÈGLES STRICTES :

1. Format : 2 à 4 mots en anglais.

2. OBLIGATOIRE : un SUJET PHYSIQUE + un VERBE DE MOUVEMENT.
   Sujets : person, man, woman, kid, student, couple, boy, girl,
            worker, athlete, chef, teacher, driver, dancer.
   Verbes : walking, running, jumping, dancing, typing, driving,
            cooking, eating, drinking, laughing, talking, opening,
            closing, throwing, climbing, swimming, playing, writing,
            drawing, cleaning, building, working, exercising.

3. INTERDIT (verbes statiques) :
   "sitting", "standing", "looking", "thinking", "waiting", "watching",
   "resting", "lying" → Pexels renvoie des plans fixes.
   Si tu dois exprimer une idée abstraite, transforme-la en action.

4. INTERDIT (concepts abstraits) :
   "brain power", "memory loss", "psychology", "subconscious",
   "cognitive bias", "neural network" → aucune vidéo trouvée.

5. TRADUCTIONS :
   - "memory loss" → "man forgetting keys"
   - "attention span" → "student distracted phone"
   - "dopamine" → "woman eating chocolate"
   - "subconscious" → "man sleeping bed"
   - "focus" → "student typing laptop"
   - "stress" → "person running street"

6. EXEMPLES DE BONNES QUERIES :
   "man walking street", "woman typing laptop", "kid running park",
   "couple laughing dinner", "student writing notebook",
   "man opening fridge", "woman dancing room", "person climbing stairs",
   "chef cooking kitchen", "athlete running track", "driver steering wheel".

7. Chaque scène a une query DIFFÉRENTE. Varie les sujets.

============================================================
INTENSITY
============================================================
- 1 = calme (contexte)
- 2 = explicatif normal
- 3 = exemple concret
- 4 = relance, détail surprenant
- 5 = punchline, révélation

Obligation : au moins 2 scènes à 4, 2 à 5, 2 à 1.

============================================================
ÉMOTIONS
============================================================
default, thinking, confused, laughing, explaining,
surprised, angry, happy, shocked, sad.

============================================================
TITRE / HASHTAGS
============================================================
Titre : max 65 caractères.
Hashtags : 4 à 6 ciblés.

============================================================
RÈGLE ABSOLUE
============================================================
Query statique → tu as échoué.
3 intensités identiques → tu as échoué.
Pas de relance → tu as échoué.
"""


# ============================================================
# HASHTAGS
# ============================================================

def normalize_hashtags(hashtags):
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


# ============================================================
# PEXELS QUERY
# ============================================================

def clean_pexels_query(query: str) -> str:
    query = re.sub(r"[^a-zA-Z\s]", "", query or "")
    words = [w for w in query.split() if len(w) > 2]
    return " ".join(words[:4])


# ============================================================
# NORMALISATION
# ============================================================

def normalize_scene(scene) -> Optional[Dict]:
    if hasattr(scene, "model_dump"):
        scene = scene.model_dump()
    if not isinstance(scene, dict):
        return None

    text = str(scene.get("text", "")).strip()
    if not text:
        return None

    emotion = str(scene.get("emotion", "default")).strip().lower()
    visual_query = str(scene.get("visual_query", "person walking")).strip()
    visual_query = clean_pexels_query(visual_query) or "person walking"

    try:
        intensity = int(scene.get("intensity", 3))
    except (ValueError, TypeError):
        intensity = 3
    intensity = max(1, min(5, intensity))

    allowed_emotions = set(MASCOT_FILES.keys())
    if emotion not in allowed_emotions:
        emotion = "default"

    return {
        "text": text,
        "emotion": emotion,
        "intensity": intensity,
        "visual_query": visual_query[:80],
    }


SENTENCE_SPLIT_RE = re.compile(r"(?<=[\.!\?])\s+(?=[A-ZÀ-Ý])")


def split_multi_sentence_scenes(scenes: List[Dict]) -> List[Dict]:
    result = []
    for scene in scenes:
        text = scene["text"].strip()
        parts = [p.strip() for p in SENTENCE_SPLIT_RE.split(text) if p.strip()]
        if len(parts) <= 1:
            result.append(scene)
            continue
        for part in parts:
            new_scene = dict(scene)
            new_scene["text"] = part
            result.append(new_scene)
    return result


def enforce_rhythm_diversity(scenes: List[Dict]) -> List[Dict]:
    if len(scenes) < 3:
        return scenes
    for i in range(2, len(scenes)):
        a = scenes[i - 2].get("intensity", 3)
        b = scenes[i - 1].get("intensity", 3)
        c = scenes[i].get("intensity", 3)
        if a == b == c:
            scenes[i]["intensity"] = 5 if a < 4 else 1
    return scenes


def dedupe_visual_queries(scenes: List[Dict]) -> List[Dict]:
    variants = [
        "man walking street", "woman typing laptop", "person running park",
        "student writing notebook", "couple laughing dinner",
    ]
    for i in range(1, len(scenes)):
        if scenes[i].get("visual_query") == scenes[i - 1].get("visual_query"):
            scenes[i]["visual_query"] = random.choice(variants)
    return scenes


# ============================================================
# VALIDATION
# ============================================================

def validate_and_repair_script(data: Dict) -> Dict:
    if not isinstance(data, dict):
        raise RuntimeError("Réponse Gemini invalide.")

    scenes = data.get("script_principal") or []
    if not scenes:
        raise RuntimeError("Gemini n'a généré aucune scène.")

    normalized = [normalize_scene(s) for s in scenes]
    normalized = [s for s in normalized if s]
    if not normalized:
        raise RuntimeError("Script Gemini vide.")

    normalized = split_multi_sentence_scenes(normalized)
    normalized = enforce_rhythm_diversity(normalized)
    normalized = dedupe_visual_queries(normalized)

    first_text = normalized[0]["text"]
    if not first_text.lower().startswith(INTRO_SIGNATURE.lower()):
        normalized[0]["text"] = f"{INTRO_SIGNATURE}, {first_text}"

    normalized[-1]["text"] = CTA_SIGNATURE
    normalized[-1]["emotion"] = "happy"
    normalized[-1]["intensity"] = 5
    normalized[-1]["visual_query"] = "smiling person thumbs up"

    data["script_principal"] = normalized

    teaser = data.get("script_teaser") or []
    normalized_teaser = [normalize_scene(s) for s in teaser]
    normalized_teaser = [s for s in normalized_teaser if s]
    normalized_teaser = split_multi_sentence_scenes(normalized_teaser)
    normalized_teaser = enforce_rhythm_diversity(normalized_teaser)
    normalized_teaser = dedupe_visual_queries(normalized_teaser)
    data["script_teaser"] = normalized_teaser

    allowed_formats = {"short_single", "short_twoparts", "long_plus_teaser"}
    if data.get("format_choisi") not in allowed_formats:
        data["format_choisi"] = "short_single"

    title = str(data.get("title", "Pourquoi ton cerveau fait ça")).strip()
    title = re.sub(r"\s+", " ", title).strip("\"'")
    if len(title) > 65:
        title = title[:65].rstrip()
    if not title:
        title = "Pourquoi ton cerveau fait ça"
    data["title"] = title

    data["hashtags"] = normalize_hashtags(data.get("hashtags", []))
    if not data["hashtags"]:
        data["hashtags"] = ["#Cerveau", "#Psychologie", "#Science", "#CerveauCurieux"]

    return data


# ============================================================
# GEMINI
# ============================================================

def call_gemini_script(client, contents: str) -> Dict:
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
    if hasattr(response, "parsed") and response.parsed:
        parsed = response.parsed.model_dump()
    if parsed is None:
        parsed = json.loads(response.text)
    return validate_and_repair_script(parsed)


def repair_script_by_words(client, topic, data, status_cb, too_short):
    scenes = data.get("script_principal", [])
    word_count = count_words_in_scenes(scenes)
    current_script = "\n".join(s.get("text", "") for s in scenes)

    if too_short:
        instruction = f"""
Le script est trop court ({word_count} mots).
Réécris-le pour atteindre {SHORT_TARGET_MIN_WORDS} à {SHORT_TARGET_MAX_WORDS} mots.
Ajoute uniquement : mécanisme, exemple, conséquence, nuance.
Ajoute au moins une relance courte et une punchline.
Une phrase = une scène. Garde l'intensity et visual_query (verbe d'action).
"""
    else:
        instruction = f"""
Le script est trop long ({word_count} mots).
Réduis vers {SHORT_TARGET_MIN_WORDS} à {SHORT_TARGET_MAX_WORDS} mots.
Supprime répétitions. Garde faits, nuances, relances, punchlines.
Une phrase = une scène. Garde l'intensity et visual_query (verbe d'action).
"""

    prompt = f"""
Sujet : {topic.strip()}
Script actuel :
{current_script}
{instruction}
Scène 1 : "{INTRO_SIGNATURE}". Dernière scène : "{CTA_SIGNATURE}".
Format : {data.get("format_choisi", "short_single")}.
Renvoie le JSON complet.
"""
    status_cb("🧠 Ajustement...")
    repaired = call_gemini_script(client, prompt)
    repaired["format_choisi"] = data.get("format_choisi", repaired.get("format_choisi", "short_single"))
    return validate_and_repair_script(repaired)


def generate_script_gemini(topic: str, status_cb) -> Tuple[Dict, object]:
    if not GEMINI_API_KEY:
        raise RuntimeError("Clé API GEMINI manquante.")

    client = genai.Client(api_key=GEMINI_API_KEY)
    status_cb("🧠 Analyse du sujet...")

    prompt = f"""
Sujet : {topic.strip()}

Crée le contenu de la vidéo.
Short : {SHORT_TARGET_MIN_WORDS} à {SHORT_TARGET_MAX_WORDS} mots.
Durée : > 45 s, idéal 50-75 s.

RAPPEL : une scène = UNE phrase.
RAPPEL : relances + punchlines OBLIGATOIRES.
RAPPEL : visual_query avec VERBE D'ACTION (walking, typing, running...).

Scène 1 : "{INTRO_SIGNATURE}" + hook.
Dernière scène : "{CTA_SIGNATURE}".
"""
    try:
        data = call_gemini_script(client, prompt)
        format_choisi = data.get("format_choisi", "short_single")
        if format_choisi in ("short_single", "short_twoparts"):
            wc = count_words_in_scenes(data.get("script_principal", []))
            if wc < SHORT_MIN_WORDS:
                data = repair_script_by_words(client, topic, data, status_cb, True)
            elif wc > SHORT_MAX_WORDS:
                data = repair_script_by_words(client, topic, data, status_cb, False)
        return validate_and_repair_script(data), client
    except Exception as e:
        raise RuntimeError(f"Erreur Gemini : {e}")


def repair_script_by_real_duration(client, topic, data, measured_duration, status_cb):
    scenes = data.get("script_principal", [])
    current_script = "\n".join(s.get("text", "") for s in scenes)

    if measured_duration < SHORT_MIN_DURATION:
        status_cb(f"⏱️ Trop court ({measured_duration:.1f}s). Enrichissement...")
        prompt = f"""
Sujet : {topic.strip()}
Durée actuelle : {measured_duration:.1f}s. Il faut > 45s.
Vise 55-70 secondes.
Script actuel :
{current_script}
Ajoute uniquement : mécanisme, exemple, conséquence, nuance.
Une phrase = une scène. visual_query avec verbe d'action.
Commence par "{INTRO_SIGNATURE}". Finis par "{CTA_SIGNATURE}".
Format : {data.get("format_choisi", "short_single")}.
"""
    else:
        status_cb(f"⏱️ Trop long ({measured_duration:.1f}s). Resserrement...")
        prompt = f"""
Sujet : {topic.strip()}
Durée actuelle : {measured_duration:.1f}s. Max 90s.
Vise 55-75 secondes.
Script actuel :
{current_script}
Supprime répétitions. Garde hook, faits, relances, punchlines.
Une phrase = une scène. visual_query avec verbe d'action.
Commence par "{INTRO_SIGNATURE}". Finis par "{CTA_SIGNATURE}".
Format : {data.get("format_choisi", "short_single")}.
"""

    repaired = call_gemini_script(client, prompt)
    repaired["format_choisi"] = data.get("format_choisi", repaired.get("format_choisi", "short_single"))
    return validate_and_repair_script(repaired)


# ============================================================
# PEXELS v6 — FILTRE DURÉE + SCORE DURÉE×RÉSOLUTION
# ============================================================

def search_pexels_video(query: str, orientation: str,
                        used_urls: Optional[set] = None) -> Optional[str]:
    """
    v6 :
    - per_page = 40 (au lieu de 15) pour avoir plus de choix
    - FILTRE : durée vidéo >= 3 secondes (élimine les clips trop courts)
    - SCORE : durée * 1M + résolution (priorise les clips longs)
    - Prend au hasard parmi les 5 meilleurs pour varier
    """
    if not PEXELS_API_KEY:
        return None
    if used_urls is None:
        used_urls = set()

    clean_query = clean_pexels_query(query) or "person walking"
    url = "https://api.pexels.com/videos/search"
    headers = {"Authorization": PEXELS_API_KEY}

    attempts = [clean_query]
    words = clean_query.split()
    if len(words) >= 3:
        attempts.append(" ".join(words[:2]))
    attempts.append("person walking street")

    for attempt in attempts:
        try:
            r = requests.get(
                url, headers=headers,
                params={"query": attempt, "orientation": orientation, "per_page": 40},
                timeout=12,
            )
            if r.status_code != 200:
                continue

            videos = r.json().get("videos", [])
            candidates = []

            for video in videos:
                # ▼ FILTRE DURÉE : on élimine les clips < 3s
                vid_duration = float(video.get("duration", 0) or 0)
                if vid_duration < 3:
                    continue

                for fi in video.get("video_files", []):
                    link = fi.get("link")
                    if not link or ".mp4" not in str(link).lower():
                        continue
                    w = int(fi.get("width", 0) or 0)
                    h = int(fi.get("height", 0) or 0)
                    if w <= 0 or h <= 0:
                        continue
                    if orientation == "portrait" and h < 720:
                        continue
                    if orientation == "landscape" and w < 1280:
                        continue
                    # ▼ SCORE : durée en priorité, résolution en secondaire
                    score = vid_duration * 1_000_000 + w * h
                    candidates.append((score, link))

            if not candidates:
                continue

            fresh = [c for c in candidates if c[1] not in used_urls]
            pool = fresh if fresh else candidates
            pool.sort(reverse=True)
            top = pool[:min(5, len(pool))]
            return random.choice(top)[1]

        except Exception:
            continue

    return None


# ============================================================
# PIXABAY v6
# ============================================================

def search_pixabay_video(query: str, orientation: str,
                          used_urls: Optional[set] = None) -> Optional[str]:
    if not PIXABAY_API_KEY:
        return None
    if used_urls is None:
        used_urls = set()

    clean_query = clean_pexels_query(query) or "person walking"
    orientation_param = "vertical" if orientation == "portrait" else "horizontal"

    url = "https://pixabay.com/api/videos/"
    params = {
        "key": PIXABAY_API_KEY,
        "q": clean_query,
        "video_type": "film",
        "orientation": orientation_param,
        "per_page": 30,
        "safesearch": "true",
        "min_duration": 3,  # ▼ Pixabay SUPPORTE ce paramètre
    }

    try:
        r = requests.get(url, params=params, timeout=12)
        if r.status_code != 200:
            return None
        hits = r.json().get("hits", [])
        candidates = []

        for hit in hits:
            dur = float(hit.get("duration", 0) or 0)
            if dur < 3:
                continue
            videos = hit.get("videos", {})
            for quality in ["large", "medium", "small"]:
                v = videos.get(quality)
                if not v:
                    continue
                link = v.get("url")
                if not link:
                    continue
                w = int(v.get("width", 0) or 0)
                h = int(v.get("height", 0) or 0)
                if w <= 0 or h <= 0:
                    continue
                score = dur * 1_000_000 + w * h
                candidates.append((score, link))
                break

        if not candidates:
            return None

        fresh = [c for c in candidates if c[1] not in used_urls]
        pool = fresh if fresh else candidates
        pool.sort(reverse=True)
        top = pool[:min(5, len(pool))]
        return random.choice(top)[1]

    except Exception:
        return None


def download_file(url: str, dest: Path) -> bool:
    try:
        with requests.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        f.write(chunk)
        return dest.exists() and dest.stat().st_size > 10000
    except Exception:
        return False


# ============================================================
# SOUS-TITRES ASS
# ============================================================

def ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds - int(seconds)) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def create_ass_subtitles(scenes: List[Dict], output_ass: Path, width: int, height: int):
    is_portrait = height > width
    if is_portrait:
        sub_fontsize = 72
        sub_margin_v = int(height * 0.24)
    else:
        sub_fontsize = 48
        sub_margin_v = 120

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,{sub_fontsize},&H00FFFFFF,&H00000000,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,3,2,40,40,{sub_margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = []
    current_time = 0.0

    for scene in scenes:
        scene_duration = float(scene.get("duration", 0))
        text = str(scene.get("text", "")).replace("\n", " ").replace("{", "").replace("}", "").strip()
        words = text.split()
        if not words:
            current_time += scene_duration
            continue

        chunk_size = 4 if is_portrait else 5
        chunks = [words[i:i + chunk_size] for i in range(0, len(words), chunk_size)]
        chunk_duration = scene_duration / len(chunks)

        for idx_c, chunk_words in enumerate(chunks):
            chunk_start = current_time + idx_c * chunk_duration
            word_duration = chunk_duration / len(chunk_words)

            for idx_w, w in enumerate(chunk_words):
                start_t = chunk_start + idx_w * word_duration
                end_t = start_t + word_duration
                formatted_words = []
                for k, ww in enumerate(chunk_words):
                    safe_word = re.sub(r"[,.?!;:]", "", ww)
                    if k == idx_w:
                        formatted_words.append("{\\c&H00FFFF&}" + safe_word + "{\\c&HFFFFFF&}")
                    else:
                        formatted_words.append(safe_word)
                dialogue_text = " ".join(formatted_words)
                lines.append(f"Dialogue: 0,{ass_time(start_t)},{ass_time(end_t)},Default,,0,0,0,,{dialogue_text}")

        current_time += scene_duration

    with open(output_ass, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(lines))


# ============================================================
# SFX
# ============================================================

def choose_sfx_for_scene(scene, idx, total_scenes):
    text = str(scene.get("text", "")).strip().lower()
    emotion = str(scene.get("emotion", "default")).strip().lower()
    intensity = int(scene.get("intensity", 3))

    if idx == total_scenes - 1 and DING_SFX_FILE.exists():
        return {"file": DING_SFX_FILE, "volume": SFX_VOLUME_DING, "delay": SFX_DELAY_DING,
                "max_duration": SFX_MAX_DURATION_DING, "name": "ding"}
    if idx == 1 and WHOOSH_SFX_FILE.exists():
        return {"file": WHOOSH_SFX_FILE, "volume": SFX_VOLUME_WHOOSH, "delay": SFX_DELAY_WHOOSH,
                "max_duration": SFX_MAX_DURATION_WHOOSH, "name": "whoosh"}
    if intensity >= 5 and DING_SFX_FILE.exists():
        return {"file": DING_SFX_FILE, "volume": SFX_VOLUME_DING, "delay": SFX_DELAY_DING,
                "max_duration": SFX_MAX_DURATION_DING, "name": "ding"}
    if emotion in ("shocked", "surprised") and POP_SFX_FILE.exists():
        return {"file": POP_SFX_FILE, "volume": SFX_VOLUME_POP, "delay": SFX_DELAY_POP,
                "max_duration": SFX_MAX_DURATION_POP, "name": "pop"}

    transition_words = ["mais", "pourtant", "en réalité", "en fait", "le problème",
                        "voilà pourquoi", "c'est là", "sauf que", "cependant", "résultat", "donc"]
    if any(k in text for k in transition_words) and WHOOSH_SFX_FILE.exists():
        return {"file": WHOOSH_SFX_FILE, "volume": SFX_VOLUME_WHOOSH, "delay": SFX_DELAY_WHOOSH,
                "max_duration": SFX_MAX_DURATION_WHOOSH, "name": "whoosh"}

    reveal_words = ["surprenant", "important", "incroyable", "bizarre", "étonnant",
                    "détail", "secret", "mécanisme", "résultat", "pourquoi"]
    if any(k in text for k in reveal_words) and POP_SFX_FILE.exists():
        return {"file": POP_SFX_FILE, "volume": SFX_VOLUME_POP, "delay": SFX_DELAY_POP,
                "max_duration": SFX_MAX_DURATION_POP, "name": "pop"}

    if "?" in text and POP_SFX_FILE.exists():
        return {"file": POP_SFX_FILE, "volume": SFX_VOLUME_POP, "delay": SFX_DELAY_POP,
                "max_duration": SFX_MAX_DURATION_POP, "name": "pop"}

    return None


# ============================================================
# AUDIO PAR SCÈNE
# ============================================================

def process_scene_audio(scene, idx, total_scenes, work_dir):
    temp_audio = work_dir / f"temp_audio_{idx:03d}.mp3"
    processed_audio = work_dir / f"audio_{idx:03d}.wav"

    is_cta = (idx == total_scenes - 1)
    generate_tts(scene["text"], temp_audio, emotion=scene.get("emotion", "default"), is_cta=is_cta)

    sfx_info = choose_sfx_for_scene(scene, idx, total_scenes)

    if not sfx_info:
        cmd = [FFMPEG_BIN, "-y", "-i", str(temp_audio), "-af",
               "aresample=48000,aformat=channel_layouts=stereo,loudnorm=I=-16:LRA=11:TP=-1.5",
               "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(processed_audio)]
        run_command(cmd, cwd=work_dir)
    else:
        cmd = [FFMPEG_BIN, "-y", "-i", str(temp_audio), "-i", str(sfx_info["file"]),
               "-filter_complex",
               ("[0:a]aresample=48000,aformat=channel_layouts=stereo[voice];"
                f"[1:a]atrim=0:{sfx_info['max_duration']},asetpts=N/SR/TB,"
                f"volume={sfx_info['volume']},adelay={sfx_info['delay']}|{sfx_info['delay']},"
                "aresample=48000,aformat=channel_layouts=stereo[sfx];"
                "[voice][sfx]amix=inputs=2:duration=first:dropout_transition=0,"
                "loudnorm=I=-16:LRA=11:TP=-1.5[a]"),
               "-map", "[a]", "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(processed_audio)]
        run_command(cmd, cwd=work_dir)

    scene["duration"] = get_media_duration(processed_audio)
    return processed_audio


def concatenate_audio(audio_clips, work_dir):
    concat_file = work_dir / "concat_audio.txt"
    with open(concat_file, "w", encoding="utf-8") as f:
        for a in audio_clips:
            f.write(f"file '{a.name}'\n")
    raw_audio = work_dir / "raw_audio.wav"
    run_command([FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0", "-i", "concat_audio.txt",
                 "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(raw_audio)], cwd=work_dir)
    return raw_audio


def add_nasheed_track(voice_audio, work_dir, status_cb=None):
    output = work_dir / "full_audio.m4a"
    if not NASHEED_FILE.exists():
        if status_cb:
            status_cb("🎙️ Aucun nasheed : voix seule.")
        run_command([FFMPEG_BIN, "-y", "-i", str(voice_audio), "-c:a", "aac",
                     "-b:a", "192k", "-ar", "48000", "-ac", "2", str(output)], cwd=work_dir)
        return output

    if status_cb:
        status_cb("🎵 Nasheed actif...")

    cmd = [FFMPEG_BIN, "-y", "-i", str(voice_audio), "-stream_loop", "-1", "-i", str(NASHEED_FILE),
           "-filter_complex",
           ("[0:a]aresample=48000,aformat=channel_layouts=stereo,volume=1.0[voice];"
            "[1:a]aresample=48000,aformat=channel_layouts=stereo,"
            f"volume={NASHEED_VOLUME},highpass=f=100,lowpass=f=9000,afade=t=in:st=0:d=1.5[nasheed_raw];"
            "[nasheed_raw][voice]sidechaincompress=threshold=0.045:ratio=7:attack=20:release=300:makeup=1:knee=3"
            "[nasheed_ducked];"
            "[voice][nasheed_ducked]amix=inputs=2:duration=first:dropout_transition=2,"
            "loudnorm=I=-16:LRA=11:TP=-1.5[mixed]"),
           "-map", "[mixed]", "-ar", "48000", "-ac", "2", "-c:a", "aac", "-b:a", "192k", str(output)]
    run_command(cmd, cwd=work_dir)
    return output


# ============================================================
# VIDÉO CLIP
# ============================================================

def create_video_clip_from_pexels(visual_file, mascot_img, output_clip, duration,
                                   width, height, mascot_scale, pos_x, pos_y,
                                   enable_expr, work_dir, intensity=3):
    fps = 30
    total_frames = max(1, int(duration * fps))
    zoom_end = 1.03 + (min(intensity, 5) - 1) * 0.0075

    mascot_dur = min(2.5, duration)
    fade_in_d = 0.2
    fade_out_start = max(0.1, mascot_dur - 0.35)
    fade_out_d = 0.3

    if mascot_img is not None and Path(mascot_img).exists():
        filter_complex = (
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},fps={fps},setsar=1,"
            f"zoompan=z='min(zoom+0.0006,{zoom_end})':d={total_frames}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height},setsar=1[bg];"
            f"[1:v]scale={mascot_scale}:-1,format=rgba,"
            f"fade=t=in:st=0:d={fade_in_d}:alpha=1,"
            f"fade=t=out:st={fade_out_start}:d={fade_out_d}:alpha=1[mascot];"
            f"[bg][mascot]overlay=x={pos_x}:y={pos_y}:enable='{enable_expr}'[v_out]"
        )
        cmd = [FFMPEG_BIN, "-y", "-stream_loop", "-1", "-i", str(visual_file),
               "-loop", "1", "-i", str(mascot_img.resolve()), "-t", str(duration),
               "-filter_complex", filter_complex, "-map", "[v_out]", "-an",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
               "-pix_fmt", "yuv420p", "-r", str(fps), "-movflags", "+faststart", str(output_clip)]
    else:
        filter_complex = (
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},fps={fps},setsar=1,"
            f"zoompan=z='min(zoom+0.0006,{zoom_end})':d={total_frames}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height},setsar=1[v_out]"
        )
        cmd = [FFMPEG_BIN, "-y", "-stream_loop", "-1", "-i", str(visual_file), "-t", str(duration),
               "-filter_complex", filter_complex, "-map", "[v_out]", "-an",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
               "-pix_fmt", "yuv420p", "-r", str(fps), "-movflags", "+faststart", str(output_clip)]

    run_command(cmd, cwd=work_dir)


def create_fallback_video_clip(output_clip, mascot_img, duration, width, height,
                                mascot_scale, pos_x, pos_y, enable_expr, work_dir, intensity=3):
    fallback = work_dir / f"fallback_{output_clip.stem}.png"
    Image.new("RGB", (width, height), color=(20, 20, 35)).save(fallback)

    fps = 30
    total_frames = max(1, int(duration * fps))
    zoom_end = 1.03 + (min(intensity, 5) - 1) * 0.0075
    mascot_dur = min(2.5, duration)

    if mascot_img is not None and Path(mascot_img).exists():
        filter_complex = (
            f"[0:v]scale={width}:{height},fps={fps},setsar=1,"
            f"zoompan=z='min(zoom+0.0006,{zoom_end})':d={total_frames}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height},setsar=1[bg];"
            f"[1:v]scale={mascot_scale}:-1,format=rgba,"
            f"fade=t=in:st=0:d=0.2:alpha=1,"
            f"fade=t=out:st={max(0.1, mascot_dur - 0.35)}:d=0.3:alpha=1[mascot];"
            f"[bg][mascot]overlay=x={pos_x}:y={pos_y}:enable='{enable_expr}'[v_out]"
        )
        cmd = [FFMPEG_BIN, "-y", "-loop", "1", "-i", str(fallback),
               "-loop", "1", "-i", str(mascot_img.resolve()), "-t", str(duration),
               "-filter_complex", filter_complex, "-map", "[v_out]", "-an",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
               "-pix_fmt", "yuv420p", "-r", str(fps), "-movflags", "+faststart", str(output_clip)]
    else:
        filter_complex = (
            f"[0:v]scale={width}:{height},fps={fps},setsar=1,"
            f"zoompan=z='min(zoom+0.0006,{zoom_end})':d={total_frames}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height},setsar=1[v_out]"
        )
        cmd = [FFMPEG_BIN, "-y", "-loop", "1", "-i", str(fallback), "-t", str(duration),
               "-filter_complex", filter_complex, "-map", "[v_out]", "-an",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
               "-pix_fmt", "yuv420p", "-r", str(fps), "-movflags", "+faststart", str(output_clip)]

    run_command(cmd, cwd=work_dir)


# ============================================================
# PIPELINE VIDÉO
# ============================================================

def generate_video_pipeline(script_scenes, video_format, status_cb):
    if not script_scenes:
        raise ValueError("Le script est vide.")

    work_dir = TEMP_DIR / f"run_{int(time.time())}_{video_format}_{random.randint(1000,9999)}"
    work_dir.mkdir(parents=True, exist_ok=True)

    width, height = (1080, 1920) if video_format == "portrait" else (1920, 1080)
    orientation = "portrait" if video_format == "portrait" else "landscape"

    mascot_available = has_any_mascot()
    if not mascot_available:
        status_cb("⚠️ Aucune mascotte : vidéo sans overlay mascotte.")

    status_cb("🎙️ Génération de la voix off...")
    audio_clips = []
    total_scenes = len(script_scenes)

    for idx, scene in enumerate(script_scenes):
        audio_path = process_scene_audio(scene, idx, total_scenes, work_dir)
        audio_clips.append(audio_path)

    raw_audio = concatenate_audio(audio_clips, work_dir)
    full_audio = add_nasheed_track(raw_audio, work_dir, status_cb)
    voice_duration = get_media_duration(full_audio)
    status_cb(f"⏱️ Durée audio : {voice_duration:.1f} s")

    if video_format == "portrait":
        if voice_duration <= SHORT_MIN_DURATION:
            raise ShortTooShortError(f"Audio trop court : {voice_duration:.1f}s (min {SHORT_MIN_DURATION:.1f}s)")
        if voice_duration > SHORT_MAX_DURATION:
            raise ShortTooLongError(f"Audio trop long : {voice_duration:.1f}s (max {SHORT_MAX_DURATION:.0f}s)")
        status_cb(f"✅ Durée validée : {voice_duration:.1f} s")

    if PEXELS_API_KEY:
        status_cb("🎬 Pexels : actif (primaire)")
    if PIXABAY_API_KEY:
        status_cb("🎬 Pixabay : actif (secondaire)")
    if not PEXELS_API_KEY and not PIXABAY_API_KEY:
        status_cb("⚠️ Aucune clé API → fallback fond coloré")

    status_cb("🎥 Recherche des clips vidéo...")
    video_clips = []
    used_urls = set()
    video_success = 0
    video_fail = 0

    if video_format == "portrait":
        mascot_scale = int(width * 0.19)
        mascot_positions = [("(W-w)/2", "H-h-470"), ("40", "H-h-470"), ("W-w-40", "H-h-470")]
    else:
        mascot_scale = int(width * 0.14)
        mascot_positions = [("40", "H-h-40"), ("W-w-40", "H-h-40"), ("40", "H-h-120")]

    for idx, scene in enumerate(script_scenes):
        duration = max(0.5, float(scene.get("duration", 1.0)))
        intensity = int(scene.get("intensity", 3))
        emotion = scene.get("emotion", "default")

        if mascot_available:
            mascot_img = MASCOT_FILES.get(emotion, MASCOT_FILES["default"])
            if not mascot_img.exists():
                mascot_img = MASCOT_FILES["default"]
            if not mascot_img.exists():
                mascot_img = None
        else:
            mascot_img = None

        query = scene.get("visual_query", "person walking")
        status_cb(f"🎬 Clip {idx+1}/{total_scenes} : {query}")

        visual_file = work_dir / f"src_vis_{idx:03d}.mp4"
        output_clip = work_dir / f"clip_{idx:03d}.mp4"
        pos_x, pos_y = mascot_positions[idx % len(mascot_positions)]
        mascot_duration = min(2.5, duration)
        enable_expr = f"between(t,0,{mascot_duration})"

        got_clip = False

        if PEXELS_API_KEY:
            url = search_pexels_video(query, orientation, used_urls=used_urls)
            if url and download_file(url, visual_file):
                used_urls.add(url)
                got_clip = True
                video_success += 1

        if PIXABAY_API_KEY and not got_clip:
            url = search_pixabay_video(query, orientation, used_urls=used_urls)
            if url and download_file(url, visual_file):
                used_urls.add(url)
                got_clip = True
                video_success += 1

        if got_clip:
            create_video_clip_from_pexels(
                visual_file, mascot_img, output_clip, duration,
                width, height, mascot_scale, pos_x, pos_y,
                enable_expr, work_dir, intensity=intensity,
            )
        else:
            video_fail += 1
            status_cb(f"⚠️ Fallback clip {idx+1}")
            create_fallback_video_clip(
                output_clip, mascot_img, duration,
                width, height, mascot_scale, pos_x, pos_y,
                enable_expr, work_dir, intensity=intensity,
            )

        video_clips.append(output_clip)

    status_cb(f"📊 Vidéos : {video_success} clips trouvés, {video_fail} fallbacks")
    if video_success == 0:
        status_cb("⚠️ Aucun clip trouvé. Vérifie tes clés API.")

    status_cb("⚡ Fusion des scènes...")
    raw_video = work_dir / "raw_video.mp4"

    if len(video_clips) == 1:
        shutil.copy(video_clips[0], raw_video)
    else:
        concat_file = work_dir / "concat_video.txt"
        with open(concat_file, "w", encoding="utf-8") as f:
            for v in video_clips:
                f.write(f"file '{v.name}'\n")
        run_command([FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0", "-i", "concat_video.txt",
                     "-c", "copy", "raw_video.mp4"], cwd=work_dir)

    status_cb("💬 Sous-titres karaoké...")
    subtitles_file = work_dir / "subtitles.ass"
    create_ass_subtitles(script_scenes, subtitles_file, width, height)

    status_cb("🎬 Rendu final...")
    watermark_y = 55 if video_format == "portrait" else 35

    vf_filter = (
        "subtitles=subtitles.ass,"
        "drawtext=text='CERVEAU CURIEUX':x=35:y=" + str(watermark_y) + ":"
        "fontsize=25:fontcolor=white:box=1:boxcolor=black@0.45:boxborderw=7"
    )

    final_output = OUTPUT_DIR / f"export_{int(time.time())}_{video_format}.mp4"

    cmd_final = [FFMPEG_BIN, "-y", "-i", "raw_video.mp4", "-i", "full_audio.m4a",
                 "-vf", vf_filter, "-map", "0:v:0", "-map", "1:a:0",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                 "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                 "-shortest", "-movflags", "+faststart", str(final_output.resolve())]
    run_command(cmd_final, cwd=work_dir)

    status_cb("🔍 QC final...")
    final_duration = qc_validate_video(
        final_output,
        expected_format=("portrait" if video_format == "portrait" else "landscape"),
    )

    if video_format == "portrait":
        if final_duration <= SHORT_MIN_DURATION:
            raise ShortTooShortError(f"QC : {final_duration:.1f}s trop court.")
        if final_duration > SHORT_MAX_DURATION:
            raise ShortTooLongError(f"QC : {final_duration:.1f}s trop long.")

    status_cb(f"✅ Vidéo validée : {final_duration:.1f} s")
    return final_output


# ============================================================
# SPLIT
# ============================================================

def split_video_in_two(input_video, total_duration, out_dir):
    mid_point = total_duration / 2.0
    part1 = out_dir / f"{input_video.stem}_Part1.mp4"
    part2 = out_dir / f"{input_video.stem}_Part2.mp4"

    run_command([FFMPEG_BIN, "-y", "-i", str(input_video), "-t", str(mid_point),
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                 "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(part1)])
    run_command([FFMPEG_BIN, "-y", "-ss", str(mid_point), "-i", str(input_video),
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                 "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(part2)])
    return part1, part2


# ============================================================
# SESSION
# ============================================================

def initialize_session_state():
    defaults = {
        "generation_done": False, "ai_data": None, "format_choisi": None,
        "title": None, "video_path": None, "topic_generated": "",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def save_generation_result(ai_data, format_choisi, video_path, topic):
    st.session_state.generation_done = True
    st.session_state.ai_data = ai_data
    st.session_state.format_choisi = format_choisi
    st.session_state.title = ai_data.get("title", "Pourquoi ton cerveau fait ça")
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
# AFFICHAGE
# ============================================================

def render_results():
    if not st.session_state.get("generation_done", False):
        return

    ai_data = st.session_state.ai_data
    format_choisi = st.session_state.format_choisi
    video_path = st.session_state.video_path
    title = st.session_state.title

    if not ai_data or not video_path:
        return

    st.markdown("---")
    st.markdown("## 🍿 Ton contenu est prêt !")

    info_tab, video_tab = st.tabs(["📄 Informations", "🎥 Vidéo(s)"])

    with info_tab:
        st.info(f"**Titre suggéré :** {title}")
        st.write("**Hashtags :** " + " ".join(ai_data.get("hashtags", [])))
        word_count = count_words_in_scenes(ai_data.get("script_principal", []))
        st.write(f"📝 **Narration : {word_count} mots**")

        st.markdown("---")
        if NASHEED_FILE.exists():
            st.success("🎵 Nasheed : actif")
        else:
            st.info("🎵 Nasheed : `nasheed.mp3` non détecté.")

        active_sfx = []
        if WHOOSH_SFX_FILE.exists(): active_sfx.append("whoosh")
        if POP_SFX_FILE.exists(): active_sfx.append("pop")
        if DING_SFX_FILE.exists(): active_sfx.append("ding")
        if active_sfx:
            st.caption("🔊 SFX actifs : " + ", ".join(active_sfx))

        with st.expander("📜 Voir le script complet"):
            script_complet = ""
            for idx, scene in enumerate(ai_data.get("script_principal", [])):
                script_complet += (
                    f"Scène {idx+1} [{scene.get('emotion','')} • int {scene.get('intensity',3)}]\n"
                    f"  VISUEL: {scene.get('visual_query','')}\n"
                    f"  TEXTE: {scene.get('text','')}\n\n"
                )
            st.code(script_complet, language="text")

    with video_tab:
        if format_choisi == "short_single":
            vf = Path(str(video_path))
            if not vf.exists():
                st.error("Fichier vidéo plus disponible.")
                return
            final_duration = get_media_duration(vf)
            st.success(f"Durée finale : **{final_duration:.1f} s**")
            st.video(str(vf))
            with open(vf, "rb") as fh:
                st.download_button("⬇️ Télécharger la vidéo", data=fh.read(),
                                   file_name=vf.name, mime="video/mp4",
                                   on_click="ignore", key="dl_short_single",
                                   type="primary", use_container_width=True)

        elif format_choisi == "short_twoparts":
            paths = [Path(str(x)) for x in video_path]
            if len(paths) < 2:
                st.error("Parties indisponibles.")
                return
            c1, c2 = st.columns(2)
            for col, p, label, key in [(c1, paths[0], "Partie 1", "dl_p1"), (c2, paths[1], "Partie 2", "dl_p2")]:
                with col:
                    st.caption(label)
                    st.video(str(p))
                    if p.exists():
                        with open(p, "rb") as f:
                            st.download_button(f"⬇️ {label}", data=f.read(),
                                               file_name=p.name, mime="video/mp4",
                                               on_click="ignore", key=key, use_container_width=True)

        elif format_choisi == "long_plus_teaser":
            paths = [Path(str(x)) for x in video_path]
            if len(paths) < 2:
                st.error("Fichiers indisponibles.")
                return
            st.subheader("📺 Format Long (16:9)")
            st.video(str(paths[0]))
            if paths[0].exists():
                with open(paths[0], "rb") as f:
                    st.download_button("⬇️ Vidéo longue", data=f.read(),
                                       file_name=paths[0].name, mime="video/mp4",
                                       on_click="ignore", key="dl_long",
                                       type="primary", use_container_width=True)
            st.divider()
            st.subheader("📱 Teaser Short (9:16)")
            st.video(str(paths[1]))
            if paths[1].exists():
                with open(paths[1], "rb") as f:
                    st.download_button("⬇️ Teaser", data=f.read(),
                                       file_name=paths[1].name, mime="video/mp4",
                                       on_click="ignore", key="dl_teaser",
                                       type="primary", use_container_width=True)


# ============================================================
# MAIN
# ============================================================

def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="🧠",
                       layout="centered", initial_sidebar_state="expanded")

    initialize_session_state()

    st.markdown("""
        <style>
        .stApp { background-color: #0E1117; }
        div.stButton > button:first-child {
            background: linear-gradient(90deg, #FF4B4B 0%, #FF8F8F 100%);
            color: white; border: none; border-radius: 12px;
            padding: 0.6rem 1rem; font-size: 1.2rem;
            font-weight: 700; width: 100%;
            box-shadow: 0 4px 6px rgba(255,75,75,0.2);
        }
        div.stButton > button:first-child:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 15px rgba(255,75,75,0.4);
            color: white;
        }
        .main-title { text-align: center; font-size: 3rem; font-weight: 800; color: #FFF; margin-bottom: 0; }
        .sub-title { text-align: center; font-size: 1.2rem; color: #A0AEC0; margin-top: 0; margin-bottom: 30px; }
        .stTextArea textarea {
            background-color: #1A1C24; border: 1px solid #2D3748;
            border-radius: 10px; color: #E2E8F0; font-size: 1.1rem;
        }
        </style>
    """, unsafe_allow_html=True)

    with st.sidebar:
        st.markdown("<h3 style='text-align:center;'>Tableau de bord</h3>", unsafe_allow_html=True)

        if MASCOT_FILES["default"].exists():
            st.image(str(MASCOT_FILES["default"]), use_container_width=True)
            st.caption("✅ Mascotte active")
        else:
            st.warning("⚠️ Aucune mascotte détectée")

        st.markdown("---")
        st.markdown("🎯 **Mode Autonome Actif**")
        st.write("Gemini + Edge-TTS + Pexels + Pixabay + FFmpeg.")

        st.markdown("---")
        st.markdown("### 🎥 Vidéo")
        if PEXELS_API_KEY:
            st.success("Pexels : connecté")
        else:
            st.error("Pexels : clé manquante")

        if PIXABAY_API_KEY:
            st.success("Pixabay : connecté")
        else:
            st.info("Pixabay : non configuré (optionnel)")

        st.markdown("---")
        st.markdown("### 🎵 Audio")
        if NASHEED_FILE.exists():
            st.success("Nasheed actif")
        else:
            st.info("Nasheed désactivé")

        sfx_count = sum([WHOOSH_SFX_FILE.exists(), POP_SFX_FILE.exists(), DING_SFX_FILE.exists()])
        st.caption(f"🔊 {sfx_count}/3 bruitages disponibles")
        st.markdown("---")
        st.caption("✨ v6 Action Video Edition")

    st.markdown('<div class="main-title">🧠 Cerveau Curieux</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-title">Studio IA Autonome 🎬</div>', unsafe_allow_html=True)

    cleanup_old_temp_dirs()

    st.markdown("### 📝 Quel est ton sujet aujourd'hui ?")
    topic = st.text_area(
        "Sujet",
        placeholder="Ex: Pourquoi le cerveau oublie-t-il ce qu'il est venu chercher en passant une porte ?",
        label_visibility="collapsed", height=120, key="topic_input",
    )

    if st.button("🚀 LANCER LA GÉNÉRATION", key="generate_video_button"):
        if not topic.strip():
            st.warning("⚠️ Écris un sujet d'abord.")
            return

        clear_generation_result()

        with st.status("🎬 Allumage des caméras...", expanded=True) as status_box:
            try:
                def update_status(msg):
                    st.write(msg)

                ai_data, gemini_client = generate_script_gemini(topic, update_status)
                format_choisi = ai_data.get("format_choisi", "short_single")
                title = ai_data.get("title", "Pourquoi ton cerveau fait ça")

                wc = count_words_in_scenes(ai_data.get("script_principal", []))
                st.write(f"✅ Format : **{format_choisi}**")
                st.write(f"📝 Narration initiale : **{wc} mots**")

                if format_choisi in ("short_single", "short_twoparts"):
                    max_repair = 2
                    attempt = 0
                    while True:
                        try:
                            full_video_path = generate_video_pipeline(
                                ai_data.get("script_principal", []), "portrait", update_status)
                            break
                        except (ShortTooShortError, ShortTooLongError) as e:
                            attempt += 1
                            if attempt > max_repair:
                                raise RuntimeError(str(e))
                            m = re.search(r"([0-9]+(?:\.[0-9]+)?)", str(e))
                            dur = float(m.group(1)) if m else 44.0
                            ai_data = repair_script_by_real_duration(
                                gemini_client, topic, ai_data, dur, update_status)
                            st.write(f"📝 Nouveau script : "
                                     f"**{count_words_in_scenes(ai_data.get('script_principal', []))} mots**")

                    if format_choisi == "short_twoparts":
                        update_status("✂️ Découpage en 2 parties...")
                        total_dur = get_media_duration(full_video_path)
                        p1, p2 = split_video_in_two(full_video_path, total_dur, OUTPUT_DIR)
                        video_path = [p1, p2]
                    else:
                        video_path = full_video_path

                elif format_choisi == "long_plus_teaser":
                    long_path = generate_video_pipeline(
                        ai_data.get("script_principal", []), "landscape", update_status)
                    teaser = ai_data.get("script_teaser", [])
                    if not teaser:
                        raise RuntimeError("Teaser vide.")
                    short_path = generate_video_pipeline(teaser, "portrait", update_status)
                    video_path = [long_path, short_path]

                else:
                    raise RuntimeError(f"Format inconnu : {format_choisi}")

                save_generation_result(ai_data, format_choisi, video_path, topic)
                status_box.update(label="🎉 Production terminée !", state="complete", expanded=False)

            except Exception as e:
                status_box.update(label="❌ Une erreur s'est produite.", state="error", expanded=True)
                st.error(str(e))
                return

    render_results()


if __name__ == "__main__":
    main()
