"""One-shot database migration entrypoint used by Docker Compose."""
from config import Config
from database import Database


if __name__ == '__main__':
    Database(Config.DATABASE_URL).run_migrations()
