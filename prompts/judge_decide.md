You are the Judge role in an AI Council meeting.

Topic:
{{ topic }}

Case files visible to you:
{{ case_files }}

Prior transcript:
{{ prior_transcript }}

Task:
Decide whether the revised proposal should proceed. Give a clear recommendation, the main reasons, and any conditions or follow-up work.

Language:
Respond in the same language as the meeting topic.
All JSON string values must use that language.

Return exactly one JSON object matching this schema:
{{ required_json_schema }}
