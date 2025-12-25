from sqlalchemy import Column, String, DateTime, Text, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid
import enum

from ..db import Base


class RecordingStatus(str, enum.Enum):
    ACTIVE = "active"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class Recording(Base):
    __tablename__ = "recordings"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    egress_id = Column(String(255), unique=True, nullable=False, index=True)
    room_name = Column(String(255), nullable=False, index=True)
    matrix_room_id = Column(String(255), nullable=True, index=True)

    file_path = Column(Text, nullable=True)  # Legacy field, kept for compatibility
    file_url = Column(Text, nullable=True)
    file_size = Column(String(50), nullable=True)
    duration = Column(String(50), nullable=True)
    
    # S3/MinIO metadata
    bucket = Column(String(255), nullable=True, index=True)  # S3 bucket name
    object_key = Column(Text, nullable=True)  # S3 object key (path in bucket)

    started_by = Column(String(255), nullable=True)
    stopped_by = Column(String(255), nullable=True)
    status = Column(SQLEnum(RecordingStatus), default=RecordingStatus.ACTIVE, nullable=False)

    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    stopped_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    

    context = Column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<Recording(id={self.id}, egress_id={self.egress_id}, status={self.status})>"


