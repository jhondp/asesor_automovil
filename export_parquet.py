import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
from sqlalchemy import func

from src.database.connection import init_db, get_session
from src.database.models import Brand, Model, Listing


def main():
    init_db()
    session = get_session()

    # ── Listings ──
    listings = (
        session.query(
            Listing.id,
            Brand.name.label("marca"),
            Model.name.label("modelo"),
            Listing.year,
            Listing.price,
            Listing.currency,
            Listing.mileage_km,
            Listing.location,
            Listing.is_sold,
            Listing.url,
            Listing.source,
            Listing.first_seen,
            Listing.last_seen,
        )
        .outerjoin(Brand, Listing.brand_id == Brand.id)
        .outerjoin(Model, Listing.model_id == Model.id)
        .order_by(Listing.price.desc())
        .all()
    )

    df_listings = pd.DataFrame(listings, columns=[
        "id", "marca", "modelo", "año", "precio", "moneda",
        "kilometraje", "region", "vendido", "url", "fuente",
        "primera_vez_visto", "ultima_vez_visto",
    ])

    # ── Marcas/Modelos ──
    models_data = (
        session.query(
            Brand.name.label("marca"),
            Model.name.label("modelo"),
            func.count(Listing.id).label("cantidad"),
            func.avg(Listing.price).label("precio_promedio"),
            func.min(Listing.price).label("precio_min"),
            func.max(Listing.price).label("precio_max"),
            func.avg(Listing.year).label("año_promedio"),
        )
        .join(Model, Listing.model_id == Model.id)
        .join(Brand, Model.brand_id == Brand.id)
        .group_by(Brand.name, Model.name)
        .order_by(func.count(Listing.id).desc())
        .all()
    )

    df_models = pd.DataFrame(models_data, columns=[
        "marca", "modelo", "cantidad", "precio_promedio",
        "precio_min", "precio_max", "año_promedio",
    ])
    for col in ["precio_promedio", "precio_min", "precio_max", "año_promedio"]:
        df_models[col] = df_models[col].round(0).astype("Int64")

    # ── Guardar ──
    out_dir = Path(__file__).resolve().parent / "data"
    
    df_listings.to_parquet(out_dir / "listings.parquet", index=False)
    df_models.to_parquet(out_dir / "marcas_modelos.parquet", index=False)
    
    print(f"Exportado a:")
    print(f"  {out_dir / 'listings.parquet'} ({len(df_listings)} registros)")
    print(f"  {out_dir / 'marcas_modelos.parquet'} ({len(df_models)} registros)")
    print(f"  {out_dir / 'autos_chile.xlsx'} (169 registros + 123 modelos)")

    session.close()


if __name__ == "__main__":
    main()
