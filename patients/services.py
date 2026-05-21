from datetime import date, timedelta
from django.db.models import Q
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
            status='scheduled'
        )
        fractions.append(fraction)
        current_date += timedelta(days=1)
    
    FractionHistory.objects.bulk_create(fractions)
    
    # Завжди встановлюємо дату виписки на основі останньої фракції
    if fractions:
        patient.discharge_date = fractions[-1].date
        patient.save()
        print(f"Встановлено дату виписки для {patient.full_name}: {patient.discharge_date}")
    
    return True

def auto_confirm_today_fractions():
    """Автоматично підтверджує фракції за сьогодні"""
    today = date.today()
    active_patients_q = Q(discharge_date__isnull=True) | Q(discharge_date__gte=today)
    active_patients = Patient.objects.filter(active_patients_q)
    
    today_fractions = FractionHistory.objects.filter(
        date=today,
        patient__in=active_patients,
        status='scheduled'
    )
    
    count = today_fractions.count()
    if count > 0:
        today_fractions.update(status='delivered')
        for patient in active_patients:
            patient.recalculate_received_dose()
            
    return count

def get_patient_treatment_info(patient):
    """Отримує інформацію про лікування пацієнта"""
    total_fractions = patient.total_fractions or 0
    completed_fractions = patient.fractions.filter(status='delivered').count()
    remaining_fractions = total_fractions - completed_fractions
    
    return {
        'total_fractions': total_fractions,
        'completed_fractions': completed_fractions,
        'remaining_fractions': remaining_fractions,
        'progress_percentage': (completed_fractions / total_fractions * 100) if total_fractions > 0 else 0
    }

def calculate_discharge_date(patient):
    """Розраховує очікувану дату виписки на основі фракцій"""
    if not patient.treatment_start_date or not patient.total_fractions:
        return None
    
    # Рахуємо робочі дні для всіх фракцій
    current_date = patient.treatment_start_date
    working_days = 0
    
    while working_days < patient.total_fractions:
        if current_date.weekday() < 5:  # Пн-Пт
            working_days += 1
        current_date += timedelta(days=1)
    
    return current_date - timedelta(days=1)

def recalculate_discharge_date(patient):
    """Перераховує дату виписки на основі поточних фракцій"""
    # Знаходимо останню фракцію
    last_fraction = patient.fractions.order_by('date').last()
    if last_fraction:
        patient.discharge_date = last_fraction.date
        patient.save()
        return patient.discharge_date
    return None

def set_discharge_date_from_fractions(patient):
    """Встановлює дату виписки на основі згенерованих фракцій"""
    if patient.fractions.exists():
        last_fraction = patient.fractions.order_by('date').last()
        patient.discharge_date = last_fraction.date
        patient.save()
        return patient.discharge_date
    return None

def shift_patient_schedule(patient, from_date):
    """
    Зсуває всі заплановані фракції пацієнта, починаючи з from_date,
    на 1 день вперед (пропускаючи вихідні).
    """
    scheduled_fractions = list(patient.fractions.filter(status='scheduled', date__gte=from_date).order_by('date'))
    for fraction in scheduled_fractions:
        new_date = fraction.date + timedelta(days=1)
        while new_date.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
            new_date += timedelta(days=1)
        fraction.date = new_date
        fraction.save()
    
    # Оновлюємо discharge_date на основі дати останньої фракції
    recalculate_discharge_date(patient)