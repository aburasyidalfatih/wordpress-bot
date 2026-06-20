from database import Database, User, Config as DBConfig
from werkzeug.security import generate_password_hash

db = Database('sqlite:///wordpress_bot.db')
with db.get_session() as session:
    existing = session.query(User).filter_by(email='admin@kelasmaster.id').first()
    if not existing:
        user = User(
            email='admin@kelasmaster.id',
            name='Admin',
            password_hash=generate_password_hash('admin123'),
            role='admin',
            tier='free',
            credits=5,
            is_active=True
        )
        session.add(user)
        session.commit()
        
        cfg = DBConfig(user_id=user.id, gemini_api_key='', gemini_model='gemini-2.5-flash')
        session.add(cfg)
        session.commit()
        print('Admin user created successfully!')
    else:
        print('Admin already exists.')
