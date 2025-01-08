from django.urls import re_path
from core.consumers import UserNotificationConsumer

websocket_urlpatterns = [
    # user-specific notifications, e.g. ws://<host>/ws/notify/<user_id>/
    re_path(r'^ws/notify/(?P<user_id>\d+)/$', UserNotificationConsumer.as_asgi()),
]
