import os
import re
import json
import time
import math
import shutil
import random
import asyncio
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

OPENROUTER_MODEL = "meta-llama/llama-3.3-70b-instruct"

OPENROUTER_FALLBACK_MODELS = [
    "meta-llama/llama-3.3-70b-instruct",
    "google/gemini-2.0-flash-001",
]

PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"


# ============================================================
# IDENTITÉ DE LA CHAÎNE
# ============================================================

CHANNEL_NAME = "Cerveau Curieux"

CHANNEL_DESCRIPTION = (
    "Psychologie, neurosciences et comportement humain "
    "racontés de manière surprenante, amusante et accessible."
)

# Couleur de la mascotte et du mot actif dans les sous-titres.
# Ces valeurs sont utilisées par PIL et ASS.
MASCOT_BLUE = (83, 113, 255)
MASCOT_PURPLE = (139, 92, 246)
MASCOT_WHITE = (255, 255, 255)
MASCOT_BLACK = (20, 20, 30)

SUBTITLE_ACTIVE_RGB = (255, 215, 0)


# ============================================================
# SEUILS DE LONGUEUR
# ============================================================

REGENERATE_BELOW = 70

ONE_SHORT_MIN = 70
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
# PARAMÈTRES VISUELS
# ============================================================

SHORT_VISUAL_MIN = 6
SHORT_VISUAL_MAX = 12

LONG_VISUAL_MIN = 10
LONG_VISUAL_MAX = 24

# Une phrase visuelle ne doit pas rester trop longtemps
# sans raison.
VISUAL_TARGET_SECONDS = 3.8

# Taille de la mascotte dans les Shorts.
MASCOT_WIDTH = 220

# Marge basse de sécurité.
MASCOT_BOTTOM_MARGIN = 175


# ============================================================
# RÉPERTOIRES
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

OUTPUT_DIR = BASE_DIR / "outputs"
TEMP_DIR = BASE_DIR / "temp"

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

TEMP_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


# ============================================================
# SECRETS
# ============================================================

def get_secret(
    name: str,
    default: str = "",
) -> str:

    try:

        value = st.secrets.get(
            name
        )

        if value:
            return str(value)

    except Exception:
        pass

    return os.getenv(
        name,
        default,
    )


OPENROUTER_API_KEY = get_secret(
    "OPENROUTER_API_KEY"
)

PEXELS_API_KEY = get_secret(
    "PEXELS_API_KEY"
)


# ============================================================
# OUTILS TEXTE
# ============================================================

def normalize_text(
    text: str,
) -> str:

    if not text:
        return ""

    text = str(text)

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

    text = normalize_text(
        text
    )

    if not text:
        return 0

    return len(
        re.findall(
            r"\b[\wÀ-ÿ'-]+\b",
            text,
        )
    )


def clean_ai_text(
    text: str,
) -> str:

    if not text:
        return ""

    text = str(
        text
    ).strip()

    text = re.sub(
        r"^```(?:text|markdown|json)?\s*",
        "",
        text,
        flags=re.I,
    )

    text = re.sub(
        r"\s*```$",
        "",
        text,
    )

    return normalize_text(
        text
    )


def extract_json_object(
    text: str,
) -> Optional[dict]:

    if not text:
        return None

    text = text.strip()

    try:

        return json.loads(
            text
        )

    except Exception:
        pass

    match = re.search(
        r"\{.*\}",
        text,
        flags=re.S,
    )

    if match:

        try:

            return json.loads(
                match.group(0)
            )

        except Exception:
            return None

    return None


# ============================================================
# COMMANDES SYSTÈME
# ============================================================

def run_command(
    command: List[str],
    timeout: int = 300,
    cwd: Optional[str] = None,
) -> subprocess.CompletedProcess:

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

    if not shutil.which(
        "ffmpeg"
    ):

        raise RuntimeError(
            "FFmpeg est introuvable. "
            "Ajoutez `ffmpeg` dans packages.txt "
            "à la racine du dépôt Streamlit."
        )

    if not shutil.which(
        "ffprobe"
    ):

        raise RuntimeError(
            "FFprobe est introuvable. "
            "Vérifiez l'installation de FFmpeg "
            "dans packages.txt."
        )


# ============================================================
# OPENROUTER
# ============================================================

def _extract_openrouter_error(
    response: requests.Response,
) -> str:

    try:

        data = response.json()

        if isinstance(
            data,
            dict,
        ):

            error = data.get(
                "error"
            )

            if isinstance(
                error,
                dict,
            ):

                message = error.get(
                    "message"
                )

                if message:
                    return str(
                        message
                    )

            message = data.get(
                "message"
            )

            if message:
                return str(
                    message
                )

    except Exception:
        pass

    text = response.text.strip()

    if text:
        return text[:500]

    return "Erreur inconnue."


def _get_retry_after(
    response: requests.Response,
) -> Optional[float]:

    value = response.headers.get(
        "Retry-After"
    )

    if not value:
        return None

    try:

        return float(
            value
        )

    except (
        ValueError,
        TypeError,
    ):
        return None


def openrouter_request(
    messages: List[Dict[str, str]],
    temperature: float = 0.7,
    max_tokens: int = 1800,
    timeout: int = 75,
    max_retries: int = 1,
) -> str:

    if not OPENROUTER_API_KEY:

        raise RuntimeError(
            "OPENROUTER_API_KEY est introuvable. "
            "Ajoutez-la dans les secrets Streamlit."
        )

    headers = {
        "Authorization": (
            f"Bearer {OPENROUTER_API_KEY}"
        ),
        "Content-Type": "application/json",
        "X-Title": APP_TITLE,
    }

    # HTTP-Referer est facultatif.
    # On évite ici de conserver l'ancienne URL Render.
    streamlit_url = get_secret(
        "APP_URL"
    )

    if streamlit_url:
        headers["HTTP-Referer"] = streamlit_url

    models = list(
        dict.fromkeys(
            OPENROUTER_FALLBACK_MODELS
        )
    )

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

    total_attempts = max(
        1,
        int(max_retries) + 1,
    )

    for attempt in range(
        total_attempts
    ):

        if attempt > 0:

            wait_time = min(
                2 + attempt * 2,
                8,
            )

            st.info(
                "Nouvelle tentative OpenRouter "
                f"dans {wait_time} seconde(s)..."
            )

            time.sleep(
                wait_time
            )

        try:

            response = requests.post(
                OPENROUTER_URL,
                headers=headers,
                json=payload,
                timeout=timeout,
            )

        except requests.Timeout as exc:

            last_error = (
                f"OpenRouter n'a pas répondu "
                f"dans le délai de {timeout} secondes."
            )

            if (
                attempt + 1
                >= total_attempts
            ):

                raise RuntimeError(
                    last_error
                ) from exc

            st.warning(
                "OpenRouter met trop de temps "
                "à répondre. Nouvelle tentative."
            )

            continue

        except requests.RequestException as exc:

            last_error = (
                f"Erreur réseau OpenRouter : {exc}"
            )

            if (
                attempt + 1
                >= total_attempts
            ):

                raise RuntimeError(
                    last_error
                ) from exc

            st.warning(
                "La connexion à OpenRouter a été "
                "interrompue. Nouvelle tentative."
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
                    "OpenRouter a renvoyé "
                    "un JSON invalide."
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
                    "Réponse OpenRouter invalide : "
                    "contenu introuvable."
                ) from exc

            content = clean_ai_text(
                content
            )

            if not content:

                raise RuntimeError(
                    "OpenRouter a répondu sans "
                    "contenu exploitable."
                )

            used_model = data.get(
                "model"
            )

            if used_model:

                st.caption(
                    f"Modèle IA utilisé : {used_model}"
                )

            return content

        # ----------------------------------------------------
        # 429
        # ----------------------------------------------------

        if response.status_code == 429:

            error_message = (
                _extract_openrouter_error(
                    response
                )
            )

            retry_after = (
                _get_retry_after(
                    response
                )
            )

            if retry_after is not None:

                wait_time = min(
                    max(
                        retry_after,
                        1,
                    ),
                    10,
                )

            else:

                wait_time = min(
                    2 + attempt * 2,
                    8,
                )

            last_error = (
                "OpenRouter a retourné HTTP 429 "
                "(Too Many Requests). "
                f"{error_message}"
            )

            if (
                attempt + 1
                < total_attempts
            ):

                st.warning(
                    "OpenRouter limite temporairement "
                    "la requête (429). "
                    f"Nouvelle tentative dans "
                    f"{wait_time:.0f} seconde(s)."
                )

                time.sleep(
                    wait_time
                )

                continue

            raise RuntimeError(
                last_error
                + " La génération est arrêtée "
                  "plutôt que de rester bloquée."
            )

        # ----------------------------------------------------
        # AUTRES ERREURS HTTP
        # ----------------------------------------------------

        error_message = (
            _extract_openrouter_error(
                response
            )
        )

        last_error = (
            f"Erreur OpenRouter HTTP "
            f"{response.status_code} : "
            f"{error_message}"
        )

        if (
            400
            <= response.status_code
            < 500
        ):

            raise RuntimeError(
                last_error
            )

        if (
            attempt + 1
            < total_attempts
        ):

            st.warning(
                f"OpenRouter a rencontré une "
                f"erreur serveur "
                f"({response.status_code}). "
                "Nouvelle tentative."
            )

            continue

        raise RuntimeError(
            last_error
        )

    raise RuntimeError(
        last_error
        or "Erreur inconnue OpenRouter."
    )


# ============================================================
# GÉNÉRATION DU SCRIPT PRINCIPAL
# ============================================================

def generate_main_script(
    topic: str,
) -> str:

    topic = normalize_text(
        topic
    )

    if not topic:

        raise ValueError(
            "Le sujet est vide."
        )

    prompt = f"""
Vous êtes le scénariste principal de la chaîne YouTube
« {CHANNEL_NAME} ».

La chaîne parle de psychologie, neurosciences et comportement
humain, mais son identité n'est PAS celle d'une chaîne scolaire.

SUJET :
{topic}

MISSION :

Créer une histoire courte, surprenante et divertissante autour
du sujet.

Le spectateur doit avoir l'impression qu'un ami très curieux
lui révèle quelque chose d'étonnant sur le cerveau ou le
comportement humain.

STYLE :

- amusant
- surprenant
- naturel
- intelligent
- accessible
- dynamique
- parfois légèrement drôle
- proche des situations de la vie quotidienne
- jamais scolaire
- jamais artificiellement sensationnaliste

L'objectif principal est la RÉTENTION.

Le début doit donner immédiatement envie de connaître la réponse.

Évitez les introductions du type :
« Bonjour et bienvenue ».

PRINCIPES NARRATIFS :

1. Commencez par une accroche forte.

2. Créez une question, un paradoxe ou une situation
   dans laquelle le spectateur peut se reconnaître.

3. Expliquez progressivement pourquoi le phénomène arrive.

4. Gardez une petite révélation ou un élément surprenant
   pour la fin lorsque le sujet le permet.

5. Utilisez des exemples du quotidien.

6. Vous pouvez utiliser une petite touche d'humour,
   mais elle doit rester naturelle et ne jamais déformer
   l'information scientifique.

7. Utilisez des phrases relativement courtes adaptées
   à une narration vocale.

8. Ne faites pas de cours magistral.

9. Ne répétez pas inutilement la même idée.

10. Terminez par une idée mémorable.

RÈGLES SCIENTIFIQUES ABSOLUES :

- Ne jamais inventer une étude.
- Ne jamais inventer une expérience.
- Ne jamais inventer une statistique.
- Ne jamais inventer un chercheur.
- Ne jamais inventer une citation.
- Ne jamais présenter comme certain quelque chose
  qui est scientifiquement incertain.
- Si une affirmation dépend du contexte,
  utilisez une formulation prudente.
- Ne faites pas de pseudo-science.
- Ne promettez jamais un effet psychologique garanti.

VISUELS :

Insérez régulièrement des marqueurs :

[IMAGE: description précise]

ou :

[VISUAL: description précise]

Chaque marqueur doit décrire ce qu'une image ou une scène
peut réellement montrer.

Les descriptions doivent être concrètes.

Exemple de mauvaise description :
[IMAGE: la psychologie]

Exemple de bonne description :
[IMAGE: jeune personne assise dans un bus regardant son téléphone
avec une expression hésitante]

Les visuels doivent suivre la narration.

Pour environ 40 à 60 secondes, visez environ 8 à 12
marqueurs visuels lorsque le sujet s'y prête.

Les scènes doivent être variées :
personnes, objets, environnement, gestes, situations quotidiennes,
cerveau ou illustrations scientifiques simples lorsque pertinent.

Ne demandez jamais des images choquantes simplement pour attirer
l'attention.

Interdictions visuelles :

- gore
- sang
- nudité
- sexualisation
- pornographie
- drogues
- alcool
- tabac
- violence gratuite
- armes
- automutilation
- suicide
- contenu choquant destiné uniquement au clic

IMPORTANT :

Peu importe la taille du script.

Un script court ne doit jamais être considéré comme un échec.

Le système décidera ensuite s'il doit être utilisé directement,
adapté en Short ou développé autrement.

Retournez uniquement le script.
"""

    messages = [
        {
            "role": "system",
            "content": (
                "Vous êtes un scénariste spécialisé "
                "en psychologie et neurosciences accessibles. "
                "Votre priorité est la précision scientifique "
                "et la rétention du spectateur. "
                "Vous n'inventez jamais de faits."
            ),
        },
        {
            "role": "user",
            "content": prompt,
        },
    ]

    return openrouter_request(
        messages=messages,
        temperature=0.72,
        max_tokens=2200,
        timeout=75,
        max_retries=1,
    )


# ============================================================
# CHOIX DU FORMAT
# ============================================================

def choose_content_mode(
    word_count: int,
) -> str:

    # Un script même très court reste exploitable.
    if word_count < REGENERATE_BELOW:
        return "one_short"

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
# RÉGÉNÉRATION D'UN SCRIPT COURT
# ============================================================

def regenerate_short_main_script(
    topic: str,
) -> str:

    prompt = f"""
Créez un Short YouTube pour la chaîne « {CHANNEL_NAME} ».

SUJET :
{topic}

Le Short doit parler de psychologie, neurosciences ou
comportement humain.

IDENTITÉ :

Le contenu doit être amusant, surprenant et très accessible.
Il ne doit surtout pas donner l'impression de regarder un cours.

OBJECTIF :

Faire penser au spectateur :
« Attends, c'est vraiment comme ça que mon cerveau fonctionne ? »

CONTRAINTES :

- accroche forte dès la première phrase
- aucune introduction inutile
- narration naturelle
- explication scientifique accessible
- aucune invention
- aucune fausse statistique
- aucune étude inventée
- aucun chercheur inventé
- environ 90 à 130 mots si possible
- conclusion mémorable
- ton humain et dynamique
- petites touches d'humour possibles
- exemples du quotidien lorsque pertinents
- pas de pseudo-science

VISUELS :

Ajoutez 5 à 8 marqueurs :

[IMAGE: description précise]

ou :

[VISUAL: description précise]

Chaque marqueur doit être directement lié à la narration.

Les visuels doivent pouvoir être recherchés facilement sur
une banque d'images.

Évitez les descriptions abstraites.

Aucun contenu gore, sexuel, violent, lié aux drogues,
à l'alcool, aux armes ou à l'automutilation.

Retournez uniquement le script.
"""

    messages = [
        {
            "role": "system",
            "content": (
                "Vous écrivez des Shorts scientifiques "
                "divertissants, précis et accessibles. "
                "Vous n'inventez aucune information."
            ),
        },
        {
            "role": "user",
            "content": prompt,
        },
    ]

    return openrouter_request(
        messages=messages,
        temperature=0.72,
        max_tokens=700,
        timeout=60,
        max_retries=1,
    )


# ============================================================
# GÉNÉRATION D'UN SHORT
# ============================================================

def generate_one_short(
    script: str,
    topic: str = "",
) -> str:

    script = clean_ai_text(
        script
    )

    word_count = count_words(
        remove_visual_markers(
            script
        )
    )

    if word_count == 0:

        raise RuntimeError(
            "Impossible de créer un Short "
            "à partir d'un script vide."
        )

    # Un texte court reste utilisable.
    if word_count < SHORT_MIN_WORDS:

        if topic:

            try:

                regenerated = (
                    regenerate_short_main_script(
                        topic
                    )
                )

                regenerated = clean_ai_text(
                    regenerated
                )

                if count_words(
                    remove_visual_markers(
                        regenerated
                    )
                ) > 0:

                    return regenerated

            except Exception as exc:

                st.warning(
                    "La régénération du Short "
                    f"n'a pas fonctionné : {exc}"
                )

        return script

    if (
        SHORT_MIN_WORDS
        <= word_count
        <= SHORT_MAX_WORDS
    ):

        return script

    return fit_short_script(
        script,
        part_label="Short",
        target_min=SHORT_MIN_WORDS,
        target_max=SHORT_MAX_WORDS,
    )


# ============================================================
# GÉNÉRATION DE DEUX SHORTS
# ============================================================

def generate_two_shorts(
    script: str,
    topic: str,
) -> Tuple[str, str]:

    script = clean_ai_text(
        script
    )

    if count_words(script) < 2:
        return script, ""

    prompt = f"""
Transformez le script suivant en DEUX Shorts YouTube
autonomes pour « {CHANNEL_NAME} ».

SUJET :
{topic}

SCRIPT ORIGINAL :
{script}

IDENTITÉ DE LA CHAÎNE :

Psychologie, neurosciences et comportement humain présentés
de façon amusante, surprenante et accessible.

Les Shorts ne doivent pas ressembler à deux morceaux
d'un cours scolaire.

PARTIE 1 :

- hook très fort
- situation ou question intrigante
- découverte du phénomène
- première explication
- fin qui donne envie de connaître la suite

PARTIE 2 :

- accroche permettant de reprendre naturellement
- suite de l'explication
- élément surprenant
- conclusion satisfaisante
- idée mémorable

RÈGLES :

- ne rien inventer
- aucune étude inventée
- aucune statistique inventée
- aucun chercheur inventé
- ne pas exagérer les résultats scientifiques
- conserver les informations essentielles
- narration naturelle
- phrases courtes
- ton amusant et humain
- exemples du quotidien lorsque pertinents
- aucune introduction inutile

VISUELS :

Chaque partie doit contenir suffisamment de marqueurs :

[IMAGE: description précise]

ou :

[VISUAL: description précise]

Les descriptions doivent suivre précisément la narration.

Les visuels doivent être variés et faciles à rechercher.

Retournez exactement :

[PARTIE 1]
texte

[PARTIE 2]
texte
"""

    messages = [
        {
            "role": "system",
            "content": (
                "Vous êtes un scénariste et monteur éditorial "
                "spécialisé dans les contenus scientifiques "
                "courts et divertissants."
            ),
        },
        {
            "role": "user",
            "content": prompt,
        },
    ]

    result = openrouter_request(
        messages=messages,
        temperature=0.65,
        max_tokens=1800,
        timeout=75,
        max_retries=1,
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

    part1 = (
        clean_ai_text(
            match1.group(1)
        )
        if match1
        else ""
    )

    part2 = (
        clean_ai_text(
            match2.group(1)
        )
        if match2
        else ""
    )

    if not part1 or not part2:

        words = script.split()

        middle = max(
            1,
            len(words) // 2,
        )

        part1 = " ".join(
            words[:middle]
        ).strip()

        part2 = " ".join(
            words[middle:]
        ).strip()

    return part1, part2


# ============================================================
# ADAPTATION INTELLIGENTE D'UN SHORT
# ============================================================

def fit_short_script(
    script: str,
    part_label: str = "Short",
    target_min: int = SHORT_MIN_WORDS,
    target_max: int = SHORT_MAX_WORDS,
) -> str:

    script = clean_ai_text(
        script
    )

    if not script:
        return ""

    word_count = count_words(
        remove_visual_markers(
            script
        )
    )

    if (
        target_min
        <= word_count
        <= target_max
    ):

        return script

    # IMPORTANT :
    # Un script trop court n'est pas une erreur.
    if word_count < target_min:
        return script

    prompt = f"""
Adaptez le texte suivant pour un {part_label} YouTube
de « {CHANNEL_NAME} ».

Objectif :
obtenir un texte court, naturel, captivant et agréable
à écouter.

Idéalement :
{target_min} à {target_max} mots.

TEXTE ORIGINAL :
{script}

STYLE :

- amusant
- surprenant
- naturel
- accessible
- dynamique
- pas scolaire

RÈGLES :

- conserver les informations essentielles
- ne rien inventer
- aucune nouvelle statistique
- aucune nouvelle étude
- aucun nouveau fait
- conserver le sens scientifique
- accroche forte
- phrases courtes
- narration fluide
- conclusion mémorable
- conserver les marqueurs [IMAGE:] ou [VISUAL:]
  lorsqu'ils restent pertinents

Si atteindre exactement la plage demandée
oblige à supprimer une information importante,
privilégiez la qualité du contenu.

Retournez uniquement le texte final.
"""

    messages = [
        {
            "role": "system",
            "content": (
                "Vous êtes un éditeur de scripts "
                "scientifiques courts. "
                "Vous réduisez les textes sans inventer "
                "de nouvelles informations."
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
            timeout=60,
            max_retries=0,
        )

        result = clean_ai_text(
            result
        )

        if result:
            return result

    except Exception:

        st.warning(
            f"{part_label} : adaptation IA "
            "indisponible. Le texte original "
            "sera utilisé."
        )

    return script


# ============================================================
# TEASER
# ============================================================

def generate_teaser(
    script: str,
    topic: str = "",
) -> str:

    script = clean_ai_text(
        script
    )

    if not script:
        return ""

    word_count = count_words(
        remove_visual_markers(
            script
        )
    )

    if (
        SHORT_MIN_WORDS
        <= word_count
        <= SHORT_MAX_WORDS
    ):

        return script

    prompt = f"""
Créez un teaser captivant pour une vidéo YouTube
de la chaîne « {CHANNEL_NAME} ».

SUJET :
{topic}

SCRIPT SOURCE :
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
- avoir un ton amusant et surprenant
- faire environ 60 à 100 mots
- finir sur une phrase donnant envie de regarder la vidéo

Retournez uniquement le texte.
"""

    messages = [
        {
            "role": "system",
            "content": (
                "Vous créez des teasers scientifiques "
                "courts, divertissants et factuellement "
                "prudents."
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
            timeout=60,
            max_retries=0,
        )

    except Exception:

        words = script.split()

        fallback = " ".join(
            words[:90]
        ).strip()

        return fallback


# ============================================================
# MARQUEURS VISUELS
# ============================================================

IMAGE_MARKER_RE = re.compile(
    r"\[(?:IMAGE|VISUAL)\s*:\s*(.*?)\]",
    flags=re.I | re.S,
)


def extract_visual_markers(
    text: str,
) -> List[str]:

    if not text:
        return []

    markers = IMAGE_MARKER_RE.findall(
        text
    )

    cleaned = []

    for marker in markers:

        marker = normalize_text(
            marker
        )

        if marker:
            cleaned.append(
                marker
            )

    return cleaned


def remove_visual_markers(
    text: str,
) -> str:

    if not text:
        return ""

    text = IMAGE_MARKER_RE.sub(
        " ",
        text,
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


# ============================================================
# FIN DE LA PARTIE 1
# ============================================================# ============================================================
# PARTIE 2/4
# VISUELS, RECHERCHE PEXELS ET PLANIFICATION DES SCÈNES
# ============================================================


# ============================================================
# LISTE DE MOTS À IGNORER POUR LES RECHERCHES VISUELLES
# ============================================================

VISUAL_STOPWORDS = {
    "a",
    "à",
    "au",
    "aux",
    "avec",
    "ce",
    "cela",
    "ces",
    "cet",
    "cette",
    "comme",
    "dans",
    "de",
    "des",
    "du",
    "elle",
    "elles",
    "en",
    "est",
    "et",
    "eux",
    "il",
    "ils",
    "je",
    "la",
    "le",
    "les",
    "leur",
    "leurs",
    "lui",
    "mais",
    "me",
    "même",
    "mes",
    "mon",
    "ne",
    "nos",
    "notre",
    "nous",
    "on",
    "ou",
    "par",
    "pas",
    "pour",
    "que",
    "quel",
    "quelle",
    "quelles",
    "quels",
    "qui",
    "se",
    "ses",
    "son",
    "sur",
    "ta",
    "te",
    "tes",
    "toi",
    "ton",
    "tu",
    "un",
    "une",
    "vos",
    "votre",
    "vous",
    "y",
    "dans",
    "donc",
    "car",
    "très",
    "plus",
    "moins",
    "aussi",
    "encore",
    "alors",
    "ainsi",
    "être",
    "avoir",
    "fait",
    "faire",
    "tout",
    "tous",
    "toute",
    "toutes",
}


# ============================================================
# SÉCURITÉ DES REQUÊTES VISUELLES
# ============================================================

UNSAFE_VISUAL_TERMS = {
    "blood",
    "bloody",
    "gore",
    "gory",
    "dead body",
    "corpse",
    "murder",
    "killing",
    "kill",
    "suicide",
    "self harm",
    "self-harm",
    "automutilation",
    "violence",
    "violent",
    "weapon",
    "gun",
    "rifle",
    "knife",
    "drug",
    "drugs",
    "cocaine",
    "heroin",
    "meth",
    "marijuana",
    "weed",
    "alcohol",
    "beer",
    "wine",
    "vodka",
    "smoking",
    "cigarette",
    "vape",
    "porn",
    "pornography",
    "nude",
    "nudity",
    "naked",
    "sexual",
    "sex",
}


def _visual_query_is_safe(
    query: str,
) -> bool:

    if not query:
        return False

    lowered = query.lower()

    for term in UNSAFE_VISUAL_TERMS:

        if term in lowered:
            return False

    return True


# ============================================================
# EXTRACTION DES MOTS-CLÉS
# ============================================================

def _visual_query_keywords(
    text: str,
    max_words: int = 8,
) -> List[str]:

    text = remove_visual_markers(
        text
    )

    text = text.lower()

    words = re.findall(
        r"[a-zàâäçéèêëîïôöùûüÿœæ'-]+",
        text,
        flags=re.I,
    )

    result = []

    for word in words:

        word = word.strip(
            "'-"
        )

        if not word:
            continue

        if len(word) < 4:
            continue

        if word in VISUAL_STOPWORDS:
            continue

        if word not in result:

            result.append(
                word
            )

        if len(result) >= max_words:
            break

    return result


# ============================================================
# CONSTRUCTION D'UNE REQUÊTE PEXELS
# ============================================================

def _make_visual_query(
    text: str,
    index: int = 0,
) -> str:

    keywords = _visual_query_keywords(
        text,
        max_words=7,
    )

    if keywords:

        query = " ".join(
            keywords
        )

    else:

        query = (
            "person thinking everyday life"
        )

    # Les suffixes permettent de varier le type de photo.
    suffixes = [
        "realistic photo",
        "candid lifestyle photo",
        "close up realistic photo",
        "people everyday life photo",
        "natural realistic photo",
        "cinematic lifestyle photo",
        "human behavior photo",
        "brain psychology concept photo",
    ]

    suffix = suffixes[
        index % len(suffixes)
    ]

    query = (
        f"{query} {suffix}"
    )

    if not _visual_query_is_safe(
        query
    ):

        return (
            "person everyday life "
            "realistic photo"
        )

    return query


# ============================================================
# RECHERCHES VISUELLES SUPPLÉMENTAIRES
# ============================================================

def _build_supplemental_visual_queries(
    script: str,
    target_count: int,
) -> List[str]:

    markers = extract_visual_markers(
        script
    )

    narration = remove_visual_markers(
        script
    )

    queries = []

    # --------------------------------------------------------
    # PRIORITÉ 1 : marqueurs générés par l'IA
    # --------------------------------------------------------

    for index, marker in enumerate(
        markers
    ):

        query = _make_visual_query(
            marker,
            index,
        )

        if query not in queries:

            queries.append(
                query
            )

    # --------------------------------------------------------
    # PRIORITÉ 2 : phrases de narration
    # --------------------------------------------------------

    sentences = re.split(
        r"(?<=[.!?])\s+",
        narration,
    )

    for sentence in sentences:

        sentence = normalize_text(
            sentence
        )

        if count_words(sentence) < 3:
            continue

        query = _make_visual_query(
            sentence,
            len(queries),
        )

        if query not in queries:

            queries.append(
                query
            )

        if len(queries) >= target_count * 2:
            break

    # --------------------------------------------------------
    # FALLBACK
    # --------------------------------------------------------

    fallback_queries = [
        "person thinking realistic photo",
        "young person everyday life realistic photo",
        "brain neuroscience concept realistic photo",
        "human behavior realistic lifestyle photo",
        "person surprised realistic photo",
        "person looking at phone realistic photo",
        "friends talking realistic lifestyle photo",
        "person working realistic lifestyle photo",
    ]

    for query in fallback_queries:

        if query not in queries:

            queries.append(
                query
            )

    return queries[
        :max(
            target_count * 2,
            target_count,
        )
    ]


# ============================================================
# PEXELS
# ============================================================

def pexels_search(
    query: str,
    per_page: int = 8,
    orientation: str = "landscape",
) -> List[dict]:

    if not PEXELS_API_KEY:
        return []

    if not query:
        return []

    if not _visual_query_is_safe(
        query
    ):
        return []

    headers = {
        "Authorization": PEXELS_API_KEY,
    }

    params = {
        "query": query,
        "per_page": max(
            1,
            min(
                per_page,
                80,
            ),
        ),
        "orientation": orientation,
    }

    try:

        response = requests.get(
            PEXELS_SEARCH_URL,
            headers=headers,
            params=params,
            timeout=20,
        )

    except requests.RequestException:

        return []

    if response.status_code != 200:
        return []

    try:

        data = response.json()

    except Exception:

        return []

    photos = data.get(
        "photos",
        [],
    )

    if not isinstance(
        photos,
        list,
    ):

        return []

    return photos


# ============================================================
# TÉLÉCHARGEMENT
# ============================================================

def download_file(
    url: str,
    destination: Path,
    timeout: int = 30,
) -> bool:

    if not url:
        return False

    try:

        response = requests.get(
            url,
            timeout=timeout,
            stream=True,
        )

        response.raise_for_status()

        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with open(
            destination,
            "wb",
        ) as file:

            for chunk in response.iter_content(
                chunk_size=1024 * 64
            ):

                if chunk:

                    file.write(
                        chunk
                    )

        return (
            destination.exists()
            and destination.stat().st_size > 0
        )

    except (
        requests.RequestException,
        OSError,
    ):

        return False


# ============================================================
# NORMALISATION DES IMAGES
# ============================================================

def normalize_image(
    source: Path,
    destination: Path,
    width: int = 1920,
    height: int = 1080,
) -> bool:

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

                return False

            source_ratio = (
                source_width
                / source_height
            )

            target_ratio = (
                width
                / height
            )

            # ------------------------------------------------
            # Crop centré en conservant le sujet autant
            # que possible.
            # ------------------------------------------------

            if source_ratio > target_ratio:

                new_width = int(
                    source_height
                    * target_ratio
                )

                left = (
                    source_width
                    - new_width
                ) // 2

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

                top = (
                    source_height
                    - new_height
                ) // 2

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
                    width,
                    height,
                ),
                Image.Resampling.LANCZOS,
            )

            destination.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            image.save(
                destination,
                "JPEG",
                quality=92,
                optimize=True,
            )

        return True

    except (
        OSError,
        ValueError,
    ):

        return False


# ============================================================
# PLACEHOLDER
# ============================================================

def create_placeholder(
    destination: Path,
    width: int,
    height: int,
    text: str = "Cerveau Curieux",
) -> bool:

    try:

        image = Image.new(
            "RGB",
            (
                width,
                height,
            ),
            (
                28,
                25,
                55,
            ),
        )

        draw = ImageDraw.Draw(
            image
        )

        # Cercle central.
        margin = min(
            width,
            height,
        ) // 6

        draw.ellipse(
            (
                margin,
                margin,
                width - margin,
                height - margin,
            ),
            fill=(
                83,
                113,
                255,
            ),
        )

        # Petit cerveau stylisé.
        brain_left = width * 0.36
        brain_top = height * 0.32
        brain_right = width * 0.64
        brain_bottom = height * 0.68

        draw.ellipse(
            (
                brain_left,
                brain_top,
                brain_right,
                brain_bottom,
            ),
            fill=(
                255,
                155,
                203,
            ),
            outline=(
                35,
                25,
                70,
            ),
            width=max(
                4,
                width // 180,
            ),
        )

        try:

            font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/"
                "DejaVuSans-Bold.ttf",
                max(
                    24,
                    width // 24,
                ),
            )

        except OSError:

            font = ImageFont.load_default()

        bbox = draw.textbbox(
            (0, 0),
            text,
            font=font,
        )

        text_width = (
            bbox[2] - bbox[0]
        )

        text_height = (
            bbox[3] - bbox[1]
        )

        draw.text(
            (
                (width - text_width) / 2,
                height * 0.76,
            ),
            text,
            fill="white",
            font=font,
        )

        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        image.save(
            destination,
            "JPEG",
            quality=90,
        )

        return True

    except Exception:

        return False


# ============================================================
# SÉLECTION DE LA MEILLEURE PHOTO
# ============================================================

def _select_best_visual_photo(
    photos: List[dict],
    query: str,
    used_photo_ids: Optional[set] = None,
) -> Optional[dict]:

    if not photos:
        return None

    if used_photo_ids is None:
        used_photo_ids = set()

    query_words = set(
        _visual_query_keywords(
            query,
            max_words=12,
        )
    )

    candidates = []

    for photo in photos:

        if not isinstance(
            photo,
            dict,
        ):
            continue

        photo_id = str(
            photo.get(
                "id",
                "",
            )
        )

        if (
            photo_id
            and photo_id in used_photo_ids
        ):
            continue

        alt = str(
            photo.get(
                "alt",
                "",
            )
        ).lower()

        photographer = str(
            photo.get(
                "photographer",
                "",
            )
        ).lower()

        searchable = (
            f"{alt} {photographer}"
        )

        score = 0

        # Correspondance directe.
        for word in query_words:

            if word in searchable:

                score += 4

        # Favoriser une vraie photo.
        if photo.get("src"):
            score += 2

        # Favoriser une photo avec des dimensions
        # exploitables.
        width = photo.get(
            "width",
            0,
        )

        height = photo.get(
            "height",
            0,
        )

        try:

            width = int(
                width
            )

            height = int(
                height
            )

            if width >= 1000:
                score += 1

            if height >= 700:
                score += 1

        except (
            ValueError,
            TypeError,
        ):
            pass

        candidates.append(
            (
                score,
                photo,
            )
        )

    if not candidates:

        return None

    candidates.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    # Parmi les meilleurs résultats, choisir parfois
    # une autre photo pour éviter une série visuellement
    # trop similaire.
    top_score = candidates[0][0]

    top_candidates = [
        photo
        for score, photo in candidates
        if score >= max(
            0,
            top_score - 1,
        )
    ]

    return random.choice(
        top_candidates
    )


# ============================================================
# REQUÊTES ALTERNATIVES
# ============================================================

def _visual_query_variants(
    query: str,
) -> List[str]:

    keywords = _visual_query_keywords(
        query,
        max_words=8,
    )

    base = (
        " ".join(
            keywords
        )
        if keywords
        else "person thinking"
    )

    variants = [
        query,
        f"{base} realistic photo",
        f"{base} lifestyle photo",
        f"{base} candid photo",
    ]

    result = []

    for item in variants:

        item = normalize_text(
            item
        )

        if not item:
            continue

        if not _visual_query_is_safe(
            item
        ):
            continue

        if item not in result:

            result.append(
                item
            )

    return result


# ============================================================
# NOMBRE DE VISUELS
# ============================================================

def estimate_visual_count(
    duration: float,
    is_short: bool = True,
) -> int:

    try:

        duration = float(
            duration
        )

    except (
        ValueError,
        TypeError,
    ):

        duration = SHORT_TARGET_SECONDS

    if is_short:

        count = int(
            math.ceil(
                duration
                / VISUAL_TARGET_SECONDS
            )
        )

        return max(
            SHORT_VISUAL_MIN,
            min(
                count,
                SHORT_VISUAL_MAX,
            ),
        )

    count = int(
        math.ceil(
            duration
            / 7.0
        )
    )

    return max(
        LONG_VISUAL_MIN,
        min(
            count,
            LONG_VISUAL_MAX,
        ),
    )


# ============================================================
# DÉCOUPAGE DU TEXTE EN UNITÉS VISUELLES
# ============================================================

def _split_visual_units(
    text: str,
) -> List[str]:

    text = remove_visual_markers(
        text
    )

    text = normalize_text(
        text
    )

    if not text:
        return []

    sentences = re.split(
        r"(?<=[.!?])\s+",
        text,
    )

    units = []

    for sentence in sentences:

        sentence = normalize_text(
            sentence
        )

        if not sentence:
            continue

        words = count_words(
            sentence
        )

        # Une phrase très longue peut être séparée
        # naturellement sur une virgule ou un deux-points.
        if words > 18:

            clauses = re.split(
                r"\s*[,:\n]\s*",
                sentence,
            )

            valid_clauses = [
                normalize_text(
                    clause
                )
                for clause in clauses
                if count_words(
                    clause
                ) >= 3
            ]

            if len(
                valid_clauses
            ) >= 2:

                units.extend(
                    valid_clauses
                )

                continue

        units.append(
            sentence
        )

    return units


# ============================================================
# REGROUPEMENT DES UNITÉS
# ============================================================

def _group_visual_units(
    units: List[str],
    target_count: int,
) -> List[str]:

    if not units:
        return []

    target_count = max(
        1,
        min(
            target_count,
            len(units),
        ),
    )

    if len(units) <= target_count:

        return units

    total_words = sum(
        count_words(unit)
        for unit in units
    )

    if total_words <= 0:
        return units[
            :target_count
        ]

    target_words = (
        total_words
        / target_count
    )

    groups = []

    current = []

    current_words = 0

    for index, unit in enumerate(
        units
    ):

        current.append(
            unit
        )

        current_words += count_words(
            unit
        )

        remaining_units = (
            len(units)
            - index
            - 1
        )

        remaining_groups = (
            target_count
            - len(groups)
            - 1
        )

        should_close = False

        if (
            remaining_groups <= 0
        ):

            should_close = True

        elif (
            current_words
            >= target_words
        ):

            should_close = True

        elif (
            current_words
            >= target_words * 0.78
            and remaining_units
            >= remaining_groups
        ):

            should_close = True

        if should_close:

            groups.append(
                " ".join(
                    current
                ).strip()
            )

            current = []

            current_words = 0

    if current:

        groups.append(
            " ".join(
                current
            ).strip()
        )

    # Si un regroupement a produit trop peu de groupes,
    # on garde la meilleure segmentation possible.
    if len(groups) > target_count:

        groups = groups[
            :target_count - 1
        ] + [
            " ".join(
                groups[
                    target_count - 1:
                ]
            )
        ]

    return groups


# ============================================================
# PLAN VISUEL
# ============================================================

def build_visual_requests(
    script: str,
    target_count: int,
) -> List[Dict[str, str]]:

    units = _split_visual_units(
        script
    )

    groups = _group_visual_units(
        units,
        target_count,
    )

    markers = extract_visual_markers(
        script
    )

    requests = []

    for index, group in enumerate(
        groups
    ):

        # On donne la priorité aux marqueurs explicites
        # écrits par le scénariste IA.
        if index < len(markers):

            visual_description = (
                markers[index]
            )

        else:

            visual_description = group

        query = _make_visual_query(
            visual_description,
            index,
        )

        requests.append(
            {
                "text": group,
                "query": query,
            }
        )

    return requests


# ============================================================
# TIMING DES VISUELS À PARTIR DES MOTS
# ============================================================

def build_visual_timing(
    requests: List[Dict[str, str]],
    boundaries: List[Tuple[str, float, float]],
    total_duration: float,
) -> List[Dict]:

    if not requests:
        return []

    if not boundaries:

        total_words = sum(
            count_words(
                item["text"]
            )
            for item in requests
        )

        if total_words <= 0:
            total_words = len(
                requests
            )

        cursor = 0.0

        result = []

        for item in requests:

            words = max(
                1,
                count_words(
                    item["text"]
                ),
            )

            duration = (
                total_duration
                * words
                / total_words
            )

            result.append(
                {
                    **item,
                    "start": cursor,
                    "end": cursor + duration,
                }
            )

            cursor += duration

        if result:

            result[-1]["end"] = (
                total_duration
            )

        return result

    total_request_words = sum(
        max(
            1,
            count_words(
                item["text"]
            ),
        )
        for item in requests
    )

    boundary_count = len(
        boundaries
    )

    result = []

    cursor_word = 0

    for index, item in enumerate(
        requests
    ):

        item_words = max(
            1,
            count_words(
                item["text"]
            ),
        )

        start_word = cursor_word

        end_word = (
            cursor_word
            + item_words
        )

        start_ratio = (
            start_word
            / total_request_words
        )

        end_ratio = (
            end_word
            / total_request_words
        )

        start_index = int(
            round(
                start_ratio
                * boundary_count
            )
        )

        end_index = int(
            round(
                end_ratio
                * boundary_count
            )
        ) - 1

        start_index = max(
            0,
            min(
                start_index,
                boundary_count - 1,
            ),
        )

        end_index = max(
            start_index,
            min(
                end_index,
                boundary_count - 1,
            ),
        )

        if index == 0:

            start_time = 0.0

        else:

            start_time = boundaries[
                start_index
            ][1]

        if index == len(
            requests
        ) - 1:

            end_time = (
                total_duration
            )

        else:

            end_time = boundaries[
                end_index
            ][2]

        if end_time <= start_time:

            # Sécurité contre une segmentation
            # impossible à cause de différences de tokens.
            fallback_duration = (
                total_duration
                * item_words
                / total_request_words
            )

            end_time = (
                start_time
                + fallback_duration
            )

        result.append(
            {
                **item,
                "start": max(
                    0.0,
                    start_time,
                ),
                "end": min(
                    total_duration,
                    end_time,
                ),
            }
        )

        cursor_word = end_word

    # --------------------------------------------------------
    # Correction finale pour que les scènes s'enchaînent
    # exactement.
    # --------------------------------------------------------

    for index in range(
        len(result)
    ):

        if index > 0:

            result[index]["start"] = (
                result[index - 1]["end"]
            )

    if result:

        result[0]["start"] = 0.0

        result[-1]["end"] = (
            total_duration
        )

    return result


# ============================================================
# RÉCUPÉRATION DES VISUELS
# ============================================================

def get_visuals(
    script: str,
    output_dir: Path,
    target_count: int,
    width: int = 1920,
    height: int = 1080,
) -> List[Path]:

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    is_vertical = (
        height > width
    )

    orientation = (
        "portrait"
        if is_vertical
        else "landscape"
    )

    requests_list = (
        _build_supplemental_visual_queries(
            script,
            target_count,
        )
    )

    used_photo_ids = set()

    visuals = []

    query_index = 0

    for scene_index in range(
        target_count
    ):

        if query_index >= len(
            requests_list
        ):

            query = (
                "person everyday life "
                "realistic photo"
            )

        else:

            query = requests_list[
                query_index
            ]

        query_index += 1

        photo = None

        # ----------------------------------------------------
        # Plusieurs variantes permettent de récupérer
        # un résultat pertinent même si Pexels ne trouve
        # rien sur la première requête.
        # ----------------------------------------------------

        variants = (
            _visual_query_variants(
                query
            )
        )

        for variant in variants:

            photos = pexels_search(
                variant,
                per_page=8,
                orientation=orientation,
            )

            if not photos:
                continue

            candidate = (
                _select_best_visual_photo(
                    photos,
                    variant,
                    used_photo_ids,
                )
            )

            if candidate:

                photo = candidate
                break

        destination = (
            output_dir
            / f"visual_{scene_index + 1:02d}.jpg"
        )

        if photo:

            photo_id = str(
                photo.get(
                    "id",
                    "",
                )
            )

            if photo_id:

                used_photo_ids.add(
                    photo_id
                )

            src = photo.get(
                "src",
                {},
            )

            image_url = (
                src.get(
                    "large2x"
                )
                or src.get(
                    "large"
                )
                or src.get(
                    "original"
                )
            )

            temporary = (
                output_dir
                / f"_download_{scene_index + 1:02d}.jpg"
            )

            if (
                image_url
                and download_file(
                    image_url,
                    temporary,
                )
                and normalize_image(
                    temporary,
                    destination,
                    width=width,
                    height=height,
                )
            ):

                try:

                    temporary.unlink(
                        missing_ok=True
                    )

                except Exception:
                    pass

                visuals.append(
                    destination
                )

                continue

            try:

                temporary.unlink(
                    missing_ok=True
                )

            except Exception:
                pass

        # ----------------------------------------------------
        # Si Pexels échoue, utiliser un placeholder.
        # Le pipeline continue au lieu de planter.
        # ----------------------------------------------------

        if create_placeholder(
            destination,
            width,
            height,
            CHANNEL_NAME,
        ):

            visuals.append(
                destination
            )

    # --------------------------------------------------------
    # Garantie du nombre minimum.
    # --------------------------------------------------------

    while len(
        visuals
    ) < target_count:

        index = len(
            visuals
        )

        destination = (
            output_dir
            / f"visual_{index + 1:02d}.jpg"
        )

        if create_placeholder(
            destination,
            width,
            height,
            CHANNEL_NAME,
        ):

            visuals.append(
                destination
            )

        else:

            break

    return visuals


# ============================================================
# FIN DE LA PARTIE 2
# ============================================================# ============================================================
# PARTIE 3/4
# TTS, TIMINGS, SOUS-TITRES ET MASCOTTE
# ============================================================


# ============================================================
# VOIX EDGE-TTS
# ============================================================

PREFERRED_FRENCH_VOICES = [
    "fr-FR-DeniseNeural",
    "fr-FR-HenriNeural",
    "fr-FR-VivienneMultilingualNeural",
    "fr-FR-RemyMultilingualNeural",
]

# Le même débit doit être utilisé pour la narration
# ET pour les timings des sous-titres.
VOICE_RATE = "+2%"

VOICE_VOLUME = "+0%"


async def _list_tts_voices_async():
    return await edge_tts.list_voices()


def list_tts_voices() -> List[dict]:

    try:

        return asyncio.run(
            _list_tts_voices_async()
        )

    except RuntimeError:

        # Certains environnements possèdent déjà
        # une boucle asyncio active.
        loop = asyncio.new_event_loop()

        try:

            asyncio.set_event_loop(
                loop
            )

            return loop.run_until_complete(
                _list_tts_voices_async()
            )

        finally:

            loop.close()

            try:
                asyncio.set_event_loop(
                    None
                )
            except Exception:
                pass

    except Exception:

        return []


def select_french_voice() -> str:

    voices = list_tts_voices()

    available = {
        str(
            voice.get(
                "ShortName",
                ""
            )
        )
        for voice in voices
        if isinstance(
            voice,
            dict,
        )
    }

    for preferred in (
        PREFERRED_FRENCH_VOICES
    ):

        if preferred in available:

            return preferred

    # Fallback francophone.
    french_voices = sorted(
        [
            name
            for name in available
            if name.lower().startswith(
                "fr-"
            )
        ]
    )

    if french_voices:

        return french_voices[0]

    # Edge-TTS connaît normalement cette voix.
    return "fr-FR-DeniseNeural"


# ============================================================
# SYNTHÈSE VOCALE
# ============================================================

async def _synthesize_async(
    text: str,
    voice: str,
    output_path: str,
    rate: str,
    volume: str,
):

    communicator = edge_tts.Communicate(
        text,
        voice,
        rate=rate,
        volume=volume,
    )

    await communicator.save(
        output_path
    )


def synthesize_with_voice(
    text: str,
    output_path: Path,
    voice: Optional[str] = None,
    rate: str = VOICE_RATE,
    volume: str = VOICE_VOLUME,
) -> Path:

    text = remove_visual_markers(
        text
    )

    text = normalize_text(
        text
    )

    if not text:

        raise ValueError(
            "Impossible de synthétiser "
            "une narration vide."
        )

    if voice is None:

        voice = select_french_voice()

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:

        asyncio.run(
            _synthesize_async(
                text,
                voice,
                str(output_path),
                rate,
                volume,
            )
        )

    except RuntimeError:

        loop = asyncio.new_event_loop()

        try:

            asyncio.set_event_loop(
                loop
            )

            loop.run_until_complete(
                _synthesize_async(
                    text,
                    voice,
                    str(output_path),
                    rate,
                    volume,
                )
            )

        finally:

            loop.close()

            try:
                asyncio.set_event_loop(
                    None
                )
            except Exception:
                pass

    if not output_path.exists():

        raise RuntimeError(
            "Edge-TTS n'a pas produit "
            "le fichier audio."
        )

    if output_path.stat().st_size <= 0:

        raise RuntimeError(
            "Le fichier audio généré "
            "est vide."
        )

    return output_path


# ============================================================
# DURÉE AUDIO
# ============================================================

def get_audio_duration(
    audio_path: Path,
) -> float:

    ensure_ffmpeg()

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
        timeout=30,
    )

    if result.returncode != 0:

        raise RuntimeError(
            "Impossible de déterminer "
            "la durée audio : "
            + result.stderr[-1000:]
        )

    try:

        duration = float(
            result.stdout.strip()
        )

    except (
        ValueError,
        TypeError,
    ) as exc:

        raise RuntimeError(
            "Durée audio invalide."
        ) from exc

    if duration <= 0:

        raise RuntimeError(
            "La durée audio est nulle."
        )

    return duration


# ============================================================
# WORD BOUNDARIES EDGE-TTS
# ============================================================

async def _get_word_boundaries_async(
    text: str,
    voice: str,
    rate: str,
    volume: str,
) -> List[Tuple[str, float, float]]:

    communicator = edge_tts.Communicate(
        text,
        voice,
        rate=rate,
        volume=volume,
    )

    boundaries = []

    async for event in communicator.stream():

        event_type = str(
            event.get(
                "type",
                ""
            )
        )

        if event_type != "WordBoundary":
            continue

        word = str(
            event.get(
                "text",
                ""
            )
        ).strip()

        if not word:
            continue

        offset = event.get(
            "offset"
        )

        duration = event.get(
            "duration"
        )

        try:

            offset = float(
                offset
            )

            duration = float(
                duration
            )

        except (
            ValueError,
            TypeError,
        ):

            continue

        # Edge-TTS fournit les valeurs en unités
        # de 100 nanosecondes.
        start = offset / 10_000_000.0

        end = (
            offset + duration
        ) / 10_000_000.0

        if end <= start:

            end = start + 0.08

        boundaries.append(
            (
                word,
                start,
                end,
            )
        )

    return boundaries


def _weighted_word_boundaries(
    text: str,
    duration: float,
) -> List[Tuple[str, float, float]]:

    words = re.findall(
        r"\S+",
        text,
    )

    if not words:
        return []

    weights = []

    for word in words:

        clean = re.sub(
            r"[^\wÀ-ÿ'-]",
            "",
            word,
        )

        weight = max(
            1,
            len(clean),
        )

        # Une ponctuation forte provoque souvent
        # une petite pause vocale.
        if word.endswith(
            (".", "!", "?")
        ):

            weight += 2

        elif word.endswith(
            (",", ":")
        ):

            weight += 1

        weights.append(
            weight
        )

    total_weight = sum(
        weights
    )

    cursor = 0.0

    result = []

    for word, weight in zip(
        words,
        weights,
    ):

        word_duration = (
            duration
            * weight
            / total_weight
        )

        start = cursor

        end = (
            cursor
            + word_duration
        )

        result.append(
            (
                word,
                start,
                end,
            )
        )

        cursor = end

    if result:

        result[-1] = (
            result[-1][0],
            result[-1][1],
            duration,
        )

    return result


def get_word_boundaries(
    text: str,
    voice: str,
    duration: float,
    rate: str = VOICE_RATE,
    volume: str = VOICE_VOLUME,
) -> List[Tuple[str, float, float]]:

    clean_text = remove_visual_markers(
        text
    )

    clean_text = normalize_text(
        clean_text
    )

    if not clean_text:

        return []

    try:

        boundaries = asyncio.run(
            _get_word_boundaries_async(
                clean_text,
                voice,
                rate,
                volume,
            )
        )

    except Exception:

        boundaries = []

    if not boundaries:

        return _weighted_word_boundaries(
            clean_text,
            duration,
        )

    # Edge-TTS peut parfois produire un léger décalage
    # sur la dernière limite.
    if boundaries[-1][2] > duration:

        scale = (
            duration
            / boundaries[-1][2]
        )

        boundaries = [
            (
                word,
                start * scale,
                end * scale,
            )
            for word, start, end
            in boundaries
        ]

    # Sécurité.
    boundaries = [
        (
            word,
            max(
                0.0,
                start,
            ),
            min(
                duration,
                max(
                    start + 0.03,
                    end,
                ),
            ),
        )
        for word, start, end
        in boundaries
    ]

    return boundaries


# ============================================================
# GROUPES DE SOUS-TITRES
# ============================================================

def _subtitle_word_count_limit(
    video_width: int,
    video_height: int,
) -> int:

    if video_height > video_width:

        return 6

    return 8


def _group_subtitle_boundaries(
    boundaries: List[Tuple[str, float, float]],
    max_words: int = 6,
    max_duration: float = 2.8,
) -> List[List[Tuple[str, float, float]]]:

    if not boundaries:
        return []

    groups = []

    current = []

    for index, boundary in enumerate(
        boundaries
    ):

        word, start, end = boundary

        current.append(
            boundary
        )

        current_duration = (
            current[-1][2]
            - current[0][1]
        )

        word_count = len(
            current
        )

        punctuation_end = word.endswith(
            (".", "!", "?", ",", ":")
        )

        next_exists = (
            index + 1
            < len(boundaries)
        )

        should_close = False

        if word_count >= max_words:

            should_close = True

        elif (
            current_duration
            >= max_duration
        ):

            should_close = True

        elif (
            punctuation_end
            and word_count >= 3
        ):

            should_close = True

        elif not next_exists:

            should_close = True

        if should_close:

            groups.append(
                current
            )

            current = []

    if current:

        groups.append(
            current
        )

    return groups


# ============================================================
# ÉCHAPPEMENT ASS
# ============================================================

def escape_ass_text(
    text: str,
) -> str:

    if not text:
        return ""

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
        r"\N",
    )

    return text


def ass_timestamp(
    seconds: float,
) -> str:

    seconds = max(
        0.0,
        float(seconds),
    )

    hours = int(
        seconds // 3600
    )

    minutes = int(
        (
            seconds
            % 3600
        )
        // 60
    )

    remaining = (
        seconds
        % 60
    )

    # ASS utilise des centièmes de seconde.
    centiseconds = int(
        round(
            (
                remaining
                - int(remaining)
            )
            * 100
        )
    )

    whole_seconds = int(
        remaining
    )

    if centiseconds >= 100:

        whole_seconds += 1

        centiseconds = 0

    if whole_seconds >= 60:

        minutes += 1

        whole_seconds -= 60

    if minutes >= 60:

        hours += 1

        minutes -= 60

    return (
        f"{hours}:"
        f"{minutes:02d}:"
        f"{whole_seconds:02d}."
        f"{centiseconds:02d}"
    )


# ============================================================
# SOUS-TITRES PHRASE + MOT ACTIF
# ============================================================

def create_ass_subtitles(
    boundaries: List[Tuple[str, float, float]],
    output_path: Path,
    video_width: int = 1080,
    video_height: int = 1920,
) -> Path:

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if video_height > video_width:

        font_size = 60

        margin_vertical = 285

        max_words = 6

        max_phrase_duration = 2.7

    else:

        font_size = 48

        margin_vertical = 95

        max_words = 8

        max_phrase_duration = 3.0

    groups = _group_subtitle_boundaries(
        boundaries,
        max_words=max_words,
        max_duration=max_phrase_duration,
    )

    # ASS utilise BGR et non RGB.
    white = "&H00FFFFFF&"

    active = "&H004AD5FF&"

    outline = "&H00141420&"

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "ScaledBorderAndShadow: yes",
        "WrapStyle: 2",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        (
            "Style: Default,"
            "DejaVu Sans,"
            f"{font_size},"
            f"{white},"
            f"{white},"
            f"{outline},"
            "&H80000000&,"
            "1,0,0,0,"
            "100,100,0,0,"
            "1,4,2,2,"
            "60,60,"
            f"{margin_vertical},"
            "1"
        ),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    # --------------------------------------------------------
    # Pour chaque phrase, plusieurs événements sont créés.
    #
    # La phrase entière reste visible.
    # Seul le mot actuellement prononcé change de couleur.
    # --------------------------------------------------------

    for group in groups:

        if not group:
            continue

        phrase_start = group[0][1]

        phrase_end = group[-1][2]

        escaped_words = [
            escape_ass_text(
                word
            )
            for word, _, _
            in group
        ]

        for active_index, boundary in enumerate(
            group
        ):

            word, word_start, word_end = (
                boundary
            )

            event_start = (
                phrase_start
            )

            event_end = (
                phrase_end
            )

            # Le mot actif reste coloré pendant son temps
            # de prononciation.
            parts = []

            for index, escaped_word in enumerate(
                escaped_words
            ):

                if index == active_index:

                    parts.append(
                        "{"
                        f"\\c{active}"
                        "}"
                        f"{escaped_word}"
                        "{"
                        f"\\c{white}"
                        "}"
                    )

                else:

                    parts.append(
                        escaped_word
                    )

            subtitle_text = " ".join(
                parts
            )

            lines.append(
                "Dialogue: 0,"
                f"{ass_timestamp(event_start)},"
                f"{ass_timestamp(event_end)},"
                "Default,"
                ",0,0,0,,"
                f"{subtitle_text}"
            )

    output_path.write_text(
        "\n".join(
            lines
        ),
        encoding="utf-8",
    )

    return output_path


# ============================================================
# MASCOTTE CERVEAU CURIEUX
# ============================================================

def _find_existing_mascot() -> Optional[Path]:

    candidates = [
        BASE_DIR / "assets" / "mascot.png",
        BASE_DIR / "assets" / "cerveau_curieux.png",
        BASE_DIR / "assets" / "brain_mascot.png",
        BASE_DIR / "mascot.png",
        BASE_DIR / "cerveau_curieux.png",
        BASE_DIR / "brain_mascot.png",
    ]

    for candidate in candidates:

        if candidate.exists():

            return candidate

    return None


def _font_for_mascot(
    size: int,
    bold: bool = True,
):

    filenames = []

    if bold:

        filenames.append(
            "/usr/share/fonts/truetype/dejavu/"
            "DejaVuSans-Bold.ttf"
        )

    filenames.append(
        "/usr/share/fonts/truetype/dejavu/"
        "DejaVuSans.ttf"
    )

    for filename in filenames:

        try:

            return ImageFont.truetype(
                filename,
                size,
            )

        except OSError:
            continue

    return ImageFont.load_default()


def create_mascot_asset(
    output_dir: Path,
) -> Path:

    existing = _find_existing_mascot()

    if existing:

        return existing

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        output_dir
        / "cerveau_curieux_mascot.png"
    )

    size = 600

    image = Image.new(
        "RGBA",
        (
            size,
            size,
        ),
        (
            0,
            0,
            0,
            0,
        ),
    )

    draw = ImageDraw.Draw(
        image
    )

    # --------------------------------------------------------
    # Badge circulaire bleu-violet.
    # --------------------------------------------------------

    center = size // 2

    for radius in range(
        280,
        235,
        -1,
    ):

        ratio = (
            280 - radius
        ) / 45

        r = int(
            MASCOT_BLUE[0]
            * (1 - ratio)
            + MASCOT_PURPLE[0]
            * ratio
        )

        g = int(
            MASCOT_BLUE[1]
            * (1 - ratio)
            + MASCOT_PURPLE[1]
            * ratio
        )

        b = int(
            MASCOT_BLUE[2]
            * (1 - ratio)
            + MASCOT_PURPLE[2]
            * ratio
        )

        draw.ellipse(
            (
                center - radius,
                center - radius,
                center + radius,
                center + radius,
            ),
            fill=(
                r,
                g,
                b,
                255,
            ),
        )

    # --------------------------------------------------------
    # Cerveau.
    # --------------------------------------------------------

    brain_fill = (
        255,
        158,
        205,
        255,
    )

    brain_outline = (
        66,
        38,
        115,
        255,
    )

    # Partie principale.
    draw.rounded_rectangle(
        (
            150,
            155,
            450,
            440,
        ),
        radius=105,
        fill=brain_fill,
        outline=brain_outline,
        width=13,
    )

    # Lobes supérieurs.
    for box in [
        (155, 95, 260, 225),
        (220, 75, 330, 220),
        (295, 80, 405, 220),
        (355, 110, 455, 235),
    ]:

        draw.ellipse(
            box,
            fill=brain_fill,
            outline=brain_outline,
            width=11,
        )

    # --------------------------------------------------------
    # Circonvolutions du cerveau.
    # --------------------------------------------------------

    fold_color = (
        170,
        65,
        145,
        255,
    )

    folds = [
        (205, 145, 245, 190),
        (250, 130, 290, 185),
        (305, 135, 350, 190),
        (365, 150, 405, 205),
        (185, 230, 245, 275),
        (265, 220, 320, 275),
        (335, 225, 395, 280),
        (205, 305, 255, 350),
        (275, 300, 330, 350),
        (350, 305, 395, 355),
    ]

    for box in folds:

        draw.arc(
            box,
            20,
            155,
            fill=fold_color,
            width=8,
        )

    # --------------------------------------------------------
    # Yeux.
    # --------------------------------------------------------

    eye_y = 265

    draw.ellipse(
        (
            205,
            eye_y,
            255,
            eye_y + 60,
        ),
        fill="white",
    )

    draw.ellipse(
        (
            345,
            eye_y,
            395,
            eye_y + 60,
        ),
        fill="white",
    )

    draw.ellipse(
        (
            222,
            eye_y + 17,
            244,
            eye_y + 42,
        ),
        fill=(
            20,
            20,
            30,
        ),
    )

    draw.ellipse(
        (
            362,
            eye_y + 17,
            384,
            eye_y + 42,
        ),
        fill=(
            20,
            20,
            30,
        ),
    )

    # Reflets.
    draw.ellipse(
        (
            227,
            eye_y + 19,
            233,
            eye_y + 25,
        ),
        fill="white",
    )

    draw.ellipse(
        (
            367,
            eye_y + 19,
            373,
            eye_y + 25,
        ),
        fill="white",
    )

    # --------------------------------------------------------
    # Sourire ouvert, donnant l'impression que le cerveau
    # raconte quelque chose.
    # --------------------------------------------------------

    draw.ellipse(
        (
            250,
            340,
            350,
            400,
        ),
        fill=(
            65,
            30,
            75,
        ),
    )

    draw.arc(
        (
            268,
            355,
            332,
            390,
        ),
        0,
        180,
        fill=(
            255,
            220,
            235,
        ),
        width=8,
    )

    # Petite dentition.
    draw.rounded_rectangle(
        (
            280,
            352,
            320,
            370,
        ),
        radius=7,
        fill="white",
    )

    # --------------------------------------------------------
    # Petite bulle "?" pour renforcer le côté curieux.
    # --------------------------------------------------------

    font = _font_for_mascot(
        55
    )

    draw.ellipse(
        (
            405,
            45,
            515,
            155,
        ),
        fill="white",
        outline=brain_outline,
        width=8,
    )

    bbox = draw.textbbox(
        (0, 0),
        "?",
        font=font,
    )

    q_width = (
        bbox[2] - bbox[0]
    )

    q_height = (
        bbox[3] - bbox[1]
    )

    draw.text(
        (
            460 - q_width / 2,
            100 - q_height / 2 - 5,
        ),
        "?",
        fill=(
            75,
            55,
            180,
        ),
        font=font,
    )

    # --------------------------------------------------------
    # Réduction antialiasée.
    # --------------------------------------------------------

    image = image.resize(
        (
            420,
            420,
        ),
        Image.Resampling.LANCZOS,
    )

    image.save(
        output_path,
        "PNG",
    )

    return output_path


# ============================================================
# ANIMATION DE LA MASCOTTE
# ============================================================

def create_mascot_variant(
    output_dir: Path,
    variant: str = "talking",
) -> Path:

    base_path = create_mascot_asset(
        output_dir
    )

    if variant != "talking":

        return base_path

    output_path = (
        output_dir
        / "cerveau_curieux_talking.png"
    )

    # Une variante légèrement plus expressive.
    try:

        image = Image.open(
            base_path
        ).convert(
            "RGBA"
        )

        draw = ImageDraw.Draw(
            image
        )

        width, height = (
            image.size
        )

        # Petite bouche plus ouverte.
        draw.ellipse(
            (
                int(width * 0.57),
                int(height * 0.70),
                int(width * 0.76),
                int(height * 0.86),
            ),
            fill=(
                55,
                25,
                65,
                255,
            ),
        )

        draw.ellipse(
            (
                int(width * 0.61),
                int(height * 0.715),
                int(width * 0.72),
                int(height * 0.76),
            ),
            fill=(
                255,
                225,
                240,
                255,
            ),
        )

        image.save(
            output_path,
            "PNG",
        )

        return output_path

    except Exception:

        return base_path


# ============================================================
# FIN DE LA PARTIE 3
# ============================================================# ============================================================
# PARTIE 4/4
# MONTAGE FFmpeg, MASCOTTE, PRODUCTION ET INTERFACE
# ============================================================


# ============================================================
# DURÉES DES SCÈNES
# ============================================================

def distribute_scene_durations(
    total_duration: float,
    count: int,
) -> List[float]:

    if count <= 0:
        return []

    total_duration = max(
        0.1,
        float(total_duration),
    )

    # Répartition légèrement naturelle.
    # Les durées ne sont plus complètement identiques.
    base = (
        total_duration
        / count
    )

    durations = []

    for index in range(
        count
    ):

        factor_pattern = [
            0.90,
            1.05,
            0.96,
            1.08,
            0.94,
            1.03,
        ]

        factor = factor_pattern[
            index
            % len(factor_pattern)
        ]

        durations.append(
            base * factor
        )

    current_total = sum(
        durations
    )

    if current_total <= 0:

        return [
            base
            for _ in range(count)
        ]

    correction = (
        total_duration
        / current_total
    )

    durations = [
        duration * correction
        for duration in durations
    ]

    # Dernière correction pour éviter
    # les erreurs d'arrondi.
    difference = (
        total_duration
        - sum(durations)
    )

    if durations:

        durations[-1] += difference

    return durations


# ============================================================
# CRÉATION D'UNE SCÈNE IMAGE
# ============================================================

def create_image_scene(
    image_path: Path,
    output_path: Path,
    duration: float,
    width: int = 1080,
    height: int = 1920,
    scene_index: int = 0,
) -> Path:

    ensure_ffmpeg()

    duration = max(
        0.2,
        float(duration),
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # On agrandit légèrement l'image avant le crop.
    #
    # Cela permet de créer un mouvement de caméra très léger
    # sans utiliser zoompan, qui était beaucoup trop lourd
    # pour Streamlit Community Cloud.
    # --------------------------------------------------------

    scale_factor = 1.10

    scaled_width = max(
        width + 2,
        int(
            width
            * scale_factor
        ),
    )

    scaled_height = max(
        height + 2,
        int(
            height
            * scale_factor
        ),
    )

    period = max(
        4.0,
        duration * 1.25,
    )

    # Plusieurs directions permettent de ne pas donner
    # l'impression que toutes les images font exactement
    # le même mouvement.
    movement = scene_index % 6

    if movement == 0:

        x_expr = (
            f"((iw-{width})/2)"
            f"*(1+0.72*sin(2*PI*t/{period:.3f}))"
        )

        y_expr = (
            f"(ih-{height})/2"
        )

    elif movement == 1:

        x_expr = (
            f"(iw-{width})/2"
        )

        y_expr = (
            f"((ih-{height})/2)"
            f"*(1+0.72*sin(2*PI*t/{period:.3f}))"
        )

    elif movement == 2:

        x_expr = (
            f"((iw-{width})/2)"
            f"*(1-0.72*sin(2*PI*t/{period:.3f}))"
        )

        y_expr = (
            f"(ih-{height})/2"
        )

    elif movement == 3:

        x_expr = (
            f"(iw-{width})/2"
        )

        y_expr = (
            f"((ih-{height})/2)"
            f"*(1-0.72*sin(2*PI*t/{period:.3f}))"
        )

    elif movement == 4:

        x_expr = (
            f"((iw-{width})/2)"
            f"*(1+0.58*sin(2*PI*t/{period:.3f}))"
        )

        y_expr = (
            f"((ih-{height})/2)"
            f"*(1+0.48*cos(2*PI*t/{period:.3f}))"
        )

    else:

        x_expr = (
            f"((iw-{width})/2)"
            f"*(1+0.58*cos(2*PI*t/{period:.3f}))"
        )

        y_expr = (
            f"((ih-{height})/2)"
            f"*(1+0.48*sin(2*PI*t/{period:.3f}))"
        )

    filter_complex = (
        f"scale={scaled_width}:{scaled_height}:"
        "force_original_aspect_ratio=increase,"
        f"crop=w={width}:h={height}:"
        f"x='{x_expr}':"
        f"y='{y_expr}',"
        "format=yuv420p"
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
        "23",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    result = run_command(
        command,
        timeout=120,
    )

    if result.returncode != 0:

        # ----------------------------------------------------
        # Fallback sans mouvement.
        #
        # La fiabilité du pipeline est prioritaire.
        # ----------------------------------------------------

        fallback_filter = (
            f"scale={width}:{height}:"
            "force_original_aspect_ratio=increase,"
            f"crop={width}:{height},"
            "format=yuv420p"
        )

        fallback_command = [
            "ffmpeg",
            "-y",
            "-loop",
            "1",
            "-i",
            str(image_path),
            "-vf",
            fallback_filter,
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
            "23",
            "-pix_fmt",
            "yuv420p",
            str(output_path),
        ]

        fallback_result = run_command(
            fallback_command,
            timeout=120,
        )

        if fallback_result.returncode != 0:

            raise RuntimeError(
                "FFmpeg n'a pas réussi à créer "
                f"la scène {scene_index + 1}.\n"
                + fallback_result.stderr[-2000:]
            )

    if not output_path.exists():

        raise RuntimeError(
            "La scène vidéo n'a pas été créée."
        )

    return output_path


# ============================================================
# CONCATÉNATION DES SCÈNES
# ============================================================

def concat_scenes(
    scene_paths: List[Path],
    output_path: Path,
) -> Path:

    ensure_ffmpeg()

    if not scene_paths:

        raise RuntimeError(
            "Aucune scène à concaténer."
        )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    list_file = (
        output_path.parent
        / "concat_list.txt"
    )

    lines = []

    for path in scene_paths:

        absolute_path = (
            path.resolve()
        )

        escaped = str(
            absolute_path
        ).replace(
            "'",
            "'\\''",
        )

        lines.append(
            f"file '{escaped}'"
        )

    list_file.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    # --------------------------------------------------------
    # Première tentative : concaténation sans réencodage.
    # --------------------------------------------------------

    command = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    result = run_command(
        command,
        timeout=120,
    )

    if (
        result.returncode == 0
        and output_path.exists()
    ):

        return output_path

    # --------------------------------------------------------
    # Fallback : réencodage.
    # --------------------------------------------------------

    fallback_command = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    fallback_result = run_command(
        fallback_command,
        timeout=180,
    )

    if (
        fallback_result.returncode != 0
        or not output_path.exists()
    ):

        raise RuntimeError(
            "Impossible de concaténer les scènes.\n"
            + fallback_result.stderr[-2500:]
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

    ensure_ffmpeg()

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

    result = run_command(
        command,
        timeout=120,
    )

    if (
        result.returncode != 0
        or not output_path.exists()
    ):

        raise RuntimeError(
            "Impossible d'ajouter la narration.\n"
            + result.stderr[-2500:]
        )

    return output_path


# ============================================================
# INCRUSTATION SOUS-TITRES + MASCOTTE
# ============================================================

def _escape_filter_path(
    path: Path,
) -> str:

    value = str(
        path.resolve()
    )

    value = value.replace(
        "\\",
        "\\\\",
    )

    value = value.replace(
        ":",
        "\\:",
    )

    value = value.replace(
        "'",
        "\\'",
    )

    value = value.replace(
        "[",
        "\\[",
    )

    value = value.replace(
        "]",
        "\\]",
    )

    return value


def burn_subtitles(
    video_path: Path,
    ass_path: Path,
    output_path: Path,
    mascot_path: Optional[Path] = None,
    mascot_width: int = MASCOT_WIDTH,
) -> Path:

    ensure_ffmpeg()

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    ass_filter_path = (
        _escape_filter_path(
            ass_path
        )
    )

    # --------------------------------------------------------
    # SANS MASCOTTE
    # --------------------------------------------------------

    if (
        mascot_path is None
        or not mascot_path.exists()
    ):

        video_filter = (
            f"ass='{ass_filter_path}'"
        )

        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vf",
            video_filter,
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
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
            "-movflags",
            "+faststart",
            "-shortest",
            str(output_path),
        ]

    else:

        mascot_filter_path = (
            _escape_filter_path(
                mascot_path
            )
        )

        # ----------------------------------------------------
        # La mascotte est placée en bas à gauche.
        #
        # Le mouvement est volontairement discret.
        # Elle semble donc "vivante" sans distraire du contenu.
        # ----------------------------------------------------

        filter_complex = (
            f"[0:v]"
            f"ass='{ass_filter_path}'"
            "[sub];"
            f"[1:v]"
            "format=rgba,"
            f"scale={mascot_width}:-1"
            "[mas];"
            "[sub][mas]"
            "overlay="
            "x='35+5*sin(2*PI*t/1.8)':"
            "y='H-h-35+4*sin(2*PI*t/0.9)':"
            "eof_action=pass:"
            "shortest=1"
            "[outv]"
        )

        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-loop",
            "1",
            "-i",
            str(mascot_path),
            "-filter_complex",
            filter_complex,
            "-map",
            "[outv]",
            "-map",
            "0:a:0?",
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
            "-movflags",
            "+faststart",
            "-shortest",
            str(output_path),
        ]

    result = run_command(
        command,
        timeout=180,
    )

    if (
        result.returncode != 0
        or not output_path.exists()
    ):

        # ----------------------------------------------------
        # Fallback : sous-titres sans mascotte.
        #
        # On ne veut surtout pas faire échouer une vidéo
        # complète uniquement à cause de l'overlay.
        # ----------------------------------------------------

        if (
            mascot_path is not None
            and mascot_path.exists()
        ):

            st.warning(
                "La mascotte n'a pas pu être "
                "incrustée. La vidéo sera finalisée "
                "avec les sous-titres."
            )

            fallback_filter = (
                f"ass='{ass_filter_path}'"
            )

            fallback_command = [
                "ffmpeg",
                "-y",
                "-i",
                str(video_path),
                "-vf",
                fallback_filter,
                "-map",
                "0:v:0",
                "-map",
                "0:a:0?",
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
                "-movflags",
                "+faststart",
                "-shortest",
                str(output_path),
            ]

            fallback_result = run_command(
                fallback_command,
                timeout=180,
            )

            if (
                fallback_result.returncode != 0
                or not output_path.exists()
            ):

                raise RuntimeError(
                    "Impossible de brûler les "
                    "sous-titres.\n"
                    + fallback_result.stderr[-2500:]
                )

        else:

            raise RuntimeError(
                "Impossible de finaliser la vidéo.\n"
                + result.stderr[-2500:]
            )

    return output_path


# ============================================================
# CRÉATION DU PLAN VISUEL COMPLET
# ============================================================

def create_visual_plan(
    script: str,
    boundaries: List[Tuple[str, float, float]],
    duration: float,
    output_dir: Path,
    width: int,
    height: int,
    is_short: bool,
) -> Tuple[List[Path], List[float]]:

    target_count = estimate_visual_count(
        duration,
        is_short=is_short,
    )

    requests_list = build_visual_requests(
        script,
        target_count,
    )

    timing_plan = build_visual_timing(
        requests_list,
        boundaries,
        duration,
    )

    if not timing_plan:

        timing_plan = []

        fallback_durations = (
            distribute_scene_durations(
                duration,
                target_count,
            )
        )

        for index in range(
            target_count
        ):

            timing_plan.append(
                {
                    "text": "",
                    "query": (
                        "person everyday life "
                        "realistic photo"
                    ),
                    "start": sum(
                        fallback_durations[
                            :index
                        ]
                    ),
                    "end": sum(
                        fallback_durations[
                            :index + 1
                        ]
                    ),
                }
            )

    # --------------------------------------------------------
    # Récupération des images.
    # --------------------------------------------------------

    visual_dir = (
        output_dir
        / "visuals"
    )

    visual_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    used_photo_ids = set()

    visuals = []

    for index, item in enumerate(
        timing_plan
    ):

        query = item.get(
            "query",
            "",
        )

        if not query:

            query = (
                "person everyday life "
                "realistic photo"
            )

        photo = None

        for variant in _visual_query_variants(
            query
        ):

            photos = pexels_search(
                variant,
                per_page=8,
                orientation=(
                    "portrait"
                    if height > width
                    else "landscape"
                ),
            )

            if not photos:
                continue

            candidate = (
                _select_best_visual_photo(
                    photos,
                    variant,
                    used_photo_ids,
                )
            )

            if candidate:

                photo = candidate
                break

        destination = (
            visual_dir
            / f"visual_{index + 1:02d}.jpg"
        )

        if photo:

            photo_id = str(
                photo.get(
                    "id",
                    "",
                )
            )

            if photo_id:

                used_photo_ids.add(
                    photo_id
                )

            src = photo.get(
                "src",
                {},
            )

            image_url = (
                src.get(
                    "large2x"
                )
                or src.get(
                    "large"
                )
                or src.get(
                    "original"
                )
            )

            temporary = (
                visual_dir
                / f"_raw_{index + 1:02d}.jpg"
            )

            if (
                image_url
                and download_file(
                    image_url,
                    temporary,
                )
                and normalize_image(
                    temporary,
                    destination,
                    width=width,
                    height=height,
                )
            ):

                try:

                    temporary.unlink(
                        missing_ok=True
                    )

                except Exception:
                    pass

                visuals.append(
                    destination
                )

                continue

            try:

                temporary.unlink(
                    missing_ok=True
                )

            except Exception:
                pass

        # Fallback visuel.
        if create_placeholder(
            destination,
            width,
            height,
            CHANNEL_NAME,
        ):

            visuals.append(
                destination
            )

    # --------------------------------------------------------
    # Garantie du nombre de scènes.
    # --------------------------------------------------------

    while len(
        visuals
    ) < len(timing_plan):

        index = len(
            visuals
        )

        destination = (
            visual_dir
            / f"visual_{index + 1:02d}.jpg"
        )

        if create_placeholder(
            destination,
            width,
            height,
            CHANNEL_NAME,
        ):

            visuals.append(
                destination
            )

        else:

            break

    # --------------------------------------------------------
    # Durées correspondant au plan.
    # --------------------------------------------------------

    durations = []

    for item in timing_plan:

        start = float(
            item.get(
                "start",
                0,
            )
        )

        end = float(
            item.get(
                "end",
                0,
            )
        )

        scene_duration = max(
            0.2,
            end - start,
        )

        durations.append(
            scene_duration
        )

    # Correction du total.
    if durations:

        difference = (
            duration
            - sum(durations)
        )

        durations[-1] = max(
            0.2,
            durations[-1]
            + difference,
        )

    return visuals, durations


# ============================================================
# CONSTRUCTION D'UNE VIDÉO COMPLÈTE
# ============================================================

def build_video(
    script: str,
    output_dir: Path,
    is_short: bool = True,
    width: int = 1080,
    height: int = 1920,
) -> Path:

    ensure_ffmpeg()

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    clean_script = remove_visual_markers(
        script
    )

    clean_script = normalize_text(
        clean_script
    )

    if not clean_script:

        raise RuntimeError(
            "Le script ne contient aucune "
            "narration exploitable."
        )

    # --------------------------------------------------------
    # 1. VOIX
    # --------------------------------------------------------

    voice = select_french_voice()

    st.write(
        f"Voix sélectionnée : `{voice}`"
    )

    audio_path = (
        output_dir
        / "narration.mp3"
    )

    st.write(
        "Génération de la narration..."
    )

    synthesize_with_voice(
        clean_script,
        audio_path,
        voice=voice,
        rate=VOICE_RATE,
        volume=VOICE_VOLUME,
    )

    duration = get_audio_duration(
        audio_path
    )

    st.write(
        f"Durée de narration : "
        f"{duration:.1f} secondes"
    )

    # --------------------------------------------------------
    # 2. TIMINGS MOTS
    #
    # IMPORTANT :
    # on utilise exactement le même VOICE_RATE que
    # pour la génération audio.
    # --------------------------------------------------------

    st.write(
        "Calcul de la synchronisation..."
    )

    boundaries = get_word_boundaries(
        clean_script,
        voice=voice,
        duration=duration,
        rate=VOICE_RATE,
        volume=VOICE_VOLUME,
    )

    # --------------------------------------------------------
    # 3. VISUELS
    # --------------------------------------------------------

    target_visual_count = estimate_visual_count(
        duration,
        is_short=is_short,
    )

    st.write(
        f"Recherche de {target_visual_count} "
        "visuels adaptés..."
    )

    visuals, scene_durations = (
        create_visual_plan(
            script,
            boundaries,
            duration,
            output_dir,
            width,
            height,
            is_short,
        )
    )

    if not visuals:

        raise RuntimeError(
            "Aucun visuel n'a pu être préparé."
        )

    # --------------------------------------------------------
    # 4. CRÉATION DES SCÈNES
    # --------------------------------------------------------

    scenes_dir = (
        output_dir
        / "scenes"
    )

    scenes_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    scene_paths = []

    progress = st.progress(
        0
    )

    total_scenes = min(
        len(visuals),
        len(scene_durations),
    )

    for index in range(
        total_scenes
    ):

        scene_duration = (
            scene_durations[index]
        )

        scene_path = (
            scenes_dir
            / f"scene_{index + 1:02d}.mp4"
        )

        st.write(
            f"Scène {index + 1}/{total_scenes} "
            f"• {scene_duration:.1f}s"
        )

        create_image_scene(
            visuals[index],
            scene_path,
            scene_duration,
            width=width,
            height=height,
            scene_index=index,
        )

        scene_paths.append(
            scene_path
        )

        progress.progress(
            int(
                (
                    index + 1
                )
                / total_scenes
                * 100
            )
        )

    progress.empty()

    # --------------------------------------------------------
    # 5. CONCATÉNATION
    # --------------------------------------------------------

    st.write(
        "Assemblage des scènes..."
    )

    silent_video = (
        output_dir
        / "video_silent.mp4"
    )

    concat_scenes(
        scene_paths,
        silent_video,
    )

    # --------------------------------------------------------
    # 6. AUDIO
    # --------------------------------------------------------

    st.write(
        "Ajout de la narration..."
    )

    video_with_audio = (
        output_dir
        / "video_audio.mp4"
    )

    attach_audio(
        silent_video,
        audio_path,
        video_with_audio,
    )

    # --------------------------------------------------------
    # 7. SOUS-TITRES
    # --------------------------------------------------------

    st.write(
        "Création des sous-titres "
        "mot par mot avec phrase persistante..."
    )

    ass_path = (
        output_dir
        / "subtitles.ass"
    )

    create_ass_subtitles(
        boundaries,
        ass_path,
        video_width=width,
        video_height=height,
    )

    # --------------------------------------------------------
    # 8. MASCOTTE
    # --------------------------------------------------------

    st.write(
        "Préparation de la mascotte "
        "Cerveau Curieux..."
    )

    mascot_dir = (
        output_dir
        / "mascot"
    )

    mascot_path = create_mascot_variant(
        mascot_dir,
        variant="talking",
    )

    # --------------------------------------------------------
    # 9. RENDU FINAL
    # --------------------------------------------------------

    final_path = (
        output_dir
        / "final.mp4"
    )

    st.write(
        "Rendu final : sous-titres + mascotte..."
    )

    burn_subtitles(
        video_with_audio,
        ass_path,
        final_path,
        mascot_path=mascot_path,
        mascot_width=(
            MASCOT_WIDTH
            if is_short
            else 160
        ),
    )

    if not final_path.exists():

        raise RuntimeError(
            "Le fichier final n'existe pas."
        )

    final_duration = get_video_duration(
        final_path
    )

    st.write(
        f"Vidéo finale : "
        f"{final_duration:.1f} secondes"
    )

    return final_path


# ============================================================
# DURÉE VIDÉO
# ============================================================

def get_video_duration(
    video_path: Path,
) -> float:

    ensure_ffmpeg()

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
        timeout=30,
    )

    if result.returncode != 0:

        return 0.0

    try:

        return max(
            0.0,
            float(
                result.stdout.strip()
            ),
        )

    except (
        ValueError,
        TypeError,
    ):

        return 0.0


# ============================================================
# RÉPERTOIRE D'UNE PRODUCTION
# ============================================================

def create_production_directory(
    prefix: str = "production",
) -> Path:

    timestamp = time.strftime(
        "%Y%m%d_%H%M%S"
    )

    production_dir = (
        TEMP_DIR
        / f"{prefix}_{timestamp}"
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
    topic: str,
    short_number: int = 1,
) -> Path:

    production_dir = (
        create_production_directory(
            f"short_{short_number}"
        )
    )

    final_path = build_video(
        script,
        production_dir,
        is_short=True,
        width=1080,
        height=1920,
    )

    # Copie pratique dans outputs.
    output_path = (
        OUTPUT_DIR
        / f"short_{short_number}.mp4"
    )

    shutil.copy2(
        final_path,
        output_path,
    )

    return output_path


# ============================================================
# TRAITEMENT D'UNE VIDÉO LONGUE
# ============================================================

def process_long_video(
    script: str,
    topic: str,
) -> Path:

    production_dir = (
        create_production_directory(
            "long_video"
        )
    )

    final_path = build_video(
        script,
        production_dir,
        is_short=False,
        width=1920,
        height=1080,
    )

    output_path = (
        OUTPUT_DIR
        / "long_video.mp4"
    )

    shutil.copy2(
        final_path,
        output_path,
    )

    return output_path


# ============================================================
# TRAITEMENT DU TEASER
# ============================================================

def process_teaser(
    script: str,
    topic: str,
) -> Path:

    production_dir = (
        create_production_directory(
            "teaser"
        )
    )

    final_path = build_video(
        script,
        production_dir,
        is_short=True,
        width=1080,
        height=1920,
    )

    output_path = (
        OUTPUT_DIR
        / "teaser.mp4"
    )

    shutil.copy2(
        final_path,
        output_path,
    )

    return output_path


# ============================================================
# COPIE DE SORTIE
# ============================================================

def copy_final_output(
    source: Path,
    filename: str,
) -> Path:

    destination = (
        OUTPUT_DIR
        / filename
    )

    shutil.copy2(
        source,
        destination,
    )

    return destination


# ============================================================
# NETTOYAGE DES ANCIENNES PRODUCTIONS
# ============================================================

def cleanup_old_temp(
    max_age_hours: int = 24,
) -> None:

    if not TEMP_DIR.exists():
        return

    now = time.time()

    max_age_seconds = (
        max_age_hours
        * 3600
    )

    for item in TEMP_DIR.iterdir():

        try:

            age = (
                now
                - item.stat().st_mtime
            )

            if age > max_age_seconds:

                if item.is_dir():

                    shutil.rmtree(
                        item,
                        ignore_errors=True,
                    )

                else:

                    item.unlink(
                        missing_ok=True
                    )

        except Exception:
            continue


# ============================================================
# WORKFLOW GLOBAL
# ============================================================

def run_generation(
    topic: str,
) -> Dict:

    topic = normalize_text(
        topic
    )

    if not topic:

        raise ValueError(
            "Veuillez entrer un sujet."
        )

    ensure_ffmpeg()

    cleanup_old_temp()

    result = {
        "topic": topic,
        "mode": "",
        "videos": [],
        "script": "",
    }

    # --------------------------------------------------------
    # 1. SCRIPT PRINCIPAL
    # --------------------------------------------------------

    st.write(
        "Génération du scénario..."
    )

    main_script = generate_main_script(
        topic
    )

    main_script = clean_ai_text(
        main_script
    )

    narration_script = remove_visual_markers(
        main_script
    )

    word_count = count_words(
        narration_script
    )

    result["script"] = main_script

    st.write(
        f"Script généré : {word_count} mots"
    )

    # --------------------------------------------------------
    # 2. CHOIX AUTOMATIQUE
    # --------------------------------------------------------

    mode = choose_content_mode(
        word_count
    )

    result["mode"] = mode

    # --------------------------------------------------------
    # 3. SCRIPT TROP COURT
    #
    # On tente une régénération, mais si elle échoue,
    # le contenu reste exploitable.
    # --------------------------------------------------------

    if (
        word_count < REGENERATE_BELOW
    ):

        st.warning(
            "Le premier script est très court. "
            "Tentative d'amélioration..."
        )

        try:

            improved_script = (
                regenerate_short_main_script(
                    topic
                )
            )

            improved_script = (
                clean_ai_text(
                    improved_script
                )
            )

            if count_words(
                remove_visual_markers(
                    improved_script
                )
            ) > word_count:

                main_script = improved_script

                word_count = count_words(
                    remove_visual_markers(
                        main_script
                    )
                )

                result["script"] = (
                    main_script
                )

        except Exception as exc:

            st.warning(
                "La régénération n'a pas fonctionné. "
                f"Le script initial sera utilisé. {exc}"
            )

        mode = choose_content_mode(
            word_count
        )

        result["mode"] = mode

    # --------------------------------------------------------
    # 4. UN SHORT
    # --------------------------------------------------------

    if mode == "one_short":

        st.info(
            "Format choisi : 1 Short vertical"
        )

        short_script = generate_one_short(
            main_script,
            topic=topic,
        )

        st.write(
            "Adaptation du Short terminée : "
            f"{count_words(remove_visual_markers(short_script))} mots"
        )

        video = process_short(
            short_script,
            topic,
            short_number=1,
        )

        result["videos"].append(
            {
                "type": "Short",
                "path": video,
                "script": short_script,
            }
        )

        return result

    # --------------------------------------------------------
    # 5. DEUX SHORTS
    # --------------------------------------------------------

    if mode == "two_shorts":

        st.info(
            "Format choisi : 2 Shorts"
        )

        part1, part2 = (
            generate_two_shorts(
                main_script,
                topic,
            )
        )

        part1 = generate_one_short(
            part1,
            topic=topic,
        )

        part2 = generate_one_short(
            part2,
            topic=topic,
        )

        if part1:

            st.write(
                "Production du Short 1..."
            )

            video1 = process_short(
                part1,
                topic,
                short_number=1,
            )

            result["videos"].append(
                {
                    "type": "Short 1",
                    "path": video1,
                    "script": part1,
                }
            )

        if part2:

            st.write(
                "Production du Short 2..."
            )

            video2 = process_short(
                part2,
                topic,
                short_number=2,
            )

            result["videos"].append(
                {
                    "type": "Short 2",
                    "path": video2,
                    "script": part2,
                }
            )

        return result

    # --------------------------------------------------------
    # 6. VIDÉO LONGUE
    # --------------------------------------------------------

    if mode == "long":

        st.info(
            "Format choisi : vidéo longue 16:9"
        )

        long_video = process_long_video(
            main_script,
            topic,
        )

        result["videos"].append(
            {
                "type": "Vidéo longue",
                "path": long_video,
                "script": main_script,
            }
        )

        # ----------------------------------------------------
        # Teaser vertical.
        # ----------------------------------------------------

        try:

            teaser_script = generate_teaser(
                main_script,
                topic=topic,
            )

            if teaser_script:

                st.write(
                    "Création du teaser vertical..."
                )

                teaser_video = process_teaser(
                    teaser_script,
                    topic,
                )

                result["videos"].append(
                    {
                        "type": "Teaser",
                        "path": teaser_video,
                        "script": teaser_script,
                    }
                )

        except Exception as exc:

            st.warning(
                "Le teaser n'a pas pu être créé : "
                f"{exc}"
            )

        return result

    # --------------------------------------------------------
    # Sécurité.
    # --------------------------------------------------------

    raise RuntimeError(
        f"Mode de production inconnu : {mode}"
    )


# ============================================================
# AFFICHAGE D'UNE VIDÉO
# ============================================================

def show_video_result(
    video_info: Dict,
) -> None:

    path = video_info.get(
        "path"
    )

    if not path:

        st.error(
            "Fichier vidéo introuvable."
        )

        return

    path = Path(
        path
    )

    if not path.exists():

        st.error(
            f"Le fichier n'existe pas : {path}"
        )

        return

    video_type = video_info.get(
        "type",
        "Vidéo",
    )

    st.subheader(
        video_type
    )

    # Utilisation directe du chemin.
    # Cela évite de charger tout le MP4 en mémoire
    # dans la session Streamlit.
    st.video(
        str(path)
    )

    size_mb = (
        path.stat().st_size
        / (
            1024
            * 1024
        )
    )

    duration = get_video_duration(
        path
    )

    st.caption(
        f"Durée : {duration:.1f} s • "
        f"Taille : {size_mb:.1f} Mo"
    )

    # --------------------------------------------------------
    # Téléchargement.
    # --------------------------------------------------------

    try:

        video_bytes = path.read_bytes()

        st.download_button(
            label=(
                f"Télécharger {video_type}"
            ),
            data=video_bytes,
            file_name=path.name,
            mime="video/mp4",
            key=(
                "download_"
                + path.name.replace(
                    ".",
                    "_",
                )
            ),
        )

    except Exception as exc:

        st.warning(
            "Le bouton de téléchargement "
            f"n'a pas pu être préparé : {exc}"
        )

    # --------------------------------------------------------
    # Script correspondant.
    # --------------------------------------------------------

    script = video_info.get(
        "script"
    )

    if script:

        with st.expander(
            "Voir le script"
        ):

            st.write(
                remove_visual_markers(
                    script
                )
            )


# ============================================================
# INTERFACE STREAMLIT
# ============================================================

st.set_page_config(
    page_title=APP_TITLE,
    page_icon="🧠",
    layout="centered",
    initial_sidebar_state="collapsed",
)


# ============================================================
# CSS
# ============================================================

st.markdown(
    """
<style>

.main-title {
    font-size: 2.4rem;
    font-weight: 800;
    text-align: center;
    margin-bottom: 0.2rem;
}

.subtitle {
    text-align: center;
    opacity: 0.75;
    margin-bottom: 1.8rem;
}

.badge {
    display: inline-block;
    padding: 0.35rem 0.8rem;
    border-radius: 999px;
    font-size: 0.8rem;
    font-weight: 700;
    margin-bottom: 1rem;
}

.result-card {
    padding: 1rem;
    border-radius: 18px;
    border: 1px solid rgba(128,128,128,0.25);
    margin-bottom: 1rem;
}

</style>
""",
    unsafe_allow_html=True,
)


# ============================================================
# EN-TÊTE
# ============================================================

st.markdown(
    '<div class="main-title">🧠 Cerveau Curieux</div>',
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="subtitle">'
    "Psychologie, neurosciences et comportements humains "
    "racontés de manière surprenante."
    "</div>",
    unsafe_allow_html=True,
)


st.markdown(
    '<div class="badge">STUDIO VIDÉO IA</div>',
    unsafe_allow_html=True,
)


# ============================================================
# ÉTAT DES SERVICES
# ============================================================

with st.expander(
    "⚙️ Configuration",
    expanded=False,
):

    openrouter_ok = bool(
        OPENROUTER_API_KEY
    )

    pexels_ok = bool(
        PEXELS_API_KEY
    )

    ffmpeg_ok = bool(
        shutil.which(
            "ffmpeg"
        )
    )

    st.write(
        "OpenRouter : "
        + (
            "connecté"
            if openrouter_ok
            else "non configuré"
        )
    )

    st.write(
        "Pexels : "
        + (
            "connecté"
            if pexels_ok
            else "non configuré"
        )
    )

    st.write(
        "FFmpeg : "
        + (
            "disponible"
            if ffmpeg_ok
            else "introuvable"
        )
    )

    st.caption(
        "Sur Streamlit Community Cloud, "
        "FFmpeg doit être déclaré dans packages.txt."
    )


# ============================================================
# SAISIE DU SUJET
# ============================================================

topic = st.text_area(
    "Sujet de la vidéo",
    placeholder=(
        "Exemple : "
        "Pourquoi votre cerveau repense parfois "
        "à une vieille situation gênante juste avant de dormir ?"
    ),
    height=110,
    key="topic_input",
)


# ============================================================
# OPTIONS
# ============================================================

with st.expander(
    "Options",
    expanded=False,
):

    st.write(
        "Le format est choisi automatiquement "
        "en fonction de la longueur et du potentiel "
        "du script."
    )

    st.write(
        "• script court → Short"
    )

    st.write(
        "• script moyen → 2 Shorts"
    )

    st.write(
        "• script long → vidéo 16:9 + teaser"
    )

    st.write(
        "Les visuels sont recherchés à partir "
        "du contenu de la narration."
    )

    st.write(
        "Les sous-titres gardent une phrase visible "
        "et mettent en évidence le mot prononcé."
    )


# ============================================================
# BOUTON DE GÉNÉRATION
# ============================================================

generate_clicked = st.button(
    "🎬 Générer la vidéo",
    type="primary",
    use_container_width=True,
)


# ============================================================
# WORKFLOW
# ============================================================

if generate_clicked:

    if not topic.strip():

        st.error(
            "Veuillez entrer un sujet."
        )

        st.stop()

    if not OPENROUTER_API_KEY:

        st.error(
            "OPENROUTER_API_KEY est absente "
            "des secrets Streamlit."
        )

        st.stop()

    if not PEXELS_API_KEY:

        st.error(
            "PEXELS_API_KEY est absente "
            "des secrets Streamlit."
        )

        st.stop()

    if not shutil.which(
        "ffmpeg"
    ):

        st.error(
            "FFmpeg est introuvable. "
            "Vérifiez que le fichier packages.txt "
            "contient bien : ffmpeg"
        )

        st.stop()

    st.session_state[
        "last_generation"
    ] = None

    try:

        with st.status(
            "🎬 Production en cours...",
            expanded=True,
        ) as status:

            result = run_generation(
                topic
            )

            st.session_state[
                "last_generation"
            ] = result

            status.update(
                label=(
                    "✅ Production terminée"
                ),
                state="complete",
                expanded=False,
            )

    except Exception as exc:

        st.session_state[
            "last_generation"
        ] = None

        st.error(
            "❌ La génération a échoué."
        )

        st.exception(
            exc
        )


# ============================================================
# AFFICHAGE DES RÉSULTATS
# ============================================================

last_generation = st.session_state.get(
    "last_generation"
)

if last_generation:

    st.divider()

    st.header(
        "🎥 Résultats"
    )

    videos = last_generation.get(
        "videos",
        [],
    )

    if not videos:

        st.warning(
            "La génération est terminée, "
            "mais aucune vidéo n'a été produite."
        )

    else:

        for video_info in videos:

            st.markdown(
                '<div class="result-card">',
                unsafe_allow_html=True,
            )

            show_video_result(
                video_info
            )

            st.markdown(
                "</div>",
                unsafe_allow_html=True,
            )

    st.divider()

    st.caption(
        f"Chaîne : {CHANNEL_NAME}"
    )

    st.caption(
        "Objectif : raconter des phénomènes "
        "étonnants sur le cerveau et le comportement "
        "avec un ton amusant, accessible et scientifiquement "
        "rigoureux."
    )


# ============================================================
# FIN DE APP.PY
# ============================================================
