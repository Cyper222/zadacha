import asyncio
import logging
from typing import Optional, Dict, Any
import aiohttp
import time
from livekit import api as livekit_api_module
from livekit import api
from ..config.config import LiveKitConfig, MinIOConfig
from livekit.protocol.room import CreateRoomRequest
from livekit.protocol.egress import RoomCompositeEgressRequest, EncodedFileOutput, S3Upload, StopEgressRequest

logger = logging.getLogger(__name__)


class LiveKitClient:
    def __init__(self, config: LiveKitConfig, minio_config: MinIOConfig):
        self.config = config
        self.minio_config = minio_config
        self.livekit_api: Optional[api.LiveKitAPI] = None
        self._internal_session: Optional[aiohttp.ClientSession] = None

    async def _ensure_api(self) -> None:
        if self.livekit_api is None:
            self.livekit_api = api.LiveKitAPI(
                url=self.config.url,
                api_key=self.config.api_key,
                api_secret=self.config.api_secret
            )
            self._internal_session = None

    async def close(self) -> None:
        session_closed = False
        if self._internal_session and not self._internal_session.closed:
            try:
                await self._internal_session.close()
                session_closed = True
            except Exception:
                pass

        if self.livekit_api and not session_closed:
            if hasattr(self.livekit_api, 'close') and callable(getattr(self.livekit_api, 'close')):
                try:
                    close_method = getattr(self.livekit_api, 'close')
                    if asyncio.iscoroutinefunction(close_method):
                        await close_method()
                    else:
                        close_method()
                    session_closed = True
                except Exception:
                    pass

            if not session_closed:
                for attr_name in ['_http_client', '_session', '_client', 'http_client', 'session', '_aiohttp_session']:
                    if hasattr(self.livekit_api, attr_name):
                        try:
                            http_client = getattr(self.livekit_api, attr_name)
                            if isinstance(http_client, aiohttp.ClientSession) and not http_client.closed:
                                await http_client.close()
                                session_closed = True
                                break
                            elif hasattr(http_client, 'close'):
                                close_method = getattr(http_client, 'close')
                                if asyncio.iscoroutinefunction(close_method):
                                    await close_method()
                                else:
                                    close_method()
                                session_closed = True
                                break
                            elif hasattr(http_client, '_session') and isinstance(getattr(http_client, '_session'),
                                                                                 aiohttp.ClientSession):
                                session = getattr(http_client, '_session')
                                if not session.closed:
                                    await session.close()
                                    session_closed = True
                                    break
                        except Exception:
                            pass
        else:
            logger.info("LiveKit client closed successfully")

    async def start_recording(
            self,
            room_name: str,
            layout: Optional[str] = None,
            **kwargs
    ) -> Dict[str, Any]:
        await self._ensure_api()

        try:
            timestamp = int(time.time())
            object_key = f"recordings/{room_name}/{timestamp}.mp4"

            # Build S3 configuration with real values
            s3_config = {
                "access_key": self.minio_config.access_key,
                "secret": self.minio_config.secret_key,
                "region": self.minio_config.region,
                "bucket": self.minio_config.bucket,
            }

            if self.minio_config.endpoint:
                s3_config["endpoint"] = self.minio_config.endpoint

            # Log S3 config (without sensitive data) for debugging
            logger.info(
                f"S3 config for recording: endpoint={s3_config.get('endpoint')}, bucket={s3_config.get('bucket')}, region={s3_config.get('region')}, has_access_key={bool(s3_config.get('access_key'))}, has_secret={bool(s3_config.get('secret'))}")

            # Use direct HTTP request to bypass SDK's credential masking
            # The SDK replaces credentials with placeholders, so we need to send raw JSON
            try:
                egress_info = await self._start_egress_via_http(room_name, layout or "speaker", object_key, s3_config)
            except Exception as http_error:
                logger.warning(f"HTTP direct request failed: {http_error}, falling back to SDK method")
                # Fallback to SDK method (may have placeholder issue, but worth trying)
                file_output = {
                    "file_type": "MP4",
                    "filepath": object_key,
                    "s3": s3_config,
                }

                request_dict = {
                    "room_name": room_name,
                    "layout": layout or "speaker",
                    "file_outputs": [file_output],
                }

                import inspect
                method = self.livekit_api.egress.start_room_composite_egress
                sig = inspect.signature(method)
                params = list(sig.parameters.keys())

                if len(params) == 1 and params[0] not in ['self', 'cls']:
                    try:
                        egress_info = await method(request_dict)
                    except (TypeError, AttributeError, ValueError):
                        try:
                            request = RoomCompositeEgressRequest(**request_dict)
                            egress_info = await method(request)
                        except (TypeError, AttributeError, ImportError, ValueError):
                            egress_info = await method(**request_dict)
                elif 'room' in params:
                    egress_info = await method(
                        room=room_name,
                        layout=layout or "speaker",
                        file_outputs=[file_output],
                    )
                else:
                    egress_info = await method(**request_dict)

            # Handle both SDK response objects and our custom EgressInfo objects
            egress_id = getattr(egress_info, 'egress_id', None) or (
                egress_info.get('egress_id') if isinstance(egress_info, dict) else None)
            if not egress_id:
                raise ValueError("No egress_id in response")

            logger.info(
                f"Started recording for room {room_name}, egress_id: {egress_id}, bucket: {self.minio_config.bucket}")

            return {
                "egress_id": egress_id,
                "room_name": room_name,
                "bucket": self.minio_config.bucket,
                "object_key": object_key,
                "status": "active",
            }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to start recording: {e}")

            if "unavailable" in error_msg.lower() or "503" in error_msg or "no response" in error_msg.lower():
                logger.error(f"LiveKit server appears to be unavailable at {self.config.url}")

            raise

    async def stop_recording(self, egress_id: str) -> Dict[str, Any]:
        logger.info(f"stop_recording called with egress_id: {egress_id}")
        await self._ensure_api()
        if not self.livekit_api:
            raise RuntimeError("LiveKit API not initialized")

        try:
            egress_service = self.livekit_api.egress
            logger.info(f"Got egress service: {egress_service}")
            method = egress_service.stop_egress

            try:
                request = StopEgressRequest(egress_id=egress_id)
                result = await method(stop=request)
            except Exception as e1:
                error_msg1 = str(e1)
                error_type1 = type(e1).__name__
                logger.warning(f"Full error: {repr(e1)}")

                try:
                    request_dict = {"egress_id": egress_id}
                    result = await method(stop=request_dict)
                except Exception as e2:
                    raise e2

            logger.info(f"Stopped recording successful: {egress_id}")

            return {
                "egress_id": egress_id,
                "status": "stopped",
            }

        except Exception as lib_error:
            error_str = str(lib_error)
            error_type = type(lib_error).__name__
            logger.warning(f"Library call failed ({error_type}): {error_str}")
            logger.warning(f"Full error: {repr(lib_error)}")

            error_lower = error_str.lower()
            is_keyword_error = (
                    "keyword argument" in error_lower or
                    "unexpected keyword" in error_lower or
                    "got an unexpected keyword" in error_lower or
                    "unexpected keyword argument" in error_lower
            )
            is_unavailable_error = (
                    "unavailable" in error_lower or
                    "no response from servers" in error_lower or
                    "503" in error_str or
                    error_type == "TwirpError"
            )

            if is_keyword_error:
                logger.info(f"Detected keyword argument error, using HTTP fallback")
            elif is_unavailable_error:
                logger.info(f"Detected LiveKit service unavailable error (503/TwirpError), using HTTP fallback")
            else:
                logger.info(f"Library error detected, trying HTTP fallback as workaround")

            try:
                result = await self._stop_egress_via_http(egress_id)
                logger.info(f"HTTP fallback succeeded: {result}")
                return result
            except Exception as http_error:
                logger.error(f"HTTP fallback also failed: {http_error}", exc_info=True)
                raise lib_error from http_error

    async def _start_egress_via_http(
            self,
            room_name: str,
            layout: str,
            filepath: str,
            s3_config: Dict[str, Any]
    ) -> Any:
        """Start egress via direct HTTP request to bypass SDK credential masking"""
        try:
            api_url = self.config.url.rstrip('/')
            if api_url.startswith('ws://'):
                api_url = api_url.replace('ws://', 'http://')
            elif api_url.startswith('wss://'):
                api_url = api_url.replace('wss://', 'https://')

            endpoint = f"{api_url}/twirp/livekit.EgressService/StartRoomCompositeEgress"

            # Build payload with real credentials (not masked by SDK)
            payload = {
                "room_name": room_name,
                "layout": layout,
                "file_outputs": [{
                    "file_type": 1,  # MP4
                    "filepath": filepath,
                    "s3": {
                        "access_key": s3_config["access_key"],
                        "secret": s3_config["secret"],
                        "region": s3_config["region"],
                        "bucket": s3_config["bucket"],
                    }
                }]
            }

            # Add endpoint if present
            if "endpoint" in s3_config:
                payload["file_outputs"][0]["s3"]["endpoint"] = s3_config["endpoint"]

            # Generate auth token
            token = None
            auth_header = None

            try:
                if hasattr(livekit_api_module, 'AccessToken'):
                    token_obj = api.AccessToken(self.config.api_key, self.config.api_secret)
                    video_grants = api.VideoGrants()
                    video_grants.can_update = True
                    token_obj.with_grants(video_grants)
                    token = token_obj.to_jwt()
                    auth_header = f"Bearer {token}"
            except (ImportError, AttributeError, Exception):
                pass

            if not token:
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
                    auth_header = f"Bearer {token}"
                except ImportError:
                    import base64
                    auth_str = f"{self.config.api_key}:{self.config.api_secret}"
                    auth_bytes = base64.b64encode(auth_str.encode()).decode()
                    auth_header = f"Basic {auth_bytes}"
                except Exception as e:
                    raise Exception(f"JWT token generation failed: {e}")

            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": auth_header,
                    "Content-Type": "application/json",
                }

                logger.info(f"Starting egress via HTTP: {endpoint}")
                logger.info(f"Room: {room_name}, Layout: {layout}, Filepath: {filepath}")

                async with session.post(
                        endpoint,
                        json=payload,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    response_text = await response.text()

                    if response.status == 200:
                        try:
                            result = await response.json()

                            # Create a simple object-like response
                            class EgressInfo:
                                def __init__(self, data):
                                    self.egress_id = data.get("egress_id", "")
                                    self._data = data

                            return EgressInfo(result)
                        except Exception as e:
                            logger.error(f"Failed to parse response: {e}, response: {response_text}")
                            raise Exception(f"Invalid response format: {response_text}")
                    else:
                        error_msg = f"HTTP {response.status}: {response_text}"
                        logger.error(f"Failed to start egress: {error_msg}")
                        raise Exception(error_msg)

        except Exception as e:
            raise Exception(f"HTTP start_egress failed: {e}")

    async def _stop_egress_via_http(self, egress_id: str) -> Dict[str, Any]:
        try:
            api_url = self.config.url.rstrip('/')
            if api_url.startswith('ws://'):
                api_url = api_url.replace('ws://', 'http://')
            elif api_url.startswith('wss://'):
                api_url = api_url.replace('wss://', 'https://')

            endpoints_to_try = [
                f"{api_url}/twirp/livekit.EgressService/StopEgress",
                f"{api_url}/twirp/livekit.Egress/StopEgress",
                f"{api_url}/api/egress/stop",
            ]

            payload = {"egress_id": egress_id}

            token = None
            auth_header = None

            try:

                if hasattr(livekit_api_module, 'AccessToken'):
                    token_obj = api.AccessToken(self.config.api_key, self.config.api_secret)
                    video_grants = api.VideoGrants()
                    video_grants.can_update = True
                    token_obj.with_grants(video_grants)
                    token = token_obj.to_jwt()
                    auth_header = f"Bearer {token}"
            except (ImportError, AttributeError, Exception):
                pass

            if not token:
                try:
                    import jwt
                    import time as time_module
                    import base64
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
                    auth_header = f"Bearer {token}"
                except ImportError:
                    auth_str = f"{self.config.api_key}:{self.config.api_secret}"
                    auth_bytes = base64.b64encode(auth_str.encode()).decode()
                    auth_header = f"Basic {auth_bytes}"
                except Exception as e:
                    raise Exception(f"JWT token generation failed: {e}")

            async with aiohttp.ClientSession() as session:
                last_error = None

                for endpoint in endpoints_to_try:
                    try:
                        headers = {
                            "Authorization": auth_header,
                            "Content-Type": "application/json",
                        }

                        logger.info(f"HTTP Fallback: Trying POST to {endpoint}")
                        logger.info(f"Payload: {payload}")

                        async with session.post(endpoint, json=payload, headers=headers,
                                                timeout=aiohttp.ClientTimeout(total=10)) as response:
                            response_text = await response.text()
                            if response.status == 200:
                                try:
                                    result = await response.json()
                                except:
                                    result = {"status": "ok"}
                                logger.info(f"HTTP stop_egress succeeded at {endpoint}: {result}")
                                return {
                                    "egress_id": egress_id,
                                    "status": "stopped",
                                }
                            elif response.status == 404:
                                last_error = f"HTTP {response.status}: {response_text}"
                                continue
                            else:
                                logger.warning(f"Endpoint {endpoint} returned {response.status}: {response_text}")
                                last_error = f"HTTP {response.status}: {response_text}"
                                continue
                    except asyncio.TimeoutError:
                        logger.warning(f"Timeout connecting to {endpoint}")
                        last_error = f"Timeout connecting to {endpoint}"
                        continue
                    except Exception as e:
                        logger.warning(f"Error connecting to {endpoint}: {e}")
                        last_error = str(e)
                        continue

                raise Exception(f"All endpoints failed. Last error: {last_error}")

        except Exception as e:
            raise Exception(f"HTTP fallback failed: {e}")

    async def create_room(self, room_name: str) -> Dict[str, Any]:
        await self._ensure_api()

        try:
            try:

                request = CreateRoomRequest(name=room_name)
                room_info = await self.livekit_api.room.create_room(request)
            except (ImportError, AttributeError, TypeError):
                try:
                    request = {"name": room_name}
                    room_info = await self.livekit_api.room.create_room(request)
                except (TypeError, AttributeError):
                    room_info = await self.livekit_api.room.create_room(name=room_name)

            logger.info(f"Created LiveKit room: {room_name}")

            return {
                "name": room_name,
                "room": room_info,
                "status": "created",
            }

        except Exception as e:
            raise Exception(f"Failed to create room {room_name}: {e}")
