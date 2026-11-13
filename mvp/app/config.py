from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = 'postgresql://warm:local-demo@localhost:5432/warm'
    temporal_address: str = 'localhost:7233'
    mock_url: str = 'http://localhost:8001'
    weather_provider: Literal['mock', 'open_meteo'] = 'mock'
    poll_seconds: int = Field(default=60, ge=10)
    recheck_seconds: int = Field(default=1800, ge=1)


settings = Settings()
