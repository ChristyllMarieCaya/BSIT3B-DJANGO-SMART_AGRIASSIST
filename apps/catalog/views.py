"""Read-only crop catalog views.

Farmers can browse, search, and filter the agricultural catalog. Catalog
entries are reference data and cannot be created, edited, or deleted through
the application.
"""

from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, render

from .models import CropCatalog


def catalog_list(request):
    """Render the searchable, filterable crop catalog list."""
    query = request.GET.get('q', '').strip()
    category = request.GET.get('category', '').strip()

    crops = CropCatalog.objects.filter(is_active=True)

    if query:
        crops = crops.filter(
            Q(common_name__icontains=query)
            | Q(scientific_name__icontains=query)
            | Q(description__icontains=query)
        )

    if category:
        crops = crops.filter(category=category)

    crops = crops.order_by('category', 'common_name')

    paginator = Paginator(crops, 12)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    categories = CropCatalog.Category.choices

    return render(request, 'catalog/catalog_list.html', {
        'crops': page_obj,
        'query': query,
        'category': category,
        'categories': categories,
    })


def catalog_detail(request, pk):
    """Render a single crop's detail page (read-only)."""
    crop = get_object_or_404(CropCatalog, pk=pk, is_active=True)
    return render(request, 'catalog/catalog_detail.html', {
        'crop': crop,
    })
