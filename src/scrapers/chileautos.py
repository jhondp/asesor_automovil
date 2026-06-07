import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
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
    "SKODA": "Skoda", "Skoda": "Skoda", "DS": "DS", "Ds": "DS", "ds": "DS",
    "Mercedes Benz": "Mercedes-Benz", "Mercedes": "Mercedes-Benz", "mercedes": "Mercedes-Benz",
    "VW": "Volkswagen", "Vw": "Volkswagen", "Seat": "SEAT", "Byd": "BYD",
    "Mg": "MG", "Ram": "RAM", "Jac": "JAC", "Bmw": "BMW", "Gwm": "GWM",
    "Baic": "BAIC", "Chery": "Chery", "Dfsk": "DFSK", "Zna": "ZNA",
    "Daf": "DAF", "Man": "MAN", "Iveco": "IVECO",
    "Peugeot": "Peugeot", "peugeot": "Peugeot",
    "Landrover": "Land Rover", "land rover": "Land Rover",
    "Mini Cooper": "Mini",
}

NON_BRAND_WORDS = {
    "motorhome", "housecar", "remolque", "trailer", "semi",
    "carroceria", "carrocería", "automotora", "concesionario",
    "otra marca", "otra", "bayliner", "randon", "semi remolque",
    "hechizo", "carro de arrastre", "carro arrastre", "carroceria",
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

    def scrape(self, max_pages: Optional[int] = None, start_offset: int = 0):
        session = get_session()
        total_saved = 0
        total_new = 0
        seen_ids = set()
        total_available = None
        start_page = start_offset // PAGE_SIZE
        page = start_page
        empty_streak = 0

        if start_offset > 0:
            existing_ids = session.query(Listing.source_id).filter_by(source=self.source_name).all()
            seen_ids = {row[0] for row in existing_ids}
            logger.info("Continuando desde offset %s. %s listings ya en BD.", start_offset, f"{len(seen_ids):,}")

        try:
            while True:
                if max_pages is not None and page >= max_pages:
                    break

                offset = page * PAGE_SIZE
                url = f"{API_URL}?offset={offset}"

                page_label = f"{page + 1}"
                if total_available:
                    est_pages = total_available // 9  # ~9 new unique per page
                    page_label = f"{page + 1}/~{est_pages}"
                elif max_pages:
                    page_label = f"{page + 1}/{max_pages}"

                logger.info("Fetching page %s (offset=%s)", page_label, offset)

                try:
                    resp = self.client.get(url)
                    if resp.status_code != 200:
                        logger.warning("HTTP %s on page %s", resp.status_code, page + 1)
                        break
                except Exception as e:
                    logger.error("Request failed: %s", e)
                    break

                if total_available is None:
                    total_match = re.search(r'"searchResultCount"\s*:\s*(\d+)', resp.text)
                    if not total_match:
                        total_match = re.search(r'"listingresultcount"\s*:\s*"(\d+)"', resp.text)
                    if total_match:
                        total_available = int(total_match.group(1))
                        logger.info("Total listings disponibles: %s", f"{total_available:,}")

                listings = self._parse_listings(resp.text)
                if not listings:
                    empty_streak += 1
                    if empty_streak >= 3:
                        logger.info("3 páginas vacías consecutivas, deteniendo.")
                        break
                    page += 1
                    continue
                empty_streak = 0

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
                        total_saved += 1
                        continue

                    brand, model = self._find_or_create_brand_model(
                        session, listing_data.get("make", ""), listing_data.get("model", "")
                    )
                    listing.brand_id = brand.id if brand else None
                    listing.model_id = model.id if model else None

                    session.add(listing)
                    try:
                        session.flush()
                        total_new += 1
                        total_saved += 1
                        new_on_page += 1
                    except Exception:
                        session.rollback()
                        logger.debug("Skipped duplicate: %s", nid)

                session.commit()

                pct = ""
                if total_available:
                    pct = f" ({seen_ids.__len__() / total_available * 100:.1f}%)"
                logger.info(
                    "Page %s: +%s nuevos, %s total únicos%s",
                    page + 1, new_on_page, f"{total_saved:,}", pct,
                )

                if new_on_page == 0:
                    logger.info("Sin listings nuevos, deteniendo.")
                    break

                page += 1
                time.sleep(settings.request_delay)

        finally:
            session.close()
            self.client.close()

        logger.info("Scraping finalizado. %s nuevos, %s total.", f"{total_new:,}", f"{total_saved:,}")

        self._export_parquet()
        return total_saved

    def _export_parquet(self):
        try:
            import pandas as pd

            session = get_session()
            rows = (
                session.query(
                    Brand.name.label("marca"),
                    Model.name.label("modelo"),
                    Listing.year.label("año"),
                    Listing.price.label("precio_clp"),
                    Listing.currency.label("moneda"),
                    Listing.mileage_km.label("kilometraje"),
                    Listing.location.label("region"),
                    Listing.is_sold.label("vendido"),
                    Listing.url,
                    Listing.source.label("fuente"),
                    Listing.source_id,
                    Listing.first_seen,
                    Listing.last_seen,
                )
                .outerjoin(Brand, Listing.brand_id == Brand.id)
                .outerjoin(Model, Listing.model_id == Model.id)
                .order_by(Listing.price.desc())
                .all()
            )

            df = pd.DataFrame(rows, columns=[
                "marca", "modelo", "año", "precio_clp", "moneda", "kilometraje",
                "region", "vendido", "url", "fuente", "source_id",
                "primera_vez_visto", "ultima_vez_visto",
            ])

            out = Path(settings.data_dir) / "listings.parquet"
            df.to_parquet(out, index=False)
            logger.info("Parquet exportado: %s (%s registros)", out, f"{len(df):,}")

            session.close()
        except ImportError:
            logger.warning("pandas/pyarrow no instalado, no se exporto Parquet.")
        except Exception as e:
            logger.warning("Error exportando Parquet: %s", e)

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
