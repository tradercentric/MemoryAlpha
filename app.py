import os
import uuid
import mimetypes
from flask import Flask, request, session, jsonify, Response, render_template
from werkzeug.security import generate_password_hash, check_password_hash
from google.cloud import storage, firestore

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))

GCS_BUCKET = os.environ.get('GCS_BUCKET', 'memory-alpha-397310840166')

db = firestore.Client()
gcs = storage.Client()
bucket = gcs.bucket(GCS_BUCKET)


def require_album_auth(album_id):
    return session.get(f'auth_{album_id}') is True


def get_album(album_id):
    doc = db.collection('albums').document(album_id).get()
    if not doc.exists:
        return None
    return doc.to_dict()


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/albums', methods=['POST'])
def create_album():
    data = request.get_json()
    if not data or not data.get('name') or not data.get('secret'):
        return jsonify({'error': 'name and secret required'}), 400

    album_id = str(uuid.uuid4())
    secret_hash = generate_password_hash(data['secret'])

    db.collection('albums').document(album_id).set({
        'id': album_id,
        'name': data['name'],
        'secret_hash': secret_hash,
        'created_at': firestore.SERVER_TIMESTAMP,
        'photos': []
    })

    session[f'auth_{album_id}'] = True
    return jsonify({'album_id': album_id, 'name': data['name']}), 201


@app.route('/api/albums/<album_id>/verify', methods=['POST'])
def verify_album(album_id):
    album = get_album(album_id)
    if not album:
        return jsonify({'error': 'Album not found'}), 404

    data = request.get_json()
    if not data or not data.get('secret'):
        return jsonify({'error': 'secret required'}), 400

    if not check_password_hash(album['secret_hash'], data['secret']):
        return jsonify({'error': 'Invalid secret'}), 401

    session[f'auth_{album_id}'] = True
    return jsonify({'album_id': album_id, 'name': album['name']})


@app.route('/api/albums/<album_id>', methods=['GET'])
def get_album_info(album_id):
    if not require_album_auth(album_id):
        return jsonify({'error': 'Unauthorized'}), 401

    album = get_album(album_id)
    if not album:
        return jsonify({'error': 'Album not found'}), 404

    return jsonify({
        'album_id': album_id,
        'name': album['name'],
        'photos': album.get('photos', [])
    })


@app.route('/api/albums/<album_id>/photos', methods=['POST'])
def upload_photos(album_id):
    if not require_album_auth(album_id):
        return jsonify({'error': 'Unauthorized'}), 401

    album = get_album(album_id)
    if not album:
        return jsonify({'error': 'Album not found'}), 404

    files = request.files.getlist('photos')
    if not files:
        return jsonify({'error': 'No files provided'}), 400

    uploaded = []
    for f in files:
        if not f.filename:
            continue
        ext = os.path.splitext(f.filename)[1].lower()
        filename = str(uuid.uuid4()) + ext
        blob_path = f'albums/{album_id}/{filename}'
        blob = bucket.blob(blob_path)
        content_type = f.content_type or mimetypes.guess_type(f.filename)[0] or 'application/octet-stream'
        blob.upload_from_file(f.stream, content_type=content_type)
        uploaded.append(filename)

    if uploaded:
        db.collection('albums').document(album_id).update({
            'photos': firestore.ArrayUnion(uploaded)
        })

    return jsonify({'uploaded': uploaded}), 201


@app.route('/api/albums/<album_id>/photos/<filename>', methods=['DELETE'])
def delete_photo(album_id, filename):
    if not require_album_auth(album_id):
        return jsonify({'error': 'Unauthorized'}), 401

    album = get_album(album_id)
    if not album:
        return jsonify({'error': 'Album not found'}), 404

    blob_path = f'albums/{album_id}/{filename}'
    blob = bucket.blob(blob_path)
    if blob.exists():
        blob.delete()

    db.collection('albums').document(album_id).update({
        'photos': firestore.ArrayRemove([filename])
    })

    return jsonify({'deleted': filename})


@app.route('/api/albums/<album_id>/photos/<filename>', methods=['GET'])
def serve_photo(album_id, filename):
    if not require_album_auth(album_id):
        return jsonify({'error': 'Unauthorized'}), 401

    album = get_album(album_id)
    if not album:
        return jsonify({'error': 'Album not found'}), 404

    blob_path = f'albums/{album_id}/{filename}'
    blob = bucket.blob(blob_path)
    if not blob.exists():
        return jsonify({'error': 'Photo not found'}), 404

    data = blob.download_as_bytes()
    content_type = blob.content_type or mimetypes.guess_type(filename)[0] or 'application/octet-stream'
    return Response(data, content_type=content_type)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
