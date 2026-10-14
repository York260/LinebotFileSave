import io
import json
import mimetypes
import os
import sys
from datetime import datetime

from dotenv import load_dotenv
from flask import Flask, abort, request
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials as GoogleUserCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    MessagingApiBlob,
)
from linebot.v3.webhooks import (
    AudioMessageContent,
    FileMessageContent,
    ImageMessageContent,
    MessageEvent,
    VideoMessageContent,
)

load_dotenv()

# 雲端平台（例如 Render）上 stdout 不是終端機，print 會被整塊緩衝，
# 錯誤訊息要等程式結束才出現在日誌、甚至看不到；改成每行立刻輸出。
sys.stdout.reconfigure(line_buffering=True)

app = Flask(__name__)

configuration = Configuration(access_token=os.environ["LINE_CHANNEL_ACCESS_TOKEN"])
handler = WebhookHandler(os.environ["LINE_CHANNEL_SECRET"])

# --- Google Drive 備份設定 ---
# 服務帳戶沒有儲存空間配額，個人（非 Workspace）帳號沒辦法讓它建立檔案，
# 所以改用 OAuth 使用者授權：檔案的擁有者是你自己的帳號，算在你自己的容量裡。
# 授權是一次性的，本機執行 google_auth_setup.py 完成登入後會產生 token；
# refresh_token 本身不會過期，之後都是自動續期，不需要再次登入。
#
# token 的來源有兩種（擇一即可）：
#   1. GOOGLE_OAUTH_TOKEN_JSON：把 google-token.json 的完整內容當成環境變數。
#      給雲端平台用（例如 Render）——那種平台的檔案系統重啟後不會保留，
#      所以不能只存在本機檔案裡。
#   2. GOOGLE_OAUTH_TOKEN_FILE：本機檔案路徑，本機開發用。
GOOGLE_OAUTH_SCOPES = ["https://www.googleapis.com/auth/drive.file"]
GOOGLE_OAUTH_TOKEN_JSON = os.environ.get("GOOGLE_OAUTH_TOKEN_JSON")
GOOGLE_OAUTH_TOKEN_FILE = os.environ.get("GOOGLE_OAUTH_TOKEN_FILE", "google-token.json")
GOOGLE_DRIVE_FOLDER_ID = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")


def _load_drive_credentials():
    if not GOOGLE_DRIVE_FOLDER_ID:
        return None

    if GOOGLE_OAUTH_TOKEN_JSON:
        creds = GoogleUserCredentials.from_authorized_user_info(
            json.loads(GOOGLE_OAUTH_TOKEN_JSON), scopes=GOOGLE_OAUTH_SCOPES
        )
    elif os.path.exists(GOOGLE_OAUTH_TOKEN_FILE):
        creds = GoogleUserCredentials.from_authorized_user_file(
            GOOGLE_OAUTH_TOKEN_FILE, scopes=GOOGLE_OAUTH_SCOPES
        )
    else:
        return None

    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleAuthRequest())
        # 只有本機檔案模式才寫回去；環境變數模式下一次啟動會重新用
        # refresh_token 換新的 access token，不需要（也無法持久）寫回。
        if not GOOGLE_OAUTH_TOKEN_JSON:
            with open(GOOGLE_OAUTH_TOKEN_FILE, "w", encoding="utf-8") as f:
                f.write(creds.to_json())
    return creds


_drive_service = None
_drive_error: str | None = None  # 最近一次無法使用 Drive 的原因，首頁會顯示


def _set_drive_error(message: str) -> None:
    global _drive_service, _drive_error
    _drive_service = None
    _drive_error = message
    print(message)


def _set_auth_expired(exc: Exception) -> None:
    _set_drive_error(
        f"Google Drive 授權失效，雲端備份暫停（{exc}）。"
        "請重新執行 google_auth_setup.py，並更新 GOOGLE_OAUTH_TOKEN_JSON"
    )


def get_drive_service():
    """取得 Drive API client，還沒成功初始化就再試一次。

    授權失敗（例如 refresh token 過期，invalid_grant）時不讓整個 app 掛掉，
    否則 webhook 跟首頁都會整個打不開，很難看出原因。
    失敗原因會印在日誌、顯示在首頁，之後每次要備份時都會重試。
    """
    global _drive_service, _drive_error
    if _drive_service is not None:
        return _drive_service

    try:
        creds = _load_drive_credentials()
    except Exception as exc:  # noqa: BLE001
        _set_auth_expired(exc)
        return None
    if creds is None:
        _set_drive_error(
            "尚未完成 Google Drive OAuth 授權或缺少 GOOGLE_DRIVE_FOLDER_ID，"
            "雲端備份功能已停用（請先執行 google_auth_setup.py）"
        )
        return None

    _drive_service = build("drive", "v3", credentials=creds, cache_discovery=False)
    _drive_error = None
    return _drive_service


# 啟動時先試一次，授權有問題馬上就會在日誌看到
get_drive_service()


def backup_to_drive(content: bytes, filename: str, mime_type: str, parent_folder_id: str) -> bool:
    """把檔案內容上傳到指定的 Google Drive 資料夾備份，回傳是否成功。"""
    drive_service = get_drive_service()
    if drive_service is None:
        return False
    try:
        media = MediaIoBaseUpload(io.BytesIO(content), mimetype=mime_type)
        drive_service.files().create(
            body={"name": filename, "parents": [parent_folder_id]},
            media_body=media,
            fields="id",
        ).execute()
        return True
    except RefreshError as exc:
        # 執行中 refresh token 失效：清掉 client，讓首頁顯示原因、下次重新載入授權
        _set_auth_expired(exc)
        return False
    except Exception as exc:  # noqa: BLE001
        print(f"上傳 Google Drive 失敗: {exc}")
        return False


def source_label(source) -> str:
    """依訊息來源（私訊／群組／多人聊天室）產生識別字串，抓不到名稱時的備用值。"""
    if source.type == "group":
        return f"group_{source.group_id}"
    if source.type == "room":
        return f"room_{source.room_id}"
    return f"user_{source.user_id}"


def resolve_source_name(event, line_bot_api) -> str:
    """取得訊息來源的人類可讀名稱（群組名稱／使用者暱稱），當成子資料夾名稱。
    查不到名稱（例如 API 失敗）就退回用 ID，仍能正常分資料夾，只是名稱較不好認。
    """
    source = event.source
    try:
        if source.type == "group":
            summary = line_bot_api.get_group_summary(source.group_id)
            name = f"群組-{summary.group_name}"
        elif source.type == "room":
            # 多人聊天室沒有名稱可查，只能用 ID
            name = f"多人聊天室-{source.room_id}"
        else:
            profile = line_bot_api.get_profile(source.user_id)
            name = f"私訊-{profile.display_name}"
    except Exception as exc:  # noqa: BLE001
        print(f"取得來源名稱失敗，改用 ID: {exc}")
        name = source_label(source)

    # Drive 資料夾名稱不能有斜線，避免顯示上跟路徑搞混
    return name.replace("/", "／")


_folder_id_cache: dict[str, str] = {}


def get_or_create_subfolder(name: str) -> str | None:
    """取得（沒有就在備份資料夾底下建立）指定名稱的子資料夾，回傳其 ID。

    不限定子資料夾一定要在備份資料夾底下：使用者可能把它搬到別的資料夾共用。
    drive.file 權限只看得到 bot 自己建立的檔案，所以不會抓到使用者其他同名資料夾；
    若有重複，取最早建立的那個。
    """
    drive_service = get_drive_service()
    if drive_service is None:
        return None
    if name in _folder_id_cache:
        return _folder_id_cache[name]

    escaped_name = name.replace("\\", "\\\\").replace("'", "\\'")
    query = (
        f"name = '{escaped_name}' "
        "and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    )
    try:
        results = drive_service.files().list(
            q=query, fields="files(id)", orderBy="createdTime"
        ).execute()
        files = results.get("files", [])
        if files:
            folder_id = files[0]["id"]
        else:
            folder = drive_service.files().create(
                body={
                    "name": name,
                    "mimeType": "application/vnd.google-apps.folder",
                    "parents": [GOOGLE_DRIVE_FOLDER_ID],
                },
                fields="id",
            ).execute()
            folder_id = folder["id"]
    except Exception as exc:  # noqa: BLE001
        print(f"建立/取得子資料夾失敗: {exc}")
        return None

    _folder_id_cache[name] = folder_id
    return folder_id


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def handle_media_backup(event, mime_type, label, extension=None, filename_override=None):
    """共用邏輯：下載媒體訊息內容、依來源分資料夾備份到 Google Drive。
    不管成功或失敗都不回覆任何訊息（純背景備份，失敗原因看伺服器日誌）。
    """
    if get_drive_service() is None:
        print(f"{label}備份失敗（Google Drive 無法使用）: message_id={event.message.id}")
        return

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        blob_api = MessagingApiBlob(api_client)

        content = blob_api.get_message_content(event.message.id)
        filename = filename_override or f"{timestamp()}_{event.message.id}.{extension}"

        source_name = resolve_source_name(event, line_bot_api)
        folder_id = get_or_create_subfolder(source_name) or GOOGLE_DRIVE_FOLDER_ID

        ok = folder_id is not None and backup_to_drive(content, filename, mime_type, folder_id)
        if not ok:
            print(f"{label}備份失敗: message_id={event.message.id}")


@app.route("/")
def home():
    # 打開網址就能確認備份是否正常，不用翻伺服器日誌
    if get_drive_service() is None:
        return f"backup bot running，但 Google Drive 備份目前無法使用：{_drive_error}"
    return "backup bot running，Google Drive 備份正常"


@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK"


@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image(event):
    handle_media_backup(event, mime_type="image/jpeg", label="圖片", extension="jpg")


@handler.add(MessageEvent, message=VideoMessageContent)
def handle_video(event):
    handle_media_backup(event, mime_type="video/mp4", label="影片", extension="mp4")


@handler.add(MessageEvent, message=AudioMessageContent)
def handle_audio(event):
    handle_media_backup(event, mime_type="audio/mp4", label="語音", extension="m4a")


@handler.add(MessageEvent, message=FileMessageContent)
def handle_file(event):
    filename = event.message.file_name
    mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    handle_media_backup(event, mime_type=mime_type, label="檔案", filename_override=filename)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
