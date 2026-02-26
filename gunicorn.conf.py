# Gunicorn config so timeout applies even when Render uses a custom start command
# (Procfile may be overridden in Render dashboard)
timeout = 300
workers = 1
