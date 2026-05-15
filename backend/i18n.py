from __future__ import annotations

from os import getenv

from dotenv import load_dotenv


load_dotenv()

DEFAULT_LOCALE = "zh_HK"

_MESSAGES = {
    "zh_HK": {
        "channels.evolution.duplicate_message_skipped": "已略過短時間內重覆收到的 WhatsApp 訊息",
        "channels.evolution.invalid_media_type": "訊息媒體類型必須是 image、video、audio 或 document",
        "channels.evolution.missing_global_api_key": "需要設定 EVOLUTION_API_KEY 或 whatsapp_key",
        "channels.evolution.missing_whatsapp_instance": "需要設定 whatsapp_instance",
        "channels.evolution.missing_whatsapp_key": "需要設定 whatsapp_key",
        "channels.evolution.receive_handler_failed": "WhatsApp 訊息處理器執行失敗",
        "main.db_health_check_failed": "資料庫連線檢查失敗",
        "main.db_health_check_ok": "資料庫連線檢查成功",
        "main.shutdown_complete": "服務已關閉",
        "main.shutdown_requested": "收到關閉訊號",
        "main.startup": "agent-server background worker 啟動中",
        "main.whatsapp_listener_started": "WhatsApp Global WebSocket listener 已啟動",
        "main.whatsapp_message_received": "收到 WhatsApp 訊息：instance=%s message_id=%s remote_jid=%s phone_no=%s content_type=%s has_text=%s has_media=%s",
    },
    "en": {
        "channels.evolution.duplicate_message_skipped": "Skipped duplicated WhatsApp message received within the TTL window",
        "channels.evolution.invalid_media_type": "Message media type must be image, video, audio, or document",
        "channels.evolution.missing_global_api_key": "EVOLUTION_API_KEY or whatsapp_key is required",
        "channels.evolution.missing_whatsapp_instance": "whatsapp_instance is required",
        "channels.evolution.missing_whatsapp_key": "whatsapp_key is required",
        "channels.evolution.receive_handler_failed": "WhatsApp receive handler failed",
        "main.db_health_check_failed": "Database health check failed",
        "main.db_health_check_ok": "Database health check completed",
        "main.shutdown_complete": "Services shut down",
        "main.shutdown_requested": "Shutdown signal received",
        "main.startup": "Starting agent-server background worker",
        "main.whatsapp_listener_started": "WhatsApp Global WebSocket listener started",
        "main.whatsapp_message_received": "WhatsApp message received: instance=%s message_id=%s remote_jid=%s phone_no=%s content_type=%s has_text=%s has_media=%s",
    },
}


def get_locale() -> str:
    return getenv("LANG_LOCALE", DEFAULT_LOCALE) or DEFAULT_LOCALE


def t(message_key: str) -> str:
    locale = get_locale()
    messages = _MESSAGES.get(locale) or _MESSAGES[DEFAULT_LOCALE]
    return messages.get(message_key) or _MESSAGES[DEFAULT_LOCALE].get(message_key, message_key)
