import os
import requests
import base64
from flask import Flask, render_template, request, redirect, session, url_for, flash, send_from_directory
import uuid
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import OperationalError

app = Flask(__name__)

app.secret_key = os.environ.get('FLASK_SECRET_KEY') #strong key

# Database Setup
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Define the User database model
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)

    def __repr__(self):
        return f'<User {self.username}>'

# A helper function to create the database tables.
def create_tables():
    """This function is called to create the database tables."""
    print("Creating database tables...")
    with app.app_context():
        db.create_all()
    print("Database tables created.")

# Directory for saving uploaded images.
UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Allowed image extensions for validation
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/')
@app.route('/home')
def home():
    """Renders the home page, accessible to all users."""
    return render_template('home.html', 
                           logged_in=session.get('logged_in'), 
                           username=session.get('username'))

@app.route('/login_page')
def login_page():
    """Renders the login form, if the user is not already logged in."""
    if session.get('logged_in'):
        flash("You are already logged in.", 'info')
        return redirect(url_for('main'))
    return render_template('login.html')

@app.route('/register_page')
def register_page():
    """Renders the registration form, if the user is not already logged in."""
    if session.get('logged_in'):
        flash("You are already logged in.", 'info')
        return redirect(url_for('main'))
    return render_template('register.html')

@app.route('/register_user', methods=['POST'])
def register_user():
    """Handles new user registration by creating a new User object and saving it."""
    username = request.form.get('username')
    password = request.form.get('password')

    if not username or not password:
        flash("Username and password cannot be empty.", 'error')
        return redirect(url_for('register_page'))

    # try-except block to handle the case where the table doesn't exist yet.
    try:
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash("Username already exists. Please choose a different one.", 'error')
            return redirect(url_for('register_page'))

        # Create a new user object
        new_user = User(username=username, password=password)
    
        # Add the new user to the database session and commit
        db.session.add(new_user)
        db.session.commit()
        flash("Registration successful! Please log in.", 'success')
        return redirect(url_for('login_page'))
    except OperationalError:
        # If the 'user' table doesn't exist, create it and retry the registration.
        print("OperationalError caught. Creating tables and retrying registration.")
        db.session.rollback()
        create_tables()
        return register_user() # Rerun the function to complete the registration.
    except Exception as e:
        db.session.rollback() # Roll back on other errors
        flash(f"An unexpected error occurred: {e}", 'error')
        return redirect(url_for('register_page'))

@app.route('/submit', methods=['POST'])
def submit():
    """Handles user login."""
    username = request.form.get('username')
    password = request.form.get('password') 
    
    # try-except block to handle the case where the table doesn't exist yet.
    try:
        # Query the database for a user with the given username and password
        user = User.query.filter_by(username=username, password=password).first()    
        if user:
            session['logged_in'] = True
            session['username'] = user.username
            flash("Login successful!", 'success')
            return redirect(url_for('main')) 
        else:
            flash("Invalid credentials. Please try again.", 'error')
            return redirect(url_for('login_page'))
    except OperationalError:
        # If the 'user' table doesn't exist, create it and retry the login.
        print("OperationalError caught. Creating tables and retrying login.")
        db.session.rollback()
        create_tables()
        return submit() # Rerun the function to complete the login.

@app.route('/logout')
def logout():
    """Logs the user out."""
    session.pop('logged_in', None)
    session.pop('username', None)
    flash("You have been logged out.", 'info')
    return redirect(url_for('home'))

@app.route('/main')
def main():
    """A protected page for authenticated users."""
    if not session.get('logged_in'):
        flash("Please log in to access this page.", 'error')
        return redirect(url_for('login_page'))
    
    return render_template('main.html', username=session.get('username'))

@app.route('/upload_and_classify', methods=['POST'])
def upload_and_classify():
    """Handles file upload and then calls the Gemini API for classification."""
    if not session.get('logged_in'):
        flash("You must be logged in to upload files.", 'error')
        return redirect(url_for('login_page'))
    # Check if the file part is in the request
    if 'file' not in request.files:
        flash('No file part', 'error')
        return redirect(url_for('main'))
    
    file = request.files['file']
    
    # If the user does not select a file, the browser submits an empty part without a filename
    if file.filename == '':
        flash('No selected file', 'error')
        return redirect(url_for('main'))
    
    if file and allowed_file(file.filename):
        try:
            filename = str(uuid.uuid4()) + os.path.splitext(file.filename)[1]
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)

            # Read the image file and encode it to base64
            with open(filepath, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode('utf-8')

            # Configure the API call to Gemini
            api_key = "GEMINI_API_KEY"
            headers = {
                "Content-Type": "application/json",
            }
            # The prompt for the Gemini model
            prompt = "In not more than 6-8 short & to-the point lines, tell what waste category is this image? Classify it as biodegradable, non-biodegradable, e-waste, hazardous, recyclable and others. Also, give a short, friendly explanation and the right and convenient way to dump it for better waste management. If it's recyclable, suggest convincing ideas for recycling it."
            
            # The API request payload
            payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {"text": prompt},
                            {
                                "inlineData": {
                                    # MimeType for the API request
                                    "mimeType": "image/jpeg" if file.filename.lower().endswith(('.jpg', '.jpeg')) else "image/png",
                                    "data": encoded_string
                                }
                            }
                        ]
                    }
                ]
            }

            # The model and URL have been updated to a newer, more stable version.
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-05-20:generateContent?key={api_key}"

            # Make the API call
            response = requests.post(url, json=payload, headers=headers)
            response.raise_for_status() # Raise an error for bad status codes
            
            # Parse the response to get the classification text
            result = response.json()
            classification_text = result['candidates'][0]['content']['parts'][0]['text']

            # Render a new page with the classification result
            return render_template('classify.html', 
                                   classification=classification_text, 
                                   image_filename=filename, # Pass the filename to the template
                                   logged_in=session.get('logged_in'), 
                                   username=session.get('username'))

        except OperationalError:
            # If the 'user' table doesn't exist, create it and retry.
            db.session.rollback()
            create_tables()
            # Retry the function call after creating the tables
            return upload_and_classify()
        except requests.exceptions.RequestException as e:
            flash(f"An error occurred during API call: {e}", 'error')
            return redirect(url_for('main'))
        except Exception as e:
            flash(f"An unexpected error occurred: {e}", 'error')
            return redirect(url_for('main'))
    else:
        flash('Allowed file types are png, jpg, jpeg', 'error')
        return redirect(url_for('main'))

if __name__ == '__main__':
    app.run()
    