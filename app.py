from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import sqlite3
import os

# ... (نفس الـ imports اللي عندك)

app = Flask(__name__)
app.secret_key = 'farhtak_super_secret_key'
DB_NAME = 'farhtak.db'

# === تعديل هنا: خلي الدالة تتنفذ بمجرد تشغيل الملف ===
def init_db():
    # بنستخدم absolute path عشان نضمن إن الملف يتكريت في نفس مكان الكود
    db_path = os.path.join(os.path.dirname(__file__), DB_NAME)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # جدول المستخدمين
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name TEXT,
            last_name TEXT,
            phone TEXT,
            email TEXT UNIQUE,
            password TEXT,
            role TEXT
        )
    ''')
    
    # جدول القاعات
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS halls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER,
            name TEXT,
            location TEXT,
            capacity INTEGER,
            price REAL,
            FOREIGN KEY(owner_id) REFERENCES users(id)
        )
    ''')
    
    # جدول الحجوزات
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            hall_name TEXT,
            booking_date TEXT,
            guests INTEGER,
            total_price REAL,
            status TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')
    conn.commit()
    conn.close()

# نداء مباشر للدالة هنا عشان تتنفذ سواء شغلت بـ python app.py أو بـ waitress
init_db() 

# تعديل بسيط في دالة get_db عشان تلاقي المسار صح دايماً
def get_db():
    db_path = os.path.join(os.path.dirname(__file__), DB_NAME)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn



# ==========================================
# 2. مسارات الصفحات (Routing)
# ==========================================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/search.html')
def search():
    return render_template('search.html')

@app.route('/booking.html')
def booking():
    return render_template('booking.html')

@app.route('/dashboard.html')
def dashboard():
    # التأكد إن المستخدم مسجل دخول وصاحب قاعة
    if 'user_id' not in session or session.get('role') != 'owner':
        return redirect(url_for('login'))
    
    db = get_db()
    # جلب حجوزات صاحب القاعة
    bookings = db.execute('''
        SELECT b.*, u.first_name, u.last_name, u.phone 
        FROM bookings b
        JOIN users u ON b.user_id = u.id
    ''').fetchall()
    return render_template('dashboard.html', bookings=bookings)

# ==========================================
# 3. معالجة البيانات (الربط مع الـ Forms)
# ==========================================
@app.route('/login.html', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE email = ? AND password = ?', (email, password)).fetchone()
        
        if user:
            # تخزين بيانات المستخدم في الجلسة
            session.permanent = True # عشان الجلسة ما تروحش أول ما تقفل المتصفح
            session['user_id'] = user['id']
            session['role'] = user['role']
            session['name'] = user['first_name']
            
            if user['role'] == 'owner':
                return redirect(url_for('dashboard'))
            else:
                return redirect('/') # يرجع للصفحة الرئيسية بعد الدخول
        else:
            return "خطأ في البيانات، حاول مرة أخرى", 401
            
    return render_template('login.html')

@app.route('/register', methods=['POST'])
def register():
    first_name = request.form.get('first_name')
    last_name = request.form.get('last_name')
    phone = request.form.get('phone')
    email = request.form.get('email')
    password = request.form.get('password')
    role = request.form.get('role', 'customer') # customer or owner
    
    db = get_db()
    try:
        db.execute('INSERT INTO users (first_name, last_name, phone, email, password, role) VALUES (?, ?, ?, ?, ?, ?)',
                   (first_name, last_name, phone, email, password, role))
        db.commit()
        return redirect(url_for('login'))
    except sqlite3.IntegrityError:
        return "البريد الإلكتروني مسجل بالفعل", 400

@app.route('/api/book', methods=['POST'])
def api_book():
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "يجب تسجيل الدخول أولاً"}), 401
        
    data = request.json
    db = get_db()
    db.execute('INSERT INTO bookings (user_id, hall_name, booking_date, guests, total_price, status) VALUES (?, ?, ?, ?, ?, ?)',
               (session['user_id'], data.get('hall_name'), data.get('date'), data.get('guests'), data.get('price'), 'pending'))
    db.commit()
    
    return jsonify({"success": True, "message": "تم الحجز بنجاح!"})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

if __name__ == '__main__':
    init_db() # إنشاء الجداول عند التشغيل لأول مرة
    from waitress import serve
    serve(app, host="0.0.0.0", port=5000)

    #test