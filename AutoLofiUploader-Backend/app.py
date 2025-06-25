# app.py (Architecture de Production : Polling)

from flask import Flask, request, jsonify, send_file
from flask import g
import os
import services
import media
import uuid
import requests
import json
import zipfile
from google.auth.exceptions import RefreshError
import gspread

app = Flask(__name__)

# Le TASK_STORE est maintenant plus important que jamais. Il contient l'état de chaque tâche.
TASK_STORE = {}
# Ex: TASK_STORE['<task_id>'] = {"status": "pending", "context": {...}}
#     TASK_STORE['<task_id>'] = {"status": "ready_for_download", "files": {...}, "metadata": {...}}
#     TASK_STORE['<task_id>'] = {"status": "error", "message": "..."}

# --- ENDPOINT 1 : Lancement du processus ---
@app.route('/run', methods=['POST'])
def run_process():
    data = request.get_json()
    try:
        # ... (logique d'extraction et de validation des paramètres) ...
        # ... (logique de lecture du Google Sheet) ...
        access_token = data['access_token']
        sheet_id = data['sheet_id']
        prompt_id = data['prompt_id']
        suno_key = data['suno_key']
        image_key = data['image_key']

        print(f"📄 Lecture du prompt '{prompt_id}'...")
        sheets_client = services.get_sheets_client(access_token)
        prompt_data = services.get_prompt_from_sheet(sheets_client, sheet_id, prompt_id)

        if len(prompt_data) < 13: raise IndexError("Structure de ligne incorrecte.")

        task_context = {
            "prompt_id": prompt_id, "sheet_id": sheet_id, "access_token": access_token,
            "image_key": image_key, "lyrics_or_description": prompt_data[1], "image_prompt": prompt_data[2],
            "video_title": prompt_data[3], "video_description": prompt_data[4],
            "video_tags": [tag.strip() for tag in prompt_data[5].split(',')],
            "mode": prompt_data[10].lower().strip(), "style": prompt_data[11], "song_title": prompt_data[12]
        }

        callback_url = request.url_root + "suno_callback"

        if task_context["mode"] == "simple":
            task_id = media.start_suno_simple_generation(suno_key, task_context["lyrics_or_description"], callback_url)
        elif task_context["mode"] == "custom":
            if not task_context["style"] or not task_context["song_title"]: raise ValueError("Champs requis manquants pour le mode custom.")
            task_id = media.start_suno_custom_generation(suno_key, task_context["lyrics_or_description"], task_context["style"], task_context["song_title"], callback_url)
        else:
            raise ValueError(f"Mode inconnu : '{task_context['mode']}'.")
        
        # Initialiser la tâche dans le store
        TASK_STORE[task_id] = {"status": "pending", "context": task_context}
        print(f"   - Tâche '{task_id}' initialisée avec le statut 'pending'.")
        
        return jsonify({"success": True, "status": "pending", "task_id": task_id}), 202

    except Exception as e:
        # ... (gestion des erreurs) ...
        return jsonify({"error": str(e)}), 400


# --- ENDPOINT 2 : Callback de Suno ---
@app.route('/suno_callback', methods=['POST'])
def suno_callback():
    print("\n🔔 Callback reçu de Suno !")
    callback_data = request.get_json() or {}
    task_id = None # On doit pouvoir identifier la tâche même en cas d'erreur

    try:
        main_data_obj = callback_data.get("data", {})
        task_id = main_data_obj.get("task_id")

        if not task_id:
            print("❌ Callback reçu sans task_id. Ignoré.")
            return jsonify({"status": "ignored, no task_id"}), 200

        # On vérifie si la tâche est connue
        if task_id not in TASK_STORE:
            print(f"⚠️ Callback reçu pour une tâche inconnue ou déjà traitée: {task_id}")
            return jsonify({"status": "ignored, unknown task"}), 200

        if main_data_obj.get("callbackType") != 'complete':
            print(f"   - Callback intermédiaire pour la tâche {task_id} ignoré.")
            return jsonify({"status": "intermediate callback ignored"}), 200

        # --- C'est le callback final, on commence le travail ! ---
        context = TASK_STORE[task_id]["context"]
        print(f"   - Traitement du callback final pour la tâche {task_id}.")

        item = main_data_obj.get("data", [{}])[0]
        audio_url = item.get("audio_url") or item.get("stream_audio_url")
        if not audio_url: raise ValueError("URL audio manquante dans le callback final.")

        # Télécharger l'audio et l'image
        print("   - Téléchargement de l'audio...")
        resp = requests.get(audio_url, timeout=180)
        resp.raise_for_status()
        audio_path = f"/tmp/{task_id}_audio.mp3"
        with open(audio_path, "wb") as f: f.write(resp.content)
        
        print("   - Téléchargement de l'image...")
        image_path = media.download_image_from_ia(context['image_key'], context['image_prompt'])

        # Mettre à jour la tâche avec les fichiers prêts et les métadonnées
        TASK_STORE[task_id] = {
            "status": "ready_for_download",
            "files": {"audio": audio_path, "image": image_path},
            "metadata": {
                "video_title": context["video_title"],
                "video_description": context["video_description"],
                "video_tags": context["video_tags"],
                "access_token": context["access_token"],
                "sheet_id": context["sheet_id"],
                "prompt_id": context["prompt_id"]
            }
        }
        print(f"✅ Tâche '{task_id}' mise à jour au statut 'ready_for_download'.")
        return jsonify({"status": "callback processed successfully"}), 200

    except Exception as e:
        if task_id and task_id in TASK_STORE:
            TASK_STORE[task_id] = {"status": "error", "message": str(e)}
        print(f"❌ Erreur lors du traitement du callback : {e}")
        return jsonify({"error": "Erreur lors du traitement du callback."}), 400


# --- ENDPOINT 3 : Statut et récupération des fichiers (Polling) ---
@app.route('/status/<task_id>', methods=['GET'])
def get_task_status(task_id):
    print(f"   - Requête de statut pour la tâche : {task_id}")
    task = TASK_STORE.get(task_id)

    if not task:
        return jsonify({"status": "not_found"}), 404

    if task["status"] == "pending":
        return jsonify({"status": "pending"}), 202
    
    if task["status"] == "error":
        # On renvoie l'erreur et on nettoie
        error_message = task.get("message", "Erreur inconnue.")
        TASK_STORE.pop(task_id, None)
        return jsonify({"status": "error", "message": error_message}), 500

    if task["status"] == "ready_for_download":
        print(f"   - La tâche {task_id} est prête. Création du ZIP...")
        try:
            audio_path = task["files"]["audio"]
            image_path = task["files"]["image"]
            zip_path = f"/tmp/{task_id}_bundle.zip"
            
            with zipfile.ZipFile(zip_path, 'w') as zipf:
                zipf.write(audio_path, arcname='audio.mp3')
                zipf.write(image_path, arcname='image.jpg')
                zipf.writestr('metadata.json', json.dumps(task["metadata"]))

            # On programme le nettoyage après l'envoi
            @after_this_request
            def cleanup(response):
                print(f"🧹 Nettoyage des fichiers pour la tâche {task_id}...")
                os.remove(zip_path)
                os.remove(audio_path)
                os.remove(image_path)
                TASK_STORE.pop(task_id, None) # Nettoyer la tâche de la mémoire
                return response

            return send_file(zip_path, as_attachment=True, download_name='media_bundle.zip')

        except Exception as e:
            return jsonify({"status": "error", "message": f"Erreur lors de la création du ZIP : {e}"}), 500

    return jsonify({"status": "unknown"}), 500


# --- ENDPOINT 4 : Publication (inchangé) ---
@app.route('/publish', methods=['POST'])
def publish_video():
    # ... (cette fonction reste EXACTEMENT la même que précédemment) ...
    # Elle reçoit la vidéo montée, l'uploade et met à jour le Sheet.
    pass # Remplacez 'pass' par votre code existant pour /publish

# --- Helper pour le nettoyage ---
def after_this_request(f):
    if not hasattr(g, 'after_request_callbacks'):
        g.after_request_callbacks = []
    g.after_request_callbacks.append(f)
    return f

@app.after_request
def call_after_request_callbacks(response):
    for callback in getattr(g, 'after_request_callbacks', ()):
        response = callback(response)
    return response

# N'oubliez pas 'g' de Flask en haut du fichier
# from flask import g

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=False, host='0.0.0.0', port=port)
