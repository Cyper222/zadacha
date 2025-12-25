"""LiveKit client integration"""
import asyncio
import logging
from typing import Optional, Dict, Any
import aiohttp
import time
import hmac
import hashlib
import base64
from livekit import api

from ..config.config import LiveKitConfig, MinIOConfig

logger = logging.getLogger(__name__)


class LiveKitClient:
    """LiveKit client for recording operations
    
    Manages a single aiohttp ClientSession for all HTTP requests.
    Session is created on initialization and closed on shutdown.
    """
    
    def __init__(self, config: LiveKitConfig, minio_config: MinIOConfig):
        self.config = config
        self.minio_config = minio_config
        # LiveKit API will create its own internal ClientSession
        self.livekit_api: Optional[api.LiveKitAPI] = None
        self._internal_session: Optional[aiohttp.ClientSession] = None
        logger.info("LiveKit client initialized")
    
    async def _ensure_api(self) -> None:
        """Ensure LiveKit API is initialized"""
        if self.livekit_api is None:
            # Initialize LiveKit API - it will create its own internal ClientSession
            # We'll try to close it in close() method
            # Note: LiveKit API uses lazy initialization, so session may not be created until first use
            logger.info(f"Initializing LiveKit API with URL: {self.config.url}")
            self.livekit_api = api.LiveKitAPI(
                url=self.config.url,
                api_key=self.config.api_key,
                api_secret=self.config.api_secret
            )
            logger.debug("LiveKit API initialized (session will be created on first use)")
            
            # Try to find and store reference to the internal session for later cleanup
            # This helps us close it properly on shutdown
            # Note: Session might not exist yet, we'll check again in close()
            self._internal_session = None
    
    async def close(self) -> None:
        """Close LiveKit API's internal ClientSession and cleanup resources"""
        session_closed = False
        
        # Method 1: Close stored internal session reference
        if self._internal_session and not self._internal_session.closed:
            try:
                await self._internal_session.close()
                session_closed = True
                logger.debug("LiveKit API session closed via stored reference")
            except Exception as e:
                logger.debug(f"Failed to close stored session: {e}")
        
        # Method 2: Check for close() method on LiveKit API
        if self.livekit_api and not session_closed:
            if hasattr(self.livekit_api, 'close') and callable(getattr(self.livekit_api, 'close')):
                try:
                    close_method = getattr(self.livekit_api, 'close')
                    if asyncio.iscoroutinefunction(close_method):
                        await close_method()
                    else:
                        close_method()
                    session_closed = True
                    logger.debug("LiveKit API closed via close() method")
                except Exception as e:
                    logger.debug(f"LiveKit API close() failed: {e}")
            
            # Method 3: Try to access internal HTTP client/session attributes
            if not session_closed:
                for attr_name in ['_http_client', '_session', '_client', 'http_client', 'session', '_aiohttp_session']:
                    if hasattr(self.livekit_api, attr_name):
                        try:
                            http_client = getattr(self.livekit_api, attr_name)
                            # If it's a ClientSession directly
                            if isinstance(http_client, aiohttp.ClientSession) and not http_client.closed:
                                await http_client.close()
                                session_closed = True
                                logger.debug(f"LiveKit API session closed via {attr_name}")
                                break
                            # If it has a close method
                            elif hasattr(http_client, 'close'):
                                close_method = getattr(http_client, 'close')
                                if asyncio.iscoroutinefunction(close_method):
                                    await close_method()
                                else:
                                    close_method()
                                session_closed = True
                                logger.debug(f"LiveKit API session closed via {attr_name}.close()")
                                break
                            # If it has a session attribute
                            elif hasattr(http_client, '_session') and isinstance(getattr(http_client, '_session'), aiohttp.ClientSession):
                                session = getattr(http_client, '_session')
                                if not session.closed:
                                    await session.close()
                                    session_closed = True
                                    logger.debug(f"LiveKit API session closed via {attr_name}._session")
                                    break
                        except Exception as e:
                            logger.debug(f"Could not close LiveKit API {attr_name}: {e}")
        
        if not session_closed:
            logger.debug("Could not find LiveKit API session to close (may be managed internally)")
        else:
            logger.info("LiveKit client closed successfully")
        
    async def start_recording(
        self,
        room_name: str,
        layout: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Start recording a LiveKit room with S3 (MinIO) output
        
        Args:
            room_name: Name of the LiveKit room to record
            layout: Recording layout (optional)
            **kwargs: Additional recording options
            
        Returns:
            Dictionary with recording information
        """
        await self._ensure_api()
        
        try:
            # Generate object key (path in bucket)
            # Format: recordings/{room_name}/{timestamp}.mp4
            import time
            timestamp = int(time.time())
            object_key = f"recordings/{room_name}/{timestamp}.mp4"
            
            # Configure S3 output for MinIO
            # LiveKit egress expects EncodedFileOutput with s3 field
            # Format: file_outputs with EncodedFileOutput containing s3 config
            s3_config = {
                "access_key": self.minio_config.access_key,
                "secret": self.minio_config.secret_key,
                "region": self.minio_config.region,
                "bucket": self.minio_config.bucket,
            }
            
            # Add endpoint for MinIO (S3-compatible)
            if self.minio_config.endpoint:
                s3_config["endpoint"] = self.minio_config.endpoint
            
            # Create file output with S3 configuration
            file_output = {
                "file_type": "MP4",
                "filepath": object_key,
                "s3": s3_config,
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
                    from livekit.protocol.egress import RoomCompositeEgressRequest, EncodedFileOutput, S3Upload
                    # Try using protocol objects
                    try:
                        s3_upload = S3Upload(
                            access_key=self.minio_config.access_key,
                            secret=self.minio_config.secret_key,
                            region=self.minio_config.region,
                            bucket=self.minio_config.bucket,
                        )
                        if self.minio_config.endpoint:
                            s3_upload.endpoint = self.minio_config.endpoint
                        
                        encoded_output = EncodedFileOutput(
                            filepath=object_key,
                            s3=s3_upload,
                        )
                        
                        request = RoomCompositeEgressRequest(
                            room_name=room_name,
                            layout=layout or "speaker",
                            file_outputs=[encoded_output],
                        )
                        egress_info = await method(request)
                    except (TypeError, AttributeError) as e:
                        logger.debug(f"Failed to use protocol objects, trying dict: {e}")
                        # Fallback: use dict format
                        request = {
                            "room_name": room_name,
                            "layout": layout or "speaker",
                            "file_outputs": [file_output],
                        }
                        egress_info = await method(request)
                except (ImportError, AttributeError) as e:
                    logger.debug(f"Failed to import protocol classes: {e}")
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
            
            logger.info(f"Started recording for room {room_name}, egress_id: {egress_info.egress_id}, bucket: {self.minio_config.bucket}")
            
            return {
                "egress_id": egress_info.egress_id,
                "room_name": room_name,
                "bucket": self.minio_config.bucket,
                "object_key": object_key,
                "status": "active",
            }
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to start recording: {e}")
            
            # Provide helpful error messages
            if "unavailable" in error_msg.lower() or "503" in error_msg or "no response" in error_msg.lower():
                logger.error(f"LiveKit server appears to be unavailable at {self.config.url}")
                logger.error("Please check:")
                logger.error("  1. Is LiveKit server running? (docker-compose ps)")
                logger.error("  2. Is LiveKit Egress service running? (docker-compose ps livekit-egress)")
                logger.error(f"  3. Is it accessible at {self.config.url}?")
                logger.error("  4. Check LiveKit server logs: docker-compose logs livekit")
                logger.error("  5. Check LiveKit Egress logs: docker-compose logs livekit-egress")
                logger.error("  6. Verify LIVEKIT_URL in your .env file")
                logger.error("  7. Ensure Egress is configured in livekit.yaml")
            
            raise
            
    async def stop_recording(self, egress_id: str) -> Dict[str, Any]:
        """
        Stop an active recording
        
        Args:
            egress_id: Egress ID of the recording to stop
            
        Returns:
            Dictionary with stop confirmation
        """
        logger.info(f"🛑 stop_recording called with egress_id: {egress_id}")
        await self._ensure_api()
        
        if not self.livekit_api:
            raise RuntimeError("LiveKit API not initialized")
        
        # IMPORTANT: Due to known issues with livekit-api library's stop_egress method,
        # we'll try library first, but immediately fallback to HTTP if it fails
        # This is a workaround for the "unexpected keyword argument 'egress_id'" error
        try:
            # Access egress service directly
            egress_service = self.livekit_api.egress
            logger.info(f"✅ Got egress service: {egress_service}")
            
            method = egress_service.stop_egress
            logger.info(f"✅ Got method: {method}")
            
            # Debug: Check method signature
            import inspect
            try:
                sig = inspect.signature(method)
                logger.info(f"📋 stop_egress method signature: {sig}")
                params = list(sig.parameters.keys())
                logger.info(f"📋 stop_egress parameters: {params}")
                for param_name, param in sig.parameters.items():
                    logger.info(f"  📋 {param_name}: kind={param.kind.name if hasattr(param.kind, 'name') else param.kind}, default={param.default}, annotation={param.annotation}")
            except Exception as sig_err:
                logger.warning(f"Could not inspect signature: {sig_err}")
            
            # Try calling with positional argument only
            logger.info(f"🔵 Attempting stop_egress with positional string: {egress_id}")
            result = await method(egress_id)  # Positional only!
            logger.info(f"✅ stop_egress succeeded, result: {result}")
            
            return {
                "egress_id": egress_id,
                "status": "stopped",
            }
            
        except Exception as lib_error:
            error_str = str(lib_error)
            error_type = type(lib_error).__name__
            logger.warning(f"⚠️ Library call failed ({error_type}): {error_str}")
            logger.warning(f"⚠️ Full error: {repr(lib_error)}")
            
            # ALWAYS try HTTP fallback for any error from library
            # This is a workaround for known issues with livekit-api stop_egress method
            error_lower = error_str.lower()
            is_keyword_error = (
                "keyword argument" in error_lower or 
                "unexpected keyword" in error_lower or
                "got an unexpected keyword" in error_lower or
                "unexpected keyword argument" in error_lower
            )
            
            if is_keyword_error:
                logger.info(f"🔄 Detected keyword argument error, using HTTP fallback")
            else:
                logger.info(f"🔄 Library error detected, trying HTTP fallback as workaround")
            
            try:
                result = await self._stop_egress_via_http(egress_id)
                logger.info(f"✅ HTTP fallback succeeded: {result}")
                return result
            except Exception as http_error:
                logger.error(f"❌ HTTP fallback also failed: {http_error}", exc_info=True)
                # Raise original error if HTTP fallback fails
                raise lib_error from http_error
        
    async def _stop_egress_via_http(self, egress_id: str) -> Dict[str, Any]:
        """
        Stop egress via direct HTTP call to LiveKit API
        This is a fallback when the library has issues with keyword arguments
        """
        try:
            # Build LiveKit API URL
            api_url = self.config.url.rstrip('/')
            if api_url.startswith('ws://'):
                api_url = api_url.replace('ws://', 'http://')
            elif api_url.startswith('wss://'):
                api_url = api_url.replace('wss://', 'https://')
            
            # LiveKit uses Twirp protocol - endpoint for stopping egress
            endpoint = f"{api_url}/twirp/livekit.EgressService/StopEgress"
            
            # Create request payload (Twirp uses JSON)
            payload = {"egress_id": egress_id}
            
            # Generate LiveKit JWT token for authentication
            # Try using livekit-api's token generation if available
            try:
                from livekit import api as livekit_api_module
                # Check if there's a token generation method
                if hasattr(livekit_api_module, 'AccessToken'):
                    from livekit import api
                    token = api.AccessToken(self.config.api_key, self.config.api_secret) \
                        .with_grants(api.VideoGrants()) \
                        .to_jwt()
                else:
                    # Fallback: use PyJWT
                    import jwt
                    import time as time_module
                    now = int(time_module.time())
                    token = jwt.encode(
                        {
                            "iss": self.config.api_key,
                            "exp": now + 3600,
                            "nbf": now - 5,
                        },
                        self.config.api_secret,
                        algorithm="HS256"
                    )
            except ImportError:
                # Try PyJWT directly
                try:
                    import jwt
                    import time as time_module
                    now = int(time_module.time())
                    token = jwt.encode(
                        {
                            "iss": self.config.api_key,
                            "exp": now + 3600,
                            "nbf": now - 5,
                        },
                        self.config.api_secret,
                        algorithm="HS256"
                    )
                except ImportError:
                    logger.error("❌ Neither livekit AccessToken nor PyJWT available for HTTP fallback")
                    raise Exception("JWT library required for HTTP fallback")
            
            # Make HTTP request
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                }
                
                logger.info(f"🌐 HTTP Fallback: POST to {endpoint}")
                logger.info(f"🌐 Payload: {payload}")
                
                async with session.post(endpoint, json=payload, headers=headers) as response:
                    response_text = await response.text()
                    if response.status == 200:
                        try:
                            result = await response.json()
                        except:
                            result = {"status": "ok"}
                        logger.info(f"✅ HTTP stop_egress succeeded: {result}")
                        return {
                            "egress_id": egress_id,
                            "status": "stopped",
                        }
                    else:
                        logger.error(f"❌ HTTP stop_egress failed: {response.status} - {response_text}")
                        raise Exception(f"HTTP {response.status}: {response_text}")
                        
        except Exception as e:
            logger.error(f"❌ HTTP fallback failed: {e}", exc_info=True)
            raise
    
    async def create_room(self, room_name: str) -> Dict[str, Any]:
        """
        Create a LiveKit room (production-ready)
        
        Args:
            room_name: Name of the room to create (typically call_id)
            
        Returns:
            Dictionary with room information
            
        Raises:
            Exception if room creation fails
        """
        await self._ensure_api()
        
        try:
            # Try to import CreateRoomRequest from livekit.protocol.room
            try:
                from livekit.protocol.room import CreateRoomRequest
                request = CreateRoomRequest(name=room_name)
                room_info = await self.livekit_api.room.create_room(request)
            except (ImportError, AttributeError, TypeError) as e:
                logger.debug(f"Failed to use CreateRoomRequest, trying alternative: {e}")
                # Fallback: try with dict or direct parameters
                try:
                    # Try with dict
                    request = {"name": room_name}
                    room_info = await self.livekit_api.room.create_room(request)
                except (TypeError, AttributeError):
                    # Try with direct parameter
                    room_info = await self.livekit_api.room.create_room(name=room_name)
            
            logger.info(f"Created LiveKit room: {room_name}")
            
            return {
                "name": room_name,
                "room": room_info,
                "status": "created",
            }
            
        except Exception as e:
            logger.error(f"Failed to create room {room_name}: {e}")
            raise
