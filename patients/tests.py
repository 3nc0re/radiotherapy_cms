# Tests file

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from datetime import date, timedelta
from .models import Patient, FractionHistory
from .forms import PatientForm

User = get_user_model()

class CriticalModelTests(TestCase):
    """Критичні тести моделей - можуть викликати падіння сервісу"""
    
    def test_patient_creation_minimal(self):
        """Тест створення пацієнта з мінімальними даними"""
        patient = Patient.objects.create(
            last_name='Тестовий',
            first_name='Пацієнт',
            diagnosis='Тестовий діагноз'
        )
        self.assertIsNotNone(patient.id)
        self.assertEqual(patient.full_name, 'Тестовий Тестовий Пацієнт')
    
    def test_display_stage_property(self):
        """Тест властивості display_stage - критична для відображення"""
        patient = Patient.objects.create(
            last_name='Тестовий',
            first_name='Пацієнт',
            diagnosis='Тестовий діагноз',
            treatment_start_date=date.today() - timedelta(days=5)
        )
        
        # Тест для пацієнта в лікуванні
        self.assertEqual(patient.display_stage, "Лікування")
        
        # Тест для пацієнта в архіві
        patient.discharge_date = date.today() - timedelta(days=1)
        patient.save()
        self.assertEqual(patient.display_stage, "Архів")
    
    def test_current_fraction_property(self):
        """Тест властивості current_fraction - критична для розрахунків"""
        patient = Patient.objects.create(
            last_name='Тестовий',
            first_name='Пацієнт',
            diagnosis='Тестовий діагноз'
        )
        
        # Створюємо фракції
        FractionHistory.objects.create(
            patient=patient,
            date=date.today() - timedelta(days=1),
            dose=2.0,
            delivered=True
        )
        
        self.assertEqual(patient.current_fraction, 1)


class CriticalViewsTests(TestCase):
    """Критичні тести представлень - можуть викликати падіння сервісу"""
    
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            role='doctor',
            approved=True
        )
        
        self.patient = Patient.objects.create(
            last_name='Тестовий',
            first_name='Пацієнт',
            diagnosis='Тестовий діагноз'
        )
    
    def test_dashboard_view_requires_login(self):
        """Тест що дашборд вимагає авторизації"""
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 302)  # Redirect to login
        
        # Після авторизації
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
    
    def test_patient_list_view(self):
        """Тест списку пацієнтів - критична функція"""
        self.client.login(username='testuser', password='testpass123')
        
        response = self.client.get(reverse('patient_list'))
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.patient, response.context['patients'])
    
    def test_patient_detail_view(self):
        """Тест деталей пацієнта - критична функція"""
        self.client.login(username='testuser', password='testpass123')
        
        response = self.client.get(reverse('patient_detail', kwargs={'pk': self.patient.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['patient'], self.patient)
    
    def test_nonexistent_patient_detail(self):
        """Тест обробки неіснуючого пацієнта - критична для стабільності"""
        self.client.login(username='testuser', password='testpass123')
        
        response = self.client.get(reverse('patient_detail', kwargs={'pk': 99999}))
        self.assertEqual(response.status_code, 404)


class CriticalURLTests(TestCase):
    """Критичні тести URL-ів - можуть викликати падіння сервісу"""
    
    def setUp(self):
        self.client = Client()
    
    def test_critical_urls_require_login(self):
        """Тест що критичні URL вимагають авторизації"""
        critical_urls = [
            'dashboard',
            'patient_list',
            'patient_create',
            'fraction_list'
        ]
        
        for url_name in critical_urls:
            response = self.client.get(reverse(url_name))
            self.assertEqual(response.status_code, 302)  # Redirect to login
    
    def test_login_url_accessible(self):
        """Тест що сторінка логіну доступна"""
        response = self.client.get(reverse('login'))
        self.assertEqual(response.status_code, 200)
    
    def test_register_url_accessible(self):
        """Тест що сторінка реєстрації доступна"""
        response = self.client.get(reverse('register'))
        self.assertEqual(response.status_code, 200)


class CriticalErrorHandlingTests(TestCase):
    """Критичні тести обробки помилок - можуть викликати падіння сервісу"""
    
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            role='doctor',
            approved=True
        )
    
    def test_invalid_patient_id_handling(self):
        """Тест обробки невалідного ID пацієнта"""
        self.client.login(username='testuser', password='testpass123')
        
        # Неіснуючий ID
        response = self.client.get(reverse('patient_detail', kwargs={'pk': 99999}))
        self.assertEqual(response.status_code, 404)
    
    def test_invalid_url_handling(self):
        """Тест обробки невалідних URL"""
        response = self.client.get('/patients/nonexistent/')
        self.assertEqual(response.status_code, 404)


class PatientFormDateTest(TestCase):
    """Тести для перевірки правильного форматування дат у формі пацієнта"""
    
    def setUp(self):
        # Створюємо тестового користувача
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            role='doctor',
            approved=True
        )
        self.client = Client()
        self.client.login(username='testuser', password='testpass123')
        
        # Створюємо тестового пацієнта з датами
        self.patient = Patient.objects.create(
            last_name='Тестовий',
            first_name='Пацієнт',
            birth_date=date(1980, 5, 15),
            ct_simulation_date=date(2024, 3, 20),
            treatment_start_date=date(2024, 4, 1),
            discharge_date=date(2024, 6, 30),
            last_blood_test_date=date(2024, 4, 15),
            histology_date=date(2024, 2, 10)
        )
    
    def test_patient_form_date_formatting(self):
        """Тест перевіряє, що дати правильно форматуются у формі редагування"""
        # Створюємо форму з існуючим пацієнтом
        form = PatientForm(instance=self.patient)
        
        # Перевіряємо, що дати відображаються у правильному форматі
        self.assertEqual(form.initial.get('birth_date'), '15.05.1980')
        self.assertEqual(form.initial.get('ct_simulation_date'), '20.03.2024')
        self.assertEqual(form.initial.get('treatment_start_date'), '01.04.2024')
        self.assertEqual(form.initial.get('discharge_date'), '30.06.2024')
        self.assertEqual(form.initial.get('last_blood_test_date'), '15.04.2024')
        self.assertEqual(form.initial.get('histology_date'), '10.02.2024')
    
    def test_patient_edit_page_loads_with_correct_dates(self):
        """Тест перевіряє, що сторінка редагування завантажується з правильними датами"""
        response = self.client.get(reverse('patient_update', kwargs={'pk': self.patient.pk}))
        self.assertEqual(response.status_code, 200)
        
        # Перевіряємо, що форма містить правильні дати
        form = response.context['form']
        self.assertEqual(form.initial.get('birth_date'), '15.05.1980')
        self.assertEqual(form.initial.get('treatment_start_date'), '01.04.2024')
    
    def test_patient_form_saves_dates_correctly(self):
        """Тест перевіряє, що форма правильно зберігає дати"""
        form_data = {
            'last_name': 'Тестовий',
            'first_name': 'Пацієнт',
            'birth_date': '20.12.1985',
            'ct_simulation_date': '25.03.2024',
            'treatment_start_date': '01.04.2024',
            'discharge_date': '30.06.2024',
            'last_blood_test_date': '15.04.2024',
            'histology_date': '10.02.2024'
        }
        
        form = PatientForm(data=form_data, instance=self.patient)
        self.assertTrue(form.is_valid())
        
        patient = form.save()
        self.assertEqual(patient.birth_date, date(1985, 12, 20))
        self.assertEqual(patient.ct_simulation_date, date(2024, 3, 25))
    
    def test_diagnosis_text_generation(self):
        """Тест перевіряє правильне формування тексту діагнозу для копіювання"""
        # Оновлюємо пацієнта з повними даними діагнозу
        self.patient.diagnosis = 'Са правої молочної залози'
        self.patient.tnm_staging = 'T4N0M0'
        self.patient.disease_stage = 'IIIA'
        self.patient.clinical_group = '2'
        self.patient.treatment_type = 'радикальне'
        self.patient.histology_number = '46779-90'
        self.patient.histology_date = date(2024, 11, 22)
        self.patient.histology_description = 'Внутрішньопротоковий інвазивний Са (G2), mts в л/в'
        self.patient.save()
        
        # Перевіряємо згенерований текст
        expected_text = "Са правої молочної залози. T4N0M0. gr. IIIA. кл. гр. 2. Стан після радикального лікування. ПГЗ № 46779-90 від 22.11.2024. - Внутрішньопротоковий інвазивний Са (G2), mts в л/в"
        self.assertEqual(self.patient.get_diagnosis_text_for_copy(), expected_text)
