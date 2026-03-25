from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import sqlite3
import os
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "secret123")
DB = "ideas.db"
UPLOAD_FOLDER = "static/uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            role TEXT DEFAULT 'user'
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS ideas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            description TEXT,
            photo TEXT,
            author_id INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            is_pinned INTEGER DEFAULT 0,
            FOREIGN KEY(author_id) REFERENCES users(id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            idea_id INTEGER,
            user_id INTEGER,
            content TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(idea_id) REFERENCES ideas(id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            idea_id INTEGER,
            user_id INTEGER,
            vote_type INTEGER,
            UNIQUE(idea_id, user_id),
            FOREIGN KEY(idea_id) REFERENCES ideas(id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            description TEXT,
            author_id INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute("PRAGMA table_info(ideas)")
    columns = [x[1] for x in c.fetchall()]
    if "is_pinned" not in columns:
        c.execute("ALTER TABLE ideas ADD COLUMN is_pinned INTEGER DEFAULT 0")
    c.execute("SELECT id FROM users WHERE username='host'")
    if not c.fetchone():
        c.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                  ("host", generate_password_hash("host123"), "admin"))
    conn.commit()
    conn.close()

init_db()

def query_db(query, args=(), one=False):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute(query, args)
    res = c.fetchall()
    conn.commit()
    conn.close()
    return (res[0] if res and one else res) if one else res

def get_ideas_with_scores(only_pinned_first=False):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    order = "is_pinned DESC, created_at DESC" if only_pinned_first else "created_at DESC"
    c.execute(f'''
        SELECT i.id, i.title, i.description, i.photo, u.username, i.author_id,
               IFNULL(SUM(v.vote_type),0) as score,
               COUNT(DISTINCT cm.id) as comments_count,
               i.created_at, i.is_pinned
        FROM ideas i
        LEFT JOIN users u ON i.author_id = u.id
        LEFT JOIN votes v ON v.idea_id = i.id
        LEFT JOIN comments cm ON cm.idea_id = i.id
        GROUP BY i.id
        ORDER BY {order}
    ''')
    res = c.fetchall()
    conn.close()
    return res

def get_announcements():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute('''
        SELECT a.id, a.title, a.description, u.username, a.author_id, a.created_at
        FROM announcements a
        LEFT JOIN users u ON a.author_id = u.id
        ORDER BY a.created_at DESC
    ''')
    ann = c.fetchall()
    conn.close()
    return ann

@app.route('/')
def root():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route('/register', methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "user")
        if not username or not password:
            flash("Please provide username and password", "warning")
            return redirect(url_for("register"))
        try:
            conn = sqlite3.connect(DB)
            c = conn.cursor()
            c.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                    (username, generate_password_hash(password), role))
            conn.commit()
            conn.close()
            flash("Account created — please login", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Username already exists", "danger")
            return redirect(url_for("register"))
    return render_template("register.html")

@app.route('/login', methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        selected_role = request.form.get("role", "user")
        conn = sqlite3.connect(DB)
        c = conn.cursor()
        c.execute("SELECT id, password, role FROM users WHERE username=?", (username,))
        row = c.fetchone()
        conn.close()
        if row and check_password_hash(row[1], password):
            actual_role = row[2]
            if selected_role == "admin" and actual_role != "admin":
                flash("Account is not a host/admin", "danger")
                return redirect(url_for("login"))
            session["user_id"] = row[0]
            session["username"] = username
            session["role"] = actual_role
            flash(f"Welcome, {username}!", "success")
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid credentials", "danger")
    return render_template("login.html")

@app.route('/logout')
def logout():
    session.clear()
    flash("Logged out", "info")
    return redirect(url_for("login"))

@app.route('/dashboard')
def dashboard():
    if "user_id" not in session:
        flash("Please login", "warning")
        return redirect(url_for("login"))
    ideas = get_ideas_with_scores(only_pinned_first=True)
    ann = get_announcements()
    trending = sorted(ideas, key=lambda r: r[6], reverse=True)[:6]
    return render_template("dashboard.html", ideas=ideas, trending=trending, announcements=ann)

@app.route("/trending")
def trending_view():
    if "user_id" not in session:
        flash("Please login", "warning")
        return redirect(url_for("login"))
    ideas = sorted(get_ideas_with_scores(), key=lambda r: r[6], reverse=True)
    return render_template("trending.html", ideas=ideas)

@app.route('/submit', methods=["GET", "POST"])
def submit():
    if "user_id" not in session:
        flash("Please login", "warning")
        return redirect(url_for("login"))
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        photo = request.files.get("photo")
        filename = None
        if photo and photo.filename:
            filename = secure_filename(photo.filename)
            photo.save(os.path.join(UPLOAD_FOLDER, filename))
        conn = sqlite3.connect(DB)
        c = conn.cursor()
        c.execute("INSERT INTO ideas (title, description, photo, author_id) VALUES (?, ?, ?, ?)",
                (title, description, filename, session["user_id"]))
        conn.commit()
        conn.close()
        flash("Idea/Suggestion submitted", "success")
        return redirect(url_for("dashboard"))
    return render_template("idea_submit.html")

@app.route("/idea/edit/<int:idea_id>", methods=["GET","POST"])
def idea_edit(idea_id):
    if "user_id" not in session:
        flash("Please login", "warning")
        return redirect(url_for("login"))
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT id, title, description, photo, author_id FROM ideas WHERE id=?", (idea_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        flash("Idea not found", "danger")
        return redirect(url_for("dashboard"))
    if session.get("role") != "admin" and session.get("user_id") != row[4]:
        conn.close()
        flash("Access denied", "danger")
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        title = request.form.get("title","").strip()
        description = request.form.get("description","").strip()
        photo = request.files.get("photo")
        filename = row[3]
        if photo and photo.filename:
            filename = secure_filename(photo.filename)
            photo.save(os.path.join(UPLOAD_FOLDER, filename))
        c.execute("UPDATE ideas SET title=?, description=?, photo=? WHERE id=?",
                  (title, description, filename, idea_id))
        conn.commit()
        conn.close()
        flash("Idea updated", "success")
        return redirect(url_for("idea_detail", idea_id=idea_id))
    conn.close()
    return render_template("idea_edit.html", idea=row)

@app.route("/admin/announcements")
def admin_announcements():
    if session.get("role") != "admin":
        flash("Access denied", "danger")
        return redirect(url_for("dashboard"))
    ann = get_announcements()
    return render_template("admin_announcements.html", announcements=ann)

@app.route("/announcement/submit", methods=["GET","POST"])
def announcement_submit():
    if session.get("role") != "admin":
        flash("Access denied", "danger")
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        title = request.form.get("title","").strip()
        description = request.form.get("description","").strip()
        conn = sqlite3.connect(DB)
        c = conn.cursor()
        c.execute("INSERT INTO announcements (title, description, author_id) VALUES (?, ?, ?)", 
                  (title, description, session["user_id"]))
        conn.commit()
        conn.close()
        flash("Announcement posted", "success")
        return redirect(url_for("admin_announcements"))
    return render_template("announcement_submit.html")

@app.route("/announcement/edit/<int:announcement_id>", methods=["GET","POST"])
def announcement_edit(announcement_id):
    if session.get("role") != "admin":
        flash("Access denied", "danger")
        return redirect(url_for("dashboard"))
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT id, title, description, author_id FROM announcements WHERE id=?", (announcement_id,))
    ann = c.fetchone()
    if not ann:
        conn.close()
        flash("Announcement not found", "danger")
        return redirect(url_for("admin_announcements"))
    if request.method == "POST":
        title = request.form.get("title","").strip()
        description = request.form.get("description","").strip()
        c.execute("UPDATE announcements SET title=?, description=? WHERE id=?",
                    (title, description, announcement_id))
        conn.commit()
        conn.close()
        flash("Announcement updated", "success")
        return redirect(url_for("admin_announcements"))
    conn.close()
    return render_template("announcement_edit.html", announcement=ann)

@app.route("/announcement/delete/<int:announcement_id>", methods=["POST"])
def announcement_delete(announcement_id):
    if session.get("role") != "admin":
        flash("Access denied", "danger")
        return redirect(url_for("dashboard"))
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("DELETE FROM announcements WHERE id=?", (announcement_id,))
    conn.commit()
    conn.close()
    flash("Announcement deleted", "success")
    return redirect(url_for("admin_announcements"))

@app.route('/idea/<int:idea_id>', methods=["GET","POST"])
def idea_detail(idea_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT i.id, i.title, i.description, i.photo, u.username, i.author_id, i.created_at, i.is_pinned FROM ideas i JOIN users u ON i.author_id = u.id WHERE i.id=?", (idea_id,))
    idea = c.fetchone()
    c.execute("SELECT c.content, u.username, c.timestamp, c.id, c.user_id FROM comments c JOIN users u ON c.user_id = u.id WHERE c.idea_id=? ORDER BY c.id DESC", (idea_id,))
    comments = c.fetchall()
    conn.close()
    if request.method == "POST":
        if "user_id" not in session:
            flash("Please login to comment", "warning")
            return redirect(url_for("login"))
        content = request.form.get("comment","").strip()
        if content:
            conn = sqlite3.connect(DB)
            c = conn.cursor()
            c.execute("INSERT INTO comments (idea_id, user_id, content) VALUES (?, ?, ?)", (idea_id, session["user_id"], content))
            conn.commit()
            conn.close()
            flash("Comment posted", "success")
        return redirect(url_for("idea_detail", idea_id=idea_id))
    return render_template("idea_detail.html", idea=idea, comments=comments)

@app.route("/comment/edit/<int:comment_id>", methods=["GET","POST"])
def comment_edit(comment_id):
    if "user_id" not in session:
        flash("Please login", "warning")
        return redirect(url_for("login"))
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT content, user_id, idea_id FROM comments WHERE id=?", (comment_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        flash("Comment not found", "danger")
        return redirect(url_for("dashboard"))
    if session.get("role") != "admin" and session.get("user_id") != row[1]:
        conn.close()
        flash("Access denied", "danger")
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        content = request.form.get("content","").strip()
        c.execute("UPDATE comments SET content=? WHERE id=?", (content, comment_id))
        conn.commit()
        conn.close()
        flash("Comment updated", "success")
        return redirect(url_for("idea_detail", idea_id=row[2]))
    conn.close()
    return render_template("comment_edit.html", comment=row, comment_id=comment_id)

@app.route("/comment/delete/<int:comment_id>", methods=["POST"])
def comment_delete(comment_id):
    if "user_id" not in session:
        flash("Please login", "warning")
        return redirect(url_for("login"))
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT user_id, idea_id FROM comments WHERE id=?", (comment_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        flash("Comment not found", "danger")
        return redirect(url_for("dashboard"))
    if session.get("role") != "admin" and session.get("user_id") != row[0]:
        conn.close()
        flash("Access denied", "danger")
        return redirect(url_for("dashboard"))
    c.execute("DELETE FROM comments WHERE id=?", (comment_id,))
    conn.commit()
    conn.close()
    flash("Comment deleted", "success")
    return redirect(url_for("idea_detail", idea_id=row[1]))

@app.route("/idea/pin/<int:idea_id>", methods=["POST"])
def idea_pin(idea_id):
    if session.get("role") != "admin":
        flash("Access denied", "danger")
        return redirect(url_for("dashboard"))
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("UPDATE ideas SET is_pinned=1 WHERE id=?", (idea_id,))
    conn.commit()
    conn.close()
    flash("Idea pinned", "success")
    return redirect(url_for("dashboard"))

@app.route("/idea/unpin/<int:idea_id>", methods=["POST"])
def idea_unpin(idea_id):
    if session.get("role") != "admin":
        flash("Access denied", "danger")
        return redirect(url_for("dashboard"))
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("UPDATE ideas SET is_pinned=0 WHERE id=?", (idea_id,))
    conn.commit()
    conn.close()
    flash("Idea unpinned", "info")
    return redirect(url_for("dashboard"))

@app.route("/vote", methods=["POST"])
def vote():
    if "user_id" not in session:
        return jsonify({"status":"error","message":"Login required"}), 401
    data = request.get_json() or {}
    try:
        idea_id = int(data.get("idea_id"))
        vote_type = int(data.get("vote_type"))
    except:
        return jsonify({"status":"error","message":"Invalid data"}), 400

    user_id = session["user_id"]
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT id, vote_type FROM votes WHERE idea_id=? AND user_id=?", (idea_id, user_id))
    existing = c.fetchone()
    if not existing:
        c.execute("INSERT INTO votes (idea_id, user_id, vote_type) VALUES (?, ?, ?)", (idea_id, user_id, vote_type))
        conn.commit()
        conn.close()
        return jsonify({"status":"ok","action":"added","vote_type":vote_type})
    else:
        vid, cur = existing
        if cur == vote_type:
            c.execute("DELETE FROM votes WHERE id=?", (vid,))
            conn.commit()
            conn.close()
            return jsonify({"status":"ok","action":"removed","vote_type":vote_type})
        else:
            c.execute("UPDATE votes SET vote_type=? WHERE id=?", (vote_type, vid))
            conn.commit()
            conn.close()
            return jsonify({"status":"ok","action":"switched","vote_type":vote_type})

@app.route("/delete_idea/<int:idea_id>", methods=["POST"])
def delete_idea(idea_id):
    if "user_id" not in session:
        flash("Please login", "warning")
        return redirect(url_for("login"))
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT author_id, photo FROM ideas WHERE id=?", (idea_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        flash("Idea not found", "danger")
        return redirect(url_for("dashboard"))
    author_id, photo = row
    if session.get("role") == "admin" or session.get("user_id") == author_id:
        c.execute("DELETE FROM comments WHERE idea_id=?", (idea_id,))
        c.execute("DELETE FROM votes WHERE idea_id=?", (idea_id,))
        c.execute("DELETE FROM ideas WHERE id=?", (idea_id,))
        conn.commit()
        conn.close()
        if photo:
            try:
                os.remove(os.path.join(UPLOAD_FOLDER, photo))
            except:
                pass
        flash("Idea deleted", "success")
    else:
        conn.close()
        flash("Access denied", "danger")
    return redirect(url_for("dashboard"))

@app.route("/admin/users")
def admin_users():
    if session.get("role") != "admin":
        flash("Access denied", "danger")
        return redirect(url_for("dashboard"))
    users = query_db("SELECT id, username, role FROM users ORDER BY id DESC")
    return render_template("admin_users.html", users=users)

@app.route("/admin/delete_user/<int:user_id>", methods=["POST"])
def admin_delete_user(user_id):
    if session.get("role") != "admin":
        flash("Access denied", "danger")
        return redirect(url_for("dashboard"))
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("DELETE FROM comments WHERE user_id=?", (user_id,))
    c.execute("DELETE FROM votes WHERE user_id=?", (user_id,))
    c.execute("DELETE FROM ideas WHERE author_id=?", (user_id,))
    c.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    flash("User deleted", "success")
    return redirect(url_for("admin_users"))

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)