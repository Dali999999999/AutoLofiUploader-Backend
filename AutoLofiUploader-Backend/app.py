# app.py (version corrigée et robuste)

from flask import Flask, request, jsonify
import os
import services
import media
from google.auth.exceptions import RefreshError
import gspread

app = Flask(__name__)

@app.route('/run', methods=['POST'])
def run_process():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Requête JSON invalide ou vide."}), 400

    required_keys = ["access_token", "sheet_id", "prompt_id", "suno_key", "image_key"]
    if not all(key in data for key in required_keys):
        return jsonify({"error": f"Paramètres manquants. Requis : {required_keys}"}), 400

    access_token = data['access_token']
    sheet_id = data['sheet_id']
    prompt_id = data['prompt_id']
    suno_key = data['suno_key']
    image_key = data['image_key']
    
    temp_files = []

    try:
        # 1. Lire les données du prompt depuis Google Sheet
        print(f"📄 Lecture du prompt '{prompt_id}' depuis le Google Sheet '{sheet_id}'.")
        sheets_client = services.get_sheets_client(access_token)
        prompt_data = services.get_prompt_from_sheet(sheets_client, sheet_id, prompt_id)

        # --- CORRECTION MAJEURE : MAPPING DE LA NOUVELLE STRUCTURE ---
        # Ancienne structure (supposée) : ID, Prompt, Titre, Description, Tags
        # Nouvelle structure (robuste) : ID, Music_Prompt, Image_Prompt, Video_Title, Video_Description, Tags
        
        # Vérification que la ligne a assez de colonnes pour éviter les erreurs
        if len(prompt_data) < 6:
            raise IndexError(f"La ligne du prompt '{prompt_id}' ne contient pas assez de colonnes. Structure attendue : ID, Music_Prompt, Image_Prompt, Video_Title, Video_Description, Tags.")

        music_prompt = prompt_data[1]       # Colonne B: Prompt pour l'IA musicale
        image_prompt = prompt_data[2]       # Colonne C: Prompt pour l'IA visuelle
        video_title = prompt_data[3]        # Colonne D: Titre de la vidéo YouTube
        video_description = prompt_data[4]  # Colonne E: Description de la vidéo
        video_tags = [tag.strip() for tag in prompt_data[5].split(',')] # Colonne F: Tags

        print(f"   - Prompt Musique : '{music_prompt[:50]}...'")
        print(f"   - Prompt Image : '{image_prompt[:50]}...'")

        # 2. Générer l'audio et l'image avec les prompts dédiés
        print("🎵 Génération de l'audio...")
        audio_path = media.generate_audio_from_ia(suno_key, music_prompt)
        temp_files.append(audio_path)
        
        print("🎨 Génération de l'image...")
        image_path = media.generate_image_from_ia(image_key, image_prompt)
        temp_files.append(image_path)
        
        # 3. Assembler la vidéo avec FFmpeg
        print("🎬 Assemblage de la vidéo (image + audio)...")
        video_path = media.assemble_video(image_path, audio_path)
        temp_files.append(video_path)

        # 4. Uploader sur YouTube
        print("🚀 Upload de la vidéo sur YouTube...")
        video_url = services.upload_to_youtube(access_token, video_path, video_title, video_description, video_tags)

        # 5. Mettre à jour le statut et l'URL dans Google Sheet
        print("✍️ Mise à jour du Google Sheet...")
        services.update_video_url_in_sheet(sheets_client, sheet_id, prompt_id, video_url)
        
        print("✅ Processus complet terminé avec succès !")
        return jsonify({
            "success": True,
            "message": "Processus complet terminé.",
            "video_url": video_url
        }), 200

    except (RefreshError, gspread.exceptions.APIError) as e:
        return jsonify({"error": "Token Google expiré ou invalide. Le client doit relancer l'authentification.", "details": str(e)}), 401
    
    except (ValueError, IndexError) as e:
        # Erreur si un prompt n'est pas trouvé ou si la structure de la ligne est incorrecte
        return jsonify({"error": "Erreur de données ou de configuration du Google Sheet.", "details": str(e)}), 400

    except Exception as e:
        # Gérer toutes les autres erreurs (ex: FFmpeg, API IA, etc.)
        import traceback
        traceback.print_exc() # Imprime la trace complète dans les logs de Render pour le débogage
        return jsonify({"error": "Une erreur interne est survenue sur le serveur.", "details": str(e)}), 500

    finally:
        # 6. Nettoyer les fichiers temporaires quoi qu'il arrive
        print("🧹 Nettoyage des fichiers temporaires...")
        for file_path in temp_files:
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    print(f"  - Supprimé : {file_path}")
                except OSError as e:
                    print(f"  - Erreur lors de la suppression de {file_path}: {e}")

# Note: Les autres endpoints restent inchangés car ils ne sont pas encore implémentés.
@app.route('/prompts', methods=['GET'])
def get_prompts():
    return jsonify({"message": "Endpoint /prompts non implémenté."}), 501

@app.route('/update_prompt', methods=['POST'])
def update_prompt():
    return jsonify({"message": "Endpoint /update_prompt non implémenté."}), 501
    
@app.route('/delete_prompt', methods=['POST'])
def delete_prompt():
    return jsonify({"message": "Endpoint /delete_prompt non implémenté."}), 501

if __name__ == '__main__':
    # Utilise le port défini par Render, avec une valeur par défaut de 8080 pour les tests locaux
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=False, host='0.0.0.0', port=port)
