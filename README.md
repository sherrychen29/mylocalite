# MyLocalite

Discover and support local businesses. Find cafés, shops, and services near you—save favourites, read reviews, and grab deals.

## Features

- **Discover** — Browse businesses by category (Food, Retail, Services), search by name, and sort (random, name, rating).
- **Bookmarks** — Save favourite businesses (session-based; no account required).
- **Reviews** — Leave star ratings and comments. Optional verification (Q&A) to confirm you visited.
- **Deals** — View active deals and coupon codes per business.
- **Photos** — Upload and view photos per business; landing page uses them in a background gallery.
- **Add business** — Anyone can add a new listing from the header.

## Tech stack

- **Backend:** Flask (Python)
- **Database:** SQLite (WAL mode)
- **Frontend:** Jinja2 templates, vanilla CSS, no JS framework

## Setup

1. Clone the repo and create a virtual environment (recommended):

   ```bash
   python3 -m venv venv
   source venv/bin/activate   # Windows: venv\Scripts\activate
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Run the app:

   ```bash
   python app.py
   ```

   Then open http://127.0.0.1:5000/ in your browser.

## Project layout

- `app.py` — Flask app, routes, and DB logic
- `data/` — SQLite database (`locallift.db` is created on first run)
- `static/` — CSS, media (icons, logo), and `uploads/` for business photos
- `templates/` — Jinja2 HTML (base, landing, discover, business detail, bookmarks)

## Configuration

- **Secret key** — Set `app.secret_key` in `app.py` for production (used for session).
- **Database** — Path is `data/locallift.db`; change `DB_PATH` in `app.py` if needed.
- **Uploads** — Business photos go to `static/uploads/`; max 8 MB per upload.

## License

Use as you like for learning or projects.
