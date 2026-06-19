import time
import os
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from redis import Redis
from rq import Queue
from database import Database, WordPressSite, User

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
    wib = ZoneInfo("Asia/Jakarta")
    with db.get_session() as session:
        # Get all active WordPress sites
        sites = session.query(WordPressSite).filter_by(is_active=True).all()
        
        current_hour = datetime.now(wib).hour
        
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
                        q.enqueue('app.generate_and_post', user_id, None, site_id)
                except Exception as e:
                    logger.error(f"Error parsing schedule for site_id={site_id}: {e}")
            
            # Check auto research (runs daily at 00:00)
            if site.auto_research_enabled:
                if current_hour == 0:
                    try:
                        logger.info(f"Enqueueing deep_research_job for user_id={user_id}, site_id={site_id} (hour={current_hour})")
                        q.enqueue('app.deep_research_job', user_id, True, site_id)
                    except Exception as e:
                        logger.error(f"Error enqueuing deep_research_job for site_id={site_id}: {e}")

if __name__ == '__main__':
    logger.info("Dispatcher started.")
    
    # Target timezone is Asia/Jakarta (WIB)
    wib = ZoneInfo("Asia/Jakarta")
    
    while True:
        try:
            now = datetime.now(wib)
            current_hour_str = now.strftime("%Y-%m-%d %H")
            
            # Check Redis for the last run hour to prevent missed/double runs on restarts
            last_run = redis_conn.get("scheduler:last_run")
            if last_run:
                last_run = last_run.decode('utf-8')
            
            # If the current hour is different from the last run hour, execute jobs
            if last_run != current_hour_str:
                dispatch_jobs()
                redis_conn.set("scheduler:last_run", current_hour_str)
                
        except Exception as e:
            logger.error(f"Error in scheduler loop: {e}")
            
        # Check every 10 seconds to ensure high precision without CPU overhead
        time.sleep(10)
