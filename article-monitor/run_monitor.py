from monitor.app import app, start_scheduler
from monitor.config import FLASK_HOST, FLASK_PORT, FLASK_DEBUG

if __name__ == '__main__':
    print("Starting Article Monitor...")
    # Start the scheduler
    start_scheduler()
    
    # Start Flask app
    print(f"Starting Flask on {FLASK_HOST}:{FLASK_PORT} (Debug: {FLASK_DEBUG})")
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG)

