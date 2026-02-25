# How to Deploy GreenLake Device Management

This app is a **Flask backend** (Python) that serves **HTML/JS frontends** and exposes APIs at `http://localhost:5000/api`. Below are ways to run and deploy it.

---

## 1. Quick run (local, Windows)

**Option A – Double-click**
- Run **`start.bat`**. It will:
  - Activate the `.venv` virtual environment
  - Install dependencies from `requirements.txt`
  - Start the server on **port 5000**

**Option B – Command line**
```bat
cd path\to\GreenLake
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Then open in a browser:
- **Device Management:** http://localhost:5000/DeviceManagement.html  
- **Home / Tools:** http://localhost:5000/  
- **Subscription Management:** http://localhost:5000/SubscriptionManagement.html  

---

## 2. Prerequisites

- **Python 3.10+** (recommended)
- Create a virtual environment if you don’t have one:
  ```bat
  python -m venv .venv
  .venv\Scripts\activate
  pip install -r requirements.txt
  ```

---

## 3. Production-style deployment (same machine / server)

For a more stable, production-like run on one machine:

**Install Gunicorn (Unix/Linux/WSL) or Waitress (Windows):**

- **Windows:** add to `requirements.txt` and install:
  ```text
  waitress>=3.0.0
  ```
  Then run the app with Waitress:
  ```bat
  .venv\Scripts\activate
  pip install -r requirements.txt
  waitress-serve --port=5000 main:app
  ```

- **Linux / WSL / macOS:** add to `requirements.txt`:
  ```text
  gunicorn>=21.0.0
  ```
  Run:
  ```bash
  source .venv/bin/activate
  pip install -r requirements.txt
  gunicorn -w 4 -b 0.0.0.0:5000 main:app
  ```
  `-w 4` = 4 worker processes; `-b 0.0.0.0:5000` = listen on all interfaces on port 5000.

**Important:** The frontend in `DeviceManagement.html` uses **`API_BASE = 'http://localhost:5000/api'`**. If users will open the site by **hostname or IP** (e.g. `http://myserver:5000/DeviceManagement.html`), the browser will still call `localhost` for the API and it will fail. In that case you must either:

- Serve the app so that the same origin is used (e.g. open as `http://myserver:5000/DeviceManagement.html` and change `API_BASE` to that origin), or  
- Set `API_BASE` dynamically (e.g. same host and port as the page).

---

## 4. Deploying to a cloud/server (e.g. single VM)

1. Copy the whole **GreenLake** folder (including `main.py`, `deviceApp.py`, `subscriptionApp.py`, `requirements.txt`, all `.html` files, and optionally `.venv` or recreate `.venv` on the server).
2. On the server:
   - Install Python 3.10+, create and activate a venv, then:
     ```bash
     pip install -r requirements.txt
     ```
   - Run with Gunicorn (Linux) or Waitress (Windows) as in **§3**.
3. Open the required **firewall port** (e.g. 5000) if you want access from other machines.
4. For production, put a **reverse proxy** (e.g. Nginx or IIS) in front of the app and use **HTTPS**; optionally change the app to listen only on `127.0.0.1` and let the proxy handle the public port.

---

## 5. Deploy for free (cloud)

All of these have a **free tier** suitable for a small Flask app. Your app calls HPE APIs from the server, so the backend must be able to make outbound HTTPS requests (all of these can).

### Option A: Render (recommended, simple)

1. Push your code to **GitHub** (create a repo and push the GreenLake folder).
2. Sign up at [render.com](https://render.com) (free).
3. **New → Web Service**, connect your repo.
4. Settings:
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `gunicorn main:app` (add `gunicorn>=21.0.0` to `requirements.txt`)
   - **Environment:** add `PORT` if needed; Render sets it. In `main.py` you can use:  
     `port = int(os.environ.get('PORT', 5000))` and `app.run(host='0.0.0.0', port=port)` for local; for Render, use **Start command** `gunicorn -b 0.0.0.0:$PORT main:app`.
5. Deploy. You’ll get a URL like `https://your-app.onrender.com`.
6. **Important:** In `DeviceManagement.html` (and any other HTML that calls the API), set the API base from the current page so it works on any host:
   ```javascript
   const API_BASE = (window.location.origin || 'http://localhost:5000') + '/api';
   ```
   Then the same code works locally and on Render.

Free tier: service may sleep after inactivity; first request can be slow.

---

### Option B: PythonAnywhere

1. Sign up at [pythonanywhere.com](https://www.pythonanywhere.com) (free account).
2. Open a **Bash** console.
3. Clone your repo or upload your GreenLake project files.
4. Create a virtualenv and install deps:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt gunicorn
   ```
5. **Web** tab → **Add a new web app** → **Manual configuration** → **Python 3.x**.
6. Set **Source code** and **WSGI configuration file** to point to your app (e.g. `/home/yourusername/GreenLake` and a `wsgi.py` that imports `app` from `main`).
7. In the WSGI file, load your app, e.g.:
   ```python
   import sys
   path = '/home/yourusername/GreenLake'
   if path not in sys.path:
       sys.path.append(path)
   from main import app
   application = app
   ```
8. Reload the web app. Your site will be `https://yourusername.pythonanywhere.com`.
9. Set **`API_BASE`** in the HTML to use the same origin (e.g. the dynamic line above) so the frontend calls your PythonAnywhere URL.

Free tier: one web app, subdomain only, no long-running processes 24/7.

---

### Option C: Fly.io

1. Install [flyctl](https://fly.io/docs/hands-on/install-flyctl/) and sign up.
2. In your project folder run `fly launch`, follow prompts (choose a region, don’t add a DB).
3. Fly will generate a `Dockerfile` or use a buildpack. For Flask, you can use a simple **Dockerfile**:
   ```dockerfile
   FROM python:3.11-slim
   WORKDIR /app
   COPY requirements.txt .
   RUN pip install --no-cache-dir -r requirements.txt gunicorn
   COPY . .
   CMD ["gunicorn", "-b", "0.0.0.0:8080", "main:app"]
   ```
   And in `fly.toml` set `internal_port = 8080`.
4. `fly deploy`. You’ll get `https://your-app.fly.dev`.
5. Set **`API_BASE`** in the HTML to the same origin (dynamic line above).

Free tier: limited resources; good for low-traffic apps.

---

### Option D: Run on your own PC (always free)

- Use **`start.bat`** or `python main.py` and open **http://localhost:5000/DeviceManagement.html**.
- To allow others on your network to access it, run with `app.run(host='0.0.0.0', port=5000)` (and use the dynamic `API_BASE` in the HTML), then share your PC’s local IP (e.g. `http://192.168.1.10:5000/DeviceManagement.html`). No cloud cost.

---

### Make API_BASE work everywhere (local + free cloud)

In **DeviceManagement.html** (around line 968), replace the fixed URL with:

```javascript
const API_BASE = (window.location.origin || 'http://localhost:5000') + '/api';
```

Do the same in **SubscriptionManagement.html** if it calls the API. Then the app works locally and on any host (Render, PythonAnywhere, Fly.io, your PC’s IP) without changing code.

---

## 6. Summary

| Goal                    | Action                                                                 |
|-------------------------|------------------------------------------------------------------------|
| Run locally (Windows)   | Use **`start.bat`** or `python main.py` after activating `.venv`.     |
| Run on server (Windows) | Use **Waitress**: `waitress-serve --port=5000 main:app`.              |
| Run on server (Linux)   | Use **Gunicorn**: `gunicorn -w 4 -b 0.0.0.0:5000 main:app`.           |
| **Deploy for free**     | **§5**: Render, PythonAnywhere, Fly.io, or your own PC. Use dynamic **`API_BASE`** (same section). |
| Access by hostname/IP   | Set **`API_BASE`** from `window.location.origin` so it works on any URL. |

After deployment, open **http://&lt;your-host&gt;:5000/DeviceManagement.html** (or the URL you configured) to use the app.
