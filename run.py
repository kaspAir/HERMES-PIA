from app.factory import create_app

app = create_app()

if __name__ == "__main__":
    import os
    # reloader_type='stat' statt 'watchdog': verhindert Endlos-Neustarts
    # durch SQLAlchemy-/Flask-Dateiaenderungen in site-packages (Windows).
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)),
            debug=True, reloader_type="stat")
