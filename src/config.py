from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    data_dir: Path = Path(__file__).resolve().parent.parent / "data"
    db_url: str = f"sqlite:///{data_dir / 'autos_chile.db'}"

    request_delay: float = 0.5
    max_retries: int = 3
    retry_delay: float = 5.0

    headless: bool = False

    class Config:
        env_prefix = "AUTOS_"
        env_file = ".env"
        extra = "ignore"


settings = Settings()
