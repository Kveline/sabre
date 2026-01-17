"""
This file runs the backend for a simple read-aloud audio book recorder app.
It works as follows:
    - a user selects and uploads a .txt file that contains 1 sentence per line
    - the backend stores the
"""
from flask import Flask, render_template, request, jsonify, send_file, session
import os
from zipfile import ZipFile
from io import BytesIO
import hashlib
import uuid
import json
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, storage

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24).hex())

# Initialize Firebase
firebase_creds = json.loads(os.environ.get('FIREBASE_CREDENTIALS', '{}'))
if firebase_creds:
    cred = credentials.Certificate(firebase_creds)
    firebase_admin.initialize_app(cred, {
        'storageBucket': os.environ.get('FIREBASE_BUCKET')
    })
    bucket = storage.bucket()
else:
    bucket = None
    print("WARNING: Firebase not configured, using local storage")

LOCAL_SENTENCES_FILE = "last_uploaded_sentences.txt"


def get_session_id():
    """Get or create a unique session ID for the current user."""
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
    return session['session_id']


def upload_to_firebase(file_data, blob_path):
    """Upload file data to Firebase Storage."""
    if bucket:
        blob = bucket.blob(blob_path)
        blob.upload_from_file(file_data, content_type='audio/webm')
        return True
    return False


def download_from_firebase(blob_path):
    """Download file from Firebase Storage."""
    if bucket:
        blob = bucket.blob(blob_path)
        if blob.exists():
            data = BytesIO()
            blob.download_to_file(data)
            data.seek(0)
            return data
    return None


def delete_from_firebase(blob_path):
    """Delete file from Firebase Storage."""
    if bucket:
        blob = bucket.blob(blob_path)
        if blob.exists():
            blob.delete()


def get_user_mapping_path(session_id):
    """Get the Firebase path for user's mapping file."""
    return f"{session_id}/mapping.json"


def get_user_audio_path(session_id, filename):
    """Get the Firebase path for user's audio file."""
    return f"{session_id}/{filename}"


def load_user_mappings(session_id):
    """Load user's audio mappings from Firebase."""
    mapping_path = get_user_mapping_path(session_id)
    data = download_from_firebase(mapping_path)
    if data:
        return json.load(data)
    return {}


def save_user_mappings(session_id, mappings):
    """Save user's audio mappings to Firebase."""
    mapping_path = get_user_mapping_path(session_id)
    data = BytesIO(json.dumps(mappings).encode('utf-8'))
    if bucket:
        blob = bucket.blob(mapping_path)
        blob.upload_from_file(data, content_type='application/json')


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/upload-sentences', methods=['POST'])
def upload():
    file = request.files['file']
    sentences = file.read().decode('utf-8').split('\n')
    sentences = [s.strip() for s in sentences if s.strip()]
    with open(LOCAL_SENTENCES_FILE, 'w', encoding='utf-8') as f:
        f.write('\n'.join(sentences))
    return jsonify(sentences)


@app.route('/upload-audio', methods=['POST'])
def upload_audio():
    audio = request.files['audio']
    sentence = request.form.get("sentence_text")
    md5hash = hashlib.md5(sentence.encode())
    filename = f"{md5hash.hexdigest()}.webm"

    session_id = get_session_id()

    # Upload audio to Firebase
    audio_path = get_user_audio_path(session_id, filename)
    upload_to_firebase(audio, audio_path)

    # Update mappings in Firebase
    mappings = load_user_mappings(session_id)
    mappings[filename] = sentence
    save_user_mappings(session_id, mappings)

    return 'Audio received', 200


@app.route('/download-recordings')
def download_recordings():
    session_id = get_session_id()

    # Load mappings from Firebase
    mappings = load_user_mappings(session_id)

    if not mappings:
        return 'No recordings found', 404

    # Create TSV content
    tsv_content = "audio_filename\tsentence\n" + '\n'.join(
        f"{fn}\t{sent}" for fn, sent in mappings.items()
    )

    # Create ZIP file
    memory_file = BytesIO()
    with ZipFile(memory_file, 'w') as zf:
        # Add audio files from Firebase
        for filename, _ in mappings.items():
            audio_path = get_user_audio_path(session_id, filename)
            audio_data = download_from_firebase(audio_path)
            if audio_data:
                zf.writestr(filename, audio_data.read())
                # Delete from Firebase after adding to ZIP
                delete_from_firebase(audio_path)

        # Add TSV mapping
        zf.writestr("mapping.tsv", tsv_content)

    # Delete mapping file from Firebase
    delete_from_firebase(get_user_mapping_path(session_id))

    memory_file.seek(0)
    return send_file(memory_file, as_attachment=True, download_name='recordings.zip')


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port)
