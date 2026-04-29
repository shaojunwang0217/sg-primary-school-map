#!/usr/bin/env python3
"""
Fix missing coordinates for schools that have addresses but no lat/lng.
Also try to fill remaining gaps using web_search for the 13 failed schools.
"""
import json
import re
import time
import urllib.request
import urllib.parse

SCHOOLS_FILE = "schools.json"
SLEEP = 0.3

def load_schools():
    with open(SCHOOLS_FILE, "r") as f:
        return json.load(f)

def save_schools(schools):
    with open(SCHOOLS_FILE, "w") as f:
        json.dump(schools, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(schools)} schools")

def onemap_geocode(address):
    url = f"https://www.onemap.gov.sg/api/common/elastic/search?searchVal={urllib.parse.quote(address)}&returnGeom=Y&getAddrDetails=Y&pageNum=1"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("found") and data.get("results"):
            r = data["results"][0]
            lat = float(r["LATITUDE"])
            lng = float(r["LONGITUDE"])
            return lat, lng
    except Exception as e:
        pass
    return None, None

def extract_session_from_desc(desc):
    """Extract session from description."""
    if not desc:
        return ""
    d = desc.lower()
    if "single session" in d:
        return "Single session"
    if "full day" in d or "fullday" in d:
        return "Full day session"
    if "morning session" in d:
        return "Morning session"
    if "double session" in d:
        return "Double session"
    return ""

def main():
    schools = load_schools()
    changes = []
    
    # Part 1: Geocode schools that have addresses but missing coords
    print("="*60)
    print("PART 1: Geocoding schools with addresses but missing coords")
    print("="*60)
    
    for i, school in enumerate(schools):
        name = school["name"]
        has_addr = bool(school.get("address"))
        lat = school.get("lat")
        lng = school.get("lng", "")
        
        # lat/lng might be None, empty, or 0
        missing_coords = (lat is None or str(lat) == "" or 
                          lng is None or str(lng) == "" or 
                          (lat == 0 and (lng is None or lng == 0 or lng == "")))
        
        if has_addr and missing_coords:
            addr = school["address"]
            print(f"\n[{i+1}/{len(schools)}] {name}")
            print(f"  Address: {addr}")
            
            lat, lng = onemap_geocode(addr)
            if lat is not None:
                school["lat"] = lat
                school["lng"] = lng
                changes.append((name, f"coords: ({lat}, {lng})"))
                print(f"  -> ({lat}, {lng})")
            else:
                print(f"  -> FAILED to geocode")
            time.sleep(SLEEP)
    
    save_schools(schools)
    
    # Print summary
    print(f"\n{'='*60}")
    print(f"Geocoding changes: {len(changes)}")
    print(f"{'='*60}")
    for name, change in changes:
        print(f"  {name}: {change}")

if __name__ == "__main__":
    main()
