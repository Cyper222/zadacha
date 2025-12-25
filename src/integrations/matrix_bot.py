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
        self.client.access_token = self.matrix_config.access_token
        
        # Login if needed
        if not self.client.access_token:
            logger.info("No access token provided, attempting login...")
            response = await self.client.login(password="")
            if isinstance(response, Exception):
                raise Exception(f"Failed to login: {response}")
        else:
            logger.info(f"Using provided access token for {self.matrix_config.user_id}")
        
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
        
        # Register callback for unknown events (new VoIP protocol MSC3401/MSC2746)
        # matrix-nio doesn't fully support new VoIP and maps them as UnknownEvent
        self.client.add_event_callback(
            self._on_unknown_event,
            UnknownEvent
        )
        
        self.client.add_event_callback(
            self._on_room_member,
            InviteMemberEvent
        )

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
            response_type_class = type(whoami)
            
            logger.debug(f"Matrix whoami response type: {response_type} ({response_type_class})")
            
            # Check for WhoamiError (authentication failure)
            if isinstance(whoami, WhoamiError) or response_type == 'WhoamiError':
                error_msg = getattr(whoami, 'message', 'No error message')
                status_code = getattr(whoami, 'status_code', 'Unknown')
                logger.error(f"❌ Failed to verify Matrix connection: WhoamiError")
                logger.error(f"Error message: {error_msg}")
                logger.error(f"Status code: {status_code}")
                logger.error("Please check your MATRIX_ACCESS_TOKEN - it may be invalid or expired")
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
                logger.debug(f"Response attributes: {[attr for attr in dir(whoami) if not attr.startswith('_')]}")
                # Don't return - may still work
                
        except Exception as e:
            logger.error(f"Failed to verify Matrix connection: {e}", exc_info=True)
            logger.error("Please check your Matrix access token and homeserver URL")
            logger.error(f"Homeserver: {self.matrix_config.homeserver}")
            logger.error(f"User ID: {self.matrix_config.user_id}")
            return
        
        logger.info("🔄 Starting Matrix sync loop...")
        
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
            await self.event_handler.handle_message(room_id, event)
        except Exception as e:
            logger.error(f"Error in _on_message: {e}, room type: {type(room)}, room: {room}")
            raise

    async def _on_unknown_event(self, room: MatrixRoom, event: UnknownEvent) -> None:
        """Callback for unknown events - handles new VoIP protocol (MSC3401/MSC2746)"""
        try:
            room_id = room.room_id if isinstance(room, MatrixRoom) else str(room)
            await self.event_handler.handle_unknown_event(room_id, event)
        except Exception as e:
            logger.debug(f"Error in _on_unknown_event: {e}, room type: {type(room)}, event type: {getattr(event, 'type', 'unknown')}")
            # Don't raise - unknown events are expected

    async def send_message(self, room_id: str, message: str) -> None:
        """Send a message to a Matrix room"""
        if not self.client:
            raise RuntimeError("Client not connected")
        
        response = await self.client.room_send(
            room_id=room_id,
            message_type="m.room.message",
            content={
                "msgtype": "m.text",
                "body": message
            }
        )
        
        if isinstance(response, Exception):
            logger.error(f"Failed to send message: {response}")
        else:
            logger.debug(f"Message sent to {room_id}")


    async def _on_room_member(self, room: MatrixRoom, event: InviteMemberEvent) -> None:
        """Callback for room member events (invites)"""
        if event.membership == "invite":
            room_id = room.room_id if isinstance(room, MatrixRoom) else room
            logger.info(f"Invited to room {room_id}, joining")
            await self.client.join(room_id)

            
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
