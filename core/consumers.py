import json
from channels.generic.websocket import AsyncWebsocketConsumer

class UserNotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        # user_id from the URL route (regex group name "user_id")
        self.user_id = self.scope['url_route']['kwargs']['user_id']
        self.group_name = f"user_{self.user_id}"

        # Join the user-specific group
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )

        # Accept the WebSocket connection
        await self.accept()

    async def disconnect(self, close_code):
        # Leave the user-specific group
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )

    async def receive(self, text_data=None, bytes_data=None):
        """
        If your frontend sends data to the backend,
        handle it here. For simple "notification only" usage,
        you might not need this at all.
        """
        # Typically not needed if we just push from server to client.

    # Handler for "new_receipt_notification" events
    async def new_receipt_notification(self, event):
        """
        This is invoked when the server does
        `channel_layer.group_send({"type": "new_receipt_notification", ...})`.
        We'll send a minimal JSON to the client instructing it to refresh.
        """

        receipt_id = event.get("receipt_id", {})
        await self.send(json.dumps({
            "type": "new_receipt_notification",
            "receipt_id": receipt_id,
        }))

    async def new_email_notification(self, event):
        """
        Expected payload from group_send:

            {
                "type":      "new_email_notification",
                "email_id":  123,
                "subject":   "Your order shipped",   # optional
                "category":  "message",              # optional
                "company":   "Amazon"                # NEW
            }
        """
        await self.send(json.dumps({
            "type":     "new_email_notification",
            "email_id": event.get("email_id"),
            "subject":  event.get("subject"),
            "category": event.get("category"),
            "company":  event.get("company"),   # <- now included
        }))
        