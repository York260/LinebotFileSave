"""
一次性執行：完成 Google Drive 的 OAuth 授權。

用法：
    uv run python google_auth_setup.py

執行後會跳出瀏覽器，用你自己的 Google 帳號登入並允許權限，
完成後會把授權結果（refresh token）存到 GOOGLE_OAUTH_TOKEN_FILE
（預設 google-token.json），之後 app.py 會自動用這個檔案續期，
不需要再重複這個步驟。
"""

import os

from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def main():
    client_file = os.environ["GOOGLE_OAUTH_CLIENT_FILE"]
    token_file = os.environ.get("GOOGLE_OAUTH_TOKEN_FILE", "google-token.json")

    flow = InstalledAppFlow.from_client_secrets_file(client_file, SCOPES)
    credentials = flow.run_local_server(port=0)

    with open(token_file, "w", encoding="utf-8") as f:
        f.write(credentials.to_json())

    print(f"授權完成，token 已存到 {token_file}")


if __name__ == "__main__":
    main()
