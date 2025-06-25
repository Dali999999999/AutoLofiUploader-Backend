# app.py (Nouvelle architecture : client-side processing)

from flask import Flask, request, jsonify, send_file
import os
import services
import media
import zipfile
from google.auth.exceptions import RefreshError
import gspread

app = Flask(__name__)

# Le stockage en mémoire reste nécessaire pour lier la tâche initiale au callback
TASK_STORE = {}

# --- ENDPOINT 1 : Lancement du processus (inchangé) ---
@app.route('/run', methods=['POST'])
def run_process():
    # ... (cette fonction reste EXACTEMENT la même que la vôtre) ...
    # Elle lit le sheet, détermine le mode, lance la tâche Suno,
    # stocke le contexte et répond 202. C'est parfait.
    data = request.get_json()
    if not data:
        return jsonify({"error": "Requête JSON invalide ou vide."}), 400

    required_keys = ["access_token", "sheet_id", "prompt_id", "suno_key", "image_key"]
    if not all(key in data for key in required_keys):
        return jsonify({"error": f"Paramètres manquants. Requis : {required_keys}"}), 400

    try:
        access_token = data['access_token']
        sheet_id = data['sheet_id']
        prompt_id = data['prompt_id']
        suno_key = data['suno_key']
        image_key = data['image_key']

        print(f"📄 Lecture du prompt '{prompt_id}' depuis le Google Sheet '{sheet_id}'.")
        sheets_client = services.get_sheets_client(access_token)
        prompt_data = services.get_prompt_from_sheet(sheets_client, sheet_id, prompt_id)

        if len(prompt_data) < 13:
            raise IndexError("Structure de ligne incorrecte. 13 colonnes (A-M) sont attendues.")

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
            if not task_context["style"] or not task_context["song_title"]:
                raise ValueError("Pour le mode 'custom', 'Style_Prompt' et 'Song_Title' sont obligatoires.")
            task_id = media.start_suno_custom_generation(suno_key, task_context["lyrics_or_description"], task_context["style"], task_context["song_title"], callback_url)
        else:
            raise ValueError(f"Mode inconnu : '{task_context['mode']}'. Doit être 'simple' ou 'custom'.")
        
        TASK_STORE[task_id] = task_context
        print(f"   - Contexte de la tâche '{task_id}' stocké en mémoire.")
        
        return jsonify({"success": True, "status": "pending", "message": "La génération des médias a été lancée.", "task_id": task_id}), 202

    except (RefreshError, gspread.exceptions.APIError) as e:
        return jsonify({"error": "Token Google expiré ou invalide.", "details": str(e)}), 401
    except (ValueError, IndexError, IOError) as e:
        return jsonify({"error": "Erreur de données, de configuration ou d'API.", "details": str(e)}), 400
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": "Une erreur interne imprévue est survenue.", "details": str(e)}), 500


# --- ENDPOINT 2 : Callback de Suno (fortement simplifié) ---
@app.route('/suno_callback', methods=['POST'])
def suno_callback():
    print("\n🔔 Callback reçu de Suno !")
    callback_data = request.get_json() or {}
    print(f"   - Corps COMPLET du callback reçu: {callback_data}")
    temp_files = []

    try:
        main_data_obj = callback_data.get("data", {})
        if main_data_obj.get("callbackType") != 'complete':
            return jsonify({"status": "intermediate callback ignored"}), 200

        task_id = main_data_obj.get("task_id")
        item = main_data_obj.get("data", [{}])[0]
        audio_url = item.get("audio_url") or item.get("stream_audio_url")

        if not task_id or not audio_url:
            raise ValueError("ID de tâche ou URL audio manquant dans le callback final.")

        context = TASK_STORE.pop(task_id, None)
        if not context:
            raise ValueError(f"Tâche inconnue ou déjà traitée : {task_id}")

        # === Étape 1: Télécharger l'audio ===
        print(f"   - Téléchargement de l'audio depuis : {audio_url}")
        resp = requests.get(audio_url, timeout=180)
        resp.raise_for_status()
        audio_path = f"/tmp/{task_id}_audio.mp3"
        with open(audio_path, "wb") as f:
            f.write(resp.content)
        temp_files.append(audio_path)
        print(f"   - Audio sauvegardé à : {audio_path}")

        # === Étape 2: Télécharger l'image ===
        image_path = media.download_image_from_ia(context['image_key'], context['image_prompt'])
        temp_files.append(image_path)
        
        # === Étape 3: Zipper les fichiers et les métadonnées ===
        # Votre question est excellente: il faut renvoyer les métadonnées !
        zip_path = f"/tmp/{task_id}_bundle.zip"
        temp_files.append(zip_path)

        metadata = {
            "video_title": context["video_title"],
            "video_description": context["video_description"],
            "video_tags": context["video_tags"],
            "access_token": context["access_token"],
            "sheet_id": context["sheet_id"],
            "prompt_id": context["prompt_id"]
        }
        
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            zipf.write(audio_path, arcname='audio.mp3')
            zipf.write(image_path, arcname='image.jpg')
            zipf.writestr('metadata.json', json.dumps(metadata))

        print(f"   - Fichiers et métadonnées zippés dans : {zip_path}")

        # === Étape 4: Envoyer le ZIP au client ===
        # Le client recevra ce ZIP, fera le montage, et rappellera /publish
        return send_file(zip_path, as_attachment=True, download_name='media_bundle.zip', mimetype='application/zip')

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": "Erreur lors de la préparation des fichiers.", "details": str(e)}), 500
    finally:
        print("🧹 Nettoyage des fichiers temporaires...")
        for file_path in temp_files:
            if os.path.exists(file_path):
                os.remove(file_path)


# --- ENDPOINT 3 : Réception de la vidéo finale et publication ---
@app.route('/publish', methods=['POST'])
def publish_video():
    """
    Reçoit la vidéo montée par le client, l'uploade sur YouTube
    et met à jour le Google Sheet.
    """
    temp_files = []
    try:
        # Les données ne sont plus en JSON, mais en 'multipart/form-data'
        if 'video_file' not in request.files:
            return jsonify({"error": "Fichier vidéo manquant ('video_file')."}), 400
        if 'metadata_str' not in request.form:
            return jsonify({"error": "Données de métadonnées manquantes ('metadata_str')."}), 400

        video_file = request.files['video_file']
        metadata = json.loads(request.form['metadata_str'])

        # Sauvegarder temporairement la vidéo reçue
        video_path = f"/tmp/{uuid.uuid4()}_{video_file.filename}"
        video_file.save(video_path)
        temp_files.append(video_path)
        print(f"📹 Vidéo reçue du client et sauvegardée à : {video_path}")

        # Uploader sur YouTube
        video_url = services.upload_to_youtube(
            metadata['access_token'],
            video_path,
            metadata['video_title'],
            metadata['video_description'],
            metadata['video_tags']
        )

        # Mettre à jour le Google Sheet
        sheets_client = services.get_sheets_client(metadata['access_token'])
        services.update_video_url_in_sheet(sheets_client, metadata['sheet_id'], metadata['prompt_id'], video_url)
        
        print("✅ Publication terminée avec succès !")
        return jsonify({"success": True, "video_url": video_url}), 200

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": "Erreur lors de la publication.", "details": str(e)}), 500
    finally:
        print("🧹 Nettoyage du fichier vidéo temporaire...")
        for file_path in temp_files:
            if os.path.exists(file_path):
                os.remove(file_path)

# N'oubliez pas d'importer json et zipfile en haut du fichier app.py
# import json
# import zipfile
# et 'send_file' de flask

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=False, host='0.0.0.0', port=port)
