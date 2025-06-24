# services.py

import gspread
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import os

# --- Constantes pour les Scopes Google ---
SCOPES_SHEETS = ['https://www.googleapis.com/auth/spreadsheets']
SCOPES_YOUTUBE = ['https://www.googleapis.com/auth/youtube.upload']

# --- Fonctions Google Sheets ---

def get_sheets_client(access_token: str):
    """Crée un client gspread authentifié avec un access_token."""
    creds = Credentials(token=access_token)
    return gspread.Client(auth=creds)

def get_prompt_from_sheet(client: gspread.Client, sheet_id: str, prompt_id: str):
    """Récupère une ligne de prompt par son ID."""
    sheet = client.open_by_key(sheet_id).sheet1
    # Suppose que la colonne 'ID' est la première (A)
    cell = sheet.find(prompt_id, in_column=1)
    if not cell:
        raise ValueError(f"Prompt avec l'ID '{prompt_id}' non trouvé.")
    return sheet.row_values(cell.row)

def update_video_url_in_sheet(client: gspread.Client, sheet_id: str, prompt_id: str, video_url: str):
    """Met à jour la ligne du prompt avec l'URL de la vidéo et le statut."""
    sheet = client.open_by_key(sheet_id).sheet1
    cell = sheet.find(prompt_id, in_column=1)
    if not cell:
        raise ValueError(f"Prompt avec l'ID '{prompt_id}' non trouvé.")
    
    # Suppose que la colonne pour l'URL est la 5ème (E) et le statut la 6ème (F)
    sheet.update_cell(cell.row, 5, video_url)
    sheet.update_cell(cell.row, 6, "Publié")
    print(f"✅ Google Sheet mis à jour pour le prompt {prompt_id}.")

# --- Fonction YouTube ---

def upload_to_youtube(access_token: str, video_path: str, title: str, description: str, tags: list[str]):
    """Uploade une vidéo sur YouTube et la retourne son URL."""
    creds = Credentials(token=access_token, scopes=SCOPES_YOUTUBE)
    
    # La méthode build crée un objet de service pour interagir avec l'API. [1]
    youtube = build('youtube', 'v3', credentials=creds)

    body = {
        'snippet': {
            'title': title,
            'description': description,
            'tags': tags,
            'categoryId': '10'  # 10 = Musique
        },
        'status': {
            'privacyStatus': 'private' # ou 'public' / 'unlisted'
        }
    }
    
    # MediaFileUpload gère le processus d'upload du fichier. [1]
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True)

    request = youtube.videos().insert(
        part=','.join(body.keys()),
        body=body,
        media_body=media
    )

    response = request.execute()
    video_id = response.get('id')
    if not video_id:
        raise IOError("Impossible de récupérer l'ID de la vidéo après l'upload.")
        
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"🚀 Vidéo uploadée avec succès sur YouTube : {video_url}")
    return video_url