# google_client.py
import os, json
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

load_dotenv()

class GoogleClient:
    def __init__(self):
        creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
        creds_dict = json.loads(creds_json)
        self.creds = Credentials.from_service_account_info(
            creds_dict,
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
                "https://www.googleapis.com/auth/calendar"
            ]
        )

    def sheets(self):
        return build("sheets", "v4", credentials=self.creds)

    def calendar(self):
        return build("calendar", "v3", credentials=self.creds)
