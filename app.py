#!/usr/bin/env python3
"""
SG Primary School Map - Backend Server v2
Data: MOE School Directory + OneMap geocoding + SGSchooling ballot history
"""

import json, os, re, math, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import urllib.request
import urllib.parse

DATA_DIR = os.path.dirname(os.path.abspath(__file__))

# === LOAD DATA ===
SCHOOLS = json.loads(open(os.path.join(DATA_DIR, "schools.json"), encoding="utf-8").read())

PRESTIGE = {}
BALLOT_HISTORY = {}
try:
    with open(os.path.join(DATA_DIR, "prestige.json"), encoding="utf-8") as f:
        p = json.load(f)
        PRESTIGE = p.get("prestige", {})
        BALLOT_HISTORY = p.get("ballots", {})
except Exception as e:
    print(f"Warning: could not load prestige.json: {e}")

# Add CCA / programme data if present
CCA_DATA = {}
PROGRAMME_DATA = {}
try:
    with open(os.path.join(DATA_DIR, "cca.json"), encoding="utf-8") as f:
        CCA_DATA = json.load(f)
except FileNotFoundError:
    pass

try:
    with open(os.path.join(DATA_DIR, "programmes.json"), encoding="utf-8") as f:
        PROGRAMME_DATA = json.load(f)
except FileNotFoundError:
    pass

COORDS_CACHE = {}

# === UTILITIES ===

def extract_sg_postal(address):
    m = re.search(r'Singapore (\d{6})$', address)
    return m.group(1) if m else None


def onemap_search(query, retries=2):
    """Geocode via OneMap. Retries on network errors; negative results cached 60s."""
    cached = COORDS_CACHE.get(query)
    if cached is not None:
        coords, ts = cached
        if coords is not None or time.time() - ts < 60:
            return coords
        del COORDS_CACHE[query]
    url = f"https://www.onemap.gov.sg/api/common/elastic/search?searchVal={urllib.parse.quote(query)}&returnGeom=Y&getAddrDetails=Y&pageNum=1"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=5)
            data = json.loads(resp.read())
            if data.get("results"):
                r = data["results"][0]
                lat, lng = float(r["LATITUDE"]), float(r["LONGITUDE"])
                COORDS_CACHE[query] = ((lat, lng), time.time())
                return (lat, lng)
            break  # valid response, no match — don't retry
        except Exception as e:
            print(f"OneMap error for '{query}' (attempt {attempt + 1}/{retries}): {e}")
            time.sleep(0.3)
    COORDS_CACHE[query] = (None, time.time())
    return None


def parse_radius(params, default=2.0):
    try:
        r = float(params.get("radius", [default])[0])
        return r if 0 < r <= 10 else default
    except (ValueError, TypeError):
        return default


def norm_text(t):
    """Normalize for search matching: unify apostrophes, strip punctuation."""
    t = t.lower()
    t = re.sub(r"[\u2018\u2019`´]", "'", t)
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def haversine(lat1, lng1, lat2, lng2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


def school_id_by_name(name):
    nl = name.lower()
    for s in SCHOOLS:
        if s["id"] == nl or s["name"].lower() == nl:
            return s["id"]
    return None


def enrich_school(s, include_nearby=True, nearby_radius=1.0):
    """Attach prestige, ballot summary, and nearby schools to a school dict."""
    out = dict(s)
    pid = out.get("id", "")
    prestige = PRESTIGE.get(pid, {})
    out["prestige_tier"] = prestige.get("tier")
    out["prestige_label"] = prestige.get("label")
    out["ballot_summary"] = prestige.get("last_2c")
    out["avg_ratio_2c"] = prestige.get("avg_ratio_2c")
    out["ballot_3yr"] = prestige.get("ballot_3yr", 0)
    out["ballot_6yr"] = prestige.get("ballot_6yr", 0)
    
    # Compact recent ballots
    raw = BALLOT_HISTORY.get(pid, [])
    if raw:
        recent = []
        phase_order = ["1", "2A", "2A(1)", "2A(2)", "2B", "2C", "2C(S)"]
        for b in raw:
            phases = b.get("phases", {})
            pd = {}
            for ph in phase_order:
                d = phases.get(ph)
                if d:
                    pd[ph] = {
                        "vac": d.get("vac"),
                        "app": d.get("app"),
                        "ballot": d.get("ballot", False),
                        "ballot_cat": d.get("ballot_cat"),
                    }
            if pd:
                recent.append({"year": b.get("year"), "phases": pd})
        if recent:
            out["ballots"] = recent[-6:]  # last 6 years
    
    # CCA / programmes
    out["ccas"] = CCA_DATA.get(pid, [])
    out["programmes"] = PROGRAMME_DATA.get(pid, [])
    
    if include_nearby and out.get("lat") and out.get("lng"):
        nearby = []
        for s2 in SCHOOLS:
            if s2.get("id") == pid or not s2.get("lat"):
                continue
            d = haversine(out["lat"], out["lng"], s2["lat"], s2["lng"])
            if d <= nearby_radius:
                nearby.append({"id": s2["id"], "name": s2["name"], "distance_km": round(d, 2)})
        nearby.sort(key=lambda x: x["distance_km"])
        out["nearby_schools"] = nearby[:10]
    
    return out


# === HTTP HANDLER ===

class SchoolAPIHandler(BaseHTTPRequestHandler):
    def api_response(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "public, max-age=60")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    
    def do_GET(self):
        try:
            self._dispatch_get()
        except (BrokenPipeError, ConnectionResetError):
            pass  # client went away; nothing to do
        except Exception as e:
            print(f"Unhandled error for {self.path}: {e}")
            try:
                self.api_response({"error": "Internal server error"}, 500)
            except Exception:
                pass

    def _dispatch_get(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)
        
        if path == "/api/schools":
            self._serve_schools(params)
        elif path == "/api/search":
            self._serve_search(params)
        elif path == "/api/school":
            self._serve_school_detail(params)
        elif path == "/api/nearyou":
            self._serve_nearby(params)
        elif path == "/api/postal":
            self._serve_postal(params)
        elif path == "/api/compare":
            self._serve_compare(params)
        elif path == "/api/stats":
            self._serve_stats()
        elif path == "/api/health":
            self._serve_health()
        else:
            self.serve_static()
    
    def _serve_schools(self, params):
        tag = params.get("tag", [None])[0]
        q = params.get("q", [""])[0].lower().strip()
        stype = params.get("type", [None])[0]
        gender = params.get("gender", [None])[0]
        session = params.get("session", [None])[0]
        
        results = []
        for s in SCHOOLS:
            if tag and tag != "all":
                if tag == "top":
                    if s.get("id") not in PRESTIGE:
                        continue
                elif tag == "elite":
                    if PRESTIGE.get(s.get("id", ""), {}).get("tier", 99) > 1:
                        continue
                elif tag == "popular":
                    if PRESTIGE.get(s.get("id", ""), {}).get("tier", 99) > 2:
                        continue
                elif tag == "gep":
                    if "gep" not in s.get("tags", []):
                        continue
                elif tag == "sap":
                    if "sap" not in s.get("tags", []):
                        continue
                elif tag == "affiliated":
                    if "affiliated" not in s.get("tags", []):
                        continue
                elif tag == "girls":
                    if s.get("gender") != "Girls":
                        continue
                elif tag == "boys":
                    if s.get("gender") != "Boys":
                        continue
                elif tag not in s.get("tags", []):
                    continue
            
            if stype and s.get("type", "").lower() != stype.lower():
                continue
            if gender and s.get("gender", "").lower() != gender.lower():
                continue
            if session and s.get("session", "").lower().replace(" ", "") != session.lower().replace(" ", ""):
                continue
            
            if q:
                match = (q in s["name"].lower() or
                         q in s.get("address", "").lower() or
                         q in s.get("region", "").lower() or
                         q in s.get("mrt_desc", "").lower() or
                         q in " ".join(s.get("tags", [])).lower())
                if not match:
                    continue
            
            results.append(enrich_school(s, include_nearby=False))
        
        # Default sort by tier then name
        results.sort(key=lambda x: (x.get("prestige_tier") or 99, x["name"]))
        
        self.api_response({"total": len(results), "schools": results})
    
    def _serve_search(self, params):
        q = params.get("q", [""])[0].strip()
        if not q:
            self.api_response({"results": []})
            return
        
        coords = onemap_search(q)
        # OneMap sometimes needs a country hint for bare 6-digit postal codes
        if not coords and re.match(r'^\d{6}$', q):
            coords = onemap_search(f"Singapore {q}")
        nearby = []
        if coords:
            lat, lng = coords
            radius = parse_radius(params)
            for s in SCHOOLS:
                if s.get("lat") is None:
                    continue
                d = haversine(lat, lng, s["lat"], s["lng"])
                if d <= radius:
                    s_copy = enrich_school(s, include_nearby=False)
                    s_copy["distance_km"] = round(d, 2)
                    nearby.append(s_copy)
            nearby.sort(key=lambda x: x["distance_km"])
        
        direct = []
        ql = norm_text(q)
        if ql:
            for s in SCHOOLS:
                if ql in norm_text(s["name"]):
                    direct.append(enrich_school(s, include_nearby=False))
        
        self.api_response({
            "query": q,
            "coords": {"lat": coords[0], "lng": coords[1]} if coords else None,
            "nearby_schools": nearby[:30],
            "direct_matches": direct[:10]
        })
    
    def _serve_school_detail(self, params):
        sid = params.get("id", [None])[0]
        if not sid:
            self.api_response({"error": "No school id"}, 400)
            return
        
        school = next((s for s in SCHOOLS if s.get("id") == sid), None)
        if not school:
            self.api_response({"error": "Not found"}, 404)
            return
        
        self.api_response(enrich_school(school, include_nearby=True, nearby_radius=1.0))
    
    def _serve_postal(self, params):
        postal = params.get("code", [None])[0]
        if not postal or not re.match(r'^\d{6}$', postal):
            self.api_response({"error": "Need 6-digit postal code"}, 400)
            return
        
        coords = onemap_search(postal) or onemap_search(f"Singapore {postal}")
        if not coords:
            self.api_response({"error": "Could not find location for this postal code"}, 404)
            return
        
        lat, lng = coords
        radius = parse_radius(params)
        results = []
        for s in SCHOOLS:
            if s.get("lat") is None:
                continue
            d = haversine(lat, lng, s["lat"], s["lng"])
            if d <= radius:
                s_copy = enrich_school(s, include_nearby=False)
                s_copy["distance_km"] = round(d, 2)
                results.append(s_copy)
        
        results.sort(key=lambda x: x["distance_km"])
        self.api_response({
            "postal": postal,
            "lat": lat,
            "lng": lng,
            "radius_km": radius,
            "schools": results[:40],
            "count": len(results)
        })
    
    def _serve_nearby(self, params):
        lat = params.get("lat", [None])[0]
        lng = params.get("lng", [None])[0]
        if not lat or not lng:
            self.api_response({"error": "Need lat,lng"}, 400)
            return
        
        try:
            lat, lng = float(lat), float(lng)
        except ValueError:
            self.api_response({"error": "Invalid lat,lng"}, 400)
            return
        
        radius = parse_radius(params)
        results = []
        for s in SCHOOLS:
            if s.get("lat") is None:
                continue
            d = haversine(lat, lng, s["lat"], s["lng"])
            if d <= radius:
                s_copy = enrich_school(s, include_nearby=False)
                s_copy["distance_km"] = round(d, 2)
                results.append(s_copy)
        
        results.sort(key=lambda x: x["distance_km"])
        self.api_response({"lat": lat, "lng": lng, "radius_km": radius, "schools": results[:40], "count": len(results)})
    
    def _serve_compare(self, params):
        ids = params.get("ids", [""])[0]
        if not ids:
            self.api_response({"error": "Need ids"}, 400)
            return
        
        id_list = [x.strip() for x in ids.split(",") if x.strip()]
        schools = []
        for sid in id_list[:4]:
            s = next((x for x in SCHOOLS if x.get("id") == sid), None)
            if s:
                schools.append(enrich_school(s, include_nearby=False))
        
        self.api_response({"schools": schools})
    
    def _serve_stats(self):
        total = len(SCHOOLS)
        geocoded = sum(1 for s in SCHOOLS if s.get("lat"))
        with_prestige = sum(1 for s in SCHOOLS if PRESTIGE.get(s.get("id", "")))
        
        self.api_response({
            "total_schools": total,
            "geocoded": geocoded,
            "with_prestige": with_prestige,
            "tags": sorted(list({t for s in SCHOOLS for t in s.get("tags", [])})),
            "regions": sorted(list({s.get("region", "") for s in SCHOOLS if s.get("region")})),
        })
    
    def _serve_health(self):
        self.api_response({"status": "ok"})
    
    def serve_static(self):
        frontend_path = os.path.join(DATA_DIR, "frontend.html")
        with open(frontend_path, encoding="utf-8") as f:
            html = f.read()
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")  # always revalidate; users must get JS fixes
        self.end_headers()
        self.wfile.write(body)
    
    def log_message(self, format, *args):
        # NOTE: called with variable arg counts (requests: 3 args, errors: 2) — never index blindly
        try:
            msg = format % args if args else str(format)
        except Exception:
            msg = str(format)
        print(f"[{self.log_date_time_string()}] {msg}", flush=True)


if __name__ == "__main__":
    print(f"Starting SG Primary School Map v2 with {len(SCHOOLS)} schools ({sum(1 for s in SCHOOLS if s.get('lat'))} geocoded)")
    PORT = int(os.environ.get("PORT", 3456))

    class SchoolMapServer(ThreadingHTTPServer):
        daemon_threads = True
        request_queue_size = 64  # default 5 drops connections under bursts

    server = SchoolMapServer(("0.0.0.0", PORT), SchoolAPIHandler)
    print(f"🎒 Running at http://localhost:{PORT}")
    server.serve_forever()
