"""Minimal SMTP delivery that keeps reports out of public Actions artifacts."""

from __future__ import annotations

from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import os
import smtplib
from typing import Sequence, Tuple, Union


class MailConfigError(RuntimeError):
    pass


#: ``(file name, content, MIME type)``: a file that rides beside the report. Content is built in memory by the
#: caller and never written to disk here.
Attachment = Tuple[str, Union[bytes, str], str]


def send_html(subject: str, html: str, *, text: str = "",
              attachments: Sequence[Attachment] = ()) -> None:
    """Deliver the report as a multipart e-mail: plain text first, HTML second.

    ``text`` is the plain-text twin of ``html``. When it is empty the part
    still exists (a plain-only reader must get something rather than a
    multipart it cannot read), so it says how to read the report.

    ``attachments`` (22 Oct 2026) are files that ride beside the report: the full-detail HTML the body points at,
    because Gmail clips an HTML part near 102 KB. With any, the message is ``multipart/mixed`` around the usual
    text + HTML alternative; with none it is the ``multipart/alternative`` it always was.
    """
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "587"))
    sender = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    recipient = os.environ.get("REPORT_RECIPIENT", "")
    if not sender or not password or not recipient:
        raise MailConfigError("SMTP_USER, SMTP_PASSWORD and REPORT_RECIPIENT are required")
    alternative = MIMEMultipart("alternative")
    alternative.attach(
        MIMEText(
            text or "Open this message in an HTML-capable mail client.",
            "plain",
            "utf-8",
        )
    )
    alternative.attach(MIMEText(html, "html", "utf-8"))
    if attachments:
        message = MIMEMultipart("mixed")
        message.attach(alternative)
        for name, content, mime_type in attachments:
            subtype = mime_type.split("/", 1)[1] if "/" in mime_type else "octet-stream"
            data = content.encode("utf-8") if isinstance(content, str) else content
            if mime_type.startswith("text/"):
                part = MIMEText(data.decode("utf-8"), subtype, "utf-8")
            else:
                part = MIMEApplication(data, _subtype=subtype)
            part.add_header("Content-Disposition", "attachment", filename=name)
            message.attach(part)
    else:
        message = alternative
    message["Subject"] = " ".join(subject.split())[:180]
    message["From"] = sender
    message["To"] = recipient
    with smtplib.SMTP(host, port, timeout=30) as server:
        server.starttls()
        server.login(sender, password)
        server.sendmail(sender, [recipient], message.as_string())
