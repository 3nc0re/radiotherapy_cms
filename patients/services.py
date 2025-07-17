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
    
    # Завжди встановлюємо дату виписки на основі останньої фракції
    if fractions:
        patient.discharge_date = fractions[-1].date
        patient.save()
        print(f"Встановлено дату виписки для {patient.full_name}: {patient.discharge_date}")
    
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
    # Знаходимо останню заплановану фракцію
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

def postpone_fraction(fraction, new_date, reason=""):
    """Відкладає фракцію на нову дату"""
    if not fraction.original_date:
        fraction.original_date = fraction.date
    
    fraction.date = new_date
    fraction.is_postponed = True
    fraction.reason = reason
    fraction.save()
    
    # Перераховуємо дату виписки
    recalculate_discharge_date(fraction.patient)
    return fraction

def mark_fraction_missed(fraction, reason=""):
    """Позначає фракцію як пропущену"""
    fraction.is_missed = True
    fraction.reason = reason
    fraction.save()
    return fraction

def get_missed_fractions_count(patient):
    """Підраховує кількість пропущених фракцій"""
    return patient.fractions.filter(is_missed=True).count()

def get_postponed_fractions_count(patient):
    """Підраховує кількість відкладених фракцій"""
    return patient.fractions.filter(is_postponed=True).count() 