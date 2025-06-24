# app.py (version asynchrone avec callback)

from flask import Flask, request, jsonify
import os
import services
import media
import uuid
import requests
from google.auth.exceptions import RefreshError
import gspread

app = Flask(__name__)

# --- Stockage temporaire en mémoire ---
# Ce dictionnaire stockera les informations d'une tâche entre l'appel initial
# et le callback de Suno. La clé est le task_id de Suno.
TASK_STORE = {}

@app.route('/run', methods=['POST'])
def run_process():
    """
    Endpoint initial : lit le prompt, lance la génération audio et répond immédiatement.
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "Requête JSON invalide ou vide."}), 400

    required_keys = ["access_token", "sheet_id", "prompt_id", "suno_key", "image_key"]
    if not all(key in data for key in required_keys):
        return jsonify({"error": f"Paramètres manquants. Requis : {required_keys}"}), 400

    try:
        # 1. Extraire les données de la requête
        access_token = data['access_token']
        sheet_id = data['sheet_id']
        prompt_id = data['prompt_id']
        suno_key = data['suno_key']
        image_key = data['image_key']

        # 2. Lire les données du prompt depuis Google Sheet
        print(f"📄 Lecture du prompt '{prompt_id}' depuis le Google Sheet '{sheet_id}'.")
        sheets_client = services.get_sheets_client(access_token)
        prompt_data = services.get_prompt_from_sheet(sheets_client, sheet_id, prompt_id)

        if len(prompt_data) < 6:
            raise IndexError("Structure de ligne incorrecte. 6 colonnes attendues (A-F).")

        # 3. Préparer les informations pour la tâche
        task_context = {
            "prompt_id": prompt_id,
            "sheet_id": sheet_id,
            "access_token": access_token,
            "image_key": image_key,
            "music_prompt": prompt_data[1],
            "image_prompt": prompt_data[2],
            "video_title": prompt_data[3],
            "video_description": prompt_data[4],
            "video_tags": [tag.strip() for tag in prompt_data[5].split(',')]
        }

        # 4. Construire l'URL du callback
        # request.url_root donne la base de l'URL (ex: https://myapp.onrender.com/)
        callback_url = request.url_root + "suno_callback"
        print(f"   - URL de callback configurée : {callback_url}")

        # 5. Lancer la génération audio asynchrone
        task_id = media.start_suno_audio_generation(suno_key, task_context["music_prompt"], callback_url)
        
        # 6. Stocker le contexte de la tâche en mémoire
        TASK_STORE[task_id] = task_context
        print(f"   - Contexte de la tâche '{task_id}' stocké en mémoire.")

        # 7. Répondre au client que la tâche a bien été lancée
        return jsonify({
            "success": True,
            "status": "pending",
            "message": "La génération de la vidéo a été lancée. Le serveur traitera la suite en arrière-plan.",
            "task_id": task_id
        }), 202  # 202 Accepted: indique que la requête est acceptée mais pas encore terminée.

    except (RefreshError, gspread.exceptions.APIError) as e:
        return jsonify({"error": "Token Google expiré ou invalide.", "details": str(e)}), 401
    except (ValueError, IndexError, IOError) as e:
        return jsonify({"error": "Erreur de données ou de configuration.", "details": str(e)}), 400
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": "Une erreur interne est survenue.", "details": str(e)}), 500


@app.route('/suno_callback', methods=['POST'])
def suno_callback():
    """
    Endpoint de callback appelé par Suno, maintenant plus robuste pour extraire les données.
    """
    print("\n🔔 Callback reçu de Suno !")
    callback_data = request.get_json() or {}
    print(f"   - Corps COMPLET du callback reçu: {callback_data}")
    temp_files = []

    try:
        # --- DÉBUT DE LA CORRECTION FINALE DU CALLBACK ---
        
        # 1. Valider la structure générale du callback
        if callback_data.get("code") != 200 or not isinstance(callback_data.get("data"), dict):
            raise ValueError(f"Callback Suno en erreur ou structure de 'data' invalide.")

        # 2. Naviguer prudemment dans le dictionnaire
        item_list = callback_data["data"].get("data")
        if not isinstance(item_list, list) or not item_list:
            raise ValueError("La clé 'data.data' est manquante ou n'est pas une liste valide.")
        
        item = item_list[0]
        
        # 3. Extraire l'ID de la tâche et l'URL de l'audio
        # L'ID de la tâche originale est dans "task_id", l'URL dans "audio_url"
        task_id = item.get("task_id")
        audio_url = item.get("audio_url")

        if not task_id or not audio_url:
            raise ValueError("Clés 'task_id' ou 'audio_url' manquantes dans le premier objet du callback.")

        # --- FIN DE LA CORRECTION FINALE DU CALLBACK ---

        print(f"   - Récupération du contexte pour la tâche : {task_id}")
        context = TASK_STORE.pop(task_id, None)
        if not context:
            raise ValueError(f"Tâche inconnue ou déjà traitée : {task_id}")

        # --- Le reste du processus est déclenché ici ---
        
        # 3. Télécharger l'audio généré
        print(f"   - Téléchargement de l'audio depuis : {audio_url}")
        resp = requests.get(audio_url, timeout=60)
        resp.raise_for_status()
        audio_path = f"/tmp/{task_id}.mp3"
        with open(audio_path, "wb") as f:
            f.write(resp.content)
        temp_files.append(audio_path)
        print(f"   - Audio sauvegardé à : {audio_path}")

        # 4. Générer l'image
        image_path = media.generate_image_from_ia(context['image_key'], context['image_prompt'])
        temp_files.append(image_path)
        
        # 5. Assembler la vidéo
        video_path = media.assemble_video(image_path, audio_path)
        temp_files.append(video_path)

        # 6. Uploader sur YouTube
        video_url = services.upload_to_youtube(
            context['access_token'], video_path, context['video_title'],
            context['video_description'], context['video_tags']
        )

        # 7. Mettre à jour le Google Sheet
        sheets_client = services.get_sheets_client(context['access_token'])
        services.update_video_url_in_sheet(sheets_client, context['sheet_id'], context['prompt_id'], video_url)
        
        print(f"✅ Processus complet terminé avec succès pour la tâche {task_id} !")
        return jsonify({"status": "callback processed successfully"}), 200

    except (ValueError, IndexError, IOError, requests.exceptions.RequestException) as e:
        print(f"❌ Erreur lors du traitement du callback : {e}")
        # Optionnel : Mettre à jour le sheet avec un statut "Erreur"
        return jsonify({"error": "Erreur lors du traitement du callback.", "details": str(e)}), 400
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": "Erreur interne pendant le callback.", "details": str(e)}), 500
    finally:
        # 8. Nettoyer les fichiers temporaires
        print("🧹 Nettoyage des fichiers temporaires du callback...")
        for file_path in temp_files:
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    print(f"  - Supprimé : {file_path}")
                except OSError as e:
                    print(f"  - Erreur lors de la suppression de {file_path}: {e}")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=False, host='0.0.0.0', port=port)
