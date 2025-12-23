"""Recording service for business logic"""
import logging
from typing import Optional, Callable, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
import json

from ..server.models.recording import Recording, RecordingStatus
from ..server.repositories.recordings_repository import RecordingsRepository
from ..integrations.livekit_client import LiveKitClient

logger = logging.getLogger(__name__)


class RecordingService:
    """Service for managing recordings"""
    
    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
        livekit_client: LiveKitClient,
    ):
        self.session_factory = session_factory
        self.livekit_client = livekit_client
        
    async def start_recording(
        self,
        room_name: str,
        matrix_room_id: Optional[str] = None,
        started_by: Optional[str] = None,
    ) -> Recording:
        """
        Start a new recording
        
        Args:
            room_name: LiveKit room name
            matrix_room_id: Matrix room ID (optional)
            started_by: User who started recording (optional)
            
        Returns:
            Created Recording object
        """
        # Start recording in LiveKit
        result = await self.livekit_client.start_recording(room_name=room_name)
        egress_id = result["egress_id"]
        
        # Create recording record in database
        async with self.session_factory() as session:
            repository = RecordingsRepository(session)
            recording_data = {
                "egress_id": egress_id,
                "room_name": room_name,
                "matrix_room_id": matrix_room_id,
                "started_by": started_by,
                "status": RecordingStatus.ACTIVE,
                "started_at": datetime.utcnow(),
            }
            recording = await repository.create(recording_data)
            await session.commit()
            logger.info(f"Recording started: {egress_id}")
            return recording
    
    async def stop_recording(self, egress_id: str) -> Optional[Recording]:
        """
        Stop an active recording
        
        Args:
            egress_id: LiveKit egress ID
            
        Returns:
            Updated Recording object or None
        """
        # Stop recording in LiveKit
        await self.livekit_client.stop_recording(egress_id=egress_id)
        
        # Update recording status in database
        async with self.session_factory() as session:
            repository = RecordingsRepository(session)
            recording = await repository.update_by_egress_id(
                egress_id,
                {
                    "status": RecordingStatus.STOPPED,
                    "stopped_at": datetime.utcnow(),
                }
            )
            await session.commit()
            logger.info(f"Recording stopped: {egress_id}")
            return recording
    
    async def handle_webhook_event(
        self,
        event_type: str,
        egress_info: Dict[str, Any]
    ) -> Optional[Recording]:
        """
        Handle webhook event from LiveKit
        
        Args:
            event_type: Event type (egress_started, egress_updated, egress_ended)
            egress_info: Egress information from webhook
            
        Returns:
            Updated Recording object or None
        """
        egress_id = egress_info.get("egress_id")
        if not egress_id:
            logger.warning("No egress_id in webhook payload")
            return None
        
        async with self.session_factory() as session:
            repository = RecordingsRepository(session)
            
            if event_type == "egress_started":
                # Check if recording exists
                recording = await repository.get_by_egress_id(egress_id)
                if not recording:
                    # Create if doesn't exist
                    recording = await repository.create({
                        "egress_id": egress_id,
                        "room_name": egress_info.get("room_name", "unknown"),
                        "status": RecordingStatus.ACTIVE,
                        "started_at": datetime.utcnow(),
                    })
                else:
                    # Update status
                    recording = await repository.update_by_egress_id(
                        egress_id,
                        {"status": RecordingStatus.ACTIVE}
                    )
                await session.commit()
                return recording
                
            elif event_type == "egress_ended":
                # Recording completed
                file_info = egress_info.get("file", {})
                stream_info = egress_info.get("stream", {})
                
                file_path = file_info.get("filename") or file_info.get("path")
                file_url = file_info.get("url")
                file_size = file_info.get("size")
                duration = str(egress_info["duration"]) if "duration" in egress_info else None
                
                status = RecordingStatus.COMPLETED
                if egress_info.get("error"):
                    status = RecordingStatus.FAILED
                
                update_data = {
                    "status": status,
                    "file_path": file_path,
                    "file_url": file_url,
                    "file_size": file_size,
                    "duration": duration,
                    "completed_at": datetime.utcnow(),
                    "metadata": json.dumps({
                        "egress_info": egress_info,
                        "file_info": file_info,
                        "stream_info": stream_info,
                    }),
                }
                
                recording = await repository.update_by_egress_id(egress_id, update_data)
                await session.commit()
                logger.info(f"Recording completed: {egress_id}, file: {file_path}")
                return recording
                
            elif event_type == "egress_updated":
                # Just log the update
                logger.debug(f"Recording updated: {egress_id}")
                return None
                
            else:
                logger.warning(f"Unknown event type: {event_type}")
                return None


