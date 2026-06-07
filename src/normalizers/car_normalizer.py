import logging
import re
from typing import Optional, Tuple
from unicodedata import normalize

from rapidfuzz import fuzz, process

from src.database.connection import get_session
from src.database.models import Brand, Model

logger = logging.getLogger(__name__)

CATALOGO_MARCAS = [
    "Toyota", "Chevrolet", "Suzuki", "Hyundai", "Kia", "Nissan", "Mitsubishi",
    "Ford", "Volkswagen", "Peugeot", "Renault", "Citroën", "Mazda", "Honda",
    "Subaru", "BMW", "Mercedes-Benz", "Audi", "Volvo", "Jeep", "Dodge",
    "Changan", "Chery", "Great Wall", "Haval", "JAC", "MG", "BYD", "Maxus",
    "SsangYong", "Opel", "Fiat", "Land Rover", "Lexus", "Mini", "Porsche",
    "RAM", "SEAT", "Skoda", "GWM", "DFSK", "Dongfeng", "Geely", "BAIC",
    "Foton", "ZNA", "Mahindra", "Tata",
]

SINONIMOS_MARCA = {
    "mercedes": "Mercedes-Benz",
    "mercedes benz": "Mercedes-Benz",
    "mercedez": "Mercedes-Benz",
    "bmw": "BMW",
    "vw": "Volkswagen",
    "vocho": "Volkswagen",
    "mb": "Mercedes-Benz",
    "mitsubichi": "Mitsubishi",
    "chevrolet": "Chevrolet",
    "chevy": "Chevrolet",
    "toy": "Toyota",
    "hyund": "Hyundai",
    "nissa": "Nissan",
    "suzu": "Suzuki",
    "maz": "Mazda",
    "mitsub": "Mitsubishi",
    "land rover": "Land Rover",
    "landrover": "Land Rover",
    "range rover": "Land Rover",
    "citroen": "Citroën",
    "peugeo": "Peugeot",
    "ssang yong": "SsangYong",
    "ssanyong": "SsangYong",
}

PALABRAS_IGNORAR = {
    "autos", "autos usados", "autos nuevos", "vehiculos", "vehículo",
    "auto", "usado", "nuevo", "camioneta", "suv", "sedan", "hatchback",
    "venta", "vendo", "compro", "financiamiento", "cuotas", "patente",
    "al dia", "papeles", "transferencia", "4x4", "4x2", "automático",
    "mecánico", "gasolina", "diesel", "diésel", "petrolero",
    "oportunidad", "único", "remate", "liquidación", "oferta",
    "detalle", "vehiculo", "vehiculos", "auto usado", "auto nuevo",
}


def _clean(s: str) -> str:
    s = normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9\s\-]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


class CarNormalizer:
    def __init__(self):
        self._cat_marcas_clean = {_clean(m): m for m in CATALOGO_MARCAS}
        self._sinonimos_clean = {_clean(k): v for k, v in SINONIMOS_MARCA.items()}

    def match(self, raw_title: str) -> Tuple[Optional[Brand], Optional[Model]]:
        session = get_session()
        try:
            title_clean = _clean(raw_title)
            brand_name = self._extract_brand(title_clean)
            brand = None
            model = None

            if brand_name:
                brand = session.query(Brand).filter_by(slug=_clean(brand_name)).first()
                if not brand:
                    brand = Brand(name=brand_name, slug=_clean(brand_name))
                    session.add(brand)
                    session.flush()

                model_name = self._extract_model(title_clean, brand_name)
                if model_name:
                    model = (
                        session.query(Model)
                        .filter_by(brand_id=brand.id, slug=_clean(model_name))
                        .first()
                    )
                    if not model:
                        model = Model(
                            brand_id=brand.id,
                            name=model_name,
                            slug=_clean(model_name),
                        )
                        session.add(model)
                        session.flush()

            session.commit()
            return brand, model
        except Exception as e:
            session.rollback()
            logger.warning("Normalization error for '%s': %s", raw_title, e)
            return None, None
        finally:
            session.close()

    def _extract_brand(self, title_clean: str) -> Optional[str]:
        title_words = title_clean.split()
        if not title_words:
            return None

        for word in title_words:
            if word in PALABRAS_IGNORAR:
                continue
            if word in self._sinonimos_clean:
                return self._sinonimos_clean[word]
            if word in self._cat_marcas_clean:
                return self._cat_marcas_clean[word]

        for cat_name, original_name in self._cat_marcas_clean.items():
            if f" {cat_name} " in f" {title_clean} ":
                return original_name

        first_word = title_words[0]
        match, score, _ = process.extractOne(
            first_word,
            list(self._cat_marcas_clean.keys()),
            scorer=fuzz.ratio,
            score_cutoff=80,
        )
        if match and match in self._cat_marcas_clean:
            return self._cat_marcas_clean[match]

        for word in title_words[:3]:
            if word in PALABRAS_IGNORAR or word in {"1", "2", "3", "4"}:
                continue
            match, score, _ = process.extractOne(
                word,
                list(self._cat_marcas_clean.keys()),
                scorer=fuzz.ratio,
                score_cutoff=82,
            )
            if match and match in self._cat_marcas_clean:
                return self._cat_marcas_clean[match]

        return None

    def _extract_model(self, title_clean: str, brand_name: str) -> Optional[str]:
        brand_clean = _clean(brand_name)
        remaining = title_clean.replace(brand_clean, "", 1).strip()
        remaining = re.sub(r"\b(19|20)\d{2}\b", "", remaining)
        remaining = re.sub(r"\b\d{1,3}(?:[.,]\d{3})*\s*(?:cc|hp|km|kms)\b", "", remaining, flags=re.IGNORECASE)
        remaining = re.sub(r"\b(?:usado|nuevo|vendo|venta|semi\s*nuevo)\b", "", remaining)
        remaining = re.sub(r"\s+", " ", remaining).strip()

        words = remaining.split()
        if not words:
            return None

        significant_words = [w for w in words if w not in PALABRAS_IGNORAR and len(w) > 1]
        if not significant_words:
            return None

        return " ".join(significant_words[:4])
