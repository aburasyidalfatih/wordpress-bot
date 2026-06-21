import time
import os
import logging
import random
from datetime import datetime, timedelta
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

from sqlalchemy.orm import joinedload # Removing this later

def dispatch_jobs():
    with db.get_session() as session:
        # Get all active WordPress sites
        sites = session.query(WordPressSite).filter_by(is_active=True).all()
        
        # Batch load users to prevent N+1 queries
        user_ids = list(set([site.user_id for site in sites]))
        users = session.query(User).filter(User.id.in_(user_ids)).all()
        users_dict = {user.id: user for user in users}
        
        for site in sites:
            user_id = site.user_id
            site_id = site.id
            user = users_dict.get(user_id)
            
            # Check user credits
            if not user or (user.credits or 0) <= 0:
                # Log only once every hour to avoid spamming the log
                lock_key_log = f"scheduler:log_credit_warning:{site_id}"
                has_logged = redis_conn.get(lock_key_log)
                if not has_logged:
                    logger.info(f"Skipping auto-post for site_id={site_id}: user_id={user_id} has insufficient credits.")
                    redis_conn.setex(lock_key_log, 3600, "1")
                continue
            
            tz_name = site.timezone or 'Asia/Jakarta'
            try:
                tz = ZoneInfo(tz_name)
            except Exception as e:
                logger.error(f"Invalid timezone '{tz_name}' for site_id={site_id}, falling back to Asia/Jakarta: {e}")
                tz = ZoneInfo('Asia/Jakarta')
            
            now_site = datetime.now(tz)
            current_hour = now_site.hour
            current_hour_str = now_site.strftime("%Y-%m-%d %H")
            
            # 1. Check auto post
            if site.auto_post and site.selected_categories:
                schedule_hours = site.schedule_hours or '0,6,12,18'
                try:
                    hours_list = [int(h.strip()) for h in schedule_hours.split(',') if h.strip().isdigit()]
                    if current_hour in hours_list:
                        lock_key = f"scheduler:last_run_post:{site_id}"
                        last_run = redis_conn.get(lock_key)
                        if last_run:
                            last_run = last_run.decode('utf-8')
                        
                        if last_run != current_hour_str:
                            delay_minutes = random.randint(0, 50)
                            
                            # Check if there is a pending item in ContentQueue (pick top/newest)
                            from database import ContentQueue
                            queue_item = session.query(ContentQueue).filter_by(
                                user_id=user_id, 
                                site_id=site_id, 
                                status='pending'
                            ).order_by(ContentQueue.created_at.asc()).first()
                            
                            item_id = None
                            if queue_item:
                                item_id = queue_item.id
                                queue_item.status = 'posting' # Mark as posting to prevent duplicate pickup
                                session.commit()
                            
                            logger.info(f"Enqueueing generate_and_post for user_id={user_id}, site_id={site_id}, item_id={item_id} (delayed by {delay_minutes}m, hour={current_hour} in {tz_name})")
                            q.enqueue_in(timedelta(minutes=delay_minutes), 'app.generate_and_post', user_id, item_id, site_id)
                            redis_conn.set(lock_key, current_hour_str)
                except Exception as e:
                    logger.error(f"Error checking auto post schedule for site_id={site_id}: {e}")
            
            # Auto research scheduler check removed since manual research is used instead.

if __name__ == '__main__':
    logger.info("Dispatcher started.")
    
    while True:
        try:
            dispatch_jobs()
        except Exception as e:
            logger.error(f"Error in scheduler main loop: {e}")
            
        # Check every 10 seconds to ensure high precision without CPU overhead
        time.sleep(10)
