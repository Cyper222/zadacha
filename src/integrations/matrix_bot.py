"""Matrix bot integration"""
import asyncio
import logging
from typing import Optional
from nio import AsyncClient, MatrixRoom, RoomMessageText
from nio.responses import WhoamiError, WhoamiResponse
from nio.events import UnknownEvent
from nio.events.invite_events import InviteMemberEvent

from ..config.config import MatrixConfig, LiveKitConfig
from ..bot.commands import CommandHandler
from ..bot.event_handler import EventHandler
from ..bot.livekit_controller import LiveKitController
from .livekit_client import LiveKitClient


logger = logging.getLogger(__name__)


class MatrixBot:
    """Matrix bot for handling commands"""
    
    def __init__(
        self,
        matrix_config: MatrixConfig,
        livekit_config: LiveKitConfig,
        livekit_client: LiveKitClient,
        recording_service = None,  # RecordingService, using Any to avoid circular import
    ):
        self.matrix_config = matrix_config
        self.livekit_config = livekit_config
        self.client: Optional[AsyncClient] = None
        self.livekit_client = livekit_client
        self.recording_service = recording_service
        self.command_handler: Optional[CommandHandler] = None
        self.event_handler: Optional[EventHandler] = None
        self.running = False
        self._sync_task: Optional[asyncio.Task] = None
        
    async def start(self) -> None:
        """Start the Matrix bot"""
        if self.running:
            logger.warning("Bot is already running")
            return
        
        # Create LiveKit controller - it will use livekit_api from LiveKitClient
        # Ensure LiveKit API is initialized
        await self.livekit_client._ensure_api()
        livekit_controller = LiveKitController(self.livekit_config)
        livekit_controller.livekit_api = self.livekit_client.livekit_api
        
        # Initialize Matrix client
        self.client = AsyncClient(
            homeserver=self.matrix_config.homeserver,
            user=self.matrix_config.user_id,
            device_id=self.matrix_config.device_id,
        )
        
        # Login logic: prefer password over token for automatic refresh
        if self.matrix_config.password:
            # Use password login (recommended - automatic token refresh)
            logger.info("Using password authentication (automatic token refresh enabled)")
            await self._login_with_password()
        elif self.matrix_config.access_token:
            # Use provided access token
            logger.info(f"Using provided access token for {self.matrix_config.user_id}")
            self.client.access_token = self.matrix_config.access_token
            # Verify token is still valid
            whoami = await self.client.whoami()
            if isinstance(whoami, (WhoamiError, Exception)):
                logger.warning("Access token appears to be invalid or expired")
                # If password is also provided, fall back to password auth
                if self.matrix_config.password:
                    logger.info("Falling back to password authentication...")
                    await self._login_with_password()
                else:
                    raise Exception(f"Access token invalid and no password provided: {whoami}")
            else:
                logger.info("Access token verified successfully")
        else:
            raise ValueError("Neither access token nor password provided")
        
        # Initialize handlers
        self.command_handler = CommandHandler(
            livekit_controller,
            recording_service=self.recording_service
        )
        self.event_handler = EventHandler(self, self.command_handler)
        
        # Register callbacks for messages
        self.client.add_event_callback(
            self._on_message,
            RoomMessageText
        )
        logger.info("✅ Registered callback for RoomMessageText events")
        
        # Register callback for unknown events (new VoIP protocol MSC3401/MSC2746)
        # matrix-nio doesn't fully support new VoIP and maps them as UnknownEvent
        self.client.add_event_callback(
            self._on_unknown_event,
            UnknownEvent
        )
        logger.info("✅ Registered callback for UnknownEvent events")
        
        self.client.add_event_callback(
            self._on_room_member,
            InviteMemberEvent
        )
        logger.info("✅ Registered callback for InviteMemberEvent events")

        logger.info(f"Matrix bot started as {self.matrix_config.user_id}")
        self.running = True
        
    async def run(self) -> None:
        """Run the bot (sync loop)"""
        if not self.running:
            await self.start()
        
        if not self.client:
            raise RuntimeError("Client not initialized")
        
        # Verify connection to Matrix
        try:
            whoami = await self.client.whoami()
            
            # Check response type - matrix-nio returns WhoamiError for failures
            response_type = type(whoami).__name__
            
            # Check for WhoamiError (authentication failure)
            if isinstance(whoami, WhoamiError) or response_type == 'WhoamiError':
                error_msg = getattr(whoami, 'message', 'No error message')
                status_code = getattr(whoami, 'status_code', 'Unknown')
                logger.warning(f"⚠️  Matrix connection verification failed: WhoamiError")
                logger.warning(f"Error message: {error_msg}")
                logger.warning(f"Status code: {status_code}")
                
                # Try to refresh token if password is available
                if self.matrix_config.password:
                    logger.info("Attempting to refresh token using password...")
                    refreshed = await self._refresh_token_if_needed()
                    if refreshed:
                        # Retry whoami after refresh
                        whoami = await self.client.whoami()
                        if isinstance(whoami, (WhoamiError, Exception)):
                            logger.error("❌ Failed to verify Matrix connection after token refresh")
                            logger.error(f"Homeserver: {self.matrix_config.homeserver}")
                            logger.error(f"User ID: {self.matrix_config.user_id}")
                            logger.error("Sync will not start due to authentication failure")
                            return
                        else:
                            logger.info("✅ Matrix connection verified after token refresh")
                    else:
                        logger.error("❌ Failed to refresh token")
                        logger.error("Please check your MATRIX_PASSWORD")
                        logger.error(f"Homeserver: {self.matrix_config.homeserver}")
                        logger.error(f"User ID: {self.matrix_config.user_id}")
                        logger.error("Sync will not start due to authentication failure")
                        return
                else:
                    logger.error("Please check your MATRIX_ACCESS_TOKEN - it may be invalid or expired")
                    logger.error("Or provide MATRIX_PASSWORD for automatic token refresh")
                    logger.error(f"Homeserver: {self.matrix_config.homeserver}")
                    logger.error(f"User ID: {self.matrix_config.user_id}")
                    logger.error("Sync will not start due to authentication failure")
                    return
            
            # Also check if it's any exception type
            if isinstance(whoami, Exception):
                logger.error(f"❌ Failed to verify Matrix connection: {response_type}")
                logger.error(f"Exception: {whoami}")
                logger.error(f"Exception message: {getattr(whoami, 'message', str(whoami))}")
                logger.error("Please check your MATRIX_ACCESS_TOKEN and homeserver configuration")
                logger.error(f"Homeserver: {self.matrix_config.homeserver}")
                logger.error(f"User ID: {self.matrix_config.user_id}")
                logger.error("Sync will not start due to authentication failure")
                return
            
            # Success - whoami should be a WhoamiResponse object
            if isinstance(whoami, WhoamiResponse) or response_type == 'WhoamiResponse':
                user_id = getattr(whoami, 'user_id', None)
                if user_id:
                    logger.info(f"✅ Matrix connection verified: {user_id}")
                else:
                    logger.warning(f"Matrix connection verified but user_id not found in response")
                    # Still continue - may work anyway
            elif hasattr(whoami, 'user_id'):
                # Fallback: try to get user_id from response object
                user_id = whoami.user_id
                logger.info(f"✅ Matrix connection verified: {user_id}")
            else:
                # Unknown response type - log but continue
                logger.warning(f"Matrix whoami returned unexpected response type: {response_type}")
                # Don't return - may still work
                
        except Exception as e:
            logger.error(f"Failed to verify Matrix connection: {e}", exc_info=True)
            logger.error("Please check your Matrix access token and homeserver URL")
            logger.error(f"Homeserver: {self.matrix_config.homeserver}")
            logger.error(f"User ID: {self.matrix_config.user_id}")
            return
        
        logger.info("🔄 Starting Matrix sync loop...")
        
        # Log rooms the bot is in
        try:
            rooms = self.client.rooms
            room_count = len(rooms) if rooms else 0
            logger.info(f"📋 Bot is member of {room_count} rooms")
            if rooms:
                for room_id, room in rooms.items():
                    logger.info(f"   - Room: {room_id} (name: {getattr(room, 'name', 'N/A')})")
        except Exception as e:
            logger.warning(f"Could not list rooms: {e}")
        
        try:
            # Suppress matrix-nio validation warnings for next_batch
            # These warnings are non-critical and occur during sync
            import warnings
            import logging as std_logging
            
            # Temporarily suppress warnings from nio.responses
            nio_logger = std_logging.getLogger('nio.responses')
            original_level = nio_logger.level
            nio_logger.setLevel(std_logging.ERROR)  # Only show errors, not warnings
            
            try:
                logger.info("📡 Starting sync_forever...")
                await self.client.sync_forever(timeout=30000, full_state=True)
            finally:
                # Restore original log level
                nio_logger.setLevel(original_level)
        except asyncio.CancelledError:
            logger.info("Bot sync cancelled")
        except Exception as e:
            logger.error(f"Error in bot sync: {e}", exc_info=True)
            # Don't raise, just log - allow bot to continue running
            logger.warning("Bot sync error logged, continuing...")

    async def _on_message(self, room: MatrixRoom, event: RoomMessageText) -> None:
        """Callback for Matrix messages"""
        try:
            room_id = room.room_id if isinstance(room, MatrixRoom) else str(room)
            sender = getattr(event, 'sender', 'unknown')
            body = getattr(event, 'body', '')
            logger.info(f"📨 Received message in room {room_id} from {sender}: {body[:100]}")
            await self.event_handler.handle_message(room_id, event)
        except Exception as e:
            logger.error(f"Error in _on_message: {e}, room type: {type(room)}, room: {room}")
            raise

    async def _on_unknown_event(self, room: MatrixRoom, event: UnknownEvent) -> None:
        """Callback for unknown events - handles new VoIP protocol (MSC3401/MSC2746)"""
        try:
            room_id = room.room_id if isinstance(room, MatrixRoom) else str(room)
            await self.event_handler.handle_unknown_event(room_id, event)
        except Exception:
            # Don't raise - unknown events are expected
            pass

    async def _login_with_password(self) -> None:
        """Login to Matrix using password"""
        if not self.matrix_config.password:
            raise ValueError("Password not provided for login")
        
        logger.info(f"Logging in as {self.matrix_config.user_id} using password...")
        response = await self.client.login(
            password=self.matrix_config.password,
            device_name="Matrix LiveKit Bot"
        )
        
        if isinstance(response, Exception):
            error_msg = str(response)
            logger.error(f"❌ Failed to login: {error_msg}")
            raise Exception(f"Matrix login failed: {error_msg}")
        
        # Login successful - access_token is automatically set in client
        if hasattr(response, 'access_token') and response.access_token:
            self.client.access_token = response.access_token
            logger.info(f"✅ Successfully logged in, access token obtained")
        else:
            logger.warning("Login response received but no access token found")
    
    async def _refresh_token_if_needed(self) -> bool:
        """Refresh token if it's expired. Returns True if token was refreshed."""
        if not self.matrix_config.password:
            return False
        
        try:
            # Check if token is still valid
            whoami = await self.client.whoami()
            if isinstance(whoami, (WhoamiError, Exception)):
                # Token expired or invalid, refresh it
                logger.warning("Access token expired or invalid, refreshing...")
                await self._login_with_password()
                logger.info("✅ Token refreshed successfully")
                return True
        except Exception as e:
            logger.warning(f"Error checking token validity: {e}, attempting refresh...")
            try:
                await self._login_with_password()
                logger.info("✅ Token refreshed successfully")
                return True
            except Exception as refresh_error:
                logger.error(f"❌ Failed to refresh token: {refresh_error}")
                return False
        
        return False
    
    async def send_message(self, room_id: str, message: str) -> None:
        """Send a message to a Matrix room with automatic token refresh"""
        if not self.client:
            raise RuntimeError("Client not connected")
        
        logger.info(f"📤 Sending message to room {room_id}: {message[:100]}")
        
        # Try to send message
        response = await self.client.room_send(
            room_id=room_id,
            message_type="m.room.message",
            content={
                "msgtype": "m.text",
                "body": message
            }
        )
        
        # Check if we got an authentication error
        if isinstance(response, Exception):
            error_str = str(response).lower()
            # Check for 401/403 errors (authentication issues)
            if "401" in error_str or "403" in error_str or "unauthorized" in error_str or "forbidden" in error_str:
                logger.warning("Authentication error detected, attempting token refresh...")
                refreshed = await self._refresh_token_if_needed()
                if refreshed:
                    # Retry sending the message
                    logger.info("Retrying message send after token refresh...")
                    response = await self.client.room_send(
                        room_id=room_id,
                        message_type="m.room.message",
                        content={
                            "msgtype": "m.text",
                            "body": message
                        }
                    )
                    if isinstance(response, Exception):
                        logger.error(f"❌ Failed to send message after token refresh: {response}")
                    else:
                        logger.info(f"✅ Message sent successfully to room {room_id} after token refresh")
                else:
                    logger.error(f"❌ Failed to send message (token refresh failed): {response}")
            else:
                logger.error(f"❌ Failed to send message: {response}")
        else:
            logger.info(f"✅ Message sent successfully to room {room_id}")


    async def _on_room_member(self, room: MatrixRoom, event: InviteMemberEvent) -> None:
        """Callback for room member events (invites)"""
        if event.membership == "invite":
            room_id = room.room_id if isinstance(room, MatrixRoom) else room
            invited_user = getattr(event, 'state_key', 'unknown')
            logger.info(f"📩 Invited to room {room_id} (invited user: {invited_user}), joining...")
            try:
                join_response = await self.client.join(room_id)
                if isinstance(join_response, Exception):
                    logger.error(f"❌ Failed to join room {room_id}: {join_response}")
                else:
                    logger.info(f"✅ Successfully joined room {room_id}")
            except Exception as e:
                logger.error(f"❌ Error joining room {room_id}: {e}", exc_info=True)

            
    async def stop(self) -> None:
        """Stop the Matrix bot"""
        self.running = False
        
        if self._sync_task:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
        
        if self.client:
            await self.client.close()
            logger.info("Matrix bot stopped")
