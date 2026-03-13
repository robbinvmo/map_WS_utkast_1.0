from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"
STORE_DIR = DATA_DIR / "store"
BOUNDARIES_DIR = DATA_DIR / "boundaries"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
STORE_DIR.mkdir(parents=True, exist_ok=True)
BOUNDARIES_DIR.mkdir(parents=True, exist_ok=True)

TRAVELTIME_APP_ID = os.getenv("TRAVELTIME_APP_ID", "")
TRAVELTIME_API_KEY = os.getenv("TRAVELTIME_API_KEY", "")

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "CityLayersApp/1.0 (personal analysis project)"
