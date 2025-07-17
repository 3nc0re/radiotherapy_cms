from django.contrib import admin
from django.http import HttpResponseRedirect
from django.urls import path
from django.contrib import messages
from .models import User, Patient, FractionHistory, MedicalIncapacity
from .services import recalculate_discharge_date


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'treatment_start_date', 'discharge_date', 'display_stage']
    list_filter = ['treatment_start_date', 'discharge_date']
    search_fields = ['last_name', 'first_name', 'middle_name']
    
    actions = ['update_discharge_dates']
    
    def update_discharge_dates(self, request, queryset):
        updated_count = 0
        for patient in queryset:
            if patient.fractions.exists():
                old_date = patient.discharge_date
                new_date = recalculate_discharge_date(patient)
                if new_date and new_date != old_date:
                    updated_count += 1
        
        if updated_count > 0:
            self.message_user(
                request, 
                f'Успішно оновлено дати виписки для {updated_count} пацієнтів',
                messages.SUCCESS
            )
        else:
            self.message_user(
                request, 
                'Немає пацієнтів для оновлення дати виписки',
                messages.INFO
            )
    
    update_discharge_dates.short_description = "Оновити дати виписки для вибраних пацієнтів"


admin.site.register(User)
admin.site.register(FractionHistory)
admin.site.register(MedicalIncapacity)
