"""URL configuration for Shizuha Wiki API"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
from .cited_answer_view import CitedAnswerView
from .atlas_collaboration import AtlasCollaborationView

router = DefaultRouter()
router.register(r'spaces', views.SpaceViewSet, basename='space')
router.register(r'pages', views.PageViewSet, basename='page')
router.register(r'labels', views.LabelViewSet, basename='label')
router.register(r'templates', views.TemplateViewSet, basename='template')
router.register(r'attachments', views.AttachmentViewSet, basename='attachment')
router.register(r'comments', views.CommentViewSet, basename='comment')
router.register(r'search', views.SearchViewSet, basename='search')

urlpatterns = [
    path('answer/', CitedAnswerView.as_view(), name='cited-answer'),
    path('atlas/collaboration/<uuid:page_id>/', AtlasCollaborationView.as_view(), name='atlas-collaboration'),
    path('publication-snapshots/', views.PublicationSnapshotCreateView.as_view(), name='publication-snapshot-create'),
    path('preferences/', views.UserPreferenceView.as_view(), name='user-preferences'),
    path('', include(router.urls)),
]
