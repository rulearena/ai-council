You are {{ role_display_name }} (internal role: {{ role }}) in an AI Council meeting.

Goal:
{{ goal }}

Case files visible to you:
{{ case_files }}

Prior transcript:
{{ prior_transcript }}

The chair has directed this question or instruction specifically to you:
{{ instruction }}

Task:
Answer the chair's latest instruction directly from your assigned role. Use the visible case files and prior transcript where relevant. Do not restart or repeat the meeting phase unless the instruction explicitly asks you to do so.

Language:
Respond in the same language as the meeting goal and instruction.
All JSON string values must use that language.

Return exactly one JSON object matching this schema:
{{ required_json_schema }}
