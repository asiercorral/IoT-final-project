"""T-17: test call to the Euskalmet API.
Usage: python3 scripts/euskalmet_test.py <path>
Example: python3 scripts/euskalmet_test.py /euskalmet/geo/regions/basque_country/zones
"""
import json, os, pathlib, sys, time
import jwt, requests
from dotenv import load_dotenv

BASE = "https://api.euskadi.eus"

load_dotenv()
private_key = pathlib.Path(os.environ["EUSKALMET_PRIVATE_KEY"]).read_text()
now = int(time.time())
token = jwt.encode(
    {"aud": "met01.apikey", "iss": "PlantPulse", "iat": now, "exp": now + 3600,
     "version": "1.0.0", "email": os.environ["EUSKALMET_EMAIL"]},
    private_key, algorithm="RS256")

path = sys.argv[1]
r = requests.get(BASE + path, headers={"Authorization": f"Bearer {token}"}, timeout=15)
print("HTTP", r.status_code, "-", BASE + path)

if r.ok:
    name = sys.argv[2] if len(sys.argv) > 2 else "euskalmet_sample"
    out = pathlib.Path(f"docs/{name}.json")    
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(r.json(), indent=2, ensure_ascii=False), encoding="utf-8")
    print("saved", out)
else:
    print(r.text[:500])