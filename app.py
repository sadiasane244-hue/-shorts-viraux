import os
import re
import time
import shutil
import random
import asyncio
import threading
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import requests
import streamlit as st
import edge_tts
from PIL import Image


# ============================================================
# CONFIGURATION
# ============================================================

APP_TITLE = "Studio Vidéo IA"

BASE_DIR = Path(__file__).resolve().parent
TEMP_ROOT = BASE_DIR / "temp_video"
OUTPUT_ROOT = BASE_DIR / "outputs"
ASSETS_ROOT = BASE_DIR / "assets"

TEMP_ROOT.mkdir(parents=True, exist_ok=True)
OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
ASSETS_ROOT.mkdir(parents=True, exist_ok=True)


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "meta-llama/llama-3.3-70b-instruct"

PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"


# ============================================================
# SEUILS DE ROUTAGE
# ============================================================

REGENERATE_BELOW = 200

ONE_SHORT_MIN = 200
ONE_SHORT_MAX = 349

TWO_SHORTS_MIN = 350
TWO_SHORTS_MAX = 699

LONG_MIN = 700


# ============================================================
# PARAMÈTRES DES SHORTS
# ============================================================

SHORT_MIN_SECONDS = 10
SHORT_TARGET_MIN_SECONDS = 20
SHORT_TARGET_MAX_SECONDS = 45
SHORT_MAX_SECONDS = 60

SHORT_MIN_WORDS = 20
SHORT_TARGET_MIN_WORDS = 45
SHORT_TARGET_MAX_WORDS = 110
SHORT_MAX_WORDS = 150

SHORT_MIN_IMAGES = 4
SHORT_TARGET_MIN_IMAGES = 6
SHORT_TARGET_MAX_IMAGES = 12
SHORT_MAX_IMAGES = 16


# ============================================================
# PARAMÈTRES VIDÉO LONGUE
# ============================================================

LONG_MIN_IMAGES = 8
LONG_TARGET_MIN_IMAGES = 12
LONG_TARGET_MAX_IMAGES = 36
LONG_MAX_IMAGES = 40


# ============================================================
# VOIX EDGE-TTS
# ============================================================

PREFERRED_VOICES = [
    "fr-FR-DeniseNeural",
    "fr-FR-HenriNeural",
    "fr-FR-EloiseNeural",
    "fr-FR-VivienneMultilingualNeural",
]


# ============================================================
# EXTENSIONS
# ============================================================

IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
}

VIDEO_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".mkv",
    ".webm",
}


# ============================================================
# SECRETS
# ============================================================

def get_secret(name: str, default: str = "") -> str:
    """
    Récupère une variable depuis st.secrets ou os.environ.
    """
    try:
        value = st.secrets.get(name)
        if value:
            return str(value).strip()
    except Exception:
        pass

    return os.getenv(name, default).strip()


OPENROUTER_API_KEY = get_secret("OPENROUTER_API_KEY")
PEXELS_API_KEY = get_secret("PEXELS_API_KEY")


# ============================================================
# OUTILS TEXTE
# ============================================================

IMAGE_MARKER_RE = re.compile(
    r"IMAGE\s*:\s*(.*?)",
    flags=re.IGNORECASE | re.DOTALL,
)


def clean_text(text: str) -> str:
    """
    Nettoie le texte sans supprimer les marqueurs [IMAGE: ...].
    """
    if not text:
        return ""

    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

    # Normalisation des espaces
    text = re.sub(r"[ \t]+", " ", text)

    # Nettoyage des lignes vides excessives
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def count_words(text: str) -> int:
    """
    Compte les mots en ignorant les marqueurs d'image.
    """
    if not text:
        return 0

    without_markers = IMAGE_MARKER_RE.sub(" ", text)

    words = re.findall(
        r"\b[\wÀ-ÿ'-]+\b",
        without_markers,
        flags=re.UNICODE,
    )

    return len(words)


def format_seconds(seconds: float) -> str:
    """
    Convertit une durée en MM:SS.
    """
    seconds = max(0, float(seconds))

    minutes = int(seconds // 60)
    remaining = int(round(seconds % 60))

    if remaining >= 60:
        minutes += 1
        remaining = 0

    return f"{minutes:02d}:{remaining:02d}"


def safe_filename(value: str, fallback: str = "video") -> str:
    """
    Produit un nom de fichier sûr.
    """
    value = value.strip()

    value = re.sub(
        r"[^\wÀ-ÿ\- ]+",
        "",
        value,
        flags=re.UNICODE,
    )

    value = re.sub(r"\s+", "_", value)

    value = value.strip("_")

    return value[:80] or fallback


# ============================================================
# EXÉCUTION DES COMMANDES
# ============================================================

def run_command(
    command: List[str],
    timeout: int = 600,
) -> subprocess.CompletedProcess:
    """
    Exécute une commande système et remonte une erreur lisible.
    """

    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Commande interrompue après {timeout} secondes."
        ) from exc

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()

        if len(stderr) > 5000:
            stderr = stderr[-5000:]

        raise RuntimeError(
            "Une commande système a échoué.\n\n"
            f"Commande : {' '.join(command)}\n\n"
            f"Détails :\n{stderr}"
        )

    return result


def ensure_ffmpeg() -> None:
    """
    Vérifie que FFmpeg et FFprobe sont disponibles.
    """

    ffmpeg_path = shutil.which("ffmpeg")
    ffprobe_path = shutil.which("ffprobe")

    if not ffmpeg_path:
        raise RuntimeError(
            "FFmpeg est introuvable sur le serveur."
        )

    if not ffprobe_path:
        raise RuntimeError(
            "FFprobe est introuvable sur le serveur."
        )


# ============================================================
# OPENROUTER
# ============================================================

def openrouter_request(
    messages: List[Dict[str, str]],
    max_tokens: int = 3000,
    temperature: float = 0.75,
) -> str:

    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY est manquante."
        )

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://shorts-viraux-1.onrender.com",
        "X-Title": APP_TITLE,
    }

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    try:
        response = requests.post(
            OPENROUTER_URL,
            headers=headers,
            json=payload,
            timeout=120,
        )
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Impossible de contacter OpenRouter : {exc}"
        ) from exc

    if response.status_code != 200:
        details = response.text[:4000]

        raise RuntimeError(
            f"OpenRouter a répondu avec HTTP {response.status_code}.\n\n"
            f"{details}"
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(
            "La réponse d'OpenRouter n'est pas un JSON valide."
        ) from exc

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(
            "La réponse d'OpenRouter ne contient pas de texte exploitable."
        ) from exc

    if not content or not content.strip():
        raise RuntimeError(
            "OpenRouter a renvoyé un contenu vide."
        )

    return clean_text(content)


# ============================================================
# PROMPT PRINCIPAL
# ============================================================

def generate_main_script(topic: str) -> str:
    """
    Génère le contenu principal.

    Le script n'est pas artificiellement limité à une longueur exacte.
    Le routage sera effectué ensuite en fonction du contenu réellement
    produit.
    """

    system_prompt = """
Vous êtes un vulgarisateur scientifique spécialisé en :

- psychologie cognitive
- neurosciences
- comportement humain
- mémoire
- attention
- apprentissage
- prise de décision
- habitudes
- émotions
- motivation

Votre mission est de produire des contenus captivants mais scientifiquement
responsables.

RÈGLES ABSOLUES :

1. Ne jamais inventer de faits.
2. Ne jamais inventer d'étude scientifique.
3. Ne jamais inventer de chercheur.
4. Ne jamais inventer de pourcentage.
5. Ne jamais présenter une hypothèse comme un fait établi.
6. Éviter les neuromythes.
7. Ne pas diagnostiquer les spectateurs.
8. Ne pas présenter une explication simpliste comme une vérité universelle.
9. Si les différences individuelles sont importantes, le préciser brièvement.
10. Le contenu doit rester compréhensible par quelqu'un qui ne connaît rien
    aux neurosciences.

STYLE :

- commencer par une accroche forte ;
- créer immédiatement une question ou une curiosité ;
- donner progressivement l'explication ;
- utiliser des exemples concrets ;
- éviter les introductions longues ;
- garder un rythme narratif ;
- faire comprendre le mécanisme plutôt que simplement donner une définition ;
- terminer par une idée mémorable.

Le but est de donner au spectateur envie de rester jusqu'à la fin.

FORMAT :

Écrivez un script narratif naturel en français.

Utilisez régulièrement des marqueurs visuels sous cette forme :

[IMAGE: description précise du visuel]

Les descriptions doivent correspondre à des images que l'on pourrait réellement
trouver dans une banque d'images.

Les marqueurs doivent être répartis tout au long du script.

Pour une vidéo longue, essayez normalement d'utiliser environ
12 à 36 marqueurs [IMAGE: ...], selon la longueur réelle du contenu.

Ne remplissez jamais artificiellement le script uniquement pour atteindre
un nombre de mots.
"""

    user_prompt = f"""
Sujet :

{topic}

Créez maintenant le meilleur script possible sur ce sujet.

Le contenu doit être suffisamment développé pour pouvoir être transformé
automatiquement en vidéo longue ou en un ou plusieurs Shorts selon sa
longueur réelle.

Privilégiez la qualité, la curiosité et la précision scientifique plutôt
qu'un nombre de mots artificiel.
"""

    return openrouter_request(
        messages=[
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
        max_tokens=4000,
        temperature=0.78,
    )


# ============================================================
# ROUTAGE DU CONTENU
# ============================================================

def choose_content_mode(word_count: int) -> str:
    """
    Détermine le format initial.

    Important :
    la longueur n'est jamais considérée comme une erreur.

    Elle sert uniquement à choisir le format le plus pertinent.
    """

    if word_count < REGENERATE_BELOW:
        return "regenerate"

    if ONE_SHORT_MIN <= word_count <= ONE_SHORT_MAX:
        return "one_short"

    if TWO_SHORTS_MIN <= word_count <= TWO_SHORTS_MAX:
        return "two_shorts"

    if word_count >= LONG_MIN:
        return "long"

    # Sécurité
    return "one_short"


# ============================================================
# RÉGÉNÉRATION D'UN CONTENU TROP COURT
# ============================================================

def regenerate_short_main_script(
    topic: str,
    previous_script: str,
) -> str:
    """
    Si le premier script est très court, on tente une amélioration.

    Une seule régénération automatique est effectuée afin d'éviter
    une boucle coûteuse.
    """

    prompt = f"""
Le texte suivant est trop court pour être exploité correctement :

{previous_script}

Sujet :
{topic}

Réécrivez-le en conservant uniquement des informations scientifiquement
défendables.

Développez suffisamment l'explication pour obtenir un contenu réellement
exploitable.

Ajoutez :

- une accroche ;
- une explication claire ;
- un exemple concret ;
- une conclusion mémorable.

Ajoutez plusieurs marqueurs :

[IMAGE: description du visuel]

Ne remplissez pas artificiellement le texte.
Ne fabriquez aucun fait.

Le résultat doit être un script narratif naturel en français.
"""

    return openrouter_request(
        messages=[
            {
                "role": "system",
                "content": """
Vous êtes un vulgarisateur scientifique rigoureux spécialisé en psychologie,
neurosciences et comportement humain.

Vous devez privilégier l'exactitude scientifique.
""",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        max_tokens=3000,
        temperature=0.72,
    )


# ============================================================
# GÉNÉRATION D'UN SHORT
# ============================================================

def generate_one_short(
    topic: str,
    source_script: str,
) -> str:
    """
    Transforme le contenu principal en un Short autonome.

    Le résultat n'est volontairement PAS soumis à une longueur exacte.
    La longueur sera adaptée ensuite à l'audio réellement produit.
    """

    prompt = f"""
Sujet :
{topic}

Voici le contenu source :

{source_script}

Transformez ce contenu en UN Short vertical autonome.

OBJECTIF :

Le spectateur doit comprendre l'idée principale même s'il ne voit pas
la vidéo longue.

STRUCTURE :

1. Accroche immédiate.
2. Question ou élément intrigant.
3. Explication claire.
4. Exemple concret si utile.
5. Conclusion mémorable.

STYLE :

- naturel ;
- dynamique ;
- phrases courtes ;
- aucune introduction inutile ;
- aucune affirmation scientifique inventée.

IMPORTANT :

Ne cherchez PAS à atteindre artificiellement un nombre de mots précis.

La longueur doit être déterminée par la quantité d'informations réellement
nécessaire pour raconter correctement l'idée.

Le résultat peut donc être court si le sujet s'y prête.

Ajoutez entre 4 et 12 marqueurs visuels :

[IMAGE: description précise du visuel]

Les marqueurs doivent être répartis dans le texte.

Ne faites aucune référence à "la partie 1", "la vidéo précédente" ou
"la vidéo suivante".

Retournez uniquement le script.
"""

    return openrouter_request(
        messages=[
            {
                "role": "system",
                "content": """
Vous êtes un scénariste spécialisé dans les Shorts de vulgarisation
scientifique.

Votre priorité est la rétention et la clarté, sans sacrifier l'exactitude.
""",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        max_tokens=1800,
        temperature=0.78,
    )


# ============================================================
# GÉNÉRATION DE DEUX SHORTS
# ============================================================

def generate_two_shorts(
    topic: str,
    source_script: str,
) -> Tuple[str, str]:
    """
    Restructure le contenu en deux Shorts cohérents.

    IMPORTANT :
    On ne coupe jamais simplement le texte en deux.

    Le modèle doit reconstruire deux narrations cohérentes.
    """

    prompt = f"""
Sujet :
{topic}

Contenu source :

{source_script}

Transformez ce contenu en DEUX Shorts verticaux cohérents.

IMPORTANT :

Ne coupez surtout pas le texte simplement en deux moitiés.

Vous devez restructurer l'histoire ou l'explication afin que chaque Short
soit intéressant et compréhensible.

PARTIE 1 :

- accroche très forte ;
- présenter le phénomène ;
- donner le contexte nécessaire ;
- commencer l'explication ;
- terminer avec une idée qui donne envie de connaître la suite.

PARTIE 2 :

- reprendre naturellement là où la première partie s'arrête ;
- donner l'explication principale ;
- apporter le point le plus intéressant ;
- terminer avec une conclusion satisfaisante.

CONTRAINTE IMPORTANTE :

Les deux parties n'ont PAS besoin d'avoir la même longueur.

Une partie peut être plus courte que l'autre si cela correspond naturellement
au contenu.

Ne rajoutez jamais de faits inventés pour équilibrer les longueurs.

Chaque partie doit être exploitable indépendamment dans une vidéo verticale.

Chaque partie doit contenir plusieurs marqueurs visuels :

[IMAGE: description précise du visuel]

Utilisez généralement entre 4 et 12 marqueurs par partie.

Le texte doit rester naturel et dynamique.

FORMAT OBLIGATOIRE :

=== PARTIE 1 ===
texte de la partie 1

=== PARTIE 2 ===
texte de la partie 2

Ne mettez rien avant "=== PARTIE 1 ===".
Ne mettez rien après le texte de la Partie 2.
"""

    result = openrouter_request(
        messages=[
            {
                "role": "system",
                "content": """
Vous êtes un scénariste spécialisé dans les contenus courts de psychologie,
neurosciences et comportement humain.

Vous devez optimiser la narration et la rétention sans inventer
d'informations.
""",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        max_tokens=2600,
        temperature=0.78,
    )

    match = re.search(
        r"===\s*PARTIE\s*1\s*===\s*(.*?)\s*===\s*PARTIE\s*2\s*===\s*(.*)",
        result,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if not match:
        raise RuntimeError(
            "Le modèle n'a pas retourné les deux parties dans le format attendu."
        )

    part1 = clean_text(match.group(1))
    part2 = clean_text(match.group(2))

    if not part1:
        raise RuntimeError(
            "La Partie 1 générée est vide."
        )

    if not part2:
        raise RuntimeError(
            "La Partie 2 générée est vide."
        )

    return part1, part2


# ============================================================
# ADAPTATION D'UN SHORT
# ============================================================

def fit_short_script(
    topic: str,
    script: str,
    part_label: str = "Short",
) -> str:
    """
    Adapte un script de Short.

    NOUVELLE LOGIQUE :

    La longueur n'est plus une condition bloquante.

    On tente une adaptation si le texte semble trop long ou trop court,
    mais si le modèle renvoie toujours un texte court, on l'accepte.

    Le seul véritable minimum est un contenu narratif exploitable.
    """

    script = clean_text(script)

    if not script:
        raise RuntimeError(
            f"{part_label} : le script est vide."
        )

    initial_words = count_words(script)

    # --------------------------------------------------------
    # Cas très court
    # --------------------------------------------------------

    if initial_words < SHORT_MIN_WORDS:
        prompt = f"""
Sujet :
{topic}

{part_label} :

{script}

Le texte est très court.

Essayez de l'améliorer légèrement afin d'obtenir un Short cohérent,
mais UNIQUEMENT avec les informations déjà présentes ou scientifiquement
défendables.

Ne cherchez pas à atteindre un nombre de mots précis.

Si le contenu ne permet naturellement pas de faire plus long, conservez-le.

Ajoutez quelques marqueurs :

[IMAGE: description du visuel]

Retournez uniquement le script.
"""

        try:
            candidate = openrouter_request(
                messages=[
                    {
                        "role": "system",
                        "content": """
Vous adaptez des scripts courts de vulgarisation scientifique.

Ne fabriquez aucune information pour augmenter artificiellement la longueur.
""",
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                max_tokens=1200,
                temperature=0.65,
            )

            candidate = clean_text(candidate)

            if candidate and count_words(candidate) >= initial_words:
                script = candidate

        except Exception:
            # L'adaptation est facultative.
            # Le contenu original reste utilisable.
            pass

    # --------------------------------------------------------
    # Cas très long
    # --------------------------------------------------------

    words = count_words(script)

    if words > SHORT_MAX_WORDS:
        prompt = f"""
Sujet :
{topic}

{part_label} :

{script}

Condensez ce texte pour en faire un Short dynamique.

Conservez :

- l'idée principale ;
- les faits importants ;
- l'accroche ;
- l'explication essentielle ;
- la conclusion.

Supprimez les répétitions et les détails secondaires.

Ne fabriquez aucune information.

Le résultat doit rester naturel et compréhensible.

Conservez ou recréez des marqueurs :

[IMAGE: description du visuel]

Ne cherchez pas à respecter un nombre de mots exact.
"""

        try:
            candidate = openrouter_request(
                messages=[
                    {
                        "role": "system",
                        "content": """
Vous êtes un monteur-rédacteur spécialisé dans la condensation
de contenus scientifiques pour Shorts.
""",
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                max_tokens=1600,
                temperature=0.62,
            )

            candidate = clean_text(candidate)

            if candidate and count_words(candidate) > 0:
                script = candidate

        except Exception:
            # Si la condensation échoue, le texte original sera utilisé.
            pass

    # --------------------------------------------------------
    # NOUVEAU :
    # aucun RuntimeError basé uniquement sur le nombre de mots.
    # --------------------------------------------------------

    final_words = count_words(script)

    if final_words < SHORT_MIN_WORDS:
        st.warning(
            f"{part_label} contient# ============================================================
# MARQUEURS IMAGE
# ============================================================

def extract_image_markers(script: str) -> List[str]:
    """
    Extrait les descriptions contenues dans les marqueurs [IMAGE: ...].
    """

    if not script:
        return []

    markers = []

    for match in IMAGE_MARKER_RE.finditer(script):
        description = clean_text(match.group(1))

        if description:
            markers.append(description)

    return markers


def remove_image_markers(script: str) -> str:
    """
    Supprime les marqueurs [IMAGE: ...] du texte destiné à la narration.
    """

    if not script:
        return ""

    text = IMAGE_MARKER_RE.sub(" ", script)

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def validate_script_images(
    script: str,
    minimum: int = 4,
    maximum: int = 40,
) -> List[str]:
    """
    Vérifie le nombre de marqueurs visuels.

    Contrairement à la longueur du texte, un nombre insuffisant de visuels
    peut être corrigé automatiquement dans get_visuals() en complétant
    avec des recherches supplémentaires.
    """

    markers = extract_image_markers(script)

    if len(markers) > maximum:
        markers = markers[:maximum]

    if len(markers) < minimum:
        # On ne fait pas planter immédiatement le pipeline.
        # Les fonctions de génération visuelle pourront compléter les visuels.
        return markers

    return markers


# ============================================================
# PEXELS
# ============================================================

def pexels_headers() -> Dict[str, str]:
    """
    Prépare les headers Pexels.
    """

    if not PEXELS_API_KEY:
        return {}

    return {
        "Authorization": PEXELS_API_KEY,
    }


def download_file(
    url: str,
    destination: Path,
    timeout: int = 30,
) -> bool:
    """
    Télécharge un fichier HTTP.
    """

    try:
        response = requests.get(
            url,
            timeout=timeout,
            stream=True,
        )
    except requests.RequestException:
        return False

    if response.status_code != 200:
        return False

    try:
        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with destination.open("wb") as file:
            for chunk in response.iter_content(
                chunk_size=1024 * 64
            ):
                if chunk:
                    file.write(chunk)

    except OSError:
        return False

    return destination.exists() and destination.stat().st_size > 0


def search_pexels_photo(
    query: str,
    orientation: str = "landscape",
) -> Optional[str]:
    """
    Recherche une image Pexels.

    L'orientation est désormais transmise explicitement afin que les Shorts
    puissent privilégier des images verticales.
    """

    if not PEXELS_API_KEY:
        return None

    query = clean_text(query)

    if not query:
        return None

    params = {
        "query": query[:120],
        "per_page": 8,
        "orientation": (
            "portrait"
            if orientation == "portrait"
            else "landscape"
        ),
        "size": "large",
    }

    try:
        response = requests.get(
            PEXELS_SEARCH_URL,
            headers=pexels_headers(),
            params=params,
            timeout=30,
        )
    except requests.RequestException:
        return None

    if response.status_code != 200:
        return None

    try:
        data = response.json()
    except ValueError:
        return None

    photos = data.get("photos", [])

    if not photos:
        return None

    # Mélange léger pour éviter de récupérer toujours la même image.
    random.shuffle(photos)

    for photo in photos:
        src = photo.get("src", {})

        if not isinstance(src, dict):
            continue

        # Pour les vidéos verticales, on privilégie portrait.
        if orientation == "portrait":
            image_url = (
                src.get("portrait")
                or src.get("large2x")
                or src.get("large")
                or src.get("original")
            )
        else:
            image_url = (
                src.get("landscape")
                or src.get("large2x")
                or src.get("large")
                or src.get("original")
            )

        if image_url:
            return image_url

    return None


# ============================================================
# PLACEHOLDER VISUEL
# ============================================================

def create_placeholder(
    destination: Path,
    width: int,
    height: int,
    title: str = "",
) -> Path:
    """
    Crée une image de secours si aucune image externe n'est disponible.
    """

    width = max(320, int(width))
    height = max(320, int(height))

    image = Image.new(
        "RGB",
        (width, height),
        (18, 18, 24),
    )

    # Le texte n'est volontairement pas ajouté ici.
    # Les sous-titres et éléments narratifs seront ajoutés au montage.

    image.save(
        destination,
        format="JPEG",
        quality=90,
    )

    return destination


# ============================================================
# NORMALISATION DES IMAGES
# ============================================================

def normalize_image(
    source: Path,
    destination: Path,
    orientation: str = "landscape",
) -> Path:
    """
    Convertit toutes les images dans un format homogène.

    Landscape :
        1280 x 720

    Portrait :
        1080 x 1920
    """

    if orientation == "portrait":
        target_width = 1080
        target_height = 1920
    else:
        target_width = 1280
        target_height = 720

    try:
        with Image.open(source) as image:
            image = image.convert("RGB")

            source_width, source_height = image.size

            if source_width <= 0 or source_height <= 0:
                raise ValueError("Dimensions d'image invalides.")

            target_ratio = target_width / target_height
            source_ratio = source_width / source_height

            # ------------------------------------------------
            # Recadrage centré
            # ------------------------------------------------

            if source_ratio > target_ratio:
                # Image trop large
                new_width = int(
                    source_height * target_ratio
                )

                left = max(
                    0,
                    (source_width - new_width) // 2,
                )

                image = image.crop(
                    (
                        left,
                        0,
                        left + new_width,
                        source_height,
                    )
                )

            elif source_ratio < target_ratio:
                # Image trop haute
                new_height = int(
                    source_width / target_ratio
                )

                top = max(
                    0,
                    (source_height - new_height) // 2,
                )

                image = image.crop(
                    (
                        0,
                        top,
                        source_width,
                        top + new_height,
                    )
                )

            image = image.resize(
                (
                    target_width,
                    target_height,
                ),
                Image.Resampling.LANCZOS,
            )

            destination.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            image.save(
                destination,
                format="JPEG",
                quality=94,
            )

    except Exception as exc:
        raise RuntimeError(
            f"Impossible de normaliser l'image {source.name} : {exc}"
        ) from exc

    return destination


# ============================================================
# GÉNÉRATION DES VISUELS
# ============================================================

def get_visuals(
    script: str,
    output_dir: Path,
    orientation: str = "landscape",
    target_count: Optional[int] = None,
) -> List[Path]:
    """
    Télécharge les visuels correspondant aux marqueurs du script.

    Si le script contient peu de marqueurs, on complète avec des visuels
    génériques liés au sujet des marqueurs existants plutôt que de faire
    échouer la production.
    """

    markers = extract_image_markers(script)

    if target_count is None:
        target_count = len(markers)

    target_count = max(1, int(target_count))

    if markers:
        selected_markers = markers[:target_count]
    else:
        selected_markers = [
            "illustration cinématique du sujet principal"
        ]

    # --------------------------------------------------------
    # Complétion prudente des marqueurs
    # --------------------------------------------------------

    while len(selected_markers) < target_count:
        base = selected_markers[-1]

        selected_markers.append(
            f"nouvelle scène visuelle liée à : {base}"
        )

    visuals_dir = output_dir / "visuals"
    visuals_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    visuals = []

    for index, description in enumerate(
        selected_markers,
        start=1,
    ):
        raw_path = visuals_dir / f"raw_{index:03d}.jpg"
        normalized_path = visuals_dir / f"visual_{index:03d}.jpg"

        image_url = search_pexels_photo(
            query=description,
            orientation=orientation,
        )

        success = False

        if image_url:
            success = download_file(
                image_url,
                raw_path,
            )

        if success:
            try:
                normalize_image(
                    raw_path,
                    normalized_path,
                    orientation=orientation,
                )

                if normalized_path.exists():
                    visuals.append(normalized_path)
                    continue

            except Exception:
                pass

        # ----------------------------------------------------
        # Fallback automatique
        # ----------------------------------------------------

        if orientation == "portrait":
            width = 1080
            height = 1920
        else:
            width = 1280
            height = 720

        placeholder_path = visuals_dir / f"fallback_{index:03d}.jpg"

        create_placeholder(
            placeholder_path,
            width,
            height,
            title=description,
        )

        visuals.append(placeholder_path)

        # Petite pause pour éviter une série de requêtes trop rapprochées.
        time.sleep(0.10)

    if not visuals:
        raise RuntimeError(
            "Aucun visuel n'a pu être préparé."
        )

    return visuals


# ============================================================
# NOMBRE DE VISUELS SELON LA DURÉE
# ============================================================

def visual_count_for_duration(
    duration: float,
    orientation: str = "landscape",
) -> int:
    """
    Calcule un nombre de visuels cohérent avec la durée réelle.

    Short :
        environ 1 visuel / 3 secondes

    Long :
        environ 1 visuel / 6 secondes
    """

    duration = max(
        1.0,
        float(duration),
    )

    if orientation == "portrait":
        minimum = SHORT_MIN_IMAGES
        target_minimum = SHORT_TARGET_MIN_IMAGES
        target_maximum = SHORT_TARGET_MAX_IMAGES
        maximum = SHORT_MAX_IMAGES
        seconds_per_visual = 3.0
    else:
        minimum = LONG_MIN_IMAGES
        target_minimum = LONG_TARGET_MIN_IMAGES
        target_maximum = LONG_TARGET_MAX_IMAGES
        maximum = LONG_MAX_IMAGES
        seconds_per_visual = 6.0

    calculated = int(
        round(duration / seconds_per_visual)
    )

    calculated = max(
        minimum,
        calculated,
    )

    calculated = max(
        target_minimum,
        calculated,
    )

    calculated = min(
        target_maximum,
        calculated,
    )

    calculated = min(
        maximum,
        calculated,
    )

    return calculated


# ============================================================
# EDGE-TTS : RÉCUPÉRATION SYNCHRONE DES VOIX
# ============================================================

def _edge_tts_list_voices_in_new_loop() -> List[Dict]:
    """
    Exécute edge_tts.list_voices() dans une nouvelle boucle asyncio.

    Cette fonction protège le pipeline contre les environnements dans
    lesquels Streamlit ou une autre librairie possède déjà une boucle
    asyncio active.
    """

    result = []
    errors = []

    def runner():
        try:
            voices = asyncio.run(
                edge_tts.list_voices()
            )

            if voices:
                result.extend(voices)

        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(
        target=runner,
        daemon=True,
    )

    thread.start()
    thread.join()

    if errors:
        raise errors[0]

    return result


def fetch_edge_tts_voices_sync() -> List[Dict]:
    """
    Version synchrone robuste de edge_tts.list_voices().
    """

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # Aucune boucle active.
        return asyncio.run(
            edge_tts.list_voices()
        )

    # Une boucle existe déjà.
    return _edge_tts_list_voices_in_new_loop()


# ============================================================
# VOIX FRANÇAISES DISPONIBLES
# ============================================================

def get_available_french_voices() -> List[str]:
    """
    Retourne les voix françaises disponibles.

    Si la découverte échoue, on utilise uniquement des voix françaises
    connues comme fallback.
    """

    try:
        voices = fetch_edge_tts_voices_sync()

        available = []

        for voice in voices:
            if not isinstance(voice, dict):
                continue

            short_name = voice.get("ShortName", "")
            locale = voice.get("Locale", "")

            if not short_name:
                continue

            if str(locale).lower().startswith("fr-"):
                available.append(short_name)

        # Priorité aux voix préférées.
        ordered = []

        for preferred in PREFERRED_VOICES:
            if preferred in available:
                ordered.append(preferred)

        # Puis les autres voix françaises.
        for voice in available:
            if voice not in ordered:
                ordered.append(voice)

        if ordered:
            return ordered

    except Exception:
        pass

    # Fallback minimal fiable.
    return [
        "fr-FR-DeniseNeural",
        "fr-FR-HenriNeural",
    ]


# ============================================================
# SYNTHÈSE VOCALE
# ============================================================

def synthesize_with_voice(
    text: str,
    voice: str,
    output_path: Path,
) -> List[Dict]:
    """
    Génère l'audio et récupère les événements WordBoundary.

    Ces événements permettent ensuite de produire des sous-titres
    mot par mot.
    """

    text = remove_image_markers(text)

    if not text.strip():
        raise RuntimeError(
            "Impossible de générer l'audio : texte vide."
        )

    communicate = edge_tts.Communicate(
        text,
        voice,
        rate="+0%",
        volume="+0%",
        pitch="+0Hz",
        boundary="WordBoundary",
    )

    boundaries = []

    try:
        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with output_path.open("wb") as audio_file:
            for event in communicate.stream_sync():

                event_type = event.get("type")

                if event_type == "audio":
                    data = event.get("data")

                    if data:
                        audio_file.write(data)

                elif event_type == "WordBoundary":
                    offset = event.get("offset")
                    duration = event.get("duration")
                    text_value = event.get("text")

                    if (
                        offset is not None
                        and duration is not None
                        and text_value
                    ):
                        boundaries.append(
                            {
                                "offset": int(offset),
                                "duration": int(duration),
                                "text": str(text_value),
                            }
                        )

    except Exception as exc:
        raise RuntimeError(
            f"Erreur Edge-TTS avec la voix {voice} : {exc}"
        ) from exc

    if not output_path.exists():
        raise RuntimeError(
            "Edge-TTS n'a pas créé le fichier audio."
        )

    if output_path.stat().st_size == 0:
        raise RuntimeError(
            "Edge-TTS a créé un fichier audio vide."
        )

    return boundaries


# ============================================================
# DURÉE AUDIO
# ============================================================

def get_audio_duration(
    audio_path: Path,
) -> float:
    """
    Obtient la durée exacte de l'audio via FFprobe.
    """

    if not audio_path.exists():
        raise RuntimeError(
            f"Fichier audio introuvable : {audio_path}"
        )

    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]

    result = run_command(
        command,
        timeout=60,
    )

    value = (result.stdout or "").strip()

    try:
        duration = float(value)
    except ValueError as exc:
        raise RuntimeError(
            "Impossible de déterminer la durée de l'audio."
        ) from exc

    if duration <= 0:
        raise RuntimeError(
            "La durée audio est invalide."
        )

    return duration


# ============================================================
# GÉNÉRATION AUDIO
# ============================================================

def generate_audio(
    script: str,
    output_dir: Path,
) -> Tuple[Path, List[Dict], str, float]:
    """
    Génère l'audio avec une voix française disponible.

    Retourne :

        audio_path
        word_boundaries
        voice
        duration
    """

    audio_dir = output_dir / "audio"

    audio_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    audio_path = audio_dir / "narration.mp3"

    voices = get_available_french_voices()

    if not voices:
        raise RuntimeError(
            "Aucune voix française Edge-TTS n'est disponible."
        )

    errors = []

    for voice in voices:

        try:
            if audio_path.exists():
                audio_path.unlink()

            boundaries = synthesize_with_voice(
                script,
                voice,
                audio_path,
            )

            duration = get_audio_duration(
                audio_path
            )

            if duration <= 0:
                raise RuntimeError(
                    "Durée audio invalide."
                )

            if not boundaries:
                st.warning(
                    "Edge-TTS n'a pas retourné de marqueurs "
                    "WordBoundary. Les sous-titres mot par mot "
                    "seront générés par repli."
                )

            return (
                audio_path,
                boundaries,
                voice,
                duration,
            )

        except Exception as exc:
            errors.append(
                f"{voice}: {exc}"
            )

    details = "\n".join(errors)

    raise RuntimeError(
        "Impossible de générer la narration avec les voix disponibles.\n\n"
        f"{details}"
    )# ============================================================
# SOUS-TITRES ASS
# ============================================================

def ass_time(seconds: float) -> str:
    """
    Convertit des secondes en temps ASS.

    Format :
        H:MM:SS.cc
    """

    seconds = max(0.0, float(seconds))

    hours = int(seconds // 3600)

    minutes = int(
        (seconds % 3600) // 60
    )

    remaining = seconds % 60

    centiseconds = int(
        round(remaining * 100)
    )

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


def escape_ass_text(text: str) -> str:
    """
    Protège le texte pour le format ASS.
    """

    if not text:
        return ""

    text = str(text)

    text = text.replace(
        "\\",
        "\\\\",
    )

    text = text.replace(
        "{",
        "\\{",
    )

    text = text.replace(
        "}",
        "\\}",
    )

    text = text.replace(
        "\n",
        " ",
    )

    return text.strip()


# ============================================================
# FALLBACK SOUS-TITRES
# ============================================================

def estimate_word_boundaries(
    text: str,
    duration: float,
) -> List[Dict]:
    """
    Fallback lorsque Edge-TTS ne fournit pas de WordBoundary.

    On répartit approximativement les mots sur la durée audio.

    Ce n'est pas utilisé lorsque Edge-TTS fournit ses timings réels.
    """

    clean = remove_image_markers(text)

    words = re.findall(
        r"\S+",
        clean,
        flags=re.UNICODE,
    )

    if not words:
        return []

    duration = max(
        0.1,
        float(duration),
    )

    # Répartition pondérée par la longueur des mots.
    weights = [
        max(
            1,
            len(re.sub(r"[^\wÀ-ÿ'-]", "", word)),
        )
        for word in words
    ]

    total_weight = sum(weights)

    boundaries = []

    current_time = 0.0

    for index, word in enumerate(words):

        if index == len(words) - 1:
            word_duration = max(
                0.05,
                duration - current_time,
            )
        else:
            word_duration = (
                duration
                * weights[index]
                / total_weight
            )

            word_duration = max(
                0.05,
                word_duration,
            )

        start = current_time
        end = min(
            duration,
            current_time + word_duration,
        )

        boundaries.append(
            {
                "offset": int(
                    start * 10_000_000
                ),
                "duration": int(
                    (end - start) * 10_000_000
                ),
                "text": word,
            }
        )

        current_time = end

    return boundaries


# ============================================================
# CONSTRUCTION DES SOUS-TITRES
# ============================================================

def build_ass_subtitles(
    boundaries: List[Dict],
    output_path: Path,
    width: int,
    height: int,
) -> Path:
    """
    Crée un fichier ASS avec un mot affiché à la fois.

    Les sous-titres sont placés dans la partie basse de l'écran
    sans être collés au bord.
    """

    if not boundaries:
        raise RuntimeError(
            "Aucun timing de mot disponible pour les sous-titres."
        )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # Position verticale
    # --------------------------------------------------------

    if height > width:
        # Vertical
        margin_v = 260
        font_size = 58
    else:
        # Horizontal
        margin_v = 80
        font_size = 48

    ass_header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes
WrapStyle: 2
YCbCr Matrix: None

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{font_size},&H00FFFFFF,&H00FFFFFF,&H00101010,&H90000000,1,0,0,0,100,100,0,0,1,3,1,2,60,60,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = [ass_header]

    for boundary in boundaries:

        try:
            offset = int(
                boundary.get("offset", 0)
            )

            duration = int(
                boundary.get("duration", 0)
            )

            word = str(
                boundary.get("text", "")
            ).strip()

        except (TypeError, ValueError):
            continue

        if not word:
            continue

        # Edge-TTS utilise des unités de 100 ns.
        start = offset / 10_000_000

        word_duration = duration / 10_000_000

        end = start + max(
            0.05,
            word_duration,
        )

        # Évite les temps négatifs.
        start = max(
            0.0,
            start,
        )

        end = max(
            start + 0.05,
            end,
        )

        safe_word = escape_ass_text(
            word
        )

        line = (
            "Dialogue: 0,"
            f"{ass_time(start)},"
            f"{ass_time(end)},"
            "Default,,0,0,0,,"
            f"{safe_word}"
        )

        lines.append(line)

    if len(lines) <= 1:
        raise RuntimeError(
            "Impossible de créer les événements de sous-titres."
        )

    output_path.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    return output_path


# ============================================================
# DURÉE DES SCÈNES
# ============================================================

def calculate_scene_durations(
    total_duration: float,
    scene_count: int,
) -> List[float]:
    """
    Répartit la durée totale entre les scènes.

    Les durées sont légèrement variées afin d'éviter un changement
    d'image parfaitement mécanique toutes les X secondes.

    La somme finale est toujours exactement égale à la durée audio.
    """

    total_duration = max(
        0.5,
        float(total_duration),
    )

    scene_count = max(
        1,
        int(scene_count),
    )

    if scene_count == 1:
        return [total_duration]

    weights = []

    for _ in range(scene_count):
        weights.append(
            random.uniform(
                0.85,
                1.15,
            )
        )

    weight_sum = sum(weights)

    durations = [
        total_duration * weight / weight_sum
        for weight in weights
    ]

    # --------------------------------------------------------
    # Minimum raisonnable
    # --------------------------------------------------------

    minimum_scene_duration = 0.35

    durations = [
        max(
            minimum_scene_duration,
            value,
        )
        for value in durations
    ]

    # --------------------------------------------------------
    # Correction pour conserver exactement la durée totale
    # --------------------------------------------------------

    current_total = sum(durations)

    difference = (
        total_duration
        - current_total
    )

    durations[-1] += difference

    # Sécurité
    if durations[-1] <= 0:
        durations[-1] = 0.35

        correction = (
            sum(durations)
            - total_duration
        )

        if len(durations) > 1:
            durations[-2] -= correction

    # Dernière correction flottante.
    final_difference = (
        total_duration
        - sum(durations)
    )

    durations[-1] += final_difference

    return durations


# ============================================================
# CRÉATION D'UNE SCÈNE
# ============================================================

def create_image_scene(
    image_path: Path,
    output_path: Path,
    duration: float,
    width: int,
    height: int,
) -> Path:
    """
    Crée une scène vidéo à partir d'une image.

    Un zoom très léger est appliqué afin de donner du mouvement
    sans détourner l'attention du contenu.
    """

    duration = max(
        0.35,
        float(duration),
    )

    fps = 30

    frames = max(
        1,
        int(
            round(
                duration * fps
            )
        ),
    )

    # Intensité très légère.
    zoom_increment = (
        0.0009
        if height > width
        else 0.0007
    )

    zoom_expression = (
        f"min(zoom+{zoom_increment},1.12)"
    )

    filter_complex = (
        "scale="
        f"{width}:"
        f"{height}:"
        "force_original_aspect_ratio=increase,"
        f"crop={width}:{height},"
        "zoompan="
        f"z='{zoom_expression}':"
        "x='iw/2-(iw/zoom/2)':"
        "y='ih/2-(ih/zoom/2)':"
        f"d={frames}:"
        f"s={width}x{height}:"
        f"fps={fps},"
        "format=yuv420p"
    )

    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-loop",
        "1",
        "-i",
        str(image_path),
        "-vf",
        filter_complex,
        "-t",
        f"{duration:.3f}",
        "-r",
        str(fps),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        str(output_path),
    ]

    run_command(
        command,
        timeout=180,
    )

    if not output_path.exists():
        raise RuntimeError(
            f"La scène vidéo n'a pas été créée : {output_path.name}"
        )

    return output_path


# ============================================================
# CONCATÉNATION DES SCÈNES
# ============================================================

def concatenate_scenes(
    scene_paths: List[Path],
    output_path: Path,
) -> Path:
    """
    Assemble les scènes vidéo.
    """

    if not scene_paths:
        raise RuntimeError(
            "Aucune scène à concaténer."
        )

    concat_file = (
        output_path.parent
        / "concat.txt"
    )

    lines = []

    for scene_path in scene_paths:

        if not scene_path.exists():
            raise RuntimeError(
                f"Scène introuvable : {scene_path}"
            )

        # Échappement compatible avec le fichier concat FFmpeg.
        path_string = str(
            scene_path.resolve()
        )

        path_string = path_string.replace(
            "'",
            "'\\''",
        )

        lines.append(
            f"file '{path_string}'"
        )

    concat_file.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
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

    except RuntimeError:
        # ----------------------------------------------------
        # Fallback :
        # réencodage si le concat en stream copy échoue.
        # ----------------------------------------------------

        fallback_command = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
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
            "23",
            "-pix_fmt",
            "yuv420p",
            str(output_path),
        ]

        run_command(
            fallback_command,
            timeout=600,
        )

    if not output_path.exists():
        raise RuntimeError(
            "La concaténation des scènes a échoué."
        )

    return output_path


# ============================================================
# AJOUT AUDIO + SOUS-TITRES
# ============================================================

def add_audio_and_subtitles(
    video_path: Path,
    audio_path: Path,
    ass_path: Path,
    output_path: Path,
    duration: float,
) -> Path:
    """
    Ajoute la narration et les sous-titres à la vidéo.

    La durée finale est alignée sur la narration.
    """

    if not video_path.exists():
        raise RuntimeError(
            f"Vidéo intermédiaire introuvable : {video_path}"
        )

    if not audio_path.exists():
        raise RuntimeError(
            f"Audio introuvable : {audio_path}"
        )

    if not ass_path.exists():
        raise RuntimeError(
            f"Sous-titres introuvables : {ass_path}"
        )

    duration = max(
        0.5,
        float(duration),
    )

    # --------------------------------------------------------
    # Chemin ASS
    # --------------------------------------------------------

    subtitle_path = str(
        ass_path.resolve()
    )

    # Pour le filtre subtitles FFmpeg.
    subtitle_path = subtitle_path.replace(
        "\\",
        "/",
    )

    subtitle_path = subtitle_path.replace(
        ":",
        "\\:",
    )

    subtitle_path = subtitle_path.replace(
        "'",
        "\\'",
    )

    filter_complex = (
        f"subtitles='{subtitle_path}'"
    )

    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video_path),
        "-i",
        str(audio_path),
        "-filter:v",
        filter_complex,
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-t",
        f"{duration:.3f}",
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
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    run_command(
        command,
        timeout=600,
    )

    if not output_path.exists():
        raise RuntimeError(
            "La vidéo finale n'a pas été créée."
        )

    return output_path


# ============================================================
# DURÉE VIDÉO
# ============================================================

def get_video_duration(
    video_path: Path,
) -> float:
    """
    Retourne la durée d'une vidéo.
    """

    if not video_path.exists():
        raise RuntimeError(
            f"Vidéo introuvable : {video_path}"
        )

    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]

    result = run_command(
        command,
        timeout=60,
    )

    value = (
        result.stdout or ""
    ).strip()

    try:
        duration = float(value)
    except ValueError as exc:
        raise RuntimeError(
            "Impossible de lire la durée de la vidéo."
        ) from exc

    if duration <= 0:
        raise RuntimeError(
            "La vidéo possède une durée invalide."
        )

    return duration


# ============================================================
# VALIDATION VIDÉO
# ============================================================

def validate_video_file(
    video_path: Path,
    expected_duration: Optional[float] = None,
    tolerance: float = 2.0,
) -> Dict:
    """
    Vérifie que le fichier vidéo existe et possède une durée valide.
    """

    if not video_path.exists():
        raise RuntimeError(
            "Le fichier vidéo final est introuvable."
        )

    file_size = video_path.stat().st_size

    if file_size <= 0:
        raise RuntimeError(
            "Le fichier vidéo final est vide."
        )

    duration = get_video_duration(
        video_path
    )

    result = {
        "path": video_path,
        "size": file_size,
        "duration": duration,
        "valid": True,
    }

    if expected_duration is not None:

        difference = abs(
            duration
            - float(expected_duration)
        )

        if difference > tolerance:
            result["valid"] = False
            result["duration_difference"] = difference

            raise RuntimeError(
                "La durée de la vidéo finale est incohérente.\n"
                f"Durée attendue : {expected_duration:.2f}s\n"
                f"Durée obtenue : {duration:.2f}s\n"
                f"Écart : {difference:.2f}s"
            )

    return result


# ============================================================
# CONSTRUCTION GÉNÉRALE D'UNE VIDÉO
# ============================================================

def build_video(
    script: str,
    output_dir: Path,
    orientation: str,
    output_filename: str,
    progress_callback=None,
) -> Tuple[Path, Dict]:
    """
    Pipeline complet :

    1. audio
    2. durée réelle
    3. nombre de visuels
    4. téléchargement des visuels
    5. création des scènes
    6. concaténation
    7. sous-titres
    8. ajout audio
    9. validation

    La durée de la vidéo est toujours pilotée par la narration réelle.
    """

    if not script or not script.strip():
        raise RuntimeError(
            "Impossible de produire une vidéo avec un script vide."
        )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # Dimensions
    # --------------------------------------------------------

    if orientation == "portrait":
        width = 1080
        height = 1920
    else:
        width = 1280
        height = 720

    # --------------------------------------------------------
    # Étape 1 : audio
    # --------------------------------------------------------

    if progress_callback:
        progress_callback(
            0.05,
            "Génération de la narration..."
        )

    audio_path, boundaries, voice, audio_duration = (
        generate_audio(
            script,
            output_dir,
        )
    )

    # --------------------------------------------------------
    # Fallback WordBoundary
    # --------------------------------------------------------

    if not boundaries:
        boundaries = estimate_word_boundaries(
            script,
            audio_duration,
        )

    if not boundaries:
        raise RuntimeError(
            "Impossible de construire les sous-titres mot par mot."
        )

    # --------------------------------------------------------
    # Étape 2 : validation durée Short
    # --------------------------------------------------------

    if orientation == "portrait":

        if audio_duration < SHORT_MIN_SECONDS:
            st.warning(
                f"Le Short ne dure que {audio_duration:.1f} secondes. "
                "Le studio conserve néanmoins ce format car le contenu "
                "est exploitable."
            )

        elif audio_duration > SHORT_TARGET_MAX_SECONDS:
            st.warning(
                f"Le Short dure {audio_duration:.1f} secondes. "
                "Il est plus long que la cible habituelle, mais sera "
                "conservé si le contenu reste cohérent."
            )

        if audio_duration > SHORT_MAX_SECONDS:
            st.warning(
                f"Le Short dépasse {SHORT_MAX_SECONDS} secondes. "
                "Une condensation supplémentaire sera préférable lors "
                "d'une prochaine optimisation."
            )

    # --------------------------------------------------------
    # Étape 3 : nombre de visuels
    # --------------------------------------------------------

    visual_target = visual_count_for_duration(
        audio_duration,
        orientation=orientation,
    )

    if progress_callback:
        progress_callback(
            0.15,
            f"Préparation de {visual_target} visuels..."
        )

    # --------------------------------------------------------
    # Étape 4 : récupération des visuels
    # --------------------------------------------------------

    visuals = get_visuals(
        script=script,
        output_dir=output_dir,
        orientation=orientation,
        target_count=visual_target,
    )

    if not visuals:
        raise RuntimeError(
            "Aucun visuel n'est disponible pour le montage."
        )

    # Si moins de visuels que prévu ont réellement été obtenus,
    # on utilise le nombre réel.
    visual_count = len(visuals)

    # --------------------------------------------------------
    # Étape 5 : durées des scènes
    # --------------------------------------------------------

    scene_durations = calculate_scene_durations(
        total_duration=audio_duration,
        scene_count=visual_count,
    )

    scenes_dir = (
        output_dir / "scenes"
    )

    scenes_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    scene_paths = []

    for index, (
        image_path,
        scene_duration,
    ) in enumerate(
        zip(
            visuals,
            scene_durations,
        ),
        start=1,
    ):

        if progress_callback:

            progress = (
                0.20
                + (
                    index
                    / max(1, visual_count)
                )
                * 0.40
            )

            progress_callback(
                progress,
                f"Création de la scène {index}/{visual_count}..."
            )

        scene_path = (
            scenes_dir
            / f"scene_{index:03d}.mp4"
        )

        create_image_scene(
            image_path=image_path,
            output_path=scene_path,
            duration=scene_duration,
            width=width,
            height=height,
        )

        scene_paths.append(
            scene_path
        )

    # --------------------------------------------------------
    # Étape 6 : concaténation
    # --------------------------------------------------------

    if progress_callback:
        progress_callback(
            0.65,
            "Assemblage des scènes..."
        )

    base_video = (
        output_dir
        / "base_video.mp4"
    )

    concatenate_scenes(
        scene_paths,
        base_video,
    )

    # --------------------------------------------------------
    # Étape 7 : sous-titres
    # --------------------------------------------------------

    if progress_callback:
        progress_callback(
            0.74,
            "Création des sous-titres mot par mot..."
        )

    subtitle_path = (
        output_dir
        / "subtitles.ass"
    )

    build_ass_subtitles(
        boundaries=boundaries,
        output_path=subtitle_path,
        width=width,
        height=height,
    )

    # --------------------------------------------------------
    # Étape 8 : audio + sous-titres
    # --------------------------------------------------------

    if progress_callback:
        progress_callback(
            0.82,
            "Finalisation de la vidéo..."
        )

    final_path = (
        output_dir
        / output_filename
    )

    add_audio_and_subtitles(
        video_path=base_video,
        audio_path=audio_path,
        ass_path=subtitle_path,
        output_path=final_path,
        duration=audio_duration,
    )

    # --------------------------------------------------------
    # Étape 9 : validation
    # --------------------------------------------------------

    if progress_callback:
        progress_callback(
            0.95,
            "Vérification de la vidéo..."
        )

    validation = validate_video_file(
        final_path,
        expected_duration=audio_duration,
        tolerance=2.0,
    )

    if progress_callback:
        progress_callback(
            1.0,
            "Vidéo terminée."
        )

    metadata = {
        "voice": voice,
        "audio_duration": audio_duration,
        "video_duration": validation["duration"],
        "visual_count": visual_count,
        "subtitle_count": len(boundaries),
        "orientation": orientation,
        "width": width,
        "height": height,
        "words": count_words(script),
    }

    return final_path, metadata# ============================================================
# CRÉATION D'UN SHORT
# ============================================================

def create_short_video(
    script: str,
    output_dir: Path,
    filename: str,
    progress_callback=None,
) -> Tuple[Path, Dict]:
    """
    Crée une vidéo Short verticale 9:16.
    """

    return build_video(
        script=script,
        output_dir=output_dir,
        orientation="portrait",
        output_filename=filename,
        progress_callback=progress_callback,
    )


# ============================================================
# CRÉATION D'UNE VIDÉO LONGUE
# ============================================================

def create_long_video(
    script: str,
    output_dir: Path,
    filename: str,
    progress_callback=None,
) -> Tuple[Path, Dict]:
    """
    Crée une vidéo longue horizontale 16:9.
    """

    return build_video(
        script=script,
        output_dir=output_dir,
        orientation="landscape",
        output_filename=filename,
        progress_callback=progress_callback,
    )


# ============================================================
# NETTOYAGE DES ANCIENS FICHIERS
# ============================================================

def cleanup_old_runs(
    max_age_hours: int = 24,
) -> None:
    """
    Supprime les anciennes productions temporaires.

    Les fichiers récents sont conservés afin d'éviter de supprimer
    une production actuellement utilisée.
    """

    current_time = time.time()

    for root in [
        TEMP_ROOT,
        OUTPUT_ROOT,
    ]:

        if not root.exists():
            continue

        for item in root.iterdir():

            try:
                age_seconds = (
                    current_time
                    - item.stat().st_mtime
                )

                age_hours = (
                    age_seconds / 3600
                )

                if age_hours <= max_age_hours:
                    continue

                if item.is_dir():
                    shutil.rmtree(
                        item,
                        ignore_errors=True,
                    )

                elif item.is_file():
                    item.unlink(
                        missing_ok=True
                    )

            except OSError:
                continue


# ============================================================
# CRÉATION D'UN DOSSIER DE PRODUCTION
# ============================================================

def create_run_directory(
    topic: str,
) -> Path:
    """
    Crée un dossier unique pour une production.
    """

    timestamp = time.strftime(
        "%Y%m%d_%H%M%S"
    )

    topic_slug = safe_filename(
        topic,
        fallback="production",
    )

    run_dir = (
        OUTPUT_ROOT
        / f"{timestamp}_{topic_slug}"
    )

    run_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    return run_dir


# ============================================================
# AFFICHAGE D'UNE VIDÉO
# ============================================================

def display_video_result(
    video_path: Path,
    metadata: Dict,
    title: str,
) -> None:
    """
    Affiche une production dans Streamlit.
    """

    st.subheader(title)

    if not video_path.exists():
        st.error(
            "Le fichier vidéo n'existe plus."
        )
        return

    try:
        video_bytes = video_path.read_bytes()

        st.video(
            video_bytes
        )

    except Exception as exc:
        st.error(
            f"Impossible d'afficher la vidéo : {exc}"
        )

    # --------------------------------------------------------
    # Informations
    # --------------------------------------------------------

    duration = metadata.get(
        "video_duration",
        metadata.get(
            "audio_duration",
            0,
        ),
    )

    words = metadata.get(
        "words",
        0,
    )

    visuals = metadata.get(
        "visual_count",
        0,
    )

    subtitles = metadata.get(
        "subtitle_count",
        0,
    )

    voice = metadata.get(
        "voice",
        "inconnue",
    )

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            "Durée",
            format_seconds(duration),
        )

    with col2:
        st.metric(
            "Mots",
            words,
        )

    with col3:
        st.metric(
            "Visuels",
            visuals,
        )

    with col4:
        st.metric(
            "Sous-titres",
            subtitles,
        )

    st.caption(
        f"Voix : {voice}"
    )

    # --------------------------------------------------------
    # Téléchargement
    # --------------------------------------------------------

    try:
        st.download_button(
            label="Télécharger la vidéo",
            data=video_bytes,
            file_name=video_path.name,
            mime="video/mp4",
            key=f"download_{video_path.name}",
        )

    except Exception:
        pass


# ============================================================
# BARRE DE PROGRESSION
# ============================================================

def make_progress_callback(
    progress_bar,
    status_placeholder,
):
    """
    Fabrique une fonction compatible avec build_video().
    """

    def callback(
        progress: float,
        message: str,
    ) -> None:

        progress = max(
            0.0,
            min(
                1.0,
                float(progress),
            ),
        )

        progress_bar.progress(
            progress
        )

        status_placeholder.info(
            message
        )

    return callback


# ============================================================
# PRÉPARATION DU SCRIPT PRINCIPAL
# ============================================================

def prepare_main_script(
    topic: str,
) -> Tuple[str, str, int]:
    """
    Génère et prépare le script principal.

    Retourne :
        script
        mode
        nombre_de_mots
    """

    st.info(
        "Génération du contenu scientifique..."
    )

    script = generate_main_script(
        topic
    )

    script = clean_text(
        script
    )

    word_count = count_words(
        script
    )

    if word_count <= 0:
        raise RuntimeError(
            "Le modèle a généré un script vide."
        )

    # --------------------------------------------------------
    # Si le script est très court
    # --------------------------------------------------------

    if word_count < REGENERATE_BELOW:

        st.warning(
            f"Le premier script contient {word_count} mots. "
            "Tentative d'enrichissement avant adaptation."
        )

        try:

            improved_script = (
                regenerate_short_main_script(
                    topic=topic,
                    previous_script=script,
                )
            )

            improved_script = clean_text(
                improved_script
            )

            improved_words = count_words(
                improved_script
            )

            # On ne remplace que si la nouvelle version
            # contient réellement du contenu supplémentaire.
            if improved_words > word_count:
                script = improved_script
                word_count = improved_words

                st.success(
                    f"Script enrichi : {word_count} mots."
                )

            else:
                st.warning(
                    "L'enrichissement n'a pas apporté suffisamment "
                    "de contenu supplémentaire. Le script original "
                    "sera adapté au format le plus pertinent."
                )

        except Exception as exc:

            st.warning(
                "L'enrichissement automatique n'a pas pu être effectué. "
                f"Le studio poursuit avec le script existant.\n\n{exc}"
            )

    # --------------------------------------------------------
    # Choix du format
    # --------------------------------------------------------

    mode = choose_content_mode(
        word_count
    )

    # --------------------------------------------------------
    # IMPORTANT :
    # un texte court ne doit jamais provoquer une erreur
    # uniquement à cause de son nombre de mots.
    # --------------------------------------------------------

    if mode == "regenerate":
        mode = "one_short"

    return (
        script,
        mode,
        word_count,
    )


# ============================================================
# GÉNÉRATION D'UN SHORT ADAPTÉ
# ============================================================

def prepare_short_script(
    topic: str,
    source_script: str,
) -> str:
    """
    Transforme le contenu source en Short.

    La longueur n'est jamais utilisée comme condition
    d'échec automatique.
    """

    short_script = generate_one_short(
        topic=topic,
        source_script=source_script,
    )

    short_script = clean_text(
        short_script
    )

    if not short_script:
        raise RuntimeError(
            "Le Short généré est vide."
        )

    short_script = fit_short_script(
        topic=topic,
        script=short_script,
        part_label="Short",
    )

    return short_script


# ============================================================
# GÉNÉRATION DES DEUX SHORTS
# ============================================================

def prepare_two_short_scripts(
    topic: str,
    source_script: str,
) -> Tuple[str, str]:
    """
    Transforme un contenu source en deux Shorts cohérents.
    """

    part1, part2 = generate_two_shorts(
        topic=topic,
        source_script=source_script,
    )

    part1 = fit_short_script(
        topic=topic,
        script=part1,
        part_label="Partie 1",
    )

    part2 = fit_short_script(
        topic=topic,
        script=part2,
        part_label="Partie 2",
    )

    return (
        part1,
        part2,
    )


# ============================================================
# GÉNÉRATION VIDÉO AVEC PROGRESSION
# ============================================================

def run_video_generation(
    script: str,
    output_dir: Path,
    orientation: str,
    filename: str,
    label: str,
) -> Tuple[Path, Dict]:

    st.markdown(
        f"### {label}"
    )

    progress_bar = st.progress(
        0.0
    )

    status_placeholder = st.empty()

    callback = make_progress_callback(
        progress_bar,
        status_placeholder,
    )

    if orientation == "portrait":

        video_path, metadata = (
            create_short_video(
                script=script,
                output_dir=output_dir,
                filename=filename,
                progress_callback=callback,
            )
        )

    else:

        video_path, metadata = (
            create_long_video(
                script=script,
                output_dir=output_dir,
                filename=filename,
                progress_callback=callback,
            )
        )

    progress_bar.progress(
        1.0
    )

    status_placeholder.success(
        f"{label} terminée."
    )

    return (
        video_path,
        metadata,
    )


# ============================================================
# INTERFACE STREAMLIT
# ============================================================

def configure_page() -> None:
    """
    Configuration de la page Streamlit.
    """

    st.set_page_config(
        page_title=APP_TITLE,
        page_icon="🎬",
        layout="wide",
        initial_sidebar_state="expanded",
    )


def render_header() -> None:
    """
    En-tête de l'application.
    """

    st.title(
        "🎬 Studio Vidéo IA"
    )

    st.write(
        "Génération automatique de contenus captivants "
        "sur la psychologie, le cerveau et le comportement humain."
    )

    st.divider()


def render_sidebar() -> Dict:
    """
    Paramètres de production.
    """

    st.sidebar.header(
        "Paramètres"
    )

    topic = st.sidebar.text_area(
        "Sujet",
        value="Pourquoi ton cerveau procrastine",
        height=100,
        help=(
            "Indiquez le sujet scientifique que le studio doit "
            "transformer en contenu vidéo."
        ),
    )

    st.sidebar.divider()

    st.sidebar.subheader(
        "Formats automatiques"
    )

    st.sidebar.caption(
        "Le studio choisit automatiquement le format selon "
        "la quantité réelle de contenu."
    )

    st.sidebar.markdown(
        """
**Moins de 200 mots**
→ tentative d'enrichissement puis adaptation

**200 à 349 mots**
→ 1 Short

**350 à 699 mots**
→ 2 Shorts cohérents

**700 mots ou plus**
→ vidéo longue + teaser
"""
    )

    st.sidebar.divider()

    st.sidebar.subheader(
        "Principe important"
    )

    st.sidebar.caption(
        "La longueur n'est jamais une raison suffisante "
        "pour faire échouer une production. Le contenu est "
        "adapté au format le plus pertinent."
    )

    return {
        "topic": topic.strip(),
    }


# ============================================================
# AFFICHAGE DU SCRIPT
# ============================================================

def display_script(
    title: str,
    script: str,
) -> None:
    """
    Affiche le script dans une zone dépliable.
    """

    with st.expander(
        title,
        expanded=False,
    ):
        st.text(
            remove_image_markers(script)
        )

        markers = extract_image_markers(
            script
        )

        if markers:

            st.caption(
                f"{len(markers)} marqueurs visuels détectés."
            )


# ============================================================
# WORKFLOW PRINCIPAL
# ============================================================

def main() -> None:

    configure_page()

    render_header()

    cleanup_old_runs()

    settings = render_sidebar()

    topic = settings.get(
        "topic",
        "",
    )

    if not topic:

        st.warning(
            "Veuillez saisir un sujet."
        )

        return

    st.subheader(
        "Sujet sélectionné"
    )

    st.info(
        topic
    )

    generate_button = st.button(
        "🚀 Générer la vidéo",
        type="primary",
        use_container_width=True,
    )

    if not generate_button:
        return

    # --------------------------------------------------------
    # Vérifications initiales
    # --------------------------------------------------------

    try:
        ensure_ffmpeg()

    except Exception as exc:

        st.error(
            f"FFmpeg n'est pas correctement configuré :\n\n{exc}"
        )

        return

    if not OPENROUTER_API_KEY:

        st.error(
            "La clé OPENROUTER_API_KEY est absente."
        )

        st.stop()

    if not PEXELS_API_KEY:

        st.warning(
            "PEXELS_API_KEY est absente. "
            "Le studio utilisera des visuels de secours."
        )

    # --------------------------------------------------------
    # Dossier de production
    # --------------------------------------------------------

    run_dir = create_run_directory(
        topic
    )

    try:

        # ====================================================
        # 1. GÉNÉRATION DU SCRIPT PRINCIPAL
        # ====================================================

        script, mode, word_count = (
            prepare_main_script(
                topic
            )
        )

        st.success(
            f"Script généré : {word_count} mots."
        )

        st.caption(
            f"Mode sélectionné : {mode}"
        )

        display_script(
            "Voir le script principal",
            script,
        )

        # ====================================================
        # 2. UN SHORT
        # ====================================================

        if mode == "one_short":

            st.info(
                "Format sélectionné : 1 Short vertical."
            )

            short_script = (
                prepare_short_script(
                    topic=topic,
                    source_script=script,
                )
            )

            display_script(
                "Voir le script du Short",
                short_script,
            )

            short_dir = (
                run_dir / "short"
            )

            video_path, metadata = (
                run_video_generation(
                    script=short_script,
                    output_dir=short_dir,
                    orientation="portrait",
                    filename="short.mp4",
                    label="Short vertical",
                )
            )

            st.divider()

            display_video_result(
                video_path=video_path,
                metadata=metadata,
                title="🎬 Short final",
            )

        # ====================================================
        # 3. DEUX SHORTS
        # ====================================================

        elif mode == "two_shorts":

            st.info(
                "Format sélectionné : 2 Shorts verticaux cohérents."
            )

            part1, part2 = (
                prepare_two_short_scripts(
                    topic=topic,
                    source_script=script,
                )
            )

            display_script(
                "Voir la Partie 1",
                part1,
            )

            display_script(
                "Voir la Partie 2",
                part2,
            )

            # ------------------------------------------------
            # Partie 1
            # ------------------------------------------------

            part1_dir = (
                run_dir / "partie_1"
            )

            video1, metadata1 = (
                run_video_generation(
                    script=part1,
                    output_dir=part1_dir,
                    orientation="portrait",
                    filename="short_partie_1.mp4",
                    label="Short Partie 1",
                )
            )

            st.divider()

            display_video_result(
                video_path=video1,
                metadata=metadata1,
                title="🎬 Short Partie 1",
            )

            st.divider()

            # ------------------------------------------------
            # Partie 2
            # ------------------------------------------------

            part2_dir = (
                run_dir / "partie_2"
            )

            video2, metadata2 = (
                run_video_generation(
                    script=part2,
                    output_dir=part2_dir,
                    orientation="portrait",
                    filename="short_partie_2.mp4",
                    label="Short Partie 2",
                )
            )

            st.divider()

            display_video_result(
                video_path=video2,
                metadata=metadata2,
                title="🎬 Short Partie 2",
            )

        # ====================================================
        # 4. VIDÉO LONGUE + TEASER
        # ====================================================

        elif mode == "long":

            st.info(
                "Format sélectionné : vidéo longue 16:9 + teaser vertical."
            )

            display_script(
                "Voir le script de la vidéo longue",
                script,
            )

            # ------------------------------------------------
            # Vidéo longue
            # ------------------------------------------------

            long_dir = (
                run_dir / "long"
            )

            long_video, long_metadata = (
                run_video_generation(
                    script=script,
                    output_dir=long_dir,
                    orientation="landscape",
                    filename="video_longue.mp4",
                    label="Vidéo longue",
                )
            )

            st.divider()

            display_video_result(
                video_path=long_video,
                metadata=long_metadata,
                title="🎬 Vidéo longue finale",
            )

            st.divider()

            # ------------------------------------------------
            # Teaser
            # ------------------------------------------------

            st.info(
                "Création du teaser vertical..."
            )

            teaser_script = generate_teaser(
                topic=topic,
                source_script=script,
            )

            teaser_script = clean_text(
                teaser_script
            )

            if not teaser_script:

                raise RuntimeError(
                    "Le teaser généré est vide."
                )

            display_script(
                "Voir le script du teaser",
                teaser_script,
            )

            teaser_dir = (
                run_dir / "teaser"
            )

            teaser_video, teaser_metadata = (
                run_video_generation(
                    script=teaser_script,
                    output_dir=teaser_dir,
                    orientation="portrait",
                    filename="teaser.mp4",
                    label="Teaser vertical",
                )
            )

            st.divider()

            display_video_result(
                video_path=teaser_video,
                metadata=teaser_metadata,
                title="🎬 Teaser final",
            )

        # ====================================================
        # 5. MODE INCONNU
        # ====================================================

        else:

            raise RuntimeError(
                f"Mode de production inconnu : {mode}"
            )

        # ====================================================
        # FIN
        # ====================================================

        st.success(
            "✅ Production terminée avec succès."
        )

        st.caption(
            f"Dossier de production : {run_dir}"
        )

    except Exception as exc:

        st.error(
            "❌ Une erreur est survenue pendant la production."
        )

        st.exception(
            exc
        )

        st.warning(
            "La production a été arrêtée proprement. "
            "Les fichiers déjà créés restent dans le dossier "
            "de cette production afin de faciliter le diagnostic."
        )


# ============================================================
# POINT D'ENTRÉE
# ============================================================

if __name__ == "__main__":
    main()
