from django.urls import path

from . import api, views

app_name = 'kentucky'

A = 'api/ka/'
urlpatterns = [
    # ---------------------------------------------------------------- UI
    path('ka/', views.page, name='home'),
    path('ka/datasets/<int:pk>/', views.page, {'name': 'dataset'}, name='dataset-page'),
    path('ka/graph/<int:pk>/', views.page, {'name': 'graph'}, name='graph-page'),
    path('ka/experiments/<int:pk>/', views.page, {'name': 'experiment'}, name='experiment-page'),
    path('ka/<str:name>/', views.page, name='page'),
    path('ka/files/sheet/<int:pk>/image.png', views.sheet_image, name='sheet-image'),
    path('ka/files/sheet/<int:pk>/tile/<int:level>/<int:col>/<int:row>.png', views.sheet_tile, name='sheet-tile'),
    path('ka/files/signed/<str:token>', views.signed_file, name='signed-file'),
    # ---------------------------------------------------------------- API
    path(A + 'dashboard/', api.dashboard),
    path(A + 'datasets/', api.datasets),
    path(A + 'datasets/<int:pk>/', api.dataset_detail),
    path(A + 'datasets/<int:pk>/taxonomy/', api.taxonomy),
    path(A + 'datasets/<int:pk>/documents/', api.documents),
    path(A + 'datasets/<int:pk>/sheets/', api.sheets),
    path(A + 'datasets/<int:pk>/sync/', api.dataset_sync),
    path(A + 'datasets/<int:pk>/objects/', api.dataset_objects),
    path(A + 'datasets/<int:pk>/objects/review/', api.objects_review),
    path(A + 'datasets/<int:pk>/readiness/', api.dataset_readiness),
    path(A + 'datasets/<int:pk>/versions/', api.dataset_versions),
    path(A + 'datasets/<int:pk>/proposals/', api.proposals),
    path(A + 'datasets/<int:pk>/agent/<str:action>/', api.agent_action),
    path(A + 'versions/<int:pk>/export/', api.version_export),
    path(A + 'sheets/<int:pk>/', api.sheet_detail),
    path(A + 'sheets/<int:pk>/primitives/', api.sheet_primitives),
    path(A + 'sheets/<int:pk>/graph/', api.sheet_graph),
    path(A + 'sheets/<int:pk>/graph/review/', api.sheet_graph_review),
    path(A + 'sheets/<int:pk>/graph/versions/', api.sheet_graph_versions),
    path(A + 'sheets/<int:pk>/graph/rebuild/', api.sheet_graph_rebuild),
    path(A + 'sheets/<int:pk>/proposals/apply/', api.sheet_apply_proposals),
    path(A + 'proposals/<int:pk>/review/', api.proposal_review),
    path(A + 'catalog/', api.model_catalog),
    path(A + 'training/recommend/', api.training_recommend),
    path(A + 'jobs/', api.jobs),
    path(A + 'jobs/compare/', api.jobs_compare),
    path(A + 'jobs/<int:pk>/', api.job_detail),
    path(A + 'jobs/<int:pk>/authorize/', api.job_authorize),
    path(A + 'jobs/<int:pk>/cancel/', api.job_cancel),
    path(A + 'jobs/<int:pk>/diagnose/', api.job_diagnose),
    path(A + 'models/', api.models_list),
    path(A + 'model-versions/<int:pk>/', api.model_version_detail),
    path(A + 'model-versions/<int:pk>/archive/', api.model_version_archive),
    path(A + 'model-versions/<int:pk>/download/', api.model_version_download),
    path(A + 'model-versions/<int:pk>/predict/', api.model_version_predict),
    path(A + 'deployments/', api.deployments),
    path(A + 'deployments/<int:pk>/<str:action>/', api.deployment_action),
    path(A + 'v1/deployments/<str:slug>/predict', api.predict),
    path(A + 'api-keys/', api.api_keys),
    path(A + 'api-keys/<int:pk>/<str:action>/', api.api_key_action),
    path(A + 'billing/', api.billing),
    path(A + 'org/', api.org_info),
    path(A + 'audit/', api.audit_log),
]

urlpatterns += [
    path(A + 'sheets/<int:pk>/markup/', api.sheet_markup),
    path('ka/engine/<path:path>', views.engine_asset, name='engine-asset'),
    path('ka/markup/<int:pk>/', views.page, {'name': 'markup'}, name='markup-page'),
    path('ka/projects/<int:pk>/', views.page, {'name': 'dataset'}, name='project-page'),
]
