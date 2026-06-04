from django.urls import path
from django.contrib.auth import views as auth_views
import app.views.index_views as index
import app.views.dashboard as dashboard_views
import app.views.ux as ux
from app.views.classes import *
from app.views.school_settings import *
from app.views.student import *
from app.views.subject_views import *
from app.views.staffs_views import *
from app.views.fees_view import *
from app.views.finance import *
from app.views.communications import *
from app.views.results import *
from app.views.accounts import *
from app.views.timetables import *
from app.views.attendance import *
from app.decorators.mode import primary_mode_required


def primary(view):
    return primary_mode_required(view)


urlpatterns = [
    path('index/', index.index_view, name="index_page"),
    path('search/', index.global_search_view, name="global_search"),
    path('coming-soon/', index.under_construction_view, name="under_construction"),
    path('operations/', ux.operations_center_view, name="operations_center"),
    path('setup-checklist/', ux.setup_checklist_view, name="setup_checklist"),
    path('fees/quick-payment/', ux.bursar_quick_payment_view, name="bursar_quick_payment"),
    path('dashboard/overview/', dashboard_views.dashboard_overview_view, name='dashboard_overview'),
    path('dashboard/finance/', dashboard_views.dashboard_finance_view, name='dashboard_finance'),
    path('dashboard/academics/', dashboard_views.dashboard_academics_view, name='dashboard_academics'),
    path('dashboard/attendance/', dashboard_views.dashboard_attendance_view, name='dashboard_attendance'),
    path('dashboard/reports/', dashboard_views.dashboard_reports_view, name='dashboard_reports'),

    # School Details
    path('settings/', settings_page,name="settings_page"),
    path('update_settings/', update_school_settings, name="update_settings_page"),
    path('switch-school-level/', switch_active_school_level, name='switch_school_level'),
    # Sections
    path('sections/', school_section_view, name="section_page"),
    path('edit_section/<int:id>/', edit_section_view, name="edit_section"),
    path('delete_section/<int:id>/', delete_section_view, name="delete_section"),
    
    #Signatures
    path('signature/', add_signature_view, name="add_signature_page"),
    path('edit_signature/<int:id>/', edit_signature_view, name="edit_signature"),
    path('delete_signature/<int:id>/', delete_signature_view, name="delete_signature"),
    
    #Departments
    path('department/', add_department_view, name="add_department_page"),
    path('edit_department/<int:id>/', edit_department_view, name="edit_department"),
    path('delete_department/<int:id>/', delete_department_view, name="delete_department"),
    
    #Classes
    path('classes/', class_view, name="class_page"),
    path('edit_class/<int:id>/', edit_classe_view,name="edit_class"),
    path('delete_class/<int:id>/',delete_class_view, name="delete_class"),
    path('class-stream/edit/<int:id>/', edit_class_stream, name="edit_class_stream"),
    path('class-stream/delete/<int:id>/', delete_class_stream, name="delete_class_stream"),

    
    
    #Stream
    path('stream/', stream_view, name="stream_page"),
    path('edit_stream/<int:id>/',edit_stream, name="edit_stream"),
    path('delete_stream/<int:id>/', delete_stream_view, name="delete_stream"),
   
    #Academic Class
    path('academic_classes/', academic_class_view, name="academic_class_page"),
    path('academic_classes/bulk-action/', bulk_academic_class_action_view, name="academic_class_bulk_action"),
    path('academic_classes/student-promotion/', student_promotion_workflow, name="student_promotion_workflow"),
    path('academic_class_details/<int:id>/', academic_class_details_view, name="academic_class_details_page"),
    path(
        'academic_class_details/<int:id>/promote/',
        promote_academic_class_students,
        name='promote_academic_class_students',
    ),
    path('add_class_stream/<int:id>/', add_class_stream, name="add_class_stream_page"),
    path('edit_academic_class_details/<int:id>/', edit_academic_class_details_view,name="edit_academic_class_details_page"),
    path('delete_academic_class/<int:id>/',delete_academic_class_view,name="delete_academic_class"),
    
    #Student
    path('students/', manage_student_view, name="student_page"),
    path('students/export/', export_students_csv_view, name="students_export_csv"),
    path('students/bulk-action/', student_bulk_action_view, name="students_bulk_action"),
    path('students/<int:id>/summary/', student_summary_api_view, name="student_summary_api"),
    path('add_student/', add_student_view, name="add_student"),
    path('students/quick-create-academic-class/', quick_create_academic_class_view, name="quick_create_academic_class"),
    path('students/quick-create-class-stream/', quick_create_class_stream_view, name="quick_create_class_stream"),
    path('student_details/<int:id>/', student_details_view, name="student_details_page"),
    path('student_details/<int:id>/attendance/', student_details_attendance_redirect_view, name="student_details_attendance_tab"),
    path('student_details/<int:id>/Attendance', student_details_attendance_redirect_view),
    path('student/<int:id>/upload-document/', upload_student_document, name='upload_student_document'),
    path('student/document/delete/<int:id>/', delete_student_document, name='delete_student_document'),
    path('student/<int:id>/exam-report/download/', primary(download_student_exam_report), name='download_student_exam_report'),
    path('student/<int:id>/exam-report/view/', primary(view_student_exam_report), name='view_student_exam_report'),
    path('download_student_template/', download_student_template_csv, name="download_student_template"),
    path('bulk_student_registration/', bulk_student_registration_view, name="bulk_student_registration"),
    path('edit_student/<int:id>/', edit_student_view, name="edit_student_page"),
    path('delete_student/<int:id>/', delete_student_view, name="delete_student_page"),
    path("register/", bulk_register_students, name="bulk_register_students"),# student registration in classes
    
    
    #Subject
    path('subjects/', manage_subjects_view, name="subjects_page"),
    path('add_subject/', add_subject_view, name="add_subject_page"),
    path('edit_subject/<int:id>/', edit_subject_view, name="edit_subject_page"),
    path('delete_subject/<int:id>/', delete_subject_view, name="delete_subject_page"),
    
    #Subject Allocation
    path('subject_allocation/', add_class_subject_allocation, name="subject_allocation_page"),
    path('subject_allocation_list/',class_subject_allocation_list,name= "class_subject_allocation_page"),
    path('edit_subject_allocation/<int:id>/',edit_subject_allocation_view, name="edit_subject_allocation_page"),
    path('delete_subject_allocation/<int:id>/',delete_class_subject_allocation, name="delete_subject_allocation"),
    path('copy_allocations/',copy_allocations_from_previous_term, name="copy_allocations"),
    
    #Staff
    path('staff/<int:id>/upload-document/', staff_details_view, name='upload_staff_document'),
    path('staffs/', manage_staff_view, name="staff_page"),
    path('add_staff/', add_staff, name="add_staff"),
    path('staff_details/<int:id>/', staff_details_view, name="staff_details_page"),
    path('edit_staff_details/<int:id>/', edit_staff_details_view, name="edit_staff_details_page"),
    path('delete_staff/<int:id>/', delete_staff_view, name="delete_staff_page"),
    path('staff/document/delete/<int:id>/', delete_staff_document, name='delete_staff_document'),

    #Fees
    path('bill_items/', manage_bill_items_view, name="bill_item_page"),
    path('add_bill_item/', add_bill_item_view, name="add_bill_item_page"),
    path('edit_bill_item/<int:id>/', edit_bill_item_view, name="edit_bill_item_page"),
    path('delete_bill_item/<int:id>/',delete_bill_item_view, name="delete_bill_item_page"), 
    path('student_bill/', manage_student_bills_view, name="student_bill_page"),
    path('student_bill_details/<int:id>/', manage_student_bill_details_view, name="student_bill_details_page"),
    path('add_student_bill_item/<int:id>/', add_student_bill_item_view, name="add_student_bill_item"),
    path('add_class_bill_item/<int:id>/add-bill/', add_class_bill_item_view, name="add_class_bill_items"),
    path('record_payment/<int:id>/', add_student_payment_view, name="record_payment"),
    path('ajax-payment-form/<int:bill_id>/', ajax_payment_form_view, name="ajax_payment_form"),
    path('bill/<int:id>/upload-document/', upload_bill_document, name='upload_bill_document'),
    path('bill/document/delete/<int:id>/', delete_bill_document, name='delete_bill_document'),
    path("class-bills/", class_bill_list_view, name="class_bill_list"),
    path('class/bill-item/<int:id>/edit/', edit_class_bill_item_view, name="edit_class_bill_item"),
    path('delete_class_bill_item/<int:id>/', delete_class_bill_item_view, name='delete_class_bill_item'),
    path('bulk-create-bills/', bulk_create_class_bills, name='bulk_create_class_bills'),
    path('fees-status/', student_fees_status_view, name='fees_status'),
    path('fees/carry-forward/', carry_forward_balances_view, name='carry_forward_balances'),
    path('fees-ledger/', payment_ledger_view, name='payment_ledger'),
    path('fees-help/', fees_help_view, name='fees_help'),
    path('student-ledger-modal/<int:student_id>/', student_ledger_modal_view, name='student_ledger_modal'),
    path('student-fees-history/<int:student_id>/', student_fees_history_view, name='student_fees_history'),
    path('student-fees-receipt/<int:student_id>/', student_fees_receipt_pdf_view, name='student_fees_receipt'),
    path('payment-receipt/<int:payment_id>/', student_payment_receipt_view, name='student_payment_receipt'),
    path('reconcile-overpayments/<int:student_id>/', reconcile_student_overpayments, name='reconcile_overpayments'),

    
    #Finance
    path('income_sources/', manage_income_sources, name="income_source_page"),
    path('add_income_source/', add_income_source, name="add_income_source_page"),
    path('edit_income_source/<int:id>/', edit_income_sources, name="edit_income_source"),
    path('delete_income_source/<int:id>/', delete_income_source, name="delete_income_source"),
    
    #Expenses
    path('expenses/', manage_expenses, name="expense_page"),
    path('add_expense/', add_expense, name="add_expense_page"),
    path('edit_expense/<int:id>/', edit_expenses, name="edit_expense"),
    path('delete_expense/<int:id>/', delete_expense, name="delete_expense"),
    
    #Expenditures
    path('expenditures/', manage_expenditures, name="expenditure_page"),
    path('add_expenditure/', add_expenditure, name="add_expenditure_page"),
    path('edit_expenditure/<int:id>/', edit_expenditures, name="edit_expenditure"),
    path('expenditure/edit/<int:id>/', edit_expenditures, name='edit_expenditure'),
    path('delete_expenditure/<int:id>/', delete_expenditure, name="delete_expenditure"),
    # Expenditure approval
    path('expenditure/<int:id>/approve/', approve_expenditure, name="approve_expenditure"),
    path('expenditure/<int:id>/revoke-approval/', revoke_expenditure_approval, name="revoke_expenditure_approval"),
     
    #Expenditure Items
    path('items/<int:id>/', manage_expenditure_items, name="items_page"),
    path('add_expenditure_item/', add_expenditure_item, name="add_expenditure_item_page"),
    path('edit_expenditure_item/<int:id>/', edit_expenditure_items, name="edit_expenditure_item"),
    path('delete_expenditure_item/<int:id>/', delete_expenditure_item, name="delete_expenditure_item"),
    
    #Vendors
    path('vendors/', manage_vendors, name="vendor_page"),
    path('add_vendor/', add_vendor, name="add_vendor_page"),
    path('edit_vendor/<int:id>/', edit_vendors, name="edit_vendor"),
    path('delete_vendor/<int:id>/', delete_vendor, name="delete_vendor"),
    # Vendor Payments Report
    path('vendor-report/', vendor_payments_report, name="vendor_report"),
    
    #Budgets
    path('budgets/', manage_budgets, name="budget_page"),
    path('add_budget/', add_budget, name="add_budget_page"),
    path('edit_budget/<int:id>/', edit_budgets, name="edit_budget"),
    path('delete_budget/<int:id>/', delete_budget, name="delete_budget"),
    
    #Budget Items
    path('budget_items/<int:id>/', manage_budget_items, name="budget_item_page"),
    path('add_budget_item/', add_budget_item, name="add_budget_item_page"),
    path('edit_budget_item/<int:id>/', edit_budget_items, name="edit_budget_item"),
    path('delete_budget_item/<int:id>/', delete_budget_item, name="delete_budget_item"),

   #Financial Summary Report
    path('financial-summary/', financial_summary_report, name="financial_summary_report"),
   # Income Statement
    path('income-statement/', income_statement_report, name="income_statement"),
   # Cash Flow Report
    path('cash-flow/', cash_flow_report, name="cash_flow"),

   # Financial Dashboard and Reconciliation
    path('finance/dashboard/', financial_dashboard_view, name="financial_dashboard"),
    path('finance/bank-reconciliation/', bank_reconciliation_view, name="bank_reconciliation"),
    path('finance/bank-reconciliation/upload/', upload_bank_statement_view, name="upload_bank_statement"),
    path('finance/reconcile/<int:transaction_id>/', reconcile_transaction_view, name="reconcile_transaction"),
    path('finance/send-reminders/', send_payment_reminders_view, name="send_payment_reminders"),
    path('finance/approvals/', approval_workflow_view, name="approval_workflow"),
    path('finance/export/', export_financial_data_view, name="export_financial_data"),

    # Communications
    path('communications/announcements/', announcement_list, name="announcement_list"),
    path('communications/announcements/new/', announcement_create, name="announcement_create"),
    path('communications/announcements/<int:pk>/edit/', announcement_edit, name="announcement_edit"),
    path('communications/announcements/<int:pk>/delete/', announcement_delete, name="announcement_delete"),
    path('communications/events/', event_list, name="event_list"),
    path('communications/events/new/', event_create, name="event_create"),
    path('communications/events/<int:pk>/edit/', event_edit, name="event_edit"),
    path('communications/events/<int:pk>/delete/', event_delete, name="event_delete"),

    # Messaging
    path('communications/messages/', message_inbox, name="message_inbox"),
    path('communications/messages/new/', message_new, name="message_new"),
    path('communications/messages/<int:pk>/', message_thread, name="message_thread"),

    # Exam Timetable
    path('results/exam-timetable/', primary(exam_timetable_view), name="exam_timetable"),
 
    #Results
    path('add_grading_system/', primary(grading_system_view), name='add_grading_system_page'),
    path('edit_grading_system/<int:id>/', primary(edit_grading_system_view), name="edit_grading_system"),
    path('delete_grading_system/<int:id>/', primary(delete_grading_system_view), name="delete_grading_system"),
    path('bulk_result_entry/', primary(bulk_result_entry_view), name='bulk_result_entry'),
    path('bulk_result_entry/<int:assessment_id>/', primary(bulk_result_entry_view), name='bulk_result_entry'),
    path('add_results/', primary(add_results_view), name="add_results_page"),
    path('add_results/<int:assessment_id>/', primary(add_results_view), name='add_results'),
    path('edit_results/<int:assessment_id>/<int:student_id>/edit_results/', primary(edit_results_view), name='edit_results_view'),
    path('classes_assessments/', primary(class_assessment_list_view), name='class_assessment_list'),
    path('classes_assessments/<int:class_id>/assessments/', primary(list_assessments_view), name='list_assessments'),
    path('assessments/<int:assessment_id>/verification/', primary(verification_queue_view), name='verification_queue'),
    path('assessments/<int:assessment_id>/verification/report/', primary(verification_report_view), name='verification_report'),
    path('assessments/<int:assessment_id>/verified-sheet/', primary(assessment_verified_sheet_view), name='assessment_verified_sheet'),
    path("class-student-filter/", primary(class_result_filter_view), name="class_stream_filter"),
    path("student/<int:student_id>/performance/", primary(student_performance_view), name="student_performance"),
    # Mini Report per Assessment Type
    path('student/<int:student_id>/report/<int:assessment_type_id>/', primary(student_assessment_type_report), name='student_mini_report'),
    # Consolidated Term Report
    path('student/<int:student_id>/term-report/', primary(student_term_report), name='student_term_report'),
    path('class/bulk-reports/', primary(class_bulk_reports), name='class_bulk_reports'),
    # Bulk mini-reports per assessment type for a whole class
    path('class/bulk-reports/assessment-type/', primary(class_assessment_type_bulk_reports), name='class_assessment_type_bulk_reports'),
    path('class-performance-summary/', primary(class_performance_summary), name='class_performance_summary'),
    path('results/overview/', primary(results_overview_dashboard), name='school_results_dashboard'),
    path('results/verification-overview/', primary(verification_overview_view), name='verification_overview'),
    path('assessment-sheet/', primary(assessment_sheet_view), name='assessment_sheet'),
    path('class/combined-assessments/', primary(class_assessment_combined_view), name='class_assessment_combined'),
    path('class/combined-assessments/print/', primary(class_assessment_combined_print), name='class_assessment_combined_print'),
    

    #Assessment
    path('assessments/', primary(assessment_list_view), name='assessment_list'),
    path('assessments/create/', primary(add_assessment_view), name='assessment_create'),
    path('edit_assessments/<int:id>/', primary(edit_assessment), name='edit_assessment_page'),
    path('delete_assessments/<int:id>/', primary(delete_assessment_view), name='delete_assessment'),
    path('assesment_type/', primary(assesment_type_view), name="assesment_type_page"),
    path('edit_assesment_type/<int:id>/', primary(edit_assesment_type), name="edit_assesment_type"),
    path('delete_assesment_type/<int:id>/', primary(delete_assesment_view), name="delete_assesment_type"),

    #Authentication
    path('', user_login, name='login'),
    path('dashboard/', dashboard, name='dashboard'),
    path('switch-role/', switch_role, name='switch_role'),
    path('logout/', logout_view, name='logout'),
    path('users/', UserListView.as_view(), name='user_list'),
    path('users/<int:pk>/',UserDetailView.as_view(), name='user_detail'),
    path('create-account/',create_account_view, name='create_account'),
    path('users/delete/<int:id>/',delete_user_view, name='delete_user'),
    path('password_change/',password_change_view, name='password_change'),

    #Reset Password
    path('password_reset/', auth_views.PasswordResetView.as_view(), name='password_reset'),
    path('password_reset/done/', auth_views.PasswordResetDoneView.as_view(), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(), name='password_reset_complete'),

    #Timetables
    path('timetable-center/', timetable_center, name='timetable_center'),
    path('timetable/school/', school_timetable_overview, name='school_timetable'),
    path('timetable/class/', class_timetable_overview, name='class_timetable'),
    path('timetable/classrooms/', classrooms_overview, name='classrooms'),
    path('teacher/timetable/', teacher_timetable_view, name='teacher_timetable'),

    #Attendance
    path('attendance/', attendance_dashboard, name='attendance_dashboard'),
    path('attendance/take/', take_attendance, name='take_attendance'),
    path('attendance/history/', attendance_history, name='attendance_history'),
    path('attendance/analysis/', attendance_analysis, name='attendance_analysis'),
    path('attendance/admin-control/', attendance_admin_control, name='attendance_admin_control'),
    path('attendance/export/', export_attendance_csv, name='export_attendance_csv'),
    path('attendance/unlock/<int:session_id>/', unlock_attendance, name='unlock_attendance'),
    path('attendance/student-report/', student_attendance_report, name='student_attendance_report'),
    path('attendance/class-report/', class_attendance_report, name='class_attendance_report'),
]



    


    

    
