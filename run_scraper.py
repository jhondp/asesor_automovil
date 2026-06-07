import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.config import settings
from src.database.connection import init_db
from src.scrapers.chileautos import ChileautosScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("scraper")


def main():
    parser = argparse.ArgumentParser(description="Scraper de autos chilenos")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--pages", "-p", type=int, default=None,
                       help="Numero de paginas a scrapear (default: 5 si no se usa --all)")
    group.add_argument("--all", "-a", action="store_true",
                       help="Scrapea hasta que no haya mas listings nuevos (~63k totales)")
    parser.add_argument("--start-offset", type=int, default=0,
                        help="Offset inicial para continuar un scrape interrumpido")
    parser.add_argument("--reset", action="store_true",
                        help="Eliminar todos los datos existentes antes de scrapear")
    parser.add_argument("--no-parquet", action="store_true",
                        help="No exportar a Parquet al finalizar")
    args = parser.parse_args()

    logger.info("Inicializando base de datos en %s", settings.db_url)
    init_db()

    if args.reset:
        from src.database.connection import engine, Base
        logger.warning("Reseteando base de datos...")
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        logger.info("Base de datos reseteada.")

    if args.all:
        pages = None
        logger.info("Modo: scrapear TODO hasta agotar listings")
    elif args.pages:
        pages = args.pages
        logger.info("Modo: %s paginas", pages)
    else:
        pages = 5
        logger.info("Modo: %s paginas (default)", pages)

    scraper = ChileautosScraper()
    total = scraper.scrape(max_pages=pages, start_offset=args.start_offset)
    logger.info("Listo. %s listings en la base de datos.", f"{total:,}")


if __name__ == "__main__":
    main()
