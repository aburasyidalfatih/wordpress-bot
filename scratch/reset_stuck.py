from core_extensions import db
from database import ContentQueue
session = db.Session()
stuck_items = session.query(ContentQueue).filter_by(status='posting').all()
for item in stuck_items:
    item.status = 'pending'
session.commit()
print(f'Reset {len(stuck_items)} stuck items to pending.')
