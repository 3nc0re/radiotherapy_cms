from django.utils import timezone

def pending_counts(request):
    if not request.user.is_authenticated:
        return {}
    
    from patients.views import get_pending_mis_discharge_patients, get_pending_mvtn_staging_patients
    today = timezone.localdate()
    
    pending_mis = len(get_pending_mis_discharge_patients(today))
    pending_mvtn = len(get_pending_mvtn_staging_patients(today))
            
    return {
        'pending_mis_count': pending_mis,
        'pending_mvtn_count': pending_mvtn,
    }
