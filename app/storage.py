"""Original PDFs live in a PRIVATE Supabase Storage bucket — never on the server's disk.

We call the Storage REST API directly with `requests` (no SDK), using the
service-role key, which stays on the server. Users never get the key: to open a
PDF they get a short-lived signed URL, issued only after our permission check.
"""
import requests

SIGNED_URL_SECONDS = 300  # a link to the PDF works for 5 minutes


class StorageError(Exception):
    pass


class SupabaseStorage:
    def __init__(self, base_url, service_key, bucket, timeout=15):
        self.base_url = base_url
        self.service_key = service_key
        self.bucket = bucket
        self.timeout = timeout

    def _headers(self, extra=None):
        headers = {"Authorization": f"Bearer {self.service_key}", "apikey": self.service_key}
        headers.update(extra or {})
        return headers

    def upload_pdf(self, key, data):
        url = f"{self.base_url}/storage/v1/object/{self.bucket}/{key}"
        resp = requests.post(
            url,
            data=data,
            headers=self._headers({"Content-Type": "application/pdf", "x-upsert": "false"}),
            timeout=self.timeout,
        )
        if resp.status_code not in (200, 201):
            raise StorageError(f"upload failed with HTTP {resp.status_code}")

    def signed_url(self, key):
        url = f"{self.base_url}/storage/v1/object/sign/{self.bucket}/{key}"
        resp = requests.post(
            url, json={"expiresIn": SIGNED_URL_SECONDS}, headers=self._headers(), timeout=self.timeout
        )
        if resp.status_code != 200:
            raise StorageError(f"signing failed with HTTP {resp.status_code}")
        signed_path = resp.json().get("signedURL") or resp.json().get("signedUrl")
        return f"{self.base_url}/storage/v1{signed_path}"

    def delete(self, key):
        url = f"{self.base_url}/storage/v1/object/{self.bucket}"
        try:
            requests.delete(url, json={"prefixes": [key]}, headers=self._headers(), timeout=self.timeout)
        except requests.RequestException:
            pass  # best effort: an orphaned file is harmless, a failed request is not

    def ping(self):
        if not (self.base_url and self.service_key):
            return False
        try:
            resp = requests.get(
                f"{self.base_url}/storage/v1/bucket/{self.bucket}", headers=self._headers(), timeout=5
            )
            return resp.status_code == 200
        except requests.RequestException:
            return False
