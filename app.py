import os
import subprocess
from flask import Flask, request, jsonify, send_from_directory  # Import send_from_directory here
from flask_cors import CORS
from PIL import Image
import threading, re

app = Flask(__name__)
CORS(app)

# Global dictionary to track download status
download_status = {}
# Initialize a global dictionary to store the colorization status for each session
colorization_status = {}


# Set the base directory for uploads and downloads
BASE_DIR = './'
UPLOADS_DIR = os.path.join(BASE_DIR, 'uploads')
DOWNLOADS_DIR = os.path.join(BASE_DIR, 'downloads')


def run_colorization(session_id):
    # Define the Docker command without port exposure
    global colorization_status
    
    # Set the status to 'in progress' when colorization starts
    colorization_status[session_id] = 'in progress'

    docker_command = [
        "docker", "run",
        "-v", f"{UPLOADS_DIR}:/app/uploads",
        "colorizer",
        "-p", f"/app/uploads/{session_id}"
    ]

    # Print the command for debugging
    print(f"Running command: {' '.join(docker_command)}")

    try:
        # Execute the Docker command
        subprocess.run(docker_command, check=True)
        colorization_status[session_id] = 'completed'
        print("Colorization process completed successfully.")
    except subprocess.CalledProcessError as e:
        colorization_status[session_id] = 'failed'
        print(f"An error occurred: {e}")


def run_gallery_dl(url, session_id):
    global download_status
    session_dir = os.path.join(DOWNLOADS_DIR, session_id)
    os.makedirs(session_dir, exist_ok=True)

    download_status[session_id] = 'in progress'
    command = ['gallery-dl', url, '--dest', session_dir]

    try:
        subprocess.run(command, check=True)

        uploads_dir = os.path.join(UPLOADS_DIR, session_id)
        os.makedirs(uploads_dir, exist_ok=True)

        for root, _, files in os.walk(session_dir):
            for file_name in files:
                src_file_path = os.path.join(root, file_name)
                target_file_path = os.path.join(uploads_dir, file_name.rsplit('.', 1)[0] + '.jpg')

                with Image.open(src_file_path) as img:
                    img.convert('RGB').save(target_file_path, 'JPEG')

        download_status[session_id] = 'completed'

    except subprocess.CalledProcessError:
        download_status[session_id] = 'failed'


@app.route('/upload', methods=['POST'])
def upload_images():
    session_id = request.form.get('sessionId') or 'default'
    upload_dir = os.path.join(UPLOADS_DIR, session_id)
    os.makedirs(upload_dir, exist_ok=True)

    # Get files from the request
    if 'images' not in request.files:
        return jsonify({'error': 'No images provided'}), 400

    files = request.files.getlist('images')

    for file in files:
        file_path = os.path.join(upload_dir, file.filename)
        file.save(file_path)

    return jsonify({'message': 'Files uploaded successfully', 'files': [f.filename for f in files]})

@app.route('/get-images/<session_id>', methods=['GET'])
def get_images(session_id):
    session_dir = os.path.join(UPLOADS_DIR, session_id)

    if not os.path.exists(session_dir):
        return jsonify({'error': f'No images found for session {session_id}'}), 404

    # Get image files
    image_files = [f for f in os.listdir(session_dir) if f.endswith(('.jpg', '.jpeg', '.png'))]
    
    # Sort filenames numerically based on extracted numbers
    def sort_key(filename):
        return [int(part) for part in re.findall(r'(\d+)', filename)]

    image_files.sort(key=sort_key)

    image_urls = [f'https://sturdy-eureka-4rqw559p6jgfjpx9-6000.app.github.dev/uploads/{session_id}/{f}' for f in image_files]

    return jsonify({'images': image_urls})

@app.route('/get-colorized-images/<session_id>', methods=['GET'])
def get_colorized_images(session_id):
    # Define the colorized directory path
    colorized_dir = os.path.join(UPLOADS_DIR, session_id, 'colorization')

    # Check if the colorization folder exists
    if not os.path.exists(colorized_dir):
        return jsonify({'error': f'No colorized images found for session {session_id}'}), 404

    # Get image files in the colorization folder
    colorized_image_files = [f for f in os.listdir(colorized_dir) if f.endswith(('.jpg', '.jpeg', '.png'))]
    
    # Sort filenames numerically based on extracted numbers
    def sort_key(filename):
        return [int(part) for part in re.findall(r'(\d+)', filename)]

    # Sort the colorized image files using the sort_key function
    colorized_image_files.sort(key=sort_key)

    # Generate URLs for each colorized image
    colorized_image_urls = [f'https://sturdy-eureka-4rqw559p6jgfjpx9-6000.app.github.dev/uploads/{session_id}/colorization/{f}' for f in colorized_image_files]

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
    model = data.get('model')
    colorizer_enabled = data.get('colorizer', False)
    translator_enabled = data.get('translator', False)

    input_dir = os.path.join(UPLOADS_DIR, session_id)
    translated_dir = os.path.join(input_dir, 'translated')

    os.makedirs(translated_dir, exist_ok=True)

    # Translation process
    if translator_enabled:
        print("Translation is enabled.")

    # Colorization process
    if colorizer_enabled:
        print("Colorization is enabled.")
        threading.Thread(target=run_colorization, args=(session_id,)).start()

    return jsonify({"status": "processing_started"})


@app.route('/uploads/<session_id>/<path:filename>', methods=['GET'])
def serve_uploaded_files(session_id, filename):
    return send_from_directory(os.path.join(UPLOADS_DIR, session_id), filename)

if __name__ == '__main__':
    app.run(port=6000)
