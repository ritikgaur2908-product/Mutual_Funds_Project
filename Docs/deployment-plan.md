# Deployment Plan: Vercel & Railway

This document outlines the deployment strategy for the HDFC Mutual Fund FAQ Assistant. The architecture splits the application across three platforms:

1. **Frontend**: Vercel (Optimized for Next.js)
2. **Backend**: Railway (Optimized for Python FastAPI & Vector DB)
3. **Data Scheduler**: GitHub Actions (Daily Scraping & Re-indexing)

---

## 1. Backend Deployment (Railway)

Railway is used to host the FastAPI backend because it provides a persistent environment suitable for Python, unlike Vercel's serverless functions which have strict execution timeouts and bundle size limits.

### Prerequisites
- Create an account on [Railway.app](https://railway.app/).
- Ensure your repository is pushed to GitHub.

### Deployment Steps
1. In the Railway dashboard, click **New Project** → **Deploy from GitHub repo**.
2. Select the `Grow` repository.
3. Railway will automatically detect the `requirements.txt` file in the root directory and use the Python builder.
4. **Environment Variables**: Go to the **Variables** tab and add:
   - `GEMINI_API_KEY` = `<your-gemini-key>`
   - `GROQ_API_KEY` = `<your-groq-key>`
   - `ADMIN_TOKEN` = `<your-admin-secret>`
   - `PORT` = `8000` (Optional, Railway usually handles this)
5. **Start Command**: Go to the **Settings** tab. Under **Deploy** -> **Custom Start Command**, enter:
   ```bash
   uvicorn api.main:app --host 0.0.0.0 --port $PORT
   ```
6. **Generate Public Domain**: In the **Settings** tab under **Networking**, click **Generate Domain** to get your public API URL (e.g., `https://grow-backend.up.railway.app`).

---

## 2. Frontend Deployment (Vercel)

Vercel is the optimal hosting platform for the Next.js frontend.

### Prerequisites
- Create an account on [Vercel.com](https://vercel.com).
- Copy the Railway API public URL generated in the previous step.

### Deployment Steps
1. In the Vercel dashboard, click **Add New...** → **Project**.
2. Import the `Grow` repository.
3. **Configure Project**:
   - **Framework Preset**: Next.js
   - **Root Directory**: Select `frontend`
4. **Environment Variables**: Add your backend URL:
   - `NEXT_PUBLIC_API_URL` = `https://grow-backend.up.railway.app`
5. Click **Deploy**.

### Optimization: Prevent Unnecessary Frontend Builds
Because the GitHub Actions scheduler pushes database updates to the `chroma_db/` folder every day at 10:00 AM IST, Vercel will automatically try to rebuild the frontend on every commit. To save Vercel build minutes, we should configure it to ignore backend-only commits.

1. Go to your Vercel Project **Settings** → **Git**.
2. Scroll to **Ignored Build Step**.
3. Select **Command** and enter:
   ```bash
   git diff --quiet HEAD^ HEAD ./
   ```
   *Since the Vercel root directory is `frontend`, this command ensures Vercel only rebuilds if files inside the `frontend/` folder were changed.*

---

## 3. Daily Data Refresh (GitHub Actions)

We have already configured the `.github/workflows/reindex.yml` file to run daily at 10:00 AM IST.

### How it integrates with Deployment:
1. **04:30 UTC (10:00 AM IST)**: GitHub Actions wakes up and runs `run_ingestion.py`.
2. **Scraping & Indexing**: The pipeline fetches the latest NAV and returns, recreating the NumPy vector store inside `chroma_db/`.
3. **Commit & Push**: The workflow commits the updated `chroma_db/` files and pushes them to the `main` branch.
4. **Auto-Redeploy**:
   - **Railway** detects the new commit and automatically pulls the latest `chroma_db/` files, restarting the FastAPI server to serve the fresh data.
   - **Vercel** detects the commit, but skips the build (thanks to the Ignored Build Step) since the frontend UI hasn't changed.

### Required Setup
Ensure the GitHub Actions runner has the environment variables it needs to generate embeddings during the run.
1. Go to your GitHub Repository **Settings** → **Secrets and variables** → **Actions**.
2. Add the following **Repository Secrets**:
   - `GEMINI_API_KEY`
   - `GROQ_API_KEY`
3. Go to **Settings** → **Actions** → **General** -> **Workflow permissions**.
4. Ensure **Read and write permissions** is selected so the action can push the updated database back to the repo.

---

## 4. Verification Check
- Visit the Vercel frontend URL.
- Ask a factual question (e.g., *"What is the exit load for HDFC Defence Fund?"*).
- The frontend will send the request to the Railway backend, which will query the vector database and return the correct answer along with the source citation.
