# LINE 檔案備份 Bot

收到 LINE 訊息（私訊或群組）裡的圖片、影片、語音、檔案，自動備份一份到指定的 Google Drive 資料夾。

## 本機開發

```bash
uv sync
uv run python app.py
```

需要 `.env`（參考 `.env.example`）：

- `LINE_CHANNEL_SECRET` / `LINE_CHANNEL_ACCESS_TOKEN`：LINE Developers 後台的 Messaging API 頻道資訊
- `GOOGLE_DRIVE_FOLDER_ID`：備份目的地資料夾 ID（Drive 資料夾網址 `/folders/` 後面那一串）
- Google Drive 授權（本機開發用檔案模式）：
  1. 到 [Google Cloud Console](https://console.cloud.google.com/) 建立專案，啟用 **Google Drive API**
  2. 「API 和服務」→「OAuth 同意畫面」，使用者類型選外部，在**測試使用者**加入你自己的 Google 帳號，
     接著把發布狀態改成**實際運作中**（新版介面在「Google Auth Platform」→「目標對象」→「發布應用程式」）。
     **這步不能省**：停在「測試中」的話，Google 發的 refresh token 只有 7 天效期，一週後備份就會停掉。
     這個 bot 只用 `drive.file` 權限，屬於非敏感範圍，發布不需要送 Google 審查
  3. 「憑證」→「建立憑證」→ OAuth 用戶端 ID，類型選 **桌面應用程式**，下載 JSON，存成專案根目錄的 `google-oauth-client.json`
  4. 把要備份到的 Drive 資料夾**共用**給你剛才登入的那個帳號（本來就是你自己的帳號，通常不用另外設定）
  5. 執行 `uv run python google_auth_setup.py`，會跳出瀏覽器完成一次性授權，產生 `google-token.json`

`google-oauth-client.json`、`google-token.json`、`.env` 都已加進 `.gitignore`，不會進版控。

## 部署到 Render（24 小時運作，不需要留著本機電腦開機）

專案已附上 `render.yaml`，Render 連上這個 repo 時會自動帶入建置/啟動指令。

1. 把這個 repo 推上 GitHub（Render 需要從 GitHub/GitLab 讀取程式碼）
2. 到 [Render](https://render.com/) 註冊帳號，**New** → **Blueprint**，選你剛推上去的 repo，它會讀到 `render.yaml` 自動帶入設定
3. 部署前會要求你手動填入以下環境變數（`render.yaml` 裡故意設 `sync: false`，避免把機密寫進版控）：
   - `LINE_CHANNEL_SECRET`
   - `LINE_CHANNEL_ACCESS_TOKEN`
   - `GOOGLE_DRIVE_FOLDER_ID`
   - `GOOGLE_OAUTH_TOKEN_JSON`：把本機 `google-token.json` 的**完整檔案內容**貼進去（單行 JSON 字串）。雲端環境的檔案系統不持久，不能只存本機檔案，所以改用環境變數保存
4. 部署完成後，Render 會給一個永久網址（例如 `https://line-bot-backup.onrender.com`）
5. 到 LINE Developers 後台，把 Webhook URL 改成 `https://<你的網址>/webhook`，並確認「Use webhook」是打開的

免費方案閒置一段時間會睡眠，收到訊息時幾秒內會自動喚醒，對這種低流量的個人 bot 完全夠用。

## 確認備份是否正常／備份突然停了

用瀏覽器打開 bot 的網址（例如 `https://line-bot-backup.onrender.com`）：

- 顯示「Google Drive 備份正常」：沒問題
- 顯示「Google Drive 備份目前無法使用」：後面會寫原因。最常見的是 `invalid_grant: Token has been expired or revoked`，
  代表 Google 授權失效（通常是 OAuth 同意畫面還停在「測試中」，token 7 天就過期）。處理方式：
  1. 照上面「本機開發」第 2 步，把 OAuth 同意畫面發布為**實際運作中**
  2. 本機重新執行 `uv run python google_auth_setup.py`，產生新的 `google-token.json`
  3. 到 Render 的 Environment 頁面，把 `GOOGLE_OAUTH_TOKEN_JSON` 換成新的檔案內容並儲存（會自動重新部署）

授權失效期間收到的檔案不會被備份，事後也補不回來，要自己從 LINE 另外存。

## 功能

| 訊息類型 | 行為 |
|---|---|
| 圖片／影片／語音／檔案 | 下載後備份到 Google Drive，依來源（群組名稱／私訊對象）分子資料夾，不回覆任何訊息 |
| 純文字 | 不處理 |

檔名格式：`時間戳記_訊息ID.副檔名`（一般檔案訊息會保留原始檔名）。
