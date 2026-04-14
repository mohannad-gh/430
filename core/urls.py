from django.urls import path
from . import views

urlpatterns = [
    # Auth
    path('', views.home, name='home'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.register_view, name='register'),

    # Dashboard
    path('dashboard/', views.dashboard, name='dashboard'),

    # Teams
    path('teams/', views.teams_list, name='teams_list'),
    path('teams/create/', views.team_create, name='team_create'),
    path('teams/<int:pk>/', views.team_detail, name='team_detail'),
    path('teams/<int:pk>/availability/', views.team_availability, name='team_availability'),
    path('teams/<int:pk>/edit/', views.team_edit, name='team_edit'),
    path('teams/<int:pk>/delete/', views.team_delete, name='team_delete'),
    path('teams/<int:pk>/assign-coach/', views.assign_coach, name='assign_coach'),
    path('teams/<int:pk>/remove-coach/<int:coach_id>/', views.remove_coach, name='remove_coach'),
    path('teams/<int:pk>/request-join/', views.request_join_team, name='request_join_team'),
    path('teams/<int:pk>/request-leave/', views.request_leave_team, name='request_leave_team'),
    path('teams/<int:pk>/leave/', views.leave_team, name='leave_team'),
    path('teams/<int:pk>/requests/', views.team_join_requests, name='team_join_requests'),
    path('teams/<int:pk>/requests/<int:request_id>/review/', views.review_join_request, name='review_join_request'),
    path('teams/<int:pk>/leave-requests/', views.team_leave_requests, name='team_leave_requests'),
    path('teams/<int:pk>/leave-requests/<int:request_id>/review/', views.review_leave_request, name='review_leave_request'),
    path('teams/<int:pk>/remove-player/<int:player_id>/', views.remove_player, name='remove_player'),

    # Availability
    path('availability/', views.availability, name='availability'),

    # Sessions
    path('sessions/', views.sessions_list, name='sessions_list'),
    path('sessions/create/', views.session_create, name='session_create'),
    path('sessions/<int:pk>/', views.session_detail, name='session_detail'),
    path('sessions/<int:pk>/edit/', views.session_edit, name='session_edit'),
    path('sessions/<int:pk>/delete/', views.session_delete, name='session_delete'),
    path('sessions/<int:pk>/attendance/', views.manage_attendance, name='manage_attendance'),
    path('sessions/ai-schedule/', views.ai_schedule, name='ai_schedule'),

    # Courts
    path('courts/', views.courts_list, name='courts_list'),
    path('courts/create/', views.court_create, name='court_create'),
    path('courts/<int:pk>/edit/', views.court_edit, name='court_edit'),
    path('courts/<int:pk>/delete/', views.court_delete, name='court_delete'),

    # Announcements
    path('announcements/', views.announcements_list, name='announcements_list'),
    path('announcements/create/', views.announcement_create, name='announcement_create'),

    # Notifications
    path('notifications/', views.notifications_list, name='notifications_list'),
    path('notifications/<int:pk>/read/', views.mark_notification_read, name='mark_notification_read'),
    path('notifications/read-all/', views.mark_all_read, name='mark_all_read'),

    # Fees
    path('fees/', views.fees_list, name='fees_list'),
    path('fees/create/', views.fee_create, name='fee_create'),
    path('fees/<int:pk>/', views.fee_detail, name='fee_detail'),
    path('fees/<int:pk>/edit/', views.fee_edit, name='fee_edit'),
    path('fees/<int:pk>/delete/', views.fee_delete, name='fee_delete'),
    path('fees/<int:pk>/assign/', views.fee_assign, name='fee_assign'),
    path('fees/player/<int:pk>/pay/', views.pay_fee, name='pay_fee'),
    path('fees/summary/', views.financial_summary, name='financial_summary'),

    # Coach Earnings
    path('earnings/', views.earnings_list, name='earnings_list'),
    path('payouts/', views.payouts, name='payouts'),
    path('payouts/<int:pk>/edit/', views.payout_edit, name='payout_edit'),
    path('payouts/<int:pk>/delete/', views.payout_delete, name='payout_delete'),
    path('payouts/record/<int:session_id>/<int:coach_id>/', views.payout_record, name='payout_record'),

    # Users
    path('users/', views.users_list, name='users_list'),
    path('users/<int:pk>/edit/', views.user_edit, name='user_edit'),
]
