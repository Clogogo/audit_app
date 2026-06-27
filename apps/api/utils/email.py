"""Transactional email via Maileroo's HTTP API. Each send_* function is kept
separate and trivial to mock in tests; _send and _card do the shared
plumbing/markup. Colors match the app's actual brand palette
(apps/web/src/styles.css --primary/--foreground/etc, converted to hex)."""
import os

import requests

MAILEROO_API_URL = "https://smtp.maileroo.com/api/v2/emails"

_PRIMARY = "#1a756c"
_FOREGROUND = "#161b1d"
_MUTED = "#5e696e"
_BORDER = "#e2e7e9"
_FOOTNOTE = "#9aa3a7"
_ALERT_BG = "#fdf2f4"
_ALERT_BORDER = "#f6d4da"
_ALERT_TEXT = "#a23044"

_CARD_TEMPLATE = """\
<!DOCTYPE html>
<html>
  <body style="margin:0;padding:0;background-color:#f4f6f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f6f7;padding:40px 16px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" style="max-width:480px;">
            <tr>
              <td style="padding:0 8px 24px 8px;text-align:center;">
                <span style="font-size:20px;font-weight:700;color:{foreground};letter-spacing:-0.3px;">FinanceAudit</span>
              </td>
            </tr>
            <tr>
              <td style="background-color:#ffffff;border-radius:12px;border:1px solid {border};overflow:hidden;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                  <tr><td style="height:4px;background-color:{primary};font-size:0;line-height:0;">&nbsp;</td></tr>
                  <tr>
                    <td style="padding:36px 36px 28px 36px;">
                      <p style="margin:0 0 6px 0;font-size:12px;font-weight:600;letter-spacing:0.06em;text-transform:uppercase;color:{primary};">{eyebrow}</p>
                      <h1 style="margin:0 0 14px 0;font-size:20px;font-weight:700;color:{foreground};">{heading}</h1>
                      <p style="margin:0;font-size:14px;line-height:1.65;color:{muted};">{body}</p>
                    </td>
                  </tr>
                  {cta_row}
                  {notice_row}
                  <tr>
                    <td style="padding:0 36px 32px 36px;">
                      <p style="margin:0;font-size:12px;line-height:1.6;color:{footnote_color};">{footnote}</p>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td style="padding:24px 8px 0 8px;text-align:center;">
                <p style="margin:0;font-size:12px;color:{footnote_color};">FinanceAudit — finance &amp; payroll management</p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""

_CTA_ROW_TEMPLATE = """\
                  <tr>
                    <td style="padding:0 36px 32px 36px;">
                      <a href="{link}"
                         style="display:inline-block;background-color:{primary};color:#ffffff;text-decoration:none;
                                font-size:14px;font-weight:600;padding:13px 32px;border-radius:8px;">
                        {label}
                      </a>
                    </td>
                  </tr>
"""

_NOTICE_ROW_TEMPLATE = """\
                  <tr>
                    <td style="padding:0 36px 24px 36px;">
                      <table role="presentation" width="100%" style="background-color:{bg};border:1px solid {border};border-radius:8px;">
                        <tr><td style="padding:14px 16px;font-size:13px;line-height:1.5;color:{text};">{notice}</td></tr>
                      </table>
                    </td>
                  </tr>
"""


def _card(
    eyebrow: str, heading: str, body: str, footnote: str,
    cta_label: str = "", cta_link: str = "", notice: str = "",
) -> str:
    cta_row = _CTA_ROW_TEMPLATE.format(link=cta_link, label=cta_label, primary=_PRIMARY) if cta_link else ""
    notice_row = (
        _NOTICE_ROW_TEMPLATE.format(bg=_ALERT_BG, border=_ALERT_BORDER, text=_ALERT_TEXT, notice=notice)
        if notice else ""
    )
    return _CARD_TEMPLATE.format(
        eyebrow=eyebrow, heading=heading, body=body, footnote=footnote,
        cta_row=cta_row, notice_row=notice_row,
        primary=_PRIMARY, foreground=_FOREGROUND, muted=_MUTED, border=_BORDER, footnote_color=_FOOTNOTE,
    )


def _send(to_email: str, subject: str, html: str) -> None:
    api_key = os.getenv("MAILEROO_API_KEY")
    from_email = os.getenv("MAILEROO_FROM_EMAIL")
    if not api_key or not from_email:
        raise RuntimeError("MAILEROO_API_KEY/MAILEROO_FROM_EMAIL are not set — cannot send email")

    resp = requests.post(
        MAILEROO_API_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "from": {"address": from_email, "display_name": "FinanceAudit"},
            "to": {"address": to_email},
            "subject": subject,
            "html": html,
        },
        timeout=10,
    )
    if not resp.ok:
        raise RuntimeError(f"Maileroo send failed ({resp.status_code}): {resp.text}")


def send_password_reset_email(to_email: str, reset_link: str) -> None:
    html = _card(
        eyebrow="Password Reset",
        heading="Reset your password",
        body="We received a request to reset the password for your FinanceAudit account. Click below to choose a new one.",
        footnote=(
            f"This link expires in 30 minutes. Button not working? Copy and paste this link into your browser: {reset_link}"
        ),
        cta_label="Reset Password",
        cta_link=reset_link,
        notice="Didn't request this? You can safely ignore this email — your password won't be changed.",
    )
    _send(to_email, "Reset your FinanceAudit password", html)


def send_welcome_email(to_email: str, full_name: str | None = None) -> None:
    name = full_name or to_email.split("@")[0]
    html = _card(
        eyebrow="Welcome",
        heading=f"Welcome aboard, {name}",
        body="Your FinanceAudit account is ready. You can log in any time with the email and password you chose.",
        footnote="Didn't create this account? Please contact your administrator.",
    )
    _send(to_email, "Welcome to FinanceAudit", html)


def send_password_changed_email(to_email: str) -> None:
    html = _card(
        eyebrow="Security Notice",
        heading="Your password was changed",
        body="This confirms that the password for your FinanceAudit account was just changed.",
        footnote="If you made this change, no action is needed.",
        notice="Didn't make this change? Contact your administrator immediately — someone else may have access to your account.",
    )
    _send(to_email, "Your FinanceAudit password was changed", html)
