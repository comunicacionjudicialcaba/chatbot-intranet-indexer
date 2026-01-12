import os
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build

def main():
    creds_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not creds_json:
        raise Exception("Missing service account credentials")

    creds_info = json.loads(creds_json)

    credentials = service_account.Credentials.from_service_account_info(
        creds_info,
        scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )

    service = build("drive", "v3", credentials=credentials)

    results = service.files().list(
        q="mimeType='application/vnd.google-apps.folder'",
        fields="files(id, name)"
    ).execute()

    folders = results.get("files", [])

    print("Carpetas accesibles:")
    for folder in folders:
        print(f"- {folder['name']} ({folder['id']})")

if __name__ == "__main__":
    main()
