import logging
from typing import Dict, Any
from fastapi import APIRouter, Request, HTTPException, Header

from ...services.recording_service import RecordingService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhook"])


@router.post("/livekit/egress")
async def handle_livekit_webhook(
    request: Request,
    authorization: str = Header(None),
) -> Dict[str, Any]:
    try:
        recording_service: RecordingService = request.app.state.recording_service
        payload = await request.json()
        event_type = payload.get("event")
        egress_info = payload.get("egress", {})
        
        logger.info(f"Received LiveKit webhook: {event_type}, egress_id: {egress_info.get('egress_id')}")
        recording = await recording_service.handle_webhook_event(event_type, egress_info)
        
        if event_type == "egress_ended" and recording:
            return {
                "status": "ok",
                "message": "Recording completed",
                "egress_id": recording.egress_id,
                "file_path": recording.file_path,
            }
        elif event_type == "egress_started":
            return {"status": "ok", "message": "Recording started"}
        elif event_type == "egress_updated":
            return {"status": "ok", "message": "Recording updated"}
        else:
            return {"status": "ok", "message": f"Event processed: {event_type}"}
    
    except Exception as e:
        logger.error(f"Error handling webhook: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_check() -> Dict[str, str]:
    return {"status": "ok", "service": "matrix-livekit-bot"}


