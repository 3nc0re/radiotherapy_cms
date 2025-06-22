from django.urls import path
from . import views

urlpatterns = [
    # General
    path('', views.dashboard, name='dashboard'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('search/', views.search_patients, name='search_patients'),

    # Patients
    path('patients/', views.patient_list, name='patient_list'),
    path('patients/new/', views.patient_create, name='patient_create'), # Specific path first
    path('patients/archive/', views.patient_archive, name='patient_archive'),
    path('patients/inpatient/', views.inpatient_list, name='inpatient_list'),
    path('patients/filter/<str:filter_type>/', views.patient_list, name='patient_list_filtered'),
    path('patients/<int:pk>/', views.patient_detail, name='patient_detail'),
    path('patients/<int:pk>/edit/', views.patient_update, name='patient_update'),
    path('patients/<int:pk>/delete/', views.patient_delete, name='patient_delete'),
    
    # Fractions
    path('fractions/', views.fraction_list, name='fraction_list'),
    path('patients/<int:pk>/fractions/', views.fraction_list, name='patient_fraction_list'),
    path('patients/<int:patient_id>/generate_fractions/', views.generate_fractions, name='generate_fractions'),
    path('fractions/confirm/doctor/', views.confirm_fractions_doctor, name='confirm_fractions_doctor'),
    path('fractions/confirm/nurse/', views.confirm_fractions_nurse, name='confirm_fractions_nurse'),

    # Medical Incapacity
    path('patients/<int:patient_pk>/medical_incapacity/create/', views.medical_incapacity_create, name='medical_incapacity_create'),
    path('medical_incapacity/<int:pk>/delete/', views.medical_incapacity_delete, name='medical_incapacity_delete'),

    # Auth & Users
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.register_view, name='register'),
    path('users/', views.admin_users, name='admin_users'),
    path('users/<int:pk>/approve/', views.approve_user, name='approve_user'),

    # Misc
    path('confirm_blood_test/<int:patient_id>/', views.confirm_blood_test, name='confirm_blood_test'),
] 