"""Minimal SMTP delivery that keeps reports out of public Actions artifacts."""

from __future__ import annotations

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import os
import smtplib


class MailConfigError(RuntimeError):
    pass


def send_html(subject: str, html: str) -> None:
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "587"))
    sender = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    recipient = os.environ.get("REPORT_RECIPIENT", "")
    if not sender or not password or not recipient:
        raise MailConfigError("SMTP_USER, SMTP_PASSWORD and REPORT_RECIPIENT are required")
    message = MIMEMultipart("alternative")
    message["Subject"] = " ".join(subject.split())[:180]
    message["From"] = sender
    message["To"] = recipient
    message.attach(MIMEText("Open this message in an HTML-capable mail client.", "plain", "utf-8"))
    message.attach(MIMEText(html, "html", "utf-8"))
    with smtplib.SMTP(host, port, timeout=30) as server:
        server.starttls()
        server.login(sender, password)
        server.sendmail(sender, [recipient], message.as_string())
