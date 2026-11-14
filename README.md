# Flame in Freefall

Fire-hazard explorer for spacecraft cabins, built on NASA BASS-II microgravity combustion data (PSI-25, DOI 10.60555/4qc4-de67).

- `index.html` – the whole dashboard (works on its own; the assistant falls back to built-in answers)
- `api/chat.js` – serverless backend for the AI assistant (any OpenAI-compatible API)
- `clean_bass2.py` – cleans the raw BASS-II experimental table

## Deploy (Vercel)
1. Push this folder to a GitHub repo.
2. Import the repo at vercel.com/new (no build settings needed).
3. Add environment variable `LLM_API_KEY` (and optionally `LLM_BASE_URL`, `LLM_MODEL`; defaults: Groq, `llama-3.3-70b-versatile`).
4. Redeploy. The assistant badge shows "AI mode" when the key works.

## AI disclosure
Code in this repository was written with AI assistance (Anthropic Claude). Hazard ratings come from a deterministic model over the test data; the language model only interprets questions and explains results. Not affiliated with or endorsed by NASA.
