# app.py

from flask import Flask, request, jsonify
import os
import services
import media
from google.auth.exceptions import RefreshError

app = Flask(__name__)

# --- Endpoint Principal ---
@app.route('/run', methods=['POST'])
def run_process():
    # La méthode request.get_json() parse le corps de la requête en dictionnaire Python. [2, 3, 7]
    data = request.get_json()
    if not data:
        return jsonify({"error": "Requête JSON invalide ou vide."}), 400

    required_keys = ["access_token", "sheet_id", "prompt_id", "suno_key", "image_key"]
    if not all(key in data for key in required_keys):
        return jsonify({"error": "Paramètres manquants dans la requête."}), 400

    access_token = data['access_token']
    sheet_id = data['sheet_id']
    prompt_id = data['prompt_id']
    suno_key = data['suno_key']
    image_key = data['image_key']
    
    temp_files = []

    try:
        # 1. Lire le prompt dans Google Sheet
        sheets_client = services.get_sheets_client(access_token)
        prompt_data = services.get_prompt_from_sheet(sheets_client, sheet_id, prompt_id)
        # Supposons la structure: ID, Prompt, Titre, Description, Tags
        prompt_text = prompt_data[1]
        video_title = prompt_data[2]
        video_description = prompt_data[3]
        video_tags = [tag.strip() for tag in prompt_data[4].split(',')]

        # 2. Générer l'audio et l'image
        audio_path = media.generate_audio_from_ia(suno_key, prompt_text)
        temp_files.append(audio_path)
        
        image_path = media.generate_image_from_ia(image_key, prompt_text)
        temp_files.append(image_path)
        
        # 3. Assembler la vidéo
        video_path = media.assemble_video(image_path, audio_path)
        temp_files.append(video_path)

        # 4. Uploader sur YouTube
        video_url = services.upload_to_youtube(access_token, video_path, video_title, video_description, video_tags)

        # 5. Mettre à jour le Google Sheet
        services.update_video_url_in_sheet(sheets_client, sheet_id, prompt_id, video_url)
        
        return jsonify({
            "success": True,
            "message": "Processus complet terminé.",
            "video_url": video_url
        }), 200

    except (RefreshError, gspread.exceptions.APIError) as e:
        # Gérer les erreurs d'authentification Google
        return jsonify({"error": "Token Google expiré ou invalide.", "details": str(e)}), 401
    
    except Exception as e:
        # Gérer toutes les autres erreurs
        return jsonify({"error": f"Une erreur est survenue: {str(e)}"}), 500

    finally:
        # 6. Nettoyer les fichiers temporaires
        print("🧹 Nettoyage des fichiers temporaires...")
        for file_path in temp_files:
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"  - Supprimé : {file_path}")

# --- Autres Endpoints (simplifiés) ---

@app.route('/prompts', methods=['GET'])
def get_prompts():
    # Implémentation future : lire et filtrer les prompts non publiés
    return jsonify({"message": "Endpoint /prompts non implémenté."}), 501

@app.route('/update_prompt', methods=['POST'])
def update_prompt():
    # Implémentation future : modifier une ligne du Sheet
    return jsonify({"message": "Endpoint /update_prompt non implémenté."}), 501
    
@app.route('/delete_prompt', methods=['POST'])
def delete_prompt():
    # Implémentation future : supprimer une ligne du Sheet
    return jsonify({"message": "Endpoint /delete_prompt non implémenté."}), 501

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))