"""
نماذج قاعدة البيانات - طربوش
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    lectures = relationship("Lecture", back_populates="user")

class Lecture(Base):
    __tablename__ = "lectures"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    title = Column(String, index=True)
    original_filename = Column(String)
    file_path = Column(String)
    file_hash = Column(String, index=True)  # لمنع التكرار
    file_size = Column(Integer)
    mime_type = Column(String)
    duration_seconds = Column(Integer, default=0)
    
    status = Column(String, default="queued")  # queued, preprocessing, transcribing, summarizing, done, failed
    progress = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    user = relationship("User", back_populates="lectures")
    transcript = relationship("Transcript", back_populates="lecture", uselist=False, cascade="all, delete-orphan")
    summaries = relationship("Summary", back_populates="lecture", cascade="all, delete-orphan")
    glossary_items = relationship("GlossaryItem", back_populates="lecture", cascade="all, delete-orphan")
    quiz = relationship("Quiz", back_populates="lecture", uselist=False, cascade="all, delete-orphan")
    jobs = relationship("Job", back_populates="lecture", cascade="all, delete-orphan")
    topics = relationship(
        "Topic",
        back_populates="lecture",
        cascade="all, delete-orphan",
        order_by="Topic.order_index",
    )

class Job(Base):
    __tablename__ = "jobs"
    id = Column(Integer, primary_key=True, index=True)
    lecture_id = Column(Integer, ForeignKey("lectures.id"))
    task_type = Column(String)  # transcribe, summarize, quiz, export
    status = Column(String, default="pending")  # pending, running, done, failed
    progress = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    trace_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    lecture = relationship("Lecture", back_populates="jobs")

class Transcript(Base):
    __tablename__ = "transcripts"
    id = Column(Integer, primary_key=True, index=True)
    lecture_id = Column(Integer, ForeignKey("lectures.id"), unique=True)
    full_text = Column(Text)
    segments = Column(JSON)  # [{"start": 0.0, "end": 5.2, "text": "..."}]
    language = Column(String, default="ar")
    word_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    lecture = relationship("Lecture", back_populates="transcript")

class Summary(Base):
    __tablename__ = "summaries"
    id = Column(Integer, primary_key=True, index=True)
    lecture_id = Column(Integer, ForeignKey("lectures.id"))
    level = Column(String)  # glimpse, bullets, page, detailed
    title = Column(String)
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    lecture = relationship("Lecture", back_populates="summaries")

class GlossaryItem(Base):
    __tablename__ = "glossary_items"
    id = Column(Integer, primary_key=True, index=True)
    lecture_id = Column(Integer, ForeignKey("lectures.id"))
    term_ar = Column(String)
    term_en = Column(String, nullable=True)
    definition = Column(Text)
    
    lecture = relationship("Lecture", back_populates="glossary_items")

class Quiz(Base):
    __tablename__ = "quizzes"
    id = Column(Integer, primary_key=True, index=True)
    lecture_id = Column(Integer, ForeignKey("lectures.id"), unique=True)
    questions = Column(JSON)  # [{"question": "...", "options": [...], "answer": 0, "explanation": "..."}]
    created_at = Column(DateTime, default=datetime.utcnow)
    
    lecture = relationship("Lecture", back_populates="quiz")


class Topic(Base):
    """موضوع مستخرج من المحاضرة (تقسيم دلالي/استخراجي)"""
    __tablename__ = "topics"

    id = Column(Integer, primary_key=True, index=True)
    lecture_id = Column(Integer, ForeignKey("lectures.id"), index=True)
    order_index = Column(Integer, default=0)
    title = Column(String, default="")
    excerpt = Column(Text, default="")
    key_terms = Column(JSON, default=list)
    start_seconds = Column(Integer, default=0)
    end_seconds = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    lecture = relationship("Lecture", back_populates="topics")
    resources = relationship(
        "TopicResource",
        back_populates="topic",
        cascade="all, delete-orphan",
        order_by="TopicResource.rank",
    )


class TopicResource(Base):
    """مصدر تعليمي خارجي مرتبط بموضوع (يوتيوب/ويكيبيديا/ويكي الجامعة/arXiv)"""
    __tablename__ = "topic_resources"

    id = Column(Integer, primary_key=True, index=True)
    topic_id = Column(Integer, ForeignKey("topics.id"), index=True)
    lecture_id = Column(Integer, ForeignKey("lectures.id"), index=True)
    provider = Column(String, default="youtube")
    title = Column(String, default="")
    url = Column(String, default="")
    snippet = Column(Text, default="")
    thumbnail = Column(String, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    channel = Column(String, nullable=True)
    query_used = Column(String, nullable=True)
    lang = Column(String, default="ar")
    rank = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    topic = relationship("Topic", back_populates="resources")
