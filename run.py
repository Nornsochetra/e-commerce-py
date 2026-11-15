"""Local development server: python run.py  →  http://127.0.0.1:8000"""
import os

from app import create_app, init_database

app = create_app()

if __name__ == "__main__":
    init_database(app)  # creates tables, the admin account and sample products on first run
    app.run(debug=True, port=int(os.environ.get("PORT", 8000)))
