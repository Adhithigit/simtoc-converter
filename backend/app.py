from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import traceback

app = Flask(__name__)

# Fix CORS — allow ALL origins explicitly
CORS(app, resources={
    r"/*": {
        "origins": "*",
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization", "Accept"]
    }
})

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


@app.after_request
def add_cors_headers(response):
    """Add CORS headers to every response — belt and suspenders approach."""
    response.headers['Access-Control-Allow-Origin']  = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, Accept'
    return response


@app.route('/health', methods=['GET', 'OPTIONS'])
def health():
    return jsonify({'status': 'running', 'message': 'SimToC backend is live!'})


@app.route('/convert', methods=['POST', 'OPTIONS'])
def convert():
    # Handle preflight OPTIONS request
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200

    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file     = request.files['file']
    filename = file.filename

    if not filename:
        return jsonify({'error': 'Empty filename'}), 400

    ext      = filename.rsplit('.', 1)[-1].lower()
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)

    try:
        sim_dt   = 0.1
        sim_stop = 10.0

        if ext == 'slx':
            from parsers.slx_parser import parse_slx
            result = parse_slx(filepath)
            if len(result) == 4:
                blocks, connections, sim_dt, sim_stop = result
            else:
                blocks, connections = result

        elif ext == 'mdl':
            from parsers.mdl_parser import parse_mdl
            result = parse_mdl(filepath)
            if len(result) == 4:
                blocks, connections, sim_dt, sim_stop = result
            else:
                blocks, connections = result

        elif ext == 'pdf':
            from parsers.pdf_parser import parse_pdf
            result = parse_pdf(filepath)
            if len(result) == 4:
                blocks, connections, sim_dt, sim_stop = result
            else:
                blocks, connections = result

        elif ext in ['png', 'jpg', 'jpeg', 'bmp']:
            from parsers.image_parser import parse_image
            result = parse_image(filepath)
            if len(result) == 4:
                blocks, connections, sim_dt, sim_stop = result
            else:
                blocks, connections = result

        else:
            return jsonify({'error': f'Unsupported file type: .{ext}'}), 400

        from converter.c_code_generator import generate_c_code
        c_code = generate_c_code(
            blocks, connections,
            sim_dt=sim_dt, sim_stop=sim_stop
        )

        return jsonify({
            'success':          True,
            'c_code':           c_code,
            'blocks': [
                {
                    'id':   str(b['id']),
                    'type': b['type'],
                    'name': b['name'],
                    'x':    float(b.get('x', 0)),
                    'y':    float(b.get('y', 0))
                }
                for b in blocks
            ],
            'connections': [
                {
                    'from': str(c.get('from', '')),
                    'to':   str(c.get('to',   ''))
                }
                for c in connections
            ],
            'block_count':      len(blocks),
            'connection_count': len(connections)
        })

    except Exception as e:
        return jsonify({
            'error': str(e),
            'trace': traceback.format_exc()
        }), 500

    finally:
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except:
            pass


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=False, host='0.0.0.0', port=port)