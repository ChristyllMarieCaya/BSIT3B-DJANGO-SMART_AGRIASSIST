from django.urls import path

from . import views

app_name = 'catalog'

urlpatterns = [
    path('', views.catalog_list, name='catalog_list'),
    path('<int:pk>/', views.catalog_detail, name='catalog_detail'),
]
