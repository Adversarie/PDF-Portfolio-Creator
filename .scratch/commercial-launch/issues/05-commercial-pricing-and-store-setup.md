# 05 Commercial Pricing and Store Setup

Type: grilling
Status: resolved
Blocked by:

## Question

What is the commercial pricing structure, merchant of record platform, and customer terms for the initial release?

1. Merchant of Record selection: Lemon Squeezy vs Gumroad vs Paddle. (Evaluation of fees, VAT/sales tax handling, and webhook reliability).
2. Pricing tiering: One-time perpetual license with 1 year of free updates (e.g. $49 individual / $149 5-seat team pack) vs flat lifetime pricing.
3. Trial mechanism: 14-day evaluation or watermark-stamped Cover Sheet on export.
4. Refund and support policy: 30-day money-back guarantee, email support SLA.

## Answer

### 1. Merchant of Record: Lemon Squeezy
- **Fee**: 5% + 50¢ per successful transaction.
- **Tax Compliance**: Lemon Squeezy acts as the legal reseller, handling 100% of international sales tax, EU VAT, and UK VAT remittance automatically.
- **Integration**: `order_created` JSON webhook triggers serverless Ed25519 license key signing and transactional email delivery via Resend/Postmark.

### 2. Pricing Tiers: Perpetual License with 1 Year of Updates
- **Solo Professional**: **$49** one-time purchase. Grants perpetual use of all releases built within 12 months, valid for activation on up to 2 machines owned by the licensee.
- **Firm / Team Pack**: **$149** one-time purchase. Multi-seat license for up to 5 team members / computers.
- **Upgrade Path**: 50% discount on maintenance renewals after year 1 (optional; existing versions work indefinitely).

### 3. Trial & Evaluation Mechanism
- **Watermarked Cover Sheet**: Evaluation mode has zero artificial time limits and zero file count restrictions so professionals can verify format compliance.
- **Incentive to Purchase**: Exported portfolios in evaluation mode include a header banner on the Cover Sheet: *"Created with PDF Portfolio Maker (Evaluation Copy - Unregistered)"*. Valid license activation immediately unlocks clean, unwatermarked export.

### 4. Guarantee & Support SLA
- **30-Day Money-Back Guarantee**: Full no-questions-asked refund window within 30 days of purchase.
- **Support SLA**: Email support with a 48-hour response target.

