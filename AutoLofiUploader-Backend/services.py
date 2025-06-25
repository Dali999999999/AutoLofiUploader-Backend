# services.py (corrigé)

import gspread
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import os

# --- Constantes pour les Scopes Google ---
SCOPES_SHEETS = ['https://www.googleapis.com/auth/spreadsheets']
SCOPES_YOUTUBE = ['https://www.googleapis.com/auth/youtube.upload']

def get_sheets_client(access_token: str):
    creds = Credentials(token=access_token)
    return gspread.Client(auth=creds)

# Dans services.py

# Dans services.py

def get_prompt_from_sheet(client: gspread.Client, sheet_id: str, prompt_id: str):
    """
    Récupère une ligne de prompt par son ID de manière robuste, en garantissant
    que 13 colonnes sont toujours retournées, même si elles sont vides.
    """
    sheet = client.open_by_key(sheet_id).sheet1
    cell = sheet.find(prompt_id, in_column=1)
    if not cell:
        raise ValueError(f"Prompt avec l'ID '{prompt_id}' non trouvé.")
    
    # --- DÉBUT DE LA CORRECTION ---
    # La méthode correcte dans gspread pour lire une plage est simplement `get()`.
    row_number = cell.row
    range_to_get = f'A{row_number}:M{row_number}'
    
    # La méthode `get()` retourne une liste de listes.
    # Ex: [['valeurA', 'valeurB', ...]]
    values = sheet.get(range_to_get)
    
    if not values:
        # Si la plage est complètement vide, on retourne une liste vide pour la sécurité.
        prompt_data = []
    else:
        # On prend la première (et seule) ligne de la liste des résultats.
        prompt_data = values[0]
    
    # On garde la logique pour s'assurer d'avoir toujours 13 éléments.
    # C'est la garantie contre les cellules vides en fin de ligne.
    while len(prompt_data) < 13:
        prompt_data.append('')
        
    return prompt_data
    # --- FIN DE LA CORRECTION ---

def update_video_url_in_sheet(client: gspread.Client, sheet_id: str, prompt_id: str, video_url: str):
    """Met à jour la ligne du prompt avec l'URL de la vidéo et le statut 'Publié'."""
    sheet = client.open_by_key(sheet_id).sheet1
    cell = sheet.find(prompt_id, in_column=1)
    if not cell:
        raise ValueError(f"Prompt avec l'ID '{prompt_id}' non trouvé.")
    
    # CORRECTION : Mettre à jour les colonnes G (7) pour l'URL et H (8) pour le statut
    print(f"✍️ Mise à jour du Google Sheet : URL en colonne G, Statut en colonne H pour la ligne {cell.row}.")
    sheet.update_cell(cell.row, 7, video_url)
    sheet.update_cell(cell.row, 8, "Publié")
    print(f"✅ Google Sheet mis à jour pour le prompt {prompt_id}.")

def upload_to_youtube(access_token: str, video_path: str, title: str, description: str, tags: list[str]):
    """Uploade une vidéo sur YouTube et retourne son URL."""
    creds = Credentials(token=access_token, scopes=SCOPES_YOUTUBE)
    youtube = build('youtube', 'v3', credentials=creds)

    body = {
        'snippet': {'title': title, 'description': description, 'tags': tags, 'categoryId': '10'},
        'status': {'privacyStatus': 'private'}
    }
    
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
    request = youtube.videos().insert(part=','.join(body.keys()), body=body, media_body=media)

    response = request.execute()
    video_id = response.get('id')
    if not video_id:
        raise IOError("Impossible de récupérer l'ID de la vidéo après l'upload.")
        
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"🚀 Vidéo uploadée avec succès sur YouTube : {video_url}")
    return video_url
