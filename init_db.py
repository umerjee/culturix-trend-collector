from app.db import Base, engine
from app.models.trend import Trend

print("Creating tables...")
Base.metadata.create_all(bind=engine)
print("Done.")
