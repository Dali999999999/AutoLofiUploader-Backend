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

def start_suno_audio_generation(api_key: str, prompt: str, callback_url: str) -> str:
    """
    Lance une tâche de génération audio sur l'API Suno et retourne un ID de tâche.
    La génération est asynchrone et notifiera le serveur via le callback_url.
    """
    print(f"🎵 Lancement de la tâche Suno pour le prompt : '{prompt[:70]}...'")
    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {
        "prompt": prompt,
        "instrumental": True,
        "callBackUrl": callback_url
    }
    
    try:
        response = requests.post(SUNO_API_URL, headers=headers, json=payload, timeout=30)
        response.raise_for_status()  # Lève une exception pour les codes d'erreur HTTP (4xx ou 5xx)
        
        data = response.json()
        tasks = data.get("data", [])
        if not tasks or not tasks[0].get("id"):
            raise ValueError("La réponse de l'API Suno ne contient pas d'ID de tâche valide.")
        
        task_id = tasks[0]["id"]
        print(f"   - Tâche Suno démarrée avec succès. ID : {task_id}")
        return task_id

    except requests.exceptions.RequestException as e:
        print(f"❌ Erreur lors de l'appel à l'API Suno : {e}")
        raise IOError("Impossible de démarrer la génération audio sur Suno.") from e

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
