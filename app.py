import os
import requests
import base64
from io import BytesIO
import mimetypes
from flask import Flask, render_template, request, redirect, session, url_for, flash, send_from_directory
import uuid
from supabase import create_client, Client
from dotenv import load_dotenv
load_dotenv()
import json

app = Flask(__name__)

app.secret_key = os.environ.get('FLASK_SECRET_KEY')

# Supabase configuration from environment variables
# These environment variables must be set in your Vercel deployment settings.
SUPABASE_URL: str = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY: str = os.environ.get("SUPABASE_SERVICE_KEY")
GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# Allowed image extensions for validation
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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
    username = request.form.get('username')
    password = request.form.get('password')

    if not username or not password:
        flash("Username and password cannot be empty.", 'error')
        return redirect(url_for('register_page'))

    try:
        # Check if username already exists in the 'users' table
        # Using the Supabase client to query the 'users' table
        response = supabase.table('users').select('*').eq('username', username).execute()
        
        # The Supabase client returns data in response.data (list of dictionaries)
        if response.data:
            flash("Username already exists. Please choose a different one.", 'error')
            return redirect(url_for('register_page'))

        # Insert the new user into the 'users' table
        supabase.table('users').insert({"username": username, "password": password}).execute()
        flash("Registration successful! Please log in.", 'success')
        return redirect(url_for('login_page'))
    except Exception as e:
        flash(f"An unexpected error occurred during registration: {e}", 'error')
        return redirect(url_for('register_page'))

@app.route('/submit', methods=['POST'])
def submit():
    #Handles user login by querying the Supabase 'users' table
    username = request.form.get('username')
    password = request.form.get('password') 
    
    try:
        # Query the Supabase 'users' table for a user with the given username and password
        response = supabase.table('users').select('*').eq('username', username).eq('password', password).execute()
        user_data = response.data

        if user_data:
            # If user_data is not empty, a user was found
            session['logged_in'] = True
            session['username'] = user_data[0]['username'] # Get username from the first matching record
            flash("Login successful!", 'success')
            return redirect(url_for('main')) 
        else:
            flash("Invalid credentials. Please try again.", 'error')
            return redirect(url_for('login_page'))
    except Exception as e:
        flash(f"An unexpected error occurred during login: {e}", 'error')
        return redirect(url_for('login_page'))

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
    """Handles file upload, stores the image in Supabase, and then calls the Gemini API for classification."""
    if not session.get('logged_in'):
        flash("You must be logged in to upload files.", 'error')
        return redirect(url_for('login_page'))
    
    if 'file' not in request.files:
        flash('No file part', 'error')
        return redirect(url_for('main'))
    
    file = request.files['file']
    
    if file.filename == '':
        flash('No selected file', 'error')
        return redirect(url_for('main'))
    
    if file and allowed_file(file.filename):
        try:
            filename = str(uuid.uuid4()) + os.path.splitext(file.filename)[1]
            
            supabase_url = os.environ.get("SUPABASE_URL")
            supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")
            supabase = create_client(supabase_url, supabase_key)

            # Read the file content into a bytes object
            file_content = file.read()
            
            # Store image in Supabase bucket using the bytes object
            bucket_name = 'uploads'
            res = supabase.storage.from_(bucket_name).upload(path=filename, file=file_content, file_options={"content-type": file.mimetype})
            
            # if 'error' in res and res['error']:
            #     flash(f"Error uploading to Supabase: {res['error'].get('message', 'Unknown error')}", 'error')
            #     return redirect(url_for('main'))

            image_url = supabase.storage.from_(bucket_name).get_public_url(filename)

            # We already have the file content, so no need to re-read.
            # Just encode the existing 'file_content' for the Gemini API call.
            encoded_string = base64.b64encode(file_content).decode('utf-8')
            
            api_key = os.environ.get("GEMINI_API_KEY")
            headers = {
                "Content-Type": "application/json",
            }
            prompt = "In not more than 6-8 short & to-the point lines, tell what waste category is this image? Classify it as biodegradable, non-biodegradable, e-waste, hazardous, recyclable and others. Also, give a short, friendly explanation and the right and convenient way to dump it for better waste management. If it's recyclable, suggest convincing ideas for recycling it."
            
            payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {"text": prompt},
                            {
                                "inlineData": {
                                    "mimeType": file.mimetype,
                                    "data": encoded_string
                                }
                            }
                        ]
                    }
                ]
            }
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-05-20:generateContent?key={api_key}"

            response = requests.post(url, json=payload, headers=headers)
            response.raise_for_status()
            
            result = response.json()
            classification_text = result['candidates'][0]['content']['parts'][0]['text']

            return render_template('classify.html', 
                                    classification=classification_text, 
                                    image_url=image_url, 
                                    logged_in=session.get('logged_in'), 
                                    username=session.get('username'))

        except requests.exceptions.RequestException as e:
            flash(f"An error occurred during API call: {e}", 'error')
            return redirect(url_for('main'))
        except Exception as e:
            flash(f"An unexpected error occurred: {e}", 'error')
            return redirect(url_for('main'))
    else:
        flash('Allowed file types are png, jpg, jpeg', 'error')
        return redirect(url_for('main'))
#     app.run(debug=True)
