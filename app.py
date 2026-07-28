import os
import tempfile

import speech_recognition as sr
from dotenv import load_dotenv
from flask import Flask, abort, request
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    MessagingApiBlob,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import AudioMessageContent, MessageEvent, TextMessageContent
from pydub import AudioSegment

load_dotenv()

app = Flask(__name__)

configuration = Configuration(access_token=os.environ["LINE_CHANNEL_ACCESS_TOKEN"])
handler = WebhookHandler(os.environ["LINE_CHANNEL_SECRET"])


@app.route("/")
def home():
    return "eco bot running"


@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK"


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=event.message.text)],
            )
        )


@handler.add(MessageEvent, message=AudioMessageContent)
def handle_audio(event):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        blob_api = MessagingApiBlob(api_client)

        # 下載語音檔
        audio_content = blob_api.get_message_content(event.message.id)

        # 存成暫存 m4a，轉成 wav
        with tempfile.NamedTemporaryFile(suffix=".m4a", delete=False) as f:
            f.write(audio_content)
            temp_m4a = f.name

        temp_wav = temp_m4a.replace(".m4a", ".wav")
        AudioSegment.from_file(temp_m4a, format="m4a").export(temp_wav, format="wav")

        # 語音辨識
        recognizer = sr.Recognizer()
        with sr.AudioFile(temp_wav) as source:
            audio_data = recognizer.record(source)

        try:
            text = recognizer.recognize_google(audio_data, language="zh-TW")
        except sr.UnknownValueError:
            text = "無法辨識語音內容"
        except sr.RequestError:
            text = "語音辨識服務發生錯誤"

        # 清理暫存檔
        os.unlink(temp_m4a)
        os.unlink(temp_wav)

        # 回傳辨識結果
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=text)],
            )
        )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
