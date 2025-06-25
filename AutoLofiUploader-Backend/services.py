# services.py (version finale épurée)

import gspread
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import os

SCOPES_YOUTUBE = ['https://www.googleapis.com/auth/youtube.upload']

def get_sheets_client(access_token: str):
    creds = Credentials(token=access_token)
    return gspread.Client(auth=creds)

def get_prompt_from_sheet(client: gspread.Client, sheet_id: str, prompt_id: str):
    """
    Récupère une ligne de prompt, garantissant que 11 colonnes (A à K) sont retournées.
    """
    sheet = client.open_by_key(sheet_id).sheet1
    cell = sheet.find(prompt_id, in_column=1)
    if not cell:
        raise ValueError(f"Prompt avec l'ID '{prompt_id}' non trouvé.")
    
    row_number = cell.row
    range_to_get = f'A{row_number}:K{row_number}' # Lire jusqu'à la colonne K
    values = sheet.get(range_to_get)
    
    prompt_data = values[0] if values else []
    
    while len(prompt_data) < 11: # S'assurer d'avoir 11 éléments
        prompt_data.append('')
    return prompt_data

def update_video_url_in_sheet(client: gspread.Client, sheet_id: str, prompt_id: str, video_url: str):
    """Met à jour la ligne du prompt avec l'URL de la vidéo et le statut."""
    sheet = client.open_by_key(sheet_id).sheet1
    cell = sheet.find(prompt_id, in_column=1)
    if not cell:
        raise ValueError(f"Prompt avec l'ID '{prompt_id}' non trouvé.")
    
    sheet.update_cell(cell.row, 7, video_url) # Colonne G pour l'URL
    sheet.update_cell(cell.row, 8, "Publié")  # Colonne H pour le statut
    print(f"✅ Google Sheet mis à jour pour le prompt {prompt_id}.")

def upload_to_youtube(access_token: str, video_path: str, title: str, description: str, tags: list[str], visibility: str = 'private'):
    """Uploade une vidéo sur YouTube avec la visibilité spécifiée."""
    creds = Credentials(token=access_token, scopes=SCOPES_YOUTUBE)
    youtube = build('youtube', 'v3', credentials=creds)

    valid_visibilities = ['private', 'public', 'unlisted']
    safe_visibility = visibility.lower() if visibility.lower() in valid_visibilities else 'private'
    
    body = {
        'snippet': {'title': title, 'description': description, 'tags': tags, 'categoryId': '10'},
        'status': {'privacyStatus': safe_visibility}
    }
    
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
    request = youtube.videos().insert(part=','.join(body.keys()), body=body, media_body=media)

    response = request.execute()
    video_id = response.get('id')
    if not video_id:
        raise IOError("Impossible de récupérer l'ID de la vidéo après l'upload.")
        
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"🚀 Vidéo uploadée avec succès sur YouTube ({safe_visibility}) : {video_url}")
    return video_url
