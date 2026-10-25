# PDF Portfolio Maker — Serverless License Fulfillment Webhook

This directory is a self-contained serverless deployment bundle that receives Lemon Squeezy `order_created` webhooks, verifies the `X-Signature` HMAC-SHA256 header, signs an offline Ed25519 `PPM1` license key (`solo` = 1 seat / $49, `firm` = 5 seats / $149), and emails the formatted license block via Resend.

## 1-Command Deployment (Vercel)

```bash
cd "packaging/webhook-worker"
npx vercel deploy --prod
```

## Required Environment Variables

Configure these three secrets in your Vercel Project Settings (or AWS Lambda environment):

1. `ED25519_PRIVATE_KEY_HEX`: Copy from `.secrets/production_ed25519_private_key.txt`.
2. `LEMONSQUEEZY_WEBHOOK_SECRET`: The signing secret configured in Lemon Squeezy (`Settings -> Webhooks`).
3. `RESEND_API_KEY`: Your Resend API key (`re_...`).
4. `SENDER_EMAIL` *(optional)*: Verified Resend sender address (defaults to `PDF Portfolio Maker <licenses@pdfportfoliomaker.com>`).
