#!/usr/bin/env python3
"""
SG Primary School Map - Backend Server
Integrates OneMap, KiasuParents, and SGSchooling data.
Usage: python3 app.py
"""

import json, os, re, time, threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import urllib.request
import urllib.parse

# === DATA ===
# Combined school data: name, address, type, gender, tags
# Tags: sap, affiliated, girls, boys, methodist, catholic
SCHOOLS = json.loads(open(os.path.join(os.path.dirname(__file__), "schools.json")).read())

# === CACHED ONEMAP COORDS ===
COORDS_CACHE = {}

def extract_sg_postal(address):
    """Extract Singapore 6-digit postal code from address."""
    m = re.search(r'Singapore (\d{6})$', address)
    return m.group(1) if m else None


def onemap_search(query):
    """Search OneMap for coordinates. Caches results."""
    if query in COORDS_CACHE:
        return COORDS_CACHE[query]
    
    try:
        quoted = urllib.parse.quote(query)
        url = f"https://www.onemap.gov.sg/api/common/elastic/search?searchVal={quoted}&returnGeom=Y&getAddrDetails=Y&pageNum=1"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=5)
        data = json.loads(resp.read())
        
        if data.get("results"):
            r = data["results"][0]
            lat, lng = float(r["LATITUDE"]), float(r["LONGITUDE"])
            COORDS_CACHE[query] = (lat, lng)
            return (lat, lng)
    except Exception as e:
        print(f"OneMap error for '{query}': {e}")
    
    return None


def onemap_search_by_postal(address):
    """Search OneMap for coordinates using the postal code from the address.
    More accurate than name-based search."""
    postal = extract_sg_postal(address)
    if not postal:
        return None
    return onemap_search(postal)

def geocode_all_schools():
    """Geocode all schools that don't have coordinates yet."""
    count = sum(1 for s in SCHOOLS if s.get("lat") is None)
    if count == 0:
        print(f"All {len(SCHOOLS)} schools already geocoded!")
        return
    
    print(f"Geocoding {count} schools via OneMap...")
    for i, s in enumerate(SCHOOLS):
        if s.get("lat") is not None:
            continue
        
        # Try postal code first (most accurate), then full address, then name
        addr = s.get("address", "")
        if addr:
            result = onemap_search_by_postal(addr)
        if not result and addr:
            result = onemap_search(addr)
        if not result and s["name"]:
            result = onemap_search(s["name"])
        
        if result:
            s["lat"], s["lng"] = result
            print(f"  [{i+1}/{len(SCHOOLS)}] {s['name'][:30]:30s} -> {result}")
        else:
            print(f"  [{i+1}/{len(SCHOOLS)}] {s['name'][:30]:30s} -> NOT FOUND")
        
        if (i+1) % 10 == 0:
            time.sleep(0.5)  # Rate limit
    
    # Save coordinates back
    with open(os.path.join(os.path.dirname(__file__), "schools.json"), "w") as f:
        json.dump(SCHOOLS, f, indent=2)
    print(f"Saved {len(SCHOOLS)} schools to schools.json")

# === PRESTIGE / BALLOT DATA ===
# From SGSchooling - ballot history at Phase 2C (most competitive)
PRESTIGE = {}
BALLOT_HISTORY = {}

try:
    with open(os.path.join(os.path.dirname(__file__), "prestige.json")) as f:
        data = json.load(f)
        PRESTIGE = data.get("prestige", {})
        BALLOT_HISTORY = data.get("ballots", {})
except:
    print("No prestige.json found. Creating from known data...")
    # Will be populated from SGSchooling

def load_or_create_prestige():
    """Try to load prestige data, create from SGSchooling if not found."""
    try:
        with open(os.path.join(os.path.dirname(__file__), "prestige.json")) as f:
            return json.load(f)
    except:
        pass
    
    return {"prestige": {}, "ballots": {}}

# ============================================================
# HTTP SERVER
# ============================================================

def _enrich_school(s):
    """Attach prestige + compact ballot data to a school dict."""
    pid = s.get("id", "")
    s["prestige_tier"] = PRESTIGE.get(pid, {}).get("tier")
    s["prestige_label"] = PRESTIGE.get(pid, {}).get("label")
    s["ballot_summary"] = PRESTIGE.get(pid, {}).get("last_2c")
    raw = BALLOT_HISTORY.get(pid, [])
    if raw:
        recent = []
        phase_order = ["2A", "2A(1)", "2A(2)", "2B", "2C", "2C(S)"]
        for b in raw:
            phases = b.get("phases", {})
            pd = {}
            for ph in phase_order:
                d = phases.get(ph)
                if d:
                    pd[ph] = {"vac": d.get("vac"), "app": d.get("app"), "ballot": d.get("ballot", False)}
            if pd:
                recent.append({"year": b.get("year"), "phases": pd})
        if recent:
            s["ballots"] = recent
    return s

class SchoolAPIHandler(BaseHTTPRequestHandler):
    def api_response(self, data):
        """Send JSON response with proper HTTP headers."""
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "public, max-age=60")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    
    def do_GET(self):
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
        elif path == "/api/stats":
            self._serve_stats()
        else:
            # All other paths serve the frontend
            self.serve_static()
    
    def _serve_schools(self, params):
        tag = params.get("tag", [None])[0]
        q = params.get("q", [""])[0].lower()
        
        results = []
        for s in SCHOOLS:
            if tag and tag != "all":
                if tag == "top":
                    pid = s.get("id", "")
                    if pid not in PRESTIGE:
                        continue
                elif tag not in s.get("tags", []):
                    continue
            
            if q:
                if q not in s["name"].lower() and q not in s.get("address","").lower() and q not in s.get("region","").lower():
                    continue
            
            r = _enrich_school(dict(s))
            results.append(r)
        
        self.api_response({"total": len(results), "schools": results})
    
    def _serve_search(self, params):
        q = params.get("q", [""])[0].strip()
        if not q:
            self.api_response({"results": []})
            return
        
        # Search OneMap for address/property
        coords = onemap_search(q)
        
        # Find nearby schools
        nearby = []
        if coords:
            lat, lng = coords[0], coords[1]
            for s in SCHOOLS:
                if s.get("lat") is None:
                    continue
                d = haversine(lat, lng, s["lat"], s["lng"])
                if d <= 2.0:  # Within 2km
                    s_copy = _enrich_school(dict(s))
                    s_copy["distance_km"] = round(d, 2)
                    nearby.append(s_copy)
            
            nearby.sort(key=lambda x: x["distance_km"])
        
        # Also direct school name search
        direct = []
        ql = q.lower()
        for s in SCHOOLS:
            if ql in s["name"].lower():
                direct.append(s)
        
        self.api_response({"coords": coords, "nearby_schools": nearby[:20], "direct_matches": direct[:10]})
    
    def _serve_school_detail(self, params):
        sid = params.get("id", [None])[0]
        if not sid:
            self.api_response({"error": "No school id"})
            return
        
        school = None
        for s in SCHOOLS:
            if s.get("id") == sid:
                school = dict(s)
                break
        
        if not school:
            self.api_response({"error": "Not found"})
            return
        
        pid = school.get("id", "")
        school["prestige"] = PRESTIGE.get(pid, {})
        
        # Transform ballots into frontend-friendly format
        raw_ballots = BALLOT_HISTORY.get(pid, [])
        transformed = []
        for b in raw_ballots:
            yr = b.get("year")
            phases = b.get("phases", {})
            
            # Build a phase map dynamically for ALL available phases
            phase_order = ["2A", "2A(1)", "2A(2)", "2B", "2C", "2C(S)"]
            phase_data = {}
            for ph in phase_order:
                d = phases.get(ph, {})
                if d:
                    phase_data[ph] = {
                        "vac": d.get("vac"),
                        "app": d.get("app"),
                        "ballot": d.get("ballot", False)
                    }
            
            p2c = phases.get("2C", {})
            
            transformed.append({
                "year": yr,
                "phases": phase_data,
                "oversubscribed": p2c.get("ballot", False),
                "phase2c_applicants": p2c.get("app"),
                "phase2c_vacancies": p2c.get("vac"),
                "phase2b_applicants": phases.get("2B", {}).get("app"),
                "phase2b_vacancies": phases.get("2B", {}).get("vac"),
                "ratio": round(p2c.get("app", 0) / p2c.get("vac", 1), 2) if p2c.get("vac") else None,
            })
        school["ballots"] = transformed
        
        # Find nearby schools (within 1km)
        nearby = []
        if school.get("lat"):
            for s in SCHOOLS:
                if s.get("id") == sid or s.get("lat") is None:
                    continue
                d = haversine(school["lat"], school["lng"], s["lat"], s["lng"])
                if d <= 1.0:
                    nearby.append({"name": s["name"], "id": s["id"], "distance_km": round(d, 2)})
            nearby.sort(key=lambda x: x["distance_km"])
        school["nearby_schools"] = nearby[:8]
        
        self.api_response(school)
    
    def _serve_postal(self, params):
        postal = params.get("code", [None])[0]
        if not postal or not re.match(r'^\d{6}$', postal):
            self.api_response({"error": "Need 6-digit postal code"})
            return
        
        # Geocode via OneMap
        coords = onemap_search(postal)
        if not coords:
            # Try searching with 'Singapore' prefix
            coords = onemap_search(f"Singapore {postal}")
        
        if coords:
            lat, lng = coords
            results = []
            for s in SCHOOLS:
                if s.get("lat") is None:
                    continue
                d = haversine(lat, lng, s["lat"], s["lng"])
                if d <= 2.0:
                    s_copy = _enrich_school(dict(s))
                    s_copy["distance_km"] = round(d, 2)
                    results.append(s_copy)
            
            results.sort(key=lambda x: x["distance_km"])
            self.api_response({"postal": postal, "lat": lat, "lng": lng, "schools": results[:30], "count": len(results)})
        else:
            self.api_response({"error": "Could not find location for this postal code"})
    
    def _serve_nearby(self, params):
        lat = params.get("lat", [None])[0]
        lng = params.get("lng", [None])[0]
        
        if not lat or not lng:
            self.api_response({"error": "Need lat,lng"})
            return
        
        lat, lng = float(lat), float(lng)
        
        results = []
        for s in SCHOOLS:
            if s.get("lat") is None:
                continue
            d = haversine(lat, lng, s["lat"], s["lng"])
            if d <= 2.0:
                s_copy = _enrich_school(dict(s))
                s_copy["distance_km"] = round(d, 2)
                results.append(s_copy)
        
        results.sort(key=lambda x: x["distance_km"])
        self.api_response({"schools": results[:30], "count": len(results)})
    
    def _serve_stats(self):
        total = len(SCHOOLS)
        geocoded = sum(1 for s in SCHOOLS if s.get("lat"))
        with_prestige = sum(1 for s in SCHOOLS if PRESTIGE.get(s.get("id","")))
        
        self.api_response({"total_schools": total, "geocoded": geocoded, "with_prestige": with_prestige})
    
    def serve_static(self):
        """Serve frontend HTML/JS/CSS."""
        frontend_path = os.path.join(os.path.dirname(__file__), "frontend.html")
        with open(frontend_path) as f:
            html = f.read()
        
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    
    def log_message(self, format, *args):
        print(f"[{self.log_date_time_string()}] {args[0]} {args[1]} {args[2]}")


def haversine(lat1, lng1, lat2, lng2):
    """Distance in km between two lat/lng points."""
    import math
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


if __name__ == "__main__":
    DATA_DIR = os.path.dirname(__file__)
    
    # Load/create data files
    prestige_data = load_or_create_prestige()
    PRESTIGE = prestige_data.get("prestige", {})
    BALLOT_HISTORY = prestige_data.get("ballots", {})
    
    # Geocoding via OneMap - run manually if needed: python3 -c "from app import geocode_all_schools; geocode_all_schools()"
    print(f"Starting server with {len(SCHOOLS)} schools ({sum(1 for s in SCHOOLS if s.get('lat') is not None)} geocoded)")
    
    PORT = int(os.environ.get("PORT", 3456))
    server = HTTPServer(("0.0.0.0", PORT), SchoolAPIHandler)
    print(f"🎒 SG Primary School Map running at http://localhost:{PORT}")
    print(f"   Click the URL to open the interactive map!")
    server.serve_forever()
