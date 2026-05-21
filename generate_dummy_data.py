import os
import django
from datetime import date, timedelta
import random

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cms_django.settings')
django.setup()

from patients.models import Patient, FractionHistory

def create_dummy_data():
    print("Deleting old dummy data...")
    test_patients = Patient.objects.filter(last_name__startswith='Тестовий')
    FractionHistory.objects.filter(patient__in=test_patients).delete()
    test_patients.delete()
    
    first_names = ['Іван', 'Петро', 'Олександр', 'Михайло', 'Василь', 'Марія', 'Олена', 'Оксана', 'Наталія']
    last_names = ['Тестовий', 'Тестова']
    middle_names = ['Іванович', 'Петрович', 'Олександрович', 'Іванівна', 'Петрівна']
    
    diagnoses = ['С34.1 Злоякісне новоутворення верхньої частки бронха або легень', 'С50.9 Злоякісне новоутворення молочної залози, неуточнене']
    
    today = date.today()
    
    patients_created = 0
    fractions_created = 0
    
    for i in range(5):
        is_male = random.choice([True, False])
        gender_code = 'Ч' if is_male else 'Ж'
        last_name = last_names[0] if is_male else last_names[1]
        
        # Create a patient
        patient = Patient.objects.create(
            ambulatory_card_id=f"{random.randint(100000, 999999)}/26",
            last_name=f"{last_name}_{i+1}",
            first_name=random.choice(first_names),
            middle_name=random.choice(middle_names),
            birth_date=date(1960 + random.randint(0, 30), random.randint(1, 12), random.randint(1, 28)),
            gender=gender_code,
            diagnosis=random.choice(diagnoses),
            disease_stage=random.choice(['IIA', 'IIB', 'III', 'IV']),
            total_fractions=random.randint(15, 30),
            dose_per_fraction=random.choice([2.0, 2.5, 3.0]),
            treatment_start_date=today - timedelta(days=random.randint(5, 15)),
            inpatient_status='амбулаторно'
        )
        patient.received_dose = patient.total_fractions * patient.dose_per_fraction
        patient.save()
        patients_created += 1
        
        # The post_save signal automatically generates all fractions.
        # So we just need to take the first few generated fractions and update them.
        generated_fractions = list(FractionHistory.objects.filter(patient=patient).order_by('date'))
        
        past_fractions_count = random.randint(5, 10)
        
        for j in range(min(past_fractions_count, len(generated_fractions))):
            fraction = generated_fractions[j]
            
            # Make the last 2-3 fractions delivered but NOT confirmed by doctor
            if j >= past_fractions_count - 3:
                fraction.delivered = True
                fraction.confirmed_by_doctor = False
            else:
                fraction.delivered = True
                fraction.confirmed_by_doctor = True
                
            fraction.save()
            fractions_created += 1
            
    print(f"Successfully created {patients_created} test patients and {fractions_created} fractions!")

if __name__ == '__main__':
    create_dummy_data()
