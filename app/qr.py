"""QR-код локально (fallback если Express-Pay не вернул QR)."""
import base64, io
from typing import Optional
import qrcode
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.moduledrawers.pil import RoundedModuleDrawer
from PIL import Image, ImageDraw, ImageFont

def base64_to_png(b64: str) -> bytes:
    if "," in b64:
        b64 = b64.split(",", 1)[1]
    return base64.b64decode(b64)

def generate_local_qr(url: str, label: str = "") -> bytes:
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=10, border=4)
    qr.add_data(url); qr.make(fit=True)
    img = qr.make_image(image_factory=StyledPilImage, module_drawer=RoundedModuleDrawer()).convert("RGB")
    if label:
        w, h = img.size; footer = 52
        canvas = Image.new("RGB", (w, h + footer), (255, 255, 255))
        canvas.paste(img, (0, 0))
        draw = ImageDraw.Draw(canvas)
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
        except OSError:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), label, font=font)
        tw = bbox[2] - bbox[0]
        draw.text(((w - tw) // 2, h + (footer - (bbox[3] - bbox[1])) // 2), label, fill=(30, 30, 30), font=font)
        img = canvas
    buf = io.BytesIO(); img.save(buf, format="PNG", optimize=True); buf.seek(0)
    return buf.read()
