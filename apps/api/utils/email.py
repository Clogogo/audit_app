"""Transactional email via Resend — currently used only for password-reset
links. Kept as a single function so it's trivial to mock in tests."""
import os

import resend


def send_password_reset_email(to_email: str, reset_link: str) -> None:
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        raise RuntimeError("RESEND_API_KEY is not set — cannot send email")

    resend.api_key = api_key
    from_email = os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev")

    resend.Emails.send({
        "from": f"FinanceAudit <{from_email}>",
        "to": [to_email],
        "subject": "Reset your FinanceAudit password",
        "html": (
            f"<p>Someone requested a password reset for this account.</p>"
            f"<p><a href=\"{reset_link}\">Click here to reset your password</a></p>"
            f"<p>This link expires in 30 minutes. If you didn't request this, you can ignore this email.</p>"
        ),
    })
