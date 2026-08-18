from django.utils import timezone

def pending_counts(request):
    if not request.user.is_authenticated:
        return {}
    
    from patients.models import Patient
    today = timezone.localdate()
    
    patients = Patient.objects.filter(mis_discharged=False).prefetch_related('fractions')
    pending_mis_count = 0
    for p in patients:
        actual_discharge = p.get_actual_discharge_date or p.discharge_date
        if actual_discharge and actual_discharge <= today:
            pending_mis_count += 1
            
    return {
        'pending_mis_count': pending_mis_count
    }
