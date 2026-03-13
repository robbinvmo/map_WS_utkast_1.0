# Deploy till GitHub + Netlify + Render

## 1. Push till GitHub

Kör från repo-roten:

```powershell
git add .
git commit -m "Prepare deploy for netlify and render"
git push
```

## 2. Deploy frontend på Netlify

1. Skapa ny site i Netlify och koppla GitHub-repot.
2. Netlify läser `netlify.toml` automatiskt:
   - Base: `city_layers_app/frontend`
   - Build command: `npm run build`
3. Sätt environment variable i Netlify:
   - `NEXT_PUBLIC_API_BASE_URL=https://<din-render-backend>.onrender.com`
4. Deploya.

## 3. Deploy backend på Render

1. Skapa ny **Web Service** från samma GitHub-repo.
2. Render läser `render.yaml` automatiskt.
3. Lägg till env vars i Render (om du använder TravelTime):
   - `TRAVELTIME_APP_ID`
   - `TRAVELTIME_API_KEY`
4. Deploya och kontrollera:
   - `https://<din-render-backend>.onrender.com/health`

## 4. CORS

Backend accepterar nu:

- `localhost` (3000-3004)
- `*.netlify.app` automatiskt
- extra origins via `CORS_ALLOWED_ORIGINS` (kommaseparerad lista)

Om du vill ändra regex för tillåtna domäner:

- `CORS_ALLOW_ORIGIN_REGEX`

