# SimToC — Simulink to C Code Converter

Upload .slx, .mdl, .pdf, or image files and get clean C code output instantly.

## Local Setup (Mac)
```bash
cd backend
source venv/bin/activate
python app.py
```
Then open frontend/index.html in Chrome.
```

---

### `backend/requirements.txt`
```
flask
flask-cors
pymupdf
opencv-python-headless
pytesseract
pillow
lxml
numpy
python-dotenv
gunicorn
```

---

### `backend/Procfile`
```
web: gunicorn app:app