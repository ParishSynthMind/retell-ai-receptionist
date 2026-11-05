from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Weekday (0 = Monday) -> list of (open, close) in "HH:MM", business local time.
DEFAULT_HOURS: Dict[int, List[Tuple[str, str]]] = {
    0: [("09:00", "17:00")],
    1: [("09:00", "17:00")],
    2: [("09:00", "17:00")],
    3: [("09:00", "17:00")],
    4: [("09:00", "17:00")],
    5: [("10:00", "14:00")],
    6: [],
}


@dataclass
class Settings:
    business_name: str = "Harbour Dental Clinic"
    timezone: str = "Europe/London"
    slot_minutes: int = 30
    min_notice_minutes: int = 60
    hours: Dict[int, List[Tuple[str, str]]] = field(default_factory=lambda: dict(DEFAULT_HOURS))
    data_dir: Path = Path("var")
    knowledge_base: Path = Path(__file__).resolve().parent.parent / "data" / "knowledge_base.md"
    retell_api_key: Optional[str] = None  # the key with the webhook badge; used ONLY to verify X-Retell-Signature
    allow_unsigned: bool = False  # local development only; never set this on a public server
    admin_token: Optional[str] = None  # bearer token for /calls and /calendar.ics
    calendar_backend: str = "local"
    google_calendar_id: Optional[str] = None
    google_service_account_file: Optional[str] = None
    google_service_account_json: Optional[str] = None
    team_email: Optional[str] = None
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from: Optional[str] = None

    def __post_init__(self) -> None:
        # The summary and handover emails go to ONE fixed address from the config. Nothing a caller
        # says, and nothing the model puts in a tool call, can change the recipient.
        if self.team_email and ("," in self.team_email or ";" in self.team_email or "@" not in self.team_email):
            raise ValueError("TEAM_EMAIL must be a single email address")

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ.get
        return cls(
            business_name=env("BUSINESS_NAME", cls.business_name),
            timezone=env("BUSINESS_TZ", cls.timezone),
            slot_minutes=int(env("SLOT_MINUTES", str(cls.slot_minutes))),
            min_notice_minutes=int(env("MIN_NOTICE_MINUTES", str(cls.min_notice_minutes))),
            data_dir=Path(env("DATA_DIR", "var")),
            retell_api_key=env("RETELL_API_KEY"),
            allow_unsigned=env("ALLOW_UNSIGNED", "") == "1",
            admin_token=env("ADMIN_TOKEN"),
            calendar_backend=env("CALENDAR_BACKEND", "local"),
            google_calendar_id=env("GOOGLE_CALENDAR_ID"),
            google_service_account_file=env("GOOGLE_SERVICE_ACCOUNT_FILE"),
            google_service_account_json=env("GOOGLE_SERVICE_ACCOUNT_JSON"),
            team_email=env("TEAM_EMAIL"),
            smtp_host=env("SMTP_HOST"),
            smtp_port=int(env("SMTP_PORT", "587")),
            smtp_user=env("SMTP_USER"),
            smtp_password=env("SMTP_PASSWORD"),
            smtp_from=env("SMTP_FROM") or env("SMTP_USER"),
        )
