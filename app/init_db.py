from app.db import Base, engine
from app.models.trend import Trend                    # noqa: F401
from app.models.persona import Persona                # noqa: F401
from app.models.trendpersona import TrendPersona      # noqa: F401
from app.models.cluster import Cluster                # noqa: F401
from app.models.user_profile import UserProfile       # noqa: F401
from app.models.generated_content import GeneratedContent  # noqa: F401
from app.models.trend_theme import TrendTheme               # noqa: F401
from app.models.trend_occurrence import TrendOccurrence     # noqa: F401
from app.models.high_velocity_alert import HighVelocityAlert  # noqa: F401

print("Creating tables...")
Base.metadata.create_all(bind=engine)
print("Done.")
