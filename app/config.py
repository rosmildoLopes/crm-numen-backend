from pydantic import model_validator
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
    automation_enabled: bool = True
    automation_poll_seconds: int = 60
    email_delivery_enabled: bool = False
    email_max_attempts: int = 3
    ai_enabled: bool = False
    openai_api_key: str = ''
    openai_model: str = ''
    ai_daily_call_limit: int = 20
    public_crm_url: str = ''
    demo_mode: bool = False
    @model_validator(mode='after')
    def local_demo_has_no_external_actions(self):
        if self.demo_mode:
            self.email_delivery_enabled=False
            self.ai_enabled=False
            self.automation_enabled=False
        return self
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
settings = Settings()
