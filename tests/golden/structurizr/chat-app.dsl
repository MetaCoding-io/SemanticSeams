# Structurizr DSL workspace of the model's C4 layer, written by the seams_gen structurizr generator (ADR-0044). Regenerate it with `seams generate`; do not edit it.
# gap: select_conversation has no seam:governedBy policy with an odrl:assignee (on it, its operation or the user task its form completes), so no person uses it
workspace {
    model {
        authenticated_user = person "Authenticated users"
        chat_system = softwareSystem "LLM Chat App" {
            chat_api = container "Chat API" "" "FastAPI, SSE streaming"
            chat_ui = container "Chat Web Interface" "" "htmx + server-rendered fragments"
            llm_gateway = container "LLM Provider Gateway" "" "OpenAI-compatible API proxy"
            message_db = container "Message Store" "" "PostgreSQL"
        }
        authenticated_user -> chat_ui "send_message"
        chat_api -> llm_gateway "depends on"
        chat_api -> message_db "depends on"
        chat_ui -> chat_api "list_conversations_op, message_thread_op, send_message_op, stream_events"
    }
    views {
        systemContext chat_system "chat_system-context" {
            include *
            autoLayout
        }
        container chat_system "chat_system-containers" {
            include *
            autoLayout
        }
    }
}
