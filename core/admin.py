from django.contrib import admin
from .models import UserProfile, Team, Court, Availability, Session, Attendance, Announcement, Notification, Fee, PlayerFee, CoachEarning

admin.site.register(UserProfile)
admin.site.register(Team)
admin.site.register(Court)
admin.site.register(Availability)
admin.site.register(Session)
admin.site.register(Attendance)
admin.site.register(Announcement)
admin.site.register(Notification)
admin.site.register(Fee)
admin.site.register(PlayerFee)
admin.site.register(CoachEarning)
