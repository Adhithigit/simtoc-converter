# SimToC — Offline Setup Guide

Run SimToC **completely offline** on any Mac, Windows, or Linux computer.

---

## What You Need (One-Time Setup)

| Requirement | Mac | Windows | Linux |
|-------------|-----|---------|-------|
| Python 3.8+ | `brew install python` | [python.org](https://python.org/downloads) | `sudo apt install python3` |
| Tesseract | `brew install tesseract` | [GitHub releases](https://github.com/UB-Mannheim/tesseract/wiki) | `sudo apt install tesseract-ocr` |
| Git | Already installed | [git-scm.com](https://git-scm.com) | `sudo apt install git` |

---

## Step 1 — Get the Code

```bash
git clone https://github.com/Adhithigit/simtoc-converter.git
cd simtoc-converter
```

Or just download the ZIP from GitHub and unzip it.

---

## Step 2 — Run Offline

### Mac / Linux
```bash
bash run_local.sh
```
That's it! The browser opens automatically.

### Windows
Double-click `run_local.bat`

---

## What the Script Does Automatically

1. Creates a Python virtual environment
2. Installs all Python packages from `requirements.txt`
3. Changes the frontend API URL from the Render server to `localhost:8080`
4. Starts the Flask backend on port 8080
5. Opens `frontend/index.html` in your browser
6. When you press Ctrl+C — stops the backend and restores the online URL

---

## Manual Setup (if script doesn't work)

```bash
# 1. Go to project folder
cd simtoc-converter

# 2. Create and activate virtual environment
python3 -m venv backend/venv
source backend/venv/bin/activate        # Mac/Linux
# backend\venv\Scripts\activate         # Windows

# 3. Install dependencies
cd backend
pip install -r requirements.txt
cd ..

# 4. Change API URL in frontend/script.js
# Open frontend/script.js and change line 2 to:
# const API = 'http://localhost:8080';

# 5. Start backend
cd backend
python app.py

# 6. Open frontend in browser
# Open frontend/index.html in Chrome/Firefox
```

---

## Sharing with Others (Offline)

To give SimToC to someone else to run offline:

1. Zip the entire `simtoc-converter` folder
2. Share the zip file
3. They unzip it and run `run_local.sh` (Mac/Linux) or `run_local.bat` (Windows)
4. They need Python installed — that's the only requirement

**The zip will work on any computer that has Python 3!**

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Port 8080 in use | The script kills it automatically. Or change port in `app.py` last line |
| `pip install` fails | Run `pip install --break-system-packages -r requirements.txt` |
| "Backend Offline" in browser | Wait 3 seconds and refresh. Or check terminal for errors |
| Tesseract not found (image uploads) | Install tesseract via Homebrew (Mac) or from GitHub (Windows) |
| Windows: script doesn't open browser | Manually open `frontend/index.html` in Chrome |

---

## File Structure

```
simtoc-converter/
├── run_local.sh          ← Mac/Linux: double-click or bash run_local.sh
├── run_local.bat         ← Windows: double-click
├── backend/
│   ├── app.py            ← Flask server
│   ├── requirements.txt  ← Python packages
│   ├── parsers/          ← SLX, MDL, PDF, Image parsers
│   └── converter/        ← C code generator
└── frontend/
    ├── index.html        ← Open this in browser
    ├── style.css
    └── script.js         ← API URL is auto-swapped by the script
```