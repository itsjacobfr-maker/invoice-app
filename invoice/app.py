from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import os, datetime, json, uuid, base64
from dotenv import load_dotenv

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY", "dev-secret")
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'data.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

# --- Models ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    paypal_active = db.Column(db.Boolean, default=False)
    business_name = db.Column(db.String(200), nullable=True)

class Client(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(200), nullable=True)
    phone = db.Column(db.String(50), nullable=True)

class Invoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    due_date = db.Column(db.DateTime, nullable=True)
    items_json = db.Column(db.Text, nullable=False)
    total = db.Column(db.Float, nullable=False)
    paid = db.Column(db.Boolean, default=False)
    filename = db.Column(db.String(300), nullable=True)
    invoice_number = db.Column(db.String(20), nullable=True)

# --- Flask-Login ---
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- Routes ---
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']
        if User.query.filter_by(email=email).first():
            flash('Email already exists', 'warning')
            return redirect(url_for('register'))
        u = User(email=email, password_hash=generate_password_hash(password))
        db.session.add(u)
        db.session.commit()
        login_user(u)
        return redirect(url_for('dashboard'))
    return render_template('register.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']
        u = User.query.filter_by(email=email).first()
        if not u or not check_password_hash(u.password_hash, password):
            flash('Invalid credentials', 'danger')
            return redirect(url_for('login'))
        login_user(u)
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    if not current_user.paypal_active:
        flash('Subscription required. Please subscribe to continue.', 'warning')
        return redirect(url_for('settings'))
    invoices = Invoice.query.filter_by(user_id=current_user.id).order_by(Invoice.created_at.desc()).all()
    unpaid = [i for i in invoices if not i.paid]
    total_outstanding = sum(i.total for i in unpaid)
    clients = Client.query.filter_by(user_id=current_user.id).all()
    return render_template('dashboard.html', invoices=invoices, total_outstanding=total_outstanding, clients=clients)

@app.route('/clients', methods=['GET','POST'])
@login_required
def clients():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form.get('email')
        phone = request.form.get('phone')
        c = Client(user_id=current_user.id, name=name, email=email, phone=phone)
        db.session.add(c)
        db.session.commit()
        return redirect(url_for('clients'))
    clients = Client.query.filter_by(user_id=current_user.id).all()
    return render_template('clients.html', clients=clients)

@app.route('/invoice/new', methods=['GET','POST'])
@login_required
def invoice_new():
    if request.method == 'POST':
        client_id = request.form.get('client_id') or None
        items_json = request.form['items_json']
        total = float(request.form['total'])
        due_date = request.form.get('due_date') or None
        due = datetime.datetime.strptime(due_date, '%Y-%m-%d') if due_date else None
        inv = Invoice(user_id=current_user.id, client_id=client_id, items_json=items_json, total=total, due_date=due)
        db.session.add(inv)
        db.session.commit()
        return redirect(url_for('dashboard'))
    clients = Client.query.filter_by(user_id=current_user.id).all()
    return render_template('invoice_new.html', clients=clients)

@app.route('/invoice/<int:id>')
@login_required
def invoice_view(id):
    inv = Invoice.query.get_or_404(id)
    if inv.user_id != current_user.id:
        flash("Not allowed", "danger")
        return redirect(url_for('dashboard'))
    client = Client.query.get(inv.client_id) if inv.client_id else None
    items = json.loads(inv.items_json)
    return render_template('invoice_view.html', inv=inv, client=client, items=items)

@app.route('/invoice/<int:id>/download')
@login_required
def invoice_download(id):
    inv = Invoice.query.get_or_404(id)
    if inv.user_id != current_user.id:
        flash("Not allowed", "danger")
        return redirect(url_for('dashboard'))

    uploads = os.path.join(basedir, 'uploads')
    os.makedirs(uploads, exist_ok=True)

    if not inv.filename:
        client = Client.query.get(inv.client_id) if inv.client_id else None
        filename = f"invoice_{inv.id}_{uuid.uuid4().hex[:8]}.pdf"
        path = os.path.join(uploads, filename)

        c = canvas.Canvas(path, pagesize=letter)
        width, height = letter

        # Business info
        c.setFont("Helvetica-Bold", 16)
        c.drawString(50, height-50, current_user.business_name or "Your Business Name")

        # Invoice info
        c.setFont("Helvetica", 12)
        c.drawString(50, height-80, f"Invoice #: {inv.invoice_number or inv.id}")
        c.drawString(50, height-100, f"Created: {inv.created_at.strftime('%Y-%m-%d')}")
        if inv.due_date:
            c.drawString(50, height-120, f"Due: {inv.due_date.strftime('%Y-%m-%d')}")

        # Client info
        if client:
            c.drawString(50, height-150, f"Bill To: {client.name}")
            if client.email: c.drawString(50, height-170, f"Email: {client.email}")
            if client.phone: c.drawString(50, height-190, f"Phone: {client.phone}")

        # Items
        c.drawString(50, height-220, "Items:")
        y = height-240
        try:
            items = json.loads(inv.items_json)
            for item in items:
                desc = item.get("description","")
                qty = item.get("quantity",1)
                price = item.get("unit_price",0)
                total_item = item.get("total",0)
                c.drawString(60, y, f"{desc} | Qty: {qty} | Unit: ${price:.2f} | Total: ${total_item:.2f}")
                y -= 20
        except:
            c.drawString(60, y, "No items found.")
            y -= 20

        # Total & Paid status
        c.drawString(50, y-10, f"Total: ${inv.total:.2f}")
        c.drawString(50, y-30, f"Paid: {'Yes' if inv.paid else 'No'}")

        c.showPage()
        c.save()
        inv.filename = filename
        db.session.commit()

    return send_from_directory(uploads, inv.filename, as_attachment=True)

@app.route('/invoice/<int:id>/mark_paid', methods=['POST'])
@login_required
def invoice_mark_paid(id):
    inv = Invoice.query.get_or_404(id)
    if inv.user_id != current_user.id:
        return jsonify({'ok':False}), 403
    inv.paid = True
    db.session.commit()
    return jsonify({'ok':True})

@app.route('/upload_pdf/<int:id>', methods=['POST'])
@login_required
def upload_pdf(id):
    inv = Invoice.query.get_or_404(id)
    if inv.user_id != current_user.id:
        return jsonify({'ok':False}), 403
    data = request.json.get('pdf_base64')
    if not data:
        return jsonify({'ok':False}), 400
    parts = data.split(',',1)
    b = base64.b64decode(parts[1])
    uploads = os.path.join(basedir, 'uploads')
    os.makedirs(uploads, exist_ok=True)
    filename = f"invoice_{inv.id}_{uuid.uuid4().hex[:8]}.pdf"
    path = os.path.join(uploads, filename)
    with open(path, 'wb') as f:
        f.write(b)
    inv.filename = filename
    db.session.commit()
    return jsonify({'ok':True, 'filename':filename})

# ---- PayPal webhook endpoint ----
@app.route('/paypal/webhook', methods=['POST'])
def paypal_webhook():
    event = request.get_json()
    try:
        etype = event.get('event_type')
        resource = event.get('resource', {})

        subscriber_email = resource.get('subscriber', {}).get('email_address')
        invoice_id = resource.get('custom_id')

        # Update user subscription
        if etype in ('BILLING.SUBSCRIPTION.CANCELLED','BILLING.SUBSCRIPTION.SUSPENDED','PAYMENT.SALE.DENIED'):
            if subscriber_email:
                u = User.query.filter_by(email=subscriber_email.lower()).first()
                if u:
                    u.paypal_active = False
                    db.session.commit()

        elif etype in ('PAYMENT.SALE.COMPLETED','BILLING.SUBSCRIPTION.ACTIVATED','BILLING.SUBSCRIPTION.CREATED'):
            if subscriber_email:
                u = User.query.filter_by(email=subscriber_email.lower()).first()
                if u:
                    u.paypal_active = True
                    db.session.commit()

            if invoice_id:
                inv = Invoice.query.get(int(invoice_id))
                if inv and not inv.paid:
                    inv.paid = True
                    db.session.commit()
                    print(f"Invoice {inv.id} marked as paid via webhook.")

    except Exception as e:
        print("Webhook processing error:", e)

    return jsonify({'ok': True})

# ---- Settings page with PayPal button ----
@app.route('/settings')
@login_required
def settings():
    paypal_plan = os.getenv("PAYPAL_PLAN_ID","REPLACE_WITH_PLAN_ID")
    return render_template('settings.html', paypal_plan=paypal_plan, paypal_active=current_user.paypal_active)

@app.route('/settings', methods=['POST'])
@login_required
def update_settings():
    current_user.business_name = request.form.get('business_name')
    db.session.commit()
    flash('Settings updated', 'success')
    return redirect(url_for('settings'))

# Utility to init DB (not exposed in prod)
@app.cli.command("initdb")
def initdb():
    db.create_all()
    print("DB initialized")

# --- Main ---
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
