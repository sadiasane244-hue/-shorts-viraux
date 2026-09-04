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
# CONFIGURATION GÉNÉRALE
# ============================================================

APP_TITLE = "Studio Vidéo IA"

BASE_DIR = Path(__file__).resolve().parent

TEMP_ROOT = BASE_DIR / "temp_video"
OUTPUT_ROOT = BASE_DIR / "outputs"
ASSETS_ROOT = BASE_DIR / "assets"

TEMP_ROOT.mkdir(
    parents=True,
    exist_ok=True,
)

OUTPUT_ROOT.mkdir(
    parents=True,
    exist_ok=True,
)

ASSETS_ROOT.mkdir(
    parents=True,
    exist_ok=True,
)


# ============================================================
# API ET MODÈLES
# ============================================================

OPENROUTER_URL = (
    "https://openrouter.ai/api/v1/chat/completions"
)

OPENROUTER_MODEL = (
    "meta-llama/llama-3.3-70b-instruct"
)

PEXELS_SEARCH_URL = (
    "https://api.pexels.com/v1/search"
)


# ============================================================
# RÈGLES DE FORMAT
# ============================================================

REGENERATE_BELOW = 200

ONE_SHORT_MIN = 200
ONE_SHORT_MAX = 349

TWO_SHORTS_MIN = 350
TWO_SHORTS_MAX = 699

LONG_MIN = 700


# ============================================================
# CONTRAINTES SHORT
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
# CONTRAINTES VIDÉO LONGUE
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
# VARIABLES STREAMLIT
# ============================================================

IMAGE_MARKER_RE = re.compile(
    r"\[IMAGE\s*:\s*(.*?)\]",
    flags=re.IGNORECASE | re.DOTALL,
)


# ============================================================
# OUTILS TEXTE
# ============================================================

def get_secret(
    name: str,
    default: str = "",
) -> str:
    """
    Récupère une variable depuis les secrets Streamlit
    ou depuis les variables d'environnement.
    """

    try:
        value = st.secrets.get(name)

        if value:
            return str(value).strip()

    except Exception:
        pass

    return os.getenv(
        name,
        default,
    ).strip()


OPENROUTER_API_KEY = get_secret(
    "OPENROUTER_API_KEY"
)

PEXELS_API_KEY = get_secret(
    "PEXELS_API_KEY"
)


def clean_text(
    text: str,
) -> str:
    """
    Nettoie un texte sans modifier son contenu de manière agressive.
    """

    if not text:
        return ""

    text = text.replace(
        "\r\n",
        "\n",
    )

    text = text.replace(
        "\r",
        "\n",
    )

    text = re.sub(
        r"[ \t]+",
        " ",
        text,
    )

    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text,
    )

    return text.strip()


def count_words(
    text: str,
) -> int:
    """
    Compte les mots narratifs en ignorant les marqueurs [IMAGE: ...].
    """

    if not text:
        return 0

    without_markers = IMAGE_MARKER_RE.sub(
        " ",
        text,
    )

    words = re.findall(
        r"\b[\wÀ-ÿ'-]+\b",
        without_markers,
        flags=re.UNICODE,
    )

    return len(words)


def format_seconds(
    seconds: float,
) -> str:
    """
    Transforme une durée en MM:SS.
    """

    seconds = max(
        0,
        float(seconds),
    )

    minutes = int(
        seconds // 60
    )

    remaining = int(
        round(seconds % 60)
    )

    if remaining >= 60:
        minutes += 1
        remaining = 0

    return (
        f"{minutes:02d}:"
        f"{remaining:02d}"
    )


def safe_filename(
    value: str,
    fallback: str = "video",
) -> str:
    """
    Produit un nom de fichier compatible avec le système.
    """

    value = value.strip()

    value = re.sub(
        r"[^\wÀ-ÿ\- ]+",
        "",
        value,
        flags=re.UNICODE,
    )

    value = re.sub(
        r"\s+",
        "_",
        value,
    )

    value = value.strip(
        "_"
    )

    return (
        value[:80]
        or fallback
    )


# ============================================================
# EXÉCUTION DES COMMANDES SYSTÈME
# ============================================================

def run_command(
    command: List[str],
    timeout: int = 600,
) -> subprocess.CompletedProcess:
    """
    Exécute une commande système et remonte une erreur exploitable.
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
            f"Commande interrompue après "
            f"{timeout} secondes."
        ) from exc

    if result.returncode != 0:

        stderr = (
            result.stderr or ""
        ).strip()

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
    Vérifie la présence de FFmpeg et FFprobe.
    """

    ffmpeg_path = shutil.which(
        "ffmpeg"
    )

    ffprobe_path = shutil.which(
        "ffprobe"
    )

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
    """
    Envoie une requête au modèle OpenRouter.
    """

    if not OPENROUTER_API_KEY:

        raise RuntimeError(
            "OPENROUTER_API_KEY est manquante."
        )

    headers = {
        "Authorization": (
            f"Bearer {OPENROUTER_API_KEY}"
        ),
        "Content-Type": "application/json",
        "HTTP-Referer": (
            "https://shorts-viraux-1.onrender.com"
        ),
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
            "OpenRouter a répondu avec "
            f"HTTP {response.status_code}.\n\n"
            f"{details}"
        )

    try:

        data = response.json()

    except ValueError as exc:

        raise RuntimeError(
            "La réponse d'OpenRouter n'est pas "
            "un JSON valide."
        ) from exc

    try:

        content = (
            data["choices"][0]
            ["message"]["content"]
        )

    except (
        KeyError,
        IndexError,
        TypeError,
    ) as exc:

        raise RuntimeError(
            "La réponse d'OpenRouter ne contient "
            "pas de texte exploitable."
        ) from exc

    if not content or not content.strip():

        raise RuntimeError(
            "OpenRouter a renvoyé un contenu vide."
        )

    return clean_text(
        content
    )


# ============================================================
# GÉNÉRATION DU SCRIPT PRINCIPAL
# ============================================================

def generate_main_script(
    topic: str,
) -> str:
    """
    Génère le contenu scientifique principal.
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

Votre mission est de produire des contenus captivants
mais scientifiquement responsables.

RÈGLES ABSOLUES :

1. Ne jamais inventer de faits.
2. Ne jamais inventer d'étude scientifique.
3. Ne jamais inventer de chercheur.
4. Ne jamais inventer de pourcentage.
5. Ne jamais présenter une hypothèse comme un fait établi.
6. Éviter les neuromythes.
7. Ne pas diagnostiquer les spectateurs.
8. Ne pas présenter une explication simpliste comme une vérité universelle.
9. Lorsque les différences individuelles sont importantes,
   le préciser brièvement.
10. Le contenu doit rester compréhensible par quelqu'un
    qui ne connaît rien aux neurosciences.

STYLE :

- commencer par une accroche forte ;
- créer immédiatement une question ou une curiosité ;
- donner progressivement l'explication ;
- utiliser des exemples concrets ;
- éviter les introductions longues ;
- garder un rythme narratif ;
- expliquer le mécanisme plutôt que simplement donner une définition ;
- terminer par une idée mémorable.

Le but est de donner au spectateur envie de rester
jusqu'à la fin.

FORMAT :

Écrivez un script narratif naturel en français.

Utilisez régulièrement des marqueurs visuels sous cette forme :

[IMAGE: description précise du visuel]

Les descriptions doivent correspondre à des images
que l'on pourrait réellement trouver dans une banque d'images.

Pour une vidéo longue, utilisez normalement environ
12 à 36 marqueurs [IMAGE: ...], selon la longueur réelle.

Ne remplissez jamais artificiellement le script
uniquement pour atteindre un nombre de mots.
"""

    user_prompt = f"""
Sujet :

{topic}

Créez maintenant le meilleur script possible sur ce sujet.

Le contenu doit être suffisamment développé pour pouvoir
être transformé automatiquement en vidéo longue ou en
un ou plusieurs Shorts selon sa longueur réelle.

Privilégiez la qualité, la curiosité et la précision
scientifique plutôt qu'un nombre de mots artificiel.
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
# CHOIX AUTOMATIQUE DU FORMAT
# ============================================================

def choose_content_mode(
    word_count: int,
) -> str:
    """
    Détermine le format selon la quantité de contenu.

    La longueur n'est jamais une cause d'échec.
    """

    if word_count < REGENERATE_BELOW:
        return "regenerate"

    if (
        ONE_SHORT_MIN
        <= word_count
        <= ONE_SHORT_MAX
    ):
        return "one_short"

    if (
        TWO_SHORTS_MIN
        <= word_count
        <= TWO_SHORTS_MAX
    ):
        return "two_shorts"

    if word_count >= LONG_MIN:
        return "long"

    return "one_short"


# ============================================================
# ENRICHISSEMENT D'UN SCRIPT TROP COURT
# ============================================================

def regenerate_short_main_script(
    topic: str,
    previous_script: str,
) -> str:
    """
    Essaie d'enrichir un script très court.

    L'enrichissement n'est jamais forcé.
    """

    prompt = f"""
Sujet :

{topic}

Voici le texte actuellement disponible :

{previous_script}

Le texte est court.

Essayez de l'améliorer afin d'obtenir un contenu
réellement exploitable en vidéo.

Ajoutez si cela est pertinent :

- une accroche ;
- une explication claire ;
- un exemple concret ;
- une conclusion mémorable.

Ajoutez plusieurs marqueurs :

[IMAGE: description du visuel]

IMPORTANT :

Ne fabriquez aucun fait.
Ne fabriquez aucune étude.
Ne fabriquez aucun chiffre.
Ne fabriquez aucune citation.

Si le sujet ne permet naturellement pas d'être beaucoup
plus long, conservez un texte plus court.

Le but est d'améliorer le contenu, pas de gonfler
artificiellement le nombre de mots.

Retournez uniquement le script.
"""

    return openrouter_request(
        messages=[
            {
                "role": "system",
                "content": (
                    "Vous êtes un vulgarisateur scientifique "
                    "rigoureux spécialisé en psychologie, "
                    "neurosciences et comportement humain."
                ),
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
    Transforme le contenu source en un Short autonome.
    """

    prompt = f"""
Sujet :

{topic}

Voici le contenu source :

{source_script}

Transformez ce contenu en UN Short vertical autonome.

OBJECTIF :

Le spectateur doit comprendre l'idée principale
même s'il ne voit pas la vidéo longue.

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

Ne cherchez PAS à atteindre artificiellement
un nombre de mots précis.

La longueur doit être déterminée par la quantité
d'informations réellement nécessaire.

Le résultat peut donc être court si le sujet s'y prête.

Ajoutez entre 4 et 12 marqueurs visuels :

[IMAGE: description précise du visuel]

Les marqueurs doivent être répartis dans le texte.

Ne faites aucune référence à :
- "la partie 1"
- "la partie 2"
- "la vidéo précédente"
- "la vidéo suivante"

Retournez uniquement le script.
"""

    return openrouter_request(
        messages=[
            {
                "role": "system",
                "content": (
                    "Vous êtes un scénariste spécialisé "
                    "dans les Shorts de vulgarisation "
                    "scientifique."
                ),
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
    Transforme le contenu source en deux Shorts cohérents.
    """

    prompt = f"""
Sujet :

{topic}

Contenu source :

{source_script}

Transformez ce contenu en DEUX Shorts verticaux cohérents.

IMPORTANT :

Ne coupez surtout pas le texte simplement en deux moitiés.

Vous devez restructurer le contenu afin que chaque Short
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

Une partie peut être beaucoup plus courte que l'autre
si cela correspond naturellement au contenu.

Ne rajoutez jamais de faits inventés pour équilibrer
les longueurs.

Chaque partie doit être exploitable dans une vidéo verticale.

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
                "content": (
                    "Vous êtes un scénariste spécialisé "
                    "dans les contenus courts de psychologie, "
                    "neurosciences et comportement humain."
                ),
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
        r"===\s*PARTIE\s*1\s*===\s*(.*?)"
        r"\s*===\s*PARTIE\s*2\s*===\s*(.*)",
        result,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if not match:

        raise RuntimeError(
            "Le modèle n'a pas retourné les deux parties "
            "dans le format attendu."
        )

    part1 = clean_text(
        match.group(1)
    )

    part2 = clean_text(
        match.group(2)
    )

    if not part1:

        raise RuntimeError(
            "La Partie 1 générée est vide."
        )

    if not part2:

        raise RuntimeError(
            "La Partie 2 générée est vide."
        )

    return (
        part1,
        part2,
    )


# ============================================================
# ADAPTATION D'UN SHORT
# ============================================================

def fit_short_script(
    topic: str,
    script: str,
    part_label: str = "Short",
) -> str:
    """
    Adapte un Short sans imposer artificiellement une longueur.

    C'est ici que l'ancien plantage de la Partie 2 est corrigé.
    """

    script = clean_text(
        script
    )

    if not script:

        raise RuntimeError(
            f"{part_label} : le script est vide."
        )

    initial_words = count_words(
        script
    )

    # --------------------------------------------------------
    # Script très court
    # --------------------------------------------------------

    if initial_words < SHORT_MIN_WORDS:

        prompt = f"""
Sujet :

{topic}

{part_label} :

{script}

Le texte est très court.

Essayez de l'améliorer légèrement afin d'obtenir
un Short cohérent.

Utilisez uniquement les informations déjà présentes
ou des informations scientifiquement défendables.

Ne cherchez PAS à atteindre un nombre de mots précis.

Si le contenu ne permet naturellement pas de faire
plus long, conservez-le.

Ajoutez quelques marqueurs :

[IMAGE: description du visuel]

Retournez uniquement le script.
"""

        try:

            candidate = openrouter_request(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Vous adaptez des scripts courts "
                            "de vulgarisation scientifique."
                        ),
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                max_tokens=1200,
                temperature=0.65,
            )

            candidate = clean_text(
                candidate
            )

            candidate_words = count_words(
                candidate
            )

            if (
                candidate
                and candidate_words >= initial_words
            ):
                script = candidate

        except Exception:

            # Le contenu existant reste exploitable.
            pass

    # --------------------------------------------------------
    # Script très long
    # --------------------------------------------------------

    words = count_words(
        script
    )

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

Supprimez :

- les répétitions ;
- les détails secondaires ;
- les formulations inutiles.

Ne fabriquez aucune information.

Conservez ou recréez des marqueurs :

[IMAGE: description du visuel]

Ne cherchez pas à respecter un nombre de mots exact.

Retournez uniquement le script.
"""

        try:

            candidate = openrouter_request(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Vous êtes un monteur-rédacteur "
                            "spécialisé dans la condensation "
                            "de contenus scientifiques."
                        ),
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                max_tokens=1600,
                temperature=0.62,
            )

            candidate = clean_text(
                candidate
            )

            if (
                candidate
                and count_words(candidate) > 0
            ):
                script = candidate

        except Exception:

            # Si la condensation échoue, on conserve
            # le texte original plutôt que de faire planter
            # toute la production.
            pass

    # --------------------------------------------------------
    # IMPORTANT
    # --------------------------------------------------------

    final_words = count_words(
        script
    )

    if final_words < SHORT_MIN_WORDS:

        st.warning(
            f"{part_label} contient seulement "
            f"{final_words} mots. "
            "Le studio va quand même essayer de produire "
            "le Short en adaptant automatiquement sa durée."
        )

    return script


# ============================================================
# GÉNÉRATION DU TEASER
# ============================================================

def generate_teaser(
    topic: str,
    source_script: str,
) -> str:
    """
    Génère un teaser vertical.
    """

    prompt = f"""
Sujet :

{topic}

Voici le contenu de la vidéo :

{source_script}

Créez un teaser vertical très court.

OBJECTIF :

Donner envie de regarder la vidéo complète
sans raconter toute l'explication.

STRUCTURE :

- accroche intrigante ;
- question ou révélation ;
- curiosité ouverte ;
- conclusion qui donne envie d'en savoir plus.

Ne fabriquez aucun fait.

Le teaser peut être court.

Ne cherchez pas à atteindre artificiellement
une longueur donnée.

Ajoutez entre 4 et 8 marqueurs visuels :

[IMAGE: description précise du visuel]

Retournez uniquement le script.
"""

    return openrouter_request(
        messages=[
            {
                "role": "system",
                "content": (
                    "Vous êtes spécialisé dans les teasers "
                    "vidéo de vulgarisation scientifique."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        max_tokens=1200,
        temperature=0.8,
        )# ============================================================
# MARQUEURS IMAGE
# ============================================================

def extract_image_markers(
    script: str,
) -> List[str]:
    """
    Extrait les descriptions contenues dans :
    [IMAGE: description]
    """

    if not script:
        return []

    markers = []

    for match in IMAGE_MARKER_RE.finditer(
        script
    ):
        description = clean_text(
            match.group(1)
        )

        if description:
            markers.append(
                description
            )

    return markers


def remove_image_markers(
    script: str,
) -> str:
    """
    Supprime les marqueurs visuels du texte
    destiné à la narration.
    """

    if not script:
        return ""

    text = IMAGE_MARKER_RE.sub(
        " ",
        script,
    )

    text = re.sub(
        r"[ \t]+",
        " ",
        text,
    )

    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text,
    )

    return text.strip()


def validate_script_images(
    script: str,
    minimum: int = 4,
    maximum: int = 40,
) -> List[str]:
    """
    Vérifie les marqueurs visuels sans faire échouer
    la production si leur nombre est insuffisant.
    """

    markers = extract_image_markers(
        script
    )

    if len(markers) > maximum:
        markers = markers[:maximum]

    return markers


# ============================================================
# PEXELS
# ============================================================

def pexels_headers() -> Dict[str, str]:
    """
    Prépare les headers de l'API Pexels.
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
    Télécharge un fichier depuis une URL.
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

        with destination.open(
            "wb"
        ) as file:

            for chunk in response.iter_content(
                chunk_size=1024 * 64
            ):

                if chunk:
                    file.write(chunk)

    except OSError:

        return False

    return (
        destination.exists()
        and destination.stat().st_size > 0
    )


def search_pexels_photo(
    query: str,
    orientation: str = "landscape",
) -> Optional[str]:
    """
    Recherche une image Pexels adaptée au format.
    """

    if not PEXELS_API_KEY:
        return None

    query = clean_text(
        query
    )

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

    photos = data.get(
        "photos",
        [],
    )

    if not photos:
        return None

    random.shuffle(
        photos
    )

    for photo in photos:

        if not isinstance(
            photo,
            dict,
        ):
            continue

        sources = photo.get(
            "src",
            {},
        )

        if not isinstance(
            sources,
            dict,
        ):
            continue

        if orientation == "portrait":

            image_url = (
                sources.get("portrait")
                or sources.get("large2x")
                or sources.get("large")
                or sources.get("original")
            )

        else:

            image_url = (
                sources.get("landscape")
                or sources.get("large2x")
                or sources.get("large")
                or sources.get("original")
            )

        if image_url:
            return image_url

    return None


# ============================================================
# PLACEHOLDER
# ============================================================

def create_placeholder(
    destination: Path,
    width: int,
    height: int,
    title: str = "",
) -> Path:
    """
    Crée un visuel de secours.
    """

    width = max(
        320,
        int(width),
    )

    height = max(
        320,
        int(height),
    )

    image = Image.new(
        "RGB",
        (
            width,
            height,
        ),
        (18, 18, 24),
    )

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
    Recadre et redimensionne l'image au format final.
    """

    if orientation == "portrait":

        target_width = 1080
        target_height = 1920

    else:

        target_width = 1280
        target_height = 720

    try:

        with Image.open(
            source
        ) as image:

            image = image.convert(
                "RGB"
            )

            source_width, source_height = (
                image.size
            )

            if (
                source_width <= 0
                or source_height <= 0
            ):
                raise ValueError(
                    "Dimensions d'image invalides."
                )

            target_ratio = (
                target_width
                / target_height
            )

            source_ratio = (
                source_width
                / source_height
            )

            # --------------------------------------------
            # Recadrage
            # --------------------------------------------

            if source_ratio > target_ratio:

                new_width = int(
                    source_height
                    * target_ratio
                )

                left = max(
                    0,
                    (
                        source_width
                        - new_width
                    ) // 2,
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

                new_height = int(
                    source_width
                    / target_ratio
                )

                top = max(
                    0,
                    (
                        source_height
                        - new_height
                    ) // 2,
                )

                image = image.crop(
                    (
                        0,
                        top,
                        source_width,
                        top + new_height,
                    )
                )

            # --------------------------------------------
            # Redimensionnement
            # --------------------------------------------

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
            f"Impossible de normaliser "
            f"l'image {source.name} : {exc}"
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
    Prépare les visuels nécessaires au montage.

    Si le script contient moins de marqueurs que nécessaire,
    les recherches supplémentaires sont générées à partir
    du dernier contexte visuel disponible.
    """

    markers = extract_image_markers(
        script
    )

    if target_count is None:

        target_count = len(
            markers
        )

    target_count = max(
        1,
        int(target_count),
    )

    if markers:

        selected_markers = markers[
            :target_count
        ]

    else:

        selected_markers = [
            "illustration cinématique du sujet principal"
        ]

    # --------------------------------------------------------
    # Complétion
    # --------------------------------------------------------

    while len(
        selected_markers
    ) < target_count:

        base = selected_markers[
            -1
        ]

        selected_markers.append(
            "nouvelle scène visuelle "
            f"liée à : {base}"
        )

    visuals_dir = (
        output_dir / "visuals"
    )

    visuals_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    visuals = []

    for index, description in enumerate(
        selected_markers,
        start=1,
    ):

        raw_path = (
            visuals_dir
            / f"raw_{index:03d}.jpg"
        )

        normalized_path = (
            visuals_dir
            / f"visual_{index:03d}.jpg"
        )

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

                    visuals.append(
                        normalized_path
                    )

                    continue

            except Exception:
                pass

        # ----------------------------------------------------
        # Fallback
        # ----------------------------------------------------

        if orientation == "portrait":

            width = 1080
            height = 1920

        else:

            width = 1280
            height = 720

        placeholder_path = (
            visuals_dir
            / f"fallback_{index:03d}.jpg"
        )

        create_placeholder(
            placeholder_path,
            width,
            height,
            title=description,
        )

        visuals.append(
            placeholder_path
        )

        time.sleep(
            0.10
        )

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
    Calcule le nombre de visuels selon la durée réelle.
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
        round(
            duration
            / seconds_per_visual
        )
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
# EDGE-TTS
# ============================================================

def _edge_tts_list_voices_in_new_loop(
) -> List[Dict]:
    """
    Exécute list_voices dans une nouvelle boucle asyncio.
    """

    result = []
    errors = []

    def runner():

        try:

            voices = asyncio.run(
                edge_tts.list_voices()
            )

            if voices:
                result.extend(
                    voices
                )

        except Exception as exc:

            errors.append(
                exc
            )

    thread = threading.Thread(
        target=runner,
        daemon=True,
    )

    thread.start()
    thread.join()

    if errors:
        raise errors[0]

    return result


def fetch_edge_tts_voices_sync(
) -> List[Dict]:
    """
    Version synchrone robuste de list_voices().
    """

    try:

        asyncio.get_running_loop()

    except RuntimeError:

        return asyncio.run(
            edge_tts.list_voices()
        )

    return _edge_tts_list_voices_in_new_loop()


# ============================================================
# VOIX FRANÇAISES
# ============================================================

def get_available_french_voices(
) -> List[str]:
    """
    Retourne les voix françaises disponibles.
    """

    try:

        voices = (
            fetch_edge_tts_voices_sync()
        )

        available = []

        for voice in voices:

            if not isinstance(
                voice,
                dict,
            ):
                continue

            short_name = voice.get(
                "ShortName",
                "",
            )

            locale = voice.get(
                "Locale",
                "",
            )

            if not short_name:
                continue

            if str(
                locale
            ).lower().startswith(
                "fr-"
            ):
                available.append(
                    short_name
                )

        ordered = []

        for preferred in PREFERRED_VOICES:

            if preferred in available:

                ordered.append(
                    preferred
                )

        for voice in available:

            if voice not in ordered:

                ordered.append(
                    voice
                )

        if ordered:
            return ordered

    except Exception:
        pass

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
    """

    text = remove_image_markers(
        text
    )

    if not text.strip():

        raise RuntimeError(
            "Impossible de générer l'audio : "
            "texte vide."
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

        with output_path.open(
            "wb"
        ) as audio_file:

            for event in communicate.stream_sync():

                event_type = event.get(
                    "type"
                )

                if event_type == "audio":

                    data = event.get(
                        "data"
                    )

                    if data:
                        audio_file.write(
                            data
                        )

                elif event_type == "WordBoundary":

                    offset = event.get(
                        "offset"
                    )

                    duration = event.get(
                        "duration"
                    )

                    text_value = event.get(
                        "text"
                    )

                    if (
                        offset is not None
                        and duration is not None
                        and text_value
                    ):

                        boundaries.append(
                            {
                                "offset": int(
                                    offset
                                ),
                                "duration": int(
                                    duration
                                ),
                                "text": str(
                                    text_value
                                ),
                            }
                        )

    except Exception as exc:

        raise RuntimeError(
            f"Erreur Edge-TTS avec la voix "
            f"{voice} : {exc}"
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
            f"Fichier audio introuvable : "
            f"{audio_path}"
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

    value = (
        result.stdout or ""
    ).strip()

    try:

        duration = float(
            value
        )

    except ValueError as exc:

        raise RuntimeError(
            "Impossible de déterminer "
            "la durée de l'audio."
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
) -> Tuple[
    Path,
    List[Dict],
    str,
    float,
]:
    """
    Génère la narration française.

    Retourne :
        audio_path
        word_boundaries
        voice
        duration
    """

    audio_dir = (
        output_dir / "audio"
    )

    audio_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    audio_path = (
        audio_dir
        / "narration.mp3"
    )

    voices = (
        get_available_french_voices()
    )

    if not voices:

        raise RuntimeError(
            "Aucune voix française Edge-TTS "
            "n'est disponible."
        )

    errors = []

    for voice in voices:

        try:

            if audio_path.exists():

                audio_path.unlink()

            boundaries = (
                synthesize_with_voice(
                    text=script,
                    voice=voice,
                    output_path=audio_path,
                )
            )

            duration = (
                get_audio_duration(
                    audio_path
                )
            )

            if duration <= 0:

                raise RuntimeError(
                    "Durée audio invalide."
                )

            if not boundaries:

                st.warning(
                    "Edge-TTS n'a pas retourné de "
                    "marqueurs WordBoundary. "
                    "Un calcul de secours sera utilisé "
                    "pour les sous-titres."
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

    details = "\n".join(
        errors
    )

    raise RuntimeError(
        "Impossible de générer la narration "
        "avec les voix disponibles.\n\n"
        f"{details}"
    )# ============================================================
# FFPROBE VIDÉO / AUDIO
# ============================================================

def get_media_duration(
    media_path: Path,
) -> float:
    """
    Retourne la durée exacte d'un média.
    """

    if not media_path.exists():
        raise RuntimeError(
            f"Média introuvable : {media_path}"
        )

    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(media_path),
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
            f"Durée impossible à lire pour {media_path.name}."
        ) from exc

    if duration <= 0:
        raise RuntimeError(
            f"Durée invalide pour {media_path.name}."
        )

    return duration


# ============================================================
# SOUS-TITRES MOT PAR MOT
# ============================================================

def split_text_words(
    text: str,
) -> List[str]:
    """
    Découpe un texte en unités de mots pour les sous-titres.
    """

    if not text:
        return []

    return re.findall(
        r"\S+",
        text,
        flags=re.UNICODE,
    )


def build_word_timestamps_from_boundaries(
    text: str,
    boundaries: List[Dict],
    audio_duration: float,
) -> List[Dict]:
    """
    Transforme les événements WordBoundary Edge-TTS
    en segments utilisables par FFmpeg.

    Les offsets Edge-TTS sont exprimés en 100 ns.
    """

    words = split_text_words(
        text
    )

    if not words:
        return []

    result = []

    valid_boundaries = []

    for item in boundaries or []:

        if not isinstance(
            item,
            dict,
        ):
            continue

        try:

            offset = int(
                item.get(
                    "offset",
                    0,
                )
            )

            duration = int(
                item.get(
                    "duration",
                    0,
                )
            )

        except (
            TypeError,
            ValueError,
        ):
            continue

        if offset < 0:
            continue

        if duration < 0:
            duration = 0

        valid_boundaries.append(
            {
                "offset": offset,
                "duration": duration,
                "text": str(
                    item.get(
                        "text",
                        "",
                    )
                ).strip(),
            }
        )

    if not valid_boundaries:
        return build_fallback_word_timestamps(
            text,
            audio_duration,
        )

    # --------------------------------------------------------
    # Edge-TTS peut fournir une quantité légèrement différente
    # de tokens par rapport à notre séparation locale.
    # On utilise donc les boundaries disponibles comme source
    # principale et le texte du script comme source secondaire.
    # --------------------------------------------------------

    boundary_count = len(
        valid_boundaries
    )

    if boundary_count != len(words):

        # Recherche simple par correspondance séquentielle.
        # Si le modèle Edge-TTS a regroupé ou séparé un token,
        # on conserve néanmoins les timings réels.

        usable_count = min(
            boundary_count,
            len(words),
        )

        for index in range(
            usable_count
        ):

            boundary = (
                valid_boundaries[index]
            )

            start = (
                boundary["offset"]
                / 10_000_000
            )

            boundary_duration = (
                boundary["duration"]
                / 10_000_000
            )

            end = (
                start
                + boundary_duration
            )

            result.append(
                {
                    "word": words[index],
                    "start": max(
                        0.0,
                        start,
                    ),
                    "end": max(
                        start + 0.05,
                        end,
                    ),
                }
            )

        # Si certains mots n'ont pas reçu de timing,
        # on les répartit dans la partie restante.
        if usable_count < len(words):

            last_end = (
                result[-1]["end"]
                if result
                else 0.0
            )

            remaining_words = words[
                usable_count:
            ]

            remaining_count = len(
                remaining_words
            )

            remaining_duration = max(
                0.05,
                audio_duration - last_end,
            )

            step = (
                remaining_duration
                / remaining_count
            )

            for index, word in enumerate(
                remaining_words
            ):

                start = (
                    last_end
                    + index * step
                )

                end = min(
                    audio_duration,
                    start + step,
                )

                result.append(
                    {
                        "word": word,
                        "start": start,
                        "end": max(
                            start + 0.05,
                            end,
                        ),
                    }
                )

        return result

    # --------------------------------------------------------
    # Cas normal
    # --------------------------------------------------------

    for index, word in enumerate(
        words
    ):

        boundary = (
            valid_boundaries[index]
        )

        start = (
            boundary["offset"]
            / 10_000_000
        )

        duration = (
            boundary["duration"]
            / 10_000_000
        )

        end = (
            start
            + duration
        )

        result.append(
            {
                "word": word,
                "start": max(
                    0.0,
                    start,
                ),
                "end": max(
                    start + 0.05,
                    end,
                ),
            }
        )

    # --------------------------------------------------------
    # Correction des chevauchements
    # --------------------------------------------------------

    for index in range(
        1,
        len(result),
    ):

        previous = result[
            index - 1
        ]

        current = result[
            index
        ]

        if current["start"] < previous["start"]:

            current["start"] = (
                previous["start"]
            )

        if current["start"] < previous["end"]:

            midpoint = (
                previous["end"]
                + current["start"]
            ) / 2

            previous["end"] = max(
                previous["start"] + 0.05,
                midpoint,
            )

            current["start"] = (
                previous["end"]
            )

        if current["end"] <= current["start"]:

            current["end"] = (
                current["start"]
                + 0.05
            )

    # --------------------------------------------------------
    # Limitation à la durée réelle
    # --------------------------------------------------------

    for item in result:

        item["start"] = min(
            max(
                0.0,
                item["start"],
            ),
            audio_duration,
        )

        item["end"] = min(
            max(
                item["start"] + 0.05,
                item["end"],
            ),
            audio_duration,
        )

    return result


def build_fallback_word_timestamps(
    text: str,
    audio_duration: float,
) -> List[Dict]:
    """
    Fallback lorsque Edge-TTS ne fournit pas
    de WordBoundary.

    Ce système n'est pas utilisé lorsque les timings
    Edge-TTS sont disponibles.
    """

    words = split_text_words(
        text
    )

    if not words:
        return []

    # Pondération simple selon la longueur des mots.
    weights = []

    for word in words:

        clean_word = re.sub(
            r"[^\wÀ-ÿ'-]",
            "",
            word,
            flags=re.UNICODE,
        )

        weight = max(
            1.0,
            len(clean_word),
        )

        weights.append(
            weight
        )

    total_weight = sum(
        weights
    )

    if total_weight <= 0:
        total_weight = float(
            len(words)
        )

    result = []

    current_time = 0.0

    for word, weight in zip(
        words,
        weights,
    ):

        duration = (
            audio_duration
            * weight
            / total_weight
        )

        start = current_time

        end = min(
            audio_duration,
            start + duration,
        )

        result.append(
            {
                "word": word,
                "start": start,
                "end": max(
                    start + 0.05,
                    end,
                ),
            }
        )

        current_time = end

    return result


def escape_ass_text(
    text: str,
) -> str:
    """
    Échappe le texte destiné au format ASS.
    """

    text = str(
        text
    )

    text = text.replace(
        "\\",
        r"\\",
    )

    text = text.replace(
        "{",
        r"\{",
    )

    text = text.replace(
        "}",
        r"\}",
    )

    text = text.replace(
        "\n",
        " ",
    )

    return text


def ass_timestamp(
    seconds: float,
) -> str:
    """
    Convertit les secondes vers le format ASS :
    H:MM:SS.cc
    """

    seconds = max(
        0.0,
        float(seconds),
    )

    total_centiseconds = int(
        round(
            seconds * 100
        )
    )

    hours = (
        total_centiseconds
        // 360000
    )

    remainder = (
        total_centiseconds
        % 360000
    )

    minutes = (
        remainder
        // 6000
    )

    remainder %= 6000

    secs = (
        remainder
        // 100
    )

    centiseconds = (
        remainder
        % 100
    )

    return (
        f"{hours}:"
        f"{minutes:02d}:"
        f"{secs:02d}."
        f"{centiseconds:02d}"
    )


def create_word_by_word_ass(
    word_timestamps: List[Dict],
    output_path: Path,
    orientation: str = "landscape",
) -> Path:
    """
    Crée un fichier ASS avec un mot affiché à la fois.

    Position :
    bas de l'écran.

    Objectif :
    ne jamais placer les sous-titres au centre de la vidéo.
    """

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if orientation == "portrait":

        play_res_x = 1080
        play_res_y = 1920

        font_size = 58
        margin_v = 190

    else:

        play_res_x = 1280
        play_res_y = 720

        font_size = 42
        margin_v = 70

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {play_res_x}",
        f"PlayResY: {play_res_y}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, "
        "SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, "
        "Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        (
            "Style: Default,Arial,"
            f"{font_size},"
            "&H00FFFFFF,"
            "&H00FFFFFF,"
            "&H00000000,"
            "&H80000000,"
            "1,0,0,0,"
            "100,100,0,0,"
            "1,3,1,"
            "2,40,40,"
            f"{margin_v},1"
        ),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, "
        "MarginR, MarginV, Effect, Text",
    ]

    for item in word_timestamps:

        word = escape_ass_text(
            item.get(
                "word",
                "",
            )
        )

        if not word:
            continue

        start = ass_timestamp(
            item.get(
                "start",
                0,
            )
        )

        end = ass_timestamp(
            item.get(
                "end",
                0,
            )
        )

        if end <= start:
            continue

        lines.append(
            "Dialogue: 0,"
            f"{start},"
            f"{end},"
            "Default,,"
            "0,0,0,"
            f"{margin_v},"
            "0,"
            f"{word}"
        )

    output_path.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    return output_path


# ============================================================
# DÉCOUPAGE DU SCRIPT EN SCÈNES
# ============================================================

def prepare_scene_text(
    script: str,
) -> str:
    """
    Nettoie le script pour le montage.
    """

    return remove_image_markers(
        script
    )


def estimate_scene_durations(
    text: str,
    audio_duration: float,
    scene_count: int,
) -> List[float]:
    """
    Distribue la durée audio entre les scènes.

    La somme finale est exactement égale à la durée audio.
    """

    scene_count = max(
        1,
        int(scene_count),
    )

    words = split_text_words(
        text
    )

    if not words:

        return [
            audio_duration
            / scene_count
        ] * scene_count

    # Répartition approximative selon le nombre de mots.
    base = len(words) // scene_count
    remainder = (
        len(words)
        % scene_count
    )

    word_counts = []

    for index in range(
        scene_count
    ):

        count = base

        if index < remainder:
            count += 1

        word_counts.append(
            max(
                1,
                count,
            )
        )

    total_words = sum(
        word_counts
    )

    durations = []

    for count in word_counts:

        duration = (
            audio_duration
            * count
            / total_words
        )

        durations.append(
            duration
        )

    # Correction flottante.
    difference = (
        audio_duration
        - sum(durations)
    )

    durations[-1] += difference

    return durations


# ============================================================
# CONVERSION DES VISUELS EN VIDÉOS DE SCÈNES
# ============================================================

def create_scene_video(
    image_path: Path,
    duration: float,
    output_path: Path,
    orientation: str = "landscape",
) -> Path:
    """
    Transforme une image en scène vidéo avec un léger
    mouvement de zoom pour éviter un rendu totalement statique.
    """

    duration = max(
        0.10,
        float(duration),
    )

    if orientation == "portrait":

        width = 1080
        height = 1920

    else:

        width = 1280
        height = 720

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # Mouvement Ken Burns léger.
    zoom_filter = (
        "scale="
        f"{width * 2}:"
        f"{height * 2}:"
        "force_original_aspect_ratio=increase,"
        f"crop={width * 2}:{height * 2},"
        "zoompan="
        f"z='min(zoom+0.0008,1.08)':"
        f"d=1:"
        f"s={width}x{height}:"
        "fps=30,"
        "setsar=1"
    )

    command = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-i",
        str(image_path),
        "-vf",
        zoom_filter,
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

    if not output_path.exists():

        raise RuntimeError(
            f"La scène vidéo n'a pas été créée : "
            f"{output_path.name}"
        )

    return output_path


# ============================================================
# CONCATÉNATION DES SCÈNES
# ============================================================

def concat_scene_videos(
    scene_paths: List[Path],
    output_path: Path,
) -> Path:
    """
    Assemble toutes les scènes vidéo.
    """

    if not scene_paths:

        raise RuntimeError(
            "Aucune scène vidéo à concaténer."
        )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    concat_file = (
        output_path.parent
        / "concat.txt"
    )

    lines = []

    for scene_path in scene_paths:

        absolute_path = (
            scene_path.resolve()
        )

        escaped = (
            str(
                absolute_path
            )
            .replace(
                "'",
                "'\\''",
            )
        )

        lines.append(
            f"file '{escaped}'"
        )

    concat_file.write_text(
        "\n".join(lines),
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
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    run_command(
        command,
        timeout=300,
    )

    if not output_path.exists():

        raise RuntimeError(
            "La concaténation des scènes a échoué."
        )

    return output_path


# ============================================================
# AJOUT AUDIO
# ============================================================

def attach_audio(
    video_path: Path,
    audio_path: Path,
    output_path: Path,
) -> Path:
    """
    Ajoute la narration au montage.
    """

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(audio_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
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
        timeout=300,
    )

    if not output_path.exists():

        raise RuntimeError(
            "Impossible d'ajouter la narration à la vidéo."
        )

    return output_path


# ============================================================
# SOUS-TITRES
# ============================================================

def burn_subtitles(
    video_path: Path,
    subtitle_path: Path,
    output_path: Path,
) -> Path:
    """
    Incruste les sous-titres dans la vidéo.
    """

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # Le chemin du fichier ASS doit être correctement échappé
    # pour le filtre subtitles de FFmpeg.
    subtitle_string = (
        str(
            subtitle_path.resolve()
        )
        .replace(
            "\\",
            "/",
        )
        .replace(
            ":",
            r"\:",
        )
        .replace(
            "'",
            r"\'",
        )
    )

    vf = (
        f"subtitles='{subtitle_string}'"
    )

    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-c:a",
        "copy",
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
            "Impossible d'incruster les sous-titres."
        )

    return output_path


# ============================================================
# MONTAGE COMPLET
# ============================================================

def build_video(
    script: str,
    audio_path: Path,
    word_boundaries: List[Dict],
    output_dir: Path,
    orientation: str = "landscape",
    filename: str = "video_finale.mp4",
) -> Path:
    """
    Pipeline complet :

    1. récupère les visuels ;
    2. crée les scènes ;
    3. concatène les scènes ;
    4. ajoute la narration ;
    5. génère les sous-titres mot par mot ;
    6. incruste les sous-titres.
    """

    ensure_ffmpeg()

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    duration = get_audio_duration(
        audio_path
    )

    scene_count = visual_count_for_duration(
        duration,
        orientation=orientation,
    )

    visuals = get_visuals(
        script=script,
        output_dir=output_dir,
        orientation=orientation,
        target_count=scene_count,
    )

    if len(visuals) < scene_count:

        scene_count = len(
            visuals
        )

    scene_durations = (
        estimate_scene_durations(
            prepare_scene_text(script),
            duration,
            scene_count,
        )
    )

    scenes_dir = (
        output_dir / "scenes"
    )

    scenes_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    scene_paths = []

    for index in range(
        scene_count
    ):

        scene_path = (
            scenes_dir
            / f"scene_{index + 1:03d}.mp4"
        )

        create_scene_video(
            image_path=visuals[index],
            duration=scene_durations[index],
            output_path=scene_path,
            orientation=orientation,
        )

        scene_paths.append(
            scene_path
        )

    raw_video = (
        output_dir
        / "video_sans_audio.mp4"
    )

    concat_scene_videos(
        scene_paths,
        raw_video,
    )

    video_audio = (
        output_dir
        / "video_audio.mp4"
    )

    attach_audio(
        raw_video,
        audio_path,
        video_audio,
    )

    subtitles_path = (
        output_dir
        / "subtitles.ass"
    )

    narration_text = (
        prepare_scene_text(
            script
        )
    )

    timestamps = (
        build_word_timestamps_from_boundaries(
            narration_text,
            word_boundaries,
            duration,
        )
    )

    create_word_by_word_ass(
        timestamps,
        subtitles_path,
        orientation=orientation,
    )

    final_path = (
        output_dir
        / safe_filename(
            filename,
            fallback="video_finale",
        )
    )

    if final_path.suffix.lower() != ".mp4":

        final_path = final_path.with_suffix(
            ".mp4"
        )

    burn_subtitles(
        video_audio,
        subtitles_path,
        final_path,
    )

    if not final_path.exists():

        raise RuntimeError(
            "Le fichier vidéo final n'existe pas."
        )

    final_duration = get_media_duration(
        final_path
    )

    if final_duration <= 0:

        raise RuntimeError(
            "La durée de la vidéo finale est invalide."
        )

    return final_path# ============================================================
# INTERFACE STREAMLIT
# ============================================================

def render_header() -> None:
    """
    Affiche l'en-tête de l'application.
    """

    st.set_page_config(
        page_title=APP_TITLE,
        page_icon="🎬",
        layout="wide",
    )

    st.title(
        "🎬 Studio Vidéo IA"
    )

    st.caption(
        "Génération automatique de contenus captivants "
        "sur la psychologie, le cerveau et le comportement humain."
    )


def display_script_stats(
    script: str,
    label: str = "Script",
) -> None:
    """
    Affiche les statistiques principales d'un script.
    """

    words = count_words(
        script
    )

    markers = extract_image_markers(
        script
    )

    col1, col2, col3 = st.columns(
        3
    )

    with col1:

        st.metric(
            "Mots",
            words,
        )

    with col2:

        st.metric(
            "Marqueurs image",
            len(markers),
        )

    with col3:

        mode = choose_content_mode(
            words
        )

        if mode == "regenerate":
            mode_label = "À enrichir"
        elif mode == "one_short":
            mode_label = "1 Short"
        elif mode == "two_shorts":
            mode_label = "2 Shorts"
        else:
            mode_label = "Vidéo longue"

        st.metric(
            "Format",
            mode_label,
        )

    st.caption(
        f"{label} : {words} mots | "
        f"{len(markers)} visuels détectés"
    )


def show_video_result(
    title: str,
    video_path: Path,
) -> None:
    """
    Affiche une vidéo produite.
    """

    if not video_path.exists():

        st.error(
            f"Le fichier {title} est introuvable."
        )

        return

    st.subheader(
        title
    )

    st.video(
        str(video_path)
    )

    file_size_mb = (
        video_path.stat().st_size
        / (
            1024 * 1024
        )
    )

    duration = 0.0

    try:

        duration = get_media_duration(
            video_path
        )

    except Exception:
        pass

    col1, col2 = st.columns(
        2
    )

    with col1:

        st.caption(
            f"Durée : {format_seconds(duration)}"
        )

    with col2:

        st.caption(
            f"Taille : {file_size_mb:.1f} Mo"
        )

    with open(
        video_path,
        "rb",
    ) as file:

        video_bytes = file.read()

    st.download_button(
        label=f"⬇️ Télécharger {title}",
        data=video_bytes,
        file_name=video_path.name,
        mime="video/mp4",
        key=f"download_{video_path.stem}",
    )


# ============================================================
# CRÉATION D'UN DOSSIER DE PRODUCTION
# ============================================================

def create_production_directory(
    topic: str,
) -> Path:
    """
    Crée un dossier unique pour chaque génération.
    """

    timestamp = time.strftime(
        "%Y%m%d_%H%M%S"
    )

    slug = safe_filename(
        topic,
        fallback="sujet",
    )

    production_dir = (
        TEMP_ROOT
        / f"{timestamp}_{slug}"
    )

    production_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    return production_dir


# ============================================================
# PIPELINE SHORT
# ============================================================

def process_short(
    topic: str,
    script: str,
    production_dir: Path,
    filename: str,
    label: str,
) -> Path:
    """
    Produit un Short complet.
    """

    script = fit_short_script(
        topic=topic,
        script=script,
        part_label=label,
    )

    words = count_words(
        script
    )

    if words < SHORT_MIN_WORDS:

        st.warning(
            f"{label} ne contient que {words} mots. "
            "Le Short sera produit avec une durée adaptée "
            "à la narration disponible."
        )

    st.write(
        f"**{label} : {words} mots**"
    )

    audio_path, boundaries, voice, duration = (
        generate_audio(
            script=script,
            output_dir=production_dir / label.replace(
                " ",
                "_",
            ),
        )
    )

    st.caption(
        f"Voix : {voice} | "
        f"Durée narration : {format_seconds(duration)}"
    )

    if duration < SHORT_MIN_SECONDS:

        st.warning(
            f"{label} est très court "
            f"({format_seconds(duration)}). "
            "Le studio conserve néanmoins le contenu "
            "au lieu de le rejeter automatiquement."
        )

    elif duration > SHORT_MAX_SECONDS:

        st.warning(
            f"{label} dépasse environ "
            f"{SHORT_MAX_SECONDS} secondes. "
            "Le contenu est conservé afin d'éviter "
            "une suppression artificielle d'informations."
        )

    video_dir = (
        production_dir
        / label.replace(
            " ",
            "_",
        )
    )

    final_path = build_video(
        script=script,
        audio_path=audio_path,
        word_boundaries=boundaries,
        output_dir=video_dir,
        orientation="portrait",
        filename=filename,
    )

    return final_path


# ============================================================
# PIPELINE VIDÉO LONGUE
# ============================================================

def process_long_video(
    topic: str,
    script: str,
    production_dir: Path,
) -> Path:
    """
    Produit une vidéo longue 16:9.
    """

    clean_script = clean_text(
        script
    )

    if not clean_script:

        raise RuntimeError(
            "Le script de la vidéo longue est vide."
        )

    words = count_words(
        clean_script
    )

    st.write(
        f"**Vidéo longue : {words} mots**"
    )

    audio_path, boundaries, voice, duration = (
        generate_audio(
            script=clean_script,
            output_dir=production_dir / "long_video",
        )
    )

    st.caption(
        f"Voix : {voice} | "
        f"Durée narration : {format_seconds(duration)}"
    )

    video_path = build_video(
        script=clean_script,
        audio_path=audio_path,
        word_boundaries=boundaries,
        output_dir=production_dir / "long_video",
        orientation="landscape",
        filename="video_longue.mp4",
    )

    return video_path


# ============================================================
# PIPELINE TEASER
# ============================================================

def process_teaser(
    topic: str,
    source_script: str,
    production_dir: Path,
) -> Path:
    """
    Produit le teaser vertical associé à une vidéo longue.
    """

    teaser_script = generate_teaser(
        topic=topic,
        source_script=source_script,
    )

    teaser_script = clean_text(
        teaser_script
    )

    if not teaser_script:

        raise RuntimeError(
            "Le script du teaser est vide."
        )

    st.write(
        f"**Teaser : {count_words(teaser_script)} mots**"
    )

    teaser_dir = (
        production_dir
        / "teaser"
    )

    audio_path, boundaries, voice, duration = (
        generate_audio(
            script=teaser_script,
            output_dir=teaser_dir,
        )
    )

    st.caption(
        f"Voix teaser : {voice} | "
        f"Durée : {format_seconds(duration)}"
    )

    teaser_path = build_video(
        script=teaser_script,
        audio_path=audio_path,
        word_boundaries=boundaries,
        output_dir=teaser_dir,
        orientation="portrait",
        filename="teaser.mp4",
    )

    return teaser_path


# ============================================================
# SAUVEGARDE D'UNE COPIE DANS OUTPUTS
# ============================================================

def copy_final_output(
    source: Path,
    topic: str,
    suffix: str,
) -> Path:
    """
    Copie le résultat final dans le dossier outputs.
    """

    OUTPUT_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = time.strftime(
        "%Y%m%d_%H%M%S"
    )

    slug = safe_filename(
        topic,
        fallback="video",
    )

    destination = (
        OUTPUT_ROOT
        / (
            f"{timestamp}_"
            f"{slug}_"
            f"{suffix}.mp4"
        )
    )

    shutil.copy2(
        source,
        destination,
    )

    return destination


# ============================================================
# PIPELINE PRINCIPAL
# ============================================================

def run_generation(
    topic: str,
) -> None:
    """
    Orchestre toute la génération.
    """

    if not topic.strip():

        st.error(
            "Veuillez saisir un sujet."
        )

        return

    if not OPENROUTER_API_KEY:

        st.error(
            "La variable OPENROUTER_API_KEY "
            "n'est pas configurée."
        )

        return

    if not PEXELS_API_KEY:

        st.warning(
            "PEXELS_API_KEY n'est pas configurée. "
            "Le studio utilisera des visuels de secours."
        )

    try:

        ensure_ffmpeg()

    except Exception as exc:

        st.error(
            str(exc)
        )

        return

    production_dir = (
        create_production_directory(
            topic
        )
    )

    st.info(
        "Génération du script..."
    )

    progress = st.progress(
        0
    )

    status = st.empty()

    try:

        # ----------------------------------------------------
        # ÉTAPE 1 : SCRIPT
        # ----------------------------------------------------

        status.write(
            "🧠 Génération du script scientifique..."
        )

        script = generate_main_script(
            topic
        )

        progress.progress(
            10
        )

        if not script:

            raise RuntimeError(
                "Le modèle n'a généré aucun script."
            )

        initial_words = count_words(
            script
        )

        st.success(
            f"Script généré : {initial_words} mots"
        )

        display_script_stats(
            script,
            "Script initial",
        )

        # ----------------------------------------------------
        # ÉTAPE 2 : ADAPTATION DES SCRIPTS COURTS
        # ----------------------------------------------------

        mode = choose_content_mode(
            initial_words
        )

        if mode == "regenerate":

            status.write(
                "✏️ Le script est court. "
                "Tentative d'enrichissement..."
            )

            improved_script = (
                regenerate_short_main_script(
                    topic=topic,
                    previous_script=script,
                )
            )

            improved_words = count_words(
                improved_script
            )

            if improved_script and (
                improved_words > initial_words
            ):

                script = improved_script

                st.success(
                    "Le script a été enrichi."
                )

            else:

                st.warning(
                    "Le script n'a pas pu être "
                    "significativement enrichi. "
                    "Il sera quand même adapté."
                )

            mode = choose_content_mode(
                count_words(script)
            )

        progress.progress(
            20
        )

        # ----------------------------------------------------
        # ÉTAPE 3 : CHOIX DU FORMAT
        # ----------------------------------------------------

        final_words = count_words(
            script
        )

        if final_words < ONE_SHORT_MIN:

            # ------------------------------------------------
            # Même un script très court doit être exploité.
            # ------------------------------------------------

            status.write(
                "✂️ Script très court : "
                "création d'un Short adapté..."
            )

            part1 = generate_one_short(
                topic=topic,
                source_script=script,
            )

            part1 = fit_short_script(
                topic=topic,
                script=part1,
                part_label="Short",
            )

            short_path = process_short(
                topic=topic,
                script=part1,
                production_dir=production_dir,
                filename="short.mp4",
                label="Short",
            )

            saved_short = copy_final_output(
                short_path,
                topic,
                "short",
            )

            progress.progress(
                100
            )

            status.success(
                "✅ Short généré avec succès."
            )

            show_video_result(
                "🎬 Short final",
                saved_short,
            )

            return

        # ----------------------------------------------------
        # 200-349 mots : 1 Short
        # ----------------------------------------------------

        if (
            ONE_SHORT_MIN
            <= final_words
            <= ONE_SHORT_MAX
        ):

            status.write(
                "📱 Format sélectionné : "
                "1 Short vertical."
            )

            short_script = generate_one_short(
                topic=topic,
                source_script=script,
            )

            short_script = fit_short_script(
                topic=topic,
                script=short_script,
                part_label="Short",
            )

            progress.progress(
                30
            )

            short_path = process_short(
                topic=topic,
                script=short_script,
                production_dir=production_dir,
                filename="short.mp4",
                label="Short",
            )

            saved_short = copy_final_output(
                short_path,
                topic,
                "short",
            )

            progress.progress(
                100
            )

            status.success(
                "✅ Short généré avec succès."
            )

            show_video_result(
                "🎬 Short final",
                saved_short,
            )

            return

        # ----------------------------------------------------
        # 350-699 mots : 2 Shorts
        # ----------------------------------------------------

        if (
            TWO_SHORTS_MIN
            <= final_words
            <= TWO_SHORTS_MAX
        ):

            status.write(
                "✂️ Restructuration en deux Shorts cohérents..."
            )

            part1, part2 = generate_two_shorts(
                topic=topic,
                source_script=script,
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

            st.success(
                "Format sélectionné : "
                "2 Shorts verticaux, Partie 1 + Partie 2."
            )

            col1, col2 = st.columns(
                2
            )

            with col1:

                st.write(
                    f"**Partie 1 : "
                    f"{count_words(part1)} mots**"
                )

            with col2:

                st.write(
                    f"**Partie 2 : "
                    f"{count_words(part2)} mots**"
                )

            progress.progress(
                30
            )

            status.write(
                "🎙️ Génération de la Partie 1..."
            )

            short1_path = process_short(
                topic=topic,
                script=part1,
                production_dir=production_dir,
                filename="partie_1.mp4",
                label="Partie_1",
            )

            progress.progress(
                60
            )

            status.write(
                "🎙️ Génération de la Partie 2..."
            )

            short2_path = process_short(
                topic=topic,
                script=part2,
                production_dir=production_dir,
                filename="partie_2.mp4",
                label="Partie_2",
            )

            progress.progress(
                90
            )

            saved_short1 = copy_final_output(
                short1_path,
                topic,
                "partie_1",
            )

            saved_short2 = copy_final_output(
                short2_path,
                topic,
                "partie_2",
            )

            progress.progress(
                100
            )

            status.success(
                "✅ Les deux Shorts ont été générés."
            )

            show_video_result(
                "🎬 Short Partie 1",
                saved_short1,
            )

            show_video_result(
                "🎬 Short Partie 2",
                saved_short2,
            )

            return

        # ----------------------------------------------------
        # 700+ mots : vidéo longue + teaser
        # ----------------------------------------------------

        status.write(
            "🎥 Format sélectionné : "
            "vidéo longue 16:9 + teaser vertical."
        )

        st.success(
            "Le script est suffisamment développé "
            "pour produire une vidéo longue."
        )

        progress.progress(
            30
        )

        status.write(
            "🎙️ Génération de la narration longue..."
        )

        long_path = process_long_video(
            topic=topic,
            script=script,
            production_dir=production_dir,
        )

        progress.progress(
            70
        )

        status.write(
            "📱 Génération du teaser vertical..."
        )

        teaser_path = process_teaser(
            topic=topic,
            source_script=script,
            production_dir=production_dir,
        )

        progress.progress(
            90
        )

        saved_long = copy_final_output(
            long_path,
            topic,
            "longue",
        )

        saved_teaser = copy_final_output(
            teaser_path,
            topic,
            "teaser",
        )

        progress.progress(
            100
        )

        status.success(
            "✅ Vidéo longue et teaser générés."
        )

        show_video_result(
            "🎥 Vidéo longue 16:9",
            saved_long,
        )

        show_video_result(
            "📱 Teaser vertical",
            saved_teaser,
        )

    except Exception as exc:

        progress.progress(
            100
        )

        status.error(
            "❌ Une erreur est survenue."
        )

        st.error(
            str(exc)
        )

        with st.expander(
            "Détails techniques"
        ):

            st.exception(
                exc
            )


# ============================================================
# INTERFACE PRINCIPALE
# ============================================================

def main() -> None:
    """
    Point d'entrée Streamlit.
    """

    render_header()

    st.markdown(
        """
Cette application transforme automatiquement un sujet en
contenu vidéo grâce à l'IA.

**Formats automatiques :**

- moins de 200 mots → tentative d'enrichissement puis adaptation ;
- 200 à 349 mots → 1 Short ;
- 350 à 699 mots → 2 Shorts cohérents ;
- 700 mots ou plus → vidéo longue + teaser.

La longueur n'est jamais considérée comme une raison
suffisante pour abandonner une génération.
"""
    )

    st.divider()

    topic = st.text_input(
        "Sujet de la vidéo",
        value="Pourquoi ton cerveau procrastine",
        max_chars=300,
        placeholder=(
            "Exemple : Pourquoi ton cerveau procrastine"
        ),
    )

    st.caption(
        "Conseil : utilisez un sujet précis et intéressant "
        "lié à la psychologie, aux neurosciences ou au "
        "comportement humain."
    )

    generate_button = st.button(
        "🚀 Générer la vidéo",
        type="primary",
        use_container_width=True,
    )

    if generate_button:

        run_generation(
            topic=topic
        )


# ============================================================
# LANCEMENT
# ============================================================

if __name__ == "__main__":

    main()
