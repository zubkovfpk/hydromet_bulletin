"""
email_sender.py
Отправка готового .docx бюллетеня на email через корпоративный SMTP.

SMTP: mail.hosting.reg.ru, порт 465 (SSL/TLS)
"""

import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


def send_bulletin(
    docx_path: str,
    recipient: str,
    smtp_host: str,
    smtp_port: int,
    login: str,
    password: str,
    bulletin_type: str = "утренний",
    run_date: datetime | None = None,
) -> bool:
    """
    Отправляет .docx бюллетень на указанный адрес.

    Parameters
    ----------
    docx_path     : str      — путь к готовому .docx файлу
    recipient     : str      — адрес получателя (или несколько через запятую)
    smtp_host     : str      — SMTP-сервер
    smtp_port     : int      — порт (465 для SSL/TLS)
    login         : str      — учётная запись отправителя
    password      : str      — пароль SMTP
    bulletin_type : str      — 'утренний' или 'вечерний' (для темы письма)
    run_date      : datetime — дата бюллетеня; если None — берётся сегодня

    Returns
    -------
    bool — True при успешной отправке, False при ошибке
    """
    if run_date is None:
        run_date = datetime.now()

    date_str = run_date.strftime("%d.%m.%Y")
    recipients = [r.strip() for r in recipient.split(",")]

    subject = (
        f"Гидрометеорологический бюллетень ({bulletin_type}) — {date_str}"
    )
    body_text = (
        f"Гидрометеорологический бюллетень ({bulletin_type}) за {date_str} "
        f"сформирован автоматически.\n\n"
        f"Файл приложен к письму.\n"
    )

    msg = MIMEMultipart()
    msg["From"]    = login
    msg["To"]      = ", ".join(recipients)
    msg["Subject"] = subject

    msg.attach(MIMEText(body_text, "plain", "utf-8"))

    # Прикрепляем .docx
    filename = Path(docx_path).name
    try:
        with open(docx_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            "attachment",
            filename=("utf-8", "", filename),
        )
        msg.attach(part)
    except FileNotFoundError:
        logger.error(f"Файл не найден: {docx_path}")
        return False

    # Отправка через SMTP SSL/TLS (порт 465)
    try:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30) as server:
            server.login(login, password)
            server.sendmail(login, recipients, msg.as_string())
        logger.info(f"Бюллетень отправлен: {', '.join(recipients)} | {filename}")
        return True

    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"Ошибка аутентификации SMTP: {e}")
    except smtplib.SMTPException as e:
        logger.error(f"Ошибка SMTP при отправке: {e}")
    except Exception as e:
        logger.error(f"Неожиданная ошибка при отправке email: {e}")

    return False
