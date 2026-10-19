"""تصدير النماذج لتسجيلها في SQLAlchemy metadata"""
from app.models.lecture import (  # noqa: F401
    User,
    Lecture,
    Job,
    Transcript,
    Summary,
    GlossaryItem,
    Quiz,
    Topic,
    TopicResource,
)
