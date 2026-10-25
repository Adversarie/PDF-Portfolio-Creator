"""
packaging/webhook_handler.py
----------------------------
Thin compatibility entry point that delegates to the self-contained serverless
fulfillment bundle in `packaging/webhook-worker/api/webhook.py`.
"""

import importlib.util
from pathlib import Path
from typing import Any, Dict

_WORKER_PATH = Path(__file__).resolve().parent / "webhook-worker" / "api" / "webhook.py"
_spec = importlib.util.spec_from_file_location("webhook_worker", _WORKER_PATH)
_worker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_worker)

verify_signature = _worker.verify_signature
send_fulfillment_email = _worker.send_fulfillment_email
create_signed_ppm1_token = _worker.create_signed_ppm1_token
format_email_block = _worker.format_email_block


def handle_webhook_event(event_headers: Dict[str, str], raw_body: bytes) -> Dict[str, Any]:
    """Delegates webhook processing to `packaging/webhook-worker/api/webhook.py`."""
    res = _worker.process_webhook(event_headers, raw_body)
    return {"status": res["status"], **res["body"]}
