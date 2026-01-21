from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('register/', views.register_view, name='register'),
    path('scan/', views.scan_view, name='scan'),
    path('gallery/', views.gallery_view, name='gallery'),
    path('delete_face/<int:face_id>/', views.delete_face, name='delete_face'),
    path('delete_person/<int:person_id>/', views.delete_person, name='delete_person'),
    path('edit_face/<int:face_id>/', views.edit_face, name='edit_face'),
    path('edit_person/<int:person_id>/', views.edit_person, name='edit_person'),
    path('video_feed/', views.video_feed, name='video_feed'),
    path('cctv/', views.cctv_view, name='cctv'),
    path('cctv_feed/', views.cctv_feed, name='cctv_feed'),
    path('report/', views.report_view, name='report'),
    path('delete_log/<int:log_id>/', views.delete_log, name='delete_log'),
    path('daily-report/<str:date_str>/', views.daily_report_view, name='daily_report'),
    path('stop_camera/', views.stop_camera, name='stop_camera'),
    path('get_recognized_faces/', views.get_recognized_faces, name='get_recognized_faces'),
    path('get_camera_status/', views.get_camera_status, name='get_camera_status'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('signup/', views.signup_view, name='signup'),
    path('forgot-password/', views.forgot_password_view, name='forgot_password'),
    path('verify-otp/', views.verify_otp_view, name='verify_otp'),
    path('reset-password/', views.reset_password_view, name='reset_password'),
]
