"""
src/config.py
-------------
Application build metadata and embedded cryptographic configuration.
"""

APP_NAME = "PDF Portfolio Maker"
APP_VERSION = "1.0.0"
APP_BUILD_DATE = "2026-11-01T00:00:00Z"

# 32-byte Ed25519 public key embedded directly in the application binary
# Used for 100% offline license token verification without network calls.
EMBEDDED_PUBLIC_KEY_HEX = "209850db3e18e6840d4a357cc82562ff0e7f05645d6c7020becd237cf6b6972b"

SUPPORT_EMAIL = "support@pdfportfoliomaker.com"
PURCHASE_URL = "https://pictureperfect.lemonsqueezy.com/checkout"

