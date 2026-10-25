from django.db import IntegrityError
from django.db.models import Q
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.exceptions import APIException, NotFound, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response

from .catalogue_models import CatalogueImport, CatalogueProduct, CatalogueWarranty
from .catalogue_serializers import CatalogueImportSerializer, CatalogueProductSerializer, CatalogueWarrantySerializer
from .catalogue_service import MAX_CATALOGUE_BYTES, CatalogueValidationError, collision_counts, import_catalogue
from .permissions import InternalPermission, ManagerPermission


EMPTY_COUNTS = {'products': 0, 'warranties': 0, 'year_mappings': 0, 'na_codes': 0, 'duplicate_code_groups': 0}


class CatalogueUploadTooLarge(APIException):
    status_code = 413
    default_detail = 'Le fichier catalogue dépasse la limite de 8 Mio.'


def active_import():
    return CatalogueImport.objects.select_related('imported_by').filter(is_active=True).first()


def selected_import(request):
    value = request.query_params.get('import_id')
    if value is None:
        return active_import()
    if len(value) > 19 or not value.isascii() or not value.isdigit() or not 1 <= int(value) <= 9223372036854775807:
        raise ValidationError({'import_id': 'Identifiant de version invalide.'})
    snapshot = CatalogueImport.objects.filter(pk=int(value)).first()
    if snapshot is None:
        raise NotFound('Cette version du catalogue n’existe pas.')
    return snapshot


class CataloguePagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 100
    def get_paginated_response(self, data):
        return Response({'import_id': getattr(self, 'import_id', None), 'count': self.page.paginator.count, 'next': self.get_next_link(), 'previous': self.get_previous_link(), 'page': self.page.number, 'page_size': self.get_page_size(self.request), 'results': data})


@api_view(['GET'])
@permission_classes([InternalPermission])
def catalogue_status(request):
    snapshot = active_import()
    if not snapshot:
        return Response({'available': False, 'active_import': None, 'counts': EMPTY_COUNTS, 'structures': [], 'year_tables': [], 'warnings': []})
    return Response({
        'available': True,
        'active_import': CatalogueImportSerializer(snapshot).data,
        'counts': {**EMPTY_COUNTS, **snapshot.metadata.get('counts', {}), 'products': snapshot.product_count, 'warranties': snapshot.warranty_count},
        'structures': list(snapshot.products.order_by('structure').values_list('structure', flat=True).distinct()),
        'year_tables': snapshot.metadata.get('year_tables', []),
        'warnings': snapshot.metadata.get('warnings', []),
    })


@api_view(['GET'])
@permission_classes([InternalPermission])
def catalogue_products(request):
    snapshot = selected_import(request)
    all_products = CatalogueProduct.objects.filter(snapshot=snapshot) if snapshot else CatalogueProduct.objects.none()
    products = all_products
    query = request.query_params.get('q', '').strip()
    structure = request.query_params.get('structure', '').strip()
    if len(query) > 200:
        raise ValidationError({'q': 'La recherche est limitée à 200 caractères.'})
    if len(structure) > 32:
        raise ValidationError({'structure': 'Le profil est limité à 32 caractères.'})
    if query:
        products = products.filter(Q(range_name__icontains=query) | Q(product_name__icontains=query) | Q(product_code__icontains=query) | Q(manufacturing_part_number__icontains=query) | Q(catalogue_number__icontains=query) | Q(replacement_product__icontains=query) | Q(replacement_part_number__icontains=query))
    if structure:
        products = products.filter(structure__iexact=structure)
    paginator = CataloguePagination()
    paginator.import_id = snapshot.pk if snapshot else None
    page = paginator.paginate_queryset(products, request)
    collisions = collision_counts(all_products.values_list('structure', 'product_code'))
    return paginator.get_paginated_response(CatalogueProductSerializer(page, many=True, context={'collision_counts': collisions}).data)


@api_view(['GET'])
@permission_classes([InternalPermission])
def catalogue_warranties(request):
    snapshot = selected_import(request)
    warranties = CatalogueWarranty.objects.filter(snapshot=snapshot) if snapshot else CatalogueWarranty.objects.none()
    return Response(CatalogueWarrantySerializer(warranties, many=True).data)


@api_view(['POST'])
@permission_classes([ManagerPermission])
@parser_classes([MultiPartParser, FormParser])
def catalogue_import(request):
    files = request.FILES.getlist('file')
    if len(files) != 1:
        raise ValidationError({'file': 'Joignez exactement un fichier catalogue XLS dans le champ file.'})
    uploaded = files[0]
    if uploaded.size > MAX_CATALOGUE_BYTES:
        raise CatalogueUploadTooLarge()
    data = bytearray()
    for chunk in uploaded.chunks():
        if len(data) + len(chunk) > MAX_CATALOGUE_BYTES:
            raise CatalogueUploadTooLarge()
        data.extend(chunk)
    try:
        result = import_catalogue(bytes(data), uploaded.name, actor=request.user)
    except CatalogueValidationError as exc:
        raise ValidationError({'file': str(exc)}) from exc
    except IntegrityError as exc:
        raise ValidationError({'file': 'Le catalogue contient des lignes incompatibles ou une identité source dupliquée. L’import actif a été conservé.'}) from exc
    snapshot = result.snapshot
    return Response({
        'created': result.created, 'activated': result.activated, 'already_imported': not result.created,
        'import': CatalogueImportSerializer(snapshot).data,
        'counts': {**EMPTY_COUNTS, **snapshot.metadata.get('counts', {}), 'products': snapshot.product_count, 'warranties': snapshot.warranty_count},
        'year_tables': snapshot.metadata.get('year_tables', []),
        'warnings': snapshot.metadata.get('warnings', []),
    }, status=status.HTTP_201_CREATED if result.created else status.HTTP_200_OK)
