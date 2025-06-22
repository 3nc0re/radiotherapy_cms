from datetime import date, timedelta
from .models import Patient, FractionHistory

def generate_fractions_for_patient(patient, start_date=None, total_fractions=None, dose_per_fraction=None):
    """Генерує фракції для пацієнта"""
    if not start_date:
        start_date = patient.treatment_start_date
    if not total_fractions:
        total_fractions = patient.total_fractions
    if not dose_per_fraction:
        dose_per_fraction = patient.dose_per_fraction
    
    if not all([start_date, total_fractions, dose_per_fraction]):
        return False
    
    # Видаляємо існуючі фракції
    FractionHistory.objects.filter(patient=patient).delete()
    
    # Генеруємо нові фракції
    fractions = []
    current_date = start_date
    
    for i in range(total_fractions):
        # Пропускаємо вихідні (субота, неділя)
        while current_date.weekday() >= 5:  # 5=субота, 6=неділя
            current_date += timedelta(days=1)
        
        fraction = FractionHistory(
            patient=patient,
            date=current_date,
            dose=dose_per_fraction,
            delivered=False,
            confirmed_by_doctor=False
        )
        fractions.append(fraction)
        current_date += timedelta(days=1)
    
    FractionHistory.objects.bulk_create(fractions)
    return True

def auto_confirm_today_fractions():
    """Автоматично підтверджує фракції за сьогодні"""
    today = date.today()
    today_fractions = FractionHistory.objects.filter(date=today)
    
    for fraction in today_fractions:
        fraction.delivered = True
        fraction.confirmed_by_doctor = True
        fraction.save()
    
    return today_fractions.count()

def get_patient_treatment_info(patient):
    """Отримує інформацію про лікування пацієнта"""
    total_fractions = patient.total_fractions or 0
    completed_fractions = patient.fractions.filter(delivered=True).count()
    remaining_fractions = total_fractions - completed_fractions
    
    return {
        'total_fractions': total_fractions,
        'completed_fractions': completed_fractions,
        'remaining_fractions': remaining_fractions,
        'progress_percentage': (completed_fractions / total_fractions * 100) if total_fractions > 0 else 0
    } 