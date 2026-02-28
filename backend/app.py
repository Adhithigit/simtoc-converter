from flask import Flask, request, jsonify
from flask_cors import CORS
import os

app = Flask(__name__)
CORS(app, origins=["*"])

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

from parsers.slx_parser import parse_slx
from parsers.mdl_parser import parse_mdl
from parsers.pdf_parser import parse_pdf
from parsers.image_parser import parse_image
from converter.c_code_generator import generate_c_code

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'running', 'message': 'SimToC backend is live!'})

@app.route('/convert', methods=['POST'])
def convert():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['file']
    filename = file.filename

    if not filename:
        return jsonify({'error': 'Empty filename'}), 400

    ext = filename.rsplit('.', 1)[-1].lower()
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)

    try:
        if ext == 'slx':
            blocks, connections = parse_slx(filepath)
        elif ext == 'mdl':
            blocks, connections = parse_mdl(filepath)
        elif ext == 'pdf':
            blocks, connections = parse_pdf(filepath)
        elif ext in ['png', 'jpg', 'jpeg', 'bmp']:
            blocks, connections = parse_image(filepath)
        else:
            return jsonify({'error': f'Unsupported file type: .{ext}'}), 400

        c_code = generate_c_code(blocks, connections)

        diagram_data = {
            'blocks': [
                {
                    'id': str(b['id']),
                    'type': b['type'],
                    'name': b['name'],
                    'x': float(b.get('x', 0)),
                    'y': float(b.get('y', 0))
                }
                for b in blocks
            ],
            'connections': [
                {'from': str(c.get('from', '')), 'to': str(c.get('to', ''))}
                for c in connections
            ]
        }

        return jsonify({
            'success': True,
            'c_code': c_code,
            'diagram': diagram_data,
            'block_count': len(blocks),
            'connection_count': len(connections)
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

    finally:
        if os.path.exists(filepath):
            os.remove(filepath)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=False, host='0.0.0.0', port=8080)