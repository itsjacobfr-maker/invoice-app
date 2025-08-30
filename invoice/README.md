# InvoiceApp (Minimal)
Simple invoice generator with PayPal subscription integration (basic).

## What it does
- User registration/login
- Create clients
- Create invoices (line items) and save them to SQLite
- Client-side PDF generation (jsPDF) with upload to server for storage
- PayPal subscription button (client-side). Webhook endpoint exists to process subscription events.

## Quick start (local)
1. Install deps:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
2. Edit `.env` and set `SECRET_KEY` and `PAYPAL_PLAN_ID` (see PayPal docs to create a subscription plan).
3. Initialize DB:
   ```bash
   flask --app app.py initdb
   ```
4. Run the app:
   ```bash
   flask --app app.py run
   ```
5. Visit `http://127.0.0.1:5000` and register. Then go to Settings to subscribe via PayPal.

## PayPal notes
- Create a **Subscription Plan** in PayPal (either sandbox or live). Use the Plan ID and put it in `.env` as `PAYPAL_PLAN_ID`.
- Configure a PayPal webhook (in Developer Dashboard) to call `https://<your-server>/paypal/webhook` and subscribe to relevant events (e.g., `BILLING.SUBSCRIPTION.*`, `PAYMENT.SALE.COMPLETED`). For local testing, use a tunnel like `ngrok` to expose your local server.
- This app's webhook handler is minimal — it identifies users by subscriber email or custom_id and toggles `paypal_active`. For production, verify webhook signatures and validate events per PayPal docs.

## Limitations / Security
- Minimal webhook verification: **not secure** for production. Implement signature verification.
- Passwords are stored hashed, but there are no email verifications.
- No rate limiting or CSRF tokens — add for production.
- The app uses client-side PDF generation for simplicity.

## Files
- `app.py` — Flask app
- `templates/` — HTML templates
- `static/` — static files (js/css)
- `.env` — config (do not commit in public repos)

## License
MIT. You can sell/modify as you like. Good luck!
