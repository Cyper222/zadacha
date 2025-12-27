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
        try:
            result = await self.livekit_client.start_recording(room_name=room_name)
        except Exception as e:
            error_msg = str(e)
            if ("room does not exist" in error_msg.lower() or "not_found" in error_msg.lower()) and hasattr(self.livekit_client, 'config'):
                config = getattr(self.livekit_client, 'config', None)
                if config and getattr(config, 'dev_mode', False):
                    logger.info(f"Room {room_name} doesn't exist, creating it (dev_mode enabled)")
                    try:
                        await self.livekit_client.create_room(room_name=room_name)
                        logger.info("Retrying recording after room creation")
                        result = await self.livekit_client.start_recording(room_name=room_name)
                    except Exception as create_error:
                        logger.error(f"Failed to create room or retry recording: {create_error}")
                        raise
                else:
                    raise
            else:
                raise
        
        egress_id = result["egress_id"]
        bucket = result.get("bucket")
        object_key = result.get("object_key")

        async with self.session_factory() as session:
            repository = RecordingsRepository(session)
            recording_data = {
                "egress_id": egress_id,
                "room_name": room_name,
                "matrix_room_id": matrix_room_id,
                "started_by": started_by,
                "status": RecordingStatus.ACTIVE,
                "started_at": datetime.utcnow(),
                "bucket": bucket,
                "object_key": object_key,
            }
            recording = await repository.create(recording_data)
            await session.commit()
            logger.info(f"Recording started: {egress_id}, bucket: {bucket}, object_key: {object_key}")
            return recording
    
    async def stop_recording(self, egress_id: str) -> Optional[Recording]:
        await self.livekit_client.stop_recording(egress_id=egress_id)

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

        egress_id = egress_info.get("egress_id")
        if not egress_id:
            logger.warning("No egress_id in webhook payload")
            return None
        
        async with self.session_factory() as session:
            repository = RecordingsRepository(session)
            
            if event_type == "egress_started":
                recording = await repository.get_by_egress_id(egress_id)
                if not recording:
                    recording = await repository.create({
                        "egress_id": egress_id,
                        "room_name": egress_info.get("room_name", "unknown"),
                        "status": RecordingStatus.ACTIVE,
                        "started_at": datetime.utcnow(),
                    })
                else:
                    recording = await repository.update_by_egress_id(
                        egress_id,
                        {"status": RecordingStatus.ACTIVE}
                    )
                await session.commit()
                return recording
                
            elif event_type == "egress_ended":
                file_info = egress_info.get("file", {})
                stream_info = egress_info.get("stream", {})

                egress_status = egress_info.get("status", "").upper()

                if egress_status == "EGRESS_ABORTED":
                    status = RecordingStatus.FAILED
                    logger.warning(f"Recording aborted: {egress_id}, reason: {egress_info.get('error', 'unknown')}")
                elif egress_info.get("error"):
                    status = RecordingStatus.FAILED
                    logger.error(f"Recording failed: {egress_id}, error: {egress_info.get('error')}")
                else:
                    status = RecordingStatus.COMPLETED

                s3_info = egress_info.get("s3", {}) or file_info.get("s3", {})
                
                bucket = s3_info.get("bucket") or file_info.get("bucket")
                object_key = s3_info.get("key") or file_info.get("key") or file_info.get("filename") or file_info.get("path")

                file_path = object_key or file_info.get("filename") or file_info.get("path")
                file_url = file_info.get("url") or s3_info.get("url")
                file_size = file_info.get("size") or s3_info.get("size")
                duration = str(egress_info["duration"]) if "duration" in egress_info else None
                
                update_data = {
                    "status": status,
                    "file_path": file_path,
                    "file_url": file_url,
                    "file_size": file_size,
                    "duration": duration,
                    "bucket": bucket,
                    "object_key": object_key,
                    "completed_at": datetime.utcnow(),
                    "extra_metadata": json.dumps({
                        "egress_info": egress_info,
                        "file_info": file_info,
                        "stream_info": stream_info,
                        "s3_info": s3_info,
                    }),
                }
                
                recording = await repository.update_by_egress_id(egress_id, update_data)
                await session.commit()
                
                if status == RecordingStatus.COMPLETED:
                    logger.info(f"Recording completed: {egress_id}, bucket: {bucket}, object_key: {object_key}")
                else:
                    logger.warning(f"Recording ended with status {status}: {egress_id}")
                
                return recording
                
            elif event_type == "egress_updated":
                egress_status = egress_info.get("status", "").upper()
                update_status = None
                
                if egress_status == "EGRESS_STARTING":
                    update_status = RecordingStatus.ACTIVE
                elif egress_status == "EGRESS_ACTIVE":
                    update_status = RecordingStatus.PROCESSING
                elif egress_status == "EGRESS_ABORTED":
                    update_status = RecordingStatus.FAILED
                    logger.warning(f"Recording aborted during update: {egress_id}")
                
                if update_status:
                    await repository.update_by_egress_id(egress_id, {"status": update_status})
                    await session.commit()
                
                return None
                
            else:
                logger.warning(f"Unknown event type: {event_type}")
                return None


