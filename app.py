from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'super-camp-platform-key-2026'

def init_db():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    
    # Таблица пользователей с полем group_num (номер отряда)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            camp_name TEXT NOT NULL,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            status TEXT NOT NULL,
            group_num INTEGER -- Номер отряда (для детей и вожатых)
        )
    ''')
    
    # Таблица теста Лутошкина с полем group_num
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mood_votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            camp_name TEXT NOT NULL,
            group_num INTEGER,
            color TEXT NOT NULL,
            comment TEXT,
            vote_date TEXT NOT NULL
        )
    ''')
    
    # Главный админ сайта
    cursor.execute('SELECT * FROM users WHERE username = ?', ('admin',))
    if not cursor.fetchone():
        hashed_pw = generate_password_hash('k16admin')
        cursor.execute("INSERT INTO users (camp_name, username, password, role, status) VALUES (?, ?, ?, ?, ?)",
                       ('Система', 'admin', hashed_pw, 'admin', 'approved'))
        
    conn.commit()
    conn.close()

MOOD_COLORS = {
    'red': 'Восторженное',
    'blue': 'Грустное',
    'orange': 'Радостное',
    'yellow': 'Приятное',
    'green': 'Спокойное',
    'purple': 'Тревожное',
    'gray': 'Трудно сказать'
    'black': 'Очень плохое'
    'swampy': 'Плохое'
    'white': 'Другое'
}

@app.route('/')
def home():
    return render_template('home.html')

# Регистрация с учетом отряда
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        camp_name = request.form['camp_name']
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']
        # Номер отряда берем, только если это ребенок или вожатый
        group_num = request.form.get('group_num') if role in ['kid', 'counselor'] else None
        
        status = 'pending' if role == 'camp_admin' else 'approved'
        hashed_password = generate_password_hash(password)
        
        try:
            conn = sqlite3.connect('database.db')
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO users (camp_name, username, password, role, status, group_num) 
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (camp_name, username, hashed_password, role, status, group_num))
            conn.commit()
            conn.close()
            if status == 'pending': return "Заявка отправлена! Ожидайте одобрения."
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            return "Этот логин уже занят!"
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE username = ?', (username,))
        user = cursor.fetchone()
        conn.close()
        
        if user and check_password_hash(user[3], password):
            if user[5] == 'pending': return "Ваш аккаунт еще не одобрен!"
            session['username'] = user[2]
            session['camp_name'] = user[1]
            session['role'] = user[4]
            session['group_num'] = user[6] # Сохраняем отряд в сессию
            return redirect(url_for('dashboard'))
        return "Неверный логин или пароль!"
    return render_template('login.html')

# Отправка теста с защитой от повторов
@app.route('/submit_lutoshkin', methods=['POST'])
def submit_lutoshkin():
    if 'username' not in session or session['role'] != 'kid':
        return "Доступ запрещен", 403
        
    username = session['username']
    camp = session['camp_name']
    group_num = session['group_num']
    color = request.form['color']
    comment = request.form['comment']
    today_str = datetime.now().strftime('%Y-%m-%d')
    
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    
    # Проверка: голосовал ли ребенок сегодня?
    cursor.execute('SELECT id FROM mood_votes WHERE username = ? AND vote_date = ?', (username, today_str))
    if cursor.fetchone():
        conn.close()
        return "Вы уже заполняли тест сегодня! Возвращайтесь завтра."
        
    # Если не голосовал, записываем в БД
    cursor.execute('''
        INSERT INTO mood_votes (username, camp_name, group_num, color, comment, vote_date)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (username, camp, group_num, color, comment, today_str))
    conn.commit()
    conn.close()
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
def dashboard():
    if 'username' not in session: return redirect(url_for('login'))
    role = session['role']
    camp = session['camp_name']
    username = session['username']
    group_num = session['group_num']
    today_str = datetime.now().strftime('%Y-%m-%d')
    
    if role == 'admin':
        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()
        cursor.execute("SELECT id, camp_name, username FROM users WHERE status = 'pending'")
        pending_camps = cursor.fetchall()
        conn.close()
        return render_template('admin_dashboard.html', pending_camps=pending_camps)
    
    # Для ребенка проверяем, прошел ли он тест сегодня
    already_voted = False
    if role == 'kid':
        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM mood_votes WHERE username = ? AND vote_date = ?', (username, today_str))
        if cursor.fetchone():
            already_voted = True
        conn.close()

    # Сбор статистики для вожатых и создателей лагеря
    votes = []
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    
    if role == 'counselor':
        # Вожатый видит ТОЛЬКО свой отряд в своем лагере
        cursor.execute('''
            SELECT username, color, comment, vote_date, group_num 
            FROM mood_votes WHERE camp_name = ? AND group_num = ? ORDER BY id DESC
        ''', (camp, group_num))
        votes = cursor.fetchall()
    elif role == 'camp_admin':
        # Директор лагеря видит ВСЕ отряды своего лагеря
        cursor.execute('''
            SELECT username, color, comment, vote_date, group_num 
            FROM mood_votes WHERE camp_name = ? ORDER BY id DESC
        ''', (camp,))
        votes = cursor.fetchall()
        
    conn.close()

    return render_template('dashboard.html', username=username, camp_name=camp, 
                           role=role, group_num=group_num, votes=votes, already_voted=already_voted)

@app.route('/approve/<int:user_id>')
def approve(user_id):
    if session.get('role') != 'admin': return "Доступ запрещен!", 403
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET status = 'approved' WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('dashboard'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
