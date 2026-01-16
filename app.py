"""
This file runs the backend for a simple read-aloud audio book recorder app.
It works as follows:
    - a user selects and uploads a .txt file that contains 1 sentence per line
    - the backend stores the 
"""
from flask import Flask, render_template, request, jsonify, send_file, session
import os
import glob
from zipfile import ZipFile
from io import BytesIO
import hashlib
import uuid


app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
UPLOAD_FOLDER = 'audio_files'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def get_session_id():
    """Get or create a unique session ID for the current user."""
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
    return session['session_id']


def get_user_folder():
    """Get the folder path for the current user's audio files."""
    session_id = get_session_id()
    user_folder = os.path.join(UPLOAD_FOLDER, session_id)
    os.makedirs(user_folder, exist_ok=True)
    return user_folder


def get_user_tsv():
    """Get the TSV file path for the current user's mappings."""
    session_id = get_session_id()
    return os.path.join(UPLOAD_FOLDER, session_id, 'audio_mapping.tsv')

LOCAL_SENTENCES_FILE = "last_uploaded_sentences.txt"


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
    idx = request.form.get('sentence_idx', '0')
    sentence = request.form.get("sentence_text")
    md5hash = hashlib.md5(sentence.encode())
    filename = f"{md5hash.hexdigest()}.webm"

    user_folder = get_user_folder()
    user_tsv = get_user_tsv()

    path = os.path.join(user_folder, filename)
    audio.save(path)

    # Make sure mapping is unique and up-to-date
    mappings = {}
    if os.path.exists(user_tsv):
        with open(user_tsv, encoding='utf-8') as f:
            for line in f:
                parts = line.rstrip('\n').split('\t')
                if len(parts) == 2:
                    mappings[parts[0]] = parts[1]
    mappings[filename] = sentence
    with open(user_tsv, 'w', encoding='utf-8') as f:
        for fn, sent in mappings.items():
            f.write(f"{fn}\t{sent}\n")

    return 'Audio received', 200

@app.route('/download-recordings')
def download_recordings():
    user_folder = get_user_folder()
    user_tsv = get_user_tsv()

    # Load mapping of audio files to sentences (only for this user)
    mappings = []
    if os.path.exists(user_tsv):
        with open(user_tsv, encoding='utf-8') as f:
            for line in f:
                parts = line.rstrip('\n').split('\t')
                if len(parts) == 2 and os.path.exists(os.path.join(user_folder, parts[0])):
                    mappings.append((parts[0], parts[1]))

    tsv_content = "audio_filename\tsentence\n" + '\n'.join(f"{fn}\t{sent}" for fn, sent in mappings)
    memory_file = BytesIO()
    with ZipFile(memory_file, 'w') as zf:
        # Add audio files
        for filename, _ in mappings:
            zf.write(os.path.join(user_folder, filename), filename)
            os.remove(os.path.join(user_folder, filename))
        # Add TSV mapping
        zf.writestr("mapping.tsv", tsv_content)

    # Clean up user's TSV file after download
    if os.path.exists(user_tsv):
        os.remove(user_tsv)

    memory_file.seek(0)
    return send_file(memory_file, as_attachment=True, download_name='recordings.zip')

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))  # Render sets $PORT automatically
    app.run(host="0.0.0.0", port=port)