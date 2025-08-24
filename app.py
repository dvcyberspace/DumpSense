import os
import requests
import base64
from flask import Flask, render_template, request, redirect, session, url_for, flash, send_from_directory
import uuid
from supabase import create_client, Client

app = Flask(__name__)

app.secret_key = os.environ.get('FLASK_SECRET_KEY')

# Supabase configuration from environment variables
# These environment variables must be set in your Vercel deployment settings.
SUPABASE_URL: str = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY: str = os.environ.get("SUPABASE_SERVICE_KEY")
GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY") 

print(f"SUPABASE_URL: {SUPABASE_URL}")
print(f"SUPABASE_SERVICE_KEY: {SUPABASE_SERVICE_KEY}")

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
        # Check if username already exists in the 'user' table
        # Using the Supabase client to query the 'user' table
        response = supabase.table('user').select('*').eq('username', username).execute()
        
        # The Supabase client returns data in response.data (list of dictionaries)
        if response.data:
            flash("Username already exists. Please choose a different one.", 'error')
            return redirect(url_for('register_page'))

        # Insert the new user into the 'user' table
        supabase.table('user').insert({"username": username, "password": password}).execute()
        flash("Registration successful! Please log in.", 'success')
        return redirect(url_for('login_page'))
    except Exception as e:
        flash(f"An unexpected error occurred during registration: {e}", 'error')
        return redirect(url_for('register_page'))

@app.route('/submit', methods=['POST'])
def submit():
    #Handles user login by querying the Supabase 'user' table
    username = request.form.get('username')
    password = request.form.get('password') 
    
    try:
        # Query the Supabase 'user' table for a user with the given username and password
        response = supabase.table('user').select('*').eq('username', username).eq('password', password).execute()
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
    """
    Handles file upload to Supabase Storage and then calls the Gemini API for classification.
    """
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
            # Generate a unique filename
            filename = str(uuid.uuid4()) + os.path.splitext(file.filename)[1]
            
            # Upload the file directly to Supabase Storage
            # 'uploads' is your bucket name, 'public/' is a folder within the bucket.
            # The file.stream.read() ensures the entire file content is sent.
            supabase.storage.from_('uploads').upload(f"public/{filename}", file.stream.read())

            # Construct the public URL for the uploaded image
            image_url = f"{SUPABASE_URL}/storage/v1/object/public/uploads/public/{filename}"

            file.seek(0) # Reset file pointer to the beginning before reading again for base64
            encoded_string = base64.b64encode(file.stream.read()).decode('utf-8')

            api_key = GEMINI_API_KEY 
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
                                    "mimeType": file.mimetype, # Use the actual mimetype from the uploaded file
                                    "data": encoded_string
                                }
                            }
                        ]
                    }
                ]
            }

            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-05-20:generateContent?key={api_key}"

            # Make the API call
            response = requests.post(url, json=payload, headers=headers)
            response.raise_for_status() # Raise an error for bad status codes
            
            # Parse the response to get the classification text
            result = response.json()
            classification_text = result['candidates'][0]['content']['parts'][0]['text']

            # Render a new page with the classification result
            # Pass the full image_url to the template
            return render_template('classify.html', 
                                   classification=classification_text, 
                                   image_filename=image_url, # Now passing the Supabase image URL
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
