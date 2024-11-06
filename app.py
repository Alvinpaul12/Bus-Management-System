from flask import Flask, render_template, request, redirect, url_for, session, flash, g
from functools import wraps
import sqlite3
from datetime import datetime

app = Flask(__name__)
app.config.from_mapping(
    SECRET_KEY='dev',  # In production, use os.environ.get('SECRET_KEY')
    DATABASE='bus_system.db'
)

# Define admin credentials
ADMIN_CREDENTIALS = {
    'username': 'admin',
    'password': 'admin123'
}

# Replace the STUDENT_CREDENTIALS dictionary with a function to get credentials from DB
def get_student_credentials():
    db = get_db()
    students = db.execute('SELECT passengers.name, passengers.bus_number FROM passengers').fetchall()
    credentials = {}
    for student in students:
        # Password format: studentname+busnumber (e.g., "John123" for student John on bus 123)
        credentials[student['name']] = student['name'] + student['bus_number']
    db.close()
    return credentials

# Login required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('admin_login_page'))
        return f(*args, **kwargs)
    return decorated_function

# Admin required decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'is_admin' not in session or not session['is_admin']:
            flash('Admin access required')
            return redirect(url_for('admin_login_page'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def landing():
    return render_template('landing.html')

@app.route('/admin-login', methods=['GET'])
def admin_login_page():
    return render_template('admin_login.html')

@app.route('/student-login', methods=['GET'])
def student_login_page():
    return render_template('student_login.html')

@app.route('/admin-login', methods=['POST'])
def admin_login():
    username = request.form['username']
    password = request.form['password']
    
    if username == ADMIN_CREDENTIALS['username'] and password == ADMIN_CREDENTIALS['password']:
        session['username'] = username
        session['is_admin'] = True
        return redirect(url_for('index'))
    
    return render_template('admin_login.html', error='Invalid credentials')

@app.route('/student-login', methods=['POST'])
def student_login():
    student_id = request.form['student_id']
    
    try:
        db = get_db()
        student = db.execute('SELECT * FROM passengers WHERE name = ?', 
                           [student_id]).fetchone()
        
        if student:
            expected_password = f"{student['name']}{student['bus_number']}"
            if request.form['password'] == expected_password:
                session['username'] = student_id
                session['is_admin'] = False
                return redirect(url_for('student_dashboard'))
        
        return render_template('student_login.html', error='Invalid credentials')
    finally:
        db.close()

@app.route('/logout')
def logout():
    username = session.get('username', 'Unknown')
    session.clear()
    return redirect(url_for('landing'))

@app.route('/index')
@login_required
@admin_required
def index():
    try:
        db = get_db()
        buses = db.execute('''
            SELECT buses.*, drivers.name as driver_name 
            FROM buses 
            LEFT JOIN drivers ON buses.driver_id = drivers.id
        ''').fetchall()
        drivers = db.execute('SELECT * FROM drivers').fetchall()
        passengers = db.execute('SELECT * FROM passengers').fetchall()
        db.close()
        return render_template('index.html', 
                             buses=buses, 
                             drivers=drivers, 
                             passengers=passengers)
    except Exception as e:
        # Debug print (remove in production)
        print(f"Error in index route: {str(e)}")
        return f"An error occurred: {str(e)}", 500

@app.route('/student_dashboard')
@login_required
def student_dashboard():
    student_name = session['username']
    db = get_db()
    # Get all buses and their drivers
    buses = db.execute('''
        SELECT buses.*, drivers.name as driver_name 
        FROM buses 
        LEFT JOIN drivers ON buses.driver_id = drivers.id
    ''').fetchall()
    # Get all passengers
    passengers = db.execute('SELECT * FROM passengers').fetchall()
    db.close()
    
    return render_template('student_dashboard.html', 
                         student_name=student_name,
                         buses=buses,
                         passengers=passengers)

def init_db():
    try:
        db = get_db()
        with app.open_resource('schema.sql', mode='r') as f:
            db.executescript(f.read())
        db.commit()
        return "Database initialized successfully"
    except Exception as e:
        return f"Error initializing database: {str(e)}"

def get_db():
    if not hasattr(g, 'db'):
        g.db = sqlite3.connect('bus_system.db')
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(error):
    if hasattr(g, 'db'):
        g.db.close()

def render_partial():
    db = get_db()
    buses = db.execute('SELECT buses.*, drivers.name as driver_name FROM buses LEFT JOIN drivers ON buses.driver_id = drivers.id').fetchall()
    drivers = db.execute('SELECT * FROM drivers').fetchall()
    passengers = db.execute('SELECT * FROM passengers').fetchall()
    db.close()
    return render_template('partial.html', buses=buses, drivers=drivers, passengers=passengers)

@app.route('/add_bus', methods=['POST'])
def add_bus():
    number = request.form['number']
    db = get_db()
    try:
        db.execute('INSERT INTO buses (number) VALUES (?)', [number])
        db.commit()
    except sqlite3.IntegrityError:
        pass  # Bus number already exists
    db.close()
    return redirect(url_for('index'))

@app.route('/add_driver', methods=['POST'])
def add_driver():
    name = request.form['name']
    bus_number = request.form.get('bus')  # Make bus optional
    db = get_db()
    try:
        # Insert driver
        db.execute('INSERT INTO drivers (name) VALUES (?)', [name])
        driver_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        
        # Assign to bus if specified
        if bus_number:
            db.execute('UPDATE buses SET driver_id = ? WHERE number = ?', [driver_id, bus_number])
        db.commit()
    except sqlite3.IntegrityError:
        pass  # Driver name already exists
    db.close()
    return redirect(url_for('index'))

@app.route('/add_passenger', methods=['POST'])
@login_required
@admin_required
def add_passenger():
    try:
        name = request.form['name']
        bus_number = request.form['bus']
        
        db = get_db()
        db.execute('INSERT INTO passengers (name, bus_number) VALUES (?, ?)',
                  [name, bus_number])
        db.commit()
        flash('Passenger added successfully', 'success')
        return redirect(url_for('index'))
    except sqlite3.IntegrityError:
        db.rollback()
        flash('Error: Passenger already exists or invalid bus number', 'error')
        return redirect(url_for('index'))
    except Exception as e:
        flash('An unexpected error occurred', 'error')
        return redirect(url_for('index'))

@app.route('/remove_bus/<number>')
def remove_bus(number):
    db = get_db()
    db.execute('DELETE FROM passengers WHERE bus_number = ?', [number])
    db.execute('DELETE FROM buses WHERE number = ?', [number])
    db.commit()
    db.close()
    return render_partial() if request.headers.get('X-Requested-With') == 'XMLHttpRequest' else redirect(url_for('index'))

@app.route('/remove_driver/<name>')
def remove_driver(name):
    db = get_db()
    driver_id = db.execute('SELECT id FROM drivers WHERE name = ?', [name]).fetchone()
    if driver_id:
        db.execute('UPDATE buses SET driver_id = NULL WHERE driver_id = ?', [driver_id[0]])
        db.execute('DELETE FROM drivers WHERE id = ?', [driver_id[0]])
        db.commit()
    db.close()
    return render_partial() if request.headers.get('X-Requested-With') == 'XMLHttpRequest' else redirect(url_for('index'))

@app.route('/remove_passenger/<name>')
def remove_passenger(name):
    db = get_db()
    db.execute('DELETE FROM passengers WHERE name = ?', [name])
    db.commit()
    db.close()
    return render_partial() if request.headers.get('X-Requested-With') == 'XMLHttpRequest' else redirect(url_for('index'))

@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    db = get_db()
    db.rollback()
    return render_template('500.html'), 500

if __name__ == '__main__':
    with app.app_context():
        init_db()
    app.run(debug=False)  # Set to False in production
