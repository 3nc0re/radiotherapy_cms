from django.contrib import admin
from .models import User, Patient, FractionHistory, MedicalIncapacity

admin.site.register(User)
admin.site.register(Patient)
admin.site.register(FractionHistory)
admin.site.register(MedicalIncapacity)
