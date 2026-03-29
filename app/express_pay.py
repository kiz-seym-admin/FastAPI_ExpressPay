"""
Интеграция с Express-Pay API v1 (express-pay.by).
Sandbox токен: a75b74cbcfe446509e8ee874f421bd64
"""
import hashlib, hmac, logging, os
from typing import Optional
from urllib.parse import urlencode
import httpx

logger = logging.getLogger(__name__)

EP_TOKEN = os.getenv("EP_TOKEN", "a75b74cbcfe446509e8ee874f421bd64")
EP_SECRET_WORD = os.getenv("EP_SECRET_WORD", "")
EP_IS_TEST = os.getenv("EP_IS_TEST", "true").lower() == "true"
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")

_PROD_API = "https://api.express-pay.by/v1"
_SAND_API = "https://sandbox-api.express-pay.by/v1"
CURRENCY_BYN = 933

def _api_base() -> str:
    return _SAND_API if EP_IS_TEST else _PROD_API

def _sign(params: dict) -> str:
    raw = "".join(str(v) for v in params.values())
    sig = hmac.new(EP_SECRET_WORD.encode(), raw.encode(), hashlib.sha1)
    return sig.hexdigest().upper()

async def create_card_invoice(
    account_no: str, amount: float, info: str,
    return_url: str, fail_url: str,
    expiration: Optional[str] = None, language: str = "ru",
) -> dict:
    url = f"{_api_base()}/cardinvoices?token={EP_TOKEN}"
    params = {
        "Token": EP_TOKEN, "AccountNo": account_no,
        "Amount": f"{amount:.2f}".replace(".", ","),
        "Currency": CURRENCY_BYN, "Info": info,
        "ReturnUrl": return_url, "FailUrl": fail_url, "Language": language,
    }
    if expiration:
        params["Expiration"] = expiration
    if EP_SECRET_WORD:
        sign_params = {k: v for k, v in params.items() if k not in ("SmsPhone", "LifeTime")}
        params["signature"] = _sign(sign_params)
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, data=params)
        if resp.status_code not in (200, 201):
            logger.error(f"EP cardinvoices error {resp.status_code}: {resp.text}")
        resp.raise_for_status()
        return resp.json()

async def get_card_invoice_status(invoice_no: int) -> dict:
    params = {"Token": EP_TOKEN, "InvoiceNo": str(invoice_no)}
    if EP_SECRET_WORD:
        params["signature"] = _sign(params)
    url = f"{_api_base()}/cardinvoices/{invoice_no}/status?" + urlencode(params)
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()

async def get_qr_code_base64(invoice_no: int) -> Optional[str]:
    params = {"Token": EP_TOKEN, "InvoiceId": str(invoice_no), "ViewType": "base64"}
    if EP_SECRET_WORD:
        params["signature"] = _sign(params)
    url = f"{_api_base()}/qrcode/getqrcode/?" + urlencode(params)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json().get("QrCodeBody")
    except Exception as exc:
        logger.warning(f"EP QR error: {exc}")
        return None

async def run_startup_test() -> dict:
    import uuid
    account_no = f"test-{uuid.uuid4().hex[:10]}"
    try:
        result = await create_card_invoice(
            account_no=account_no, amount=1.00,
            info="Автоматический тест при запуске",
            return_url=f"{BASE_URL}/payment/success",
            fail_url=f"{BASE_URL}/payment/fail",
        )
        return {
            "account_no": account_no, "ok": result.get("InvoiceNo") is not None,
            "invoice_no": result.get("InvoiceNo"),
            "card_invoice_no": result.get("CardInvoiceNo"),
            "form_url": result.get("FormUrl") or None, "raw": result,
        }
    except Exception as exc:
        return {"account_no": account_no, "ok": False, "error": str(exc), "raw": {}}
