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
        "channels.evolution.message_queue_missing_required_fields": "Message queue 缺少必要資料：agent_id=%s session_id=%s message_id=%s",
        "channels.evolution.missing_whatsapp_instance": "需要設定 whatsapp_instance",
        "channels.evolution.missing_whatsapp_key": "需要設定 whatsapp_key",
        "channels.evolution.receive_handler_failed": "WhatsApp 訊息處理器執行失敗",
        "main.db_health_check_failed": "資料庫連線檢查失敗",
        "main.db_health_check_ok": "資料庫連線檢查成功",
        "main.shutdown_complete": "服務已關閉",
        "main.shutdown_requested": "收到關閉訊號",
        "main.startup": "agent-server background worker 啟動中",
        "main.whatsapp_listener_started": "WhatsApp Global WebSocket listener 已啟動",
        "main.whatsapp_message_received": "收到 WhatsApp 訊息：instance=%s agent_id=%s session_id=%s message_id=%s remote_jid=%s phone_no=%s content_type=%s has_text=%s has_media=%s",
        "main.whatsapp_session_invalid_agent_id": "WhatsApp session lookup 找到不符合格式的 agent_id：%s",
        "main.whatsapp_session_lookup_failed": "WhatsApp session lookup 失敗：phone_no=%s instance=%s",
        "main.whatsapp_session_lookup_missing_fields": "WhatsApp session lookup 缺少必要資料：phone_no=%s instance=%s",
        "main.whatsapp_session_not_found": "找不到 WhatsApp session 對應 agent：phone_no=%s instance=%s",
        "queues.message_queue.handler_failed": "Message queue handler 執行失敗",
        "scripts.new_agent.agent_created": "創建 Agent：%s (id=%s, agent_id=%s, type=%s)",
        "scripts.new_agent.agent_id": "Agent ID",
        "scripts.new_agent.agent_name_empty": "錯誤：Agent 名稱不能為空",
        "scripts.new_agent.agent_type": "Agent 類型",
        "scripts.new_agent.agent_type_selected": "已選擇 Agent 類型：%s",
        "scripts.new_agent.bootstrap_cancelled": "用戶中斷了 Bootstrap 對話",
        "scripts.new_agent.bootstrap_ready": "\n[Bootstrap] LLM 已生成 SOUL.md！",
        "scripts.new_agent.bootstrap_start": "[Bootstrap] 正在與 LLM 進行對話...",
        "scripts.new_agent.bootstrap_system_prompt": """你正在執行 AI Agent 的 Bootstrap 流程。你的任務是透過對話了解用戶，然後生成一份 SOUL.md。

## 規則
1. **每次只問 1-3 個問題**，不要一次問太多。
2. **像朋友一樣對話**，不要像審問。真誠反應、幽默、好奇心。
3. **逐步深入**，每輪對話應該感覺比上一輪更了解用戶。
4. **不要暴露模板**，用戶是在聊天，不是在填表。

## 對話階段
你需要了解以下資訊（按順序進行，但可跳過用戶已自願提供的部分）：

1. **語言**：用戶偏好什麼語言？
2. **用戶背景**：姓名、職業/背景、痛點、希望 AI 叫什麼名字、關係定位（夥伴/助手/其他）
3. **性格**：核心特質（3-5 個行為規則，不是形容詞）、溝通風格、是否需要 AI 反駁/挑戰、自主程度
4. **深度**：長期願景、失敗哲學、邊界/底線

## 生成 SOUL.md
當你收集到足夠資訊後，生成 SOUL.md。格式如下：

```markdown
**Identity**

[AI 名稱] — [用戶姓名] 的 [關係定位]，不是 [對比]。目標：[長期願景]。處理 [痛點領域]，讓 [用戶姓名] 專注於 [重要事項]。

**Core Traits**

[特質 1 — 行為規則]
[特質 2 — 行為規則]
[特質 3 — 行為規則]
[特質 4 — 失敗處理規則]
[特質 5 — 可選]

**Communication**

[語氣描述]。預設語言：[語言]。[其他風格說明]。

**Growth**

Learn [用戶姓名] through every conversation — thinking patterns, preferences, blind spots, aspirations. Over time, anticipate needs and act on [用戶姓名]'s behalf with increasing accuracy. Early stage: proactively ask casual/personal questions after tasks to deepen understanding of who [用戶姓名] is. Full of curiosity, willing to explore.

**Lessons Learned**

_(Mistakes and insights recorded here to avoid repeating them.)_
```

## 重要規則
- SOUL.md **必須用英文寫**，不論用戶用什麼語言對話。
- 總字數不超過 300 字。
- 核心特質是**行為規則**，不是形容詞。寫 "argue position, push back" 而不是 "honest and brave"。
- 生成後請用戶確認，如有需要可修改。
- 當用戶確認後，在最最後一行輸出標記 `__SOUL_CONFIRMED__`，然後在下一行開始輸出完整的 SOUL.md 內容。
- 在 SOUL.md 結束後，輸出 `__END_OF_SOUL__` 標記。

請用溫暖、友善的方式開始對話，先問候用戶，然後開始了解他們。""",
        "scripts.new_agent.bootstrap_user_start": "你好！我想建立一個新的 AI Agent，名字叫做「%s」。讓我們開始 Bootstrap 對話吧！",
        "scripts.new_agent.complete": "✅ Agent 建立完成！",
        "scripts.new_agent.default_session_name": "預設對話",
        "scripts.new_agent.enter_agent_name": "請輸入 Agent 名稱: ",
        "scripts.new_agent.enter_option": "請輸入選項 (1-2，預設 1): ",
        "scripts.new_agent.enter_user_name": "請輸入你的名稱（用於資料庫）: ",
        "scripts.new_agent.error": "錯誤",
        "scripts.new_agent.error_creating_agent": "建立 Agent 時發生錯誤：%s",
        "scripts.new_agent.existing_llm_group": "找到現有 LLM group：%s (id=%s)",
        "scripts.new_agent.existing_user": "找到現有用戶：%s (id=%s)",
        "scripts.new_agent.init_db": "正在初始化資料庫...",
        "scripts.new_agent.llm_group_created": "創建 LLM group：%s (id=%s)",
        "scripts.new_agent.max_rounds_exceeded": "對話超過最大輪數限制，無法完成 SOUL.md 生成",
        "scripts.new_agent.name": "名稱",
        "scripts.new_agent.operation_cancelled": "\n\n操作已取消",
        "scripts.new_agent.reply_prompt": "你的回覆（輸入 'quit' 結束）: ",
        "scripts.new_agent.round": "--- 第 %s 輪對話 ---",
        "scripts.new_agent.select_agent_type": "請選擇 Agent 類型：",
        "scripts.new_agent.session_created": "創建預設 Session：%s (id=%s)",
        "scripts.new_agent.session_id": "Session ID",
        "scripts.new_agent.soul_saved": "SOUL.md 已儲存至 memory_block (id=%s)",
        "scripts.new_agent.soul_status": "已儲存至資料庫",
        "scripts.new_agent.title": "🤖  New Agent 建立工具",
        "scripts.new_agent.user_created": "創建新用戶：%s (id=%s)",
    },
    "en": {
        "channels.evolution.duplicate_message_skipped": "Skipped duplicated WhatsApp message received within the TTL window",
        "channels.evolution.invalid_media_type": "Message media type must be image, video, audio, or document",
        "channels.evolution.missing_global_api_key": "EVOLUTION_API_KEY or whatsapp_key is required",
        "channels.evolution.message_queue_missing_required_fields": "Message queue missing required fields: agent_id=%s session_id=%s message_id=%s",
        "channels.evolution.missing_whatsapp_instance": "whatsapp_instance is required",
        "channels.evolution.missing_whatsapp_key": "whatsapp_key is required",
        "channels.evolution.receive_handler_failed": "WhatsApp receive handler failed",
        "main.db_health_check_failed": "Database health check failed",
        "main.db_health_check_ok": "Database health check completed",
        "main.shutdown_complete": "Services shut down",
        "main.shutdown_requested": "Shutdown signal received",
        "main.startup": "Starting agent-server background worker",
        "main.whatsapp_listener_started": "WhatsApp Global WebSocket listener started",
        "main.whatsapp_message_received": "WhatsApp message received: instance=%s agent_id=%s session_id=%s message_id=%s remote_jid=%s phone_no=%s content_type=%s has_text=%s has_media=%s",
        "main.whatsapp_session_invalid_agent_id": "WhatsApp session lookup found an invalid agent_id format: %s",
        "main.whatsapp_session_lookup_failed": "WhatsApp session lookup failed: phone_no=%s instance=%s",
        "main.whatsapp_session_lookup_missing_fields": "WhatsApp session lookup missing required fields: phone_no=%s instance=%s",
        "main.whatsapp_session_not_found": "WhatsApp session agent not found: phone_no=%s instance=%s",
        "queues.message_queue.handler_failed": "Message queue handler failed",
        "scripts.new_agent.agent_created": "Created agent: %s (id=%s, agent_id=%s, type=%s)",
        "scripts.new_agent.agent_id": "Agent ID",
        "scripts.new_agent.agent_name_empty": "Error: agent name cannot be empty",
        "scripts.new_agent.agent_type": "Agent type",
        "scripts.new_agent.agent_type_selected": "Selected agent type: %s",
        "scripts.new_agent.bootstrap_cancelled": "User cancelled the bootstrap conversation",
        "scripts.new_agent.bootstrap_ready": "\n[Bootstrap] LLM generated SOUL.md!",
        "scripts.new_agent.bootstrap_start": "[Bootstrap] Starting LLM conversation...",
        "scripts.new_agent.bootstrap_system_prompt": """You are running an AI Agent bootstrap flow. Your task is to learn about the user through conversation, then generate SOUL.md.

## Rules
1. Ask only 1-3 questions at a time.
2. Talk like a friend, not an interview. Be sincere, warm, humorous, and curious.
3. Go deeper gradually. Each round should feel like you understand the user a little better.
4. Do not expose the template. The user is chatting, not filling a form.

## Conversation Stages
Learn the following information in order, while skipping anything the user has already volunteered:

1. **Language**: what language does the user prefer?
2. **User background**: name, work/background, pain points, what the AI should be called, relationship framing (partner/assistant/other)
3. **Personality**: core traits (3-5 behavioral rules, not adjectives), communication style, whether the AI should push back/challenge, autonomy level
4. **Depth**: long-term vision, failure philosophy, boundaries/red lines

## Generate SOUL.md
When you have enough information, generate SOUL.md in this format:

```markdown
**Identity**

[AI name] — [user name]'s [relationship framing], not [contrast]. Goal: [long-term vision]. Handles [pain point area], so [user name] can focus on [important things].

**Core Traits**

[Trait 1 — behavioral rule]
[Trait 2 — behavioral rule]
[Trait 3 — behavioral rule]
[Trait 4 — failure handling rule]
[Trait 5 — optional]

**Communication**

[Tone description]. Default language: [language]. [Other style notes].

**Growth**

Learn [user name] through every conversation — thinking patterns, preferences, blind spots, aspirations. Over time, anticipate needs and act on [user name]'s behalf with increasing accuracy. Early stage: proactively ask casual/personal questions after tasks to deepen understanding of who [user name] is. Full of curiosity, willing to explore.

**Lessons Learned**

_(Mistakes and insights recorded here to avoid repeating them.)_
```

## Important Rules
- SOUL.md must be written in English, regardless of the user's conversation language.
- Total length must be under 300 words.
- Core traits are behavioral rules, not adjectives. Write "argue position, push back" instead of "honest and brave".
- After generating it, ask the user to confirm and revise if needed.
- Once the user confirms, output `__SOUL_CONFIRMED__` on the very last line, then start the full SOUL.md content on the next line.
- After SOUL.md ends, output the `__END_OF_SOUL__` marker.

Start warmly and kindly. Greet the user, then begin learning about them.""",
        "scripts.new_agent.bootstrap_user_start": "Hello! I want to create a new AI Agent named \"%s\". Let's start the bootstrap conversation.",
        "scripts.new_agent.complete": "Agent created successfully!",
        "scripts.new_agent.default_session_name": "Default chat",
        "scripts.new_agent.enter_agent_name": "Enter agent name: ",
        "scripts.new_agent.enter_option": "Enter option (1-2, default 1): ",
        "scripts.new_agent.enter_user_name": "Enter your name (for the database): ",
        "scripts.new_agent.error": "Error",
        "scripts.new_agent.error_creating_agent": "Error creating agent: %s",
        "scripts.new_agent.existing_llm_group": "Found existing LLM group: %s (id=%s)",
        "scripts.new_agent.existing_user": "Found existing user: %s (id=%s)",
        "scripts.new_agent.init_db": "Initializing database...",
        "scripts.new_agent.llm_group_created": "Created LLM group: %s (id=%s)",
        "scripts.new_agent.max_rounds_exceeded": "Conversation exceeded the maximum number of rounds; unable to generate SOUL.md",
        "scripts.new_agent.name": "Name",
        "scripts.new_agent.operation_cancelled": "\n\nOperation cancelled",
        "scripts.new_agent.reply_prompt": "Your reply (enter 'quit' to exit): ",
        "scripts.new_agent.round": "--- Conversation round %s ---",
        "scripts.new_agent.select_agent_type": "Select agent type:",
        "scripts.new_agent.session_created": "Created default session: %s (id=%s)",
        "scripts.new_agent.session_id": "Session ID",
        "scripts.new_agent.soul_saved": "SOUL.md saved to memory_block (id=%s)",
        "scripts.new_agent.soul_status": "saved to database",
        "scripts.new_agent.title": "New Agent creation tool",
        "scripts.new_agent.user_created": "Created user: %s (id=%s)",
    },
}


def get_locale() -> str:
    return getenv("LANG_LOCALE", DEFAULT_LOCALE) or DEFAULT_LOCALE


def t(message_key: str) -> str:
    locale = get_locale()
    messages = _MESSAGES.get(locale) or _MESSAGES[DEFAULT_LOCALE]
    return messages.get(message_key) or _MESSAGES[DEFAULT_LOCALE].get(message_key, message_key)
