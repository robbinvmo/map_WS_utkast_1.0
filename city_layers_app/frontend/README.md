# City Layers Frontend (Next.js + Leaflet)

## 1) Starta backend (FastAPI)

Kör från projektroten:

```powershell
cd C:\Users\robbin.modigh\Documents\city_layers\city_layers_app
python -m uvicorn api.main:app --reload --port 8000
```

## 2) Starta frontend

Kör i en ny terminal:

```powershell
cd C:\Users\robbin.modigh\Documents\city_layers\city_layers_app\frontend
copy .env.local.example .env.local
npm.cmd install
npm.cmd run dev
```

Öppna sedan [http://localhost:3000](http://localhost:3000).

## Vad som ingår i testversionen

- Alltid karta över Stockholm som standard.
- Sök plats + automatisk viewport-hämtning när kartan flyttas.
- Lagerfilter för kontor, service och kollektivtrafik.
- Granulära filter: cafe, restaurang, fast food, food court, office-typer, buss, tunnelbana, tåg, cykel.
- Karttema: Ljus / Mörk / Satellit.
- KPI-kort och enkelt transformationsindex.
- Koppling till backend-endpoints `/geocode`, `/osm/search` och `/osm/viewport`.
- Strukturerad JSON-cache för viewport lagras under `data/cache/viewport/`.
