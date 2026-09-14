import streamlit as st
import os
import json
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from PIL import Image
import google.generativeai as genai

# ==========================================
# CONFIGURATION & CHEMINS
# ==========================================
FFMPEG_BIN = "ffmpeg"
SFX_FILE = Path("sfx_transition.mp3")      # Mets ton fichier bruitage ici
CLICK_SFX_FILE = Path("sfx_click.mp3")     # Mets ton fichier clic/pop final ici
MASCOT_FILE = Path("mascot.png")           # Ton image de mascotte (fond transparent)

# Crée une mascotte de secours si le fichier n'existe pas
if not MASCOT_FILE.exists():
    img = Image.new('RGBA', (200, 200), color=(0, 0, 0, 0))
    img.save(MASCOT_FILE)

# ==========================================
# 1. LE PROMPT SYSTÈME (CORRIGÉ POUR LE RYTHME)
# ==========================================
SYSTEM_PROMPT = """Tu es le réalisateur IA de 'Cerveau Curieux'. Ton but est de créer des scripts de vidéos ultra-dynamiques (min 45 secondes).

RÈGLES DE NARRATION (STYLE STREET/URBAIN) :
- Utilise un vocabulaire très jeune, "street" et urbain (ex : "une dinguerie", "frérot", "wesh l'équipe", "carrément", "ça rend ouf", "le cerveau il pète un câble", "bref").
- Le ton doit être ultra-familier, direct et dynamique. Tutoiement obligatoire.
- INTERDICTION STRICTE d'utiliser des insultes ou du vocabulaire vulgaire.
- Explique le sujet avec des exemples très concrets.

RÈGLES DE DÉCOUPAGE (TRÈS IMPORTANT) :
- DÉCOUPE LE SCRIPT : 1 seule phrase TRÈS COURTE par scène (maximum 3 secondes de lecture par scène).
- Une vidéo doit contenir au minimum 12 à 15 scènes pour un rythme visuel frénétique.
- Termine la dernière scène par un appel à l'action hyper positif ("Abonne-toi frérot", "Lâche ton like").

RÈGLES VISUELLES (`visual_query`) :
- Actions physiques et concrètes uniquement (2 à 4 mots en ANGLAIS).
- POUR LA DERNIÈRE SCÈNE (CTA) : Le visuel DOIT OBLIGATOIREMENT être ultra-positif (ex: "smiling person thumbs up", "happy cheering"). JAMAIS de geste négatif.

RÉPONSE ATTENDUE AU FORMAT JSON EXACTEMENT :
{
  "titre": "Ton titre",
  "hashtags": ["#shorts", "#tiktok"],
  "script_principal": [
    {"text": "Wesh l'équipe, t'as déjà repoussé un truc...", "visual_query": "person looking confused"}
  ]
}
"""

# ==========================================
# FONCTIONS UTILITAIRES
# ==========================================
def run_command(cmd, cwd=None):
    """Exécute une commande shell (ffmpeg, edge-tts)."""
    subprocess.run(cmd, cwd=cwd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def get_media_duration(file_path):
    """Récupère la durée d'un fichier média avec ffprobe."""
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(file_path)
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, text=True)
    return float(result.stdout.strip())

def generate_tts(text, output_path):
    """Génère la voix avec edge-tts."""
    cmd = ["edge-tts", "--voice", "fr-FR-HenriNeural", "--text", text, "--write-media", str(output_path)]
    run_command(cmd)

def generate_script(topic, api_key):
    """Fait appel à Google Gemini pour générer le script."""
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-flash', generation_config={"response_mime_type": "application/json"})
    prompt = f"{SYSTEM_PROMPT}\n\nSujet de la vidéo : {topic}"
    response = model.generate_content(prompt)
    return json.loads(response.text)

# ==========================================
# LE COEUR DU MOTEUR VIDÉO
# ==========================================
def generate_video_pipeline(ai_data, work_dir_path):
    """Génère la vidéo finale à partir des données de l'IA."""
    work_dir = Path(work_dir_path)
    script_scenes = ai_data.get("script_principal", [])
    total_scenes = len(script_scenes)
    
    audio_clips = []
    video_clips = []
    
    width, height = 1080, 1920
    fps = 30

    st.write("🎙️ Génération des voix et suppression des silences...")
    
    for idx, scene in enumerate(script_scenes):
        temp_audio = work_dir / f"temp_audio_{idx:03d}.mp3"
        final_audio = work_dir / f"audio_{idx:03d}.mp3"
        
        # 1. Génération de la voix
        generate_tts(scene["text"], temp_audio)
        
        # Choix du bruitage
        is_last_scene = (idx == total_scenes - 1)
        sfx_to_use = CLICK_SFX_FILE if (is_last_scene and CLICK_SFX_FILE.exists()) else (SFX_FILE if (idx > 0 and SFX_FILE.exists()) else None)

        # 2. APPLICATION DU FILTRE SILENCEREMOVE (Suppression du blanc de 1 seconde)
        if sfx_to_use:
            cmd_mix = [
                FFMPEG_BIN, "-y", "-i", str(temp_audio), "-i", str(sfx_to_use),
                "-filter_complex", "[0:a]silenceremove=stop_periods=1:stop_duration=0:stop_threshold=-35dB[voice];[1:a]volume=0.15[sfx];[voice][sfx]amix=inputs=2:duration=first[mix];[mix]volume=2.0[a]",
                "-map", "[a]", str(final_audio)
            ]
            run_command(cmd_mix, cwd=work_dir)
        else:
            cmd_trim = [
                FFMPEG_BIN, "-y", "-i", str(temp_audio),
                "-af", "silenceremove=stop_periods=1:stop_duration=0:stop_threshold=-35dB",
                str(final_audio)
            ]
            run_command(cmd_trim, cwd=work_dir)

        duration = get_media_duration(final_audio)
        scene["duration"] = duration
        audio_clips.append(final_audio)

    st.write("🎨 Création des visuels (Effets dynamiques + Mascotte)...")
    
    for idx, scene in enumerate(script_scenes):
        duration = scene["duration"]
        video_out = work_dir / f"video_{idx:03d}.mp4"
        
        # Effet flash au début de chaque scène (sauf la première)
        flash_effect = ""
        if idx > 0:
            flash_effect = ",colorchannelmixer=rr=2:gg=2:bb=2:aa=1"

        # 3. CRÉATION DU VISUEL DE SECOURS (Avec le Punch-Zoom accéléré à 0.0025)
        fallback = work_dir / f"fallback_{idx:03d}.png"
        Image.new("RGB", (width, height), color=(30, 30, 45)).save(fallback)
        frames = int(duration * fps)
        
        base_filter = f"[0:v]zoompan=z='min(zoom+0.0025,1.5)':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)',scale={width}:{height}{flash_effect}[bg]"
        
        cmd_vid = [
            FFMPEG_BIN, "-y", "-loop", "1", "-i", str(fallback), "-i", str(MASCOT_FILE.resolve()), 
            "-filter_complex", f"{base_filter};[bg][1:v]scale=300:-1[mascot];[bg][mascot]overlay=W-w-50:H-h-50[v]", 
            "-map", "[v]", "-t", str(duration), "-pix_fmt", "yuv420p", str(video_out)
        ]
        run_command(cmd_vid, cwd=work_dir)
        
        # Ajout des sous-titres basiques incrustés
        video_with_subs = work_dir / f"video_sub_{idx:03d}.mp4"
        safe_text = scene["text"].replace("'", "\\'").replace(":", "")
        cmd_sub = [
            FFMPEG_BIN, "-y", "-i", str(video_out),
            "-vf", f"drawtext=text='{safe_text}':fontcolor=white:fontsize=64:x=(w-text_w)/2:y=(h-text_h)/2+200:borderw=4:bordercolor=black",
            str(video_with_subs)
        ]
        run_command(cmd_sub, cwd=work_dir)
        
        video_clips.append(video_with_subs)

    st.write("🎞️ Assemblage final de la vidéo...")
    
    # Création du fichier concat
    concat_file = work_dir / "concat_list.txt"
    with open(concat_file, "w") as f:
        for idx in range(total_scenes):
            f.write(f"file 'video_sub_{idx:03d}.mp4'\n")
            
    concat_video = work_dir / "merged_video.mp4"
    cmd_concat_vid = [FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(concat_video)]
    run_command(cmd_concat_vid, cwd=work_dir)
    
    # Concaténation des audios
    concat_audio_file = work_dir / "concat_audio.txt"
    with open(concat_audio_file, "w") as f:
        for clip in audio_clips:
            f.write(f"file '{clip.name}'\n")
            
    concat_audio = work_dir / "merged_audio.mp3"
    cmd_concat_aud = [FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_audio_file), "-c", "copy", str(concat_audio)]
    run_command(cmd_concat_aud, cwd=work_dir)

    # Mixage final
    final_output = work_dir / "FINAL_SHORTS.mp4"
    cmd_final = [
        FFMPEG_BIN, "-y", "-i", str(concat_video), "-i", str(concat_audio),
        "-c:v", "copy", "-c:a", "aac", "-map", "0:v:0", "-map", "1:a:0", "-shortest", str(final_output)
    ]
    run_command(cmd_final, cwd=work_dir)
    
    return final_output

# ==========================================
# INTERFACE STREAMLIT
# ==========================================
def main():
    st.set_page_config(page_title="Studio Shorts IA", page_icon="🎬", layout="centered")
    
    st.title("🎬 Studio Shorts IA (Version Ultra-Dynamique)")
    st.markdown("Génère tes vidéos TikTok/Shorts avec rythme frénétique et rétention maximale.")

    api_key = st.text_input("Clé API Google Gemini :", type="password")
    topic = st.text_area("Quel est le sujet de ta vidéo ?", "Pourquoi on procrastine toujours ?")
    
    if st.button("🚀 Générer la vidéo", use_container_width=True):
        if not api_key:
            st.error("Veuillez entrer une clé API Gemini.")
            return
            
        with st.spinner("🧠 Rédaction du script par l'IA..."):
            try:
                ai_data = generate_script(topic, api_key)
                title = ai_data.get("titre", "Vidéo IA")
            except Exception as e:
                st.error(f"Erreur de génération du script : {e}")
                return
                
        # Dossier de travail temporaire
        with tempfile.TemporaryDirectory() as tmpdirname:
            with st.spinner("🎬 Production en cours (Voix, Visuels, Montage)..."):
                try:
                    final_video_path = generate_video_pipeline(ai_data, tmpdirname)
                    
                    st.success("✅ Vidéo terminée avec succès !")
                    
                    # ONGLET 1 : LA VIDÉO
                    video_tab, info_tab = st.tabs(["🎥 Ta Vidéo", "ℹ️ Informations & Script"])
                    
                    with video_tab:
                        with open(final_video_path, "rb") as file:
                            st.video(file.read())
                        
                        with open(final_video_path, "rb") as file:
                            st.download_button(
                                label="💾 Télécharger le Short",
                                data=file,
                                file_name="Mon_Short_IA.mp4",
                                mime="video/mp4",
                                use_container_width=True
                            )
                            
                    # ONGLET 2 : LE NOUVEAU MENU SCRIPT POUR CLAUDE
                    with info_tab:
                        st.info(f"**Titre suggéré :** {title}")
                        st.write(f"**Hashtags :** " + " ".join(ai_data.get('hashtags', [])))
                        st.write("*(Copie ces éléments pour ta description TikTok/YouTube)*")
                        
                        st.markdown("---")
                        # 4. INTÉGRATION DE L'AFFICHEUR DE SCRIPT
                        with st.expander("📜 Voir le script complet (pour l'audit de Claude)"):
                            script_complet = ""
                            for idx, scene in enumerate(ai_data.get("script_principal", [])):
                                script_complet += f"**Scène {idx + 1}** : {scene.get('text', '')}\n\n"
                            st.markdown(script_complet)
                            st.code(script_complet, language="markdown") # Permet de copier d'un clic !
                            
                except Exception as e:
                    st.error(f"Erreur pendant le montage : {e}")

if __name__ == "__main__":
    main()

