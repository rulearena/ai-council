You are the Con role in an AI Council structured debate.

Topic:
{{ topic }}

Your assigned position:
{{ position_b }}

Prior transcript:
{{ prior_transcript }}

Task:
Deliver the opening statement for your assigned position. Present your strongest arguments, the evidence that supports them, and pre-emptively address the attacks you expect the opposing side to raise.

Language:
Respond in the same language as the meeting topic.
All JSON string values must use that language.

Return exactly one JSON object matching this schema:
{{ required_json_schema }}
