# media.py

import subprocess
import os
import uuid

# --- Fonctions de remplacement pour les API d'IA ---
# Remplacez ces fonctions par de vrais appels aux API de Suno, Stable Diffusion, etc.

def generate_audio_from_ia(suno_key: str, prompt_text: str) -> str:
    """
    Simule la génération d'un fichier audio à partir d'un prompt.
    REMPLACER par un appel à l'API Suno ou autre.
    """
    print(f"🎵 Simulation de la génération audio pour le prompt : '{prompt_text}'")
    # Pour le test, copiez un fichier audio local
    # Dans un vrai scénario, vous téléchargeriez le résultat de l'API ici.
    audio_path = "sample_audio.mp3"
    if not os.path.exists(audio_path):
        raise FileNotFoundError("Le fichier 'sample_audio.mp3' est nécessaire pour la simulation.")
    
    temp_audio_path = f"/tmp/{uuid.uuid4()}.mp3"
    subprocess.run(['cp', audio_path, temp_audio_path], check=True)
    print(f"🎧 Fichier audio simulé créé à : {temp_audio_path}")
    return temp_audio_path

def generate_image_from_ia(image_key: str, prompt_text: str) -> str:
    """
    Simule la génération d'une image de couverture.
    REMPLACER par un appel à l'API de génération d'images.
    """
    print(f"🎨 Simulation de la génération d'image pour le prompt : '{prompt_text}'")
    # Pour le test, copiez une image locale
    image_path = "sample_image.png"
    if not os.path.exists(image_path):
        raise FileNotFoundError("Le fichier 'sample_image.png' est nécessaire pour la simulation.")

    temp_image_path = f"/tmp/{uuid.uuid4()}.png"
    subprocess.run(['cp', image_path, temp_image_path], check=True)
    print(f"🖼️ Fichier image simulé créé à : {temp_image_path}")
    return temp_image_path

# --- Fonction de montage vidéo ---

def assemble_video(image_path: str, audio_path: str) -> str:
    """
    Assemble une image et un audio en une vidéo MP4 en utilisant FFmpeg.
    """
    output_path = f"/tmp/{uuid.uuid4()}.mp4"
    print(f"🎬 Début de l'assemblage vidéo -> {output_path}")

    # Commande FFmpeg pour créer une vidéo à partir d'une image et d'un audio
    # -loop 1: Fait boucler l'image
    # -i image.png -i audio.mp3: Spécifie les fichiers d'entrée
    # -c:v libx264: Encodeur vidéo
    # -tune stillimage: Optimise pour une image fixe
    # -c:a aac: Encodeur audio
    # -b:a 192k: Bitrate audio
    # -pix_fmt yuv420p: Format de pixel pour une compatibilité maximale
    # -shortest: La vidéo s'arrête en même temps que le flux le plus court (l'audio)
    command = [
        'ffmpeg',
        '-loop', '1',
        '-i', image_path,
        '-i', audio_path,
        '-c:v', 'libx264',
        '-tune', 'stillimage',
        '-c:a', 'aac',
        '-b:a', '192k',
        '-pix_fmt', 'yuv420p',
        '-shortest',
        output_path
    ]

    try:
        # L'utilisation de subprocess.run est une manière moderne et flexible d'exécuter des commandes. [6, 8]
        subprocess.run(command, check=True, capture_output=True, text=True)
        print("✅ Vidéo assemblée avec succès.")
        return output_path
    except subprocess.CalledProcessError as e:
        print(f"❌ Erreur FFmpeg: {e.stderr}")
        raise IOError("La création de la vidéo a échoué.") from e