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
    parser.add_argument(
        "--pages", "-p",
        type=int,
        default=5,
        help="Número de páginas a scrapear (default: 5)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Eliminar todos los datos existentes antes de scrapear",
    )
    args = parser.parse_args()

    logger.info("Initializing database at %s", settings.db_url)
    init_db()

    if args.reset:
        from src.database.connection import engine, Base
        logger.warning("Resetting database...")
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        logger.info("Database reset complete.")

    logger.info("Database ready. Starting scrape with %s pages...", args.pages)

    scraper = ChileautosScraper()
    total = scraper.scrape(max_pages=args.pages)
    logger.info("Done. %s new listings saved.", total)


if __name__ == "__main__":
    main()
