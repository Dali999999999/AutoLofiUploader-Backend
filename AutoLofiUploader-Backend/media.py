# media.py (version finale épurée)

import os
import uuid
import requests

# --- Constantes pour les API ---
SUNO_API_URL = "https://apibox.erweima.ai/api/v1/generate"
HUGGING_FACE_API_URL = "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-dev"

def _call_suno_api(api_key: str, payload: dict) -> str:
    """Fonction interne pour appeler l'API Suno et gérer la réponse."""
    print(f"🎵 Envoi de la requête à Suno avec le payload : {payload}")
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        response = requests.post(SUNO_API_URL, headers=headers, json=payload, timeout=30)
        print(f"   - Réponse BRUTE de Suno reçue (Statut {response.status_code}): {response.text}")
        if response.status_code != 200:
            raise ValueError(f"Suno a répondu avec un code d'erreur HTTP {response.status_code}.")
        data = response.json()
        if data.get("code") != 200:
             raise ValueError(f"Suno a renvoyé une erreur : {data.get('msg')}")
        task_data = data.get("data")
        if not isinstance(task_data, dict):
            raise ValueError("La clé 'data' de la réponse Suno n'est pas un dictionnaire valide.")
        task_id = task_data.get("taskId")
        if not task_id:
            raise ValueError("Le dictionnaire 'data' ne contient pas de clé 'taskId'.")
        print(f"✅ Tâche Suno démarrée avec succès ! ID : {task_id}")
        return task_id
    except requests.exceptions.RequestException as e:
        raise IOError(f"Erreur réseau lors de l'appel à Suno : {e}") from e
    except (ValueError, KeyError, IndexError) as e:
        raise ValueError(f"Structure de réponse de Suno inattendue. Détails : {e}") from e

def start_suno_generation(api_key: str, description: str, callback_url: str) -> str:
    """
    Génère une chanson complète (musique + voix) à partir d'une description.
    """
    print("   - Lancement de la génération de musique automatique.")
    payload = {
        "prompt": description,
        "instrumental": False,
        "customMode": False,
        "model": "V3_5",
        "callBackUrl": callback_url
    }
    return _call_suno_api(api_key, payload)

def download_image_from_ia(api_key: str, prompt_text: str) -> str:
    """
    Appelle l'API d'image et sauvegarde le résultat directement sur disque.
    """
    print(f"🎨 Lancement de la génération d'image pour le prompt : '{prompt_text[:70]}...'")
    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {"inputs": prompt_text}
    temp_image_path = f"/tmp/{uuid.uuid4()}.jpg"
    try:
        with requests.post(HUGGING_FACE_API_URL, headers=headers, json=payload, timeout=120, stream=True) as response:
            response.raise_for_status()
            with open(temp_image_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
        print(f"🖼️ Image téléchargée avec succès à : {temp_image_path}")
        return temp_image_path
    except requests.exceptions.RequestException as e:
        raise IOError(f"Le téléchargement de l'image a échoué. Détails: {e}") from e
