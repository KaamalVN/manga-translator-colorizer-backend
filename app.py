import os
import subprocess
from flask import Flask, request, jsonify
from flask_cors import CORS
from PIL import Image
import threading
import re
from azure.storage.blob import BlobServiceClient

app = Flask(__name__)
CORS(app)

# Azure Blob Storage Configuration
AZURE_CONNECTION_STRING = os.getenv('AZURE_CONNECTION_STRING')
AZURE_CONTAINER_NAME = "images"

# Initialize the BlobServiceClient
blob_service_client = BlobServiceClient.from_connection_string(AZURE_CONNECTION_STRING)
container_client = blob_service_client.get_container_client(AZURE_CONTAINER_NAME)

# Global dictionary to track download status and colorization status
download_status = {}
colorization_status = {}

def run_colorization(session_id):
    global colorization_status
    
    colorization_status[session_id] = 'in progress'
    
    docker_command = [
        "docker", "run",
        "-v", f"/tmp/uploads:/app/uploads",  # Update to use temp folder for Docker
        "colorizer",
        "-p", f"/app/uploads/{session_id}"   # Include session-specific folder in Docker run
    ]

    print(f"Running command: {' '.join(docker_command)}")

    try:
        subprocess.run(docker_command, check=True)
        colorization_status[session_id] = 'completed'
        print("Colorization process completed successfully.")
    except subprocess.CalledProcessError as e:
        colorization_status[session_id] = 'failed'
        print(f"An error occurred: {e}")

def upload_to_blob(file_path, blob_name):
    with open(file_path, "rb") as data:
        container_client.upload_blob(name=blob_name, data=data, overwrite=True)

def download_from_blob(blob_name, download_path):
    with open(download_path, "wb") as download_file:
        download_file.write(container_client.download_blob(blob_name).readall())

def run_gallery_dl(url, session_id):
    global download_status
    session_dir = f"/tmp/downloads/{session_id}"  # Local temporary download directory
    os.makedirs(session_dir, exist_ok=True)

    download_status[session_id] = 'in progress'
    command = ['gallery-dl', url, '--dest', session_dir]

    try:
        subprocess.run(command, check=True)

        upload_dir = f"{session_id}/"
        
        for root, _, files in os.walk(session_dir):
            for file_name in files:
                src_file_path = os.path.join(root, file_name)
                target_file_path = f"/tmp/uploads/{session_id}/{file_name.rsplit('.', 1)[0]}.jpg"

                os.makedirs(f"/tmp/uploads/{session_id}", exist_ok=True)  # Ensure session-specific upload folder exists

                with Image.open(src_file_path) as img:
                    img.convert('RGB').save(target_file_path, 'JPEG')

                # Upload to Azure Blob Storage
                upload_to_blob(target_file_path, f"{upload_dir}{file_name.rsplit('.', 1)[0]}.jpg")

        download_status[session_id] = 'completed'

    except subprocess.CalledProcessError:
        download_status[session_id] = 'failed'

@app.route('/upload', methods=['POST'])
def upload_images():
    session_id = request.form.get('sessionId') or 'default'
    upload_dir = f"{session_id}/"
    
    # Get files from the request
    if 'images' not in request.files:
        return jsonify({'error': 'No images provided'}), 400

    files = request.files.getlist('images')

    for file in files:
        # Create a blob name
        blob_name = f"{upload_dir}{file.filename}"
        # Save file locally for Docker
        local_path = f"/tmp/uploads/{session_id}/{file.filename}"
        os.makedirs(f"/tmp/uploads/{session_id}", exist_ok=True)  # Ensure session-specific folder exists
        file.save(local_path)
        # Upload to Azure Blob Storage
        upload_to_blob(local_path, blob_name)

    return jsonify({'message': 'Files uploaded successfully', 'files': [f.filename for f in files]})

@app.route('/get-images/<session_id>', methods=['GET'])
def get_images(session_id):
    # List blobs in the specified session directory
    image_urls = []
    blobs = container_client.list_blobs(name_starts_with=f"{session_id}/")
    for blob in blobs:
        image_url = f"https://{blob_service_client.account_name}.blob.core.windows.net/{AZURE_CONTAINER_NAME}/{blob.name}"
        image_urls.append(image_url)

    return jsonify({'images': image_urls})

@app.route('/get-colorized-images/<session_id>', methods=['GET'])
def get_colorized_images(session_id):
    # Define the colorized directory path
    colorized_dir = f"{session_id}/colorization/"

    # List colorized blobs
    colorized_image_urls = []
    blobs = container_client.list_blobs(name_starts_with=colorized_dir)
    for blob in blobs:
        colorized_image_url = f"https://{blob_service_client.account_name}.blob.core.windows.net/{AZURE_CONTAINER_NAME}/{blob.name}"
        colorized_image_urls.append(colorized_image_url)

    if not colorized_image_urls:
        return jsonify({'error': f'No colorized images found for session {session_id}'}), 404

    return jsonify({'colorized_images': colorized_image_urls})

@app.route('/colorization-status/<session_id>', methods=['GET'])
def check_colorization_status(session_id):
    global colorization_status
    status = colorization_status.get(session_id, 'not found')
    return jsonify({'status': status})

@app.route('/download', methods=['GET'])
def download_images():
    url = request.args.get('url')
    session_id = request.args.get('sessionId')

    # Start a background thread for downloading
    threading.Thread(target=run_gallery_dl, args=(url, session_id)).start()

    return jsonify({'job_id': session_id}), 202  # Return job ID and HTTP 202 Accepted

@app.route('/download-status/<session_id>', methods=['GET'])
def check_download_status(session_id):
    global download_status
    status = download_status.get(session_id, 'not found')
    return jsonify({'status': status})

@app.route('/process', methods=['POST'])
def process_images():
    data = request.json
    session_id = data.get('sessionId')
    colorizer_enabled = data.get('colorizer', False)

    if colorizer_enabled:
        print("Colorization is enabled.")
        threading.Thread(target=run_colorization, args=(session_id,)).start()

    return jsonify({"status": "processing_started"})

if __name__ == '__main__':
    app.run(port=6000)
