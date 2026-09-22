
from flask import Flask, render_template, request, redirect, session, flash, make_response
from flask_mail import Mail, Message
import sqlite3
import bcrypt
import random
import config
import os
import razorpay
from werkzeug.utils import secure_filename
from utils.pdf_generator import generate_pdf
from init_db import init_db

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

# Initialize SQLite database schema
init_db()

# =========================================================
# EMAIL CONFIGURATION
# =========================================================

app.config['MAIL_SERVER'] = config.MAIL_SERVER
app.config['MAIL_PORT'] = config.MAIL_PORT
app.config['MAIL_USE_TLS'] = config.MAIL_USE_TLS
app.config['MAIL_USERNAME'] = config.MAIL_USERNAME
app.config['MAIL_PASSWORD'] = config.MAIL_PASSWORD

mail = Mail(app)

# =========================================================
# RAZORPAY CONFIGURATION
# =========================================================

razorpay_client = razorpay.Client(
    auth=(
        config.RAZORPAY_KEY_ID,
        config.RAZORPAY_KEY_SECRET
    )
)


# =========================================================
# DATABASE CONNECTION
# =========================================================

def get_db_connection():

    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


# =========================================================
# LOAD USER CART FROM DATABASE
# =========================================================

def load_user_cart(user_id):

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            c.product_id,
            c.quantity,
            p.name,
            p.price,
            p.image
        FROM cart_items c
        JOIN products p
            ON c.product_id = p.product_id
        WHERE c.user_id = ?
    """, (user_id,))

    items = cursor.fetchall()

    cursor.close()
    conn.close()

    cart = {}

    for item in items:

        pid = str(item['product_id'])

        cart[pid] = {
            'name': item['name'],
            'price': float(item['price']),
            'image': item['image'],
            'quantity': item['quantity']
        }

    return cart


# =========================================================
# SAVE USER CART TO DATABASE
# =========================================================

def save_user_cart(user_id, cart):

    conn = get_db_connection()
    cursor = conn.cursor()

    # Remove old cart records for this user
    cursor.execute(
        "DELETE FROM cart_items WHERE user_id=?",
        (user_id,)
    )

    # Insert current cart
    for pid, item in cart.items():

        cursor.execute("""
            INSERT INTO cart_items
            (
                user_id,
                product_id,
                quantity
            )
            VALUES (?, ?, ?)
        """, (
            user_id,
            int(pid),
            item['quantity']
        ))

    conn.commit()

    cursor.close()
    conn.close()


# =========================================================
# HOME
# =========================================================

@app.route('/')
def home():

    return redirect('/admin-signup')


# =========================================================
# ADMIN SIGNUP
# =========================================================

@app.route('/admin-signup', methods=['GET', 'POST'])
def admin_signup():

    if request.method == "GET":
        return render_template(
            "admin/admin_signup.html"
        )

    name = request.form['name']
    email = request.form['email']

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT admin_id FROM admin WHERE email=?",
        (email,)
    )

    existing_admin = cursor.fetchone()

    cursor.close()
    conn.close()

    if existing_admin:

        flash(
            "This email is already registered. "
            "Please login instead.",
            "danger"
        )

        return redirect('/admin-login')

    session['signup_name'] = name
    session['signup_email'] = email

    otp = random.randint(
        100000,
        999999
    )

    session['otp'] = otp

    message = Message(
        subject="SmartCart Admin OTP",
        sender=config.MAIL_USERNAME,
        recipients=[email]
    )

    message.body = (
        f"Your OTP for SmartCart "
        f"Admin Registration is: {otp}"
    )

    mail.send(message)

    flash(
        "OTP sent to your email!",
        "success"
    )

    return redirect('/verify-otp')


# =========================================================
# ADMIN OTP PAGE
# =========================================================

@app.route('/verify-otp', methods=['GET'])
def verify_otp_get():

    return render_template(
        "admin/verify_otp.html"
    )


# =========================================================
# ADMIN VERIFY OTP
# =========================================================

@app.route('/verify-otp', methods=['POST'])
def verify_otp_post():

    user_otp = request.form['otp']
    password = request.form['password']

    if str(session.get('otp')) != str(user_otp):

        flash(
            "Invalid OTP. Try again!",
            "danger"
        )

        return redirect('/verify-otp')

    hashed_password = bcrypt.hashpw(
        password.encode('utf-8'),
        bcrypt.gensalt()
    ).decode('utf-8')

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO admin
        (name, email, password)
        VALUES (?, ?, ?)
        """,
        (
            session['signup_name'],
            session['signup_email'],
            hashed_password
        )
    )

    conn.commit()

    cursor.close()
    conn.close()

    session.pop('otp', None)
    session.pop('signup_name', None)
    session.pop('signup_email', None)

    flash(
        "Admin Registered Successfully!",
        "success"
    )

    return redirect('/admin-signup')


# =========================================================
# ADMIN LOGIN
# =========================================================

@app.route(
    '/admin-login',
    methods=['GET', 'POST']
)
def admin_login():

    if request.method == 'GET':

        return render_template(
            "admin/admin_login.html"
        )

    email = request.form['email']
    password = request.form['password']

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM admin WHERE email=?",
        (email,)
    )

    admin = cursor.fetchone()

    cursor.close()
    conn.close()

    if admin is None:

        flash(
            "Email not found! Please register first.",
            "danger"
        )

        return redirect('/admin-login')

    stored = admin['password']
    stored_hashed_password = stored.encode('utf-8') if isinstance(stored, str) else stored

    if not bcrypt.checkpw(
        password.encode('utf-8'),
        stored_hashed_password
    ):

        flash(
            "Incorrect password! Try again.",
            "danger"
        )

        return redirect('/admin-login')

    session['admin_id'] = admin['admin_id']
    session['admin_name'] = admin['name']
    session['admin_email'] = admin['email']

    flash(
        "Login Successful!",
        "success"
    )

    return redirect('/admin-dashboard')


# =========================================================
# ADMIN DASHBOARD
# =========================================================

@app.route('/admin-dashboard')
def admin_dashboard():

    if 'admin_id' not in session:

        flash(
            "Please login to access dashboard!",
            "danger"
        )

        return redirect('/admin-login')

    return render_template(
        "admin/dashboard.html",
        admin_name=session['admin_name']
    )


# =========================================================
# ADMIN LOGOUT
# =========================================================

@app.route('/admin-logout')
def admin_logout():

    session.pop('admin_id', None)
    session.pop('admin_name', None)
    session.pop('admin_email', None)

    flash(
        "Logged out successfully.",
        "success"
    )

    return redirect('/admin-login')


# =========================================================
# IMAGE UPLOAD PATHS
# =========================================================

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'uploads', 'product_images')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

ADMIN_UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'uploads', 'admin_profiles')
app.config['ADMIN_UPLOAD_FOLDER'] = ADMIN_UPLOAD_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(ADMIN_UPLOAD_FOLDER, exist_ok=True)


# =========================================================
# ADMIN ADD PRODUCT PAGE
# =========================================================

@app.route(
    '/admin/add-item',
    methods=['GET']
)
def add_item_page():

    if 'admin_id' not in session:

        flash(
            "Please login first!",
            "danger"
        )

        return redirect('/admin-login')

    return render_template(
        "admin/add_item.html"
    )


# =========================================================
# ADMIN ADD PRODUCT
# =========================================================

@app.route(
    '/admin/add-item',
    methods=['POST']
)
def add_item():

    if 'admin_id' not in session:

        flash(
            "Please login first!",
            "danger"
        )

        return redirect('/admin-login')

    name = request.form['name']
    description = request.form['description']
    category = request.form['category']
    price = request.form['price']

    image_file = request.files['image']

    if image_file.filename == "":

        flash(
            "Please upload a product image!",
            "danger"
        )

        return redirect('/admin/add-item')

    filename = secure_filename(
        image_file.filename
    )

    image_path = os.path.join(
        app.config['UPLOAD_FOLDER'],
        filename
    )

    image_file.save(image_path)

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO products
        (
            name,
            description,
            category,
            price,
            image
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        name,
        description,
        category,
        price,
        filename
    ))

    conn.commit()

    cursor.close()
    conn.close()

    flash(
        "Product added successfully!",
        "success"
    )

    return redirect('/admin/add-item')


# =========================================================
# ADMIN VIEW SINGLE PRODUCT
# =========================================================

@app.route(
    '/admin/view-item/<int:item_id>'
)
def view_item(item_id):

    if 'admin_id' not in session:

        flash(
            "Please login first!",
            "danger"
        )

        return redirect('/admin-login')

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *
        FROM products
        WHERE product_id=?
        """,
        (item_id,)
    )

    product = cursor.fetchone()

    cursor.close()
    conn.close()

    if not product:

        flash(
            "Product not found!",
            "danger"
        )

        return redirect('/admin/item-list')

    return render_template(
        "admin/view_item.html",
        product=product
    )


# =========================================================
# ADMIN UPDATE PRODUCT PAGE
# =========================================================

@app.route(
    '/admin/update-item/<int:item_id>',
    methods=['GET']
)
def update_item_page(item_id):

    if 'admin_id' not in session:

        flash(
            "Please login!",
            "danger"
        )

        return redirect('/admin-login')

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *
        FROM products
        WHERE product_id=?
        """,
        (item_id,)
    )

    product = cursor.fetchone()

    cursor.close()
    conn.close()

    if not product:

        flash(
            "Product not found!",
            "danger"
        )

        return redirect('/admin/item-list')

    return render_template(
        "admin/update_item.html",
        product=product
    )


# =========================================================
# ADMIN UPDATE PRODUCT
# =========================================================

@app.route(
    '/admin/update-item/<int:item_id>',
    methods=['POST']
)
def update_item(item_id):

    if 'admin_id' not in session:

        flash(
            "Please login!",
            "danger"
        )

        return redirect('/admin-login')

    name = request.form['name']
    description = request.form['description']
    category = request.form['category']
    price = request.form['price']

    new_image = request.files['image']

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *
        FROM products
        WHERE product_id=?
        """,
        (item_id,)
    )

    product = cursor.fetchone()

    if not product:

        cursor.close()
        conn.close()

        flash(
            "Product not found!",
            "danger"
        )

        return redirect('/admin/item-list')

    old_image_name = product['image']

    if new_image and new_image.filename != "":

        new_filename = secure_filename(
            new_image.filename
        )

        new_image_path = os.path.join(
            app.config['UPLOAD_FOLDER'],
            new_filename
        )

        new_image.save(
            new_image_path
        )

        old_image_path = os.path.join(
            app.config['UPLOAD_FOLDER'],
            old_image_name
        )

        if os.path.exists(old_image_path):
            os.remove(old_image_path)

        final_image_name = new_filename

    else:

        final_image_name = old_image_name

    cursor.execute("""
        UPDATE products
        SET
            name=?,
            description=?,
            category=?,
            price=?,
            image=?
        WHERE product_id=?
    """, (
        name,
        description,
        category,
        price,
        final_image_name,
        item_id
    ))

    conn.commit()

    cursor.close()
    conn.close()

    flash(
        "Product updated successfully!",
        "success"
    )

    return redirect('/admin/item-list')


# =========================================================
# ADMIN PRODUCT LIST
# =========================================================

@app.route('/admin/item-list')
def item_list():

    if 'admin_id' not in session:

        flash(
            "Please login!",
            "danger"
        )

        return redirect('/admin-login')

    search = request.args.get(
        'search',
        ''
    )

    category_filter = request.args.get(
        'category',
        ''
    )

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT DISTINCT category FROM products"
    )

    categories = cursor.fetchall()

    query = (
        "SELECT * FROM products WHERE 1=1"
    )

    params = []

    if search:

        query += " AND name LIKE ?"

        params.append(
            "%" + search + "%"
        )

    if category_filter:

        query += " AND category=?"

        params.append(
            category_filter
        )

    cursor.execute(
        query,
        params
    )

    products = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "admin/item_list.html",
        products=products,
        categories=categories
    )


# =========================================================
# ADMIN DELETE PRODUCT
# =========================================================

@app.route(
    '/admin/delete-item/<int:item_id>'
)
def delete_item(item_id):

    if 'admin_id' not in session:

        flash(
            "Please login first!",
            "danger"
        )

        return redirect('/admin-login')

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT image
        FROM products
        WHERE product_id=?
        """,
        (item_id,)
    )

    product = cursor.fetchone()

    if not product:

        cursor.close()
        conn.close()

        flash(
            "Product not found!",
            "danger"
        )

        return redirect('/admin/item-list')

    image_name = product['image']

    image_path = os.path.join(
        app.config['UPLOAD_FOLDER'],
        image_name
    )

    if os.path.exists(image_path):
        os.remove(image_path)

    cursor.execute(
        """
        DELETE FROM products
        WHERE product_id=?
        """,
        (item_id,)
    )

    conn.commit()

    cursor.close()
    conn.close()

    flash(
        "Product deleted successfully!",
        "success"
    )

    return redirect('/admin/item-list')


# =========================================================
# ADMIN PROFILE
# =========================================================

@app.route(
    '/admin/profile',
    methods=['GET']
)
def admin_profile():

    if 'admin_id' not in session:

        flash(
            "Please login!",
            "danger"
        )

        return redirect('/admin-login')

    admin_id = session['admin_id']

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *
        FROM admin
        WHERE admin_id=?
        """,
        (admin_id,)
    )

    admin = cursor.fetchone()

    cursor.close()
    conn.close()

    return render_template(
        "admin/admin_profile.html",
        admin=admin
    )


# =========================================================
# UPDATE ADMIN PROFILE
# =========================================================

@app.route(
    '/admin/profile',
    methods=['POST']
)
def admin_profile_update():

    if 'admin_id' not in session:

        flash(
            "Please login!",
            "danger"
        )

        return redirect('/admin-login')

    admin_id = session['admin_id']

    name = request.form['name']
    email = request.form['email']
    new_password = request.form['password']
    new_image = request.files['profile_image']

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *
        FROM admin
        WHERE admin_id=?
        """,
        (admin_id,)
    )

    admin = cursor.fetchone()

    old_image_name = admin['profile_image']

    if new_password:

        hashed_password = bcrypt.hashpw(
            new_password.encode('utf-8'),
            bcrypt.gensalt()
        ).decode('utf-8')

    else:

        hashed_password = admin['password']

    if new_image and new_image.filename != "":

        new_filename = secure_filename(
            new_image.filename
        )

        image_path = os.path.join(
            app.config['ADMIN_UPLOAD_FOLDER'],
            new_filename
        )

        new_image.save(image_path)

        if old_image_name:

            old_image_path = os.path.join(
                app.config['ADMIN_UPLOAD_FOLDER'],
                old_image_name
            )

            if os.path.exists(old_image_path):
                os.remove(old_image_path)

        final_image_name = new_filename

    else:

        final_image_name = old_image_name

    cursor.execute("""
        UPDATE admin
        SET
            name=?,
            email=?,
            password=?,
            profile_image=?
        WHERE admin_id=?
    """, (
        name,
        email,
        hashed_password,
        final_image_name,
        admin_id
    ))

    conn.commit()

    cursor.close()
    conn.close()

    session['admin_name'] = name
    session['admin_email'] = email

    flash(
        "Profile updated successfully!",
        "success"
    )

    return redirect('/admin/profile')


# =========================================================
# USER SIGNUP
# =========================================================

@app.route(
    '/user-signup',
    methods=['GET', 'POST']
)
def user_signup():

    if request.method == "GET":

        return render_template(
            "user/user_signup.html"
        )

    name = request.form['name']
    email = request.form['email']

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT admin_id
        FROM admin
        WHERE email=?
        """,
        (email,)
    )

    existing_user = cursor.fetchone()

    cursor.close()
    conn.close()

    if existing_user:

        flash(
            "This email is already registered. "
            "Please login instead.",
            "danger"
        )

        return redirect('/user-login')

    session['signup_name'] = name
    session['signup_email'] = email

    otp = random.randint(
        100000,
        999999
    )

    session['otp'] = otp

    message = Message(
        subject="SmartCart User OTP",
        sender=config.MAIL_USERNAME,
        recipients=[email]
    )

    message.body = (
        f"Your OTP for SmartCart "
        f"user registration is: {otp}"
    )

    mail.send(message)

    flash(
        "OTP sent to your email!",
        "success"
    )

    return redirect('/verify-otp')


# =========================================================
# USER OTP PAGE
# =========================================================

@app.route(
    '/user/verify-otp',
    methods=['GET']
)
def verify_user_otp_get():

    return render_template(
        "user/verify_otp.html"
    )


# =========================================================
# USER VERIFY OTP
# =========================================================

@app.route(
    '/user/verify-otp',
    methods=['POST']
)
def verify_user_otp_post():

    user_otp = request.form['otp']
    password = request.form['password']

    if str(session.get('otp')) != str(user_otp):

        flash(
            "Invalid OTP. Try again!",
            "danger"
        )

        return redirect('/user/verify-otp')

    hashed_password = bcrypt.hashpw(
        password.encode('utf-8'),
        bcrypt.gensalt()
    ).decode('utf-8')

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO admin
        (name, email, password)
        VALUES (?, ?, ?)
    """, (
        session['signup_name'],
        session['signup_email'],
        hashed_password
    ))

    conn.commit()

    cursor.close()
    conn.close()

    session.pop('otp', None)
    session.pop('signup_name', None)
    session.pop('signup_email', None)

    flash(
        "User Registered Successfully!",
        "success"
    )

    return redirect('/user-login')


# =========================================================
# USER LOGIN
# =========================================================

@app.route(
    '/user-login',
    methods=['GET', 'POST']
)
def user_login():

    if request.method == 'GET':

        return render_template(
            "user/user_login.html"
        )

    email = request.form['email']
    password = request.form['password']

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *
        FROM admin
        WHERE email=?
        """,
        (email,)
    )

    user = cursor.fetchone()

    cursor.close()
    conn.close()

    if user is None:

        flash(
            "Email not found! Please register first.",
            "danger"
        )

        return redirect('/user-login')

    stored = user['password']
    stored_hashed_password = stored.encode('utf-8') if isinstance(stored, str) else stored

    if not bcrypt.checkpw(
        password.encode('utf-8'),
        stored_hashed_password
    ):

        flash(
            "Incorrect password! Try again.",
            "danger"
        )

        return redirect('/user-login')

    session['user_id'] = user['admin_id']
    session['user_name'] = user['name']
    session['user_email'] = user['email']

    # -----------------------------------------------------
    # RESTORE THIS USER'S CART FROM DATABASE
    # -----------------------------------------------------

    session['cart'] = load_user_cart(
        session['user_id']
    )

    flash(
        "Login Successful!",
        "success"
    )

    return redirect('/user-dashboard')


# =========================================================
# USER DASHBOARD
# =========================================================

@app.route('/user-dashboard')
def user_dashboard():

    if 'user_id' not in session:

        flash(
            "Please login!",
            "danger"
        )

        return redirect('/user-login')

    return render_template(
        "user/user_dashboard.html",
        user_name=session.get('user_name')
    )


# =========================================================
# USER VIEW PRODUCTS
# =========================================================

@app.route('/user/products')
def user_products():

    if 'user_id' not in session:

        flash(
            "Please login!",
            "danger"
        )

        return redirect('/user-login')

    search = request.args.get(
        'search',
        ''
    )

    category_filter = request.args.get(
        'category',
        ''
    )

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT DISTINCT category FROM products"
    )

    categories = cursor.fetchall()

    query = (
        "SELECT * FROM products WHERE 1=1"
    )

    params = []

    if search:

        query += " AND name LIKE ?"

        params.append(
            "%" + search + "%"
        )

    if category_filter:

        query += " AND category=?"

        params.append(
            category_filter
        )

    cursor.execute(
        query,
        params
    )

    products = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "user/user_products.html",
        products=products,
        categories=categories
    )


# =========================================================
# USER VIEW SINGLE PRODUCT
# =========================================================

@app.route(
    '/user/user-view-item/<int:product_id>'
)
def user_view_item(product_id):

    if 'user_id' not in session:

        flash(
            "Please login!",
            "danger"
        )

        return redirect('/user-login')

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *
        FROM products
        WHERE product_id=?
        """,
        (product_id,)
    )

    product = cursor.fetchone()

    cursor.close()
    conn.close()

    if not product:

        flash(
            "Product not found!",
            "danger"
        )

        return redirect('/user/products')

    return render_template(
        "user/user_view_item.html",
        product=product
    )


# =========================================================
# USER ADD TO CART
# =========================================================

@app.route(
    '/user/add-to-cart/<int:product_id>'
)
def add_to_cart(product_id):

    if 'user_id' not in session:

        flash(
            "Please login first!",
            "danger"
        )

        return redirect('/user-login')

    if 'cart' not in session:
        session['cart'] = {}

    cart = session['cart']

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *
        FROM products
        WHERE product_id=?
        """,
        (product_id,)
    )

    product = cursor.fetchone()

    cursor.close()
    conn.close()

    if not product:

        flash(
            "Product not found!",
            "danger"
        )

        return redirect('/user/products')

    pid = str(product_id)

    if pid in cart:

        cart[pid]['quantity'] += 1

    else:

        cart[pid] = {
            'name': product['name'],
            'price': float(product['price']),
            'image': product['image'],
            'quantity': 1
        }

    session['cart'] = cart

    # Save permanently
    save_user_cart(
        session['user_id'],
        cart
    )

    flash(
        "Item added to cart!",
        "success"
    )

    return redirect(
        request.referrer or '/user/products'
    )


# =========================================================
# USER VIEW CART
# =========================================================

@app.route('/user/cart')
def view_cart():

    if 'user_id' not in session:

        flash(
            "Please login first!",
            "danger"
        )

        return redirect('/user-login')

    cart = session.get('cart', {})

    grand_total = sum(
        item['price'] * item['quantity']
        for item in cart.values()
    )

    return render_template(
        "user/cart.html",
        cart=cart,
        grand_total=grand_total
    )


# =========================================================
# NORMAL INCREASE QUANTITY
# =========================================================

@app.route(
    '/user/cart/increase/<pid>'
)
def increase_quantity(pid):

    if 'user_id' not in session:
        return redirect('/user-login')

    cart = session.get('cart', {})

    if pid in cart:

        cart[pid]['quantity'] += 1

        session['cart'] = cart

        save_user_cart(
            session['user_id'],
            cart
        )

    return redirect('/user/cart')


# =========================================================
# NORMAL DECREASE QUANTITY
# =========================================================

@app.route(
    '/user/cart/decrease/<pid>'
)
def decrease_quantity(pid):

    if 'user_id' not in session:
        return redirect('/user-login')

    cart = session.get('cart', {})

    if pid in cart:

        cart[pid]['quantity'] -= 1

        if cart[pid]['quantity'] <= 0:
            cart.pop(pid)

        session['cart'] = cart

        save_user_cart(
            session['user_id'],
            cart
        )

    return redirect('/user/cart')


# =========================================================
# REMOVE FROM CART
# =========================================================

@app.route(
    '/user/cart/remove/<pid>'
)
def remove_from_cart(pid):

    if 'user_id' not in session:
        return redirect('/user-login')

    cart = session.get('cart', {})

    if pid in cart:

        cart.pop(pid)

        session['cart'] = cart

        save_user_cart(
            session['user_id'],
            cart
        )

        flash(
            "Item removed from cart!",
            "success"
        )

    return redirect('/user/cart')


# =========================================================
# AJAX ADD TO CART
# =========================================================

@app.route(
    '/user/add-to-cart-ajax/<int:product_id>'
)
def add_to_cart_ajax(product_id):

    if 'user_id' not in session:

        return {
            "error": "not_logged_in"
        }, 401

    if 'cart' not in session:
        session['cart'] = {}

    cart = session['cart']

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *
        FROM products
        WHERE product_id=?
        """,
        (product_id,)
    )

    product = cursor.fetchone()

    cursor.close()
    conn.close()

    if not product:

        return {
            "error": "Product not found"
        }, 404

    pid = str(product_id)

    if pid in cart:

        cart[pid]['quantity'] += 1

    else:

        cart[pid] = {
            'name': product['name'],
            'price': float(product['price']),
            'image': product['image'],
            'quantity': 1
        }

    session['cart'] = cart

    # Save permanently
    save_user_cart(
        session['user_id'],
        cart
    )

    return {
        "message": "Item added to cart!",
        "cart_count": len(cart)
    }


# =========================================================
# AJAX INCREASE QUANTITY
# =========================================================

@app.route(
    '/user/cart/increase-ajax/<pid>'
)
def increase_quantity_ajax(pid):

    if 'user_id' not in session:

        return {
            "error": "not_logged_in"
        }, 401

    cart = session.get('cart', {})

    if pid not in cart:

        return {
            "error": "Product not found in cart"
        }, 404

    cart[pid]['quantity'] += 1

    session['cart'] = cart

    save_user_cart(
        session['user_id'],
        cart
    )

    item = cart[pid]

    item_total = (
        float(item['price']) *
        int(item['quantity'])
    )

    return {
        "success": True,
        "quantity": item['quantity'],
        "item_total": item_total
    }


# =========================================================
# AJAX DECREASE QUANTITY
# =========================================================

@app.route(
    '/user/cart/decrease-ajax/<pid>'
)
def decrease_quantity_ajax(pid):

    if 'user_id' not in session:

        return {
            "error": "not_logged_in"
        }, 401

    cart = session.get('cart', {})

    if pid not in cart:

        return {
            "error": "Product not found in cart"
        }, 404

    cart[pid]['quantity'] -= 1

    if cart[pid]['quantity'] <= 0:

        cart.pop(pid)

        session['cart'] = cart

        save_user_cart(
            session['user_id'],
            cart
        )

        return {
            "success": True,
            "removed": True
        }

    session['cart'] = cart

    save_user_cart(
        session['user_id'],
        cart
    )

    item = cart[pid]

    item_total = (
        float(item['price']) *
        int(item['quantity'])
    )

    return {
        "success": True,
        "quantity": item['quantity'],
        "item_total": item_total
    }


# =========================================================
# USER BUY NOW
# =========================================================

@app.route(
    '/user/buy-now/<int:product_id>'
)
def buy_now(product_id):

    if 'user_id' not in session:

        flash(
            "Please login first!",
            "danger"
        )

        return redirect('/user-login')

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *
        FROM products
        WHERE product_id=?
        """,
        (product_id,)
    )

    product = cursor.fetchone()

    cursor.close()
    conn.close()

    if not product:

        flash(
            "Product not found!",
            "danger"
        )

        return redirect('/user/products')

    # Buy Now = only this product
    session['selected_products'] = [
        str(product_id)
    ]

    session['selected_total'] = float(
        product['price']
    )

    session['purchase_mode'] = 'buy_now'

    return redirect('/user/address')


# =========================================================
# USER ADDRESS PAGE
# ONE ROUTE ONLY - GET + POST
# =========================================================

@app.route(
    '/user/address',
    methods=['GET', 'POST']
)
def user_address():

    if 'user_id' not in session:

        flash(
            "Please login first!",
            "danger"
        )

        return redirect('/user-login')


    # -----------------------------------------------------
    # COMING FROM CART
    # -----------------------------------------------------

    if request.method == 'POST':

        selected_products = (
            request.form.getlist(
                'selected_products'
            )
        )

        if not selected_products:

            flash(
                "Please select at least one product.",
                "danger"
            )

            return redirect('/user/cart')

        session['selected_products'] = (
            selected_products
        )

        session['purchase_mode'] = 'cart'

        cart = session.get(
            'cart',
            {}
        )

        selected_items = []

        selected_total = 0

        for pid in selected_products:

            if pid in cart:

                item = cart[pid]

                item_total = (
                    float(item['price']) *
                    int(item['quantity'])
                )

                selected_items.append({
                    'product_id': pid,
                    'name': item['name'],
                    'price': item['price'],
                    'image': item['image'],
                    'quantity': item['quantity'],
                    'total': item_total
                })

                selected_total += (
                    item_total
                )

        session['selected_total'] = (
            selected_total
        )

        return render_template(
            "user/address.html",
            selected_items=selected_items,
            selected_total=selected_total
        )


    # -----------------------------------------------------
    # COMING FROM BUY NOW
    # -----------------------------------------------------

    selected_products = session.get(
        'selected_products',
        []
    )

    if not selected_products:

        flash(
            "Please select a product first.",
            "danger"
        )

        return redirect('/user/products')

    selected_total = session.get(
        'selected_total',
        0
    )

    return render_template(
        "user/address.html",
        selected_total=selected_total
    )


# =========================================================
# SAVE ADDRESS TO DATABASE + CONTINUE TO PAYMENT
# =========================================================

@app.route(
    '/user/address/continue',
    methods=['POST']
)
def address_continue():

    if 'user_id' not in session:

        flash(
            "Please login first!",
            "danger"
        )

        return redirect('/user-login')


    # Get address form data
    full_name = request.form[
        'full_name'
    ]

    mobile = request.form[
        'mobile'
    ]

    house_number = request.form[
        'house_number'
    ]

    area = request.form[
        'area'
    ]

    landmark = request.form.get(
        'landmark',
        ''
    )

    city = request.form[
        'city'
    ]

    state = request.form[
        'state'
    ]

    pincode = request.form[
        'pincode'
    ]


    # -----------------------------------------------------
    # SAVE ADDRESS IN DATABASE
    # -----------------------------------------------------

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO user_addresses
        (
            user_id,
            full_name,
            mobile,
            house_number,
            area,
            landmark,
            city,
            state,
            pincode
        )
        VALUES
        (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        session['user_id'],
        full_name,
        mobile,
        house_number,
        area,
        landmark,
        city,
        state,
        pincode
    ))

    conn.commit()

    address_id = cursor.lastrowid

    cursor.close()
    conn.close()


    # Save address ID for future order
    session['address_id'] = (
        address_id
    )


    # Keep address temporarily for Razorpay
    session['delivery_address'] = {

        'full_name':
            full_name,

        'mobile':
            mobile,

        'house_number':
            house_number,

        'area':
            area,

        'landmark':
            landmark,

        'city':
            city,

        'state':
            state,

        'pincode':
            pincode
    }


    return redirect('/user/payment')


# =========================================================
# RAZORPAY PAYMENT PAGE
# =========================================================

@app.route('/user/payment')
def user_payment():

    if 'user_id' not in session:

        flash(
            "Please login first!",
            "danger"
        )

        return redirect('/user-login')


    selected_total = session.get(
        'selected_total'
    )


    if not selected_total:

        flash(
            "No products selected.",
            "danger"
        )

        return redirect('/user/products')


    address = session.get(
        'delivery_address'
    )


    if not address:

        flash(
            "Please enter delivery address.",
            "danger"
        )

        return redirect('/user/address')


    # Razorpay requires amount in paise
    amount_in_paise = int(
        round(
            float(selected_total) * 100
        )
    )


    order_data = {

        "amount":
            amount_in_paise,

        "currency":
            "INR",

        "receipt":
            "smartcart_" +
            str(session['user_id'])
    }


    razorpay_order = (
        razorpay_client.order.create(
            data=order_data
        )
    )


    session['razorpay_order_id'] = (
        razorpay_order['id']
    )


    return render_template(

        "user/payment.html",

        razorpay_key_id=
            config.RAZORPAY_KEY_ID,

        razorpay_order_id=
            razorpay_order['id'],

        amount=
            amount_in_paise,

        total=
            selected_total,

        user_name=
            address['full_name'],

        user_email=
            session.get(
                'user_email',
                ''
            ),

        user_mobile=
            address['mobile']
    )


# =========================================================
# VERIFY RAZORPAY PAYMENT
# =========================================================
# =========================================================
# VERIFY PAYMENT + CREATE ORDER
# =========================================================

@app.route(
    '/user/payment-success',
    methods=['POST']
)
def payment_success():

    # -----------------------------------------------------
    # CHECK LOGIN
    # -----------------------------------------------------

    if 'user_id' not in session:

        return {
            "success": False,
            "error": "not_logged_in"
        }, 401


    # -----------------------------------------------------
    # GET PAYMENT DATA FROM RAZORPAY
    # -----------------------------------------------------

    data = request.get_json()

    razorpay_payment_id = data.get(
        'razorpay_payment_id'
    )

    razorpay_order_id = data.get(
        'razorpay_order_id'
    )

    razorpay_signature = data.get(
        'razorpay_signature'
    )


    # -----------------------------------------------------
    # CHECK REQUIRED DATA
    # -----------------------------------------------------

    if not razorpay_payment_id:
        return {
            "success": False,
            "error": "Missing payment ID"
        }, 400


    if not razorpay_order_id:
        return {
            "success": False,
            "error": "Missing order ID"
        }, 400


    if not razorpay_signature:
        return {
            "success": False,
            "error": "Missing signature"
        }, 400


    # -----------------------------------------------------
    # GET SERVER-SIDE RAZORPAY ORDER ID
    # -----------------------------------------------------

    server_order_id = session.get(
        'razorpay_order_id'
    )


    if not server_order_id:

        return {
            "success": False,
            "error": "Payment session expired"
        }, 400


    # -----------------------------------------------------
    # MAKE SURE ORDER ID MATCHES
    # -----------------------------------------------------

    if razorpay_order_id != server_order_id:

        return {
            "success": False,
            "error": "Invalid order"
        }, 400


    # -----------------------------------------------------
    # VERIFY RAZORPAY SIGNATURE
    # -----------------------------------------------------

    try:

        razorpay_client.utility.verify_payment_signature({

            'razorpay_order_id':
                server_order_id,

            'razorpay_payment_id':
                razorpay_payment_id,

            'razorpay_signature':
                razorpay_signature
        })

    except Exception as e:

        app.logger.error(
            "Razorpay verification failed: %s",
            str(e)
        )

        return {
            "success": False,
            "error": "Payment verification failed"
        }, 400


    # =====================================================
    # PAYMENT VERIFIED
    # =====================================================

    user_id = session['user_id']
    address_id = session.get('address_id')

    cart = session.get(
        'cart',
    
        {}
    )

    selected_products = session.get(
        'selected_products',
        []
    )

    purchase_mode = session.get(
        'purchase_mode'
    )


    # -----------------------------------------------------
    # CHECK CART
    # -----------------------------------------------------

    if not cart:
        return {
            "success": False,
            "error": "Cart is empty"
        }, 400
    if not address_id:
        return {
            "success": False,
            "error": "Delivery address not found"
        }, 400
    


    # -----------------------------------------------------
    # DETERMINE WHICH PRODUCTS WERE PURCHASED
    # -----------------------------------------------------

    if purchase_mode == 'buy_now':

        selected_products = [
            str(selected_products[0])
        ]

    elif purchase_mode == 'cart':

        selected_products = [
            str(pid)
            for pid in selected_products
        ]

    else:

        return {
            "success": False,
            "error": "Invalid purchase mode"
        }, 400


    # -----------------------------------------------------
    # BUILD ORDER ITEMS
    # -----------------------------------------------------

    order_items = []

    total_amount = 0


    for pid in selected_products:

        if pid not in cart:
            continue

        item = cart[pid]

        quantity = int(
            item['quantity']
        )

        price = float(
            item['price']
        )

        item_total = price * quantity

        total_amount += item_total

        order_items.append({

            'product_id':
                int(pid),

            'product_name':
                item['name'],

            'quantity':
                quantity,

            'price':
                price
        })


    # -----------------------------------------------------
    # CHECK SELECTED PRODUCTS
    # -----------------------------------------------------

    if not order_items:

        return {
            "success": False,
            "error": "No products selected"
        }, 400


    # =====================================================
    # SAVE ORDER TO MYSQL
    # =====================================================

    conn = get_db_connection()

    cursor = conn.cursor()


    try:

        # -------------------------------------------------
        # INSERT INTO ORDERS
        # -------------------------------------------------

        cursor.execute(
            """
            INSERT INTO orders
            (
                user_id,
                address_id,
                razorpay_order_id,
                razorpay_payment_id,
                amount,
                payment_status
            )
            VALUES
            (
                ?,
                ?,
                ?,
                ?,
                ?,
                ?
            )
            """,

            (
                user_id,
                address_id,
                razorpay_order_id,
                razorpay_payment_id,
                total_amount,
                'paid'
            )
        )


        # Get newly created order ID

        order_db_id = cursor.lastrowid


        # -------------------------------------------------
        # INSERT ORDER ITEMS
        # -------------------------------------------------

        for item in order_items:

            cursor.execute(
                """
                INSERT INTO order_items
                (
                    order_id,
                    product_id,
                    product_name,
                    quantity,
                    price
                )
                VALUES
                (
                    ?,
                    ?,
                    ?,
                    ?,
                    ?
                )
                """,

                (
                    order_db_id,
                    item['product_id'],
                    item['product_name'],
                    item['quantity'],
                    item['price']
                )
            )


        # -------------------------------------------------
        # COMMIT
        # -------------------------------------------------

        conn.commit()


        # =================================================
        # REMOVE PURCHASED PRODUCTS FROM CART
        # =================================================

        for pid in selected_products:

            cart.pop(
                pid,
                None
            )


        # Update session cart

        session['cart'] = cart


        # Save updated cart to MySQL

        save_user_cart(
            user_id,
            cart
        )


        # -------------------------------------------------
        # CLEAR PAYMENT SESSION DATA
        # -------------------------------------------------

        session.pop(
            'selected_products',
            None
        )

        session.pop(
            'selected_total',
            None
        )

        session.pop(
            'delivery_address',
            None
        )

        session.pop(
            'address_id',
            None
        )

        session.pop(
            'purchase_mode',
            None
        )

        session.pop(
            'razorpay_order_id',
            None
        )

        session.pop(
            'payment_id',
            None
        )

        session.pop(
            'payment_verified',
            None
        )


        # -------------------------------------------------
        # SUCCESS
        # -------------------------------------------------

        return {

            "success": True,

            "order_id":
                order_db_id

        }


    except Exception as e:

        # -------------------------------------------------
        # ROLLBACK
        # -------------------------------------------------

        conn.rollback()

        app.logger.error(
            "Order creation failed: %s",
            str(e)
        )

        return {

            "success": False,

            "error":
                "Order could not be saved"

        }, 500


    finally:

        cursor.close()

        conn.close()

# =========================================================
# PAYMENT SUCCESS PAGE
# =========================================================

@app.route(
    '/user/payment-success-page'
)
def payment_success_page():

    if 'user_id' not in session:

        return redirect(
            '/user-login'
        )


    if not session.get(
        'payment_verified'
    ):

        return redirect(
            '/user/products'
        )


    return render_template(
        "user/payment_success.html",
        payment_id=session.get(
            'payment_id'
        )
    )

# =========================================================
# ORDER SUCCESS PAGE
# =========================================================

@app.route(
    '/user/order-success/<int:order_db_id>'
)
def order_success(order_db_id):

    # -----------------------------------------------------
    # CHECK LOGIN
    # -----------------------------------------------------

    if 'user_id' not in session:

        flash(
            "Please login!",
            "danger"
        )

        return redirect(
            '/user-login'
        )


    user_id = session['user_id']


    # -----------------------------------------------------
    # DATABASE CONNECTION
    # -----------------------------------------------------

    conn = get_db_connection()

    cursor = conn.cursor()


    # -----------------------------------------------------
    # GET ORDER
    # -----------------------------------------------------

    cursor.execute(
        """
        SELECT *
        FROM orders
        WHERE order_id=?
        AND user_id=?
        """,

        (
            order_db_id,
            user_id
        )
    )


    order = cursor.fetchone()


    # -----------------------------------------------------
    # ORDER DOES NOT EXIST
    # -----------------------------------------------------

    if not order:

        cursor.close()

        conn.close()

        flash(
            "Order not found.",
            "danger"
        )

        return redirect(
            '/user/products'
        )


    # -----------------------------------------------------
    # GET ORDER ITEMS
    # -----------------------------------------------------

    cursor.execute(
        """
        SELECT *
        FROM order_items
        WHERE order_id=?
        """,

        (
            order_db_id,
        )
    )


    items = cursor.fetchall()


    cursor.close()

    conn.close()


    # -----------------------------------------------------
    # SHOW PAGE
    # -----------------------------------------------------

    return render_template(
        "user/order_success.html",

        order=order,

        items=items
    )

# =========================================================
# MY ORDERS
# =========================================================

@app.route('/user/my-orders')
def my_orders():

    # -----------------------------------------------------
    # CHECK LOGIN
    # -----------------------------------------------------

    if 'user_id' not in session:

        flash(
            "Please login!",
            "danger"
        )

        return redirect(
            '/user-login'
        )


    user_id = session['user_id']


    # -----------------------------------------------------
    # DATABASE
    # -----------------------------------------------------

    conn = get_db_connection()

    cursor = conn.cursor()


    # -----------------------------------------------------
    # GET USER ORDERS
    # -----------------------------------------------------

    cursor.execute(
        """
        SELECT *
        FROM orders
        WHERE user_id=?
        ORDER BY created_at DESC
        """,

        (
            user_id,
        )
    )


    orders = cursor.fetchall()


    cursor.close()

    conn.close()


    # -----------------------------------------------------
    # SHOW PAGE
    # -----------------------------------------------------

    return render_template(
        "user/my_orders.html",
        orders=orders
    )

# =========================================================
# DOWNLOAD ORDER INVOICE
# =========================================================

@app.route('/user/download-invoice/<int:order_id>')
def download_invoice(order_id):

    # -----------------------------------------------------
    # CHECK LOGIN
    # -----------------------------------------------------

    if 'user_id' not in session:

        flash(
            "Please login!",
            "danger"
        )

        return redirect('/user-login')


    user_id = session['user_id']


    # -----------------------------------------------------
    # DATABASE CONNECTION
    # -----------------------------------------------------

    conn = get_db_connection()

    cursor = conn.cursor()


    # -----------------------------------------------------
    # GET ORDER
    # -----------------------------------------------------

    cursor.execute(
    """
    SELECT
        o.*,
        a.full_name,
        a.mobile,
        a.house_number,
        a.area,
        a.landmark,
        a.city,
        a.state,
        a.pincode
    FROM orders o
    JOIN user_addresses a
        ON o.address_id = a.address_id
    WHERE o.order_id=?
    AND o.user_id=?
    """,
    (
        order_id,
        user_id
    )
    )

    order = cursor.fetchone()


    # -----------------------------------------------------
    # CHECK ORDER
    # -----------------------------------------------------

    if not order:

        cursor.close()
        conn.close()

        flash(
            "Order not found.",
            "danger"
        )

        return redirect('/user/my-orders')


    # -----------------------------------------------------
    # GET ORDER ITEMS
    # -----------------------------------------------------

    cursor.execute(
        """
        SELECT *
        FROM order_items
        WHERE order_id=?
        """,
        (
            order_id,
        )
    )

    items = cursor.fetchall()


    cursor.close()
    conn.close()


    # -----------------------------------------------------
    # CREATE HTML INVOICE
    # -----------------------------------------------------

    html = render_template(
        "user/invoice.html",
        order=order,
        items=items
    )


    # -----------------------------------------------------
    # CONVERT HTML TO PDF
    # -----------------------------------------------------

    pdf = generate_pdf(html)


    if not pdf:

        flash(
            "Error generating invoice PDF.",
            "danger"
        )

        return redirect('/user/my-orders')


    # -----------------------------------------------------
    # CREATE FLASK RESPONSE
    # -----------------------------------------------------

    response = make_response(
        pdf.getvalue()
    )


    # -----------------------------------------------------
    # PDF CONTENT TYPE
    # -----------------------------------------------------

    response.headers[
        'Content-Type'
    ] = 'application/pdf'


    # -----------------------------------------------------
    # FORCE DOWNLOAD
    # -----------------------------------------------------

    response.headers[
        'Content-Disposition'
    ] = (
        f'attachment; '
        f'filename=invoice_{order_id}.pdf'
    )


    return response

# =========================================================
# USER LOGOUT
# =========================================================

@app.route('/user-logout')
def user_logout():

    if 'user_id' not in session:

        flash(
            "Please login first!",
            "danger"
        )

        return redirect('/user-login')


    # -----------------------------------------------------
    # Cart is already saved in MySQL.
    # Therefore browser session cart can be cleared safely.
    # -----------------------------------------------------

    session.pop('user_id', None)
    session.pop('user_name', None)
    session.pop('user_email', None)

    session.pop('cart', None)

    session.pop(
        'selected_products',
        None
    )

    session.pop(
        'selected_total',
        None
    )

    session.pop(
        'delivery_address',
        None
    )

    session.pop(
        'address_id',
        None
    )

    session.pop(
        'purchase_mode',
        None
    )

    session.pop(
        'razorpay_order_id',
        None
    )

    session.pop(
        'payment_id',
        None
    )

    session.pop(
        'payment_verified',
        None
    )


    return render_template(
        "user/user_logout.html"
    )


if __name__ == '__main__':
    app.run(debug=True)