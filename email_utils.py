"""
Utilitários de e-mail para backup/restauração do Controle Financeiro.
Suporta envio via SMTP e leitura via IMAP (SSL).
"""
import smtplib
import imaplib
import email as email_lib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "email_config.json")
SUBJECT_MARKER = "Backup Financeiro Krauss"


# ── Configuração ─────────────────────────────────────────────────────────────

def load_config() -> dict:
    """Lê configuração do email_config.json (uso local)."""
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            return {}
    return {}


def save_config(cfg: dict):
    """Salva configuração no email_config.json."""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def _secrets_config() -> dict:
    """Tenta ler config dos st.secrets (Streamlit Cloud)."""
    try:
        import streamlit as st
        if hasattr(st, "secrets") and "email" in st.secrets:
            s = st.secrets["email"]
            return {
                "smtp_host":     str(s.get("smtp_host", "")),
                "smtp_port":     int(s.get("smtp_port", 587)),
                "smtp_user":     str(s.get("smtp_user", "")),
                "smtp_password": str(s.get("smtp_password", "")),
                "imap_host":     str(s.get("imap_host", "")),
                "imap_port":     int(s.get("imap_port", 993)),
                "email_destino": str(s.get("email_destino", "")),
            }
    except Exception:
        pass
    return {}


def get_config() -> dict:
    """Retorna configuração: st.secrets > email_config.json."""
    cfg = _secrets_config()
    if cfg.get("smtp_user"):
        return cfg
    return load_config()


def is_configured(cfg: dict) -> bool:
    return bool(
        cfg.get("smtp_host")
        and cfg.get("smtp_user")
        and cfg.get("smtp_password")
        and cfg.get("imap_host")
    )


# ── Envio ─────────────────────────────────────────────────────────────────────

def send_backup(excel_bytes: bytes, filename: str, cfg: dict):
    """Envia arquivo Excel de backup como anexo via SMTP/TLS."""
    msg = MIMEMultipart()
    msg["From"] = cfg["smtp_user"]
    msg["To"] = cfg["email_destino"]
    msg["Subject"] = f"{SUBJECT_MARKER} - {filename}"
    msg.attach(MIMEText(
        f"Backup automático — Controle Financeiro Krauss.\n\n"
        f"Arquivo: {filename}\n\n"
        "Não responda este e-mail.",
        "plain", "utf-8"
    ))

    part = MIMEBase("application", "octet-stream")
    part.set_payload(excel_bytes)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
    msg.attach(part)

    with smtplib.SMTP(cfg["smtp_host"], int(cfg["smtp_port"]), timeout=_TIMEOUT) as server:
        server.ehlo()
        server.starttls()
        server.login(cfg["smtp_user"], cfg["smtp_password"])
        server.sendmail(cfg["smtp_user"], cfg["email_destino"], msg.as_string())


# ── Recebimento ──────────────────────────────────────────────────────────────

_TIMEOUT = 20  # segundos; evita travamento no startup do Streamlit Cloud


def get_latest_backup(cfg: dict) -> tuple:
    """
    Busca na caixa de entrada o backup mais recente (pelo assunto).
    Retorna (excel_bytes: bytes, filename: str) ou (None, None).
    """
    raw_msg = None
    imap = imaplib.IMAP4_SSL(cfg["imap_host"], int(cfg.get("imap_port", 993)), timeout=_TIMEOUT)
    try:
        imap.login(cfg["smtp_user"], cfg["smtp_password"])
        imap.select("INBOX")

        _, ids_raw = imap.search(None, f'SUBJECT "{SUBJECT_MARKER}"')
        ids = ids_raw[0].split()

        if not ids:
            return None, None

        # Buscar o mais recente (maior ID = mais novo na ordem de chegada)
        _, msg_data = imap.fetch(ids[-1], "(RFC822)")
        raw_msg = msg_data[0][1]
    finally:
        try:
            imap.logout()
        except Exception:
            pass

    if raw_msg is None:
        return None, None

    msg = email_lib.message_from_bytes(raw_msg)
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if part.get("Content-Disposition") is None:
            continue
        fname = part.get_filename()
        if fname and fname.endswith(".xlsx"):
            return part.get_payload(decode=True), fname

    return None, None


def delete_old_backups(cfg: dict) -> int:
    """
    Remove todos os e-mails de backup antigos da caixa de entrada,
    mantendo apenas o mais recente.
    Retorna a quantidade de e-mails removidos.
    """
    removed = 0
    imap = imaplib.IMAP4_SSL(cfg["imap_host"], int(cfg.get("imap_port", 993)), timeout=_TIMEOUT)
    try:
        imap.login(cfg["smtp_user"], cfg["smtp_password"])
        imap.select("INBOX")

        _, ids_raw = imap.search(None, f'SUBJECT "{SUBJECT_MARKER}"')
        ids = ids_raw[0].split()

        if len(ids) <= 1:
            return 0

        # Apagar todos exceto o último (mais recente)
        for msg_id in ids[:-1]:
            imap.store(msg_id, "+FLAGS", "\\Deleted")
            removed += 1

        imap.expunge()
    finally:
        try:
            imap.logout()
        except Exception:
            pass

    return removed
