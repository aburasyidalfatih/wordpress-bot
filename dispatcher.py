import time
import os
import logging
from datetime import datetime
from redis import Redis
from rq import Queue
from database import Database, WordPressSite, User
from app import generate_and_post, deep_research_job

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('dispatcher')

# Init Redis and Queue
redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
redis_conn = Redis.from_url(redis_url, protocol=2)
q = Queue('default', connection=redis_conn)

# Init DB - align default with app.py fallback to SQLite
db_url = os.getenv('DATABASE_URL', 'sqlite:///wordpress_bot.db')
db = Database(db_url)

def dispatch_jobs():
    logger.info("Running central dispatcher...")
    with db.get_session() as session:
        # Get all active WordPress sites
        sites = session.query(WordPressSite).filter_by(is_active=True).all()
        
        current_hour = datetime.now().hour
        
        for site in sites:
            user_id = site.user_id
            site_id = site.id
            
            # Check auto post
            if site.auto_post and site.selected_categories:
                schedule_hours = site.schedule_hours or '0,6,12,18'
                try:
                    hours_list = [int(h.strip()) for h in schedule_hours.split(',') if h.strip().isdigit()]
                    if current_hour in hours_list:
                        logger.info(f"Enqueueing generate_and_post for user_id={user_id}, site_id={site_id} (hour={current_hour})")
                        q.enqueue(generate_and_post, user_id, None, site_id)
                except Exception as e:
                    logger.error(f"Error parsing schedule for site_id={site_id}: {e}")
            
            # Check auto research (runs daily at 00:00)
            if site.auto_research_enabled:
                if current_hour == 0:
                    logger.info(f"Enqueueing deep_research_job for user_id={user_id}, site_id={site_id} (hour={current_hour})")
                    q.enqueue(deep_research_job, user_id, True, site_id)

if __name__ == '__main__':
    logger.info("Dispatcher started.")
    last_run_hour = -1
    
    while True:
        now = datetime.now()
        # Run only once per hour, at the 0th minute (top of the hour)
        if now.minute == 0 and now.hour != last_run_hour:
            dispatch_jobs()
            last_run_hour = now.hour
        
        # Sleep for a minute before checking again
        time.sleep(60)
