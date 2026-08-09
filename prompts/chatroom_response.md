# Chatroom response contract

Role: {{ role_display_name }} ({{ role }})
Goal: {{ goal }}
Current instruction: {{ instruction }}
Recent transcript: {{ prior_transcript }}

This template name identifies the message-only `chat-message/v1` response contract.
The runner owns the canonical system/developer/user layers so provider adapters receive
the same pre-transport messages. Chatroom Slice 2 context is limited to the current
instruction, an optional quote, and recent transcript; source bodies are selected only
by the later source contract.

Use natural conversational sentences, useful Markdown when appropriate, and avoid fixed
report headings. Return exactly this schema:
{{ required_json_schema }}
