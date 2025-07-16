# Tests file

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from datetime import date, timedelta
from .models import Patient, FractionHistory

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

    def test_summary_text_property(self):
        patient = Patient.objects.create(
            last_name='Тестовий',
            first_name='Пацієнт',
            diagnosis='Са прямої кишки',
            tnm_staging='T2N0M0',
            disease_stage='II',
            clinical_group='2',
            histology_number='123',
            histology_date=date(2025, 1, 28),
            histology_description='Аденокарцинома (G2)'
        )

        summary = patient.summary_text
        self.assertIn('T2N0M0', summary)
        self.assertIn('Аденокарцинома', summary)


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

    def test_summary_text_displayed(self):
        self.client.login(username='testuser', password='testpass123')
        self.patient.tnm_staging = 'T2N0M0'
        self.patient.histology_description = 'Carcinoma'
        self.patient.save()

        response = self.client.get(reverse('patient_detail', kwargs={'pk': self.patient.pk}))
        self.assertContains(response, 'T2N0M0')
        self.assertContains(response, 'Carcinoma')
    
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

