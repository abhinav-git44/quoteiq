# Deploy QuoteIQ (about 30–45 minutes)

You'll end up with three links: a **GitHub repo**, an **API on Render**, and a **frontend on Vercel**. The frontend is the "live link" you send.

## 0. What you need
- A GitHub account, a [Render](https://render.com) account and a [Vercel](https://vercel.com) account (sign in to both with GitHub).
- A **free Google Gemini API key** from [aistudio.google.com](https://aistudio.google.com) → **Get API key → Create API key**. No card needed. (An Anthropic key also works if you have credit.)
- Free-tier caveats: only a few requests per minute (the app waits and retries automatically, so first-time extraction takes about 5–10 minutes instead of 2), a daily request cap, and Google may use free-tier inputs to improve its models (fine here: the data is synthetic).
- Render cost: the database is free; the API needs the **Starter** plan (about $7/month) for the persistent disk. On the free plan it works, but uploaded files are lost whenever the service restarts.

## 1. Push the code to GitHub
```bash
unzip quoteiq.zip && cd quoteiq
git init && git add . && git commit -m "QuoteIQ: Aerchain PM assignment"
# Create an EMPTY repo named quoteiq on github.com (no README), then:
git branch -M main
git remote add origin https://github.com/<your-username>/quoteiq.git
git push -u origin main
```
That repo URL is your **code link**. `.env` is git-ignored; never commit your key.

## 2. API + database on Render
1. Render dashboard → **New → Blueprint** → connect the `quoteiq` repo. Render reads `render.yaml` and creates `quoteiq-db` and `quoteiq-api`.
2. When prompted for env vars:
   - `GEMINI_API_KEY`: your free Google AI Studio key
   - `CORS_ORIGINS`: leave blank for now (any `*.vercel.app` URL is already allowed)
3. Deploy. The first build takes about 8–10 minutes (Python dependencies and Tesseract).
4. On first start the container runs migrations, seeds the demo and **runs the real AI extraction** on the 5 quotes and 5 certificates. Watch the logs for `job ... done`. On the Gemini free tier this takes about 5–10 minutes, because of rate limits ("retrying in Ns" lines are normal).
5. Open `https://quoteiq-api.onrender.com/api/health` (your URL may differ). You should see `"ai_enabled": true`.

## 3. Frontend on Vercel
1. Vercel → **Add New → Project** → import the `quoteiq` repo.
2. **Root Directory:** `frontend` (important). The framework is detected as Next.js.
3. Environment variable: `NEXT_PUBLIC_API_URL` = your Render API URL, e.g. `https://quoteiq-api.onrender.com`.
4. Deploy. If the build fails on a TypeScript error, the log shows the file and line; fix it, push, and Vercel redeploys.
5. Your **live link** is the URL Vercel gives you, e.g. `https://quoteiq-xyz.vercel.app`.
6. Optional: set Render's `CORS_ORIGINS` to that exact URL and redeploy the API.

## 4. Check it before you send it
Log in with `buyer@kaveri.example` / `quoteiq-demo`, then check that:
- [ ] The dashboard shows 5 submissions
- [ ] Submissions shows the extraction statuses as Needs review / Succeeded (not AI unavailable)
- [ ] The comparison shows 30 rows, and clicking a cell opens the trace and source
- [ ] The analyst answers the VP split question with tool calls
- [ ] Award: the discount-aware scenario runs, and the Award PDF downloads

Also run `python scripts/eval_extraction.py` locally (instructions in the README) and note the silent-error number for your document.

## 5. Record the walkthrough
Follow `docs/DEMO_SCRIPT.md` (10 minutes). Record with Loom on the live Vercel URL.

## Troubleshooting
| Symptom | Fix |
|---|---|
| Frontend shows "Failed to fetch" | `NEXT_PUBLIC_API_URL` is wrong or the API is asleep (the free plan sleeps; first request takes about 50 s). Redeploy Vercel after changing the env var. |
| CORS error in the browser console | Add your Vercel URL to `CORS_ORIGINS` on Render. |
| Extraction shows `AI_UNAVAILABLE` | `GEMINI_API_KEY` is missing on Render. Add it, then click the retry icon on each document in Submissions. |
| `FAILED` with HTTP 404 / "model not found" | Set `GEMINI_MODEL` to a model listed in AI Studio (for example a current Flash model) and retry. |
| `FAILED` "quota may be exhausted" | Free daily cap reached: wait until it resets (midnight US Pacific, 1:30 PM IST), or use a second Google account's key. |
| Analyst answers are slow | Each question makes several calls, and the free tier allows only a few per minute. Ask one question at a time during the demo. |
| Need to re-seed | Render shell: `python /app/scripts/seed_demo.py --reset --extract` |
