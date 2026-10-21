from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    SECRET_KEY: str = "polsl_rau2_super_secret_jwt_key_change_in_production_2026"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 720
    COOKIE_SECURE: bool = False

    ADMIN_EMAIL: str = "starosta@student.polsl.pl"
    ADMIN_PASSWORD: str = "StarostaRAU2!2026"
    ADMIN_FULL_NAME: str = "Starosta Roku RAU2"

    DATABASE_URL: str = "sqlite:///./starosta_hub.db"

    SMTP_HOST: str = "smtp.office365.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_NAME: str = "Starosta Roku AEiI (RAU2)"
    SMTP_USE_TLS: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
