"""
Módulo de autenticação para o Controle Financeiro Krauss.
Credenciais: st.secrets (cloud) > auth_config.json (local).
"""
import json
import os
import hashlib
import smtplib
from email.mime.text import MIMEText

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auth_config.json")

DEFAULTS = {
    "username": "Krauss",
    "password_hash": "48bfb125f20e8c4c7ad90459b88e2f1dd7b9bf67d17abb49386eb30f462d6a4a",
    "recovery_email": "krauss.christian@gmail.com",
}


# ── Configuração ─────────────────────────────────────────────────────────────

def _hash(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()


def _load_local() -> dict:
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_local(cfg: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def _secrets_auth() -> dict:
    try:
        import streamlit as st
        if hasattr(st, "secrets") and "auth" in st.secrets:
            s = st.secrets["auth"]
            return {
                "username": str(s.get("username", "")),
                "password_hash": str(s.get("password_hash", "")),
                "recovery_email": str(s.get("recovery_email", "")),
            }
    except Exception:
        pass
    return {}


def get_auth() -> dict:
    """Retorna configuração de autenticação: st.secrets > local > defaults."""
    cfg = _secrets_auth()
    if cfg.get("username"):
        return cfg
    cfg = _load_local()
    if cfg.get("username"):
        return cfg
    # primeira execução: salva defaults localmente
    _save_local(DEFAULTS)
    return dict(DEFAULTS)


def verificar_login(username: str, password: str) -> bool:
    auth = get_auth()
    return username == auth["username"] and _hash(password) == auth["password_hash"]


def alterar_senha(nova_senha: str):
    """Altera a senha (funciona apenas no config local)."""
    cfg = get_auth()
    cfg["password_hash"] = _hash(nova_senha)
    _save_local(cfg)


# ── Recuperação de senha via e-mail ──────────────────────────────────────────

def enviar_recuperacao() -> str:
    """
    Envia e-mail de recuperação com instruções.
    Retorna mensagem de status.
    """
    import email_utils

    auth = get_auth()
    email_cfg = email_utils.get_config()

    if not email_utils.is_configured(email_cfg):
        return "❌ Configuração de e-mail não encontrada. Configure o e-mail na aba Importar/Exportar."

    destino = auth.get("recovery_email", "")
    if not destino:
        return "❌ E-mail de recuperação não configurado."

    corpo = (
        "Olá! Você solicitou a recuperação de acesso ao Controle Financeiro Krauss.\n\n"
        "Para redefinir sua senha, abra o aplicativo e use a opção "
        "'Redefinir senha' na tela de login.\n\n"
        "Se não foi você quem solicitou, ignore este e-mail.\n\n"
        "— Controle Financeiro Krauss"
    )

    msg = MIMEText(corpo, "plain", "utf-8")
    msg["From"] = email_cfg["smtp_user"]
    msg["To"] = destino
    msg["Subject"] = "Recuperação de Senha – Controle Financeiro Krauss"

    try:
        with smtplib.SMTP(email_cfg["smtp_host"], int(email_cfg["smtp_port"])) as server:
            server.ehlo()
            server.starttls()
            server.login(email_cfg["smtp_user"], email_cfg["smtp_password"])
            server.sendmail(email_cfg["smtp_user"], destino, msg.as_string())
        return f"✅ E-mail de recuperação enviado para {destino}"
    except Exception as e:
        return f"❌ Falha ao enviar e-mail: {e}"
