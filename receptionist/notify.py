from __future__ import annotations

import json
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Protocol


class Notifier(Protocol):
    def send(self, subject: str, body: str) -> None: ...


class SmtpNotifier:
    """Emails the team over SMTP (works with Gmail app passwords, Microsoft 365, SES SMTP and so on)."""

    def __init__(self, host: str, port: int, user: str, password: str, sender: str, to: str):
        self.host, self.port, self.user, self.password, self.sender, self.to = host, port, user, password, sender, to

    def send(self, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.sender, self.to, subject
        msg.set_content(body)
        with smtplib.SMTP(self.host, self.port, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(self.user, self.password)
            smtp.send_message(msg)


class OutboxNotifier:
    """No email configured: append messages to a JSON-lines outbox file instead, so nothing is lost."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def send(self, subject: str, body: str) -> None:
        with self.path.open("a") as f:
            f.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "subject": subject, "body": body}) + "\n")
