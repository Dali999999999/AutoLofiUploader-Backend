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

# Dans app.py, remplacez la fonction run_process

@app.route('/run', methods=['POST'])
def run_process():
    """
    Endpoint initial : lit le prompt, détermine le mode (simple/custom) et lance la génération.
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

        # La nouvelle structure a 13 colonnes (A à M)
        if len(prompt_data) < 13:
            raise IndexError("Structure de ligne incorrecte. 13 colonnes (A-M) sont attendues.")

        # 3. Mapper les données aux variables
        task_context = {
            "prompt_id": prompt_id,
            "sheet_id": sheet_id,
            "access_token": access_token,
            "image_key": image_key,
            "lyrics_or_description": prompt_data[1],  # Col B
            "image_prompt": prompt_data[2],           # Col C
            "video_title": prompt_data[3],            # Col D
            "video_description": prompt_data[4],      # Col E
            "video_tags": [tag.strip() for tag in prompt_data[5].split(',')], # Col F
            "mode": prompt_data[10].lower().strip(),  # Col K
            "style": prompt_data[11],                 # Col L
            "song_title": prompt_data[12]             # Col M
        }

        # 4. Construire l'URL du callback
        callback_url = request.url_root + "suno_callback"

        # 5. Appeler la bonne fonction en fonction du mode
        if task_context["mode"] == "simple":
            task_id = media.start_suno_simple_generation(
                suno_key,
                task_context["lyrics_or_description"],
                callback_url
            )
        elif task_context["mode"] == "custom":
            # Vérifier que les champs requis pour le mode custom ne sont pas vides
            if not task_context["style"] or not task_context["song_title"]:
                raise ValueError("Pour le mode 'custom', les colonnes 'Style_Prompt' et 'Song_Title' sont obligatoires.")
            task_id = media.start_suno_custom_generation(
                suno_key,
                task_context["lyrics_or_description"],
                task_context["style"],
                task_context["song_title"],
                callback_url
            )
        else:
            raise ValueError(f"Mode inconnu : '{task_context['mode']}'. Doit être 'simple' ou 'custom'.")
        
        # 6. Stocker le contexte et répondre au client
        TASK_STORE[task_id] = task_context
        print(f"   - Contexte de la tâche '{task_id}' stocké en mémoire.")
        
        return jsonify({
            "success": True,
            "status": "pending",
            "message": "La génération de la vidéo a été lancée.",
            "task_id": task_id
        }), 202

    except (RefreshError, gspread.exceptions.APIError) as e:
        return jsonify({"error": "Token Google expiré ou invalide.", "details": str(e)}), 401
    except (ValueError, IndexError, IOError) as e:
        return jsonify({"error": "Erreur de données, de configuration ou de l'API Suno.", "details": str(e)}), 400
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": "Une erreur interne imprévue est survenue.", "details": str(e)}), 500




@app.route('/suno_callback', methods=['POST'])
# app.py - FONCTION CALLBACK COMPLÈTE À REMPLACER

@app.route('/suno_callback', methods=['POST'])
def suno_callback():
    print("\n🔔 Callback reçu de Suno !")
    callback_data = request.get_json() or {}
    print(f"   - Corps COMPLET du callback reçu: {callback_data}")
    temp_files = []

    try:
        main_data_obj = callback_data.get("data", {})
        
        # FILTRE CRUCIAL : On n'agit que sur le callback final.
        if main_data_obj.get("callbackType") != 'complete':
            print("   - Callback intermédiaire ignoré. En attente du message 'complete'.")
            return jsonify({"status": "intermediate callback ignored"}), 200

        # --- Le reste de la logique ne s'exécute que pour le VRAI callback ---
        task_id = main_data_obj.get("task_id")
        if not task_id:
            raise ValueError("La clé 'task_id' est manquante dans l'objet 'data' du callback.")

        item_list = main_data_obj.get("data")
        if not isinstance(item_list, list) or not item_list:
            raise ValueError("La clé 'data.data' (liste des pistes) est manquante ou n'est pas une liste valide.")
        
        item = item_list[0]
        audio_url = item.get("audio_url") or item.get("stream_audio_url")
        if not audio_url:
            raise ValueError("Aucune URL audio valide ('audio_url' ou 'stream_audio_url') n'a été trouvée.")

        print(f"   - Données extraites avec succès ! Tâche: {task_id}, URL: {audio_url}")
        
        context = TASK_STORE.pop(task_id, None)
        if not context:
            raise ValueError(f"Tâche inconnue ou déjà traitée : {task_id}")

        print(f"   - Téléchargement de l'audio depuis : {audio_url}")
        resp = requests.get(audio_url, timeout=180) # Augmentation du timeout pour le téléchargement
        resp.raise_for_status()
        audio_path = f"/tmp/{task_id}.mp3"
        with open(audio_path, "wb") as f:
            f.write(resp.content)
        temp_files.append(audio_path)
        print(f"   - Audio sauvegardé à : {audio_path}")

        image_path = media.generate_image_from_ia(context['image_key'], context['image_prompt'])
        temp_files.append(image_path)
        
        video_path = media.assemble_video(image_path, audio_path)
        temp_files.append(video_path)

        video_url = services.upload_to_youtube(
            context['access_token'], video_path, context['video_title'],
            context['video_description'], context['video_tags']
        )

        sheets_client = services.get_sheets_client(context['access_token'])
        services.update_video_url_in_sheet(sheets_client, context['sheet_id'], context['prompt_id'], video_url)
        
        print(f"✅ Processus complet terminé avec succès pour la tâche {task_id} !")
        return jsonify({"status": "callback processed successfully"}), 200

    except (ValueError, IndexError, IOError, requests.exceptions.RequestException) as e:
        print(f"❌ Erreur lors du traitement du callback : {e}")
        return jsonify({"error": "Erreur lors du traitement du callback.", "details": str(e)}), 400
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": "Erreur interne pendant le callback.", "details": str(e)}), 500
    finally:
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
