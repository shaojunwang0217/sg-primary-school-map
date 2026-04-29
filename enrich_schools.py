#!/usr/bin/env python3
"""
Cross-reference all 186 schools against KiasuParents.com data.
Fetch each school page, extract address/region/phone/website/description,
re-geocode if address differs, and update schools.json.
"""
import json
import re
import time
import urllib.request
import urllib.parse
import sys

SCHOOLS_FILE = "schools.json"
SLEEP = 0.5  # rate limit between fetches

def load_schools():
    with open(SCHOOLS_FILE, "r") as f:
        return json.load(f)

def save_schools(schools):
    with open(SCHOOLS_FILE, "w") as f:
        json.dump(schools, f, indent=2, ensure_ascii=False)
    print(f"  Saved {len(schools)} schools to {SCHOOLS_FILE}")

def slugify(name):
    """Convert school name to KiasuParents slug."""
    # Remove text in parentheses but keep the rest
    s = name.lower()
    # Remove special chars, replace spaces with hyphens
    s = re.sub(r'[^a-z0-9\s-]', '', s)
    s = re.sub(r'\s+', '-', s.strip())
    # Handle specific known mappings
    special_cases = {
        "anglo-chinese-school-junior": "anglo-chinese-junior",
        "anglo-chinese-school-primary": "anglo-chinese-primary",
        "chij-katong-primary": "chij-katong-primary",
        "chij-kellock": "chij-kellock",
        "chij-our-lady-of-good-counsel": "chij-our-lady-of-good-counsel",
        "chij-our-lady-of-the-nativity": "chij-our-lady-of-the-nativity",
        "chij-our-lady-queen-of-peace": "chij-our-lady-queen-of-peace",
        "chij-primary-toa-payoh": "chij-primary-toa-payoh",
        "chij-st-nicholas-girls-school": "chij-st-nicholas-girls-school",
        "fairfield-methodist-school-primary": "fairfield-methodist-school-primary",
        "geylang-methodist-school-primary": "geylang-methodist-school-primary",
        "methodist-girls-school-primary": "methodist-girls-school-primary",
        "paya-lebar-methodist-girls-school-primary": "paya-lebar-methodist-girls-school-primary",
        "raffles-girls-primary-school": "raffles-girls-primary-school",
        "singapore-chinese-girls-primary-school": "singapore-chinese-girls-primary-school",
        "st-andrews-junior-school": "st-andrews-junior-school",
        "st-anthonys-canossian-primary-school": "st-anthonys-canossian-primary-school",
        "st-anthonys-primary-school": "st-anthonys-primary-school",
        "st-gabriels-primary-school": "st-gabriels-primary-school",
        "st-hildas-primary-school": "st-hildas-primary-school",
        "st-josephs-institution-junior": "st-josephs-institution-junior",
        "st-margarets-school-primary": "st-margarets-school-primary",
        "st-stephens-school": "st-stephens-school",
        "haig-girls-school": "haig-girls-school",
        "anglo-chinese-school-junior": "anglo-chinese-junior",
        "anglo-chinese-school-primary": "anglo-chinese-primary",
    }
    if s in special_cases:
        return special_cases[s]
    return s

def fetch_page(url):
    """Fetch a URL and return HTML text, or None on error."""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
            return html
    except Exception as e:
        print(f"    ERROR fetching {url}: {e}")
        return None

def extract_field(html, pattern, group=1):
    """Extract a field from HTML using regex, or return empty string."""
    m = re.search(pattern, html, re.DOTALL)
    if m:
        return m.group(group).strip()
    return ""

def extract_description(html):
    """Extract meta description."""
    m = re.search(r'<meta\s+name="description"\s+content="([^"]+)"', html, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return ""

def parse_session_from_description(desc):
    """Parse session info from description (e.g. 'Full day session')."""
    if not desc:
        return ""
    desc_lower = desc.lower()
    # Check for session type
    if "single session" in desc_lower:
        return "Single session"
    elif "full day session" in desc_lower or "fullday session" in desc_lower:
        return "Full day session"
    elif "morning session" in desc_lower:
        return "Morning session"
    elif "double session" in desc_lower:
        return "Double session"
    return ""

def extract_type_from_description(desc):
    """Extract school type from description like 'Government School' or 'Govt-Aided School'."""
    if not desc:
        return ""
    m = re.search(r'(Government School|Govt-Aided School|Government-Aided School|Government|Govt-Aided)', desc)
    if m:
        val = m.group(1)
        if "Govt-Aided" in val or "Government-Aided" in val:
            return "Govt-Aided"
        return "Government"
    return ""

def extract_gender_from_description(desc):
    """Extract gender from description like 'Co-Ed', 'Boys', 'Girls'."""
    if not desc:
        return ""
    m = re.search(r'(Co-Ed|Coed|Co Ed|Boys\'?|Girls\'?)', desc, re.IGNORECASE)
    if m:
        val = m.group(1).strip()
        if val.lower() in ("co-ed", "coed", "co ed"):
            return "Co-Ed"
        if val.lower().startswith("boy"):
            return "Boys"
        if val.lower().startswith("girl"):
            return "Girls"
    return ""

def onemap_geocode(address):
    """Geocode an address using OneMap API."""
    url = f"https://www.onemap.gov.sg/api/common/elastic/search?searchVal={urllib.parse.quote(address)}&returnGeom=Y&getAddrDetails=Y&pageNum=1"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0"
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("found") and data.get("results"):
            r = data["results"][0]
            lat = float(r["LATITUDE"])
            lng = float(r["LONGITUDE"])
            print(f"    OneMap geocode: ({lat}, {lng})")
            return lat, lng
    except Exception as e:
        print(f"    OneMap ERROR: {e}")
    return None, None

def is_blank(val):
    """Check if a value is blank/empty/None."""
    return val is None or val == "" or val == " "

def main():
    schools = load_schools()
    print(f"Loaded {len(schools)} schools")

    changes = []
    errors = []
    
    for i, school in enumerate(schools):
        slug = slugify(school["name"])
        url = f"https://www.kiasuparents.com/kiasu/primary-schools/{slug}"
        
        print(f"\n[{i+1}/{len(schools)}] {school['name']} -> {slug}")
        print(f"  Fetching: {url}")
        
        html = fetch_page(url)
        if not html:
            errors.append((school["name"], "Failed to fetch page"))
            print(f"  SKIPPING (fetch failed)")
            time.sleep(SLEEP)
            continue
        
        # Check if page is valid (not a redirect/error page for wrong slug)
        if "404" in html[:500] or "Page not found" in html[:1000]:
            errors.append((school["name"], "404 - slug probably wrong"))
            print(f"  SKIPPING (404 page)")
            time.sleep(SLEEP)
            continue
        
        # Check if the page title/school name matches
        title_match = re.search(r'<title>([^<]+)</title>', html, re.IGNORECASE)
        page_title = title_match.group(1).strip() if title_match else ""
        
        # Extract fields
        address = extract_field(html, r"font-bold'>Address.*?</div><div class=\"col-span-3[^\"]*\"><p>([^<]+)</p>")
        region = extract_field(html, r"font-bold'>Region.*?</div><div class=\"col-span-3[^\"]*\"><p>([^<]+)</p>")
        phone = extract_field(html, r"href=\"tel:([^\"]+)\"[^>]*>([^<]+)</a>", group=2)
        website = extract_field(html, r"font-bold'>Website.*?</div><div class=\"col-span-3[^\"]*\"><a href=\"([^\"]+)\"")
        
        # Also try alternate regex for website
        if not website:
            website = extract_field(html, r"font-bold'>Website.*?</div><div class=\"col-span-3[^\"]*\"[^>]*><a[^>]+href=\"([^\"]+)\"")
        
        desc = extract_description(html)
        session = parse_session_from_description(desc)
        type_from_desc = extract_type_from_description(desc)
        gender_from_desc = extract_gender_from_description(desc)
        
        print(f"  Address: {address}")
        print(f"  Region: {region}")
        print(f"  Phone: {phone}")
        print(f"  Website: {website}")
        print(f"  Description: {desc[:120] if desc else ''}")
        print(f"  Session: {session}")
        
        school_changes = []
        
        # Check address
        if address and school.get("address", "") != address:
            old_addr = school.get("address", "")
            print(f"  ADDRESS CHANGED: '{old_addr}' -> '{address}'")
            school["address"] = address
            school_changes.append(f"address: '{old_addr}' -> '{address}'")
            
            # Re-geocode with new address
            lat, lng = onemap_geocode(address)
            if lat is not None:
                school["lat"] = lat
                school["lng"] = lng
                school_changes.append(f"lat/lng re-geocoded to ({lat}, {lng})")
        
        # Check region
        if region and school.get("region", "") != region:
            old = school.get("region", "")
            print(f"  REGION CHANGED: '{old}' -> '{region}'")
            school["region"] = region
            school_changes.append(f"region: '{old}' -> '{region}'")
        
        # Check phone
        if phone and school.get("phone", "") != phone:
            old = school.get("phone", "")
            print(f"  PHONE CHANGED: '{old}' -> '{phone}'")
            school["phone"] = phone
            school_changes.append(f"phone: '{old}' -> '{phone}'")
        
        # Check website (MOE URL)
        if website and school.get("moe_url", "") != website:
            old = school.get("moe_url", "")
            print(f"  WEBSITE CHANGED: '{old}' -> '{website}'")
            school["moe_url"] = website
            school_changes.append(f"moe_url: '{old}' -> '{website}'")
        
        # Check session
        if session and school.get("session", "") != session:
            old = school.get("session", "")
            print(f"  SESSION CHANGED: '{old}' -> '{session}'")
            school["session"] = session
            school_changes.append(f"session: '{old}' -> '{session}'")
        
        # Also check lat/lng: if we fetched a page with an address but school has no lat/lng, geocode
        if address and is_blank(school.get("lat")) and is_blank(school.get("lng", "")):
            # lat could be null or 0
            lat_raw = school.get("lat")
            lng_raw = school.get("lng", "")
            if lat_raw is None or lng_raw is None or lat_raw == "" or lng_raw == "" or (lat_raw == 0 and lng_raw == 0):
                print(f"  Missing coords, geocoding...")
                lat, lng = onemap_geocode(address)
                if lat is not None:
                    school["lat"] = lat
                    school["lng"] = lng
                    school_changes.append(f"lat/lng set to ({lat}, {lng}) via OneMap")
        
        # Check type from description (overwrite if we got a clear signal)
        if type_from_desc and school.get("type", "") != type_from_desc:
            old = school.get("type", "")
            # Only overwrite if the old value is "Government" and new is more specific or vice versa
            print(f"  TYPE from desc: '{type_from_desc}' (current: '{old}')")
            # We'll be conservative - only update if current is empty or obviously wrong
            if not old or old == "":
                school["type"] = type_from_desc
                school_changes.append(f"type: '{old}' -> '{type_from_desc}'")
        
        # Check gender from description
        if gender_from_desc and school.get("gender", "") != gender_from_desc:
            old = school.get("gender", "")
            print(f"  GENDER from desc: '{gender_from_desc}' (current: '{old}')")
            if not old or old == "":
                school["gender"] = gender_from_desc
                school_changes.append(f"gender: '{old}' -> '{gender_from_desc}'")
        
        if school_changes:
            changes.append((school["name"], school_changes))
        
        time.sleep(SLEEP)
    
    # Save final output
    save_schools(schools)
    
    # Print summary
    print("\n" + "="*80)
    print("SUMMARY OF ALL CHANGES:")
    print("="*80)
    for name, school_changes in changes:
        print(f"\n{name}:")
        for c in school_changes:
            print(f"  - {c}")
    
    print(f"\n\nTotal schools with changes: {len(changes)}")
    print(f"Total errors/skipped: {len(errors)}")
    for name, reason in errors:
        print(f"  - {name}: {reason}")

if __name__ == "__main__":
    main()
