"""
CEJ apartment watcher
=====================

STEP 2 of 4: Read CEJ's apartments AND keep only the ones that match us.

How it works:
  1. Download the list page https://udlejning.cej.dk/find-bolig/overblik
     and read the basic facts of every apartment (rooms, rent, postcode...).
  2. Quick filter on those basic facts: still open for applications,
     at least 2 rooms, in our area, rent not obviously too high.
  3. For the apartments that pass, open each apartment's own page to read
     the details the list doesn't show: aconto (utilities), move-in date,
     balcony and pets.
  4. Final filter: rent + aconto within budget, move-in in December/January.
  5. Print a short summary of each match with the key details:
     price, location, size, move-in, balcony, pets and furnished.

Later steps will add:
  3. Emailing you both when a NEW match appears.
  4. Running automatically every 5 minutes.
"""

# --- Libraries we use -------------------------------------------------------
# re            : built into Python. "Regular expressions" let us search text
#                 for patterns, e.g. "a number followed by m²".
# time          : built into Python. Used to pause briefly between page
#                 downloads, so we don't hammer CEJ's website.
# requests      : downloads web pages (installed by the workflow file).
# BeautifulSoup : reads the downloaded HTML so we can find parts of the page.
import re
import time

import requests
from bs4 import BeautifulSoup


# =============================================================================
# OUR REQUIREMENTS - change these whenever you like
# =============================================================================

# Minimum number of rooms (in Denmark the living room counts as a room,
# so "2 rooms" = one bedroom + one living room).
MIN_ROOMS = 2

# Maximum total monthly cost: rent ("husleje") + utilities ("aconto").
MAX_MONTHLY_COST = 12_000

# Which months we want to move in. Format: (year, month).
WANTED_MOVE_IN = [(2026, 12), (2027, 1)]  # December 2026, January 2027

# Many listings say "Snarest" (= as soon as possible) instead of a date.
# True  -> include them anyway, marked "check with CEJ if Dec/Jan is OK".
# False -> skip them.
INCLUDE_ASAP = True

# Postcodes we're interested in. "Not too far from the city centre".
# Postcodes 1000-1999 (Indre By, Vesterbro, Frederiksberg C) are always
# included - see in_our_area() below. Add or remove postcodes here.
# To include an area, remove the "#" at the start of its line.
EXTRA_POSTCODES = {
    2000,  # Frederiksberg
    2100,  # København Ø (Østerbro)
    2150,  # Nordhavn
    2200,  # København N (Nørrebro)
    2300,  # København S (Amager)
    2400,  # København NV
    2450,  # København SV (Sydhavnen)
    2500,  # Valby
    # 2700,  # Brønshøj
    # 2720,  # Vanløse
    # 2770,  # Kastrup
    # 2900,  # Hellerup
}


# =============================================================================
# Website settings - you shouldn't need to change these
# =============================================================================

BASE = "https://udlejning.cej.dk"
LIST_URL = BASE + "/find-bolig/overblik"

# Some websites refuse requests that don't look like they come from a normal
# web browser. These "headers" are what a real Chrome browser sends along
# with every request, so our request looks like one.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "da-DK,da;q=0.9,en;q=0.8",
}

# If the site refuses us, try again this many times, waiting a bit longer
# each time (in seconds).
RETRY_WAITS = [10, 30]

# One shared "session" works like one browser tab: it keeps any cookies the
# site hands out between requests, just like a browser would.
session = requests.Session()
session.headers.update(HEADERS)

# The listings are split over several pages. We'll never need more than this.
MAX_PAGES = 5

# The labels in the "Diverse" feature list on each apartment page. Every page
# shows all of them (we can't yet tell which are ticked), so we ignore these
# lines when searching the page for words like "altan" or "møbleret".
FEATURE_LIST_LABELS = {
    "Elevator", "Mulighed for husdyr", "Møbleret", "Altan/terrasse",
    "Parkering", "Delevenlig", "Fælles gårdanlæg", "Cykelparkering",
    "Ungdomsbolig", "Studiebolig", "Seniorvenlig", "Fællesvaskeri",
    "Depotrum",
}

# Danish (and English) month names, so we can read dates like "1. december".
MONTHS = {
    "januar": 1, "februar": 2, "marts": 3, "april": 4, "maj": 5, "juni": 6,
    "juli": 7, "august": 8, "september": 9, "oktober": 10, "november": 11,
    "december": 12,
    "january": 1, "february": 2, "march": 3, "may": 5, "june": 6,
    "july": 7, "october": 10,
}


# =============================================================================
# Small helper functions
# =============================================================================

def parse_number(text):
    """
    Turn a Danish-formatted number into a Python number.

    Danish websites write twelve thousand eight hundred as "12.800"
    (a dot as the thousands separator). Python would read "12.800" as
    twelve point eight, so we remove the dots first.

    Example: parse_number("12.800 kr./md") -> 12800
    """
    digits = re.search(r"[\d.]+", text)
    return int(digits.group(0).replace(".", "")) if digits else None


def get_page(url, params=None):
    """
    Download one web page, trying again if the site refuses us.

    Websites answer every request with a status code: 200 means OK,
    429 means "Too Many Requests" (the site wants us to slow down or thinks
    we're a robot), 403 means "Forbidden". If we get anything other than
    200, we wait and try again. If it still fails, we print details that
    help work out why, then stop.
    """
    for attempt, wait in enumerate([0] + RETRY_WAITS, start=1):
        if wait:
            print(f"  ...waiting {wait} seconds before trying again")
            time.sleep(wait)

        # timeout=20: give up after 20 seconds if the site doesn't answer.
        response = session.get(url, params=params, timeout=20)
        if response.status_code == 200:
            return response
        print(f"  Attempt {attempt}: the site answered {response.status_code} for {response.url}")

    # Still refused after all attempts: print what the site told us.
    print("\n===== DIAGNOSTICS (please paste this to Claude) =====")
    print("Status code:", response.status_code)
    for name in ["server", "retry-after", "x-vercel-mitigated", "x-vercel-id",
                 "cf-ray", "content-type"]:
        if name in response.headers:
            print(f"{name}: {response.headers[name]}")
    print("First part of the page:")
    print(response.text[:800])
    print("===== end =====\n")
    response.raise_for_status()  # stop the script with the error


def format_kr(amount):
    """Write 12800 the Danish way: '12.800 kr'."""
    return f"{amount:,} kr".replace(",", ".") if amount is not None else "unknown"


def in_our_area(postcode):
    """True if the postcode is one we're interested in."""
    if postcode is None:
        return False
    return 1000 <= postcode <= 1999 or postcode in EXTRA_POSTCODES


def parse_move_in(text):
    """
    Work out the move-in month from the "Ledig" (available) field.

    Returns one of:
      "asap"          if it says "Snarest" / "Straks" (as soon as possible)
      (year, month)   if we found a date, e.g. (2026, 12). year may be None.
      None            if we couldn't understand it
    """
    if not text:
        return None
    t = text.lower()

    if "snarest" in t or "straks" in t:
        return "asap"

    # Numeric dates like "01-12-2026", "1.12.2026" or "1/12/26".
    m = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})", t)
    if m:
        year = int(m.group(3))
        if year < 100:
            year += 2000  # "26" -> 2026
        return (year, int(m.group(2)))

    # Written dates like "1. december 2026".
    for name, month in MONTHS.items():
        if re.search(rf"\b{name}\b", t):
            year = re.search(r"\b(20\d\d)\b", t)
            return (int(year.group(1)) if year else None, month)

    return None


def move_in_ok(move_in):
    """
    Decide whether a move-in date suits us.

    Returns "yes", "maybe" (asap or unclear - worth checking) or "no".
    """
    if move_in == "asap":
        return "maybe" if INCLUDE_ASAP else "no"
    if move_in is None:
        return "maybe"  # couldn't read the date - better to look than miss it
    year, month = move_in
    for wanted_year, wanted_month in WANTED_MOVE_IN:
        if month == wanted_month and (year is None or year == wanted_year):
            return "yes"
    return "no"


# =============================================================================
# Reading the list page
# =============================================================================

def read_list_entry(link):
    """
    Pull the basic facts out of one apartment on the list page.

    On CEJ's list page, each apartment is a single clickable link, and its
    basic details are written inside the link as text, for example:

        "Reserveret Lys og rummelig 3-værelses lejlighed i Valby
         Glostervej 62, 1., 3, 2500 Valby 1. sal 3 vær. 90 m² 14.350 kr./md"

    We search that text for patterns to find each fact.
    """
    # The link points to e.g. "/boliger/34616c838edc44b8a7fd3f00370fdd51".
    # The long code at the end is the apartment's unique ID. In step 3 we use
    # it to remember which apartments we've already emailed about.
    listing_id = link["href"].rstrip("/").split("/")[-1]

    # Get all the text inside the link as one line, with single spaces.
    text = " ".join(link.get_text(" ").split())

    # Search the text for each fact. Each pattern means:
    #   (\d+)\s*vær          -> a number, then "vær"     e.g. "3 vær."
    #   (\d+)\s*m²           -> a number, then "m²"      e.g. "90 m²"
    #   ([\d.]+)\s*kr\./md   -> a number, then "kr./md"  e.g. "14.350 kr./md"
    #   \b(\d{4})\s+[A-ZÆØÅ] -> four digits + a capitalised town name
    #                           (a Danish postcode)       e.g. "2500 Valby"
    # The part in brackets ( ) is what we keep.
    rooms = re.search(r"(\d+)\s*vær", text)
    size = re.search(r"(\d+)\s*m²", text)
    rent = re.search(r"([\d.]+)\s*kr\./md", text)
    postcode = re.search(r"\b(\d{4})\s+[A-ZÆØÅ]", text)

    # CEJ marks apartments you can no longer apply for with a label at the
    # start of the text. Anything without a label is open for applications.
    if "Reserveret" in text:
        status = "reserved"
    elif "Lukket for henvendelser" in text:  # "closed for enquiries"
        status = "closed"
    else:
        status = "open"

    return {
        "id": listing_id,
        "url": f"{BASE}/boliger/{listing_id}",
        "list_text": text,
        "status": status,
        "rooms": int(rooms.group(1)) if rooms else None,
        "m2": int(size.group(1)) if size else None,
        "rent": parse_number(rent.group(1)) if rent else None,
        "postcode": int(postcode.group(1)) if postcode else None,
    }


def fetch_listings():
    """
    Download every page of CEJ's apartment list and return all apartments.

    We keep going page by page (page=1, page=2, ...) until a page contains
    no apartments we haven't already seen. That means we've reached the end.
    """
    listings = {}  # apartments found so far, stored by ID so none count twice

    for page in range(1, MAX_PAGES + 1):
        response = get_page(LIST_URL, params={"page": page})
        soup = BeautifulSoup(response.text, "html.parser")

        # Every apartment is a link whose address contains "/boliger/".
        new_on_this_page = 0
        for link in soup.select('a[href*="/boliger/"]'):
            entry = read_list_entry(link)
            if entry["id"] not in listings:
                listings[entry["id"]] = entry
                new_on_this_page += 1

        print(f"List page {page}: {new_on_this_page} new apartments")
        if new_on_this_page == 0:
            break  # nothing new on this page, so we've seen them all

    return list(listings.values())


# =============================================================================
# Reading an apartment's own page
# =============================================================================

def value_after(lines, label):
    """
    On an apartment's page the details appear as a label on one line and
    its value on the next, for example:

        Aconto
        749 kr./md
        Ledig
        Snarest

    This finds the first line that equals `label` and returns the next line.
    """
    for i, line in enumerate(lines[:-1]):
        if line == label:
            return lines[i + 1]
    return None


def feature_hint(page_text, words):
    """
    Look for words like "altan" (balcony) in the apartment's title and
    description. Returns True if mentioned, otherwise None (= unknown).

    Why only a hint: the page also has a "Diverse" list of features with
    ticks, but that list shows ALL possible features, and we can't yet tell
    which ones are ticked. See debug_feature_list() below.
    """
    t = page_text.lower()
    return True if any(word in t for word in words) else None


def debug_feature_list(soup):
    """
    TEMPORARY, for step 2 only: print the HTML around "Altan/terrasse" in
    the feature list, so Claude can see how the site marks a feature as
    present or absent and make the balcony/pets check reliable.
    """
    for element in soup.find_all(string=re.compile(r"Altan/terrasse")):
        container = element.find_parent(["li", "div"])
        if container is not None and container.parent is not None:
            print("----- HTML around 'Altan/terrasse' (please paste to Claude) -----")
            print(str(container.parent)[:3000])
            print("----- end -----")
            return


def fetch_details(entry, debug=False):
    """
    Open one apartment's own page and add the details the list page lacks.
    """
    response = get_page(entry["url"])
    soup = BeautifulSoup(response.text, "html.parser")

    # All the page's text, one item per line, without empty lines.
    lines = [line.strip() for line in soup.get_text("\n").split("\n") if line.strip()]

    # The text we search for hints (balcony, pets, furnished). We leave out
    # the lines of the "Diverse" feature list: that list shows every possible
    # feature on every apartment, so words like "Møbleret" and
    # "Altan/terrasse" would otherwise always be found.
    page_text = " ".join(line for line in lines if line not in FEATURE_LIST_LABELS)

    title = soup.find("h1")
    aconto_text = value_after(lines, "Aconto")
    available_text = value_after(lines, "Ledig")
    move_in_price_text = value_after(lines, "Indflytningspris")

    entry["title"] = title.get_text(strip=True) if title else ""
    entry["address"] = value_after(lines, "Adresse") or entry["list_text"]
    entry["aconto"] = parse_number(aconto_text) if aconto_text else 0
    entry["monthly_cost"] = (entry["rent"] or 0) + entry["aconto"]
    entry["move_in_price"] = parse_number(move_in_price_text) if move_in_price_text else None
    entry["available_text"] = available_text or "unknown"
    entry["move_in"] = parse_move_in(available_text)
    entry["balcony"] = feature_hint(page_text, ["altan", "terrasse", "balkon"])
    entry["pets"] = feature_hint(page_text, ["husdyr tilladt", "kæledyr tilladt",
                                             "husdyr er tilladt", "må holde hund",
                                             "må holde kat"])

    entry["furnished"] = furnished_hint(page_text)

    if debug:
        debug_feature_list(soup)
    return entry


def furnished_hint(page_text):
    """
    Is the apartment furnished ("møbleret")?

    Returns True (furnished), False (unfurnished) or None (not mentioned).
    We check for "umøbleret" (unfurnished) first, because the word
    "møbleret" is hidden inside it and would otherwise count as furnished.
    Like balcony and pets, this is a hint from the text for now.
    """
    t = page_text.lower()
    if "umøbleret" in t or "ikke møbleret" in t:
        return False
    if "møbleret" in t:
        return True
    return None


# =============================================================================
# Filtering and summarising
# =============================================================================

def quick_reject_reason(entry):
    """
    First filter, using only the facts from the list page.
    Returns a reason if the apartment is ruled out, or None if it passes.
    """
    if entry["status"] != "open":
        return f"not open ({entry['status']})"
    if entry["rooms"] is None or entry["rooms"] < MIN_ROOMS:
        return f"too few rooms ({entry['rooms']})"
    if not in_our_area(entry["postcode"]):
        return f"outside our area ({entry['postcode']})"
    if entry["rent"] is None or entry["rent"] > MAX_MONTHLY_COST:
        return f"rent alone too high ({format_kr(entry['rent'])})"
    return None


def final_reject_reason(entry):
    """Second filter, using the details from the apartment's own page."""
    if entry["monthly_cost"] > MAX_MONTHLY_COST:
        return f"rent + aconto too high ({format_kr(entry['monthly_cost'])})"
    if move_in_ok(entry["move_in"]) == "no":
        return f"move-in doesn't suit ({entry['available_text']})"
    return None


def yes_no_unknown(value):
    return {True: "yes", False: "no"}.get(value, "not mentioned - check listing")


def summary(entry):
    """The key details we'll put in the notification email (step 3)."""
    move_in_note = ""
    if move_in_ok(entry["move_in"]) == "maybe":
        move_in_note = "  (check with CEJ that December/January works)"

    return "\n".join([
        f"{entry['title']}",
        f"  Location: {entry['address']}",
        f"  Price:    {format_kr(entry['monthly_cost'])}/month "
        f"({format_kr(entry['rent'])} rent + {format_kr(entry['aconto'])} aconto)"
        f" - move-in cost {format_kr(entry['move_in_price'])}",
        f"  Size:     {entry['rooms']} rooms, {entry['m2']} m²",
        f"  Move-in:  {entry['available_text']}{move_in_note}",
        f"  Balcony:  {yes_no_unknown(entry['balcony'])}",
        f"  Pets:     {yes_no_unknown(entry['pets'])}",
        f"  Furnished: {yes_no_unknown(entry['furnished'])}",
        f"  Link:     {entry['url']}",
    ])


def find_matches():
    """Run both filters and return the matching apartments."""
    listings = fetch_listings()
    print(f"\nFound {len(listings)} apartments in total\n")

    matches = []
    rejected = []  # (apartment, reason) - printed so we can check the filter
    first_detail_page = True

    for entry in listings:
        reason = quick_reject_reason(entry)
        if reason is None:
            time.sleep(1)  # be polite: one page per second
            fetch_details(entry, debug=first_detail_page)
            first_detail_page = False
            reason = final_reject_reason(entry)

        if reason is None:
            matches.append(entry)
        else:
            rejected.append((entry, reason))

    print("Ruled out:")
    for entry, reason in rejected:
        print(f"  - {reason}: {entry['list_text'][:80]}")

    return matches


# --- Run the script ---------------------------------------------------------
# This part only runs when the file is started directly
# (which is what the GitHub workflow does with "python cej_watch.py").
if __name__ == "__main__":
    matches = find_matches()
    print(f"\n{len(matches)} apartments match our requirements:\n")
    for entry in matches:
        print(summary(entry))
        print()
