"""LiveKit recording controller"""
import logging
from typing import Optional, Dict, Any
from livekit import api

from ..config.config import LiveKitConfig

logger = logging.getLogger(__name__)


class LiveKitController:
    """Controller for LiveKit recording operations"""
    
    def __init__(self, config: LiveKitConfig):
        self.config = config
        self.livekit_api = api.LiveKitAPI(
            url=config.url,
            api_key=config.api_key,
            api_secret=config.api_secret
        )
        
    async def start_recording(
        self,
        room_name: str,
        layout: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Start recording a LiveKit room"""
        try:
            # Start egress with file output
            # Use dict format as livekit-api expects
            file_output = {
                "file_type": "MP4",
                "filepath": f"recordings/{room_name}/{{time}}.mp4",
            }
            
            # Check method signature and call appropriately
            import inspect
            method = self.livekit_api.egress.start_room_composite_egress
            sig = inspect.signature(method)
            params = list(sig.parameters.keys())
            
            logger.debug(f"start_room_composite_egress signature: {params}")
            
            # Try different calling patterns based on signature
            if len(params) == 1 and params[0] not in ['self', 'cls']:
                # Method expects a single request object
                try:
                    from livekit.protocol.egress import RoomCompositeEgressRequest
                    request = RoomCompositeEgressRequest(
                        room_name=room_name,
                        layout=layout or "speaker",
                        file_outputs=[file_output],
                    )
                    egress_info = await method(request)
                except (ImportError, TypeError, AttributeError) as e:
                    logger.debug(f"Failed to use RoomCompositeEgressRequest: {e}")
                    # Fallback: use dict as request
                    request = {
                        "room_name": room_name,
                        "layout": layout or "speaker",
                        "file_outputs": [file_output],
                    }
                    egress_info = await method(request)
            elif 'room' in params:
                # Method expects 'room' parameter (not 'room_name')
                egress_info = await method(
                    room=room_name,
                    layout=layout or "speaker",
                    file_outputs=[file_output],
                )
            else:
                # Try with dict unpacking as fallback
                request = {
                    "room_name": room_name,
                    "layout": layout or "speaker",
                    "file_outputs": [file_output],
                }
                egress_info = await method(**request)
            
            logger.info(f"Started recording for room {room_name}, egress_id: {egress_info.egress_id}")
            
            return {
                "egress_id": egress_info.egress_id,
                "room_name": room_name,
                "status": "active",
            }
            
        except Exception as e:
            logger.error(f"Failed to start recording: {e}")
            raise
            
    async def stop_recording(self, egress_id: str) -> Dict[str, Any]:
        """Stop an active recording"""
        try:
            method = self.livekit_api.egress.stop_egress
            
            # Debug: Check method signature
            import inspect
            try:
                sig = inspect.signature(method)
                logger.info(f"stop_egress method signature: {sig}")
                logger.info(f"stop_egress parameters: {list(sig.parameters.keys())}")
                for param_name, param in sig.parameters.items():
                    logger.info(f"  - {param_name}: {param.kind}, default={param.default}, annotation={param.annotation}")
            except Exception as sig_err:
                logger.warning(f"Could not inspect signature: {sig_err}")
            
            # LiveKit API stop_egress expects positional argument, NOT keyword argument
            # Try different patterns in order:
            # 1. Direct positional string (most common)
            # 2. StopEgressRequest object
            # 3. Dict as request
            
            # Pattern 1: Direct positional argument (string)
            try:
                logger.info(f"Attempting stop_egress with positional string argument: {egress_id}")
                result = await method(egress_id)  # NO keyword argument here!
                logger.info("stop_egress succeeded with positional string argument")
            except Exception as e1:
                error_msg1 = str(e1)
                error_type1 = type(e1).__name__
                logger.debug(f"Positional string argument failed ({error_type1}): {error_msg1}")
                
                # Pattern 2: StopEgressRequest object
                try:
                    from livekit.protocol.egress import StopEgressRequest
                    request = StopEgressRequest(egress_id=egress_id)
                    logger.info(f"Attempting stop_egress with StopEgressRequest object")
                    result = await method(request)  # Positional, not keyword
                    logger.info("stop_egress succeeded with StopEgressRequest object")
                except Exception as e2:
                    error_msg2 = str(e2)
                    error_type2 = type(e2).__name__
                    logger.debug(f"StopEgressRequest object failed ({error_type2}): {error_msg2}")
                    
                    # Pattern 3: Dict as request (last resort)
                    try:
                        request_dict = {"egress_id": egress_id}
                        logger.info(f"Attempting stop_egress with dict request")
                        result = await method(request_dict)  # Positional
                        logger.info("stop_egress succeeded with dict request")
                    except Exception as e3:
                        error_msg3 = str(e3)
                        error_type3 = type(e3).__name__
                        logger.error(f"All stop_egress patterns failed:")
                        logger.error(f"  1. Positional string ({error_type1}): {error_msg1}")
                        logger.error(f"  2. StopEgressRequest ({error_type2}): {error_msg2}")
                        logger.error(f"  3. Dict request ({error_type3}): {error_msg3}")
                        raise e1  # Raise first error
            
            logger.info(f"Stopped recording: {egress_id}")
            
            return {
                "egress_id": egress_id,
                "status": "stopped",
            }
            
        except Exception as e:
            logger.error(f"Failed to stop recording: {e}")
            raise
