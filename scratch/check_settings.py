from database import Database, SystemSetting

db = Database('sqlite:///wordpress_bot.db')
with db.get_session() as session:
    settings = session.query(SystemSetting).all()
    print("Database Settings:")
    for s in settings:
        print(f"{s.key}: {s.value}")
