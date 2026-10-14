"""
一次性執行：完成 Google Drive 的 OAuth 授權。

用法：
    uv run python google_auth_setup.py

執行後會跳出瀏覽器，用你自己的 Google 帳號登入並允許權限，
完成後會把授權結果（refresh token）存到 GOOGLE_OAUTH_TOKEN_FILE
（預設 google-token.json），之後 app.py 會自動用這個檔案續期，
不需要再重複這個步驟。

注意：OAuth 同意畫面的發布狀態如果還是「測試中」，Google 發的 refresh token
只有 7 天效期，一週後備份就會停掉。執行前請先把應用程式發布為「實際運作中」
（見 README）；發布前拿到的 token 一樣只有 7 天，發布後要重新執行一次。
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
    # prompt="consent"：已經授權過的帳號再跑一次時，Google 才會重新發 refresh token
    credentials = flow.run_local_server(port=0, prompt="consent")

    with open(token_file, "w", encoding="utf-8") as f:
        f.write(credentials.to_json())

    print(f"授權完成，token 已存到 {token_file}")


if __name__ == "__main__":
    main()
