"""Transactional email via Resend. Each send_* function is kept separate and
trivial to mock in tests; _send and _card do the shared plumbing/markup."""
import os

import resend

_CARD_TEMPLATE = """\
<!DOCTYPE html>
<html>
  <body style="margin:0;padding:0;background-color:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f1f5f9;padding:32px 16px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" style="max-width:480px;background-color:#ffffff;border-radius:12px;border:1px solid #e2e8f0;overflow:hidden;">
            <tr>
              <td style="padding:32px 32px 24px 32px;text-align:center;">
                <div style="font-size:24px;font-weight:700;color:#0f172a;">💰 FinanceAudit</div>
              </td>
            </tr>
            <tr>
              <td style="padding:0 32px 8px 32px;">
                <h1 style="font-size:18px;font-weight:600;color:#0f172a;margin:0 0 12px 0;">{heading}</h1>
                <p style="font-size:14px;line-height:1.6;color:#475569;margin:0 0 24px 0;">{body}</p>
              </td>
            </tr>
            {cta_row}
            <tr>
              <td style="padding:0 32px 32px 32px;">
                <p style="font-size:12px;line-height:1.6;color:#94a3b8;margin:0;">{footnote}</p>
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
              <td style="padding:0 32px 24px 32px;text-align:center;">
                <a href="{link}"
                   style="display:inline-block;background-color:#0f172a;color:#ffffff;text-decoration:none;
                          font-size:14px;font-weight:600;padding:12px 28px;border-radius:8px;">
                  {label}
                </a>
              </td>
            </tr>
"""


def _card(heading: str, body: str, footnote: str, cta_label: str = "", cta_link: str = "") -> str:
    cta_row = _CTA_ROW_TEMPLATE.format(link=cta_link, label=cta_label) if cta_link else ""
    return _CARD_TEMPLATE.format(heading=heading, body=body, cta_row=cta_row, footnote=footnote)


def _send(to_email: str, subject: str, html: str) -> None:
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        raise RuntimeError("RESEND_API_KEY is not set — cannot send email")

    resend.api_key = api_key
    from_email = os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev")

    resend.Emails.send({
        "from": f"FinanceAudit <{from_email}>",
        "to": [to_email],
        "subject": subject,
        "html": html,
    })


def send_password_reset_email(to_email: str, reset_link: str) -> None:
    html = _card(
        heading="Reset your password",
        body="Someone requested a password reset for this account. Click the button below to choose a new password.",
        footnote=(
            "This link expires in 30 minutes. If you didn't request this, you can safely ignore this email — "
            f"your password won't be changed.<br><br>Button not working? Copy and paste this link: {reset_link}"
        ),
        cta_label="Reset Password",
        cta_link=reset_link,
    )
    _send(to_email, "Reset your FinanceAudit password", html)


def send_welcome_email(to_email: str, full_name: str | None = None) -> None:
    name = full_name or to_email.split("@")[0]
    html = _card(
        heading=f"Welcome, {name}!",
        body="Your FinanceAudit account has been created. You can log in any time with the email and password you chose.",
        footnote="If you didn't create this account, please contact your administrator.",
    )
    _send(to_email, "Welcome to FinanceAudit", html)


def send_password_changed_email(to_email: str) -> None:
    html = _card(
        heading="Your password was changed",
        body="This is a confirmation that the password for your FinanceAudit account was just changed.",
        footnote=(
            "If you made this change, no action is needed. If you didn't, contact your administrator immediately — "
            "someone else may have access to your account."
        ),
    )
    _send(to_email, "Your FinanceAudit password was changed", html)
