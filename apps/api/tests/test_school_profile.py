"""School Profile API — singleton profile with logo upload.

GET is open to any authenticated user (header/report branding); PUT and
logo upload require the user_management permission. The logo is stored as
base64 in the DB and served back as a data URI.
"""
import base64

# 1×1 transparent PNG — smallest valid PNG for upload round-trips.
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)

PROFILE_BODY = {
    "name": "Marvelous Light School",
    "tagline": "LEARN SHINE LEAD",
    "phone": "+2348154027867, +2347038692765",
    "website": "https://example.edu.ng",
    "address": "05 Life success school",
    "country": "Nigeria",
}


class TestGetProfile:
    def test_get_returns_empty_defaults_when_unset(self, client):
        r = client.get("/school-profile")
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == ""
        assert body["logo"] is None
        assert body["country"] == "Nigeria"

    def test_get_requires_auth(self, anon_client):
        # HTTPBearer rejects missing credentials with 403 (repo-wide convention)
        r = anon_client.get("/school-profile")
        assert r.status_code == 403


class TestUpdateProfile:
    def test_admin_can_create_and_get_reflects(self, admin_client):
        r = admin_client.put("/school-profile", json=PROFILE_BODY)
        assert r.status_code == 200
        assert r.json()["name"] == "Marvelous Light School"
        assert r.json()["tagline"] == "LEARN SHINE LEAD"

        r2 = admin_client.get("/school-profile")
        assert r2.json()["phone"] == "+2348154027867, +2347038692765"
        assert r2.json()["address"] == "05 Life success school"

    def test_admin_can_update_existing(self, admin_client):
        admin_client.put("/school-profile", json=PROFILE_BODY)
        r = admin_client.put(
            "/school-profile", json={**PROFILE_BODY, "name": "Renamed School"}
        )
        assert r.status_code == 200
        assert r.json()["name"] == "Renamed School"

    def test_blank_name_rejected(self, admin_client):
        r = admin_client.put("/school-profile", json={**PROFILE_BODY, "name": "   "})
        assert r.status_code == 422

    def test_non_admin_cannot_update(self, client):
        # `client` is an Accountant — every permission except user_management
        r = client.put("/school-profile", json=PROFILE_BODY)
        assert r.status_code == 403

    def test_update_is_audit_logged(self, admin_client):
        admin_client.put("/school-profile", json=PROFILE_BODY)
        r = admin_client.get("/audit-log", params={"entity_type": "school_profile"})
        assert r.status_code == 200
        entries = r.json()
        assert any(e["entity_type"] == "school_profile" for e in entries)


class TestLogoUpload:
    def _upload(self, http, content: bytes, mime: str = "image/png"):
        return http.post(
            "/school-profile/logo",
            files={"file": ("logo.png", content, mime)},
        )

    def test_valid_png_roundtrip(self, admin_client):
        r = self._upload(admin_client, PNG_1PX)
        assert r.status_code == 200
        logo = r.json()["logo"]
        assert logo is not None
        assert logo.startswith("data:image/png;base64,")
        assert base64.b64decode(logo.split(",", 1)[1]) == PNG_1PX

        r2 = admin_client.get("/school-profile")
        assert r2.json()["logo"] == logo

    def test_logo_upload_before_profile_created(self, admin_client):
        # Uploading a logo with no profile row yet must not 500
        r = self._upload(admin_client, PNG_1PX)
        assert r.status_code == 200

    def test_rejects_non_image_content(self, admin_client):
        r = self._upload(admin_client, b"not an image at all", mime="image/png")
        assert r.status_code == 400

    def test_rejects_oversize_file(self, admin_client):
        big = PNG_1PX + b"\x00" * (500 * 1024)
        r = self._upload(admin_client, big)
        assert r.status_code == 413

    def test_rejects_empty_file(self, admin_client):
        r = self._upload(admin_client, b"")
        assert r.status_code == 400

    def test_non_admin_cannot_upload(self, client):
        r = self._upload(client, PNG_1PX)
        assert r.status_code == 403


class TestReportBranding:
    def test_audit_report_renders_with_profile_and_logo(self, admin_client):
        admin_client.put("/school-profile", json=PROFILE_BODY)
        admin_client.post(
            "/school-profile/logo",
            files={"file": ("logo.png", PNG_1PX, "image/png")},
        )
        r = admin_client.get("/reports/audit-report")
        assert r.status_code == 200
        assert r.content.startswith(b"%PDF")

    def test_audit_report_renders_without_profile(self, admin_client):
        r = admin_client.get("/reports/audit-report")
        assert r.status_code == 200
        assert r.content.startswith(b"%PDF")
