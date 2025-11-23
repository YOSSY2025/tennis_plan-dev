from google.oauth2 import service_account

SERVICE_FILE = "src/tennis-478115-f1146de4b35d.json"
SHEET_ID = "1_l57W7GIx1OR56uaWt8OBZ1_Lbr8GtWwS_QfvqFrKp0"

creds = service_account.Credentials.from_service_account_file(
    SERVICE_FILE,
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)

client = gspread.authorize(creds)
sheet = client.open_by_key(SHEET_ID).sheet1
print(sheet.get_all_values())
