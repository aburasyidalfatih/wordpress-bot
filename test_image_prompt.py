from app import app
from core_extensions import db
from database import WordPressSite

with app.app_context():
    with db.get_session() as s:
        site = s.query(WordPressSite).filter_by(id=4).first()
        print('===PROMPT===')
        print(site.image_prompt)
        print('===END===')
