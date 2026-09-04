import os
import re
import json
import time
import math
import shutil
import random
import asyncio
import tempfile
import subprocess
from pathlib import Path
from typing import List, Dict, Tuple, Optional

import requests
import streamlit as st
from PIL import Image, ImageDraw, ImageFont
import edge_tts


# ============================================================
# CONFIGURATION GÉNÉRALE
# ============================================================

APP_TITLE = "Studio Vidéo IA"

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Modèle principal
OPENROUTER_MODEL = "meta-llama/llama-3.3-70b-instruct"

# Modèles de secours.
# OpenRouter les essaiera automatiquement si le modèle principal
# ou ses fournisseurs rencontrent un problème.
OPENROUTER_FALLBACK_MODELS = [
    "meta-llama/llama-3.3-70b-instruct",
    "google/gemini-2.0-flash-001",
]

PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"


# ============================================================
# SEUILS DE LONGUEUR
# ============================================================

# Ces valeurs servent à choisir la stratégie de production.
# Elles ne constituent PAS des erreurs bloquantes.

REGENERATE_BELOW = 200

ONE_SHORT_MIN = 200
ONE_SHORT_MAX = 349

TWO_SHORTS_MIN = 350
TWO_SHORTS_MAX = 699

LONG_MIN = 700


# ============================================================
# PARAMÈTRES VIDÉO
# ============================================================

SHORT_TARGET_SECONDS = 45
SHORT_MIN_SECONDS = 25
SHORT_MAX_SECONDS = 60

SHORT_MIN_WORDS = 70
SHORT_MAX_WORDS = 150

LONG_MIN_SECONDS = 180


# ============================================================
# RÉPERTOIRES
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

OUTPUT_DIR = BASE_DIR / "outputs"
TEMP_DIR = BASE_DIR / "temp"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# SECRETS
# ============================================================

def get_secret(name: str, default: str = "") -> str:
    """
    Cherche une variable d'abord dans Streamlit Secrets,
    puis dans les variables d'environnement.
    """
    try:
        value = st.secrets.get(name)
        if value:
            return str(value)
    except Exception:
        pass

    return os.getenv(name, default)


OPENROUTER_API_KEY = get_secret("OPENROUTER_API_KEY")
PEXELS_API_KEY = get_secret("PEXELS_API_KEY")


# ============================================================
# OUTILS TEXTE
# ============================================================

def normalize_text(text: str) -> str:
    if not text:
        return ""

    text = str(text)
    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

    # Nettoyage des espaces
    text = re.sub(r"[ \t]+", " ", text)

    # Nettoyage des lignes multiples
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def count_words(text: str) -> int:
    text = normalize_text(text)

    if not text:
        return 0

    return len(re.findall(r"\b[\wÀ-ÿ'-]+\b", text))


def clean_ai_text(text: str) -> str:
    """
    Nettoie les éventuels blocs Markdown ou balises inutiles
    renvoyés par le modèle.
    """
    if not text:
        return ""

    text = str(text).strip()

    # Retirer les blocs JSON/Markdown accidentels
    text = re.sub(r"^```(?:text|markdown|json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)

    return normalize_text(text)


def extract_json_object(text: str) -> Optional[dict]:
    """
    Essaie d'extraire un objet JSON même si le modèle a ajouté
    quelques explications autour.
    """
    if not text:
        return None

    text = text.strip()

    try:
        return json.loads(text)
    except Exception:
        pass

    match = re.search(r"\{.*\}", text, flags=re.S)

    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            return None

    return None


# ============================================================
# COMMANDES SYSTÈME
# ============================================================

def run_command(
    command: List[str],
    timeout: int = 300,
    cwd: Optional[str] = None
) -> subprocess.CompletedProcess:
    """
    Exécute une commande système avec capture stdout/stderr.
    """
    return subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        cwd=cwd,
        check=False,
    )


def ensure_ffmpeg() -> None:
    """
    Vérifie que FFmpeg et FFprobe sont disponibles.
    """
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")

    if not ffmpeg:
        raise RuntimeError(
            "FFmpeg est introuvable. Vérifiez que ffmpeg est présent dans apt.txt."
        )

    if not ffprobe:
        raise RuntimeError(
            "FFprobe est introuvable. Vérifiez l'installation de FFmpeg."
        )


# ============================================================
# OPENROUTER
# ============================================================

def openrouter_request(
    messages: List[Dict[str, str]],
    temperature: float = 0.7,
    max_tokens: int = 1800,
    timeout: int = 90,
    max_retries: int = 2,
) -> str:
    """
    Appel robuste à OpenRouter.

    Améliorations :
    - fallback entre modèles
    - gestion explicite du 429
    - respect limité de Retry-After
    - timeout borné
    - pas de boucle de retry interminable
    - affichage clair de l'état dans Streamlit
    """

    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY est introuvable. "
            "Ajoutez-la dans les secrets Render."
        )

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://shorts-viraux-1.onrender.com",
        "X-Title": APP_TITLE,
    }

    # On laisse OpenRouter gérer le fallback entre modèles.
    models = list(dict.fromkeys(OPENROUTER_FALLBACK_MODELS))

    payload = {
        "model": OPENROUTER_MODEL,
        "models": models,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "provider": {
            "allow_fallbacks": True,
        },
    }

    last_error = None

    for attempt in range(max_retries + 1):

        try:
            if attempt > 0:
                wait_time = min(4 * attempt, 8)

                st.info(
                    f"Nouvelle tentative OpenRouter dans {wait_time} seconde(s)..."
                )

                time.sleep(wait_time)

            response = requests.post(
                OPENROUTER_URL,
                headers=headers,
                json=payload,
                timeout=timeout,
            )

        except requests.Timeout as exc:
            last_error = (
                "OpenRouter a dépassé le délai d'attente "
                f"de {timeout} secondes."
            )

            if attempt >= max_retries:
                raise RuntimeError(last_error) from exc

            st.warning(
                "OpenRouter met trop de temps à répondre. "
                "Nouvelle tentative..."
            )

            continue

        except requests.RequestException as exc:
            last_error = f"Erreur réseau OpenRouter : {exc}"

            if attempt >= max_retries:
                raise RuntimeError(last_error) from exc

            st.warning(
                "Connexion à OpenRouter interrompue. "
                "Nouvelle tentative..."
            )

            continue

        # ----------------------------------------------------
        # SUCCÈS
        # ----------------------------------------------------

        if response.status_code == 200:

            try:
                data = response.json()
            except Exception as exc:
                raise RuntimeError(
                    "OpenRouter a répondu avec un contenu JSON invalide."
                ) from exc

            try:
                content = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                raise RuntimeError(
                    "Réponse OpenRouter invalide : contenu introuvable."
                ) from exc

            content = clean_ai_text(content)

            if not content:
                raise RuntimeError(
                    "OpenRouter a répondu sans contenu exploitable."
                )

            # Permet de savoir quel modèle a finalement répondu.
            used_model = data.get("model")

            if used_model:
                st.caption(
                    f"Modèle IA utilisé : {used_model}"
                )

            return content

        # ----------------------------------------------------
        # RATE LIMIT 429
        # ----------------------------------------------------

        if response.status_code == 429:

            retry_after_header = response.headers.get("Retry-After")

            retry_after = None

            if retry_after_header:
                try:
                    retry_after = float(retry_after_header)
                except (ValueError, TypeError):
                    retry_after = None

            # On ne laisse jamais l'application dormir plusieurs minutes.
            if retry_after is not None:
                wait_time = min(max(retry_after, 1), 10)
            else:
                wait_time = min(3 * (attempt + 1), 8)

            try:
                error_data = response.json()
                error_message = (
                    error_data.get("error", {}).get("message")
                    if isinstance(error_data, dict)
                    else None
                )
            except Exception:
                error_message = None

            last_error = (
                "OpenRouter a retourné une erreur 429 "
                "(Too Many Requests)."
            )

            if error_message:
                last_error += f" {error_message}"

            if attempt < max_retries:
                st.warning(
                    "OpenRouter limite temporairement la requête (429). "
                    f"Nouvelle tentative dans {wait_time:.0f} seconde(s)."
                )

                time.sleep(wait_time)
                continue

            raise RuntimeError(
                last_error
                + " Les tentatives ont été limitées pour éviter "
                  "un blocage prolongé de la génération."
            )

        # ----------------------------------------------------
        # AUTRES ERREURS HTTP
        # ----------------------------------------------------

        try:
            error_data = response.json()

            if isinstance(error_data, dict):
                error_message = (
                    error_data.get("error", {}).get("message")
                    or error_data.get("message")
                )
            else:
                error_message = None

        except Exception:
            error_message = None

        if not error_message:
            error_message = response.text[:500]

        last_error = (
            f"Erreur OpenRouter HTTP {response.status_code} : "
            f"{error_message}"
        )

        # Les erreurs 4xx classiques ne doivent pas être répétées
        # inutilement, sauf 429 traité ci-dessus.
        if 400 <= response.status_code < 500:
            raise RuntimeError(last_error)

        # Les erreurs 5xx peuvent être temporaires.
        if attempt < max_retries:
            st.warning(
                f"OpenRouter a rencontré une erreur serveur "
                f"({response.status_code}). Nouvelle tentative..."
            )
            continue

        raise RuntimeError(last_error)

    raise RuntimeError(
        last_error or "Erreur inconnue lors de l'appel à OpenRouter."
    )


# ============================================================
# GÉNÉRATION DU SCRIPT PRINCIPAL
# ============================================================

def generate_main_script(topic: str) -> str:
    """
    Génère le script principal à partir du sujet.

    Le contenu doit rester factuel, accessible et captivant.
    """

    topic = normalize_text(topic)

    if not topic:
        raise ValueError("Le sujet est vide.")

    prompt = f"""
Vous êtes un scénariste spécialisé en psychologie,
neurosciences accessibles et comportement humain.

Sujet :
{topic}

Écrivez un script captivant destiné à une vidéo YouTube.

RÈGLES ABSOLUES :

1. Utilisez uniquement des informations scientifiquement plausibles
   et ne présentez jamais une invention comme un fait.

2. N'inventez aucune étude, expérience, citation, statistique,
   nom de chercheur ou résultat scientifique.

3. Si une affirmation est incertaine ou trop controversée,
   reformulez-la prudemment.

4. Le début doit créer immédiatement de la curiosité.

5. Expliquez les mécanismes avec des mots simples.

6. Évitez le jargon inutile.

7. Le ton doit être naturel, dynamique et humain.

8. Le script doit fonctionner avec une narration vocale.

9. Utilisez des paragraphes courts.

10. Ajoutez des marqueurs visuels lorsque cela peut aider,
    sous cette forme :

[IMAGE: description précise]

ou :

[VISUAL: description précise]

11. Les marqueurs doivent correspondre à de vrais éléments
    que l'on pourrait illustrer.

12. N'écrivez aucune introduction du type
    "Bonjour et bienvenue sur ma chaîne".

13. Ne donnez pas de conclusion artificiellement longue.

14. Terminez avec une idée mémorable.

Le script doit être suffisamment développé pour pouvoir être
adapté intelligemment en vidéo longue ou en Short selon sa longueur.

Retournez uniquement le script.
"""

    messages = [
        {
            "role": "system",
            "content": (
                "Vous êtes un scénariste scientifique précis. "
                "Vous ne devez jamais inventer de faits."
            ),
        },
        {
            "role": "user",
            "content": prompt,
        },
    ]

    return openrouter_request(
        messages=messages,
        temperature=0.65,
        max_tokens=2200,
        timeout=90,
        max_retries=2,
    )


# ============================================================
# CHOIX DU MODE DE CONTENU
# ============================================================

def choose_content_mode(word_count: int) -> str:
    """
    Détermine le meilleur format selon la longueur.

    IMPORTANT :
    la longueur ne provoque jamais une erreur à elle seule.
    """

    if word_count < REGENERATE_BELOW:
        return "regenerate"

    if ONE_SHORT_MIN <= word_count <= ONE_SHORT_MAX:
        return "one_short"

    if TWO_SHORTS_MIN <= word_count <= TWO_SHORTS_MAX:
        return "two_shorts"

    if word_count >= LONG_MIN:
        return "long"

    # Cas intermédiaire.
    # On privilégie l'adaptation plutôt que le rejet.
    return "one_short"


# ============================================================
# RÉÉCRITURE POUR UN FORMAT COURT
# ============================================================

def regenerate_short_main_script(topic: str) -> str:
    """
    Si le premier script est beaucoup trop court,
    on demande une nouvelle version mieux adaptée au Short.
    """

    prompt = f"""
Transformez le sujet suivant en un script de Short YouTube
sur la psychologie, le cerveau ou le comportement humain.

Sujet :
{topic}

Contraintes :

- narration naturelle
- accroche très forte dès la première phrase
- explication scientifique accessible
- aucune invention
- aucune fausse statistique
- aucune étude inventée
- environ 90 à 130 mots
- conclusion mémorable
- texte directement utilisable par une voix off

Retournez uniquement le script.
"""

    messages = [
        {
            "role": "system",
            "content": (
                "Vous écrivez des Shorts scientifiques "
                "accessibles et factuellement prudents."
            ),
        },
        {
            "role": "user",
            "content": prompt,
        },
    ]

    return openrouter_request(
        messages=messages,
        temperature=0.7,
        max_tokens=700,
        timeout=75,
        max_retries=2,
    )


# ============================================================
# GÉNÉRATION D'UN SHORT
# ============================================================

def generate_one_short(
    script: str,
    topic: str = ""
) -> str:
    """
    Transforme un script en un Short cohérent.

    Si le script est déjà utilisable, on évite un appel IA
    supplémentaire.
    """

    script = clean_ai_text(script)

    word_count = count_words(script)

    if word_count == 0:
        raise RuntimeError("Impossible de créer un Short à partir d'un script vide.")

    # Si le script est déjà dans une taille raisonnable,
    # aucune réécriture supplémentaire n'est nécessaire.
    if SHORT_MIN_WORDS <= word_count <= SHORT_MAX_WORDS:
        return script

    # Si le script est trop court, adaptation IA.
    if word_count < SHORT_MIN_WORDS:

        if topic:
            return regenerate_short_main_script(topic)

        return script

    # Si le script est trop long, on le restructure.
    return fit_short_script(
        script,
        part_label="Short",
        target_min=SHORT_MIN_WORDS,
        target_max=SHORT_MAX_WORDS,
    )


# ============================================================
# GÉNÉRATION DE DEUX SHORTS
# ============================================================

def generate_two_shorts(script: str, topic: str) -> Tuple[str, str]:
    """
    Divise un script relativement long en deux Shorts cohérents.

    L'objectif est de faire UN appel de restructuration,
    puis de laisser le montage adapter les longueurs finales.
    """

    script = clean_ai_text(script)

    if count_words(script) < 2:
        return script, ""

    prompt = f"""
Vous devez transformer ce script en DEUX Shorts YouTube
sur la psychologie, le cerveau ou le comportement humain.

SUJET :
{topic}

SCRIPT ORIGINAL :
{script}

OBJECTIF :

Créer deux parties autonomes et cohérentes.

PARTIE 1 :
- doit avoir une accroche forte
- introduit le phénomène
- développe la première idée importante
- doit donner envie de comprendre la suite

PARTIE 2 :
- doit reprendre naturellement le sujet
- développe la suite de l'explication
- apporte une conclusion satisfaisante

RÈGLES :

- ne jamais inventer de faits
- ne jamais inventer d'études
- ne pas ajouter de statistiques non présentes
  dans le script original
- conserver les informations essentielles
- phrases naturelles pour une narration vocale
- pas d'introduction inutile
- pas de remplissage
- chaque partie doit pouvoir fonctionner seule

Vous pouvez conserver ou déplacer les marqueurs visuels.

Retournez exactement ce format :

[PARTIE 1]
texte

[PARTIE 2]
texte
"""

    messages = [
        {
            "role": "system",
            "content": (
                "Vous êtes un monteur éditorial spécialisé "
                "dans les vidéos courtes scientifiques."
            ),
        },
        {
            "role": "user",
            "content": prompt,
        },
    ]

    result = openrouter_request(
        messages=messages,
        temperature=0.55,
        max_tokens=1800,
        timeout=90,
        max_retries=2,
    )

    match1 = re.search(
        r"\[PARTIE\s*1\](.*?)(?=\[PARTIE\s*2\]|$)",
        result,
        flags=re.I | re.S,
    )

    match2 = re.search(
        r"\[PARTIE\s*2\](.*)$",
        result,
        flags=re.I | re.S,
    )

    if match1:
        part1 = clean_ai_text(match1.group(1))
    else:
        part1 = ""

    if match2:
        part2 = clean_ai_text(match2.group(1))
    else:
        part2 = ""

    # Sécurité supplémentaire.
    # Si le modèle n'a pas respecté le format,
    # on coupe localement le script en deux.
    if not part1 or not part2:

        words = script.split()

        middle = max(1, len(words) // 2)

        part1 = " ".join(words[:middle]).strip()
        part2 = " ".join(words[middle:]).strip()

    return part1, part2# ============================================================
# ADAPTATION INTELLIGENTE D'UN SCRIPT POUR UN SHORT
# ============================================================

def fit_short_script(
    script: str,
    part_label: str = "Short",
    target_min: int = SHORT_MIN_WORDS,
    target_max: int = SHORT_MAX_WORDS,
) -> str:
    """
    Adapte un texte pour un Short.

    Principe important :
    la longueur n'est jamais considérée comme une erreur fatale.

    Si le texte est déjà exploitable, on le conserve.
    S'il est trop long, on demande une compression à l'IA.
    S'il est trop court, on le conserve plutôt que de provoquer
    une nouvelle cascade d'appels API.
    """

    script = clean_ai_text(script)

    if not script:
        return ""

    word_count = count_words(script)

    # --------------------------------------------------------
    # TEXTE DÉJÀ DANS LA BONNE ZONE
    # --------------------------------------------------------

    if target_min <= word_count <= target_max:
        return script

    # --------------------------------------------------------
    # TEXTE COURT
    # --------------------------------------------------------
    # On ne force PAS l'IA à inventer du contenu pour atteindre
    # artificiellement un nombre de mots.
    #
    # Le montage pourra adapter la durée avec la narration.
    # Cela évite également un appel OpenRouter supplémentaire.

    if word_count < target_min:
        return script

    # --------------------------------------------------------
    # TEXTE TROP LONG
    # --------------------------------------------------------

    prompt = f"""
Adaptez le texte suivant pour un {part_label} YouTube.

Objectif :
obtenir un texte court, naturel et captivant,
idéalement entre {target_min} et {target_max} mots.

TEXTE ORIGINAL :
{script}

RÈGLES :

- conserver les informations essentielles
- ne rien inventer
- ne créer aucune nouvelle statistique
- ne créer aucune étude
- ne pas ajouter de faits absents du texte
- conserver le sens scientifique
- commencer par une accroche forte
- garder uniquement les éléments utiles
- phrases courtes et naturelles
- narration fluide
- terminer avec une idée mémorable
- conserver les marqueurs [IMAGE:] ou [VISUAL:]
  lorsqu'ils restent pertinents

IMPORTANT :
Si atteindre exactement la plage demandée oblige à supprimer
une information importante, privilégiez la qualité et le sens
plutôt que le nombre exact de mots.

Retournez uniquement le texte final.
"""

    messages = [
        {
            "role": "system",
            "content": (
                "Vous êtes un éditeur de scripts scientifiques. "
                "Vous réduisez les textes sans inventer "
                "d'informations."
            ),
        },
        {
            "role": "user",
            "content": prompt,
        },
    ]

    try:
        result = openrouter_request(
            messages=messages,
            temperature=0.45,
            max_tokens=900,
            timeout=75,
            max_retries=1,
        )

        result = clean_ai_text(result)

        if result:
            return result

    except Exception as exc:
        # Une adaptation ratée ne doit pas faire échouer
        # toute la production.
        st.warning(
            f"{part_label} : adaptation IA indisponible. "
            "Le texte original sera utilisé."
        )

    return script


# ============================================================
# GÉNÉRATION D'UN TEASER
# ============================================================

def generate_teaser(script: str, topic: str = "") -> str:
    """
    Génère une version teaser courte à partir d'un script existant.

    Le teaser est conçu pour être utilisé comme Short promotionnel.
    """

    script = clean_ai_text(script)

    if not script:
        return ""

    # Si le script est déjà court, on peut directement l'utiliser.
    word_count = count_words(script)

    if SHORT_MIN_WORDS <= word_count <= SHORT_MAX_WORDS:
        return script

    prompt = f"""
Créez un teaser très captivant pour une vidéo YouTube.

Sujet :
{topic}

Script source :
{script}

Le teaser doit :

- attirer immédiatement l'attention
- poser une question ou créer une curiosité forte
- présenter le phénomène sans tout révéler
- rester scientifiquement correct
- ne rien inventer
- ne pas utiliser de fausse statistique
- ne pas exagérer les résultats scientifiques
- être naturel à l'oral
- faire environ 60 à 100 mots
- finir sur une phrase qui donne envie de regarder la suite

Retournez uniquement le texte du teaser.
"""

    messages = [
        {
            "role": "system",
            "content": (
                "Vous créez des teasers courts, "
                "scientifiques et captivants."
            ),
        },
        {
            "role": "user",
            "content": prompt,
        },
    ]

    try:
        return openrouter_request(
            messages=messages,
            temperature=0.7,
            max_tokens=600,
            timeout=75,
            max_retries=1,
        )

    except Exception:
        # Si l'API rencontre un problème, le teaser peut être
        # créé localement à partir du début du script.
        words = script.split()

        fallback_words = words[:90]

        if not fallback_words:
            return script

        fallback = " ".join(fallback_words).strip()

        return fallback


# ============================================================
# MARQUEURS VISUELS
# ============================================================

IMAGE_MARKER_RE = re.compile(
    r"\[(?:IMAGE|VISUAL)\s*:\s*(.*?)\]",
    flags=re.I | re.S,
)


def extract_visual_markers(text: str) -> List[str]:
    """
    Extrait les descriptions présentes dans :

    [IMAGE: ...]
    [VISUAL: ...]
    """

    if not text:
        return []

    markers = IMAGE_MARKER_RE.findall(text)

    cleaned = []

    for marker in markers:
        marker = normalize_text(marker)

        if marker:
            cleaned.append(marker)

    return cleaned


def remove_visual_markers(text: str) -> str:
    """
    Retire les marqueurs visuels du texte destiné à la narration.
    """

    if not text:
        return ""

    text = IMAGE_MARKER_RE.sub(" ", text)

    # Nettoyage des espaces créés par la suppression.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


# ============================================================
# PEXELS
# ============================================================

def pexels_search(
    query: str,
    per_page: int = 8,
) -> List[dict]:
    """
    Recherche des photos sur Pexels.
    """

    if not PEXELS_API_KEY:
        return []

    query = normalize_text(query)

    if not query:
        return []

    headers = {
        "Authorization": PEXELS_API_KEY,
    }

    params = {
        "query": query,
        "per_page": per_page,
        "orientation": "landscape",
    }

    try:
        response = requests.get(
            PEXELS_SEARCH_URL,
            headers=headers,
            params=params,
            timeout=20,
        )

        if response.status_code != 200:
            return []

        data = response.json()

        photos = data.get("photos", [])

        if not isinstance(photos, list):
            return []

        return photos

    except Exception:
        return []


def download_file(
    url: str,
    destination: Path,
    timeout: int = 30,
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

        if response.status_code != 200:
            return False

        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with open(destination, "wb") as file:
            for chunk in response.iter_content(chunk_size=1024 * 128):
                if chunk:
                    file.write(chunk)

        return destination.exists() and destination.stat().st_size > 0

    except Exception:
        return False


def normalize_image(
    source: Path,
    destination: Path,
    width: int = 1920,
    height: int = 1080,
) -> bool:
    """
    Convertit une image en image JPEG standardisée.
    """

    try:
        with Image.open(source) as image:

            image = image.convert("RGB")

            src_ratio = image.width / image.height
            dst_ratio = width / height

            if src_ratio > dst_ratio:
                # Image trop large
                new_height = height
                new_width = int(height * src_ratio)

            else:
                # Image trop haute
                new_width = width
                new_height = int(width / src_ratio)

            image = image.resize(
                (new_width, new_height),
                Image.Resampling.LANCZOS,
            )

            left = max(0, (new_width - width) // 2)
            top = max(0, (new_height - height) // 2)

            image = image.crop(
                (
                    left,
                    top,
                    left + width,
                    top + height,
                )
            )

            destination.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            image.save(
                destination,
                "JPEG",
                quality=94,
                optimize=True,
            )

        return True

    except Exception:
        return False


# ============================================================
# PLACEHOLDER VISUEL
# ============================================================

def create_placeholder(
    destination: Path,
    text: str,
    width: int = 1920,
    height: int = 1080,
) -> Path:
    """
    Crée un visuel de secours si aucune image pertinente
    n'a été trouvée.
    """

    image = Image.new(
        "RGB",
        (width, height),
        "black",
    )

    draw = ImageDraw.Draw(image)

    # Police système si disponible.
    font = None

    possible_fonts = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ]

    for font_path in possible_fonts:
        if Path(font_path).exists():
            try:
                font = ImageFont.truetype(
                    font_path,
                    64,
                )
                break
            except Exception:
                pass

    if font is None:
        font = ImageFont.load_default()

    text = normalize_text(text)

    # Limitation de longueur du texte affiché.
    if len(text) > 120:
        text = text[:117] + "..."

    bbox = draw.multiline_textbbox(
        (0, 0),
        text,
        font=font,
        spacing=12,
        align="center",
    )

    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    x = (width - text_width) // 2
    y = (height - text_height) // 2

    draw.multiline_text(
        (x, y),
        text,
        font=font,
        spacing=12,
        align="center",
        fill="white",
    )

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    image.save(
        destination,
        "JPEG",
        quality=94,
    )

    return destination


# ============================================================
# VISUELS
# ============================================================

def get_visuals(
    script: str,
    output_dir: Path,
    target_count: Optional[int] = None,
) -> List[Path]:
    """
    Récupère les visuels nécessaires à la vidéo.

    Priorité :
    1. marqueurs visuels du script
    2. recherches Pexels
    3. placeholders de secours
    """

    markers = extract_visual_markers(script)

    if not markers:
        markers = [
            "psychology brain human behavior",
            "human brain neuroscience",
            "person thinking",
        ]

    if target_count is not None:
        target_count = max(1, int(target_count))
        markers = markers[:target_count]

    visual_dir = output_dir / "visuals"
    visual_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    visuals = []

    used_queries = set()

    for index, query in enumerate(markers):

        query = normalize_text(query)

        if not query:
            continue

        # Éviter les recherches strictement identiques.
        query_key = query.lower()

        if query_key in used_queries:
            continue

        used_queries.add(query_key)

        photos = pexels_search(
            query=query,
            per_page=5,
        )

        selected_photo = None

        if photos:
            # Choix aléatoire parmi quelques résultats
            # pour éviter que toutes les vidéos utilisent
            # systématiquement la première image.
            selected_photo = random.choice(
                photos[: min(len(photos), 5)]
            )

        raw_path = visual_dir / f"raw_{index:03d}.jpg"
        final_path = visual_dir / f"visual_{index:03d}.jpg"

        if selected_photo:

            src = (
                selected_photo.get("src", {})
                if isinstance(selected_photo, dict)
                else {}
            )

            image_url = (
                src.get("large2x")
                or src.get("large")
                or src.get("original")
            )

            if image_url:

                if download_file(
                    image_url,
                    raw_path,
                    timeout=30,
                ):

                    if normalize_image(
                        raw_path,
                        final_path,
                    ):
                        visuals.append(final_path)
                        continue

        # ----------------------------------------------------
        # SECOURS
        # ----------------------------------------------------

        placeholder = create_placeholder(
            final_path,
            query,
        )

        visuals.append(placeholder)

    # Si aucune image n'a été récupérée.
    if not visuals:

        fallback_path = visual_dir / "visual_fallback.jpg"

        create_placeholder(
            fallback_path,
            "Psychologie • Cerveau • Comportement",
        )

        visuals.append(fallback_path)

    return visuals


# ============================================================
# NOMBRE DE VISUELS
# ============================================================

def estimate_visual_count(duration_seconds: float) -> int:
    """
    Estime le nombre de visuels nécessaires.

    On change régulièrement de visuel sans provoquer
    un montage excessivement chargé.
    """

    duration_seconds = max(
        1.0,
        float(duration_seconds),
    )

    # Environ un visuel toutes les 4 à 5 secondes.
    count = math.ceil(duration_seconds / 4.5)

    # Limites raisonnables.
    return max(
        5,
        min(count, 24),
    )


# ============================================================
# EDGE-TTS
# ============================================================

def list_tts_voices() -> List[dict]:
    """
    Récupère la liste des voix Edge-TTS.

    Edge-TTS utilise de l'asyncio.
    Cette fonction crée une boucle dédiée pour éviter
    les problèmes de boucle déjà active dans Streamlit.
    """

    async def _get_voices():
        return await edge_tts.list_voices()

    try:
        return asyncio.run(_get_voices())

    except RuntimeError:
        # Une boucle asyncio est déjà active.
        result = []

        def runner():
            nonlocal result

            loop = asyncio.new_event_loop()

            try:
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(
                    _get_voices()
                )
            finally:
                loop.close()
                asyncio.set_event_loop(None)

        import threading

        thread = threading.Thread(
            target=runner,
        )

        thread.start()
        thread.join()

        return result

    except Exception:
        return []


def select_french_voice() -> str:
    """
    Sélectionne une voix française disponible.
    """

    preferred = [
        "fr-FR-DeniseNeural",
        "fr-FR-HenriNeural",
        "fr-FR-VivienneMultilingualNeural",
        "fr-FR-RemyMultilingualNeural",
    ]

    try:
        voices = list_tts_voices()

        available = {
            str(v.get("ShortName"))
            for v in voices
            if isinstance(v, dict)
        }

        for voice in preferred:
            if voice in available:
                return voice

        # Chercher n'importe quelle voix française.
        for voice in voices:

            if not isinstance(voice, dict):
                continue

            short_name = str(
                voice.get("ShortName", "")
            )

            locale = str(
                voice.get("Locale", "")
            )

            if locale.lower().startswith("fr-"):
                return short_name

    except Exception:
        pass

    # Valeur de secours.
    return "fr-FR-DeniseNeural"


async def synthesize_with_voice_async(
    text: str,
    output_path: Path,
    voice: str,
) -> None:
    """
    Synthèse Edge-TTS asynchrone.
    """

    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate="+0%",
        volume="+0%",
    )

    await communicate.save(
        str(output_path),
    )


def synthesize_with_voice(
    text: str,
    output_path: Path,
    voice: str,
) -> None:
    """
    Lance Edge-TTS dans une boucle dédiée.
    """

    async def runner():
        await synthesize_with_voice_async(
            text,
            output_path,
            voice,
        )

    try:
        asyncio.run(runner())

    except RuntimeError:

        result = {
            "error": None,
        }

        def thread_runner():
            loop = asyncio.new_event_loop()

            try:
                asyncio.set_event_loop(loop)

                loop.run_until_complete(
                    runner()
                )

            except Exception as exc:
                result["error"] = exc

            finally:
                loop.close()
                asyncio.set_event_loop(None)

        import threading

        thread = threading.Thread(
            target=thread_runner,
        )

        thread.start()
        thread.join()

        if result["error"]:
            raise result["error"]


def get_audio_duration(audio_path: Path) -> float:
    """
    Récupère la durée d'un fichier audio avec FFprobe.
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
        timeout=30,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Impossible de déterminer la durée audio."
        )

    try:
        return float(result.stdout.strip())
    except Exception as exc:
        raise RuntimeError(
            "Durée audio invalide."
        ) from exc


def generate_audio(
    text: str,
    output_path: Path,
) -> Tuple[Path, float, str]:
    """
    Génère la narration audio et retourne :
    chemin audio
    durée
    voix utilisée
    """

    text = remove_visual_markers(text)

    if not text:
        raise RuntimeError(
            "Impossible de générer une narration à partir d'un texte vide."
        )

    voice = select_french_voice()

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    synthesize_with_voice(
        text=text,
        output_path=output_path,
        voice=voice,
    )

    if not output_path.exists():
        raise RuntimeError(
            "Edge-TTS n'a pas créé le fichier audio."
        )

    duration = get_audio_duration(
        output_path,
    )

    if duration <= 0:
        raise RuntimeError(
            "La durée audio obtenue est invalide."
        )

    return output_path, duration, voiceshort_name = str(
                voice.get("ShortName", "")
            )

            locale = str(
                voice.get("Locale", "")
            )

            if locale.lower().startswith("fr-"):
                return short_name

    except Exception:
        pass

    # Voix française par défaut.
    return "fr-FR-DeniseNeural"


# ============================================================
# SYNTHÈSE VOCALE
# ============================================================

def synthesize_with_voice(
    text: str,
    output_path: Path,
    voice: Optional[str] = None,
    rate: str = "+0%",
    volume: str = "+0%",
) -> Path:
    """
    Génère la narration avec Edge-TTS.
    """

    text = remove_visual_markers(text)
    text = normalize_text(text)

    if not text:
        raise RuntimeError(
            "Impossible de générer l'audio : le texte est vide."
        )

    if voice is None:
        voice = select_french_voice()

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    async def _generate():
        communicate = edge_tts.Communicate(
            text=text,
            voice=voice,
            rate=rate,
            volume=volume,
        )

        await communicate.save(
            str(output_path)
        )

    try:
        asyncio.run(_generate())

    except RuntimeError:
        # Gestion d'une éventuelle boucle asyncio active.
        error_holder = []

        def runner():
            loop = asyncio.new_event_loop()

            try:
                asyncio.set_event_loop(loop)
                loop.run_until_complete(_generate())

            except Exception as exc:
                error_holder.append(exc)

            finally:
                loop.close()
                asyncio.set_event_loop(None)

        import threading

        thread = threading.Thread(
            target=runner
        )

        thread.start()
        thread.join()

        if error_holder:
            raise RuntimeError(
                f"Erreur Edge-TTS : {error_holder[0]}"
            )

    except Exception as exc:
        raise RuntimeError(
            f"Impossible de générer la narration : {exc}"
        ) from exc

    if not output_path.exists():
        raise RuntimeError(
            "Edge-TTS n'a pas créé le fichier audio."
        )

    if output_path.stat().st_size == 0:
        raise RuntimeError(
            "Le fichier audio généré est vide."
        )

    return output_path


# ============================================================
# DURÉE AUDIO
# ============================================================

def get_audio_duration(audio_path: Path) -> float:
    """
    Retourne la durée audio en secondes grâce à FFprobe.
    """

    ensure_ffmpeg()

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
        timeout=30,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Impossible de déterminer la durée de l'audio : "
            + result.stderr[:500]
        )

    try:
        duration = float(
            result.stdout.strip()
        )
    except ValueError as exc:
        raise RuntimeError(
            "Durée audio invalide."
        ) from exc

    if duration <= 0:
        raise RuntimeError(
            "La durée audio est nulle."
        )

    return duration


# ============================================================
# SOUS-TITRES MOT PAR MOT
# ============================================================

def get_word_boundaries(
    text: str,
    audio_path: Path,
    voice: Optional[str] = None,
) -> List[Tuple[str, float, float]]:
    """
    Génère des timings mot par mot.

    Edge-TTS peut fournir des événements WordBoundary.
    Si ceux-ci ne sont pas disponibles, on utilise un timing
    de secours calculé à partir de la durée réelle de l'audio.
    """

    text = remove_visual_markers(text)
    text = normalize_text(text)

    if not text:
        return []

    if voice is None:
        voice = select_french_voice()

    words = re.findall(
        r"\S+",
        text,
    )

    if not words:
        return []

    boundaries = []

    async def _collect():
        communicate = edge_tts.Communicate(
            text=text,
            voice=voice,
        )

        async for event in communicate.stream():

            if event["type"] == "WordBoundary":

                offset = event.get("offset", 0)

                duration = event.get(
                    "duration",
                    0,
                )

                # Edge-TTS utilise des ticks de 100 ns.
                start = float(offset) / 10_000_000
                event_duration = float(duration) / 10_000_000

                word = str(
                    event.get("text", "")
                ).strip()

                if word:
                    boundaries.append(
                        (
                            word,
                            start,
                            max(
                                0.03,
                                event_duration,
                            ),
                        )
                    )

    try:
        asyncio.run(_collect())

    except RuntimeError:
        result_holder = []

        def runner():
            loop = asyncio.new_event_loop()

            try:
                asyncio.set_event_loop(loop)
                loop.run_until_complete(
                    _collect()
                )
                result_holder.extend(
                    boundaries
                )

            except Exception:
                pass

            finally:
                loop.close()
                asyncio.set_event_loop(None)

        import threading

        thread = threading.Thread(
            target=runner
        )

        thread.start()
        thread.join()

    except Exception:
        boundaries = []

    # --------------------------------------------------------
    # VÉRIFICATION DES DONNÉES EDGE-TTS
    # --------------------------------------------------------

    if boundaries:
        duration = get_audio_duration(
            audio_path
        )

        cleaned = []

        for index, item in enumerate(boundaries):

            word, start, word_duration = item

            start = max(
                0.0,
                min(start, duration),
            )

            if index + 1 < len(boundaries):
                next_start = boundaries[index + 1][1]

                end = min(
                    duration,
                    max(
                        start + 0.03,
                        next_start,
                    ),
                )

            else:
                end = min(
                    duration,
                    max(
                        start + word_duration,
                        start + 0.08,
                    ),
                )

            if end > start:
                cleaned.append(
                    (
                        word,
                        start,
                        end,
                    )
                )

        if cleaned:
            return cleaned

    # --------------------------------------------------------
    # FALLBACK
    # --------------------------------------------------------

    duration = get_audio_duration(
        audio_path
    )

    word_count = len(words)

    # Répartition pondérée approximative.
    # Les mots plus longs reçoivent légèrement plus de temps.
    weights = []

    for word in words:
        clean_word = re.sub(
            r"[^\wÀ-ÿ'-]",
            "",
            word,
        )

        weights.append(
            max(
                1.0,
                len(clean_word) ** 0.7,
            )
        )

    total_weight = sum(weights)

    if total_weight <= 0:
        total_weight = float(word_count)

    result = []

    current_time = 0.0

    for word, weight in zip(words, weights):

        word_duration = (
            duration
            * weight
            / total_weight
        )

        start = current_time
        end = min(
            duration,
            current_time + word_duration,
        )

        result.append(
            (
                word,
                start,
                end,
            )
        )

        current_time = end

    return result


# ============================================================
# SOUS-TITRES ASS
# ============================================================

def ass_time(seconds: float) -> str:
    """
    Convertit des secondes vers HH:MM:SS.cc
    """

    seconds = max(
        0.0,
        float(seconds),
    )

    hours = int(
        seconds // 3600
    )

    minutes = int(
        (seconds % 3600) // 60
    )

    remaining = (
        seconds
        % 60
    )

    whole_seconds = int(
        remaining
    )

    centiseconds = int(
        round(
            (remaining - whole_seconds)
            * 100
        )
    )

    if centiseconds >= 100:
        whole_seconds += 1
        centiseconds -= 100

    if whole_seconds >= 60:
        minutes += 1
        whole_seconds -= 60

    if minutes >= 60:
        hours += 1
        minutes -= 60

    return (
        f"{hours:01d}:"
        f"{minutes:02d}:"
        f"{whole_seconds:02d}."
        f"{centiseconds:02d}"
    )


def escape_ass(text: str) -> str:
    """
    Échappe les caractères spéciaux ASS.
    """

    text = str(text)

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


def create_ass_subtitles(
    boundaries: List[Tuple[str, float, float]],
    output_path: Path,
    width: int = 1080,
    height: int = 1920,
) -> Path:
    """
    Crée des sous-titres mot par mot.

    Les sous-titres restent en bas de l'image.
    Une seule unité de texte est affichée à la fois afin
    de garder une lecture très claire.
    """

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # Taille de police adaptée au format.
    if height > width:
        font_size = 64
        margin_vertical = 145
    else:
        font_size = 52
        margin_vertical = 80

    content = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "",
        "[V4+ Styles]",
        (
            "Format: Name, Fontname, Fontsize, PrimaryColour, "
            "SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, "
            "Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
            "MarginL, MarginR, MarginV, Encoding"
        ),
        (
            "Style: Default,Arial,"
            f"{font_size},"
            "&H00FFFFFF,"
            "&H000000FF,"
            "&H00000000,"
            "&H99000000,"
            "1,0,0,0,100,100,0,0,1,3,1,2,"
            "45,45,"
            f"{margin_vertical},1"
        ),
        "",
        "[Events]",
        (
            "Format: Layer, Start, End, Style, Name, "
            "MarginL, MarginR, MarginV, Effect, Text"
        ),
    ]

    for word, start, end in boundaries:

        word = escape_ass(word)

        content.append(
            "Dialogue: 0,"
            f"{ass_time(start)},"
            f"{ass_time(end)},"
            "Default,,0,0,0,,"
            f"{word}"
        )

    output_path.write_text(
        "\n".join(content),
        encoding="utf-8",
    )

    return output_path


# ============================================================
# DURÉE DES SCÈNES
# ============================================================

def distribute_scene_durations(
    total_duration: float,
    visual_count: int,
) -> List[float]:
    """
    Distribue la durée totale entre les visuels.
    """

    total_duration = max(
        1.0,
        float(total_duration),
    )

    visual_count = max(
        1,
        int(visual_count),
    )

    base = total_duration / visual_count

    durations = [
        base
        for _ in range(visual_count)
    ]

    # Petit facteur de variation pour éviter
    # une sensation trop mécanique.
    for index in range(
        visual_count
    ):

        variation = (
            0.94
            + random.random() * 0.12
        )

        durations[index] *= variation

    # Normalisation pour retrouver exactement
    # la durée totale.
    current_total = sum(
        durations
    )

    if current_total <= 0:
        return [
            base
            for _ in range(visual_count)
        ]

    factor = (
        total_duration
        / current_total
    )

    durations = [
        value * factor
        for value in durations
    ]

    return durations


# ============================================================
# CRÉATION D'UNE SCÈNE IMAGE → VIDÉO
# ============================================================

def create_image_scene(
    image_path: Path,
    output_path: Path,
    duration: float,
    width: int,
    height: int,
    scene_index: int = 0,
) -> Path:
    """
    Transforme une image en courte scène vidéo avec
    zoom/pan subtil.

    Le mouvement évite l'effet diaporama complètement statique.
    """

    ensure_ffmpeg()

    duration = max(
        0.5,
        float(duration),
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    fps = 30

    # Mouvement légèrement différent selon la scène.
    mode = scene_index % 4

    if mode == 0:
        zoom_expr = (
            "min(zoom+0.0008,1.12)"
        )

        x_expr = (
            "(iw-iw/zoom)/2"
        )

        y_expr = (
            "(ih-ih/zoom)/2"
        )

    elif mode == 1:
        zoom_expr = (
            "min(zoom+0.00065,1.10)"
        )

        x_expr = (
            "(iw-iw/zoom)*"
            "0.25"
        )

        y_expr = (
            "(ih-ih/zoom)/2"
        )

    elif mode == 2:
        zoom_expr = (
            "min(zoom+0.0007,1.11)"
        )

        x_expr = (
            "(iw-iw/zoom)*"
            "0.75"
        )

        y_expr = (
            "(ih-ih/zoom)/2"
        )

    else:
        zoom_expr = (
            "min(zoom+0.0006,1.09)"
        )

        x_expr = (
            "(iw-iw/zoom)/2"
        )

        y_expr = (
            "(ih-ih/zoom)*"
            "0.35"
        )

    frames = max(
        1,
        int(
            math.ceil(
                duration * fps
            )
        ),
    )

    filter_complex = (
        f"scale={width*2}:{height*2}:"
        "force_original_aspect_ratio=increase,"
        f"crop={width*2}:{height*2},"
        "zoompan="
        f"z='{zoom_expr}':"
        f"x='{x_expr}':"
        f"y='{y_expr}':"
        f"d={frames}:"
        f"s={width}x{height}:"
        f"fps={fps},"
        "format=yuv420p"
    )

    result = run_command(
        [
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
            str(fps),
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            str(output_path),
        ],
        timeout=180,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Impossible de créer une scène vidéo : "
            + result.stderr[-1000:]
        )

    if not output_path.exists():
        raise RuntimeError(
            "FFmpeg n'a pas créé la scène vidéo."
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
    Assemble les scènes vidéo.
    """

    ensure_ffmpeg()

    if not scene_paths:
        raise RuntimeError(
            "Aucune scène à assembler."
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

    for scene in scene_paths:

        absolute_path = (
            scene.resolve()
            .as_posix()
        )

        # Échappement simple pour le format concat FFmpeg.
        absolute_path = (
            absolute_path
            .replace("'", r"'\''")
        )

        lines.append(
            f"file '{absolute_path}'"
        )

    concat_file.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    result = run_command(
        [
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
        ],
        timeout=300,
    )

    if result.returncode != 0:
        # Certains fichiers peuvent nécessiter
        # une ré-encodage.
        result = run_command(
            [
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
                "20",
                "-pix_fmt",
                "yuv420p",
                str(output_path),
            ],
            timeout=300,
        )

    if result.returncode != 0:
        raise RuntimeError(
            "Impossible d'assembler les scènes : "
            + result.stderr[-1200:]
        )

    return output_path


# ============================================================
# AJOUT DE LA NARRATION
# ============================================================

def attach_audio(
    video_path: Path,
    audio_path: Path,
    output_path: Path,
) -> Path:
    """
    Ajoute la narration au montage vidéo.
    """

    ensure_ffmpeg()

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    result = run_command(
        [
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
            str(output_path),
        ],
        timeout=300,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Impossible d'ajouter l'audio : "
            + result.stderr[-1200:]
        )

    return output_path


# ============================================================
# SOUS-TITRES DANS LA VIDÉO
# ============================================================

def burn_subtitles(
    video_path: Path,
    ass_path: Path,
    output_path: Path,
) -> Path:
    """
    Incruste les sous-titres ASS dans la vidéo.
    """

    ensure_ffmpeg()

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # Le chemin peut contenir des caractères spéciaux.
    ass_filter_path = (
        str(ass_path)
        .replace("\\", "/")
        .replace(":", r"\:")
        .replace("'", r"\'")
    )

    subtitle_filter = (
        f"ass='{ass_filter_path}'"
    )

    result = run_command(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vf",
            subtitle_filter,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "19",
            "-c:a",
            "copy",
            str(output_path),
        ],
        timeout=400,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Impossible d'incruster les sous-titres : "
            + result.stderr[-1500:]
        )

    return output_path# ============================================================
# CONSTRUCTION COMPLÈTE D'UNE VIDÉO
# ============================================================

def build_video(
    script: str,
    output_dir: Path,
    filename: str,
    vertical: bool = True,
) -> Path:
    """
    Construit une vidéo complète :

    1. narration
    2. visuels
    3. scènes animées
    4. assemblage
    5. ajout audio
    6. sous-titres mot par mot
    """

    ensure_ffmpeg()

    script = clean_ai_text(script)

    if not script:
        raise RuntimeError(
            "Impossible de construire la vidéo : script vide."
        )

    # --------------------------------------------------------
    # FORMAT
    # --------------------------------------------------------

    if vertical:
        width = 1080
        height = 1920
    else:
        width = 1920
        height = 1080

    video_dir = output_dir / "video"
    audio_dir = output_dir / "audio"
    subtitle_dir = output_dir / "subtitles"

    video_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    audio_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    subtitle_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # AUDIO
    # --------------------------------------------------------

    st.write("🎙️ Génération de la narration...")

    audio_path = audio_dir / (
        Path(filename).stem + ".mp3"
    )

    voice = select_french_voice()

    synthesize_with_voice(
        text=script,
        output_path=audio_path,
        voice=voice,
        rate="+2%",
    )

    audio_duration = get_audio_duration(
        audio_path
    )

    st.write(
        f"⏱️ Durée de narration : "
        f"{audio_duration:.1f} secondes"
    )

    # --------------------------------------------------------
    # VISUELS
    # --------------------------------------------------------

    st.write("🖼️ Recherche des visuels...")

    visual_count = estimate_visual_count(
        audio_duration
    )

    visuals = get_visuals(
        script=script,
        output_dir=output_dir,
        target_count=visual_count,
    )

    st.write(
        f"🖼️ {len(visuals)} visuels disponibles"
    )

    # --------------------------------------------------------
    # DURÉES DES SCÈNES
    # --------------------------------------------------------

    scene_durations = distribute_scene_durations(
        total_duration=audio_duration,
        visual_count=len(visuals),
    )

    # --------------------------------------------------------
    # CRÉATION DES SCÈNES
    # --------------------------------------------------------

    scene_dir = video_dir / "scenes"

    scene_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    scene_paths = []

    progress = st.progress(
        0,
        text="🎬 Création des scènes...",
    )

    for index, (
        image_path,
        scene_duration,
    ) in enumerate(
        zip(
            visuals,
            scene_durations,
        )
    ):

        scene_path = (
            scene_dir
            / f"scene_{index:03d}.mp4"
        )

        create_image_scene(
            image_path=image_path,
            output_path=scene_path,
            duration=scene_duration,
            width=width,
            height=height,
            scene_index=index,
        )

        scene_paths.append(
            scene_path
        )

        progress.progress(
            int(
                ((index + 1) / len(visuals))
                * 100
            ),
            text=(
                f"🎬 Scène {index + 1}/"
                f"{len(visuals)}"
            ),
        )

    progress.empty()

    # --------------------------------------------------------
    # ASSEMBLAGE
    # --------------------------------------------------------

    st.write("🔗 Assemblage des scènes...")

    silent_video = (
        video_dir
        / f"{Path(filename).stem}_silent.mp4"
    )

    concat_scenes(
        scene_paths=scene_paths,
        output_path=silent_video,
    )

    # --------------------------------------------------------
    # AUDIO
    # --------------------------------------------------------

    st.write("🎙️ Ajout de la narration...")

    narrated_video = (
        video_dir
        / f"{Path(filename).stem}_narrated.mp4"
    )

    attach_audio(
        video_path=silent_video,
        audio_path=audio_path,
        output_path=narrated_video,
    )

    # --------------------------------------------------------
    # TIMING MOT PAR MOT
    # --------------------------------------------------------

    st.write(
        "📝 Calcul des sous-titres mot par mot..."
    )

    boundaries = get_word_boundaries(
        text=script,
        audio_path=audio_path,
        voice=voice,
    )

    if not boundaries:
        raise RuntimeError(
            "Impossible de générer les timings des sous-titres."
        )

    ass_path = (
        subtitle_dir
        / f"{Path(filename).stem}.ass"
    )

    create_ass_subtitles(
        boundaries=boundaries,
        output_path=ass_path,
        width=width,
        height=height,
    )

    # --------------------------------------------------------
    # INCRUSTATION DES SOUS-TITRES
    # --------------------------------------------------------

    st.write(
        "✨ Incrustation des sous-titres..."
    )

    final_path = (
        output_dir
        / filename
    )

    burn_subtitles(
        video_path=narrated_video,
        ass_path=ass_path,
        output_path=final_path,
    )

    if not final_path.exists():
        raise RuntimeError(
            "La vidéo finale n'a pas été créée."
        )

    return final_path


# ============================================================
# RÉPERTOIRE DE PRODUCTION
# ============================================================

def create_production_directory(
    topic: str,
) -> Path:
    """
    Crée un dossier unique pour une production.
    """

    safe_topic = re.sub(
        r"[^a-zA-Z0-9À-ÿ_-]+",
        "_",
        topic,
    )

    safe_topic = safe_topic.strip(
        "_"
    )

    if not safe_topic:
        safe_topic = "video"

    timestamp = time.strftime(
        "%Y%m%d_%H%M%S"
    )

    production_dir = (
        OUTPUT_DIR
        / f"{safe_topic}_{timestamp}"
    )

    production_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    return production_dir


# ============================================================
# TRAITEMENT D'UN SHORT
# ============================================================

def process_short(
    script: str,
    production_dir: Path,
    filename: str,
    label: str = "Short",
) -> Path:
    """
    Produit un Short vertical.
    """

    st.subheader(
        f"📱 {label}"
    )

    script = clean_ai_text(
        script
    )

    if not script:
        raise RuntimeError(
            f"{label} : script vide."
        )

    word_count = count_words(
        remove_visual_markers(script)
    )

    st.write(
        f"📝 {word_count} mots"
    )

    return build_video(
        script=script,
        output_dir=production_dir,
        filename=filename,
        vertical=True,
    )


# ============================================================
# TRAITEMENT VIDÉO LONGUE
# ============================================================

def process_long_video(
    script: str,
    production_dir: Path,
) -> Path:
    """
    Produit une vidéo longue en 16:9.
    """

    st.subheader(
        "🎬 Vidéo YouTube longue"
    )

    script = clean_ai_text(
        script
    )

    word_count = count_words(
        remove_visual_markers(script)
    )

    st.write(
        f"📝 {word_count} mots"
    )

    return build_video(
        script=script,
        output_dir=production_dir,
        filename="video_longue.mp4",
        vertical=False,
    )


# ============================================================
# TRAITEMENT TEASER
# ============================================================

def process_teaser(
    script: str,
    topic: str,
    production_dir: Path,
) -> Optional[Path]:
    """
    Produit un teaser vertical.
    """

    st.subheader(
        "🎯 Teaser"
    )

    try:
        teaser = generate_teaser(
            script=script,
            topic=topic,
        )

        if not teaser:
            return None

        return build_video(
            script=teaser,
            output_dir=production_dir,
            filename="teaser.mp4",
            vertical=True,
        )

    except Exception as exc:
        st.warning(
            f"Teaser non généré : {exc}"
        )

        return None


# ============================================================
# COPIE DE LA VIDÉO FINALE
# ============================================================

def copy_final_output(
    source: Path,
    filename: str,
) -> Path:
    """
    Copie une vidéo dans outputs/ pour la rendre
    facilement accessible depuis l'application.
    """

    destination = (
        OUTPUT_DIR
        / filename
    )

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    shutil.copy2(
        source,
        destination,
    )

    return destination


# ============================================================
# WORKFLOW PRINCIPAL
# ============================================================

def run_generation(
    topic: str,
) -> Dict[str, List[Path]]:
    """
    Workflow complet :

    1. génération du script
    2. sélection automatique du format
    3. adaptation
    4. génération vidéo
    """

    topic = normalize_text(
        topic
    )

    if not topic:
        raise ValueError(
            "Veuillez saisir un sujet."
        )

    production_dir = (
        create_production_directory(
            topic
        )
    )

    st.info(
        "🧠 Génération du script..."
    )

    script = generate_main_script(
        topic
    )

    script = clean_ai_text(
        script
    )

    clean_script = remove_visual_markers(
        script
    )

    word_count = count_words(
        clean_script
    )

    visual_marker_count = len(
        extract_visual_markers(
            script
        )
    )

    st.success(
        f"Script généré : {word_count} mots"
    )

    st.write(
        f"Marqueurs visuels : "
        f"{visual_marker_count}"
    )

    mode = choose_content_mode(
        word_count
    )

    # ========================================================
    # SCRIPT TROP COURT
    # ========================================================

    if mode == "regenerate":

        st.info(
            "🧠 Le script initial est très court. "
            "Création d'une version mieux adaptée..."
        )

        regenerated = regenerate_short_main_script(
            topic
        )

        regenerated = clean_ai_text(
            regenerated
        )

        # Si la nouvelle version est exploitable,
        # on l'utilise.
        if count_words(
            remove_visual_markers(
                regenerated
            )
        ) > 0:
            script = regenerated

        word_count = count_words(
            remove_visual_markers(
                script
            )
        )

        mode = "one_short"

        st.write(
            f"Nouvelle version : "
            f"{word_count} mots"
        )

    results = {
        "shorts": [],
        "long": [],
        "teaser": [],
    }

    # ========================================================
    # UN SHORT
    # ========================================================

    if mode == "one_short":

        st.info(
            "📱 Format sélectionné : "
            "1 Short."
        )

        short_script = generate_one_short(
            script=script,
            topic=topic,
        )

        short_path = process_short(
            script=short_script,
            production_dir=production_dir,
            filename="short_1.mp4",
            label="Short",
        )

        results["shorts"].append(
            short_path
        )

        return results

    # ========================================================
    # DEUX SHORTS
    # ========================================================

    if mode == "two_shorts":

        st.info(
            "✂️ Restructuration en deux Shorts cohérents..."
        )

        part1, part2 = generate_two_shorts(
            script=script,
            topic=topic,
        )

        part1 = fit_short_script(
            part1,
            part_label="Partie 1",
        )

        part2 = fit_short_script(
            part2,
            part_label="Partie 2",
        )

        # Si une partie est vide, on ne plante pas.
        # On utilise le script original ou l'autre partie.
        if not part1:
            part1 = script

        if not part2:
            part2 = part1

        st.success(
            "Structure des deux Shorts terminée."
        )

        st.write(
            f"Partie 1 : "
            f"{count_words(remove_visual_markers(part1))} mots"
        )

        st.write(
            f"Partie 2 : "
            f"{count_words(remove_visual_markers(part2))} mots"
        )

        short1 = process_short(
            script=part1,
            production_dir=production_dir,
            filename="short_1.mp4",
            label="Short 1",
        )

        results["shorts"].append(
            short1
        )

        short2 = process_short(
            script=part2,
            production_dir=production_dir,
            filename="short_2.mp4",
            label="Short 2",
        )

        results["shorts"].append(
            short2
        )

        return results

    # ========================================================
    # VIDÉO LONGUE
    # ========================================================

    if mode == "long":

        st.info(
            "🎬 Format sélectionné : "
            "vidéo longue 16:9."
        )

        long_video = process_long_video(
            script=script,
            production_dir=production_dir,
        )

        results["long"].append(
            long_video
        )

        # Un teaser est créé à partir de la vidéo longue.
        teaser = process_teaser(
            script=script,
            topic=topic,
            production_dir=production_dir,
        )

        if teaser:
            results["teaser"].append(
                teaser
            )

        return results

    # ========================================================
    # SÉCURITÉ
    # ========================================================

    st.warning(
        "Format inattendu. Adaptation automatique vers un Short."
    )

    short_script = generate_one_short(
        script=script,
        topic=topic,
    )

    short_path = process_short(
        script=short_script,
        production_dir=production_dir,
        filename="short_1.mp4",
        label="Short",
    )

    results["shorts"].append(
        short_path
    )

    return results


# ============================================================
# INTERFACE STREAMLIT
# ============================================================

def show_video_result(
    path: Path,
    title: str,
) -> None:
    """
    Affiche une vidéo produite.
    """

    if not path.exists():
        return

    st.subheader(
        title
    )

    try:
        with open(
            path,
            "rb",
        ) as video_file:

            video_bytes = (
                video_file.read()
            )

        st.video(
            video_bytes
        )

    except Exception as exc:
        st.warning(
            f"Impossible d'afficher {title} : {exc}"
        )


def main() -> None:
    """
    Point d'entrée Streamlit.
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
        "Création automatisée de vidéos "
        "sur la psychologie, le cerveau et "
        "le comportement humain."
    )

    st.divider()

    # --------------------------------------------------------
    # SIDEBAR
    # --------------------------------------------------------

    with st.sidebar:

        st.header(
            "⚙️ Configuration"
        )

        if OPENROUTER_API_KEY:
            st.success(
                "OpenRouter : connecté"
            )
        else:
            st.error(
                "OpenRouter : clé absente"
            )

        if PEXELS_API_KEY:
            st.success(
                "Pexels : connecté"
            )
        else:
            st.warning(
                "Pexels : clé absente"
            )

        st.caption(
            "Sans clé Pexels, des visuels de secours "
            "seront utilisés."
        )

        st.divider()

        st.write(
            "Formats automatiques :"
        )

        st.write(
            "• 1 Short pour un script moyen"
        )

        st.write(
            "• 2 Shorts pour un script plus long"
        )

        st.write(
            "• Vidéo 16:9 pour un script long"
        )

        st.write(
            "• Adaptation automatique si le script "
            "ne correspond pas parfaitement"
        )

    # --------------------------------------------------------
    # SAISIE
    # --------------------------------------------------------

    st.header(
        "🧠 Nouveau sujet"
    )

    topic = st.text_input(
        "Sujet de la vidéo",
        placeholder=(
            "Exemple : Pourquoi ton cerveau procrastine"
        ),
    )

    st.caption(
        "Conseil : choisissez un phénomène précis "
        "de psychologie, de neurosciences ou de "
        "comportement humain."
    )

    generate_button = st.button(
        "🚀 Générer la vidéo",
        type="primary",
        use_container_width=True,
    )

    # --------------------------------------------------------
    # GÉNÉRATION
    # --------------------------------------------------------

    if generate_button:

        if not topic.strip():

            st.error(
                "Veuillez saisir un sujet."
            )

            return

        # Évite de garder des résultats anciens
        # dans une même session.
        st.session_state.pop(
            "generation_results",
            None,
        )

        try:

            with st.status(
                "🎬 Production en cours...",
                expanded=True,
            ):

                results = run_generation(
                    topic=topic
                )

                st.session_state[
                    "generation_results"
                ] = results

                st.success(
                    "✅ Production terminée."
                )

        except Exception as exc:

            st.error(
                "❌ La génération a échoué."
            )

            st.exception(
                exc
            )

            return

    # --------------------------------------------------------
    # RÉSULTATS
    # --------------------------------------------------------

    results = st.session_state.get(
        "generation_results"
    )

    if not results:
        return

    st.divider()

    st.header(
        "🎉 Résultats"
    )

    shorts = results.get(
        "shorts",
        [],
    )

    long_videos = results.get(
        "long",
        [],
    )

    teasers = results.get(
        "teaser",
        [],
    )

    for index, path in enumerate(
        shorts,
        start=1,
    ):

        show_video_result(
            path,
            f"📱 Short {index}",
        )

    for path in long_videos:

        show_video_result(
            path,
            "🎬 Vidéo longue",
        )

    for path in teasers:

        show_video_result(
            path,
            "🎯 Teaser",
        )

    # --------------------------------------------------------
    # INFORMATIONS
    # --------------------------------------------------------

    st.divider()

    st.info(
        "Les vidéos sont enregistrées dans le dossier "
        "`outputs` du serveur."
    )


# ============================================================
# LANCEMENT
# ============================================================

if __name__ == "__main__":
    main()
