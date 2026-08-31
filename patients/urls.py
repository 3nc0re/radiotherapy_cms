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
    path('patients/blood-tests/', views.patient_blood_tests, name='patient_blood_tests'),
    path('patients/mis-discharge/', views.mis_discharge_list, name='mis_discharge_list'),
    path('patients/mvtn-control/', views.mvtn_control_list, name='mvtn_control_list'),
    path('api/patients/<int:pk>/confirm-mis-discharge/', views.confirm_mis_discharge_api, name='confirm_mis_discharge_api'),
    path('api/patients/<int:pk>/confirm-no-mvtn/', views.confirm_no_mvtn_api, name='confirm_no_mvtn_api'),
    path('api/patients/<int:pk>/undo-no-mvtn/', views.undo_no_mvtn_api, name='undo_no_mvtn_api'),
    path('api/patients/<int:pk>/save-mvtn-staging/', views.save_mvtn_staging_api, name='save_mvtn_staging_api'),
    path('api/patients/<int:pk>/quick-update/', views.quick_update_patient_api, name='quick_update_patient_api'),
    path('patients/filter/<str:filter_type>/', views.patient_list, name='patient_list_filtered'),
    path('patients/<int:pk>/', views.patient_detail, name='patient_detail'),
    path('patients/<int:pk>/edit/', views.patient_update, name='patient_update'),
    path('patients/<int:pk>/archive/', views.archive_patient, name='archive_patient'),
    path('patients/<int:pk>/admit/', views.admit_patient, name='admit_patient'),
    path('patients/<int:pk>/update_notes/', views.update_patient_notes, name='update_patient_notes'),
    path('patients/<int:pk>/delete/', views.patient_delete, name='patient_delete'),
    
    # Fractions
    path('fractions/', views.fraction_list, name='fraction_list'),
    path('fractions/save-today/', views.save_today_fractions, name='save_today_fractions'),
    path('patients/<int:pk>/fractions/', views.fraction_list, name='patient_fraction_list'),
    path('patients/<int:patient_id>/generate_fractions/', views.generate_fractions, name='generate_fractions'),
    path('patients/<int:pk>/approve-all/', views.approve_all_fractions, name='approve_all_fractions'),
    path('patients/<int:patient_id>/recalculate_discharge/', views.recalculate_discharge, name='recalculate_discharge'),
    path('fractions/<int:pk>/edit/', views.fraction_edit, name='fraction_edit'),
    path('api/update-fraction-status/', views.update_fraction_status_api, name='update_fraction_status_api'),
    path('fractions/confirm/doctor/', views.confirm_fractions_doctor, name='confirm_fractions_doctor'),
    path('fractions/confirm/nurse/', views.confirm_fractions_nurse, name='confirm_fractions_nurse'),
    path('fractions/auto-confirm/', views.auto_confirm_fractions, name='auto_confirm_fractions'),
    path('api/fractions/bulk-confirm-preview/', views.bulk_confirm_preview_api, name='bulk_confirm_preview_api'),
    path('api/fractions/bulk-confirm-period/', views.bulk_confirm_period_api, name='bulk_confirm_period_api'),
    path('api/patients/<int:patient_id>/bulk-confirm-up-to-date/', views.bulk_confirm_patient_up_to_date_api, name='bulk_confirm_patient_up_to_date_api'),

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
    path('update_all_discharge_dates/', views.update_all_discharge_dates, name='update_all_discharge_dates'),
    
    # API endpoints for PIN & Confidential Notes
    path('api/user/set-pin/', views.set_user_pin, name='set_user_pin'),
    path('api/patients/<int:pk>/decrypt-notes/', views.decrypt_patient_notes, name='decrypt_patient_notes'),
    path('api/patients/<int:pk>/encrypt-notes/', views.encrypt_patient_notes, name='encrypt_patient_notes'),
    path('api/fractions/<int:pk>/toggle-status/', views.toggle_fraction_status, name='toggle_fraction_status'),
    path('api/fractions/<int:pk>/update-note/', views.update_fraction_note_api, name='update_fraction_note_api'),
    path('api/patients/<int:pk>/add-fraction/', views.add_patient_fraction_api, name='add_patient_fraction_api'),
    
    # AI Assistant endpoints
    path('patients/<int:pk>/ai/save_notes/', views.save_ai_notes, name='save_ai_notes'),
    path('patients/<int:pk>/ai/generate_doc/<str:doc_type>/', views.generate_ai_doc, name='generate_ai_doc'),
    path('patients/<int:pk>/ai/save_doc_text/', views.save_ai_doc_text, name='save_ai_doc_text'),
    path('patients/<int:pk>/ai/generate_diary/', views.generate_ai_diary, name='generate_ai_diary'),
    path('patients/<int:pk>/ai/save_diary/<int:diary_id>/', views.save_ai_diary, name='save_ai_diary'),
    path('patients/<int:pk>/ai/delete_diary/<int:diary_id>/', views.delete_ai_diary, name='delete_ai_diary'),
] 