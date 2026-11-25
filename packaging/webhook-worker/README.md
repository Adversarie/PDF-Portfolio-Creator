# PDF Portfolio Maker — Serverless License Fulfillment Webhook

This directory is a self-contained serverless deployment bundle that receives order webhooks, verifies the cryptographic webhook signature, signs an offline Ed25519 `PPM1` license key (`solo` = 1 seat / $49, `firm` = 5 seats / $149), and emails the formatted license block via **Gmail SMTP** (recommended — no custom domain DNS required) or **Resend**.

## 1-Command Deployment (Vercel)

```bash
cd "packaging/webhook-worker"
npx vercel deploy --prod
```

## Required Environment Variables

Configure these secrets in your Vercel Project Settings (or AWS Lambda environment):

1. `ED25519_PRIVATE_KEY_HEX`: Copy from `.secrets/production_ed25519_private_key.txt`.
2. `LEMONSQUEEZY_WEBHOOK_SECRET`: The signing secret configured in your Merchant of Record webhook settings.
3. **Email Delivery (choose Option A or Option B):**
   - **Option A — Gmail SMTP (Recommended, zero domain DNS setup):**
     - `GMAIL_USER`: Your Gmail address (defaults to `matt18201@gmail.com`).
     - `GMAIL_APP_PASSWORD`: 16-character Google App Password generated at https://myaccount.google.com/apppasswords (requires 2-Step Verification enabled on Google Account; spaces are stripped automatically).
     - `GMAIL_FROM_EMAIL` *(optional)*: Custom `From` display/alias header (defaults to `PDF Portfolio Maker <GMAIL_USER>`).
   - **Option B — Resend API (Optional fallback when `GMAIL_APP_PASSWORD` is unset):**
     - `RESEND_API_KEY`: Your Resend API key (`re_...`).
     - `SENDER_EMAIL` *(optional)*: Verified Resend sender address.
