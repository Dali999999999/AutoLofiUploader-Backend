# media.py

import subprocess
import os
import uuid
import requests
from io import BytesIO
from PIL import Image

# --- Constantes pour les API ---
SUNO_API_URL = "https://apibox.erweima.ai/api/v1/generate"
HUGGING_FACE_API_URL = "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-dev"

# --- Fonctions de génération de média ---

# Dans media.py

# Dans media.py

def start_suno_audio_generation(api_key: str, prompt: str, callback_url: str) -> str:
    """
    Lance une tâche de génération audio sur l'API Suno de manière robuste, en utilisant
    la structure de réponse découverte.
    """
    print(f"🎵 Lancement de la tâche Suno pour le prompt : '{prompt[:70]}...'")
    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {
        "prompt": prompt,
        "instrumental": True,
        "customMode": False,
        "model": "V3_5",
        "callBackUrl": callback_url
    }
    
    try:
        response = requests.post(SUNO_API_URL, headers=headers, json=payload, timeout=30)
        
        print(f"   - Réponse BRUTE de Suno reçue (Statut {response.status_code}): {response.text}")

        if response.status_code != 200:
            raise ValueError(f"Suno a répondu avec un code d'erreur {response.status_code}.")
        
        data = response.json()
        
        # --- DÉBUT DE LA CORRECTION FINALE ---
        # Le chemin exact pour trouver l'ID est data -> data -> taskId
        
        # 1. Vérifier que 'data' est bien un dictionnaire
        task_data = data.get("data")
        if not isinstance(task_data, dict):
            raise ValueError("La clé 'data' de la réponse Suno n'est pas un dictionnaire valide.")
        
        # 2. Extraire 'taskId' de ce dictionnaire
        task_id = task_data.get("taskId")
        if not task_id:
            raise ValueError("Le dictionnaire 'data' ne contient pas de clé 'taskId'.")
        # --- FIN DE LA CORRECTION FINALE ---
        
        print(f"✅ Tâche Suno démarrée avec succès ! ID de la tâche : {task_id}")
        return task_id

    except requests.exceptions.RequestException as e:
        print(f"❌ Erreur réseau lors de l'appel à Suno : {e}")
        raise IOError("Impossible de démarrer la génération audio sur Suno.") from e
    except (ValueError, KeyError, IndexError) as e:
        print(f"❌ Erreur lors du traitement de la réponse de Suno : {e}")
        raise ValueError(f"Structure de réponse de Suno inattendue. Détails : {e}") from e

def generate_image_from_ia(api_key: str, prompt_text: str) -> str:
    """
    Génère une image via l'API Hugging Face, la redimensionne et la sauvegarde.
    """
    print(f"🎨 Génération de l'image via Hugging Face pour le prompt : '{prompt_text[:70]}...'")
    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {"inputs": prompt_text}
    
    temp_image_path = f"/tmp/{uuid.uuid4()}.jpg"

    try:
        response = requests.post(HUGGING_FACE_API_URL, headers=headers, json=payload, timeout=120)
        response.raise_for_status()

        if not response.headers.get("content-type", "").startswith("image/"):
            raise ValueError(f"La réponse de l'API d'image n'est pas une image. Réponse : {response.text[:200]}")

        # Ouvrir, redimensionner et sauvegarder l'image
        img = Image.open(BytesIO(response.content))
        img_resized = img.resize((1280, 720), Image.LANCZOS)
        img_resized.save(temp_image_path, format="JPEG", quality=95)
        
        print(f"🖼️ Image générée et sauvegardée à : {temp_image_path}")
        return temp_image_path

    except requests.exceptions.RequestException as e:
        print(f"❌ Erreur lors de l'appel à l'API d'image : {e}")
        raise IOError("La génération de l'image a échoué.") from e

def assemble_video(image_path: str, audio_path: str) -> str:
    """Assemble une image et un audio en une vidéo MP4 en utilisant FFmpeg."""
    output_path = f"/tmp/{uuid.uuid4()}.mp4"
    print(f"🎬 Début de l'assemblage vidéo -> {output_path}")

    command = [
        'ffmpeg', '-loop', '1', '-i', image_path, '-i', audio_path,
        '-c:v', 'libx264', '-tune', 'stillimage', '-c:a', 'aac', '-b:a', '192k',
        '-pix_fmt', 'yuv420p', '-shortest', output_path
    ]

    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        print("✅ Vidéo assemblée avec succès.")
        return output_path
    except subprocess.CalledProcessError as e:
        print(f"❌ Erreur FFmpeg : {e.stderr}")
        raise IOError("La création de la vidéo avec FFmpeg a échoué.") from e
