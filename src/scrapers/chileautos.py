import logging
import re
from datetime import datetime, timezone
from typing import Optional

import httpx

from src.config import settings
from src.database.connection import get_session
from src.database.models import Brand, Model, Listing, ListingSnapshot

logger = logging.getLogger(__name__)

BASE_URL = "https://www.chileautos.cl"
API_URL = BASE_URL + "/_api/search-core/"
PAGE_SIZE = 24

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64; rv:136.0) "
        "Gecko/20100101 Firefox/136.0"
    ),
    "Accept": "application/json",
}

BRAND_NORMALIZE = {
    "SKODA": "Skoda",
    "Skoda": "Skoda",
    "DS": "DS",
    "Ds": "DS",
    "ds": "DS",
    "Mercedes Benz": "Mercedes-Benz",
    "Mercedes": "Mercedes-Benz",
    "mercedes": "Mercedes-Benz",
    "VW": "Volkswagen",
    "Vw": "Volkswagen",
    "Seat": "SEAT",
    "Byd": "BYD",
    "Mg": "MG",
    "Ram": "RAM",
    "Jac": "JAC",
    "Bmw": "BMW",
    "Gwm": "GWM",
    "Baic": "BAIC",
    "Chery": "Chery",
    "Dfsk": "DFSK",
    "Zna": "ZNA",
    "Daf": "DAF",
    "Man": "MAN",
    "Iveco": "IVECO",
}

NON_BRAND_WORDS = {
    "motorhome", "housecar", "remolque", "trailer", "semi",
    "carroceria", "carrocería", "automotora", "concesionario",
    "otra marca", "otra", "bayliner", "randon", "semi remolque",
}

BRAND_FIXES = {
    "Compass": ("Jeep", "Compass"),
    "Chevrolet Captiva": ("Chevrolet", "Captiva"),
}


def _normalize(text: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9\s\-]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


class ChileautosScraper:
    source_name = "chileautos"

    def __init__(self):
        self.client = httpx.Client(headers=HEADERS, timeout=60, follow_redirects=True)
        self._brand_cache = {}
        self._model_cache = {}

    def scrape(self, max_pages: int = 3):
        session = get_session()
        total_saved = 0
        seen_ids = set()

        try:
            for page in range(max_pages):
                offset = page * PAGE_SIZE
                url = f"{API_URL}?offset={offset}"
                logger.info("Fetching page %s/%s (offset=%s)", page + 1, max_pages, offset)

                try:
                    resp = self.client.get(url)
                    if resp.status_code != 200:
                        logger.warning("HTTP %s on page %s", resp.status_code, page + 1)
                        break
                except Exception as e:
                    logger.error("Request failed: %s", e)
                    break

                listings = self._parse_listings(resp.text)
                if not listings:
                    logger.info("No more listings found at offset %s", offset)
                    break

                new_on_page = 0
                for listing_data in listings:
                    nid = listing_data.get("networkId", "")
                    if nid in seen_ids:
                        continue
                    seen_ids.add(nid)

                    listing = self._build_listing(listing_data)
                    if listing is None:
                        continue

                    existing = (
                        session.query(Listing)
                        .filter_by(source=self.source_name, source_id=listing.source_id)
                        .first()
                    )
                    if existing:
                        if existing.price != listing.price or existing.is_sold != listing.is_sold:
                            snapshot = ListingSnapshot(
                                listing_id=existing.id,
                                price=existing.price,
                                is_sold=existing.is_sold,
                                scraped_at=datetime.now(timezone.utc),
                            )
                            session.add(snapshot)
                            existing.price = listing.price
                            existing.is_sold = listing.is_sold
                            existing.last_seen = datetime.now(timezone.utc)
                            existing.scraped_at = datetime.now(timezone.utc)
                        else:
                            existing.last_seen = datetime.now(timezone.utc)
                        session.flush()
                        continue

                    brand, model = self._find_or_create_brand_model(
                        session, listing_data.get("make", ""), listing_data.get("model", "")
                    )
                    listing.brand_id = brand.id if brand else None
                    listing.model_id = model.id if model else None

                    session.add(listing)
                    try:
                        session.flush()
                        total_saved += 1
                        new_on_page += 1
                    except Exception:
                        session.rollback()
                        logger.debug("Skipped duplicate: %s", nid)

                session.commit()
                logger.info(
                    "Page %s done: %s new, %s total unique so far",
                    page + 1, new_on_page, total_saved,
                )

                if new_on_page == 0:
                    logger.info("No new listings on this page, stopping.")
                    break

        finally:
            session.close()
            self.client.close()

        logger.info("Scraping finished. Total new listings: %s", total_saved)
        return total_saved

    def _parse_listings(self, text: str) -> list[dict]:
        results = []
        seen = set()

        for m in re.finditer(r'"networkId"\s*:\s*"((?:CL|CP|GI|GV)-AD-\d+)"', text):
            nid = m.group(1)
            if nid in seen:
                continue
            seen.add(nid)

            start = max(0, m.start() - 600)
            end = min(len(text), m.end() + 2000)
            ctx = text[start:end]

            fields = {}
            for fname in [
                "make", "model", "year", "price", "state", "type",
                "adtype", "networkId", "sortby", "bodyType", "odometer",
                "transmission", "fuelType", "color",
            ]:
                fmatch = re.search(rf'"{fname}"\s*:\s*"([^"]*)"', ctx)
                if fmatch:
                    fields[fname] = fmatch.group(1)

            if fields.get("make") and fields.get("model"):
                if fields["make"] in BRAND_FIXES:
                    new_brand, new_model = BRAND_FIXES[fields["make"]]
                    fields["make"] = new_brand
                    if not fields.get("model") or fields["model"] == fields.get("make"):
                        fields["model"] = new_model
                results.append(fields)

        return results

    def _build_listing(self, data: dict) -> Optional[Listing]:
        nid = data.get("networkId", "")
        make = data.get("make", "")
        model = data.get("model", "")
        year_str = data.get("year", "")
        price_str = data.get("price", "")
        state = data.get("state", "")
        adtype = data.get("type", "")

        url = f"{BASE_URL}/vehiculos/detalle/{nid}/" if nid else ""

        year = int(year_str) if year_str and year_str.isdigit() else None
        price = float(price_str) if price_str and price_str.replace(".", "").isdigit() else None

        raw_title = f"{make} {model} {year_str}".strip()

        return Listing(
            source=self.source_name,
            source_id=nid,
            url=url,
            raw_title=raw_title[:500],
            raw_brand=make,
            raw_model=model,
            year=year,
            price=price,
            currency="CLP",
            location=state,
            is_sold=False,
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
            scraped_at=datetime.now(timezone.utc),
        )

    def _find_or_create_brand_model(self, session, make: str, model_name: str):
        brand = None
        model = None

        if make:
            make_clean = make.strip()
            if _normalize(make_clean) in {_normalize(w) for w in NON_BRAND_WORDS}:
                return None, None

            if make_clean in BRAND_NORMALIZE:
                make_clean = BRAND_NORMALIZE[make_clean]

            slug = _normalize(make_clean)
            if slug in self._brand_cache:
                brand = self._brand_cache[slug]
            else:
                brand = session.query(Brand).filter_by(slug=slug).first()
                if not brand:
                    brand = Brand(name=make_clean, slug=slug)
                    session.add(brand)
                    session.flush()
                self._brand_cache[slug] = brand

        if brand and model_name:
            model_clean = _normalize(model_name)
            model_slug = model_clean
            cache_key = f"{brand.id}:{model_slug}"
            if cache_key in self._model_cache:
                model = self._model_cache[cache_key]
            else:
                model = (
                    session.query(Model)
                    .filter_by(brand_id=brand.id, slug=model_slug)
                    .first()
                )
                if not model:
                    model = Model(
                        brand_id=brand.id,
                        name=model_name.strip(),
                        slug=model_slug,
                    )
                    session.add(model)
                    session.flush()
                self._model_cache[cache_key] = model

        return brand, model
