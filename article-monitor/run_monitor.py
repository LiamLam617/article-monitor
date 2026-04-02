import logging

from monitor.app import app, start_scheduler
from monitor.config import FLASK_HOST, FLASK_PORT, FLASK_DEBUG
from monitor.logging_config import setup_logging

setup_logging(force=True)
logger = logging.getLogger(__name__)

if __name__ == '__main__':
    logger.info("Starting Article Monitor...")
    # Start the scheduler
    start_scheduler()
    
    # Start Flask app
    logger.info("Starting Flask on %s:%s (Debug: %s)", FLASK_HOST, FLASK_PORT, FLASK_DEBUG)
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG)

