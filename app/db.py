import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

# 1. Load environment variables
load_dotenv()

# 2. Read DATABASE_URL
DATABASE_URL = os.getenv("DATABASE_URL")

# 3. Create engine
engine = create_engine(DATABASE_URL)

# 4. Create Base class for models
Base = declarative_base()

# 5. Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 6. Dependency for FastAPI routes
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
