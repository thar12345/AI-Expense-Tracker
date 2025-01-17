from django.urls import path
from . import views

app_name = 'email_mgmt'

urlpatterns = [
    path('emails/', views.EmailListView.as_view(), name='email-list'),
    path('emails/by-vendor/', views.EmailByCompanyView.as_view(), name='email-buckets'),
    path('emails/<int:pk>/', views.EmailDetailView.as_view(), name='email-detail'),
    path('emails/create/', views.create_email, name='create-email'), # Uploads email receipt
]