import os
import re
import time
import shutil
import random
import subprocess
from pathlib import Path
from typing import List, Dict, Tuple, Optional

import requests
import streamlit as st
import edge_tts
from PIL import Image


# ============================================================
# CONFIGURATION
# ============================================================

APP_TITLE = "Studio Vidéo IA"

OPENROUTER_MODEL = "meta-llama/llama-3.3-70b-instruct"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"

OUTPUT_DIR = Path("outputs")
TEMP_DIR = Path("temp")

OUTPUT_DIR.mkdir(exist_ok=True)
TEMP_DIR.mkdir(exist_ok=True)

CTA = "Abonne-toi pour en savoir plus sur le monde."

PREFERRED_VOICES = [
    "fr-FR-HenriNeural",
    "fr-FR-DeniseNeural",
    "fr-FR-EloiseNeural",
    "fr-FR-RemyMultilingualNeural",
    "fr-FR-VivienneMultilingualNeural",
]


# ============================================================
# ROUTAGE DES CONTENUS
# ============================================================

MIN_WORDS = 200

ONE_SHORT_MAX = 349
TWO_SHORT_MAX = 699

LONG_MAX_RECOMMENDED = 1000

SHORT_MIN_SECONDS = 20
SHORT_TARGET_MIN_SECONDS = 25
SHORT_TARGET_MAX_SECONDS = 40
SHORT_MAX_SECONDS = 45


# ============================================================
# OUTILS GÉNÉRAUX
# ============================================================

def get_secret(name: str, default: str = "") -> str:
    """
    Récupère une variable depuis st.secrets ou os.environ.
    """
    try:
        value = st.secrets.get(name)
        if value:
            return str(value)
    except Exception:
        pass

    return os.getenv(name, default)


def clean_text(text: str) -> str:
    """
    Nettoyage basique du texte.
    """
    if not text:
        return ""

    text = text.replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)

    return text.strip()


def count_words(text: str) -> int:
    """
    Compte les mots en ignorant les marqueurs [IMAGE: ...].
    """
    if not text:
        return 0

    without_images = re.sub(
        r"\[IMAGE:\s*(.*?)\]",
        " ",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    words = re.findall(r"\b[\wÀ-ÿ'-]+\b", without_images)

    return len(words)


def format_seconds(seconds: float) -> str:
    """
    Convertit des secondes en MM:SS.
    """
    seconds = max(0, int(round(seconds)))

    minutes = seconds // 60
    remaining = seconds % 60

    return f"{minutes:02d}:{remaining:02d}"


def run_command(
    command: List[str],
    timeout: int = 300,
) -> subprocess.CompletedProcess:
    """
    Exécute une commande système et remonte une erreur lisible.
    """
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Commande échouée:\n"
            + " ".join(command)
            + "\n\n"
            + result.stderr[-4000:]
        )

    return result


def ensure_ffmpeg() -> None:
    """
    Vérifie que FFmpeg et FFprobe sont disponibles.
    """
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "FFmpeg est introuvable. "
            "Ajoutez un fichier apt.txt contenant simplement : ffmpeg"
        )

    if shutil.which("ffprobe") is None:
        raise RuntimeError(
            "FFprobe est introuvable. "
            "Ajoutez un fichier apt.txt contenant simplement : ffmpeg"
        )


# ============================================================
# OPENROUTER
# ============================================================

def openrouter_request(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.7,
    max_tokens: int = 5000,
) -> str:
    """
    Appelle OpenRouter.
    """

    api_key = get_secret("OPENROUTER_API_KEY")

    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY est absente. "
            "Ajoutez-la dans les variables d'environnement de Render."
        )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://shorts-viraux-1.onrender.com",
        "X-Title": APP_TITLE,
    }

    payload = {
        "model": OPENROUTER_MODEL,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
    }

    try:
        response = requests.post(
            OPENROUTER_URL,
            headers=headers,
            json=payload,
            timeout=180,
        )
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Impossible de contacter OpenRouter : {exc}"
        ) from exc

    if response.status_code != 200:
        try:
            details = response.json()
        except Exception:
            details = response.text

        raise RuntimeError(
            f"OpenRouter a renvoyé HTTP {response.status_code} :\n"
            f"{details}"
        )

    try:
        data = response.json()
    except Exception as exc:
        raise RuntimeError(
            "La réponse d'OpenRouter n'est pas un JSON valide."
        ) from exc

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(
            f"Réponse OpenRouter inattendue : {data}"
        ) from exc

    if not content or not str(content).strip():
        raise RuntimeError(
            "OpenRouter a renvoyé une réponse vide."
        )

    return str(content).strip()


# ============================================================
# GÉNÉRATION DU SCRIPT PRINCIPAL
# ============================================================

def generate_main_script(topic: str, retry: bool = False) -> str:
    """
    Génère le script historique principal.

    Le script doit être factuel et comporter des marqueurs
    [IMAGE: mots-clés en anglais].
    """

    if retry:
        target = """
Le premier résultat était trop court.

Vous devez impérativement produire au moins 200 mots.
Visez idéalement 500 à 800 mots.
"""
    else:
        target = """
Visez environ 550 à 900 mots.
"""

    system_prompt = """
Vous êtes un scénariste spécialisé dans l'histoire mondiale.

Votre priorité absolue est l'exactitude historique.

RÈGLES STRICTES :

1. Ne jamais inventer de faits.
2. Ne jamais inventer de dates, personnes, citations ou événements.
3. Si un détail est incertain ou controversé, ne pas le présenter
   comme une certitude.
4. Le récit doit être compréhensible par le grand public.
5. Le début doit avoir un hook fort.
6. Le récit doit rester chronologique lorsque cela est pertinent.
7. Éviter les longues introductions.
8. Utiliser des phrases naturelles adaptées à une narration vocale.
9. Ne pas mettre de titre dans le corps du récit.
10. Ne pas ajouter de bibliographie.
11. Ne pas utiliser de Markdown inutile.

Pour les images, insérer régulièrement des marqueurs exactement
sous cette forme :

[IMAGE: english visual keywords]

Les mots-clés des images doivent être en anglais afin d'améliorer
les recherches sur les banques d'images.

Les marqueurs [IMAGE: ...] ne comptent pas comme des mots du script.
"""

    user_prompt = f"""
Créez un script YouTube sur le sujet suivant :

{topic}

{target}

Structure recommandée :

- Hook très accrocheur
- Contexte
- Développement
- Moment important
- Conséquences
- Conclusion

Le script doit raconter une histoire historique réelle,
intéressante et vérifiable.

Ajoutez suffisamment de marqueurs [IMAGE: ...] pour permettre
une illustration visuelle régulière.

Terminez par :

{CTA}
"""

    return clean_text(
        openrouter_request(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.65,
            max_tokens=5000,
        )
    )


# ============================================================
# DÉTERMINATION DU FORMAT
# ============================================================

def choose_content_mode(word_count: int) -> str:
    """
    Détermine automatiquement le format à produire.

    < 200       -> régénération
    200-349     -> 1 Short
    350-699     -> 2 Shorts
    >= 700      -> vidéo longue + teaser
    """

    if word_count < MIN_WORDS:
        return "REGENERATE"

    if word_count <= ONE_SHORT_MAX:
        return "ONE_SHORT"

    if word_count <= TWO_SHORT_MAX:
        return "TWO_SHORTS"

    return "LONG_PLUS_TEASER"


# ============================================================
# GÉNÉRATION D'UN SHORT
# ============================================================

def generate_one_short(topic: str, source_script: str) -> str:
    """
    Transforme une histoire en un Short cohérent de 25 à 40 secondes.
    """

    system_prompt = """
Vous êtes un scénariste expert en YouTube Shorts historiques.

Transformez le contenu fourni en un Short très dynamique.

RÈGLES :

- Conserver uniquement des faits historiques réels.
- Ne rien inventer.
- Ne pas modifier le sens historique.
- Commencer immédiatement avec un hook.
- Viser environ 60 à 100 mots.
- Viser environ 25 à 40 secondes de narration.
- Ajouter environ 7 à 12 marqueurs visuels.
- Les marqueurs doivent être exactement :
  [IMAGE: english visual keywords]
- Les mots-clés d'image doivent être en anglais.
- Le texte doit être fluide pour une voix TTS.
- Ne pas mettre de titre.
- Terminer avec le CTA demandé.

Le Short doit donner envie de regarder jusqu'à la fin.
"""

    user_prompt = f"""
SUJET :
{topic}

SCRIPT SOURCE :
{source_script}

Créez maintenant une version Short de 60 à 100 mots.

Terminez exactement par :

{CTA}
"""

    return clean_text(
        openrouter_request(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.7,
            max_tokens=1800,
        )
    )


# ============================================================
# GÉNÉRATION DE DEUX SHORTS
# ============================================================

def generate_two_shorts(
    topic: str,
    source_script: str,
) -> Tuple[str, str]:
    """
    Restructure une histoire de 350 à 699 mots en deux Shorts.

    IMPORTANT :
    On ne coupe PAS simplement le texte en deux.
    Le modèle reconstruit deux parties cohérentes.
    """

    system_prompt = """
Vous êtes un scénariste expert en YouTube Shorts historiques.

Vous devez transformer une histoire relativement longue en
DEUX Shorts complémentaires.

IMPORTANT :
Ne coupez surtout pas le texte original en deux moitiés.

Vous devez restructurer et condenser l'histoire pour obtenir
deux Shorts cohérents.

CONTRAINTES POUR CHAQUE PARTIE :

- environ 60 à 100 mots
- environ 25 à 40 secondes
- environ 7 à 12 marqueurs [IMAGE: ...]
- uniquement des faits historiques réels
- aucune invention
- narration naturelle
- hook fort
- phrases courtes et dynamiques
- mots-clés visuels en anglais

PARTIE 1 :

Elle doit contenir :
- le hook
- le contexte
- le début de l'histoire
- les premiers événements
- une fin qui donne envie de voir la partie 2

PARTIE 2 :

Elle doit contenir :
- la continuation directe
- l'événement principal
- les conséquences
- une conclusion satisfaisante

Les deux parties doivent rester fidèles aux faits
et respecter la chronologie lorsque celle-ci est importante.

Format obligatoire :

=== PARTIE 1 ===
texte

=== PARTIE 2 ===
texte
"""

    user_prompt = f"""
SUJET :
{topic}

HISTOIRE SOURCE :
{source_script}

Transformez cette histoire en deux Shorts.

Terminez la PARTIE 2 par :

{CTA}
"""

    result = clean_text(
        openrouter_request(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.65,
            max_tokens=3000,
        )
    )

    match = re.search(
        r"===\s*PARTIE\s*1\s*===\s*(.*?)"
        r"===\s*PARTIE\s*2\s*===\s*(.*)",
        result,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if not match:
        raise RuntimeError(
            "Le modèle n'a pas respecté le format demandé "
            "pour les deux Shorts."
        )

    part1 = clean_text(match.group(1))
    part2 = clean_text(match.group(2))

    if count_words(part1) < 40 or count_words(part2) < 40:
        raise RuntimeError(
            "Une des deux parties générées est trop courte."
        )

    return part1, part2


# ============================================================
# GÉNÉRATION DU TEASER
# ============================================================

def generate_teaser(
    topic: str,
    source_script: str,
) -> str:
    """
    Génère un teaser vertical pour accompagner une vidéo longue.
    """

    system_prompt = """
Vous êtes un spécialiste des teasers YouTube Shorts.

Créez un teaser très accrocheur à partir de l'histoire fournie.

CONTRAINTES :

- 70 à 100 mots environ
- 25 à 40 secondes environ
- hook très fort dès la première phrase
- ne pas raconter toute l'histoire
- créer de la curiosité
- conserver uniquement des faits réels
- ne rien inventer
- ajouter 7 à 12 marqueurs visuels
- format exact :
  [IMAGE: english visual keywords]
- mots-clés visuels en anglais
- narration naturelle pour TTS
- terminer par le CTA
"""

    user_prompt = f"""
SUJET :
{topic}

SCRIPT :
{source_script}

Créez un teaser Short qui donne envie de regarder
la vidéo longue.

Terminez exactement par :

{CTA}
"""

    return clean_text(
        openrouter_request(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.75,
            max_tokens=1800,
        )
    )# ============================================================
# PARSING DES MARQUEURS IMAGE
# ============================================================

IMAGE_MARKER_PATTERN = re.compile(
    r"\[IMAGE:\s*(.*?)\]",
    flags=re.IGNORECASE | re.DOTALL,
)


def extract_image_markers(text: str) -> List[str]:
    """
    Extrait les descriptions d'images du script.
    """
    if not text:
        return []

    markers = IMAGE_MARKER_PATTERN.findall(text)

    cleaned = []

    for marker in markers:
        marker = re.sub(r"\s+", " ", marker).strip()

        if marker:
            cleaned.append(marker)

    return cleaned


def remove_image_markers(text: str) -> str:
    """
    Supprime les marqueurs [IMAGE: ...] du texte destiné à la voix.
    """
    if not text:
        return ""

    text = IMAGE_MARKER_PATTERN.sub(" ", text)

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def validate_script_images(text: str) -> None:
    """
    Vérifie que le script possède suffisamment de marqueurs visuels.
    """

    markers = extract_image_markers(text)

    if not markers:
        raise RuntimeError(
            "Aucun marqueur [IMAGE: ...] n'a été trouvé dans le script."
        )


# ============================================================
# PEXELS
# ============================================================

def pexels_headers() -> Dict[str, str]:
    """
    Prépare les headers Pexels.
    """

    api_key = get_secret("PEXELS_API_KEY")

    if not api_key:
        raise RuntimeError(
            "PEXELS_API_KEY est absente. "
            "Ajoutez-la dans les variables d'environnement de Render."
        )

    return {
        "Authorization": api_key,
    }


def download_file(
    url: str,
    output_path: Path,
    timeout: int = 60,
) -> bool:
    """
    Télécharge un fichier distant.
    """

    try:
        response = requests.get(
            url,
            timeout=timeout,
            stream=True,
        )

        response.raise_for_status()

        with open(output_path, "wb") as file:
            for chunk in response.iter_content(chunk_size=1024 * 64):
                if chunk:
                    file.write(chunk)

        return output_path.exists() and output_path.stat().st_size > 1000

    except Exception:
        try:
            if output_path.exists():
                output_path.unlink()
        except Exception:
            pass

        return False


def search_pexels_photo(
    query: str,
    orientation: str = "landscape",
) -> Optional[str]:
    """
    Recherche une image sur Pexels.

    Retourne l'URL de la meilleure image trouvée.
    """

    query = clean_text(query)

    if not query:
        return None

    headers = pexels_headers()

    params = {
        "query": query,
        "per_page": 10,
        "orientation": orientation,
    }

    try:
        response = requests.get(
            PEXELS_SEARCH_URL,
            headers=headers,
            params=params,
            timeout=30,
        )

        if response.status_code != 200:
            return None

        data = response.json()

    except Exception:
        return None

    photos = data.get("photos", [])

    if not photos:
        return None

    random.shuffle(photos)

    for photo in photos:
        source = photo.get("src", {})

        candidates = [
            source.get("large2x"),
            source.get("large"),
            source.get("original"),
            source.get("medium"),
        ]

        for candidate in candidates:
            if candidate:
                return candidate

    return None


# ============================================================
# PLACEHOLDER VISUEL
# ============================================================

def create_placeholder(
    output_path: Path,
    width: int,
    height: int,
    label: str = "Visual indisponible",
) -> Path:
    """
    Crée une image de secours si aucune image n'est disponible.
    """

    image = Image.new(
        "RGB",
        (width, height),
        (28, 28, 32),
    )

    try:
        from PIL import ImageDraw, ImageFont

        draw = ImageDraw.Draw(image)

        try:
            font = ImageFont.truetype(
                "DejaVuSans.ttf",
                48,
            )
        except Exception:
            font = ImageFont.load_default()

        bbox = draw.textbbox(
            (0, 0),
            label,
            font=font,
        )

        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        x = (width - text_width) / 2
        y = (height - text_height) / 2

        draw.text(
            (x, y),
            label,
            font=font,
            fill=(230, 230, 230),
        )

    except Exception:
        pass

    image.save(
        output_path,
        format="JPEG",
        quality=90,
    )

    return output_path


# ============================================================
# RÉCUPÉRATION DES VISUELS
# ============================================================

def get_visuals(
    script: str,
    output_dir: Path,
    orientation: str,
    expected_count: int,
) -> List[Path]:
    """
    Recherche et télécharge les visuels nécessaires.

    Un visuel est associé à chaque marqueur [IMAGE: ...].
    Si Pexels échoue, un placeholder est utilisé.
    """

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    markers = extract_image_markers(script)

    if not markers:
        raise RuntimeError(
            "Impossible de créer les visuels : "
            "aucun marqueur [IMAGE: ...]."
        )

    # On limite le nombre d'images pour éviter une génération
    # inutilement lourde.
    markers = markers[:expected_count]

    width = 1080 if orientation == "portrait" else 1920
    height = 1920 if orientation == "portrait" else 1080

    visuals: List[Path] = []

    progress = st.progress(
        0,
        text="Recherche des visuels...",
    )

    for index, query in enumerate(markers, start=1):
        output_path = output_dir / f"visual_{index:03d}.jpg"

        image_url = search_pexels_photo(
            query=query,
            orientation=orientation,
        )

        success = False

        if image_url:
            success = download_file(
                image_url,
                output_path,
            )

        if not success:
            create_placeholder(
                output_path,
                width,
                height,
                f"Visual {index}",
            )

        visuals.append(output_path)

        progress.progress(
            index / len(markers),
            text=f"Visuel {index}/{len(markers)}",
        )

        time.sleep(0.15)

    progress.empty()

    if not visuals:
        raise RuntimeError(
            "Aucun visuel n'a pu être préparé."
        )

    return visuals


# ============================================================
# CALCUL DU NOMBRE DE VISUELS
# ============================================================

def visual_count_for_duration(
    duration: float,
    vertical: bool,
) -> int:
    """
    Détermine automatiquement le nombre de visuels.

    Shorts :
        environ 1 visuel toutes les 3 secondes
        minimum 7
        maximum 14

    Vidéo longue :
        environ 1 visuel toutes les 6 secondes
        minimum 12
        maximum 36
    """

    duration = max(1.0, float(duration))

    if vertical:
        count = round(duration / 3.0)
        return max(7, min(14, count))

    count = round(duration / 6.0)
    return max(12, min(36, count))


# ============================================================
# EDGE TTS
# ============================================================

def get_available_french_voices() -> List[str]:
    """
    Récupère les voix françaises disponibles.

    Retourne les voix préférées en priorité.
    """

    try:
        voices = edge_tts.list_voices()
    except Exception:
        return PREFERRED_VOICES.copy()

    available = []

    for voice in voices:
        short_name = voice.get("ShortName", "")

        if short_name.startswith("fr-FR-"):
            available.append(short_name)

    ordered = []

    for preferred in PREFERRED_VOICES:
        if preferred in available:
            ordered.append(preferred)

    for voice in available:
        if voice not in ordered:
            ordered.append(voice)

    return ordered or PREFERRED_VOICES.copy()


def synthesize_with_voice(
    text: str,
    voice: str,
    output_path: Path,
) -> List[Dict]:
    """
    Synthétise la narration et récupère les timings mot-à-mot.
    """

    communicate = edge_tts.Communicate(
        text,
        voice,
        rate="+5%",
        volume="+0%",
        pitch="+0Hz",
        boundary="WordBoundary",
    )

    timings: List[Dict] = []
    audio_received = False

    with open(output_path, "wb") as audio_file:

        for chunk in communicate.stream_sync():

            chunk_type = chunk.get("type")

            if chunk_type == "audio":

                data = chunk.get(
                    "data",
                    b"",
                )

                if data:
                    audio_received = True
                    audio_file.write(data)

            elif chunk_type == "WordBoundary":

                offset = chunk.get("offset")
                duration = chunk.get("duration")
                word = chunk.get("text", "")

                if offset is not None:

                    timings.append(
                        {
                            "word": word,
                            "start": float(offset) / 10_000_000,
                            "duration": (
                                float(duration) / 10_000_000
                                if duration is not None
                                else 0.1
                            ),
                        }
                    )

    if not audio_received:
        raise RuntimeError(
            f"Aucune donnée audio reçue avec la voix {voice}."
        )

    if (
        not output_path.exists()
        or output_path.stat().st_size < 1000
    ):
        raise RuntimeError(
            f"Le fichier audio généré avec {voice} est invalide."
        )

    return timings


def get_audio_duration(
    audio_path: Path,
) -> float:
    """
    Récupère la durée exacte d'un fichier audio avec FFprobe.
    """

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
        timeout=60,
    )

    try:
        duration = float(result.stdout.strip())
    except Exception as exc:
        raise RuntimeError(
            "Impossible de déterminer la durée audio."
        ) from exc

    if duration <= 0:
        raise RuntimeError(
            "La durée audio retournée par FFprobe est invalide."
        )

    return duration


def generate_audio(
    text: str,
    output_path: Path,
) -> Tuple[Path, List[Dict], float, str]:
    """
    Génère la narration avec plusieurs voix de secours.
    """

    voices = get_available_french_voices()

    last_error = None

    for voice in voices[:5]:

        try:

            timings = synthesize_with_voice(
                text=text,
                voice=voice,
                output_path=output_path,
            )

            duration = get_audio_duration(
                output_path,
            )

            return (
                output_path,
                timings,
                duration,
                voice,
            )

        except Exception as exc:

            last_error = exc

            try:
                if output_path.exists():
                    output_path.unlink()
            except Exception:
                pass

            time.sleep(1.5)

    raise RuntimeError(
        "Toutes les voix TTS ont échoué. "
        f"Dernière erreur : {last_error}"
        )# ============================================================
# SOUS-TITRES ASS
# ============================================================

def ass_time(seconds: float) -> str:
    """
    Convertit des secondes en format ASS :
    H:MM:SS.cc
    """

    seconds = max(0.0, float(seconds))

    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    remaining = seconds % 60

    centiseconds = int(round(remaining * 100))

    if centiseconds >= 100:
        centiseconds = 0
        minutes += 1

    if minutes >= 60:
        minutes = 0
        hours += 1

    return (
        f"{hours}:"
        f"{minutes:02d}:"
        f"{int(remaining):02d}."
        f"{centiseconds:02d}"
    )


def escape_ass(text: str) -> str:
    """
    Échappe les caractères spéciaux utilisés par ASS.
    """

    if not text:
        return ""

    text = str(text)

    text = text.replace("\\", r"\\")
    text = text.replace("{", r"\{")
    text = text.replace("}", r"\}")

    return text


def create_ass_subtitles(
    timings: List[Dict],
    output_path: Path,
    vertical: bool = True,
) -> Path:
    """
    Crée des sous-titres mot par mot au format ASS.

    Les sous-titres sont positionnés en bas de l'image
    afin de ne pas masquer la vidéo.
    """

    if vertical:
        play_res_x = 1080
        play_res_y = 1920
        font_size = 58
        margin_v = 180
    else:
        play_res_x = 1920
        play_res_y = 1080
        font_size = 52
        margin_v = 90

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_res_x}
PlayResY: {play_res_y}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{font_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H99000000,1,0,0,0,100,100,0,0,1,3,1,2,70,70,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = [header]

    for item in timings:

        word = str(item.get("word", "")).strip()

        if not word:
            continue

        start = float(
            item.get(
                "start",
                0,
            )
        )

        duration = float(
            item.get(
                "duration",
                0.2,
            )
        )

        end = start + max(
            duration,
            0.08,
        )

        word = escape_ass(word)

        lines.append(
            "Dialogue: 0,"
            f"{ass_time(start)},"
            f"{ass_time(end)},"
            f"Default,,0,0,0,,"
            f"{word}\n"
        )

    output_path.write_text(
        "".join(lines),
        encoding="utf-8",
    )

    return output_path


# ============================================================
# DURÉES DES SCÈNES
# ============================================================

def calculate_scene_durations(
    audio_duration: float,
    scene_count: int,
) -> List[float]:
    """
    Répartit la durée audio entre les scènes.

    La somme des scènes est corrigée afin d'être exactement
    égale à la durée audio.
    """

    audio_duration = max(
        0.1,
        float(audio_duration),
    )

    scene_count = max(
        1,
        int(scene_count),
    )

    if scene_count == 1:
        return [audio_duration]

    # Variation légère pour éviter un montage trop mécanique.
    weights = [
        random.uniform(0.85, 1.15)
        for _ in range(scene_count)
    ]

    total_weight = sum(weights)

    durations = [
        audio_duration * weight / total_weight
        for weight in weights
    ]

    # Une scène ne doit pas être ridiculement courte.
    minimum_scene_duration = 1.25

    for index in range(
        len(durations)
    ):
        if durations[index] < minimum_scene_duration:
            difference = (
                minimum_scene_duration
                - durations[index]
            )

            durations[index] = minimum_scene_duration

            # Retire la différence d'une scène plus longue.
            for donor_index in reversed(
                range(len(durations))
            ):
                if (
                    donor_index != index
                    and durations[donor_index]
                    > minimum_scene_duration + difference
                ):
                    durations[donor_index] -= difference
                    break

    # Correction finale pour garantir une somme exacte.
    difference = audio_duration - sum(durations)

    durations[-1] += difference

    # Protection contre une éventuelle valeur trop faible.
    if durations[-1] <= 0:
        durations[-1] = 0.1

        difference = audio_duration - sum(durations[:-1]) - 0.1

        if difference > 0:
            durations[-2] += difference

    return durations


# ============================================================
# CRÉATION D'UNE SCÈNE VIDÉO
# ============================================================

def create_image_scene(
    image_path: Path,
    output_path: Path,
    duration: float,
    vertical: bool,
) -> Path:
    """
    Transforme une image en clip vidéo avec un léger mouvement
    de zoom afin d'éviter un rendu totalement statique.
    """

    duration = max(
        0.1,
        float(duration),
    )

    if vertical:
        width = 1080
        height = 1920
    else:
        width = 1920
        height = 1080

    # Zoom très léger.
    zoom = 1.04

    filter_complex = (
        f"scale="
        f"{int(width * zoom)}:"
        f"{int(height * zoom)}:"
        f"force_original_aspect_ratio=increase,"
        f"crop={width}:{height},"
        f"zoompan="
        f"z='min(zoom+0.0008,{zoom})':"
        f"d=1:"
        f"s={width}x{height}:"
        f"fps=30"
    )

    command = [
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
        "30",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "22",
        "-pix_fmt",
        "yuv420p",
        str(output_path),
    ]

    run_command(
        command,
        timeout=180,
    )

    if (
        not output_path.exists()
        or output_path.stat().st_size < 5000
    ):
        raise RuntimeError(
            f"La scène vidéo n'a pas été créée : {output_path}"
        )

    return output_path


# ============================================================
# CONCATÉNATION DES SCÈNES
# ============================================================

def concat_scenes(
    scene_paths: List[Path],
    output_path: Path,
) -> Path:
    """
    Assemble toutes les scènes en une seule vidéo.
    """

    if not scene_paths:
        raise RuntimeError(
            "Aucune scène à concaténer."
        )

    concat_file = output_path.parent / (
        output_path.stem + "_concat.txt"
    )

    lines = []

    for scene in scene_paths:
        absolute_path = scene.resolve()

        # Échappement compatible avec le concat demuxer FFmpeg.
        escaped = str(absolute_path).replace(
            "'",
            r"'\''",
        )

        lines.append(
            f"file '{escaped}'\n"
        )

    concat_file.write_text(
        "".join(lines),
        encoding="utf-8",
    )

    command = [
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
    ]

    try:
        run_command(
            command,
            timeout=300,
        )

    except Exception:
        # Fallback : réencodage si le concat copy échoue.
        command = [
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
            "22",
            "-pix_fmt",
            "yuv420p",
            str(output_path),
        ]

        run_command(
            command,
            timeout=300,
        )

    if (
        not output_path.exists()
        or output_path.stat().st_size < 5000
    ):
        raise RuntimeError(
            "La concaténation vidéo a échoué."
        )

    return output_path


# ============================================================
# AUDIO + SOUS-TITRES
# ============================================================

def add_audio_and_subtitles(
    video_path: Path,
    audio_path: Path,
    subtitle_path: Path,
    output_path: Path,
) -> Path:
    """
    Ajoute la narration et les sous-titres au montage final.
    """

    # Le fichier ASS peut contenir des chemins complexes.
    subtitle_filter_path = str(
        subtitle_path.resolve()
    ).replace(
        "\\",
        "/",
    ).replace(
        ":",
        r"\:",
    )

    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(audio_path),
        "-vf",
        f"ass='{subtitle_filter_path}'",
        "-map",
        "0:v:0",
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
        "-shortest",
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    run_command(
        command,
        timeout=600,
    )

    if (
        not output_path.exists()
        or output_path.stat().st_size < 10000
    ):
        raise RuntimeError(
            "La vidéo finale n'a pas été créée correctement."
        )

    return output_path


# ============================================================
# CONSTRUCTION VIDÉO COMPLÈTE
# ============================================================

def build_video(
    visuals: List[Path],
    audio_path: Path,
    timings: List[Dict],
    audio_duration: float,
    output_path: Path,
    vertical: bool,
) -> Path:
    """
    Construit le montage complet :
    images -> scènes -> concaténation -> audio -> sous-titres.
    """

    if not visuals:
        raise RuntimeError(
            "Impossible de construire la vidéo sans visuels."
        )

    work_dir = output_path.parent / (
        output_path.stem + "_work"
    )

    work_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # Le nombre de scènes ne dépasse jamais le nombre de visuels.
    scene_count = min(
        len(visuals),
        max(
            1,
            int(audio_duration / 1.25),
        ),
    )

    selected_visuals = visuals[:scene_count]

    durations = calculate_scene_durations(
        audio_duration=audio_duration,
        scene_count=len(selected_visuals),
    )

    scene_paths: List[Path] = []

    progress = st.progress(
        0,
        text="Création des scènes vidéo...",
    )

    for index, (
        image_path,
        duration,
    ) in enumerate(
        zip(
            selected_visuals,
            durations,
        ),
        start=1,
    ):

        scene_path = work_dir / (
            f"scene_{index:03d}.mp4"
        )

        create_image_scene(
            image_path=image_path,
            output_path=scene_path,
            duration=duration,
            vertical=vertical,
        )

        scene_paths.append(scene_path)

        progress.progress(
            index / len(selected_visuals),
            text=(
                f"Scène {index}/"
                f"{len(selected_visuals)}"
            ),
        )

    progress.empty()

    base_video = work_dir / "base_video.mp4"

    concat_scenes(
        scene_paths=scene_paths,
        output_path=base_video,
    )

    subtitle_path = work_dir / "subtitles.ass"

    create_ass_subtitles(
        timings=timings,
        output_path=subtitle_path,
        vertical=vertical,
    )

    add_audio_and_subtitles(
        video_path=base_video,
        audio_path=audio_path,
        subtitle_path=subtitle_path,
        output_path=output_path,
    )

    return output_path# ============================================================
# CRÉATION D'UN SHORT
# ============================================================

def create_short_video(
    topic: str,
    script: str,
    output_path: Path,
    work_dir: Path,
) -> Tuple[Path, float, str]:
    """
    Génère un Short vertical complet.

    Format :
    1080x1920
    narration TTS
    sous-titres mot par mot
    visuels réguliers
    """

    ensure_ffmpeg()

    script = clean_text(script)

    word_count = count_words(script)

    if word_count < 40:
        raise RuntimeError(
            "Le script du Short est beaucoup trop court."
        )

    validate_script_images(script)

    work_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # Préparation du texte TTS
    # --------------------------------------------------------

    narration_text = remove_image_markers(script)

    if not narration_text:
        raise RuntimeError(
            "Le texte destiné à la narration est vide."
        )

    # --------------------------------------------------------
    # Génération audio
    # --------------------------------------------------------

    audio_path = work_dir / "narration.mp3"

    (
        audio_path,
        timings,
        audio_duration,
        voice,
    ) = generate_audio(
        text=narration_text,
        output_path=audio_path,
    )

    st.info(
        f"Voix utilisée : {voice} | "
        f"Durée : {format_seconds(audio_duration)}"
    )

    # --------------------------------------------------------
    # Vérification durée
    # --------------------------------------------------------

    if audio_duration < SHORT_MIN_SECONDS:

        st.warning(
            "Le Short est plus court que la durée recommandée "
            f"de {SHORT_MIN_SECONDS} secondes."
        )

    elif audio_duration > SHORT_MAX_SECONDS:

        st.warning(
            "Le Short dépasse "
            f"{SHORT_MAX_SECONDS} secondes. "
            "Le montage sera quand même généré."
        )

    elif audio_duration < SHORT_TARGET_MIN_SECONDS:

        st.info(
            "La durée est légèrement inférieure à la cible "
            f"de {SHORT_TARGET_MIN_SECONDS} à "
            f"{SHORT_TARGET_MAX_SECONDS} secondes."
        )

    # --------------------------------------------------------
    # Nombre de visuels
    # --------------------------------------------------------

    visual_count = visual_count_for_duration(
        duration=audio_duration,
        vertical=True,
    )

    visuals_dir = work_dir / "visuals"

    visuals = get_visuals(
        script=script,
        output_dir=visuals_dir,
        orientation="portrait",
        expected_count=visual_count,
    )

    if len(visuals) < 7:

        st.warning(
            "Moins de 7 visuels ont pu être préparés. "
            "Des placeholders peuvent être utilisés."
        )

    # --------------------------------------------------------
    # Montage
    # --------------------------------------------------------

    final_video = build_video(
        visuals=visuals,
        audio_path=audio_path,
        timings=timings,
        audio_duration=audio_duration,
        output_path=output_path,
        vertical=True,
    )

    return (
        final_video,
        audio_duration,
        voice,
    )


# ============================================================
# CRÉATION D'UNE VIDÉO LONGUE
# ============================================================

def create_long_video(
    topic: str,
    script: str,
    output_path: Path,
    work_dir: Path,
) -> Tuple[Path, float, str]:
    """
    Génère une vidéo horizontale.

    Il n'y a volontairement PAS de durée minimale de 2 minutes.
    Si le routage considère que le script est suffisamment long,
    la vidéo longue est générée.
    """

    ensure_ffmpeg()

    script = clean_text(script)

    word_count = count_words(script)

    if word_count < MIN_WORDS:
        raise RuntimeError(
            "Le script est trop court pour une vidéo longue."
        )

    validate_script_images(script)

    work_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # Texte de narration
    # --------------------------------------------------------

    narration_text = remove_image_markers(script)

    if not narration_text:
        raise RuntimeError(
            "Le texte destiné à la narration est vide."
        )

    # --------------------------------------------------------
    # Génération TTS
    # --------------------------------------------------------

    audio_path = work_dir / "narration.mp3"

    (
        audio_path,
        timings,
        audio_duration,
        voice,
    ) = generate_audio(
        text=narration_text,
        output_path=audio_path,
    )

    st.info(
        f"Voix utilisée : {voice} | "
        f"Durée vidéo : {format_seconds(audio_duration)}"
    )

    # --------------------------------------------------------
    # Nombre de visuels
    # --------------------------------------------------------

    visual_count = visual_count_for_duration(
        duration=audio_duration,
        vertical=False,
    )

    visuals_dir = work_dir / "visuals"

    visuals = get_visuals(
        script=script,
        output_dir=visuals_dir,
        orientation="landscape",
        expected_count=visual_count,
    )

    # --------------------------------------------------------
    # Montage horizontal
    # --------------------------------------------------------

    final_video = build_video(
        visuals=visuals,
        audio_path=audio_path,
        timings=timings,
        audio_duration=audio_duration,
        output_path=output_path,
        vertical=False,
    )

    return (
        final_video,
        audio_duration,
        voice,
    )


# ============================================================
# NETTOYAGE
# ============================================================

def cleanup_temp_files() -> None:
    """
    Nettoie les anciens fichiers temporaires.

    Les vidéos finales présentes dans outputs/ sont conservées.
    """

    try:
        if TEMP_DIR.exists():
            for item in TEMP_DIR.iterdir():

                try:
                    if item.is_dir():
                        shutil.rmtree(
                            item,
                            ignore_errors=True,
                        )
                    else:
                        item.unlink(
                            missing_ok=True,
                        )

                except Exception:
                    pass

    except Exception:
        pass


# ============================================================
# AFFICHAGE D'UN SCRIPT
# ============================================================

def display_script_info(
    title: str,
    script: str,
) -> None:
    """
    Affiche les informations principales d'un script.
    """

    words = count_words(script)
    images = len(
        extract_image_markers(script)
    )

    st.subheader(title)

    col1, col2 = st.columns(2)

    with col1:
        st.metric(
            "Nombre de mots",
            words,
        )

    with col2:
        st.metric(
            "Marqueurs image",
            images,
        )

    with st.expander(
        "Voir le script",
        expanded=False,
    ):
        st.text_area(
            "Script",
            value=script,
            height=400,
            key=f"script_{title}_{words}_{images}",
        )


# ============================================================
# TÉLÉCHARGEMENT VIDÉO
# ============================================================

def show_video_result(
    title: str,
    video_path: Path,
) -> None:
    """
    Affiche une vidéo et son bouton de téléchargement.
    """

    if not video_path.exists():

        st.error(
            f"Fichier vidéo introuvable : {video_path}"
        )

        return

    st.subheader(title)

    st.video(
        str(video_path)
    )

    with open(
        video_path,
        "rb",
    ) as video_file:

        st.download_button(
            label=f"⬇️ Télécharger {title}",
            data=video_file.read(),
            file_name=video_path.name,
            mime="video/mp4",
            key=f"download_{video_path.name}",
        )


# ============================================================
# INTERFACE STREAMLIT
# ============================================================

st.set_page_config(
    page_title=APP_TITLE,
    page_icon="🎬",
    layout="wide",
)


st.title("🎬 Studio Vidéo IA")

st.markdown(
    """
### Génération automatique de contenu historique

Le studio choisit automatiquement le meilleur format selon
la longueur du script :

- **moins de 200 mots** → régénération automatique
- **200 à 349 mots** → 1 Short
- **350 à 699 mots** → 2 Shorts
- **700 mots ou plus** → vidéo longue + teaser Short

Les Shorts sont générés en **9:16** avec une narration,
des visuels et des sous-titres mot par mot.
"""
)


# ============================================================
# SAISIE DU SUJET
# ============================================================

topic = st.text_input(
    "Sujet de la vidéo",
    placeholder=(
        "Exemple : "
        "La chute de Constantinople en 1453"
    ),
)


generate_button = st.button(
    "🚀 Générer le Pack",
    type="primary",
    use_container_width=True,
)


# ============================================================
# WORKFLOW PRINCIPAL
# ============================================================

if generate_button:

    if not topic.strip():

        st.warning(
            "Veuillez entrer un sujet avant de lancer la génération."
        )

        st.stop()

    cleanup_temp_files()

    run_id = str(
        int(time.time())
    )

    current_work_dir = (
        TEMP_DIR / f"run_{run_id}"
    )

    current_work_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:

        # ----------------------------------------------------
        # ÉTAPE 1 : SCRIPT PRINCIPAL
        # ----------------------------------------------------

        st.header("1. Génération du script")

        with st.spinner(
            "Création de l'histoire..."
        ):

            main_script = generate_main_script(
                topic=topic.strip(),
                retry=False,
            )

        main_word_count = count_words(
            main_script
        )

        st.success(
            f"Script généré : "
            f"{main_word_count} mots"
        )

        display_script_info(
            "Script principal",
            main_script,
        )

        # ----------------------------------------------------
        # ÉTAPE 2 : ROUTAGE
        # ----------------------------------------------------

        mode = choose_content_mode(
            main_word_count
        )

        # ----------------------------------------------------
        # Si moins de 200 mots :
        # régénération automatique
        # ----------------------------------------------------

        if mode == "REGENERATE":

            st.warning(
                "Le script contient moins de 200 mots. "
                "Nouvelle génération automatique..."
            )

            with st.spinner(
                "Enrichissement automatique du script..."
            ):

                main_script = generate_main_script(
                    topic=topic.strip(),
                    retry=True,
                )

            main_word_count = count_words(
                main_script
            )

            st.info(
                f"Après régénération : "
                f"{main_word_count} mots"
            )

            display_script_info(
                "Script régénéré",
                main_script,
            )

            mode = choose_content_mode(
                main_word_count
            )

            if mode == "REGENERATE":

                raise RuntimeError(
                    "Même après régénération, le script reste "
                    "sous les 200 mots. Impossible de produire "
                    "un contenu suffisamment développé."
                )

        # ----------------------------------------------------
        # AFFICHAGE DU FORMAT CHOISI
        # ----------------------------------------------------

        if mode == "ONE_SHORT":

            st.info(
                "Format sélectionné : "
                "**1 Short vertical**."
            )

        elif mode == "TWO_SHORTS":

            st.info(
                "Format sélectionné : "
                "**2 Shorts verticaux, Partie 1 + Partie 2**."
            )

        elif mode == "LONG_PLUS_TEASER":

            if main_word_count <= LONG_MAX_RECOMMENDED:

                st.info(
                    "Format sélectionné : "
                    "**vidéo longue + teaser Short**."
                )

            else:

                st.info(
                    "Script très long : "
                    "**vidéo longue + teaser Short**."
                )

        # ----------------------------------------------------
        # ÉTAPE 3 : PRODUCTION
        # ----------------------------------------------------

        st.header("2. Production vidéo")        # ====================================================
        # 1 SHORT
        # ====================================================

        if mode == "ONE_SHORT":

            with st.spinner(
                "Transformation du script en Short..."
            ):

                short_script = generate_one_short(
                    topic=topic.strip(),
                    source_script=main_script,
                )

            short_words = count_words(
                short_script
            )

            display_script_info(
                "Script du Short",
                short_script,
            )

            short_path = (
                OUTPUT_DIR
                / "short.mp4"
            )

            short_work_dir = (
                current_work_dir
                / "short"
            )

            with st.spinner(
                "Création du Short vertical..."
            ):

                (
                    final_path,
                    duration,
                    voice,
                ) = create_short_video(
                    topic=topic.strip(),
                    script=short_script,
                    output_path=short_path,
                    work_dir=short_work_dir,
                )

            st.success(
                "Short généré avec succès."
            )

            show_video_result(
                "Short final",
                final_path,
            )

            st.caption(
                f"{short_words} mots | "
                f"{format_seconds(duration)} | "
                f"Voix : {voice}"
            )


        # ====================================================
        # 2 SHORTS
        # ====================================================

        elif mode == "TWO_SHORTS":

            with st.spinner(
                "Restructuration en deux Shorts cohérents..."
            ):

                (
                    short_1_script,
                    short_2_script,
                ) = generate_two_shorts(
                    topic=topic.strip(),
                    source_script=main_script,
                )

            # ------------------------------------------------
            # Partie 1
            # ------------------------------------------------

            display_script_info(
                "Short - Partie 1",
                short_1_script,
            )

            short_1_path = (
                OUTPUT_DIR
                / "short_partie_1.mp4"
            )

            short_1_work_dir = (
                current_work_dir
                / "short_partie_1"
            )

            with st.spinner(
                "Création du Short Partie 1..."
            ):

                (
                    final_path_1,
                    duration_1,
                    voice_1,
                ) = create_short_video(
                    topic=topic.strip(),
                    script=short_1_script,
                    output_path=short_1_path,
                    work_dir=short_1_work_dir,
                )

            st.success(
                "Partie 1 générée."
            )

            show_video_result(
                "Short - Partie 1",
                final_path_1,
            )

            st.caption(
                f"{count_words(short_1_script)} mots | "
                f"{format_seconds(duration_1)} | "
                f"Voix : {voice_1}"
            )

            # ------------------------------------------------
            # Partie 2
            # ------------------------------------------------

            display_script_info(
                "Short - Partie 2",
                short_2_script,
            )

            short_2_path = (
                OUTPUT_DIR
                / "short_partie_2.mp4"
            )

            short_2_work_dir = (
                current_work_dir
                / "short_partie_2"
            )

            with st.spinner(
                "Création du Short Partie 2..."
            ):

                (
                    final_path_2,
                    duration_2,
                    voice_2,
                ) = create_short_video(
                    topic=topic.strip(),
                    script=short_2_script,
                    output_path=short_2_path,
                    work_dir=short_2_work_dir,
                )

            st.success(
                "Partie 2 générée."
            )

            show_video_result(
                "Short - Partie 2",
                final_path_2,
            )

            st.caption(
                f"{count_words(short_2_script)} mots | "
                f"{format_seconds(duration_2)} | "
                f"Voix : {voice_2}"
            )

            st.success(
                "Les deux Shorts ont été générés avec succès."
            )


        # ====================================================
        # VIDÉO LONGUE + TEASER
        # ====================================================

        elif mode == "LONG_PLUS_TEASER":

            # ------------------------------------------------
            # Vidéo longue
            # ------------------------------------------------

            st.subheader(
                "Vidéo longue"
            )

            long_path = (
                OUTPUT_DIR
                / "video_longue.mp4"
            )

            long_work_dir = (
                current_work_dir
                / "video_longue"
            )

            with st.spinner(
                "Création de la vidéo longue..."
            ):

                (
                    final_long_path,
                    long_duration,
                    long_voice,
                ) = create_long_video(
                    topic=topic.strip(),
                    script=main_script,
                    output_path=long_path,
                    work_dir=long_work_dir,
                )

            st.success(
                "Vidéo longue générée."
            )

            show_video_result(
                "Vidéo longue finale",
                final_long_path,
            )

            st.caption(
                f"{main_word_count} mots | "
                f"{format_seconds(long_duration)} | "
                f"Voix : {long_voice}"
            )

            # ------------------------------------------------
            # Teaser
            # ------------------------------------------------

            st.subheader(
                "Teaser Short"
            )

            with st.spinner(
                "Création du teaser..."
            ):

                teaser_script = generate_teaser(
                    topic=topic.strip(),
                    source_script=main_script,
                )

            display_script_info(
                "Script du teaser",
                teaser_script,
            )

            teaser_path = (
                OUTPUT_DIR
                / "teaser_short.mp4"
            )

            teaser_work_dir = (
                current_work_dir
                / "teaser"
            )

            with st.spinner(
                "Création du teaser vertical..."
            ):

                (
                    final_teaser_path,
                    teaser_duration,
                    teaser_voice,
                ) = create_short_video(
                    topic=topic.strip(),
                    script=teaser_script,
                    output_path=teaser_path,
                    work_dir=teaser_work_dir,
                )

            st.success(
                "Teaser généré."
            )

            show_video_result(
                "Teaser Short final",
                final_teaser_path,
            )

            st.caption(
                f"{count_words(teaser_script)} mots | "
                f"{format_seconds(teaser_duration)} | "
                f"Voix : {teaser_voice}"
            )

            st.success(
                "Pack complet généré : "
                "vidéo longue + teaser Short."
            )


        # ====================================================
        # MODE INCONNU
        # ====================================================

        else:

            raise RuntimeError(
                f"Mode de génération inconnu : {mode}"
            )


    # ========================================================
    # GESTION DES ERREURS
    # ========================================================

    except Exception as exc:

        st.error(
            "Une erreur est survenue pendant la génération."
        )

        st.exception(exc)

        st.info(
            "Vérifiez notamment les variables "
            "OPENROUTER_API_KEY et PEXELS_API_KEY, "
            "ainsi que la présence de FFmpeg sur Render."
        )


# ============================================================
# INFORMATIONS TECHNIQUES
# ============================================================

with st.expander(
    "ℹ️ Informations sur le fonctionnement",
    expanded=False,
):

    st.markdown(
        """
### Routage automatique

| Nombre de mots | Résultat |
|---:|---|
| < 200 | Régénération automatique |
| 200–349 | 1 Short |
| 350–699 | 2 Shorts |
| 700+ | Vidéo longue + teaser |

### Shorts

- Format : 1080 × 1920
- Ratio : 9:16
- Narration TTS
- Sous-titres mot par mot
- Sous-titres positionnés en bas
- Visuels adaptés à la durée
- Cible : environ 25 à 40 secondes

### Vidéo longue

- Format : 1920 × 1080
- Ratio : 16:9
- Narration TTS
- Sous-titres synchronisés
- Visuels adaptés à la durée
- Aucune durée minimale artificielle

### Visuels

Les images sont recherchées à partir des marqueurs :

`[IMAGE: english visual keywords]`

Le système utilise Pexels et crée un visuel de secours
si une recherche échoue.

### Audio

La narration utilise Edge-TTS avec plusieurs voix françaises
de secours.

### Montage

FFmpeg assemble :

1. les images
2. les scènes
3. la narration
4. les sous-titres
5. le fichier MP4 final
"""
    )
