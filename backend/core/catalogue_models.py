from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class CatalogueImport(models.Model):
    filename = models.CharField(max_length=255)
    sha256 = models.CharField(max_length=64, unique=True)
    imported_at = models.DateTimeField(auto_now_add=True)
    imported_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='catalogue_imports')
    product_count = models.PositiveIntegerField()
    warranty_count = models.PositiveIntegerField()
    is_active = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict)

    class Meta:
        ordering = ['-imported_at', '-id']
        constraints = [models.UniqueConstraint(fields=['is_active'], condition=models.Q(is_active=True), name='catalogue_one_active_import')]


class CatalogueState(models.Model):
    """Stable row locked before every import/activation, including first import."""
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(id=1), name='catalogue_singleton_state')]


class CatalogueProduct(models.Model):
    snapshot = models.ForeignKey(CatalogueImport, on_delete=models.CASCADE, related_name='products')
    source_row = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    source_sheet = models.CharField(max_length=100, blank=True)
    range_name = models.TextField(blank=True)
    product_name = models.TextField()
    product_code = models.CharField(max_length=64, blank=True)
    structure = models.CharField(max_length=32)
    launch_year = models.TextField(blank=True)
    manufacturing_part_number = models.TextField(blank=True)
    catalogue_number = models.TextField(blank=True)
    market_status = models.TextField(blank=True)
    replacement_product = models.TextField(blank=True)
    replacement_part_number = models.TextField(blank=True)
    version = models.TextField(blank=True)
    return_text = models.TextField(blank=True)
    raw_data = models.JSONField(default=dict)

    class Meta:
        ordering = ['source_row', 'id']
        constraints = [
            models.UniqueConstraint(fields=['snapshot', 'source_row'], name='catalogue_product_source_row_unique'),
            models.CheckConstraint(condition=models.Q(source_row__gte=1), name='catalogue_product_row_positive'),
        ]
        indexes = [models.Index(fields=['snapshot', 'structure', 'product_code'], name='catalogue_product_lookup')]


class CatalogueWarranty(models.Model):
    snapshot = models.ForeignKey(CatalogueImport, on_delete=models.CASCADE, related_name='warranties')
    source_sheet = models.CharField(max_length=100, blank=True)
    source_row = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    source_column = models.CharField(max_length=8)
    scope = models.CharField(max_length=32)
    category = models.TextField(blank=True)
    product_name = models.TextField(blank=True)
    brand_group = models.TextField(blank=True)
    duration_text = models.TextField(blank=True)
    duration_months = models.PositiveIntegerField(null=True, blank=True)
    conditions = models.TextField(blank=True)
    raw_data = models.JSONField(default=dict)

    class Meta:
        ordering = ['source_row', 'source_column', 'id']
        constraints = [
            models.UniqueConstraint(fields=['snapshot', 'source_row', 'source_column'], name='catalogue_warranty_source_unique'),
            models.CheckConstraint(condition=models.Q(source_row__gte=1), name='catalogue_warranty_row_positive'),
        ]
