import os
import sqlite3
from flask import Flask, jsonify, redirect, render_template, request, session, url_for

DB_NAME = "farhtak.db"


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY="farhtak_super_secret_key",
        DB_PATH=os.path.join(os.path.dirname(__file__), DB_NAME),
    )
    if test_config:
        app.config.update(test_config)

    def get_db():
        conn = sqlite3.connect(app.config["DB_PATH"])
        conn.row_factory = sqlite3.Row
        return conn

    def init_db():
        conn = get_db()
        cursor = conn.cursor()

        # جدول المستخدمين: عميل أو صاحب قاعة.
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('customer', 'owner'))
            )
            """
        )

        # جدول القاعات المضافة من أصحاب القاعات.
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS halls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                location TEXT NOT NULL,
                capacity INTEGER NOT NULL,
                price REAL NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY(owner_id) REFERENCES users(id)
            )
            """
        )

        # توافق مع قواعد البيانات القديمة التي أنشأت halls بدون is_active.
        hall_columns = {
            col["name"] for col in cursor.execute("PRAGMA table_info(halls)").fetchall()
        }
        if "is_active" not in hall_columns:
            cursor.execute("ALTER TABLE halls ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")

        # جدول الحجوزات يربط العميل بالقاعة والتاريخ.
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                hall_id INTEGER NOT NULL,
                booking_date TEXT NOT NULL,
                guests INTEGER NOT NULL,
                total_price REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'confirmed', 'cancelled')),
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(hall_id) REFERENCES halls(id)
            )
            """
        )

        # ترحيل بسيط للتوافق مع قواعد البيانات القديمة:
        # بعض النسخ القديمة كانت تحتوي hall_name بدل hall_id.
        booking_columns = {
            col["name"] for col in cursor.execute("PRAGMA table_info(bookings)").fetchall()
        }
        if "hall_id" not in booking_columns:
            cursor.execute("ALTER TABLE bookings ADD COLUMN hall_id INTEGER")
            # محاولة ربط الحجوزات القديمة بالقاعة حسب الاسم إن كان متاحًا.
            if "hall_name" in booking_columns:
                cursor.execute(
                    """
                    UPDATE bookings
                    SET hall_id = (
                        SELECT h.id
                        FROM halls h
                        WHERE h.name = bookings.hall_name
                        LIMIT 1
                    )
                    WHERE hall_id IS NULL
                    """
                )
        conn.commit()
        conn.close()

    def row_to_dict(row):
        return dict(row) if row else None

    def require_login():
        return "user_id" in session

    def require_owner():
        return require_login() and session.get("role") == "owner"

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/search.html")
    def search_page():
        return render_template("search.html")

    @app.route("/booking.html")
    def booking_page():
        return render_template("booking.html")

    @app.route("/dashboard.html")
    def dashboard():
        if not require_owner():
            return redirect(url_for("login"))

        db = get_db()
        bookings = db.execute(
            """
            SELECT b.id, b.booking_date, b.guests, b.total_price, b.status,
                   u.first_name, u.last_name, u.phone, h.name AS hall_name
            FROM bookings b
            JOIN users u ON b.user_id = u.id
            JOIN halls h ON b.hall_id = h.id
            WHERE h.owner_id = ?
            ORDER BY b.id DESC
            """,
            (session["user_id"],),
        ).fetchall()
        db.close()
        return render_template("dashboard.html", bookings=bookings)

    @app.route("/login.html", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            email = request.form.get("email", "").strip()
            password = request.form.get("password", "")

            db = get_db()
            user = db.execute(
                "SELECT * FROM users WHERE email = ? AND password = ?",
                (email, password),
            ).fetchone()
            db.close()

            if not user:
                return "خطأ في البيانات، حاول مرة أخرى", 401

            # حفظ بيانات الجلسة لاستخدامها في صلاحيات الـ API.
            session.permanent = True
            session["user_id"] = user["id"]
            session["role"] = user["role"]
            session["name"] = user["first_name"]
            return redirect(url_for("dashboard" if user["role"] == "owner" else "index"))

        return render_template("login.html")

    @app.route("/register", methods=["POST"])
    def register():
        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "customer").strip()

        if not all([first_name, last_name, phone, email, password]):
            return "كل الحقول مطلوبة", 400

        if role not in ("customer", "owner"):
            return "نوع المستخدم غير صحيح", 400

        db = get_db()
        try:
            db.execute(
                """
                INSERT INTO users (first_name, last_name, phone, email, password, role)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (first_name, last_name, phone, email, password, role),
            )
            db.commit()
        except sqlite3.IntegrityError:
            db.close()
            return "البريد الإلكتروني مسجل بالفعل", 400
        db.close()
        return redirect(url_for("login"))

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("index"))

    @app.route("/api/me", methods=["GET"])
    def current_user():
        if not require_login():
            return jsonify({"success": False, "message": "غير مسجل دخول"}), 401
        return jsonify(
            {
                "success": True,
                "data": {
                    "id": session.get("user_id"),
                    "name": session.get("name"),
                    "role": session.get("role"),
                },
            }
        )

    @app.route("/api/halls", methods=["GET"])
    def list_halls():
        location = request.args.get("location", "").strip()
        min_capacity = request.args.get("min_capacity", type=int)
        max_price = request.args.get("max_price", type=float)

        query = """
            SELECT h.*, u.first_name || ' ' || u.last_name AS owner_name
            FROM halls h
            JOIN users u ON h.owner_id = u.id
            WHERE h.is_active = 1
        """
        params = []

        if location:
            query += " AND h.location LIKE ?"
            params.append(f"%{location}%")
        if min_capacity is not None:
            query += " AND h.capacity >= ?"
            params.append(min_capacity)
        if max_price is not None:
            query += " AND h.price <= ?"
            params.append(max_price)
        query += " ORDER BY h.id DESC"

        db = get_db()
        halls = [dict(row) for row in db.execute(query, tuple(params)).fetchall()]
        db.close()
        return jsonify({"success": True, "data": halls})

    @app.route("/api/halls/<int:hall_id>", methods=["GET"])
    def get_hall(hall_id):
        db = get_db()
        hall = db.execute(
            """
            SELECT h.*, u.first_name || ' ' || u.last_name AS owner_name
            FROM halls h
            JOIN users u ON h.owner_id = u.id
            WHERE h.id = ? AND h.is_active = 1
            """,
            (hall_id,),
        ).fetchone()
        db.close()
        if not hall:
            return jsonify({"success": False, "message": "القاعة غير موجودة"}), 404
        return jsonify({"success": True, "data": dict(hall)})

    @app.route("/api/halls", methods=["POST"])
    def create_hall():
        if not require_owner():
            return jsonify({"success": False, "message": "صلاحية غير كافية"}), 403

        data = request.get_json(silent=True) or {}
        name = (data.get("name") or "").strip()
        location = (data.get("location") or "").strip()
        capacity = data.get("capacity")
        price = data.get("price")

        if not all([name, location]) or capacity is None or price is None:
            return jsonify({"success": False, "message": "بيانات القاعة غير مكتملة"}), 400

        db = get_db()
        cursor = db.execute(
            """
            INSERT INTO halls (owner_id, name, location, capacity, price)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session["user_id"], name, location, int(capacity), float(price)),
        )
        db.commit()
        hall_id = cursor.lastrowid
        hall = db.execute("SELECT * FROM halls WHERE id = ?", (hall_id,)).fetchone()
        db.close()
        return jsonify({"success": True, "data": row_to_dict(hall)}), 201

    @app.route("/api/book", methods=["POST"])
    def create_booking():
        if not require_login():
            return jsonify({"success": False, "message": "يجب تسجيل الدخول أولاً"}), 401

        data = request.get_json(silent=True) or {}
        hall_id = data.get("hall_id")
        booking_date = (data.get("date") or "").strip()
        guests = data.get("guests")

        if hall_id is None:
            # دعم التوافق مع الواجهة الحالية التي ترسل hall_name بدل hall_id.
            hall_name = (data.get("hall_name") or "").strip()
            if hall_name:
                db = get_db()
                hall_row = db.execute(
                    "SELECT id FROM halls WHERE name = ? AND is_active = 1",
                    (hall_name,),
                ).fetchone()
                db.close()
                hall_id = hall_row["id"] if hall_row else None

        if not all([hall_id, booking_date, guests]):
            return jsonify({"success": False, "message": "بيانات الحجز غير مكتملة"}), 400

        db = get_db()
        hall = db.execute(
            "SELECT id, price FROM halls WHERE id = ? AND is_active = 1",
            (hall_id,),
        ).fetchone()
        if not hall:
            db.close()
            return jsonify({"success": False, "message": "القاعة غير موجودة"}), 404

        total_price = float(data.get("price") or hall["price"])
        cursor = db.execute(
            """
            INSERT INTO bookings (user_id, hall_id, booking_date, guests, total_price, status)
            VALUES (?, ?, ?, ?, ?, 'pending')
            """,
            (session["user_id"], hall["id"], booking_date, int(guests), total_price),
        )
        db.commit()
        db.close()
        return jsonify(
            {"success": True, "message": "تم الحجز بنجاح!", "booking_id": cursor.lastrowid}
        )

    @app.route("/api/owner/bookings", methods=["GET"])
    def owner_bookings():
        if not require_owner():
            return jsonify({"success": False, "message": "صلاحية غير كافية"}), 403

        status = request.args.get("status", "").strip()
        query = """
            SELECT b.id, b.booking_date, b.guests, b.total_price, b.status,
                   h.name AS hall_name,
                   u.first_name || ' ' || u.last_name AS customer_name
            FROM bookings b
            JOIN halls h ON b.hall_id = h.id
            JOIN users u ON b.user_id = u.id
            WHERE h.owner_id = ?
        """
        params = [session["user_id"]]
        if status in ("pending", "confirmed", "cancelled"):
            query += " AND b.status = ?"
            params.append(status)
        query += " ORDER BY b.id DESC"

        db = get_db()
        rows = [dict(row) for row in db.execute(query, tuple(params)).fetchall()]
        db.close()
        return jsonify({"success": True, "data": rows})

    @app.route("/api/owner/halls", methods=["GET"])
    def owner_halls():
        if not require_owner():
            return jsonify({"success": False, "message": "صلاحية غير كافية"}), 403

        db = get_db()
        rows = db.execute(
            """
            SELECT id, name, location, capacity, price, is_active
            FROM halls
            WHERE owner_id = ?
            ORDER BY id DESC
            """,
            (session["user_id"],),
        ).fetchall()
        db.close()
        return jsonify({"success": True, "data": [dict(row) for row in rows]})

    @app.route("/api/owner/halls/<int:hall_id>", methods=["PATCH"])
    def update_owner_hall(hall_id):
        if not require_owner():
            return jsonify({"success": False, "message": "صلاحية غير كافية"}), 403

        data = request.get_json(silent=True) or {}
        name = (data.get("name") or "").strip()
        location = (data.get("location") or "").strip()
        capacity = data.get("capacity")
        price = data.get("price")
        is_active = data.get("is_active")

        db = get_db()
        existing = db.execute(
            "SELECT id FROM halls WHERE id = ? AND owner_id = ?",
            (hall_id, session["user_id"]),
        ).fetchone()
        if not existing:
            db.close()
            return jsonify({"success": False, "message": "القاعة غير موجودة"}), 404

        updates = []
        params = []
        if name:
            updates.append("name = ?")
            params.append(name)
        if location:
            updates.append("location = ?")
            params.append(location)
        if capacity is not None:
            updates.append("capacity = ?")
            params.append(int(capacity))
        if price is not None:
            updates.append("price = ?")
            params.append(float(price))
        if is_active is not None:
            updates.append("is_active = ?")
            params.append(1 if is_active else 0)

        if not updates:
            db.close()
            return jsonify({"success": False, "message": "لا توجد بيانات للتحديث"}), 400

        params.append(hall_id)
        db.execute(f"UPDATE halls SET {', '.join(updates)} WHERE id = ?", tuple(params))
        db.commit()
        hall = db.execute(
            "SELECT id, name, location, capacity, price, is_active FROM halls WHERE id = ?",
            (hall_id,),
        ).fetchone()
        db.close()
        return jsonify({"success": True, "data": dict(hall), "message": "تم تحديث القاعة"})

    @app.route("/api/owner/bookings/<int:booking_id>/status", methods=["PATCH"])
    def update_booking_status(booking_id):
        if not require_owner():
            return jsonify({"success": False, "message": "صلاحية غير كافية"}), 403

        data = request.get_json(silent=True) or {}
        new_status = (data.get("status") or "").strip()
        if new_status not in ("pending", "confirmed", "cancelled"):
            return jsonify({"success": False, "message": "الحالة غير صحيحة"}), 400

        db = get_db()
        booking = db.execute(
            """
            SELECT b.id
            FROM bookings b
            JOIN halls h ON b.hall_id = h.id
            WHERE b.id = ? AND h.owner_id = ?
            """,
            (booking_id, session["user_id"]),
        ).fetchone()
        if not booking:
            db.close()
            return jsonify({"success": False, "message": "الحجز غير موجود"}), 404

        db.execute("UPDATE bookings SET status = ? WHERE id = ?", (new_status, booking_id))
        db.commit()
        db.close()
        return jsonify({"success": True, "message": "تم تحديث حالة الحجز"})

    init_db()
    return app


app = create_app()

if __name__ == "__main__":
    from waitress import serve

    serve(app, host="0.0.0.0", port=5000)