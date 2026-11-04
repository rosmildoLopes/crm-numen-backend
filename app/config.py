from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str = 'sqlite:///./numen_crm.db'
    jwt_secret: str = 'development-only-change-this-secret'
    jwt_expire_minutes: int = 480
    admin_email: str = 'admin@numen.local'
    admin_password: str = 'CHANGE_ME_BEFORE_PRODUCTION'
    cors_origins: str = 'http://localhost:3000'
    smtp_host: str = ''
    smtp_port: int = 587
    smtp_user: str = ''
    smtp_password: str = ''
    smtp_from: str = ''
    smtp_starttls: bool = True
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
settings = Settings()
