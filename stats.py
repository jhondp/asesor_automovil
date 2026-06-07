import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from sqlalchemy import func
except ImportError:
    print("ERROR: sqlalchemy no está instalado.")
    print("Ejecutá: pip3 install --break-system-packages sqlalchemy")
    sys.exit(1)

from src.database.connection import init_db, get_session
from src.database.models import Brand, Model, Listing


def main():
    init_db()
    session = get_session()

    total_listings = session.query(Listing).count()
    total_brands = session.query(Brand).count()
    total_models = session.query(Model).count()

    print("=" * 60)
    print("  BASE DE DATOS DE AUTOS CHILENOS")
    print("=" * 60)
    print(f"  Marcas: {total_brands}  |  Modelos: {total_models}  |  Listings: {total_listings}")
    print()

    price_stats = session.query(
        func.min(Listing.price), func.avg(Listing.price), func.max(Listing.price)
    ).filter(Listing.price.isnot(None)).first()
    year_stats = session.query(
        func.min(Listing.year), func.avg(Listing.year), func.max(Listing.year)
    ).filter(Listing.year.isnot(None)).first()

    if price_stats[0]:
        print(f"  Precios: ${price_stats[0]:,.0f} ~ ${price_stats[1]:,.0f} (prom) ~ ${price_stats[2]:,.0f}")
    if year_stats[0]:
        print(f"  Años:    {int(year_stats[0])} ~ {year_stats[1]:.0f} (prom) ~ {int(year_stats[2])}")
    print()

    print("--- Top 15 marcas ---")
    brands = (
        session.query(Brand.name, func.count(Listing.id).label("cnt"))
        .join(Listing, Listing.brand_id == Brand.id)
        .group_by(Brand.id)
        .order_by(func.count(Listing.id).desc())
        .limit(15)
        .all()
    )
    for name, cnt in brands:
        bar = "#" * max(1, cnt // 2)
        print(f"  {name:<20} {cnt:>4} {bar}")

    print()
    print("--- Regiones ---")
    locations = (
        session.query(Listing.location, func.count(Listing.id))
        .filter(Listing.location.isnot(None))
        .group_by(Listing.location)
        .order_by(func.count(Listing.id).desc())
        .all()
    )
    for loc, cnt in locations:
        print(f"  {loc:<40} {cnt:>4}")

    print()
    print("--- Listings más caros ---")
    for l in (
        session.query(Listing)
        .order_by(Listing.price.desc())
        .limit(5)
        .all()
    ):
        brand_name = l.brand.name if l.brand else "?"
        model_name = l.model.name if l.model else "?"
        print(f"  {brand_name} {model_name} ({l.year}) - ${l.price:,.0f} - {l.location}")

    print()
    print("--- Listings más baratos ---")
    for l in (
        session.query(Listing)
        .filter(Listing.price > 0)
        .order_by(Listing.price.asc())
        .limit(5)
        .all()
    ):
        brand_name = l.brand.name if l.brand else "?"
        model_name = l.model.name if l.model else "?"
        print(f"  {brand_name} {model_name} ({l.year}) - ${l.price:,.0f} - {l.location}")

    session.close()


if __name__ == "__main__":
    main()
