# app.py (version finale avec les deux architectures V1 et V2)

import os
import uuid
import json
import zipfile
import requests
import traceback

from flask import Flask, request, jsonify, send_file, g
from google.auth.exceptions import RefreshError
import gspread

import services
import media

app = Flask(__name__)

# --- Stockages en mémoire, un pour chaque architecture ---
TASK_STORE = {}     # Pour l'architecture V1
TASK_STORE_V2 = {}  # Pour la NOUVELLE architecture V2

# ==============================================================================
# === V1 - ARCHITECTURE ORIGINALE (Complète, avec traitement côté serveur) =====
# ==============================================================================

# Helper pour le nettoyage après une requête (utilisé par /status/ et /v2/get_audio/)
@app.after_request
def call_after_request_callbacks(response):
    for callback in getattr(g, 'after_request_callbacks', ()):
        response = callback(response)
    return response

@app.route('/run', methods=['POST'])
def run_process():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Requête JSON invalide"}), 400
    try:
        access_token = data['access_token']
        sheet_id = data['sheet_id']
        prompt_id = data['prompt_id']
        suno_key = data['suno_key']
        image_key = data['image_key']

        print(f"📄 [V1] Lecture du prompt '{prompt_id}'...")
        sheets_client = services.get_sheets_client(access_token)
        prompt_data = services.get_prompt_from_sheet(sheets_client, sheet_id, prompt_id)

        if len(prompt_data) < 11:
            raise IndexError("Structure de ligne incorrecte. 11 colonnes (A-K) sont attendues pour la V1.")

        task_context = {
            "prompt_id": prompt_id, "sheet_id": sheet_id, "access_token": access_token,
            "image_key": image_key, "music_description": prompt_data[1], "image_prompt": prompt_data[2],
            "video_title": prompt_data[3], "video_description": prompt_data[4],
            "video_tags": [tag.strip() for tag in prompt_data[5].split(',')],
            "visibility": prompt_data[10]
        }

        callback_url = request.url_root + "suno_callback"
        task_id = media.start_suno_generation(suno_key, task_context["music_description"], callback_url)
        
        TASK_STORE[task_id] = {"status": "pending", "context": task_context}
        print(f"   - [V1] Tâche '{task_id}' initialisée avec le statut 'pending'.")
        
        return jsonify({"success": True, "status": "pending", "task_id": task_id}), 202

    except (ValueError, IndexError, IOError) as e:
        return jsonify({"error": "Erreur de données ou de configuration", "details": str(e)}), 400
    except (RefreshError, gspread.exceptions.APIError) as e:
        return jsonify({"error": "Token Google invalide ou expiré", "details": str(e)}), 401
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": "Erreur interne sur le serveur", "details": str(e)}), 500


@app.route('/suno_callback', methods=['POST'])
def suno_callback():
    print("\n🔔 [V1] Callback reçu de Suno !")
    callback_data = request.get_json() or {}
    task_id = None
    try:
        main_data_obj = callback_data.get("data", {})
        task_id = main_data_obj.get("task_id")

        if not task_id or task_id not in TASK_STORE:
            return jsonify({"status": "ignored, unknown task"}), 200
        if main_data_obj.get("callbackType") != 'complete':
            print(f"   - [V1] Callback intermédiaire pour la tâche {task_id} ignoré.")
            return jsonify({"status": "intermediate callback ignored"}), 200

        context = TASK_STORE[task_id]["context"]
        print(f"   - [V1] Traitement du callback final pour la tâche {task_id}.")

        item = main_data_obj.get("data", [{}])[0]
        audio_url = item.get("audio_url") or item.get("stream_audio_url")
        if not audio_url: raise ValueError("URL audio manquante dans le callback.")

        print("   - [V1] Téléchargement de l'audio...")
        resp = requests.get(audio_url, timeout=180)
        resp.raise_for_status()
        audio_path = f"/tmp/{task_id}_audio.mp3"
        with open(audio_path, "wb") as f: f.write(resp.content)
        
        print("   - [V1] Téléchargement de l'image...")
        image_path = media.download_image_from_ia(context['image_key'], context['image_prompt'])

        TASK_STORE[task_id] = {
            "status": "ready_for_download",
            "files": {"audio": audio_path, "image": image_path},
            "metadata": {
                "video_title": context["video_title"], "video_description": context["video_description"],
                "video_tags": context["video_tags"], "access_token": context["access_token"],
                "sheet_id": context["sheet_id"], "prompt_id": context["prompt_id"],
                "visibility": context["visibility"]
            }
        }
        print(f"✅ [V1] Tâche '{task_id}' mise à jour au statut 'ready_for_download'.")
        return jsonify({"status": "callback processed successfully"}), 200

    except Exception as e:
        if task_id and task_id in TASK_STORE: TASK_STORE[task_id] = {"status": "error", "message": str(e)}
        traceback.print_exc()
        return jsonify({"error": "Erreur lors du traitement du callback V1."}), 400


@app.route('/status/<task_id>', methods=['GET'])
def get_task_status(task_id):
    print(f"   - [V1] Requête de statut pour la tâche : {task_id}")
    task = TASK_STORE.get(task_id)

    if not task: return jsonify({"status": "not_found"}), 404
    status = task.get("status", "unknown")
    if status == "pending": return jsonify({"status": "pending"}), 202
    if status == "error":
        error_message = task.get("message", "Erreur inconnue.")
        TASK_STORE.pop(task_id, None)
        return jsonify({"status": "error", "message": error_message}), 500
    if status == "ready_for_download":
        print(f"   - [V1] La tâche {task_id} est prête. Création du ZIP...")
        try:
            audio_path = task["files"]["audio"]
            image_path = task["files"]["image"]
            zip_path = f"/tmp/{task_id}_bundle.zip"
            
            with zipfile.ZipFile(zip_path, 'w') as zipf:
                zipf.write(audio_path, arcname='audio.mp3')
                zipf.write(image_path, arcname='image.jpg')
                zipf.writestr('metadata.json', json.dumps(task["metadata"]))
            
            response = send_file(zip_path, as_attachment=True, download_name='media_bundle.zip')
            
            @g.after_request
            def cleanup(resp):
                print(f"🧹 [V1] Nettoyage des fichiers pour la tâche {task_id}...")
                if os.path.exists(zip_path): os.remove(zip_path)
                if os.path.exists(audio_path): os.remove(audio_path)
                if os.path.exists(image_path): os.remove(image_path)
                TASK_STORE.pop(task_id, None)
                return resp
            return response
        except Exception as e:
            traceback.print_exc()
            return jsonify({"status": "error", "message": f"Erreur lors de la création du ZIP : {e}"}), 500
    return jsonify({"status": "unknown"}), 500


@app.route('/publish', methods=['POST'])
def publish_video():
    temp_files = []
    try:
        if 'video_file' not in request.files or 'metadata_str' not in request.form:
            return jsonify({"error": "Requête invalide."}), 400

        video_file = request.files['video_file']
        metadata = json.loads(request.form['metadata_str'])

        video_path = f"/tmp/{uuid.uuid4()}_{video_file.filename}"
        video_file.save(video_path)
        temp_files.append(video_path)
        print(f"📹 [V1] Vidéo reçue du client et sauvegardée à : {video_path}")

        video_url = services.upload_to_youtube(
            metadata['access_token'], video_path,
            metadata['video_title'], metadata['video_description'], metadata['video_tags'],
            metadata.get('visibility', 'private')
        )

        sheets_client = services.get_sheets_client(metadata['access_token'])
        services.update_video_url_in_sheet(sheets_client, metadata['sheet_id'], metadata['prompt_id'], video_url)
        
        print("✅ [V1] Publication terminée avec succès !")
        return jsonify({"success": True, "video_url": video_url}), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": "Erreur lors de la publication.", "details": str(e)}), 500
    finally:
        print("🧹 [V1] Nettoyage du fichier vidéo temporaire...")
        for file_path in temp_files:
            if os.path.exists(file_path):
                os.remove(file_path)

# ==============================================================================
# === V2 - NOUVELLE ARCHITECTURE MINIMALISTE (AUDIO SEULEMENT) =================
# ==============================================================================

@app.route('/v2/generate_audio', methods=['POST'])
def v2_generate_audio():
    """V2 Endpoint: Lance UNIQUEMENT la génération audio."""
    data = request.get_json()
    if not data or not all(k in data for k in ['suno_key', 'music_description', 'task_id']):
        return jsonify({"error": "Paramètres manquants : 'suno_key', 'music_description', 'task_id' sont requis."}), 400
    
    try:
        suno_key = data['suno_key']
        music_description = data['music_description']
        task_id = data['task_id']

        callback_url = request.url_root + "v2/suno_callback"
        suno_task_id = media.start_suno_generation(suno_key, music_description, callback_url)
        
        TASK_STORE_V2[task_id] = {"status": "pending", "suno_task_id": suno_task_id}
        print(f"   - [V2] Tâche '{task_id}' initialisée avec le statut 'pending'.")

        return jsonify({"success": True, "status": "pending", "task_id": task_id}), 202

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": "Erreur interne lors du lancement de la tâche audio.", "details": str(e)}), 500

@app.route('/v2/suno_callback', methods=['POST'])
def v2_suno_callback():
    """V2 Callback: Reçoit la notification de Suno et prépare l'audio."""
    print("\n🔔 [V2] Callback reçu de Suno !")
    callback_data = request.get_json() or {}
    suno_task_id = None
    
    try:
        main_data_obj = callback_data.get("data", {})
        if main_data_obj.get("callbackType") != 'complete':
            return jsonify({"status": "intermediate callback ignored"}), 200

        suno_task_id = main_data_obj.get("task_id")
        if not suno_task_id:
            raise ValueError("ID de tâche Suno manquant dans le callback.")

        client_task_id = next((key for key, value in TASK_STORE_V2.items() if value.get("suno_task_id") == suno_task_id), None)
        if not client_task_id:
            return jsonify({"status": "ignored, unknown suno task"}), 200
            
        print(f"   - [V2] Traitement du callback final pour la tâche client : {client_task_id}.")
        item = main_data_obj.get("data", [{}])[0]
        audio_url = item.get("audio_url") or item.get("stream_audio_url")
        if not audio_url:
            raise ValueError("URL audio manquante dans le callback final.")

        print("   - [V2] Téléchargement de l'audio...")
        resp = requests.get(audio_url, timeout=180)
        resp.raise_for_status()
        audio_path = f"/tmp/{client_task_id}_audio.mp3"
        with open(audio_path, "wb") as f: f.write(resp.content)

        TASK_STORE_V2[client_task_id] = {"status": "ready", "audio_path": audio_path}
        print(f"✅ [V2] Tâche '{client_task_id}' mise à jour au statut 'ready'.")
        return jsonify({"status": "callback processed"}), 200

    except Exception as e:
        if suno_task_id:
            client_task_id = next((key for key, value in TASK_STORE_V2.items() if value.get("suno_task_id") == suno_task_id), None)
            if client_task_id: TASK_STORE_V2[client_task_id] = {"status": "error", "message": str(e)}
        traceback.print_exc()
        return jsonify({"error": "Erreur lors du traitement du callback V2."}), 400

# Dans app.py

@app.route('/v2/get_audio/<task_id>', methods=['GET'])
def v2_get_audio(task_id):
    """
    V2 Endpoint de Polling: Le client appelle ici pour récupérer son fichier audio.
    """
    print(f"   - [V2] Requête de statut/audio pour la tâche : {task_id}")
    task = TASK_STORE_V2.get(task_id)

    if not task:
        return jsonify({"status": "not_found"}), 404

    status = task.get("status", "unknown")

    if status == "pending":
        return jsonify({"status": "pending"}), 202
    
    if status == "error":
        error_message = task.get("message", "Erreur inconnue.")
        TASK_STORE_V2.pop(task_id, None)
        return jsonify({"status": "error", "message": error_message}), 500

    if status == "ready":
        audio_path = task.get("audio_path")
        if not audio_path or not os.path.exists(audio_path):
             return jsonify({"status": "error", "message": "Fichier audio prêt mais introuvable sur le serveur."}), 500

        print(f"   - [V2] La tâche {task_id} est prête. Envoi du fichier audio.")
        
        try:
            # On prépare la réponse AVANT de faire le nettoyage
            response = send_file(audio_path, as_attachment=True, download_name='generated_audio.mp3', mimetype='audio/mpeg')

            # --- DÉBUT DE LA CORRECTION ---
            # Le nettoyage se fait après la création de la réponse, mais avant de la retourner.
            # Pas besoin de décorateur complexe.
            print(f"🧹 [V2] Nettoyage du fichier pour la tâche {task_id}...")
            if os.path.exists(audio_path):
                os.remove(audio_path)
            TASK_STORE_V2.pop(task_id, None)
            
            return response
            # --- FIN DE LA CORRECTION ---

        except Exception as e:
            traceback.print_exc()
            return jsonify({"status": "error", "message": f"Erreur lors de l'envoi du fichier : {e}"}), 500

    return jsonify({"status": "unknown"}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=False, host='0.0.0.0', port=port)
